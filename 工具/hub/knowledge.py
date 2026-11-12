import re
from dataclasses import dataclass, field

from .errors import FormatError

POINT_STATUS = ("已掌握", "学习中", "没碰")
SECTION_HEADING = "## 知识点"
_ANCHOR = re.compile(r"\s->\s+#(.*)$")
_FIELD = re.compile(r"^([^:：]+?)\s*[:：]\s*(.*)$")


@dataclass
class Point:
    name: str
    line: int  # 1-based line number in the file
    raw: str  # the original line, without line ending
    status: str = "没碰"
    summary: str = ""
    prereqs: list[str] = field(default_factory=list)
    confusions: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    anchor: str = ""  # heading text after '-> #'


def split_list(value: str) -> list[str]:
    """Split a list value on ',' '，' '、' and drop empty items."""
    return [item.strip() for item in re.split(r"[,，、]", value) if item.strip()]


def split_points(body_md: str, first_line: int, source: str) -> tuple[str, list[Point], list[FormatError]]:
    """Cut the '## 知识点' section out of a note body.

    Returns (body without the section, points, errors). first_line is the file line number of
    the first line of body_md.
    """
    lines = body_md.split("\n")
    start = next((i for i, line in enumerate(lines) if line.rstrip() == SECTION_HEADING), None)
    if start is None:
        return body_md, [], []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    points: list[Point] = []
    errors: list[FormatError] = []
    seen: set[str] = set()
    for i in range(start + 1, end):
        if lines[i].strip():
            _read_point_line(lines[i], first_line + i, source, points, errors, seen)
    rest = "\n".join(lines[:start] + lines[end:]).strip("\n")
    return rest, points, errors


def _read_point_line(raw: str, line_no: int, source: str, points: list, errors: list, seen: set) -> None:
    text = raw.strip()
    if text != "-" and not text.startswith("- "):
        errors.append(FormatError(source, line_no, "知识点小节里只能写 '- 名称 | …' 列表项"))
        return
    text = text[2:]
    anchor = ""
    if match := _ANCHOR.search(text):
        anchor = match.group(1).strip()
        text = text[: match.start()]
    name, *fields = [part.strip() for part in text.split("|")]
    if not name:
        errors.append(FormatError(source, line_no, "知识点缺名称"))
        return
    point = Point(name=name, line=line_no, raw=raw, anchor=anchor)
    keys: set[str] = set()
    for item in filter(None, fields):
        key = _apply_field(point, item, source, errors)
        if key in keys:  # the later value wins; the page's status buttons refuse such a line
            errors.append(FormatError(source, line_no, f"知识点字段重复：{key}"))
        keys.add(key)
    if name in seen:
        errors.append(FormatError(source, line_no, f"知识点重复：{name}"))
        return
    seen.add(name)
    points.append(point)


def _apply_field(point: Point, item: str, source: str, errors: list) -> str:
    """Set one 'key: value' field on point; returns the key."""
    match = _FIELD.match(item)
    key, value = (match.group(1), match.group(2).strip()) if match else (item, "")
    if key == "状态":
        if value in POINT_STATUS:
            point.status = value
        else:
            errors.append(FormatError(source, point.line, f"知识点状态不合法：{value}"))
    elif key == "一句话":
        point.summary = value
    elif key == "要先懂":
        point.prereqs = split_list(value)
    elif key == "容易混淆":
        point.confusions = split_list(value)
    elif key == "别名":
        point.aliases = split_list(value)
    else:
        errors.append(FormatError(source, point.line, f"知识点字段不认识：{key}"))
    return key
