#!/usr/bin/env python3
"""Creates or updates the startup farm workflows in n8n through the public API.

Workflows are matched by name, so re-running updates them in place.
Reads N8N_URL, N8N_API_KEY, PG_CRED_ID, TG_CRED_ID from /home/kalikys/prj/farm/.env.
Run: python3 services/farm/n8n/build.py
"""
import json
import os
import urllib.request
import uuid

ENV_FILE = "/home/kalikys/prj/farm/.env"
env = dict(line.strip().split("=", 1) for line in open(ENV_FILE) if "=" in line and not line.startswith("#"))
URL = env["N8N_URL"].rstrip("/") + "/api/v1"
KEY = env["N8N_API_KEY"]
PG = {"postgres": {"id": env["PG_CRED_ID"], "name": "Farm DB (farm)"}}
TG = {"telegramApi": {"id": env["TG_CRED_ID"], "name": "Telegram (Hermes bot, send only)"}}
RUNNER = {"httpHeaderAuth": {"id": env["RUNNER_CRED_ID"], "name": "Agent runner token"}}
PANEL_URL = "https://n8n.home.kalik8s.ru/webhook/farm"
PANEL_TOKEN = env["FARM_CONTROL_TOKEN"]
REAL_MONEY = "source NOT LIKE 'claude_subscription%'"


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


def sticky(name, text, pos, w=360, h=220, color=5):
    return node(name, "n8n-nodes-base.stickyNote", 1, {"content": text, "width": w, "height": h, "color": color}, pos)


def sql(name, query, params_expr, pos):
    p = {"operation": "executeQuery", "query": query, "options": {}}
    if params_expr:
        p["options"]["queryReplacement"] = params_expr
    return node(name, "n8n-nodes-base.postgres", 2.5, p, pos, PG)


def code(name, js, pos, disabled=False):
    return node(name, "n8n-nodes-base.code", 2, {"jsCode": js}, pos, disabled=disabled)


def telegram(name, chat_expr, text_expr, pos):
    return node(name, "n8n-nodes-base.telegram", 1.2,
                {"chatId": chat_expr, "text": text_expr,
                 "additionalFields": {"parse_mode": "HTML", "appendAttribution": False}}, pos, TG)


def sub_trigger(pos):
    return node("Called by another workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1,
                {"inputSource": "passthrough"}, pos)


def call(name, wf_id_expr, pos):
    return node(name, "n8n-nodes-base.executeWorkflow", 1.2,
                {"source": "database", "workflowId": {"__rl": True, "value": wf_id_expr, "mode": "id"},
                 "options": {"waitForSubWorkflow": True}}, pos)


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


def link(conns, a, b, out=0):
    conns.setdefault(a, {"main": []})
    while len(conns[a]["main"]) <= out:
        conns[a]["main"].append([])
    conns[a]["main"][out].append({"node": b, "type": "main", "index": 0})


SETTINGS = {"executionOrder": "v1", "saveManualExecutions": True,
            "saveDataSuccessExecution": "all", "saveDataErrorExecution": "all", "timezone": "Asia/Tbilisi"}

existing = {w["name"]: w["id"] for w in api("GET", "/workflows?limit=250")["data"]}


def upsert(name, nodes, conns, error_wf=None):
    settings = dict(SETTINGS)
    if error_wf:
        settings["errorWorkflow"] = error_wf
    body = {"name": name, "nodes": nodes, "connections": conns, "settings": settings}
    if name in existing:
        api("PUT", f"/workflows/{existing[name]}", body)
        wid = existing[name]
    else:
        wid = api("POST", "/workflows", body)["id"]
        existing[name] = wid
    print(f"{wid}  {name}")
    return wid


CHAT = "(SELECT value FROM settings WHERE key = 'owner_chat_id')"

