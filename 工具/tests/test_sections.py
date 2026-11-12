import unittest

from hub.sections import (find_heading, heading_count, heading_stem, mentions, names_agree, section_span,
                          section_text, stem)

HEADINGS = [(2, "一、位置", "d-h1"), (3, "1. 四个库", "d-h2"), (3, "2. 两张表", "d-h3"), (2, "二、概念", "d-h4"),
            (3, "6. 运费和包装费", "d-h5"), (2, "样本", "d-h6"), (2, "样本", "d-h7")]


class StemTest(unittest.TestCase):
    def test_stem_drops_notes_and_takes_the_part_before_separators(self):
        self.assertEqual(stem("GMV 验算设计（#10002，设计阶段）"), "gmv验算设计")
        self.assertEqual(stem("出库数据流 — 以及怎么读数据流"), "出库数据流")
        self.assertEqual(stem("结算地基：钱在哪"), "结算地基")
        self.assertEqual(stem("业务 · 一本书的一生"), "业务")
        self.assertEqual(stem("运费和包装费"), stem("运费与包装费"))

    def test_heading_stem_drops_the_number(self):
        for text in ("7. 优惠顺序：几种优惠先用哪一个", "一、优惠顺序", "第 7 条：优惠顺序", "（3）优惠顺序", "4.2 优惠顺序"):
            self.assertEqual(heading_stem(text), "优惠顺序", text)

    def test_names_agree_when_one_stem_contains_the_other(self):
        self.assertTrue(names_agree("超时定时任务与运费", "超时定时任务与运费"))
        self.assertTrue(names_agree("优惠顺序与满减", "7. 优惠顺序：几种优惠先用哪一个", heading=True))
        self.assertTrue(names_agree("运费与包装费", "运费和包装费怎么算（ShippingFeeCalculator.java）",
                                    heading=True))
        self.assertFalse(names_agree("积分与会员等级", "等级与积分"))
        self.assertFalse(names_agree("价格构成", "4. 向用户收的钱有哪几种", heading=True))

    def test_name_agrees_through_the_part_after_the_dot(self):
        self.assertTrue(names_agree("定位与决策 · 总览与决策", "demo-app 总览与决策"))
        self.assertTrue(names_agree("结算地基 · 钱在哪", "结算地基：钱在哪、怎么算、怎么记"))
        self.assertFalse(names_agree("定位与决策 · 第一版", "demo-app 总览与决策"))

    def test_target_agrees_through_the_part_after_a_separator(self):
        self.assertTrue(names_agree("选书与下单", "差异清单：选书与下单（10-31）", heading=True))
        self.assertTrue(names_agree("AB 测试", "① AB 测试（#/promoTest，POST /api/promo/rule）", heading=True))
        self.assertFalse(names_agree("GMV 销量", "GMV 计算链路 — 从一条数据库改动到一张销量报表"))


class SectionTest(unittest.TestCase):
    def test_find_and_count(self):
        self.assertEqual(find_heading(HEADINGS, "样本"), 5)
        self.assertEqual(heading_count(HEADINGS, "样本"), 2)
        self.assertIsNone(find_heading(HEADINGS, "没有"))

    def test_span_ends_at_same_or_higher_level(self):
        self.assertEqual(section_span(HEADINGS, 0), (0, 3))
        self.assertEqual(section_span(HEADINGS, 1), (1, 2))
        self.assertEqual(section_span(HEADINGS, 4), (4, 5))
        self.assertEqual(section_span(HEADINGS, 6), (6, 7))

    def test_section_text(self):
        body = ('<h2 id="d-h1">位置</h2><p>甲 &amp; 乙</p><h3 id="d-h2">库</h3><p><span class="term">运</span>费</p>'
                '<h4>细节</h4><p>丙</p><h3 id="d-h3">表</h3><p>丁</p><h2 id="d-h4">概念</h2><p>戊</p>')
        self.assertEqual(section_text(body, "d-h2"), "库运费细节丙")
        self.assertEqual(section_text(body, "d-h1"), "位置甲 & 乙库运费细节丙表丁")
        self.assertEqual(section_text(body, "d-h4"), "概念戊")
        self.assertEqual(section_text(body, "missing"), "")

    def test_mentions_ignores_case_and_spaces(self):
        self.assertTrue(mentions("用 Kafka消费组 收消息", ["kafka 消费组"]))
        self.assertTrue(mentions("先冲运费", ["优惠顺序", "运费"]))
        self.assertFalse(mentions("先冲运费", ["优惠顺序", " "]))


if __name__ == "__main__":
    unittest.main()
