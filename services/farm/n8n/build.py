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
LANDING = {"httpHeaderAuth": {"id": env["LANDING_CRED_ID"], "name": "Landing stats token"}}
LANDING_URL = env["LANDING_BASE_URL"].rstrip("/")
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
a AS (SELECT count(*) AS n FROM experiments WHERE status IN ('active', 'running', 'waiting_owner', 'testing') AND track = (SELECT track FROM e)),
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_%'),
x AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE exp_id = $1 AND source NOT LIKE 'claude_%'),
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
                "disc_about": "## 01 · Discovery (стартапы)\nАгент получает память фермы (история идей, 10 самых весомых уроков) и ищет задачи, за которые уже платят → 5–8 брифов. Запрещены «дешёвые клоны лидера».\n\n**Guardrails (код):** поля и чек-лист · ≥ 2 типа источников · ≥ 3 цитаты найдены дословно (эхо собственного запроса не считается) · **экономика**: LTV ≥ $150; платный канал — CPC из цитаты свежего бенчмарка ≤ $1 и LTV/CAC ≥ 1,5; органический — проверенная цифра спроса в канале.\n\nНикто не прошёл → `93` (уроки + новый раунд). Успех → этап 02 сам.",
                "dd_about": "## 02 · Due diligence and pitch (стартапы)\nАналитики по ≤ 5 брифам: спрос, рынок, конкуренты, юнит-экономика, план теста, red team → `memo.json` → проверка кодом (счёт только по подтверждённым цитатам, потолки допущений) → **панель 3 независимых судей** (не видят оценку автора, обязаны проверить факт по ссылке) → PDF.\n\n**Тебе уходят только лучшие:** медиана судей ≥ `min_show_score`, не «pass», максимум `max_shown`. В PDF — слайд «Что нужно от инвестора».\n\n**Твой шаг:** G1 — выбрать идею по PDF. Без этого ни одного доллара на тест."},
    "game": {"p": "G", "disc_role": "game-discovery", "dd_role": "game-diligence", "dd_validate": "game-diligence", "noun": "концептов",
             "disc_name": "G01 · Game discovery", "dd_name": "G02 · Game due diligence and pitch", "dd_legacy": None,
             "disc_input": "Find 4 to 6 game concepts; stop when at least 4 pass the checklist",
             "pick_limit": 5, "dd_title": "меморандумы по играм", "choice": "Делать эту игру",
             "disc_about": "## G01 · Game discovery\nАгент изучает тренды порталов (CrazyGames, Poki, itch.io) → 4–6 концептов «популярная механика + новый поворот».\n\n**Guardrails:** проверка **кодом**: поля, чек-лист, ≥2 типа источников, ≥3 цитаты дословно, у референса есть цифра популярности.\n\nУспех → G02 запускается сам.",
             "dd_about": "## G02 · Game due diligence and pitch\nАналитики по ≤5 концептам: популярность механики, похожие игры, сценарии дохода (код пересчитывает), план разработки, требования порталов, red team → PDF.\n\n**Тебе уходят только лучшие** (как у стартапов).\n\n**Твой шаг:** G1 — выбрать игры для прототипа."},
}
STAGE_WF = {}

# Farm memory for agents: the 10 strongest lessons (more turned discovery into an echo chamber that wrote 0 briefs)
# and past ideas of the same track, plus whether the API budget still has room.
MEMORY_SQL = """(SELECT json_build_object(
  'lessons', (SELECT coalesce(json_agg(json_build_object('id', l.id, 'kind', l.kind, 'lesson', l.lesson, 'weight', l.weight)), '[]'::json)
              FROM (SELECT * FROM lessons WHERE active AND track = x.track ORDER BY weight DESC, last_seen DESC LIMIT 10) l),
  'history', (SELECT coalesce(json_agg(json_build_object('slug', h.slug, 'title', h.title, 'outcome', h.outcome, 'score', h.score,
                                                          'verdict', h.verdict, 'why', h.reasons) ORDER BY h.ts DESC), '[]'::json)
              FROM (SELECT DISTINCT ON (slug) * FROM idea_history WHERE track = x.track ORDER BY slug, ts DESC LIMIT 200) h))
 FROM (SELECT track FROM experiments WHERE id = $1) x)"""
USE_API_SQL = """((SELECT coalesce(max(value) FILTER (WHERE key = 'api_budget_month_usd'), '0')::numeric FROM settings)
  - (SELECT coalesce(sum(usd), 0) FROM costs WHERE source = 'claude_api' AND ts >= date_trunc('month', now())) > 5)"""
COST_SOURCE = "CASE WHEN {0}->>'billing' = 'api' THEN 'claude_api' ELSE 'claude_subscription_equiv' END"


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
  billing: run.billing,
  briefs: briefs.map(b => ({{ slug: b.slug, title: b.title, channel: b.channel, cpc: b.cpc, price: b.price, passed: b.passed, failures: b.failures }})) }} }}];"""
    record_sql = f"""WITH j AS (SELECT $1::jsonb AS j),
c AS (INSERT INTO costs (exp_id, source, usd, detail)
      SELECT j->>'exp_id', {COST_SOURCE.format("j")}, coalesce((j->>'cost')::numeric, 0), '{role} session ' || coalesce(j->>'session','') FROM j RETURNING 1),
h AS (INSERT INTO idea_history (exp_id, track, round, slug, title, outcome, reasons)
      SELECT e.id, e.track, e.round, b->>'slug', b->>'title', 'rejected_by_checks', jsonb_build_object('failed_checks', b->'failures')
      FROM j, experiments e, jsonb_array_elements(j->'briefs') b
      WHERE e.id = j->>'exp_id' AND NOT coalesce((b->>'passed')::boolean, false) RETURNING 1),
u AS (UPDATE experiments SET stage  = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 2 ELSE stage END,
                             status = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 'active' ELSE 'blocked' END,
                             briefs = (SELECT j->'briefs' FROM j), updated_at = now()
      WHERE id = (SELECT j->>'exp_id' FROM j) AND status = 'running' RETURNING id),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT j->>'exp_id', 1, CASE WHEN (j->>'passed')::int > 0 THEN 'candidates_ready' ELSE 'candidates_rejected' END, 'n8n',
              'Discovery: прошли проверку ' || (j->>'passed') || ' из ' || (j->>'total') || ' {cfg['noun']}, ходов агента ' || coalesce(j->>'turns','?') FROM j RETURNING 1)
SELECT (SELECT (j->>'passed')::int FROM j) AS passed"""
    failed_js = f"""const exp = $('Expect this stage').first().json.exp_id;
const r = $input.first().json || {{}};
const why = r.error || r.result || (r.message ?? 'нет ответа от агента');
return [{{ json: {{ exp_id: exp, stage: 1, kind: 'agent_failed', actor: 'n8n', message: '⛔ {cfg['disc_name']}: агент не справился — ' + String(why).slice(0, 400), notify: true }} }}];"""
    c, n = {}, []
    stage_head(n, c, 1, cfg["disc_about"])
    n.append(sql("Load memory", f"SELECT {MEMORY_SQL} AS memory, {USE_API_SQL} AS use_api",
                 "={{ [$('Expect this stage').first().json.exp_id] }}", [600, -260]))
    link(c, "All checks passed?", "Load memory", 0)
    n.append(node(f"Agent: {role}", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": f"{RUNNER_URL}/run/{role}",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "sendBody": True, "specifyBody": "json",
                   "jsonBody": "={\"exp_id\": \"{{ $('Expect this stage').first().json.exp_id }}\", \"stage\": 1, \"max_turns\": 150, \"queue_timeout_s\": 10800, \"budget_usd\": 8, \"use_api\": {{ $json.use_api }}, \"memory\": {{ JSON.stringify($json.memory) }}, \"input\": {\"note\": \"" + cfg["disc_input"] + ". Read memory.json first.\"}}",
                   "options": {"timeout": 10800000}}, [720, -100], RUNNER, extra={"onError": "continueErrorOutput"}))
    link(c, "Load memory", f"Agent: {role}")
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
    n.append(if_true("Any candidates?", "={{ $json.passed > 0 }}", [1920, -180]))
    link(c, "Record cost, candidates, stage", "Any candidates?")
    n.append(code("Retry input", "return [{ json: { exp_id: $('Expect this stage').first().json.exp_id } }];", [2160, -60]))
    link(c, "Any candidates?", "Retry input", 1)
    n.append(call("Learn and retry", LEARN, [2400, -60], wait=False))
    link(c, "Retry input", "Learn and retry")
    n.append(code("Next stage input", "return [{ json: { exp_id: $('Expect this stage').first().json.exp_id } }];", [2160, -300]))
    link(c, "Any candidates?", "Next stage input", 0)
    n.append(call("Start due diligence", next_id, [2400, -300], wait=False))
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
    pick_sql = f"""SELECT e.id AS exp_id, b->>'slug' AS slug, b->>'title' AS title, {MEMORY_SQL} AS memory, {USE_API_SQL} AS use_api
