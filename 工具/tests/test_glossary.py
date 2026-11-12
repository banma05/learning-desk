import unittest

from hub.glossary import Term, parse_glossary

HEADER = "| 术语 | 一句话 | 出处 |\n|---|---|---|\n"
ROW = "| 运费 / 超时仓储费（`shippingFeeAmount`（`shippingFeeRate`，日费率）） | 超时后按天产生的仓储费 | `ShippingRule.java:35,53` |"


class ParseGlossaryTest(unittest.TestCase):
    def test_names_and_code_aliases(self):
        terms, errors = parse_glossary(f"## 二\n{HEADER}{ROW}\n", "术语表.md")
        self.assertEqual(errors, [])
        self.assertEqual(
            terms,
            [
                Term(
                    name="运费",
                    aliases=["超时仓储费", "shippingFeeAmount", "shippingFeeRate"],
                    meaning="超时后按天产生的仓储费",
                    source="`ShippingRule.java:35,53`",
                    line=4,
                )
            ],
        )

    def test_parenthesised_values_are_not_aliases(self):
        text = HEADER + "| 计划状态（10 待还 / 20 部分付款） | 付款计划的进度 | 要问人 |\n"
        terms, _ = parse_glossary(text, "术语表.md")
        self.assertEqual((terms[0].name, terms[0].aliases), ("计划状态", []))

    def test_half_width_parentheses_and_bold(self):
        text = HEADER + "| **KYC (Know Your Customer)** | 核实身份 | x |\n"
        terms, _ = parse_glossary(text, "术语表.md")
        self.assertEqual((terms[0].name, terms[0].aliases), ("KYC", []))

    def test_plain_words_in_parentheses_dropped_but_codes_kept(self):
        text = HEADER + "| 活体（live / `LiveAuthEnum`） | 证明是真人 | x |\n"
        terms, _ = parse_glossary(text, "术语表.md")
        self.assertEqual((terms[0].name, terms[0].aliases), ("活体", ["LiveAuthEnum"]))

    def test_parentheses_inside_code_span_do_not_break_nesting(self):
        text = HEADER + "| 出库（`pay()`） | 打钱 | x |\n| 仓储费 | 借钱的价格 | x |\n"
        terms, _ = parse_glossary(text, "术语表.md")
        self.assertEqual([(t.name, t.aliases) for t in terms], [("出库", ["pay()"]), ("仓储费", [])])

    def test_other_tables_ignored(self):
        text = "| 名称 | 说明 | 备注 |\n|---|---|---|\n| 甲 | 乙 | 丙 |\n\n" + HEADER + "| 仓储费 | 借钱的价格 | x |\n"
        terms, errors = parse_glossary(text, "术语表.md")
        self.assertEqual([t.name for t in terms], ["仓储费"])
        self.assertEqual(errors, [])

    def test_reads_every_glossary_table(self):
        text = HEADER + "| 甲 | a | x |\n\n### 下一节\n\n" + HEADER + "| 乙 | b | y |\n"
        terms, _ = parse_glossary(text, "术语表.md")
        self.assertEqual([(t.name, t.line) for t in terms], [("甲", 3), ("乙", 9)])

    def test_blank_line_ends_table_before_other_table(self):
        text = HEADER + "| 甲 | a | x |\n\n| 名称 | 说明 | 备注 |\n|---|---|---|\n| 乙 | b | y |\n"
        terms, errors = parse_glossary(text, "术语表.md")
        self.assertEqual([t.name for t in terms], ["甲"])
        self.assertEqual(errors, [])

    def test_blank_line_ends_table_before_next_glossary_table(self):
        text = HEADER + "| 甲 | a | x |\n\n" + HEADER + "| 乙 | b | y |\n"
        terms, errors = parse_glossary(text, "术语表.md")
        self.assertEqual([t.name for t in terms], ["甲", "乙"])
        self.assertEqual(errors, [])

    def test_empty_name_reported(self):
        terms, errors = parse_glossary(HEADER + "| | m | s |\n", "术语表.md")
        self.assertEqual(terms, [])
        self.assertEqual((errors[0].file, errors[0].line), ("术语表.md", 3))
        self.assertIn("术语表行缺名称", errors[0].message)

    def test_short_row_reported(self):
        text = HEADER + "| 仓储费 | 借钱的价格 |\n| 书款 | 借的钱 | x |\n"
        terms, errors = parse_glossary(text, "术语表.md")
        self.assertEqual([t.name for t in terms], ["书款"])
        self.assertEqual(len(errors), 1)
        self.assertEqual((errors[0].file, errors[0].line), ("术语表.md", 3))
        self.assertIn("术语表行缺列", errors[0].message)


if __name__ == "__main__":
    unittest.main()
