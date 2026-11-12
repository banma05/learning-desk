const test = require("node:test");
const assert = require("node:assert");
const Status = require("../../hub/static/status.js");

function pointEdit(raw, line) {
  return { file: "项目/P/笔记.md", line: line || 2, raw, kind: "point" };
}

test("replaces only the status value on a point line", () => {
  const raw = "- 运费怎么算 | 状态: 学习中 | 一句话: 每天累加 -> #四、运费";
  const got = Status.rewriteStatus("# t\n" + raw + "\n尾\n", pointEdit(raw), "已掌握");
  assert.deepStrictEqual(got, { ok: true, text: "# t\n- 运费怎么算 | 状态: 已掌握 | 一句话: 每天累加 -> #四、运费\n尾\n" });
  const wide = "  - 甲 | 一句话: x | 状态：没碰";
  assert.strictEqual(Status.rewriteStatus("# t\n" + wide, pointEdit(wide), "学习中").text, "# t\n  - 甲 | 一句话: x | 状态：学习中");
});

test("inserts status after the name when missing", () => {
  const cases = [
    ["- 甲 | 一句话: x", "- 甲 | 状态: 学习中 | 一句话: x"],
    ["- 甲", "- 甲 | 状态: 学习中"],
    ["- 甲 -> #一节", "- 甲 | 状态: 学习中 -> #一节"],
    ["- 甲 | 别名: a -> #x | y", "- 甲 | 状态: 学习中 | 别名: a -> #x | y"],
  ];
  cases.forEach(([before, after]) => {
    assert.strictEqual(Status.rewriteStatus("# t\n" + before + "\n", pointEdit(before), "学习中").text, "# t\n" + after + "\n");
  });
});

test("a status word in the anchor or inside another field is left alone", () => {
  const anchor = "- 甲 | 一句话: x -> #状态: 学习中";
  assert.strictEqual(Status.rewriteStatus("# t\n" + anchor, pointEdit(anchor), "已掌握").text,
    "# t\n- 甲 | 状态: 已掌握 | 一句话: x -> #状态: 学习中");
  const inside = "- 甲 | 一句话: 某状态: x";
  assert.strictEqual(Status.rewriteStatus("# t\n" + inside, pointEdit(inside), "已掌握").text,
    "# t\n- 甲 | 状态: 已掌握 | 一句话: 某状态: x");
  const both = "- 甲 | 状态: 没碰 | 一句话: 某状态: x";
  assert.strictEqual(Status.rewriteStatus("# t\n" + both, pointEdit(both), "已掌握").text,
    "# t\n- 甲 | 状态: 已掌握 | 一句话: 某状态: x");
});

test("an empty status value is filled in and keeps the spacing around it", () => {
  const raw = "- 甲 | 状态: | 一句话: x";
  assert.strictEqual(Status.rewriteStatus("# t\n" + raw, pointEdit(raw), "学习中").text, "# t\n- 甲 | 状态: 学习中 | 一句话: x");
  const tight = "- 甲 |状态:| 一句话: x";
  assert.strictEqual(Status.rewriteStatus("# t\n" + tight, pointEdit(tight), "学习中").text, "# t\n- 甲 |状态: 学习中| 一句话: x");
  const last = "- 甲 | 状态: ";
  assert.strictEqual(Status.rewriteStatus("# t\n" + last, pointEdit(last), "学习中").text, "# t\n- 甲 | 状态: 学习中 ");
  const head = { file: "a.md", line: 1, raw: "> 状态: ", kind: "header" };
  assert.strictEqual(Status.rewriteStatus("> 状态: \n", head, "只看过").text, "> 状态: 只看过 \n");
});

test("a point line with two status fields is refused", () => {
  const raw = "- 甲 | 状态: 已掌握 | 状态: 没碰";
  assert.deepStrictEqual(Status.rewriteStatus("# t\n" + raw, pointEdit(raw), "已掌握"), { ok: false, reason: "ambiguous" });
});

