import re

from .errors import FormatError

SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def parse_md_table(text: str, source: str):
    """Parse the first markdown table in text.

    Returns (header, [(line_no, row_dict)], errors); line numbers are 1-based.
    """
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        if lines[i].lstrip().startswith("|") and SEPARATOR.match(lines[i + 1].strip()):
            return _parse_from(lines, i, source)
    return [], [], []


def _parse_from(lines: list[str], start: int, source: str):
    header = split_cells(lines[start])
    rows, errors = [], []
    for idx in range(start + 2, len(lines)):
        line = lines[idx]
        if not line.strip():
            continue
        if not line.lstrip().startswith("|"):
            break
        cells = split_cells(line)
        line_no = idx + 1
        if len(cells) != len(header):
            errors.append(FormatError(source, line_no, f"列数应为 {len(header)}，实际为 {len(cells)}"))
            continue
        rows.append((line_no, dict(zip(header, cells))))
    return header, rows, errors
