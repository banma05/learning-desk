const test = require("node:test");
const assert = require("node:assert");
const KG = require("../../hub/static/graph.js");

// A tiny hand-made graph: P > A > (A1 > A1x, A2), B (leaf), plus prereq edges.
function node(id, parent, children, extra) {
  return Object.assign({ id, name: id.split("/").pop(), parent, children, block: 0, kind: "group",
    prereqs: [], next: [], shape: "empty" }, extra || {});
}

function sample() {
  const nodes = {
    "P": node("P", null, ["P/A", "P/B"], { kind: "project", block: -1 }),
    "P/A": node("P/A", "P", ["P/A/A1", "P/A/A2"], { kind: "block" }),
    "P/B": node("P/B", "P", [], { kind: "block", block: 1, prereqs: ["P/A"] }),
    "P/A/A1": node("P/A/A1", "P/A", ["P/A/A1/x"], { kind: "note", prereqs: ["概念/幂等"], next: ["P/A/A2"] }),
    "P/A/A2": node("P/A/A2", "P/A", [], { kind: "note", prereqs: ["P/A/A1", "P/A/A1/x"] }),
    "P/A/A1/x": node("P/A/A1/x", "P/A/A1", [], { kind: "point", next: ["P/A/A2"] }),
  };
  return { name: "P", root: "P", nodes };
}

function fan(count) {
  const kids = Array.from({ length: count }, (_, i) => `R/k${i}`);
  const nodes = { "R": node("R", null, kids, { kind: "project" }) };
  kids.forEach((id) => { nodes[id] = node(id, "R", []); });
  return { name: "R", root: "R", nodes };
}

const levels = (win) => Object.fromEntries(win.nodes.map((n) => [n.id, n.lvl]));

test("window has parent ghost, children, grandchildren", () => {
  const graph = sample();
  graph.nodes["P/A/A1/x"].children = ["P/A/A1/x/deep"];
  graph.nodes["P/A/A1/x/deep"] = node("P/A/A1/x/deep", "P/A/A1/x", []);
  const win = KG.visibleWindow(graph, "P/A");
  assert.deepStrictEqual(levels(win), { "P": -1, "P/A": 0, "P/A/A1": 1, "P/A/A2": 1, "P/A/A1/x": 2 });
  assert.deepStrictEqual(win.links, [
    { a: "P", b: "P/A", kind: "up" },
    { a: "P/A", b: "P/A/A1", kind: "c1" },
    { a: "P/A/A1", b: "P/A/A1/x", kind: "c2" },
    { a: "P/A", b: "P/A/A2", kind: "c1" },
  ]);
});

test("root has no ghost", () => {
  const win = KG.visibleWindow(sample(), "P");
  assert.strictEqual(win.nodes.filter((n) => n.lvl === -1).length, 0);
  assert.strictEqual(win.links.filter((l) => l.kind === "up").length, 0);
  assert.deepStrictEqual(levels(win), { "P": 0, "P/A": 1, "P/B": 1, "P/A/A1": 2, "P/A/A2": 2 });
});

test("radius per level is exported", () => {
  assert.deepStrictEqual(KG.RADIUS, { "-1": 12, 0: 24, 1: 15, 2: 6 });
});

test("targets stay inside and apart for 20 children", () => {
  const graph = fan(20);
  const [w, h] = [720, 540];
  const tgt = KG.targets(KG.visibleWindow(graph, "R"), graph, w, h);
  const kids = graph.nodes.R.children;
  for (const id of ["R", ...kids]) {
    const { x, y } = tgt[id];
    assert.ok(x >= 0 && x <= w && y >= 0 && y <= h, `${id} at ${x},${y}`);
  }
  for (let i = 0; i < kids.length; i++) {
    for (let j = i + 1; j < kids.length; j++) {
      const d = Math.hypot(tgt[kids[i]].x - tgt[kids[j]].x, tgt[kids[i]].y - tgt[kids[j]].y);
      assert.ok(d > 2 * KG.RADIUS[1], `${kids[i]} and ${kids[j]} only ${d} apart`);
    }
  }
  assert.deepStrictEqual([tgt.R.x, tgt.R.y], [w / 2, h / 2]);
});

