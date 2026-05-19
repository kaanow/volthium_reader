"""Tests for `dashboard.Handler._markdown_to_html`.

The dashboard's `/today-report` and `/report/YYYY-MM-DD` routes pipe
the day-report markdown through this static helper to produce nice
HTML instead of raw <pre>. We don't pull in a markdown dependency,
so this function is the entire renderer — any regression here
breaks all report views.

Tests cover the subset of markdown that end_of_day_report.build_report
actually emits, plus edge cases (HTML-escaping, unrecognized lines).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dashboard  # noqa: E402


def md_to_html(md: str) -> str:
    return dashboard.Handler._markdown_to_html(md)


class TestMarkdownRenderer(unittest.TestCase):

    # ---------- headings ----------

    def test_h1_promotes_to_h2(self) -> None:
        """`# Title` becomes <h2> because the page already has its own
        <h1> as the page title."""
        html = md_to_html("# Day report — 2026-05-18 (Loon Lake)")
        self.assertIn("<h2>Day report", html)
        self.assertIn("</h2>", html)
        # Must NOT produce <h1> (would collide with page header)
        self.assertNotIn("<h1>", html)

    def test_h2_becomes_h3(self) -> None:
        """`## section` → <h3> so the visual hierarchy stays sane."""
        html = md_to_html("## Pack")
        self.assertIn("<h3>Pack</h3>", html)

    def test_h3_becomes_h4(self) -> None:
        html = md_to_html("### Subsection")
        self.assertIn("<h4>Subsection</h4>", html)

    # ---------- inline ----------

    def test_bold(self) -> None:
        html = md_to_html("Result: **Complete day**: harvest 122 %.")
        self.assertIn("<strong>Complete day</strong>", html)

    def test_italic(self) -> None:
        html = md_to_html("*(partial day so far)*")
        self.assertIn("<em>(partial day so far)</em>", html)

    def test_inline_code(self) -> None:
        html = md_to_html("See `data/pack.csv` for raw samples.")
        self.assertIn("<code>data/pack.csv</code>", html)

    def test_link(self) -> None:
        html = md_to_html("See [the docs](docs/site/loon_lake.md).")
        self.assertIn('<a href="docs/site/loon_lake.md">the docs</a>', html)

    def test_bold_and_italic_can_coexist(self) -> None:
        """**bold** and *italic* on the same line — neither pattern
        should swallow the other."""
        html = md_to_html("**peak charge** = *21.4 A*")
        self.assertIn("<strong>peak charge</strong>", html)
        self.assertIn("<em>21.4 A</em>", html)

    # ---------- lists ----------

    def test_list_items(self) -> None:
        html = md_to_html(
            "- Charge: +45.8 Ah\n"
            "- Discharge: −42.7 Ah\n"
            "- Net: +3.1 Ah\n"
        )
        self.assertIn("<ul>", html)
        self.assertIn("</ul>", html)
        self.assertEqual(html.count("<li>"), 3)
        self.assertIn("<li>Charge: +45.8 Ah</li>", html)

    def test_list_ends_at_blank_line(self) -> None:
        """A blank line separates a list from following content; the
        list should be properly closed before the next element."""
        html = md_to_html(
            "- first\n"
            "- second\n"
            "\n"
            "After list."
        )
        # </ul> must appear BEFORE the paragraph
        ul_close = html.index("</ul>")
        para_start = html.index("<p>After list.")
        self.assertLess(ul_close, para_start)

    def test_list_inline_formatting_works(self) -> None:
        """Bold/code inside a list item still renders inline."""
        html = md_to_html("- Peak charge: **21.4 A** from `pack.csv`")
        self.assertIn("<strong>21.4 A</strong>", html)
        self.assertIn("<code>pack.csv</code>", html)

    # ---------- tables ----------

    def test_table_renders_with_thead(self) -> None:
        html = md_to_html(
            "| timestamp | coef | source |\n"
            "|-----------|-----:|--------|\n"
            "| 13:13 | 7.000 | loop-iteration |\n"
            "| 21:05 | 8.230 | advisor-invocation |\n"
        )
        self.assertIn("<table>", html)
        self.assertIn("<thead>", html)
        self.assertIn("<th>timestamp</th>", html)
        self.assertIn("<th>coef</th>", html)
        self.assertIn("<tbody>", html)
        self.assertIn("<td>13:13</td>", html)
        self.assertIn("<td>8.230</td>", html)
        # The separator row (|---|---|) must NOT appear as data
        self.assertNotIn("<td>-----------</td>", html)

    def test_table_ends_at_non_table_line(self) -> None:
        """Table terminates when the next line is not a `| ... |` row."""
        html = md_to_html(
            "| a | b |\n"
            "|---|---|\n"
            "| 1 | 2 |\n"
            "\n"
            "After table."
        )
        table_close = html.index("</table>")
        after_text = html.index("After table.")
        self.assertLess(table_close, after_text)

    # ---------- escaping + safety ----------

    def test_user_content_is_html_escaped(self) -> None:
        """Markdown content can contain <, >, & — these must be
        escaped so they render as text, not HTML."""
        html = md_to_html("Pack reading: 13 < 14 < 15")
        # The literal '<' should appear escaped, not as a tag
        self.assertIn("&lt;", html)

    def test_bold_inside_paragraph_is_safe(self) -> None:
        """The bold pattern itself can't break out via unescaped HTML."""
        html = md_to_html("Result: **<script>alert(1)</script>**")
        # The script-tag-looking content gets escaped, so the page
        # stays safe even if the report ever contained user data.
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(md_to_html("").strip(), "")

    def test_blank_lines_only(self) -> None:
        """A bunch of empty lines shouldn't crash or produce stray
        elements."""
        html = md_to_html("\n\n\n")
        self.assertNotIn("<h", html)
        self.assertNotIn("<p>", html)
        self.assertNotIn("<ul>", html)

    def test_unrecognized_line_becomes_paragraph(self) -> None:
        """Anything that doesn't match a known pattern still renders
        as a <p> rather than disappearing."""
        html = md_to_html("Just a plain sentence.")
        self.assertIn("<p>Just a plain sentence.</p>", html)


if __name__ == "__main__":
    unittest.main()
