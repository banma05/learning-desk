import tempfile
import unittest
from pathlib import Path

from hub.records import load_outputs, load_questions, load_work

FIXTURES = Path(__file__).parent / "fixtures"
WORK = ["自己", "同事", "上级"]
HEADER = "| 编号 | 问题 | 所属 | 问谁 | 怎么查 | 状态 | 答案 | 来源/日期 |\n|---|---|---|---|---|---|---|---|\n"
NO_ASKER_HEADER = "| 编号 | 问题 | 所属 | 怎么查 | 状态 | 答案 | 来源/日期 |\n|---|---|---|---|---|---|---|\n"


def _questions_file(tmp: str, text: str) -> Path:
    path = Path(tmp) / "问题.md"
    path.write_text(text, encoding="utf-8")
    return path


class RecordsTest(unittest.TestCase):
    def test_question_enum_validation(self):
        _, rows, errors = load_questions(FIXTURES / "问题.md", WORK)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].fields["编号"], "Q1")
        self.assertIn("问谁不合法：导师", str(errors[0]))

    def test_questions_without_askers_need_no_asker_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _questions_file(tmp, NO_ASKER_HEADER + "| Q1 | 甲 | 学习方法 | | 待解决 | | 01-02 |\n")
            _, rows, errors = load_questions(path, [])
            self.assertEqual((len(rows), errors), (1, []))

    def test_questions_with_askers_validate_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _questions_file(tmp, HEADER + "| Q1 | 甲 | 学习方法 | 同事 | | 待解决 | | 01-02 |\n")
            _, _, errors = load_questions(path, ["自己"])
            self.assertEqual([str(e) for e in errors], ["问题.md:3 问谁不合法：同事"])

    def test_questions_intro_text_kept(self):
        intro, _, _ = load_questions(FIXTURES / "问题.md", WORK)
        self.assertIn("GMV 需求", intro)
        self.assertNotIn("| 编号", intro)

    def test_intro_drops_file_title(self):
        intro, _, _ = load_questions(FIXTURES / "问题.md", WORK)
        self.assertFalse(intro.startswith("# "))

    def test_outputs_missing_column(self):
        _, rows, errors = load_outputs(FIXTURES / "缺列成果.md")
        self.assertEqual(rows, [])
        self.assertIn("缺少列：所属", str(errors[0]))

    def test_work_enums_and_date(self):
        _, rows, errors = load_work(FIXTURES / "坏工作.md")
        self.assertEqual(len(rows), 1)
        self.assertIn("类型不合法：开会", str(errors[0]))
        self.assertIn("日期格式应为 YYYY-MM-DD：10-24", str(errors[1]))


if __name__ == "__main__":
    unittest.main()
