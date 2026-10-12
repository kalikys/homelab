"""Stages 03-05 (smoke test): code checks for the pre-registration, the landing and the campaign, and landing publishing.

The agent writes files under /work/<EXP>/test/; everything here is deterministic code. Publishing uses the Cloudflare
token from the server's environment, which agents (uid 1000) cannot read.
"""
import hashlib
import json
import os
import re
import secrets
import urllib.request
from pathlib import Path

TEST_ROLES = {"preregistration", "landing", "traffic"}
CHANNELS = {"google_ads", "meta_ads", "cold_email", "community", "marketplace_listing"}
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
ALLOWED_EXT = {"html", "css", "svg", "png", "jpg", "webp", "ico", "txt"}
EXTERNAL_OK = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
# Social proof the product cannot have before it exists: fake testimonials, ratings, logos and user counts.
FAKE_PROOF = re.compile(r"trusted by|join \d[\d,]* |\d[\d,]*\+? (?:users|customers|teams|businesses) (?:use|trust|love)|testimonial|★|⭐|as seen (?:on|in)|rated \d", re.I)


def test_dir(exp):
    return Path("/work") / exp / "test"


def prepare(exp, role, body):
    """Inputs for a test-stage agent: the chosen memo and brief, and for later stages the approved pre-registration from the DB."""
    slug = body.get("slug", "")
    dd = Path("/work") / exp / "dd" / slug
    if not (dd / "memo.json").exists():
        return None, f"no memo for the chosen idea {slug!r}"
    work = test_dir(exp)
    work.mkdir(parents=True, exist_ok=True)
    for name in ("memo.json", "brief.json"):
        if (dd / name).exists():
            (work / name).write_text((dd / name).read_text())
    if role in ("landing", "traffic"):
        if not body.get("prereg"):
            return None, "approved pre-registration missing"
        (work / "prereg.json").write_text(json.dumps(body["prereg"], ensure_ascii=False, indent=2))
    if role == "landing":
        site = work / "landing"
        if site.exists():
            site.rename(work / f"landing-previous-{secrets.token_hex(3)}")
    if role == "traffic":
        (work / "landing_url.txt").write_text(body.get("landing_url", ""))
    return work, None


def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def validate_prereg(exp, body):
    checks = []

    def chk(rule, ok, detail):
        checks.append({"rule": rule, "passed": bool(ok), "detail": detail})

    work = test_dir(exp)
    try:
        p = json.loads((work / "prereg.json").read_text())
        memo = json.loads((work / "memo.json").read_text())
    except (OSError, ValueError) as ex:
        return {"ok": True, "exp_id": exp, "passed": False, "checks": [{"rule": "files", "passed": False, "detail": f"prereg.json или memo.json не читаются: {ex}"}]}
    cap = _num(body.get("budget_cap_usd")) or 150
    offer = p.get("offer") or {}
    th = p.get("thresholds") or {}
    go, kill, early = th.get("go") or {}, th.get("kill") or {}, th.get("early_kill") or {}
    budget, days, n = _num(p.get("budget_usd")), _num(p.get("duration_days")), _num(p.get("target_visitors"))
    chk("hypothesis", len(str(p.get("hypothesis", ""))) >= 40, "Гипотеза сформулирована")
    chk("channel", p.get("channel") in CHANNELS, f"Канал: {p.get('channel')}")
    chk("budget", budget is not None and 0 <= budget <= cap, f"Бюджет ${budget} (потолок ${cap:.0f})")
    chk("daily_cap", _num(p.get("daily_cap_usd")) is not None and _num(p.get("daily_cap_usd")) <= max(budget or 0, 0) and (budget == 0 or _num(p.get("daily_cap_usd")) > 0), "Дневной лимит не больше бюджета")
    chk("duration", days is not None and 3 <= days <= 21, f"Длительность {days} дн. (3–21)")
    chk("sample", n is not None and n >= 100, f"Цель — {n} уникальных посетителей (≥ 100)")
    price, memo_price = _num(offer.get("price_usd")), _num((memo.get("unit_economics") or {}).get("price_usd_month"))
    chk("price", price is not None and price > 0 and (memo_price is None or abs(price - memo_price) <= 0.25 * memo_price),
        f"Цена на лендинге ${price} совпадает с меморандумом (${memo_price}) ±25%")
    sg, sk = _num(go.get("signup_rate")), _num(kill.get("signup_rate"))
    chk("thresholds", sg is not None and sk is not None and 0 < sk < sg < 1, f"GO: заявки ≥ {sg}, KILL: ≤ {sk}")
    # The test must check the assumption the economics rest on: the GO bar is at least the landing conversion used for CAC.
    conv = _num((memo.get("unit_economics") or {}).get("landing_conversion"))
    chk("go_matches_economics", sg is not None and conv is not None and sg >= conv,
        f"Порог GO ({sg}) не ниже конверсии лендинга из расчёта CAC ({conv})")
    chk("early_kill", _num(early.get("after_visitors")) and _num(early.get("cta_rate_below")) is not None,
        "Ранняя остановка: после N посетителей, если клики по цене ниже порога")
    chk("decision_rule", len(str(p.get("decision_rule", ""))) >= 30, "Правило решения записано словами")
    chk("validity_risks", len(p.get("risks_to_validity") or []) >= 2, "Указаны риски, искажающие тест")
    passed = all(c["passed"] for c in checks)
    return {"ok": True, "exp_id": exp, "passed": passed, "checks": checks, "prereg": p if passed else None,
            "hash": canonical_hash(p) if passed else None}


