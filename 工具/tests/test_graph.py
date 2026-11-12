import unittest
from pathlib import Path

from hub.assets import AssetBook
from hub.concepts import load_concepts
from hub.errors import FormatError
from hub.graph import build_concept_graph, build_graph, link_concept_next
from hub.knowledge import Point
from hub.mdrender import render_markdown
from hub.notes import parse_note
from hub.page import ProjectView
from hub.skeleton import Node, parse_skeleton
from hub.textio import read_text

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"
DEMO = SAMPLE / "项目/示例项目"
OUTBOUND = "示例项目/业务/交易/出库/出库流程"
PLAN = "示例项目/业务/交易/订单与优惠/付款计划生成"
OUTBOUND_FILE = DEMO / "业务/出库数据流.md"


def load_sample():
    """Project view, notes and concepts of the sample 示例项目 project, as build.py prepares them."""
    book = AssetBook(FIXTURES)
    project = ProjectView(name="示例项目")
    project.skeleton, _ = parse_skeleton(read_text(DEMO / "骨架.md"), "示例项目/骨架.md", DEMO)
    notes = {}
    for node in _walk(project.skeleton):
        for link in node.links:
            doc_id = book.register_doc(DEMO / link)
            project.link_ids[link] = doc_id
            note = parse_note(DEMO / link)[0]
            notes.setdefault(doc_id, (note, render_markdown(note.body_md)))
    concepts, _ = load_concepts(SAMPLE / "概念")
    concept_doc_ids = {c.name: book.register_doc(c.path) for c in concepts}
    return project, notes, concepts, concept_doc_ids, book


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.project, self.notes, self.concepts, self.concept_doc_ids, self.book = load_sample()

    def _graph(self):
        return build_graph(self.project, self.notes, self.concepts, self.concept_doc_ids, SAMPLE)

    def _outbound_note(self):
        return self.notes[self.book.register_doc(OUTBOUND_FILE)][0]

    def test_leaf_and_note_merge_with_points(self):
        graph, errors = self._graph()
        self.assertEqual(errors, [])
        self.assertEqual((graph["name"], graph["root"]), ("示例项目", "示例项目"))
        node = graph["nodes"][OUTBOUND]
        self.assertEqual((node["kind"], node["name"]), ("note", "出库流程"))
        self.assertEqual(node["doc"], self.book.register_doc(OUTBOUND_FILE))
        self.assertEqual(node["children"], [f"{OUTBOUND}/出库四幕", f"{OUTBOUND}/出库幂等", f"{OUTBOUND}/回调重试"])
        point = graph["nodes"][f"{OUTBOUND}/出库四幕"]
        self.assertEqual((point["kind"], point["parent"], point["doc"]), ("point", OUTBOUND, node["doc"]))
        self.assertEqual((point["anchor"], point["summary"]), ("一句话", "下单、审核、出库、回调"))
        self.assertEqual(graph["nodes"]["示例项目/业务"]["kind"], "block")
        self.assertEqual(graph["nodes"]["示例项目/业务/交易"]["kind"], "group")
        self.assertEqual(graph["nodes"]["示例项目"]["kind"], "project")
        self.assertEqual(graph["nodes"]["示例项目"]["children"], ["示例项目/业务", "示例项目/发货"])
        self.assertEqual([graph["nodes"][i]["block"] for i in ("示例项目", "示例项目/业务", OUTBOUND, "示例项目/发货/分拣")],
                         [-1, 0, 0, 1])
        self.assertEqual(graph["nodes"]["示例项目/业务"]["doc"], self.book.register_doc(DEMO / "系统全景.md"))

    def test_same_note_counted_once_upstream(self):
        graph, _ = self._graph()
        nodes = graph["nodes"]
        self.assertEqual(nodes["示例项目/业务/交易"]["units"], 3)
        self.assertEqual(nodes["示例项目/业务/交易"]["mastered"], 1)
        # 系统全景 (on the block itself, 学习中) + 出库数据流 (3 points) + 发货 (no status)
        root = nodes["示例项目"]
        self.assertEqual((root["units"], root["mastered"], root["started"]), (5, 1, 3))
        self.assertEqual(root["status"], "学习中")

    def test_points_hang_under_one_node_only(self):
        nodes = self._graph()[0]["nodes"]
        self.assertEqual(len(nodes[OUTBOUND]["children"]), 3)
        self.assertEqual(nodes[PLAN]["children"], [])  # 付款计划生成 shows a section none of the points is in
        # a section node without points of its own: the note's header status
        self.assertEqual((nodes[PLAN]["status"], nodes[PLAN]["units"], nodes[PLAN]["doc_status"]), ("已掌握", 1, "学习中"))

    def test_mastery_rollup_and_shapes(self):
        nodes = self._graph()[0]["nodes"]
        shapes = [(nodes[f"{OUTBOUND}/{n}"]["status"], nodes[f"{OUTBOUND}/{n}"]["shape"]) for n in ("出库四幕", "出库幂等", "回调重试")]
        self.assertEqual(shapes, [("已掌握", "full"), ("学习中", "half"), ("没碰", "empty")])
        note = nodes[OUTBOUND]
        self.assertEqual((note["status"], note["shape"], note["mastered"], note["units"], note["started"]),
                         ("学习中", "half", 1, 3, 2))
        blank = nodes["示例项目/业务/交易/出库/支付路由与通道"]
        self.assertEqual((blank["kind"], blank["status"], blank["shape"], blank["units"]), ("blank", "空白", "dashed", 0))
        unmarked = nodes["示例项目/发货/分拣/分拣流程"]
        self.assertEqual((unmarked["status"], unmarked["shape"], unmarked["units"], unmarked["started"]),
                         ("未标", "empty", 1, 0))
        other_blank = nodes["示例项目/业务/交易/订单与优惠/运费与包装费"]
        self.assertEqual(other_blank["shape"], "dashed")

    def test_rollup_all_mastered_and_untouched(self):
        for point in self._outbound_note().points:
            point.status = "已掌握"
        nodes = self._graph()[0]["nodes"]
        self.assertEqual((nodes[OUTBOUND]["status"], nodes[OUTBOUND]["shape"]), ("已掌握", "full"))
        self.assertEqual(nodes["示例项目/业务/交易"]["status"], "已掌握")
        for point in self._outbound_note().points:
            point.status = "没碰"
        nodes = self._graph()[0]["nodes"]
        self.assertEqual((nodes[OUTBOUND]["status"], nodes[OUTBOUND]["started"]), ("没碰", 0))
        self.assertEqual(nodes["示例项目/业务/交易"]["status"], "没碰")

    def test_prereq_resolves_to_point_and_concept(self):
        graph, errors = self._graph()
        self.assertEqual(errors, [])
        nodes = graph["nodes"]
        self.assertEqual(nodes[f"{OUTBOUND}/出库幂等"]["prereqs"], [f"{OUTBOUND}/出库四幕", "概念/幂等"])
        self.assertEqual(nodes[f"{OUTBOUND}/出库四幕"]["next"], [f"{OUTBOUND}/出库幂等"])
        self.assertEqual(nodes[f"{OUTBOUND}/回调重试"]["confusions"], [f"{OUTBOUND}/出库幂等"])
        # no '> 要先懂:' on the note: its prereqs are its points' prereqs minus its own points
        self.assertEqual(nodes[OUTBOUND]["prereqs"], ["概念/幂等"])

    def test_note_header_prereqs_resolve_to_titles_and_skeleton_names(self):
        note = self._outbound_note()
        note.prereqs, note.prereqs_line = ["系统全景", "分拣流程", "IDEMPOTENT"], 4
        graph, errors = self._graph()
        self.assertEqual(errors, [])
        nodes = graph["nodes"]
        self.assertEqual(nodes[OUTBOUND]["prereqs"], ["示例项目/业务", "示例项目/发货/分拣/分拣流程", "概念/幂等"])
        self.assertEqual(nodes["示例项目/业务"]["next"], [OUTBOUND, PLAN])

    def test_unknown_prereq_reported(self):
        self._outbound_note().points[1].prereqs = ["不存在"]
        _, errors = self._graph()
        line = self._outbound_note().points[1].line
        self.assertEqual(errors, [FormatError("出库数据流.md", line, "要先懂找不到：不存在")])

    def test_unknown_header_prereq_and_confusion_reported(self):
        note = self._outbound_note()
        note.prereqs, note.prereqs_line = ["没有这篇"], 4
        note.points[2].confusions = ["没有这个"]
        _, errors = self._graph()
        self.assertEqual(errors, [FormatError("出库数据流.md", 4, "要先懂找不到：没有这篇"),
                                  FormatError("出库数据流.md", note.points[2].line, "容易混淆找不到：没有这个")])

    def test_point_name_clashing_with_concept_reported(self):
        note = self._outbound_note()
        note.points[2].name = "幂等性"
        _, errors = self._graph()
        self.assertEqual(errors, [FormatError("出库数据流.md", note.points[2].line, "知识点重名：幂等性")])

    def test_point_name_clashing_across_notes_reported(self):
        other = next(n for n, _ in self.notes.values() if n.title == "分拣流程概览")
        clone = self._outbound_note().points[0]
        other.points = [type(clone)(name="出库四幕", line=7, raw="- 出库四幕")]
        _, errors = self._graph()
        self.assertEqual(errors, [FormatError("发货.md", 7, "知识点重名：出库四幕")])

    def _overview_note(self):
        return self.notes[self.book.register_doc(DEMO / "系统全景.md")][0]

    def test_points_of_note_on_block(self):
        self._overview_note().points = [
            Point("全景三层", 7, "- 全景三层 | 状态: 已掌握 | 要先懂: 不存在的名字", status="已掌握", prereqs=["不存在的名字"]),
            Point("全景四幕", 8, "- 全景四幕 | 要先懂: 出库四幕", prereqs=["出库四幕"]),
            Point("幂等", 9, "- 幂等"),
        ]
        graph, errors = self._graph()
        nodes = graph["nodes"]
        self.assertEqual(nodes["示例项目/业务"]["children"],
                         ["示例项目/业务/交易", "示例项目/业务/全景三层", "示例项目/业务/全景四幕", "示例项目/业务/幂等"])
        self.assertEqual(nodes["示例项目/业务/全景四幕"]["prereqs"], [f"{OUTBOUND}/出库四幕"])
        self.assertEqual(errors, [FormatError("系统全景.md", 9, "知识点重名：幂等"),
                                  FormatError("系统全景.md", 7, "要先懂找不到：不存在的名字")])
        block = nodes["示例项目/业务"]
        self.assertEqual((block["units"], block["mastered"]), (6, 2))  # 3 overview points once + 3 outbound points
        self.assertEqual((block["doc_status"], block["edit"]), ("学习中", None))
        self.assertEqual(nodes["示例项目"]["units"], 7)

    def test_doc_status_is_the_notes_own_status(self):
        self._overview_note().status = "已掌握"
        nodes = self._graph()[0]["nodes"]
        block = nodes["示例项目/业务"]
        self.assertEqual((block["status"], block["doc_status"]), ("学习中", "已掌握"))
        self.assertEqual(block["edit"]["kind"], "header")
        self.assertEqual((nodes[OUTBOUND]["doc_status"], nodes[f"{OUTBOUND}/出库四幕"]["doc_status"]), ("学习中", "学习中"))
        self.assertEqual(nodes["示例项目/发货/分拣/分拣流程"]["doc_status"], "未标")
        self.assertIsNone(nodes["示例项目/业务/交易"]["doc_status"])

    def test_sibling_short_name_clash_keeps_first(self):
        group = self.project.skeleton[0].children[0]
        group.children.append(Node(name="出库（旧）", line=99))
        graph, errors = self._graph()
        nodes = graph["nodes"]
        self.assertEqual(errors, [FormatError("示例项目/骨架.md", 99, "骨架同级重名：出库（旧）")])
        self.assertEqual(nodes["示例项目/业务/交易/出库"]["name"], "出库")
        self.assertEqual(nodes["示例项目/业务/交易"]["children"], ["示例项目/业务/交易/出库", "示例项目/业务/交易/订单与优惠"])

    def test_point_name_with_slash_skipped(self):
        self._outbound_note().points[2].name = "回调/重试"
        graph, errors = self._graph()
        self.assertEqual(errors, [FormatError("出库数据流.md", 15, "知识点名不能含 /：回调/重试")])
        node = graph["nodes"][OUTBOUND]
        self.assertEqual((len(node["children"]), node["units"]), (2, 2))

    def test_edit_locator(self):
        nodes = self._graph()[0]["nodes"]
        lines = read_text(OUTBOUND_FILE).split("\n")
        point = self._outbound_note().points[0]
        self.assertEqual(nodes[f"{OUTBOUND}/出库四幕"]["edit"],
                         {"file": "项目/示例项目/业务/出库数据流.md", "line": point.line, "raw": lines[point.line - 1],
                          "kind": "point"})
        self.assertTrue(lines[point.line - 1].startswith("- 出库四幕"))
        self.assertEqual(nodes["示例项目/业务"]["edit"],
                         {"file": "项目/示例项目/系统全景.md", "line": 3, "raw": "> 状态: 学习中", "kind": "header"})
        self.assertIsNone(nodes[OUTBOUND]["edit"])  # status comes from its points
        self.assertIsNone(nodes["示例项目/发货/分拣/分拣流程"]["edit"])  # no '> 状态:' line
        self.assertIsNone(nodes["示例项目/业务/交易"]["edit"])

    def test_notes_outside_the_kb_root_get_no_edit(self):
        graph, _ = build_graph(self.project, self.notes, self.concepts, self.concept_doc_ids, SAMPLE / "概念")
        nodes = graph["nodes"]
        self.assertIsNone(nodes["示例项目/业务"]["edit"])
        self.assertIsNone(nodes[f"{OUTBOUND}/出库四幕"]["edit"])
        self.assertEqual(nodes[f"{OUTBOUND}/出库四幕"]["status"], "已掌握")

    def test_measures_from_skeleton(self):
        nodes = self._graph()[0]["nodes"]
        self.assertEqual(nodes["示例项目/业务/交易/出库"]["measures"], ["出库"])
        self.assertEqual(nodes[OUTBOUND]["measures"], [])
        self.assertEqual(nodes[f"{OUTBOUND}/出库四幕"]["measures"], [])
        self.assertEqual(nodes["示例项目"]["measures"], [])
        concept_nodes = build_concept_graph(self.concepts, self.concept_doc_ids, SAMPLE)["nodes"]
        self.assertTrue(all(node["measures"] == [] for node in concept_nodes.values()))

    def test_reference_roots_excluded(self):
        nodes = self._graph()[0]["nodes"]
        self.assertFalse(any("术语表" in node_id for node_id in nodes))

    def test_concept_graph_groups(self):
        graph = build_concept_graph(self.concepts, self.concept_doc_ids, SAMPLE)
        self.assertEqual((graph["name"], graph["root"]), ("概念", "概念"))
        nodes = graph["nodes"]
        self.assertEqual(nodes["概念"]["children"], ["概念/概念", "概念/方法"])
        self.assertEqual(nodes["概念/概念"]["children"], ["概念/Kafka offset", "概念/幂等"])
        self.assertEqual(nodes["概念/方法"]["children"], [])
        card = nodes["概念/幂等"]
        self.assertEqual((card["kind"], card["parent"], card["block"]), ("concept", "概念/概念", -1))
        self.assertEqual((card["status"], card["shape"], card["units"], card["mastered"]), ("已掌握", "full", 1, 1))
        self.assertEqual((card["doc"], card["doc_status"]), (self.concept_doc_ids["幂等"], "已掌握"))
        self.assertEqual(card["summary"], "同一操作做多次和做一次结果一样。")
        self.assertEqual(card["edit"], {"file": "概念/幂等.md", "line": 4, "raw": "> 状态: 已掌握", "kind": "header"})
        group = nodes["概念/概念"]
        self.assertEqual((group["units"], group["mastered"], group["started"], group["status"]), (2, 1, 2, "学习中"))

    def test_concept_without_kind_goes_to_concept_group(self):
        self.concepts[0].kind = None
        self.concepts[1].kind = "方法"
        nodes = build_concept_graph(self.concepts, self.concept_doc_ids, SAMPLE)["nodes"]
        self.assertEqual(nodes["概念/概念"]["children"], ["概念/Kafka offset"])
        self.assertEqual(nodes["概念/方法"]["children"], ["概念/幂等"])

    def test_concept_next_links_back_to_project_points(self):
        concept_graph = build_concept_graph(self.concepts, self.concept_doc_ids, SAMPLE)
        graph, _ = self._graph()
        link_concept_next(concept_graph, [graph])
        self.assertEqual(concept_graph["nodes"]["概念/幂等"]["next"],
                         [OUTBOUND, f"{OUTBOUND}/出库幂等", PLAN])


