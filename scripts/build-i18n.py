#!/usr/bin/env python3
"""Builds the translated pages of the site (/ru/, /sk/) from the English ones and services/public/i18n/<lang>.json.

Each English page is the template: every element with data-i18n holds plain text,
which is swapped for its translation. Run after any change to an English page or a translation file;
CI fails if a committed translated page is out of date.
"""
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "services/public"
SITE = "https://kalik8s.com"

# Language code -> og:locale.
LANGS = {"ru": "ru_RU", "sk": "sk_SK"}

# Per-language files that replace the English ones on the translated pages.
CV_PDF = {"sk": "/Kalislav-Smirnov-CV-SK.pdf"}

# English source, URL path, prefix of its meta strings, extra exact swaps for links between pages ({p} = /<lang>).
PAGES = [
    ("site/index.html", "/", "meta", [
        ('href="/lab/"', 'href="{p}/lab/"'),
    ]),
    ("site/lab/index.html", "/lab/", "certlab.meta", [
        ('class="brand" href="/"', 'class="brand" href="{p}/"'),
        ('class="back" href="/"', 'class="back" href="{p}/"'),
    ]),
]


def attr(value):
    return html.escape(value, quote=True)


def build(lang, src, path, meta, extra):
    ru = json.loads((PUBLIC / f"i18n/{lang}.json").read_text())  # strings of the target language
    source = PUBLIC / src
    if not source.exists():
        print(f"skip {src}: no English page yet")
        return
    page = source.read_text()
    en_url, ru_url = SITE + path, SITE + f"/{lang}" + path

    def swap(old, new):
        nonlocal page
        if page.count(old) != 1:
            sys.exit(f"build-i18n: {src}: expected exactly one match for {old!r}")
        page = page.replace(old, new)

    ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    ld = json.loads(ld_match.group(1)) if ld_match else None

    # The FAQPage JSON-LD must repeat the visible English Q&A word for word.
    faq_node = next((n for n in ld["@graph"] if n["@type"] == "FAQPage"), None) if ld else None
    if faq_node:
        for i, item in enumerate(faq_node["mainEntity"], 1):
            q = html.unescape(re.search(rf'data-i18n="faq.q{i}">([^<]*)<', page).group(1))
            a = html.unescape(re.search(rf'data-i18n="faq.a{i}">([^<]*)<', page).group(1))
            if (item["name"], item["acceptedAnswer"]["text"]) != (q, a):
                sys.exit(f"build-i18n: {src}: FAQ #{i} in JSON-LD differs from the page text")

    # Head: language, titles, canonical URL. hreflang links are the same on both pages.
    en_title = re.search(r"<title>(.*?)</title>", page).group(1)
    en_desc = re.search(r'<meta name="description" content="(.*?)">', page).group(1)
    en_alt = re.search(r'<meta property="og:image:alt" content="(.*?)">', page).group(1)
    swap('<html lang="en">', f'<html lang="{lang}">')
    swap(f"<title>{en_title}</title>", f"<title>{html.escape(ru[meta + '.title'])}</title>")
    swap(f'<meta property="og:title" content="{en_title}">', f'<meta property="og:title" content="{attr(ru[meta + ".title"])}">')
    swap(f'<meta name="description" content="{en_desc}">', f'<meta name="description" content="{attr(ru[meta + ".description"])}">')
    swap(f'<meta property="og:description" content="{en_desc}">', f'<meta property="og:description" content="{attr(ru[meta + ".description"])}">')
    swap(f'<meta property="og:image:alt" content="{en_alt}">', f'<meta property="og:image:alt" content="{attr(ru[meta + ".ogAlt"])}">')
    swap('<meta property="og:locale" content="en_US">', f'<meta property="og:locale" content="{LANGS[lang]}">')
    if '<meta property="og:locale:alternate"' in page:
        others = ["en_US"] + [loc for code, loc in LANGS.items() if code != lang]
        page = re.sub(r'(  <meta property="og:locale:alternate" content="[^"]+">\n)+',
                      "".join(f'  <meta property="og:locale:alternate" content="{loc}">\n' for loc in others), page, count=1)
    swap(f'<meta property="og:url" content="{en_url}">', f'<meta property="og:url" content="{ru_url}">')
    swap(f'<link rel="canonical" href="{en_url}">', f'<link rel="canonical" href="{ru_url}">')

    # JSON-LD: the page node and the FAQ describe the Russian page; the Person entity is shared.
    if ld:
        for node in ld["@graph"]:
            if node["@type"] == "ProfilePage":
                node.update({"@id": f"{ru_url}#page", "url": ru_url, "name": ru[meta + ".title"], "inLanguage": lang})
            elif node["@type"] == "FAQPage":
                node["@id"] = f"{ru_url}#recruiters"
                for i, item in enumerate(node["mainEntity"], 1):
                    item["name"] = ru[f"faq.q{i}"]
                    item["acceptedAnswer"]["text"] = ru[f"faq.a{i}"]
        ld_block = json.dumps(ld, ensure_ascii=False, indent=2)
        page = re.sub(r'(<script type="application/ld\+json">\n).*?(\n  </script>)',
                      lambda m: m.group(1) + ld_block + m.group(2), page, count=1, flags=re.S)

    # Language switch: the current language is the active link.
    swap('data-lang="en" class="is-active" aria-current="page">', 'data-lang="en">')
    swap(f'data-lang="{lang}">', f'data-lang="{lang}" class="is-active" aria-current="page">')
    for old, new in extra:
        swap(old, new.format(p="/" + lang))
    if lang in CV_PDF and 'href="/Kalislav-Smirnov-CV.pdf"' in page:
        page = page.replace('href="/Kalislav-Smirnov-CV.pdf"', f'href="{CV_PDF[lang]}"')  # hero and contact

    # Body text.
    missing = []

    def translate(m):
        open_tag, key, close_tag = m.group("open"), m.group("key"), m.group("close")
        if key not in ru:
            missing.append(key)
            return m.group(0)
        return f"{open_tag}{html.escape(ru[key], quote=False)}{close_tag}"

    page = re.sub(r'(?P<open><(?P<tag>\w+)[^>]*\bdata-i18n="(?P<key>[^"]+)"[^>]*>)[^<]*(?P<close></(?P=tag)>)',
                  translate, page)
    if missing:
        sys.exit(f"build-i18n: {src}: no {lang} string for {sorted(set(missing))}")

    out = PUBLIC / "site" / lang / path.lstrip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    print(f"wrote {out.relative_to(ROOT)}")


for lang in LANGS:
    for page_args in PAGES:
        build(lang, *page_args)
