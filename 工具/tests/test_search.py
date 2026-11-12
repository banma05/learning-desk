import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path
import tempfile

from build import build
from hub.assets import AssetBook
from hub.page import render_page
from hub.search import search_entries

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"
NOW = datetime(2025, 11, 3, 9, 0)


def node(node_id: str, name: str, kind: str, doc: str | None = None, **extra) -> dict:
    return {"id": node_id, "name": name, "kind": kind, "doc": doc, "anchor": "", "summary": "",
            "aliases": [], **extra}


PROJECT = {"name": "P", "root": "P", "nodes": {
    "P": node("P", "P", "project"),
    "P/块": node("P/块", "块", "block", "d0"),
    "P/块/笔记甲": node("P/块/笔记甲", "笔记甲", "note", "d1"),
    "P/块/笔记甲/幂等点": node("P/块/笔记甲/幂等点", "幂等点", "point", "d1", anchor="d1-h2",
                         summary="重复请求只生效一次", aliases=["幂等性", "幂等点"]),
    "P/块/笔记乙": node("P/块/笔记乙", "挂在另一处的甲", "note", "d1"),
    "P/块/空": node("P/块/空", "空", "blank"),
}}
CONCEPTS = {"name": "概念", "root": "概念", "nodes": {
    "概念": node("概念", "概念", "project"),
    "概念/概念": node("概念/概念", "概念", "group"),
    "概念/幂等": node("概念/幂等", "幂等", "concept", "dc", summary="做一次和做很多次结果一样", aliases=["idempotent"]),
}}
HEADINGS = {"d1": [(1, "题", "d1-h0"), (2, "第一节", "d1-h1"), (3, "第二节", "d1-h2"), (4, "细", "d1-h3")],
            "da": [(2, "附件节", "da-h1")]}
TITLES = {"d0": "概览", "d1": "出库笔记", "dc": "幂等", "da": "附件"}


class SearchEntriesTest(unittest.TestCase):
    def setUp(self):
        self.entries = search_entries([PROJECT], CONCEPTS, HEADINGS, TITLES)

    def of_kind(self, kind: str) -> list[dict]:
        return [e for e in self.entries if e["k"] == kind]

    def test_entries_for_points_notes_concepts_headings(self):
        self.assertEqual(self.of_kind("point"), [
            {"k": "point", "t": "幂等点", "s": "重复请求只生效一次", "w": ["幂等点", "幂等性"],
             "href": "#doc-d1", "a": "d1-h2", "node": "P/块/笔记甲/幂等点"}])
        self.assertEqual(self.of_kind("concept"), [
            {"k": "concept", "t": "幂等", "s": "做一次和做很多次结果一样", "w": ["幂等", "idempotent"],
             "href": "#doc-dc", "a": "", "node": "概念/幂等"}])
        self.assertEqual(self.of_kind("heading"), [
            {"k": "heading", "t": "第一节", "s": "出库笔记", "w": ["第一节"], "href": "#doc-d1", "a": "d1-h1", "node": ""},
            {"k": "heading", "t": "第二节", "s": "出库笔记", "w": ["第二节"], "href": "#doc-d1", "a": "d1-h2", "node": ""},
            {"k": "heading", "t": "附件节", "s": "附件", "w": ["附件节"], "href": "#doc-da", "a": "da-h1", "node": ""}])

    def test_one_note_entry_per_doc_named_by_title(self):
        notes = self.of_kind("note")
        self.assertEqual([(e["t"], e["node"]) for e in notes], [("概览", "P/块"), ("出库笔记", "P/块/笔记甲")])
        self.assertEqual(notes[1], {"k": "note", "t": "出库笔记", "s": "", "w": ["出库笔记"], "href": "#doc-d1",
                                    "a": "", "node": "P/块/笔记甲"})

    def test_note_entry_opens_from_a_node_showing_the_whole_note(self):
        nodes = {key: dict(value) for key, value in PROJECT["nodes"].items()}
        nodes["P/块/笔记甲"]["anchor"] = "d1-h1"  # shows only one section
        notes = [e for e in search_entries([{**PROJECT, "nodes": nodes}], CONCEPTS, HEADINGS, TITLES) if e["k"] == "note"]
        self.assertEqual([(e["t"], e["node"], e["a"]) for e in notes], [("概览", "P/块", ""), ("出库笔记", "P/块/笔记乙", "")])

    def test_nodes_without_doc_and_project_root_have_no_entry(self):
        self.assertEqual(len(self.entries), 1 + 2 + 1 + 3)  # point, notes, concept, headings


class SearchWiringTest(unittest.TestCase):
    def test_build_fills_site_search(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("build.render_page", wraps=render_page) as render:
            build(SAMPLE, FIXTURES, Path(tmp) / "学习台.html", NOW)
        search = render.call_args.args[0].search
        outbound = AssetBook(FIXTURES).register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        kinds = {e["k"] for e in search}
        self.assertEqual(kinds, {"point", "note", "concept", "heading"})
        self.assertEqual(len([e for e in search if e["k"] == "note" and e["href"] == f"#doc-{outbound}"]), 1)
        heading = next(e for e in search if e["k"] == "heading" and e["href"] == f"#doc-{outbound}")
        self.assertTrue(heading["a"].startswith(f"{outbound}-h"))
        self.assertTrue(heading["s"])


if __name__ == "__main__":
    unittest.main()
