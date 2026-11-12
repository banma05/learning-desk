const test = require("node:test");
const assert = require("node:assert");
const Reader = require("../../hub/static/reader.js");

// P > 结算 > 足迹 (note, doc d1) > 借据的钱 / 优惠顺序 (points); a concept card and a glossary term.
function node(id, parent, children, extra) {
  return Object.assign({ id, name: id.split("/").pop(), parent, children, block: 0, kind: "group", doc: null,
    anchor: "", summary: "", status: "没碰", shape: "empty", doc_status: null, prereqs: [], next: [],
    confusions: [] }, extra || {});
}

function sample() {
  const project = {
    "P": node("P", null, ["P/结算 · 钱"], { kind: "project", block: -1 }),
    "P/结算 · 钱": node("P/结算 · 钱", "P", ["P/结算 · 钱/足迹"], { kind: "block", name: "结算 · 钱" }),
    "P/结算 · 钱/足迹": node("P/结算 · 钱/足迹", "P/结算 · 钱", ["P/结算 · 钱/足迹/借据的钱", "P/结算 · 钱/足迹/优惠顺序"],
      { kind: "note", doc: "d1", status: "学习中", shape: "half", doc_status: "学习中", prereqs: ["概念/幂等"],
        mastered: 1, units: 2 }),
    "P/结算 · 钱/足迹/借据的钱": node("P/结算 · 钱/足迹/借据的钱", "P/结算 · 钱/足迹", [],
      { kind: "point", doc: "d1", anchor: "d1-h2", status: "已掌握", shape: "full", doc_status: "学习中" }),
    "P/结算 · 钱/足迹/优惠顺序": node("P/结算 · 钱/足迹/优惠顺序", "P/结算 · 钱/足迹", [],
      { kind: "point", doc: "d1", anchor: "d1-h3", status: "学习中", shape: "half", doc_status: "学习中",
        summary: "先抵**运费**，再书款 <b>", prereqs: ["P/结算 · 钱/足迹/借据的钱", "概念/幂等", "不存在"],
        confusions: ["概念/幂等"] }),
  };
  const concepts = {
    "概念": node("概念", null, ["概念/概念"], { kind: "project", block: -1 }),
    "概念/概念": node("概念/概念", "概念", ["概念/幂等"], { block: -1 }),
    "概念/幂等": node("概念/幂等", "概念/概念", [], { kind: "concept", block: -1, doc: "c1", status: "已掌握",
      shape: "full", doc_status: "已掌握", summary: "做多次和做一次一样。" }),
  };
  return {
    graphs: { P: { name: "P", root: "P", nodes: project }, "概念": { name: "概念", root: "概念", nodes: concepts } },
    terms: {
      "p:P/结算 · 钱/足迹/优惠顺序": { name: "优惠顺序", kind: "point", summary: "先抵**运费**，再书款 <b>",
        source: "", node: "P/结算 · 钱/足迹/优惠顺序" },
      "c:幂等": { name: "幂等", kind: "concept", summary: "做多次和做一次一样。", source: "", node: "概念/幂等" },
      "g:P/运费": { name: "运费", kind: "term", summary: "超时后<b>按天</b>产生的仓储费",
        source: "<code>ShippingRule.java:35</code>", node: null },
    },
    docNodes: { d1: ["P/结算 · 钱/足迹"], c1: ["概念/幂等"] },
    search: [{ k: "note", t: "一本书的足迹", s: "", w: [], href: "#doc-d1", a: "", node: "P/结算 · 钱/足迹" }],
  };
}

test("crumb from root", () => {
  const graph = sample().graphs.P;
  assert.deepStrictEqual(Reader.crumbPath(graph, "P/结算 · 钱/足迹"), [
    { id: "P", name: "P", doc: null },
    { id: "P/结算 · 钱", name: "结算", doc: null },
    { id: "P/结算 · 钱/足迹", name: "足迹", doc: "d1" },
  ]);
  assert.deepStrictEqual(Reader.crumbPath(graph, "missing"), []);
});

test("scroll remembered per hash and overwritten", () => {
  const store = {};
  assert.strictEqual(Reader.recallScroll(store, "doc-a"), null);
  Reader.rememberScroll(store, "doc-a", 120.6);
  Reader.rememberScroll(store, "doc-b", 40);
  assert.strictEqual(Reader.recallScroll(store, "doc-a"), 121);
  Reader.rememberScroll(store, "doc-a", 0);
  assert.strictEqual(Reader.recallScroll(store, "doc-a"), 0);
  assert.strictEqual(Reader.recallScroll(store, "doc-b"), 40);
});

