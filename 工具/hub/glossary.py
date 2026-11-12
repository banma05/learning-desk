import re
from dataclasses import dataclass, field

from .errors import FormatError
from .tables import SEPARATOR, split_cells

_CODE_SPAN = re.compile(r"`([^`]+)`")
_OPEN, _CLOSE = "(（", ")）"


@dataclass
class Term:
    name: str
    aliases: list[str] = field(default_factory=list)
    meaning: str = ""
    source: str = ""
    line: int = 0


def parse_glossary(text: str, source: str):
    """Read every table whose header starts with '术语'. Returns (terms, errors)."""
    lines = text.split("\n")
    terms: list[Term] = []
    errors: list[FormatError] = []
    i = 0
    while i < len(lines) - 1:
        if _is_glossary_header(lines[i]) and SEPARATOR.match(lines[i + 1].strip()):
            i = _read_rows(lines, i + 2, source, terms, errors)
        else:
            i += 1
    return terms, errors


def _is_glossary_header(line: str) -> bool:
    return line.lstrip().startswith("|") and split_cells(line)[0] == "术语"


def _read_rows(lines, start, source, terms, errors) -> int:
    idx = start
    while idx < len(lines):
        line = lines[idx]
        if not line.lstrip().startswith("|"):
            break  # a blank line or any non-table line ends the table
        _read_row(split_cells(line), idx + 1, source, terms, errors)
        idx += 1
    return idx


def _read_row(cells, line_no, source, terms, errors) -> None:
    if len(cells) < 3:
        errors.append(FormatError(source, line_no, f"术语表行缺列：应有 3 列，实际为 {len(cells)}"))
        return
    name, aliases = _split_name(cells[0])
    if not name:
        errors.append(FormatError(source, line_no, "术语表行缺名称"))
        return
    terms.append(Term(name, aliases, cells[1], cells[2], line_no))


def _split_name(cell: str):
    """Split a name cell into (name, aliases); parenthesised plain text is dropped, code names kept."""
    outside, inside = _separate_parentheses(cell.replace("**", ""))
    words = [w.replace("`", "").strip() for w in outside.split(" / ")]
    words = [w for w in words if w]
    if not words:
        return "", []
    codes = [c.strip() for chunk in inside for c in _CODE_SPAN.findall(chunk)]
    aliases: list[str] = []
    for alias in words[1:] + codes:
        if alias and alias != words[0] and alias not in aliases:
            aliases.append(alias)
    return words[0], aliases


def _separate_parentheses(text: str):
    """Return (text outside the outermost parentheses, list of texts inside them).

    Parentheses within backtick code spans are not counted.
    """
    outside: list[str] = []
    inside: list[str] = []
    depth = 0
    in_code = False
    for ch in text:
        if ch == "`":
            in_code = not in_code
        elif not in_code and ch in _OPEN:
            depth += 1
            if depth == 1:
                inside.append("")
                continue
        elif not in_code and ch in _CLOSE and depth > 0:
            depth -= 1
            if depth == 0:
                continue
        if depth > 0:
            inside[-1] += ch
        else:
            outside.append(ch)
    return "".join(outside), inside
