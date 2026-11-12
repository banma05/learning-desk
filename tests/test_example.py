import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "示例"
sys.path.insert(0, str(REPO / "工具"))

from build import build  # noqa: E402


class ExampleTest(unittest.TestCase):
    def test_example_builds_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = build(EXAMPLE, None, Path(tmp) / "学习台.html", datetime(2026, 1, 7, 18, 0))
        self.assertEqual([str(e) for e in errors], [])
        skeletons = list(EXAMPLE.glob("项目/*/骨架.md"))
        notes = [p for p in EXAMPLE.glob("项目/**/*.md") if p.name != "骨架.md"]
        days = [p for p in EXAMPLE.glob("计划/*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)]
        self.assertGreaterEqual(len(skeletons), 1)
        self.assertGreaterEqual(len(notes), 3)
        self.assertGreaterEqual(len(list(EXAMPLE.glob("概念/*.md"))), 2)
        self.assertGreaterEqual(len(days), 3)

    def test_example_page_is_committed(self):
        self.assertTrue((EXAMPLE / "学习台.html").exists())


if __name__ == "__main__":
    unittest.main()
