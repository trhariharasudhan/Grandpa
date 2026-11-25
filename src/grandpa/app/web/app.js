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
  const plusMenu = $("plus-menu");
  const icon = (name, size) => window.GrandpaIcons.make(name, size);
  const narrow = window.matchMedia("(max-width: 860px)");
  const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");

  const STORE = "grandpa.chats.v1", SETTINGS = "grandpa.settings.v1";
  const WORDS = { starting: "Starting…", idle: "", thinking: "Thinking…", asking: "Waiting for your answer", stopped: "Stopped" };
  let socket = null, retry = 500, state = "starting", busySince = 0;
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");
  let incognito = null;          // the incognito chat while it is on (never stored)
  let attached = [];             // file paths for the next message
  let picking = false;           // the model menu is waiting for Grandpa's list
  let ignoreModelAsk = false;    // the menu was closed before the list came
  // Grandpa's own conversation starts empty in a new app run and after each
  // /clear. The chat's earlier messages (and its project's instructions) go
  // with the next message, so an old chat continues where it left off.
  let contextPending = true;
  const quiet = [];              // replies to our own commands: [{re, toast}]

  // --- storage -------------------------------------------------------------
  function read(key, fallback) {
    try { return Object.assign(fallback, JSON.parse(localStorage.getItem(key)) || {}); }
    catch (_) { return fallback; }
  }
  let db = read(STORE, { current: null, chats: [], projects: [] });
  if (!Array.isArray(db.projects)) db.projects = [];
  let settings = read(SETTINGS, { name: "", theme: "", size: "m", model: "", enter: true, stream: true });
  try { if (!settings.theme) settings.theme = localStorage.getItem("grandpa.theme") || "dark"; } catch (_) { settings.theme = "dark"; }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(db)); } catch (_) { toast("Couldn't save the chat list (storage full?)", true); } }
  function saveSettings() { try { localStorage.setItem(SETTINGS, JSON.stringify(settings)); } catch (_) { /* ignore */ } }
  function newId() { return String(Date.now()) + Math.random().toString(36).slice(2, 6); }
  function project(id) { return db.projects.find((p) => p.id === id) || null; }

  function currentChat() {
    if (incognito) return incognito;
    let chat = db.chats.find((c) => c.id === db.current);
    if (!chat) {
      chat = { id: newId(), title: "New chat", at: Date.now(), project: null, pinned: false, messages: [] };
      db.chats.unshift(chat); db.current = chat.id; save();
    }
    return chat;
  }

  // --- helpers ---------------------------------------------------------------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function iconButton(name, title, onClick, cls) {
    const b = el("button", cls || ""); b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
    b.appendChild(icon(name, 16));
    b.addEventListener("click", onClick);
    return b;
  }
  // A file sent from a browser tab is saved as "<date>-<time>-<name>"; show <name>.
  function baseName(path) {
    const name = String(path).split(/[\\/]/).pop() || String(path);
    return /[\\/]uploads[\\/]/i.test(String(path)) ? name.replace(/^\d{8}-\d{6}-/, "") : name;
  }
  function ago(at) {
    const s = Math.round((Date.now() - (at || 0)) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return new Date(at).toLocaleDateString();
  }
  function copyText(text, button) {
    const done = (ok) => {
      if (!button) return toast(ok ? "Copied" : "Couldn't copy", !ok);
      button.textContent = ""; button.appendChild(icon(ok ? "check" : "warning", 16));
      setTimeout(() => { button.textContent = ""; button.appendChild(icon("copy", 16)); }, 1400);
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
    else done(false);
  }
  let toastTimer = 0;
  function toast(text, bad) {
    const t = $("toast"); t.textContent = text; t.className = bad ? "bad" : ""; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2800);
  }

  // --- look & profile ----------------------------------------------------------
  function greeting() {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  }
  function applySettings() {
    const mode = settings.theme === "system" ? (darkScheme.matches ? "dark" : "light") : settings.theme;
    document.documentElement.dataset.theme = mode === "light" ? "light" : "dark";
    document.documentElement.dataset.size = ["s", "m", "l"].includes(settings.size) ? settings.size : "m";
    const name = settings.name || "You";
    $("user-name").textContent = name;
    $("avatar").textContent = name.replace(/^(Mr|Ms|Mrs|Mx)\.\s+/i, "").trim().charAt(0).toUpperCase() || "?";
    $("hello").textContent = settings.name ? greeting() + ", " + settings.name : "What shall we do?";
  }
  darkScheme.addEventListener("change", () => { if (settings.theme === "system") applySettings(); });
  function toggleTheme() {
    settings.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    saveSettings(); applySettings(); syncSettingsForm();
  }

  // In the window the name comes from Grandpa's own profile (the same one the
  // terminal uses); in a plain browser tab it is kept in this page.
  let profile = null;
  // In a browser tab there is no pywebview bridge: the same methods are
  // called over the socket (Grandpa lists the ones a tab may use).
  let wsApi = null, nextCall = 1;
  const calls = new Map();
  function makeWsApi(methods) {
    const out = {};
    (methods || []).forEach((name) => {
      if (typeof name !== "string") return;
      out[name] = (...args) => new Promise((resolve, reject) => {
        if (!socket || socket.readyState !== 1) { reject(new Error("Not connected")); return; }
        const id = nextCall++;
        calls.set(id, { resolve, reject });
        socket.send(JSON.stringify({ type: "api", id, method: name, args }));
      });
    });
    return out;
  }
  function failCalls() { calls.forEach((c) => c.reject(new Error("Disconnected"))); calls.clear(); }
  function api() { return window.pywebview && window.pywebview.api ? window.pywebview.api : wsApi; }
  const inBrowser = () => !(window.pywebview && window.pywebview.api) && !!wsApi;
  function windowReady() {
    const a = api();
    attachBtn.disabled = !a;
    $("plus-orb").disabled = !(a && a.open_orb);
    if (!a || !a.get_profile) return;
    a.get_profile().then((p) => {
      profile = p || null;
      if (profile && profile.display) { settings.name = String(profile.display).slice(0, 48); saveSettings(); applySettings(); redraw(); }
      if (profile && !profile.onboarded) openSettings(true);
    }).catch(() => { /* keep the page's own name */ });
  }
  window.addEventListener("pywebviewready", windowReady);

  // --- views -------------------------------------------------------------------
  let viewProject = null;
  function setView(view, arg) {
    closeMenu(); closePops();
    app.dataset.view = view;
    $("chat-view").hidden = false;
    document.querySelectorAll(".view.page").forEach((page) => { page.hidden = page.id !== view + "-view"; });
    document.querySelectorAll(".nav-item[data-goto]").forEach((b) => {
      b.classList.toggle("active", b.dataset.goto === view || (b.dataset.goto === "projects" && view === "project"));
    });
    if (view === "projects") drawProjects();
    if (view === "project") { viewProject = arg; drawProject(); }
    if (view === "memory") loadMemories();
    if (view === "skills") loadSkills();
    if (view === "connectors") loadConnectors();
    if (view === "models") loadModels();
    if (view === "chat") setTimeout(() => input.focus(), 30);
    if (narrow.matches) app.classList.remove("side-open-small");
  }
  document.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.goto)));

  // --- drawing messages ----------------------------------------------------------
  const MENTION = /@"([^"]+)"|@(\S+)/g;
  function userText(msg) {
    const files = (msg.attached || []).filter(Boolean);
    let text = msg.text;
    if (files.length) text = text.replace(MENTION, (all, q, plain) => (files.includes(q || plain) ? "" : all)).trim();
    return text;
  }
  function fileChip(path, onRemove) {
    const chip = el("span", "file"); chip.title = path;
    chip.appendChild(icon("file", 14));
    chip.appendChild(el("span", "", baseName(path)));
    if (onRemove) chip.appendChild(iconButton("close", "Remove", onRemove));
    return chip;
  }
  function draw(msg, index) {
    const li = el("li");
    li.dataset.index = String(index);
    if (msg.type === "user") {
      li.className = "msg-user";
      const files = (msg.attached || []).filter(Boolean);
      if (files.length) {
        const row = el("div", "files");
        files.forEach((f) => row.appendChild(fileChip(f)));
        li.appendChild(row);
      }
      const text = userText(msg);
      if (text) li.appendChild(el("div", "bubble", text));
      const actions = el("div", "actions");
      actions.appendChild(iconButton("copy", "Copy", (e) => copyText(text, e.currentTarget)));
      actions.appendChild(iconButton("edit", "Edit and send again", () => editMessage(li, index), "edit-btn"));
      li.appendChild(actions);
    } else if (msg.type === "reply") {
      li.className = "msg-grandpa";
      const body = el("div", "body");
      body.appendChild(window.GrandpaMarkdown.render(msg.text, msg.format !== "text"));
      li.appendChild(body);
      const actions = el("div", "actions");
      actions.appendChild(iconButton("copy", "Copy", (e) => copyText(msg.text, e.currentTarget)));
      actions.appendChild(iconButton("retry", "Retry", () => retryLast(), "retry-btn"));
      const when = new Date(msg.at || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      actions.appendChild(el("span", "meta", when + (msg.secs ? " · " + msg.secs + "s" : "") + (msg.model ? " · " + msg.model : "")));
      li.appendChild(actions);
    } else if (msg.type === "note") {
      li.className = "msg-note" + (msg.failed ? " failed" : "");
      li.textContent = msg.text;
    } else return null;
    list.appendChild(li);
    return li;
  }
  // Only the last message of each kind can be edited or retried.
  function markLast() {
    const items = Array.from(list.children);
    items.forEach((li) => li.classList.remove("last"));
    const lastUser = items.filter((li) => li.classList.contains("msg-user")).pop();
    const lastReply = items.filter((li) => li.classList.contains("msg-grandpa") && !li.classList.contains("streaming")).pop();
    items.forEach((li) => {
      const edit = li.querySelector(".edit-btn"); if (edit) edit.hidden = li !== lastUser;
      const again = li.querySelector(".retry-btn"); if (again) again.hidden = li !== lastReply;
    });
    if (lastReply && lastReply === items[items.length - 1]) lastReply.classList.add("last");
  }
  function updateEmpty() {
    const chat = currentChat();
    app.classList.toggle("empty", !chat.messages.length && !list.children.length);
  }
  function redraw() {
    list.textContent = "";
    const chat = currentChat();
    chat.messages.forEach((m, i) => draw(m, i));
    markLast();
    updateEmpty();
    const p = chat.project ? project(chat.project) : null;
    $("title").textContent = incognito ? "Incognito chat" : chat.title + (p ? "  ·  " + p.name : "");
    $("project-hint").hidden = !p;
    $("project-hint").textContent = p ? "In the project " + p.name + (p.instructions ? " · its instructions go with your first message" : "") : "";
    drawSidebar();
    feed.scrollTop = feed.scrollHeight;
  }
  function keep(msg) {
    const chat = currentChat();
    const stored = Object.assign({ at: Date.now() }, msg);
    delete stored.v; delete stored.run; delete stored.seq;
    chat.messages.push(stored);
    chat.messages = chat.messages.slice(-300);
    if (msg.type === "user" && chat.title === "New chat") {
      chat.title = (userText(msg) || "Files").slice(0, 48);
      const p = chat.project ? project(chat.project) : null;
      $("title").textContent = incognito ? "Incognito chat" : chat.title + (p ? "  ·  " + p.name : "");
    }
    chat.at = Date.now();
    if (!incognito) { save(); if (msg.type === "user") drawSidebar(); }
    draw(stored, chat.messages.length - 1);
    markLast(); updateEmpty();
    feed.scrollTop = feed.scrollHeight;
  }

  // --- streaming and "thinking" ------------------------------------------------------
  let liveLi = null, liveText = "", liveTimer = 0, thinkingLi = null;
  function showThinking() {
    if (thinkingLi || liveLi) return;
    thinkingLi = el("li", "thinking");
    const m = el("span", "mark"); thinkingLi.appendChild(m);
    thinkingLi.appendChild(el("span", "", "Thinking…"));
    list.appendChild(thinkingLi); updateEmpty();
    feed.scrollTop = feed.scrollHeight;
  }
  function hideThinking() { if (thinkingLi) { thinkingLi.remove(); thinkingLi = null; } }
  function renderLive() {
    liveTimer = 0;
    if (!liveLi) return;
    const body = liveLi.firstChild; body.textContent = "";
    body.appendChild(window.GrandpaMarkdown.render(liveText, true));
    const near = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 120;
    if (near) feed.scrollTop = feed.scrollHeight;
  }
  function onDelta(msg) {
    if (msg.reset) { dropLive(); return; }
    if (settings.stream === false) return;
    hideThinking();
    if (!liveLi) {
      liveLi = el("li", "msg-grandpa streaming");
      liveLi.appendChild(el("div", "body"));
      list.appendChild(liveLi); liveText = ""; updateEmpty();
    }
    liveText += String(msg.text || "");
    if (!liveTimer) liveTimer = setTimeout(renderLive, 80);
  }
  function dropLive() { if (liveLi) { liveLi.remove(); liveLi = null; liveText = ""; } clearTimeout(liveTimer); liveTimer = 0; }

  // --- left panel ---------------------------------------------------------------------
  function matches(chat, needle) {
    if (!needle) return true;
    if (chat.title.toLowerCase().includes(needle)) return true;
    return chat.messages.some((m) => String(m.text || "").toLowerCase().includes(needle));
  }
  function chatRow(chat, withTag) {
    const li = el("li");
    const row = el("div", "row" + (!incognito && chat.id === db.current && app.dataset.view === "chat" ? " current" : ""));
    const open = el("button", "open", chat.title); open.type = "button"; open.title = chat.title;
    open.addEventListener("click", () => switchTo(chat.id));
    row.appendChild(open);
    const p = withTag && chat.project ? project(chat.project) : null;
    if (p) row.appendChild(el("span", "tag", p.name));
    const more = iconButton("more", "Rename, pin, move or delete", (e) => { e.stopPropagation(); chatMenu(chat, more); }, "more");
    row.appendChild(more); li.appendChild(row);
    return li;
  }
  function drawSidebar() {
    const pinned = $("pinned"), chats = $("chats");
    pinned.textContent = ""; chats.textContent = "";
    const byTime = db.chats.filter((c) => c.messages.length).sort((a, b) => (b.at || 0) - (a.at || 0));
    const pins = byTime.filter((c) => c.pinned);
    pins.forEach((c) => pinned.appendChild(chatRow(c, true)));
    $("pinned-section").hidden = !pins.length;
    const rest = byTime.filter((c) => !c.pinned).slice(0, 60);
    rest.forEach((c) => chats.appendChild(chatRow(c, true)));
    if (!rest.length) chats.appendChild(el("li", "empty", "Your chats will show here"));
  }

  // a small menu next to something
  let openMenu = null;
  function closeMenu() { if (openMenu) { openMenu.remove(); openMenu = null; } }
  function showMenu(anchor, items, above) {
    closeMenu();
    const menu = el("div", "menu"); menu.setAttribute("role", "menu");
    items.forEach((item) => {
      if (item === "-") { menu.appendChild(el("div", "sep")); return; }
      if (item.head) { menu.appendChild(el("div", "head", item.head)); return; }
      const b = el("button", item.danger ? "danger" : ""); b.type = "button";
      if (item.icon) b.appendChild(icon(item.icon, 16));
      b.appendChild(el("span", "", item.text));
      b.addEventListener("click", () => { closeMenu(); item.run(); });
      menu.appendChild(b);
    });
    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)) + "px";
    const top = above ? r.top - menu.offsetHeight - 6 : r.bottom + 4;
    menu.style.top = Math.max(8, Math.min(top, window.innerHeight - menu.offsetHeight - 8)) + "px";
    openMenu = menu;
  }
  function closePops() { plusMenu.hidden = true; if (!modelMenu.hidden) closeModelMenu(); }
  document.addEventListener("click", (e) => {
    if (openMenu && !openMenu.contains(e.target)) closeMenu();
    if (!modelMenu.hidden && !modelMenu.contains(e.target) && !modelBtn.contains(e.target)) closeModelMenu();
    if (!plusMenu.hidden && !plusMenu.contains(e.target) && !$("plus").contains(e.target)) plusMenu.hidden = true;
  });

  function chatMenu(chat, anchor) {
    const items = [
      { text: "Rename", icon: "edit", run: () => ask({ title: "Rename chat", value: chat.title }).then((v) => { if (v) { chat.title = v.slice(0, 60); save(); redraw(); } }) },
      { text: chat.pinned ? "Unpin" : "Pin", icon: "pin", run: () => { chat.pinned = !chat.pinned; save(); drawSidebar(); } },
      "-", { head: "Move to project" },
    ];
    db.projects.forEach((p) => { if (chat.project !== p.id) items.push({ text: p.name, icon: "folder", run: () => { chat.project = p.id; save(); redraw(); } }); });
    if (chat.project) items.push({ text: "Remove from project", icon: "close", run: () => { chat.project = null; save(); redraw(); } });
    items.push({ text: "New project…", icon: "folder-plus", run: () => newProject().then((p) => { if (p) { chat.project = p.id; save(); redraw(); } }) });
    items.push("-", { text: "Delete", icon: "trash", danger: true, run: () => confirmBox("Delete this chat?", "“" + chat.title + "” is removed from this PC.").then((ok) => { if (ok) removeChat(chat.id); }) });
    showMenu(anchor, items);
  }
  $("title-button").addEventListener("click", (e) => {
    e.stopPropagation();
    if (incognito) return toast("Incognito chats aren't kept, so there's nothing to rename or move.");
    const chat = currentChat();
    if (!chat.messages.length) return toast("Send a message first.");
    chatMenu(chat, $("title-button"));
  });
  $("user-button").addEventListener("click", (e) => {
    e.stopPropagation();
    showMenu($("user-button"), [
      { text: "Settings", icon: "settings", run: () => openSettings() },
      { text: "Memory", icon: "memory", run: () => setView("memory") },
      { text: "Show the orb", icon: "orb", run: showOrb },
      { text: document.documentElement.dataset.theme === "dark" ? "Light mode" : "Dark mode", icon: document.documentElement.dataset.theme === "dark" ? "sun" : "moon", run: toggleTheme },
      { text: "Keyboard shortcuts", icon: "command", run: () => { openSettings(); showTab("keys"); } },
    ], true);
  });

  // --- projects --------------------------------------------------------------------------
  function newProject() {
    return ask({ title: "New project", text: "A folder for related chats, with its own instructions.", value: "", placeholder: "Project name" }).then((name) => {
      if (!name) return null;
      const p = { id: newId(), name: name.slice(0, 40), at: Date.now(), instructions: "" };
      db.projects.push(p); save();
      if (app.dataset.view === "projects") setView("project", p.id);
      return p;
    });
  }
  $("new-project").addEventListener("click", newProject);
  function drawProjects() {
    const grid = $("project-grid"); grid.textContent = "";
    db.projects.slice().sort((a, b) => (b.at || 0) - (a.at || 0)).forEach((p) => {
      const n = db.chats.filter((c) => c.project === p.id && c.messages.length).length;
      const card = el("button", "card"); card.type = "button";
      const t = el("p", "card-title"); t.appendChild(icon("folder", 16)); t.appendChild(el("span", "", p.name)); card.appendChild(t);
      card.appendChild(el("p", "hint", p.instructions || "No instructions yet."));
      card.appendChild(el("span", "hint", n + (n === 1 ? " chat" : " chats")));
      card.addEventListener("click", () => setView("project", p.id));
      grid.appendChild(card);
    });
    if (!db.projects.length) grid.appendChild(el("p", "empty", "No projects yet. Create one to group chats and give Grandpa standing instructions."));
  }
  function drawProject() {
    const p = project(viewProject);
    if (!p) return setView("projects");
    $("project-name").textContent = p.name;
    $("project-instructions").value = p.instructions || "";
    $("instructions-msg").textContent = "";
    const ol = $("project-chats"); ol.textContent = "";
    const chats = db.chats.filter((c) => c.project === p.id && c.messages.length).sort((a, b) => (b.at || 0) - (a.at || 0));
    chats.forEach((c) => {
      const li = chatRow(c, false);
      li.querySelector(".row").insertBefore(el("span", "when", ago(c.at)), li.querySelector(".more"));
      ol.appendChild(li);
    });
    if (!chats.length) ol.appendChild(el("li", "empty", "No chats in this project yet."));
  }
  $("back-projects").addEventListener("click", () => setView("projects"));
  $("project-new-chat").addEventListener("click", () => newChat(viewProject));
  $("save-instructions").addEventListener("click", () => {
    const p = project(viewProject); if (!p) return;
    p.instructions = $("project-instructions").value.trim().slice(0, 4000); save();
    $("instructions-msg").textContent = "Saved";
  });
  $("project-name").addEventListener("dblclick", () => {
    const p = project(viewProject); if (!p) return;
    ask({ title: "Rename project", value: p.name }).then((v) => { if (v) { p.name = v.slice(0, 40); save(); drawProject(); drawSidebar(); } });
  });

  // --- memory page ----------------------------------------------------------------------
  let memories = [];
  function loadMemories() {
    const a = api(); const ol = $("memory-list"); ol.textContent = "";
    if (!a || !a.list_memories) { ol.appendChild(el("li", "empty", "Memory is available in the Grandpa window.")); return; }
    ol.appendChild(el("li", "empty", "Loading…"));
    a.list_memories().then((items) => { memories = items || []; drawMemories(); }).catch(() => { ol.textContent = ""; ol.appendChild(el("li", "empty", "Couldn't read the memory.")); });
  }
  function drawMemories() {
    const ol = $("memory-list"); ol.textContent = "";
    const needle = $("memory-filter").value.trim().toLowerCase();
    const shown = memories.filter((m) => !needle || (m.key + " " + m.value + " " + m.category).toLowerCase().includes(needle));
    shown.forEach((m) => {
      const li = el("li", "memory-item");
      const text = el("div", "text");
      text.appendChild(el("div", "", m.value));
      text.appendChild(el("div", "cat", (m.category || "memory") + " · " + ago((m.updated_at || 0) * 1000)));
      li.appendChild(text);
      li.appendChild(iconButton("trash", "Forget this", () => confirmBox("Forget this?", m.value).then((ok) => {
        if (!ok) return;
        api().forget_memory(m.id).then((done) => { if (done) { memories = memories.filter((x) => x.id !== m.id); drawMemories(); toast("Forgotten"); } else toast("Couldn't forget it.", true); });
      }), "icon-btn"));
      ol.appendChild(li);
    });
    if (!shown.length) ol.appendChild(el("li", "empty", needle ? "Nothing matches." : "Grandpa doesn't remember anything yet. Tell him in a chat (“remember that I like tea”) or add a note above."));
  }
  $("memory-filter").addEventListener("input", drawMemories);
  $("memory-add").addEventListener("submit", (e) => {
    e.preventDefault();
    const a = api(); const text = $("memory-text").value.trim();
    if (!a || !text) return;
    a.add_memory(text).then((ok) => { if (ok) { $("memory-text").value = ""; loadMemories(); toast("Remembered"); } else toast("Couldn't save it.", true); });
  });

  // --- skills -------------------------------------------------------------------------------
  let skills = { yours: [], builtin: [] };
  let activeSkill = null;   // {name, instructions} for the next message
  function setSkill(skill) {
    activeSkill = skill;
    const box = $("skill-chip"); box.textContent = ""; box.hidden = !skill;
    if (!skill) return;
    const chip = el("span", "file"); chip.appendChild(icon("spark", 14));
    chip.appendChild(el("span", "", "Skill: " + skill.name));
    chip.appendChild(iconButton("close", "Don't use this skill", () => setSkill(null)));
    box.appendChild(chip);
  }
  function loadSkills(then) {
    const a = api();
    if (!a || !a.list_skills) { drawSkills(); return; }
    a.list_skills().then((r) => { skills = r || skills; drawSkills(); if (then) then(); }).catch(() => drawSkills());
  }
  function drawSkills() {
    const grid = $("skill-grid"); grid.textContent = "";
    if (!api()) grid.appendChild(el("p", "empty", "Skills are available in the Grandpa window."));
    skills.yours.forEach((sk) => {
      const card = el("div", "card");
      const t = el("p", "card-title"); t.appendChild(icon("spark", 16)); t.appendChild(el("span", "", sk.name)); card.appendChild(t);
      card.appendChild(el("p", "hint", sk.description || sk.instructions.slice(0, 140)));
      const row = el("div", "card-actions");
      const use = el("button", "", "Use"); use.type = "button";
      use.addEventListener("click", () => { setSkill(sk); setView("chat"); toast("The skill goes with your next message."); });
      const edit = el("button", "", "Edit"); edit.type = "button";
      edit.addEventListener("click", () => openSkillForm(sk));
      const del = el("button", "danger", "Delete"); del.type = "button";
      del.addEventListener("click", () => confirmBox("Delete the skill \u201c" + sk.name + "\u201d?", "Its SKILL.md is removed from this PC.").then((ok) => {
        if (ok) api().delete_skill(sk.name).then(() => loadSkills());
      }));
      row.appendChild(use); row.appendChild(edit); row.appendChild(del); card.appendChild(row);
      grid.appendChild(card);
    });
    if (api() && !skills.yours.length) grid.appendChild(el("p", "empty", "No skills yet. Make one for something you ask often: \u201cpolish my email\u201d, \u201creview my code like a senior dev\u201d."));
    const built = $("builtin-grid"); built.textContent = "";
    skills.builtin.forEach((sk) => {
      const card = el("div", "card"); card.appendChild(el("p", "card-title", sk.name));
      card.appendChild(el("p", "hint", sk.description)); built.appendChild(card);
    });
  }
  function openSkillForm(sk) {
    $("skill-form").hidden = false;
    $("skill-name").value = sk ? sk.name : ""; $("skill-description").value = sk ? sk.description : "";
    $("skill-instructions").value = sk ? sk.instructions : ""; $("skill-msg").textContent = "";
    $("skill-name").focus();
  }
  $("new-skill").addEventListener("click", () => openSkillForm(null));
  $("skill-cancel").addEventListener("click", () => { $("skill-form").hidden = true; });
  $("skill-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const a = api(); if (!a) return;
    a.save_skill($("skill-name").value, $("skill-description").value, $("skill-instructions").value).then((r) => {
      if (!r || !r.ok) { $("skill-msg").textContent = (r && r.error) || "Couldn't save."; return; }
      $("skill-form").hidden = true; toast("Skill saved"); loadSkills();
    });
  });
  $("import-skill").addEventListener("click", () => {
    const a = api(); if (!a || !a.import_skill) return toast("Importing a skill file works in the Grandpa window. Here, use New skill.", true);
    a.import_skill().then((r) => { if (r && r.ok) { toast("Imported " + r.name); loadSkills(); } else if (r && r.error) toast(r.error, true); });
  });
  function pickSkill() {
    plusMenu.hidden = true;
    loadSkills(() => {
      if (!skills.yours.length) { setView("skills"); return toast("Make a skill first."); }
      showMenu($("plus"), skills.yours.map((sk) => ({ text: sk.name, icon: "spark", run: () => { setSkill(sk); input.focus(); } })), true);
    });
  }
  $("plus-skill").addEventListener("click", (e) => { e.stopPropagation(); pickSkill(); });

  // --- connectors (MCP) --------------------------------------------------------------------------
  const MCP_PRESETS = [
    { label: "GitHub", name: "github", command: "npx -y @modelcontextprotocol/server-github", key: "GITHUB_PERSONAL_ACCESS_TOKEN", allow: "search_repositories, get_file_contents, list_issues, get_issue" },
    { label: "Files (a folder)", name: "files", command: "npx -y @modelcontextprotocol/server-filesystem D:/Notes", key: "", allow: "read_text_file, list_directory, search_files" },
    { label: "Fetch web pages", name: "fetch", command: "uvx mcp-server-fetch", key: "", allow: "fetch" },
    { label: "Memory graph", name: "memory-graph", command: "npx -y @modelcontextprotocol/server-memory", key: "", allow: "*" },
    { label: "Brave Search", name: "brave", command: "npx -y @modelcontextprotocol/server-brave-search", key: "BRAVE_API_KEY", allow: "brave_web_search" },
  ];
  function loadConnectors() {
    const a = api(); const grid = $("mcp-grid"); grid.textContent = "";
    const presets = $("mcp-presets"); presets.textContent = "";
    MCP_PRESETS.forEach((p) => {
      const b = el("button", "", p.label); b.type = "button";
      b.addEventListener("click", () => { $("mcp-name").value = p.name; $("mcp-command").value = p.command; $("mcp-allow").value = p.allow; $("mcp-key-name").value = p.key; $("mcp-key-value").focus(); });
      presets.appendChild(b);
    });
    if (!a || !a.mcp_status) { grid.appendChild(el("p", "empty", "Connectors are available in the Grandpa window.")); return; }
    a.mcp_status().then((st) => {
      $("mcp-on").checked = !st.off;
      $("mcp-problems").hidden = !st.problems.length; $("mcp-problems").textContent = st.problems.join("\n");
      st.servers.forEach((srv) => {
        const card = el("div", "card");
        const t = el("p", "card-title");
        t.appendChild(el("span", "status-dot " + (srv.enabled && !st.off ? "on" : "off")));
        t.appendChild(el("span", "", srv.name)); card.appendChild(t);
        card.appendChild(el("p", "mono", srv.command));
        card.appendChild(el("p", "hint", "May use: " + (srv.allow.join(", ") || "nothing yet") + (srv.env.length ? " · keys: " + srv.env.join(", ") : "")));
        const row = el("div", "card-actions");
        const test = el("button", "", "Test"); test.type = "button";
        test.addEventListener("click", () => { test.textContent = "Testing…"; a.mcp_test(srv.name).then((r) => {
          test.textContent = "Test";
          if (r.ok) toast(srv.name + ": OK, " + r.tools.length + " tools, " + r.allowed.length + " allowed"); else toast(r.error, true);
        }); });
        const toggle = el("button", "", srv.enabled ? "Turn off" : "Turn on"); toggle.type = "button";
        toggle.addEventListener("click", () => a.mcp_toggle_server(srv.name, !srv.enabled).then(loadConnectors));
        const edit = el("button", "", "Edit"); edit.type = "button";
        edit.addEventListener("click", () => { $("mcp-name").value = srv.name; $("mcp-command").value = srv.command; $("mcp-allow").value = srv.allow.join(", "); $("mcp-key-name").value = srv.env[0] || ""; $("mcp-key-value").value = ""; $("mcp-name").focus(); });
        const del = el("button", "danger", "Remove"); del.type = "button";
        del.addEventListener("click", () => confirmBox("Remove the connector \u201c" + srv.name + "\u201d?", "Its stored keys are deleted too.").then((ok) => { if (ok) a.mcp_remove_server(srv.name).then(loadConnectors); }));
        row.appendChild(test); row.appendChild(toggle); row.appendChild(edit); row.appendChild(del); card.appendChild(row);
        grid.appendChild(card);
      });
      if (!st.servers.length) grid.appendChild(el("p", "empty", "No connectors yet. Pick one below to start."));
    });
  }
  $("mcp-on").addEventListener("change", () => { const a = api(); if (a) a.mcp_set_off(!$("mcp-on").checked).then(loadConnectors); });
  $("mcp-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const a = api(); if (!a) return;
    const keys = {};
    const keyName = $("mcp-key-name").value.trim();
    if (keyName) keys[keyName] = $("mcp-key-value").value;
    dialog({ title: "Add this connector?", text: "Grandpa will start this program on your PC: " + $("mcp-command").value, ok: "Add" }).then((ok) => {
      if (ok === null) return;
      a.mcp_save_server($("mcp-name").value, $("mcp-command").value, $("mcp-allow").value, keys).then((r) => {
        if (!r.ok) { $("mcp-msg").textContent = r.error; return; }
        $("mcp-msg").textContent = "Saved"; $("mcp-key-value").value = ""; loadConnectors();
      });
    });
  });

  // --- models & API keys ------------------------------------------------------------------------------
  let providerInfo = null;
  function loadModels() {
    const a = api(); const grid = $("provider-grid"); grid.textContent = "";
    if (!a || !a.providers_status) { grid.appendChild(el("p", "empty", "Available in the Grandpa window.")); return; }
    a.providers_status().then((st) => {
      providerInfo = st;
      $("key-store").textContent = st.store;
      const select = $("provider-preset"); select.textContent = "";
      st.presets.forEach((p) => { const o = el("option", "", p.label); o.value = p.id; select.appendChild(o); });
      const custom = el("option", "", "Other (OpenAI-compatible)"); custom.value = "custom"; select.appendChild(custom);
      presetChanged();
      st.providers.forEach((p) => {
        const card = el("div", "card");
        const t = el("p", "card-title"); t.appendChild(el("span", "status-dot " + (!p.needs_key || p.has_key ? "on" : "off"))); t.appendChild(el("span", "", p.label)); card.appendChild(t);
        card.appendChild(el("p", "mono", p.base_url));
        card.appendChild(el("p", "hint", (p.models.length ? p.models.map((m) => "@" + p.id + "/" + m).join(", ") : "No models chosen yet") + (p.needs_key && !p.has_key ? " · no key" : "")));
        const row = el("div", "card-actions");
        const edit = el("button", "", "Edit"); edit.type = "button";
        edit.addEventListener("click", () => { select.value = st.presets.some((x) => x.id === p.id) ? p.id : "custom"; presetChanged(); $("provider-id").value = p.id; $("provider-url").value = p.base_url; $("provider-models").value = p.models.join(", "); $("provider-key").value = ""; $("provider-key").placeholder = p.has_key ? "key saved (leave empty to keep it)" : "paste the key"; });
        const del = el("button", "danger", "Remove"); del.type = "button";
        del.addEventListener("click", () => confirmBox("Remove " + p.label + "?", "Its key is deleted from this PC.").then((ok) => { if (ok) a.provider_remove(p.id).then(loadModels); }));
        row.appendChild(edit); row.appendChild(del); card.appendChild(row);
        grid.appendChild(card);
      });
      if (!st.providers.length) grid.appendChild(el("p", "empty", "Only local models so far."));
    });
  }
  function presetChanged() {
    const id = $("provider-preset").value;
    const preset = providerInfo && providerInfo.presets.find((p) => p.id === id);
    $("provider-url").value = preset ? preset.base_url : "";
    $("provider-id-row").hidden = !!preset;
    $("provider-key").placeholder = preset && !preset.needs_key ? "no key needed" : "paste the key (stored encrypted)";
    $("provider-found").hidden = true;
  }
  $("provider-preset").addEventListener("change", presetChanged);
  function saveProvider(fetchModels) {
    const a = api(); if (!a) return;
    const preset = $("provider-preset").value;
    const id = preset === "custom" ? $("provider-id").value.trim().toLowerCase() : preset;
    $("provider-msg").textContent = "Saving…";
    a.provider_save(id, $("provider-url").value, $("provider-key").value, $("provider-models").value).then((r) => {
      if (!r.ok) { $("provider-msg").textContent = r.error; return; }
      $("provider-key").value = "";
      $("provider-msg").textContent = "Saved";
      loadModels();
      if (!fetchModels) return;
      $("provider-msg").textContent = "Asking the provider for its models…";
      a.provider_models(id).then((m) => {
        if (!m.ok) { $("provider-msg").textContent = m.error; return; }
        $("provider-msg").textContent = m.models.length + " models: click to add or remove, then Save";
        const box = $("provider-found"); box.textContent = ""; box.hidden = false;
        const chosen = () => $("provider-models").value.split(",").map((x) => x.trim()).filter(Boolean);
        m.models.forEach((name) => {
          const b = el("button", chosen().includes(name) ? "on" : "", name); b.type = "button";
          b.addEventListener("click", () => {
            const now = chosen(); const i = now.indexOf(name);
            if (i >= 0) now.splice(i, 1); else now.push(name);
            $("provider-models").value = now.join(", "); b.classList.toggle("on", i < 0);
          });
          box.appendChild(b);
        });
      });
    });
  }
  $("provider-form").addEventListener("submit", (e) => { e.preventDefault(); saveProvider(false); });
  $("provider-fetch").addEventListener("click", () => saveProvider(true));
  $("open-models").addEventListener("click", () => { closeSettings(); setView("models"); });

  // --- small dialog (rename, new project, confirm) -----------------------------------------
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

  // --- questions from Grandpa (confirm / choose / type) ----------------------------------------
  function question(msg) {
    if (msg.kind === "choose" && msg.prompt === "Switch model") {
      if (picking) return fillModelMenu(msg.options);
      if (ignoreModelAsk) { ignoreModelAsk = false; cancel(); return; }
    }
    hideThinking(); dropLive();
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
    li.appendChild(box); list.appendChild(li); updateEmpty();
    feed.scrollTop = feed.scrollHeight;
  }

  // --- the model picker in the typing box ----------------------------------------------------------
  // It asks Grandpa's own /model list (the same one as F6 in the terminal).
  let modelName = "";
  function openModelMenu() {
    if (state !== "idle" || !modelMenu.hidden) { closeModelMenu(); return; }
    plusMenu.hidden = true;
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
      const words = el("span");
      words.appendChild(el("span", "name", parts[1]));
      words.appendChild(el("small", "", parts[2]));
      b.appendChild(words);
      b.addEventListener("click", () => { picking = false; modelMenu.hidden = true; quietly(opt, [], [/^Model (changed|unchanged)/]); input.focus(); });
      modelMenu.appendChild(b);
    });
    const manage = el("button", ""); manage.type = "button";
    manage.appendChild(icon("key", 16));
    const words = el("span"); words.appendChild(el("span", "name", "Models & API keys…")); words.appendChild(el("small", "", "Add Groq, OpenAI, Gemini, OpenRouter…"));
    manage.appendChild(words);
    manage.addEventListener("click", () => { closeModelMenu(); setView("models"); });
    modelMenu.appendChild(manage);
  }
  function closeModelMenu() {
    if (modelMenu.hidden) return;
    modelMenu.hidden = true;
    if (!picking) return;
    picking = false;
    const waiting = pending.findIndex((p) => p.text === "/model");
    if (waiting >= 0) { pending.splice(waiting, 1); return; }   // never sent
    quiet.push({ re: /^Model unchanged/ });
    if (state === "asking") cancel(); else ignoreModelAsk = true;  // the list is still coming
  }
  modelBtn.addEventListener("click", (e) => { e.stopPropagation(); openModelMenu(); });

  // --- state -----------------------------------------------------------------------------------------
  function setState(next) {
    if (next === "thinking" && state !== "thinking") busySince = Date.now();
    state = next; app.dataset.state = next;
    sendBtn.hidden = next === "thinking";
    stopBtn.hidden = next !== "thinking";
    sendBtn.disabled = next === "starting" || next === "stopped";
    modelBtn.disabled = next !== "idle" && !picking;
    micBtn.disabled = next === "starting" || next === "stopped";
    if (next === "thinking" && !ownBusy) showThinking();
    if (next !== "thinking") hideThinking();
    if (next !== "idle") { awaiting = false; clearTimeout(awaitTimer); } else { ownBusy = false; dropLive(); pump(); }
    tick();
  }
  function tick() {
    let words = WORDS[state] || "";
    if (state === "thinking" && busySince) words += " " + Math.round((Date.now() - busySince) / 1000) + "s";
    statusLine.textContent = socket && socket.readyState === WebSocket.OPEN ? words : "Connecting…";
  }
  setInterval(tick, 1000);

  // --- sending -------------------------------------------------------------------------------------------
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
  function escapeRe(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  function quietly(text, hideUser, hideReplies, toastIt) {
    (hideUser || [new RegExp("^" + escapeRe(text) + "$")]).forEach((re) => quiet.push({ re }));
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
  const CONTEXT_CHARS = 7000, MESSAGE_CHARS = 900;
  function contextFor(chat, upto) {
    const parts = [];
    const p = !incognito && chat.project ? project(chat.project) : null;
    if (p && p.instructions) parts.push("Project instructions (follow them):\n" + p.instructions);
    const earlier = chat.messages.slice(0, upto === undefined ? chat.messages.length : upto)
      .filter((m) => m.type === "user" || m.type === "reply");
    const lines = [];
    let used = 0;
    for (let i = earlier.length - 1; i >= 0 && used < CONTEXT_CHARS - 1200; i -= 1) {
      const m = earlier[i];
      let text = String(m.type === "user" ? userText(m) : m.text).replace(/\s+\n/g, "\n").trim();
      if (text.length > MESSAGE_CHARS) text = text.slice(0, MESSAGE_CHARS) + " …";
      lines.unshift((m.type === "user" ? "User: " : "Grandpa: ") + text);
      used += text.length + 10;
    }
    if (lines.length) parts.push("Earlier in this chat (continue from here):\n" + lines.join("\n"));
    return parts.join("\n\n").slice(0, CONTEXT_CHARS);
  }
  function withContext(then, upto) {
    const a = api();
    const skill = activeSkill;
    if ((!contextPending && !skill) || !a || !a.set_next_context) { contextPending = false; return then(); }
    const parts = [];
    if (contextPending) { const history = contextFor(currentChat(), upto); if (history) parts.push(history); }
    contextPending = false;
    if (skill) { parts.push("Use the skill \u201c" + skill.name + "\u201d for this message:\n" + skill.instructions); setSkill(null); }
    if (!parts.length) return then();
    a.set_next_context(parts.join("\n\n").slice(0, 7900)).then(then, then);
  }
  // Send a line again without showing it twice (retry, edit). Grandpa starts
  // fresh with the chat up to that message, so the old answer doesn't linger.
  function resend(text, upto) {
    quietly("/clear", null, [/^Conversation cleared/], false);
    contextPending = true;
    quiet.push({ re: new RegExp("^" + escapeRe(text) + "$") });
    withContext(() => queue(text), upto);
  }

  function submit() {
    const typed = input.value.trim();
    if (!typed && !attached.length) return;
    const ownWork = ownBusy || (pending.length && pending.every((p) => p.own));
    if ((state === "thinking" && !ownWork) || state === "starting") { toast("Grandpa is still busy. Esc stops him."); return; }
    const mentions = attached.map((p) => '@"' + p + '"').join(" ");
    const text = (typed + (mentions ? (typed ? "\n" : "") + mentions : "")).trim();
    if (text.length > 2000) { toast("That message is too long (2000 characters at most).", true); return; }
    if (!socket || socket.readyState !== WebSocket.OPEN) { toast("Not connected to Grandpa yet.", true); return; }
    if (state === "asking") { queue(text); }
    else withContext(() => queue(text));
    input.value = ""; attached = []; drawAttachments(); grow();
  }
  function grow() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 240) + "px";
    input.style.overflowY = input.scrollHeight > 240 ? "auto" : "hidden";
  }
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || e.altKey) return;
    const sends = settings.enter !== false ? !e.shiftKey : e.ctrlKey;
    if (sends) { e.preventDefault(); submit(); }
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  stopBtn.addEventListener("click", cancel);
  document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => { input.value = chip.dataset.text; submit(); }));

  // retry the last reply; edit the last message
  function lastUserIndex(chat) {
    for (let i = chat.messages.length - 1; i >= 0; i -= 1) if (chat.messages[i].type === "user") return i;
    return -1;
  }
  function retryLast() {
    if (state !== "idle") return toast("Wait for Grandpa to finish first.");
    const chat = currentChat();
    const i = lastUserIndex(chat);
    if (i < 0) return;
    const text = chat.messages[i].text;
    chat.messages = chat.messages.slice(0, i + 1);
    if (!incognito) save();
    redraw();
    resend(text, i);
  }
  function editMessage(li, index) {
    if (state !== "idle") return toast("Wait for Grandpa to finish first.");
    const chat = currentChat();
    const msg = chat.messages[index];
    if (!msg || msg.type !== "user") return;
    const box = el("div", "edit-box");
    const area = el("textarea"); area.value = msg.text; box.appendChild(area);
    const row = el("div", "row-actions");
    const cancelB = el("button", "", "Cancel"); cancelB.type = "button";
    const saveB = el("button", "primary small", "Send"); saveB.type = "button";
    row.appendChild(cancelB); row.appendChild(saveB); box.appendChild(row);
    li.textContent = ""; li.appendChild(box); area.focus();
    cancelB.addEventListener("click", redraw);
    const go = () => {
      const text = area.value.trim();
      if (!text) return;
      msg.text = text;
      chat.messages = chat.messages.slice(0, index + 1);
      if (!incognito) save();
      redraw();
      resend(text, index);
    };
    saveB.addEventListener("click", go);
    area.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); go(); } if (e.key === "Escape") { e.stopPropagation(); redraw(); } });
  }

  // files: the + menu, the dialog, and drag and drop
  function drawAttachments() {
    const box = $("attachments"); box.textContent = "";
    attached.forEach((p, i) => box.appendChild(fileChip(p, () => { attached.splice(i, 1); drawAttachments(); })));
  }
  function addPaths(paths) {
    let skipped = 0;
    (paths || []).forEach((path) => {
      path = String(path);
      if (!path || attached.includes(path)) return;
      if (attached.length >= 5) { skipped += 1; return; }
      attached.push(path);
    });
    if (skipped) toast("Five files at most per message.", true);
    drawAttachments(); input.focus();
  }
  const MAX_UPLOAD = 10 * 1024 * 1024;
  function uploadFiles(files) {
    const a = api();
    if (!a || !a.upload_file) { toast("Adding files works in the Grandpa window.", true); return; }
    Array.from(files || []).slice(0, 5).forEach((file) => {
      if (file.size > MAX_UPLOAD) { toast(file.name + " is over 10 MB.", true); return; }
      const reader = new FileReader();
      reader.onload = () => {
        const data = String(reader.result || "").replace(/^data:[^,]*,/, "");
        a.upload_file(file.name, data).then((path) => {
          if (path) addPaths([path]); else toast("Couldn't add " + file.name + ".", true);
        }).catch(() => toast("Couldn't add " + file.name + ".", true));
      };
      reader.onerror = () => toast("Couldn't read " + file.name + ".", true);
      reader.readAsDataURL(file);
    });
  }
  const fileInput = document.createElement("input");
  fileInput.type = "file"; fileInput.multiple = true; fileInput.hidden = true;
  document.body.appendChild(fileInput);
  fileInput.addEventListener("change", () => { uploadFiles(fileInput.files); fileInput.value = ""; });
  function addFiles() {
    plusMenu.hidden = true;
    const a = api();
    if (inBrowser()) { fileInput.click(); return; }
    if (!a) { toast("Adding files works in the Grandpa window.", true); return; }
    const pick = a.pick_files ? a.pick_files() : a.pick_file().then((p) => (p ? [p] : []));
    pick.then(addPaths).catch(() => toast("Couldn't open the file picker.", true));
  }
  attachBtn.addEventListener("click", addFiles);
  window.grandpaDropped = (paths) => { $("drop-shade").hidden = true; if (app.dataset.view !== "chat") setView("chat"); addPaths(paths); };
  let dragDepth = 0;
  document.addEventListener("dragenter", (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) { dragDepth += 1; $("drop-shade").hidden = false; } });
  document.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("drop-shade").hidden = true; });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0;
    setTimeout(() => { $("drop-shade").hidden = true; }, 300);
    if (inBrowser()) { if (app.dataset.view !== "chat") setView("chat"); uploadFiles(e.dataTransfer && e.dataTransfer.files); }
    else if (!api()) toast("Dropping files works in the Grandpa window.", true);
  });

  $("plus").addEventListener("click", (e) => { e.stopPropagation(); closeModelMenu(); plusMenu.hidden = !plusMenu.hidden; });
  $("plus-voice").addEventListener("click", () => { plusMenu.hidden = true; micBtn.click(); });
  function showOrb() {
    plusMenu.hidden = true;
    const a = api();
    if (!a || !a.open_orb) return toast("The orb opens from the Grandpa window.");
    a.open_orb().then((r) => toast(r === "running" ? "The orb is already on screen." : r === "started" ? "Opening the orb…" : "Couldn't open the orb.", r === "failed"))
      .catch(() => toast("Couldn't open the orb.", true));
  }
  $("plus-orb").addEventListener("click", showOrb);

  // voice typing: Grandpa listens for one sentence; the words land in the box
  function listening(on) { micBtn.classList.toggle("on", on); app.classList.toggle("listening", on); micBtn.title = on ? "Listening… click to stop" : "Voice typing: say one sentence"; }
  micBtn.addEventListener("click", () => { if (send({ type: "talk" }) && micBtn.classList.contains("on")) listening(false); });

  // --- chats ---------------------------------------------------------------------------------------------
  function freshEngine() {
    // Grandpa forgets the previous conversation (our /clear is not shown) and,
    // if the settings name one, starts on the chosen model.
    quietly("/clear", null, [/^Conversation cleared/], false);
    if (settings.model) quietly("/model " + settings.model, null, [/^Model (changed|unchanged)|is not installed/]);
    contextPending = true;
  }
  function newChat(projectId) {
    if (incognito) setIncognito(false, true);
    setView("chat");
    const chat = currentChat();
    if (!chat.messages.length) { chat.project = projectId || null; save(); redraw(); contextPending = true; input.focus(); return; }
    db.current = null;
    const fresh = currentChat(); fresh.project = projectId || null;
    save(); redraw(); freshEngine(); input.focus();
  }
  function switchTo(id) {
    if (incognito) setIncognito(false, true);
    else if (id === db.current && app.dataset.view === "chat") return;
    const same = id === db.current;
    const old = db.chats.find((c) => c.id === db.current);
    if (old && !old.messages.length && old.id !== id) db.chats = db.chats.filter((c) => c !== old);
    db.current = id; save(); setView("chat"); redraw();
    if (!same) freshEngine();
  }
  function removeChat(id) {
    db.chats = db.chats.filter((c) => c.id !== id);
    if (db.current === id && !incognito) { db.current = null; currentChat(); freshEngine(); }
    save(); redraw();
    if (app.dataset.view === "project") drawProject();
  }
  $("new-chat").addEventListener("click", () => newChat(null));
  $("brand").addEventListener("click", () => newChat(null));

  // incognito: a chat that is never stored; Grandpa starts fresh and forgets it after
  function setIncognito(on, quietSwitch) {
    if (on === !!incognito) return;
    incognito = on ? { id: "incognito", title: "Incognito chat", messages: [] } : null;
    $("incognito").setAttribute("aria-pressed", on ? "true" : "false");
    $("incognito-banner").hidden = !on;
    app.classList.toggle("incognito", on);
    if (!quietSwitch) freshEngine();
    if (!on && !quietSwitch) { db.current = null; currentChat(); save(); }
    setView("chat"); redraw();
  }
  $("incognito").addEventListener("click", () => setIncognito(!incognito));

  // --- left panel open / close -----------------------------------------------------------------------------
  function togglePanel() {
    if (narrow.matches) app.classList.toggle("side-open-small");
    else { app.classList.toggle("side-closed"); try { localStorage.setItem("grandpa.side", app.classList.contains("side-closed") ? "closed" : "open"); } catch (_) { /* ignore */ } }
  }
  try { if (localStorage.getItem("grandpa.side") === "closed") app.classList.add("side-closed"); } catch (_) { /* ignore */ }
  $("side-close").addEventListener("click", togglePanel);
  $("side-open").addEventListener("click", togglePanel);

  // --- search + commands (Ctrl+K) ---------------------------------------------------------------------------------
  const COMMANDS = [
    { text: "New chat", icon: "new-chat", run: () => newChat(null) },
    { text: "New project", icon: "folder-plus", run: () => { setView("projects"); newProject(); } },
    { text: "Projects", icon: "folder", run: () => setView("projects") },
    { text: "Memory", icon: "memory", run: () => setView("memory") },
    { text: "Skills", icon: "spark", run: () => setView("skills") },
    { text: "Connectors", icon: "plug", run: () => setView("connectors") },
    { text: "Models & API keys", icon: "key", run: () => setView("models") },
    { text: "Switch model", icon: "chevron-down", run: () => { setView("chat"); setTimeout(openModelMenu, 50); } },
    { text: "Incognito chat", icon: "incognito", run: () => setIncognito(!incognito) },
    { text: "Show the orb", icon: "orb", run: showOrb },
    { text: "Dark / light mode", icon: "sun", run: toggleTheme },
    { text: "Open or close the panel", icon: "sidebar", run: togglePanel },
    { text: "Settings", icon: "settings", run: () => openSettings() },
  ];
  let paletteItems = [], paletteSel = 0;
  function openPalette() { closeMenu(); closePops(); $("palette").hidden = false; $("palette-input").value = ""; drawPalette(); $("palette-input").focus(); }
  function closePalette() { $("palette").hidden = true; }
  function drawPalette() {
    const needle = $("palette-input").value.trim().toLowerCase();
    const ol = $("palette-list"); ol.textContent = "";
    const cmds = COMMANDS.filter((c) => !needle || c.text.toLowerCase().includes(needle));
    const chats = db.chats.filter((c) => c.messages.length && matches(c, needle)).sort((a, b) => (b.at || 0) - (a.at || 0)).slice(0, 12);
    paletteItems = [];
    const add = (item, kind) => {
      const li = el("li"); const b = el("button"); b.type = "button";
      b.appendChild(icon(item.icon, 16)); b.appendChild(el("span", "", item.text)); b.appendChild(el("span", "kind", kind));
      const index = paletteItems.length;
      b.addEventListener("click", () => { closePalette(); item.run(); });
      b.addEventListener("mousemove", () => { paletteSel = index; markPalette(); });
      li.appendChild(b); ol.appendChild(li); paletteItems.push(b);
    };
    if (chats.length) { ol.appendChild(el("li", "head", needle ? "Chats" : "Recent chats")); chats.forEach((c) => add({ text: c.title, icon: "chat", run: () => switchTo(c.id) }, ago(c.at))); }
    if (cmds.length) { ol.appendChild(el("li", "head", "Commands")); cmds.forEach((c) => add(c, "")); }
    if (!paletteItems.length) ol.appendChild(el("li", "empty", "Nothing matches."));
    paletteSel = 0; markPalette();
  }
  function markPalette() { paletteItems.forEach((b, i) => b.classList.toggle("sel", i === paletteSel)); if (paletteItems[paletteSel]) paletteItems[paletteSel].scrollIntoView({ block: "nearest" }); }
  $("palette-input").addEventListener("input", drawPalette);
  $("palette-input").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); paletteSel = Math.min(paletteItems.length - 1, paletteSel + 1); markPalette(); }
    if (e.key === "ArrowUp") { e.preventDefault(); paletteSel = Math.max(0, paletteSel - 1); markPalette(); }
    if (e.key === "Enter" && paletteItems[paletteSel]) { e.preventDefault(); paletteItems[paletteSel].click(); }
  });
  $("palette").addEventListener("click", (e) => { if (e.target === $("palette")) closePalette(); });
  $("open-search").addEventListener("click", openPalette);

  // --- settings page ------------------------------------------------------------------------------------------------
  function syncSettingsForm() {
    $("set-name").value = profile ? profile.name || "" : settings.name || "";
    $("set-title").value = profile ? profile.title || "" : "";
    $("set-email").value = profile ? profile.email || "" : "";
    $("set-title").disabled = $("set-email").disabled = !profile;
    $("profile-msg").textContent = "";
    $("set-model").value = settings.model || "";
    $("set-enter").checked = settings.enter !== false;
    $("set-stream").checked = settings.stream !== false;
    document.querySelectorAll("#set-theme button").forEach((b) => b.classList.toggle("on", b.dataset.v === settings.theme));
    document.querySelectorAll("#set-size button").forEach((b) => b.classList.toggle("on", b.dataset.v === settings.size));
  }
  function showTab(name) {
    document.querySelectorAll("#settings-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll("#settings-box .tab").forEach((t) => { t.hidden = t.dataset.tab !== name; });
  }
  function openSettings(welcome) {
    closeMenu(); closePops();
    syncSettingsForm(); showTab("profile");
    $("profile-welcome").hidden = welcome !== true;
    $("settings").hidden = false; $("set-name").focus();
  }
  function closeSettings() { $("settings").hidden = true; input.focus(); }
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
      profile = r; msg.style.color = ""; msg.textContent = "Saved";
      settings.name = String(r.display || r.name || "").slice(0, 48); saveSettings(); applySettings(); redraw();
      $("profile-welcome").hidden = true;
    }).catch(() => { msg.textContent = "Couldn't save."; });
  }
  $("save-profile").addEventListener("click", saveProfile);
  ["set-name", "set-email"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveProfile(); } }));
  $("set-model").addEventListener("change", () => { settings.model = $("set-model").value.trim().replace(/[^\w.:\-]/g, "").slice(0, 60); saveSettings(); syncSettingsForm(); });
  $("set-enter").addEventListener("change", () => { settings.enter = $("set-enter").checked; saveSettings(); });
  $("set-stream").addEventListener("change", () => { settings.stream = $("set-stream").checked; saveSettings(); });
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
      db = { current: null, chats: [], projects: [] }; currentChat(); save(); setView("chat"); redraw(); freshEngine();
      toast("All chats deleted");
    });
  });

  // --- keys ----------------------------------------------------------------------------------------------------------------
  document.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    if (e.key === "Escape") {
      if (dialogDone) return dialogDone(null);
      if (!$("palette").hidden) return closePalette();
      if (!$("settings").hidden) return closeSettings();
      if (openMenu) return closeMenu();
      if (!modelMenu.hidden) return closeModelMenu();
      if (!plusMenu.hidden) { plusMenu.hidden = true; return; }
      if (state === "thinking") cancel();
      return;
    }
    if (e.key === "F6") { e.preventDefault(); openModelMenu(); }
    if (!e.ctrlKey) return;
    if (key === "k") { e.preventDefault(); if ($("palette").hidden) openPalette(); else closePalette(); }
    if (key === "t") { e.preventDefault(); toggleTheme(); }
    if (key === "n") { e.preventDefault(); newChat(null); }
    if (key === "b") { e.preventDefault(); togglePanel(); }
    if (key === ",") { e.preventDefault(); openSettings(); }
  });

  // Grandpa couldn't start (most often: Ollama isn't running yet). A card
  // with the reason and a way out; it is not kept in the chat.
  let downCard = null;
  function engineDown(msg) {
    if (downCard) downCard.remove();
    hideThinking(); dropLive();
    downCard = el("li", "msg-ask down");
    downCard.appendChild(el("p", "", msg.ollama
      ? "Grandpa can't reach Ollama, the program that runs the models. It may not be started yet."
      : "Grandpa couldn't start."));
    downCard.appendChild(el("p", "mono", String(msg.reason || "").slice(0, 600)));
    const row = el("div", "choices");
    const retryButton = (label, startOllama) => {
      const b = el("button", startOllama ? "yes" : "", label); b.type = "button";
      b.addEventListener("click", () => {
        const a = api();
        if (!a || !a.restart_engine) return toast("Close and open the app again.", true);
        row.querySelectorAll("button").forEach((x) => { x.disabled = true; });
        b.textContent = startOllama ? "Starting Ollama…" : "Retrying…";
        a.restart_engine(startOllama).then((r) => {
          if (r && r.ok) { downCard.remove(); downCard = null; contextPending = true; toast("Grandpa is starting…"); }
          else { toast((r && r.error) || "Still not working.", true); row.querySelectorAll("button").forEach((x) => { x.disabled = false; }); b.textContent = label; }
        });
      });
      row.appendChild(b);
    };
    if (msg.ollama) retryButton("Start Ollama and retry", true);
    retryButton("Retry", false);
    downCard.appendChild(row);
    list.appendChild(downCard);
    app.classList.remove("empty");
  }

  // --- the connection ----------------------------------------------------------------------------------------------------------
  function onMessage(msg) {
    if (msg.type === "api_methods") { wsApi = makeWsApi(msg.methods); windowReady(); return; }
    if (msg.type === "api_result") {
      const call = calls.get(msg.id); if (!call) return;
      calls.delete(msg.id);
      if (msg.ok) call.resolve(msg.value); else call.reject(new Error(msg.error || "Failed"));
      return;
    }
    if (msg.type === "state") return setState(msg.state);
    if (msg.type === "model") {
      modelName = String(msg.name).replace(/:latest$/, "").replace(/^grandpa-/, "");
      $("model-name").textContent = modelName.charAt(0).toUpperCase() + modelName.slice(1);
      modelBtn.title = "Model: " + msg.name + " (F6 to switch)";
      return;
    }
    if (msg.type === "ask") return question(msg);
    if (msg.type === "delta") return onDelta(msg);
    if (msg.type === "engine_down") return engineDown(msg);
    if (msg.type === "listening") return listening(true);
    if (msg.type === "heard") {
      listening(false);
      if (msg.error) return toast(msg.error, true);
      const words = String(msg.text || "").trim();
      if (!words) return toast("Didn't catch that. Try again.", true);
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
      if (msg.type === "reply") {
        dropLive(); hideThinking();
        if (busySince) msg.secs = ((Date.now() - busySince) / 1000).toFixed(1);
        if (modelName) msg.model = modelName;
      }
      keep(msg);
      if (msg.type === "user" && state === "thinking") showThinking();
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
    socket.onclose = () => { failCalls(); statusLine.textContent = "Reconnecting…"; setTimeout(connect, retry); retry = Math.min(retry * 2, 8000); };
  }
  window.grandpaConnect = function (url) { if (socket || !url) return; address = url; connect(); };

  applySettings(); currentChat(); redraw(); setState("starting");
  if (api()) windowReady(); else { attachBtn.disabled = true; $("plus-orb").disabled = true; }
  if (address) connect(); else statusLine.textContent = "Waiting for Grandpa…";
  input.focus();
})();
