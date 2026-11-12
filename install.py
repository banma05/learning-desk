"""Create a 学习台 knowledge base and connect it to Claude Code.

    python install.py <知识库目录> [--use study|work] [--dry-run] [--claude-dir DIR]
    python install.py --uninstall <知识库目录> [--dry-run] [--claude-dir DIR]
    python install.py --update <知识库目录> [--dry-run]

Claude Code's settings.json and CLAUDE.md are backed up before every change.
"""
import argparse
import copy
import difflib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PurePath

REPO = Path(__file__).resolve().parent
TEMPLATE = REPO / "模板"
TOOL = REPO / "工具"
TOOL_EXCLUDES = {"tests", "__pycache__", "hook.log", "hook-status.json"}
USES = {"study": (), "work": ("自己", "同事", "上级")}
USE_LABELS = {"study": "自学", "work": "工作上手、了解项目"}
CONFIG_FILE = "学习台配置.json"
RULES_FILE = "维护约定.md"
_SESSION_START = "/工具/hooks/session_start.py"


class InstallError(Exception):
    pass


# ---- the knowledge base folder ----

def scaffold(kb: Path, use: str) -> None:
    if kb.exists() and any(kb.iterdir()):
        raise InstallError(f"目标文件夹不是空的：{kb}")
    shutil.copytree(TEMPLATE, kb, dirs_exist_ok=True)
    shutil.copytree(TOOL, kb / "工具", ignore=shutil.ignore_patterns(*TOOL_EXCLUDES))
    config_path = kb / CONFIG_FILE
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["问谁"] = list(USES[use])
    _write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    if not USES[use]:
        (kb / "工作.md").unlink()
        questions = kb / "问题.md"
        _write(questions, _drop_column(questions.read_text(encoding="utf-8"), "问谁"))


def _drop_column(text: str, name: str) -> str:
    """Remove one column from the header and separator rows of a table that has no data rows yet."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and name in cells:
            index = cells.index(name)
            for j in (i, i + 1):
                row = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                del row[index]
                lines[j] = "| " + " | ".join(row) + " |" if j == i else "|" + "|".join(row) + "|"
            break
    return "\n".join(lines)


def git_init(kb: Path) -> str | None:
    """git init with no remote and a first commit. Returns a hint for the user when that fails.

    Commit signing is turned off for this repository: the hook commits on every edit.
    """
    try:
        _git(kb, "init", "-q")
        _git(kb, "config", "commit.gpgsign", "false")
        _git(kb, "add", "-A")
        _git(kb, "commit", "-q", "-m", "init: 学习台")
    except FileNotFoundError:
        return "没找到 git。装好 git 后在知识库里运行：git init、git add -A、git commit -m init"
    except subprocess.CalledProcessError as exc:
        reason = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        return ("知识库建好了，但第一次 git 提交没做成" + (f"（git 说：{reason}）" if reason else "") + "。\n"
                "最常见的原因是 git 还不知道你是谁，先运行：\n"
                '  git config --global user.name "你的名字"\n'
                '  git config --global user.email "你的邮箱"\n'
                f"再在 {kb} 里运行：git add -A 和 git commit -m init")
    return None


def build_page(kb: Path, python: str) -> str | None:
    """Generate 学习台.html once. Returns what went wrong, or None."""
    run = subprocess.run([python, str(kb / "工具" / "build.py")], capture_output=True)
    if run.returncode == 0:
        return None
    output = (run.stderr or run.stdout).decode("utf-8", errors="replace").strip()
    return output[-500:] or f"build.py 退出码 {run.returncode}"


def is_knowledge_base(kb: Path) -> bool:
    return (kb / "工具" / "build.py").is_file() and (kb / RULES_FILE).is_file()


def update_tool(kb: Path) -> None:
    tool = kb / "工具"
    if not (tool / "build.py").exists():
        raise InstallError(f"这里不像学习台知识库，没有 工具/build.py：{kb}")
    kept = {name: (tool / name).read_bytes() for name in ("hook.log", "hook-status.json") if (tool / name).exists()}
    shutil.rmtree(tool)
    shutil.copytree(TOOL, tool, ignore=shutil.ignore_patterns(*TOOL_EXCLUDES))
    for name, content in kept.items():
        (tool / name).write_bytes(content)
    if (kb / ".git").exists():
        try:
            _git(kb, "add", "-A", "--", "工具")
            _git(kb, "commit", "-q", "-m", "update: 工具")
        except (OSError, subprocess.CalledProcessError):
            pass  # nothing changed, or no git identity: the files are updated either way


def _git(kb: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(kb), *args], check=True, capture_output=True)


# ---- Claude Code settings ----

def permission_path(kb: PurePath) -> str:
    """Claude Code permission rules write absolute paths as //d/... on Windows and //home/... elsewhere."""
    posix = kb.as_posix()
    if len(posix) >= 2 and posix[1] == ":":
        posix = "/" + posix[0].lower() + posix[2:]
    return "/" + posix.rstrip("/") + "/**"