class SectionNodeTest(unittest.TestCase):
    """Skeleton nodes that show one section of a note ('-> 笔记.md#小标题')."""

    def setUp(self):
        self.project, self.notes, self.concepts, self.concept_doc_ids, self.book = load_sample()
        self.outbound = self.book.register_doc(OUTBOUND_FILE)
        self.plan = self.project.skeleton[0].children[0].children[1].children[0]  # 付款计划生成

    def _graph(self, body: str | None = None):
        if body is not None:
            self.notes[self.outbound] = (self.notes[self.outbound][0], body)
        return build_graph(self.project, self.notes, self.concepts, self.concept_doc_ids, SAMPLE)

    def _note(self):
        return self.notes[self.outbound][0]

    def test_section_node_gets_heading_id(self):
        graph, errors = self._graph()
        self.assertEqual(errors, [])
        self.assertEqual(graph["nodes"][PLAN]["anchor"], f"{self.outbound}-h2")
        self.assertEqual(graph["nodes"][OUTBOUND]["anchor"], "")

    def test_point_in_section_hangs_under_section_node(self):
        self._note().points[1].anchor = "付款计划生成"
        nodes = self._graph()[0]["nodes"]
        self.assertEqual(nodes[PLAN]["children"], [f"{PLAN}/出库幂等"])
        self.assertEqual(nodes[OUTBOUND]["children"], [f"{OUTBOUND}/出库四幕", f"{OUTBOUND}/回调重试"])
        self.assertEqual(nodes[f"{PLAN}/出库幂等"]["prereqs"], [f"{OUTBOUND}/出库四幕", "概念/幂等"])
        plan = nodes[PLAN]  # counts only its own point; the whole-note node still counts the whole note
        self.assertEqual((plan["status"], plan["units"], plan["mastered"]), ("学习中", 1, 0))
        self.assertEqual((nodes[OUTBOUND]["units"], nodes[OUTBOUND]["mastered"]), (3, 1))
        self.assertEqual(nodes["示例项目/业务/交易"]["units"], 3)  # upstream: the note counts once

    def test_narrowest_section_wins(self):
        body = '<h2>一句话</h2><p>x</p><h2>付款计划生成</h2><h3>计划细节</h3><p>y</p><h2>其他</h2>'
        self._note().points[0].anchor = "计划细节"
        outbound_node = self.project.skeleton[0].children[0].children[0].children[0]
        outbound_node.anchor = "付款计划生成"  # the wider section, holding 计划细节
        self.plan.anchor = "计划细节"
        nodes = self._graph(body)[0]["nodes"]
        self.assertEqual([nodes[i]["name"] for i in nodes[PLAN]["children"]], ["出库四幕"])
        self.assertEqual([nodes[i]["name"] for i in nodes[OUTBOUND]["children"]], ["出库幂等", "回调重试"])

    def test_no_whole_note_node_falls_back_to_first(self):
        outbound_node = self.project.skeleton[0].children[0].children[0].children[0]
        outbound_node.anchor = "一句话"
        outbound_node.name = "一句话"
        graph, errors = self._graph()
        nodes = graph["nodes"]
        outbound_id = "示例项目/业务/交易/出库/一句话"
        self.assertEqual(errors, [])
        # 出库四幕 is in 一句话; the other two have no section and no node shows the whole note
        self.assertEqual(len(nodes[outbound_id]["children"]), 3)
        self.assertEqual(nodes[PLAN]["children"], [])

    def test_unknown_section_reported_and_whole_note_shown(self):
        self.plan.anchor = "没有这节"
        graph, errors = self._graph()
        self.assertEqual(errors, [FormatError("示例项目/骨架.md", 7, "骨架小节找不到：没有这节"),
                                  FormatError("示例项目/骨架.md", 7, "节点名和落点对不上：付款计划生成 / 出库流程与数据流")])
        self.assertEqual(graph["nodes"][PLAN]["anchor"], "")

    def test_section_with_repeated_heading_reported(self):
        body = "<h2>付款计划生成</h2><p>a</p><h2>付款计划生成</h2>"
        _, errors = self._graph(body)
        self.assertIn(FormatError("示例项目/骨架.md", 7, "骨架指向重名小标题：付款计划生成"), errors)

    def test_node_name_must_match_where_it_lands(self):
        self.plan.name = "计划表"
        _, errors = self._graph()
        self.assertEqual(errors, [FormatError("示例项目/骨架.md", 7, "节点名和落点对不上：计划表 / 付款计划生成")])

    def test_name_check_skips_blocks(self):
        self.project.skeleton[0].name = "业务 · 另一个名字"  # a block showing 系统全景
        _, errors = self._graph()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