# ---------- 98 Error handler ----------
c = {}
n = [
    sticky("About", "## 98 · Обработчик ошибок\nЛюбой упавший workflow фермы попадает сюда: событие в журнал + алерт в Telegram.", [-80, -260], 380, 160),
    node("When a farm workflow fails", "n8n-nodes-base.errorTrigger", 1, {}, [0, 0]),
    sql("Log the error", "INSERT INTO events (kind, actor, message, data) SELECT 'workflow_error', 'n8n', $1, $2::jsonb RETURNING " + CHAT + " AS chat_id",
        "={{ ['Workflow failed: ' + $json.workflow.name, JSON.stringify({execution: $json.execution.id, node: $json.execution.lastNodeExecuted, error: ($json.execution.error || {}).message})] }}", [240, 0]),
    telegram("Alert owner", "={{ $json.chat_id }}",
             "=🔴 <b>Ферма: ошибка</b>\nWorkflow: {{ $('When a farm workflow fails').item.json.workflow.name }}\nУзел: {{ $('When a farm workflow fails').item.json.execution.lastNodeExecuted }}\n{{ ($('When a farm workflow fails').item.json.execution.error || {}).message }}", [480, 0]),
]
link(c, "When a farm workflow fails", "Log the error")
link(c, "Log the error", "Alert owner")
ERR = upsert("98 · Error handler", n, c)

# ---------- 97 Log event ----------
c = {}
n = [
    sticky("About", "## 97 · Журнал событий\nВызывается каждым этапом. Пишет событие в таблицу events (только INSERT) и, если notify = true, шлёт сообщение в Telegram.\nВход: exp_id, stage, kind, actor, message, notify.", [-80, -280], 420, 190),
    sub_trigger([0, 0]),
    sql("Insert event",
        "INSERT INTO events (exp_id, stage, kind, actor, message) SELECT j->>'exp_id', (j->>'stage')::int, j->>'kind', coalesce(j->>'actor','n8n'), j->>'message' FROM (SELECT $1::jsonb AS j) t RETURNING id, exp_id, stage, kind, message, " + CHAT + " AS chat_id",
        "={{ [JSON.stringify($json)] }}", [240, 0]),
    if_true("Notify owner?", "={{ $('Called by another workflow').item.json.notify === true }}", [480, 0]),
    telegram("Send to Telegram", "={{ $json.chat_id }}",
             "={{ $json.exp_id ? '<b>' + $json.exp_id + '</b> · этап ' + $json.stage + '\\n' : '' }}{{ $json.message }}", [720, -80]),
]
link(c, "Called by another workflow", "Insert event")
link(c, "Insert event", "Notify owner?")
link(c, "Notify owner?", "Send to Telegram", 0)
LOG = upsert("97 · Log event", n, c, ERR)

# ---------- 90 Guardrail preflight ----------
PREFLIGHT_SQL = """WITH s AS (
  SELECT max(value) FILTER (WHERE key = 'kill_switch') AS ks,
         max(value) FILTER (WHERE key = 'wip_limit')::int AS wip,
         max(value) FILTER (WHERE key = 'budget_month_usd')::numeric AS cap
  FROM settings),
e AS (SELECT * FROM experiments WHERE id = $1),
a AS (SELECT count(*) AS n FROM experiments WHERE status IN ('active', 'waiting_owner')),
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
x AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE exp_id = $1 AND source NOT LIKE 'claude_subscription%'),
checks AS (
  SELECT * FROM (VALUES
    ('kill_switch_off',   (SELECT ks FROM s) = 'off',                                        'Kill switch выключен'),
    ('wip_limit',         (SELECT n FROM a) <= (SELECT wip FROM s),                          'В работе не больше WIP-лимита стартапов'),
    ('month_budget',      (SELECT spent FROM m) < (SELECT cap FROM s),                       'Траты фермы за месяц ниже потолка'),
    ('experiment_budget', (SELECT spent FROM x) < coalesce((SELECT budget_usd FROM e), 0),   'Траты эксперимента ниже его бюджета'),
    ('experiment_status', coalesce((SELECT status FROM e) NOT IN ('killed', 'paused'), false), 'Эксперимент не закрыт и не на паузе'),
    ('stage_order',       coalesce((SELECT stage FROM e) = $2::int, false),                  'Эксперимент действительно на этом этапе')
  ) AS v(rule, passed, detail)),
ins AS (
  INSERT INTO guardrail_events (exp_id, stage, rule, passed, detail)
  SELECT $1, $2::int, rule, passed, detail FROM checks
  RETURNING rule, passed, detail)
SELECT $1 AS exp_id, $2::int AS stage, bool_and(passed) AS ok,
       json_agg(json_build_object('rule', rule, 'passed', passed, 'detail', detail)) AS checks
FROM ins"""
c = {}
n = [
    sticky("About", "## 90 · Guardrail preflight\nЗапускается **перед каждым этапом**. Проверяет кодом, без LLM:\n- kill switch выключен\n- WIP-лимит\n- месячный потолок трат\n- бюджет эксперимента\n- эксперимент не закрыт\n- этап совпадает\nКаждая проверка пишется в guardrail_events (только INSERT).", [-80, -360], 420, 290),
    sub_trigger([0, 0]),
    sql("Run checks", PREFLIGHT_SQL, "={{ [$json.exp_id, $json.stage] }}", [240, 0]),
]
link(c, "Called by another workflow", "Run checks")
PRE = upsert("90 · Guardrail preflight", n, c, ERR)