def qa_landing(exp, body):
    checks = []

    def chk(rule, ok, detail):
        checks.append({"rule": rule, "passed": bool(ok), "detail": detail})

    site = test_dir(exp) / "landing"
    prereg = body.get("prereg") or {}
    files = [f for f in site.glob("*") if f.is_file()] if site.exists() else []
    names = {f.name for f in files}
    bad_names = [f.name for f in files if not FILE_RE.match(f.name) or f.suffix.lstrip(".") not in ALLOWED_EXT]
    total = sum(f.stat().st_size for f in files)
    chk("files", {"index.html", "privacy.html", "terms.html"} <= names and not bad_names,
        f"index, privacy, terms на месте; недопустимые файлы: {', '.join(bad_names) or 'нет'}")
    chk("size", 0 < total <= 400_000, f"Размер {total // 1024} КБ (≤ 400)")
    html_text = "\n".join(f.read_text("utf-8", "ignore") for f in files if f.suffix in (".html", ".css"))
    index = (site / "index.html").read_text("utf-8", "ignore") if "index.html" in names else ""
    chk("no_scripts", "<script" not in html_text.lower() and not re.search(r"\son\w+\s*=", html_text, re.I),
        "Нет своих скриптов и обработчиков: счётчик вставляет Worker фермы")
    ext = [u for u in re.findall(r"""(?:src|href)\s*=\s*["'](https?://[^"']+)""", html_text, re.I) if not u.startswith(EXTERNAL_OK)]
    chk("no_external", not ext, "Нет внешних ресурсов (кроме Google Fonts)" + (f": {ext[:3]}" if ext else ""))
    price = _num((prereg.get("offer") or {}).get("price_usd"))
    price_txt = f"{price:g}" if price else "?"
    chk("price_shown", price and re.search(rf"\$\s?{re.escape(price_txt)}(?:\.00)?\b", index), f"Цена ${price_txt} показана на главной")
    chk("cta", "data-farm-cta" in index, "Есть кнопка выбора цены (data-farm-cta)")
    chk("signup", re.search(r"<form[^>]*data-farm-signup", index, re.I) and 'type="email"' in index and "data-farm-thanks" in index,
        "Есть форма заявки с email и блоком «спасибо»")
    chk("legal_links", "privacy.html" in index and "terms.html" in index, "Ссылки на Privacy и Terms")
    chk("honest", re.search(r"not (?:yet )?(?:available|launched)|in development|early access|pre-?launch|coming soon", index, re.I),
        "Честно сказано, что продукт ещё не запущен и оплата сейчас не берётся")
    fake = sorted({m.group(0) for m in FAKE_PROOF.finditer(html_text)})
    chk("no_fake_proof", not fake, "Нет выдуманных отзывов, рейтингов, логотипов и числа клиентов" + (f": {fake[:3]}" if fake else ""))
    return {"ok": True, "exp_id": exp, "passed": all(c["passed"] for c in checks), "checks": checks, "files": sorted(names)}


