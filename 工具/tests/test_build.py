import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from datetime import datetime
from pathlib import Path

from build import build
from hub.assets import AssetBook
from hub.page import render_page

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "样例记录"
BROKEN_SAMPLE = FIXTURES / "样例记录坏"
NOW = datetime(2025, 10, 24, 18, 0)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "学习台.html"

    def tearDown(self):
        self.tmp.cleanup()

    def _build(self) -> str:
        build(SAMPLE, FIXTURES, self.out, NOW)
        return self.out.read_text(encoding="utf-8")

    def test_build_writes_single_offline_file(self):
        errors = build(SAMPLE, FIXTURES, self.out, NOW)
        html = self.out.read_text(encoding="utf-8")
        self.assertNotRegex(html, r'(src|href)="https?://')
        self.assertIn("生成时间：2025-10-24 18:00", html)
        self.assertEqual(errors, [])

    def test_question_board_follows_config(self):
        self.assertIn("<h3>上级", self._build())

    def test_question_board_single_column_without_askers(self):
        kb = Path(self.tmp.name) / "kb"
        shutil.copytree(SAMPLE, kb)
        (kb / "学习台配置.json").unlink()
        build(kb, None, self.out, NOW)
        html = self.out.read_text(encoding="utf-8")
        self.assertIn("<h3>待解决", html)
        self.assertNotIn("<h3>同事", html)

    def _sample_copy(self) -> Path:
        kb = Path(self.tmp.name) / "kb"
        shutil.copytree(SAMPLE, kb)
        return kb

    def test_work_page_hidden_without_work_md(self):
        kb = self._sample_copy()
        (kb / "工作.md").unlink()
        errors = build(kb, None, self.out, NOW)
        self.assertNotIn('data-nav="工作"', self.out.read_text(encoding="utf-8"))
        self.assertEqual([e for e in errors if e.file == "工作.md"], [])

    def test_overview_shown_on_plan_page(self):
        kb = self._sample_copy()
        (kb / "计划" / "总计划.md").write_text("# 总计划\n\n目标甲\n", encoding="utf-8")
        build(kb, None, self.out, NOW)
        html = self.out.read_text(encoding="utf-8")
        self.assertIn('<div class="panel route overview"><h1', html)
        self.assertIn("目标甲", html.split('class="panel route overview"', 1)[-1].split("</div>", 1)[0])

    def test_main_accepts_root_argument(self):
        import contextlib
        import io
        import build as build_module
        kb = self._sample_copy()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_module.main([str(kb)]), 0)
        self.assertIn("已生成 学习台.html", out.getvalue())
        self.assertTrue((kb / "学习台.html").exists())

    def test_counts_in_nav(self):
        html = self._build()
        self.assertIn("2/5", html)
        self.assertIn("1/1", html)
        self.assertIn("2/3 完成", html)

    def test_shared_note_rendered_once(self):
        html = self._build()
        doc_id = AssetBook(FIXTURES).register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        self.assertEqual(html.count(f'id="doc-{doc_id}"'), 1)
        self.assertEqual(html.count(f'href="#doc-{doc_id}"'), 2)  # 问题「怎么查」 + 幂等「引用了我」

    def test_attachment_and_embedded_image(self):
        html = self._build()
        self.assertIn("附页标题", html)
        self.assertIn("data:image/png;base64,", html)

    def test_questions_board_and_outputs_link(self):
        html = self._build()
        self.assertIn("会卡住吗？", html)
        self.assertIn('href="file:///', html)

    def test_block_cards_point_at_graph_block_nodes(self):
        html = self._build()
        self.assertIn('data-block="示例项目/业务"', html)
        self.assertIn('data-block="示例项目/发货"', html)
        self.assertIn('data-block="Demo/入门"', html)
        self.assertNotIn('id="blk-', html)  # the server-side tree is gone

    def test_block_card_shows_mastery_line(self):
        html = self._build()
        business = html.split('data-block="示例项目/业务"', 1)[1].split("</a>", 1)[0]
        self.assertIn('<div class="stat-mastery">已掌握 1/4</div>', business)
        collection = html.split('data-block="示例项目/发货"', 1)[1].split("</a>", 1)[0]
        self.assertIn('<div class="stat-mastery">已掌握 0/1</div>', collection)

    def test_graph_json_embedded(self):
        html = self._build()
        data = kg_data(html)
        self.assertEqual(set(data), {"generatedAt", "graphs", "terms", "search", "docNodes"})
        self.assertEqual(data["generatedAt"], "2025-10-24 18:00")
        self.assertEqual(set(data["graphs"]), {"示例项目", "Demo", "概念"})
        self.assertEqual(data["graphs"]["概念"]["root"], "概念")
        self.assertIn("示例项目/业务/交易/出库/出库流程/出库幂等", data["graphs"]["示例项目"]["nodes"])
        outbound = AssetBook(FIXTURES).register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        self.assertEqual(data["docNodes"][outbound],
                         ["示例项目/业务/交易/出库/出库流程", "示例项目/业务/交易/订单与优惠/付款计划生成"])
        self.assertTrue(data["terms"] and data["search"])
        self.assertLess(html.index('id="kg-data"'), html.index("<script>"))

    def test_project_switch_has_concept_graph_pane(self):
        html = self._build()
        self.assertIn('<button class="proj-tab" data-project="概念">概念</button>', html)
        for name in ("示例项目", "Demo", "概念"):
            self.assertIn(f'<div class="kg" data-graph="{name}"><aside class="kg-tree"></aside><div class="kg-stage">'
                          '<div class="kg-bar"></div><svg class="kg-svg"></svg><div class="kg-card"></div></div></div>',
                          html)
        concept_pane = html.split('<div class="proj-pane" data-pane="概念">', 1)[1].split('<div class="kg"', 1)[0]
        self.assertEqual(concept_pane, "")  # no stat cards or reference row

    def test_search_box_and_peek_panel(self):
        html = self._build()
        nav = html.split("<nav>", 1)[1].split("</nav>", 1)[0]
        self.assertIn('<input id="search" type="search" placeholder="搜索知识点、笔记、表名…">'
                      '<div id="search-results"></div>', nav)
        self.assertLess(nav.index('id="search"'), nav.index('class="nav-links"'))
        self.assertIn('<aside id="peek" hidden></aside>', html)

    def test_static_files_inlined(self):
        html = self._build()
        static = Path(__file__).parent.parent / "hub" / "static"
        style = html.split("<style>", 1)[1].split("</style>", 1)[0]
        self.assertIn((static / "kg.css").read_text(encoding="utf-8"), style)
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        for name in ("graph.js", "reader.js", "search.js", "status.js"):
            self.assertIn((static / name).read_text(encoding="utf-8"), script)

    def test_show_leaves_scrolling_to_the_reader(self):
        script = self._build().split("<script>", 1)[1].split("</script>", 1)[0]
        show = script.split("function show(){", 1)[1].split("\n}", 1)[0]
        self.assertIn("if(typeof Reader!=='undefined')Reader.arrive();else window.scrollTo(0,0);", show)
        self.assertNotIn("<!--", script)
        self.assertNotIn("</script", script.lower())

    def test_doc_has_side_toc_and_nodes(self):
        html = self._build()
        book = AssetBook(FIXTURES)
        outbound = book.register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        article = html.split(f'<article class="doc" id="doc-{outbound}" '
                             'data-nodes="示例项目/业务/交易/出库/出库流程,示例项目/业务/交易/订单与优惠/付款计划生成">',
                             1)[1].split("</article>", 1)[0]
        self.assertTrue(article.startswith(
            '<div class="doc-top"><a class="back-graph" href="#项目">← 回到图谱</a>'
            '<nav class="crumb"></nav><span class="doc-status"></span></div><div class="crumb-also"></div>'
            '<div class="doc-grid"><div class="doc-body"><h1>出库流程与数据流</h1>'))
        side = article.split('<aside class="doc-side">', 1)[1]
        self.assertTrue(side.startswith('<div class="mini"></div><div class="side-points"></div><div class="side-toc">'))
        toc = side.split('<div class="side-toc">', 1)[1].split('<div class="side-refs">', 1)[0]
        self.assertIn(f'<a href="#{outbound}-h1" data-toc>一句话</a>', toc)
        refs = side.split('<div class="side-refs">', 1)[1]
        self.assertIn('<a href="#问题">问题</a>', refs)
        self.assertNotIn('class="back"', html)  # the old back links gave way to back-graph

    def test_attachment_and_unlinked_note_get_reading_shell(self):
        html = self._build()
        book = AssetBook(FIXTURES)
        attachment = book.register_doc(FIXTURES / "外部/附页.md")
        article = html.split(f'<article class="doc" id="doc-{attachment}" data-nodes="">', 1)[1].split("</article>")[0]
        self.assertIn('<a class="back-graph" href="#成果">← 返回成果</a>', article)  # opened from 成果
        self.assertNotIn("回到图谱", article)
        self.assertIn('<div class="side-refs"></div>', article)  # nothing links back: no list
        collection = book.register_doc(SAMPLE / "项目/示例项目/发货.md")
        article = html.split(f'id="doc-{collection}"', 1)[1].split("</article>")[0]
        self.assertIn('<div class="side-toc"></div>', article)  # no headings: no list

    def test_no_external_resources(self):
        html = self._build()
        self.assertNotRegex(html, r'''(src|href)=["']?https?://[^"'\s>]*\.(js|css)\b''')
        self.assertNotRegex(html, r"<script[^>]*\bsrc=")
        self.assertNotIn("<link", html)

    def test_reference_entries_listed_apart_from_blocks(self):
        html = self._build()
        refs = html.split('<div class="refs">', 1)[1].split("</div>", 1)[0]
        self.assertIn("术语表", refs)
        self.assertNotIn('<div class="stat-name">术语表</div>', html)

    def test_solved_questions_grouped_by_topic(self):
        html = self._build()
        self.assertIn('<details class="solved-group"><summary>学习方法（1）</summary>', html)

    def test_format_errors_shown_in_banner(self):
        errors = build(BROKEN_SAMPLE, FIXTURES, self.out, NOW)
        self.assertTrue(errors)
        self.assertIn("问谁不合法：导师", self.out.read_text(encoding="utf-8"))

    def test_note_without_status_not_shown_as_untouched(self):
        html = self._build()
        collection = AssetBook(FIXTURES).register_doc(SAMPLE / "项目/示例项目/发货.md")
        self.assertIn("📄 未标状态", html.split(f'id="doc-{collection}"', 1)[1].split("</article>")[0])
        node = kg_data(html)["graphs"]["示例项目"]["nodes"]["示例项目/发货/分拣/分拣流程"]
        self.assertEqual((node["kind"], node["doc_status"]), ("note", "未标"))  # a note, not a blank topic

    def test_meta_line_drops_header_status_once_note_has_points(self):
        html = self._build()
        book = AssetBook(FIXTURES)

        def meta(path: str) -> str:
            doc_id = book.register_doc(SAMPLE / path)
            body = html.split(f'id="doc-{doc_id}"', 1)[1].split('<div class="doc-body">', 1)[1]
            return body.split("</h1>", 1)[1].split("</p>", 1)[0]

        outbound = meta("项目/示例项目/业务/出库数据流.md")  # has points: status comes from them (top chip)
        self.assertEqual(outbound, '<p class="muted">更新 2025-10-23')
        self.assertEqual(meta("项目/示例项目/系统全景.md"), '<p class="muted">🔄 学习中')  # no points: header status

    def test_links_inside_table_cells_are_rewritten(self):
        html = self._build()
        self.assertNotIn('href="../图/仅png.png"', html)
        self.assertNotIn('href="项目/示例项目/业务/出库数据流.md"', html)
        self.assertIn('不需要，见 <a href="#成果">', html)

    def test_two_projects_rendered_with_switch(self):
        html = self._build()
        self.assertIn('data-project="示例项目"', html)
        self.assertIn('data-project="Demo"', html)
        self.assertIn("0/1", html)

    def test_concept_page_and_backlink(self):
        html = self._build()
        self.assertIn('href="#概念"', html)
        self.assertIn("引用了我", html)
        self.assertIn("出库流程与数据流", html.split("<h1>幂等</h1>")[1].split("引用了我")[1][:500])

    def test_work_page_sorted_desc_with_filters(self):
        html = self._build()
        work = html.split('id="work"')[1].split("</table>")[0]
        self.assertLess(work.index("2025-10-24"), work.index("2025-10-22"))
        self.assertIn('href="#doc-', work)
        self.assertIn('data-filter="project"', html)
        self.assertIn('href="#工作"', html)

    def test_bad_owner_and_unknown_project_reported(self):
        errors = build(BROKEN_SAMPLE, FIXTURES, self.out, NOW)
        text = " ".join(str(e) for e in errors)
        self.assertIn("所属不存在：业务/交易/出库", text)

    def _leftover_temps(self) -> list[str]:
        return [p.name for p in self.out.parent.iterdir() if p.name.endswith(".tmp")]

    def test_page_written_via_unique_temp_and_replace(self):
        with mock.patch("build.os.replace", wraps=os.replace) as replace:
            build(SAMPLE, FIXTURES, self.out, NOW)
        tmp, target = replace.call_args.args
        replace.assert_called_once()
        self.assertEqual(target, self.out)
        self.assertTrue(tmp.name.startswith("学习台.html.") and tmp.name.endswith(".tmp"))
        self.assertEqual(self._leftover_temps(), [])
        self.assertTrue(self.out.read_text(encoding="utf-8").rstrip().endswith("</html>"))

    def test_concurrent_builds_use_distinct_temps(self):
        with mock.patch("build.os.replace", wraps=os.replace) as replace:
            build(SAMPLE, FIXTURES, self.out, NOW)
            build(SAMPLE, FIXTURES, self.out, NOW)
        first, second = (c.args[0] for c in replace.call_args_list)
        self.assertNotEqual(first, second)

    def test_replace_retried_while_page_is_locked(self):
        busy = PermissionError(13, "另一个程序正在使用此文件，进程无法访问。")
        real_replace, calls = os.replace, []

        def flaky_replace(src, dst):
            calls.append(src)
            if len(calls) <= 2:
                raise busy
            real_replace(src, dst)

        with mock.patch("build.os.replace", side_effect=flaky_replace), \
                mock.patch("build.time.sleep") as sleep:
            build(SAMPLE, FIXTURES, self.out, NOW)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(self.out.read_text(encoding="utf-8").rstrip().endswith("</html>"))
        self.assertEqual(self._leftover_temps(), [])

    def test_gives_up_after_retries_and_removes_temp(self):
        busy = PermissionError(13, "拒绝访问。")
        with mock.patch("build.os.replace", side_effect=busy), mock.patch("build.time.sleep"):
            with self.assertRaises(PermissionError):
                build(SAMPLE, FIXTURES, self.out, NOW)
        self.assertEqual(self._leftover_temps(), [])