test("ghost sits up-left of the centre, grandchildren outside their parent", () => {
  const graph = sample();
  const tgt = KG.targets(KG.visibleWindow(graph, "P/A"), graph, 720, 540);
  assert.ok(tgt.P.x < tgt["P/A"].x && tgt.P.y < tgt["P/A"].y);
  const dist = (id) => Math.hypot(tgt[id].x - 360, tgt[id].y - 270);
  assert.ok(dist("P/A/A1/x") > dist("P/A/A1"));
});

test("single child is placed, not NaN", () => {
  const graph = fan(1);
  const tgt = KG.targets(KG.visibleWindow(graph, "R"), graph, 400, 300);
  for (const { x, y } of Object.values(tgt)) assert.ok(Number.isFinite(x) && Number.isFinite(y));
  assert.notDeepStrictEqual(tgt["R/k0"], tgt.R);
  const lone = { name: "L", root: "L", nodes: { L: node("L", null, []) } };
  assert.deepStrictEqual(KG.targets(KG.visibleWindow(lone, "L"), lone, 400, 300), { L: { x: 200, y: 150 } });
});

test("step converges near targets", () => {
  const graph = sample();
  const win = KG.visibleWindow(graph, "P/A");
  const tgt = KG.targets(win, graph, 720, 540);
  const pos = {}, vel = {}, radii = {};
  for (const n of win.nodes) {
    pos[n.id] = { x: 360, y: 270 };  // everything starts stacked on the centre
    vel[n.id] = { x: 0, y: 0 };
    radii[n.id] = KG.RADIUS[n.lvl];
  }
  for (let i = 0; i < 200; i++) KG.step(pos, vel, tgt, radii, 1);
  for (const n of win.nodes) {
    const d = Math.hypot(pos[n.id].x - tgt[n.id].x, pos[n.id].y - tgt[n.id].y);
    assert.ok(d < 3, `${n.id} is ${d} from its target`);
  }
});

test("preLinks only within window and lvl>=0", () => {
  const graph = sample();
  // centre P/A: P is the ghost (lvl -1), so P/B -> P/A is out; concept ids are not in the window
  assert.deepStrictEqual(KG.preLinks(KG.visibleWindow(graph, "P/A"), graph), [
    { a: "P/A/A1", b: "P/A/A2" },
    { a: "P/A/A1/x", b: "P/A/A2" },
  ]);
  // centre P: P/A/A1/x is a great-grandchild, out of the window
  assert.deepStrictEqual(KG.preLinks(KG.visibleWindow(graph, "P"), graph), [
    { a: "P/A/A1", b: "P/A/A2" },
    { a: "P/A", b: "P/B" },
  ]);
});

test("neighborhood lists prereqs and next", () => {
  const graph = sample();
  assert.deepStrictEqual(KG.neighborhood(graph, "P/A/A1"),
    { self: "P/A/A1", parent: "P/A", prereqs: ["概念/幂等"], next: ["P/A/A2"] });
  assert.deepStrictEqual(KG.neighborhood(graph, "P"), { self: "P", parent: null, prereqs: [], next: [] });
});

test("hue by block, accent for roots", () => {
  assert.strictEqual(KG.hueOf({ block: 1 }), KG.HUES[1]);
  assert.strictEqual(KG.hueOf({ block: 7 }), KG.HUES[1]);
  assert.strictEqual(KG.hueOf({ block: -1 }), "var(--accent)");
});

test("plain drops markdown marks, keeps link text", () => {
  assert.strictEqual(KG.plain("**伪装成从库**，读 `binlog`，见 [Kafka](../Kafka.md)"), "伪装成从库，读 binlog，见 Kafka");
});

