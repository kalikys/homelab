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

ROLES = {"discovery", "diligence", "preregistration", "landing", "traffic", "builder", "analyst"}
# Roles that run on the Anthropic API key (separate prepaid budget) instead of the Claude subscription.
API_ROLES = {"diligence"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
TOOLS = {
    "discovery": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "diligence": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Task,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
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
    if role == "diligence":
        slug = body.get("slug", "")
        if not SLUG_RE.match(slug):
            return 400, {"ok": False, "error": "diligence needs a slug"}
        work = work / "dd" / slug
        if work.exists() and (work / "memo.json").exists():
            work.rename(work.parent / f"{slug}-previous-{int(time.time())}")
        work.mkdir(parents=True, exist_ok=True)
        brief = body.get("brief")
        src = Path("/work") / exp / "briefs" / f"{slug}.json"
        if not brief and src.exists():
            brief = json.loads(src.read_text())
        if not brief:
            return 404, {"ok": False, "error": f"no brief {slug} for {exp}"}
        (work / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2))
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
    env = dict(os.environ)
    billing = "subscription"
    if role in API_ROLES and env.get("ANTHROPIC_API_KEY"):
        # Prepaid API budget when a key is configured; otherwise the subscription is used.
        billing = "api"
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        budget = min(float(body.get("budget_usd", 4)), float(env.get("MAX_BUDGET_PER_RUN_USD", "8")))
        cmd += ["--max-budget-usd", f"{budget:.2f}"]
    else:
        env.pop("ANTHROPIC_API_KEY", None)
    if body.get("model"):
        cmd += ["--model", body["model"]]
    try:
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=int(body.get("timeout_s", 3000)))
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
        "role": role, "exp_id": exp, "slug": body.get("slug"), "billing": billing,
        "result": out.get("result"),
        "cost_usd": out.get("total_cost_usd"),
        "turns": out.get("num_turns"),
        "session_id": out.get("session_id"),
        "duration_s": round(time.time() - started, 1),
        "new_files": sorted(str(p.relative_to(work)) for p in after - before)[:50],
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
        kinds = {e.get("source_type") for e in ev if e.get("source_type")}
        if len(kinds) < 2:
            fails.append(f"evidence from only {len(kinds)} source type(s), need 2+ (not only app reviews)")
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


def _close(a, b, tol=0.2):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return b != 0 and abs(a - b) / abs(b) <= tol


