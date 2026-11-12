import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import FormatError
from .notes import STATUS_ICON
from .textio import read_text

KINDS = {"概念", "方法"}
_META = re.compile(r"^>\s*(类型|状态|更新|别名)\s*[:：]\s*(.*)$")


@dataclass
class Concept:
    path: Path
    name: str
    kind: str | None = None
    status: str | None = None
    updated: str | None = None
    aliases: list[str] = field(default_factory=list)
    body_md: str = ""
    status_line: int = 0  # line number of '> 状态:', 0 if absent


def parse_concept(path: Path):
    """Read a concept card: name is the file name; '> 键: 值' header, then body. Returns (concept, errors)."""
    lines = read_text(path).split("\n")
    errors: list[FormatError] = []
    concept = Concept(path=path, name=path.stem)
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith("# ")):
        i += 1
    while i < len(lines) and (match := _META.match(lines[i])):
        _apply_meta(concept, match.group(1), match.group(2).strip(), path.name, i + 1, errors)
        i += 1
    concept.body_md = "\n".join(lines[i:]).strip("\n")
    return concept, errors


def _apply_meta(concept: Concept, key: str, value: str, source: str, line_no: int, errors: list) -> None:
    if key == "类型":
        if value in KINDS:
            concept.kind = value
        else:
            errors.append(FormatError(source, line_no, f"类型不合法：{value}"))
    elif key == "状态":
        concept.status_line = line_no
        if value in STATUS_ICON:
            concept.status = value
        else:
            errors.append(FormatError(source, line_no, f"状态不合法：{value}"))
    elif key == "更新":
        concept.updated = value
    else:
        concept.aliases = [a.strip() for a in re.split(r"[,，]", value) if a.strip()]


def load_concepts(concept_dir: Path):
    """All cards sorted by name; names and aliases must be unique ignoring case."""
    concepts, errors = [], []
    for path in sorted(concept_dir.glob("*.md")):
        concept, card_errors = parse_concept(path)
        concepts.append(concept)
        errors.extend(card_errors)
    seen: dict[str, str] = {}
    for concept in concepts:
        for label in [concept.name, *concept.aliases]:
            key = label.casefold()
            if key in seen and seen[key] != concept.name:
                errors.append(FormatError(concept.path.name, 0, f"概念重复：{seen[key]} 与 {concept.name}"))
            seen.setdefault(key, concept.name)
    concepts.sort(key=lambda c: c.name.casefold())
    return concepts, errors
