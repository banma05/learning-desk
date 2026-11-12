// Changing mastery from the page: rewrite one status field in the markdown file through Chrome's File
// System Access, show the change at once and keep showing it (a localStorage overlay) until the page is
// rebuilt. Without that API, or when access is refused, the buttons copy a line to paste to Claude.
// This file runs first in the page script (KG reads the overlay while parsing the data), so it only
// reaches KG and Reader inside functions that run later.
var Status = (function () {
  "use strict";

  var CHOICES = { point: ["已掌握", "学习中", "没碰"], header: ["已掌握", "学习中", "只看过"] };
  var SHAPES = { "已掌握": "full", "学习中": "half" };  // anything else is an empty circle
  var BOM = "\uFEFF";
  var OVERLAY_KEY = "kg-overlay";
  var DB = { name: "kg-status", store: "handles", key: "root" };
  var ANCHOR = /\s->\s+#.*$/;  // same as hub/knowledge.py: the '-> #小节' tail of a point line
  // key, space after the colon, value, trailing space
  var POINT_STATUS = /^(\s*状态\s*[:：])(\s*)(.*?)(\s*)$/;  // one '|'-separated field
  var HEADER_STATUS = /^(>\s*状态\s*[:：])(\s*)(.*?)(\s*)$/;
  var SAY = { changed: "文件刚被改过，请刷新", manual: "这一行没法自动改，请让 Claude 改", copied: "已复制，粘贴给 Claude",
              pick: "请选择知识库文件夹", busy: "正在写入…", forgot: "下次改时重新选文件夹" };
  var TOAST_MS = 2600, TOAST_LONG_MS = 10000;  // long: there is something to click or copy

  // ---- pure helpers ----

  function choices(edit) {
    return edit ? (CHOICES[edit.kind] || []).slice() : [];
  }

  function shapeOf(status) {
    return SHAPES[status] || "empty";
  }

  /** The status the buttons of node stand for: a header edit is the note's own (doc_status), which on a
   *  block or group differs from the node's rollup status. */
  function current(node) {
    return node.edit && node.edit.kind === "header" ? node.doc_status : node.status;
  }

  /** A status field matched by POINT_STATUS / HEADER_STATUS with newStatus as its value. An empty value
   *  gets one space after the colon and keeps the spacing that followed it (e.g. before the next '|'). */
  function withValue(field, status) {
    return field[3] ? field[1] + field[2] + status + field[4] : field[1] + " " + status + field[2] + field[4];
  }

  function own(object, key) {
    return object && Object.prototype.hasOwnProperty.call(object, key) ? object[key] : null;
  }

  /** Text with the status of the line edit points at set to newStatus, every other character kept (BOM,
   *  each line's own \r\n or \n). {ok: false, reason}: "missing" / "changed" (the line is not edit.raw
   *  any more), "ambiguous" (two status fields), "unsupported" (a lone \r: lines are counted differently
   *  by the generator). */
  function rewriteStatus(text, edit, newStatus) {
    if (/\r(?!\n)/.test(text)) return { ok: false, reason: "unsupported" };
    var lines = text.split("\n"), i = edit.line - 1;
    if (!(i >= 0 && i < lines.length)) return { ok: false, reason: "missing" };
    var line = lines[i], bom = i === 0 && line.charAt(0) === BOM ? BOM : "";
    var cr = line.charAt(line.length - 1) === "\r" ? "\r" : "";
    var body = line.slice(bom.length, line.length - cr.length);
    if (body !== edit.raw) return { ok: false, reason: "changed" };
    var next = edit.kind === "header" ? headerLine(body, newStatus) : pointLine(body, newStatus);
    if (typeof next !== "string") return { ok: false, reason: next ? next.refused : "changed" };
    lines[i] = bom + next + cr;
    return { ok: true, text: lines.join("\n") };
  }

  /** '- 名称 | 状态: X | …': swap X, or put ' | 状态: Y' right after the name when there is none.
   *  Two status fields: {refused: "ambiguous"} (the generator reads the last one). */
  function pointLine(line, status) {
    var cut = line.search(ANCHOR), head = cut < 0 ? line : line.slice(0, cut), tail = cut < 0 ? "" : line.slice(cut);
    var parts = head.split("|"), at = -1;
    for (var i = 1; i < parts.length; i++) {
      if (!POINT_STATUS.test(parts[i])) continue;
      if (at >= 0) return { refused: "ambiguous" };
      at = i;
    }
    if (at >= 0) {
      parts[at] = withValue(POINT_STATUS.exec(parts[at]), status);
    } else {
      parts[0] = parts[0].replace(/\s*$/, function (space) { return " | 状态: " + status + space; });
    }
    return parts.join("|") + tail;
  }

  function headerLine(line, status) {
    var field = HEADER_STATUS.exec(line);
    return field ? withValue(field, status) : null;
  }

  /** A header edit sets the note's doc_status; status and shape change only on a leaf (on a block or
   *  group they are its rollup, which is not recomputed). */
  function setStatus(node, status, raw) {
    if (node.edit.kind === "header") node.doc_status = status;
    if (!(node.children && node.children.length)) {
      node.status = status;
      node.shape = shapeOf(status);
    }
    node.edit.raw = raw;
  }

  /** Does an overlay entry {status, from, raw, generatedAt} still say something about node? Only on the
   *  page build it was made on, while that page shows the line the change was made from. */
  function applies(node, entry, generatedAt) {
    return !!(node && node.edit && entry && entry.generatedAt === generatedAt && typeof entry.from === "string"
      && typeof entry.raw === "string" && node.edit.raw === entry.from && choices(node.edit).indexOf(entry.status) >= 0);
  }

  /** Show the overlay entries {nodeId: entry} that still apply to graph's nodes (built at generatedAt). */
  function applyOverlay(graph, overlay, generatedAt) {
    var nodes = graph.nodes || {};
    Object.keys(overlay || {}).forEach(function (id) {
      var node = own(nodes, id), entry = overlay[id];
      if (applies(node, entry, generatedAt)) setStatus(node, entry.status, entry.raw);
    });
    return graph;
  }

  function copyLine(node, newStatus) {
    return "把 " + node.name + " 改成 " + newStatus + "（" + (node.edit ? node.edit.file : "") + "）";
  }

  /** Name of the folder holding the page file at pathname ('' when there is none). */
  function pageFolder(pathname) {
    var parts = String(pathname || "").split("/");
    return parts.length > 2 ? parts[parts.length - 2] : "";
  }

  function lineAt(text, line) {
    var body = text.split("\n")[line - 1].replace(/\r$/, "");
    return body.charAt(0) === BOM ? body.slice(1) : body;
  }

  // ---- files (anything with the File System Access handle methods) ----

  function isMissing(error) {
    return !!error && ["NotFoundError", "TypeMismatchError", "TypeError"].indexOf(error.name) >= 0;
  }

  async function fileHandle(root, path) {
    var parts = path.split("/"), dir = root;
    for (var i = 0; i < parts.length - 1; i++) dir = await dir.getDirectoryHandle(parts[i]);
    return dir.getFileHandle(parts[parts.length - 1]);
  }

  /** Set the status of edit's line in the file under root: {ok: true, raw: that line now} only after a
   *  write; otherwise {ok: false, reason}: rewriteStatus's reasons, "unsupported" for a file that is not
   *  UTF-8, "unchanged" when the file already says newStatus (nothing written). The bytes written differ
   *  from the file's only in that one value. */
  async function writeStatus(root, edit, newStatus) {
    var handle, text;
    try {
      handle = await fileHandle(root, edit.file);
    } catch (e) {
      if (isMissing(e)) return { ok: false, reason: "missing" };
      throw e;
    }
    var bytes = await (await handle.getFile()).arrayBuffer();
    try {
      text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
    } catch (e) {
      return { ok: false, reason: "unsupported" };
    }
    var result = rewriteStatus(text, edit, newStatus);
    if (!result.ok) return result;
    if (result.text === text) return { ok: false, reason: "unchanged" };
    var out = await handle.createWritable();
    try {
      await out.write(new TextEncoder().encode(result.text));
      await out.close();
    } catch (e) {
      if (out.abort) await out.abort().catch(function () {});
      throw e;
    }
    return { ok: true, raw: lineAt(result.text, edit.line) };
  }

  /** The knowledge base: has 维护约定.md or 项目/, and (when known) is the folder holding this page. */
  async function looksLikeKb(root, folderName) {
    if (folderName && root.name !== folderName) return false;
    try {
      await root.getFileHandle("维护约定.md");
      return true;
    } catch (e) { /* try the other mark */ }
    try {
      await root.getDirectoryHandle("项目");
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---- overlay and the remembered folder, per page file (all file:// pages share one origin) ----

  function page() {
    return typeof location !== "undefined" ? decodeURIComponent(location.pathname) : "";
  }

  /** {page path: {node id: {status, from, raw, generatedAt}}} */
  function loadOverlay() {
    try {
      var saved = JSON.parse(window.localStorage.getItem(OVERLAY_KEY) || "{}");
      return saved && typeof saved === "object" ? saved : {};
    } catch (e) {
      return {};
    }
  }

  function saveOverlay(overlay) {
    try {
      window.localStorage.setItem(OVERLAY_KEY, JSON.stringify(overlay));
    } catch (e) { /* storage blocked: the change shows until the page is reloaded */ }
  }

  /** Called by KG when it first parses the page data, before anything is drawn. This page's entries
   *  that no longer apply (page rebuilt, line changed, node gone) are dropped. */
  function overlayData(data) {
    var all = loadOverlay(), here = page(), mine = own(all, here) || {}, live = {}, graphs = data.graphs || {};
    Object.keys(mine).forEach(function (id) {
      Object.keys(graphs).forEach(function (name) {
        if (applies(own(graphs[name].nodes, id), mine[id], data.generatedAt)) live[id] = mine[id];
      });
    });
    Object.keys(graphs).forEach(function (name) { applyOverlay(graphs[name], live, data.generatedAt); });
    if (Object.keys(live).length !== Object.keys(mine).length) {
      if (Object.keys(live).length) all[here] = live;
      else delete all[here];
      saveOverlay(all);
    }
    return data;
  }

  /** Drop this page's overlay entries for these node ids (their line turned out different). */
  function forgetEntries(ids) {
    var all = loadOverlay(), here = page(), mine = own(all, here);
    if (!mine) return;
    ids.forEach(function (id) { delete mine[id]; });
    if (!Object.keys(mine).length) delete all[here];
    saveOverlay(all);
  }

  function idb(run) {
    return new Promise(function (resolve, reject) {
      var open = indexedDB.open(DB.name, 1);
      open.onupgradeneeded = function () { open.result.createObjectStore(DB.store); };
      open.onerror = function () { reject(open.error); };
      open.onsuccess = function () {
        var db = open.result, tx, req;
        try {
          tx = db.transaction(DB.store, "readwrite");
          req = run(tx.objectStore(DB.store));
        } catch (e) {  // e.g. a value that cannot be stored
          db.close();
          reject(e);
          return;
        }
        tx.oncomplete = function () { db.close(); resolve(req.result); };
        tx.onerror = tx.onabort = function () { db.close(); reject(tx.error); };
      };
    });
  }

  function loadHandle() {
    return idb(function (store) { return store.get(DB.key); }).then(function (saved) {
      return saved && saved.page === page() && saved.handle ? saved.handle : null;
    }, function () { return null; });
  }

  function saveHandle(handle) {
    return idb(function (store) { return store.put({ page: page(), handle: handle }, DB.key); })
      .catch(function () { /* not remembered: the folder is asked for again next time */ });
  }

  function forgetHandle() {
    return idb(function (store) { return store.delete(DB.key); }).catch(function () {});
  }

  // ---- the page ----

  var COPY = "copy";
  var mode = "", busy = false, toast = null, toastTimer = 0;

  /** Buttons of one '.status-buttons' slot; a node without a line to change keeps it empty (hidden). */
  function fill(slot) {
    slot.dataset.filled = "1";
    var found = KG.nodeOf(slot.dataset.node), node = found && found.node;
    if (!node || !node.edit) return;
    var copying = mode === COPY;
    slot.classList.toggle("sb-copy", copying);
    slot.innerHTML = (copying ? '<span class="sb-hint">复制这句话：</span>' : "") + choices(node.edit).map(function (s) {
      var on = current(node) === s, tip = copying ? copyLine(node, s) : "改成" + s;
      return '<button type="button" class="sb' + (on ? " on" : "") + '" data-status="' + KG.esc(s) + '" aria-pressed="'
        + on + '" title="' + KG.esc(tip) + '">' + KG.esc(s) + "</button>";
    }).join("");
  }

  function fillAll() {
    if (typeof KG === "undefined") return;
    document.querySelectorAll(".status-buttons:not([data-filled])").forEach(fill);
  }

  /** Toast with optional buttons: actions = [{label, run}]. say("") hides it. */
  function say(text, actions) {
    actions = actions || [];
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "status-toast";
      toast.setAttribute("role", "status");
      document.body.appendChild(toast);
    }
    toast.textContent = text;
    actions.forEach(function (action) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "status-toast-act";
      button.textContent = action.label;
      button.addEventListener("click", function () { action.run(); });
      toast.appendChild(button);
    });
    toast.hidden = !text;
    clearTimeout(toastTimer);
    if (text) toastTimer = setTimeout(function () { toast.hidden = true; }, actions.length ? TOAST_LONG_MS : TOAST_MS);
  }

  var CHANGE_FOLDER = { label: "换文件夹", run: function () { forgetHandle().then(function () { say(SAY.forgot); }); } };

  function setBusy(on) {
    busy = on;
    document.body.classList.toggle("kg-writing", on);
  }

  function useCopy() {
    mode = COPY;
    document.querySelectorAll(".status-buttons[data-filled]").forEach(function (slot) { delete slot.dataset.filled; });
    fillAll();
  }

  function copyText(text) {
    var clip = navigator.clipboard;
    var tried = clip && clip.writeText ? clip.writeText(text) : Promise.reject(new Error("no clipboard"));
    return tried.catch(function () {  // no clipboard access: the old way
      var area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      var done = document.execCommand("copy");
      area.remove();
      if (!done) throw new Error("copy");
    });
  }

  /** Copy the line for Claude; when copying fails, show it long enough to copy by hand. */
  function copy(node, status) {
    var line = copyLine(node, status);
    return copyText(line).then(function () { say(SAY.copied); },
      function () { say(line, [{ label: "关闭", run: function () { say(""); } }]); });
  }

  /** The remembered folder with write access, a newly picked one, COPY when access is refused, or
   *  null (picking cancelled, or not this page's knowledge base: already said). */
  async function folder() {
    var root = await loadHandle();
    if (!root) {
      say(SAY.pick);
      try {
        root = await window.showDirectoryPicker({ mode: "readwrite" });
      } catch (e) {
        if (e && e.name === "AbortError") { say(""); return null; }
        return COPY;
      }
      var want = pageFolder(page());
      if (!(await looksLikeKb(root, want))) {
        say("这不是这个页面所在的 " + (want || "知识库") + " 文件夹，没有改");
        return null;
      }
      await saveHandle(root);
    }
    var state = await root.queryPermission({ mode: "readwrite" });
    if (state !== "granted") state = await root.requestPermission({ mode: "readwrite" }).catch(function () { return "denied"; });
    return state === "granted" ? root : COPY;
  }

  /** Nodes in any graph showing the same file line as node (a note hung under two topics). */
  function sameLine(node) {
    var edit = node.edit, same = [], graphs = KG.data().graphs || {};
    Object.keys(graphs).forEach(function (name) {
      var nodes = graphs[name].nodes || {};
      Object.keys(nodes).forEach(function (id) {
        var other = nodes[id].edit;
        if (other && other.file === edit.file && other.line === edit.line) same.push(nodes[id]);
      });
    });
    return same;
  }

  /** After a write: new status on the nodes, overlay entries kept from the line the page was built with
   *  (an entry back at that line is dropped), then repaint. Never throws: the file is written. */
  function saved(node, status, before, raw) {
    var shown = true;
    try {
      var same = sameLine(node), all = loadOverlay(), here = page(), mine = own(all, here) || (all[here] = {});
      var built = KG.data().generatedAt;
      same.forEach(function (other) {
        var prev = own(mine, other.id), chained = prev && prev.raw === before && prev.generatedAt === built;
        var from = chained ? prev.from : before;
        setStatus(other, status, raw);
        if (from === raw) delete mine[other.id];
        else mine[other.id] = { status: status, from: from, raw: raw, generatedAt: built };
      });
      if (!Object.keys(mine).length) delete all[here];
      saveOverlay(all);
      same.forEach(function (other) { KG.refresh(other.id); });
      if (typeof Reader !== "undefined") Reader.refresh();
    } catch (e) {
      shown = false;
    }
    say("已改成 " + status + (shown ? "" : "（刷新后显示）"), [CHANGE_FOLDER]);
  }

  function refused(node, status, reason) {
    if (reason === "unchanged") say("");
    else if (reason === "changed" || reason === "missing") {
      // an entry made from this line no longer matches the file: refreshing must show the file again
      forgetEntries(sameLine(node).map(function (other) { return other.id; }));
      say(SAY.changed, [CHANGE_FOLDER]);
    }
    else say(SAY.manual, [{ label: "复制这句话", run: function () { copy(node, status); } }]);
  }

  async function change(node, status) {
    if (busy) { say(SAY.busy); return; }
    if (mode === COPY) { await copy(node, status); return; }
    if (current(node) === status) return;
    setBusy(true);
    try {
      var root = await folder();
      if (root === COPY) {
        useCopy();
        await copy(node, status);
      } else if (root) {
        say(SAY.busy);
        var before = node.edit.raw, result = await writeStatus(root, node.edit, status);
        if (result.ok) saved(node, status, before, result.raw);
        else refused(node, status, result.reason);
      }
    } catch (e) {
      say("没改成：" + ((e && e.message) || e));
    } finally {
      setBusy(false);
    }
  }

  function onClick(e) {
    var button = e.target.closest && e.target.closest(".status-buttons button[data-status]");
    if (!button) return;
    e.preventDefault();
    var found = KG.nodeOf(button.closest(".status-buttons").dataset.node);
    if (found && found.node.edit) change(found.node, button.dataset.status);
  }

  function mount() {
    mode = typeof window.showDirectoryPicker === "function" ? "" : COPY;
    new MutationObserver(fillAll).observe(document.body, { childList: true, subtree: true });
    document.addEventListener("click", onClick);
  }

  if (typeof document !== "undefined" && document.getElementById("kg-data")) mount();

  return {
    rewriteStatus: rewriteStatus, applyOverlay: applyOverlay, copyLine: copyLine, choices: choices, pageFolder: pageFolder,
    current: current, writeStatus: writeStatus, looksLikeKb: looksLikeKb, overlayData: overlayData, forgetEntries: forgetEntries,
  };
})();
if (typeof module !== "undefined") module.exports = Status;
