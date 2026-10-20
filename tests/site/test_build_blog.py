"""Unit tests for the Markdown subset in scripts/build-blog.py. Run: python3 -m unittest discover -s tests/site -p 'test_*.py'"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_blog", ROOT / "scripts/build-blog.py")
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class Inline(unittest.TestCase):
    def test_raw_html_is_escaped(self):
        self.assertEqual(B.inline("a <script>x</script> & b"), "a &lt;script&gt;x&lt;/script&gt; &amp; b")

    def test_code_span_keeps_markup_literal(self):
        self.assertEqual(B.inline("`<b> & **x**`"), "<code>&lt;b&gt; &amp; **x**</code>")

    def test_internal_and_external_links(self):
        self.assertEqual(B.inline("[cv](/#cases)"), '<a href="/#cases">cv</a>')
        self.assertEqual(B.inline("[k](https://kubernetes.io/)"), '<a href="https://kubernetes.io/" target="_blank" rel="noopener">k</a>')

    def test_dangerous_schemes_are_dropped(self):
        self.assertIn('href="#"', B.inline("[x](javascript:alert)"))
        self.assertIn('href="#"', B.inline("[x](data:text/html,hi)"))
        self.assertIn('src="#"', B.inline("![x](JavaScript:alert)"))

    def test_quotes_and_brackets_in_attributes_are_escaped(self):
        img = B.inline('![a" onerror="x <b>](/i.png "t <q> & co")')
        self.assertIn('alt="a&quot; onerror=&quot;x &lt;b&gt;"', img)
        self.assertIn('title="t &lt;q&gt; &amp; co"', img)
        self.assertNotIn('" onerror="', img)
        link = B.inline('[x](https://e.com/a"onmouseover="y "ti <b> & co")')
        self.assertIn('href="https://e.com/a&quot;onmouseover=&quot;y"', link)
        self.assertIn('title="ti &lt;b&gt; &amp; co"', link)

    def test_emphasis_but_not_inside_snake_case(self):
        self.assertEqual(B.inline("**b** *i* _j_"), "<strong>b</strong> <em>i</em> <em>j</em>")
        self.assertEqual(B.inline("snake_case_name"), "snake_case_name")


class Blocks(unittest.TestCase):
    def test_code_fence_escapes_and_labels_language(self):
        html, _ = B.markdown("```yaml\na: <b> & c\n```")
        self.assertIn('<pre class="code"><span class="code__lang">yaml</span><code class="language-yaml">a: &lt;b&gt; &amp; c</code></pre>', html)

    def test_fence_without_language_and_markdown_inside_is_literal(self):
        html, _ = B.markdown("```\n**not bold** [x](y)\n```")
        self.assertIn("<code>**not bold** [x](y)</code>", html)

    def test_headings_get_unique_ids_and_toc_entries(self):
        html, heads = B.markdown("## Setup\n\n## Setup\n\n### Step `one`")
        self.assertIn('<h2 id="setup">Setup</h2>', html)
        self.assertIn('<h2 id="setup-2">Setup</h2>', html)
        self.assertEqual([h[:2] for h in heads], [(2, "setup"), (2, "setup-2"), (3, "step-one")])

    def test_lists_tables_quotes(self):
        html, _ = B.markdown("1. a\n2. b\n\n- x\n- y\n\n| A | B |\n|---|--:|\n| 1 | 2 |\n\n> q")
        self.assertIn("<ol><li>a</li><li>b</li></ol>", html)
        self.assertIn("<ul><li>x</li><li>y</li></ul>", html)
        self.assertIn('<th>A</th><th class="ta-right">B</th>', html)
        self.assertIn("<blockquote><p>q</p></blockquote>", html)


if __name__ == "__main__":
    unittest.main()


class LinkWithCode(unittest.TestCase):
    def test_code_inside_link_label(self):
        out = B.inline("see [`allow_failure: exit_codes`](https://docs.gitlab.com/ci/yaml/#x) now")
        self.assertIn('<a href="https://docs.gitlab.com/ci/yaml/#x"', out)
        self.assertIn("<code>allow_failure: exit_codes</code></a>", out)

    def test_code_is_not_formatted(self):
        out = B.inline("`a_b_c` and `**x**` <b>")
        self.assertIn("<code>a_b_c</code>", out)
        self.assertIn("<code>**x**</code>", out)
        self.assertIn("&lt;b&gt;", out)


class CodeInAttributes(unittest.TestCase):
    def test_code_in_alt_title_and_url_stays_plain_text(self):
        out = B.inline('![`<b>"x"`](/a.png "`t"q`") [l](`javascript:alert(1)`) [m](/p "`"><s>`")')
        self.assertNotIn("<code>", out.split("<a")[0].split(">", 1)[0])
        self.assertNotIn('alt="<code>', out)
        self.assertNotIn("<s>", out)
        self.assertNotIn('"><', out.replace('"><code', ''))
        self.assertNotIn("javascript:", out)

    def test_forged_placeholder_is_removed(self):
        out = B.inline("a \x000\x00 `x`")
        self.assertEqual(out.count("<code>"), 1)
