// Grandpa desktop app: renders what Python sends; sends typed lines back.
// The WebSocket URL (with its per-run token) arrives from the window
// (window.grandpaConnect) or, in a browser tab, in the page hash (#ws=...).
// Chats are kept in this window's localStorage (on this PC only).
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const app = $("app"), feed = $("feed"), list = $("messages"), input = $("input");
  const sendBtn = $("send"), stopBtn = $("stop"), statusLine = $("status"), modelBtn = $("model");
  const chatsList = $("chats");

  const STORE = "grandpa.chats.v1", THEME = "grandpa.theme";
  const WORDS = { starting: "Starting…", idle: "Ready", thinking: "Thinking…", asking: "Waiting for your answer", stopped: "Stopped" };
  let socket = null, retry = 500, state = "starting", busySince = 0;
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");
  let hideNext = 0; // replies to our own /clear are not shown

  // --- storage ------------------------------------------------------------
  function load() {
    try { return JSON.parse(localStorage.getItem(STORE)) || { current: null, chats: [] }; }
    catch (_) { return { current: null, chats: [] }; }
  }
  let db = load();
  function save() { try { localStorage.setItem(STORE, JSON.stringify(db)); } catch (_) { /* full or blocked */ } }
  function currentChat() {
    let chat = db.chats.find((c) => c.id === db.current);
    if (!chat) {
      chat = { id: String(Date.now()), title: "New chat", at: Date.now(), messages: [] };
      db.chats.unshift(chat); db.current = chat.id; save();
    }
    return chat;
  }

  // --- theme ---------------------------------------------------------------
  function setTheme(name) {
    document.documentElement.dataset.theme = name;
    try { localStorage.setItem(THEME, name); } catch (_) { /* ignore */ }
  }
  try { setTheme(localStorage.getItem(THEME) || "dark"); } catch (_) { setTheme("dark"); }
  $("theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

  // --- drawing -------------------------------------------------------------
  function time(at) {
    const t = document.createElement("time");
    t.textContent = new Date(at || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return t;
  }
  function label(who, at, extra) {
    const row = document.createElement("div");
    row.className = "label";
    row.appendChild(document.createTextNode(who));
    row.appendChild(time(at));
    if (extra) { const s = document.createElement("time"); s.textContent = extra; row.appendChild(s); }
    return row;
  }
  function draw(msg) {
    const li = document.createElement("li");
    if (msg.type === "user") {
      li.className = "msg-user";
      li.appendChild(label("You", msg.at));
      const b = document.createElement("div"); b.className = "bubble"; b.textContent = msg.text; li.appendChild(b);
    } else if (msg.type === "reply") {
      li.className = "msg-grandpa";
      li.appendChild(label("Grandpa", msg.at, msg.secs ? "· " + msg.secs + "s" : ""));
      const body = document.createElement("div"); body.className = "body";
      body.appendChild(window.GrandpaMarkdown.render(msg.text, msg.format !== "text"));
      li.appendChild(body);
      const tools = document.createElement("div"); tools.className = "tools";
      const copy = document.createElement("button"); copy.type = "button"; copy.textContent = "Copy";
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
    currentChat().messages.forEach(draw);
    drawChats();
  }
  function drawChats() {
    chatsList.textContent = "";
    db.chats.forEach((chat) => {
      const li = document.createElement("li");
      if (chat.id === db.current) li.className = "current";
      const open = document.createElement("button"); open.type = "button"; open.className = "open";
      open.textContent = chat.title; open.title = chat.title;
      open.addEventListener("click", () => switchTo(chat.id));
      const del = document.createElement("button"); del.type = "button"; del.className = "del";
      del.textContent = "✕"; del.title = "Delete this chat (from this PC)";
      del.addEventListener("click", (e) => { e.stopPropagation(); removeChat(chat.id); });
      li.appendChild(open); li.appendChild(del); chatsList.appendChild(li);
    });
  }
  function keep(msg) {
    const chat = currentChat();
    const stored = Object.assign({ at: Date.now() }, msg); delete stored.v;
    chat.messages.push(stored);
    if (msg.type === "user" && chat.title === "New chat") chat.title = msg.text.slice(0, 40);
    chat.messages = chat.messages.slice(-300);
    save(); draw(stored);
    if (msg.type === "user") drawChats();
  }

  // --- questions -----------------------------------------------------------
  function ask(msg) {
    const li = document.createElement("li");
    li.className = "msg-ask";
    const p = document.createElement("p"); p.textContent = msg.prompt; li.appendChild(p);
    const box = document.createElement("div"); box.className = "choices";
    const answer = (value) => {
      li.classList.add("done"); box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      sendRaw(value);
    };
    if (msg.kind === "confirm") {
      [["Yes", "yes", "yes"], ["No", "no", "no"]].forEach(([text, cls, value]) => {
        const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = text;
        b.addEventListener("click", () => answer(value)); box.appendChild(b);
      });
    } else if (msg.kind === "choose") {
      msg.options.forEach((opt) => {
        const b = document.createElement("button"); b.type = "button"; b.className = "option"; b.textContent = opt;
        b.addEventListener("click", () => answer(opt)); box.appendChild(b);
      });
    } else {
      const hint = document.createElement("span"); hint.className = "hint";
      hint.textContent = "Type your answer below and press Enter."; box.appendChild(hint);
      setTimeout(() => input.focus(), 30);
    }
    li.appendChild(box); list.appendChild(li); app.classList.add("has-messages");
    feed.scrollTop = feed.scrollHeight;
  }

  // --- state -----------------------------------------------------------------
  function setState(next) {
    if (next === "thinking" && state !== "thinking") busySince = Date.now();
    state = next; app.dataset.state = next;
    const busy = next === "thinking" || next === "starting";
    sendBtn.hidden = busy && next !== "starting";
    stopBtn.hidden = next !== "thinking";
    sendBtn.disabled = next === "starting" || next === "stopped";
    modelBtn.disabled = next !== "idle";
    tick();
  }
  function tick() {
    let words = WORDS[state] || state;
    if (state === "thinking" && busySince) words += " " + Math.round((Date.now() - busySince) / 1000) + "s";
    statusLine.textContent = socket && socket.readyState === WebSocket.OPEN ? words : "Connecting…";
  }
  setInterval(tick, 1000);

  // --- sending ---------------------------------------------------------------
  function sendRaw(text) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({ type: "send", text: String(text).slice(0, 2000) }));
    return true;
  }
  function submit() {
    const text = input.value.trim();
    if (!text) return;
    if (state !== "idle" && state !== "asking") return;
    if (sendRaw(text)) { input.value = ""; grow(); }
  }
  function grow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 200) + "px"; }
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.altKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  stopBtn.addEventListener("click", () => { if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "cancel" })); });
  modelBtn.addEventListener("click", () => { if (state === "idle") sendRaw("/model"); });
  document.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => {
    input.value = chip.textContent; submit();
  }));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state === "thinking") stopBtn.click();
    if (e.key === "F6") { e.preventDefault(); modelBtn.click(); }
    if (e.ctrlKey && (e.key === "t" || e.key === "T")) { e.preventDefault(); $("theme").click(); }
    if (e.ctrlKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); newChat(); }
  });

  // --- chats -------------------------------------------------------------------
  function freshEngine() {
    // Grandpa forgets the previous conversation; our own /clear is not shown.
    if (state === "idle" && sendRaw("/clear")) hideNext = 2;
  }
  function newChat() {
    const chat = currentChat();
    if (!chat.messages.length) { input.focus(); return; }
    db.current = null; currentChat(); redraw(); freshEngine(); input.focus();
  }
  function switchTo(id) {
    if (id === db.current) return;
    db.current = id; save(); redraw(); freshEngine();
  }
  function removeChat(id) {
    db.chats = db.chats.filter((c) => c.id !== id);
    if (db.current === id) { db.current = null; currentChat(); freshEngine(); }
    save(); redraw();
  }
  $("new-chat").addEventListener("click", newChat);

  // --- the connection ----------------------------------------------------------
  function onMessage(msg) {
    if (msg.type === "state") return setState(msg.state);
    if (msg.type === "model") { modelBtn.textContent = "Model: " + String(msg.name).replace(/:latest$/, ""); return; }
    if (msg.type === "ask") return ask(msg);
    if (msg.type === "user" || msg.type === "reply" || msg.type === "note") {
      if (hideNext > 0 && (msg.text === "/clear" || /^Conversation cleared/.test(msg.text))) { hideNext -= 1; return; }
      if (msg.type === "reply" && busySince) msg.secs = ((Date.now() - busySince) / 1000).toFixed(1);
      keep(msg);
    }
  }
  function connect() {
    if (!address) { statusLine.textContent = "No connection address."; return; }
    socket = new WebSocket(address);
    let first = true;
    socket.onopen = () => { retry = 500; tick(); };
    socket.onmessage = (event) => {
      let msg; try { msg = JSON.parse(event.data); } catch (_) { return; }
      // On (re)connect Python replays its conversation; our stored copy is
      // already on screen, so only the live state is taken from the replay.
      if (first && (msg.type === "user" || msg.type === "reply" || msg.type === "note")) return;
      if (msg.type === "state") first = false;
      onMessage(msg);
    };
    socket.onclose = () => { statusLine.textContent = "Reconnecting…"; setTimeout(connect, retry); retry = Math.min(retry * 2, 8000); };
  }
  window.grandpaConnect = function (url) { if (socket || !url) return; address = url; connect(); };

  currentChat(); redraw(); setState("starting");
  if (address) connect(); else statusLine.textContent = "Waiting for Grandpa…";
  input.focus();
})();
