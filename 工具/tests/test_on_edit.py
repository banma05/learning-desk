import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hooks.on_edit import STATUS_FILE, commit_all, main, should_handle

FIXTURES = Path(__file__).parent / "fixtures"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class OnEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _tmp_repo(self, src: Path | None = None) -> Path:
        repo = self.base / "kb"
        if src:
            shutil.copytree(src, repo)
        else:
            repo.mkdir()
            (repo / "seed.md").write_text("seed", encoding="utf-8")
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "t")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")
        return repo

    def test_should_handle_normalizes_paths(self):
        root = Path(r"D:\notes\kb")
        self.assertTrue(should_handle(r"d:\Notes\kb\问题.md", root))
        self.assertTrue(should_handle("D:/notes/kb/项目/示例项目/x.md", root))
        self.assertFalse(should_handle(r"D:\notes\kb\归档\README.md", root))
        self.assertFalse(should_handle(r"D:\notes\kb\学习台.html", root))
        self.assertFalse(should_handle(r"D:\notes\kb\学习台.html.4242-1a2b3c4d.tmp", root))
        self.assertFalse(should_handle(r"D:\notes\kb\工具\hook.log", root))
        self.assertFalse(should_handle(r"D:\notes\kb\.git\index", root))
        self.assertFalse(should_handle(r"D:\notes\other\README.md", root))
        self.assertFalse(should_handle(r"D:\notes\kb2\a.md", root))
        self.assertFalse(should_handle(r"D:\notes\kb\工具\build.py", root))
        self.assertTrue(should_handle(r"D:\notes\kb\设计\x.md", root))

    def test_should_handle_the_same_folder_spelled_two_ways(self):
        # e.g. a Windows short 8.3 name versus the long name: both resolve to the same folder
        kb = self.base / "kb"
        (kb / "概念").mkdir(parents=True)
        (kb / "概念" / "a.md").write_text("x", encoding="utf-8")
        other_spelling = self.base / "kb" / "概念" / ".." / ".." / "kb"
        self.assertTrue(should_handle(str(kb / "概念" / "a.md"), other_spelling))
        self.assertTrue(should_handle(str(other_spelling / "概念" / "a.md"), kb))

    def test_commit_gives_up_on_lock_without_raising(self):
        repo = self._tmp_repo()
        (repo / "a.md").write_text("x", encoding="utf-8")
        (repo / ".git" / "index.lock").write_text("", encoding="utf-8")
        self.assertIn("index.lock", commit_all(repo, "auto: a.md", attempts=2, delay=0.01))

    def test_git_answers_in_english_so_nothing_to_commit_is_recognised(self):
        repo = self._tmp_repo()
        with mock.patch.dict(os.environ, {"LC_ALL": "zh_CN.UTF-8", "LANGUAGE": "zh_CN"}), \
                mock.patch("hooks.on_edit.subprocess.run", wraps=subprocess.run) as run:
            self.assertIsNone(commit_all(repo, "auto: nothing"))
        self.assertTrue(all(call.kwargs["env"]["LC_ALL"] == "C" and call.kwargs["env"]["LANGUAGE"] == "C"
                            for call in run.call_args_list))

    def test_main_logs_git_error_text(self):
        root = self._tmp_repo(FIXTURES / "样例记录")
        (root / ".git" / "index.lock").write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"KB_ROOT": str(root)}), \
                mock.patch("hooks.on_edit.time.sleep"):
            main('{"tool_input": {"file_path": "%s"}}' % (root / "问题.md").as_posix())
        last = (root / "工具" / "hook.log").read_text(encoding="utf-8").strip().split("\n")[-1]
        self.assertIn("commit failed for", last)
        self.assertIn("index.lock", last)

    def test_commit_leaves_tool_code_alone(self):
        repo = self._tmp_repo()
        (repo / "工具").mkdir()
        (repo / "工具" / "build.py").write_text("half-written", encoding="utf-8")
        (repo / "a.md").write_text("x", encoding="utf-8")
        self.assertIsNone(commit_all(repo, "auto: a.md"))
        status = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", "status", "--porcelain"],
                                capture_output=True,
                                text=True, encoding="utf-8").stdout
        self.assertIn("工具/", status)
        self.assertNotIn("a.md", status)

    def test_commit_succeeds_and_noop_is_success(self):
        repo = self._tmp_repo()
        (repo / "a.md").write_text("x", encoding="utf-8")
        self.assertIsNone(commit_all(repo, "auto: a.md"))
        log = subprocess.run(["git", "-C", str(repo), "log", "--format=%s", "-1"], capture_output=True, text=True, encoding="utf-8").stdout
        self.assertEqual(log.strip(), "auto: a.md")
        self.assertIsNone(commit_all(repo, "auto: nothing"))

    def test_main_builds_commits_and_never_raises(self):
        root = self._tmp_repo(FIXTURES / "样例记录")
        (root / "工具").mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {"KB_ROOT": str(root)}):
            (root / "问题.md").write_text((root / "问题.md").read_text(encoding="utf-8") + "\n", encoding="utf-8")
            rc = main('{"tool_input": {"file_path": "%s"}}' % (root / "问题.md").as_posix())
            self.assertEqual(rc, 0)
            self.assertTrue((root / "学习台.html").exists())
            log = subprocess.run(["git", "-C", str(root), "log", "--format=%s", "-1"], capture_output=True, text=True, encoding="utf-8").stdout
            self.assertEqual(log.strip(), "auto: 问题.md")
            self.assertEqual(main("not json"), 0)
        self.assertIn("not json", (root / "工具" / "hook.log").read_text(encoding="utf-8"))

    def test_main_ignores_files_outside(self):
        root = self._tmp_repo()
        with mock.patch.dict(os.environ, {"KB_ROOT": str(root)}):
            self.assertEqual(main('{"tool_input": {"file_path": "D:/notes/other/a.java"}}'), 0)
        self.assertFalse((root / "学习台.html").exists())

    def test_main_writes_build_status_for_session_start(self):
        root = self._tmp_repo(FIXTURES / "样例记录坏")
        with mock.patch.dict(os.environ, {"KB_ROOT": str(root)}):
            main('{"tool_input": {"file_path": "%s"}}' % (root / "问题.md").as_posix())
        status = json.loads((root / STATUS_FILE).read_text(encoding="utf-8"))
        self.assertTrue(any("问谁不合法" in e for e in status["errors"]))


class RootTest(unittest.TestCase):
    def test_root_defaults_to_tool_parent(self):
        from hooks import on_edit
        tool_dir = Path(on_edit.__file__).resolve().parent.parent
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(on_edit._root(), tool_dir.parent)
        with mock.patch.dict("os.environ", {"KB_ROOT": "X"}):
            self.assertEqual(on_edit._root(), Path("X"))


if __name__ == "__main__":
    unittest.main()
