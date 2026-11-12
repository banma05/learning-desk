import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import FormatError
from .knowledge import Point, split_list, split_points
from .textio import read_text

STATUS_ICON = {"已掌握": "✅", "学习中": "🔄", "只看过": "👀", None: "📄"}
_META = re.compile(r"^>\s*(状态|更新|图|代码|要先懂)\s*[:：]\s*(.*)$")


@dataclass
class Note:
    path: Path
    title: str
    status: str | None = None
    updated: str | None = None
    images: list[str] = field(default_factory=list)
    code: str | None = None
    body_md: str = ""
    points: list[Point] = field(default_factory=list)
    prereqs: list[str] = field(default_factory=list)
    status_line: int = 0  # line number of '> 状态:', 0 if absent
    prereqs_line: int = 0  # line number of '> 要先懂:', 0 if absent


def parse_note(path: Path):
    """Read a topic note: title, '> 键: 值' header lines, then body. Returns (note, errors)."""
    lines = read_text(path).split("\n")
    errors: list[FormatError] = []
    i = _skip_blank(lines, 0)
    title = path.stem
    if i < len(lines) and lines[i].startswith("# "):
        title = lines[i][2:].strip()
        i = _skip_blank(lines, i + 1)
    note = Note(path=path, title=title)
    while i < len(lines) and (match := _META.match(lines[i])):
        _apply_meta(note, match.group(1), match.group(2).strip(), path.name, i + 1, errors)
        i += 1
    body_md, note.points, point_errors = split_points("\n".join(lines[i:]), i + 1, path.name)
    note.body_md = body_md.strip("\n")
    errors.extend(point_errors)
    return note, errors


def _skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def _apply_meta(note: Note, key: str, value: str, source: str, line_no: int, errors: list) -> None:
    if key == "状态":
        note.status_line = line_no
        if value in STATUS_ICON:
            note.status = value
        else:
            errors.append(FormatError(source, line_no, f"状态不合法：{value}"))
    elif key == "更新":
        note.updated = value
    elif key == "要先懂":
        note.prereqs_line = line_no
        note.prereqs = split_list(value)
    elif key == "图":
        note.images = [v.strip() for v in re.split(r"[,，]", value) if v.strip()]
    else:
        note.code = value
