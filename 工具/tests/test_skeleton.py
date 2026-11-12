import unittest
from pathlib import Path

from hub.skeleton import coverage, is_topic, node_paths, parse_skeleton
from hub.textio import read_text

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT = FIXTURES / "项目"
SKELETON = read_text(PROJECT / "骨架.md")


class ParseSkeletonTest(unittest.TestCase):
    def test_tree_measures_and_links(self):
        roots, errors = parse_skeleton(SKELETON, "骨架.md", PROJECT)
        biz = roots[0]
        self.assertEqual(biz.name, "业务 · 一本书的一生")
        sub = biz.children[0].children[0]
        self.assertEqual(sub.name, "引流与渠道")
        self.assertEqual(sub.measures, ["渠道与转化"])
        self.assertTrue(is_topic(sub.children[0]))
        self.assertEqual(errors, [])

    def test_same_note_linked_from_two_topics_counts_twice(self):
        roots, _ = parse_skeleton(SKELETON, "骨架.md", PROJECT)
        self.assertEqual(coverage(roots[0]), (2, 4))

    def test_link_on_non_topic_node_not_counted(self):
        roots, _ = parse_skeleton(SKELETON, "骨架.md", PROJECT)
        self.assertEqual(roots[0].links, ["系统全景.md"])
        self.assertEqual(coverage(roots[0]), (2, 4))

    def test_missing_note_is_dropped_and_reported(self):
        text = "- 结算\n  - 财务核算\n    - GMV 销量 -> 结算/不存在.md\n"
        roots, errors = parse_skeleton(text, "骨架.md", PROJECT)
        self.assertEqual(roots[0].children[0].children[0].links, [])
        self.assertEqual(str(errors[0]), "骨架.md:3 笔记不存在：结算/不存在.md")

    def test_link_to_a_section(self):
        text = "- 业务\n  - 全景主干 -> 系统全景.md#三、主流程（8 步）\n  - 整篇 -> 系统全景.md\n"
        roots, errors = parse_skeleton(text, "骨架.md", PROJECT)
        section, whole = roots[0].children
        self.assertEqual((section.links, section.anchor), (["系统全景.md"], "三、主流程（8 步）"))
        self.assertEqual((whole.links, whole.anchor), (["系统全景.md"], ""))
        self.assertEqual(errors, [])

    def test_missing_note_with_section_reported_by_file(self):
        roots, errors = parse_skeleton("- 业务\n  - 甲 -> 没有.md#某节\n", "骨架.md", PROJECT)
        self.assertEqual(roots[0].children[0].links, [])
        self.assertEqual(str(errors[0]), "骨架.md:2 笔记不存在：没有.md")

    def test_reference_heading_marks_following_roots(self):
        text = "- 业务\n  - 出库\n## 参考\n- 术语表 -> 系统全景.md\n"
        roots, errors = parse_skeleton(text, "骨架.md", PROJECT)
        self.assertEqual(errors, [])
        self.assertEqual([r.reference for r in roots], [False, True])
        self.assertEqual(roots[1].links, ["系统全景.md"])
        self.assertIn("术语表", node_paths(roots))

    def test_bad_indent_is_reported(self):
        _, errors = parse_skeleton("- 业务\n   - 三个空格\n", "骨架.md", PROJECT)
        self.assertEqual(errors[0].line, 2)

    def test_measures_accept_fullwidth_comma(self):
        roots, _ = parse_skeleton("- 推荐 | 衡量: 售前·选书与下单，推荐模型\n", "骨架.md", PROJECT)
        self.assertEqual(roots[0].measures, ["售前·选书与下单", "推荐模型"])

    def test_arrow_without_spaces_parsed_and_reported(self):
        roots, errors = parse_skeleton("- 出库流程->业务/样例笔记.md\n", "骨架.md", PROJECT)
        self.assertEqual(roots[0].name, "出库流程")
        self.assertEqual(roots[0].links, ["业务/样例笔记.md"])
        self.assertEqual(str(errors[0]), "骨架.md:1 -> 两边应有空格")

    def test_node_paths_use_short_block_names_and_strip_notes(self):
        text = "- 业务 · 一本书的一生\n  - 交易\n    - 出库\n- 多仓差异与配送\n  - 包装与配送（待 上级 核实）\n"
        roots, _ = parse_skeleton(text, "骨架.md", PROJECT)
        paths = node_paths(roots)
        self.assertIn("业务/交易/出库", paths)
        self.assertIn("多仓差异与配送/包装与配送", paths)
        self.assertIn("业务", paths)


if __name__ == "__main__":
    unittest.main()
