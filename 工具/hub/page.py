import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import FormatError
from .mdrender import render_inline
from .concepts import Concept
from .notes import STATUS_ICON, Note
from .plans import Day, ratio_label
from .records import Record
from .skeleton import Node, coverage

STATIC = Path(__file__).parent / "static"
STATIC_CSS = ["kg.css"]
# status.js first: KG applies its overlay while parsing the data, before anything is drawn
STATIC_JS = ["status.js", "graph.js", "reader.js", "search.js"]
CONCEPT_GRAPH = "概念"  # key of the concept graph next to the project graphs; also its switch button
SECTIONS = ["项目", "概念", "计划", "工作", "成果", "问题"]
NAV_ICONS = {"项目": "🗺️", "概念": "💡", "计划": "📅", "工作": "💼", "成果": "🏆", "问题": "❓"}
# chip colour by value; anything else renders as a neutral chip
_CHIP_KIND = {"完成": "ok", "已掌握": "ok", "已解决": "ok", "进行中": "doing", "学习中": "doing", "待解决": "doing",
              "暂停": "idle", "归档": "idle", "只看过": "idle", "需求": "blue", "排查": "red", "评审": "purple",
              "运维": "teal", "笔记": "blue", "图": "purple", "分析": "teal", "数据": "orange", "代码": "red",
              "概念": "blue", "方法": "purple"}


@dataclass
class ProjectView:
    name: str
    skeleton: list[Node] = field(default_factory=list)
    link_ids: dict[str, str] = field(default_factory=dict)
    graph: dict = field(default_factory=dict)  # see hub.graph.build_graph


@dataclass
class Site:
    generated_at: str
    askers: list[str] = field(default_factory=list)  # empty: one column of open questions
    projects: list[ProjectView] = field(default_factory=list)
    notes: dict[str, tuple[Note, str]] = field(default_factory=dict)
    overview_html: str = ""  # 计划/总计划.md: the plan page's left column
    days: list[tuple[Day, str, str]] = field(default_factory=list)  # day, brief html, detail html
    outputs_intro: str = ""
    outputs: list[Record] = field(default_factory=list)
    questions_intro: str = ""
    questions: list[Record] = field(default_factory=list)
    work_enabled: bool = False  # 工作.md exists
    work_intro: str = ""
    work: list[Record] = field(default_factory=list)
    attachments: dict[str, tuple[str, str]] = field(default_factory=dict)
    # (card, doc id, body HTML, [(referrer title, referrer href)])
    concepts: list[tuple[Concept, str, str, list[tuple[str, str]]]] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)
    concept_graph: dict = field(default_factory=dict)
    doc_nodes: dict[str, list[str]] = field(default_factory=dict)  # doc id -> ids of graph nodes showing it
    headings: dict[str, list[tuple[int, str, str]]] = field(default_factory=dict)  # doc id -> [(level, text, id)]
    terms: dict[str, dict] = field(default_factory=dict)  # see hub.terms.term_table
    search: list[dict] = field(default_factory=list)  # see hub.search.search_entries
    errors: list[FormatError] = field(default_factory=list)


def render_page(site: Site) -> str:
    sections = {
        "项目": _project(site), "概念": _concepts(site), "计划": _plans(site), "工作": _work(site),
        "成果": _outputs(site), "问题": _questions(site),
    }
    sections = {name: content for name, content in sections.items() if name in _sections(site)}
    body = "".join(f'<section class="sec" id="sec-{name}">{content}</section>' for name, content in sections.items())
    return _TEMPLATE.format(
        css=_CSS + _static(STATIC_CSS), js=_JS + _static(STATIC_JS), data=_graph_data(site), nav=_nav(site),
        errors=_errors(site.errors), sections=body, docs=_docs(site), templates=_image_templates(site),
        generated_at=site.generated_at,
    )


def _sections(site: Site) -> list[str]:
    return [name for name in SECTIONS if name != "工作" or site.work_enabled]


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def _static(names: list[str]) -> str:
    return "".join((STATIC / name).read_text(encoding="utf-8") for name in names)


def _graph_data(site: Site) -> str:
    """Everything the page scripts draw from, as JSON that is safe inside a <script> element."""
    graphs = {project.name: project.graph for project in site.projects}
    graphs[CONCEPT_GRAPH] = site.concept_graph
    data = {"generatedAt": site.generated_at, "graphs": graphs, "terms": site.terms,
            "search": site.search, "docNodes": site.doc_nodes}
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # '</' could close the element; '<!--' could make the parser skip the real </script>
    return text.replace("</", "<\\/").replace("<!--", "<\\u0021--")