test("header status line replaced", () => {
  const text = "# 幂等\n\n> 类型: 概念\n> 状态: 学习中\n> 更新: 2025-10-24\n";
  const edit = { file: "概念/幂等.md", line: 4, raw: "> 状态: 学习中", kind: "header" };
  assert.deepStrictEqual(Status.rewriteStatus(text, edit, "只看过"),
    { ok: true, text: "# 幂等\n\n> 类型: 概念\n> 状态: 只看过\n> 更新: 2025-10-24\n" });
  const wide = { file: "a.md", line: 1, raw: ">状态：已掌握", kind: "header" };
  assert.strictEqual(Status.rewriteStatus(">状态：已掌握", wide, "学习中").text, ">状态：学习中");
});

test("refuses when the line changed", () => {
  const edit = pointEdit("- 甲 | 状态: 没碰");
  assert.deepStrictEqual(Status.rewriteStatus("# t\n- 甲 | 状态: 学习中\n", edit, "已掌握"), { ok: false, reason: "changed" });
  assert.deepStrictEqual(Status.rewriteStatus("# t\n- 甲 | 状态: 没碰 \n", edit, "已掌握"), { ok: false, reason: "changed" });
  assert.deepStrictEqual(Status.rewriteStatus("# t", edit, "已掌握"), { ok: false, reason: "missing" });
  assert.deepStrictEqual(Status.rewriteStatus("# t\n- 甲 | 状态: 没碰\n", { ...edit, line: 0 }, "已掌握"),
    { ok: false, reason: "missing" });
  // a header edit whose line is no longer a status line is refused even if raw matches
  const odd = { file: "a.md", line: 1, raw: "> 更新: 2026", kind: "header" };
  assert.deepStrictEqual(Status.rewriteStatus("> 更新: 2026", odd, "已掌握"), { ok: false, reason: "changed" });
});

test("a lone carriage return makes the file unsupported (the generator counts lines differently)", () => {
  assert.deepStrictEqual(Status.rewriteStatus("# t\r- 甲 | 状态: 没碰\n", pointEdit("- 甲 | 状态: 没碰"), "已掌握"),
    { ok: false, reason: "unsupported" });
});

test("keeps CRLF and BOM", () => {
  const got = Status.rewriteStatus("\uFEFF# t\r\n- 甲 | 状态: 没碰\r\n", pointEdit("- 甲 | 状态: 没碰"), "已掌握");
  assert.deepStrictEqual(got, { ok: true, text: "\uFEFF# t\r\n- 甲 | 状态: 已掌握\r\n" });
  const first = { file: "a.md", line: 1, raw: "> 状态: 学习中", kind: "header" };
  assert.strictEqual(Status.rewriteStatus("\uFEFF> 状态: 学习中\r\nx\n", first, "已掌握").text, "\uFEFF> 状态: 已掌握\r\nx\n");
});

const BUILT = "2025-11-03 10:15";

function graph() {
  const nodes = {
    "P": { id: "P", status: "学习中", shape: "half", children: ["P/n", "P/blk"], edit: null },
    "P/n": { id: "P/n", status: "学习中", shape: "half", doc_status: "学习中", children: ["P/n/a", "P/n/b"], edit: null },
    "P/n/a": { id: "P/n/a", status: "没碰", shape: "empty", doc_status: "学习中", children: [],
               edit: pointEdit("- a | 状态: 没碰") },
    "P/n/b": { id: "P/n/b", status: "学习中", shape: "half", doc_status: "学习中", children: [],
               edit: pointEdit("- b | 状态: 学习中", 3) },
    "P/h": { id: "P/h", status: "学习中", shape: "half", doc_status: "学习中", children: [],
             edit: { file: "h.md", line: 3, raw: "> 状态: 学习中", kind: "header" } },
    // a block with its own note: status is the block's rollup, doc_status the note's header
    "P/blk": { id: "P/blk", status: "学习中", shape: "half", doc_status: "只看过", children: ["P/blk/x"],
               edit: { file: "blk.md", line: 3, raw: "> 状态: 只看过", kind: "header" } },
    "P/blk/x": { id: "P/blk/x", status: "学习中", shape: "half", children: [], edit: null },
  };
  return { name: "P", root: "P", nodes };
}

