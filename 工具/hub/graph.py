"""Knowledge graphs: one per project (skeleton + notes + knowledge points) and one for concept cards.

A graph is plain JSON for the page: {"name", "root", "nodes": {id: node}}. Node ids are paths:
'项目名/骨架短名/…[/知识点名]' for projects, '概念/{名}' for cards. Nodes are inserted in
skeleton order (pre-order), so iterating "nodes" walks the tree top-down.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .concepts import Concept
from .errors import FormatError
from .knowledge import Point
from .notes import Note
from .page import ProjectView
from .sections import find_heading, heading_count, names_agree, section_span
from .skeleton import Node, is_topic, short_name
from .terms import number_headings
from .textio import read_text

CONCEPT_ROOT = "概念"
CONCEPT_GROUPS = ("概念", "方法")
NOT_STARTED = ("没碰", "未标")
_SHAPES = {"已掌握": "full", "学习中": "half", "空白": "dashed"}  # anything else is an empty circle
_SUMMARY_HEADING = "## 一句话"


def concept_id(name: str) -> str:
    return f"{CONCEPT_ROOT}/{name}"


def _node(node_id: str, name: str, kind: str, parent: str | None, block: int, doc: str | None = None) -> dict:
    return {"id": node_id, "name": name, "kind": kind, "parent": parent, "children": [], "block": block,
            "doc": doc, "anchor": "", "summary": "", "status": "没碰", "shape": "empty",
            "mastered": 0, "units": 0, "started": 0, "prereqs": [], "next": [], "confusions": [],
            "refs": [], "edit": None, "doc_status": None, "aliases": [], "measures": []}


def _set_mastery(node: dict, status: str, units: int, mastered: int, started: int) -> None:
    node.update(status=status, shape=_SHAPES.get(status, "empty"), units=units, mastered=mastered, started=started)


def rollup_status(units: int, mastered: int, started: int) -> str:
    """Status of anything made of units: all mastered, some started, or none started."""
    if units and mastered == units:
        return "已掌握"
    return "学习中" if started else "没碰"


def _unit(status: str) -> tuple[int, int]:
    """(mastered, started) of one unit with this status."""
    return int(status == "已掌握"), int(status not in NOT_STARTED)


def _points(note: Note) -> list[Point]:
    """Points that can be graph nodes: a '/' in the name would break the path id (reported elsewhere)."""
    return [point for point in note.points if "/" not in point.name]


def _note_mastery(note: Note) -> tuple[str, int, int, int]:
    """(status, units, mastered, started): its points if it has any, else the whole note is one unit."""
    if points := _points(note):
        pairs = [_unit(point.status) for point in points]
        mastered, started = sum(m for m, _ in pairs), sum(s for _, s in pairs)
        return rollup_status(len(pairs), mastered, started), len(pairs), mastered, started
    status = note.status or "未标"
    return (status, 1, *_unit(status))


def _rel(path: Path, kb_root: Path) -> str | None:
    """KB-relative path of a file, or None when it lies outside the KB (a '->' link pointing elsewhere)."""
    try:
        return path.resolve().relative_to(kb_root.resolve()).as_posix()
    except ValueError:
        return None


def _edit(path: Path, line: int, raw: str, kind: str, kb_root: Path) -> dict | None:
    """Where the page's status buttons write; None for a file outside the KB."""
    rel = _rel(path, kb_root)
    return {"file": rel, "line": line, "raw": raw, "kind": kind} if rel else None


def _header_edit(path: Path, line: int, kb_root: Path) -> dict | None:
    if not line:
        return None
    return _edit(path, line, read_text(path).split("\n")[line - 1], "header", kb_root)


@dataclass
class _Mount:
    """One skeleton node showing a note: the whole note, or the section from heading span[0] up to span[1]."""
    item: dict
    note: Note
    span: tuple[int, int] | None = None


@dataclass
class _Project:
    """Working state while one project graph is built."""
    view: ProjectView
    notes: dict[str, tuple[Note, str]]
    kb_root: Path
    nodes: dict[str, dict] = field(default_factory=dict)
    errors: list[FormatError] = field(default_factory=list)
    mounts: dict[str, list[_Mount]] = field(default_factory=dict)  # doc -> nodes showing it, skeleton order
    point_nodes: dict[str, list[tuple[dict, Point]]] = field(default_factory=dict)  # doc -> its point nodes
    _headings: dict[str, list[tuple[int, str, str]]] = field(default_factory=dict)

    def add(self, item: dict, parent: dict) -> bool:
        """Hang item under parent unless its id is taken (a same-named sibling); False if taken."""
        if item["id"] in self.nodes:
            return False
        parent["children"].append(item["id"])
        self.nodes[item["id"]] = item
        return True

    def note_of(self, node: Node) -> tuple[str | None, Note | None]:
        doc = self.view.link_ids.get(node.links[0]) if node.links else None
        return (doc, self.notes[doc][0]) if doc in self.notes else (None, None)

    def headings(self, doc: str) -> list[tuple[int, str, str]]:
        """The note's h2/h3 as the reading page numbers them (same ids, same text)."""
        if doc not in self._headings:
            self._headings[doc] = number_headings(self.notes[doc][1], doc)[1]
        return self._headings[doc]


