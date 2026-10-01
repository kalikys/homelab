#!/usr/bin/env python3
"""Creates or updates the startup farm workflows in n8n through the public API (v2, after the n8n audit).

- Workflows are matched by name; every update is published (activated) except 00 Controller.
- Drift guard: deployed versionIds live in deployed.lock.json; if a workflow was edited in the UI since the
  last build, it is skipped with a warning (re-run with --force to overwrite).
- Rendered JSON goes to workflows/*.json next to this script, so changes show up in git diff.
Reads N8N_URL, N8N_API_KEY, PG_CRED_ID, TG_CRED_ID, RUNNER_CRED_ID, OWNER_CHAT_ID from /home/kalikys/prj/farm/.env.
Run: python3 services/farm/n8n/build.py [--force]
"""
import json
import sys
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = "/home/kalikys/prj/farm/.env"
env = dict(line.strip().split("=", 1) for line in open(ENV_FILE) if "=" in line and not line.startswith("#"))
URL = env["N8N_URL"].rstrip("/") + "/api/v1"
KEY = env["N8N_API_KEY"]
CHAT = env["OWNER_CHAT_ID"]
PG = {"postgres": {"id": env["PG_CRED_ID"], "name": "Farm DB (farm)"}}
TG = {"telegramApi": {"id": env["TG_CRED_ID"], "name": "Telegram (Hermes bot, send only)"}}
RUNNER = {"httpHeaderAuth": {"id": env["RUNNER_CRED_ID"], "name": "Agent runner token"}}
BASE = "https://n8n.home.kalik8s.ru/webhook"
RUNNER_URL = "http://172.30.0.10:8080"
FORCE = "--force" in sys.argv
LOCK_FILE = HERE / "deployed.lock.json"
OUT_DIR = HERE / "workflows"


def api(method, path, body=None):
    req = urllib.request.Request(
        URL + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-N8N-API-KEY": KEY, "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


# ---------- node helpers ----------
def node(name, ntype, version, params, pos, creds=None, disabled=False, extra=None):
    n = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name + ntype)), "name": name, "type": ntype,
         "typeVersion": version, "position": pos, "parameters": params}
    if creds:
        n["credentials"] = creds
    if disabled:
        n["disabled"] = True
    if extra:
        n.update(extra)
    return n


def sticky(text, pos, w=420, h=240, color=5):
    return node("About", "n8n-nodes-base.stickyNote", 1, {"content": text, "width": w, "height": h, "color": color}, pos)


def sql(name, query, params_expr, pos, extra=None):
    p = {"operation": "executeQuery", "query": query, "options": {}}
    if params_expr:
        p["options"]["queryReplacement"] = params_expr
    return node(name, "n8n-nodes-base.postgres", 2.5, p, pos, PG, extra=extra)


def code(name, js, pos, disabled=False):
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": js}, pos, disabled=disabled)


def telegram(name, text_expr, pos, chat=None):
    """Notifications never break a stage: 3 retries, then continue."""
    return node(name, "n8n-nodes-base.telegram", 1.2,
                {"chatId": chat or CHAT, "text": text_expr,
                 "additionalFields": {"parse_mode": "HTML", "appendAttribution": False, "disable_web_page_preview": True}},
                pos, TG, extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000, "onError": "continueRegularOutput"})


def sub_trigger(pos):
    return node("Called by another workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1,
                {"inputSource": "passthrough"}, pos)


def call(name, wf_id_expr, pos, wait=True, extra=None):
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2,
                {"source": "database", "workflowId": {"__rl": True, "value": wf_id_expr, "mode": "id"},
                 "mode": "each", "options": {"waitForSubWorkflow": wait}}, pos, extra=extra)


def if_true(name, left_expr, pos):
    return node(name, "n8n-nodes-base.if", 2.2, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "leftValue": left_expr,
                            "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
            "combinator": "and"},
        "options": {}}, pos)


def schedule(name, cron, pos):
    return node(name, "n8n-nodes-base.scheduleTrigger", 1.2,
                {"rule": {"interval": [{"field": "cronExpression", "expression": cron}]}}, pos)


def webhook(name, path, method, pos):
    return node(name, "n8n-nodes-base.webhook", 2,
                {"httpMethod": method, "path": path, "responseMode": "responseNode", "options": {}}, pos,
                extra={"webhookId": str(uuid.uuid5(uuid.NAMESPACE_URL, path + method))})


def respond(name, body_expr, pos, html=False):
    ctype = "text/html; charset=utf-8" if html else "application/json; charset=utf-8"
    return node(name, "n8n-nodes-base.respondToWebhook", 1.1,
                {"respondWith": "text", "responseBody": body_expr,
                 "options": {"responseHeaders": {"entries": [{"name": "Content-Type", "value": ctype}]}}}, pos)


def link(conns, a, b, out=0):
    conns.setdefault(a, {"main": []})
    while len(conns[a]["main"]) <= out:
        conns[a]["main"].append([])
    conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})


ESC_JS = "const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\n"
BASE_SETTINGS = {"executionOrder": "v1", "saveManualExecutions": True, "saveDataSuccessExecution": "all",
                 "saveDataErrorExecution": "all", "timezone": "Asia/Tbilisi", "executionTimeout": 300}

existing = {w["name"]: w for w in api("GET", "/workflows?limit=250")["data"]}
lock = json.loads(LOCK_FILE.read_text()) if LOCK_FILE.exists() else {}
OUT_DIR.mkdir(exist_ok=True)
skipped = []


def upsert(name, nodes, conns, error_wf=None, publish=True, **settings_over):
    settings = dict(BASE_SETTINGS, **settings_over)
    if error_wf:
        settings["errorWorkflow"] = error_wf
    body = {"name": name, "nodes": nodes, "connections": conns, "settings": settings}
    (OUT_DIR / (name.replace(" · ", "_").replace(" ", "_") + ".json")).write_text(json.dumps(body, ensure_ascii=False, indent=1))
    if name in existing:
        wid = existing[name]["id"]
        current = api("GET", f"/workflows/{wid}")
        if lock.get(wid) and current.get("versionId") != lock[wid] and not FORCE:
            print(f"SKIP {wid}  {name}: edited in the UI since the last build (use --force to overwrite)")
            skipped.append(name)
            return wid
        api("PUT", f"/workflows/{wid}", body)
    else:
        wid = api("POST", "/workflows", body)["id"]
        existing[name] = {"id": wid}
    if publish:
        api("POST", f"/workflows/{wid}/activate")
    else:
        try:
            api("POST", f"/workflows/{wid}/deactivate")
        except Exception:
            pass
    w = api("GET", f"/workflows/{wid}")
    lock[wid] = w.get("versionId")
    LOCK_FILE.write_text(json.dumps(lock, indent=1, sort_keys=True))  # saved per workflow, so a crash mid-build is not mistaken for UI edits
    state = "published" if w.get("active") else "draft"
    if publish and w.get("activeVersionId") and w.get("activeVersionId") != w.get("versionId"):
        state = "PUBLISH MISMATCH"
    print(f"{wid}  {state:9}  {name}")
    return wid


# ---------- 98 Error handler: Telegram and the journal in parallel ----------
c = {}
ERR_TEXT = ("={{ ((e) => '🔴 <b>Ферма: ошибка</b>\\nWorkflow: ' + e($json.workflow.name) + '\\nУзел: ' + e($json.execution.lastNodeExecuted)"
            " + '\\n' + e(($json.execution.error || {}).message))(v => String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').slice(0, 900)) }}")
