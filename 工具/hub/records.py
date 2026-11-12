import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import FormatError
from .tables import parse_md_table
from .textio import read_text

OUTPUT_COLUMNS = ["日期", "名称", "类型", "所属", "位置", "状态", "说明"]
QUESTION_COLUMNS = ["编号", "问题", "所属", "问谁", "怎么查", "状态", "答案", "来源/日期"]
OUTPUT_ENUMS = {
    "类型": {"笔记", "图", "分析", "数据", "代码", "其他"},
    "状态": {"完成", "进行中", "暂停", "归档"},
}
QUESTION_STATES = {"待解决", "已解决"}
WORK_COLUMNS = ["日期", "项目", "类型", "事项", "做了什么", "结果", "关联", "收获"]
WORK_ENUMS = {"类型": {"需求", "排查", "评审", "运维", "其他"}}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class Record:
    line: int
    fields: dict[str, str]


def load_outputs(path: Path):
    return _load(path, OUTPUT_COLUMNS, OUTPUT_ENUMS)


def load_questions(path: Path, askers: Sequence[str]):
    """Without askers the 问谁 column is optional and unchecked; with askers it is required."""
    if askers:
        return _load(path, QUESTION_COLUMNS, {"问谁": set(askers), "状态": QUESTION_STATES})
    return _load(path, [c for c in QUESTION_COLUMNS if c != "问谁"], {"状态": QUESTION_STATES})


def duplicate_numbers(records: list[Record], source: str) -> list[FormatError]:
    seen, errors = set(), []
    for record in records:
        number = record.fields["编号"]
        if number in seen:
            errors.append(FormatError(source, record.line, f"编号重复：{number}"))
        seen.add(number)
    return errors


def load_work(path: Path):
    intro, records, errors = _load(path, WORK_COLUMNS, WORK_ENUMS)
    for record in records:
        if not _DATE.match(record.fields["日期"]):
            errors.append(FormatError(path.name, record.line, f"日期格式应为 YYYY-MM-DD：{record.fields['日期']}"))
    return intro, records, errors


def _load(path: Path, columns: list[str], enums: dict[str, set[str]]):
    """Returns (intro markdown above the table, records, errors)."""
    text = read_text(path)
    intro = _intro(text)
    header, rows, errors = parse_md_table(text, path.name)
    missing = [c for c in columns if c not in header]
    if missing:
        errors.append(FormatError(path.name, 0, "缺少列：" + "、".join(missing)))
        return intro, [], errors
    records = []
    for line_no, fields in rows:
        for column, allowed in enums.items():
            if fields[column] not in allowed:
                errors.append(FormatError(path.name, line_no, f"{column}不合法：{fields[column]}"))
        records.append(Record(line=line_no, fields=fields))
    return intro, records, errors


def _intro(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    for i, line in enumerate(lines):
        if line.lstrip().startswith("|"):
            return "\n".join(lines[:i]).strip()
    return "\n".join(lines).strip()
