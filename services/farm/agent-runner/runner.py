#!/usr/bin/env python3
"""Farm agent runner: n8n calls POST /run/<role>; we run Claude Code headless with that role's skill.

One job at a time. Auth: X-Runner-Token header. The agent has no farm secrets and no database access;
it writes files under /work/<exp_id>/ and returns its result, cost and turns as JSON.
"""
import html
import json
import os
import re
import urllib.request
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROLES = {"discovery", "preregistration", "landing", "traffic", "builder", "analyst"}
TOOLS = {
    "discovery": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "preregistration": "Read,Write,Edit,Glob,Grep",
    "landing": "Read,Write,Edit,Glob,Grep,WebFetch",
    "traffic": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch",
    "builder": "Read,Write,Edit,Glob,Grep,Bash",
    "analyst": "Read,Write,Edit,Glob,Grep",
}
TOKEN = os.environ["RUNNER_TOKEN"]
LOCK = threading.Lock()
EXP_RE = re.compile(r"^EXP-\d{3}$")


def run(role, body):
    exp = body.get("exp_id", "")
    if not EXP_RE.match(exp):
        return 400, {"ok": False, "error": "exp_id must look like EXP-001"}
    skill = Path(f"/skills/{role}/SKILL.md")
    if not skill.exists():
        return 404, {"ok": False, "error": f"no skill for role {role}"}
    work = Path("/work") / exp
    (work / "runs").mkdir(parents=True, exist_ok=True)
    max_turns = min(int(body.get("max_turns", 60)), 150)
    prompt = body.get("prompt") or f"You are the farm '{role}' agent for {exp}, stage {body.get('stage')}. Follow your skill exactly. Input: {json.dumps(body.get('input', {}), ensure_ascii=False)}"
    if role == "discovery" and (work / "briefs").exists():
        # Never let a new run be judged on the previous run's briefs.
        (work / "briefs").rename(work / "runs" / f"{int(time.time())}-briefs-previous")
    before = {p for p in work.rglob("*") if p.is_file()}
    started = time.time()
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", str(max_turns),
           "--allowedTools", TOOLS[role], "--append-system-prompt", skill.read_text()]
    try:
        proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=int(body.get("timeout_s", 3000)))
    except subprocess.TimeoutExpired:
        return 504, {"ok": False, "error": "agent timed out"}
    out = {}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        out = {"raw": proc.stdout[-4000:]}
    after = {p for p in work.rglob("*") if p.is_file()}
    result = {
        "ok": proc.returncode == 0 and not out.get("is_error", False),
        "role": role, "exp_id": exp,
        "result": out.get("result"),
        "cost_usd": out.get("total_cost_usd"),
        "turns": out.get("num_turns"),
        "session_id": out.get("session_id"),
        "duration_s": round(time.time() - started, 1),
        "new_files": sorted(str(p.relative_to(work)) for p in after - before),
        "stderr_tail": proc.stderr[-2000:],
    }
    (work / "runs" / f"{int(started)}-{role}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return 200, result


def _page_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (farm-validator)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(3_000_000).decode("utf-8", "ignore")
    try:
        raw = json.dumps(json.loads(raw), ensure_ascii=False)
    except ValueError:
        pass
    raw = raw.replace("\\n", " ").replace('\\"', '"').replace("\\/", "/")
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    return _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw)))


def _norm(t):
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


REQUIRED = ["slug", "title", "segment", "problem", "evidence", "competitors", "offer", "price_hypothesis",
            "channel", "cpc_estimate_usd", "cpc_basis", "mvp_scope", "red_team", "checklist"]
CHANNELS = {"google_ads", "meta_ads", "chrome_web_store", "shopify", "wordpress", "apify", "directory", "seo_tool"}


def validate_discovery(exp):
    """Deterministic checks of the briefs the discovery agent wrote. No LLM involved."""
    briefs_dir = Path("/work") / exp / "briefs"
    reports = []
    for f in sorted(briefs_dir.glob("*.json")):
        fails = []
        try:
            b = json.loads(f.read_text())
        except Exception as e:
            reports.append({"file": f.name, "passed": False, "failures": [f"not valid JSON: {e}"]}); continue
        missing = [k for k in REQUIRED if not b.get(k)]
        if missing:
            fails.append("missing fields: " + ", ".join(missing))
        cl = b.get("checklist") or {}
        bad = [k for k, v in cl.items() if v is not True]
        if bad or len(cl) < 5:
            fails.append("checklist not all true: " + ", ".join(bad or ["fewer than 5 items"]))
        try:
            if float(b.get("cpc_estimate_usd", 99)) > 1.0:
                fails.append(f"CPC estimate {b.get('cpc_estimate_usd')} > $1")
        except (TypeError, ValueError):
            fails.append("CPC estimate is not a number")
        if b.get("channel") not in CHANNELS:
            fails.append(f"channel {b.get('channel')!r} is not allowed")
        ev = b.get("evidence") or []
        if len(ev) < 3:
            fails.append(f"only {len(ev)} evidence items, need 3")
        if not any(e.get("signals_money") for e in ev):
            fails.append("no evidence item signals money")
        checked = []
        for e in ev[:8]:
            url, quote = e.get("url", ""), _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", e.get("quote", ""))))
            if not url.startswith(("http://", "https://")) or len(quote) < 15:
                checked.append({"url": url, "ok": False, "why": "bad url or quote too short"}); continue
            try:
                ok = quote in _page_text(url)
                checked.append({"url": url, "ok": ok, "why": "" if ok else "quote not found on page"})
            except Exception as ex:
                checked.append({"url": url, "ok": False, "why": f"fetch failed: {ex}"[:160]})
        verified = sum(c["ok"] for c in checked)
        if verified < 3:
            fails.append(f"only {verified} quotes verified on their pages, need 3")
        reports.append({"file": f.name, "slug": b.get("slug"), "title": b.get("title"), "channel": b.get("channel"),
                        "cpc": b.get("cpc_estimate_usd"), "price": b.get("price_hypothesis"),
                        "passed": not fails, "failures": fails, "evidence_checked": checked})
    return {"ok": True, "exp_id": exp, "briefs": reports, "passed_count": sum(r["passed"] for r in reports)}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/healthz":
            claude = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
            return self._send(200, {"ok": True, "busy": LOCK.locked(), "claude": claude,
                                    "auth": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))})
        self._send(404, {"ok": False})

    def do_POST(self):
        if self.headers.get("X-Runner-Token") != TOKEN:
            return self._send(401, {"ok": False, "error": "bad token"})
        v = re.match(r"^/validate/discovery/(EXP-\d{3})$", self.path)
        if v:
            return self._send(200, validate_discovery(v.group(1)))
        m = re.match(r"^/run/([a-z]+)$", self.path)
        if not m or m.group(1) not in ROLES:
            return self._send(404, {"ok": False, "error": "unknown role"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if not LOCK.acquire(blocking=False):
            return self._send(409, {"ok": False, "error": "another agent job is running"})
        try:
            code, obj = run(m.group(1), body)
        finally:
            LOCK.release()
        self._send(code, obj)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
