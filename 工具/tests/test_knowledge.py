import unittest

from hub.errors import FormatError
from hub.knowledge import split_points

BODY = (
    "## 一句话\n正文\n\n## 知识点\n"
    "- 运费怎么算 | 状态: 学习中 | 要先懂: 付款计划两组列, 书款与到手 | 一句话: 每天按未付书款 × 日运费率累加 -> #四、第二遍\n"
    "- 付款计划两组列 | 别名: order_original_book_amount, 未付书款\n"
)


class SplitPointsTest(unittest.TestCase):
    def test_points_parsed_and_section_removed(self):
        body, points, errors = split_points(BODY, 10, "a.md")
        self.assertEqual(errors, [])
        self.assertNotIn("## 知识点", body)
        self.assertIn("正文", body)
        p = points[0]
        self.assertEqual(
            (p.name, p.status, p.prereqs, p.anchor, p.line),
            ("运费怎么算", "学习中", ["付款计划两组列", "书款与到手"], "四、第二遍", 14),
        )
        self.assertEqual(p.summary, "每天按未付书款 × 日运费率累加")
        self.assertTrue(p.raw.startswith("- 运费怎么算"))
        self.assertNotIn("\n", p.raw)
        self.assertEqual(points[1].status, "没碰")
        self.assertEqual(points[1].aliases, ["order_original_book_amount", "未付书款"])
        self.assertEqual(points[1].line, 15)

    def test_fullwidth_colon_and_list_separators(self):
        text = "## 知识点\n- 甲 | 状态：已掌握 | 要先懂：乙、丙，丁 | 一句话: 先扣, 后收\n"
        _, points, errors = split_points(text, 1, "a.md")
        self.assertEqual(errors, [])
        self.assertEqual(points[0].status, "已掌握")
        self.assertEqual(points[0].prereqs, ["乙", "丙", "丁"])
        self.assertEqual(points[0].summary, "先扣, 后收")

    def test_confusions_field(self):
        _, points, _ = split_points("## 知识点\n- 甲 | 容易混淆: 乙, 丙\n", 1, "a.md")
        self.assertEqual(points[0].confusions, ["乙", "丙"])

    def test_section_ends_at_next_heading(self):
        text = "## 知识点\n- 甲\n\n## 相关问题\n- 这行留在正文\n"
        body, points, errors = split_points(text, 1, "a.md")
        self.assertEqual([p.name for p in points], ["甲"])
        self.assertEqual(errors, [])
        self.assertIn("## 相关问题", body)
        self.assertIn("这行留在正文", body)
        self.assertNotIn("## 知识点", body)

    def test_errors_reported_with_line_numbers(self):
        text = (
            "## 知识点\n"
            "随便写一行\n"
            "- | 状态: 已掌握\n"
            "- 乙 | 状态: 懂了\n"
            "- 丙 | 颜色: 红\n"
            "- 丁\n"
            "- 丁 | 一句话: 又来一次\n"
        )
        _, points, errors = split_points(text, 20, "a.md")
        self.assertEqual(
            errors,
            [
                FormatError("a.md", 21, "知识点小节里只能写 '- 名称 | …' 列表项"),
                FormatError("a.md", 22, "知识点缺名称"),
                FormatError("a.md", 23, "知识点状态不合法：懂了"),
                FormatError("a.md", 24, "知识点字段不认识：颜色"),
                FormatError("a.md", 26, "知识点重复：丁"),
            ],
        )
        self.assertEqual([p.name for p in points], ["乙", "丙", "丁"])

    def test_no_section_returns_body_unchanged(self):
        text = "## 一句话\n正文\n"
        body, points, errors = split_points(text, 5, "a.md")
        self.assertEqual((body, points, errors), (text, [], []))

    def test_section_at_end_of_file_without_trailing_newline(self):
        body, points, errors = split_points("正文\n\n## 知识点\n- 甲", 1, "a.md")
        self.assertEqual((body, [p.name for p in points], errors), ("正文", ["甲"], []))
        self.assertEqual(points[0].line, 4)

    def test_raw_is_exact_file_line(self):
        line1 = "- 甲 | 状态: 学习中   "
        line2 = "- 乙 | 一句话: x -> #小节\t"
        _, points, _ = split_points("## 知识点\n" + line1 + "\n" + line2 + "\n", 1, "a.md")
        self.assertEqual([p.raw for p in points], [line1, line2])
        self.assertEqual(points[1].anchor, "小节")

    def test_bare_dash_reports_missing_name(self):
        _, points, errors = split_points("## 知识点\n- \n-\n", 1, "a.md")
        self.assertEqual(points, [])
        self.assertEqual(
            errors,
            [FormatError("a.md", 2, "知识点缺名称"), FormatError("a.md", 3, "知识点缺名称")],
        )

    def test_empty_fields_from_trailing_pipe_are_skipped(self):
        _, points, errors = split_points("## 知识点\n- 乙 | \n- 丙 | 状态: 学习中 |\n", 1, "a.md")
        self.assertEqual(errors, [])
        self.assertEqual([(p.name, p.status) for p in points], [("乙", "没碰"), ("丙", "学习中")])

    def test_repeated_field_reported_and_last_value_kept(self):
        _, points, errors = split_points("## 知识点\n- 甲 | 状态: 已掌握 | 一句话: a | 状态：没碰\n", 5, "a.md")
        self.assertEqual(errors, [FormatError("a.md", 6, "知识点字段重复：状态")])
        self.assertEqual(points[0].status, "没碰")

    def test_arrow_without_hash_is_not_an_anchor(self):
        _, points, _ = split_points("## 知识点\n- 甲 | 一句话: a -> b\n", 1, "a.md")
        self.assertEqual((points[0].summary, points[0].anchor), ("a -> b", ""))


if __name__ == "__main__":
    unittest.main()