def hook_command(python: str, script: PurePath) -> str:
    """Quote a part only when it needs it, so the plain case also runs in shells other than bash."""
    return f"{_quote(PurePath(python).as_posix())} {_quote(script.as_posix())}"


def _quote(text: str) -> str:
    return f'"{text}"' if re.search(r"""[\s"'&;|()<>$`]""", text) else text


def reconnect(settings: dict, kb: PurePath, python: str) -> dict:
    """This knowledge base's entries, written afresh: an old Python path or a duplicate is replaced."""
    return add_to_settings(remove_from_settings(settings, kb), kb, python)


def connected_knowledge_bases(settings: dict) -> list[str]:
    """Folders whose session_start hook is in the settings."""
    found = []
    for groups in (settings.get("hooks") or {}).values():
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                try:
                    tokens = shlex.split(str(hook.get("command", "")))
                except ValueError:
                    continue
                found += [t[:-len(_SESSION_START)] for t in tokens if t.endswith(_SESSION_START)]
    return sorted(set(found))


def add_to_settings(settings: dict, kb: PurePath, python: str) -> dict:
    result = copy.deepcopy(settings)
    hooks = result.setdefault("hooks", {})
    for event, entry in _hook_entries(kb, python).items():
        groups = hooks.setdefault(event, [])
        if entry not in groups:
            groups.append(entry)
    permissions = result.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    allow.extend(rule for rule in _rules(kb) if rule not in allow)
    folders = permissions.setdefault("additionalDirectories", [])
    if kb.as_posix() not in folders:
        folders.append(kb.as_posix())
    return result


def remove_from_settings(settings: dict, kb: PurePath) -> dict:
    result = copy.deepcopy(settings)
    ours = re.compile(r'(?:^|[\s"])' + re.escape(f"{kb.as_posix()}/工具/hooks/"))
    hooks = result.get("hooks", {})
    for event in list(hooks):
        for group in hooks[event]:
            group["hooks"] = [h for h in group.get("hooks", []) if not ours.search(h.get("command", ""))]
        hooks[event] = [group for group in hooks[event] if group["hooks"]]
        if not hooks[event]:
            del hooks[event]
    permissions = result.get("permissions", {})
    for key, ours in (("allow", _rules(kb)), ("additionalDirectories", [kb.as_posix()])):
        if key in permissions:
            permissions[key] = [item for item in permissions[key] if item not in ours]
            if not permissions[key]:
                del permissions[key]
    for key in ("hooks", "permissions"):
        if key in result and not result[key]:
            del result[key]
    return result


def _hook_entries(kb: PurePath, python: str) -> dict:
    hooks = kb / "工具" / "hooks"
    return {
        "SessionStart": {"matcher": "startup|resume|compact|clear", "hooks": [
            {"type": "command", "command": hook_command(python, hooks / "session_start.py"), "timeout": 15}]},
        "PostToolUse": {"matcher": "Edit|Write|MultiEdit", "hooks": [
            {"type": "command", "command": hook_command(python, hooks / "on_edit.py"), "timeout": 60, "async": True}]},
    }


def _rules(kb: PurePath) -> list[str]:
    path = permission_path(kb)
    return [f"Edit({path})", f"Write({path})"]