n = [
    sticky("## 98 · Обработчик ошибок\nЛюбой упавший workflow фермы: алерт в Telegram **и** запись в журнал — параллельно, чтобы алерт ушёл даже при упавшей базе.", [-80, -260], 420, 160),
    node("When a farm workflow fails", "n8n-nodes-base.errorTrigger", 1, {}, [0, 0]),
    telegram("Alert owner", ERR_TEXT, [260, -100]),
    sql("Log the error", "INSERT INTO events (kind, actor, message, data) SELECT 'workflow_error', 'n8n', $1, $2::jsonb",
        "={{ ['Workflow failed: ' + $json.workflow.name, JSON.stringify({execution: $json.execution.id, node: $json.execution.lastNodeExecuted, error: ($json.execution.error || {}).message})] }}",
        [260, 100], extra={"onError": "continueRegularOutput"}),
]
link(c, "When a farm workflow fails", "Alert owner")
link(c, "When a farm workflow fails", "Log the error")
ERR = upsert("98 · Error handler", n, c)

# ---------- 97 Log event ----------
c = {}
n = [
    sticky("## 97 · Журнал событий\nВызывается этапами. Пишет событие в `events` (только INSERT); при notify = true шлёт сообщение (текст экранируется).\nВход: exp_id, stage, kind, actor, message, notify.", [-80, -280], 440, 190),
    sub_trigger([0, 0]),
    sql("Insert event",
        "INSERT INTO events (exp_id, stage, kind, actor, message) SELECT j->>'exp_id', (j->>'stage')::int, j->>'kind', coalesce(j->>'actor','n8n'), j->>'message' FROM (SELECT $1::jsonb AS j) t RETURNING id, exp_id, stage, kind, message",
        "={{ [JSON.stringify($json)] }}", [240, 0]),
    if_true("Notify owner?", "={{ $('Called by another workflow').item.json.notify === true }}", [480, 0]),
    telegram("Send to Telegram",
             "={{ ($json.exp_id ? '<b>' + $json.exp_id + '</b> · этап ' + $json.stage + '\\n' : '') + String($json.message).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }}",
             [720, -80]),
]
link(c, "Called by another workflow", "Insert event")
link(c, "Insert event", "Notify owner?")
link(c, "Notify owner?", "Send to Telegram", 0)
LOG = upsert("97 · Log event", n, c, ERR)

# ---------- 90 Guardrail preflight: checks + atomic lock ----------
PREFLIGHT_SQL = """WITH s AS (
  SELECT max(value) FILTER (WHERE key = 'kill_switch') AS ks,
         max(value) FILTER (WHERE key = 'wip_limit')::int AS wip,
         max(value) FILTER (WHERE key = 'budget_month_usd')::numeric AS cap
  FROM settings),
e AS (SELECT * FROM experiments WHERE id = $1),
a AS (SELECT count(*) AS n FROM experiments WHERE status IN ('active', 'running', 'waiting_owner') AND track = (SELECT track FROM e)),
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
x AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE exp_id = $1 AND source NOT LIKE 'claude_subscription%'),
checks AS (
  SELECT * FROM (VALUES
    ('kill_switch_off',   (SELECT ks FROM s) = 'off',                                      'Kill switch выключен'),
    ('wip_limit',         (SELECT n FROM a) <= (SELECT wip FROM s),                        'В работе не больше WIP-лимита (в своём треке)'),
    ('month_budget',      (SELECT spent FROM m) < (SELECT cap FROM s),                     'Траты фермы за месяц ниже потолка'),
    ('experiment_budget', (SELECT spent FROM x) < coalesce((SELECT budget_usd FROM e), 0), 'Траты эксперимента ниже его бюджета'),
    ('experiment_active', coalesce((SELECT status FROM e) = 'active', false),              'Эксперимент в статусе active (не ждёт решения, не занят, не закрыт)'),
    ('stage_order',       coalesce((SELECT stage FROM e) = $2::int, false),                'Эксперимент на том этапе, который запускается')
  ) AS v(rule, passed, detail)),
lk AS (
  UPDATE experiments SET status = 'running', updated_at = now()
  WHERE id = $1 AND status = 'active' AND (SELECT bool_and(passed) FROM checks)
  RETURNING id),
ins AS (
  INSERT INTO guardrail_events (exp_id, stage, rule, passed, detail)
  SELECT $1, $2::int, rule, passed, detail FROM checks
  UNION ALL
  SELECT $1, $2::int, 'lock_acquired', EXISTS (SELECT 1 FROM lk), 'Этап занят этим запуском (защита от параллельных прогонов)'
  RETURNING rule, passed, detail)
SELECT $1 AS exp_id, $2::int AS stage, bool_and(passed) AS ok,
       json_agg(json_build_object('rule', rule, 'passed', passed, 'detail', detail)) AS checks
FROM ins"""
c = {}
n = [
    sticky("## 90 · Guardrail preflight\nПеред каждым этапом, кодом, без LLM: kill switch · WIP-лимит · месячный потолок · бюджет эксперимента · статус active · этап совпадает с ожидаемым.\nЕсли всё прошло — **атомарно** ставит статус `running` (второй параллельный запуск не пройдёт). Каждая проверка пишется в `guardrail_events`.\nВход: exp_id, stage (ожидаемый этап от вызывающего workflow).", [-80, -360], 460, 290),
    sub_trigger([0, 0]),
    sql("Run checks and lock", PREFLIGHT_SQL, "={{ [$json.exp_id, $json.stage] }}", [240, 0]),
]
link(c, "Called by another workflow", "Run checks and lock")
PRE = upsert("90 · Guardrail preflight", n, c, ERR)

RELEASE_SQL = "UPDATE experiments SET status = $2, updated_at = now() WHERE id = $1 AND status = 'running' RETURNING id, status"


def blocked_branch(n, c, num, title, pos_y=160):
    n.append(code("Blocked report",
                  f"const r = $('Guardrail preflight').first().json;\nconst failed = (r.checks || []).filter(c => !c.passed).map(c => '✗ ' + c.detail).join('\\n');\n"
                  f"return [{{ json: {{ exp_id: r.exp_id, stage: {num}, kind: 'guardrail_blocked', actor: 'n8n', message: '⛔ Этап {num:02d} · {title} остановлен guardrails. Не выполнены условия:\\n' + failed, notify: true }} }}];",
                  [720, pos_y]))
    link(c, "All checks passed?", "Blocked report", 1)
    n.append(call("Log blocked", LOG, [960, pos_y]))
    link(c, "Blocked report", "Log blocked")


def stage_head(n, c, num, about):
    n += [
        sticky(about, [-80, -420], 540, 320),
        sub_trigger([-240, 0]),
        code("Expect this stage", f"return $input.all().map(i => ({{ json: {{ exp_id: i.json.exp_id, stage: {num} }} }}));", [0, 0]),
        call("Guardrail preflight", PRE, [240, 0]),
        if_true("All checks passed?", "={{ $json.ok }}", [480, 0]),
    ]
    link(c, "Called by another workflow", "Expect this stage")
    link(c, "Expect this stage", "Guardrail preflight")
    link(c, "Guardrail preflight", "All checks passed?")


