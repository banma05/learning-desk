import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import FormatError

_ITEM = re.compile(r"^( *)- (.+)$")
_INDENT = 2
_ARROW = re.compile(r"\s*->\s*")
_NOTE = re.compile(r"（[^）]*）")


@dataclass
class Node:
    name: str
    line: int
    measures: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    anchor: str = ""  # heading text after '#': the node shows that section of its note, not the whole note
    children: list["Node"] = field(default_factory=list)
    reference: bool = False


def is_topic(node: Node) -> bool:
    return not node.children


def parse_skeleton(text: str, source: str, project_dir: Path):
    """Build the project tree from 骨架.md. Returns (roots, errors).

    Roots after a '## 参考' heading are reference material (glossary, tool maps):
    listed apart from the blocks and left out of coverage.
    """
    roots: list[Node] = []
    stack: list[Node] = []
    errors: list[FormatError] = []
    in_reference = False
    for line_no, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        if line.startswith("## "):
            if line[3:].strip() != "参考":
                errors.append(FormatError(source, line_no, "只支持 '## 参考' 这一个小标题"))
            in_reference = True
            stack = []
            continue
        match = _ITEM.match(line)
        if not match:
            errors.append(FormatError(source, line_no, "应为 '- 名称' 形式的列表项"))
            continue
        indent = len(match.group(1))
        depth = indent // _INDENT
        if indent % _INDENT or depth > len(stack):
            errors.append(FormatError(source, line_no, "缩进应为每级 2 个空格"))
            continue
        node = _parse_item(match.group(2), line_no, source, project_dir, errors)
        node.reference = in_reference
        del stack[depth:]
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)
    return roots, errors


def _parse_item(body: str, line_no: int, source: str, project_dir: Path, errors: list) -> Node:
    arrow = _ARROW.search(body)
    link = ""
    if arrow:
        if arrow.group(0) != " -> ":
            errors.append(FormatError(source, line_no, "-> 两边应有空格"))
        body, link = body[:arrow.start()], body[arrow.end():]
    name, _, measure = body.partition(" | ")
    node = Node(name=name.strip(), line=line_no)
    if measure:
        values = measure.split(":", 1)[-1].split("：", 1)[-1]
        node.measures = [m.strip() for m in re.split(r"[,，]", values) if m.strip()]
    link, _, anchor = link.strip().partition("#")
    link, node.anchor = link.strip(), anchor.strip()
    if link:
        if (project_dir / link).is_file():
            node.links.append(link)
        else:
            errors.append(FormatError(source, line_no, f"笔记不存在：{link}"))
    return node


def short_name(name: str) -> str:
    """Path segment for a node: block names keep the part before ' · ', notes in （…） are dropped."""
    return _NOTE.sub("", name.split(" · ", 1)[0]).strip()


def node_paths(roots: list[Node]) -> set[str]:
    paths: set[str] = set()

    def walk(nodes: list[Node], prefix: str) -> None:
        for node in nodes:
            path = f"{prefix}/{short_name(node.name)}" if prefix else short_name(node.name)
            paths.add(path)
            walk(node.children, path)

    walk(roots, "")
    return paths


def coverage(block: Node) -> tuple[int, int]:
    """(topics with a valid note, total topics) under block."""
    if is_topic(block):
        return (1 if block.links else 0), 1
    covered = total = 0
    for child in block.children:
        c, t = coverage(child)
        covered += c
        total += t
    return covered, total