class EditedSampleTest(unittest.TestCase):
    """Builds a copy of the fixtures with one note changed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixtures = Path(self.tmp.name) / "fixtures"
        shutil.copytree(FIXTURES, self.fixtures)
        self.note = self.fixtures / "样例记录/项目/示例项目/业务/出库数据流.md"

    def tearDown(self):
        self.tmp.cleanup()

    def _build_with(self, old: str, new: str) -> str:
        text = self.note.read_text(encoding="utf-8")
        self.assertIn(old, text)
        self.note.write_text(text.replace(old, new), encoding="utf-8")
        out = Path(self.tmp.name) / "学习台.html"
        build(self.fixtures / "样例记录", self.fixtures, out, NOW)
        return out.read_text(encoding="utf-8")

    def test_json_script_cannot_break_out(self):
        summary = "先 </script><script>alert(1)</script> 再 <!--<script> 结束"
        html = self._build_with("一句话: 同一笔出库只出一次钱", f"一句话: {summary}")
        node = kg_data(html)["graphs"]["示例项目"]["nodes"]["示例项目/业务/交易/出库/出库流程/出库幂等"]
        self.assertEqual(node["summary"], summary)
        raw = html.split('id="kg-data">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<!--", raw)  # would make the parser skip the real </script> after a later <script

    def test_side_toc_indents_h3(self):
        html = self._build_with("用到了[幂等]", "### 细节\n\n用到了[幂等]")
        outbound = AssetBook(self.fixtures).register_doc(self.note)
        toc = html.split(f'id="doc-{outbound}"', 1)[1].split('<div class="side-toc">', 1)[1].split('<div class="side-refs">')[0]
        self.assertIn(f'<a href="#{outbound}-h1" data-toc>一句话</a>', toc)
        self.assertIn(f'<a href="#{outbound}-h2" data-toc class="toc-3">细节</a>', toc)


def kg_data(html: str) -> dict:
    """The graph data embedded in the page, read the way a browser would: up to the first </script>."""
    raw = html.split('<script type="application/json" id="kg-data">', 1)[1].split("</script>", 1)[0]
    return json.loads(raw)


class GraphWiringTest(unittest.TestCase):
    """build() hangs the knowledge graphs on the site, which the page embeds as JSON."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with mock.patch("build.render_page", wraps=render_page) as render:
            self.errors = build(SAMPLE, FIXTURES, Path(self.tmp.name) / "学习台.html", NOW)
        self.site = render.call_args.args[0]
        self.book = AssetBook(FIXTURES)

    def tearDown(self):
        self.tmp.cleanup()

    def _demo_nodes(self) -> dict:
        return next(p for p in self.site.projects if p.name == "示例项目").graph["nodes"]

    def test_project_and_concept_graphs_built(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(self._demo_nodes()["示例项目/业务/交易/出库/出库流程"]["kind"], "note")
        self.assertEqual(self.site.concept_graph["root"], "概念")
        self.assertIn("概念/幂等", self.site.concept_graph["nodes"])

    def test_doc_nodes_in_skeleton_order(self):
        outbound = self.book.register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        overview = self.book.register_doc(SAMPLE / "项目/示例项目/系统全景.md")
        idempotent = self.book.register_doc(SAMPLE / "概念/幂等.md")
        self.assertEqual(self.site.doc_nodes[outbound],
                         ["示例项目/业务/交易/出库/出库流程", "示例项目/业务/交易/订单与优惠/付款计划生成"])
        self.assertEqual(self.site.doc_nodes[overview], ["示例项目/业务"])
        self.assertEqual(self.site.doc_nodes[idempotent], ["概念/幂等"])

    def test_refs_filled_from_backlinks(self):
        outbound = self.book.register_doc(SAMPLE / "项目/示例项目/业务/出库数据流.md")
        self.assertEqual(self._demo_nodes()["示例项目/业务/交易/出库/出库流程"]["refs"], [["问题", "#问题"]])
        card = self.site.concept_graph["nodes"]["概念/幂等"]
        self.assertEqual(card["refs"], [["工作", "#工作"], ["出库流程与数据流", f"#doc-{outbound}"]])
        self.assertIn("示例项目/业务/交易/出库/出库流程/出库幂等", card["next"])


if __name__ == "__main__":
    unittest.main()