# ---------- tracks: startups and web games share the same discovery → due diligence → gate shape ----------
TRACKS = {
    "startup": {"p": "", "disc_role": "discovery", "dd_role": "diligence", "dd_validate": "diligence", "noun": "брифов",
                "disc_name": "01 · Discovery", "dd_name": "02 · Due diligence and pitch", "dd_legacy": "02 · Brief choice",
                "disc_input": "Find 5 to 8 candidate briefs; stop when at least 5 pass the checklist",
                "pick_limit": 5, "dd_title": "инвестиционные меморандумы", "choice": "Выбрать для смоук-теста",
                "disc_about": "## 01 · Discovery (стартапы)\nАгент ищет боли с доказательствами денег → 5–8 брифов.\n\n**Guardrails:** preflight · ошибка агента → этап блокируется · проверка **кодом**: поля, чек-лист, CPC ≤ $1, канал, ≥2 типа источников, ≥3 цитаты дословно.\n\nУспех → этап 02 запускается сам.",
                "dd_about": "## 02 · Due diligence and pitch (стартапы)\nАналитики по ≤5 брифам: спрос (≥4 типа источников), рынок, конкуренты, юнит-экономика, план теста, red team → `memo.json` → проверка кодом → PDF.\n\n**Тебе уходят только лучшие:** проверка пройдена, вердикт не «pass», оценка ≥ `min_show_score`, максимум `max_shown` по убыванию оценки.\n\n**Твой шаг:** G1 — выбрать идею по PDF."},
    "game": {"p": "G", "disc_role": "game-discovery", "dd_role": "game-diligence", "dd_validate": "game-diligence", "noun": "концептов",
             "disc_name": "G01 · Game discovery", "dd_name": "G02 · Game due diligence and pitch", "dd_legacy": None,
             "disc_input": "Find 4 to 6 game concepts; stop when at least 4 pass the checklist",
             "pick_limit": 5, "dd_title": "меморандумы по играм", "choice": "Делать эту игру",
             "disc_about": "## G01 · Game discovery\nАгент изучает тренды порталов (CrazyGames, Poki, itch.io) → 4–6 концептов «популярная механика + новый поворот».\n\n**Guardrails:** проверка **кодом**: поля, чек-лист, ≥2 типа источников, ≥3 цитаты дословно, у референса есть цифра популярности.\n\nУспех → G02 запускается сам.",
             "dd_about": "## G02 · Game due diligence and pitch\nАналитики по ≤5 концептам: популярность механики, похожие игры, сценарии дохода (код пересчитывает), план разработки, требования порталов, red team → PDF.\n\n**Тебе уходят только лучшие** (как у стартапов).\n\n**Твой шаг:** G1 — выбрать игры для прототипа."},
}
STAGE_WF = {}


def wf_id(name, legacy=None):
    if legacy and legacy in existing and name not in existing:
        existing[name] = existing.pop(legacy)
    if name not in existing:
        existing[name] = {"id": api("POST", "/workflows", {"name": name, "nodes": [sub_trigger([0, 0])], "connections": {}, "settings": BASE_SETTINGS})["id"]}
    return existing[name]["id"]


