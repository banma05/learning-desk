import tempfile
import unittest
from pathlib import Path

from hub.notes import STATUS_ICON, parse_note

FIXTURES = Path(__file__).parent / "fixtures"


class ParseNoteTest(unittest.TestCase):
    def test_note_metadata_full_and_halfwidth_colons(self):
        note, errors = parse_note(FIXTURES / "项目/业务/样例笔记.md")
        self.assertEqual(note.title, "样例笔记")
        self.assertEqual((note.status, note.updated), ("已掌握", "2025-10-23"))
        self.assertEqual(note.images, ["a.svg", "b.png"])
        self.assertEqual(note.code, "`X.y`")
        self.assertFalse(note.body_md.lstrip().startswith(">"))
        self.assertIn("> 比喻里的引用块不是元数据", note.body_md)
        self.assertEqual(errors, [])

    def test_note_bad_status_reported(self):
        note, errors = parse_note(FIXTURES / "坏状态笔记.md")
        self.assertIsNone(note.status)
        self.assertIn("状态不合法：精通", str(errors[0]))

    def test_note_with_bom_crlf(self):
        note, _ = parse_note(FIXTURES / "bom_crlf_note.md")
        self.assertEqual(note.status, "学习中")
        self.assertEqual(note.title, "CRLF")

    def test_note_points_prereqs_and_status_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "n.md"
            path.write_text(
                "# 标题\n\n> 状态: 学习中\n> 要先懂: 甲, 乙\n\n正文\n\n## 知识点\n- 丙 | 状态: 学习中\n",
                encoding="utf-8",
            )
            note, errors = parse_note(path)
        self.assertEqual(errors, [])
        self.assertEqual(note.status_line, 3)
        self.assertEqual(note.prereqs, ["甲", "乙"])
        self.assertEqual(len(note.points), 1)
        self.assertNotIn("## 知识点", note.body_md)
        self.assertIn("正文", note.body_md)

    def test_note_without_knowledge_section_has_no_points(self):
        note, _ = parse_note(FIXTURES / "项目/业务/样例笔记.md")
        self.assertEqual((note.points, note.prereqs), ([], []))
        self.assertEqual(note.status_line, 3)

    def test_crlf_note_line_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crlf.md"
            text = "# CRLF\n\n> 状态: 学习中\n\nbody\n\n## 知识点\n- 甲\n- 乙\n"
            path.write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
            note, _ = parse_note(path)
        self.assertEqual(note.status_line, 3)
        self.assertEqual([(p.name, p.line) for p in note.points], [("甲", 8), ("乙", 9)])

    def test_note_without_status_has_zero_status_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "n.md"
            path.write_text("# 标题\n\n> 更新: 2025-11-02\n\n正文\n", encoding="utf-8")
            note, _ = parse_note(path)
        self.assertEqual(note.status_line, 0)

    def test_status_icons(self):
        self.assertEqual(STATUS_ICON[None], "📄")
        self.assertEqual(STATUS_ICON["只看过"], "👀")

    def test_gbk_file_does_not_crash(self):
        note, _ = parse_note(FIXTURES / "gbk_note.md")
        self.assertEqual(note.title, "GBK笔记")
        self.assertEqual(note.status, "学习中")


if __name__ == "__main__":
    unittest.main()
