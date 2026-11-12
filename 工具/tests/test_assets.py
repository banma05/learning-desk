import unittest
from pathlib import Path

from hub.assets import AssetBook

FIXTURES = Path(__file__).parent / "fixtures"
NOTE = FIXTURES / "笔记/a.md"


class AssetBookTest(unittest.TestCase):
    def setUp(self):
        self.book = AssetBook(FIXTURES)

    def test_encoded_unicode_path_resolves_and_prefers_svg(self):
        out = self.book.rewrite('<img src="../图/带%20空格%20②.png">', NOTE)
        self.assertIn('src="data:image/svg+xml;base64,', out)
        self.assertEqual(self.book.errors, [])

    def test_png_without_svg_embedded_as_png(self):
        out = self.book.rewrite('<p><img alt="x" src="../图/仅png.png"></p>', NOTE)
        self.assertIn('src="data:image/png;base64,', out)
        self.assertIn('alt="x"', out)
        self.assertTrue(out.startswith("<p>") and out.endswith("</p>"))

    def test_link_to_image_opens_overlay(self):
        out = self.book.rewrite('<a href="../图/仅png.png">图</a>', NOTE)
        self.assertIn('href="#" data-img="', out)
        self.assertEqual(len(self.book.images()), 1)

    def test_md_link_becomes_doc_anchor_and_is_pending(self):
        out = self.book.rewrite('<a href="../外部/附页.md">x</a>', NOTE)
        doc_id = self.book.register_doc(FIXTURES / "外部/附页.md")
        self.assertIn(f'href="#doc-{doc_id}"', out)
        self.assertEqual(self.book.pending_docs(), [(FIXTURES / "外部/附页.md").resolve()])

    def test_rendered_doc_no_longer_pending(self):
        self.book.rewrite('<a href="../外部/附页.md">x</a>', NOTE)
        self.book.mark_rendered(FIXTURES / "外部/附页.md")
        self.assertEqual(self.book.pending_docs(), [])

    def test_md_link_inside_attachment_not_followed(self):
        out = self.book.rewrite('<a href="附页.md">x</a>', FIXTURES / "外部/附页.md", attachment=True)
        self.assertIn('href="file:///', out)
        self.assertEqual(self.book.pending_docs(), [])

    def test_csv_and_absolute_paths_become_file_urls(self):
        absolute = (FIXTURES / "外部/数据.csv").resolve().as_posix()
        out = self.book.rewrite(f'<a href="../外部/数据.csv">c</a><a href="{absolute}">d</a>', NOTE)
        self.assertEqual(out.count('href="file:///'), 2)
        self.assertIn("数据.csv", out)

    def test_web_links_and_anchors_untouched(self):
        html = '<a href="https://example.com/x">w</a><a href="#top">t</a>'
        self.assertEqual(self.book.rewrite(html, NOTE), html)

    def test_missing_file_marked_broken(self):
        out = self.book.rewrite('<a href="../没有.md">x</a>', NOTE)
        self.assertIn('class="broken"', out)
        self.assertEqual(str(self.book.errors[0]), "a.md:0 文件不存在：../没有.md")

    def test_link_to_mapped_file_jumps_to_section(self):
        self.book.map_section(FIXTURES / "外部/附页.md", "成果")
        out = self.book.rewrite('<a href="../外部/附页.md">x</a>', NOTE)
        self.assertIn('href="#成果"', out)
        self.assertEqual(self.book.pending_docs(), [])

    def test_mapped_directory_prefix_jumps_to_section(self):
        self.book.map_section(FIXTURES / "外部", "计划")
        out = self.book.rewrite('<a href="../外部/附页.md">x</a>', NOTE)
        self.assertIn('href="#计划"', out)

    def test_backlinks_recorded(self):
        self.book.rewrite('<a href="../外部/附页.md">x</a>', NOTE)
        self.book.rewrite('<a href="../外部/附页.md">y</a>', NOTE)
        self.assertEqual(self.book.backlinks(FIXTURES / "外部/附页.md"), [NOTE.resolve()])


if __name__ == "__main__":
    unittest.main()
