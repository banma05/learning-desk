import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from build import build
from hub.glossary import Term
from hub.terms import mark_terms, number_headings, term_table

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"
NOW = datetime(2025, 11, 3, 9, 0)


def span(term_id: str, text: str) -> str:
    return f'<span class="term" data-term="{term_id}">{text}</span>'


class NumberHeadingsTest(unittest.TestCase):
    def test_headings_numbered(self):
        html, headings = number_headings("<h2>一</h2><p>x</p><h3>甲</h3>", "d1")
        self.assertEqual(html, '<h2 id="d1-h1">一</h2><p>x</p><h3 id="d1-h2">甲</h3>')
        self.assertEqual(headings, [(2, "一", "d1-h1"), (3, "甲", "d1-h2")])

    def test_text_is_plain_and_other_levels_untouched(self):
        html, headings = number_headings("<h1>题</h1><h2>A &amp; <code>b</code></h2>", "d2")
        self.assertIn("<h1>题</h1>", html)
        self.assertEqual(headings, [(2, "A & b", "d2-h1")])


class MarkTermsTest(unittest.TestCase):
    def test_first_occurrence_per_section(self):
        html = "<h2>甲</h2><p>运费和运费</p><h2>乙</h2><p>运费，运费</p>"
        out = mark_terms(html, {"运费": "t1"})
        self.assertEqual(out.count("<span"), 2)
        self.assertIn("<p>" + span("t1", "运费") + "和运费</p>", out)

    def test_text_before_first_h2_is_one_section(self):
        out = mark_terms("<p>运费 运费</p>", {"运费": "t1"})
        self.assertEqual(out.count("<span"), 1)

    def test_longest_label_wins_and_no_nesting(self):
        out = mark_terms("<p>超时仓储费和仓储费</p>", {"仓储费": "t1", "超时仓储费": "t2"})
        self.assertEqual(out, "<p>" + span("t2", "超时仓储费") + "和" + span("t1", "仓储费") + "</p>")

    def test_shorter_label_inside_seen_longer_one_is_not_marked(self):
        out = mark_terms("<p>超时仓储费，超时仓储费，仓储费</p>", {"仓储费": "t1", "超时仓储费": "t2"})
        self.assertEqual(out.count("<span"), 2)
        self.assertEqual(out.count(span("t1", "仓储费")), 1)

    def test_skips_links_headings_and_pre(self):
        html = ('<h2>运费</h2><p><a href="#x">运费</a></p><h3>运费</h3>'
                '<pre><code>运费</code></pre><p>x运费</p>')
        out = mark_terms(html, {"运费": "t1"})
        self.assertEqual(out.count("<span"), 1)
        self.assertTrue(out.endswith("<p>x" + span("t1", "运费") + "</p>"))

    def test_text_after_skipped_element_is_marked_again(self):
        out = mark_terms('<p><a href="#x">甲</a>运费</p>', {"运费": "t1"})
        self.assertIn(span("t1", "运费"), out)

    def test_inline_code_only_whole_match(self):
        labels = {"shipping_plan": "t1"}
        self.assertEqual(mark_terms("<p><code>shipping_plan</code></p>", labels),
                         "<p>" + span("t1", "<code>shipping_plan</code>") + "</p>")
        self.assertNotIn("<span", mark_terms("<p><code>shipping_plan.id</code></p>", labels))

    def test_inline_code_counts_as_first_mention(self):
        out = mark_terms("<p><code>运费</code>和运费</p>", {"运费": "t1"})
        self.assertEqual(out.count("<span"), 1)

    def test_ascii_label_word_boundary(self):
        out = mark_terms("<p>GMVX, xGMV, GMV_1, GMV</p>", {"GMV": "t1"})
        self.assertEqual(out, "<p>GMVX, xGMV, GMV_1, " + span("t1", "GMV") + "</p>")

    def test_ascii_label_does_not_match_inside_entity(self):
        self.assertNotIn("<span", mark_terms("<p>a &amp; b</p>", {"amp": "t1"}))

    def test_no_labels_leaves_html_alone(self):
        self.assertEqual(mark_terms("<p>x</p>", {}), "<p>x</p>")

    def test_term_id_is_escaped(self):
        out = mark_terms("<p>运费</p>", {"运费": 'g:a"b'})
        self.assertIn('data-term="g:a&quot;b"', out)


def point(node_id, name, aliases=(), summary="一句话"):
    return {"id": node_id, "name": name, "kind": "point", "summary": summary, "aliases": list(aliases)}


def concept(name, aliases=(), summary="说明"):
    return {"id": f"概念/{name}", "name": name, "kind": "concept", "summary": summary, "aliases": list(aliases)}


