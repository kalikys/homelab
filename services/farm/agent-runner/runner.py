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
from urllib.parse import parse_qsl, unquote, urlsplit
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from panel import summarise_panel

ROLES = {"discovery", "diligence", "game-discovery", "game-diligence", "reflector", "judges", "preregistration", "landing", "traffic", "builder", "analyst"}
# Roles that run on the Anthropic API key (separate prepaid budget) instead of the Claude subscription.
# n8n sends use_api=false once the month's API budget is spent; then the subscription is used.
API_ROLES = {"discovery", "game-discovery", "diligence", "game-diligence", "reflector", "judges"}
DILIGENCE_ROLES = {"diligence": ("briefs", "brief.json"), "game-diligence": ("concepts", "concept.json")}
DISCOVERY_DIRS = {"discovery": "briefs", "game-discovery": "concepts"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
TOOLS = {
    "discovery": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "diligence": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Task,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "game-discovery": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "game-diligence": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch,Task,Bash(curl:*),Bash(jq:*),Bash(python3:*)",
    "reflector": "Read,Write,Edit,Glob,Grep",
    "judges": "Read,Write,Glob,Grep,Task,Bash(curl:*),Bash(jq:*)",
    "preregistration": "Read,Write,Edit,Glob,Grep",
    "landing": "Read,Write,Edit,Glob,Grep,WebFetch",
    "traffic": "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch",
    "builder": "Read,Write,Edit,Glob,Grep,Bash",
    "analyst": "Read,Write,Edit,Glob,Grep",
}
TOKEN = os.environ["RUNNER_TOKEN"]
# Agents run as uid 1000 while this server runs as root, so an agent cannot read the server's /proc environ.
AGENT_UID = AGENT_GID = 1000
AGENT_HOME = "/home/agent"
MODEL_PROXY = os.environ.get("MODEL_PROXY", "http://172.30.0.5")
HAS_SUBSCRIPTION = os.environ.get("HAS_SUBSCRIPTION") == "1"
HAS_API_KEY = os.environ.get("HAS_API_KEY") == "1"
PLACEHOLDER_OAUTH = "sk-ant-oat01-farm-model-proxy-placeholder"
PLACEHOLDER_KEY = "sk-ant-api03-farm-model-proxy-placeholder"


def _drop_to_agent():
    if os.getuid() == 0:
        os.setgroups([])
        os.setgid(AGENT_GID)
        os.setuid(AGENT_UID)


def _give_to_agent(path):
    """Files the server prepared (inputs, memory) must stay writable for the agent."""
    if os.getuid() == 0:
        subprocess.run(["chown", "-R", f"{AGENT_UID}:{AGENT_GID}", str(path)], check=False)
LOCK = threading.Lock()
EXP_RE = re.compile(r"^(EXP|GAME)-\d{3}$")


def run(role, body):
    exp = body.get("exp_id", "")
    if not EXP_RE.match(exp):
        return 400, {"ok": False, "error": "exp_id must look like EXP-001 or GAME-001"}
    skill = Path(f"/skills/{role}/SKILL.md")
    if not skill.exists():
        return 404, {"ok": False, "error": f"no skill for role {role}"}
    work = Path("/work") / exp
    if role == "judges":
        # Independent panel in its own folder: a copy of the memo without the author's verdict, so judges do not anchor on it.
        slug = body.get("slug", "")
        dd = work / "dd" / slug
        if not SLUG_RE.match(slug) or not (dd / "memo.json").exists():
            return 404, {"ok": False, "error": "judges need an existing dd/<slug>/memo.json"}
        if body.get("skip"):
            return 200, {"ok": True, "role": role, "exp_id": exp, "slug": slug, "skipped": True, "panel": None}
        work = dd / "panel"
        work.mkdir(exist_ok=True)
        memo = json.loads((dd / "memo.json").read_text())
        memo.pop("verdict", None)
        (work / "memo.json").write_text(json.dumps(memo, ensure_ascii=False, indent=2))
        for name in ("verification.json", "brief.json", "concept.json"):
            if (dd / name).exists():
                v = json.loads((dd / name).read_text())
                if isinstance(v, dict):
                    v.pop("verdict", None)
                (work / name).write_text(json.dumps(v, ensure_ascii=False, indent=2))
        (work / "panel.json").unlink(missing_ok=True)
    elif role in DILIGENCE_ROLES:
        src_dir, in_name = DILIGENCE_ROLES[role]
        slug = body.get("slug", "")
        if not SLUG_RE.match(slug):
            return 400, {"ok": False, "error": "diligence needs a slug"}
        work = work / "dd" / slug
        if work.exists() and (work / "memo.json").exists():
            work.rename(work.parent / f"{slug}-previous-{int(time.time())}")
        work.mkdir(parents=True, exist_ok=True)
        brief = body.get("brief")
        src = Path("/work") / exp / src_dir / f"{slug}.json"
        if not brief and src.exists():
            brief = json.loads(src.read_text())
        if not brief:
            return 404, {"ok": False, "error": f"no brief {slug} for {exp}"}
        (work / in_name).write_text(json.dumps(brief, ensure_ascii=False, indent=2))
    (work / "runs").mkdir(parents=True, exist_ok=True)
    if body.get("memory") is not None:
        # Farm memory from the database: past ideas with outcomes and distilled lessons (see the skills).
        (work / "memory.json").write_text(json.dumps(body["memory"], ensure_ascii=False, indent=2))
    max_turns = min(int(body.get("max_turns", 60)), 150)
    prompt = body.get("prompt") or f"You are the farm '{role}' agent for {exp}, stage {body.get('stage')}. Follow your skill exactly. Input: {json.dumps(body.get('input', {}), ensure_ascii=False)}"
    if role in DISCOVERY_DIRS and (work / DISCOVERY_DIRS[role]).exists():
        # Never let a new run be judged on the previous run's output.
        (work / DISCOVERY_DIRS[role]).rename(work / "runs" / f"{int(time.time())}-{DISCOVERY_DIRS[role]}-previous")
    before = {p for p in work.rglob("*") if p.is_file()}
    started = time.time()
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", str(max_turns),
           "--allowedTools", TOOLS[role], "--append-system-prompt", skill.read_text()]
    # The agent holds no secret: model calls go through model-proxy, which swaps the placeholder for the real credential.
    keep = {"PATH", "LANG", "HTTP_PROXY", "HTTPS_PROXY", "DISABLE_AUTOUPDATER"}
    env = {k: v for k, v in os.environ.items() if k in keep or k.startswith(("OTEL_", "CLAUDE_CODE_ENABLE_TELEMETRY", "CLAUDE_CODE_ENHANCED"))}
    env.update(HOME=AGENT_HOME, USER="agent", NO_PROXY="phoenix,172.30.0.4,172.30.0.5")
    billing = "subscription"
    if role in API_ROLES and HAS_API_KEY and body.get("use_api", True):
        # Prepaid API budget when a key is configured; otherwise the subscription is used.
        billing = "api"
        env.update(ANTHROPIC_BASE_URL=f"{MODEL_PROXY}:8081", ANTHROPIC_API_KEY=PLACEHOLDER_KEY)
        budget = min(float(body.get("budget_usd", 4)), float(os.environ.get("MAX_BUDGET_PER_RUN_USD", "8")))
        cmd += ["--max-budget-usd", f"{budget:.2f}"]
    else:
        env.update(ANTHROPIC_BASE_URL=f"{MODEL_PROXY}:8080", CLAUDE_CODE_OAUTH_TOKEN=PLACEHOLDER_OAUTH)
    if body.get("model"):
        cmd += ["--model", body["model"]]
    _give_to_agent(work)
    try:
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=int(body.get("timeout_s", 3000)),
                              preexec_fn=_drop_to_agent)
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
    if role == "judges":
        try:
            raw = json.loads((work / "panel.json").read_text())
            result["panel"] = summarise_panel(raw)
        except (OSError, ValueError):
            raw, result["panel"] = {}, None
        lazy = [j.get("persona") for j in raw.get("judges", []) if not j.get("spot_checks")]
        if not result["panel"] or lazy:
            result["ok"] = False
            result["panel"] = None
            result["error"] = "panel.json missing, fewer than 3 judges, or judges without a spot check: " + ", ".join(map(str, lazy))
        else:
            (work.parent / "panel.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))
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


def _quote_found(url, quote_raw):
    """True if the quote is on the page: visible text, raw HTML (attributes such as title="4.86 average rating"),
    or JSON compared without whitespace (API responses quoted compactly)."""
    q = _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", quote_raw or "")))
    if len(q) < 15:
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (farm-validator)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(3_000_000).decode("utf-8", "ignore")
    # Search and suggest APIs echo the request back; text that only comes from our own query proves nothing.
    # A quote contained in our own URL (query or path) is an echo, whatever the page returns.
    parts = urlsplit(url)
    echoed = [_norm(v) for _, v in parse_qsl(parts.query)] + [_norm(unquote(parts.path).replace("+", " "))]
    if any(q in e for e in echoed if e):
        return False
    variants = [raw]
    try:
        obj = json.loads(raw)
        variants += [json.dumps(obj, ensure_ascii=False), json.dumps(obj, ensure_ascii=False, separators=(",", ":"))]
    except ValueError:
        pass
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    variants.append(re.sub(r"(?s)<[^>]+>", " ", text))
    q_tight = re.sub(r"\s+", "", q)
    for v in variants:
        nv = _norm(html.unescape(v))
        if q in nv or q_tight in re.sub(r"\s+", "", nv):
            return True
    return False


def _norm(t):
    t = t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


REQUIRED = ["slug", "title", "segment", "problem", "evidence", "competitors", "offer", "price_hypothesis",
            "channel", "cpc_estimate_usd", "cpc_basis", "mvp_scope", "red_team", "checklist"]
CHANNELS = {"google_ads", "meta_ads", "chrome_web_store", "shopify", "wordpress", "apify", "directory", "seo_tool"}


# Upper bounds for discovery-stage assumptions: optimistic inputs must not buy a pass.
ECON_CAPS = {"landing_conversion": 0.15, "trial_to_paid": 0.6, "lifetime_months": 24, "gross_margin": 0.95}
MIN_LTV_CAC = float(os.environ.get("MIN_LTV_CAC", "1.5"))
MIN_LTV_USD = float(os.environ.get("MIN_LTV_USD", "150"))
PAID_CHANNELS = {"google_ads", "meta_ads"}
MONEY_RE = re.compile(r"\$\s?(\d+(?:\.\d+)?)")


def _verified_number_quote(url, quote):
    """A quote with a number that the farm finds verbatim on the page; returns (ok, why)."""
    if not str(url).startswith("https://") or not re.search(r"\d", str(quote or "")):
        return False, "needs an https URL and a quote containing the number"
    try:
        return (True, "") if _quote_found(url, quote) else (False, "quote not found on the page")
    except Exception as ex:
        return False, f"fetch failed: {ex}"[:160]


def _recent_page(url, years_back=1):
    """True if the page mentions this year or last year: benchmarks from 2019 must not drive 2026 decisions."""
    now = time.gmtime().tm_year
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (farm-validator)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(3_000_000).decode("utf-8", "ignore")
    return any(str(y) in raw for y in range(now - years_back, now + 1))


def _brief_economics(e, cpc, channel=None):
    """Cheap unit-economics screen before due diligence: CAC from the CPC estimate and sourced conversion rates, LTV from price."""
    fails = []
    if not isinstance(e, dict):
        return {"failures": ["no economics block (price, billing, conversions, lifetime) — unit economics cannot be screened"]}
    try:
        price, cpc = float(e.get("price_usd")), float(cpc)
        conv, t2p = float(e.get("landing_conversion")), float(e.get("trial_to_paid"))
        life, margin = float(e.get("lifetime_months")), float(e.get("gross_margin", 0.85))
    except (TypeError, ValueError):
        return {"failures": ["economics: price_usd, landing_conversion, trial_to_paid, lifetime_months must be numbers"]}
    billing = {"monthly": "month", "yearly": "year", "annual": "year", "annually": "year", "one-time": "one_time",
               "onetime": "one_time", "lifetime": "one_time"}.get(str(e.get("billing")).lower(), e.get("billing"))
    if billing not in ("month", "year", "one_time"):
        fails.append(f"economics: billing {billing!r} must be month, year or one_time")
    for k, cap in ECON_CAPS.items():
        v = {"landing_conversion": conv, "trial_to_paid": t2p, "lifetime_months": life, "gross_margin": margin}[k]
        if not 0 < v <= cap:
            fails.append(f"economics: {k} {v} outside (0, {cap}]")
    if not str(e.get("conversion_source_url", "")).startswith("https://"):
        fails.append("economics: conversion_source_url missing")
    if fails or price <= 0 or cpc <= 0:
        return {"failures": fails or ["economics: price and CPC must be positive"]}
    monthly = {"month": price, "year": price / 12}.get(billing)
    ltv = price * margin if billing == "one_time" else monthly * margin * life
    cac = cpc / conv / t2p
    ratio = ltv / cac
    out = {"cac_usd": round(cac, 1), "ltv_usd": round(ltv, 1), "ltv_to_cac": round(ratio, 2), "channel_kind": "paid" if channel in PAID_CHANNELS else "organic"}
    # Calibration on 30 real products: low one-time prices fade after launch.
    if ltv < MIN_LTV_USD:
        fails.append(f"unit economics: LTV ${ltv:.0f} < ${MIN_LTV_USD:.0f} — price too low to build a business")
    if channel in PAID_CHANNELS:
        # Discovery used to assume $0.8 clicks that due diligence then found at $4-6: the CPC must come from a quoted benchmark.
        ok, why = _verified_number_quote(e.get("cpc_source_url"), e.get("cpc_quote"))
        if not ok:
            fails.append(f"paid channel: CPC benchmark quote not verified ({why})")
        elif not _recent_page(e.get("cpc_source_url")):
            fails.append("paid channel: CPC benchmark page has no mention of this or last year — find a current benchmark")
        else:
            nums = [float(x) for x in MONEY_RE.findall(e.get("cpc_quote", ""))]
            if nums and cpc < 0.8 * min(nums):
                fails.append(f"paid channel: CPC ${cpc} is below the quoted benchmark ${min(nums)}")
        if ratio < MIN_LTV_CAC:
            fails.append(f"unit economics: LTV ${ltv:.0f} / CAC ${cac:.0f} = {ratio:.2f} < {MIN_LTV_CAC} — paid traffic does not pay back")
    else:
        # Organic channels (marketplace search, intent SEO): prove buyers already search there, with a number.
        ok, why = _verified_number_quote(e.get("organic_evidence_url"), e.get("organic_evidence_quote"))
        if not ok:
            fails.append(f"organic channel: no verified demand number for the channel ({why})")
    out["failures"] = fails
    return out


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
            if b.get("channel") in PAID_CHANNELS and float(b.get("cpc_estimate_usd", 99)) > 1.0:
                fails.append(f"CPC estimate {b.get('cpc_estimate_usd')} > $1 for a paid channel")
        except (TypeError, ValueError):
            fails.append("CPC estimate is not a number")
        if b.get("channel") not in CHANNELS:
            fails.append(f"channel {b.get('channel')!r} is not allowed")
        econ = _brief_economics(b.get("economics"), b.get("cpc_estimate_usd"), b.get("channel"))
        fails += econ.pop("failures")
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
                ok = _quote_found(url, e.get("quote", ""))
                checked.append({"url": url, "ok": ok, "why": "" if ok else "quote not found on page"})
            except Exception as ex:
                checked.append({"url": url, "ok": False, "why": f"fetch failed: {ex}"[:160]})
        verified = sum(c["ok"] for c in checked)
        if verified < 3:
            fails.append(f"only {verified} quotes verified on their pages, need 3")
        reports.append({"file": f.name, "slug": b.get("slug"), "title": b.get("title"), "channel": b.get("channel"),
                        "cpc": b.get("cpc_estimate_usd"), "price": b.get("price_hypothesis"), "economics": econ,
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
    verified = 0
    for x in ev[:20]:
        url, quote = x.get("url", ""), _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", x.get("quote", ""))))
        ok = False
        if url.startswith(("http://", "https://")) and len(quote) >= 15:
            try:
                ok = _quote_found(url, x.get("quote", ""))
            except Exception:
                ok = False
        x["verified"] = ok
        verified += ok
    chk("quotes_verified", verified >= max(6, int(0.6 * min(len(ev), 20))), f"Цитаты найдены дословно на страницах: {verified} из {min(len(ev), 20)}")
    # Counts use verified evidence only, one item per page: relabelling or repeating a page must not add up.
    seen, good = set(), []
    for x in ev:
        if x.get("verified") and x.get("url") not in seen:
            seen.add(x.get("url")); good.append(x)
    types = {x.get("source_type") for x in good}
    domains = {re.sub(r"^www\.", "", re.sub(r"^https?://", "", x.get("url", "")).split("/")[0]) for x in good}
    chk("evidence_count", len(good) >= 8, f"Подтверждённых доказательств с разных страниц: {len(good)} (нужно ≥ 8)")
    chk("source_types", len(types) >= 4, f"Типов источников (подтверждённых): {len(types)} (нужно ≥ 4): {', '.join(sorted(t for t in types if t))}")
    chk("domains", len(domains) >= 5, f"Разных доменов (подтверждённых): {len(domains)} (нужно ≥ 5)")
    chk("money_signals", sum(1 for x in good if x.get("signals_money")) >= 3, "Не меньше 3 подтверждённых доказательств, что за решение уже платят")
    mk = m.get("market") or {}
    vals = [(mk.get(k) or {}).get("value_usd") for k in ("tam", "sam", "som_2y")]
    try:
        chk("market_order", float(vals[0]) >= float(vals[1]) >= float(vals[2]) > 0, "TAM ≥ SAM ≥ SOM > 0")
    except (TypeError, ValueError):
        chk("market_order", False, "TAM, SAM, SOM должны быть числами")
    inputs = [i for k in ("tam", "sam", "som_2y") for i in ((mk.get(k) or {}).get("inputs") or [])]
    sourced = sum(1 for i in inputs if str(i.get("source_url", "")).startswith("http"))
    chk("market_sourced", inputs and sourced * 2 >= len(inputs), f"Входов расчёта рынка с источником: {sourced} из {len(inputs)} (нужно не меньше половины)")
    comps = m.get("competitors") or []
    chk("competitors", len(comps) >= 4 and all(c.get("price_source_url") for c in comps), f"Конкурентов с ценой из источника: {sum(1 for c in comps if c.get('price_source_url'))} (нужно ≥ 4)")
    ue = m.get("unit_economics") or {}
    try:
        cac = float(ue["cpc_usd"]) / float(ue["landing_conversion"]) / float(ue["trial_to_paid"])
        ltv = float(ue["price_usd_month"]) * float(ue["gross_margin"]) / float(ue["monthly_churn"])
        ok = _close(ue.get("cac_usd"), cac) and _close(ue.get("ltv_usd"), ltv)
        # Same caps as the discovery screen: a 1% churn or a 30% landing conversion would buy any LTV/CAC.
        caps = [f"{k} {float(ue[k])} вне ({lo}, {hi}]" for k, lo, hi in (("monthly_churn", 0.02, 1), ("landing_conversion", 0, 0.15), ("trial_to_paid", 0, 0.6), ("gross_margin", 0, 0.95))
                if not lo <= float(ue[k]) <= hi]
        if caps:
            chk("ue_caps", False, "Допущения юнит-экономики вне допустимого: " + "; ".join(caps))
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


def _verify_quotes(items, limit=14):
    verified = 0
    for x in items[:limit]:
        url, quote = x.get("url", ""), _norm(html.unescape(re.sub(r"(?s)<[^>]+>", " ", x.get("quote", ""))))
        ok = False
        if url.startswith(("http://", "https://")) and len(quote) >= 15:
            try:
                ok = _quote_found(url, x.get("quote", ""))
            except Exception:
                ok = False
        x["verified"] = ok
        verified += ok
    return verified


def validate_game_discovery(exp):
    d = Path("/work") / exp / "concepts"
    reports = []
    for f in sorted(d.glob("*.json")):
        fails = []
        try:
            b = json.loads(f.read_text())
        except Exception as ex:
            reports.append({"file": f.name, "passed": False, "failures": [f"not valid JSON: {ex}"]}); continue
        missing = [k for k in ("slug", "title", "core_mechanic", "twist", "references", "evidence", "platforms", "checklist") if not b.get(k)]
        if missing:
            fails.append("missing fields: " + ", ".join(missing))
        cl = b.get("checklist") or {}
        if len(cl) < 5 or any(v is not True for v in cl.values()):
            fails.append("checklist not all true")
        items = (b.get("references") or []) + (b.get("evidence") or [])
        kinds = {x.get("source_type") for x in items if x.get("source_type")}
        if len(kinds) < 2:
            fails.append(f"only {len(kinds)} source type(s), need 2+")
        verified = _verify_quotes(items, 10)
        if verified < 3:
            fails.append(f"only {verified} quotes verified on their pages, need 3")
        if not any(x.get("verified") and re.search(r"\d", x.get("quote", "")) for x in b.get("references") or []):
            fails.append("no verified reference quote with a popularity number")
        reports.append({"file": f.name, "slug": b.get("slug"), "title": b.get("title"), "channel": ", ".join(b.get("platforms") or []),
                        "cpc": None, "price": f"{b.get('build_days_estimate', '?')} дн. разработки", "passed": not fails, "failures": fails})
    return {"ok": True, "exp_id": exp, "briefs": reports, "passed_count": sum(r["passed"] for r in reports)}


def validate_game_diligence(exp, slug):
    d = Path("/work") / exp / "dd" / slug
    checks = []

    def chk(rule, ok, detail):
        checks.append({"rule": rule, "passed": bool(ok), "detail": detail})

    try:
        m = json.loads((d / "memo.json").read_text())
    except Exception as ex:
        return {"ok": True, "exp_id": exp, "slug": slug, "passed": False, "checks": [{"rule": "memo", "passed": False, "detail": f"memo.json не читается: {ex}"}]}
    ev = m.get("evidence") or []
    kinds = {x.get("source_type") for x in ev}
    domains = {re.sub(r"^www\.", "", re.sub(r"^https?://", "", x.get("url", "")).split("/")[0]) for x in ev if x.get("url")}
    chk("evidence_count", len(ev) >= 6, f"Доказательств: {len(ev)} (нужно ≥ 6)")
    chk("source_types", len(kinds) >= 2, f"Типов источников: {len(kinds)} (нужно ≥ 2)")
    chk("domains", len(domains) >= 3, f"Разных доменов: {len(domains)} (нужно ≥ 3)")
    verified = _verify_quotes(ev)
    chk("quotes_verified", verified >= max(4, int(0.6 * min(len(ev), 14))), f"Цитаты найдены дословно на страницах: {verified} из {min(len(ev), 14)}")
    comps = m.get("competitors") or []
    chk("competitors", len(comps) >= 4 and all(c.get("source_url") for c in comps), f"Похожих игр с источником: {sum(1 for c in comps if c.get('source_url'))} (нужно ≥ 4)")
    mo = m.get("monetization") or {}
    note = "Не хватает данных для пересчёта дохода"
    try:
        rpm, share = float(mo["rpm_usd"]), float(mo["dev_share"])
        sc = mo.get("scenarios") or []
        calc = [float(x["daily_plays"]) * 30 * rpm / 1000 * share for x in sc]
        ok = len(sc) >= 3 and calc == sorted(calc) and all(_close(x.get("monthly_revenue_usd"), c) for x, c in zip(sc, calc))
        note = "Доход по формуле: " + ", ".join(f"{x.get('name')} ${c:,.0f}/мес (в отчёте ${float(x.get('monthly_revenue_usd', 0)):,.0f})" for x, c in zip(sc, calc))
    except (KeyError, TypeError, ValueError):
        ok = False
    chk("monetization", ok, note)
    chk("monetization_sourced", bool(mo.get("rpm_source_url") and mo.get("dev_share_source_url")), "RPM и доля портала взяты из источников")
    pf = m.get("portal_fit") or []
    chk("portal_fit", len(pf) >= 2 and all(x.get("source_url") for x in pf), f"Правил портала с источником: {sum(1 for x in pf if x.get('source_url'))} (нужно ≥ 2)")
    chk("risks", len(m.get("risks") or []) >= 4, f"Рисков разобрано: {len(m.get('risks') or [])} (нужно ≥ 4)")
    rec = (m.get("verdict") or {}).get("recommendation")
    chk("verdict", rec in ("invest", "maybe", "pass"), f"Вердикт: {rec}")
    m["kind"] = "game"
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
    proc = subprocess.run(args, capture_output=True, text=True, timeout=300, preexec_fn=_drop_to_agent)
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
        f = re.match(r"^/files/((?:EXP|GAME)-\d{3})/([A-Za-z0-9._/-]+)$", self.path)
        if f:
            if self.headers.get("X-Runner-Token") != TOKEN:
                return self._send(401, {"ok": False, "error": "bad token"})
            base = (Path("/work") / f.group(1)).resolve()
            target = (base / f.group(2)).resolve()
            if base not in target.parents or not target.is_file():
                return self._send(404, {"ok": False, "error": "no such file"})
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", {".pdf": "application/pdf", ".json": "application/json"}.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/healthz":
            claude = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
            return self._send(200, {"ok": True, "busy": LOCK.locked(), "claude": claude,
                                    "auth": HAS_SUBSCRIPTION, "api_key": HAS_API_KEY, "uid": os.getuid()})
        self._send(404, {"ok": False})

    def do_POST(self):
        if self.headers.get("X-Runner-Token") != TOKEN:
            return self._send(401, {"ok": False, "error": "bad token"})
        v = re.match(r"^/validate/discovery/((?:EXP|GAME)-\d{3})$", self.path)
        if v:
            return self._send(200, validate_discovery(v.group(1)))
        v = re.match(r"^/validate/diligence/((?:EXP|GAME)-\d{3})/([a-z0-9][a-z0-9-]{1,60})$", self.path)
        if v:
            return self._send(200, validate_diligence(v.group(1), v.group(2)))
        v = re.match(r"^/validate/game-discovery/((?:EXP|GAME)-\d{3})$", self.path)
        if v:
            return self._send(200, validate_game_discovery(v.group(1)))
        v = re.match(r"^/validate/game-diligence/((?:EXP|GAME)-\d{3})/([a-z0-9][a-z0-9-]{1,60})$", self.path)
        if v:
            return self._send(200, validate_game_diligence(v.group(1), v.group(2)))
        v = re.match(r"^/render/(?:game-)?diligence/((?:EXP|GAME)-\d{3})/([a-z0-9][a-z0-9-]{1,60})$", self.path)
        if v:
            return self._send(*render_diligence(v.group(1), v.group(2)))
        m = re.match(r"^/run/([a-z-]+)$", self.path)
        if not m or m.group(1) not in ROLES:
            return self._send(404, {"ok": False, "error": "unknown role"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        # Jobs are serialised: a second request waits for the first instead of being refused.
        if not LOCK.acquire(timeout=float(body.get("queue_timeout_s", 10800))):
            return self._send(409, {"ok": False, "error": "agent queue timeout"})
        try:
            code, obj = run(m.group(1), body)
        finally:
            LOCK.release()
        self._send(code, obj)

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
