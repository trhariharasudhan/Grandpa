// Grandpa desktop app: renders what Python sends; sends typed lines back.
// The WebSocket URL (with its per-run token) arrives from the window
// (window.grandpaConnect) or, in a browser tab, in the page hash (#ws=...).
// Chats, projects and settings live in this window's localStorage (this PC
// only). Everything is built with DOM calls, never from HTML strings.
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const app = $("app"), feed = $("feed"), list = $("messages"), input = $("input");
  const sendBtn = $("send"), stopBtn = $("stop"), statusLine = $("status");
  const modelBtn = $("model"), modelMenu = $("model-menu"), micBtn = $("mic"), attachBtn = $("attach");
  const narrow = window.matchMedia("(max-width: 860px)");

  const STORE = "grandpa.chats.v1", SETTINGS = "grandpa.settings.v1";
  const WORDS = { starting: "Starting…", idle: "Ready", thinking: "Thinking…", asking: "Waiting for your answer", stopped: "Stopped" };
  let socket = null, retry = 500, state = "starting", busySince = 0, modelName = "";
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");
  let incognito = null;          // the incognito chat while it is on (never stored)
  let attached = [];             // paths picked with 📎 for the next message
  let picking = false;           // the model menu is waiting for Grandpa's list
  let ignoreModelAsk = false;    // the menu was closed before the list came
  const quiet = [];              // replies to our own commands: [{re, toast}]

  // --- storage -------------------------------------------------------------
  function read(key, fallback) {
    try { return Object.assign(fallback, JSON.parse(localStorage.getItem(key)) || {}); }
    catch (_) { return fallback; }
  }
  let db = read(STORE, { current: null, chats: [], projects: [] });
  if (!Array.isArray(db.projects)) db.projects = [];
  let settings = read(SETTINGS, { name: "", theme: "", size: "m", model: "", enter: true });
  try { if (!settings.theme) settings.theme = localStorage.getItem("grandpa.theme") || "dark"; } catch (_) { settings.theme = "dark"; }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(db)); } catch (_) { toast("Couldn't save the chat list (storage full?)", true); } }
  function saveSettings() { try { localStorage.setItem(SETTINGS, JSON.stringify(settings)); } catch (_) { /* ignore */ } }
  function newId() { return String(Date.now()) + Math.random().toString(36).slice(2, 6); }

  function currentChat() {
    if (incognito) return incognito;
    let chat = db.chats.find((c) => c.id === db.current);
    if (!chat) {
      chat = { id: newId(), title: "New chat", at: Date.now(), project: null, messages: [] };
      db.chats.unshift(chat); db.current = chat.id; save();
    }
    return chat;
  }

  // --- look & settings -----------------------------------------------------
  function applySettings() {
    document.documentElement.dataset.theme = settings.theme === "light" ? "light" : "dark";
    document.documentElement.dataset.size = ["s", "m", "l"].includes(settings.size) ? settings.size : "m";
    const name = settings.name || "You";
    $("user-name").textContent = name;
    $("avatar").textContent = name.replace(/^(Mr|Ms|Mrs|Mx)\.\s+/i, "").trim().charAt(0).toUpperCase() || "?";
    $("hello").textContent = settings.name ? "Hi " + settings.name + ", what shall we do?" : "What shall we do?";
  }
  function toggleTheme() { settings.theme = settings.theme === "dark" ? "light" : "dark"; saveSettings(); applySettings(); syncSettingsForm(); }

  // The window can tell us the name Grandpa uses and open a file picker.
  function api() { return window.pywebview && window.pywebview.api ? window.pywebview.api : null; }
  // In the window the name comes from Grandpa's own profile (the same one
  // the terminal uses); in a plain browser tab it is kept in this page.
  let profile = null;
  function windowReady() {
    const a = api();
    attachBtn.disabled = !a;
    attachBtn.title = a ? "" : "Adding files works in the Grandpa window";
    $("plus-orb").disabled = !(a && a.open_orb);
    if (!a || !a.get_profile) return;
    a.get_profile().then((p) => {
      profile = p || null;
      if (profile && profile.display) { settings.name = String(profile.display).slice(0, 48); saveSettings(); applySettings(); redraw(); }
      if (profile && !profile.onboarded) openSettings(true);
    }).catch(() => { /* keep the page's own name */ });
  }
  window.addEventListener("pywebviewready", windowReady);

  let toastTimer = 0;
  function toast(text, bad) {
    const t = $("toast"); t.textContent = text; t.className = bad ? "bad" : ""; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
  }

  // --- drawing messages ----------------------------------------------------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function label(who, at, extra) {
    const row = el("div", "label", who);
    row.appendChild(el("time", "", new Date(at || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
    if (extra) row.appendChild(el("time", "", extra));
    return row;
  }
  function baseName(path) { return String(path).split(/[\\/]/).pop() || String(path); }
  const MENTION = /@"([^"]+)"|@(\S+)/g;
  function draw(msg) {
    const li = el("li");
    if (msg.type === "user") {
      li.className = "msg-user";
      li.appendChild(label(settings.name || "You", msg.at));
      const files = (msg.attached || []).filter(Boolean);
      if (files.length) {
        const row = el("div", "files");
        files.forEach((f) => { const chip = el("span", "file"); chip.title = f; chip.appendChild(el("span", "", "📄 " + baseName(f))); row.appendChild(chip); });
        li.appendChild(row);
      }
      let text = msg.text;
      if (files.length) text = text.replace(MENTION, (all, q, plain) => (files.includes(q || plain) ? "" : all)).trim();
      if (text) li.appendChild(el("div", "bubble", text));
    } else if (msg.type === "reply") {
      li.className = "msg-grandpa";
      li.appendChild(label("Grandpa", msg.at, msg.secs ? "· " + msg.secs + "s" : ""));
      const body = el("div", "body");
      body.appendChild(window.GrandpaMarkdown.render(msg.text, msg.format !== "text"));
      li.appendChild(body);
      const tools = el("div", "tools");
      const copy = el("button", "", "Copy"); copy.type = "button";
      copy.addEventListener("click", () => {
        (navigator.clipboard ? navigator.clipboard.writeText(msg.text) : Promise.reject())
          .then(() => { copy.textContent = "Copied ✓"; setTimeout(() => { copy.textContent = "Copy"; }, 1500); })
          .catch(() => { copy.textContent = "Copy failed"; });
      });
      tools.appendChild(copy); li.appendChild(tools);
    } else if (msg.type === "note") {
      li.className = "msg-note" + (msg.failed ? " failed" : "");
      li.textContent = msg.text;
    } else return null;
    list.appendChild(li);
    app.classList.add("has-messages");
    feed.scrollTop = feed.scrollHeight;
    return li;
  }
  function redraw() {
    list.textContent = "";
    app.classList.remove("has-messages");
    const chat = currentChat();
    chat.messages.forEach(draw);
    $("title").textContent = incognito ? "Incognito chat" : (chat.title === "New chat" ? "Grandpa" : chat.title);
    drawSidebar();
  }
  function keep(msg) {
    const chat = currentChat();
    const stored = Object.assign({ at: Date.now() }, msg);
    delete stored.v; delete stored.run; delete stored.seq;
    chat.messages.push(stored);
    chat.messages = chat.messages.slice(-300);
    if (msg.type === "user" && chat.title === "New chat") {
      chat.title = (msg.text.replace(MENTION, "").trim() || "Files").slice(0, 48);
      $("title").textContent = incognito ? "Incognito chat" : chat.title;
    }
    chat.at = Date.now();
    if (!incognito) { save(); if (msg.type === "user") drawSidebar(); }
    draw(stored);
  }

  // --- left panel: projects and chats ------------------------------------------
  let expanded = new Set();
  function matches(chat, needle) {
    if (!needle) return true;
    if (chat.title.toLowerCase().includes(needle)) return true;
    return chat.messages.some((m) => String(m.text || "").toLowerCase().includes(needle));
  }
  function chatRow(chat) {
    const li = el("li");
    const row = el("div", "row" + (!incognito && chat.id === db.current ? " current" : ""));
    const open = el("button", "open", chat.title); open.type = "button"; open.title = chat.title;
    open.addEventListener("click", () => switchTo(chat.id));
    const more = el("button", "more", "⋯"); more.type = "button"; more.title = "Rename, move or delete";
    more.addEventListener("click", (e) => { e.stopPropagation(); chatMenu(chat, more); });
    row.appendChild(open); row.appendChild(more); li.appendChild(row);
    return li;
  }
  function drawSidebar() {
    const needle = $("search").value.trim().toLowerCase();
    const projects = $("projects"), chats = $("chats");
    projects.textContent = ""; chats.textContent = "";
    const byTime = db.chats.slice().sort((a, b) => (b.at || 0) - (a.at || 0));
    db.projects.forEach((p) => {
      const inside = byTime.filter((c) => c.project === p.id && matches(c, needle));
      if (needle && !inside.length && !p.name.toLowerCase().includes(needle)) return;
      const li = el("li", "project" + (expanded.has(p.id) || needle ? " expanded" : ""));
      const row = el("div", "row");
      const open = el("button", "open", p.name); open.type = "button"; open.title = p.name + " (" + inside.length + " chats)";
      open.addEventListener("click", () => { expanded.has(p.id) ? expanded.delete(p.id) : expanded.add(p.id); drawSidebar(); });
      const more = el("button", "more", "⋯"); more.type = "button"; more.title = "Project options";
      more.addEventListener("click", (e) => { e.stopPropagation(); projectMenu(p, more); });
      row.appendChild(open); row.appendChild(more); li.appendChild(row);
      if (expanded.has(p.id) || needle) {
        const ol = el("ol", "project-chats");
        inside.forEach((c) => ol.appendChild(chatRow(c)));
        if (!inside.length) ol.appendChild(el("li", "empty", "No chats yet"));
        li.appendChild(ol);
      }
      projects.appendChild(li);
    });
    if (!db.projects.length) projects.appendChild(el("li", "empty", "Group chats into projects with ＋"));
    const loose = byTime.filter((c) => !c.project && c.messages.length && matches(c, needle));
    loose.forEach((c) => chats.appendChild(chatRow(c)));
    if (!loose.length) chats.appendChild(el("li", "empty", needle ? "No chats match" : "No chats yet"));
  }
  $("search").addEventListener("input", drawSidebar);

  // a small "⋯" menu next to a row
  let openMenu = null;
  function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }
  function showMenu(anchor, items) {
    closeMenu();
    const menu = el("div", "menu"); menu.setAttribute("role", "menu");
    items.forEach((item) => {
      if (item === "-") { menu.appendChild(el("div", "sep")); return; }
      if (item.head) { menu.appendChild(el("div", "head", item.head)); return; }
      const b = el("button", item.danger ? "danger" : "", item.text); b.type = "button";
      b.addEventListener("click", () => { closeMenu(); item.run(); });
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8) + "px";
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8) + "px";
    openMenu = menu;
  }
  document.addEventListener("click", (e) => {
    if (openMenu && !openMenu.contains(e.target)) closeMenu();
    if (!modelMenu.hidden && !modelMenu.contains(e.target) && e.target !== modelBtn) closeModelMenu();
    if (!$("plus-menu").hidden && !$("plus-menu").contains(e.target)) $("plus-menu").hidden = true;
  });

  function chatMenu(chat, anchor) {
    const items = [
      { text: "Rename", run: () => ask({ title: "Rename chat", value: chat.title }).then((v) => { if (v) { chat.title = v.slice(0, 60); save(); redraw(); } }) },
      "-", { head: "Move to project" },
    ];
    db.projects.forEach((p) => { if (chat.project !== p.id) items.push({ text: "📁 " + p.name, run: () => { chat.project = p.id; expanded.add(p.id); save(); drawSidebar(); } }); });
    if (chat.project) items.push({ text: "Remove from project", run: () => { chat.project = null; save(); drawSidebar(); } });
    items.push({ text: "＋ New project…", run: () => newProject().then((p) => { if (p) { chat.project = p.id; save(); drawSidebar(); } }) });
    items.push("-", { text: "Delete", danger: true, run: () => confirmBox("Delete this chat?", "“" + chat.title + "” is removed from this PC.").then((ok) => { if (ok) removeChat(chat.id); }) });
    showMenu(anchor, items);
  }
  function projectMenu(p, anchor) {
    showMenu(anchor, [
      { text: "New chat in this project", run: () => newChat(p.id) },
      { text: "Rename", run: () => ask({ title: "Rename project", value: p.name }).then((v) => { if (v) { p.name = v.slice(0, 40); save(); drawSidebar(); } }) },
      "-",
      { text: "Delete project", danger: true, run: () => confirmBox("Delete the project “" + p.name + "”?", "Its chats are kept and move to Recents.").then((ok) => {
        if (!ok) return;
        db.chats.forEach((c) => { if (c.project === p.id) c.project = null; });
        db.projects = db.projects.filter((x) => x.id !== p.id); save(); drawSidebar();
      }) },
    ]);
  }
  function newProject() {
    return ask({ title: "New project", text: "A folder for related chats.", value: "", placeholder: "Project name" }).then((name) => {
      if (!name) return null;
      const p = { id: newId(), name: name.slice(0, 40), at: Date.now() };
      db.projects.push(p); expanded.add(p.id); save(); drawSidebar();
      return p;
    });
  }
  $("new-project").addEventListener("click", newProject);

  // --- small dialog (rename, new project, confirm) ------------------------------
  let dialogDone = null;
  function dialog(opts) {
    if (dialogDone) dialogDone(null);
    $("dialog-title").textContent = opts.title;
    $("dialog-text").textContent = opts.text || "";
    const field = $("dialog-input");
    field.hidden = !opts.field; field.value = opts.value || ""; field.placeholder = opts.placeholder || "";
    $("dialog-ok").textContent = opts.ok || "OK";
    $("dialog-box").className = opts.danger ? "danger" : "";
    $("dialog").hidden = false;
    setTimeout(() => (opts.field ? field : $("dialog-ok")).focus(), 20);
    return new Promise((resolve) => { dialogDone = (v) => { dialogDone = null; $("dialog").hidden = true; resolve(v); }; });
  }
  function ask(opts) { return dialog(Object.assign({ field: true }, opts)).then((v) => (v === null ? null : String(v).trim() || null)); }
  function confirmBox(title, text) { return dialog({ title, text, ok: "Delete", danger: true }).then((v) => v !== null); }
  $("dialog-box").addEventListener("submit", (e) => { e.preventDefault(); if (dialogDone) dialogDone($("dialog-input").hidden ? true : $("dialog-input").value); });
  $("dialog-cancel").addEventListener("click", () => { if (dialogDone) dialogDone(null); });

  // --- questions from Grandpa (confirm / choose / type) ------------------------------
  function question(msg) {
    if (msg.kind === "choose" && msg.prompt === "Switch model") {
      if (picking) return fillModelMenu(msg.options);
      if (ignoreModelAsk) { ignoreModelAsk = false; cancel(); return; }
    }
    const li = el("li", "msg-ask");
    li.appendChild(el("p", "", msg.prompt));
    const box = el("div", "choices");
    const answer = (value) => {
      li.classList.add("done"); box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      sendRaw(value);
    };
    if (msg.kind === "confirm") {
      [["Yes", "yes"], ["No", "no"]].forEach(([text, value]) => {
        const b = el("button", value, text); b.type = "button";
        b.addEventListener("click", () => answer(value)); box.appendChild(b);
      });
    } else if (msg.kind === "choose") {
      msg.options.forEach((opt) => {
        const b = el("button", "option", opt); b.type = "button";
        b.addEventListener("click", () => answer(opt)); box.appendChild(b);
      });
    } else {
      box.appendChild(el("span", "hint", "Type your answer below and press Enter."));
      setTimeout(() => input.focus(), 30);
    }
    li.appendChild(box); list.appendChild(li); app.classList.add("has-messages");
    feed.scrollTop = feed.scrollHeight;
  }

  // --- the model picker in the typing box ---------------------------------------------
  // It asks Grandpa's own /model list (the same one as F6 in the terminal), so the
  // installed models and Grandpa's roles come from one place.
  function openModelMenu() {
    if (state !== "idle" || !modelMenu.hidden) { closeModelMenu(); return; }
    modelMenu.textContent = ""; modelMenu.appendChild(el("div", "wait", "Loading models…"));
    modelMenu.hidden = false; picking = true;
    quietly("/model", [/^\/model$/]);
  }
  function fillModelMenu(options) {
    modelMenu.textContent = "";
    options.forEach((opt) => {
      const text = String(opt);
      const current = text.trim().startsWith("*");
      const parts = text.replace(/^\s*\*?\s*/, "").match(/^(\S+)\s+(.*)$/) || [null, text.trim(), ""];
      const b = el("button", current ? "current" : ""); b.type = "button"; b.setAttribute("role", "menuitem");
      b.appendChild(el("span", "name", parts[1]));
      b.appendChild(el("span", "about", parts[2]));
      b.addEventListener("click", () => { picking = false; modelMenu.hidden = true; quietly(opt, [], [/^Model (changed|unchanged)/]); input.focus(); });
      modelMenu.appendChild(b);
    });
  }
  function closeModelMenu() {
    if (modelMenu.hidden) return;
    modelMenu.hidden = true;
    if (!picking) return;
    picking = false;
    const waiting = pending.findIndex((p) => p.text === "/model");
    if (waiting >= 0) { pending.splice(waiting, 1); return; }   // never sent
    quiet.push({ re: /^Model unchanged/ });
    if (state === "asking") cancel(); else ignoreModelAsk = true; // the list is still coming
  }
  modelBtn.addEventListener("click", (e) => { e.stopPropagation(); openModelMenu(); });

  // --- state ----------------------------------------------------------------------------
  function setState(next) {
    if (next === "thinking" && state !== "thinking") busySince = Date.now();
    state = next; app.dataset.state = next;
    sendBtn.hidden = next === "thinking";
    stopBtn.hidden = next !== "thinking";
    sendBtn.disabled = next === "starting" || next === "stopped";
    modelBtn.disabled = next !== "idle" && !picking;
    micBtn.disabled = next === "starting" || next === "stopped";
    if (next !== "idle") { awaiting = false; clearTimeout(awaitTimer); } else { ownBusy = false; pump(); }
    tick();
  }
  function tick() {
    let words = WORDS[state] || state;
    if (state === "thinking" && busySince) words += " " + Math.round((Date.now() - busySince) / 1000) + "s";
    statusLine.textContent = socket && socket.readyState === WebSocket.OPEN ? words : "Connecting…";
  }
  setInterval(tick, 1000);

  // --- sending ---------------------------------------------------------------------------
  function send(obj) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(obj)); return true;
  }
  function sendRaw(text) { return send({ type: "send", text: String(text).slice(0, 2000) }); }
  function cancel() { send({ type: "cancel" }); }
  // Grandpa takes one message at a time, so lines wait here until it is idle.
  // Our own commands (/clear, /model ...) go the same way without showing up.
  const pending = [];
  let awaiting = false, awaitTimer = 0, ownBusy = false;
  function pump() {
    if (state !== "idle" || awaiting || !pending.length) return;
    awaiting = true;
    const next = pending.shift();
    ownBusy = next.own;
    sendRaw(next.text);
    clearTimeout(awaitTimer);
    awaitTimer = setTimeout(() => { awaiting = false; pump(); }, 4000); // never stuck
  }
  function queue(text, own) { if (state === "asking") sendRaw(text); else { pending.push({ text, own: !!own }); pump(); } }
  function quietly(text, hideUser, hideReplies, toastIt) {
    (hideUser || [new RegExp("^" + text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$")]).forEach((re) => quiet.push({ re }));
    (hideReplies || []).forEach((re) => quiet.push({ re, toast: toastIt !== false }));
    queue(text, true);
  }
  function swallowed(msg) {
    const i = quiet.findIndex((q) => q.re.test(String(msg.text || "")));
    if (i < 0) return false;
    if (quiet[i].toast) toast(String(msg.text).split("\n")[0]);
    quiet.splice(i, 1);
    return true;
  }

  function submit() {
    const typed = input.value.trim();
    if (!typed && !attached.length) return;
    // Busy with our own /clear or /model? Then the message just waits its turn.
    const ownWork = ownBusy || (pending.length && pending.every((p) => p.own));
    if ((state === "thinking" && !ownWork) || state === "starting") { toast("Grandpa is still busy — Esc stops it."); return; }
    const mentions = attached.map((p) => '@"' + p + '"').join(" ");
    const text = (typed + (mentions ? (typed ? "\n" : "") + mentions : "")).trim();
    if (text.length > 2000) { toast("That message is too long (2000 characters at most).", true); return; }
    if (!socket || socket.readyState !== WebSocket.OPEN) { toast("Not connected to Grandpa yet.", true); return; }
    queue(text); input.value = ""; attached = []; drawAttachments(); grow();
  }
  function grow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 220) + "px"; }
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || e.altKey) return;
    const sends = settings.enter ? !e.shiftKey : e.ctrlKey;
    if (sends) { e.preventDefault(); submit(); }
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  stopBtn.addEventListener("click", cancel);
  document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => { input.value = chip.textContent; submit(); }));

  // 📎 attach: Windows' own file dialog; only the path comes back.
  function drawAttachments() {
    const box = $("attachments"); box.textContent = "";
    attached.forEach((p, i) => {
      const chip = el("span", "file"); chip.title = p;
      chip.appendChild(el("span", "", "📄 " + baseName(p)));
      const x = el("button", "", "✕"); x.type = "button"; x.title = "Remove";
      x.addEventListener("click", () => { attached.splice(i, 1); drawAttachments(); });
      chip.appendChild(x); box.appendChild(chip);
    });
  }
  function addFiles() {
    closePlus();
    const a = api();
    if (!a) { toast("Adding files works in the Grandpa window.", true); return; }
    const pick = a.pick_files ? a.pick_files() : a.pick_file().then((p) => (p ? [p] : []));
    pick.then((paths) => {
      let skipped = 0;
      (paths || []).forEach((path) => {
        path = String(path);
        if (attached.includes(path)) return;
        if (attached.length >= 5) { skipped += 1; return; }
        attached.push(path);
      });
      if (skipped) toast("Five files at most per message.", true);
      drawAttachments(); input.focus();
    }).catch(() => toast("Couldn't open the file picker.", true));
  }
  attachBtn.addEventListener("click", addFiles);

  // ＋ menu: add files, voice typing, show the orb.
  const plusMenu = $("plus-menu");
  function closePlus() { plusMenu.hidden = true; }
  $("plus").addEventListener("click", (e) => { e.stopPropagation(); closeModelMenu(); plusMenu.hidden = !plusMenu.hidden; });
  $("plus-voice").addEventListener("click", () => { closePlus(); micBtn.click(); });
  $("plus-orb").addEventListener("click", () => {
    closePlus();
    const a = api();
    if (!a || !a.open_orb) return;
    a.open_orb().then((r) => toast(r === "running" ? "The orb is already on screen." : r === "started" ? "Opening the orb…" : "Couldn't open the orb.", r === "failed"))
      .catch(() => toast("Couldn't open the orb.", true));
  });

  // 🎤 voice typing: Grandpa listens for one sentence; the words land in the box.
  function listening(on) { micBtn.classList.toggle("on", on); app.classList.toggle("listening", on); micBtn.title = on ? "Listening… click to stop" : "Voice typing: say one sentence"; }
  micBtn.addEventListener("click", () => { if (send({ type: "talk" })) { if (micBtn.classList.contains("on")) listening(false); } });

  // --- chats ----------------------------------------------------------------------------
  function freshEngine() {
    // Grandpa forgets the previous conversation (our /clear is not shown) and,
    // if the settings name one, starts on the chosen model.
    quietly("/clear", null, [/^Conversation cleared/], false);
    if (settings.model) quietly("/model " + settings.model, null, [/^Model (changed|unchanged)|is not installed/]);
  }
  function newChat(projectId) {
    if (incognito) setIncognito(false);
    const chat = currentChat();
    if (!chat.messages.length && (projectId || null) === (chat.project || null)) { input.focus(); return; }
    if (!chat.messages.length) { chat.project = projectId || null; save(); redraw(); input.focus(); return; }
    db.current = null;
    const fresh = currentChat(); fresh.project = projectId || null;
    if (projectId) expanded.add(projectId);
    save(); redraw(); freshEngine(); input.focus();
    if (narrow.matches) app.classList.remove("side-open-small");
  }
  function switchTo(id) {
    if (incognito) setIncognito(false, true);
    else if (id === db.current) return;
    // an empty "New chat" left behind is not worth keeping
    const old = db.chats.find((c) => c.id === db.current);
    if (old && !old.messages.length && old.id !== id) db.chats = db.chats.filter((c) => c !== old);
    db.current = id; save(); redraw(); freshEngine();
    if (narrow.matches) app.classList.remove("side-open-small");
  }
  function removeChat(id) {
    db.chats = db.chats.filter((c) => c.id !== id);
    if (db.current === id && !incognito) { db.current = null; currentChat(); freshEngine(); }
    save(); redraw();
  }
  $("new-chat").addEventListener("click", () => newChat(null));

  // 🕶 incognito: a chat that is never stored; Grandpa starts fresh and forgets it after.
  function setIncognito(on, quietSwitch) {
    if (on === !!incognito) return;
    incognito = on ? { id: "incognito", title: "Incognito chat", messages: [] } : null;
    $("incognito").setAttribute("aria-pressed", on ? "true" : "false");
    $("incognito-banner").hidden = !on;
    app.classList.toggle("incognito", on);
    redraw();
    if (!quietSwitch) freshEngine();
    if (!on && !quietSwitch) { db.current = null; currentChat(); save(); redraw(); }
    input.focus();
  }
  $("incognito").addEventListener("click", () => setIncognito(!incognito));

  // --- left panel open / close -------------------------------------------------------------
  function togglePanel() {
    if (narrow.matches) app.classList.toggle("side-open-small");
    else { app.classList.toggle("side-closed"); try { localStorage.setItem("grandpa.side", app.classList.contains("side-closed") ? "closed" : "open"); } catch (_) { /* ignore */ } }
  }
  try { if (localStorage.getItem("grandpa.side") === "closed") app.classList.add("side-closed"); } catch (_) { /* ignore */ }
  $("side-close").addEventListener("click", togglePanel);
  $("side-open").addEventListener("click", togglePanel);

  // --- settings page -----------------------------------------------------------------------------
  function syncSettingsForm() {
    $("set-name").value = profile ? profile.name || "" : settings.name || "";
    $("set-title").value = profile ? profile.title || "" : "";
    $("set-email").value = profile ? profile.email || "" : "";
    $("set-title").disabled = $("set-email").disabled = !profile;
    $("profile-msg").textContent = "";
    $("set-model").value = settings.model || "";
    $("set-enter").checked = settings.enter !== false;
    document.querySelectorAll("#set-theme button").forEach((b) => b.classList.toggle("on", b.dataset.v === settings.theme));
    document.querySelectorAll("#set-size button").forEach((b) => b.classList.toggle("on", b.dataset.v === settings.size));
  }
  function showTab(name) {
    document.querySelectorAll("#settings-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll("#settings-box .tab").forEach((t) => { t.hidden = t.dataset.tab !== name; });
  }
  function openSettings(welcome) {
    syncSettingsForm(); showTab("profile");
    $("profile-welcome").hidden = welcome !== true;
    $("settings").hidden = false; $("set-name").focus();
  }
  function closeSettings() { $("settings").hidden = true; input.focus(); }
  $("open-settings").addEventListener("click", () => openSettings());
  $("settings-close").addEventListener("click", closeSettings);
  $("settings").addEventListener("click", (e) => { if (e.target === $("settings")) closeSettings(); });
  document.querySelectorAll("#settings-tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  function saveProfile() {
    const a = api();
    const msg = $("profile-msg");
    if (!a || !a.save_profile || !profile) {        // browser tab: the page keeps the name
      settings.name = $("set-name").value.trim().slice(0, 40); saveSettings(); applySettings(); redraw();
      msg.textContent = "Saved"; return;
    }
    a.save_profile($("set-title").value, $("set-name").value, $("set-email").value).then((r) => {
      if (!r || !r.ok) { msg.textContent = (r && r.error) || "Couldn't save."; msg.style.color = "var(--red)"; return; }
      profile = r; msg.style.color = ""; msg.textContent = "Saved ✓";
      settings.name = String(r.display || r.name || "").slice(0, 48); saveSettings(); applySettings(); redraw();
      $("profile-welcome").hidden = true;
    }).catch(() => { msg.textContent = "Couldn't save."; });
  }
  $("save-profile").addEventListener("click", saveProfile);
  ["set-name", "set-email"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveProfile(); } }));
  $("set-model").addEventListener("change", () => { settings.model = $("set-model").value.trim().replace(/[^\w.:\-]/g, "").slice(0, 60); saveSettings(); syncSettingsForm(); });
  $("set-enter").addEventListener("change", () => { settings.enter = $("set-enter").checked; saveSettings(); });
  document.querySelectorAll("#set-theme button").forEach((b) => b.addEventListener("click", () => { settings.theme = b.dataset.v; saveSettings(); applySettings(); syncSettingsForm(); }));
  document.querySelectorAll("#set-size button").forEach((b) => b.addEventListener("click", () => { settings.size = b.dataset.v; saveSettings(); applySettings(); syncSettingsForm(); }));
  $("export-chats").addEventListener("click", () => {
    const data = JSON.stringify({ exported: new Date().toISOString(), projects: db.projects, chats: db.chats }, null, 2);
    const url = URL.createObjectURL(new Blob([data], { type: "application/json" }));
    const a = el("a"); a.href = url; a.download = "grandpa-chats-" + new Date().toISOString().slice(0, 10) + ".json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    if (navigator.clipboard) navigator.clipboard.writeText(data).then(() => toast("Exported (also copied to the clipboard)")).catch(() => toast("Exported"));
  });
  $("delete-chats").addEventListener("click", () => {
    confirmBox("Delete every chat and project?", "This removes them from this PC and can't be undone.").then((ok) => {
      if (!ok) return;
      db = { current: null, chats: [], projects: [] }; currentChat(); save(); redraw(); freshEngine();
      toast("All chats deleted");
    });
  });

  // --- keys ------------------------------------------------------------------------------
  document.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    if (e.key === "Escape") {
      if (dialogDone) return dialogDone(null);
      if (!$("settings").hidden) return closeSettings();
      if (openMenu) return closeMenu();
      if (!modelMenu.hidden) return closeModelMenu();
      if (!$("plus-menu").hidden) { $("plus-menu").hidden = true; return; }
      if (state === "thinking") cancel();
      return;
    }
    if (e.key === "F6") { e.preventDefault(); openModelMenu(); }
    if (!e.ctrlKey) return;
    if (key === "t") { e.preventDefault(); toggleTheme(); }
    if (key === "n") { e.preventDefault(); newChat(null); }
    if (key === "b") { e.preventDefault(); togglePanel(); }
    if (key === ",") { e.preventDefault(); openSettings(); }
  });

  // --- the connection ------------------------------------------------------------------------
  function onMessage(msg) {
    if (msg.type === "state") return setState(msg.state);
    if (msg.type === "model") {
      modelName = String(msg.name).replace(/:latest$/, "").replace(/^grandpa-/, "");
      modelBtn.textContent = modelName.charAt(0).toUpperCase() + modelName.slice(1);
      modelBtn.title = "Model: " + msg.name + " (F6 to switch)";
      return;
    }
    if (msg.type === "ask") return question(msg);
    if (msg.type === "listening") return listening(true);
    if (msg.type === "heard") {
      listening(false);
      if (msg.error) return toast(msg.error, true);
      const words = String(msg.text || "").trim();
      if (!words) return toast("Didn't catch that — try again.", true);
      input.value = (input.value.trim() ? input.value.trimEnd() + " " : "") + words;
      grow(); input.focus();
      return;
    }
    if (msg.type === "user" || msg.type === "reply" || msg.type === "note") {
      // Skip what this window already has (a reconnect replays the run).
      if (msg.run) {
        if (db.lastRun === msg.run && msg.seq <= (db.lastSeq || 0)) return;
        db.lastRun = msg.run; db.lastSeq = msg.seq; if (!incognito) save();
      }
      if (swallowed(msg)) return;
      if (msg.type === "reply" && busySince) msg.secs = ((Date.now() - busySince) / 1000).toFixed(1);
      keep(msg);
    }
  }
  function connect() {
    if (!address) { statusLine.textContent = "No connection address."; return; }
    socket = new WebSocket(address);
    socket.onopen = () => { retry = 500; tick(); };
    socket.onmessage = (event) => {
      let msg; try { msg = JSON.parse(event.data); } catch (_) { return; }
      onMessage(msg);
    };
    socket.onclose = () => { statusLine.textContent = "Reconnecting…"; setTimeout(connect, retry); retry = Math.min(retry * 2, 8000); };
  }
  window.grandpaConnect = function (url) { if (socket || !url) return; address = url; connect(); };

  // A chat opened earlier starts fresh in Grandpa only when the user picks another one,
  // so a restart keeps showing the last chat without re-sending anything.
  applySettings(); currentChat(); redraw(); setState("starting");
  if (api()) windowReady(); else { attachBtn.disabled = true; $("plus-orb").disabled = true; }
  if (address) connect(); else statusLine.textContent = "Waiting for Grandpa…";
  input.focus();
})();