test("peek for term point shows summary and prereq names", () => {
  const model = Reader.peekModel(sample(), { term: "p:P/结算 · 钱/足迹/优惠顺序" });
  assert.strictEqual(model.kind, "point");
  assert.strictEqual(model.title, "优惠顺序");
  assert.strictEqual(model.status, "学习中");
  assert.strictEqual(model.shape, "half");
  assert.strictEqual(model.node, "P/结算 · 钱/足迹/优惠顺序");
  assert.strictEqual(model.summary, "先抵运费，再书款 &lt;b&gt;");  // plain text: marks dropped, escaped
  assert.deepStrictEqual(model.prereqs, [
    { id: "P/结算 · 钱/足迹/借据的钱", name: "借据的钱" }, { id: "概念/幂等", name: "幂等" },
  ]);
  assert.deepStrictEqual(model.confusions, [{ id: "概念/幂等", name: "幂等" }]);
  assert.strictEqual(model.open, "#doc-d1");
  assert.strictEqual(model.anchor, "d1-h3");
});

test("peek for doc link shows note status and open href", () => {
  const model = Reader.peekModel(sample(), { doc: "d1", title: "页面上的标题" });
  assert.strictEqual(model.kind, "note");
  assert.strictEqual(model.title, "一本书的足迹");
  assert.strictEqual(model.status, "学习中");
  assert.strictEqual(model.shape, "half");
  assert.strictEqual(model.open, "#doc-d1");
  assert.strictEqual(model.anchor, "");
  assert.deepStrictEqual(model.prereqs, [{ id: "概念/幂等", name: "幂等" }]);
  assert.deepStrictEqual(model.points.map((p) => [p.name, p.status, p.anchor]),
    [["借据的钱", "已掌握", "d1-h2"], ["优惠顺序", "学习中", "d1-h3"]]);

  const concept = Reader.peekModel(sample(), { doc: "c1" });
  assert.strictEqual(concept.kind, "concept");
  assert.strictEqual(concept.summary, "做多次和做一次一样。");
  assert.strictEqual(concept.open, "#doc-c1");

  const attachment = Reader.peekModel(sample(), { doc: "x9", title: "附页 <1>" });
  assert.strictEqual(attachment.title, "附页 <1>");
  assert.strictEqual(attachment.status, "");
  assert.strictEqual(attachment.node, null);
  assert.strictEqual(attachment.open, "#doc-x9");
});

test("peek for glossary term has source and no node", () => {
  const model = Reader.peekModel(sample(), { term: "g:P/运费" });
  assert.strictEqual(model.kind, "term");
  assert.strictEqual(model.title, "运费");
  assert.strictEqual(model.node, null);
  assert.strictEqual(model.status, "");
  assert.strictEqual(model.summary, "超时后<b>按天</b>产生的仓储费");  // already rendered HTML
  assert.strictEqual(model.source, "<code>ShippingRule.java:35</code>");
  assert.deepStrictEqual(model.prereqs, []);
  assert.strictEqual(model.open, null);
  assert.strictEqual(Reader.peekModel(sample(), { term: "nope" }), null);
});

test("a point term whose node is gone is still escaped as plain text", () => {
  const data = sample();
  data.terms["p:P/gone"] = { name: "gone", kind: "point", summary: "a **b** <i>", source: "", node: "P/gone" };
  const model = Reader.peekModel(data, { term: "p:P/gone" });
  assert.strictEqual(model.kind, "point");
  assert.strictEqual(model.node, null);
  assert.strictEqual(model.summary, "a b &lt;i&gt;");
});

test("peek markup: status slot only for points, open link carries the anchor", () => {
  const point = Reader.peekHtml(Reader.peekModel(sample(), { term: "p:P/结算 · 钱/足迹/优惠顺序" }));
  assert.ok(point.includes('<span class="status-buttons" data-node="P/结算 · 钱/足迹/优惠顺序"></span>'));
  assert.ok(point.includes('<a class="peek-open" href="#doc-d1" data-anchor="d1-h3" '
    + 'data-node="P/结算 · 钱/足迹/优惠顺序">打开全文 →</a>'));
  assert.ok(point.includes('<a href="#" data-peek-node="概念/幂等">幂等</a>'));
  const note = Reader.peekHtml(Reader.peekModel(sample(), { doc: "d1" }));
  assert.ok(!note.includes("status-buttons"));
  assert.ok(note.includes('data-anchor="" data-node="">打开全文'));  // a doc link: the page picks the node
  assert.ok(note.includes('data-peek-node="P/结算 · 钱/足迹/借据的钱">借据的钱</a>'));
  const attachment = Reader.peekHtml(Reader.peekModel(sample(), { doc: "x9", title: "附页 <1>" }));
  assert.ok(attachment.includes("<span>附页 &lt;1&gt;</span>"));
  assert.ok(!attachment.includes("peek-status"));
});

