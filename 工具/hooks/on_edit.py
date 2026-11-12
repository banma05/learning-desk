"""PostToolUse hook: when a knowledge-base file is edited, rebuild 学习台.html and commit.

Claude Code pipes the hook input JSON to stdin. This script must never disturb the session:
every failure is logged to 工具/hook.log and the exit code is always 0.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

from build import build  # noqa: E402

_IGNORED_DIRS = ("归档/", ".git/", "工具/")  # 工具/ is code: committed by hand, not per keystroke
_IGNORED_FILES = ("学习台.html",)
_PAGE_TEMP = ("学习台.html.", ".tmp")  # build.py writes 学习台.html.<pid>-<id>.tmp, then swaps it in
STATUS_FILE = "工具/hook-status.json"  # last build's format hints, read by session_start


def _root() -> Path:
    """The knowledge base is the folder that holds 工具/; KB_ROOT overrides it."""
    return Path(os.environ["KB_ROOT"]) if os.environ.get("KB_ROOT") else TOOL_DIR.parent


def _norm(path: str) -> str:
    """One spelling per folder: resolved (.., links, Windows short 8.3 names), forward slashes, case folded."""
    try:
        path = str(Path(path).resolve())
    except (OSError, RuntimeError):
        pass
    return path.replace("\\", "/").rstrip("/").casefold()


def should_handle(file_path: str, root: Path) -> bool:
    base, target = _norm(str(root)), _norm(file_path)
    if not target.startswith(base + "/"):
        return False
    rel = target[len(base) + 1:]
    if rel.startswith(_PAGE_TEMP[0].casefold()) and rel.endswith(_PAGE_TEMP[1]):
        return False
    return not rel.startswith(tuple(d.casefold() for d in _IGNORED_DIRS)) and rel not in {
        f.casefold() for f in _IGNORED_FILES}


def commit_all(root: Path, message: str, attempts: int = 5, delay: float = 0.4) -> str | None:
    """git add -A + commit; retries while another hook holds index.lock.

    Returns None on success (nothing to commit counts), else git's last error text.
    """
    error = ""
    for _ in range(attempts):
        add = _git(root, "add", "-A", "--", ".", ":(exclude)工具")  # tool code is committed by hand
        if add.returncode == 0:
            commit = _git(root, "commit", "-q", "-m", message)
            if commit.returncode == 0 or "nothing to commit" in commit.stdout + commit.stderr:
                return None
            error = (commit.stderr or commit.stdout).strip()
        else:
            error = add.stderr.strip()
        if "index.lock" not in error:
            return error or "git failed"
        time.sleep(delay)
    return error


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """git in English: commit_all recognises "nothing to commit" and index.lock by their English text."""
    env = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def main(stdin_text: str) -> int:
    root = _root()
    try:
        file_path = json.loads(stdin_text).get("tool_input", {}).get("file_path", "")
        if not should_handle(file_path, root):
            return 0
        errors = build(root, None, root / "学习台.html", datetime.now())
        _write_status(root, [str(e) for e in errors])
        error = commit_all(root, f"auto: {Path(file_path).name}")
        if error is not None:
            _log(root, f"commit failed for {file_path}: {' | '.join(error.splitlines())[:300]}")
    except Exception as exc:  # the hook must never break the session
        _log(root, f"{exc!r} input={stdin_text[:200]!r}")
    return 0


def _write_status(root: Path, errors: list[str]) -> None:
    status = {"time": f"{datetime.now():%Y-%m-%d %H:%M}", "errors": errors}
    path = root / STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")


def _log(root: Path, message: str) -> None:
    try:
        log = root / "工具" / "hook.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} on_edit {message}\n")
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main(sys.stdin.buffer.read().decode("utf-8", errors="replace")))
