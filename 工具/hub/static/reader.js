// Reading page: crumb, status chip, mini graph, point list, toc that follows the scroll, hover cards,
// the peek panel, and coming back to the same scroll position. Pure helpers are exported for tests.
var Reader = (function () {
  "use strict";

  var K = typeof KG !== "undefined" ? KG : require("./graph.js");
  var SHAPES = { "已掌握": "full", "学习中": "half", "空白": "dashed" };  // anything else is an empty circle
  var KIND_LABEL = { point: "知识点", concept: "概念", term: "术语", note: "笔记", topic: "主题", doc: "附页" };
  var HOVER_DELAY = 300;
  var SCROLL_KEY = "kg-scroll";
  var TOC_LINE = 0.3;  // the current section is the last one whose heading is above 30% of the window
  var FLASH_MS = 2000;  // how long the place naming a point stays lit
  var SECTION_BLOCK = "p,li,tr,h3,h4,h5,h6";
  var NESTED_BLOCK = "p,ul,ol,li,table,blockquote,pre";
  // mini graph: at most `max` dots per side column, `row` apart; the parent sits on top
  var MINI = { width: 240, max: 4, row: 46, top: 18, firstRow: 62, side: 42, r: 7, selfR: 10 };
  var MINI_LABEL = { self: 6, prereq: 5, next: 5, parent: 12 };  // characters before "…"

  // ---- pure helpers ----

  /** {graph, node} of a node id in any graph of the page data, or null. */
  function findNode(data, id) {
    var graphs = data.graphs || {};
    for (var name in graphs) {
      var nodes = graphs[name].nodes;
      if (nodes && Object.prototype.hasOwnProperty.call(nodes, id)) return { graph: graphs[name], node: nodes[id] };
    }
    return null;
  }

  /** Levels from the graph root down to nodeId: [{id, name (short), doc}]; [] if the id is unknown. */
  function crumbPath(graph, nodeId) {
    var nodes = graph.nodes, chain = [];
    for (var id = nodeId; id && Object.prototype.hasOwnProperty.call(nodes, id); id = nodes[id].parent)
      chain.unshift({ id: id, name: K.shortName(nodes[id].name), doc: nodes[id].doc || null });
    return chain;
  }

  /** Which of the nodes showing a doc (ids, from data-nodes) the page is drawn for: the one the reader came
   *  from (a point stands for the node it hangs under), else the first one showing the whole doc, else the
   *  first one; null when none is known. */
  function chooseNode(data, ids, wanted) {
    var known = (ids || []).filter(function (id) { return !!findNode(data, id); });
    var found = wanted ? findNode(data, wanted) : null;
    if (found && found.node.kind === "point") wanted = found.node.parent;
    if (wanted && known.indexOf(wanted) >= 0) return wanted;
    var whole = known.filter(function (id) { return !findNode(data, id).node.anchor; });
    return whole[0] || known[0] || null;
  }

  /** The other places a doc hangs in the graphs: [{id, names}], names from the root down. */
  function alsoMounts(data, ids, currentId) {
    return (ids || []).filter(function (id) { return id !== currentId; }).map(function (id) {
      var found = findNode(data, id);
      return found ? { id: id, names: crumbPath(found.graph, id).map(function (level) { return level.name; }) } : null;
    }).filter(Boolean);
  }

  /** The words that name a point on the page: its name and aliases. */
  function pointLabels(node) {
    return [node.name].concat(node.aliases || []).filter(function (word) { return String(word).trim(); });
  }

  function squash(text) {
    return String(text).replace(/\s+/g, "").toLowerCase();
  }

  /** Index of the first text naming any of labels (case and spaces ignored), or -1. */
  function firstMention(texts, labels) {
    var words = labels.map(squash).filter(Boolean);
    for (var i = 0; i < texts.length; i++) {
      var text = squash(texts[i]);
      if (words.some(function (word) { return text.indexOf(word) >= 0; })) return i;
    }
    return -1;
  }

  function rememberScroll(store, hash, y) {
    store[hash] = Math.max(0, Math.round(y));
  }

  /** Last remembered scroll position of a page, or null if there is none. */
  function recallScroll(store, hash) {
    var y = Object.prototype.hasOwnProperty.call(store, hash) ? store[hash] : null;
    return typeof y === "number" && isFinite(y) ? y : null;
  }

  function shapeOf(status) {
    return SHAPES[status] || "empty";
  }

  function pointNodes(nodes, node) {
    return (node.children || []).map(function (id) { return nodes[id]; })
      .filter(function (child) { return child && child.kind === "point"; });
  }

  /** [{id, name}] of the ids that resolve to a node; unknown ids are dropped. */
  function refList(data, ids) {
    return (ids || []).map(function (id) {
      var found = findNode(data, id);
      return found ? { id: id, name: K.shortName(found.node.name) } : null;
    }).filter(Boolean);
  }

  /** The title a doc is listed under in the search entries (notes and concept cards), or "". */
  function docTitle(data, doc) {
    var href = "#doc-" + doc, entries = data.search || [];
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].href === href && (entries[i].k === "note" || entries[i].k === "concept")) return entries[i].t;
    }
    return "";
  }

  function bareModel(kind, title) {
    return { kind: kind, node: null, block: -1, title: title, status: "", shape: null, summary: "", source: "",
             prereqs: [], confusions: [], points: [], open: null, anchor: "", go: "" };
  }

  /** Peek of a graph node. Its summary is plain text in the data and comes back escaped. */
  function nodeModel(data, id) {
    var found = findNode(data, id), node = found.node, isPoint = node.kind === "point";
    var kind = isPoint ? "point" : node.kind === "concept" ? "concept" : node.doc ? "note" : "topic";
    var status = isPoint ? node.status : node.doc_status || node.status || "";
    var model = bareModel(kind, kind === "note" ? docTitle(data, node.doc) || node.name : node.name);
    model.node = id;
    model.block = node.block;
    model.status = status;
    model.shape = shapeOf(status);
    model.summary = node.summary ? K.esc(K.plain(node.summary)) : "";
    model.prereqs = refList(data, node.prereqs);
    model.confusions = refList(data, node.confusions);
    model.points = isPoint ? [] : pointNodes(found.graph.nodes, node).map(function (p) {
      return { id: p.id, name: p.name, status: p.status, shape: p.shape, block: p.block, anchor: p.anchor || "" };
    });
    model.open = node.doc ? "#doc-" + node.doc : null;
    model.anchor = node.anchor || "";  // a point's section, or the section a skeleton node shows
    model.go = id;
    return model;
  }

  /** What the peek panel shows. target: {term: id} | {doc: id, title?} | {node: id}; null if unknown.
   *  summary and source are HTML: escaped text for points and concepts, rendered HTML for glossary terms. */
  function peekModel(data, target) {
    if (target.term) {
      var term = (data.terms || {})[target.term];
      if (!term) return null;
      if (term.node && findNode(data, term.node)) return nodeModel(data, term.node);
      // only glossary terms carry rendered HTML; the rest is plain text, by kind not by node lookup
      var html = term.kind === "term", model = bareModel(KIND_LABEL[term.kind] ? term.kind : "term", term.name);
      model.summary = html ? term.summary || "" : K.esc(K.plain(term.summary || ""));
      model.source = html ? term.source || "" : K.esc(term.source || "");
      return model;
    }
    if (target.doc) {
      var ids = (data.docNodes || {})[target.doc] || [];
      var doc = ids.length && findNode(data, ids[0]) ? nodeModel(data, ids[0]) : bareModel("doc", "");
      doc.title = docTitle(data, target.doc) || target.title || doc.title;
      doc.open = "#doc-" + target.doc;
      doc.anchor = "";
      doc.go = "";  // a link to the doc, not to one of its nodes: the reading page picks the node
      return doc;
    }
    if (target.node) return findNode(data, target.node) ? nodeModel(data, target.node) : null;
    return null;
  }

  /** Positions for the mini graph: parent on top, prereqs in the left column, what comes next in the
   *  right one, this page in the middle. Long columns are cut at MINI.max (more = how many were cut). */
  function miniLayout(hood, width) {
    var left = hood.prereqs.slice(0, MINI.max), right = hood.next.slice(0, MINI.max);
    var rows = Math.max(left.length, right.length, 1), first = hood.parent ? MINI.firstRow : MINI.top + MINI.selfR;
    var cx = width / 2, dots = [];
    function column(ids, role, x) {
      var offset = (rows - ids.length) * MINI.row / 2;
      ids.forEach(function (id, i) { dots.push({ id: id, role: role, x: x, y: first + offset + i * MINI.row }); });
    }
    if (hood.parent) dots.push({ id: hood.parent, role: "parent", x: cx, y: MINI.top });
    dots.push({ id: hood.self, role: "self", x: cx, y: first + (rows - 1) * MINI.row / 2 });
    column(left, "prereq", MINI.side);
    column(right, "next", width - MINI.side);
    return { width: width, height: first + (rows - 1) * MINI.row + 30, dots: dots,
             more: { prereq: hood.prereqs.length - left.length, next: hood.next.length - right.length } };
  }

  function chip(status) {
    if (!status) return "";
    return '<span class="chip ' + (K.STATUS_CHIP[status] || "idle") + '">' + K.esc(status) + "</span>";
  }

  /** Where Task 10's status buttons mount for one node. */
  function slot(nodeId) {
    return '<span class="status-buttons" data-node="' + K.esc(nodeId) + '"></span>';
  }

  function peekRefs(items) {
    return items.map(function (item) {
      return '<a href="#" data-peek-node="' + K.esc(item.id) + '">' + K.esc(item.name) + "</a>";
    }).join("、");
  }

  function peekLine(label, html) {
    return '<div class="peek-line"><span class="peek-label">' + label + "</span>" + html + "</div>";
  }

  /** Markup of the peek panel for a model from peekModel. */
  function peekHtml(m) {
    var icon = m.shape ? K.iconSvg({ block: m.block, shape: m.shape }, 14) : "";
    var html = '<button class="peek-x" type="button" aria-label="关闭">✕</button>'
      + '<div class="peek-kind">' + KIND_LABEL[m.kind] + "</div>"
      + '<h3 class="peek-title">' + icon + "<span>" + K.esc(m.title) + "</span></h3>";
    if (m.status) html += '<div class="peek-status">' + chip(m.status) + (m.kind === "point" ? slot(m.node) : "") + "</div>";
    if (m.summary) html += '<p class="peek-sum">' + m.summary + "</p>";
    if (m.source) html += peekLine("出处", m.source);
    if (m.prereqs.length) html += peekLine("要先懂", peekRefs(m.prereqs));
    if (m.confusions.length) html += peekLine("容易混淆", peekRefs(m.confusions));
    if (m.points.length) {
      html += '<div class="peek-label peek-points-title">本篇知识点</div><ul class="peek-points">'
        + m.points.map(function (p) {
          return "<li>" + K.iconSvg(p, 12) + '<a href="#" data-peek-node="' + K.esc(p.id) + '">' + K.esc(p.name) + "</a></li>";
        }).join("") + "</ul>";
    }
    if (m.open)
      html += '<a class="peek-open" href="' + K.esc(m.open) + '" data-anchor="' + K.esc(m.anchor) + '" data-node="'
        + K.esc(m.go || "") + '">打开全文 →</a>';
    return html;
  }

  // ---- the page ----

  var data = null, store = {}, current = "", peek = null, peekTarget = null, tip = null, tipFor = null, tipTimer = 0;
  var toc = null;

  function loadStore() {
    try {
      var saved = JSON.parse(K.storage(SCROLL_KEY) || "{}");
      return saved && typeof saved === "object" ? saved : {};
    } catch (e) {
      return {};
    }
  }

  function saveStore() {
    K.storage(SCROLL_KEY, JSON.stringify(store));
  }

  function mountIds(article) {
    return (article.dataset.nodes || "").split(",").filter(Boolean);
  }

  /** The node this reading page is drawn for (set on arrival by show()). */
  function nodeOf(article) {
    var id = article && article.dataset.node;
    return id ? findNode(data, id) : null;
  }

  /** Called by the page's show() after it switched pages: draw the reading page for the node the reader
   *  came from, then scroll to the section "开始读" asked for (lighting up where a point is named), else to
   *  where this page was left, else to the top. Positions are recorded while scrolling (onScroll), so
   *  leaving a page needs no extra step. */
  function arrive() {
    if (!data) { window.scrollTo(0, 0); return; }
    closePeek();
    hideTip();
    saveStore();
    var article = document.querySelector("article.doc.show");
    current = article ? article.id : "";
    watchToc(article);
    var wanted = K.storage("kg-node"), anchor = K.storage("kg-anchor");
    K.storage("kg-node", null);
    K.storage("kg-anchor", null);
    if (!article) { window.scrollTo(0, 0); return; }
    setup(article);
    show(article, wanted);
    var found = nodeOf(article);
    if (!anchor && wanted && found && found.node.id === wanted) anchor = found.node.anchor;
    var target = anchor && document.getElementById(anchor);
    if (target && article.contains(target)) {
      goSection(target, wanted, false);
    } else {
      var y = recallScroll(store, current) || 0, id = current;
      window.scrollTo(0, y);
      requestAnimationFrame(function () {  // late layout (images) may have clamped the first try
        if (current === id && Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
      });
    }
    markToc();
  }

  /** What every reading page gets once: the button that opens the side column on narrow screens. */
  function setup(article) {
    if (article.dataset.ready) return;
    article.dataset.ready = "1";
    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "side-toggle";
    toggle.textContent = "本页";
    article.querySelector(".doc-top").appendChild(toggle);
  }

  /** Draw crumb, "也挂在", status, mini graph and point list for the node chosen from wanted. */
  function show(article, wanted) {
    var id = chooseNode(data, mountIds(article), wanted);
    if (id) article.dataset.node = id; else delete article.dataset.node;
    var found = nodeOf(article);
    if (!found) return;
    renderCrumb(article, found);
    renderStatus(article, found);
    renderMini(article, found);
    renderPoints(article, found);
  }

  function crumbLinks(path, boldLast) {
    return path.map(function (level, i) {
      var name = K.esc(level.name);
      return '<a href="#项目" data-focus-id="' + K.esc(level.id) + '" title="在图谱里看">'
        + (boldLast && i === path.length - 1 ? "<b>" + name + "</b>" : name) + "</a>";
    }).join('<span class="sep">›</span>');
  }

  function renderCrumb(article, found) {
    article.querySelector(".crumb").innerHTML = crumbLinks(crumbPath(found.graph, found.node.id), true);
    var also = article.querySelector(".crumb-also");
    if (!also) return;
    var others = alsoMounts(data, mountIds(article), found.node.id);
    also.innerHTML = others.length ? "也挂在：" + others.map(function (other) {
      var path = crumbPath(findNode(data, other.id).graph, other.id);
      return '<span class="also-path">' + crumbLinks(path, false) + "</span>";
    }).join("；") : "";
  }

  function renderStatus(article, found) {
    var node = found.node, status = node.doc_status || node.status || "";
    var points = pointNodes(found.graph.nodes, node);
    var mastered = points.filter(function (p) { return p.status === "已掌握"; }).length;
    article.querySelector(".doc-status").innerHTML = chip(status)
      + (points.length ? '<span class="doc-mastery">已掌握 ' + mastered + " / " + points.length + " 个知识点</span>" : "")
      + slot(node.id);
  }

  function renderPoints(article, found) {
    var points = pointNodes(found.graph.nodes, found.node);
    if (!points.length) return;
    article.querySelector(".side-points").innerHTML = '<div class="side-title">本篇知识点</div>'
      + points.map(function (p) {
        return '<div class="side-point">' + K.iconSvg(p, 12) + '<a href="#" class="side-point-name" data-point="'
          + K.esc(p.id) + '" data-anchor="' + K.esc(p.anchor || "") + '">' + K.esc(p.name) + "</a>" + slot(p.id) + "</div>";
      }).join("");
  }

  function clip(text, max) {
    return text.length > max ? text.slice(0, max) + "…" : text;
  }

  function miniLine(a, b, cls, marker) {
    var ra = a.role === "self" ? MINI.selfR : MINI.r, rb = (b.role === "self" ? MINI.selfR : MINI.r) + 3;
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    return '<line class="' + cls + '" x1="' + (a.x + dx / len * ra).toFixed(1) + '" y1="' + (a.y + dy / len * ra).toFixed(1)
      + '" x2="' + (b.x - dx / len * rb).toFixed(1) + '" y2="' + (b.y - dy / len * rb).toFixed(1) + '"'
      + (marker ? ' marker-end="url(#' + marker + ')"' : "") + "/>";
  }

  function miniDot(d) {
    var node = findNode(data, d.id).node, r = d.role === "self" ? MINI.selfR : MINI.r;
    var name = K.esc(clip(K.shortName(node.name), MINI_LABEL[d.role]));
    var label = d.role === "parent"
      ? '<text class="mini-lbl" x="' + (r + 5) + '" dy="4" text-anchor="start">↩ ' + name + "</text>"
      : '<text class="mini-lbl" dy="' + (r + 13) + '">' + name + "</text>";
    return '<g class="mini-dot mini-' + d.role + '"' + (d.role === "self" ? "" : ' data-id="' + K.esc(d.id) + '"')
      + ' transform="translate(' + d.x + "," + d.y + ')" style="--h:' + K.hueOf(node) + '"><title>' + K.esc(node.name)
      + "</title>" + K.shapeMarkup(node.shape, r, d.role === "self" ? 2.4 : 1.8) + label + "</g>";
  }

  /** This page, what to understand first, what to read next and the level above, drawn small. */
  function renderMini(article, found) {
    var hood = K.neighborhood(found.graph, found.node.id);
    function known(id) { return !!findNode(data, id); }
    hood.prereqs = hood.prereqs.filter(known);
    hood.next = hood.next.filter(known);
    if (hood.parent && !known(hood.parent)) hood.parent = null;
    if (!hood.parent && !hood.prereqs.length && !hood.next.length) return;
    var lay = miniLayout(hood, MINI.width), marker = "mini-ar-" + article.id, self = lay.dots[hood.parent ? 1 : 0];
    var lines = lay.dots.map(function (d) {
      if (d.role === "parent") return miniLine(d, self, "mini-up", "");
      if (d.role === "prereq") return miniLine(d, self, "mini-pre", marker);
      return d.role === "next" ? miniLine(self, d, "mini-pre", marker) : "";
    }).join("");
    var more = [];
    if (lay.more.prereq) more.push("要先懂还有 " + lay.more.prereq + " 个");
    if (lay.more.next) more.push("接着读还有 " + lay.more.next + " 个");
    article.querySelector(".mini").innerHTML = '<div class="side-title">在图谱里</div>'
      + '<svg class="mini-svg" viewBox="0 0 ' + lay.width + " " + lay.height + '" width="' + lay.width + '" height="'
      + lay.height + '"><defs><marker id="' + marker + '" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="6" '
      + 'markerHeight="6" orient="auto"><path d="M0,0L8,4L0,8" class="kg-arrow"/></marker></defs>'
      + lines + lay.dots.map(miniDot).join("") + "</svg>"
      + '<div class="mini-legend">左：要先懂　右：读完接着读' + (more.length ? "（" + more.join("，") + "）" : "") + "</div>";
  }

  /** Go where a mini graph dot points: its doc (at its section, if it has one), else the graph centred on it. */
  function goNode(id) {
    var found = findNode(data, id);
    if (!found) return;
    var node = found.node;
    if (node.doc) {
      openDoc("#doc-" + node.doc, node.anchor || "", id);
    } else {
      K.storage("kg-focus", id);
      location.hash = "#项目";
    }
  }

  /** Navigate to a doc, drawn for nodeId, and scroll to anchor on arrival; on the doc already shown, redraw
   *  for nodeId if it is one of the doc's nodes, then just scroll. */
  function openDoc(href, anchor, nodeId) {
    if (href === "#" + current) {
      var article = document.getElementById(current);
      if (nodeId && article) show(article, nodeId);
      var target = anchor && document.getElementById(anchor);
      if (target) goSection(target, nodeId, true);
      return;
    }
    K.storage("kg-anchor", anchor || null);
    K.storage("kg-node", nodeId || null);
    location.hash = href;
  }

  function scrollToId(id, smooth) {
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  }

  /** Scroll a section heading to the top; when pointId is a point, light up the first paragraph, list item
   *  or table row of the section that names it (kept in view), else the heading if only it names it. */
  function goSection(heading, pointId, smooth) {
    heading.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    var found = pointId ? findNode(data, pointId) : null;
    if (!found || found.node.kind !== "point") return;
    var blocks = sectionBlocks(heading), labels = pointLabels(found.node);
    var at = firstMention(blocks.map(ownText), labels);
    var el = at >= 0 ? blocks[at] : firstMention([heading.textContent], labels) === 0 ? heading : null;
    if (!el) return;
    if (el !== heading && el.getBoundingClientRect().bottom > window.innerHeight)
      el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "center" });
    el.classList.remove("point-flash");
    void el.offsetWidth;
    el.classList.add("point-flash");
    setTimeout(function () { el.classList.remove("point-flash"); }, FLASH_MS);
  }

  /** Paragraphs, list items, table rows and lower headings between a heading and the next heading of the
   *  same or a higher level, in page order. */
  function sectionBlocks(heading) {
    var level = Number(heading.tagName.slice(1)), blocks = [];
    for (var el = heading.nextElementSibling; el; el = el.nextElementSibling) {
      var tag = /^H([1-6])$/.exec(el.tagName);
      if (tag && Number(tag[1]) <= level) break;
      if (el.matches(SECTION_BLOCK)) blocks.push(el);
      blocks.push.apply(blocks, [].slice.call(el.querySelectorAll(SECTION_BLOCK)));
    }
    return blocks;
  }

  /** Text of a block without the blocks nested inside it (a list item's sub-list is its own block). */
  function ownText(el) {
    return [].filter.call(el.childNodes, function (node) {
      return node.nodeType === 3 || !(node.matches && node.matches(NESTED_BLOCK));
    }).map(function (node) { return node.textContent; }).join("");
  }

  /** Redraw what shows statuses (top chip, point list, mini graph, open peek) after a status changed. */
  function refresh() {
    document.querySelectorAll("article.doc[data-ready]").forEach(function (article) {
      var found = nodeOf(article);
      if (!found) return;
      renderStatus(article, found);
      renderPoints(article, found);
      renderMini(article, found);
    });
    if (peek && !peek.hidden && peekTarget) {
      var top = peek.scrollTop;
      openPeek(peekTarget);
      peek.scrollTop = top;
    }
  }

  // ---- toc that follows the scroll ----

  /** The shown article's toc links and the headings they point to (null when no reading page is shown). */
  function watchToc(article) {
    toc = null;
    if (!article) return;
    var links = [].slice.call(article.querySelectorAll(".side-toc a[data-toc]"));
    var heads = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
    toc = { links: links, heads: heads, frame: 0 };
  }

  /** Highlight the last heading above TOC_LINE; at the very bottom of the page, the last one. */
  function markToc() {
    if (!toc || !toc.links.length) return;
    var line = window.innerHeight * TOC_LINE, on = 0, root = document.documentElement;
    toc.heads.forEach(function (h, i) { if (h && h.getBoundingClientRect().top < line) on = i; });
    if (window.scrollY + window.innerHeight >= root.scrollHeight - 2) on = toc.links.length - 1;
    toc.links.forEach(function (a, i) { a.classList.toggle("on", i === on); });
  }

  function markTocSoon() {
    if (!toc || toc.frame) return;
    var shown = toc;
    shown.frame = requestAnimationFrame(function () {
      shown.frame = 0;
      if (toc === shown) markToc();
    });
  }

  // ---- peek panel and hover card ----

  function openPeek(target) {
    var model = peekModel(data, target);
    if (!model || !peek) return;
    peekTarget = target;
    peek.innerHTML = peekHtml(model);
    peek.hidden = false;
    peek.scrollTop = 0;
  }

  function closePeek() {
    if (peek) peek.hidden = true;
  }

  function showTip(term) {
    var model = peekModel(data, { term: term.dataset.term });
    if (!model) return;
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "term-tip";
      document.body.appendChild(tip);
    }
    tip.innerHTML = '<div class="tip-head"><b>' + K.esc(model.title) + "</b>" + (model.status ? chip(model.status) : "") + "</div>"
      + (model.summary ? '<div class="tip-sum">' + model.summary + "</div>" : '<div class="tip-sum muted">还没写一句话说明</div>')
      + (model.source ? '<div class="tip-src">出处：' + model.source + "</div>" : "")
      + '<div class="tip-hint">点一下在右侧打开</div>';
    tip.hidden = false;
    var box = term.getBoundingClientRect(), width = tip.offsetWidth, height = tip.offsetHeight;
    var left = Math.max(8, Math.min(box.left, window.innerWidth - width - 8));
    var top = box.bottom + 6 + height > window.innerHeight ? box.top - height - 6 : box.bottom + 6;
    tip.style.left = left + "px";
    tip.style.top = Math.max(8, top) + "px";
  }

  function hideTip() {
    clearTimeout(tipTimer);
    tipFor = null;
    if (tip) tip.hidden = true;
  }

  function onOver(e) {
    var term = e.target.closest && e.target.closest(".doc-body .term[data-term]");
    if (!term || term === tipFor) return;
    hideTip();
    tipFor = term;
    tipTimer = setTimeout(function () { showTip(term); }, HOVER_DELAY);
  }

  function onOut(e) {
    var term = e.target.closest && e.target.closest(".term[data-term]");
    if (term && !term.contains(e.relatedTarget)) hideTip();
  }

  // ---- clicks, keys, scroll ----

  function onClick(e) {
    var t = e.target, el;
    if (!t.closest) return;
    if (t.closest("#peek")) { peekClick(e, t); return; }
    if ((el = t.closest(".back-graph"))) {  // #项目 (attachments: #成果); the graph then shows this page's node
      var found = nodeOf(el.closest("article.doc"));
      if (found) K.storage("kg-focus", found.node.id);
      return;
    }
    if ((el = t.closest(".crumb a[data-focus-id], .crumb-also a[data-focus-id]"))) { K.storage("kg-focus", el.dataset.focusId); return; }
    if ((el = t.closest(".side-toggle"))) { el.closest("article.doc").querySelector(".doc-side").classList.toggle("open"); return; }
    if ((el = t.closest("[data-toc]"))) {  // no hash change: show() would take the heading id for a section
      e.preventDefault();
      closeSide(el);
      scrollToId(el.getAttribute("href").slice(1), true);
      return;
    }
    if ((el = t.closest(".side-point-name"))) {
      e.preventDefault();
      closeSide(el);
      var heading = el.dataset.anchor && document.getElementById(el.dataset.anchor);
      if (heading) goSection(heading, el.dataset.point, true);
      else openPeek({ node: el.dataset.point });
      return;
    }
    if ((el = t.closest(".mini-dot[data-id]"))) { goNode(el.dataset.id); return; }
    if (!t.closest(".doc-body")) return;
    if ((el = t.closest(".term[data-term]"))) {
      e.preventDefault();
      hideTip();
      openPeek({ term: el.dataset.term });
      return;
    }
    el = t.closest("a[href]");
    var match = el && !modified(e) && /^#(doc-[^#]+)$/.exec(el.getAttribute("href"));
    var article = match && document.getElementById(match[1]);
    if (article && article.matches("article.doc")) {  // other docs open in the peek; sections and files as before
      e.preventDefault();
      var h1 = article.querySelector(".doc-body h1");
      openPeek({ doc: match[1].slice(4), title: h1 ? h1.textContent : "" });
    }
  }

  /** Ctrl/Cmd/Shift or a non-primary button: the browser's own link handling (new tab, window). */
  function modified(e) {
    return e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0;
  }

  function closeSide(el) {
    var side = el.closest(".doc-side");
    if (side) side.classList.remove("open");
  }

  function peekClick(e, t) {
    var el;
    if (t.closest(".peek-x")) { closePeek(); return; }
    if ((el = t.closest("[data-peek-node]"))) { e.preventDefault(); openPeek({ node: el.dataset.peekNode }); return; }
    if ((el = t.closest(".peek-open")) && !modified(e)) {
      e.preventDefault();
      closePeek();
      openDoc(el.getAttribute("href"), el.dataset.anchor, el.dataset.node);
    }
  }

  function onKey(e) {
    if (e.key !== "Escape") return;
    hideTip();
    var overlay = document.getElementById("overlay");
    if (overlay && overlay.classList.contains("show")) return;  // Esc belongs to the enlarged image
    if (peek && !peek.hidden) { closePeek(); return; }
    var side = document.querySelector("article.doc.show .doc-side.open");
    if (side) side.classList.remove("open");
  }

  function onScroll() {
    if (current) rememberScroll(store, current, window.scrollY);
    if (tip && !tip.hidden) hideTip();
    markTocSoon();
  }

  function mount() {
    data = K.data();
    store = loadStore();
    peek = document.getElementById("peek");
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";  // restored per page in arrive()
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pagehide", saveStore);
    document.addEventListener("click", onClick);
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    document.addEventListener("keydown", onKey);
    arrive();
  }

  if (typeof document !== "undefined" && document.getElementById("kg-data")) mount();

  return {
    crumbPath: crumbPath, chooseNode: chooseNode, alsoMounts: alsoMounts, pointLabels: pointLabels,
    firstMention: firstMention, rememberScroll: rememberScroll, recallScroll: recallScroll, peekModel: peekModel,
    peekHtml: peekHtml, miniLayout: miniLayout, findNode: findNode, arrive: arrive, openPeek: openPeek, refresh: refresh,
  };
})();
if (typeof module !== "undefined") module.exports = Reader;
