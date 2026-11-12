import tempfile
import unittest
from pathlib import Path

from hub.config import CONFIG_FILE, DEFAULT_PREFIXES, Config, load_config
from hub.errors import FormatError


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "kb"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, text: str) -> None:
        (self.root / CONFIG_FILE).write_text(text, encoding="utf-8")

    def _hint(self, message: str) -> list[FormatError]:
        return [FormatError(CONFIG_FILE, 0, message)]

    def test_missing_file_gives_defaults_and_hint(self):
        self.assertEqual(load_config(self.root), (Config(), self._hint("没有 学习台配置.json，按默认值处理")))

    def test_valid_file(self):
        self._write('{"问谁": ["自己", "老师"], "问题编号前缀": {"X": "甲"}, "代码根目录": ".."}')
        config, errors = load_config(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(config, Config(askers=("自己", "老师"), prefixes=(("X", "甲"),),
                                        code_root=self.root.parent.resolve()))

    def test_bad_json(self):
        self._write("{")
        config, errors = load_config(self.root)
        self.assertEqual(config, Config())
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].message.startswith("读不出来，按默认值处理："))

    def test_askers_wrong_type(self):
        self._write('{"问谁": "自己"}')
        self.assertEqual(load_config(self.root), (Config(), self._hint("问谁应为文字列表，按不分问谁处理")))

    def test_prefixes_wrong_shape(self):
        self._write('{"问题编号前缀": {"xy": "甲"}}')
        config, errors = load_config(self.root)
        self.assertEqual(config.prefixes, DEFAULT_PREFIXES)
        self.assertEqual(errors, self._hint('问题编号前缀应为 {"T": "技术"} 这样的对照，按默认值处理'))

    def test_code_root_missing_dir(self):
        self._write('{"代码根目录": "不存在的目录"}')
        self.assertEqual(load_config(self.root), (Config(), self._hint("代码根目录不存在，按知识库的上一级处理")))


if __name__ == "__main__":
    unittest.main()