def build_graph(project: ProjectView, notes: dict[str, tuple[Note, str]], concepts: list[Concept],
                concept_doc_ids: dict[str, str], kb_root: Path) -> tuple[dict, list[FormatError]]:
    """Graph of one project. Returns (graph, errors) — errors for names that resolve nowhere or clash.

    notes maps doc ids to (note, rendered body); section ids and headings come from the body.
    Names of concept cards resolve to concept_id(name), nodes of the concept graph; concept_doc_ids is
    part of the shared signature but not needed here.
    """
    state = _Project(project, notes, kb_root)
    root = _node(project.name, project.name, "project", None, -1)
    state.nodes[root["id"]] = root
    docs: dict[str, None] = {}
    blocks = [node for node in project.skeleton if not node.reference]
    for index, block in enumerate(blocks):
        docs.update(_add_tree(state, block, root, index, "block"))
    for doc, mounts in state.mounts.items():
        _attach_points(state, doc, mounts)
    state.nodes = _preorder(state.nodes, root["id"])
    _set_mastery(root, *_docs_mastery(state, docs))
    _check_point_names(state, concepts)
    _resolve_relations(state, _NameIndex(state, concepts))
    _link_next(state.nodes, state.nodes)
    return {"name": project.name, "root": root["id"], "nodes": state.nodes}, list(dict.fromkeys(state.errors))


def _preorder(nodes: dict[str, dict], root: str) -> dict[str, dict]:
    """The same nodes, reinserted top-down (points were hung after the whole skeleton was read)."""
    ordered: dict[str, dict] = {}
    stack = [root]
    while stack:
        node = nodes[stack.pop()]
        ordered[node["id"]] = node
        stack.extend(reversed(node["children"]))
    return ordered


def _add_tree(state: _Project, node: Node, parent: dict, block: int, kind: str) -> dict[str, None]:
    """Add node and its subtree; return the distinct note docs in it (ordered)."""
    node_id = f"{parent['id']}/{short_name(node.name)}"
    doc, note = state.note_of(node)
    if is_topic(node):
        kind = "note" if note else "blank"
    item = _node(node_id, node.name, kind, parent["id"], block, doc)
    item["measures"] = list(node.measures)
    if not state.add(item, parent):
        state.errors.append(FormatError(f"{state.view.name}/骨架.md", node.line, f"骨架同级重名：{node.name}"))
        return {}
    if kind == "blank":
        _set_mastery(item, "空白", 0, 0, 0)
        return {}
    docs: dict[str, None] = {doc: None} if doc else {}
    for child in node.children:
        docs.update(_add_tree(state, child, item, block, "group"))
    _set_mastery(item, *(_note_mastery(note) if kind == "note" else _docs_mastery(state, docs)))
    if note:
        state.mounts.setdefault(doc, []).append(_mount(state, node, item, note))
    return docs


def _mount(state: _Project, node: Node, item: dict, note: Note) -> _Mount:
    """Resolve the node's '#section' (unknown: the whole note) and check that its name fits where it lands.

    Only topics (nodes without children) are checked: a block or group is named after its part of the map.
    """
    source, headings = f"{state.view.name}/骨架.md", state.headings(item["doc"])
    index = find_heading(headings, node.anchor) if node.anchor else None
    if node.anchor and index is None:
        state.errors.append(FormatError(source, node.line, f"骨架小节找不到：{node.anchor}"))
    elif index is not None and heading_count(headings, node.anchor) > 1:
        state.errors.append(FormatError(source, node.line, f"骨架指向重名小标题：{node.anchor}"))
    target = headings[index][1] if index is not None else note.title
    if is_topic(node) and not names_agree(node.name, target, heading=index is not None):
        state.errors.append(FormatError(source, node.line, f"节点名和落点对不上：{node.name} / {target}"))
    item["doc_status"] = _note_mastery(note)[0]
    if index is None:
        return _Mount(item, note)
    item["anchor"] = headings[index][2]
    return _Mount(item, note, section_span(headings, index))


