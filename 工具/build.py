"""Generate 学习台.html from the learning records.

Usage: python 工具\\build.py
"""
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from hub.assets import AssetBook
from hub.concepts import Concept, load_concepts
from hub.config import load_config
from hub.errors import FormatError
from hub.glossary import Term, parse_glossary
from hub.graph import build_concept_graph, build_graph, link_concept_next
from hub.mdrender import render_inline, render_markdown
from hub.notes import parse_note
from hub.owners import check_owner, valid_owners
from hub.page import ProjectView, Site, render_page
from hub.plans import OVERVIEW_FILE, load_days
from hub.records import duplicate_numbers, load_outputs, load_questions, load_work
from hub.search import search_entries
from hub.sections import find_heading, heading_count, mentions, section_text
from hub.skeleton import parse_skeleton
from hub.terms import mark_terms, number_headings, term_table
from hub.textio import read_text


def build(root: Path, code_root: Path | None, out: Path, now: datetime) -> list[FormatError]:
    """code_root None: the config's 代码根目录, else the folder that holds the knowledge base."""
    config, errors = load_config(root)
    book = AssetBook(code_root or config.code_root or root.parent)
    site = Site(generated_at=now.strftime("%Y-%m-%d %H:%M"), askers=list(config.askers))
    for name, section in (("问题.md", "问题"), ("成果.md", "成果"), ("工作.md", "工作"), ("计划", "计划")):
        book.map_section(root / name, section)
    concepts = _prepare_concepts(root / "概念", book, errors)
    _load_projects(root / "项目", book, site, errors)
    _build_graphs(root, concepts, book, site, errors)
    labels = _build_terms(root / "项目", book, site, errors)
    _load_plans(root / "计划", book, site, errors)
    _load_tables(root, book, site, errors)
    errors.extend(_check_records(site, concepts))
    titles = {note.path.resolve(): note.title for note, _ in site.notes.values()}
    _render_concepts(concepts, book, site, titles, labels)
    _load_attachments(book, site, labels)
    _build_search(site)
    _fill_graph_refs(book, site, titles)
    errors.extend(book.errors)
    site.images = book.images()
    site.errors = errors
    _write_page(out, render_page(site))
    return errors