def _nav(site: Site) -> str:
    covered = total = 0
    for project in site.projects:
        for block in _blocks(project):
            c, t = coverage(block)
            covered, total = covered + c, total + t
    open_questions = sum(1 for q in site.questions if q.fields["状态"] == "待解决")
    counts = {"项目": f"{covered}/{total}", "计划": f"{len(site.days)} 天",
              "成果": f"{len(site.outputs)} 项", "问题": f"{open_questions} 待解决",
              "概念": f"{len(site.concepts)} 张", "工作": f"{len(site.work)} 条"}
    links = "".join(f'<a href="#{name}" data-nav="{name}"><span class="nav-icon">{NAV_ICONS[name]}</span>'
                    f'<span class="nav-name">{name}</span><span class="count">{counts[name]}</span></a>'
                    for name in _sections(site))
    search = ('<div class="nav-search"><input id="search" type="search" placeholder="搜索知识点、笔记、表名…">'
              '<div id="search-results"></div></div>')
    return (f'<div class="brand"><div class="brand-name">学习台</div><div class="brand-sub">个人知识库</div></div>'
            f'{search}<div class="nav-links">{links}</div><div class="nav-foot">更新于 {_esc(site.generated_at)}</div>')


def _header(title: str, subtitle: str) -> str:
    return f'<header class="page-head"><h1>{title}</h1><p class="page-sub">{subtitle}</p></header>'


def _chip(text: str, kind: str = "") -> str:
    return f'<span class="chip {kind}">{_esc(text)}</span>' if text else ""


def _cells(row: dict[str, str], columns: list[str], escaped: set[str], chips: set[str], narrow: set[str]) -> str:
    """Table cells: escaped plain text, chips for enum columns, raw HTML for pre-rendered ones."""
    out = []
    for column in columns:
        value = row[column]
        content = _chip(value, _CHIP_KIND.get(value, "")) if column in chips else (_esc(value) if column in escaped else value)
        out.append(f'<td class="nowrap">{content}</td>' if column in narrow else f"<td>{content}</td>")
    return "".join(out)


def _errors(errors: list[FormatError]) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{_esc(str(e))}</li>" for e in errors)
    return f'<details class="warn"><summary>⚠ {len(errors)} 条格式提示</summary><ul>{items}</ul></details>'


# ---- 项目 ----

def _project(site: Site) -> str:
    names = [p.name for p in site.projects] + [CONCEPT_GRAPH]
    switch = "".join(f'<button class="proj-tab" data-project="{_esc(name)}">{_esc(name)}</button>' for name in names)
    panes = "".join(_project_pane(p, site) for p in site.projects)
    panes += f'<div class="proj-pane" data-pane="{CONCEPT_GRAPH}">{_graph_shell(CONCEPT_GRAPH)}</div>'
    return (_header("项目", "每个项目一张地图：哪几块已经弄懂，哪几块还是空白。")
            + f'<div class="proj-switch">{switch}</div>{panes}')


def _blocks(project: ProjectView) -> list[Node]:
    return [node for node in project.skeleton if not node.reference]


def _project_pane(project: ProjectView, site: Site) -> str:
    """Block cards, the reference row, and the empty tree + graph the page scripts draw from the JSON."""
    graph_blocks = {node["block"]: node for node in project.graph["nodes"].values() if node["kind"] == "block"}
    bars = "".join(_coverage_bar(block, graph_blocks.get(i)) for i, block in enumerate(_blocks(project)))
    return (f'<div class="proj-pane" data-pane="{_esc(project.name)}">'
            f'<div class="stats">{bars}</div>{_references(project, site)}{_graph_shell(project.name)}</div>')


def _graph_shell(name: str) -> str:
    return (f'<div class="kg" data-graph="{_esc(name)}"><aside class="kg-tree"></aside><div class="kg-stage">'
            '<div class="kg-bar"></div><svg class="kg-svg"></svg><div class="kg-card"></div></div></div>')


