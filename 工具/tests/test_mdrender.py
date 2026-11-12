import unittest

from hub.mdrender import render_markdown


class RenderMarkdownTest(unittest.TestCase):
    def test_renders_table_and_fenced_code(self):
        html = render_markdown("| a |\n|---|\n| 1 |\n\n```\nx\n```\n")
        self.assertIn("<table>", html)
        self.assertIn("<pre><code>x", html)

    def test_list_right_after_paragraph_is_still_a_list(self):
        html = render_markdown("每走一步都去看表。\n- 产出：笔记\n- 顺手验证\n")
        self.assertIn("<li>产出：笔记</li>", html)

    def test_list_marker_inside_code_block_untouched(self):
        html = render_markdown("```\na\n- b\n```\n")
        self.assertIn("a\n- b", html)


if __name__ == "__main__":
    unittest.main()