def build_discovery(track, cfg, next_id):
    role = cfg["disc_role"]
    summary_js = f"""const run = $('Agent: {role}').first().json;
const val = $input.first().json;
const exp = $('Expect this stage').first().json.exp_id;
const briefs = val.briefs || [];
const passed = briefs.filter(b => b.passed);
return [{{ json: {{ exp_id: exp, passed: passed.length, total: briefs.length, cost: run.cost_usd || 0, turns: run.turns, session: run.session_id,
  briefs: briefs.map(b => ({{ slug: b.slug, title: b.title, channel: b.channel, cpc: b.cpc, price: b.price, passed: b.passed, failures: b.failures }})) }} }}];"""
    record_sql = f"""WITH j AS (SELECT $1::jsonb AS j),
c AS (INSERT INTO costs (exp_id, source, usd, detail)
      SELECT j->>'exp_id', 'claude_subscription_equiv', coalesce((j->>'cost')::numeric, 0), '{role} session ' || coalesce(j->>'session','') FROM j RETURNING 1),
u AS (UPDATE experiments SET stage  = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 2 ELSE stage END,
                             status = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 'active' ELSE 'blocked' END,
                             briefs = (SELECT j->'briefs' FROM j), updated_at = now()
      WHERE id = (SELECT j->>'exp_id' FROM j) AND status = 'running' RETURNING id),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT j->>'exp_id', 1, CASE WHEN (j->>'passed')::int > 0 THEN 'candidates_ready' ELSE 'candidates_rejected' END, 'n8n',
              'Discovery: прошли проверку ' || (j->>'passed') || ' из ' || (j->>'total') || ' {cfg['noun']}, ходов агента ' || coalesce(j->>'turns','?') FROM j RETURNING 1)
SELECT (SELECT (j->>'passed')::int FROM j) AS passed"""
    message_js = ESC_JS + f"""const s = $('Summarise').first().json;
const passed = s.briefs.filter(b => b.passed);
const failed = s.briefs.filter(b => !b.passed);
let text;
if (passed.length) {{
  text = `🧭 <b>${{s.exp_id}}: в работу аналитикам ушло ${{Math.min(passed.length, {cfg['pick_limit']})}} из ${{s.total}} {cfg['noun']}</b>.\\nТебе придут только лучшие — после due diligence и проверки кодом.`;
}} else {{
  text = `⛔ <b>${{s.exp_id}}: ни один из ${{s.total}} {cfg['noun']} не прошёл проверку</b>. Этап заблокирован до разбора.\\n` +
    failed.slice(0, 3).map(b => `• ${{esc(b.title || b.slug)}}: ${{esc((b.failures || []).join('; '))}}`).join('\\n');
}}
return [{{ json: {{ text, passed: passed.length }} }}];"""
    failed_js = f"""const exp = $('Expect this stage').first().json.exp_id;
const r = $input.first().json || {{}};
const why = r.error || r.result || (r.message ?? 'нет ответа от агента');
return [{{ json: {{ exp_id: exp, stage: 1, kind: 'agent_failed', actor: 'n8n', message: '⛔ {cfg['disc_name']}: агент не справился — ' + String(why).slice(0, 400), notify: true }} }}];"""
    c, n = {}, []
    stage_head(n, c, 1, cfg["disc_about"])
    n.append(node(f"Agent: {role}", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": f"{RUNNER_URL}/run/{role}",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "sendBody": True, "specifyBody": "json",
                   "jsonBody": "={\"exp_id\": \"{{ $('Expect this stage').first().json.exp_id }}\", \"stage\": 1, \"max_turns\": 150, \"queue_timeout_s\": 10800, \"input\": {\"note\": \"" + cfg["disc_input"] + "\"}}",
                   "options": {"timeout": 10800000}}, [720, -100], RUNNER, extra={"onError": "continueErrorOutput"}))
    link(c, "All checks passed?", f"Agent: {role}", 0)
    n.append(if_true("Agent succeeded?", "={{ $json.ok === true }}", [960, -100]))
    link(c, f"Agent: {role}", "Agent succeeded?", 0)
    n.append(node("Validate (code, no LLM)", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": f"={RUNNER_URL}/validate/{role}/{{{{ $('Expect this stage').first().json.exp_id }}}}",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "options": {"timeout": 600000}}, [1200, -180], RUNNER))
    link(c, "Agent succeeded?", "Validate (code, no LLM)", 0)
    n.append(code("Summarise", summary_js, [1440, -180]))
    link(c, "Validate (code, no LLM)", "Summarise")
    n.append(sql("Record cost, candidates, stage", record_sql, "={{ [JSON.stringify($json)] }}", [1680, -180]))
    link(c, "Summarise", "Record cost, candidates, stage")
    n.append(code("Compose message", message_js, [1920, -180]))
    link(c, "Record cost, candidates, stage", "Compose message")
    n.append(telegram("Tell owner", "={{ $json.text }}", [2160, -180]))
    link(c, "Compose message", "Tell owner")
    n.append(if_true("Any candidates?", "={{ $('Compose message').first().json.passed > 0 }}", [2400, -180]))
    link(c, "Tell owner", "Any candidates?")
    n.append(code("Next stage input", "return [{ json: { exp_id: $('Expect this stage').first().json.exp_id } }];", [2640, -260]))
    link(c, "Any candidates?", "Next stage input", 0)
    n.append(call("Start due diligence", next_id, [2880, -260], wait=False))
    link(c, "Next stage input", "Start due diligence")
    n.append(code("Agent failed", failed_js, [1200, 20]))
    link(c, f"Agent: {role}", "Agent failed", 1)
    link(c, "Agent succeeded?", "Agent failed", 1)
    n.append(sql("Mark blocked", RELEASE_SQL, "={{ [$json.exp_id, 'blocked'] }}", [1440, 20], extra={"alwaysOutputData": True}))
    link(c, "Agent failed", "Mark blocked")
    n.append(code("Pass failure on", "return [{ json: $('Agent failed').first().json }];", [1680, 20]))
    link(c, "Mark blocked", "Pass failure on")
    n.append(call("Log failure", LOG, [1920, 20]))
    link(c, "Pass failure on", "Log failure")
    blocked_branch(n, c, 1, cfg["disc_name"], pos_y=220)
    return upsert(cfg["disc_name"], n, c, ERR, executionTimeout=12000)


def build_diligence(track, cfg):
    role = cfg["dd_role"]
    pick_sql = f"""SELECT e.id AS exp_id, b->>'slug' AS slug, b->>'title' AS title
FROM experiments e, jsonb_array_elements(coalesce(e.briefs, '[]'::jsonb)) b
WHERE e.id = $1 AND (b->>'passed')::boolean IS TRUE
LIMIT {cfg['pick_limit']}"""
    collect_js = f"""const items = $('To analyse').all().map(i => i.json);
const runs = $('Agent: {role}').all().map(i => i.json);
const vals = $('Validate memo (code, no LLM)').all().map(i => i.json);
const out = items.map((it, k) => {{
  const r = runs[k] || {{}}, v = vals[k] || {{}};
  return {{ slug: it.slug, title: v.title || it.title, agent_ok: r.ok === true, cost: r.cost_usd || 0, turns: r.turns, session: r.session_id,
           passed: v.passed === true, verdict: v.verdict || null, score: Number((v.verdict || {{}}).score_0_10 || 0),
           evidence: v.evidence_count, verified: v.verified_quotes, failed_checks: (v.checks || []).filter(c => !c.passed).map(c => c.detail) }};
}});
return [{{ json: {{ exp_id: $('Expect this stage').first().json.exp_id, memos: out }} }}];"""
    record_sql = f"""WITH j AS (SELECT $1::jsonb AS j),
lim AS (SELECT coalesce(max(value) FILTER (WHERE key = 'min_show_score'), '6')::numeric AS min_score,
               coalesce(max(value) FILTER (WHERE key = 'max_shown'), '3')::int AS max_shown FROM settings),
q AS (SELECT m->>'slug' AS slug FROM j, jsonb_array_elements(j->'memos') m
      WHERE (m->>'passed')::boolean AND coalesce(m->'verdict'->>'recommendation', 'pass') <> 'pass'
        AND (m->>'score')::numeric >= (SELECT min_score FROM lim)
      ORDER BY (m->>'score')::numeric DESC LIMIT (SELECT max_shown FROM lim)),
c AS (INSERT INTO costs (exp_id, source, usd, detail)
      SELECT j->>'exp_id', 'claude_subscription_equiv', coalesce((m->>'cost')::numeric, 0), '{role} ' || (m->>'slug') FROM j, jsonb_array_elements(j->'memos') m RETURNING 1),
u AS (UPDATE experiments SET diligence = (SELECT j->'memos' FROM j),
             status = CASE WHEN EXISTS (SELECT 1 FROM q) THEN 'waiting_owner' ELSE 'blocked' END, updated_at = now()
      WHERE id = (SELECT j->>'exp_id' FROM j) AND status = 'running' RETURNING id),
g AS (INSERT INTO gate_tokens (exp_id, gate, stage, choices)
      SELECT j->>'exp_id', 'G1', 2, ARRAY(SELECT slug FROM q) FROM j WHERE EXISTS (SELECT 1 FROM q) RETURNING token),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT j->>'exp_id', 2, 'memos_ready', 'n8n', 'Due diligence: разобрано ' || jsonb_array_length(j->'memos') || ', лучших (проверка + оценка) ' || (SELECT count(*) FROM q) FROM j RETURNING 1)
SELECT (SELECT token FROM g) AS token, (SELECT coalesce(json_agg(slug), '[]'::json) FROM q) AS shown, (SELECT min_score FROM lim) AS min_score"""
    message_js = ESC_JS + f"""const s = $('Collect results').first().json;
const r = $input.first().json;
const shown = r.shown || [];
const rec = {{ invest: '🟢 инвестировать', maybe: '🟡 под вопросом', pass: '🔴 не инвестировать' }};
const best = shown.map(slug => s.memos.find(m => m.slug === slug)).filter(Boolean);
const rest = s.memos.length - best.length;
let text;
if (best.length) {{
  text = `📊 <b>${{s.exp_id}}: {cfg['dd_title']}</b>\\nРазобрано ${{s.memos.length}}, тебе — лучшие ${{best.length}} (проверка кодом пройдена, оценка ≥ ${{r.min_score}}). PDF — следующими сообщениями. Ссылки одноразовые, 72 ч, дома или через Tailscale:\\n\\n` +
    best.map((m, i) => `${{i+1}}. <b>${{esc(m.title)}}</b>\\n   ${{rec[(m.verdict || {{}}).recommendation] || '—'}} · ${{m.score}}/10 · доказательств ${{m.evidence ?? '—'}}, цитат подтверждено ${{m.verified ?? '—'}}\\n   <a href="{BASE}/farm-gate?g=${{r.token}}&c=${{encodeURIComponent(m.slug)}}">{cfg['choice']}</a>`).join('\\n\\n') +
    (rest ? `\\n\\nОтсеяно аналитикой: ${{rest}}` : '');
}} else {{
  text = `🗑 <b>${{s.exp_id}}: ни одна идея не дотянула</b> до порога (проверка кодом + оценка ≥ ${{r.min_score}}). Разобрано ${{s.memos.length}}:\\n` +
    s.memos.map(m => `• ${{esc(m.title)}} — ${{m.score || '—'}}/10${{m.passed ? '' : ', не прошла проверку'}}`).join('\\n') + `\\nМожно запустить новый поиск.`;
}}
return [{{ json: {{ text }} }}];"""
    shown_items_js = """const r = $('Record memos, cost, gate').first().json;
const s = $('Collect results').first().json;
return (r.shown || []).map(slug => { const m = s.memos.find(x => x.slug === slug) || {}; return { json: { exp_id: s.exp_id, slug, title: m.title, score: m.score } }; });"""
    c, n = {}, []
    stage_head(n, c, 2, cfg["dd_about"])
    n.append(sql("To analyse", pick_sql, "={{ [$('Expect this stage').first().json.exp_id] }}", [720, -120]))
    link(c, "All checks passed?", "To analyse", 0)
    for name, url, timeout, body, pos in [
        (f"Agent: {role}", f"{RUNNER_URL}/run/{role}", 10800000,
         "={\"exp_id\": \"{{ $json.exp_id }}\", \"slug\": \"{{ $json.slug }}\", \"max_turns\": 150, \"budget_usd\": 5, \"timeout_s\": 3000, \"queue_timeout_s\": 10800}", [960, -120]),
        ("Validate memo (code, no LLM)", f"={RUNNER_URL}/validate/{cfg['dd_validate']}/{{{{ $('To analyse').item.json.exp_id }}}}/{{{{ $('To analyse').item.json.slug }}}}", 600000, None, [1200, -120]),
        ("Render PDF", f"={RUNNER_URL}/render/diligence/{{{{ $('To analyse').item.json.exp_id }}}}/{{{{ $('To analyse').item.json.slug }}}}", 300000, None, [1440, -120]),
    ]:
        params = {"method": "POST", "url": url, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "options": {"timeout": timeout, "batching": {"batch": {"batchSize": 1, "batchInterval": 0}}}}
        if body:
            params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
        n.append(node(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, RUNNER, extra={"onError": "continueRegularOutput"}))
    link(c, "To analyse", f"Agent: {role}")
    link(c, f"Agent: {role}", "Validate memo (code, no LLM)")
    link(c, "Validate memo (code, no LLM)", "Render PDF")
    n.append(code("Collect results", collect_js, [1680, -120]))
    link(c, "Render PDF", "Collect results")
    n.append(sql("Record memos, cost, gate", record_sql, "={{ [JSON.stringify($json)] }}", [1920, -120]))
    link(c, "Collect results", "Record memos, cost, gate")
    n.append(code("Compose summary", message_js, [2160, -200]))
    link(c, "Record memos, cost, gate", "Compose summary")
    n.append(telegram("Send summary and choice links", "={{ $json.text }}", [2400, -200]))
    link(c, "Compose summary", "Send summary and choice links")
    n.append(code("Best only", shown_items_js, [2160, 0]))
    link(c, "Record memos, cost, gate", "Best only")
    n.append(node("Download PDF", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "GET", "url": f"={RUNNER_URL}/files/{{{{ $json.exp_id }}}}/dd/{{{{ $json.slug }}}}/deck.pdf",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "options": {"timeout": 120000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}},
                  [2400, 0], RUNNER, extra={"onError": "continueRegularOutput"}))
    link(c, "Best only", "Download PDF")
    n.append(node("Send PDF", "n8n-nodes-base.telegram", 1.2,
                  {"operation": "sendDocument", "chatId": CHAT, "binaryData": True, "binaryPropertyName": "data",
                   "additionalFields": {"caption": "={{ '📄 ' + $('Best only').item.json.exp_id + ' · ' + $('Best only').item.json.title + ' · ' + $('Best only').item.json.score + '/10' }}",
                                        "fileName": "={{ $('Best only').item.json.exp_id + '-' + $('Best only').item.json.slug + '.pdf' }}"}},
                  [2640, 0], TG, extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000, "onError": "continueRegularOutput"}))
    link(c, "Download PDF", "Send PDF")
    blocked_branch(n, c, 2, cfg["dd_name"], pos_y=260)
    return upsert(cfg["dd_name"], n, c, ERR, executionTimeout=30000)


