import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from unittest import mock

import install

GIT_IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
NOW = datetime(2026, 1, 5, 9, 30, 0)
PY = "C:/Python/python.exe"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.claude = self.base / "claude"
        self.claude.mkdir()
        env = mock.patch.dict(os.environ, GIT_IDENTITY)
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = install.main(list(args))
        return rc, out.getvalue()

    def _install(self, kb: Path, use: str = "study", *extra: str) -> tuple[int, str]:
        return self._run(str(kb), "--use", use, "--claude-dir", str(self.claude), *extra)

    def _settings(self) -> dict:
        return json.loads((self.claude / "settings.json").read_text(encoding="utf-8"))

    def _build_output(self, kb: Path) -> str:
        return subprocess.run([sys.executable, str(kb / "工具" / "build.py")], capture_output=True,
                              text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout

    # ---- scaffold ----

    def test_study_kb_has_no_work_and_no_asker_column(self):
        kb = self.base / "kb"
        self.assertEqual(self._install(kb, "study")[0], 0)
        self.assertFalse((kb / "工作.md").exists())
        self.assertEqual(json.loads((kb / "学习台配置.json").read_text(encoding="utf-8"))["问谁"], [])
        self.assertNotIn("问谁", (kb / "问题.md").read_text(encoding="utf-8"))
        self.assertTrue((kb / "工具" / "build.py").exists())
        self.assertFalse((kb / "工具" / "tests").exists())

    def test_work_kb_has_work_md_and_askers(self):
        kb = self.base / "kb"
        self.assertEqual(self._install(kb, "work")[0], 0)
        self.assertTrue((kb / "工作.md").exists())
        self.assertEqual(json.loads((kb / "学习台配置.json").read_text(encoding="utf-8"))["问谁"], ["自己", "同事", "上级"])
        self.assertIn("| 问谁 |", (kb / "问题.md").read_text(encoding="utf-8"))

    def test_refuses_non_empty_target(self):
        kb = self.base / "kb"
        kb.mkdir()
        (kb / "mine.md").write_text("keep", encoding="utf-8")
        rc, out = self._install(kb)
        self.assertEqual(rc, 1)
        self.assertIn("目标文件夹不是空的", out)
        self.assertEqual(sorted(p.name for p in kb.iterdir()), ["mine.md"])

    def test_refuses_kb_inside_this_repo(self):
        rc, out = self._install(install.REPO / "我的知识库")
        self.assertEqual(rc, 1)
        self.assertIn("不要放在", out)
        self.assertFalse((install.REPO / "我的知识库").exists())

    def test_fresh_study_kb_builds_clean(self):
        kb = self.base / "kb"
        self._install(kb, "study")
        self.assertIn("（0 条格式提示）", self._build_output(kb))

    def test_fresh_work_kb_builds_clean(self):
        kb = self.base / "kb"
        self._install(kb, "work")
        self.assertIn("（0 条格式提示）", self._build_output(kb))

    def test_kb_is_a_git_repo_without_remote(self):
        kb = self.base / "kb"
        self._install(kb)
        log = subprocess.run(["git", "-C", str(kb), "log", "--format=%s"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(log.stdout.strip(), "init: 学习台")
        remotes = subprocess.run(["git", "-C", str(kb), "remote"], capture_output=True, text=True).stdout
        self.assertEqual(remotes.strip(), "")

    def test_git_init_without_identity_warns(self):
        kb = self.base / "kb"
        empty = self.base / "empty.gitconfig"
        empty.write_text("", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER"))}
        env.update({"GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "user.useConfigOnly", "GIT_CONFIG_VALUE_0": "true"})
        with mock.patch.dict(os.environ, env, clear=True):
            rc, out = self._install(kb)
        self.assertEqual(rc, 0)
        self.assertIn("git config", out)
        self.assertTrue((kb / "学习台.html").exists())

    # ---- Claude settings ----

    def test_install_writes_hooks_permissions_and_import(self):
        (self.claude / "settings.json").write_text('{"model": "x"}', encoding="utf-8")
        kb = self.base / "kb"
        self._install(kb)
        settings = self._settings()
        self.assertEqual(settings["model"], "x")
        start = settings["hooks"]["SessionStart"][-1]
        self.assertEqual(start["matcher"], "startup|resume|compact|clear")
        self.assertIn(f"{kb.resolve().as_posix()}/工具/hooks/session_start.py", start["hooks"][0]["command"])
        self.assertEqual(start["hooks"][0]["timeout"], 15)
        edit = settings["hooks"]["PostToolUse"][-1]
        self.assertEqual(edit["matcher"], "Edit|Write|MultiEdit")
        self.assertEqual((edit["hooks"][0]["timeout"], edit["hooks"][0]["async"]), (60, True))
        rule = install.permission_path(kb.resolve())
        self.assertEqual(settings["permissions"]["allow"], [f"Edit({rule})", f"Write({rule})"])
        self.assertEqual(settings["permissions"]["additionalDirectories"], [kb.resolve().as_posix()])
        claude_md = (self.claude / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(f"@{kb.resolve().as_posix()}/维护约定.md", claude_md)
        self.assertEqual(len(list(self.claude.glob("settings.json.bak-*"))), 1)

    def test_install_twice_is_idempotent(self):
        kb = PurePosixPath("/home/u/kb")
        once = install.add_to_settings({"model": "x"}, kb, PY)
        self.assertEqual(install.add_to_settings(once, kb, PY), once)
        text = install.add_import("# mine\n", kb)
        self.assertEqual(install.add_import(text, kb), text)

    def test_uninstall_removes_only_this_kb(self):
        other = {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]},
                 "permissions": {"allow": ["Bash(ls)"]}}
        before = install.add_to_settings(other, PurePosixPath("/home/u/other"), PY)
        after = install.remove_from_settings(install.add_to_settings(before, PurePosixPath("/home/u/kb"), PY),
                                             PurePosixPath("/home/u/kb"))
        self.assertEqual(after, before)
        text = install.add_import("# mine\n", PurePosixPath("/home/u/kb"))
        self.assertEqual(install.remove_import(text, PurePosixPath("/home/u/kb")), "# mine\n")

    def test_uninstall_cli_restores_settings(self):
        (self.claude / "settings.json").write_text('{"model": "x"}', encoding="utf-8")
        kb = self.base / "kb"
        self._install(kb)
        rc, _ = self._run("--uninstall", str(kb), "--claude-dir", str(self.claude))
        self.assertEqual(rc, 0)
        self.assertEqual(self._settings(), {"model": "x"})
        self.assertNotIn("维护约定.md", (self.claude / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertTrue((kb / "维护约定.md").exists())

    def test_uninstall_when_not_installed(self):
        (self.claude / "settings.json").write_text('{"model": "x"}', encoding="utf-8")
        rc, _ = self._run("--uninstall", str(self.base / "kb"), "--claude-dir", str(self.claude))
        self.assertEqual(rc, 0)
        self.assertEqual((self.claude / "settings.json").read_text(encoding="utf-8"), '{"model": "x"}')
        self.assertEqual(list(self.claude.glob("*.bak-*")), [])

    def test_paths_with_spaces_and_chinese(self):
        kb = self.base / "我的 笔记"
        self.assertEqual(self._install(kb)[0], 0)
        command = self._settings()["hooks"]["SessionStart"][-1]["hooks"][0]["command"]
        self.assertIn(f'"{kb.resolve().as_posix()}/工具/hooks/session_start.py"', command)
        escaped = kb.resolve().as_posix().replace(" ", "\\ ")
        self.assertIn(f"@{escaped}/维护约定.md\n", (self.claude / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertIn("（0 条格式提示）", self._build_output(kb))

    def test_import_line_escapes_spaces(self):
        kb = PurePosixPath("/home/u/我的 笔记")
        text = install.add_import("", kb)
        self.assertEqual(text, "@/home/u/我的\\ 笔记/维护约定.md\n")
        self.assertEqual(install.remove_import(text, kb), "")

    def test_refuses_path_with_hash(self):
        rc, out = self._install(self.base / "a#b")
        self.assertEqual(rc, 1)
        self.assertIn("#", out)
        self.assertFalse((self.base / "a#b").exists())

    def test_hook_command_quotes_only_when_needed(self):
        self.assertEqual(install.hook_command("C:/Python/python.exe", PurePosixPath("/home/u/kb/x.py")),
                         "C:/Python/python.exe /home/u/kb/x.py")
        self.assertEqual(install.hook_command("C:/Python/python.exe", PurePosixPath("/home/u/a b/x.py")),
                         'C:/Python/python.exe "/home/u/a b/x.py"')

    def test_reattach_existing_kb_keeps_notes(self):
        kb = self.base / "kb"
        self._install(kb)
        (kb / "问题.md").write_text("my notes", encoding="utf-8")
        self._run("--uninstall", str(kb), "--claude-dir", str(self.claude))
        rc, out = self._run(str(kb), "--claude-dir", str(self.claude))
        self.assertEqual(rc, 0, out)
        self.assertEqual((kb / "问题.md").read_text(encoding="utf-8"), "my notes")
        self.assertEqual(len(self._settings()["hooks"]["SessionStart"]), 1)
        self.assertIn("维护约定.md", (self.claude / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_reconnect_replaces_old_python(self):
        kb = PurePosixPath("/home/u/kb")
        old = install.add_to_settings({}, kb, "/old/python")
        new = install.reconnect(old, kb, "/new/python")
        commands = [h["command"] for g in new["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0].startswith("/new/python "))

    def test_uninstall_does_not_touch_kb_whose_path_ends_the_same(self):
        both = install.add_to_settings(install.add_to_settings({}, PurePosixPath("/home/u/kb"), PY), PurePosixPath("/kb"), PY)
        left = install.remove_from_settings(both, PurePosixPath("/kb"))
        self.assertEqual(left, install.add_to_settings({}, PurePosixPath("/home/u/kb"), PY))

    def test_uninstall_reports_when_nothing_matches(self):
        other = install.add_to_settings({}, PurePosixPath("/home/u/other"), PY)
        (self.claude / "settings.json").write_text(json.dumps(other), encoding="utf-8")
        rc, out = self._run("--uninstall", str(self.base / "kb"), "--claude-dir", str(self.claude))
        self.assertEqual(rc, 0)
        self.assertIn("没有找到", out)
        self.assertIn("/home/u/other", out)
        self.assertNotIn("已从 Claude Code 设置里去掉", out)

    def test_kb_turns_off_commit_signing(self):
        kb = self.base / "kb"
        self._install(kb)
        value = subprocess.run(["git", "-C", str(kb), "config", "--local", "commit.gpgsign"],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(value, "false")

    def test_permission_path_windows_and_posix(self):
        self.assertEqual(install.permission_path(PureWindowsPath("D:/a b")), "//d/a b/**")
        self.assertEqual(install.permission_path(PurePosixPath("/home/u/kb")), "//home/u/kb/**")

    def test_invalid_settings_json_left_untouched(self):
        (self.claude / "settings.json").write_text("{oops", encoding="utf-8")
        rc, out = self._install(self.base / "kb")
        self.assertEqual(rc, 0)
        self.assertEqual((self.claude / "settings.json").read_text(encoding="utf-8"), "{oops")
        self.assertIn('"SessionStart"', out)

    def test_dry_run_writes_nothing(self):
        (self.claude / "settings.json").write_text('{"model": "x"}', encoding="utf-8")
        kb = self.base / "kb"
        rc, out = self._install(kb, "study", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertFalse(kb.exists())
        self.assertEqual(sorted(p.name for p in self.claude.iterdir()), ["settings.json"])
        self.assertEqual((self.claude / "settings.json").read_text(encoding="utf-8"), '{"model": "x"}')
        self.assertIn("SessionStart", out)

    def test_write_with_backup_skips_unchanged_file(self):
        path = self.base / "a.json"
        path.write_text("same", encoding="utf-8")
        install.write_with_backup(path, "same", NOW, dry_run=False)
        self.assertEqual(list(self.base.glob("a.json.bak-*")), [])
        install.write_with_backup(path, "new", NOW, dry_run=False)
        self.assertEqual((self.base / "a.json.bak-20260105-093000").read_text(encoding="utf-8"), "same")

    # ---- update ----

    def test_update_replaces_tool_keeps_notes_and_logs(self):
        kb = self.base / "kb"
        self._install(kb)
        (kb / "工具" / "hook.log").write_text("log line", encoding="utf-8")
        (kb / "工具" / "build.py").write_text("changed", encoding="utf-8")
        (kb / "问题.md").write_text("my notes", encoding="utf-8")
        rc, _ = self._run("--update", str(kb))
        self.assertEqual(rc, 0)
        self.assertEqual((kb / "工具" / "build.py").read_bytes(), (install.REPO / "工具" / "build.py").read_bytes())
        self.assertEqual((kb / "工具" / "hook.log").read_text(encoding="utf-8"), "log line")
        self.assertEqual((kb / "问题.md").read_text(encoding="utf-8"), "my notes")
        self.assertFalse((kb / "工具" / "tests").exists())


if __name__ == "__main__":
    unittest.main()
