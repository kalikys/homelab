#!/usr/bin/env python3
"""Builds the blog of kalik8s.com ("Field notes") from content/blog/*.md.

Output (committed, the server only serves static files):
  services/public/site/blog/<slug>/index.html   one page per post
  services/public/site/blog/index.html          list of posts
  services/public/site/blog/feed.xml            RSS
  sitemap.xml / sitemap.txt / llms.txt          blog URLs between the blog markers
  index.html                                    nav link + "Latest field notes" between the blog markers

Posts whose file name starts with "_" are drafts: skipped unless --drafts.
  python3 scripts/build-blog.py            build
  python3 scripts/build-blog.py --drafts   also build drafts (local preview only, never commit that)
  python3 scripts/build-blog.py --og       also render a 1200x630 og.jpg per post with headless Chrome (local)
Run scripts/build-i18n.py afterwards: the RU/SK pages copy the blog block from the English page.
"""
import datetime
import html
import json
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content/blog"
SITE_DIR = ROOT / "services/public/site"
OUT = SITE_DIR / "blog"
SITE = "https://kalik8s.com"
AUTHOR_ID = SITE + "/#person"
CAL = "https://cal.com/kalikys/intro?utm_source=cv_site&amp;utm_medium=blog"
LINKEDIN = "https://www.linkedin.com/in/devops-kalislav-smirnov/"
VER = "202610211200"  # cache-busting suffix for shared assets

esc = lambda s: html.escape(str(s), quote=True)


# ---------------------------------------------------------------- Markdown (safe subset)

def slugify(text):
    s = re.sub(r"<[^>]+>", "", text)
    s = html.unescape(s).lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    return re.sub(r"[\s-]+", "-", s).strip("-") or "section"


def inline(text):
    """Inline Markdown to HTML. Raw HTML in the source is escaped, never passed through."""
    # Code spans become placeholders first, so a link label may contain code: [`x`](url).
    # Inside attributes (href, src, alt, title) a placeholder turns back into the plain code text,
    # escaped as an attribute value; only element content gets the <code> markup.
    global _RAW_CODES
    _RAW_CODES = []
    text = text.replace("\x00", "")  # nobody can forge a placeholder

    def stash(m):
        _RAW_CODES.append(m.group(2))
        return f"\x00{len(_RAW_CODES) - 1}\x00"
    t = _inline_text(re.sub(r"(`+)(.+?)\1", stash, text))
    return re.sub(r"\x00(\d+)\x00", lambda m: "<code>" + html.escape(_RAW_CODES[int(m.group(1))], quote=True) + "</code>", t)


_RAW_CODES = []


def _unstash(value):
    """Placeholders inside an attribute value become the raw code text (escaped later as an attribute)."""
    return re.sub(r"\x00(\d+)\x00", lambda m: html.escape(_RAW_CODES[int(m.group(1))], quote=False), value)


def _safe_url(url):
    url = url.strip()
    if re.match(r"^(https?:|mailto:|/|#|\./|\.\./)", url, re.I) or not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
        return url
    return "#"  # javascript:, data: and any other scheme are dropped


def _attr(value):
    """Value for an HTML attribute: the text was escaped with quote=False, so undo that and escape with quotes."""
    return esc(html.unescape(value))