for track, cfg in TRACKS.items():
    wf_id(cfg["dd_name"], cfg["dd_legacy"])
    # Publish order matters in n8n 2.x: the sub-workflow (02) must be published before 01 references it.
    STAGE_WF[f"{track}:2"] = build_diligence(track, cfg)
    STAGE_WF[f"{track}:1"] = build_discovery(track, cfg, STAGE_WF[f"{track}:2"])

# ---------- stage skeletons 03–08 for both tracks ----------
SKELETONS = {
    "startup": [
        (3, "Pre-registration", "preregistration", "Агент: пороги — канал, бюджет, n = 150, GO / KILL, дата решения.",
         "Guardrails: все поля · бюджет ≤ budget_test_usd · после одобрения хэш, правки запрещены.", "Твой шаг: одобрить пороги."),
        (4, "Landing", "landing", "Агент: лендинг → превью на Cloudflare Pages.",
         "Guardrails: HTTP 200 · форма пишет в waitlist · аналитика · Terms и Privacy · цена как в брифе.", "Твой шаг: одобрить публикацию."),
        (5, "Traffic and metrics", "traffic", "Агент: спецификация кампании, ежедневный сбор метрик в `metrics`.",
         "Guardrails: трата ≤ budget_day_usd и ≤ бюджета теста · ранний KILL на 100 визитах.", "Твой шаг: одобрить деньги и запустить кампанию."),
        (6, "Decision", None, "Решение по правилу предрегистрации.",
         "Guardrails: GO / KILL / продление только по правилу; переопределение пишется в decisions.", "Твой шаг: G2 — подтвердить."),
        (7, "Build MVP", "builder", "Агент: MVP в песочнице (только после GO).",
         "Guardrails: auth и оплату менять нельзя · тесты · сканеры зависимостей и секретов.", "Твой шаг: одобрить запуск оплаты."),
        (8, "Active users", "analyst", "Агент: регистрации, активация, удержание D1/D7, ошибки, аптайм — ежедневно.",
         "Guardrails: алерт при падении сайта или метрик.", "Твой шаг: G3 на 30-й день."),
    ],
    "game": [
        (3, "Prototype (HTML5)", "builder", "Агент: прототип HTML5/Phaser в песочнице, 1 механика, мобильный и десктоп.",
         "Guardrails: сборка без ошибок · без внешних запросов · размер < 10 МБ.", "Твой шаг: нет."),
        (4, "Autoplaytest and polish", "builder", "Бот играет 5 минут (Playwright), затем агент полирует: звук, частицы, обучение, SDK портала.",
         "Guardrails: 0 ошибок в консоли · FPS ≥ 50 · первый уровень проходим · чек-лист качества портала.", "Твой шаг: нет."),
        (5, "Owner review and publish", None, "Видео геймплея → тебе.", "Guardrails: публикация только после твоего решения.", "Твой шаг: G2 — публикуем или в мусор."),
        (6, "Portal metrics (30 days)", "analyst", "Агент собирает плейтайм, удержание и доход с портала.", "Guardrails: kill через 30 дней ниже порога.", "Твой шаг: нет."),
        (7, "Scale", "builder", "Уровни, обновления, порт на другие порталы и Telegram.", "Guardrails: как на этапах 03–04.", "Твой шаг: G3 — вкладываемся ли."),
        (8, "Live ops", "analyst", "Метрики и мелкие обновления.", "Guardrails: алерт при падении метрик.", "Твой шаг: нет."),
    ],
}
for track, stages in SKELETONS.items():
    pfx = TRACKS[track]["p"]
    for num, title, role, agent_txt, guard_txt, owner_txt in stages:
        c, n = {}, []
        note = "Агент ещё не подключён: узел выключен, этап проходит как каркас и снимает блокировку." if role else "Этап без агента."
        stage_head(n, c, num, f"## {pfx}{num:02d} · {title}\n{agent_txt}\n\n{guard_txt}\n\n{owner_txt}\n\n_{note}_")
        prev, x = "All checks passed?", 720
        if role:
            n.append(node(f"Agent: {role}", "n8n-nodes-base.httpRequest", 4.2,
                          {"method": "POST", "url": f"{RUNNER_URL}/run/{role}",
                           "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                           "sendBody": True, "specifyBody": "json",
                           "jsonBody": "={\"exp_id\": \"{{ $json.exp_id }}\", \"stage\": " + str(num) + "}",
                           "options": {"timeout": 3600000}}, [x, -100], RUNNER, disabled=True))
            link(c, prev, f"Agent: {role}", 0)
            prev, x = f"Agent: {role}", x + 240
            n.append(code("Validate output", "// Stage-specific checks run here once the agent is connected.\nreturn $input.all();", [x, -100], disabled=True))
            link(c, prev, "Validate output")
            prev, x = "Validate output", x + 240
        n.append(sql("Release lock", RELEASE_SQL, "={{ [$('Expect this stage').first().json.exp_id, 'active'] }}", [x, -100], extra={"alwaysOutputData": True}))
        link(c, prev, "Release lock", 0)
        n.append(code("Report", f"return [{{ json: {{ exp_id: $('Expect this stage').first().json.exp_id, stage: {num}, kind: 'stage_skeleton_ran', actor: 'n8n', message: 'Этап {pfx}{num:02d} · {title}: проверки пройдены, каркас отработал' + ({'true' if role else 'false'} ? ' (агент ещё не подключён)' : ''), notify: false }} }}];", [x + 240, -100]))
        link(c, "Release lock", "Report")
        n.append(call("Log event", LOG, [x + 480, -100]))
        link(c, "Report", "Log event")
        blocked_branch(n, c, num, f"{pfx}{num:02d} · {title}")
        STAGE_WF[f"{track}:{num}"] = upsert(f"{pfx}{num:02d} · {title}", n, c, ERR)


MAP_JS = f"const map = {json.dumps(STAGE_WF)};\nreturn $input.all().map(i => ({{ json: {{ ...i.json, workflow_id: map[(i.json.track || 'startup') + ':' + i.json.stage] }} }}));"

# ---------- 00 Controller (draft until the next stage has an agent) ----------
c = {}
n = [
    sticky("## 00 · Controller\nКаждые 15 минут берёт эксперименты в статусе `active` и запускает workflow их этапа (по одному запуску на эксперимент, без ожидания). Двойной запуск невозможен: preflight ставит `running` атомарно.\n\n**Черновик** (не опубликован), пока у следующего этапа нет агента.", [-80, -300], 460, 240),
    schedule("Every 15 minutes", "*/15 * * * *", [0, 0]),
    sql("Active experiments", "SELECT id AS exp_id, stage, track FROM experiments WHERE status = 'active' ORDER BY created_at", None, [240, 0]),
    code("Pick stage workflow", MAP_JS, [480, 0]),
    call("Run stage", "={{ $json.workflow_id }}", [720, 0], wait=False),
]
link(c, "Every 15 minutes", "Active experiments")
link(c, "Active experiments", "Pick stage workflow")
link(c, "Pick stage workflow", "Run stage")
CTRL = upsert("00 · Controller", n, c, ERR, publish=False)

