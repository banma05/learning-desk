import re
from dataclasses import dataclass
from pathlib import Path

from .errors import FormatError
from .textio import read_text

_DATE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TASK = re.compile(r"^\s*- \[([ xX])\] (.+)$")
_PLAN_HEADING = "## 今日计划"
OVERVIEW_FILE = "总计划.md"  # the plan the days are drafted from; not a day
_BRIEF_HEADINGS = {_PLAN_HEADING, "## 要点", "## 复盘"}


@dataclass
class Day:
    date: str
    title: str
    tasks: list[tuple[str, bool]] | None
    body_md: str
    brief_md: str = ""
    detail_md: str = ""


def parse_day(path: Path):
    """Read one 计划/YYYY-MM-DD.md file. tasks is None when there is no 今日计划 section."""
    errors = []
    if not _DATE_NAME.match(path.stem):
        errors.append(FormatError(path.name, 0, "文件名应为 YYYY-MM-DD.md"))
    lines = read_text(path).split("\n")
    title = path.stem
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    brief, detail = _split_brief(lines)
    day = Day(date=path.stem, title=title, tasks=_tasks(lines), body_md="\n".join(lines).strip("\n"),
              brief_md=brief, detail_md=detail)
    return day, errors


def _split_brief(lines: list[str]) -> tuple[str, str]:
    """Shown by default: the 今日计划, 要点 and 复盘 sections. Everything else is the folded detail."""
    brief, detail, target = [], [], None
    for line in lines:
        if line.startswith("## "):
            target = brief if line.strip() in _BRIEF_HEADINGS else detail
        (target if target is not None else detail).append(line)
    return "\n".join(brief).strip("\n"), "\n".join(detail).strip("\n")


def _tasks(lines: list[str]) -> list[tuple[str, bool]] | None:
    try:
        start = [line.strip() for line in lines].index(_PLAN_HEADING)
    except ValueError:
        return None
    tasks = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if match := _TASK.match(line):
            tasks.append((match.group(2).strip(), match.group(1) != " "))
    return tasks


def load_days(plan_dir: Path):
    days, errors = [], []
    for path in plan_dir.glob("*.md"):
        if path.name == OVERVIEW_FILE:
            continue
        if not _DATE_NAME.match(path.stem):
            errors.append(FormatError(path.name, 0, "计划/ 下只放 YYYY-MM-DD.md 和 总计划.md"))
            continue
        day, day_errors = parse_day(path)
        days.append(day)
        errors.extend(day_errors)
    days.sort(key=lambda d: d.date, reverse=True)
    return days, errors


def ratio_label(day: Day) -> str | None:
    if day.tasks is None:
        return None
    done = sum(1 for _, finished in day.tasks if finished)
    return f"{done}/{len(day.tasks)} 完成"
