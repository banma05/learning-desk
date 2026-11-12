import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from hooks.session_start import build_status, main

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"


class SessionStartTest(unittest.TestCase):
    def test_status_lists_unchecked_and_max_numbers(self):
        s = build_status(SAMPLE, date(2025, 10, 24))
        self.assertIn("今日计划：", s)
        self.assertIn("- c", s)
        self.assertNotIn("- a", s)
        self.assertIn("问题最大编号：Q1", s)

    def test_status_when_files_missing(self):
        s = build_status(FIXTURES / "空知识库", date(2025, 10, 26))
        self.assertIn("今日计划：还没建", s)
        self.assertIn("问题.md 不存在", s)
        self.assertLessEqual(len(s), 1500)

    def test_overview_all_weeks_past(self):
        s = build_status(FIXTURES / "路线全完成", date(2025, 10, 26))
        self.assertIn("本周：总计划的进度表已经排完，请和使用者确认下一段", s)

    def test_no_week_line_without_overview(self):
        s = build_status(FIXTURES / "空知识库", date(2025, 10, 26))
        self.assertNotIn("本周", s)

    def test_this_week_row_on_a_workday(self):
        s = build_status(FIXTURES / "昨天缺日志", date(2025, 10, 24))
        self.assertIn("本周（总计划进度表 10-20 至 10-24）：交付：交付甲；业务块（累计讲得出）：块一（6）\n", s)
        self.assertNotIn("做完了", s)

    def test_weekend_shows_next_week_with_ditto_filled(self):
        s = build_status(FIXTURES / "昨天缺日志", date(2025, 10, 25))
        self.assertIn("本周（总计划进度表 10-27 至 10-31）：交付：交付甲；业务块（累计讲得出）：块二（7）；节点：10-29", s)
        self.assertIn("上次日志（2025-10-24）：缺「搞懂了」", s)
        self.assertNotIn("「卡在哪里」", s)

    def test_week_crossing_new_year(self):
        for today in (date(2026, 12, 31), date(2027, 1, 1)):
            s = build_status(FIXTURES / "昨天缺日志", today)
            self.assertIn("本周（总计划进度表 12-28 至 01-01）：交付：交付甲；业务块（累计讲得出）：块三（8）", s)
        s = build_status(FIXTURES / "昨天缺日志", date(2027, 1, 2))
        self.assertIn("本周：总计划的进度表已经排完", s)

    def test_previous_log_gap_found_across_weekend(self):
        s = build_status(FIXTURES / "昨天缺日志", date(2025, 10, 27))
        self.assertIn("上次日志（2025-10-24）：缺「搞懂了」", s)

    def test_no_previous_log_line_when_none(self):
        s = build_status(FIXTURES / "空知识库", date(2025, 10, 27))
        self.assertNotIn("上次日志", s)

    def test_main_outputs_json(self):
        buf = io.StringIO()
        with mock.patch("hooks.session_start._root", return_value=SAMPLE), redirect_stdout(buf):
            self.assertEqual(main("{}"), 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("今日计划", payload["hookSpecificOutput"]["additionalContext"])

    def test_main_survives_errors(self):
        buf = io.StringIO()
        with mock.patch("hooks.session_start.build_status", side_effect=RuntimeError("boom")), \
                mock.patch("hooks.session_start._log"), redirect_stdout(buf):
            self.assertEqual(main("{}"), 0)
        self.assertIn("状态读取失败", buf.getvalue())

    def test_reports_format_hints_and_recent_hook_errors(self):
        import shutil, tempfile
        from datetime import datetime, timedelta
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(FIXTURES / "空知识库", root, dirs_exist_ok=True)
            (root / "工具").mkdir()
            (root / "工具" / "hook-status.json").write_text(
                json.dumps({"time": "2025-10-26 09:00", "errors": ["问题.md:5 编号重复：Q6", "a", "b", "c"]},
                           ensure_ascii=False), encoding="utf-8")
            now = datetime(2025, 10, 26, 10, 0)
            old = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
            new = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            (root / "工具" / "hook.log").write_text(f"{old} on_edit x\n{new} on_edit y\n", encoding="utf-8")
            s = build_status(root, date(2025, 10, 26), now=now)
        self.assertIn("格式提示：4 条", s)
        self.assertIn("编号重复：Q6", s)
        self.assertIn("钩子错误：最近 24 小时 1 条", s)


class RootTest(unittest.TestCase):
    def test_root_defaults_to_tool_parent(self):
        from hooks import session_start
        tool_dir = Path(session_start.__file__).resolve().parent.parent
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(session_start._root(), tool_dir.parent)
        with mock.patch.dict("os.environ", {"KB_ROOT": "X"}):
            self.assertEqual(session_start._root(), Path("X"))


class ConfigPrefixTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "问题.md").write_text(
            "| 编号 | 问题 | 所属 | 怎么查 | 状态 | 答案 | 来源/日期 |\n|---|---|---|---|---|---|---|\n"
            "| X3 | 甲 | 学习方法 | | 待解决 | | |\n| T2 | 乙 | 学习方法 | | 待解决 | | |\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_prefixes_from_config(self):
        (self.root / "学习台配置.json").write_text('{"问题编号前缀": {"X": "甲"}}', encoding="utf-8")
        self.assertIn("问题最大编号：X3\n", build_status(self.root, date(2026, 1, 5)) + "\n")

    def test_empty_progress_table_invites_planning(self):
        (self.root / "计划").mkdir()
        (self.root / "计划" / "总计划.md").write_text(
            "# 总计划\n\n## 三、进度表\n\n| 周 | 计划：交付 | 节点 |\n|---|---|---|\n", encoding="utf-8")
        self.assertIn("本周：总计划的进度表还是空的，可以和使用者一起排", build_status(self.root, date(2026, 1, 5)))

    def test_session_start_survives_broken_config(self):
        (self.root / "学习台配置.json").write_text("{", encoding="utf-8")
        self.assertIn("问题最大编号：T2", build_status(self.root, date(2026, 1, 5)))


if __name__ == "__main__":
    unittest.main()