# ---------- 91 Daily digest ----------
DIGEST_SQL = """SELECT json_build_object(
  'status',      (SELECT json_agg(v ORDER BY v.id) FROM v_status v),
  'events',      (SELECT json_agg(e ORDER BY e.ts) FROM (SELECT ts, exp_id, kind, message FROM events WHERE ts > now() - interval '24 hours') e),
  'guard_fail',  (SELECT count(*) FROM guardrail_events WHERE NOT passed AND ts > now() - interval '24 hours'),
  'month_spend', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
  'agent_equiv', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source LIKE 'claude_subscription%'),
  'month_cap',   (SELECT value FROM settings WHERE key = 'budget_month_usd'),
  'kill',        (SELECT value FROM settings WHERE key = 'kill_switch')) AS d"""
DIGEST_JS = ESC_JS + r"""const d = $input.first().json.d;
const status = (d.status || []).map(s => `• <b>${esc(s.id)}</b> ${esc(s.title)}\n   этап ${s.stage} · ${esc(s.stage_name)} · ${esc(s.status)} · $${Number(s.spent_usd).toFixed(2)} из $${Number(s.budget_usd).toFixed(0)}`).join('\n') || '—';
const events = (d.events || []).slice(-10).map(e => `• ${esc(e.exp_id || 'ферма')}: ${esc(e.message)}`).join('\n') || 'событий нет';
const text = `🌱 <b>Ферма · дайджест</b>\n\n<b>Стартапы</b>\n${status}\n\n<b>За сутки</b>\n${events}\n\nGuardrails сработали: ${d.guard_fail}\nТраты за месяц: $${Number(d.month_spend).toFixed(2)} из $${d.month_cap}\nАгенты (подписка, эквивалент API): $${Number(d.agent_equiv).toFixed(2)}\nKill switch: ${d.kill === 'on' ? '🔴 ВКЛЮЧЁН' : 'выключен'}`;
return [{ json: { text } }];"""
c = {}
n = [
    sticky("## 91 · Дайджест\n09:00 (Тбилиси): этапы, события за сутки, траты (деньги и подписка отдельно), guardrails. Вызывается и из пульта (action=digest).", [-80, -300], 440, 200),
    schedule("Every day 09:00", "0 9 * * *", [0, 0]),
    sub_trigger([0, 180]),
    sql("Collect status", DIGEST_SQL, None, [240, 80]),
    code("Format message", DIGEST_JS, [480, 80]),
    telegram("Send digest", "={{ $json.text }}", [720, 80]),
]
link(c, "Every day 09:00", "Collect status")
link(c, "Called by another workflow", "Collect status")
link(c, "Collect status", "Format message")
link(c, "Format message", "Send digest")
DIG = upsert("91 · Daily digest", n, c, ERR)

# ---------- 92 Guardrail watchdog ----------
WATCH_SQL = """WITH s AS (SELECT max(value) FILTER (WHERE key = 'budget_month_usd')::numeric AS cap FROM settings),
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
upd AS (
  UPDATE settings SET value = 'on'
  WHERE key = 'kill_switch' AND value = 'off' AND (SELECT spent FROM m) >= (SELECT cap FROM s)
  RETURNING 1),
stuck AS (
  UPDATE experiments SET status = 'blocked', updated_at = now()
  WHERE status = 'running' AND updated_at < now() - interval '4 hours'
  RETURNING id, stage),
ev AS (
  INSERT INTO events (kind, actor, message)
  SELECT 'kill_switch', 'watchdog', 'Месячный потолок трат достигнут — kill switch включён автоматически' FROM upd
  UNION ALL
  SELECT 'stuck_run', 'watchdog', id || ': этап ' || stage || ' висел в running больше 4 часов — переведён в blocked' FROM stuck
  RETURNING 1)
SELECT json_build_object(
  'budget_tripped', EXISTS (SELECT 1 FROM upd),
  'spent', (SELECT spent FROM m), 'cap', (SELECT cap FROM s),
  'stuck', (SELECT json_agg(json_build_object('id', id, 'stage', stage)) FROM stuck),
  'stale', (SELECT json_agg(json_build_object('id', id, 'stage', stage)) FROM experiments WHERE status = 'waiting_owner' AND updated_at < now() - interval '48 hours'),
  'guard_fail', (SELECT json_agg(json_build_object('exp', exp_id, 'stage', stage, 'detail', detail)) FROM guardrail_events WHERE NOT passed AND ts > now() - interval '1 hour' AND rule <> 'lock_acquired')) AS d"""
WATCH_JS = ESC_JS + r"""const d = $input.first().json.d;
const lines = [];
if (d.budget_tripped) lines.push(`🔴 Потолок трат за месяц достигнут ($${d.spent} из $${d.cap}). Kill switch включён, все этапы остановлены.`);
for (const s of d.stuck || []) lines.push(`🧱 ${esc(s.id)}: этап ${s.stage} завис больше 4 часов, переведён в blocked.`);
for (const s of d.stale || []) lines.push(`⏳ ${esc(s.id)}: ждёт твоего решения на этапе ${s.stage} больше 48 часов.`);
for (const g of d.guard_fail || []) lines.push(`⛔ ${esc(g.exp || 'ферма')} · этап ${g.stage}: ${esc(g.detail)}`);
if (!lines.length) return [];
return [{ json: { text: '🛡 <b>Ферма · guardrails</b>\n\n' + lines.join('\n') } }];"""
c = {}
n = [
    sticky("## 92 · Сторож guardrails\nКаждый час:\n- траты ≥ потолка → **сам включает kill switch**\n- этап висит в `running` > 4 ч → `blocked` + алерт\n- решение ждёт тебя > 48 ч → напоминание\n- проваленные проверки за час → алерт\nМолчит, если всё в порядке.", [-80, -340], 440, 250),
    schedule("Every hour", "5 * * * *", [0, 0]),
    sql("Check budgets, stuck runs, stale gates", WATCH_SQL, None, [240, 0]),
    code("Anything to report?", WATCH_JS, [480, 0]),
    telegram("Alert owner", "={{ $json.text }}", [720, 0]),
]
link(c, "Every hour", "Check budgets, stuck runs, stale gates")
link(c, "Check budgets, stuck runs, stale gates", "Anything to report?")
link(c, "Anything to report?", "Alert owner")
WATCH = upsert("92 · Guardrail watchdog", n, c, ERR)