def _references(project: ProjectView, site: Site) -> str:
    """Reference material (glossary, tool maps) as one row of links, apart from the learning blocks."""
    links = [(node.name, project.link_ids[link]) for root in project.skeleton if root.reference
             for node in _walk(root) for link in node.links]
    if not links:
        return ""
    chips = "".join(f'<a class="ref-link" href="#doc-{doc_id}">📚 {_esc(name)}</a>' for name, doc_id in links)
    return f'<div class="refs"><span class="refs-label">参考</span>{chips}</div>'


def _walk(node: Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _coverage_bar(block: Node, graph_node: dict | None) -> str:
    """One block card; graph_node is the block in the project graph (None if a same-named block took its id)."""
    covered, total = coverage(block)
    percent = 100 * covered // total if total else 0
    name = block.name.split(" · ", 1)
    sub = f'<div class="stat-sub">{_esc(name[1])}</div>' if len(name) > 1 else ""
    level = "full" if percent >= 60 else "mid" if percent >= 25 else "low" if percent else "none"
    target = mastery = ""
    if graph_node:
        target = f' data-block="{_esc(graph_node["id"])}"'
        mastery = f'<div class="stat-mastery">已掌握 {graph_node["mastered"]}/{graph_node["units"]}</div>'
    return (f'<a class="stat {level}" href="#项目"{target} title="在图谱里看这一块">'
            f'<div class="stat-name">{_esc(name[0])}</div>{sub}'
            f'<div class="stat-num">{covered}/{total}<span class="stat-pct">{percent}%</span></div>'
            f'<div class="bar-track"><span class="bar-fill" style="width:{percent}%"></span></div>{mastery}</a>')


# ---- 概念 ----

def _concepts(site: Site) -> str:
    cards = "".join(
        f'<a class="concept" href="#doc-{doc_id}"><div class="concept-top">'
        f'<span class="concept-name">{_esc(c.name)}</span>{_chip(c.kind or "", _CHIP_KIND.get(c.kind or "", ""))}</div>'
        f'<div class="concept-meta">{STATUS_ICON[c.status]} {_esc(c.status or "未标状态")}'
        f'<span class="concept-refs">被引用 {len(refs)}</span></div></a>'
        for c, doc_id, _, refs in site.concepts)
    return _header("概念", "跨项目通用的概念和方法，一张卡一个；主题笔记用到时链接过来。") + f'<div class="concept-grid">{cards}</div>'


def _concept_doc(site: Site, concept: Concept, doc_id: str, body: str, referrers: list[tuple[str, str]]) -> str:
    meta = [f"{STATUS_ICON[concept.status]} {concept.status or '未标状态'}"]
    if concept.kind:
        meta.append(_esc(concept.kind))
    if concept.aliases:
        meta.append("别名：" + _esc("、".join(concept.aliases)))
    return _article(site, doc_id, f'<h1>{_esc(concept.name)}</h1><p class="muted">{" · ".join(meta)}</p>{body}',
                    referrers)


# ---- 计划 ----

def _plans(site: Site) -> str:
    days = "".join(_day(day, brief, detail) for day, brief, detail in site.days)
    return (_header("计划", "总计划定目标和每周进度，每天的计划跟着它排。")
            + f'<div class="plan-grid"><div class="plan-side">{_overview(site)}</div>'
            f'<div class="days"><h2>每日记录</h2>{days}</div></div>')


def _overview(site: Site) -> str:
    """The master plan: goals, checkpoints and the weekly table the days are drafted from."""
    return f'<div class="panel route overview">{site.overview_html}</div>' if site.overview_html else ""


def _day(day: Day, brief: str, detail: str) -> str:
    """Plan and 要点 show when the day opens; the full log (做了什么、搞懂了……) stays folded below."""
    ratio = ratio_label(day)
    badge = ""
    if ratio:
        done = sum(1 for _, finished in day.tasks if finished)
        percent = 100 * done // len(day.tasks) if day.tasks else 0
        badge = (f'<span class="badge">{ratio}</span>'
                 f'<span class="mini-track"><span class="bar-fill" style="width:{percent}%"></span></span>')
    body = _checkboxes(brief)
    if detail:
        body += (f'<details class="day-more"><summary>详细记录</summary>'
                 f'<div class="day-more-body">{_checkboxes(detail)}</div></details>')
    return f'<details class="day"><summary><span class="day-title">{_esc(day.title)}</span>{badge}</summary><div class="day-body">{body}</div></details>'


def _checkboxes(html_text: str) -> str:
    return (html_text.replace("<li>[x] ", '<li class="done">☑ ').replace("<li>[X] ", '<li class="done">☑ ')
            .replace("<li>[ ] ", "<li>☐ "))


# ---- 成果 ----

def _outputs(site: Site) -> str:
    types = sorted({r.fields["类型"] for r in site.outputs})
    owners = sorted({r.fields["所属"] for r in site.outputs})
    filters = (_select("outputs", "type", "全部类型", types) + _select("outputs", "owner", "全部所属", owners))
    columns = ["日期", "名称", "类型", "所属", "状态", "位置", "说明"]
    rows = "".join(
        f'<tr data-type="{_esc(r.fields["类型"])}" data-owner="{_esc(r.fields["所属"])}">'
        + _cells(r.fields, columns, {"日期", "所属"}, {"类型", "状态"}, {"日期", "类型", "状态", "位置"}) + "</tr>"
        for r in site.outputs)
    head = "".join(f"<th>{h}</th>" for h in columns)
    return (_header("成果", "自己做过的东西：笔记、图、分析、数据……文件留在原处，这里只放入口。")
            + f'<div class="intro">{site.outputs_intro}</div><div class="filters">{filters}</div>'
            f'<div class="table-wrap"><table id="outputs"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')


def _select(table: str, key: str, label: str, values: list[str]) -> str:
    """A filter for rows of table#{table} whose data-{key} equals the chosen value."""
    options = "".join(f'<option value="{_esc(v)}">{_esc(v)}</option>' for v in values)
    return f'<select data-table="{table}" data-filter="{key}"><option value="">{label}</option>{options}</select>'


# ---- 工作 ----

def _work(site: Site) -> str:
    projects = sorted({r.fields["项目"] for r in site.work})
    types = sorted({r.fields["类型"] for r in site.work})
    filters = _select("work", "project", "全部项目", projects) + _select("work", "type", "全部类型", types)
    columns = ["日期", "项目", "类型", "事项", "做了什么", "结果", "关联", "收获"]
    rows = "".join(
        f'<tr data-project="{_esc(r.fields["项目"])}" data-type="{_esc(r.fields["类型"])}">'
        + _cells(r.fields, columns, {"日期", "项目"}, {"类型"}, {"日期", "项目", "类型"}) + "</tr>"
        for r in site.work)
    head = "".join(f"<th>{h}</th>" for h in columns)
    return (_header("工作", "真实的工作：需求、排查、评审……以及从中学到的东西。")
            + f'<div class="intro">{site.work_intro}</div><div class="filters">{filters}</div>'
            f'<div class="table-wrap"><table id="work"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')


# ---- 问题 ----

def _questions(site: Site) -> str:
    open_ = [q for q in site.questions if q.fields["状态"] == "待解决"]
    groups = ([(asker, [q for q in open_ if q.fields["问谁"] == asker]) for asker in site.askers]
              if site.askers else [("待解决", open_)])
    columns = "".join(
        f'<div class="column col-{i}"><h3>{title}<span class="col-count">{len(items)}</span></h3>'
        + "".join(_card(q) for q in items) + "</div>"
        for i, (title, items) in enumerate(groups))
    solved = [q for q in site.questions if q.fields["状态"] == "已解决"]
    groups: dict[str, list[Record]] = {}
    for q in solved:
        groups.setdefault(_topic(q.fields["所属"]), []).append(q)
    solved_groups = "".join(_solved_group(topic, groups[topic]) for topic in sorted(groups))
    return (_header("问题", "待解决的问题按该问谁分列。")
            + f'<div class="intro">{site.questions_intro}</div><div class="board">{columns}</div>'
            f'<details class="solved"><summary>已解决（{len(solved)}）</summary>{solved_groups}</details>')


def _topic(owner: str) -> str:
    """Group key for a solved question: project owners keep three levels, others one."""
    parts = owner.split("/")
    return "/".join(parts[:3]) if len(parts) > 1 and parts[0] != "概念" else parts[0]


def _solved_group(topic: str, items: list[Record]) -> str:
    rows = "".join(
        f'<tr><td>{_esc(q.fields["编号"])}</td><td>{q.fields["问题"]}</td>'
        f'<td>{q.fields["答案"]}</td><td>{_esc(q.fields["来源/日期"])}</td></tr>' for q in items)
    return (f'<details class="solved-group"><summary>{_esc(topic)}（{len(items)}）</summary>'
            f'<div class="table-wrap"><table><thead><tr><th>编号</th><th>问题</th><th>答案</th>'
            f'<th>来源/日期</th></tr></thead><tbody>{rows}</tbody></table></div></details>')


def _card(q: Record) -> str:
    f = q.fields
    how = f'<p><b>怎么查：</b>{f["怎么查"]}</p>' if f["怎么查"] else ""
    return (f'<details class="card"><summary><span class="qid">{_esc(f["编号"])}</span> {f["问题"]}</summary>'
            f'{how}<p class="muted">{_esc(f["所属"])} · {_esc(f["来源/日期"])}</p></details>')


# ---- 笔记与附页 ----

def _docs(site: Site) -> str:
    nodes = {node_id: node for project in site.projects for node_id, node in project.graph["nodes"].items()}

    def note_refs(doc_id: str) -> list:
        """Who links to the note, as kept on the first graph node showing it."""
        shown_at = site.doc_nodes.get(doc_id)
        return nodes[shown_at[0]]["refs"] if shown_at else []

    notes = "".join(_note_doc(site, doc_id, note, body, note_refs(doc_id)) for doc_id, (note, body) in site.notes.items())
    notes += "".join(_concept_doc(site, *entry) for entry in site.concepts)
    attachments = "".join(_article(site, doc_id, body, [], BACK_TO_OUTPUTS) for doc_id, (_, body) in site.attachments.items())
    return notes + attachments


def _note_doc(site: Site, doc_id: str, note: Note, body: str, refs: list) -> str:
    # with points the note's status is their rollup, shown by the reading page's top chip
    meta = [] if note.points else [f"{STATUS_ICON[note.status]} {note.status or '未标状态'}"]
    if note.updated:
        meta.append(f"更新 {_esc(note.updated)}")
    meta_line = f'<p class="muted">{" · ".join(meta)}</p>' if meta else ""
    code = f'<p class="muted">代码：{render_inline(note.code)}</p>' if note.code else ""
    return _article(site, doc_id, f'<h1>{_esc(note.title)}</h1>{meta_line}{code}{body}', refs)


BACK_TO_GRAPH = ("#项目", "← 回到图谱")
BACK_TO_OUTPUTS = ("#成果", "← 返回成果")  # attachments are opened from 成果


def _article(site: Site, doc_id: str, body: str, refs: list, back: tuple[str, str] = BACK_TO_GRAPH) -> str:
    """The reading page every doc shares. Scripts fill the crumb, status, mini graph and point list
    from the JSON (data-nodes names the graph nodes showing this doc); the toc and refs are static."""
    nodes = _esc(",".join(site.doc_nodes.get(doc_id, [])))
    return (f'<article class="doc" id="doc-{doc_id}" data-nodes="{nodes}">'
            f'<div class="doc-top"><a class="back-graph" href="{back[0]}">{back[1]}</a>'
            '<nav class="crumb"></nav><span class="doc-status"></span></div><div class="crumb-also"></div>'
            f'<div class="doc-grid"><div class="doc-body">{body}</div><aside class="doc-side">'
            '<div class="mini"></div><div class="side-points"></div>'
            f'<div class="side-toc">{_side_toc(site.headings.get(doc_id, []))}</div>'
            f'<div class="side-refs">{_side_refs(refs)}</div></aside></div></article>')


def _side_toc(headings: list[tuple[int, str, str]]) -> str:
    """Links to the doc's h2/h3 headings; h3 entries are indented."""
    if not headings:
        return ""
    indent = {3: ' class="toc-3"'}
    links = "".join(f'<a href="#{_esc(heading_id)}" data-toc{indent.get(level, "")}>{_esc(text)}</a>'
                    for level, text, heading_id in headings)
    return f'<div class="side-title">本页目录</div>{links}'


def _side_refs(refs: list) -> str:
    """'引用了我': (title, in-page href) of everything linking to the doc."""
    if not refs:
        return ""
    items = "".join(f'<li><a href="{_esc(href)}">{_esc(title)}</a></li>' for title, href in refs)
    return f'<div class="side-title">引用了我</div><ul>{items}</ul>'


def _image_templates(site: Site) -> str:
    return "".join(f'<template id="{image_id}"><img src="{uri}"></template>' for image_id, uri in site.images.items())


_CSS = """
:root{--bg:#f4f5f7;--panel:#fff;--panel-2:#f8f9fb;--text:#1d2129;--text-2:#4e5969;--muted:#86909c;
--line:#e5e6eb;--accent:#3370ff;--accent-soft:#e8efff;--ok:#00b42a;--ok-soft:#e8ffea;--doing:#ff7d00;
--doing-soft:#fff3e8;--idle:#86909c;--idle-soft:#f2f3f5;--warn-bg:#fff7e8;--warn-line:#ffcf8b;
--warn-text:#ad4e00;--shadow:0 1px 2px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.04);--radius:10px}
@media (prefers-color-scheme:dark){:root{--bg:#141518;--panel:#1d1e22;--panel-2:#232429;--text:#e8e9eb;
--text-2:#b8bcc4;--muted:#80858f;--line:#2e3036;--accent:#6b96ff;--accent-soft:#1f2a45;--ok:#3cd17a;
--ok-soft:#173326;--doing:#ffa047;--doing-soft:#3a2a17;--idle:#8b909a;--idle-soft:#2a2c31;--warn-bg:#33270f;
--warn-line:#6b4f1d;--warn-text:#ffcf8b;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);display:flex;
font:15px/1.75 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
.muted{color:var(--muted);font-size:13px}
/* sidebar */
body>nav{width:220px;height:100vh;position:sticky;top:0;flex-shrink:0;display:flex;flex-direction:column;
background:var(--panel);border-right:1px solid var(--line);padding:20px 12px}
.brand{padding:0 10px 18px;margin-bottom:10px;border-bottom:1px solid var(--line)}
.brand-name{font-size:20px;font-weight:700;letter-spacing:.5px}
.brand-sub{font-size:12px;color:var(--muted)}
.nav-links{flex:1}
.nav-links a{display:flex;align-items:center;gap:10px;padding:9px 12px;margin:2px 0;border-radius:8px;color:var(--text-2)}
.nav-links a:hover{background:var(--panel-2);text-decoration:none}
.nav-links a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
.nav-icon{width:20px;text-align:center} .nav-name{flex:1}
.nav-links .count{font-size:12px;color:var(--muted);background:var(--panel-2);padding:0 8px;border-radius:10px}
.nav-links a.active .count{background:var(--panel);color:var(--accent)}
.nav-foot{font-size:11px;color:var(--muted);padding:10px 12px 0;border-top:1px solid var(--line)}
/* main */
main{flex:1;min-width:0;padding:28px 40px 40px;max-width:1240px}
.sec,.doc{display:none} .sec.show,.doc.show{display:block;animation:fade .15s ease-out}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.page-head{margin-bottom:18px} .page-head h1{margin:0;font-size:26px;letter-spacing:.5px}
.page-sub{margin:4px 0 0;color:var(--muted);font-size:14px}
h2{font-size:18px;margin:22px 0 10px} h3{font-size:15px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px 20px;box-shadow:var(--shadow)}
.intro{color:var(--text-2);font-size:14px} .intro:empty{display:none}
.intro blockquote{margin:0 0 12px}
.warn{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-text);padding:8px 14px;
border-radius:8px;margin-bottom:18px;font-size:14px} .warn summary{cursor:pointer;font-weight:600}
.warn ul{margin:6px 0 2px;padding-left:20px}
/* chips and badges */
.chip{display:inline-block;padding:0 9px;border-radius:999px;font-size:12px;line-height:20px;white-space:nowrap;
background:var(--idle-soft);color:var(--text-2)}
.chip.ok{background:var(--ok-soft);color:var(--ok)} .chip.doing{background:var(--doing-soft);color:var(--doing)}
.chip.idle{background:var(--idle-soft);color:var(--idle)} .chip.blue{background:var(--accent-soft);color:var(--accent)}
.chip.purple{background:rgba(114,46,209,.12);color:#8e5cd9} .chip.teal{background:rgba(20,201,201,.12);color:#0fa3a3}
.chip.orange{background:var(--doing-soft);color:var(--doing)} .chip.red{background:rgba(245,63,63,.1);color:#e5484d}
.badge{font-size:12px;color:var(--text-2);background:var(--panel-2);padding:0 8px;border-radius:10px;white-space:nowrap}
/* project */
.proj-switch{margin:0 0 14px;display:flex;gap:8px}
.proj-tab{padding:5px 16px;border:1px solid var(--line);border-radius:999px;background:var(--panel);
color:var(--text-2);cursor:pointer;font:inherit;font-size:14px}
.proj-tab:hover{border-color:var(--accent);color:var(--accent)}
.proj-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.proj-pane{display:none} .proj-pane.show{display:block}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:16px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow);
display:block;color:inherit;text-decoration:none;cursor:pointer;transition:border-color .15s,transform .15s}
.stat:hover{border-color:var(--accent);transform:translateY(-1px)}
.refs{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:-4px 0 16px}
.refs-label{font-size:12px;color:var(--muted);margin-right:2px}
.ref-link{font-size:13px;padding:4px 10px;border-radius:14px;background:var(--panel-2);border:1px solid var(--line);color:var(--text-2);text-decoration:none}
.ref-link:hover{border-color:var(--accent);color:var(--accent)}
.stat-name{font-weight:600} .stat-sub{font-size:12px;color:var(--muted);margin-top:-2px}
.stat-num{font-size:24px;font-weight:700;margin:6px 0 8px;font-variant-numeric:tabular-nums}
.stat-pct{font-size:13px;font-weight:400;color:var(--muted);margin-left:8px}
.stat.none .stat-num{color:var(--muted)}
.bar-track{display:block;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.bar-fill{display:block;height:100%;background:var(--accent);border-radius:3px}
.stat.full .bar-fill{background:var(--ok)} .stat.low .bar-fill{background:var(--doing)}
/* concepts */
.concept-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.concept{display:block;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
padding:14px 16px;color:var(--text);box-shadow:var(--shadow);transition:border-color .15s,transform .15s}
.concept:hover{border-color:var(--accent);transform:translateY(-1px);text-decoration:none}
.concept-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.concept-name{font-weight:600;font-size:15px}
.concept-meta{margin-top:8px;font-size:13px;color:var(--text-2);display:flex;justify-content:space-between}
.concept-refs{color:var(--muted)}
/* plans */
.plan-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:20px;align-items:start}
.route h1{display:none} .route h2{font-size:16px;margin:18px 0 6px} .route h3{margin:14px 0 4px}
.route>p:first-of-type,.route blockquote{font-size:13px}
.days h2{margin-top:0}
.plan-side{display:flex;flex-direction:column;gap:20px;min-width:0} .overview h1{display:block;font-size:18px;margin:0 0 8px}
.day{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);margin:8px 0;box-shadow:var(--shadow)}
.day summary{cursor:pointer;padding:10px 14px;display:flex;align-items:center;gap:10px;list-style:none}
.day summary::-webkit-details-marker{display:none}
.day-title{flex:1;font-weight:600}
.mini-track{width:60px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.mini-track .bar-fill{background:var(--ok)}
.day-body{padding:0 16px 10px;border-top:1px solid var(--line)}
.day-body li.done{color:var(--muted)}
.day-body li li{font-size:13px;color:var(--muted)}
.day-more{margin-top:10px;border-top:1px dashed var(--line)}
.day .day-more summary{padding:8px 0 0;font-size:13px;color:var(--muted)}
.day .day-more summary::before{content:"▸ "} .day .day-more[open] summary::before{content:"▾ "}
.day-more-body{font-size:14px}
/* tables */
.filters{display:flex;gap:8px;margin:4px 0 12px}
.filters select{padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);font:inherit;font-size:13px}
.table-wrap{overflow:auto;max-height:calc(100vh - 220px);background:var(--panel);border:1px solid var(--line);
border-radius:var(--radius);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{position:sticky;top:0;z-index:1;background:var(--panel-2);color:var(--text-2);font-weight:600;font-size:13px;
text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top;line-height:1.6}
tbody tr:nth-child(even){background:var(--panel-2)} tbody tr:hover{background:var(--accent-soft)}
tbody tr:last-child td{border-bottom:none}
td.nowrap{white-space:nowrap}
#outputs,#work{min-width:960px}
/* questions */
.board{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start}
.column{background:var(--panel-2);border:1px solid var(--line);border-radius:var(--radius);padding:10px}
.column h3{margin:2px 4px 10px;display:flex;align-items:center;gap:8px}
.col-count{font-size:12px;font-weight:400;color:var(--muted);background:var(--panel);padding:0 8px;border-radius:10px}
.card{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;
padding:8px 12px;margin:8px 0;box-shadow:var(--shadow);font-size:14px}
.col-1 .card{border-left-color:var(--doing)} .col-2 .card{border-left-color:#8e5cd9}
.card summary{cursor:pointer;list-style:none} .card summary::-webkit-details-marker{display:none}
.card p{margin:8px 0 0}
.qid{font-weight:700;color:var(--text-2);margin-right:4px;font-variant-numeric:tabular-nums}
.solved{margin-top:20px} .solved>summary{cursor:pointer;font-weight:600;margin-bottom:10px}
.solved-group{margin:0 0 10px 12px} .solved-group>summary{cursor:pointer;color:var(--text-2);margin-bottom:6px}
/* note pages (reading layout in kg.css) */
.doc h1{font-size:26px;margin:8px 0 4px} .doc h2{border-bottom:1px solid var(--line);padding-bottom:6px;margin-top:28px}
.doc-body>p.muted{margin-top:0}
.doc table{background:var(--panel);border:1px solid var(--line);border-radius:8px;display:block;overflow-x:auto}
pre{background:var(--panel-2);border:1px solid var(--line);padding:12px 14px;border-radius:8px;overflow-x:auto;font-size:13px}
code{font-family:"Cascadia Code",Consolas,monospace;font-size:.92em;background:var(--panel-2);padding:1px 5px;border-radius:4px}
pre code{background:none;padding:0}
blockquote{margin:10px 0;padding:8px 14px;border-left:3px solid var(--accent);background:var(--accent-soft);
border-radius:0 8px 8px 0;color:var(--text-2)}
blockquote p{margin:4px 0}
.doc img,.route img{max-width:100%;background:#fff;border:1px solid var(--line);border-radius:8px;margin:8px 0;cursor:zoom-in}
a.broken{color:#e5484d;text-decoration:line-through}
#overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:9;overflow:auto;cursor:zoom-out;padding:24px}
#overlay.show{display:block} #overlay img{max-width:100%;background:#fff;display:block;margin:auto;border-radius:8px}
footer{margin-top:40px;color:var(--muted);font-size:12px}
@media (max-width:1000px){.plan-grid,.board{grid-template-columns:1fr}}
"""

_JS = """
function show(){
  var h=decodeURIComponent(location.hash.slice(1))||'项目';
  document.querySelectorAll('.sec,.doc').forEach(function(e){e.classList.remove('show')});
  var doc=h.indexOf('doc-')===0?document.getElementById(h):null;
  var sec=doc?null:(document.getElementById('sec-'+h)||document.getElementById('sec-项目'));
  (doc||sec).classList.add('show');
  var active=doc?null:sec.id.slice(4);
  document.querySelectorAll('.nav-links a').forEach(function(a){a.classList.toggle('active',a.dataset.nav===active)});
  if(typeof Reader!=='undefined')Reader.arrive();else window.scrollTo(0,0);
}
window.addEventListener('hashchange',show);show();
function pickProject(name){
  document.querySelectorAll('.proj-pane').forEach(function(p){p.classList.toggle('show',p.dataset.pane===name)});
  document.querySelectorAll('.proj-tab').forEach(function(b){b.classList.toggle('active',b.dataset.project===name)});
}
document.querySelectorAll('.proj-tab').forEach(function(b){b.addEventListener('click',function(){pickProject(b.dataset.project)})});
var firstTab=document.querySelector('.proj-tab');if(firstTab)pickProject(firstTab.dataset.project);
document.addEventListener('click',function(e){
  var a=e.target.closest('[data-img]');var o=document.getElementById('overlay');
  if(a){e.preventDefault();o.innerHTML=document.getElementById(a.dataset.img).innerHTML;o.classList.add('show');}
  else if(e.target.closest('#overlay')){o.classList.remove('show');}
});
document.querySelectorAll('select[data-filter]').forEach(function(s){s.addEventListener('change',function(){
  var table=s.dataset.table,picks=[].slice.call(document.querySelectorAll('select[data-table="'+table+'"]'));
  document.querySelectorAll('#'+table+' tbody tr').forEach(function(r){
    r.style.display=picks.every(function(p){return !p.value||r.dataset[p.dataset.filter]===p.value})?'':'none';});
});});
"""

_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>学习台</title><style>{css}</style></head>
<body><nav>{nav}</nav><main>{errors}{sections}{docs}<footer>生成时间：{generated_at}</footer></main>
<div id="overlay"></div><aside id="peek" hidden></aside>{templates}
<script type="application/json" id="kg-data">{data}</script><script>{js}</script></body></html>
"""
