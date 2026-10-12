#!/usr/bin/env python3
"""Render an investor deck (PDF) from memo.json. Deterministic: the agent writes data, this code draws it.

Usage: render_deck.py <dir containing memo.json> [<verification.json>]
Writes deck.pdf (and deck.html for debugging) into the same directory.
"""
import base64
import html
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from weasyprint import HTML  # noqa: E402
from panel import summarise_panel  # noqa: E402

INK, MUTED, ACCENT, GOOD, WARN, BAD, LINE, BG = "#16201b", "#5b6b62", "#2f6f4e", "#2f6f4e", "#b45309", "#b91c1c", "#d6ddd7", "#f6f8f5"


def e(x):
    return html.escape(str(x if x is not None else "—"))


def money(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:,.1f}{unit}"
    return f"${v:,.0f}"


def png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", transparent=True)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def chart_market(m):
    labels, vals = [], []
    for k, lab in (("tam", "TAM"), ("sam", "SAM"), ("som_2y", "SOM (2 года)")):
        v = (m.get(k) or {}).get("value_usd")
        if isinstance(v, (int, float)) and v > 0:
            labels.append(lab)
            vals.append(v)
    if not vals:
        return ""
    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    bars = ax.barh(labels[::-1], vals[::-1], color=[ACCENT, "#5c9a78", "#a7c9b5"][: len(vals)][::-1])
    ax.set_xscale("log")
    for b, v in zip(bars, vals[::-1]):
        ax.text(b.get_width(), b.get_y() + b.get_height() / 2, "  " + money(v), va="center", color=INK, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_xticks([])
    return png(fig)


def chart_evidence(ev):
    counts = {}
    for x in ev:
        counts[x.get("source_type", "other")] = counts.get(x.get("source_type", "other"), 0) + 1
    if not counts:
        return ""
    items = sorted(counts.items(), key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(4.6, 2.4))
    ax.barh([k for k, _ in items], [v for _, v in items], color=ACCENT)
    for i, (_, v) in enumerate(items):
        ax.text(v, i, f"  {v}", va="center", color=INK, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_xticks([])
    return png(fig)


def slide(title, body, kicker=""):
    k = f'<div class="kicker">{e(kicker)}</div>' if kicker else ""
    return f'<section class="slide">{k}<h2>{e(title)}</h2><div class="body">{body}</div></section>'


def chart_scenarios(sc):
    if not sc:
        return ""
    names = [str(x.get("name")) for x in sc]
    vals = [float(x.get("monthly_revenue_usd") or 0) for x in sc]
    fig, ax = plt.subplots(figsize=(4.8, 2.4))
    bars = ax.bar(names, vals, color=["#a7c9b5", "#5c9a78", ACCENT][: len(vals)])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height(), f"${v:,.0f}", ha="center", va="bottom", color=INK, fontsize=10)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_yticks([])
    ax.tick_params(colors=MUTED, labelsize=9)
    return png(fig)


def game_slides(m, ver):
    v = m.get("verdict", {})
    rec = (v.get("recommendation") or "maybe").lower()
    rec_color = {"invest": GOOD, "maybe": WARN, "pass": BAD}.get(rec, WARN)
    rec_ru = {"invest": "Делать игру", "maybe": "Под вопросом", "pass": "Не делать"}.get(rec, rec)
    ev = m.get("evidence", [])
    checks = ver.get("checks", [])
    domains = sorted({urlparse(x.get("url", "")).netloc for x in ev if x.get("url")})
    c = m.get("concept", {})
    mo = m.get("monetization", {})
    pr = m.get("production", {})
    out = [f"""<section class="slide title">
      <div class="kicker">Ферма · трек игр · меморандум · {e(m.get('slug'))}</div>
      <h1>{e(m.get('title'))}</h1><p class="lead">{e(m.get('one_liner'))}</p>
      <div class="verdict" style="border-color:{rec_color}"><span style="color:{rec_color}">{e(rec_ru)}</span>
        <b>{e(v.get('score_0_10'))}/10</b><p>{e(v.get('why'))}</p></div>
      <p class="muted small">Проверка кодом: {sum(1 for x in checks if x.get('passed'))} из {len(checks)} · {len(ev)} доказательств из {len(domains)} доменов</p></section>"""]
    out.append(slide("Концепт", f"""<div class="cols"><div><p><b>Механика:</b> {e(c.get('core_mechanic'))}</p><p><b>Новый поворот:</b> {e(c.get('twist'))}</p>
      <p><b>Сессия:</b> {e(c.get('session_minutes'))} мин · <b>Платформы:</b> {e(', '.join(c.get('platforms', [])))}</p></div>
      <div><p><b>Игровой цикл:</b> {e(pr.get('core_loop'))}</p><p><b>Управление:</b> {e(pr.get('controls'))}</p><p><b>Прогрессия:</b> {e(pr.get('progression'))}</p></div></div>""", "Что за игра"))
    rows = "".join(f'<tr><td>{e(x.get("source_type"))}</td><td>{e(x.get("signal"))}</td><td class="q">«{e(x.get("quote"))}»</td><td>{"✓" if x.get("verified") else ("✗" if "verified" in x else "")}</td></tr>' for x in ev[:9])
    img = chart_evidence(ev)
    out.append(slide("Доказательства популярности", f"""<div class="cols wide-left"><table><tr><th>Тип</th><th>Что доказывает</th><th>Цитата</th><th>Найдена</th></tr>{rows}</table>
      <div>{f'<img src="{img}">' if img else ''}<p class="muted small">Источники: {e(', '.join(domains[:8]))}</p></div></div>""", "Механика в тренде?"))
    crows = "".join(f'<tr><td><b>{e(x.get("name"))}</b><br><span class="muted small">{e(x.get("portal"))}</span></td><td>{e(x.get("plays_or_rating"))}</td><td>{e(x.get("praise"))}</td><td>{e(x.get("complaints"))}</td><td>{e(x.get("our_difference"))}</td></tr>' for x in m.get("competitors", [])[:7])
    out.append(slide("Похожие игры", f'<table><tr><th>Игра</th><th>Игры / рейтинг</th><th>Хвалят</th><th>Ругают</th><th>Наше отличие</th></tr>{crows}</table>', "С кем делим трафик портала"))
    simg = chart_scenarios(mo.get("scenarios", []))
    srows = "".join(f'<tr><td><b>{e(x.get("name"))}</b></td><td>{e(x.get("daily_plays"))}</td><td>${e(x.get("monthly_revenue_usd"))}</td></tr>' for x in mo.get("scenarios", []))
    out.append(slide("Монетизация", f"""<div class="cols"><div><table><tr><th>Сценарий</th><th>Игр в день</th><th>Доход в месяц</th></tr>{srows}</table>
      <p class="small">RPM ${e(mo.get('rpm_usd'))} на 1000 игр · доля разработчика {e(mo.get('dev_share'))}<br>{e(mo.get('formula'))}</p>
      <p class="muted small">{e(ver.get('unit_economics_note', ''))}</p></div><div>{f'<img src="{simg}">' if simg else ''}</div></div>""", "Реклама на портале, без закупки трафика"))
    out.append(slide("План разработки", f"""<div class="cols"><div><p><b>Срок:</b> {e(pr.get('build_days'))} дн. агента</p><p><b>Сочность и звук:</b> {e(pr.get('juice_and_sound'))}</p>
      <p><b>Рекламные слоты:</b> {e(', '.join(pr.get('ad_slots', [])))}</p><p><b>Ассеты:</b> {e(pr.get('assets'))}</p></div>
      <div><p><b>Технические риски</b></p><ul>{''.join(f'<li>{e(x)}</li>' for x in pr.get('tech_risks', []))}</ul></div></div>""", "Что строим за неделю"))
    prow = "".join(f'<tr><td>{e(x.get("rule"))}</td><td>{e(x.get("how_we_meet_it"))}</td></tr>' for x in m.get("portal_fit", []))
    out.append(slide("Требования порталов", f'<table><tr><th>Правило портала</th><th>Как выполняем</th></tr>{prow}</table>', "Чтобы не отклонили"))
    rrows = "".join(f'<tr><td>{e(r.get("risk"))}</td><td class="sev {e(r.get("severity"))}">{e(r.get("severity"))}</td><td>{e(r.get("mitigation"))}</td><td class="small">{e(r.get("would_change_my_mind"))}</td></tr>' for r in m.get("risks", [])[:6])
    out.append(slide("Риски (red team)", f'<table><tr><th>Риск</th><th>Тяжесть</th><th>Что делаем</th><th>Что изменит оценку</th></tr>{rrows}</table>', "Почему может не взлететь"))
    crow = "".join(f'<tr><td>{"✓" if x.get("passed") else "✗"}</td><td>{e(x.get("detail"))}</td></tr>' for x in checks)
    out.append(slide("Проверка фермой", f'<table>{crow}</table>', "Это проверил код, а не агент"))
    src = "".join(f'<li><b>{e(x.get("source_type"))}</b> · {e(x.get("url"))}</li>' for x in ev)
    out.append(slide("Источники", f'<ol class="sources">{src}</ol>', "Всё, на чём стоит меморандум"))
    return out


def main(d, verification=None):
    m = json.loads((d / "memo.json").read_text())
    ver = verification or {}
    v = m.get("verdict", {})
    rec = (v.get("recommendation") or "maybe").lower()
    rec_color = {"invest": GOOD, "maybe": WARN, "pass": BAD}.get(rec, WARN)
    rec_ru = {"invest": "Инвестировать в тест", "maybe": "Под вопросом", "pass": "Не инвестировать"}.get(rec, rec)
    ev = m.get("evidence", [])
    ue = m.get("unit_economics", {})
    mk = m.get("market", {})
    domains = sorted({urlparse(x.get("url", "")).netloc for x in ev if x.get("url")})

    slides = []
    checks = ver.get("checks", [])
    if m.get("kind") == "game":
        slides = game_slides(m, ver)
    passed_checks = sum(1 for c in checks if c.get("passed"))
    if m.get("kind") != "game":
      slides += startup_slides(m, ver, v, rec, rec_color, rec_ru, ev, ue, mk, domains, checks, passed_checks)
    panel = load_panel(d)
    if panel:
        slides.insert(1, panel_slide(panel, v))
    return finish(d, slides)


def load_panel(d):
    """Independent judges (role judges) and the median score the farm uses; None if the panel did not run."""
    try:
        return summarise_panel(json.loads((d / "panel.json").read_text()))
    except (OSError, ValueError):
        return None


def panel_slide(panel, v):
    names = {"vc": "Скептичный венчурный инвестор", "indie": "Инди-основатель без денег", "marketer": "Performance-маркетолог",
             "curator": "Куратор игрового портала", "producer": "Продюсер казуальных игр", "monetization": "Монетизация и реклама"}
    rows = "".join(f'<tr><td><b>{e(names.get(j.get("persona"), j.get("persona")))}</b></td><td><b>{e(j.get("score_0_10"))}</b></td><td>{e(j.get("recommendation"))}</td>'
                   f'<td class="small">{"<br>".join(e(r) for r in (j.get("top_reasons") or [])[:3])}</td><td class="small">{e(j.get("would_invest_if"))}</td></tr>'
                   for j in panel["judges"])
    color = GOOD if panel["median"] >= 7 else (WARN if panel["median"] >= 6 else BAD)
    return slide("Независимая панель", f"""<div class="kpis"><div style="border-color:{color}"><span>Медиана судей (это и есть оценка фермы)</span><b style="color:{color}">{panel['median']}/10</b><em>разброс {panel['spread']} · автор меморандума ставил {e(v.get('score_0_10'))}</em></div></div>
      <table><tr><th>Судья</th><th>Оценка</th><th>Вердикт</th><th>Главные причины</th><th>Вложился бы, если</th></tr>{rows}</table>""",
                 "Три судьи читали меморандум отдельно друг от друга")


def startup_slides(m, ver, v, rec, rec_color, rec_ru, ev, ue, mk, domains, checks, passed_checks):
    slides = []
    slides.append(f"""<section class="slide title">
      <div class="kicker">Ферма стартапов · инвестиционный меморандум · {e(m.get('slug'))}</div>
      <h1>{e(m.get('title'))}</h1>
      <p class="lead">{e(m.get('one_liner'))}</p>
      <div class="verdict" style="border-color:{rec_color}"><span style="color:{rec_color}">{e(rec_ru)}</span>
        <b>{e(v.get('score_0_10'))}/10</b><p>{e(v.get('why'))}</p></div>
      <p class="muted small">Проверка кодом: {passed_checks} из {len(checks)} проверок пройдено · {len(ev)} доказательств из {len(domains)} доменов</p>
    </section>""")

    p = m.get("problem", {})
    quotes = "".join(f'<blockquote>«{e(x.get("quote"))}»<cite>{e(x.get("source_type"))} · {e(urlparse(x.get("url","")).netloc)}</cite></blockquote>'
                     for x in [x for x in ev if x.get("signals_money")][:3])
    slides.append(slide("Проблема", f"""<div class="cols"><div><p>{e(p.get('summary'))}</p><p><b>Кто:</b> {e(p.get('who'))}</p>
      <p><b>Как решают сейчас:</b></p><ul>{''.join(f'<li>{e(w)}</li>' for w in p.get('current_workarounds', []))}</ul></div>
      <div>{quotes}</div></div>""", "Почему это болит"))

    rows = "".join(f'<tr><td>{e(x.get("source_type"))}</td><td>{e(x.get("signal"))}</td><td class="q">«{e(x.get("quote"))}»</td><td>{"✓" if x.get("verified") else ("✗" if "verified" in x else "")}</td></tr>'
                   for x in ev[:9])
    img = chart_evidence(ev)
    slides.append(slide("Доказательства спроса", f"""<div class="cols wide-left"><table><tr><th>Тип</th><th>Что доказывает</th><th>Цитата</th><th>Цитата найдена</th></tr>{rows}</table>
      <div>{f'<img src="{img}">' if img else ''}<p class="muted small">Источники: {e(', '.join(domains[:8]))}</p></div></div>""", "Что говорят люди, которые платят"))

    def mrow(key, lab):
        x = mk.get(key) or {}
        return f'<tr><td><b>{lab}</b></td><td>{money(x.get("value_usd"))}</td><td class="small">{e(x.get("formula"))}</td></tr>'
    trends = "".join(f'<li>{e(t.get("claim"))} <span class="muted small">({e(urlparse(t.get("source_url","")).netloc)})</span></li>' for t in mk.get("trends", []))
    mimg = chart_market(mk)
    slides.append(slide("Размер рынка", f"""<div class="cols"><div><table>{mrow('tam','TAM')}{mrow('sam','SAM')}{mrow('som_2y','SOM 2y')}</table>
      <p><b>Тренды</b></p><ul>{trends}</ul></div><div>{f'<img src="{mimg}">' if mimg else ''}</div></div>""", "Снизу вверх, с формулами"))

    crows = "".join(f'<tr><td><b>{e(c.get("name"))}</b><br><span class="muted small">{e(c.get("type"))}</span></td><td>{e(c.get("price"))}</td><td>{e(c.get("rating"))}</td><td>{e(c.get("weakness"))}</td></tr>'
                    for c in m.get("competitors", [])[:8])
    slides.append(slide("Конкуренты", f'<table><tr><th>Кто</th><th>Цена</th><th>Рейтинг</th><th>Слабость, которую используем</th></tr>{crows}</table>', "Кто уже берёт деньги"))

    def pct(x):
        return f"{float(x)*100:.1f}%" if isinstance(x, (int, float)) else "—"
    ltvcac = ue.get("ltv_to_cac")
    lc_color = GOOD if isinstance(ltvcac, (int, float)) and ltvcac >= 3 else (WARN if isinstance(ltvcac, (int, float)) and ltvcac >= 1 else BAD)
    slides.append(slide("Юнит-экономика", f"""<div class="kpis">
      <div><span>Цена</span><b>{money(ue.get('price_usd_month'))}</b><em>{e(ue.get('pricing_model'))}</em></div>
      <div><span>CPC</span><b>${e(ue.get('cpc_usd'))}</b><em>бенчмарк</em></div>
      <div><span>Конверсия лендинга</span><b>{pct(ue.get('landing_conversion'))}</b><em>trial→paid {pct(ue.get('trial_to_paid'))}</em></div>
      <div><span>CAC</span><b>{money(ue.get('cac_usd'))}</b><em>{e(ue.get('cac_formula'))}</em></div>
      <div><span>LTV</span><b>{money(ue.get('ltv_usd'))}</b><em>отток {pct(ue.get('monthly_churn'))}, маржа {pct(ue.get('gross_margin'))}</em></div>
      <div style="border-color:{lc_color}"><span>LTV / CAC</span><b style="color:{lc_color}">{e(ltvcac)}</b><em>окупаемость {e(ue.get('payback_months'))} мес</em></div>
    </div><p class="muted small">CAC и LTV пересчитаны кодом из входных данных: {e(ver.get('unit_economics_note', 'не проверялось'))}</p>""", "Сходится ли математика"))

    g = m.get("gtm", {})
    st = g.get("smoke_test", {})
    slides.append(slide("План теста и MVP", f"""<div class="cols"><div><p><b>Смоук-тест за ${e(st.get('budget_usd'))}</b></p>
      <ul><li>Канал: {e(st.get('channel'))}</li><li>Аудитория / запросы: {e(', '.join(st.get('audience_or_keywords', [])))}</li>
      <li>Обещание лендинга: {e(st.get('landing_promise'))}</li><li>Успех: {e(st.get('success_threshold'))}</li></ul></div>
      <div><p><b>MVP за 2 недели</b></p><ul>{''.join(f'<li>{e(x)}</li>' for x in g.get('mvp_2_weeks', []))}</ul>
      <p><b>Потом</b></p><ul>{''.join(f'<li>{e(x)}</li>' for x in g.get('later_channels', []))}</ul></div></div>""", "Как проверим за $150"))

    rrows = "".join(f'<tr><td>{e(r.get("risk"))}</td><td class="sev {e(r.get("severity"))}">{e(r.get("severity"))}</td><td>{e(r.get("mitigation"))}</td><td class="small">{e(r.get("would_change_my_mind"))}</td></tr>'
                    for r in m.get("risks", [])[:6])
    slides.append(slide("Риски (red team)", f'<table><tr><th>Риск</th><th>Тяжесть</th><th>Что делаем</th><th>Что изменит оценку</th></tr>{rrows}</table>', "Почему это может не сработать"))

    crow = "".join(f'<tr><td>{"✓" if c.get("passed") else "✗"}</td><td>{e(c.get("detail"))}</td></tr>' for c in checks)
    blocked = "".join(f"<li>{e(b)}</li>" for b in m.get("sources_blocked", []))
    slides.append(slide("Проверка фермой", f"""<div class="cols"><div><table>{crow}</table></div>
      <div><p><b>Что не удалось прочитать</b></p><ul>{blocked or '<li>—</li>'}</ul></div></div>""", "Это проверил код, а не агент"))

    budget = st.get("budget_usd") or 150
    slides.append(slide("Что нужно от инвестора", f"""<div class="kpis">
      <div><span>Деньги</span><b>${e(budget)}</b><em>реклама или рассылка, по твоему отдельному «да» перед запуском</em></div>
      <div><span>Твоё время</span><b>≈ 30 мин</b><em>утвердить условия · утвердить лендинг · запустить кампанию</em></div>
      <div><span>Срок</span><b>2–3 нед.</b><em>предрегистрация → лендинг → трафик → решение</em></div>
    </div>
    <p><b>Что получишь:</b> решение GO / KILL по правилу, записанному до теста: {e(st.get('success_threshold'))}.</p>
    <p class="muted small">Каждый шаг с деньгами или публичной страницей требует твоего подтверждения одноразовой ссылкой. Без «да» ферма не тратит ни доллара.</p>""",
        "Запрос на смоук-тест"))

    src = "".join(f'<li><b>{e(x.get("source_type"))}</b> · {e(x.get("url"))}</li>' for x in ev)
    slides.append(slide("Источники", f'<ol class="sources">{src}</ol>', "Всё, на чём стоит меморандум"))

    return slides


def finish(d, slides):
    css = f"""@page {{ size: 297mm 167mm; margin: 0 }}
    body {{ font-family: 'DejaVu Sans', sans-serif; color: {INK}; margin: 0 }}
    .slide {{ page-break-after: always; height: 167mm; box-sizing: border-box; padding: 12mm 14mm; background: {BG}; position: relative }}
    .slide.title {{ background: #fff; padding-top: 22mm }}
    .kicker {{ font-size: 8.5pt; letter-spacing: .08em; text-transform: uppercase; color: {ACCENT}; margin-bottom: 3mm }}
    h1 {{ font-size: 26pt; margin: 0 0 4mm; line-height: 1.15 }}
    h2 {{ font-size: 18pt; margin: 0 0 5mm }}
    .lead {{ font-size: 13pt; color: {MUTED}; max-width: 200mm }}
    .verdict {{ border-left: 5px solid; padding: 3mm 5mm; margin: 6mm 0; background: {BG}; max-width: 210mm }}
    .verdict span {{ font-weight: bold; font-size: 13pt; margin-right: 4mm }} .verdict b {{ font-size: 13pt }}
    .verdict p {{ margin: 2mm 0 0; font-size: 10pt }}
    .body {{ font-size: 10pt; line-height: 1.4 }}
    .cols {{ display: table; width: 100%; table-layout: fixed; border-spacing: 6mm 0; margin: 0 -6mm }} .cols > div {{ display: table-cell; vertical-align: top }} .cols.wide-left > div:first-child {{ width: 62% }}
    table {{ border-collapse: collapse; width: 100%; font-size: 8.5pt }}
    th {{ text-align: left; color: {MUTED}; font-weight: normal; border-bottom: 1px solid {LINE}; padding: 1.5mm }}
    td {{ border-bottom: 1px solid {LINE}; padding: 1.5mm; vertical-align: top }}
    td.q {{ font-style: italic; color: {MUTED} }}
    blockquote {{ margin: 0 0 4mm; padding: 3mm 4mm; background: #fff; border-left: 3px solid {ACCENT}; font-style: italic; font-size: 9.5pt }}
    cite {{ display: block; font-style: normal; color: {MUTED}; font-size: 8pt; margin-top: 1mm }}
    img {{ width: 100%; max-width: 100%; }}
    .kpis {{ display: flex; flex-wrap: wrap; gap: 4mm }}
    .kpis div {{ background: #fff; border: 1px solid {LINE}; border-radius: 3mm; padding: 3mm 4mm; width: 78mm; box-sizing: border-box }}
    .kpis span {{ display: block; color: {MUTED}; font-size: 8.5pt }} .kpis b {{ font-size: 17pt }} .kpis em {{ display: block; color: {MUTED}; font-size: 7.5pt; font-style: normal }}
    .muted {{ color: {MUTED} }} .small {{ font-size: 8pt }}
    .sev.high {{ color: {BAD} }} .sev.medium {{ color: {WARN} }} .sev.low {{ color: {GOOD} }}
    ol.sources {{ font-size: 7.5pt; columns: 2; column-gap: 8mm; word-break: break-all }}"""
    doc = f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>{css}</style></head><body>{"".join(slides)}</body></html>'
    (d / "deck.html").write_text(doc)
    HTML(string=doc).write_pdf(d / "deck.pdf")
    return d / "deck.pdf"


def prereg_main(d):
    """Two-slide «test conditions» PDF the owner approves before any money or public page."""
    p = json.loads((d / "prereg.json").read_text())
    m = json.loads((d / "memo.json").read_text())
    o, th = p.get("offer") or {}, p.get("thresholds") or {}
    go, kill, early = th.get("go") or {}, th.get("kill") or {}, th.get("early_kill") or {}
    pct = lambda x: f"{float(x) * 100:.1f}%" if isinstance(x, (int, float)) else "—"
    slides = [f"""<section class="slide title">
      <div class="kicker">Ферма стартапов · условия смоук-теста · {e(m.get('slug'))}</div>
      <h1>{e(m.get('title'))}</h1>
      <p class="lead">{e(p.get('hypothesis'))}</p>
      <div class="kpis">
        <div><span>Бюджет</span><b>${e(p.get('budget_usd'))}</b><em>не больше ${e(p.get('daily_cap_usd'))} в день</em></div>
        <div><span>Срок</span><b>{e(p.get('duration_days'))} дн.</b><em>цель — {e(p.get('target_visitors'))} посетителей</em></div>
        <div><span>Канал</span><b style="font-size:13pt">{e(p.get('channel'))}</b><em>{e(', '.join((p.get('keywords_or_audience') or [])[:4]))}</em></div>
      </div>
      <p class="muted small">После твоего «да» условия фиксируются (хэш), менять их нельзя. Решение — только по правилу ниже.</p>
    </section>""",
        slide("Правило решения", f"""<div class="kpis">
      <div style="border-color:{GOOD}"><span>GO</span><b style="color:{GOOD}">≥ {pct(go.get('signup_rate'))}</b><em>заявок от посетителей</em></div>
      <div style="border-color:{BAD}"><span>KILL</span><b style="color:{BAD}">≤ {pct(kill.get('signup_rate'))}</b><em>заявок от посетителей</em></div>
      <div style="border-color:{WARN}"><span>Ранняя остановка</span><b style="color:{WARN}">{e(early.get('after_visitors'))} визитов</b><em>если кликов по цене меньше {pct(early.get('cta_rate_below'))}</em></div>
    </div>
    <p><b>Предложение на лендинге:</b> {e(o.get('headline'))} — ${e(o.get('price_usd'))} / {e(o.get('billing'))}</p>
    <p><b>Правило:</b> {e(p.get('decision_rule'))}</p>
    <p><b>Что может исказить тест:</b></p><ul>{''.join(f'<li>{e(x)}</li>' for x in p.get('risks_to_validity', []))}</ul>""", "Что считаем успехом — заранее")]
    html_doc = finish(d, slides)
    (d / "deck.pdf").rename(d / "test_plan.pdf")
    (d / "deck.html").rename(d / "test_plan.html")
    return html_doc


if __name__ == "__main__":
    if sys.argv[1] == "--prereg":
        print(prereg_main(Path(sys.argv[2])))
    else:
        ver = json.loads(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None
        print(main(Path(sys.argv[1]), ver))