# ---------- 95 Owner gates: one-time links, confirm page (GET) → apply (POST) ----------
GATE_LOOKUP_SQL = """SELECT t.token, t.exp_id, t.gate, t.stage, t.choices, t.expires_at, t.used_at, t.choice,
       e.status, e.stage AS exp_stage, e.briefs,
       (t.used_at IS NULL AND t.expires_at > now() AND e.status = 'waiting_owner' AND e.stage = t.stage AND $2 = ANY (t.choices)) AS valid
FROM gate_tokens t JOIN experiments e ON e.id = t.exp_id WHERE t.token = $1"""
PAGE_CSS = "body{font:16px/1.5 system-ui,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#16201b;background:#f2f4f1}h1{font-size:22px}.card{background:#fff;border:1px solid #d6ddd7;border-radius:12px;padding:16px}button{font:inherit;padding:10px 18px;border-radius:8px;border:0;background:#2f6f4e;color:#fff;cursor:pointer}.muted{color:#5b6b62}"
GATE_PAGE_JS = ESC_JS + f"""const q = $('Gate link').first().json.query || {{}};
const r = $input.first().json || {{}};
const page = (title, body) => `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${{esc(title)}}</title><style>{PAGE_CSS}</style></head><body>${{body}}</body></html>`;
if (!r.token) return [{{ json: {{ html: page('Ссылка не найдена', '<h1>Ссылка не найдена</h1><p class="muted">Возможно, она устарела или скопирована не полностью.</p>') }} }}];
if (!r.valid) {{
  const why = r.used_at ? 'Решение по этой ссылке уже принято' + (r.choice ? ': ' + esc(r.choice) : '') + '.' : (new Date(r.expires_at) < new Date() ? 'Срок ссылки истёк.' : 'Эксперимент сейчас не ждёт этого решения (статус ' + esc(r.status) + ', этап ' + r.exp_stage + ').');
  return [{{ json: {{ html: page('Ссылка недействительна', `<h1>Ссылка недействительна</h1><p>${{why}}</p>`) }} }}];
}}
const b = (r.briefs || []).find(x => x.slug === q.c) || {{ title: q.c }};
const body = `<h1>${{esc(r.exp_id)}} · ${{esc(r.gate)}}</h1><div class="card"><p class="muted">Выбор идеи для смоук-теста</p><p><b>${{esc(b.title)}}</b></p><p class="muted">канал ${{esc(b.channel)}} · CPC ~$${{esc(b.cpc)}} · цена ${{esc(b.price)}}</p>
<form method="post" action="{BASE}/farm-gate"><input type="hidden" name="g" value="${{esc(r.token)}}"><input type="hidden" name="c" value="${{esc(q.c)}}"><button type="submit">Подтвердить выбор</button></form></div>
<p class="muted">Ссылка одноразовая. После подтверждения эксперимент перейдёт на этап ${{r.stage + 1}}.</p>`;
return [{{ json: {{ html: page('Подтвердить выбор', body) }} }}];"""
GATE_APPLY_SQL = """WITH t AS (
  UPDATE gate_tokens g SET used_at = now(), choice = $2
  WHERE g.token = $1 AND g.used_at IS NULL AND g.expires_at > now() AND $2 = ANY (g.choices)
    AND EXISTS (SELECT 1 FROM experiments e WHERE e.id = g.exp_id AND e.status = 'waiting_owner' AND e.stage = g.stage)
  RETURNING g.exp_id, g.gate, g.stage),
u AS (
  UPDATE experiments e SET stage = least(e.stage + 1, 8), status = 'active',
         chosen_brief = CASE WHEN t.gate = 'G1' THEN $2 ELSE e.chosen_brief END, updated_at = now()
  FROM t WHERE e.id = t.exp_id RETURNING e.id, e.stage),
d AS (INSERT INTO decisions (exp_id, gate, decision, decided_by, note) SELECT exp_id, gate, 'approve', 'owner', $2 FROM t RETURNING 1),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message) SELECT exp_id, stage, 'owner_decision', 'owner', gate || ': выбран ' || $2 FROM t RETURNING 1)
SELECT (SELECT count(*) FROM u) AS applied, (SELECT id FROM u) AS exp_id, (SELECT stage FROM u) AS stage"""
GATE_RESULT_JS = ESC_JS + f"""const r = $input.first().json || {{}};
const ok = Number(r.applied) > 0;
const title = ok ? 'Принято' : 'Не принято';
const body = ok ? `<h1>Принято</h1><p>${{esc(r.exp_id)}} перешёл на этап ${{r.stage}}.</p>` : '<h1>Не принято</h1><p>Ссылка уже использована, устарела, или эксперимент сейчас не ждёт этого решения.</p>';
return [{{ json: {{ ok, exp_id: r.exp_id, stage: r.stage, html: `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${{title}}</title><style>{PAGE_CSS}</style></head><body>${{body}}</body></html>` }} }}];"""
c = {}
n = [
    sticky("## 95 · Гейты владельца\nОдноразовые ссылки из Telegram (без мастер-токена):\n1. **GET** — страница подтверждения, ничего не меняет (безопасно для предпросмотров).\n2. **POST** (кнопка) — решение: ссылка гаснет, эксперимент переходит на следующий этап. Повторный клик ничего не делает.\nСрок ссылки 72 ч. Таблица `gate_tokens`.", [-80, -380], 480, 270),
    webhook("Gate link", "farm-gate", "GET", [0, 0]),
    sql("Look up gate", GATE_LOOKUP_SQL, "={{ [$json.query.g || '', $json.query.c || ''] }}", [240, 0], extra={"alwaysOutputData": True}),
    code("Render confirm page", GATE_PAGE_JS, [480, 0]),
    respond("Show page", "={{ $json.html }}", [720, 0], html=True),
    webhook("Gate confirm", "farm-gate", "POST", [0, 300]),
    sql("Apply decision", GATE_APPLY_SQL, "={{ [$json.body.g || '', $json.body.c || ''] }}", [240, 300], extra={"alwaysOutputData": True}),
    code("Render result", GATE_RESULT_JS, [480, 300]),
    respond("Show result", "={{ $json.html }}", [720, 300], html=True),
    if_true("Accepted?", "={{ $('Render result').first().json.ok }}", [960, 300]),
    telegram("Confirm in Telegram", "=✅ <b>{{ $('Render result').first().json.exp_id }}</b>: решение принято, этап {{ $('Render result').first().json.stage }}.", [1200, 300]),
]
link(c, "Gate link", "Look up gate")
link(c, "Look up gate", "Render confirm page")
link(c, "Render confirm page", "Show page")
link(c, "Gate confirm", "Apply decision")
link(c, "Apply decision", "Render result")
link(c, "Render result", "Show result")
link(c, "Show result", "Accepted?")
link(c, "Accepted?", "Confirm in Telegram", 0)
GATES = upsert("95 · Owner gates", n, c, ERR, saveDataSuccessExecution="none")

# ---------- 96 Read-only status API (Hermes) ----------
RO_SQL = """SELECT CASE WHEN $1 <> '' AND $1 = (SELECT value FROM settings WHERE key = 'ro_token') THEN json_build_object(
  'ok', true,
  'experiments', (SELECT json_agg(json_build_object('id', e.id, 'track', e.track, 'title', e.title, 'stage', e.stage, 'stage_name', s.name, 'status', e.status,
                   'chosen_brief', e.chosen_brief, 'briefs', e.briefs, 'diligence', e.diligence, 'budget_usd', e.budget_usd,
                   'spent_usd', (SELECT coalesce(sum(usd), 0) FROM costs c WHERE c.exp_id = e.id AND c.source NOT LIKE 'claude_subscription%'),
                   'agent_equiv_usd', (SELECT coalesce(sum(usd), 0) FROM costs c WHERE c.exp_id = e.id AND c.source LIKE 'claude_subscription%'),
                   'issue_url', e.issue_url, 'updated_at', e.updated_at) ORDER BY e.id)
                  FROM experiments e JOIN stages s ON s.track = e.track AND s.stage = e.stage),
  'stages', (SELECT json_agg(json_build_object('track', track, 'stage', stage, 'name', name, 'gate', gate) ORDER BY track, stage) FROM stages),
  'recent_events', (SELECT json_agg(v ORDER BY v.ts DESC) FROM (SELECT ts, exp_id, stage, kind, message FROM events ORDER BY id DESC LIMIT 30) v),
  'guardrail_failures_24h', (SELECT json_agg(v) FROM (SELECT ts, exp_id, stage, detail FROM guardrail_events WHERE NOT passed AND rule <> 'lock_acquired' AND ts > now() - interval '24 hours' ORDER BY id DESC LIMIT 20) v),
  'kill_switch', (SELECT value FROM settings WHERE key = 'kill_switch'),
  'month_spend_usd', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
  'month_cap_usd', (SELECT value FROM settings WHERE key = 'budget_month_usd'))
ELSE json_build_object('ok', false, 'error', 'bad token') END AS d"""
c = {}
n = [
    sticky("## 96 · Статус только для чтения\n`GET /webhook/farm-status` с заголовком `X-Farm-Token` (токен `ro_token`). Отдаёт стартапы, брифы, последние события, провалы guardrails, траты. **Ничего не меняет.** Им пользуется Hermes.", [-80, -300], 460, 200),
    webhook("Status request", "farm-status", "GET", [0, 0]),
    sql("Read status", RO_SQL, "={{ [$json.headers['x-farm-token'] || ''] }}", [240, 0]),
    respond("Return JSON", "={{ JSON.stringify($json.d) }}", [480, 0]),
]
link(c, "Status request", "Read status")
link(c, "Read status", "Return JSON")
RO = upsert("96 · Read-only status", n, c, ERR, saveDataSuccessExecution="none")