function entry(status, from, raw, generatedAt) {
  return { status, from, raw, generatedAt: generatedAt || BUILT };
}

test("overlay applies only to the same page build that still has the line it was changed from", () => {
  const overlay = {
    "P/n/a": entry("已掌握", "- a | 状态: 没碰", "- a | 状态: 已掌握"),
    // the page was rebuilt from the changed file: its raw is the entry's new line
    "P/n/b": entry("已掌握", "- b | 状态: 没碰", "- b | 状态: 学习中"),
    "P/h": entry("只看过", "> 状态: 学习中", "> 状态: 只看过"),
    "别处/x": entry("已掌握", "", ""),
  };
  const g = Status.applyOverlay(graph(), overlay, BUILT);
  assert.strictEqual(g.nodes["P/n/a"].status, "已掌握");
  assert.strictEqual(g.nodes["P/n/a"].shape, "full");
  assert.strictEqual(g.nodes["P/n/a"].edit.raw, "- a | 状态: 已掌握");
  assert.strictEqual(g.nodes["P/n/a"].doc_status, "学习中");  // a point's doc_status is the note's
  assert.strictEqual(g.nodes["P/n/b"].status, "学习中");
  assert.strictEqual(g.nodes["P/n/b"].shape, "half");
  assert.strictEqual(g.nodes["P/h"].status, "只看过");
  assert.strictEqual(g.nodes["P/h"].shape, "empty");
  assert.strictEqual(g.nodes["P/h"].doc_status, "只看过");
  assert.strictEqual(g.nodes["P/h"].edit.raw, "> 状态: 只看过");
  assert.strictEqual(g.nodes["P/n"].shape, "half");  // rollups are not recomputed
  assert.strictEqual(Status.applyOverlay(graph(), null, BUILT).nodes["P/n/a"].status, "没碰");
  const bad = { "P/n/a": entry("只看过", "- a | 状态: 没碰", "- a | 状态: 只看过") };
  assert.strictEqual(Status.applyOverlay(graph(), bad, BUILT).nodes["P/n/a"].status, "没碰");  // not a point status
  // rebuilt with the line set back to exactly `from` (e.g. by Claude): another build, the entry is over
  const back = { "P/n/a": entry("已掌握", "- a | 状态: 没碰", "- a | 状态: 已掌握", "2025-11-03 09:00") };
  assert.strictEqual(Status.applyOverlay(graph(), back, BUILT).nodes["P/n/a"].status, "没碰");
});

test("a block's header edit changes only its note's status, not the block's rollup", () => {
  const g = Status.applyOverlay(graph(), { "P/blk": entry("已掌握", "> 状态: 只看过", "> 状态: 已掌握") }, BUILT);
  const block = g.nodes["P/blk"];
  assert.deepStrictEqual([block.status, block.shape, block.doc_status, block.edit.raw],
    ["学习中", "half", "已掌握", "> 状态: 已掌握"]);
  assert.strictEqual(Status.current(graph().nodes["P/blk"]), "只看过");  // what the buttons show as pressed
  assert.strictEqual(Status.current(graph().nodes["P/h"]), "学习中");
  assert.strictEqual(Status.current(graph().nodes["P/n/a"]), "没碰");
});

test("copy line names the point, the new status and the file", () => {
  const node = { name: "运费怎么算", edit: { file: "项目/示例项目/超时.md", line: 9, raw: "", kind: "point" } };
  assert.strictEqual(Status.copyLine(node, "已掌握"), "把 运费怎么算 改成 已掌握（项目/示例项目/超时.md）");
});

