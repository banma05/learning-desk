"""Heading ids, the term table, and inline term marks for rendered note bodies.

Order of use for every body: number_headings first (ids for the reading page), then mark_terms.
"""
import html
import re

from .glossary import Term
from .mdrender import render_inline

MIN_LABEL = 2
_HEADING = re.compile(r"<h([23])((?:\s[^>]*)?)>(.*?)</h\1>", re.S)
_TAG = re.compile(r"<[^>]*>")
_TOKEN = re.compile(r"<!--.*?-->|<[^>]*>|[^<]+|<", re.S)
_TAG_NAME = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)")
_SKIP_TAGS = {"pre", "a", "code", "h1", "h2", "h3", "h4", "h5", "h6"}
_ASCII_EDGE = r"A-Za-z0-9_"


def number_headings(doc_html: str, doc_id: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Give every <h2>/<h3> the id '{doc_id}-h{n}' (n counts from 1). Returns (html, [(level, text, id)])."""
    headings: list[tuple[int, str, str]] = []

    def add_id(match: re.Match) -> str:
        level, attrs, inner = match.groups()
        heading_id = f"{doc_id}-h{len(headings) + 1}"
        headings.append((int(level), html.unescape(_TAG.sub("", inner)).strip(), heading_id))
        return f'<h{level} id="{heading_id}"{attrs}>{inner}</h{level}>'

    return _HEADING.sub(add_id, doc_html), headings


def term_table(graphs: list[dict], concept_graph: dict, glossary: dict[str, list[Term]]) -> tuple[dict, dict[str, str]]:
    """Build (terms, labels) from the project graphs, the concept graph and the glossaries.

    terms: {term_id: {"name", "kind", "summary", "source", "node"}}. labels: {written word: term_id}.
    When two terms claim a word, a point beats a concept card beats a glossary term; the first
    one seen wins inside the same kind. Words shorter than two characters are never labels.
    """
    terms: dict[str, dict] = {}
    labels: dict[str, str] = {}

    def add(term_id: str, entry: dict, words: list[str]) -> None:
        terms.setdefault(term_id, entry)
        for word in words:
            word = word.strip()
            if len(word) >= MIN_LABEL:
                labels.setdefault(word, term_id)

    for graph in graphs:
        for node in graph["nodes"].values():
            if node["kind"] == "point":
                entry = {"name": node["name"], "kind": "point", "summary": node["summary"], "source": "",
                         "node": node["id"]}
                add(f"p:{node['id']}", entry, [node["name"], *node["aliases"]])
    for node in concept_graph.get("nodes", {}).values():
        if node["kind"] == "concept":
            entry = {"name": node["name"], "kind": "concept", "summary": node["summary"], "source": "",
                     "node": node["id"]}
            add(f"c:{node['name']}", entry, [node["name"], *node["aliases"]])
    for project, project_terms in glossary.items():
        for term in project_terms:
            entry = {"name": term.name, "kind": "term", "summary": render_inline(term.meaning),
                     "source": render_inline(term.source), "node": None}
            add(f"g:{project}/{term.name}", entry, [term.name, *term.aliases])
    return terms, labels


def mark_terms(doc_html: str, labels: dict[str, str]) -> str:
    """Wrap the first mention of each term per <h2> section in <span class="term" data-term="id">.

    Text inside <pre>, <a> and headings is left alone; an inline <code> is wrapped (outside the
    tag) only when its whole text is a label. Longer labels are matched first, so a word that is
    already wrapped is never matched again by a shorter one.
    """
    if not labels:
        return doc_html
    pattern = _label_pattern(labels)
    tokens = _TOKEN.findall(doc_html)
    out: list[str] = []
    seen: set[str] = set()
    skip = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        tag = _TAG_NAME.match(token)
        if tag is None:
            out.append(_mark_text(token, pattern, labels, seen) if skip == 0 and not token.startswith("<") else token)
            i += 1
            continue
        closing, name = tag.group(1) == "/", tag.group(2).lower()
        if name == "code" and not closing and skip == 0 and _is_whole_code(tokens, i, labels):
            out.append(_wrap_code(tokens[i:i + 3], labels, seen))
            i += 3
            continue
        if name == "h2" and not closing:
            seen.clear()
        if name in _SKIP_TAGS and not token.endswith("/>"):
            skip = max(0, skip + (-1 if closing else 1))
        out.append(token)
        i += 1
    return "".join(out)


def _label_pattern(labels: dict[str, str]) -> re.Pattern:
    """One alternation, longest label first; pure-ASCII labels may not touch letters, digits or '_'."""
    parts = []
    for label in sorted(labels, key=len, reverse=True):
        escaped = re.escape(label)
        if label.isascii():
            escaped = rf"(?<![&{_ASCII_EDGE}]){escaped}(?![{_ASCII_EDGE}])"
        parts.append(escaped)
    return re.compile("|".join(parts))


def _span(term_id: str, inner: str) -> str:
    return f'<span class="term" data-term="{html.escape(term_id, quote=True)}">{inner}</span>'


def _mark_text(text: str, pattern: re.Pattern, labels: dict[str, str], seen: set[str]) -> str:
    def wrap(match: re.Match) -> str:
        term_id = labels[match.group(0)]
        if term_id in seen:
            return match.group(0)
        seen.add(term_id)
        return _span(term_id, match.group(0))

    return pattern.sub(wrap, text)


def _is_whole_code(tokens: list[str], i: int, labels: dict[str, str]) -> bool:
    """<code>, one text token, </code> where the text is exactly a label."""
    return (i + 2 < len(tokens) and not tokens[i + 1].startswith("<")
            and tokens[i + 2].lower() == "</code>" and html.unescape(tokens[i + 1]) in labels)


def _wrap_code(tokens: list[str], labels: dict[str, str], seen: set[str]) -> str:
    code = "".join(tokens)
    term_id = labels[html.unescape(tokens[1])]
    if term_id in seen:
        return code
    seen.add(term_id)
    return _span(term_id, code)
