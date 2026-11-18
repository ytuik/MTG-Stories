from pathlib import Path
from bs4 import BeautifulSoup
import unittest

from mtg_epub.typst_html import _apply_structural_fixes, _apply_typst_polyfills, _matching_close_paren


class TestTypstHtml(unittest.TestCase):
    def test_matching_close_paren_handles_strings_and_nested_parens(self):
        text = 'conf("test (inside string)", (nested), final)'
        closing = _matching_close_paren(text, 4)
        self.assertEqual(closing, len(text) - 1)

    def test_matching_close_paren_ignores_quotes_inside_content_blocks(self):
        text = '#figure(image("a.png"), caption: [5" tall (left)]) rest "x)"'
        closing = _matching_close_paren(text, text.index("("))
        self.assertEqual(text[closing:], ') rest "x)"')

    def test_apply_typst_polyfills_removes_local_imports_and_conf_block(self):
        content = """#import "@local/mtgstory:0.2.0": conf
#show: doc => conf(
    "Episode 1",
    set_name: "Bloomburrow",
    story_date: datetime(day: 1, month: 7, year: 2024),
    author: "WotC",
    doc
)

The adventure begins here.
"""
        result = _apply_typst_polyfills(content)
        self.assertNotIn('@local/mtgstory', result)
        self.assertNotIn('#show: doc => conf', result)
        self.assertIn('The adventure begins here.', result)
        self.assertIn('// --- START POLYFILL ---', result)
        self.assertIn('#let letter_block', result)

    def test_ast_pov_heading_and_divider_transformation(self):
        html_input = """
        <html><body>
        <p><strong>Kaito</strong></p>
        <p>He drew his blade in silence.</p>
        <div><svg><polyline points="0,0 100,0"/></svg></div>
        <p>The shadows shifted.</p>
        </body></html>
        """
        soup = BeautifulSoup(html_input, "html.parser")

        _apply_structural_fixes(soup)

        body_str = str(soup.body)
        self.assertIn("<h2>Kaito</h2>", body_str)
        self.assertIn("<hr/>", body_str)
        self.assertNotIn("<polyline", body_str)


if __name__ == "__main__":
    unittest.main()