test("choices follow the kind of line", () => {
  assert.deepStrictEqual(Status.choices({ kind: "point" }), ["已掌握", "学习中", "没碰"]);
  assert.deepStrictEqual(Status.choices({ kind: "header" }), ["已掌握", "学习中", "只看过"]);
  assert.deepStrictEqual(Status.choices(null), []);
});

// ---- the file side, over an in-memory stand-in for File System Access handles ----

class FakeFile {
  constructor(bytes) { this.bytes = bytes; this.writes = 0; }
  async getFile() { const bytes = this.bytes; return { arrayBuffer: async () => bytes.slice().buffer }; }
  async createWritable() {
    const file = this, parts = [];
    return { write: async (chunk) => { parts.push(chunk); }, close: async () => {
      file.bytes = new Uint8Array(Buffer.concat(parts.map((p) => Buffer.from(p))));
      file.writes++;
    } };
  }
}

class FakeDir {
  constructor(entries, name) { this.entries = entries; this.name = name || ""; }
  async getDirectoryHandle(name) { return this.lookup(name, FakeDir); }
  async getFileHandle(name) { return this.lookup(name, FakeFile); }
  lookup(name, kind) {
    const entry = this.entries[name];
    if (!(entry instanceof kind)) throw Object.assign(new Error(name), { name: "NotFoundError" });
    return entry;
  }
}

function bytesOf(text) {
  return new Uint8Array(Buffer.from(text, "utf8"));
}

test("writeStatus changes exactly the status bytes of one line", async () => {
  const before = "\uFEFF# 笔记\r\n> 状态: 学习中\r\n\r\n## 知识点\n- 甲 | 状态: 没碰 | 一句话: 一\r\n- 乙 | 一句话: 二\n";
  const file = new FakeFile(bytesOf(before));
  const root = new FakeDir({ "项目": new FakeDir({ "P": new FakeDir({ "笔记.md": file }) }) });
  const got = await Status.writeStatus(root, { file: "项目/P/笔记.md", line: 5, raw: "- 甲 | 状态: 没碰 | 一句话: 一", kind: "point" }, "已掌握");
  assert.deepStrictEqual(got, { ok: true, raw: "- 甲 | 状态: 已掌握 | 一句话: 一" });
  assert.deepStrictEqual(Buffer.from(file.bytes), Buffer.from(before.replace("没碰", "已掌握"), "utf8"));
  const again = await Status.writeStatus(root, { file: "项目/P/笔记.md", line: 6, raw: "- 乙 | 一句话: 二", kind: "point" }, "学习中");
  assert.strictEqual(again.ok, true);
  assert.deepStrictEqual(Buffer.from(file.bytes),
    Buffer.from(before.replace("没碰", "已掌握").replace("- 乙 |", "- 乙 | 状态: 学习中 |"), "utf8"));
});

test("writeStatus refuses without writing", async () => {
  const file = new FakeFile(bytesOf("# t\n- 甲 | 状态: 学习中\n"));
  const root = new FakeDir({ "a.md": file, "gbk.md": new FakeFile(new Uint8Array([0x2d, 0x20, 0xbc, 0xd7, 0x0a])),
                             "two.md": new FakeFile(bytesOf("- 甲 | 状态: 已掌握 | 状态: 没碰\n")) });
  const edit = { file: "a.md", line: 2, raw: "- 甲 | 状态: 没碰", kind: "point" };
  assert.deepStrictEqual(await Status.writeStatus(root, edit, "已掌握"), { ok: false, reason: "changed" });
  assert.deepStrictEqual(await Status.writeStatus(root, { ...edit, file: "b/a.md" }, "已掌握"), { ok: false, reason: "missing" });
  assert.deepStrictEqual(await Status.writeStatus(root, { ...edit, file: "gbk.md", line: 1 }, "已掌握"),
    { ok: false, reason: "unsupported" });
  assert.deepStrictEqual(await Status.writeStatus(root, { file: "two.md", line: 1, raw: "- 甲 | 状态: 已掌握 | 状态: 没碰", kind: "point" }, "已掌握"),
    { ok: false, reason: "ambiguous" });
  const same = { ...edit, raw: "- 甲 | 状态: 学习中" };
  assert.deepStrictEqual(await Status.writeStatus(root, same, "学习中"), { ok: false, reason: "unchanged" });
  assert.strictEqual(file.writes, 0);
});

