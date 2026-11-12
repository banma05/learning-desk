import unittest
from pathlib import Path

from hub.owners import check_owner, valid_owners
from hub.records import duplicate_numbers, load_questions
from hub.skeleton import parse_skeleton

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT = FIXTURES / "项目"
SKELETON = "- 业务 · 一本书的一生\n  - 交易\n    - 出库\n- 多仓差异与配送\n  - 包装与配送（待 上级 核实）\n"


class OwnersTest(unittest.TestCase):
    def setUp(self):
        roots, _ = parse_skeleton(SKELETON, "s", PROJECT)
        self.valid = valid_owners({"示例项目": roots}, [])

    def test_owner_normalization(self):
        self.assertIsNone(check_owner("示例项目/多仓差异与配送/包装与配送", self.valid, "问题.md", 3))
        self.assertIsNone(check_owner("示例项目/多仓差异与配送/包装与配送（待 上级 核实）", self.valid, "问题.md", 3))
        self.assertIsNone(check_owner(" 示例项目/业务/交易/出库 ", self.valid, "问题.md", 3))
        self.assertIsNone(check_owner("示例项目", self.valid, "问题.md", 3))
        self.assertIsNone(check_owner("学习方法", self.valid, "问题.md", 3))
        self.assertEqual(str(check_owner("示例项目/交易/出库", self.valid, "问题.md", 3)),
                         "问题.md:3 所属不存在：示例项目/交易/出库")

    def test_concept_owner(self):
        class C:
            name = "幂等"
        valid = valid_owners({}, [C()])
        self.assertIsNone(check_owner("概念/幂等", valid, "成果.md", 4))

    def test_duplicate_question_numbers(self):
        _, rows, _ = load_questions(FIXTURES / "撞号问题.md", [])
        self.assertEqual(str(duplicate_numbers(rows, "撞号问题.md")[0]), "撞号问题.md:6 编号重复：Q6")


if __name__ == "__main__":
    unittest.main()