def validate_diligence(exp, slug):
    """Deterministic checks of memo.json; writes verification.json used by the deck renderer."""
    d = Path("/work") / exp / "dd" / slug
    checks = []

    def chk(rule, ok, detail):
        checks.append({"rule": rule, "passed": bool(ok), "detail": detail})

    try:
        m = json.loads((d / "memo.json").read_text())
    except Exception as ex:
        return {"ok": True, "exp_id": exp, "slug": slug, "passed": False, "checks": [{"rule": "memo", "passed": False, "detail": f"memo.json не читается: {ex}"}]}
    ev = m.get("evidence") or []
    types = {x.get("source_type") for x in ev}
    domains = {re.sub(r"^www\.", "", re.sub(r"^https?://", "", x.get("url", "")).split("/")[0]) for x in ev if x.get("url")}
    chk("evidence_count", len(ev) >= 8, f"Доказательств: {len(ev)} (нужно ≥ 8)")
    chk("source_types", len(types) >= 4, f"Типов источников: {len(types)} (нужно ≥ 4): {', '.join(sorted(t for t in types if t))}")
    chk("domains", len(domains) >= 5, f"Разных доменов: {len(domains)} (нужно ≥ 5)")
    chk("money_signals", sum(1 for x in ev if x.get("signals_money")) >= 3, "Не меньше 3 доказательств, что за решение уже платят")
    verified = 0
    for x in ev[:14]:
        url, quote = x.get("url", ""), _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", x.get("quote", ""))))
        ok = False
        if url.startswith(("http://", "https://")) and len(quote) >= 15:
            try:
                ok = quote in _page_text(url)
            except Exception:
                ok = False
        x["verified"] = ok
        verified += ok
    chk("quotes_verified", verified >= max(6, int(0.6 * min(len(ev), 14))), f"Цитаты найдены дословно на страницах: {verified} из {min(len(ev), 14)}")
    mk = m.get("market") or {}
    vals = [(mk.get(k) or {}).get("value_usd") for k in ("tam", "sam", "som_2y")]
    try:
        chk("market_order", float(vals[0]) >= float(vals[1]) >= float(vals[2]) > 0, "TAM ≥ SAM ≥ SOM > 0")
    except (TypeError, ValueError):
        chk("market_order", False, "TAM, SAM, SOM должны быть числами")
    inputs = [i for k in ("tam", "sam", "som_2y") for i in ((mk.get(k) or {}).get("inputs") or [])]
    chk("market_sourced", inputs and all(i.get("source_url") or "estimate" in str(i.get("name", "")).lower() for i in inputs), "У каждого входа расчёта рынка есть источник или пометка «estimate»")
    comps = m.get("competitors") or []
    chk("competitors", len(comps) >= 4 and all(c.get("price_source_url") for c in comps), f"Конкурентов с ценой из источника: {sum(1 for c in comps if c.get('price_source_url'))} (нужно ≥ 4)")
    ue = m.get("unit_economics") or {}
    try:
        cac = float(ue["cpc_usd"]) / float(ue["landing_conversion"]) / float(ue["trial_to_paid"])
        ltv = float(ue["price_usd_month"]) * float(ue["gross_margin"]) / float(ue["monthly_churn"])
        ok = _close(ue.get("cac_usd"), cac) and _close(ue.get("ltv_usd"), ltv)
        note = f"CAC по формуле ${cac:,.0f} (в отчёте ${float(ue.get('cac_usd', 0)):,.0f}), LTV ${ltv:,.0f} (в отчёте ${float(ue.get('ltv_usd', 0)):,.0f})"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        ok, note = False, "Не хватает входных данных для пересчёта CAC и LTV"
    chk("unit_economics", ok, note)
    chk("ue_sourced", all(ue.get(k) for k in ("cpc_source_url", "conversion_source_url")), "CPC и конверсия взяты из источников")
    chk("risks", len(m.get("risks") or []) >= 4, f"Рисков разобрано: {len(m.get('risks') or [])} (нужно ≥ 4)")
    rec = (m.get("verdict") or {}).get("recommendation")
    chk("verdict", rec in ("invest", "maybe", "pass"), f"Вердикт: {rec}")
    (d / "memo.json").write_text(json.dumps(m, ensure_ascii=False, indent=2))
    result = {"ok": True, "exp_id": exp, "slug": slug, "passed": all(c["passed"] for c in checks), "checks": checks,
              "unit_economics_note": note, "title": m.get("title"), "verdict": m.get("verdict"),
              "evidence_count": len(ev), "verified_quotes": verified}
    (d / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def render_diligence(exp, slug):
    d = Path("/work") / exp / "dd" / slug
    if not (d / "memo.json").exists():
        return 404, {"ok": False, "error": "no memo.json"}
    args = ["python3", "/app/render_deck.py", str(d)]
    if (d / "verification.json").exists():
        args.append(str(d / "verification.json"))
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return 500, {"ok": False, "error": proc.stderr[-1500:]}
    pdf = d / "deck.pdf"
    return 200, {"ok": True, "exp_id": exp, "slug": slug, "path": f"dd/{slug}/deck.pdf", "bytes": pdf.stat().st_size}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        f = re.match(r"^/files/(EXP-\d{3})/([A-Za-z0-9._/-]+)$", self.path)
        if f:
            if self.headers.get("X-Runner-Token") != TOKEN:
                return self._send(401, {"ok": False, "error": "bad token"})
            base = (Path("/work") / f.group(1)).resolve()
            target = (base / f.group(2)).resolve()
            if base not in target.parents or not target.is_file():
                return self._send(404, {"ok": False, "error": "no such file"})
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf" if target.suffix == ".pdf" else "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/healthz":
            claude = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
            return self._send(200, {"ok": True, "busy": LOCK.locked(), "claude": claude,
                                    "auth": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
                                    "api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))})
        self._send(404, {"ok": False})

    def do_POST(self):
        if self.headers.get("X-Runner-Token") != TOKEN:
            return self._send(401, {"ok": False, "error": "bad token"})
        v = re.match(r"^/validate/discovery/(EXP-\d{3})$", self.path)
        if v:
            return self._send(200, validate_discovery(v.group(1)))
        v = re.match(r"^/validate/diligence/(EXP-\d{3})/([a-z0-9][a-z0-9-]{1,60})$", self.path)
        if v:
            return self._send(200, validate_diligence(v.group(1), v.group(2)))
        v = re.match(r"^/render/diligence/(EXP-\d{3})/([a-z0-9][a-z0-9-]{1,60})$", self.path)
        if v:
            return self._send(*render_diligence(v.group(1), v.group(2)))
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