def add_import(claude_md: str, kb: PurePath) -> str:
    line = _import_line(kb)
    if line in claude_md.splitlines():
        return claude_md
    if claude_md and not claude_md.endswith("\n"):
        claude_md += "\n"
    return claude_md + line + "\n"


def remove_import(claude_md: str, kb: PurePath) -> str:
    line = _import_line(kb)
    return "".join(l for l in claude_md.splitlines(keepends=True) if l.rstrip("\r\n") != line)


def _import_line(kb: PurePath) -> str:
    """Claude Code reads an @import path up to the first unescaped space, so spaces are escaped."""
    return "@" + kb.as_posix().replace(" ", "\\ ") + "/" + RULES_FILE


def write_with_backup(path: Path, text: str, now: datetime, dry_run: bool) -> None:
    """Write text (LF line ends) to path; a file that used CRLF keeps CRLF."""
    old = _read_text(path)
    if old == text:
        return
    if dry_run:
        print(f"会修改 {path}：")
        print("".join(difflib.unified_diff(old.splitlines(keepends=True), text.splitlines(keepends=True))))
        return
    crlf = path.exists() and b"\r\n" in path.read_bytes()
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{now:%Y%m%d-%H%M%S}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, text, "\r\n" if crlf else "\n")


def _write(path: Path, text: str, newline: str = "\n") -> None:
    with path.open("w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)


def _read_text(path: Path) -> str:
    """A user's file as text with LF line ends; a UTF-8 BOM is dropped. Missing: empty."""
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def _read_settings(claude_dir: Path) -> dict | None:
    """settings.json as a dict ({} when missing); None when it cannot be read or has an unexpected shape."""
    try:
        settings = json.loads(_read_text(claude_dir / "settings.json") or "{}")
    except ValueError:
        return None
    return settings if _well_formed(settings) else None


def _well_formed(settings) -> bool:
    """The parts this script edits have the shape Claude Code uses."""
    if not isinstance(settings, dict):
        return False
    hooks, permissions = settings.get("hooks", {}), settings.get("permissions", {})
    if not isinstance(hooks, dict) or not isinstance(permissions, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list) or not all(
                isinstance(g, dict) and isinstance(g.get("hooks", []), list)
                and all(isinstance(h, dict) for h in g.get("hooks", [])) for g in groups):
            return False
    return all(isinstance(permissions.get(key, []), list) for key in ("allow", "additionalDirectories"))


def _change_settings(claude_dir: Path, change, now: datetime, dry_run: bool, snippet: bool = True) -> bool:
    """Apply change(settings) to settings.json and say whether it changed.

    A file we cannot read is left alone; when adding, the user gets the part to paste in by hand.
    """
    path = claude_dir / "settings.json"
    old = _read_settings(claude_dir)
    if old is None:
        print(f"{path} 读不出来，没有改它。" + ("请手动把下面这段合并进去：" if snippet else ""))
        if snippet:
            print(json.dumps(change({}), ensure_ascii=False, indent=2))
        return False
    new = change(old)
    if new == old:
        return False
    write_with_backup(path, json.dumps(new, ensure_ascii=False, indent=2) + "\n", now, dry_run)
    return True


def _change_claude_md(claude_dir: Path, change, now: datetime, dry_run: bool) -> bool:
    path = claude_dir / "CLAUDE.md"
    old = _read_text(path)
    new = change(old)
    write_with_backup(path, new, now, dry_run)
    return new != old


# ---- command line ----

def default_claude_dir() -> Path:
    """Where Claude Code keeps settings.json and CLAUDE.md: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.claude_dir = (args.claude_dir or default_claude_dir()).expanduser()
    kb, now = args.kb.expanduser().resolve(), datetime.now()
    try:
        if args.update:
            if kb == REPO or REPO in kb.parents:
                raise InstallError(f"这是 learning-desk 仓库本身，不是知识库：{kb}")
            if args.dry_run:
                print(f"会用 {TOOL} 替换 {kb / '工具'}，笔记和配置不动")
            else:
                update_tool(kb)
                print(f"已更新 {kb / '工具'}")
            return 0
        if args.uninstall:
            _uninstall(kb, args, now)
            return 0
        _install(kb, args, now)
        return 0
    except InstallError as exc:
        print(f"没有完成：{exc}", file=sys.stderr)
        return 1


def _uninstall(kb: Path, args, now: datetime) -> None:
    removed = _change_settings(args.claude_dir, lambda s: remove_from_settings(s, kb), now, args.dry_run,
                               snippet=False)
    removed = _change_claude_md(args.claude_dir, lambda t: remove_import(t, kb), now, args.dry_run) or removed
    if removed:
        print(f"已从 Claude Code 设置里去掉 {kb}，知识库本身没动。")
        return
    print(f"Claude Code 设置里没有找到这个知识库：{kb}")
    known = connected_knowledge_bases(_read_settings(args.claude_dir) or {})
    if known:
        print("设置里接着的知识库是：" + "、".join(known) + "。卸载时传这里的路径。")


def _install(kb: Path, args, now: datetime) -> None:
    if kb == REPO or REPO in kb.parents:
        raise InstallError(f"知识库不要放在这个仓库里面（{REPO}），换一个文件夹，免得笔记被一起推上去")
    if "#" in str(kb):
        raise InstallError(f"知识库路径里不能有 #，Claude Code 读不到这样的路径：{kb}")
    if importlib.util.find_spec("markdown") is None:
        raise InstallError(f"缺少 Python 库 markdown，先运行：{_display(sys.executable)} -m pip install markdown")
    python, existing = sys.executable, is_knowledge_base(kb)
    if not existing and kb.exists() and any(kb.iterdir()):
        raise InstallError(f"目标文件夹不是空的：{kb}")
    if existing:
        print(f"{'会把' if args.dry_run else '把'}已有的知识库 {kb} 重新接到 Claude Code，笔记不动")
    else:
        use = args.use or _ask_use()
        if args.dry_run:
            print(f"会新建知识库 {kb}（用途：{USE_LABELS[use]}），复制 模板/ 和 工具/，并做第一次 git 提交")
        else:
            scaffold(kb, use)
            problem = build_page(kb, python)  # before the first commit, so the page is in it
            if problem:
                print(f"第一次生成网页没成功，先把知识库建好了。原因：{problem}")
            hint = git_init(kb)
            if hint:
                print(hint)
    _change_settings(args.claude_dir, lambda s: reconnect(s, kb, python), now, args.dry_run)
    _change_claude_md(args.claude_dir, lambda t: add_import(t, kb), now, args.dry_run)
    if not args.dry_run and not existing:
        print(f"学习台知识库建好了：{kb}\n"
              f"- 双击 {kb / '学习台.html'} 看网页\n"
              f"- 新开一个 Claude Code 会话，先请 Claude 帮你填好 {RULES_FILE} 第一节\"我是谁\"\n"
              "- 以后在任何项目里和 Claude 聊，它都会按约定把学到的东西记进来")


def _display(path: str) -> str:
    return f'"{path}"' if " " in path else path


def _ask_use() -> str:
    while True:
        try:
            answer = input("这个知识库主要用来做什么？[1] 自学  [2] 工作上手、了解项目\n> ").strip()
        except EOFError:
            raise InstallError("没有选用途，可以加上 --use study 或 --use work") from None
        if answer in ("1", "2"):
            return "study" if answer == "1" else "work"
        print("请输入 1 或 2")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="install.py", description="新建学习台知识库，并把它接到 Claude Code。")
    parser.add_argument("kb", type=Path, help="知识库文件夹")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--uninstall", action="store_true", help="从 Claude Code 设置里去掉这个知识库，不删文件")
    mode.add_argument("--update", action="store_true", help="用仓库里新的 工具/ 替换知识库里的，不动笔记")
    parser.add_argument("--use", choices=sorted(USES), help="study=自学，work=工作上手、了解项目；不给就问")
    parser.add_argument("--dry-run", action="store_true", help="只打印会改什么，什么都不写")
    parser.add_argument("--claude-dir", type=Path, default=None,
                        help="Claude Code 设置目录，默认 $CLAUDE_CONFIG_DIR，没有就是 ~/.claude")
    return parser


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