# ---------- 99 Control panel (owner admin; responds immediately) ----------
PLAN_JS = r"""const q = $('Control link').first().json.query || {};
const token = $input.first().json.value;
if (!q.t || q.t !== token) return [{ json: { ok: false, reply: 'Неверный токен' } }];
const a = q.action;
if (a === 'status') return [{ json: { ok: true, action: a, sql: "SELECT json_agg(v ORDER BY v.id) AS rows FROM v_status v", params: [] } }];
if (a === 'kill_on' || a === 'kill_off') {
  const v = a === 'kill_on' ? 'on' : 'off';
  return [{ json: { ok: true, action: a, sql: "WITH u AS (UPDATE settings SET value = $1 WHERE key = 'kill_switch' RETURNING value), ev AS (INSERT INTO events (kind, actor, message) SELECT 'kill_switch', 'owner', 'Kill switch: ' || value FROM u RETURNING 1) SELECT value FROM u", params: [v] } }];
}
if (a === 'decide') {
  const allowed = ['kill', 'pause', 'resume'];
  if (!q.exp || !allowed.includes(q.decision)) return [{ json: { ok: false, reply: 'decide в пульте: только ' + allowed.join(', ') + '. Одобрения гейтов идут одноразовыми ссылками из Telegram.' } }];
  return [{ json: { ok: true, action: a, sql: "WITH u AS (UPDATE experiments SET status = CASE $2 WHEN 'kill' THEN 'killed' WHEN 'pause' THEN 'paused' ELSE 'active' END, updated_at = now() WHERE id = $1 AND ($2 <> 'resume' OR status IN ('paused', 'blocked')) RETURNING id, stage, status), d AS (INSERT INTO decisions (exp_id, gate, decision, decided_by, note) SELECT id, 'panel', $2, 'owner', $3 FROM u RETURNING 1), ev AS (INSERT INTO events (exp_id, kind, actor, message) SELECT id, 'owner_decision', 'owner', 'Пульт: ' || $2 FROM u RETURNING 1) SELECT * FROM u", params: [q.exp, q.decision, q.note || ''] } }];
}
if (a === 'cost') {
  const usd = Number(q.usd);
  if (!q.exp || !(usd >= 0) || !q.source) return [{ json: { ok: false, reply: 'cost требует exp, usd (число) и source' } }];
  return [{ json: { ok: true, action: a, sql: "WITH c AS (INSERT INTO costs (exp_id, source, usd, detail) VALUES ($1, $3, $2::numeric, $4) RETURNING exp_id, source, usd), ev AS (INSERT INTO events (exp_id, kind, actor, message) SELECT exp_id, 'cost', 'owner', 'Трата ' || usd || ' USD · ' || source FROM c RETURNING 1) SELECT * FROM c", params: [q.exp, String(usd), q.source, q.note || ''] } }];
}
if (a === 'advance') {
  const to = parseInt(q.to, 10);
  if (!q.exp || !(to >= 1 && to <= 8)) return [{ json: { ok: false, reply: 'advance требует exp и to (1–8)' } }];
  return [{ json: { ok: true, action: a, sql: "WITH old AS (SELECT stage FROM experiments WHERE id = $1), u AS (UPDATE experiments SET stage = $2::int, status = 'active', updated_at = now() WHERE id = $1 AND status <> 'running' RETURNING id, stage), ev AS (INSERT INTO events (exp_id, stage, kind, actor, message) SELECT id, stage, 'stage_changed', 'owner', 'Этап ' || (SELECT stage FROM old) || ' → ' || stage FROM u RETURNING 1) SELECT * FROM u", params: [q.exp, String(to)] } }];
}
if (a === 'run') {
  if (!q.exp) return [{ json: { ok: false, reply: 'run требует exp' } }];
  return [{ json: { ok: true, action: a, sql: "SELECT id AS exp_id, stage, track FROM experiments WHERE id = $1", params: [q.exp] } }];
}
if (a === 'digest') return [{ json: { ok: true, action: a } }];
return [{ json: { ok: false, reply: 'Неизвестное действие. Есть: status, kill_on, kill_off, decide (kill/pause/resume), digest, run, cost, advance' } }];"""
c = {}
n = [
    sticky("## 99 · Пульт (администрирование)\n`https://n8n.home.kalik8s.ru/webhook/farm?t=<токен>&action=…`\n- `status` · `kill_on` / `kill_off` · `digest`\n- `run&exp=EXP-001` — запустить этап, ответ сразу («запущено»)\n- `decide&exp=…&decision=kill|pause|resume`\n- `cost&exp=…&usd=…&source=…` · `advance&exp=…&to=N`\n**Гейты (выбор брифа и т. п.) — только одноразовыми ссылками (95).** Успешные запуски пульта не сохраняются (токен в URL).", [-80, -400], 560, 300),
    webhook("Control link", "farm", "GET", [0, 0]),
    sql("Read token", "SELECT value FROM settings WHERE key = 'control_token'", None, [240, 0]),
    code("Check token and plan", PLAN_JS, [480, 0]),
    if_true("Token ok?", "={{ $json.ok }}", [720, 0]),
    code("Reject", "return [{ json: { ok: false, reply: $input.first().json.reply } }];", [960, 200]),
    respond("Respond rejected", "={{ JSON.stringify($json) }}", [1200, 200]),
    if_true("Digest?", "={{ $json.action === 'digest' }}", [960, -80]),
    call("Run digest", DIG, [1200, -220]),
    sql("Apply action", "={{ $json.sql }}", "={{ $json.params }}", [1200, 40], extra={"alwaysOutputData": True}),
    if_true("Run a stage?", "={{ $('Check token and plan').first().json.action === 'run' }}", [1440, 40]),
    respond("Respond started", "={{ JSON.stringify({ ok: true, action: 'run', started: $input.all().map(i => i.json) }) }}", [1680, -40]),
    code("Pick stage workflow", MAP_JS, [1920, -40]),
    call("Run stage", "={{ $json.workflow_id }}", [2160, -40], wait=False),
    code("Reply", "const a = $('Check token and plan').first().json.action;\nreturn [{ json: { ok: true, action: a, result: $input.all().map(i => i.json) } }];", [1680, 160]),
    respond("Respond result", "={{ JSON.stringify($json) }}", [1920, 160]),
]
link(c, "Control link", "Read token")
link(c, "Read token", "Check token and plan")
link(c, "Check token and plan", "Token ok?")
link(c, "Token ok?", "Digest?", 0)
link(c, "Token ok?", "Reject", 1)
link(c, "Reject", "Respond rejected")
link(c, "Digest?", "Run digest", 0)
link(c, "Digest?", "Apply action", 1)
link(c, "Run digest", "Reply")
link(c, "Apply action", "Run a stage?")
link(c, "Run a stage?", "Respond started", 0)
link(c, "Run a stage?", "Reply", 1)
link(c, "Respond started", "Pick stage workflow")
link(c, "Pick stage workflow", "Run stage")
link(c, "Reply", "Respond result")
PANEL = upsert("99 · Control panel", n, c, ERR, saveDataSuccessExecution="none")

LOCK_FILE.write_text(json.dumps(lock, indent=1, sort_keys=True))
print(json.dumps({"error": ERR, "log": LOG, "preflight": PRE, "stages": STAGE_WF, "controller": CTRL, "digest": DIG,
                  "watchdog": WATCH, "gates": GATES, "status_ro": RO, "panel": PANEL}))
if skipped:
    print("SKIPPED (edited in UI):", ", ".join(skipped))