class TermTableTest(unittest.TestCase):
    def _table(self, points=(), concepts=(), glossary=None):
        graph = {"nodes": {p["id"]: p for p in points}}
        concept_graph = {"nodes": {c["id"]: c for c in concepts}}
        return term_table([graph], concept_graph, glossary or {})

    def test_ids_entries_and_aliases(self):
        glossary = {"示例项目": [Term("运费", ["shippingFeeAmount"], "按天**计**的仓储费", "`A.java:1`")]}
        terms, labels = self._table([point("A/出库", "出库", ["Outbound"])], [concept("幂等", ["idempotent"])], glossary)
        self.assertEqual(labels, {"出库": "p:A/出库", "Outbound": "p:A/出库", "幂等": "c:幂等", "idempotent": "c:幂等",
                                  "运费": "g:示例项目/运费", "shippingFeeAmount": "g:示例项目/运费"})
        self.assertEqual(terms["p:A/出库"], {"name": "出库", "kind": "point", "summary": "一句话", "source": "",
                                            "node": "A/出库"})
        self.assertEqual(terms["c:幂等"]["node"], "概念/幂等")
        self.assertEqual(terms["g:示例项目/运费"]["summary"], "按天<strong>计</strong>的仓储费")
        self.assertEqual(terms["g:示例项目/运费"]["source"], "<code>A.java:1</code>")
        self.assertIsNone(terms["g:示例项目/运费"]["node"])

    def test_term_priority_point_over_concept_over_glossary(self):
        glossary = {"示例项目": [Term("仓储费", [], "g", ""), Term("幂等", [], "g", ""), Term("出库", [], "g", "")]}
        _, labels = self._table([point("A/仓储费", "仓储费")], [concept("仓储费"), concept("幂等")], glossary)
        self.assertEqual((labels["仓储费"], labels["幂等"], labels["出库"]), ("p:A/仓储费", "c:幂等", "g:示例项目/出库"))

    def test_same_kind_first_seen_wins(self):
        _, labels = self._table([point("A/甲", "仓储费"), point("A/乙", "仓储费")])
        self.assertEqual(labels["仓储费"], "p:A/甲")

    def test_short_labels_skipped(self):
        _, labels = self._table([point("A/甲", "甲", ["乙", "丙丙"])])
        self.assertEqual(labels, {"丙丙": "p:A/甲"})


class BuildTermsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "学习台.html"

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_builds_without_errors_and_output_has_ids(self):
        errors = build(SAMPLE, FIXTURES, self.out, NOW)
        html = self.out.read_text(encoding="utf-8")
        self.assertEqual(errors, [])
        self.assertRegex(html, r'<h2 id="[^"]+-h1">一句话</h2>')

    def test_site_gets_headings_terms_and_point_anchor_ids(self):
        import build as build_module
        captured = {}
        original = build_module.render_page
        build_module.render_page = lambda site: captured.setdefault("site", site) and original(site)
        try:
            build(SAMPLE, FIXTURES, self.out, NOW)
        finally:
            build_module.render_page = original
        site = captured["site"]
        graph = next(p for p in site.projects if p.name == "示例项目").graph
        point_node = graph["nodes"]["示例项目/业务/交易/出库/出库流程/出库四幕"]
        doc = point_node["doc"]
        self.assertIn((2, "一句话", point_node["anchor"]), site.headings[doc])
        self.assertIn("g:示例项目/运费", site.terms)
        self.assertIn("c:幂等", site.terms)
        self.assertEqual(site.concept_graph["nodes"]["概念/幂等"]["aliases"], ["idempotent", "幂等性"])
        self.assertIn("p:示例项目/业务/交易/出库/出库流程/出库四幕", site.terms)
        self.assertTrue(all(doc_id in site.headings for doc_id in
                            [*site.notes, *site.attachments, *[c[1] for c in site.concepts]]))

    def test_body_text_gets_term_spans(self):
        build(SAMPLE, FIXTURES, self.out, NOW)
        html = self.out.read_text(encoding="utf-8")
        self.assertIn('<span class="term" data-term="p:示例项目/业务/交易/出库/出库流程/出库四幕">出库四幕</span>', html)

    def test_missing_anchor_heading_is_reported_and_cleared(self):
        code_root = Path(self.tmp.name) / "代码"
        shutil.copytree(FIXTURES, code_root)
        root = code_root / "样例记录"
        note = root / "项目/示例项目/业务/出库数据流.md"
        note.write_text(note.read_text(encoding="utf-8").replace("-> #一句话", "-> #不存在的小节"),
                        encoding="utf-8", newline="\n")
        errors = build(root, code_root, self.out, NOW)
        self.assertEqual([(e.file, e.message) for e in errors], [("出库数据流.md", "知识点小节找不到：不存在的小节")])
        self.assertEqual(errors[0].line, 13)  # the 出库四幕 line

    def _build_with(self, *replacements: tuple[str, str]) -> list:
        code_root = Path(self.tmp.name) / "代码"
        shutil.copytree(FIXTURES, code_root)
        root = code_root / "样例记录"
        note = root / "项目/示例项目/业务/出库数据流.md"
        text = note.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        note.write_text(text, encoding="utf-8", newline="\n")
        return [(e.file, e.line, e.message) for e in build(root, code_root, self.out, NOW)]

    def test_point_anchor_on_repeated_heading_is_reported(self):
        errors = self._build_with(("## 付款计划生成", "## 一句话\n\n出库四幕又一次。\n\n## 付款计划生成"))
        self.assertEqual(errors, [("出库数据流.md", 13, "知识点指向重名小标题：一句话")])

    def test_point_section_must_mention_the_point(self):
        errors = self._build_with(("-> #一句话", "-> #付款计划生成"))
        self.assertEqual(errors, [("出库数据流.md", 13, "知识点小节里没提到它：出库四幕")])

    def test_point_section_may_mention_an_alias(self):
        alias = self._build_with(("-> #一句话", "| 别名: 付款计划 -> #付款计划生成"))
        self.assertEqual(alias, [])

    def test_point_section_stops_at_the_next_heading_of_its_level(self):
        # the h3 一句话 ends at the next h3, so the text naming 出库四幕 (now under 下一节) is not in it;
        # line 20: six lines were inserted above the point
        errors = self._build_with(("## 一句话\n", "## 前言\n\n### 一句话\n\n空\n\n### 下一节\n\n"))
        self.assertEqual(errors, [("出库数据流.md", 20, "知识点小节里没提到它：出库四幕")])


if __name__ == "__main__":
    unittest.main()