test("only this page's folder with 维护约定.md or 项目/ counts as the knowledge base", async () => {
  const mark = () => ({ "维护约定.md": new FakeFile(bytesOf("")) });
  assert.strictEqual(await Status.looksLikeKb(new FakeDir(mark(), "我的知识库"), "我的知识库"), true);
  assert.strictEqual(await Status.looksLikeKb(new FakeDir({ "项目": new FakeDir({}) }, "我的知识库"), "我的知识库"), true);
  assert.strictEqual(await Status.looksLikeKb(new FakeDir({ "其他.md": new FakeFile(bytesOf("")) }, "我的知识库"), "我的知识库"), false);
  assert.strictEqual(await Status.looksLikeKb(new FakeDir(mark(), "样例记录"), "我的知识库"), false);
  assert.strictEqual(Status.pageFolder("/D:/notes/我的知识库/学习台.html"), "我的知识库");
  assert.strictEqual(Status.pageFolder(""), "");
});

function withStorage(store, pathname, run) {
  global.window = { localStorage: { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; } } };
  global.location = { pathname };
  try {
    run();
  } finally {
    delete global.window;
    delete global.location;
  }
}

test("page data takes this page's entries that still apply and drops the others", () => {
  const here = "/D:/kb/学习台.html", other = "/D:/tmp/学习台.html";
  const saved = {
    [here]: {
      "P/n/a": entry("已掌握", "- a | 状态: 没碰", "- a | 状态: 已掌握"),
      "P/n/b": entry("已掌握", "- b | 状态: 没碰", "- b | 状态: 已掌握"),  // file changed since
      "P/h": entry("只看过", "> 状态: 学习中", "> 状态: 只看过", "2025-11-02 08:00"),  // an older build
      "P/gone": entry("已掌握", "x", "y"),
    },
    [other]: { "P/h": entry("只看过", "> 状态: 学习中", "> 状态: 只看过") },
  };
  const store = { "kg-overlay": JSON.stringify(saved) };
  withStorage(store, "/D:/kb/%E5%AD%A6%E4%B9%A0%E5%8F%B0.html", () => {
    const data = Status.overlayData({ generatedAt: BUILT, graphs: { P: graph() } });
    assert.strictEqual(data.graphs.P.nodes["P/n/a"].status, "已掌握");
    assert.strictEqual(data.graphs.P.nodes["P/n/b"].status, "学习中");
    assert.strictEqual(data.graphs.P.nodes["P/h"].status, "学习中");
    const kept = JSON.parse(store["kg-overlay"]);
    assert.deepStrictEqual(Object.keys(kept[here]), ["P/n/a"]);
    assert.deepStrictEqual(kept[other], saved[other]);
  });
});

test("forgetting a line drops this page's entries for it", () => {
  const here = "/D:/kb/学习台.html";
  const saved = { [here]: { "P/n/a": entry("已掌握", "x", "y"), "P/q/a": entry("已掌握", "x", "y"),
                            "P/n/b": entry("已掌握", "x", "y") }, "/other.html": { "P/n/a": entry("已掌握", "x", "y") } };
  const store = { "kg-overlay": JSON.stringify(saved) };
  withStorage(store, here, () => {
    Status.forgetEntries(["P/n/a", "P/q/a"]);
    const kept = JSON.parse(store["kg-overlay"]);
    assert.deepStrictEqual(Object.keys(kept[here]), ["P/n/b"]);
    assert.deepStrictEqual(Object.keys(kept["/other.html"]), ["P/n/a"]);
  });
});