def _attach_points(state: _Project, doc: str, mounts: list[_Mount]) -> None:
    """Hang every point of the note under exactly one node showing it (see _home)."""
    note, headings = mounts[0].note, state.headings(doc)
    homes: dict[int, list[Point]] = {}
    for point in _points(note):
        heading = find_heading(headings, point.anchor) if point.anchor else None
        homes.setdefault(id(_home(mounts, heading)), []).append(point)
    pairs = state.point_nodes.setdefault(doc, [])
    for mount in mounts:
        item, points = mount.item, homes.get(id(mount), [])
        if not _points(note):
            item["edit"] = _header_edit(note.path, note.status_line, state.kb_root)
        for point in points:
            node = _node(f"{item['id']}/{point.name}", point.name, "point", item["id"], item["block"], item["doc"])
            node.update(anchor=point.anchor, summary=point.summary, doc_status=item["doc_status"], aliases=point.aliases)
            node["edit"] = _edit(note.path, point.line, point.raw, "point", state.kb_root)
            _set_mastery(node, point.status, 1, *_unit(point.status))
            if state.add(node, item):
                pairs.append((node, point))
            else:  # same name as a skeleton child of this node
                state.errors.append(FormatError(note.path.name, point.line, f"知识点重名：{point.name}"))
        if mount.span and item["kind"] == "note":
            _set_mastery(item, *_section_mastery(note, points))


def _home(mounts: list[_Mount], heading: int | None) -> _Mount:
    """Where a point hangs: the narrowest section node whose section holds the point's heading; else the
    first node showing the whole note; else the first node."""
    inside = [m for m in mounts if m.span and heading is not None and m.span[0] <= heading < m.span[1]]
    if inside:
        return min(inside, key=lambda m: m.span[1] - m.span[0])
    return next((m for m in mounts if not m.span), mounts[0])


def _section_mastery(note: Note, points: list[Point]) -> tuple[str, int, int, int]:
    """A section node counts only the points hung under it; with none, the note's own header status."""
    if not points:
        status = note.status or "未标"
        return (status, 1, *_unit(status))
    pairs = [_unit(point.status) for point in points]
    mastered, started = sum(m for m, _ in pairs), sum(s for _, s in pairs)
    return rollup_status(len(pairs), mastered, started), len(pairs), mastered, started


def _docs_mastery(state: _Project, docs: dict[str, None]) -> tuple[str, int, int, int]:
    """Sum over distinct notes, so a note hung under two topics counts once upstream."""
    units = mastered = started = 0
    for doc in docs:
        _, u, m, s = _note_mastery(state.notes[doc][0])
        units, mastered, started = units + u, mastered + m, started + s
    return rollup_status(units, mastered, started), units, mastered, started


def _doc_nodes(state: _Project) -> list[dict]:
    """Nodes that show a note (not points), in skeleton order."""
    return [node for node in state.nodes.values() if node["doc"] and node["kind"] != "point"]


def _check_point_names(state: _Project, concepts: list[Concept]) -> None:
    """Point names must be unique in the project and must not equal a concept name or alias."""
    concept_labels = {label.casefold() for c in concepts for label in [c.name, *c.aliases]}
    owner: dict[str, str] = {}
    for doc in dict.fromkeys(node["doc"] for node in _doc_nodes(state)):
        note = state.notes[doc][0]
        for point in note.points:
            if "/" in point.name:
                state.errors.append(FormatError(note.path.name, point.line, f"知识点名不能含 /：{point.name}"))
                continue
            if owner.get(point.name, doc) != doc or point.name.casefold() in concept_labels:
                state.errors.append(FormatError(note.path.name, point.line, f"知识点重名：{point.name}"))
            owner.setdefault(point.name, doc)


class _NameIndex:
    """Where a written name points: knowledge point > note title / skeleton name > concept card."""

    def __init__(self, state: _Project, concepts: list[Concept]):
        self.points: dict[str, str] = {}
        self.notes: dict[str, str] = {}
        for node in state.nodes.values():
            if node["kind"] == "point":
                self.points.setdefault(node["name"], node["id"])
        for node in _doc_nodes(state):
            self.notes.setdefault(state.notes[node["doc"]][0].title, node["id"])
        for node in state.nodes.values():
            if node["kind"] not in ("project", "point"):
                self.notes.setdefault(node["name"], node["id"])
                self.notes.setdefault(short_name(node["name"]), node["id"])
        self.concepts = {label.casefold(): concept_id(c.name) for c in concepts for label in [c.name, *c.aliases]}

    def find(self, name: str, local: dict[str, str]) -> str | None:
        return (local.get(name) or self.points.get(name) or self.notes.get(name)
                or self.concepts.get(name.casefold()))