def _cf(method, path, data=None, ctype="application/octet-stream"):
    acc, token = os.environ["CF_ACCOUNT_ID"], os.environ["CF_API_TOKEN"]
    req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{acc}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def publish_landing(exp, body):
    """Upload the checked landing to KV. mode=preview keeps it behind a secret link; mode=live opens it."""
    kv = os.environ.get("CF_KV_SITES_ID")
    base = os.environ.get("LANDING_BASE_URL", "").rstrip("/")
    if not (kv and base and os.environ.get("CF_API_TOKEN")):
        return 503, {"ok": False, "error": "landing publishing is not configured"}
    mode = body.get("mode", "preview")
    site = test_dir(exp) / "landing"
    meta_path = test_dir(exp) / "landing_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {"preview_token": secrets.token_urlsafe(16)}
    if mode == "preview":
        for f in sorted(site.glob("*")):
            if f.is_file() and FILE_RE.match(f.name) and f.suffix.lstrip(".") in ALLOWED_EXT:
                _cf("PUT", f"/storage/kv/namespaces/{kv}/values/site:{exp}:{f.name}", f.read_bytes())
        meta["files_hash"] = canonical_hash(sorted((f.name, hashlib.sha256(f.read_bytes()).hexdigest()) for f in site.glob("*") if f.is_file()))
    meta["live"] = mode == "live"
    _cf("PUT", f"/storage/kv/namespaces/{kv}/values/meta:{exp}", json.dumps(meta).encode(), "application/json")
    meta_path.write_text(json.dumps(meta))
    url = f"{base}/l/{exp}/"
    return 200, {"ok": True, "exp_id": exp, "mode": mode, "url": url,
                 "preview_url": f"{url}?preview={meta['preview_token']}", "files_hash": meta.get("files_hash")}


def validate_campaign(exp, body):
    checks = []

    def chk(rule, ok, detail):
        checks.append({"rule": rule, "passed": bool(ok), "detail": detail})

    try:
        c = json.loads((test_dir(exp) / "campaign.json").read_text())
    except (OSError, ValueError) as ex:
        return {"ok": True, "exp_id": exp, "passed": False, "checks": [{"rule": "file", "passed": False, "detail": f"campaign.json не читается: {ex}"}]}
    prereg = body.get("prereg") or {}
    landing = body.get("landing_url", "")
    budget, daily = _num(c.get("budget_usd")), _num(c.get("daily_cap_usd"))
    chk("channel", c.get("channel") == prereg.get("channel"), f"Канал {c.get('channel')} как в предрегистрации ({prereg.get('channel')})")
    chk("budget", budget is not None and budget <= (_num(prereg.get("budget_usd")) or 0), f"Бюджет ${budget} ≤ утверждённого ${prereg.get('budget_usd')}")
    chk("daily_cap", daily is not None and daily <= (_num(prereg.get("daily_cap_usd")) or 0), f"Дневной лимит ${daily} ≤ ${prereg.get('daily_cap_usd')}")
    links = [str(x) for x in (c.get("links") or [])]
    chk("links", links and all(l.startswith(landing) and "utm_source=" in l and f"utm_campaign={exp}" in l for l in links),
        "Все ссылки ведут на лендинг с utm_source и utm_campaign=" + exp)
    if c.get("channel") in ("google_ads", "meta_ads"):
        ads = c.get("ads") or []
        long_h = [h for a in ads for h in a.get("headlines", []) if len(h) > 30]
        long_d = [d for a in ads for d in a.get("descriptions", []) if len(d) > 90]
        chk("ads", ads and not long_h and not long_d, f"Объявления в лимитах (заголовки ≤ 30, описания ≤ 90): длинных {len(long_h) + len(long_d)}")
        chk("targeting", len(c.get("keywords") or c.get("audiences") or []) >= 5, "Не меньше 5 ключей или аудиторий")
    if c.get("channel") == "cold_email":
        tpl = c.get("templates") or []
        chk("templates", tpl and all("unsubscribe" in t.get("body", "").lower() and t.get("sender_address") for t in tpl),
            "В каждом письме есть отписка и физический адрес отправителя (CAN-SPAM)")
        chk("targets", (c.get("target_criteria") or {}).get("excludes_eu") is True, "Получатели вне ЕС (GDPR)")
    chk("owner_steps", len(c.get("owner_steps") or []) >= 2, "Пошаговая инструкция запуска для владельца")
    return {"ok": True, "exp_id": exp, "passed": all(x["passed"] for x in checks), "checks": checks, "campaign": c}
