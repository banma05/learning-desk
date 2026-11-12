"""Search entries: one list for the page's search box (points, notes, concept cards, headings).

Body text is not listed here: it is already in the page, so the front end scans the articles itself.
"""

HEADING_LEVELS = (2, 3)
_DOC_KINDS = ("note", "block", "group")  # nodes that may carry a doc and get a note entry for it


def _words(name: str, aliases: list[str]) -> list[str]:
    return list(dict.fromkeys([name, *aliases]))


def _entry(kind: str, title: str, secondary: str, words: list[str], doc: str | None, anchor: str, node: str) -> dict:
    return {"k": kind, "t": title, "s": secondary, "w": words, "href": f"#doc-{doc}" if doc else "",
            "a": anchor, "node": node}


def _note_nodes(graph: dict) -> dict[str, str]:
    """doc -> the node a note's entry opens it from: the first one showing the whole note, else the first one."""
    chosen: dict[str, str] = {}
    for node in graph["nodes"].values():
        if node["kind"] in _DOC_KINDS and node["doc"]:
            if node["doc"] not in chosen or (not node["anchor"] and graph["nodes"][chosen[node["doc"]]]["anchor"]):
                chosen[node["doc"]] = node["id"]
    return chosen


def _graph_entries(graph: dict, doc_titles: dict[str, str], seen_docs: set[str]) -> list[dict]:
    entries = []
    note_nodes = _note_nodes(graph)
    for node in graph["nodes"].values():
        kind, doc = node["kind"], node["doc"]
        if kind == "point":
            entries.append(_entry("point", node["name"], node["summary"], _words(node["name"], node["aliases"]),
                                  doc, node["anchor"], node["id"]))
        elif kind == "concept":
            seen_docs.add(doc)
            entries.append(_entry("concept", node["name"], node["summary"], _words(node["name"], node["aliases"]),
                                  doc, "", node["id"]))
        elif kind in _DOC_KINDS and doc and doc not in seen_docs:
            seen_docs.add(doc)
            title = doc_titles.get(doc, node["name"])
            entries.append(_entry("note", title, "", _words(title, node["aliases"]), doc, "", note_nodes[doc]))
    return entries


def search_entries(graphs: list[dict], concept_graph: dict, headings: dict[str, list[tuple[int, str, str]]],
                   doc_titles: dict[str, str]) -> list[dict]:
    """Entries for points, notes (one per doc), concept cards and every h2/h3 of every doc."""
    seen_docs: set[str] = set()
    entries = []
    for graph in [*graphs, concept_graph]:
        entries.extend(_graph_entries(graph, doc_titles, seen_docs))
    for doc, items in headings.items():
        title = doc_titles.get(doc, "")
        entries.extend(_entry("heading", text, title, [text], doc, heading_id, "")
                       for level, text, heading_id in items if level in HEADING_LEVELS)
    return entries
