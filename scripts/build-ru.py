#!/usr/bin/env python3
"""Builds services/public/site/ru/index.html from the English page and services/public/i18n/ru.json.

The English index.html is the template: every element with data-i18n holds plain text,
which is swapped for its Russian string. Run after any change to index.html or ru.json;
CI fails if the committed ru/index.html is out of date.
"""
import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "services/public"
SITE = "https://cv.kalik8s.ru"

page = (PUBLIC / "site/index.html").read_text()
ru = json.loads((PUBLIC / "i18n/ru.json").read_text())


# The FAQPage JSON-LD must repeat the visible English Q&A word for word.
ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
faq_ld = next(n for n in ld["@graph"] if n["@type"] == "FAQPage")["mainEntity"]
for i, item in enumerate(faq_ld, 1):
    q = html.unescape(re.search(rf'data-i18n="faq.q{i}">([^<]*)<', page).group(1))
    a = html.unescape(re.search(rf'data-i18n="faq.a{i}">([^<]*)<', page).group(1))
    if (item["name"], item["acceptedAnswer"]["text"]) != (q, a):
        sys.exit(f"build-ru: FAQ #{i} in JSON-LD differs from the page text")


def swap(old, new):
    global page
    if page.count(old) != 1:
        sys.exit(f"build-ru: expected exactly one match for {old!r}")
    page = page.replace(old, new)


def attr(value):
    return html.escape(value, quote=True)


# Head: language, titles, canonical URL. hreflang links are the same on both pages.
en_title = re.search(r"<title>(.*?)</title>", page).group(1)
en_desc = re.search(r'<meta name="description" content="(.*?)">', page).group(1)
en_alt = re.search(r'<meta property="og:image:alt" content="(.*?)">', page).group(1)
swap('<html lang="en">', '<html lang="ru">')
swap(f"<title>{en_title}</title>", f"<title>{html.escape(ru['meta.title'])}</title>")
swap(f'<meta property="og:title" content="{en_title}">', f'<meta property="og:title" content="{attr(ru["meta.title"])}">')
swap(f'<meta name="description" content="{en_desc}">', f'<meta name="description" content="{attr(ru["meta.description"])}">')
swap(f'<meta property="og:description" content="{en_desc}">', f'<meta property="og:description" content="{attr(ru["meta.description"])}">')
swap(f'<meta property="og:image:alt" content="{en_alt}">', f'<meta property="og:image:alt" content="{attr(ru["meta.ogAlt"])}">')
swap('<meta property="og:locale" content="en_US">', '<meta property="og:locale" content="ru_RU">')
swap(f'<meta property="og:url" content="{SITE}/">', f'<meta property="og:url" content="{SITE}/ru/">')
swap(f'<link rel="canonical" href="{SITE}/">', f'<link rel="canonical" href="{SITE}/ru/">')

# JSON-LD: the page node and the FAQ describe the Russian page; the Person entity is shared.
for node in ld["@graph"]:
    if node["@type"] == "ProfilePage":
        node.update({"@id": f"{SITE}/ru/#page", "url": f"{SITE}/ru/", "name": ru["meta.title"], "inLanguage": "ru"})
    elif node["@type"] == "FAQPage":
        node["@id"] = f"{SITE}/ru/#recruiters"
        for i, item in enumerate(node["mainEntity"], 1):
            item["name"] = ru[f"faq.q{i}"]
            item["acceptedAnswer"]["text"] = ru[f"faq.a{i}"]
ld_block = json.dumps(ld, ensure_ascii=False, indent=2)
page = re.sub(r'(<script type="application/ld\+json">\n).*?(\n  </script>)',
              lambda m: m.group(1) + ld_block + m.group(2), page, count=1, flags=re.S)

# Language switch points back to the English page.
swap('href="/ru/" hreflang="ru" data-target="ru"', 'href="/" hreflang="en" data-target="en"')
swap('<span data-lang="en" class="is-active">EN</span>', '<span data-lang="en">EN</span>')
swap('<span data-lang="ru">RU</span>', '<span data-lang="ru" class="is-active">RU</span>')

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
    sys.exit(f"build-ru: no Russian string for {sorted(set(missing))}")

out = PUBLIC / "site/ru/index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(page)
print(f"wrote {out.relative_to(ROOT)}")