DISCOVERY_SUMMARY_JS = r"""const run = $('Agent: discovery').first().json;
const val = $input.first().json;
const exp = $('Called by another workflow').first().json.exp_id;
const passed = (val.briefs || []).filter(b => b.passed);
const failed = (val.briefs || []).filter(b => !b.passed);
const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const link = slug => `PANEL?t=TOKEN&action=decide&exp=${exp}&gate=G1&decision=approve&note=${encodeURIComponent(slug)}`;
let text;
if (passed.length) {
  text = `🧭 <b>${exp}: брифы готовы</b>, прошли проверку ${passed.length} из ${(val.briefs||[]).length}.\nВыбери один (G1):\n\n` +
    passed.map((b, i) => `${i+1}. <b>${esc(b.title)}</b>\n   канал ${esc(b.channel)} · CPC ~$${b.cpc} · цена ${esc(b.price)}\n   <a href="${link(b.slug)}">Выбрать</a>`).join('\n\n') +
    (failed.length ? `\n\nОтсеяно проверкой: ${failed.length}` : '');
} else {
  text = `⛔ <b>${exp}: ни один бриф не прошёл проверку</b> (${failed.length}). Этап заблокирован до разбора.\n` + failed.slice(0,3).map(b => `• ${esc(b.title || b.file)}: ${esc((b.failures||[]).join('; '))}`).join('\n');
}
return [{ json: { exp_id: exp, passed: passed.length, cost: run.cost_usd || 0, turns: run.turns, session: run.session_id, text, agent_ok: run.ok, agent_error: run.error || '' } }];""".replace("PANEL", PANEL_URL).replace("TOKEN", PANEL_TOKEN)

DISCOVERY_RECORD_SQL = """WITH j AS (SELECT $1::jsonb AS j),
c AS (INSERT INTO costs (exp_id, source, usd, detail)
      SELECT j->>'exp_id', 'claude_subscription_equiv', coalesce((j->>'cost')::numeric, 0), 'discovery session ' || coalesce(j->>'session','') FROM j RETURNING 1),
u AS (UPDATE experiments SET stage = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 2 ELSE stage END,
                             status = CASE WHEN (SELECT (j->>'passed')::int FROM j) > 0 THEN 'waiting_owner' ELSE 'blocked' END,
                             updated_at = now()
      WHERE id = (SELECT j->>'exp_id' FROM j) RETURNING stage, status),
ev AS (INSERT INTO events (exp_id, stage, kind, actor, message)
       SELECT j->>'exp_id', 1, CASE WHEN (j->>'passed')::int > 0 THEN 'briefs_ready' ELSE 'briefs_rejected' END, 'n8n',
              'Discovery: прошли проверку ' || (j->>'passed') || ' брифов, ходов агента ' || coalesce(j->>'turns','?') FROM j RETURNING 1)
SELECT (SELECT value FROM settings WHERE key = 'owner_chat_id') AS chat_id, (SELECT j->>'text' FROM j) AS text"""


