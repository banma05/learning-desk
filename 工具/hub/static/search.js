// Search box: index entries (points, notes, concept cards, headings) from kg-data, body text from the
// page's own articles (collected on the first search). Pure helpers are exported for tests.
var Search = (function () {
  "use strict";

  var K = typeof KG !== "undefined" ? KG : require("./graph.js");
  var KINDS = ["point", "note", "concept", "heading"];
  var LABELS = { point: "知识点", note: "笔记", concept: "概念", heading: "标题", text: "正文" };
  var DELAY = 150;
  var FLASH_MS = 1800;
  var SNIPPET_BEFORE = 24, SNIPPET_AFTER = 56;
  var NESTED_BLOCK = "p,ul,ol,li,table,blockquote,pre";

  // ---- matching (pure) ----

  function norm(text) {
    return String(text == null ? "" : text).toLowerCase();
  }

  /** 0 = a name equals the query, 1 = a name starts with it, 2 = a name contains it, -1 = no match. */
  function rank(entry, needle) {
    var best = -1;
    (entry.w && entry.w.length ? entry.w : [entry.t]).forEach(function (word) {
      var text = norm(word), at = text.indexOf(needle), got;
      if (at < 0) return;
      got = text === needle ? 0 : at === 0 ? 1 : 2;
      if (best < 0 || got < best) best = got;
    });
    return best;
  }

  /** Entries matching query, grouped by kind; exact name > name starts with > name or alias contains. */
  function searchIndex(entries, query, limit) {
    var max = limit === undefined ? 8 : limit, needle = norm(query).trim();
    var out = { point: [], note: [], concept: [], heading: [] };
    if (!needle) return out;
    var ranked = [];
    (entries || []).forEach(function (entry, order) {
      var r = out[entry.k] ? rank(entry, needle) : -1;
      if (r >= 0) ranked.push({ entry: entry, rank: r, order: order });
    });
    ranked.sort(function (a, b) { return a.rank - b.rank || a.order - b.order; });
    ranked.forEach(function (item) {
      var group = out[item.entry.k];
      if (group.length < max) group.push(item.entry);
    });
    return out;
  }

  /** A short piece of text around the first hit; "…" marks where it was cut. */
  function snippetOf(text, needle) {
    var at = norm(text).indexOf(needle);
    if (at < 0) return text.slice(0, SNIPPET_BEFORE + SNIPPET_AFTER);
    var from = Math.max(0, at - SNIPPET_BEFORE), to = Math.min(text.length, at + needle.length + SNIPPET_AFTER);
    return (from > 0 ? "…" : "") + text.slice(from, to) + (to < text.length ? "…" : "");
  }

  /** Blocks of text containing query, in document order: [{docId, title, snippet, elementIndex}]. */
  function searchText(docs, query, limit) {
    var max = limit === undefined ? 10 : limit, needle = norm(query).trim(), hits = [];
    if (!needle) return hits;
    (docs || []).forEach(function (doc) {
      doc.blocks.forEach(function (block, i) {
        if (hits.length < max && norm(block).indexOf(needle) >= 0)
          hits.push({ docId: doc.docId, title: doc.title, snippet: snippetOf(block, needle), elementIndex: i });
      });
    });
    return hits;
  }

  // ---- results markup (pure) ----

  /** text as HTML (escaped) with every match of query inside <mark>. */
  function highlight(text, query) {
    var needle = norm(query).trim(), source = String(text), lower = norm(source), html = "", from = 0, at;
    if (!needle) return K.esc(source);
    while ((at = lower.indexOf(needle, from)) >= 0) {
      html += K.esc(source.slice(from, at)) + "<mark>" + K.esc(source.slice(at, at + needle.length)) + "</mark>";
      from = at + needle.length;
    }
    return html + K.esc(source.slice(from));
  }

  /** The alias that matched, when the title itself does not contain the query ("" otherwise). */
  function aliasHint(entry, query) {
    var needle = norm(query).trim();
    if (!needle || norm(entry.t).indexOf(needle) >= 0) return "";
    var found = (entry.w || []).filter(function (word) { return norm(word).indexOf(needle) >= 0; });
    return found[0] || "";
  }

  function entryItem(entry, query) {
    var hint = aliasHint(entry, query);
    var sub = hint ? "别名：" + hint : entry.k === "heading" ? entry.s : K.plain(entry.s || "").slice(0, 40);
    return { kind: entry.k, title: entry.t, sub: sub, entry: entry };
  }

  /** [{label, items}] in the order 知识点 / 笔记 / 概念 / 标题 / 正文, empty groups left out. */
  function buildGroups(entries, docs, query) {
    var found = searchIndex(entries, query), groups = [];
    KINDS.forEach(function (kind) {
      if (found[kind].length)
        groups.push({ label: LABELS[kind], items: found[kind].map(function (e) { return entryItem(e, query); }) });
    });
    var hits = searchText(docs, query);
    if (hits.length)
      groups.push({ label: LABELS.text, items: hits.map(function (h) {
        return { kind: "text", title: h.snippet, sub: h.title, hit: h };
      }) });
    return groups;
  }

  function resultsHtml(groups, query) {
    if (!groups.length) return '<div class="sr-empty">没有找到</div>';
    var n = 0;
    return groups.map(function (group) {
      return '<div class="sr-group">' + K.esc(group.label) + "</div>" + group.items.map(function (item) {
        return '<div class="sr-item" role="option" data-i="' + n++ + '"><span class="sr-t">'
          + highlight(item.title, query) + "</span>"
          + (item.sub ? '<span class="sr-s">' + K.esc(item.sub) + "</span>" : "") + "</div>";
      }).join("");
    }).join("");
  }

  // ---- body text from the page ----

  /** Text of an element without the blocks nested inside it (a list item's sub-list is its own block). */
  function ownText(el) {
    return Array.prototype.filter.call(el.childNodes, function (node) {
      return node.nodeType === 3 || !(node.matches && node.matches(NESTED_BLOCK));
    }).map(function (node) { return node.textContent; }).join("");
  }

  /** Every reading page's paragraphs, list items and table cells: docs for searchText plus their elements. */
  function collectDocs(root) {
    var docs = [], elements = {};
    root.querySelectorAll("article.doc").forEach(function (article) {
      var blocks = [], els = [], title = article.querySelector("h1");
      article.querySelectorAll(".doc-body p, .doc-body li, .doc-body td").forEach(function (el) {
        var text = ownText(el).replace(/\s+/g, " ").trim();
        if (text) { blocks.push(text); els.push(el); }
      });
      var docId = article.id.replace(/^doc-/, "");
      docs.push({ docId: docId, title: title ? title.textContent.trim() : docId, blocks: blocks });
      elements[docId] = els;
    });
    return { docs: docs, elements: elements };
  }

  // ---- going to a result ----

  var corpus = null;

  function pageText() {
    if (!corpus) corpus = collectDocs(document);
    return corpus;
  }

  /** Open a doc, drawn for graph node nodeId if given, and scroll to an element id in it (the reader does the
   *  scrolling on arrival). */
  function openDoc(href, anchor, nodeId) {
    if (decodeURIComponent(location.hash) === href) {  // already there: no hashchange will come
      var el = anchor && document.getElementById(anchor);
      if (el) el.scrollIntoView({ block: "start" });
      return;
    }
    K.storage("kg-anchor", anchor || null);
    K.storage("kg-node", nodeId || null);
    location.hash = href;
  }

  /** Light up an element for a moment (restarts if it is already lit). */
  function flash(id) {
    var el = id && document.getElementById(id);
    if (!el) return;
    el.classList.remove("search-flash");
    void el.offsetWidth;
    el.classList.add("search-flash");
    setTimeout(function () { el.classList.remove("search-flash"); }, FLASH_MS);
  }

  function showGraphNode(id) {
    K.focus(id);
    var found = K.nodeOf(id);
    if (found && found.view) found.view.el.scrollIntoView({ block: "start" });
  }

  /** A point: the entry page, graph centred on it, its card open. */
  function goPoint(entry) {
    if (!entry.node || !K.nodeOf(entry.node)) { openDoc(entry.href, entry.a, entry.node); return; }
    K.storage("kg-focus", entry.node);
    var section = document.getElementById("sec-项目");
    if (section && section.classList.contains("show")) { showGraphNode(entry.node); return; }
    window.addEventListener("hashchange", function after() {  // runs once the page has switched to 项目
      window.removeEventListener("hashchange", after);
      showGraphNode(entry.node);
    });
    location.hash = "#项目";
  }

  function go(item) {
    var entry = item.entry, hit = item.hit;
    if (item.kind === "point") { goPoint(entry); return; }
    if (item.kind === "heading") { openDoc(entry.href, entry.a); flash(entry.a); return; }
    if (hit) {  // body text has no id of its own: give the block one so the reader can scroll to it
      var el = pageText().elements[hit.docId][hit.elementIndex];
      if (!el.id) el.id = hit.docId + "-hit-" + hit.elementIndex;
      openDoc("#doc-" + hit.docId, el.id);
      flash(el.id);
      return;
    }
    openDoc(entry.href, "", entry.node);
  }

  // ---- the box ----

  function mount() {
    var input = document.getElementById("search"), box = document.getElementById("search-results");
    if (!input || !box) return;
    var items = [], active = 0, timer = null;

    function close() { box.classList.remove("show"); }

    function mark(index, scroll) {
      var rows = box.querySelectorAll(".sr-item");
      active = Math.max(0, Math.min(index, rows.length - 1));
      rows.forEach(function (row, i) {
        row.classList.toggle("active", i === active);
        if (scroll && i === active) row.scrollIntoView({ block: "nearest" });
      });
    }

    function run() {
      var query = input.value.trim();
      if (!query) { items = []; box.innerHTML = ""; close(); return; }
      var groups = buildGroups(K.data().search, pageText().docs, query);
      items = [].concat.apply([], groups.map(function (g) { return g.items; }));
      box.innerHTML = resultsHtml(groups, query);
      box.classList.add("show");
      mark(0, false);
    }

    function open(index) {
      var item = items[index];
      if (!item) return;
      close();
      input.blur();
      go(item);
    }

    function reset() {
      clearTimeout(timer);
      input.value = "";
      items = [];
      box.innerHTML = "";
      close();
      input.blur();
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { timer = null; run(); }, DELAY);
    });
    input.addEventListener("focus", function () {  // coming back to the box: show what was found again
      if (!input.value.trim()) return;
      if (items.length) box.classList.add("show"); else run();
    });
    input.addEventListener("keydown", function (e) {
      if (composing(e)) return;  // Enter / arrows picking a word in the IME are not ours
      if (e.key === "Escape") { e.stopPropagation(); reset(); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (box.classList.contains("show")) mark(active + (e.key === "ArrowDown" ? 1 : -1), true);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (timer) { clearTimeout(timer); timer = null; run(); }  // pressed Enter within the typing delay
        open(active);
      }
    });
    box.addEventListener("click", function (e) {
      var row = e.target.closest(".sr-item");
      if (row) open(Number(row.dataset.i));
    });
    box.addEventListener("mousemove", function (e) {
      var row = e.target.closest(".sr-item");
      if (row && Number(row.dataset.i) !== active) mark(Number(row.dataset.i), false);
    });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".nav-search")) close();
    });
  }

  /** A key that belongs to an input method still composing (Chinese input), not to the search box. */
  function composing(e) {
    return !!(e.isComposing || e.keyCode === 229);
  }

  if (typeof document !== "undefined" && document.getElementById("kg-data")) mount();

  return {
    searchIndex: searchIndex, searchText: searchText, snippetOf: snippetOf, highlight: highlight,
    aliasHint: aliasHint, buildGroups: buildGroups, resultsHtml: resultsHtml, ownText: ownText,
    collectDocs: collectDocs, composing: composing,
  };
})();
if (typeof module !== "undefined") module.exports = Search;