def _inline_text(t):
    t = html.escape(t, quote=False)

    def image(m):
        title = f' title="{_attr(_unstash(m.group(3)))}"' if m.group(3) else ""
        return f'<img src="{_attr(_safe_url(html.unescape(_unstash(m.group(2)))))}" alt="{_attr(_unstash(m.group(1)))}"{title} loading="lazy" decoding="async">'
    t = re.sub(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)', image, t)

    def link(m):
        href = _safe_url(html.unescape(_unstash(m.group(2))))
        ext = href.startswith("http") and not href.startswith(SITE)
        rel = ' target="_blank" rel="noopener"' if ext else ""
        title = f' title="{_attr(_unstash(m.group(3)))}"' if m.group(3) else ""
        return f'<a href="{_attr(href)}"{title}{rel}>{m.group(1)}</a>'
    t = re.sub(r'(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)', link, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", t)
    return t


def markdown(src):
    """Returns (html, headings) where headings = [(level, id, text)] for h2/h3."""
    lines = src.replace("\r\n", "\n").split("\n")
    out, heads, used = [], [], set()
    i = 0

    def para(buf):
        if buf:
            text = " ".join(x.strip() for x in buf)
            if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", text.strip()):
                out.append("<figure>" + inline(text) + "</figure>")
            else:
                out.append("<p>" + inline(text) + "</p>")

    buf = []
    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^(```|~~~)\s*([\w+#.-]*)\s*$", line)
        if fence:
            para(buf); buf = []
            mark, lang = fence.group(1), fence.group(2)
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith(mark):
                code.append(lines[i]); i += 1
            i += 1
            cls = f' class="language-{esc(lang)}"' if lang else ""
            label = f'<span class="code__lang">{esc(lang)}</span>' if lang else ""
            out.append(f'<pre class="code">{label}<code{cls}>' + html.escape("\n".join(code), quote=False) + "</code></pre>")
            continue
        h = re.match(r"^(#{1,4})\s+(.+?)\s*#*\s*$", line)
        if h:
            para(buf); buf = []
            level = len(h.group(1)) + (1 if len(h.group(1)) == 1 else 0)  # a lone "#" becomes h2: h1 is the title
            text = inline(h.group(2))
            hid = base = slugify(text)
            n = 2
            while hid in used:
                hid = f"{base}-{n}"; n += 1
            used.add(hid)
            if level in (2, 3):
                heads.append((level, hid, re.sub(r"<[^>]+>", "", text)))
            out.append(f'<h{level} id="{hid}">{text}</h{level}>')
            i += 1
            continue
        if line.startswith(">"):
            para(buf); buf = []
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i][1:].lstrip()); i += 1
            inner, _ = markdown("\n".join(q))
            out.append("<blockquote>" + inner + "</blockquote>")
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            para(buf); buf = []
            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]
            head = cells(line)
            aligns = []
            for c in cells(lines[i + 1]):
                aligns.append("right" if c.endswith(":") and not c.startswith(":") else "center" if c.startswith(":") and c.endswith(":") else "")
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(cells(lines[i])); i += 1
            al = lambda k: f' class="ta-{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
            t = ['<div class="table"><table><thead><tr>' + "".join(f"<th{al(k)}>{inline(c)}</th>" for k, c in enumerate(head)) + "</tr></thead><tbody>"]
            for r in rows:
                t.append("<tr>" + "".join(f"<td{al(k)}>{inline(c)}</td>" for k, c in enumerate(r)) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue
        lm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if lm:
            para(buf); buf = []
            ordered = lm.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if m and (m.group(2)[0].isdigit()) == ordered:
                    items.append(m.group(3)); i += 1
                elif items and lines[i].startswith(("  ", "\t")) and lines[i].strip():
                    items[-1] += " " + lines[i].strip(); i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            para(buf); buf = []
            out.append("<hr>")
            i += 1
            continue
        if not line.strip():
            para(buf); buf = []
        else:
            buf.append(line)
        i += 1
    para(buf)
    return "\n".join(out), heads


# ---------------------------------------------------------------- posts

def front_matter(text, path):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        sys.exit(f"build-blog: {path.name}: missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            v = v.strip("'\"")
        meta[k.strip()] = v
    for key in ("title", "description", "date"):
        if not meta.get(key):
            sys.exit(f"build-blog: {path.name}: front matter needs '{key}'")
    if isinstance(meta.get("tags"), str):
        meta["tags"] = [t.strip() for t in meta["tags"].split(",") if t.strip()]
    meta.setdefault("tags", [])
    meta["slug"] = meta.get("canonical_slug") or path.stem.lstrip("_")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", meta["slug"]):
        sys.exit(f"build-blog: {path.name}: slug must be lowercase a-z, 0-9 and dashes")
    meta.setdefault("updated", meta["date"])
    if len(meta["description"]) > 170:
        print(f"build-blog: warning: {path.name}: description is {len(meta['description'])} chars (keep under ~160)")
    return meta, m.group(2)


def load(drafts):
    posts = []
    for p in sorted(CONTENT.glob("*.md")):
        if p.name.startswith("_") and not drafts:
            continue
        meta, body = front_matter(p.read_text(), p)
        meta["html"], meta["heads"] = markdown(body)
        words = len(re.findall(r"\w+", re.sub(r"```.*?```", " ", body, flags=re.S)))
        meta["minutes"] = max(1, round(words / 220))
        meta["url"] = f"{SITE}/blog/{meta['slug']}/"
        meta["path"] = f"/blog/{meta['slug']}/"
        posts.append(meta)
    posts.sort(key=lambda m: (m["date"], m["slug"]), reverse=True)
    return posts


def human_date(d):
    return datetime.date.fromisoformat(d).strftime("%-d %b %Y")


# ---------------------------------------------------------------- templates

def head(title, desc, url, og, og_alt, ld, kind="article"):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{esc(url)}">
  <link rel="alternate" type="application/rss+xml" title="Field notes · Kalislav Smirnov" href="/blog/feed.xml">
  <meta property="og:type" content="{kind}">
  <meta property="og:site_name" content="kalik8s.com">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{esc(url)}">
  <meta property="og:image" content="{esc(og)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{esc(og_alt)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{esc(og)}">
  <script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False, indent=2)}
  </script>
  <meta name="theme-color" content="#fdf6ec">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700;800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="/styles.css?v={VER}">
</head>"""


def topbar():
    return """<body class="blog-page">
  <a class="skip" href="#main">Skip to content</a>
  <header class="topbar">
    <div class="wrap topbar__inner">
      <a class="brand" href="/" aria-label="Kalislav Smirnov, home">
        <span class="brand__mark">KS</span><span class="brand__mission" aria-hidden="true">mission</span>
      </a>
      <nav class="nav nav--blog" aria-label="Site">
        <a href="/#payload">Cases</a>
        <a href="/#flightlog">Experience</a>
        <a href="/blog/" aria-current="true">Field notes</a>
        <a href="/#contact">Contact</a>
      </nav>
      <a class="btn btn--sun btn--sm topbar__cta" href="/Kalislav-Smirnov-CV.pdf" download>CV (PDF)</a>
    </div>
  </header>"""


FOOTER = """  <footer class="footer">
    <div class="wrap footer__inner">
      <span>© 2026 Kalislav Smirnov · <a href="/blog/feed.xml">RSS</a></span>
      <span class="footer__mono">hosted at home, published via Cloudflare Tunnel</span>
    </div>
  </footer>
  <!-- Cloudflare Web Analytics: cookie-free; the beacon token is public by design. -->
  <script type="module" src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "dac8ddebf99f4dea8a1c2deaabc561d5"}'></script> <!-- gitleaks:allow -->
</body>
</html>
"""


def author_box():
    return f"""      <aside class="author" aria-label="About the author">
        <p class="label"><span class="label__dot" aria-hidden="true"></span>Written by</p>
        <p class="author__name">Kalislav Smirnov</p>
        <p class="author__role">DevOps engineer · open to remote work</p>
        <p class="author__bio">4.5 years of Kubernetes, GitLab CI/CD, Ansible and Terraform for banks and government agencies, including fully air-gapped networks. Spacecraft engineer by degree.</p>
        <div class="cta">
          <a class="btn btn--sun" href="{CAL}" target="_blank" rel="noopener">Hiring? Book a 20-min call</a>
          <a class="btn" href="/Kalislav-Smirnov-CV.pdf" download>Download CV (PDF)</a>
        </div>
        <p class="cta__more">
          <a href="/#cases">Case studies</a>
          <a href="https://t.me/kalikys" target="_blank" rel="noopener">Telegram</a>
          <a href="{LINKEDIN}" target="_blank" rel="noopener">LinkedIn</a>
          <a href="https://github.com/kalikys" target="_blank" rel="noopener">GitHub</a>
          <a href="mailto:kalikys@outlook.com">Email</a>
        </p>
      </aside>"""


def og_url(p):
    return SITE + p["path"] + "og.jpg" if (OUT / p["slug"] / "og.jpg").exists() else SITE + "/og.jpg?v=20261020"


def tags_html(tags):
    return '<p class="tags">' + "".join(f"<span>{esc(t)}</span>" for t in tags) + "</p>" if tags else ""


def post_page(p, posts):
    i = posts.index(p)
    newer = posts[i - 1] if i > 0 else None
    older = posts[i + 1] if i + 1 < len(posts) else None
    related = sorted((q for q in posts if q is not p), key=lambda q: (-len(set(q["tags"]) & set(p["tags"])), q["date"]), reverse=False)
    related = [q for q in related if set(q["tags"]) & set(p["tags"])][:3] or [q for q in posts if q is not p][:3]
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "BlogPosting", "@id": p["url"] + "#post", "headline": p["title"], "description": p["description"],
         "url": p["url"], "mainEntityOfPage": p["url"], "datePublished": p["date"], "dateModified": p["updated"],
         "inLanguage": p.get("lang", "en"), "keywords": ", ".join(p["tags"]), "image": og_url(p),
         "wordCount": p["minutes"] * 220, "author": {"@id": AUTHOR_ID, "@type": "Person", "name": "Kalislav Smirnov", "url": SITE + "/"},
         "publisher": {"@id": AUTHOR_ID}, "isPartOf": {"@id": SITE + "/blog/#blog"}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Kalislav Smirnov", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Field notes", "item": SITE + "/blog/"},
            {"@type": "ListItem", "position": 3, "name": p["title"], "item": p["url"]}]}]}
    if p.get("devto_url"):
        ld["@graph"][0]["sameAs"] = p["devto_url"]
    toc = ""
    h2 = [h for h in p["heads"] if h[0] == 2]
    if len(h2) >= 4:
        toc = '      <nav class="toc" aria-label="Contents">\n        <p class="label">Contents</p>\n        <ol>' + "".join(
            f'<li class="toc__l{lv}"><a href="#{hid}">{esc(t)}</a></li>' for lv, hid, t in p["heads"]) + "</ol>\n      </nav>\n"
    pager = '      <nav class="pager" aria-label="More posts">'
    pager += (f'<a class="pager__prev" href="{older["path"]}"><span class="label">← Older</span><span>{esc(older["title"])}</span></a>' if older else "<span></span>")
    pager += (f'<a class="pager__next" href="{newer["path"]}"><span class="label">Newer →</span><span>{esc(newer["title"])}</span></a>' if newer else "<span></span>")
    pager += "</nav>\n"
    rel = ""
    if related:
        rel = '      <section class="related" aria-labelledby="related-title">\n        <h2 class="block__title" id="related-title">Related field notes</h2>\n        <ul class="postlist">' + "".join(
            card(q, "h3") for q in related) + "</ul>\n      </section>\n"
    devto = f' · <a href="{esc(p["devto_url"])}" target="_blank" rel="noopener">discuss on dev.to</a>' if p.get("devto_url") else ""
    updated = f' · updated <time datetime="{esc(p["updated"])}">{human_date(p["updated"])}</time>' if p["updated"] != p["date"] else ""
    return (head(f'{p["title"]} | Kalislav Smirnov', p["description"], p["url"], og_url(p), p["title"], ld) + topbar() + f"""
  <main id="main" class="wrap post">
    <article class="article">
      <header class="article__head">
        <p class="label"><a class="label__num" href="/blog/">Field notes</a> <span>{" · ".join(esc(t) for t in p["tags"][:3])}</span></p>
        <h1 class="article__title">{esc(p["title"])}</h1>
        <p class="article__lead">{esc(p["description"])}</p>
        <p class="article__meta"><time datetime="{esc(p["date"])}">{human_date(p["date"])}</time>{updated} · {p["minutes"]} min read{devto}</p>
      </header>
{toc}      <div class="prose">
{p["html"]}
      </div>
      {tags_html(p["tags"])}
{author_box()}
    </article>
{pager}{rel}  </main>
""" + FOOTER)


def card(p, tag="h2"):
    return (f'<li class="postcard"><a href="{p["path"]}"><p class="postcard__meta"><time datetime="{esc(p["date"])}">{human_date(p["date"])}</time> · {p["minutes"]} min</p>'
            f'<{tag} class="postcard__title">{esc(p["title"])}</{tag}><p class="postcard__desc">{esc(p["description"])}</p></a>{tags_html(p["tags"])}</li>')


def index_page(posts):
    url = SITE + "/blog/"
    title = "Field notes: DevOps, Kubernetes and DevSecOps in practice | Kalislav Smirnov"
    desc = "Hands-on notes from a DevOps engineer: Kubernetes, GitLab CI/CD, Terraform, Proxmox, air-gapped networks and security checks in pipelines."
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": title, "description": desc, "inLanguage": "en",
         "author": {"@id": AUTHOR_ID}, "mainEntity": {"@id": url + "#blog"}},
        {"@type": "Blog", "@id": url + "#blog", "url": url, "name": "Field notes", "author": {"@id": AUTHOR_ID},
         "blogPost": [{"@type": "BlogPosting", "headline": p["title"], "url": p["url"], "datePublished": p["date"]} for p in posts]}]}
    items = "".join(card(p) for p in posts) if posts else '<li class="postlist__empty">The first notes are on their way.</li>'
    page_head = head(title, desc, url, SITE + "/og.jpg?v=20261020", "Field notes by Kalislav Smirnov", ld, "website")
    if not posts:  # an empty list page should not be indexed
        page_head = page_head.replace('  <link rel="canonical"', '  <meta name="robots" content="noindex">\n  <link rel="canonical"', 1)
    return (page_head + topbar() + f"""
  <main id="main" class="wrap post">
    <header class="chapter__head blog-head">
      <p class="label"><span class="label__dot" aria-hidden="true"></span>Field notes</p>
      <h1 class="chapter__title">What I learned building platforms that banks trust.</h1>
      <p class="chapter__lead">{esc(desc)}</p>
    </header>
    <ul class="postlist">{items}</ul>
{author_box()}
  </main>
""" + FOOTER)


def rss(posts):
    def rfc(d):
        return datetime.datetime.combine(datetime.date.fromisoformat(d), datetime.time(9, 0), datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = "".join(f"""
    <item>
      <title>{esc(p["title"])}</title>
      <link>{p["url"]}</link>
      <guid isPermaLink="true">{p["url"]}</guid>
      <pubDate>{rfc(p["date"])}</pubDate>
      <description>{esc(p["description"])}</description>
{"".join(f"      <category>{esc(t)}</category>" + chr(10) for t in p["tags"])}    </item>""" for p in posts)
    last = rfc(max((p["updated"] for p in posts), default="2026-10-21"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Field notes · Kalislav Smirnov</title>
    <link>{SITE}/blog/</link>
    <atom:link href="{SITE}/blog/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Hands-on DevOps, Kubernetes and DevSecOps notes.</description>
    <language>en</language>
    <lastBuildDate>{last}</lastBuildDate>{items}
  </channel>
</rss>
"""


# ---------------------------------------------------------------- integration with existing files

def between(text, name, new, path):
    a, b = f"<!-- blog:{name} -->", f"<!-- /blog:{name} -->"
    if text.count(a) != 1 or text.count(b) != 1:
        sys.exit(f"build-blog: {path}: expected one {a} … {b} block")
    pre, rest = text.split(a)
    _, post = rest.split(b)
    return pre + a + new + b + post


def update_index(posts):
    p = SITE_DIR / "index.html"
    t = p.read_text()
    nav = '<a href="/blog/" data-i18n="nav.blog">Field notes</a>' if posts else ""
    t = between(t, "nav", nav, p)
    latest = ""
    if posts:
        latest = ('\n      <section class="block" id="field-notes" aria-labelledby="notes-title">\n'
                  '        <h3 class="block__title reveal" id="notes-title" data-i18n="blog.latest">Latest field notes</h3>\n'
                  '        <ul class="postlist postlist--compact">'
                  + "".join(f'<li class="postcard reveal"><a href="{q["path"]}"><p class="postcard__meta"><time datetime="{esc(q["date"])}">{human_date(q["date"])}</time></p>'
                            f'<h4 class="postcard__title">{esc(q["title"])}</h4></a></li>' for q in posts[:3])
                  + '</ul>\n        <a class="link-arrow" href="/blog/" data-i18n="blog.all">All field notes →</a>\n      </section>\n      ')
    t = between(t, "latest", latest, p)
    p.write_text(t)


def update_sitemaps(posts):
    sx = SITE_DIR / "sitemap.xml"
    t = sx.read_text()
    t = re.sub(r"\s*<url>\s*<loc>https://kalik8s\.com/blog/[^<]*</loc>.*?</url>", "", t, flags=re.S)
    if posts:
        urls = [(SITE + "/blog/", max(p["updated"] for p in posts))] + [(p["url"], p["updated"]) for p in posts]
        block = "".join(f"\n  <url>\n    <loc>{u}</loc>\n    <lastmod>{d}</lastmod>\n  </url>" for u, d in urls)
        t = t.replace("\n</urlset>", block + "\n</urlset>")
    sx.write_text(t)
    st = SITE_DIR / "sitemap.txt"
    lines = [l for l in st.read_text().splitlines() if l.strip() and not l.startswith(SITE + "/blog/")]
    if posts:
        lines += [SITE + "/blog/"] + [p["url"] for p in posts]
    st.write_text("\n".join(lines) + "\n")
    ll = SITE_DIR / "llms.txt"
    lt = ll.read_text()
    if "<!-- blog:llms -->" not in lt:
        lt = lt.replace("\n## Optional", "\n<!-- blog:llms --><!-- /blog:llms -->\n\n## Optional", 1)
    body = ""
    if posts:
        body = "\n## Field notes\n\n" + "".join(f"- [{p['title']}]({p['url']}): {p['description']}\n" for p in posts)
    ll.write_text(between(lt, "llms", body, ll))


# ---------------------------------------------------------------- og images (local, optional)

OG_HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;800&family=JetBrains+Mono:wght@500&display=swap">
<style>
html,body{{margin:0;width:1200px;height:630px;overflow:hidden;background:#fdf6ec;font-family:Unbounded}}
.img{{position:absolute;right:0;top:0;bottom:56px;width:520px;background:url({bg}) 70% 60%/cover;border-left:3px solid #1b1410}}
.t{{position:absolute;left:64px;top:60px;width:560px}}
.l{{font:500 17px 'JetBrains Mono';letter-spacing:.16em;color:#4f4239;display:flex;gap:12px;align-items:center;text-transform:uppercase}}
.l i{{width:12px;height:12px;border-radius:50%;background:#ff6a3d}}
h1{{margin:26px 0 0;font-weight:800;font-size:{size}px;line-height:1.02;letter-spacing:-.04em;color:#1b1410}}
.b{{position:absolute;left:0;right:0;bottom:0;height:56px;background:#1b1410;color:#fdf6ec;font:500 17px 'JetBrains Mono';letter-spacing:.12em;display:flex;align-items:center;gap:28px;padding-left:64px}}
.b b{{color:#ff6a3d;font-family:Unbounded}}
</style></head><body><div class="img"></div>
<div class="t"><div class="l"><i></i>Field notes · {tag}</div><h1>{title}</h1></div>
<div class="b"><span><b>KALISLAV SMIRNOV</b></span><span>DEVOPS ENGINEER</span><span>KALIK8S.COM</span></div></body></html>"""


def render_og(posts):
    shot = ROOT / "scripts/og-shot.mjs"
    bgs = ["payload", "flightlog", "origin", "ground", "contact", "launch-169"]
    for n, p in enumerate(posts):
        size = 54 if len(p["title"]) < 50 else 44 if len(p["title"]) < 80 else 36
        bg = (SITE_DIR / "media" / f"{bgs[n % len(bgs)]}.webp").as_uri()
        with tempfile.TemporaryDirectory() as d:
            page = pathlib.Path(d) / "og.html"
            page.write_text(OG_HTML.format(bg=bg, size=size, tag=esc(p["tags"][0] if p["tags"] else "DevOps"), title=esc(p["title"])))
            target = OUT / p["slug"] / "og.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["node", str(shot), page.as_uri(), str(target), "1200", "630"], check=True)
            print(f"og: {target.relative_to(ROOT)}")


def main():
    drafts = "--drafts" in sys.argv
    posts = load(drafts)
    if "--og" in sys.argv:
        render_og(posts)
    OUT.mkdir(parents=True, exist_ok=True)
    keep = {p["slug"] for p in posts}
    for d in OUT.iterdir():
        if d.is_dir() and d.name not in keep:
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
            print(f"removed blog/{d.name}/")
    for p in posts:
        (OUT / p["slug"]).mkdir(exist_ok=True)
        (OUT / p["slug"] / "index.html").write_text(post_page(p, posts))
        print(f"wrote blog/{p['slug']}/")
    (OUT / "index.html").write_text(index_page(posts))
    (OUT / "feed.xml").write_text(rss(posts))
    update_index(posts)
    update_sitemaps(posts)
    print(f"build-blog: {len(posts)} post(s){' incl. drafts' if drafts else ''}")


if __name__ == "__main__":
    main()
