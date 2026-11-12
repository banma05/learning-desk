// Entry page: collapsible tree + drill-down knowledge graph (three levels on screen), linked both ways.
// Pure layout helpers are exported for tests and for the reading page's mini graph.
var KG = (function () {
  "use strict";

  var RADIUS = { "-1": 12, 0: 24, 1: 15, 2: 6 };
  var HUES = ["#3370ff", "#14a37f", "#f08a24", "#8b5cf6", "#e2557a", "#0ea5c6"];
  var ROOT_HUE = "var(--accent)";
  // collision room around a dot: only keeps dots apart in motion; label room comes from the targets,
  // which never put two dots closer than their collision sizes
  var PAD = { "-1": 6, 0: 10, 1: 8, 2: 5 };
  var LEVEL_CLASS = { "-1": "kg-lup", 0: "kg-l0", 1: "kg-l1", 2: "kg-l2" };
  var LABEL_MAX = { "-1": 12, 0: 24, 1: 14, 2: 10 };
  // wanted distance between neighbouring grandchildren in one fan row: more when the fan points up or
  // down, because then their labels sit side by side
  var FAN_GAP = 30, FAN_LABEL_GAP = 46;
  var LABEL_HALF = { 1: 40, 2: 30 };  // about half a label's width, kept inside the stage
  // per 1/60 s; the step decays at the same rate per second at any frame rate, so slow frames (up to
  // 15 fps) are taken in one step instead of slowing the motion down
  var SPRING = 0.13, FRICTION = 0.66, PUSH = 0.35, REST_SPEED = 0.1, MAX_DT = 4;
  // the layout is computed on at least this canvas and shown zoomed out on a smaller one, so a small
  // stage never squeezes dots together
  var LAYOUT_MIN = { w: 640, h: 580 };
  var STATUS_CHIP = { "已掌握": "ok", "学习中": "doing" };

  // ---- pure helpers ----

  /** Nodes on screen around centerId: parent ghost (-1), centre (0), children (1), grandchildren (2). */
  function visibleWindow(graph, centerId) {
    var nodes = graph.nodes, center = nodes[centerId], win = { nodes: [], links: [] };
    if (center.parent && nodes[center.parent]) {
      win.nodes.push({ id: center.parent, lvl: -1 });
      win.links.push({ a: center.parent, b: centerId, kind: "up" });
    }
    win.nodes.push({ id: centerId, lvl: 0 });
    center.children.forEach(function (kid) {
      win.nodes.push({ id: kid, lvl: 1 });
      win.links.push({ a: centerId, b: kid, kind: "c1" });
      nodes[kid].children.forEach(function (grandkid) {
        win.nodes.push({ id: grandkid, lvl: 2 });
        win.links.push({ a: kid, b: grandkid, kind: "c2" });
      });
    });
    return win;
  }

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  /** Target point of every window node: centre in the middle, children on an ellipse, each child's
   *  children in a small fan outside it, the parent ghost up-left. All kept inside width x height. */
  function targets(win, graph, width, height) {
    var cx = width / 2, cy = height / 2, scale = clamp(Math.min(width / 720, height / 540), 0.5, 1.3);
    var rx = width * 0.3, ry = height * 0.28, out = {}, start = -Math.PI / 2;
    var kids = win.nodes.filter(function (n) { return n.lvl === 1; });
    win.nodes.forEach(function (n) {
      if (n.lvl === 0) out[n.id] = { x: cx, y: cy };
      if (n.lvl !== -1) return;
      out[n.id] = { x: cx - 250 * scale, y: cy - 175 * scale };
      start = Math.atan2(-175 * scale / ry, -250 * scale / rx);  // the ghost's line falls between two children
    });
    var slot = 2 * Math.PI / Math.max(kids.length, 1), crowded = kids.length > 12;
    kids.forEach(function (kid, i) {
      var angle = start + (i + 0.5) * slot, ring = crowded && i % 2 ? 0.78 : 1;  // many: two rings
      var kx = cx + rx * ring * Math.cos(angle), ky = cy + ry * ring * Math.sin(angle);
      out[kid.id] = { x: kx, y: ky };
      fan(out, graph.nodes[kid.id].children, kx, ky, angle, slot, scale);
    });
    fit(out, win, width, height);
    win.nodes.forEach(function (n) {
      var margin = RADIUS[n.lvl] + 4, p = out[n.id];
      p.x = clamp(p.x, margin, width - margin);
      p.y = clamp(p.y, margin, height - margin - 14);  // room for the label under the dot
    });
    return out;
  }

  /** A child's children in a fan outside it, using up to most of the child's slot. From 4 on they
   *  alternate between two rows (labels don't collide) and reach further so neighbours in a row keep
   *  their gap; small fans are flattened like the prototype's. */
  function fan(out, ids, kx, ky, angle, slot, scale) {
    var count = ids.length, rows = count >= 4 ? 2 : 1, perRow = Math.ceil(count / rows);
    var spread = Math.min(0.42 * (count - 1), Math.max(1.3, 0.9 * slot));
    var gap = FAN_GAP + FAN_LABEL_GAP * Math.abs(Math.sin(angle));
    var reach = Math.min(Math.max(95 * scale, spread ? gap * (perRow - 1) / spread : 0), 200 * scale);
    var flat = count > 3 ? 1 : 0.72;
    ids.forEach(function (id, j) {
      var b = count === 1 ? angle : angle - spread / 2 + j * spread / (count - 1);
      var r = reach * (rows > 1 && j % 2 ? 1.3 : 1);
      out[id] = { x: kx + r * Math.cos(b), y: ky + r * flat * Math.sin(b) };
    });
  }

  /** Squeeze the layout towards the centre when dots and their labels would stick out of the stage,
   *  but never so far that two dots end up closer than their collision sizes. */
  function fit(out, win, width, height) {
    var cx = width / 2, cy = height / 2, ex = 1, ey = 1, floor = 0, nodes = win.nodes;
    nodes.forEach(function (n) {
      var p = out[n.id], r = RADIUS[n.lvl];
      ex = Math.max(ex, Math.abs(p.x - cx) + r + (LABEL_HALF[n.lvl] || 0));
      ey = Math.max(ey, Math.abs(p.y - cy) + r + 18);
    });
    var sx = Math.min(1, (cx - 6) / ex), sy = Math.min(1, (cy - 6) / ey);
    if (sx === 1 && sy === 1) return;
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a = out[nodes[i].id], b = out[nodes[j].id], d = Math.hypot(a.x - b.x, a.y - b.y);
        floor = Math.max(floor, (collisionSize(nodes[i].lvl) + collisionSize(nodes[j].lvl)) / (d || 1));
      }
    }
    sx = Math.min(1, Math.max(sx, floor));
    sy = Math.min(1, Math.max(sy, floor));
    win.nodes.forEach(function (n) {
      out[n.id].x = cx + (out[n.id].x - cx) * sx;
      out[n.id].y = cy + (out[n.id].y - cy) * sy;
    });
  }

  function collisionSize(lvl) {
    return RADIUS[lvl] + PAD[lvl];
  }

  /** One animation frame (dt in 1/60 s): spring towards the target, push overlapping dots apart,
   *  damp. Changes pos and vel in place; only ids that have a target move. */
  function step(pos, vel, tgt, radii, dt) {
    var ids = Object.keys(tgt).filter(function (id) { return pos[id]; });
    ids.forEach(function (id) {
      var v = vel[id] || (vel[id] = { x: 0, y: 0 });
      v.x += (tgt[id].x - pos[id].x) * SPRING * dt;
      v.y += (tgt[id].y - pos[id].y) * SPRING * dt;
    });
    for (var i = 0; i < ids.length; i++) {
      for (var j = i + 1; j < ids.length; j++) {
        var a = pos[ids[i]], b = pos[ids[j]], dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
        var least = (radii[ids[i]] || 0) + (radii[ids[j]] || 0);
        if (d >= least) continue;
        if (d < 1e-6) {  // stacked: separate along a fixed direction per pair
          dx = Math.cos(i * 2.39996 + j); dy = Math.sin(i * 2.39996 + j); d = 1;
        }
        var push = (least - d) / d * PUSH * dt / 2, va = vel[ids[i]], vb = vel[ids[j]];
        va.x -= dx * push; va.y -= dy * push; vb.x += dx * push; vb.y += dy * push;
      }
    }
    var keep = Math.pow(FRICTION, dt);
    ids.forEach(function (id) {
      var v = vel[id];
      v.x *= keep; v.y *= keep;
      pos[id].x += v.x * dt; pos[id].y += v.y * dt;
    });
  }

  /** "要先懂" edges (a must be understood before b) between two window nodes that are not the ghost. */
  function preLinks(win, graph) {
    var shown = {}, seen = {}, out = [];
    win.nodes.forEach(function (n) { if (n.lvl >= 0) shown[n.id] = true; });
    win.nodes.forEach(function (n) {
      if (n.lvl < 0) return;
      (graph.nodes[n.id].prereqs || []).forEach(function (p) {
        var key = p + "\n" + n.id;
        if (shown[p] && p !== n.id && !seen[key]) {
          seen[key] = true;
          out.push({ a: p, b: n.id });
        }
      });
    });
    return out;
  }

  /** What the reading page's mini graph draws around one node (ids may live in another graph). */
  function neighborhood(graph, nodeId) {
    var node = graph.nodes[nodeId];
    return { self: nodeId, parent: node.parent || null, prereqs: (node.prereqs || []).slice(),
             next: (node.next || []).slice() };
  }

  function hueOf(node) {
    return node.block >= 0 ? HUES[node.block % HUES.length] : ROOT_HUE;
  }

  function shortName(name) {
    return name.split(" · ")[0];
  }

  /** Readable text from a markdown snippet (summaries): drop emphasis and code marks, keep link text. */
  function plain(md) {
    return String(md).replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\*\*|__|`/g, "");
  }

  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** SVG markup of a dot of radius r drawn at the origin: full, half, empty or dashed (colour = --h). */
  function shapeMarkup(shape, r, width) {
    var sw = ' stroke-width="' + width + '"';
    if (shape === "full") return '<circle class="kg-body kg-full" r="' + r + '"' + sw + "/>";
    var ring = '<circle class="kg-body kg-ring' + (shape === "dashed" ? " kg-dash" : "") + '" r="' + r + '"' + sw + "/>";
    if (shape !== "half") return ring;
    return ring + '<path class="kg-half" d="M0 ' + (-r) + " A" + r + " " + r + " 0 0 1 0 " + r + ' Z"/>';
  }

  /** Small status dot (tree rows, cards, the reading page): block colour, shape = mastery. */
  function iconSvg(node, size) {
    size = size || 12;
    var half = size / 2;
    return '<svg class="kg-ic" width="' + size + '" height="' + size + '" viewBox="' + (-half) + " " + (-half) + " "
      + size + " " + size + '" style="--h:' + hueOf(node) + '">' + shapeMarkup(node.shape, half - 1, 1.5) + "</svg>";
  }

  function isLeaf(node) {
    return node.kind === "point" || !node.children.length;
  }

  function storage(key, value) {
    try {
      if (value === undefined) return window.sessionStorage.getItem(key);
      if (value === null) window.sessionStorage.removeItem(key);
      else window.sessionStorage.setItem(key, value);
    } catch (e) { /* storage blocked: focus just isn't remembered */ }
    return null;
  }

  function curve(s, t, bend) {
    var mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2, dx = t.x - s.x, dy = t.y - s.y;
    return "M" + s.x + "," + s.y + " Q" + (mx - dy * bend) + "," + (my + dx * bend) + " " + t.x + "," + t.y;
  }

  // ---- one graph on the page ----

  var SVG_NS = "http://www.w3.org/2000/svg";
  var views = [], data = null;

  function View(el, graph, index) {
    this.el = el;
    this.graph = graph;
    this.name = el.dataset.graph;
    this.index = index;
    this.tree = el.querySelector(".kg-tree");
    this.stage = el.querySelector(".kg-stage");
    this.bar = el.querySelector(".kg-bar");
    this.svg = el.querySelector(".kg-svg");
    this.card = el.querySelector(".kg-card");
    this.center = graph.root;
    this.leaf = null;
    this.ready = false;
    this.w = this.h = 0;
    this.pos = {}; this.vel = {}; this.tgt = {}; this.radii = {}; this.lvl = {};
    this.links = []; this.pre = [];
    this.nodeEls = {}; this.linkEls = []; this.preEls = [];
    this.zoom = { k: 1, x: 0, y: 0 };
    this.raf = 0; this.last = 0; this.drag = null; this.rows = {}; this.cardId = null;
  }

  /** Take the stage size; false (keeping the last size) while the pane is hidden. */
  View.prototype.measure = function () {
    var box = this.svg.getBoundingClientRect(), w = Math.round(box.width), h = Math.round(box.height);
    if (!w || !h) return false;
    this.w = w;
    this.h = h;
    this.lw = Math.max(w, LAYOUT_MIN.w);
    this.lh = Math.max(h, LAYOUT_MIN.h);
    this.svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    return true;
  };

  /** Default view: the whole layout canvas, centred, zoomed out if the stage is smaller. */
  View.prototype.fitZoom = function () {
    var k = Math.min(1, this.w / this.lw, this.h / this.lh);
    this.zoom = { k: k, x: (this.w - this.lw * k) / 2, y: (this.h - this.lh * k) / 2 };
    this.svg.style.setProperty("--lz", (1 / Math.sqrt(k)).toFixed(3));  // labels shrink less than the layout
    this.applyZoom();
  };

  View.prototype.visible = function () {
    return this.stage.getClientRects().length > 0 && this.stage.clientWidth > 0;
  };

  /** Draw the first time the pane has a size (panes start hidden). */
  View.prototype.ensureReady = function () {
    if (!this.ready && this.measure()) {
      this.setup();
      this.ready = true;
      this.go(this.center, null);
    }
    return this.ready;
  };

  View.prototype.resized = function () {
    if (!this.ready) return this.ensureReady();
    if (!this.measure()) return this.stop();
    this.tgt = targets(this.win, this.graph, this.lw, this.lh);
    this.fitZoom();
    this.drawBar();
    this.kick();
  };

  View.prototype.setup = function () {
    var self = this, marker = "kg-arrow-" + this.index;
    this.svg.innerHTML = '<defs><marker id="' + marker + '" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" '
      + 'markerHeight="7" orient="auto"><path d="M0,0L8,4L0,8" class="kg-arrow"/></marker></defs>'
      + '<g class="kg-world"><g class="kg-links"></g><g class="kg-pre"></g><g class="kg-nodes"></g></g>';
    this.marker = marker;
    this.world = this.svg.querySelector(".kg-world");
    this.linkLayer = this.svg.querySelector(".kg-links");
    this.preLayer = this.svg.querySelector(".kg-pre");
    this.nodeLayer = this.svg.querySelector(".kg-nodes");
    this.bar.innerHTML = '<button class="kg-back" type="button">← 上一层</button><nav class="kg-crumb"></nav>'
      + '<label class="kg-pre-toggle" title="一直显示&quot;要先懂&quot;"><input type="checkbox"> 显示要先懂</label>';
    this.bar.querySelector(".kg-back").addEventListener("click", function () { self.up(); });
    this.bar.querySelector("input").addEventListener("change", function (e) {
      self.el.classList.toggle("pre-on", e.target.checked);
    });
    this.bar.querySelector(".kg-crumb").addEventListener("click", function (e) {
      var a = e.target.closest("a[data-id]");
      if (a) { e.preventDefault(); self.leaf = null; self.go(a.dataset.id, null); }
    });
    // card and legend live in a fixed footer under the svg, so they never cover a dot or a label
    var foot = document.createElement("div"), legend = document.createElement("div");
    foot.className = "kg-foot";
    legend.className = "kg-legend";
    legend.innerHTML = ["full", "half", "empty", "dashed"].map(function (shape, i) {
      return "<span>" + iconSvg({ block: -1, shape: shape }) + ["已掌握", "学习中", "没碰", "空白"][i] + "</span>";
    }).join("") + "<span>颜色 = 属于哪一块</span><span>橙色虚线 = 要先懂</span>";
    foot.appendChild(this.card);
    foot.appendChild(legend);
    this.stage.appendChild(foot);
    this.card.addEventListener("click", function (e) { self.cardClick(e); });
    this.buildTree();
    this.bindPointer();
  };

  /** Make id the centre. from: the node whose position new dots grow out of (the clicked one). */
  View.prototype.go = function (id, from) {
    var self = this, old = this.pos, origin = old[from || id] || { x: this.lw / 2, y: this.lh / 2 };
    this.center = id;
    this.win = visibleWindow(this.graph, id);
    this.tgt = targets(this.win, this.graph, this.lw, this.lh);
    this.links = this.win.links;
    this.pre = preLinks(this.win, this.graph);
    this.pos = {}; this.vel = {}; this.radii = {}; this.lvl = {};
    this.win.nodes.forEach(function (n, i) {
      var p = old[n.id], jitter = 6 * (i % 3 + 1), turn = i * 2.39996;
      self.pos[n.id] = p ? { x: p.x, y: p.y }
        : { x: origin.x + jitter * Math.cos(turn), y: origin.y + jitter * Math.sin(turn) };
      self.vel[n.id] = { x: 0, y: 0 };
      self.radii[n.id] = collisionSize(n.lvl);
      self.lvl[n.id] = n.lvl;
    });
    if (this.leaf && !(this.lvl[this.leaf] > 0)) this.leaf = null;
    this.drawNodes();
    this.drawLinks();
    this.fitZoom();
    this.drawBar();
    this.markTree();
    this.showCard(this.leaf || id);
    storage("kg-focus", this.leaf || id);
    this.draw();
    this.kick();
  };

  View.prototype.drawNodes = function () {
    var self = this, entering = [];
    Object.keys(this.nodeEls).forEach(function (id) {
      if (id in self.lvl) return;
      var gone = self.nodeEls[id];
      delete self.nodeEls[id];
      gone.classList.add("kg-out");
      setTimeout(function () { gone.remove(); }, 400);
    });
    this.win.nodes.forEach(function (n) {
      var g = self.nodeEls[n.id];
      if (!g) {
        g = self.nodeEls[n.id] = document.createElementNS(SVG_NS, "g");
        g.dataset.id = n.id;
        g.classList.add("kg-in");
        self.nodeLayer.appendChild(g);
        entering.push(g);
        g.addEventListener("pointerenter", function () { self.hover(g.dataset.id); });
        g.addEventListener("pointerleave", function () { self.hover(null); });
      }
      self.paintNode(g, self.graph.nodes[n.id], n.lvl);
    });
    if (entering.length) {
      this.svg.getBoundingClientRect();  // commit opacity 0 so the fade-in transition runs
      entering.forEach(function (g) { g.classList.remove("kg-in"); });
    }
  };

  View.prototype.paintNode = function (g, node, lvl) {
    var r = RADIUS[lvl], name = shortName(node.name), max = LABEL_MAX[lvl];
    var label = (lvl === -1 ? "↩ " : "") + (name.length > max ? name.slice(0, max) + "…" : name);
    var shape = lvl === -1 ? "empty" : node.shape;
    var dy = lvl === 0 ? r + 20 : r + (lvl === 2 ? 13 : 17);
    var halo = lvl === 0 ? '<circle class="kg-halo" r="' + (r + 7) + '"/>' : "";  // marks the centre
    g.setAttribute("class", "kg-node " + LEVEL_CLASS[lvl] + (lvl === -1 ? " kg-ghost" : "")
      + (node.id === this.leaf ? " kg-picked" : "") + (g.classList.contains("kg-in") ? " kg-in" : ""));
    g.style.setProperty("--h", hueOf(node));
    g.innerHTML = "<title>" + esc(node.name) + "</title>" + halo
      + shapeMarkup(shape, r, lvl === 0 ? 2.5 : lvl === 2 ? 1.5 : 2.2)
      + '<text class="kg-lbl" dy="' + dy + '">' + esc(label) + "</text>";
  };

  View.prototype.drawLinks = function () {
    var self = this;
    this.linkLayer.textContent = "";
    this.preLayer.textContent = "";
    this.linkEls = this.links.map(function (l) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("class", "kg-link " + l.kind);
      return self.linkLayer.appendChild(path);
    });
    this.preEls = this.pre.map(function (l) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("marker-end", "url(#" + self.marker + ")");
      return self.preLayer.appendChild(path);
    });
  };

  /** Move dots and lines to the current positions. */
  View.prototype.draw = function () {
    var pos = this.pos, self = this;
    Object.keys(this.nodeEls).forEach(function (id) {
      var p = pos[id];
      if (p) self.nodeEls[id].setAttribute("transform", "translate(" + p.x.toFixed(1) + "," + p.y.toFixed(1) + ")");
    });
    this.links.forEach(function (l, i) {
      self.linkEls[i].setAttribute("d", curve(pos[l.a], pos[l.b], l.kind === "c2" ? 0.08 : 0.04));
    });
    this.pre.forEach(function (l, i) {
      var a = pos[l.a], b = pos[l.b], dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
      var cut = RADIUS[self.lvl[l.b]] + 5;
      self.preEls[i].setAttribute("d", curve(a, { x: b.x - dx / len * cut, y: b.y - dy / len * cut }, 0.18));
    });
  };

  View.prototype.kick = function () {
    var self = this;
    if (this.raf || !this.ready || !this.visible()) return;
    this.last = 0;
    this.raf = requestAnimationFrame(function tick(now) {
      self.raf = 0;
      if (!self.visible()) return;
      var dt = self.last ? Math.min((now - self.last) / (1000 / 60), MAX_DT) : 1;
      self.last = now;
      step(self.pos, self.vel, self.tgt, self.radii, dt);
      var held = self.drag && self.drag.moved && self.drag.id;
      if (held) {
        self.pos[held] = { x: self.drag.at.x, y: self.drag.at.y };
        self.vel[held] = { x: 0, y: 0 };
      }
      self.draw();
      var fastest = 0;
      Object.keys(self.vel).forEach(function (id) { fastest = Math.max(fastest, Math.hypot(self.vel[id].x, self.vel[id].y)); });
      if (fastest > REST_SPEED || held) self.raf = requestAnimationFrame(tick);
    });
  };

  View.prototype.stop = function () {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  };

  View.prototype.applyZoom = function () {
    var z = this.zoom;
    this.world.setAttribute("transform", "translate(" + z.x + "," + z.y + ") scale(" + z.k + ")");
  };

  /** Hovering a dot keeps it, its neighbours and its "要先懂" lines lit; null clears. */
  View.prototype.hover = function (id) {
    if (this.drag && this.drag.moved) return;
    var near = {};
    if (id) {
      near[id] = true;
      this.links.concat(this.pre).forEach(function (l) {
        if (l.a === id) near[l.b] = true;
        if (l.b === id) near[l.a] = true;
      });
    }
    var self = this;
    Object.keys(this.nodeEls).forEach(function (n) { self.nodeEls[n].classList.toggle("kg-faded", !!id && !near[n]); });
    this.links.forEach(function (l, i) { self.linkEls[i].classList.toggle("kg-faded", !!id && l.a !== id && l.b !== id); });
    this.pre.forEach(function (l, i) { self.preEls[i].classList.toggle("kg-on", !!id && (l.a === id || l.b === id)); });
  };

  View.prototype.bindPointer = function () {
    var self = this, svg = this.svg;
    function toWorld(e) {
      var box = svg.getBoundingClientRect(), z = self.zoom;
      return { x: (e.clientX - box.left - z.x) / z.k, y: (e.clientY - box.top - z.y) / z.k };
    }
    svg.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      var g = e.target.closest(".kg-node");
      self.drag = { id: g && !g.classList.contains("kg-out") ? g.dataset.id : null, sx: e.clientX, sy: e.clientY,
                    zx: self.zoom.x, zy: self.zoom.y, moved: false, at: null };
    });
    svg.addEventListener("pointermove", function (e) {
      var d = self.drag;
      if (!d) return;
      if (!e.buttons) {  // released outside: no pointerup reached us
        self.drag = null;
        svg.classList.remove("kg-grabbing");
        return;
      }
      var dx = e.clientX - d.sx, dy = e.clientY - d.sy;
      if (!d.moved && Math.hypot(dx, dy) < 4) return;
      if (!d.moved) {  // capture only once it is a drag, so a plain click keeps the hover
        d.moved = true;
        self.hover(null);
        svg.setPointerCapture(e.pointerId);
        svg.classList.add("kg-grabbing");
      }
      if (d.id) {
        d.at = toWorld(e);
        self.kick();
      } else {
        self.zoom.x = d.zx + dx;
        self.zoom.y = d.zy + dy;
        self.applyZoom();
      }
    });
    function release() {
      var d = self.drag;
      self.drag = null;
      svg.classList.remove("kg-grabbing");
      if (d && !d.moved && d.id) self.clickNode(d.id);
      else if (d && d.id) self.kick();  // let the dragged dot spring back
    }
    svg.addEventListener("pointerup", release);
    svg.addEventListener("pointercancel", function () { self.drag = null; svg.classList.remove("kg-grabbing"); });
    svg.addEventListener("wheel", function (e) {
      e.preventDefault();
      var box = svg.getBoundingClientRect(), z = self.zoom, mx = e.clientX - box.left, my = e.clientY - box.top;
      var k = clamp(z.k * Math.exp(-e.deltaY * 0.0015), 0.3, 2.5);
      z.x = mx - (mx - z.x) * k / z.k;
      z.y = my - (my - z.y) * k / z.k;
      z.k = k;
      self.applyZoom();
    }, { passive: false });
  };

  View.prototype.clickNode = function (id) {
    var lvl = this.lvl[id], node = this.graph.nodes[id];
    if (lvl === -1) { this.leaf = null; this.go(id, id); return; }
    if (lvl === 0) { this.pick(null); return; }
    if (isLeaf(node)) { this.pick(id); return; }
    this.leaf = null;
    this.go(id, id);
  };

  View.prototype.up = function () {
    var parent = this.graph.nodes[this.center].parent;
    if (!parent) return;
    this.leaf = null;
    this.go(parent, parent);
  };

  /** Select a leaf on screen (null: back to the centre): highlight it, show its card, remember it. */
  View.prototype.pick = function (id) {
    var prev = this.leaf;
    this.leaf = id;
    if (prev && this.nodeEls[prev]) this.nodeEls[prev].classList.remove("kg-picked");
    if (id && this.nodeEls[id]) this.nodeEls[id].classList.add("kg-picked");
    this.markTree();
    this.showCard(id || this.center);
    storage("kg-focus", id || this.center);
  };

  /** Centre on id; a leaf centres on its parent (unless already on screen) and gets its card. */
  View.prototype.focus = function (id) {
    var node = this.graph.nodes[id];
    var leaf = isLeaf(node) && node.parent ? id : null;
    if (!this.ensureReady()) {  // pane still hidden: remember for the first draw
      this.leaf = leaf;
      this.center = leaf ? node.parent : id;
      return;
    }
    if (!leaf) { this.leaf = null; this.go(id, null); return; }
    if (!(this.lvl[id] > 0)) { this.leaf = null; this.go(node.parent, null); }
    this.pick(id);
  };

  /** Repaint one node after its status changed: dot, tree icon and the card if it shows the node. */
  View.prototype.refresh = function (id) {
    var node = this.graph.nodes[id];
    if (!node || !this.ready) return;
    if (this.nodeEls[id]) this.paintNode(this.nodeEls[id], node, this.lvl[id]);
    var icon = this.rows[id] && this.rows[id].querySelector(".kg-ic");
    if (icon) icon.outerHTML = iconSvg(node);
    if (this.cardId === id) this.showCard(id);
  };

  // ---- bar, card, tree ----

  View.prototype.drawBar = function () {
    var nodes = this.graph.nodes, chain = [];
    for (var id = this.center; id; id = nodes[id].parent) chain.unshift(id);
    this.bar.querySelector(".kg-back").disabled = chain.length < 2;
    var crumb = this.bar.querySelector(".kg-crumb");
    for (var drop = 0; drop < chain.length; drop++) {  // keep the last levels; the oldest go behind "…"
      crumb.innerHTML = (drop ? '<span class="kg-more">…</span><span class="sep">›</span>' : "")
        + chain.slice(drop).map(function (id, i, shown) {
          var name = esc(shortName(nodes[id].name));
          return i === shown.length - 1 ? "<b>" + name + "</b>"
            : '<a href="#" data-id="' + esc(id) + '">' + name + "</a>";
        }).join('<span class="sep">›</span>');
      if (crumb.scrollWidth <= crumb.clientWidth || drop === chain.length - 1) break;
    }
  };

  /** The card under the graph: name, status, mastery count, measures, summary, prereqs, "开始读 →". */
  View.prototype.showCard = function (id) {
    var node = id && this.graph.nodes[id];
    this.cardId = node && node.kind !== "project" ? id : null;
    if (!this.cardId) {
      this.card.classList.remove("show");
      this.card.innerHTML = '<span class="kg-card-hint">点一个点，这里显示它的说明和「开始读 →」</span>';
      return;
    }
    var html = '<button class="kg-card-x" type="button" aria-label="关闭">×</button>'
      + '<div class="kg-card-head">' + iconSvg(node, 14) + "<b>" + esc(node.name) + "</b>"
      + '<span class="chip ' + (STATUS_CHIP[node.status] || "idle") + '">' + esc(node.status) + "</span>"
      + (node.edit ? statusSlot(node) : "") + "</div>";
    if (node.children.length && node.units)  // a rollup: groups, blocks, notes with points
      html += '<div class="kg-card-line">已掌握 ' + node.mastered + " / " + node.units + "</div>";
    if (node.measures && node.measures.length)
      html += '<div class="kg-card-line">📊 衡量：' + esc(node.measures.join("、")) + "</div>";
    if (node.summary) html += '<p class="kg-card-sum">' + esc(plain(node.summary)) + "</p>";
    var prereqs = (node.prereqs || []).map(function (target) {
      var found = nodeOf(target);
      return found ? '<a href="#" data-focus="' + esc(target) + '">' + esc(shortName(found.node.name)) + "</a>" : "";
    }).filter(Boolean);
    if (prereqs.length) html += '<div class="kg-card-line">要先懂：' + prereqs.join("、") + "</div>";
    if (node.doc)
      html += '<a class="kg-read" href="#doc-' + esc(node.doc) + '" data-node="' + esc(id) + '" data-anchor="'
        + esc(node.anchor || "") + '">开始读 →</a>';
    this.card.innerHTML = html;
    this.card.classList.add("show");
  };

  /** Status buttons of a node's line. On a block or group they set its own note's status ("本篇"), not the
   *  rollup shown by its dot and chip. */
  function statusSlot(node) {
    return (node.children.length ? '<span class="kg-card-own">本篇：</span>' : "")
      + '<span class="status-buttons" data-node="' + esc(node.id) + '"></span>';
  }

  View.prototype.cardClick = function (e) {
    if (e.target.closest(".kg-card-x")) {
      this.showCard(null);
      return;
    }
    var jump = e.target.closest("[data-focus]");
    if (jump) {
      e.preventDefault();
      focus(jump.dataset.focus);
      return;
    }
    var read = e.target.closest(".kg-read");
    if (read) {  // the hash link navigates; remember where to scroll and where to come back to
      storage("kg-anchor", read.dataset.anchor || null);
      storage("kg-node", read.dataset.node);  // the reading page draws its crumb for this node
      storage("kg-focus", read.dataset.node);
    }
  };

  View.prototype.buildTree = function () {
    var self = this, nodes = this.graph.nodes;
    function item(id) {
      var node = nodes[id], kids = node.children;
      var measures = node.measures && node.measures.length
        ? ' <span class="kg-measure">📊 ' + esc(node.measures.join(", ")) + "</span>" : "";
      return '<li class="' + (kids.length ? "kg-has closed" : "") + '"><div class="kg-row" data-id="' + esc(id) + '">'
        + '<span class="kg-tw"></span>' + iconSvg(node) + '<span class="kg-name">' + esc(node.name) + measures
        + "</span></div>" + (kids.length ? "<ul>" + kids.map(item).join("") + "</ul>" : "") + "</li>";
    }
    this.tree.innerHTML = "<ul>" + item(this.graph.root) + "</ul>";
    this.tree.querySelectorAll(".kg-row").forEach(function (row) { self.rows[row.dataset.id] = row; });
    this.tree.addEventListener("click", function (e) {
      var row = e.target.closest(".kg-row");
      if (!row) return;
      var li = row.parentNode;
      if (e.target.closest(".kg-tw") && li.classList.contains("kg-has")) {
        li.classList.toggle("closed");
        return;
      }
      self.focus(row.dataset.id);
    });
  };

  /** Open the tree down to the selected item, highlight it and its ancestors, scroll it into view. */
  View.prototype.markTree = function () {
    var nodes = this.graph.nodes, selected = this.leaf || this.center, rows = this.rows;
    this.tree.querySelectorAll(".kg-row.on,.kg-row.anc").forEach(function (row) { row.classList.remove("on", "anc"); });
    for (var id = nodes[selected].parent; id; id = nodes[id].parent) {
      rows[id].classList.add("anc");
      rows[id].parentNode.classList.remove("closed");
    }
    rows[this.center].parentNode.classList.remove("closed");
    var row = rows[selected], box = this.tree.getBoundingClientRect(), at = row.getBoundingClientRect();
    row.classList.add("on");
    if (at.top < box.top || at.bottom > box.bottom)
      this.tree.scrollTop += at.top - box.top - this.tree.clientHeight / 3;
  };

  // ---- page wiring ----

  function graphData() {
    if (!data) {
      var el = document.getElementById("kg-data");
      data = el ? JSON.parse(el.textContent) : { graphs: {} };
      if (typeof Status !== "undefined") Status.overlayData(data);  // status changed on this page since it was built
    }
    return data;
  }

  /** {graph, node, view} of a node id in any graph (projects or 概念), or null. */
  function nodeOf(id) {
    var graphs = graphData().graphs;
    for (var name in graphs) {
      if (graphs[name].nodes && graphs[name].nodes[id]) {
        return { graph: graphs[name], node: graphs[name].nodes[id], view: viewOf(name) };
      }
    }
    return null;
  }

  function viewOf(name) {
    for (var i = 0; i < views.length; i++) if (views[i].name === name) return views[i];
    return null;
  }

  /** Show node id in its project's graph (switching the project pane). False if no graph has it. */
  function focus(id) {
    var found = nodeOf(id);
    if (!found || !found.view) return false;
    var pane = found.view.el.closest(".proj-pane");
    if (pane && !pane.classList.contains("show") && typeof pickProject === "function") pickProject(found.view.name);
    found.view.focus(id);
    return true;
  }

  function refresh(id) {
    views.forEach(function (v) { v.refresh(id); });
  }

  function restoreFocus() {
    var id = storage("kg-focus");
    if (id) focus(id);
  }

  function activeView() {
    for (var i = 0; i < views.length; i++) if (views[i].ready && views[i].visible()) return views[i];
    return null;
  }

  function mount() {
    var graphs = graphData().graphs;
    document.querySelectorAll(".kg[data-graph]").forEach(function (el, i) {
      var graph = graphs[el.dataset.graph];
      if (graph && graph.nodes && graph.nodes[graph.root]) views.push(new View(el, graph, i));
    });
    if (typeof ResizeObserver !== "undefined") {
      var watcher = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          views.forEach(function (v) { if (v.svg === entry.target) v.resized(); });
        });
      });
      views.forEach(function (v) { watcher.observe(v.svg); });
    }
    document.addEventListener("click", function (e) {
      var card = e.target.closest("[data-block]");
      if (!card) return;
      e.preventDefault();
      if (focus(card.dataset.block)) {
        var kg = nodeOf(card.dataset.block).view.el;
        kg.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || (e.target.closest && e.target.closest("input,textarea,select"))) return;
      var overlay = document.getElementById("overlay"), peek = document.getElementById("peek");
      if ((overlay && overlay.classList.contains("show")) || (peek && !peek.hidden)) return;  // Esc closes those
      var view = activeView();
      if (view) view.up();
    });
    document.querySelectorAll(".proj-tab").forEach(function (tab) {  // runs after the page's pickProject
      tab.addEventListener("click", function () {
        var view = viewOf(tab.dataset.project);
        if (view && view.ensureReady()) storage("kg-focus", view.leaf || view.center);
      });
    });
    window.addEventListener("hashchange", function (e) {  // back from a reading page: same place again
      var from = "", to = "";
      try {
        from = decodeURIComponent((e.oldURL || "").split("#")[1] || "");
        to = decodeURIComponent(location.hash.slice(1)) || "项目";
      } catch (err) {
        return;  // a malformed hash typed by hand: nothing to restore
      }
      if (to === "项目" && from.indexOf("doc-") === 0) restoreFocus();
    });
    restoreFocus();
    views.forEach(function (v) { v.ensureReady(); });
  }

  if (typeof document !== "undefined" && document.getElementById("kg-data")) mount();

  return {
    RADIUS: RADIUS, PAD: PAD, REST_SPEED: REST_SPEED, LAYOUT_MIN: LAYOUT_MIN, HUES: HUES, visibleWindow: visibleWindow, targets: targets, step: step, preLinks: preLinks,
    neighborhood: neighborhood, hueOf: hueOf, shortName: shortName, plain: plain, iconSvg: iconSvg, isLeaf: isLeaf,
    shapeMarkup: shapeMarkup, esc: esc, storage: storage, STATUS_CHIP: STATUS_CHIP,
    nodeOf: nodeOf, focus: focus, data: graphData, mount: mount, views: views, refresh: refresh,
  };
})();
if (typeof module !== "undefined") module.exports = KG;
