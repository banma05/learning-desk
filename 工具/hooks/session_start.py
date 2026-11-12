"""SessionStart hook: tell a new Claude session where the knowledge base stands today.

Prints {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}.
Never fails the session: any error degrades to a one-line notice and exit code 0.
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))

from hub.config import load_config  # noqa: E402
from hub.plans import parse_day  # noqa: E402
from hub.tables import parse_md_table  # noqa: E402
from hub.textio import read_text  # noqa: E402

MAX_CHARS = 1500
_NUMBER = re.compile(r"^([A-Z])(\d+)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WEEK = re.compile(r"^(\d{1,2})-(\d{1,2})\s*至\s*(\d{1,2})-(\d{1,2})$")


def _root() -> Path:
    """The knowledge base is the folder that holds 工具/; KB_ROOT overrides it."""
    return Path(os.environ["KB_ROOT"]) if os.environ.get("KB_ROOT") else TOOL_DIR.parent


def build_status(root: Path, today: date, now: datetime | None = None) -> str:
    now = now or datetime.now()
    lines = [f"知识库：{root}（规则见 维护约定.md）",
             _today_plan(root / "计划" / f"{today:%Y-%m-%d}.md")]
    previous = _previous_log(root / "计划", today)
    gap = _log_gap(previous) if previous else None
    if gap:
        lines.append(gap)
    week = _this_week(root / "计划" / "总计划.md", today)
    if week:
        lines.append(week)
    report = _weekly_report(root, today)
    if report:
        lines.append(report)
    prefixes = [prefix for prefix, _ in load_config(root)[0].prefixes]
    lines.append(_max_numbers(root / "问题.md", prefixes))
    lines.extend(_health(root, now))
    return "\n".join(lines)[:MAX_CHARS]


def _weekly_report(root: Path, today: date) -> str | None:
    """From Friday to Sunday: remind to write this week's report, named after the week's Monday."""
    if today.weekday() < 4:
        return None
    name = f"{today - timedelta(days=today.weekday()):%Y-%m-%d}.md"
    if (root / "周报" / name).exists():
        return None
    return f"本周周报：还没写（周报/{name}），下班写复盘时顺手写，写法见维护约定"


def _previous_log(plan_dir: Path, today: date) -> Path | None:
    """Most recent day file before today, so a Monday session still sees Friday's gaps."""
    days = sorted(p for p in plan_dir.glob("*.md") if _DAY.match(p.stem) and p.stem < f"{today:%Y-%m-%d}")
    return days[-1] if days else None


def _health(root: Path, now: datetime) -> list[str]:
    """Problems no session would otherwise notice: format hints of the last build, recent hook errors."""
    lines = []
    status_file = root / "工具" / "hook-status.json"
    if status_file.exists():
        errors = json.loads(read_text(status_file)).get("errors", [])
        if errors:
            lines.append(f"格式提示：{len(errors)} 条，能修就顺手修：" + "；".join(errors[:3]))
    log = root / "工具" / "hook.log"
    if log.exists():
        since = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        recent = [line for line in read_text(log).split("\n") if line[:19] >= since and line.strip()]
        if recent:
            lines.append(f"钩子错误：最近 24 小时 {len(recent)} 条，见 工具\\hook.log，请告诉使用者")
    return lines


def _today_plan(path: Path) -> str:
    if not path.exists():
        return "今日计划：还没建（第一次对话时按约定起草）"
    day, _ = parse_day(path)
    if day.tasks is None:
        return "今日计划：文件已建，但还没写「今日计划」"
    open_items = [text for text, done in day.tasks if not done]
    if not open_items:
        return "今日计划：全部完成"
    return "今日计划：\n" + "\n".join(f"- {text}" for text in open_items)


def _log_gap(path: Path) -> str | None:
    sections = _sections(read_text(path))
    missing = [name for name in ("搞懂了", "卡在哪里") if not sections.get(name, "").strip()]
    if not missing:
        return None
    return f"上次日志（{path.stem}）：缺" + "、".join(f"「{name}」" for name in missing) + "，先补齐"


def _sections(text: str) -> dict[str, str]:
    sections, current = {}, None
    for line in text.split("\n"):
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    return sections


def _this_week(path: Path, today: date) -> str | None:
    """This week's row of the master plan (the next week's on a weekend); None without one."""
    if not path.exists():
        return None
    section = next((body for name, body in _sections(read_text(path)).items() if "进度表" in name), None)
    if section is None:
        return None
    header, rows, _ = parse_md_table(section, path.name)
    if not rows:
        return "本周：总计划的进度表还是空的，可以和使用者一起排"
    try:
        weeks = _dated_weeks(header, [fields for _, fields in rows], today)
    except ValueError:
        return "本周：总计划进度表的日期读不出来"
    current = next(((label, fields) for label, end, fields in weeks if end >= today), None)
    if current is None:
        return "本周：总计划的进度表已经排完，请和使用者确认下一段"
    label, fields = current
    plan = "；".join(f"{name.removeprefix('计划：')}：{value}" for name, value in fields.items()
                    if name.startswith(("计划", "节点")) and value)
    return f"本周（总计划进度表 {label}）：{plan}"


def _dated_weeks(header: list[str], rows: list[dict], today: date) -> list[tuple[str, date, dict]]:
    """Resolve each row's "MM-DD 至 MM-DD" to an end date; a 〃 cell repeats the row above."""
    weeks, previous, year, last_month = [], {}, None, 0
    for fields in rows:
        label = fields.get(header[0], "").strip()
        match = _WEEK.match(label)
        if not match:
            continue
        start_month, start_day, end_month, end_day = map(int, match.groups())
        if year is None:
            year = min((today.year - 1, today.year, today.year + 1),
                       key=lambda y: abs((date(y, start_month, start_day) - today).days))
        elif start_month < last_month:
            year += 1
        last_month = start_month
        end = date(year + (end_month < start_month), end_month, end_day)
        previous = {name: previous.get(name, "") if value == "〃" else value for name, value in fields.items()}
        weeks.append((label, end, previous))
    return weeks


def _max_numbers(path: Path, prefixes: list[str]) -> str:
    if not path.exists():
        return "问题最大编号：问题.md 不存在"
    _, rows, _ = parse_md_table(read_text(path), path.name)
    best: dict[str, int] = {}
    for _, fields in rows:
        match = _NUMBER.match(fields.get("编号", ""))
        if match and match.group(1) in prefixes:
            best[match.group(1)] = max(best.get(match.group(1), 0), int(match.group(2)))
    numbers = " ".join(f"{p}{best[p]}" for p in prefixes if p in best)
    return f"问题最大编号：{numbers or '无'}"


def main(stdin_text: str) -> int:
    root = _root()
    try:
        status = build_status(root, date.today())
    except Exception as exc:  # the hook must never break the session
        _log(root, repr(exc))
        status = f"知识库：{root}（状态读取失败，见 工具\\hook.log）"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": status}},
                     ensure_ascii=False))
    return 0


def _log(root: Path, message: str) -> None:
    try:
        log = root / "工具" / "hook.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} session_start {message}\n")
    except OSError:
        pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.stdin.read() if not sys.stdin.isatty() else ""))
