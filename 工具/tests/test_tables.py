import unittest
from pathlib import Path

from hub.tables import parse_md_table
from hub.textio import read_text

FIXTURES = Path(__file__).parent / "fixtures"


class ParseMdTableTest(unittest.TestCase):
    def test_parses_header_and_rows_with_line_numbers(self):
        text = "说明\n\n| 编号 | 问题 |\n|---|---|\n| Q1 | 为什么 |\n"
        header, rows, errors = parse_md_table(text, "问题.md")
        self.assertEqual(header, ["编号", "问题"])
        self.assertEqual(rows, [(5, {"编号": "Q1", "问题": "为什么"})])
        self.assertEqual(errors, [])

    def test_row_with_extra_pipe_is_reported_not_shifted(self):
        text = "| 编号 | 问题 |\n|---|---|\n| Q1 | a|b |\n"
        _, rows, errors = parse_md_table(text, "问题.md")
        self.assertEqual(rows, [])
        self.assertEqual(str(errors[0]), "问题.md:3 列数应为 2，实际为 3")

    def test_bom_and_crlf_are_tolerated(self):
        p = FIXTURES / "bom_crlf_table.md"
        header, rows, _ = parse_md_table(read_text(p), p.name)
        self.assertEqual(header, ["编号", "问题"])
        self.assertEqual(len(rows), 1)

    def test_blank_line_inside_table_does_not_drop_rows(self):
        text = "| 编号 | 问题 |\n|---|---|\n| Q1 | a |\n\n| Q2 | b |\n"
        _, rows, errors = parse_md_table(text, "问题.md")
        self.assertEqual([r[1]["编号"] for r in rows], ["Q1", "Q2"])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