test("mini graph puts prereqs left, next right, parent on top", () => {
  const hood = { self: "s", parent: "p", prereqs: ["a", "b"], next: ["n"] };
  const spots = Reader.miniLayout(hood, 240);
  const at = Object.fromEntries(spots.dots.map((d) => [d.id, d]));
  assert.ok(at.a.x < at.s.x && at.n.x > at.s.x);
  assert.ok(at.p.y < at.s.y && at.p.x === at.s.x);
  assert.notStrictEqual(at.a.y, at.b.y);
  assert.deepStrictEqual(spots.dots.map((d) => d.role).sort(), ["next", "parent", "prereq", "prereq", "self"]);
  spots.dots.forEach((d) => assert.ok(d.x > 0 && d.x < 240 && d.y > 0 && d.y < spots.height));
  const alone = Reader.miniLayout({ self: "s", parent: null, prereqs: [], next: [] }, 240);
  assert.deepStrictEqual(alone.dots.map((d) => d.id), ["s"]);
});

// The same note hung in two places: 足迹 (whole note) and 结算 › 应付 › 运费 (one section of it).
function twoMounts() {
  const data = sample(), nodes = data.graphs.P.nodes;
  nodes["P/结算 · 钱"].children.push("P/结算 · 钱/应付");
  nodes["P/结算 · 钱/应付"] = node("P/结算 · 钱/应付", "P/结算 · 钱", ["P/结算 · 钱/应付/运费"]);
  nodes["P/结算 · 钱/应付/运费"] = node("P/结算 · 钱/应付/运费", "P/结算 · 钱/应付", [],
    { kind: "note", doc: "d1", anchor: "d1-h4" });
  data.docNodes.d1 = ["P/结算 · 钱/足迹", "P/结算 · 钱/应付/运费"];
  return data;
}

test("reading page is drawn for the node the reader came from", () => {
  const data = twoMounts(), ids = data.docNodes.d1;
  assert.strictEqual(Reader.chooseNode(data, ids, "P/结算 · 钱/应付/运费"), "P/结算 · 钱/应付/运费");
  assert.strictEqual(Reader.chooseNode(data, ids, "P/结算 · 钱/足迹"), "P/结算 · 钱/足迹");
  // a point stands for the node it hangs under
  assert.strictEqual(Reader.chooseNode(data, ids, "P/结算 · 钱/足迹/优惠顺序"), "P/结算 · 钱/足迹");
  // nothing remembered, or a node of another doc: the first node showing the whole note
  assert.strictEqual(Reader.chooseNode(data, ids, null), "P/结算 · 钱/足迹");
  assert.strictEqual(Reader.chooseNode(data, ids, "概念/幂等"), "P/结算 · 钱/足迹");
  assert.strictEqual(Reader.chooseNode(data, ["P/结算 · 钱/应付/运费", "P/结算 · 钱/足迹"], ""), "P/结算 · 钱/足迹");
  assert.strictEqual(Reader.chooseNode(data, ["P/结算 · 钱/应付/运费"], null), "P/结算 · 钱/应付/运费");
  assert.strictEqual(Reader.chooseNode(data, ["gone"], null), null);
});

test("crumb follows the chosen node and the other places are listed once", () => {
  const data = twoMounts(), ids = data.docNodes.d1, here = "P/结算 · 钱/应付/运费";
  assert.deepStrictEqual(Reader.crumbPath(data.graphs.P, here).map((l) => l.name), ["P", "结算", "应付", "运费"]);
  assert.deepStrictEqual(Reader.alsoMounts(data, ids, here), [{ id: "P/结算 · 钱/足迹", names: ["P", "结算", "足迹"] }]);
  assert.deepStrictEqual(Reader.alsoMounts(data, ["P/结算 · 钱/足迹"], "P/结算 · 钱/足迹"), []);  // one place: no line
  assert.deepStrictEqual(Reader.alsoMounts(data, [...ids, "gone"], "P/结算 · 钱/足迹").map((m) => m.id), [here]);
});

test("a section node opens at its section", () => {
  const model = Reader.peekModel(twoMounts(), { node: "P/结算 · 钱/应付/运费" });
  assert.strictEqual(model.anchor, "d1-h4");
  assert.ok(Reader.peekHtml(model).includes('data-anchor="d1-h4" data-node="P/结算 · 钱/应付/运费">打开全文'));
});

test("the place naming a point: first text with its name or an alias", () => {
  const point = { name: "运费与包装费", aliases: ["shippingFee", " "] };
  assert.deepStrictEqual(Reader.pointLabels(point), ["运费与包装费", "shippingFee"]);
  const texts = ["超时后每天跑任务", "字段 SHIPPING fee 按天加", "运费与 包装费都算"];
  assert.strictEqual(Reader.firstMention(texts, Reader.pointLabels(point)), 1);  // case and spaces ignored
  assert.strictEqual(Reader.firstMention(texts.slice(0, 1), Reader.pointLabels(point)), -1);
  assert.strictEqual(Reader.firstMention(texts.slice(2), ["运费与包装费"]), 0);
});