FROM experiments e, jsonb_array_elements(coalesce(e.briefs, '[]'::jsonb)) b
WHERE e.id = $1 AND (b->>'passed')::boolean IS TRUE
LIMIT {cfg['pick_limit']}"""
    collect_js = f"""const items = $('To analyse').all().map(i => i.json);
const runs = $('Agent: {role}').all().map(i => i.json);
const vals = $('Validate memo (code, no LLM)').all().map(i => i.json);
const panels = $('Judges panel').all().map(i => i.json);
const out = items.map((it, k) => {{
  const r = runs[k] || {{}}, v = vals[k] || {{}}, jp = panels[k] || {{}};
  const panel = jp.panel || null;
  // The farm's score is the median of three independent judges; without a panel the memo cannot qualify.
  const verdict = {{ ...(v.verdict || {{}}), author_score: (v.verdict || {{}}).score_0_10, recommendation: panel ? panel.recommendation : 'pass' }};
  return {{ slug: it.slug, title: v.title || it.title, agent_ok: r.ok === true, cost: (r.cost_usd || 0) + (jp.cost_usd || 0), turns: r.turns, session: r.session_id, billing: r.billing,
           passed: v.passed === true && !!panel, verdict, score: panel ? panel.median : 0, panel_spread: panel ? panel.spread : null,
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
      SELECT j->>'exp_id', {COST_SOURCE.format("m")}, coalesce((m->>'cost')::numeric, 0), '{role} ' || (m->>'slug') FROM j, jsonb_array_elements(j->'memos') m RETURNING 1),
h AS (INSERT INTO idea_history (exp_id, track, round, slug, title, outcome, score, verdict, reasons)
      SELECT e.id, e.track, e.round, m->>'slug', m->>'title',
             CASE WHEN m->>'slug' IN (SELECT slug FROM q) THEN 'shown_to_owner'
                  WHEN (m->>'passed')::boolean THEN 'below_threshold' ELSE 'rejected_by_checks' END,
             NULLIF(m->>'score', '')::numeric, m->'verdict'->>'recommendation',
             jsonb_build_object('why', m->'verdict'->>'why', 'failed_checks', m->'failed_checks')
      FROM j, experiments e, jsonb_array_elements(j->'memos') m WHERE e.id = j->>'exp_id' RETURNING 1),
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
const text = `📊 <b>${{s.exp_id}}: {cfg['dd_title']}</b>\\nРазобрано ${{s.memos.length}}, тебе — лучшие ${{best.length}} (проверка кодом пройдена, медиана трёх независимых судей ≥ ${{r.min_score}}). PDF — следующими сообщениями. Ссылки одноразовые, 72 ч, дома или через Tailscale:\\n\\n` +
    best.map((m, i) => `${{i+1}}. <b>${{esc(m.title)}}</b>\\n   ${{rec[(m.verdict || {{}}).recommendation] || '—'}} · ${{m.score}}/10 · доказательств ${{m.evidence ?? '—'}}, цитат подтверждено ${{m.verified ?? '—'}}\\n   <a href="{BASE}/farm-gate?g=${{r.token}}&c=${{encodeURIComponent(m.slug)}}">{cfg['choice']}</a>`).join('\\n\\n') +
    (rest ? `\\n\\nОтсеяно аналитикой: ${{rest}}` : '');
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
         "={\"exp_id\": \"{{ $json.exp_id }}\", \"slug\": \"{{ $json.slug }}\", \"max_turns\": 150, \"budget_usd\": 5, \"timeout_s\": 3000, \"queue_timeout_s\": 10800, \"use_api\": {{ $json.use_api }}, \"memory\": {{ JSON.stringify($json.memory) }}}", [960, -120]),
        ("Validate memo (code, no LLM)", f"={RUNNER_URL}/validate/{cfg['dd_validate']}/{{{{ $('To analyse').item.json.exp_id }}}}/{{{{ $('To analyse').item.json.slug }}}}", 600000, None, [1200, -120]),
        ("Judges panel", f"{RUNNER_URL}/run/judges", 10800000,
         "={\"exp_id\": \"{{ $('To analyse').item.json.exp_id }}\", \"slug\": \"{{ $('To analyse').item.json.slug }}\", \"skip\": {{ $json.passed !== true }}, \"max_turns\": 60, \"budget_usd\": 2, \"timeout_s\": 2400, \"queue_timeout_s\": 10800, \"use_api\": {{ $('To analyse').item.json.use_api }}, \"memory\": {{ JSON.stringify($('To analyse').item.json.memory) }}, \"input\": {\"note\": \"Run the three-judge panel on memo.json; write panel.json\"}}", [1440, -120]),
        ("Render PDF", f"={RUNNER_URL}/render/diligence/{{{{ $('To analyse').item.json.exp_id }}}}/{{{{ $('To analyse').item.json.slug }}}}", 300000, None, [1680, -120]),
    ]:
        params = {"method": "POST", "url": url, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "options": {"timeout": timeout, "batching": {"batch": {"batchSize": 1, "batchInterval": 0}}}}
        if body:
            params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
        n.append(node(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, RUNNER, extra={"onError": "continueRegularOutput"}))
    link(c, "To analyse", f"Agent: {role}")
    link(c, f"Agent: {role}", "Validate memo (code, no LLM)")
    link(c, "Validate memo (code, no LLM)", "Judges panel")
    link(c, "Judges panel", "Render PDF")
    n.append(code("Collect results", collect_js, [1920, -120]))
    link(c, "Render PDF", "Collect results")
    n.append(sql("Record memos, cost, gate", record_sql, "={{ [JSON.stringify($json)] }}", [2160, -120]))
    link(c, "Collect results", "Record memos, cost, gate")
    n.append(if_true("Anything worth showing?", "={{ ($json.shown || []).length > 0 }}", [2400, -120]))
    link(c, "Record memos, cost, gate", "Anything worth showing?")
    n.append(code("Compose summary", message_js, [2640, -220]))
    link(c, "Anything worth showing?", "Compose summary", 0)
    n.append(telegram("Send summary and choice links", "={{ $json.text }}", [2880, -220]))
    link(c, "Compose summary", "Send summary and choice links")
    n.append(code("Best only", shown_items_js, [2640, -20]))
    link(c, "Anything worth showing?", "Best only", 0)
    n.append(code("Retry input", "return [{ json: { exp_id: $('Expect this stage').first().json.exp_id } }];", [2640, 180]))
    link(c, "Anything worth showing?", "Retry input", 1)
    n.append(call("Learn and retry", LEARN, [2880, 180], wait=False))
    link(c, "Retry input", "Learn and retry")
    n.append(node("Download PDF", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "GET", "url": f"={RUNNER_URL}/files/{{{{ $json.exp_id }}}}/dd/{{{{ $json.slug }}}}/deck.pdf",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "options": {"timeout": 120000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}},
                  [2880, -20], RUNNER, extra={"onError": "continueRegularOutput"}))
    link(c, "Best only", "Download PDF")
    n.append(node("Send PDF", "n8n-nodes-base.telegram", 1.2,
                  {"operation": "sendDocument", "chatId": CHAT, "binaryData": True, "binaryPropertyName": "data",
                   "additionalFields": {"caption": "={{ '📄 ' + $('Best only').item.json.exp_id + ' · ' + $('Best only').item.json.title + ' · ' + $('Best only').item.json.score + '/10' }}",
                                        "fileName": "={{ $('Best only').item.json.exp_id + '-' + $('Best only').item.json.slug + '.pdf' }}"}},
                  [3120, -20], TG, extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000, "onError": "continueRegularOutput"}))
    link(c, "Download PDF", "Send PDF")
    blocked_branch(n, c, 2, cfg["dd_name"], pos_y=260)
    return upsert(cfg["dd_name"], n, c, ERR, executionTimeout=30000)