def build_discovery(n, c):
    """Stage 01: agent writes briefs → code validates them in the isolated runner → record → owner chooses (G1)."""
    n.append(node("Agent: discovery", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": "http://172.30.0.10:8080/run/discovery",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "sendBody": True, "specifyBody": "json",
                   "jsonBody": "={\"exp_id\": \"{{ $json.exp_id }}\", \"stage\": 1, \"max_turns\": 120, \"input\": {\"note\": \"Stop when 3 to 5 briefs pass the checklist\"}}",
                   "options": {"timeout": 3600000}}, [720, -100], RUNNER,
                  extra={"retryOnFail": False, "onError": "continueRegularOutput"}))
    link(c, "All checks passed?", "Agent: discovery", 0)
    n.append(node("Validate briefs (code, no LLM)", "n8n-nodes-base.httpRequest", 4.2,
                  {"method": "POST", "url": "=http://172.30.0.10:8080/validate/discovery/{{ $('Called by another workflow').first().json.exp_id }}",
                   "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                   "options": {"timeout": 600000}}, [960, -100], RUNNER))
    link(c, "Agent: discovery", "Validate briefs (code, no LLM)")
    n.append(code("Summarise for owner", DISCOVERY_SUMMARY_JS, [1200, -100]))
    link(c, "Validate briefs (code, no LLM)", "Summarise for owner")
    n.append(sql("Record cost, stage and event", DISCOVERY_RECORD_SQL, "={{ [JSON.stringify($json)] }}", [1440, -100]))
    link(c, "Summarise for owner", "Record cost, stage and event")
    n.append(telegram("Send briefs to owner", "={{ $json.chat_id }}", "={{ $json.text }}", [1680, -100]))
    link(c, "Record cost, stage and event", "Send briefs to owner")
    n.append(code("Blocked report", "const r = $('Guardrail preflight').first().json;\nconst failed = (r.checks || []).filter(c => !c.passed).map(c => '✗ ' + c.detail).join('\\n');\nreturn [{ json: { exp_id: r.exp_id, stage: 1, kind: 'guardrail_blocked', actor: 'n8n', message: '⛔ Этап 01 · Discovery остановлен guardrails. Не выполнены условия:\\n' + failed, notify: true } }];", [720, 140]))
    link(c, "All checks passed?", "Blocked report", 1)
    n.append(call("Log blocked", LOG, [960, 140]))
    link(c, "Blocked report", "Log blocked")

# ---------- stage workflows 01–08 ----------
STAGES = [
    (1, "Discovery", "discovery",
     "Агент: ресёрч источников «где текут деньги» → 3–5 брифов.",
     "Guardrails: схема брифа · ссылки живые · цитата найдена в источнике · лимит $ на сессию.",
     "Твой шаг: нет (дальше G1)."),
    (2, "Brief choice", None,
     "Брифы уходят тебе.",
     "Guardrails: WIP = 1.",
     "Твой шаг: G1 — выбрать бриф (ссылка-кнопка из Telegram)."),
    (3, "Pre-registration", "preregistration",
     "Агент: пороги — канал, бюджет, n = 150, GO / KILL, дата решения.",
     "Guardrails: все поля · бюджет ≤ budget_test_usd · после одобрения хэш, правки запрещены.",
     "Твой шаг: одобрить пороги."),
    (4, "Landing", "landing",
     "Агент: лендинг → превью на Cloudflare Pages.",
     "Guardrails: HTTP 200 · форма пишет в waitlist · аналитика стреляет · Terms и Privacy · цена как в брифе.",
     "Твой шаг: одобрить публикацию."),
    (5, "Traffic and metrics", "traffic",
     "Агент: спецификация кампании, ежедневный сбор метрик в таблицу metrics.",
     "Guardrails: трата ≤ budget_day_usd и ≤ бюджета теста · ранний KILL на 100 визитах.",
     "Твой шаг: одобрить деньги и запустить кампанию."),
    (6, "Decision", None,
     "Решение считается по правилу предрегистрации.",
     "Guardrails: GO / KILL / продление только по правилу; переопределение пишется в decisions.",
     "Твой шаг: G2 — подтвердить."),
    (7, "Build MVP", "builder",
     "Агент: MVP в песочнице (только после GO).",
     "Guardrails: auth и оплату менять нельзя · тесты · сканеры зависимостей и секретов.",
     "Твой шаг: одобрить запуск оплаты."),
    (8, "Active users", "analyst",
     "Агент: регистрации, активация, удержание D1/D7, ошибки, аптайм — ежедневно.",
     "Guardrails: алерт при падении сайта или метрик.",
     "Твой шаг: G3 на 30-й день — продолжать, автопилот или закрыть."),
]
STAGE_WF = {}
for num, title, role, agent_txt, guard_txt, owner_txt in STAGES:
    c = {}
    agent_note = "Агент ещё не подключён: узел выключен, этап проходит как каркас." if role else "Этап без агента."
    n = [
        sticky("About", f"## {num:02d} · {title}\n{agent_txt}\n\n{guard_txt}\n\n{owner_txt}\n\n_{agent_note}_", [-80, -400], 520, 300),
        sub_trigger([0, 0]),
        call("Guardrail preflight", PRE, [240, 0]),
        if_true("All checks passed?", "={{ $json.ok }}", [480, 0]),
    ]
    link(c, "Called by another workflow", "Guardrail preflight")
    link(c, "Guardrail preflight", "All checks passed?")
    prev = "All checks passed?"
    x = 720
    if role == "discovery":
        build_discovery(n, c)
        STAGE_WF[num] = upsert(f"{num:02d} · {title}", n, c, ERR)
        continue
    if role:
        n.append(node(f"Agent: {role}", "n8n-nodes-base.httpRequest", 4.2,
                      {"method": "POST", "url": f"http://agent-runner:8080/run/{role}",
                       "sendBody": True, "specifyBody": "json",
                       "jsonBody": "={{ JSON.stringify({exp_id: $json.exp_id, stage: $json.stage}) }}",
                       "options": {"timeout": 3600000}}, [x, -100], disabled=True))
        link(c, prev, f"Agent: {role}", 0)
        prev, x = f"Agent: {role}", x + 240
        n.append(code("Validate output", "// Stage-specific checks run here once the agent is connected.\nreturn $input.all();", [x, -100], disabled=True))
        link(c, prev, "Validate output")
        prev, x = "Validate output", x + 240
    n.append(code("Report", f"return [{{ json: {{ exp_id: $('Called by another workflow').first().json.exp_id, stage: {num}, kind: 'stage_skeleton_ran', actor: 'n8n', message: 'Этап {num:02d} · {title}: проверки пройдены, каркас отработал' + ({'true' if role else 'false'} ? ' (агент ещё не подключён)' : ''), notify: false }} }}];", [x, -100]))
    if prev == "All checks passed?":
        link(c, prev, "Report", 0)
    else:
        link(c, prev, "Report")
    n.append(call("Log event", LOG, [x + 240, -100]))
    link(c, "Report", "Log event")
    n.append(code("Blocked report", f"const r = $('Guardrail preflight').first().json;\nconst failed = (r.checks || []).filter(c => !c.passed).map(c => '✗ ' + c.detail).join('\\n');\nreturn [{{ json: {{ exp_id: r.exp_id, stage: {num}, kind: 'guardrail_blocked', actor: 'n8n', message: '⛔ Этап {num:02d} · {title} остановлен guardrails. Не выполнены условия:\\n' + failed, notify: true }} }}];", [720, 140]))
    link(c, "All checks passed?", "Blocked report", 1)
    n.append(call("Log blocked", LOG, [960, 140]))
    link(c, "Blocked report", "Log blocked")
    STAGE_WF[num] = upsert(f"{num:02d} · {title}", n, c, ERR)

# ---------- 00 Controller ----------
c = {}
mapping = json.dumps({str(k): v for k, v in STAGE_WF.items()})
n = [
    sticky("About", "## 00 · Controller\nКаждые 15 минут берёт активные эксперименты и запускает workflow их текущего этапа.\n\n**Выключен**, пока не подключён agent-runner: иначе каркас крутился бы вхолостую.", [-80, -300], 420, 220),
    schedule("Every 15 minutes", "*/15 * * * *", [0, 0]),
    sql("Active experiments", "SELECT id AS exp_id, stage FROM experiments WHERE status = 'active' ORDER BY created_at", None, [240, 0]),
    code("Pick stage workflow", f"const map = {mapping};\nreturn $input.all().map(i => ({{ json: {{ ...i.json, workflow_id: map[String(i.json.stage)] }} }}));", [480, 0]),
    call("Run stage", "={{ $json.workflow_id }}", [720, 0]),
]
link(c, "Every 15 minutes", "Active experiments")
link(c, "Active experiments", "Pick stage workflow")
link(c, "Pick stage workflow", "Run stage")
CTRL = upsert("00 · Controller", n, c, ERR)

# ---------- 91 Daily digest ----------
DIGEST_SQL = """SELECT json_build_object(
  'status',      (SELECT json_agg(v ORDER BY v.id) FROM v_status v),
  'events',      (SELECT json_agg(e ORDER BY e.ts) FROM (SELECT ts, exp_id, kind, message FROM events WHERE ts > now() - interval '24 hours') e),
  'guard_fail',  (SELECT count(*) FROM guardrail_events WHERE NOT passed AND ts > now() - interval '24 hours'),
  'month_spend', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
  'agent_equiv', (SELECT coalesce(sum(usd), 0) FROM costs WHERE ts >= date_trunc('month', now()) AND source LIKE 'claude_subscription%'),
  'month_cap',   (SELECT value FROM settings WHERE key = 'budget_month_usd'),
  'kill',        (SELECT value FROM settings WHERE key = 'kill_switch'),
  'chat_id',     (SELECT value FROM settings WHERE key = 'owner_chat_id')) AS d"""
DIGEST_JS = r"""const d = $input.first().json.d;
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const status = (d.status || []).map(s => `• <b>${esc(s.id)}</b> ${esc(s.title)}\n   этап ${s.stage} · ${esc(s.stage_name)} · ${esc(s.status)} · $${Number(s.spent_usd).toFixed(2)} из $${Number(s.budget_usd).toFixed(0)}`).join('\n') || '—';
const events = (d.events || []).slice(-10).map(e => `• ${esc(e.exp_id || 'ферма')}: ${esc(e.message)}`).join('\n') || 'событий нет';
const text = `🌱 <b>Ферма · дайджест</b>\n\n<b>Стартапы</b>\n${status}\n\n<b>За сутки</b>\n${events}\n\nGuardrails сработали: ${d.guard_fail}\nТраты за месяц: $${Number(d.month_spend).toFixed(2)} из $${d.month_cap}\nАгенты (подписка, эквивалент API): $${Number(d.agent_equiv).toFixed(2)}\nKill switch: ${d.kill === 'on' ? '🔴 ВКЛЮЧЁН' : 'выключен'}`;
return [{ json: { chat_id: d.chat_id, text } }];"""
c = {}
n = [
    sticky("About", "## 91 · Дайджест\nКаждый день в 09:00 (Тбилиси): где каждый стартап, что произошло за сутки, сколько потрачено, сработали ли guardrails.\nМожно вызвать из 99 · Control panel (action=digest).", [-80, -300], 420, 200),
    schedule("Every day 09:00", "0 9 * * *", [0, 0]),
    sub_trigger([0, 180]),
    sql("Collect status", DIGEST_SQL, None, [240, 80]),
    code("Format message", DIGEST_JS, [480, 80]),
    telegram("Send digest", "={{ $json.chat_id }}", "={{ $json.text }}", [720, 80]),
]
link(c, "Every day 09:00", "Collect status")
link(c, "Called by another workflow", "Collect status")
link(c, "Collect status", "Format message")
link(c, "Format message", "Send digest")
DIG = upsert("91 · Daily digest", n, c, ERR)

# ---------- 92 Guardrail watchdog ----------
WATCH_SQL = """WITH s AS (
  SELECT max(value) FILTER (WHERE key = 'budget_month_usd')::numeric AS cap FROM settings),
m AS (SELECT coalesce(sum(usd), 0) AS spent FROM costs WHERE ts >= date_trunc('month', now()) AND source NOT LIKE 'claude_subscription%'),
upd AS (
  UPDATE settings SET value = 'on'
  WHERE key = 'kill_switch' AND value = 'off' AND (SELECT spent FROM m) >= (SELECT cap FROM s)
  RETURNING 1),
ev AS (
  INSERT INTO events (kind, actor, message)
  SELECT 'kill_switch', 'watchdog', 'Месячный потолок трат достигнут — kill switch включён автоматически' FROM upd
  RETURNING 1)
SELECT json_build_object(
  'budget_tripped', EXISTS (SELECT 1 FROM upd),
  'spent', (SELECT spent FROM m), 'cap', (SELECT cap FROM s),
  'stale', (SELECT json_agg(json_build_object('id', id, 'stage', stage, 'since', updated_at)) FROM experiments WHERE status = 'waiting_owner' AND updated_at < now() - interval '48 hours'),
  'guard_fail', (SELECT json_agg(json_build_object('exp', exp_id, 'stage', stage, 'rule', rule, 'detail', detail)) FROM guardrail_events WHERE NOT passed AND ts > now() - interval '1 hour'),
  'chat_id', (SELECT value FROM settings WHERE key = 'owner_chat_id')) AS d"""
WATCH_JS = r"""const d = $input.first().json.d;
const lines = [];
if (d.budget_tripped) lines.push(`🔴 Потолок трат за месяц достигнут ($${d.spent} из $${d.cap}). Kill switch включён, все этапы остановлены.`);
for (const s of d.stale || []) lines.push(`⏳ ${s.id}: ждёт твоего решения на этапе ${s.stage} больше 48 часов.`);
for (const g of d.guard_fail || []) lines.push(`⛔ ${g.exp || 'ферма'} · этап ${g.stage}: ${g.detail}`);
if (!lines.length) return [];
return [{ json: { chat_id: d.chat_id, text: '🛡 <b>Ферма · guardrails</b>\n\n' + lines.join('\n') } }];"""
c = {}
n = [
    sticky("About", "## 92 · Сторож guardrails\nКаждый час:\n- траты за месяц ≥ потолка → **сам включает kill switch**\n- решение ждёт тебя > 48 ч → напоминание\n- проваленные проверки за час → алерт\nМолчит, если всё в порядке.", [-80, -320], 420, 230),
    schedule("Every hour", "5 * * * *", [0, 0]),
    sql("Check budgets and stale gates", WATCH_SQL, None, [240, 0]),
    code("Anything to report?", WATCH_JS, [480, 0]),
    telegram("Alert owner", "={{ $json.chat_id }}", "={{ $json.text }}", [720, 0]),
]
link(c, "Every hour", "Check budgets and stale gates")
link(c, "Check budgets and stale gates", "Anything to report?")
link(c, "Anything to report?", "Alert owner")
WATCH = upsert("92 · Guardrail watchdog", n, c, ERR)

# ---------- 99 Control panel ----------
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
  const allowed = ['approve', 'reject', 'go', 'kill', 'extend', 'pause', 'resume'];
  if (!q.exp || !q.gate || !allowed.includes(q.decision)) return [{ json: { ok: false, reply: 'decide требует exp, gate и decision из: ' + allowed.join(', ') } }];
  return [{ json: { ok: true, action: a, sql: "WITH d AS (INSERT INTO decisions (exp_id, gate, decision, decided_by, note) VALUES ($1, $2, $3, 'owner', $4) RETURNING exp_id, gate, decision), ev AS (INSERT INTO events (exp_id, kind, actor, message) SELECT exp_id, 'owner_decision', 'owner', gate || ': ' || decision FROM d RETURNING 1), u AS (UPDATE experiments SET status = CASE $3 WHEN 'kill' THEN 'killed' WHEN 'pause' THEN 'paused' WHEN 'reject' THEN 'waiting_owner' ELSE 'active' END, stage = CASE WHEN $3 IN ('approve', 'go') THEN least(stage + 1, 8) ELSE stage END, updated_at = now() WHERE id = $1 RETURNING id, stage, status) SELECT * FROM u", params: [q.exp, q.gate, q.decision, q.note || ''] } }];
}
if (a === 'digest') return [{ json: { ok: true, action: a } }];
if (a === 'cost') {
  const usd = Number(q.usd);
  if (!q.exp || !(usd >= 0) || !q.source) return [{ json: { ok: false, reply: 'cost требует exp, usd (число) и source' } }];
  return [{ json: { ok: true, action: a, sql: "WITH c AS (INSERT INTO costs (exp_id, source, usd, detail) VALUES ($1, $3, $2::numeric, $4) RETURNING exp_id, source, usd), ev AS (INSERT INTO events (exp_id, kind, actor, message) SELECT exp_id, 'cost', 'owner', 'Трата ' || usd || ' USD · ' || source FROM c RETURNING 1) SELECT * FROM c", params: [q.exp, String(usd), q.source, q.note || ''] } }];
}
if (a === 'advance') {
  const to = parseInt(q.to, 10);
  if (!q.exp || !(to >= 1 && to <= 8)) return [{ json: { ok: false, reply: 'advance требует exp и to (1–8)' } }];
  return [{ json: { ok: true, action: a, sql: "WITH old AS (SELECT stage FROM experiments WHERE id = $1), u AS (UPDATE experiments SET stage = $2::int, status = 'active', updated_at = now() WHERE id = $1 RETURNING id, stage), ev AS (INSERT INTO events (exp_id, stage, kind, actor, message) SELECT id, stage, 'stage_changed', 'owner', 'Этап ' || (SELECT stage FROM old) || ' → ' || stage FROM u RETURNING 1) SELECT * FROM u", params: [q.exp, String(to)] } }];
}
if (a === 'run') {
  if (!q.exp) return [{ json: { ok: false, reply: 'run требует exp' } }];
  return [{ json: { ok: true, action: a, sql: "SELECT id AS exp_id, stage FROM experiments WHERE id = $1", params: [q.exp] } }];
}
return [{ json: { ok: false, reply: 'Неизвестное действие. Есть: status, kill_on, kill_off, decide, digest, run, cost, advance' } }];"""
c = {}
n = [
    sticky("About", "## 99 · Пульт\nОдна ссылка, доступна только из домашней сети и Tailscale:\n`https://n8n.home.kalik8s.ru/webhook/farm?t=<токен>&action=…`\n\n- `status` — где каждый стартап\n- `kill_on` / `kill_off` — всё на паузу / снять паузу\n- `decide&exp=EXP-001&gate=G1&decision=approve` — решение на гейте\n- `digest` — дайджест сейчас\n- `run&exp=EXP-001` — прогнать текущий этап эксперимента\n- `cost&exp=EXP-001&usd=12.5&source=domain` — записать трату\n- `advance&exp=EXP-001&to=2` — перевести этап вручную\nТокен — в `/home/kalikys/prj/farm/.env` (FARM_CONTROL_TOKEN).", [-80, -380], 520, 300),
    node("Control link", "n8n-nodes-base.webhook", 2,
         {"httpMethod": "GET", "path": "farm", "responseMode": "lastNode", "options": {}}, [0, 0],
         extra={"webhookId": "b7f0c2a4-farm-control"}),
    sql("Read token", "SELECT value FROM settings WHERE key = 'control_token'", None, [240, 0]),
    code("Check token and plan", PLAN_JS, [480, 0]),
    if_true("Token ok?", "={{ $json.ok }}", [720, 0]),
    if_true("Digest?", "={{ $json.action === 'digest' }}", [960, -80]),
    call("Run digest", DIG, [1200, -200]),
    sql("Apply action", "={{ $json.sql }}", "={{ $json.params }}", [1200, 40]),
    if_true("Run a stage?", "={{ $('Check token and plan').first().json.action === 'run' }}", [1440, 40]),
    code("Pick stage workflow", f"const map = {json.dumps({str(k): v for k, v in STAGE_WF.items()})};\nreturn $input.all().map(i => ({{ json: {{ ...i.json, workflow_id: map[String(i.json.stage)] }} }}));", [1680, -40]),
    dict(call("Run stage", "={{ $json.workflow_id }}", [1920, -40]), alwaysOutputData=True),
    code("Reply", "const a = $('Check token and plan').first().json.action;\nreturn [{ json: { ok: true, action: a, result: $input.all().map(i => i.json) } }];", [2160, 40]),
    code("Reject", "return [{ json: { ok: false, reply: $input.first().json.reply } }];", [960, 140]),
]
link(c, "Control link", "Read token")
link(c, "Read token", "Check token and plan")
link(c, "Check token and plan", "Token ok?")
link(c, "Token ok?", "Digest?", 0)
link(c, "Token ok?", "Reject", 1)
link(c, "Digest?", "Run digest", 0)
link(c, "Digest?", "Apply action", 1)
link(c, "Run digest", "Reply")
link(c, "Apply action", "Run a stage?")
link(c, "Run a stage?", "Pick stage workflow", 0)
link(c, "Run a stage?", "Reply", 1)
link(c, "Pick stage workflow", "Run stage")
link(c, "Run stage", "Reply")
PANEL = upsert("99 · Control panel", n, c, ERR)

print(json.dumps({"error": ERR, "log": LOG, "preflight": PRE, "stages": STAGE_WF, "controller": CTRL,
                  "digest": DIG, "watchdog": WATCH, "panel": PANEL}))