def _resolve_relations(state: _Project, index: _NameIndex) -> None:
    for doc, mounts in state.mounts.items():
        note, pairs = mounts[0].note, state.point_nodes.get(doc, [])
        local = {node["name"]: node["id"] for node, _ in pairs}

        def resolve(names: list[str], line: int, label: str) -> list[str]:
            found, missing = _resolve(names, local, index)
            state.errors.extend(FormatError(note.path.name, line, f"{label}找不到：{name}") for name in missing)
            return found

        header = resolve(note.prereqs, note.prereqs_line, "要先懂")
        for point_node, point in pairs:
            point_node["prereqs"] = resolve(point.prereqs, point.line, "要先懂")
            point_node["confusions"] = resolve(point.confusions, point.line, "容易混淆")
        if not note.prereqs:  # no '> 要先懂:' header: what its points need from outside the note
            own = set(local.values())
            header = [target for node, _ in pairs for target in node["prereqs"] if target not in own]
        for mount in mounts:
            mount.item["prereqs"] = [target for target in dict.fromkeys(header) if target != mount.item["id"]]


def _resolve(names: list[str], local: dict[str, str], index: _NameIndex) -> tuple[list[str], list[str]]:
    """(ids the names point to, without repeats; names that point nowhere)."""
    found: list[str] = []
    missing: list[str] = []
    for name in names:
        target = index.find(name, local)
        if target is None:
            missing.append(name)
        elif target not in found:
            found.append(target)
    return found, missing


def _link_next(sources: dict[str, dict], targets: dict[str, dict]) -> None:
    """next = reverse of prereqs: who lists me as something to understand first."""
    for node in sources.values():
        for target in node["prereqs"]:
            if target in targets and node["id"] not in targets[target]["next"]:
                targets[target]["next"].append(node["id"])


def link_concept_next(concept_graph: dict, graphs: list[dict]) -> None:
    """Fill concept cards' next from project nodes that list them as prereqs."""
    for graph in graphs:
        _link_next(graph["nodes"], concept_graph["nodes"])


def build_concept_graph(concepts: list[Concept], concept_doc_ids: dict[str, str], kb_root: Path) -> dict:
    """Concept cards under two groups, 概念 and 方法 (cards without a kind go to 概念)."""
    nodes: dict[str, dict] = {}
    root = _node(CONCEPT_ROOT, CONCEPT_ROOT, "project", None, -1)
    nodes[root["id"]] = root
    groups = {}
    for name in CONCEPT_GROUPS:
        groups[name] = _node(concept_id(name), name, "group", root["id"], -1)
        root["children"].append(groups[name]["id"])
        nodes[groups[name]["id"]] = groups[name]
    for concept in concepts:
        group = groups[concept.kind or CONCEPT_GROUPS[0]]
        card = _node(concept_id(concept.name), concept.name, "concept", group["id"], -1,
                     concept_doc_ids.get(concept.name))
        card["summary"] = _summary(concept.body_md)
        card["aliases"] = list(concept.aliases)
        status = concept.status or "未标"
        _set_mastery(card, status, 1, *_unit(status))
        card["doc_status"] = status
        card["edit"] = _header_edit(concept.path, concept.status_line, kb_root)
        group["children"].append(card["id"])
        nodes[card["id"]] = card
    for group in groups.values():
        _set_mastery(group, *_cards_mastery([nodes[i] for i in group["children"]]))
    _set_mastery(root, *_cards_mastery([n for n in nodes.values() if n["kind"] == "concept"]))
    return {"name": CONCEPT_ROOT, "root": root["id"], "nodes": nodes}


def _cards_mastery(cards: list[dict]) -> tuple[str, int, int, int]:
    units, mastered, started = len(cards), sum(c["mastered"] for c in cards), sum(c["started"] for c in cards)
    return rollup_status(units, mastered, started), units, mastered, started


def _summary(body_md: str) -> str:
    """First paragraph under '## 一句话', the card's one-line explanation."""
    lines = body_md.split("\n")
    start = next((i for i, line in enumerate(lines) if line.rstrip() == _SUMMARY_HEADING), None)
    if start is None:
        return ""
    paragraph = []
    for line in lines[start + 1:]:
        if line.startswith("#") or (not line.strip() and paragraph):
            break
        if line.strip():
            paragraph.append(line.strip())
    return "".join(paragraph)
