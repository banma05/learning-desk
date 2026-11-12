import tempfile
import unittest
from pathlib import Path

from hub.plans import load_days, parse_day, ratio_label

FIXTURES = Path(__file__).parent / "fixtures"


class PlansTest(unittest.TestCase):
    def test_tasks_and_ratio(self):
        day, errors = parse_day(FIXTURES / "计划/2025-10-24.md")
        self.assertEqual(day.date, "2025-10-24")
        self.assertEqual(day.title, "2025-10-24（第 4 天）")
        self.assertEqual(day.tasks[2], ("Nacos 查超时", False))
        self.assertEqual(ratio_label(day), "2/3 完成")
        self.assertEqual(errors, [])

    def test_migrated_day_without_plan_has_no_ratio(self):
        day, _ = parse_day(FIXTURES / "计划/2025-10-21.md")
        self.assertIsNone(day.tasks)
        self.assertIsNone(ratio_label(day))

    def test_empty_plan_section_is_zero_of_zero_not_none(self):
        day, _ = parse_day(FIXTURES / "计划/2025-10-25.md")
        self.assertEqual(day.tasks, [])
        self.assertEqual(ratio_label(day), "0/0 完成")

    def test_days_sorted_desc_and_overview_skipped(self):
        days, errors = load_days(FIXTURES / "计划")
        self.assertEqual([d.date for d in days], ["2025-10-25", "2025-10-24", "2025-10-21"])
        self.assertEqual(errors, [])

    def test_load_days_skips_overview_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "总计划.md").write_text("# 总计划\n", encoding="utf-8")
            (Path(tmp) / "2026-01-02.md").write_text("# 2026-01-02\n\n## 今日计划\n- [ ] 甲\n", encoding="utf-8")
            days, errors = load_days(Path(tmp))
        self.assertEqual(([d.date for d in days], errors), (["2026-01-02"], []))

    def test_other_names_are_reported_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "笔记.md").write_text("# 笔记\n", encoding="utf-8")
            days, errors = load_days(Path(tmp))
        self.assertEqual(days, [])
        self.assertEqual([e.message for e in errors], ["计划/ 下只放 YYYY-MM-DD.md 和 总计划.md"])

    def test_plan_is_brief_and_log_is_detail(self):
        day, _ = parse_day(FIXTURES / "计划/2025-10-24.md")
        self.assertTrue(day.brief_md.startswith("## 今日计划"))
        self.assertNotIn("做了什么", day.brief_md)
        self.assertTrue(day.detail_md.startswith("## 做了什么"))

    def test_day_without_headings_is_all_detail(self):
        day, _ = parse_day(FIXTURES / "计划/2025-10-21.md")
        self.assertEqual(day.brief_md, "")
        self.assertEqual(day.detail_md, day.body_md)

    def test_review_is_shown_with_the_plan(self):
        text = ("# 2025-11-13（第 24 天）\n\n## 今日计划\n- [x] 甲\n\n## 要点\n- 一件\n\n"
                "## 做了什么\n- 细\n\n## 复盘\n- 计划 1/1\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2025-11-13.md"
            path.write_text(text, encoding="utf-8")
            day, _ = parse_day(path)
        self.assertIn("## 复盘", day.brief_md)
        self.assertNotIn("## 复盘", day.detail_md)

    def test_brief_holds_plan_and_points_only(self):
        text = ("# 2025-11-06（第 17 天）\n\n## 今日计划\n- [x] 甲\n- [ ] 乙\n\n"
                "## 要点\n- 一件大事\n\n## 做了什么\n- 很细的一行\n\n## 搞懂了\n- 一条\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2025-11-06.md"
            path.write_text(text, encoding="utf-8")
            day, errors = parse_day(path)
        self.assertEqual(errors, [])
        self.assertIn("## 要点\n- 一件大事", day.brief_md)
        self.assertIn("- [ ] 乙", day.brief_md)
        self.assertNotIn("很细的一行", day.brief_md)
        self.assertIn("## 做了什么", day.detail_md)
        self.assertIn("## 搞懂了", day.detail_md)
        self.assertEqual(ratio_label(day), "1/2 完成")

    def test_bad_filename_reported(self):
        _, errors = parse_day(FIXTURES / "计划坏名/10-24.md")
        self.assertIn("文件名应为 YYYY-MM-DD.md", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