# ---------- 93 Learn and retry: reflect on a round that produced nothing worth showing, save lessons, start the next round ----------
LEARN_LOAD_SQL = f"""SELECT e.id AS exp_id, e.track, e.round,
  ({MEMORY_SQL}::jsonb || jsonb_build_object('current',
     (SELECT coalesce(jsonb_agg(b->>'slug'), '[]'::jsonb) FROM jsonb_array_elements(coalesce(e.briefs, '[]'::jsonb)) b))) AS memory,
  {USE_API_SQL} AS use_api
FROM experiments e WHERE e.id = $1"""
LEARN_SAVE_SQL = f"""WITH j AS (SELECT $1::jsonb AS j),
e AS (SELECT * FROM experiments WHERE id = (SELECT j->>'exp_id' FROM j)),
s AS (SELECT coalesce(max(value) FILTER (WHERE key = 'max_rounds'), '3')::int AS max_rounds FROM settings),
l AS (SELECT x FROM j, jsonb_array_elements(coalesce(j->'out'->'lessons', '[]'::jsonb)) x),
c AS (INSERT INTO costs (exp_id, source, usd, detail)
      SELECT j->>'exp_id', {COST_SOURCE.format("j")}, coalesce((j->>'cost')::numeric, 0), 'reflector round ' || (SELECT round FROM e) FROM j RETURNING 1),
r AS (UPDATE lessons SET weight = weight + 1, last_seen = now()
      WHERE track = (SELECT track FROM e) AND id IN (SELECT (x->>'reinforces_id')::bigint FROM l WHERE jsonb_typeof(x->'reinforces_id') = 'number')
      RETURNING 1),
nl AS (INSERT INTO lessons (track, kind, lesson, source_exp)
       SELECT (SELECT track FROM e), x->>'kind', x->>'lesson', (SELECT id FROM e) FROM l
       WHERE jsonb_typeof(x->'reinforces_id') IS DISTINCT FROM 'number' AND length(coalesce(x->>'lesson', '')) > 10
       UNION ALL
       SELECT (SELECT track FROM e), 'avoid', 'Не предлагать: ' || (a->>'pattern') || coalesce(' — пока не изменится: ' || (a->>'until_new_evidence'), ''), (SELECT id FROM e)
       FROM j, jsonb_array_elements(coalesce(j->'out'->'avoid', '[]'::jsonb)) a WHERE length(coalesce(a->>'pattern', '')) > 3
       RETURNING 1),
d AS (UPDATE lessons SET weight = weight - 1, active = weight > 1
      WHERE track = (SELECT track FROM e) AND id IN (SELECT jsonb_array_elements_text(coalesce(j->'out'->'contradicted_ids', '[]'::jsonb))::bigint FROM j)
      RETURNING 1),
nx AS (UPDATE experiments SET round = round + 1, stage = 1, status = 'active', briefs = NULL, diligence = NULL, updated_at = now()
       WHERE id = (SELECT id FROM e) AND status = 'blocked' AND round < coalesce((SELECT round_cap FROM e), (SELECT max_rounds FROM s)) RETURNING id),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT id, stage, 'lessons_learned', 'reflector',
              'Раунд ' || round || ': уроков новых ' || (SELECT count(*) FROM nl) || ', подтверждено ' || (SELECT count(*) FROM r) ||
              CASE WHEN EXISTS (SELECT 1 FROM nx) THEN '. Запускаю раунд ' || (round + 1) ELSE '. Раунды исчерпаны' END ||
              coalesce('. ' || (SELECT j->'out'->>'round_summary' FROM j), '') FROM e RETURNING 1)
SELECT (SELECT id FROM e) AS exp_id, (SELECT track FROM e) AS track, (SELECT round FROM e) AS round,
       EXISTS (SELECT 1 FROM nx) AS next_round, (SELECT count(*) FROM nl) AS new_lessons, (SELECT count(*) FROM r) AS reinforced,
       (SELECT count(*) FROM lessons WHERE active AND track = (SELECT track FROM e)) AS lessons_total"""
LEARN_PREP_JS = """const run = $('Agent: reflector').first().json || {};
const out = $input.first().json || {};
return [{ json: { exp_id: $('Round and memory').first().json.exp_id, billing: run.billing, cost: run.cost_usd || 0,
  out: Array.isArray(out.lessons) ? out : {} } }];"""
DISC_WF = {t: wf_id(cfg["disc_name"]) for t, cfg in TRACKS.items()}
LEARN_DONE_JS = ESC_JS + """const r = $input.first().json;
return [{ json: { text: `🧪 <b>${esc(r.exp_id)}</b>: за ${r.round} раунд(а) ни одна идея не набрала проходной балл, поэтому ничего не присылаю. ` +
  `Ферма записала уроков: ${r.lessons_total}. Ещё раунды — командой retry в пульте.` } }];"""
c, n = {}, []
n += [
    sticky("## 93 · Learn and retry\nВызывается, когда раунд не дал ничего достойного (discovery без кандидатов или due diligence без оценок ≥ порога).\n\n1. Агент **reflector** читает меморандумы и отказы валидатора → `lessons.json`.\n2. Уроки пишутся в `lessons` (повтор → вес +1, опровергнут → вес −1).\n3. Если раундов меньше `max_rounds` — эксперимент снова на этапе 1, discovery стартует с памятью.\n4. Иначе — одна короткая строка владельцу, без отчётов.", [-80, -420], 560, 320),
    sub_trigger([-240, 0]),
    sql("Round and memory", LEARN_LOAD_SQL, "={{ [$json.exp_id] }}", [0, 0]),
    node("Agent: reflector", "n8n-nodes-base.httpRequest", 4.2,
         {"method": "POST", "url": f"{RUNNER_URL}/run/reflector", "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
          "sendBody": True, "specifyBody": "json",
          "jsonBody": "={\"exp_id\": \"{{ $json.exp_id }}\", \"stage\": 0, \"max_turns\": 40, \"budget_usd\": 1.5, \"timeout_s\": 1800, \"queue_timeout_s\": 10800, \"use_api\": {{ $json.use_api }}, \"memory\": {{ JSON.stringify($json.memory) }}, \"input\": {\"note\": \"Distil lessons from this round; write lessons.json\"}}",
          "options": {"timeout": 10800000}}, [240, 0], RUNNER, extra={"onError": "continueRegularOutput"}),
    node("Read lessons.json", "n8n-nodes-base.httpRequest", 4.2,
         {"method": "GET", "url": f"={RUNNER_URL}/files/{{{{ $('Round and memory').first().json.exp_id }}}}/lessons.json",
          "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
          "options": {"timeout": 60000, "response": {"response": {"responseFormat": "json"}}}}, [480, 0], RUNNER,
         extra={"onError": "continueRegularOutput"}),
    code("Prepare", LEARN_PREP_JS, [720, 0]),
    sql("Save lessons, next round", LEARN_SAVE_SQL, "={{ [JSON.stringify($json)] }}", [960, 0]),
    if_true("Another round?", "={{ $json.next_round }}", [1200, 0]),
    code("Discovery workflow", f"const map = {json.dumps(DISC_WF)};\nreturn [{{ json: {{ exp_id: $json.exp_id, workflow_id: map[$json.track] }} }}];", [1440, -100]),
    call("Start discovery", "={{ $json.workflow_id }}", [1680, -100], wait=False),
    code("Nothing this time", LEARN_DONE_JS, [1440, 100]),
    telegram("Tell owner (one line)", "={{ $json.text }}", [1680, 100]),
]
for a, b in [("Called by another workflow", "Round and memory"), ("Round and memory", "Agent: reflector"), ("Agent: reflector", "Read lessons.json"),
             ("Read lessons.json", "Prepare"), ("Prepare", "Save lessons, next round"), ("Save lessons, next round", "Another round?"),
             ("Discovery workflow", "Start discovery"), ("Nothing this time", "Tell owner (one line)")]:
    link(c, a, b)
