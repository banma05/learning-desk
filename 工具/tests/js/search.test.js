const test = require("node:test");
const assert = require("node:assert");
const Search = require("../../hub/static/search.js");

function entry(kind, title, words, extra) {
  return Object.assign({ k: kind, t: title, s: "", w: words || [title], href: "#doc-d1", a: "", node: "" }, extra || {});
}

const ENTRIES = [
  entry("point", "超时运费怎么算"),
  entry("point", "运费"),
  entry("point", "运费率的来源"),
  entry("point", "仓储费和运费的区别"),
  entry("note", "付款与完结"),
  entry("concept", "幂等", ["幂等", "idempotent", "幂等性"]),
  entry("heading", "运费的两种算法", ["运费的两种算法"]),
  entry("point", "Kafka 消费组", ["Kafka 消费组", "consumer group"]),
];

test("exact before prefix before contains", () => {
  const titles = Search.searchIndex(ENTRIES, "运费").point.map((e) => e.t);
  assert.deepStrictEqual(titles, ["运费", "运费率的来源", "超时运费怎么算", "仓储费和运费的区别"]);
});

test("results are grouped by kind", () => {
  const groups = Search.searchIndex(ENTRIES, "运费");
  assert.deepStrictEqual(Object.keys(groups), ["point", "note", "concept", "heading"]);
  assert.deepStrictEqual(groups.heading.map((e) => e.t), ["运费的两种算法"]);
  assert.deepStrictEqual(groups.note, []);
});

test("alias matches", () => {
  const groups = Search.searchIndex(ENTRIES, "idempotent");
  assert.deepStrictEqual(groups.concept.map((e) => e.t), ["幂等"]);
});

test("case insensitive ascii", () => {
  assert.deepStrictEqual(Search.searchIndex(ENTRIES, "KAFKA").point.map((e) => e.t), ["Kafka 消费组"]);
  assert.deepStrictEqual(Search.searchIndex(ENTRIES, "Consumer GROUP").point.map((e) => e.t), ["Kafka 消费组"]);
});

test("empty query empty result", () => {
  for (const query of ["", "   ", null, undefined]) {
    const groups = Search.searchIndex(ENTRIES, query);
    assert.deepStrictEqual(groups, { point: [], note: [], concept: [], heading: [] });
  }
  assert.deepStrictEqual(Search.searchText([{ docId: "d1", title: "t", blocks: ["运费"] }], "  "), []);
});

test("each group stops at the limit", () => {
  const many = Array.from({ length: 12 }, (_, i) => entry("point", "运费 " + i));
  assert.strictEqual(Search.searchIndex(many, "运费").point.length, 8);
  assert.strictEqual(Search.searchIndex(many, "运费", 3).point.length, 3);
});

test("text snippet around hit", () => {
  const long = "前".repeat(60) + "运费按日计算" + "后".repeat(80);
  const docs = [{ docId: "d1", title: "付款", blocks: ["没有相关内容", long, "短句里也有运费"] }];
  const hits = Search.searchText(docs, "运费");
  assert.deepStrictEqual(hits.map((h) => h.elementIndex), [1, 2]);
  assert.strictEqual(hits[0].docId, "d1");
  assert.strictEqual(hits[0].title, "付款");
  assert.ok(hits[0].snippet.includes("运费按日计算"));
  assert.ok(hits[0].snippet.startsWith("…") && hits[0].snippet.endsWith("…"));
  assert.ok(hits[0].snippet.length <= 90);  // 24 before + hit + 56 after + two ellipses
  assert.strictEqual(hits[1].snippet, "短句里也有运费");  // short block: shown whole, no ellipses
});

test("text search is case insensitive and stops at the limit", () => {
  const blocks = Array.from({ length: 15 }, (_, i) => "Kafka topic " + i);
  const docs = [{ docId: "d1", title: "t", blocks }, { docId: "d2", title: "u", blocks: ["kafka"] }];
  const hits = Search.searchText(docs, "KAFKA");
  assert.strictEqual(hits.length, 10);
  assert.ok(hits.every((h) => h.docId === "d1"));
  assert.strictEqual(Search.searchText(docs, "KAFKA", 20).length, 16);
});

test("highlight escapes the text and marks every match", () => {
  assert.strictEqual(Search.highlight("a<b>运费</b>", "运费"), "a&lt;b&gt;<mark>运费</mark>&lt;/b&gt;");
  assert.strictEqual(Search.highlight("Kafka kafka", "KAFKA"), "<mark>Kafka</mark> <mark>kafka</mark>");
  assert.strictEqual(Search.highlight("<i>", "运费"), "&lt;i&gt;");
});

test("alias hint only when the title itself does not match", () => {
  const idem = ENTRIES[5];
  assert.strictEqual(Search.aliasHint(idem, "idempotent"), "idempotent");
  assert.strictEqual(Search.aliasHint(idem, "幂等"), "");
});

test("groups put 知识点 / 笔记 / 概念 / 标题 / 正文 in that order and skip empty ones", () => {
  const docs = [{ docId: "d1", title: "付款", blocks: ["运费按日计算"] }];
  const groups = Search.buildGroups(ENTRIES, docs, "运费");
  assert.deepStrictEqual(groups.map((g) => g.label), ["知识点", "标题", "正文"]);
  assert.strictEqual(groups[0].items[0].kind, "point");
  assert.strictEqual(groups[2].items[0].kind, "text");
  assert.strictEqual(groups[2].items[0].hit.elementIndex, 0);
});

test("html: 没有找到 when nothing matches, markup escaped otherwise", () => {
  assert.ok(Search.resultsHtml([], "运费").includes("没有找到"));
  const groups = Search.buildGroups([entry("point", "<b>运费</b>")], [], "运费");
  const html = Search.resultsHtml(groups, "运费");
  assert.ok(html.includes("&lt;b&gt;<mark>运费</mark>&lt;/b&gt;"));
  assert.ok(!html.includes("<b>运费"));
  assert.ok(html.includes('data-i="0"') && html.includes("知识点"));
});

test("ownText leaves out nested blocks but keeps inline markup text", () => {
  const text = (value) => ({ nodeType: 3, textContent: value });
  const inline = (value) => ({ nodeType: 1, textContent: value, matches: () => false });
  const block = (value) => ({ nodeType: 1, textContent: value, matches: () => true });
  const li = { childNodes: [text("先抵 "), inline("运费"), text("，再书款"), block("子项文字")] };
  assert.strictEqual(Search.ownText(li), "先抵 运费，再书款");
});

test("keys typed while an input method is composing are left to it", () => {
  assert.strictEqual(Search.composing({ key: "Enter", isComposing: true, keyCode: 13 }), true);
  assert.strictEqual(Search.composing({ key: "Process", isComposing: false, keyCode: 229 }), true);
  assert.strictEqual(Search.composing({ key: "Enter", isComposing: false, keyCode: 13 }), false);
});