// Root with children of 0..9 grandchildren each, like a busy block.
function bushy() {
  const nodes = { R: node("R", null, [], { kind: "project" }) };
  for (let i = 0; i < 6; i++) {
    const kid = `R/k${i}`;
    nodes.R.children.push(kid);
    nodes[kid] = node(kid, "R", []);
    for (let j = 0; j < [0, 2, 4, 6, 7, 9][i]; j++) {
      const gk = `${kid}/g${j}`;
      nodes[kid].children.push(gk);
      nodes[gk] = node(gk, kid, [], { kind: "point" });
    }
  }
  return { name: "R", root: "R", nodes };
}

const size = (lvl) => KG.RADIUS[lvl] + KG.PAD[lvl];  // the collision size the page uses

test("fans keep every pair of dots apart by the page's collision size", () => {
  const graph = bushy();
  // the page lays out on at least LAYOUT_MIN and zooms out on smaller stages
  const min = [KG.LAYOUT_MIN.w, KG.LAYOUT_MIN.h];
  for (const [w, h] of [min, [720, 540], [900, 600], [1400, min[1]], [min[0], 1000]]) {
    const win = KG.visibleWindow(graph, "R");
    const tgt = KG.targets(win, graph, w, h);
    for (let i = 0; i < win.nodes.length; i++) {
      for (let j = i + 1; j < win.nodes.length; j++) {
        const a = win.nodes[i], b = win.nodes[j];
        const d = Math.hypot(tgt[a.id].x - tgt[b.id].x, tgt[a.id].y - tgt[b.id].y);
        assert.ok(d >= size(a.lvl) + size(b.lvl), `${w}x${h}: ${a.id} and ${b.id} only ${d.toFixed(1)} apart`);
      }
    }
  }
});

test("a fresh drill settles within about a second (60 frames)", () => {
  const graph = bushy();
  const [w, h] = [720, 540];
  const win = KG.visibleWindow(graph, "R/k5");
  const tgt = KG.targets(win, graph, w, h);
  const pos = {}, vel = {}, radii = {};
  win.nodes.forEach((n, i) => {  // new dots grow out of the clicked one, as on the page
    pos[n.id] = { x: 600 + 6 * Math.cos(i * 2.4), y: 120 + 6 * Math.sin(i * 2.4) };
    vel[n.id] = { x: 0, y: 0 };
    radii[n.id] = size(n.lvl);
  });
  let frames = 0;
  const speed = () => Math.max(...Object.values(vel).map((v) => Math.hypot(v.x, v.y)));
  do { KG.step(pos, vel, tgt, radii, 1); frames++; } while (speed() >= KG.REST_SPEED && frames < 600);
  assert.ok(frames <= 60, `still moving after ${frames} frames`);
  for (const n of win.nodes) {
    assert.ok(Math.hypot(pos[n.id].x - tgt[n.id].x, pos[n.id].y - tgt[n.id].y) < 2, `${n.id} off target`);
  }
});

test("slow frames take the same time to settle", () => {
  const graph = bushy();
  const win = KG.visibleWindow(graph, "R");
  const tgt = KG.targets(win, graph, 720, 540);
  const pos = {}, vel = {}, radii = {};
  win.nodes.forEach((n, i) => {
    pos[n.id] = { x: 360 + 6 * Math.cos(i * 2.4), y: 270 + 6 * Math.sin(i * 2.4) };
    vel[n.id] = { x: 0, y: 0 };
    radii[n.id] = size(n.lvl);
  });
  for (let i = 0; i < 15; i++) KG.step(pos, vel, tgt, radii, 4);  // one second at 15 fps
  for (const n of win.nodes) {
    assert.ok(Math.hypot(pos[n.id].x - tgt[n.id].x, pos[n.id].y - tgt[n.id].y) < 2, `${n.id} off target`);
  }
});