link(c, "Another round?", "Discovery workflow", 0)
link(c, "Another round?", "Nothing this time", 1)
LEARN = upsert("93 · Learn and retry", n, c, ERR, executionTimeout=12000)

for track, cfg in TRACKS.items():
    wf_id(cfg["dd_name"], cfg["dd_legacy"])
    # Publish order matters in n8n 2.x: the sub-workflow (02) must be published before 01 references it.
    STAGE_WF[f"{track}:2"] = build_diligence(track, cfg)
    STAGE_WF[f"{track}:1"] = build_discovery(track, cfg, STAGE_WF[f"{track}:2"])


# ---------- startup 03-05: smoke test (pre-registration → landing → traffic), each step behind an owner gate ----------
TEST_CTX_SQL = f"""SELECT e.id AS exp_id, e.chosen_brief AS slug, e.prereg, e.landing_url, e.title,
  (SELECT value FROM settings WHERE key = 'budget_test_usd')::numeric AS budget_cap, {MEMORY_SQL} AS memory, {USE_API_SQL} AS use_api
FROM experiments e WHERE e.id = $1"""


def runner_post(name, path_expr, body_expr, pos, timeout=600000, extra=None):
    params = {"method": "POST", "url": path_expr, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
              "options": {"timeout": timeout}}
    if body_expr:
        params.update({"sendBody": True, "specifyBody": "json", "jsonBody": body_expr})
    return node(name, "n8n-nodes-base.httpRequest", 4.2, params, pos, RUNNER, extra=extra)


def agent_body(role, stage, note, extra_fields=""):
    return ("={{ JSON.stringify({ exp_id: $('Load context').first().json.exp_id, slug: $('Load context').first().json.slug, stage: " + str(stage)
            + ", max_turns: 60, budget_usd: 3, timeout_s: 2400, queue_timeout_s: 10800, use_api: $('Load context').first().json.use_api"
            + ", memory: $('Load context').first().json.memory" + extra_fields + ", input: { note: " + json.dumps(note) + " } }) }}")


def failure_branch(n, c, num, title, sources, pos_y=260):
    js = f"""const exp = $('Expect this stage').first().json.exp_id;
const r = $input.first().json || {{}};
const failed = (r.checks || []).filter(x => !x.passed).map(x => '✗ ' + x.detail).join('\\n');
const why = failed || r.error || r.result || 'нет ответа от агента';
return [{{ json: {{ exp_id: exp, stage: {num}, kind: 'stage_failed', actor: 'n8n', message: '⛔ {title}: ' + String(why).slice(0, 700), notify: true }} }}];"""
    n.append(code("Stage failed", js, [1200, pos_y]))
    for src, out in sources:
        link(c, src, "Stage failed", out)
    n.append(sql("Mark blocked", RELEASE_SQL, "={{ [$json.exp_id, 'blocked'] }}", [1440, pos_y], extra={"alwaysOutputData": True}))
    link(c, "Stage failed", "Mark blocked")
    n.append(code("Pass failure on", "return [{ json: $('Stage failed').first().json }];", [1680, pos_y]))
    link(c, "Mark blocked", "Pass failure on")
    n.append(call("Log failure", LOG, [1920, pos_y]))
    link(c, "Pass failure on", "Log failure")


def gate_sql(gate, stage, choices, set_sql):
    return f"""WITH u AS (UPDATE experiments SET {set_sql}, status = 'waiting_owner', updated_at = now() WHERE id = $1 AND status = 'running' RETURNING id),
g AS (INSERT INTO gate_tokens (exp_id, gate, stage, choices) SELECT id, '{gate}', {stage}, ARRAY{choices!r}::text[] FROM u RETURNING token),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message) SELECT id, {stage}, 'waiting_owner', 'n8n', 'Ждёт решения владельца: {gate}' FROM u RETURNING 1)
SELECT (SELECT token FROM g) AS token"""