def _write_page(out: Path, html: str, attempts: int = 6, delay: float = 0.25) -> None:
    """Write via a per-run temp file, then swap it in.

    The swap means concurrent hook runs never expose a half-written page. The unique temp
    name keeps two sessions from fighting over one temp file. Retries ride out a page that
    another run (or a browser) briefly holds open.
    """
    tmp = out.with_name(f"{out.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(html, encoding="utf-8", newline="\n")
        for attempt in range(attempts):
            try:
                os.replace(tmp, out)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(delay)
    finally:
        tmp.unlink(missing_ok=True)


def _prepare_concepts(concept_dir: Path, book: AssetBook, errors: list) -> list[Concept]:
    """Load cards and mark them rendered before notes link to them; the folder is optional."""
    if not concept_dir.is_dir():
        return []
    concepts, concept_errors = load_concepts(concept_dir)
    errors.extend(concept_errors)
    for concept in concepts:
        book.mark_rendered(concept.path)
    return concepts


def _check_records(site: Site, concepts: list[Concept]) -> list[FormatError]:
    """Cross-file checks that only make sense once every table and skeleton is loaded."""
    valid = valid_owners({p.name: p.skeleton for p in site.projects}, concepts)
    errors = duplicate_numbers(site.questions, "问题.md")
    for source, records in (("成果.md", site.outputs), ("问题.md", site.questions)):
        for record in records:
            if error := check_owner(record.fields["所属"], valid, source, record.line):
                errors.append(error)
    names = {p.name for p in site.projects} | {"通用"}  # 通用: work not tied to any project
    for record in site.work:
        if record.fields["项目"] not in names:
            errors.append(FormatError("工作.md", record.line, f"项目不存在：{record.fields['项目']}"))
    return errors


def _render_concepts(concepts: list[Concept], book: AssetBook, site: Site, titles: dict[Path, str],
                     labels: dict[str, str]) -> None:
    """Rendered last, so backlinks from every note, plan and table are known."""
    for concept in concepts:
        html = book.rewrite(render_markdown(concept.body_md), concept.path)
        html = _finish_doc(html, book.register_doc(concept.path), labels, site)
        referrers = _referrers(concept.path, book, titles)
        site.concepts.append((concept, book.register_doc(concept.path), html, referrers))


def _referrers(path: Path, book: AssetBook, titles: dict[Path, str]) -> list[tuple[str, str]]:
    """(title, in-page href) of every file that links to path; titles maps note paths to note titles."""
    return [(titles.get(source, source.stem), book.anchor_for(source)) for source in book.backlinks(path)]


def _build_graphs(root: Path, concepts: list[Concept], book: AssetBook, site: Site, errors: list) -> None:
    """One graph per project plus the concept graph; doc_nodes maps each doc to the nodes showing it."""
    concept_doc_ids = {concept.name: book.register_doc(concept.path) for concept in concepts}
    site.concept_graph = build_concept_graph(concepts, concept_doc_ids, root)
    for project in site.projects:
        project.graph, graph_errors = build_graph(project, site.notes, concepts, concept_doc_ids, root)
        errors.extend(graph_errors)
    link_concept_next(site.concept_graph, [project.graph for project in site.projects])
    for graph in _graphs(site):
        for node in graph["nodes"].values():
            if node["doc"] and node["kind"] != "point":
                site.doc_nodes.setdefault(node["doc"], []).append(node["id"])


def _finish_doc(html: str, doc_id: str, labels: dict[str, str], site: Site) -> str:
    """Number the headings (kept in site.headings), then mark the terms."""
    html, site.headings[doc_id] = number_headings(html, doc_id)
    return mark_terms(html, labels)


def _load_glossaries(project_dir: Path, site: Site, errors: list) -> dict[str, list[Term]]:
    """Terms of each project's 术语表.md (read by path; the file is optional)."""
    glossary: dict[str, list[Term]] = {}
    for project in site.projects:
        path = project_dir / project.name / "术语表.md"
        if path.is_file():
            glossary[project.name], glossary_errors = parse_glossary(read_text(path), f"{project.name}/术语表.md")
            errors.extend(glossary_errors)
    return glossary


def _build_terms(project_dir: Path, book: AssetBook, site: Site, errors: list) -> dict[str, str]:
    """Fill site.terms, number and mark every note body, and point each knowledge point at its heading id."""
    glossary = _load_glossaries(project_dir, site, errors)
    site.terms, labels = term_table([p.graph for p in site.projects], site.concept_graph, glossary)
    for project in site.projects:
        for term in glossary.get(project.name, []):
            entry = site.terms[f"g:{project.name}/{term.name}"]
            source = project_dir / project.name / "术语表.md"
            entry["summary"], entry["source"] = (book.rewrite(entry[key], source) for key in ("summary", "source"))
    for doc_id, (note, html) in site.notes.items():
        site.notes[doc_id] = (note, _finish_doc(html, doc_id, labels, site))
    errors.extend(_resolve_anchors(site))
    return labels


def _resolve_anchors(site: Site) -> list[FormatError]:
    """Replace each point's heading text by the id of the matching heading in its own note, and check that
    the heading is unique there and that its section names the point (or an alias)."""
    errors: list[FormatError] = []
    for graph in _graphs(site):
        for node in graph["nodes"].values():
            if node["kind"] != "point" or not node["anchor"]:
                continue
            note, body = site.notes[node["doc"]]
            headings = site.headings[node["doc"]]
            line = node["edit"]["line"] if node["edit"] else 0
            report = lambda message: errors.append(FormatError(note.path.name, line, message))
            index = find_heading(headings, node["anchor"])
            if index is None:
                report(f"知识点小节找不到：{node['anchor']}")
                node["anchor"] = ""
                continue
            if heading_count(headings, node["anchor"]) > 1:
                report(f"知识点指向重名小标题：{node['anchor']}")
            node["anchor"] = headings[index][2]
            if not mentions(section_text(body, node["anchor"]), [node["name"], *node["aliases"]]):
                report(f"知识点小节里没提到它：{node['name']}")
    return list(dict.fromkeys(errors))


def _build_search(site: Site) -> None:
    """Fill site.search; needs every doc rendered (headings) and its title."""
    titles = {doc_id: note.title for doc_id, (note, _) in site.notes.items()}
    titles.update({doc_id: concept.name for concept, doc_id, _, _ in site.concepts})
    titles.update({doc_id: title for doc_id, (title, _) in site.attachments.items()})
    site.search = search_entries([p.graph for p in site.projects], site.concept_graph, site.headings, titles)


def _graphs(site: Site) -> list[dict]:
    return [project.graph for project in site.projects] + [site.concept_graph]


def _fill_graph_refs(book: AssetBook, site: Site, titles: dict[Path, str]) -> None:
    """Rendered last, like the concept cards: every graph node showing a doc lists who links to it."""
    paths = {doc_id: note.path for doc_id, (note, _) in site.notes.items()}
    paths.update({doc_id: concept.path for concept, doc_id, _, _ in site.concepts})
    for graph in _graphs(site):
        for node in graph["nodes"].values():
            if node["doc"] in paths and node["kind"] != "point":
                node["refs"] = [list(ref) for ref in _referrers(paths[node["doc"]], book, titles)]


def _missing(path: Path, errors: list) -> bool:
    if path.exists():
        return False
    errors.append(FormatError(path.name, 0, "缺少文件"))
    return True


def _load_projects(project_root: Path, book: AssetBook, site: Site, errors: list) -> None:
    if _missing(project_root, errors):
        return
    for project_dir in sorted(p for p in project_root.iterdir() if (p / "骨架.md").is_file()):
        _load_project(project_dir, book, site, errors)


def _load_project(project_dir: Path, book: AssetBook, site: Site, errors: list) -> None:
    project = ProjectView(name=project_dir.name)
    book.map_section(project_dir / "骨架.md", "项目")
    site.projects.append(project)
    source = f"{project_dir.name}/骨架.md"
    project.skeleton, skeleton_errors = parse_skeleton(read_text(project_dir / "骨架.md"), source, project_dir)
    errors.extend(skeleton_errors)
    links = sorted({link for node in _walk(project.skeleton) for link in node.links})
    for link in links:
        book.mark_rendered(project_dir / link)
    for link in links:
        path = project_dir / link
        doc_id = book.register_doc(path)
        project.link_ids[link] = doc_id
        if doc_id in site.notes:
            continue
        note, note_errors = parse_note(path)
        errors.extend(note_errors)
        images = "".join(f'<img src="{image}">' for image in note.images)
        html = book.rewrite(images + render_markdown(note.body_md), path)
        site.notes[doc_id] = (note, html)


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _load_plans(plan_dir: Path, book: AssetBook, site: Site, errors: list) -> None:
    if _missing(plan_dir, errors):
        return
    overview = plan_dir / OVERVIEW_FILE
    if overview.exists():
        site.overview_html = book.rewrite(render_markdown(read_text(overview)), overview)
    days, day_errors = load_days(plan_dir)
    errors.extend(day_errors)
    site.days = [(day, *(book.rewrite(render_markdown(md), plan_dir / f"{day.date}.md") if md else ""
                          for md in (day.brief_md, day.detail_md)))
                 for day in days]


def _load_tables(root: Path, book: AssetBook, site: Site, errors: list) -> None:
    outputs_file, questions_file = root / "成果.md", root / "问题.md"
    if not _missing(outputs_file, errors):
        intro, site.outputs, table_errors = load_outputs(outputs_file)
        site.outputs_intro = book.rewrite(render_markdown(intro), outputs_file)
        errors.extend(table_errors)
        for record in site.outputs:
            link = f'<a href="{record.fields["位置"]}">打开</a>' if record.fields["位置"] else ""
            record.fields["位置"] = book.rewrite(link, outputs_file)
            _render_cells(record, ["名称", "说明"], book, outputs_file)
    if not _missing(questions_file, errors):
        intro, site.questions, table_errors = load_questions(questions_file, site.askers)
        site.questions_intro = book.rewrite(render_markdown(intro), questions_file)
        errors.extend(table_errors)
        for record in site.questions:
            _render_cells(record, ["问题", "怎么查", "答案"], book, questions_file)
    work_file = root / "工作.md"
    if work_file.exists():  # optional: a knowledge base for study has no work log
        site.work_enabled = True
        intro, site.work, table_errors = load_work(work_file)
        site.work_intro = book.rewrite(render_markdown(intro), work_file)
        errors.extend(table_errors)
        site.work.sort(key=lambda r: r.fields["日期"], reverse=True)
        for record in site.work:
            _render_cells(record, ["事项", "做了什么", "结果", "关联", "收获"], book, work_file)


def _render_cells(record, columns: list[str], book: AssetBook, source: Path) -> None:
    """Replace markdown cells with rendered HTML whose links went through the asset book."""
    for column in columns:
        record.fields[column] = book.rewrite(render_inline(record.fields[column]), source)


def _load_attachments(book: AssetBook, site: Site, labels: dict[str, str]) -> None:
    while pending := book.pending_docs():
        for path in pending:
            book.mark_rendered(path)
            text = read_text(path)
            title = text.split("\n", 1)[0][2:].strip() if text.startswith("# ") else path.name
            html = book.rewrite(render_markdown(text), path, attachment=True)
            doc_id = book.register_doc(path)
            site.attachments[doc_id] = (title, _finish_doc(html, doc_id, labels, site))


def main(argv: list[str] | None = None) -> int:
    """python 工具/build.py [知识库目录]; without an argument the knowledge base holds this 工具/ folder."""
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent
    out = root / "学习台.html"
    errors = build(root, None, out, datetime.now())
    for error in errors:
        print(error)
    print(f"已生成 {out.name}（{len(errors)} 条格式提示）")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
