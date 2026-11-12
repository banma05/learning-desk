import unittest
from pathlib import Path

from hub.concepts import load_concepts, parse_concept

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"


class ConceptsTest(unittest.TestCase):
    def test_parse_concept_header(self):
        c, errors = parse_concept(SAMPLE / "概念/幂等.md")
        self.assertEqual((c.name, c.kind, c.status), ("幂等", "概念", "已掌握"))
        self.assertEqual(c.aliases, ["idempotent", "幂等性"])
        self.assertIn("同一操作", c.body_md)
        self.assertEqual(errors, [])

    def test_load_sorted(self):
        concepts, errors = load_concepts(SAMPLE / "概念")
        self.assertEqual([c.name for c in concepts], ["Kafka offset", "幂等"])
        self.assertEqual(errors, [])

    def test_alias_collision_case_insensitive(self):
        _, errors = load_concepts(FIXTURES / "概念重复")
        self.assertIn("概念重复", str(errors[0]))

    def test_bad_kind_reported(self):
        c, errors = parse_concept(FIXTURES / "坏概念/名词.md")
        self.assertIsNone(c.kind)
        self.assertIn("类型不合法：名词", str(errors[0]))


if __name__ == "__main__":
    unittest.main()