def build_prereg():
    c, n = {}, []
    stage_head(n, c, 3, "## 03 · Pre-registration\nАгент пишет условия смоук-теста до любых трат: предложение и цена, канал, бюджет, n посетителей, пороги **GO / KILL** и раннюю остановку.\n\n**Guardrails (код):** бюджет ≤ `budget_test_usd` · цена как в меморандуме · порог GO не ниже конверсии из расчёта CAC · n ≥ 100 · 3–21 день.\n\n**Твой шаг:** PDF «Условия теста» → одноразовая ссылка «Утверждаю». После «да» условия фиксируются хэшем.")
    n.append(sql("Load context", TEST_CTX_SQL, "={{ [$('Expect this stage').first().json.exp_id] }}", [720, -120]))
    link(c, "All checks passed?", "Load context", 0)
    n.append(runner_post("Agent: preregistration", f"{RUNNER_URL}/run/preregistration",
                         agent_body("preregistration", 3, "Write prereg.json for the chosen idea", ", input_budget_cap_usd: $('Load context').first().json.budget_cap"),
                         [960, -120], 10800000, extra={"onError": "continueErrorOutput"}))
    link(c, "Load context", "Agent: preregistration")
    n.append(if_true("Agent succeeded?", "={{ $json.ok === true }}", [1200, -120]))
    link(c, "Agent: preregistration", "Agent succeeded?", 0)
    n.append(runner_post("Validate pre-registration", f"={RUNNER_URL}/validate/prereg/{{{{ $('Load context').first().json.exp_id }}}}",
                         "={{ JSON.stringify({ budget_cap_usd: $('Load context').first().json.budget_cap }) }}", [1440, -200]))
    link(c, "Agent succeeded?", "Validate pre-registration", 0)
    n.append(if_true("Checks passed?", "={{ $json.passed === true }}", [1680, -200]))
    link(c, "Validate pre-registration", "Checks passed?")
    n.append(sql("Save plan, open gate", gate_sql("G-prereg", 3, ["approve"], "prereg = $2::jsonb, prereg_hash = $3"),
                 "={{ [$('Load context').first().json.exp_id, JSON.stringify($json.prereg), $json.hash] }}", [1920, -280]))
    link(c, "Checks passed?", "Save plan, open gate", 0)
    n.append(runner_post("Render test-plan PDF", f"={RUNNER_URL}/render/prereg/{{{{ $('Load context').first().json.exp_id }}}}", None, [2160, -280], 300000))
    link(c, "Save plan, open gate", "Render test-plan PDF")
    n.append(node("Download PDF", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "GET", "url": f"={RUNNER_URL}/files/{{{{ $('Load context').first().json.exp_id }}}}/test/test_plan.pdf",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "options": {"timeout": 120000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}}, [2400, -280], RUNNER))
    link(c, "Render test-plan PDF", "Download PDF")
    n.append(node("Send PDF", "n8n-nodes-base.telegram", 1.2,
                  {"operation": "sendDocument", "chatId": CHAT, "binaryData": True, "binaryPropertyName": "data",
                   "additionalFields": {"caption": "={{ '📋 ' + $('Load context').first().json.exp_id + ' · условия смоук-теста' }}",
                                        "fileName": "={{ $('Load context').first().json.exp_id + '-test-plan.pdf' }}"}},
                  [2640, -280], TG, extra={"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}))
    link(c, "Download PDF", "Send PDF")
    msg = ESC_JS + f"""const x = $('Load context').first().json, p = $('Validate pre-registration').first().json.prereg || {{}};
const t = $('Save plan, open gate').first().json.token;
const pct = v => (Number(v) * 100).toFixed(1) + '%';
const th = p.thresholds || {{}};
return [{{ json: {{ text: `📋 <b>${{esc(x.exp_id)}}: условия смоук-теста</b> (PDF выше)\\n${{esc(x.title)}}\\n\\n` +
  `Бюджет $${{p.budget_usd}} (≤ $${{p.daily_cap_usd}}/день) · ${{p.duration_days}} дн. · цель ${{p.target_visitors}} посетителей · канал ${{esc(p.channel)}}\\n` +
  `GO: заявки ≥ ${{pct((th.go || {{}}).signup_rate)}} · KILL: ≤ ${{pct((th.kill || {{}}).signup_rate)}}\\n\\n` +
  `<a href="{BASE}/farm-gate?g=${{t}}&c=approve">Утверждаю условия</a> — одноразовая ссылка, 72 ч. Не согласен — просто не нажимай и напиши, что поменять.` }} }}];"""
    n.append(code("Compose approval", msg, [2880, -280]))
    link(c, "Send PDF", "Compose approval")
    n.append(telegram("Ask owner", "={{ $json.text }}", [3120, -280]))
    link(c, "Compose approval", "Ask owner")
    failure_branch(n, c, 3, "03 · Pre-registration", [("Agent: preregistration", 1), ("Agent succeeded?", 1), ("Checks passed?", 1)])
    blocked_branch(n, c, 3, "03 · Pre-registration", pos_y=460)
    return upsert("03 · Pre-registration", n, c, ERR, executionTimeout=12000)


def build_landing():
    c, n = {}, []
    stage_head(n, c, 4, "## 04 · Landing\nАгент пишет статический лендинг (HTML/CSS) по утверждённым условиям. Счётчик визитов, кликов по цене и заявок вставляет **Worker фермы**, не агент.\n\n**Guardrails (код):** index/privacy/terms · без скриптов и внешних ресурсов · цена как в условиях · кнопки цены и форма · честно «продукт в разработке, оплата не берётся» · без выдуманных отзывов и цифр. Не прошёл — одна попытка исправить по списку ошибок.\n\n**Твой шаг:** открыть превью → «Опубликовать».")
    n.append(sql("Load context", TEST_CTX_SQL, "={{ [$('Expect this stage').first().json.exp_id] }}", [720, -120]))
    link(c, "All checks passed?", "Load context", 0)
    qa_body = "={{ JSON.stringify({ prereg: $('Load context').first().json.prereg }) }}"
    n.append(runner_post("Agent: landing", f"{RUNNER_URL}/run/landing",
                         agent_body("landing", 4, "Build the landing in landing/ from prereg.json", ", prereg: $('Load context').first().json.prereg"),
                         [960, -120], 10800000, extra={"onError": "continueErrorOutput"}))
    link(c, "Load context", "Agent: landing")
    n.append(runner_post("QA landing", f"={RUNNER_URL}/qa/landing/{{{{ $('Load context').first().json.exp_id }}}}", qa_body, [1200, -200]))
    link(c, "Agent: landing", "QA landing", 0)
    n.append(if_true("QA passed?", "={{ $json.passed === true }}", [1440, -200]))
    link(c, "QA landing", "QA passed?")
    fix_note = "={{ JSON.stringify({ exp_id: $('Load context').first().json.exp_id, slug: $('Load context').first().json.slug, stage: 4, max_turns: 30, timeout_s: 1800, queue_timeout_s: 10800, use_api: $('Load context').first().json.use_api, prereg: $('Load context').first().json.prereg, input: { note: 'The farm QA rejected landing/. Fix exactly these problems, keep everything else: ' + ($('QA landing').first().json.checks || []).filter(x => !x.passed).map(x => x.detail).join('; ') } }) }}"
    n.append(runner_post("Agent: fix landing", f"{RUNNER_URL}/run/landing", fix_note, [1680, -80], 10800000, extra={"onError": "continueErrorOutput"}))
    link(c, "QA passed?", "Agent: fix landing", 1)
    n.append(runner_post("QA again", f"={RUNNER_URL}/qa/landing/{{{{ $('Load context').first().json.exp_id }}}}", qa_body, [1920, -80]))
    link(c, "Agent: fix landing", "QA again", 0)
    n.append(if_true("Fixed?", "={{ $json.passed === true }}", [2160, -80]))
    link(c, "QA again", "Fixed?")
    n.append(runner_post("Publish preview", f"={RUNNER_URL}/publish/landing/{{{{ $('Load context').first().json.exp_id }}}}", '={"mode": "preview"}', [2400, -280]))
    link(c, "QA passed?", "Publish preview", 0)
    link(c, "Fixed?", "Publish preview", 0)
    n.append(sql("Save, open gate", gate_sql("G-publish", 4, ["approve"], "landing_url = $2"),
                 "={{ [$('Load context').first().json.exp_id, $json.url] }}", [2640, -280]))
    link(c, "Publish preview", "Save, open gate")
    msg = ESC_JS + f"""const x = $('Load context').first().json, pub = $('Publish preview').first().json;
const t = $('Save, open gate').first().json.token;
return [{{ json: {{ text: `🖥 <b>${{esc(x.exp_id)}}: лендинг готов</b> — проверка кодом пройдена.\\n${{esc(x.title)}}\\n\\n` +
  `<a href="${{pub.preview_url}}">Открыть превью</a> (видно только по этой ссылке, визиты не считаются)\\n\\n` +
  `<a href="{BASE}/farm-gate?g=${{t}}&c=approve">Опубликовать</a> — после этого агент готовит кампанию. Не нравится — напиши, что поменять.` }} }}];"""
    n.append(code("Compose approval", msg, [2880, -280]))
    link(c, "Save, open gate", "Compose approval")
    n.append(telegram("Ask owner", "={{ $json.text }}", [3120, -280]))
    link(c, "Compose approval", "Ask owner")
    failure_branch(n, c, 4, "04 · Landing", [("Agent: landing", 1), ("Agent: fix landing", 1), ("Fixed?", 1)], pos_y=160)
    blocked_branch(n, c, 4, "04 · Landing", pos_y=460)
    return upsert("04 · Landing", n, c, ERR, executionTimeout=12000)


def build_traffic():
    c, n = {}, []
    stage_head(n, c, 5, "## 05 · Traffic\nЛендинг публикуется → агент готовит кампанию: объявления или письма, ключи/аудитории, лимиты, ссылки с UTM, пошаговая инструкция.\n\n**Guardrails (код):** канал и бюджет как в условиях · дневной лимит · все ссылки с utm_campaign=EXP · лимиты длины объявлений · для писем — отписка, адрес, вне ЕС.\n\n**Твой шаг:** запустить кампанию по инструкции → «Я запустил». Дальше метрики собирает `05m`.")
    n.append(sql("Load context", TEST_CTX_SQL, "={{ [$('Expect this stage').first().json.exp_id] }}", [720, -120]))
    link(c, "All checks passed?", "Load context", 0)
    n.append(runner_post("Publish live", f"={RUNNER_URL}/publish/landing/{{{{ $('Load context').first().json.exp_id }}}}", '={"mode": "live"}', [960, -120], extra={"onError": "continueErrorOutput"}))
    link(c, "Load context", "Publish live")
    n.append(runner_post("Agent: traffic", f"{RUNNER_URL}/run/traffic",
                         agent_body("traffic", 5, "Write campaign.json for the owner", ", prereg: $('Load context').first().json.prereg, landing_url: $('Publish live').first().json.url"),
                         [1200, -120], 10800000, extra={"onError": "continueErrorOutput"}))
    link(c, "Publish live", "Agent: traffic", 0)
    n.append(runner_post("Validate campaign", f"={RUNNER_URL}/validate/campaign/{{{{ $('Load context').first().json.exp_id }}}}",
                         "={{ JSON.stringify({ prereg: $('Load context').first().json.prereg, landing_url: $('Publish live').first().json.url }) }}", [1440, -200]))
    link(c, "Agent: traffic", "Validate campaign", 0)
    n.append(if_true("Checks passed?", "={{ $json.passed === true }}", [1680, -200]))
    link(c, "Validate campaign", "Checks passed?")
    n.append(sql("Save campaign, open gate", gate_sql("G-launch", 5, ["launched"], "campaign = $2::jsonb, landing_url = $3"),
                 "={{ [$('Load context').first().json.exp_id, JSON.stringify($json.campaign), $('Publish live').first().json.url] }}", [1920, -280]))
    link(c, "Checks passed?", "Save campaign, open gate", 0)
    msg = ESC_JS + f"""const x = $('Load context').first().json, cmp = $('Validate campaign').first().json.campaign || {{}};
const t = $('Save campaign, open gate').first().json.token;
const steps = (cmp.owner_steps || []).map(s => esc(s)).join('\\n');
const ads = (cmp.ads || []).slice(0, 1).map(a => '«' + esc((a.headlines || []).slice(0, 3).join(' | ')) + '»').join('');
return [{{ json: {{ text: `🚀 <b>${{esc(x.exp_id)}}: кампания готова</b> · ${{esc(cmp.channel)}} · бюджет $${{cmp.budget_usd}}, не больше $${{cmp.daily_cap_usd}}/день\\n` +
  `Лендинг: ${{esc($('Publish live').first().json.url)}}\\n${{ads ? 'Объявление: ' + ads + '\\n' : ''}}\\n<b>Как запустить:</b>\\n${{steps}}\\n\\n` +
  `Полная спецификация (ключи, тексты, ссылки) — в n8n и в /work/${{esc(x.exp_id)}}/test/campaign.json.\\n` +
  `<a href="{BASE}/farm-gate?g=${{t}}&c=launched">Я запустил кампанию</a> — с этого момента считаем тест. Траты отмечай в пульте: action=cost&source=ads.` }} }}];"""
    n.append(code("Compose launch steps", msg, [2160, -280]))
    link(c, "Save campaign, open gate", "Compose launch steps")
    n.append(telegram("Ask owner", "={{ $json.text }}", [2400, -280]))
    link(c, "Compose launch steps", "Ask owner")
    failure_branch(n, c, 5, "05 · Traffic", [("Publish live", 1), ("Agent: traffic", 1), ("Checks passed?", 1)])
    blocked_branch(n, c, 5, "05 · Traffic", pos_y=460)
    return upsert("05 · Traffic", n, c, ERR, executionTimeout=12000)


METRICS_SQL = """SELECT e.id AS exp_id, e.title, e.prereg, e.test_started_at, e.landing_url,
  EXISTS (SELECT 1 FROM decisions d WHERE d.exp_id = e.id AND d.gate = 'G2' AND d.decision = 'extend') AS extended,
  (SELECT coalesce(sum(usd), 0) FROM costs c WHERE c.exp_id = e.id AND c.source NOT LIKE 'claude_%' AND c.ts >= e.test_started_at) AS spend
FROM experiments e WHERE e.status = 'testing' AND e.test_started_at IS NOT NULL"""
EVAL_JS = """// Decision by the pre-registered rule only (code, no LLM).
return $input.all().map((it, k) => {
  const x = $('Testing experiments').all()[k].json, s = it.json || {};
  const p = x.prereg || {}, th = p.thresholds || {}, early = th.early_kill || {};
  const t = s.total || {}, v = Number(t.visitors || 0), cta = Number(t.cta_visitors || 0), su = Number(t.signups || 0);
  const mult = x.extended ? 1.5 : 1;
  const days = (Date.now() - new Date(x.test_started_at).getTime()) / 86400000;
  const sr = v ? su / v : 0, cr = v ? cta / v : 0;
  let decision = null, reason = '';
  if (v >= Number(early.after_visitors || 1e9) && cr < Number(early.cta_rate_below || 0)) { decision = 'kill'; reason = `ранняя остановка: ${v} посетителей, клики по цене ${(cr * 100).toFixed(1)}% < ${(early.cta_rate_below * 100).toFixed(1)}%`; }
  else if (v >= Number(p.target_visitors || 1e9) * mult || days >= Number(p.duration_days || 1e9) * mult) {
    if (sr >= Number((th.go || {}).signup_rate)) { decision = 'go'; reason = `заявки ${(sr * 100).toFixed(1)}% ≥ порога GO`; }
    else if (sr <= Number((th.kill || {}).signup_rate)) { decision = 'kill'; reason = `заявки ${(sr * 100).toFixed(1)}% ≤ порога KILL`; }
    else { decision = x.extended ? 'kill' : 'extend'; reason = x.extended ? 'после продления всё ещё между порогами' : 'между порогами — правило говорит продлить'; }
    if (v < 30) reason += ` (мало трафика: ${v} посетителей)`;
  }
  return { json: { exp_id: x.exp_id, title: x.title, stats: s, visitors: v, cta, signups: su, signup_rate: sr, cta_rate: cr, days: Math.round(days * 10) / 10,
                   spend: Number(x.spend), decision, reason } };
});"""
METRICS_SAVE_SQL = """WITH j AS (SELECT $1::jsonb AS j),
m AS (INSERT INTO metrics (exp_id, day, visits, cta_visitors, signups, spend_usd)
      SELECT j->>'exp_id', (d->>'day')::date, (d->>'visitors')::int, (d->>'cta_visitors')::int,
             coalesce((SELECT (x->>'signups')::int FROM jsonb_array_elements(j->'stats'->'signups_by_day') x WHERE x->>'day' = d->>'day'), 0), NULL
      FROM j, jsonb_array_elements(coalesce(j->'stats'->'days', '[]'::jsonb)) d
      ON CONFLICT (exp_id, day) DO UPDATE SET visits = EXCLUDED.visits, cta_visitors = EXCLUDED.cta_visitors, signups = EXCLUDED.signups RETURNING 1),
u AS (UPDATE experiments SET stage = 6, status = 'waiting_owner', updated_at = now()
      WHERE id = (SELECT j->>'exp_id' FROM j) AND status = 'testing' AND (SELECT j->>'decision' FROM j) IS NOT NULL RETURNING id),
g AS (INSERT INTO gate_tokens (exp_id, gate, stage, choices)
      SELECT id, 'G2', 6, ARRAY(SELECT DISTINCT unnest(ARRAY[(SELECT j->>'decision' FROM j), 'kill'])) FROM u RETURNING token),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT id, 6, 'test_finished', 'n8n', 'Смоук-тест: ' || (SELECT j->>'decision' FROM j) || ' — ' || (SELECT j->>'reason' FROM j) FROM u RETURNING 1)
SELECT (SELECT token FROM g) AS token, (SELECT count(*) FROM m) AS days_saved"""
METRICS_MSG_JS = ESC_JS + f"""const x = $('Evaluate by the rule').item.json, t = $json.token;
const pct = v => (v * 100).toFixed(1) + '%';
const label = {{ go: '🟢 GO — строим MVP', kill: '🔴 KILL — закрываем', extend: '🟡 EXTEND — продлить тест' }};
const links = [x.decision, 'kill'].filter((v, i, a) => a.indexOf(v) === i)
  .map(c => `<a href="{BASE}/farm-gate?g=${{t}}&c=${{c}}">${{label[c]}}</a>`).join('\\n');
return [{{ json: {{ text: `🧪 <b>${{esc(x.exp_id)}}: смоук-тест завершён</b>\\n${{esc(x.title)}}\\n\\n` +
  `Посетителей ${{x.visitors}} · клики по цене ${{x.cta}} (${{pct(x.cta_rate)}}) · заявок ${{x.signups}} (${{pct(x.signup_rate)}}) · ${{x.days}} дн. · траты $${{x.spend}}\\n` +
  `По правилу: <b>${{x.decision.toUpperCase()}}</b> — ${{esc(x.reason)}}\\n\\n${{links}}` }} }}];"""


def build_metrics():
    c, n = {}, []
    n += [
        sticky("## 05m · Smoke-test metrics\nКаждые 6 ч для экспериментов в статусе `testing`: статистика Worker'а (уникальные посетители без ботов, клики по цене, заявки) → таблица `metrics` → решение **кодом по правилу предрегистрации**: ранняя остановка, GO, KILL или EXTEND (один раз ×1,5).\nРешение → этап 06, тебе — цифры и ссылки GO / KILL.", [-80, -400], 560, 260),
        schedule("Every 6 hours", "23 */6 * * *", [0, 0]),
        sql("Testing experiments", METRICS_SQL, None, [240, 0]),
        node("Landing stats", "n8n-nodes-base.httpRequest", 4.2,
             {"method": "GET", "url": f"={LANDING_URL}/stats?exp={{{{ $json.exp_id }}}}", "authentication": "genericCredentialType",
              "genericAuthType": "httpHeaderAuth", "options": {"timeout": 60000}}, [480, 0], LANDING),
        code("Evaluate by the rule", EVAL_JS, [720, 0]),
        sql("Save metrics, decide", METRICS_SAVE_SQL, "={{ [JSON.stringify($json)] }}", [960, 0]),
        if_true("Decision made?", "={{ !!$json.token }}", [1200, 0]),
        code("Compose result", METRICS_MSG_JS, [1440, -80]),
        telegram("Tell owner", "={{ $json.text }}", [1680, -80]),
    ]
    for a, b in [("Every 6 hours", "Testing experiments"), ("Testing experiments", "Landing stats"), ("Landing stats", "Evaluate by the rule"),
                 ("Evaluate by the rule", "Save metrics, decide"), ("Save metrics, decide", "Decision made?"), ("Compose result", "Tell owner")]:
        link(c, a, b)
    link(c, "Decision made?", "Compose result", 0)
    return upsert("05m · Smoke-test metrics", n, c, ERR)


STAGE_WF["startup:3"] = build_prereg()
STAGE_WF["startup:4"] = build_landing()
STAGE_WF["startup:5"] = build_traffic()
METRICS = build_metrics()

# ---------- stage skeletons 03–08 for both tracks ----------
SKELETONS = {
    "startup": [
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
  'month_spend', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_%'),
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
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_%'),
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
       e.status, e.stage AS exp_stage, e.briefs, e.title, e.landing_url, e.prereg, e.campaign,
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
const p = r.prereg || {{}}, cmp = r.campaign || {{}};
const what = {{
  'G1': ['Выбор идеи для смоук-теста', `<p><b>${{esc(b.title)}}</b></p><p class="muted">канал ${{esc(b.channel)}} · цена ${{esc(b.price)}}</p>`, 'Подтвердить выбор', 'Агент напишет условия теста (без трат).'],
  'G-prereg': ['Условия смоук-теста', `<p><b>${{esc(r.title)}}</b></p><p class="muted">бюджет $${{esc(p.budget_usd)}} · ${{esc(p.duration_days)}} дн. · ${{esc(p.channel)}}</p>`, 'Утверждаю условия', 'Условия фиксируются, агент делает лендинг.'],
  'G-publish': ['Публикация лендинга', `<p><b>${{esc(r.title)}}</b></p><p class="muted">${{esc(r.landing_url)}}</p>`, 'Опубликовать', 'Лендинг откроется для всех, агент подготовит кампанию.'],
  'G-launch': ['Запуск кампании', `<p><b>${{esc(r.title)}}</b></p><p class="muted">${{esc(cmp.channel)}} · бюджет $${{esc(cmp.budget_usd)}}</p>`, 'Я запустил кампанию', 'С этого момента считаем тест.'],
  'G2': ['Решение по смоук-тесту', `<p><b>${{esc(r.title)}}</b></p><p>Выбор: <b>${{esc(q.c).toUpperCase()}}</b></p>`, 'Подтвердить решение', 'GO — дальше MVP, KILL — закрываем, EXTEND — тест продлевается.'],
}}[r.gate] || ['Решение', '', 'Подтвердить', ''];
const body = `<h1>${{esc(r.exp_id)}} · ${{esc(r.gate)}}</h1><div class="card"><p class="muted">${{what[0]}}</p>${{what[1]}}
<form method="post" action="{BASE}/farm-gate"><input type="hidden" name="g" value="${{esc(r.token)}}"><input type="hidden" name="c" value="${{esc(q.c)}}"><button type="submit">${{what[2]}}</button></form></div>
<p class="muted">Ссылка одноразовая. ${{what[3]}}</p>`;
return [{{ json: {{ html: page(what[0], body) }} }}];"""
GATE_APPLY_SQL = """WITH t AS (
  UPDATE gate_tokens g SET used_at = now(), choice = $2
  WHERE g.token = $1 AND g.used_at IS NULL AND g.expires_at > now() AND $2 = ANY (g.choices)
    AND EXISTS (SELECT 1 FROM experiments e WHERE e.id = g.exp_id AND e.status = 'waiting_owner' AND e.stage = g.stage)
  RETURNING g.exp_id, g.gate, g.stage),
u AS (
  UPDATE experiments e SET
         stage = CASE WHEN t.gate = 'G-launch' OR (t.gate = 'G2' AND $2 = 'kill') THEN e.stage WHEN t.gate = 'G2' AND $2 = 'extend' THEN 5 ELSE least(e.stage + 1, 8) END,
         status = CASE WHEN t.gate = 'G-launch' OR (t.gate = 'G2' AND $2 = 'extend') THEN 'testing' WHEN t.gate = 'G2' AND $2 = 'kill' THEN 'killed' ELSE 'active' END,
         test_started_at = CASE WHEN t.gate = 'G-launch' THEN now() ELSE e.test_started_at END,
         chosen_brief = CASE WHEN t.gate = 'G1' THEN $2 ELSE e.chosen_brief END, updated_at = now()
  FROM t WHERE e.id = t.exp_id RETURNING e.id, e.stage, e.status, e.track, e.chosen_brief, e.prereg_hash),
d AS (INSERT INTO decisions (exp_id, gate, decision, decided_by, artifact_hash, note)
      SELECT t.exp_id, t.gate, CASE WHEN $2 IN ('go', 'kill', 'extend') THEN $2 ELSE 'approve' END, 'owner',
             CASE WHEN t.gate = 'G-prereg' THEN (SELECT prereg_hash FROM u) END, $2 FROM t RETURNING 1),
h AS (INSERT INTO idea_history (exp_id, track, round, slug, title, outcome)
      SELECT e.id, e.track, e.round, CASE WHEN t.gate = 'G1' THEN $2 ELSE e.chosen_brief END, e.title,
             CASE WHEN t.gate = 'G1' THEN 'chosen' WHEN $2 = 'go' THEN 'test_go' ELSE 'test_kill' END
      FROM t JOIN experiments e ON e.id = t.exp_id WHERE t.gate = 'G1' OR (t.gate = 'G2' AND $2 IN ('go', 'kill')) RETURNING 1),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message) SELECT exp_id, stage, 'owner_decision', 'owner', gate || ': ' || $2 FROM t RETURNING 1)
SELECT (SELECT count(*) FROM u) AS applied, (SELECT id FROM u) AS exp_id, (SELECT stage FROM u) AS stage,
       (SELECT status FROM u) AS status, (SELECT track FROM u) AS track"""
GATE_RESULT_JS = ESC_JS + f"""const r = $input.first().json || {{}};
const ok = Number(r.applied) > 0;
const title = ok ? 'Принято' : 'Не принято';
const body = ok ? `<h1>Принято</h1><p>${{esc(r.exp_id)}}: этап ${{r.stage}}, статус ${{esc(r.status)}}.</p>` : '<h1>Не принято</h1><p>Ссылка уже использована, устарела, или эксперимент сейчас не ждёт этого решения.</p>';
return [{{ json: {{ ok, exp_id: r.exp_id, stage: r.stage, status: r.status, track: r.track, html: `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${{title}}</title><style>{PAGE_CSS}</style></head><body>${{body}}</body></html>` }} }}];"""
c = {}
n = [
    sticky("## 95 · Гейты владельца\nОдноразовые ссылки из Telegram (без мастер-токена):\n1. **GET** — страница подтверждения, ничего не меняет (безопасно для предпросмотров).\n2. **POST** (кнопка) — решение: ссылка гаснет, эксперимент переходит дальше, следующий этап **стартует сразу**. Повторный клик ничего не делает.\nГейты: G1 идея (по PDF) → G-prereg условия теста (PDF) → G-publish лендинг → G-launch кампания запущена (статус testing) → G2 GO / KILL / EXTEND по правилу.\nСрок ссылки 72 ч. Таблица `gate_tokens`.", [-80, -380], 520, 300),
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
    if_true("Next stage to run?", "={{ $('Render result').first().json.status === 'active' }}", [1440, 300]),
    code("Pick stage workflow", "const r = $('Render result').first().json;\nconst map = " + json.dumps(STAGE_WF) + ";\nreturn [{ json: { exp_id: r.exp_id, workflow_id: map[(r.track || 'startup') + ':' + r.stage] } }];", [1680, 220]),
    call("Start next stage", "={{ $json.workflow_id }}", [1920, 220], wait=False),
]
link(c, "Gate link", "Look up gate")
link(c, "Look up gate", "Render confirm page")
link(c, "Render confirm page", "Show page")
link(c, "Gate confirm", "Apply decision")
link(c, "Apply decision", "Render result")
link(c, "Render result", "Show result")
link(c, "Show result", "Accepted?")
link(c, "Accepted?", "Confirm in Telegram", 0)
link(c, "Confirm in Telegram", "Next stage to run?")
link(c, "Next stage to run?", "Pick stage workflow", 0)
link(c, "Pick stage workflow", "Start next stage")
GATES = upsert("95 · Owner gates", n, c, ERR, saveDataSuccessExecution="none")

# ---------- 96 Read-only status API (Hermes) ----------
RO_SQL = """SELECT CASE WHEN $1 <> '' AND $1 = (SELECT value FROM settings WHERE key = 'ro_token') THEN json_build_object(
  'ok', true,
  'experiments', (SELECT json_agg(json_build_object('id', e.id, 'track', e.track, 'title', e.title, 'stage', e.stage, 'stage_name', s.name, 'status', e.status,
                   'chosen_brief', e.chosen_brief, 'briefs', e.briefs, 'diligence', e.diligence, 'budget_usd', e.budget_usd,
                   'spent_usd', (SELECT coalesce(sum(usd), 0) FROM costs c WHERE c.exp_id = e.id AND c.source NOT LIKE 'claude_%'),
                   'agent_equiv_usd', (SELECT coalesce(sum(usd), 0) FROM costs c WHERE c.exp_id = e.id AND c.source LIKE 'claude_subscription%'),
                   'issue_url', e.issue_url, 'updated_at', e.updated_at) ORDER BY e.id)
                  FROM experiments e JOIN stages s ON s.track = e.track AND s.stage = e.stage),
  'stages', (SELECT json_agg(json_build_object('track', track, 'stage', stage, 'name', name, 'gate', gate) ORDER BY track, stage) FROM stages),
  'recent_events', (SELECT json_agg(v ORDER BY v.ts DESC) FROM (SELECT ts, exp_id, stage, kind, message FROM events ORDER BY id DESC LIMIT 30) v),
  'guardrail_failures_24h', (SELECT json_agg(v) FROM (SELECT ts, exp_id, stage, detail FROM guardrail_events WHERE NOT passed AND rule <> 'lock_acquired' AND ts > now() - interval '24 hours' ORDER BY id DESC LIMIT 20) v),
  'kill_switch', (SELECT value FROM settings WHERE key = 'kill_switch'),
  'month_spend_usd', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_%'),
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
if (a === 'retry') {
  if (!q.exp) return [{ json: { ok: false, reply: 'retry требует exp' } }];
  return [{ json: { ok: true, action: a, sql: "WITH s AS (SELECT coalesce(max(value) FILTER (WHERE key = 'max_rounds'), '3')::int AS m FROM settings), u AS (UPDATE experiments SET status = 'blocked', round_cap = round + (SELECT m FROM s), updated_at = now() WHERE id = $1 AND stage <= 2 AND status IN ('blocked', 'active', 'paused') RETURNING id AS exp_id, stage, track, round, round_cap), ev AS (INSERT INTO events (exp_id, kind, actor, message) SELECT exp_id, 'owner_decision', 'owner', 'Пульт: retry — рефлексия и новые раунды до ' || round_cap FROM u RETURNING 1) SELECT * FROM u", params: [q.exp] } }];
}
if (a === 'digest') return [{ json: { ok: true, action: a } }];
return [{ json: { ok: false, reply: 'Неизвестное действие. Есть: status, kill_on, kill_off, decide (kill/pause/resume), digest, run, retry, cost, advance' } }];"""
c = {}
n = [
    sticky("## 99 · Пульт (администрирование)\n`https://n8n.home.kalik8s.ru/webhook/farm?t=<токен>&action=…`\n- `status` · `kill_on` / `kill_off` · `digest`\n- `run&exp=EXP-001` — запустить этап, ответ сразу («запущено»)\n- `retry&exp=…` — рефлексия (уроки) и новые раунды поиска\n- `decide&exp=…&decision=kill|pause|resume`\n- `cost&exp=…&usd=…&source=…` · `advance&exp=…&to=N`\n**Гейты (выбор брифа и т. п.) — только одноразовыми ссылками (95).** Успешные запуски пульта не сохраняются (токен в URL).", [-80, -400], 560, 300),
    webhook("Control link", "farm", "GET", [0, 0]),
    sql("Read token", "SELECT value FROM settings WHERE key = 'control_token'", None, [240, 0]),
    code("Check token and plan", PLAN_JS, [480, 0]),
    if_true("Token ok?", "={{ $json.ok }}", [720, 0]),
    code("Reject", "return [{ json: { ok: false, reply: $input.first().json.reply } }];", [960, 200]),
    respond("Respond rejected", "={{ JSON.stringify($json) }}", [1200, 200]),
    if_true("Digest?", "={{ $json.action === 'digest' }}", [960, -80]),
    call("Run digest", DIG, [1200, -220]),
    sql("Apply action", "={{ $json.sql }}", "={{ $json.params }}", [1200, 40], extra={"alwaysOutputData": True}),
    if_true("Run a stage?", "={{ ['run', 'retry'].includes($('Check token and plan').first().json.action) && $input.all().some(i => i.json.exp_id) }}", [1440, 40]),
    respond("Respond started", "={{ JSON.stringify({ ok: true, action: $('Check token and plan').first().json.action, started: $input.all().map(i => i.json) }) }}", [1680, -40]),
    code("Pick stage workflow", f"if ($('Check token and plan').first().json.action === 'retry') return $input.all().map(i => ({{ json: {{ exp_id: i.json.exp_id, workflow_id: '{LEARN}' }} }}));\n" + MAP_JS, [1920, -40]),
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
