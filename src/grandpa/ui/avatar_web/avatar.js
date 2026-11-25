// Renders what Python says. Never infers a state from text.
// The WebSocket URL (with its per-run token) arrives from the desktop window
// (window.grandpaConnect) or, in a browser tab, in the page's hash:
//   index.html#ws=ws%3A%2F%2F127.0.0.1%3A1234%2Favatar%3Ftoken%3D...
"use strict";

(function () {
  const app = document.getElementById("app");
  const ring = document.getElementById("ring");
  const label = document.getElementById("label");
  const actionLine = document.getElementById("action");
  const history = document.getElementById("history");
  const confirmBox = document.getElementById("confirm");
  const question = document.getElementById("question");
  const form = document.getElementById("entry");
  const input = document.getElementById("text");
  const sendButton = document.getElementById("send");
  const bar = document.getElementById("bar");
  const barStatus = document.getElementById("bar-status");

  const BUSY = new Set(["thinking", "working", "listening"]);
  const DRAG_THRESHOLD = 4; // pixels before a press counts as a drag
  let socket = null;
  let retry = 500;
  let connected = false;
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");

  // A2: the shader ring, when WebGL works. Otherwise the CSS ring stays.
  let glRing = null;
  try {
    glRing = window.GrandpaRing ? window.GrandpaRing.create(document.getElementById("ring-gl")) : null;
  } catch (_) { glRing = null; }
  if (glRing) app.classList.add("gl");
  window.__grandpaRing = glRing; // read by the page tests, never by Python

  // --- the window (pywebview js_api; absent in a browser tab) --------------

  function windowApi() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  function isOpen() {
    return app.dataset.panel === "open";
  }

  function setOpen(open) {
    app.dataset.panel = open ? "open" : "closed";
    ring.setAttribute("aria-expanded", String(open));
    ring.setAttribute("aria-label", open ? "Close Grandpa's chat" : "Open Grandpa's chat");
    if (open) {
      ring.classList.remove("unread");
      setTimeout(() => input.focus(), 50);
    }
    const api = windowApi();
    if (api && api.set_expanded) api.set_expanded(open);
  }

  // A press that moves is a drag and moves the window; one that does not is a
  // click. On the ring a click opens the chat (and the ring hides); the chat's
  // own bar drags the open window and its close button closes the chat, bringing the ring back.
  function draggable(handle, onClick) {
    let press = null;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return; // only the left button drags or clicks
      if (event.target.closest("button") && event.target !== handle) return; // the bar's buttons click normally
      press = { x: event.screenX, y: event.screenY, dragging: false };
      handle.setPointerCapture(event.pointerId);
    });
    handle.addEventListener("pointermove", (event) => {
      if (!press) return;
      const dx = event.screenX - press.x;
      const dy = event.screenY - press.y;
      if (!press.dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      press.dragging = true;
      const api = windowApi();
      if (api && api.move_by && (dx || dy)) {
        api.move_by(Math.round(dx), Math.round(dy));
        press.x = event.screenX;
        press.y = event.screenY;
      }
    });
    handle.addEventListener("pointerup", (event) => {
      if (!press) return; // a right-click, or a press that began elsewhere
      const wasDrag = press.dragging;
      press = null;
      try { handle.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
      if (!wasDrag && onClick) onClick();
    });
  }
  draggable(ring, () => setOpen(true));
  draggable(bar, null);
  document.getElementById("close").addEventListener("click", () => setOpen(false));
  const openApp = document.getElementById("open-app");
  const quitButton = document.getElementById("quit");
  function showOpenApp() {
    const api = windowApi();
    openApp.hidden = !(api && api.open_app);
    quitButton.hidden = !(api && api.quit);
  }
  quitButton.addEventListener("click", () => { const api = windowApi(); if (api && api.quit) api.quit(); });
  window.addEventListener("pywebviewready", showOpenApp);
  showOpenApp();

  // "Hey Grandpa": the mic button shows whether he is listening for it.
  const wakeButton = document.getElementById("wake");
  function drawWake(status) {
    if (!status || !status.available) { wakeButton.hidden = true; return; }
    wakeButton.hidden = false;
    const on = !!status.on;
    wakeButton.classList.toggle("on", on);
    wakeButton.setAttribute("aria-pressed", on ? "true" : "false");
    wakeButton.title = on
      ? "Listening for \u201cHey Grandpa\u201d. Click to stop."
      : (status.error ? "Hey Grandpa is off: " + status.error : "Hey Grandpa is off. Click to listen.");
    const holder = wakeButton.querySelector("[data-icon]");
    holder.setAttribute("data-icon", on ? "mic" : "mic-off");
    if (window.GrandpaIcons) window.GrandpaIcons.fill(wakeButton);
  }
  function loadWake() {
    const api = windowApi();
    if (!api || !api.wake_status) return;
    api.wake_status().then(drawWake).catch(() => { wakeButton.hidden = true; });
  }
  wakeButton.addEventListener("click", () => {
    const api = windowApi();
    if (!api || !api.set_wake) return;
    wakeButton.disabled = true;
    api.set_wake(!wakeButton.classList.contains("on")).then(drawWake)
      .catch(() => {}).then(() => { wakeButton.disabled = false; });
  });
  window.addEventListener("pywebviewready", loadWake);
  loadWake();
  document.getElementById("open-app").addEventListener("click", () => {
    const api = windowApi();
    if (api && api.open_app) api.open_app();
  });
  // A6: a right-click on the ring (or on Grandpa) talks without opening the panel.
  ring.addEventListener("contextmenu", (event) => { event.preventDefault(); talk(); });
  ring.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setOpen(!isOpen()); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) setOpen(false);
  });

  // --- what Python sends ---------------------------------------------------

  function addLine(role, text, failed) {
    const item = document.createElement("li");
    item.className = role + (failed ? " failed" : "");
    item.textContent = text; // text, never HTML
    history.appendChild(item);
    history.scrollTop = history.scrollHeight;
    if (role === "grandpa" && connected && !isOpen()) ring.classList.add("unread");
  }

  function showState(msg) {
    app.dataset.state = msg.state;
    document.documentElement.style.setProperty("--glow", msg.colour || "#E5E7EB");
    if (glRing) glRing.setState(msg);
    // A3: character.js (a module, loaded after this script) follows the state.
    window.__grandpaState = msg;
    document.dispatchEvent(new CustomEvent("grandpa:state", { detail: msg }));
    const words = msg.label || msg.state;
    label.textContent = words;
    ring.title = words;
    barStatus.textContent = msg.state === "working" && msg.action ? words + " · " + msg.action.replace(/_/g, " ") : words;
    actionLine.textContent = msg.state === "working" && msg.action ? msg.action.replace(/_/g, " ") : "";
    const asking = msg.state === "confirm";
    confirmBox.hidden = !asking;
    question.textContent = asking ? msg.question : "";
    if (asking && !isOpen()) setOpen(true); // a question must be seen to be answered
    const busy = BUSY.has(msg.state);
    input.disabled = busy;
    sendButton.disabled = busy;
    input.placeholder = msg.state === "listening" ? "Listening… release the keys when done"
      : "Ask Grandpa · hold Ctrl+Win to talk";
  }

  // A6, click-to-talk: ask Python to listen for one sentence. The message
  // carries nothing; what is heard is routed like typed text.
  function talk() {
    if (!socket || socket.readyState !== WebSocket.OPEN || BUSY.has(app.dataset.state)) return;
    socket.send(JSON.stringify({ type: "talk" }));
  }

  // Clear: the panel empties and Grandpa forgets this conversation.
  let clearing = false;
  document.getElementById("clear").addEventListener("click", () => {
    if (BUSY.has(app.dataset.state)) return;
    clearing = true;
    history.textContent = "";
    send("/clear");
    setTimeout(() => { clearing = false; }, 8000);
  });

  function send(text) {
    const cleaned = (text || "").trim();
    if (!cleaned || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "send", text: cleaned.slice(0, 2000) }));
  }

  function connect() {
    if (!address) { label.textContent = "No connection address."; return; }
    socket = new WebSocket(address);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => { retry = 500; connected = false; history.textContent = ""; };
    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        // A3: Captain's grandpa.glb, already checked by Python. Kept for a
        // character.js that has not loaded yet, then handed over.
        window.__grandpaGlb = event.data;
        document.dispatchEvent(new CustomEvent("grandpa:character", { detail: event.data }));
        return;
      }
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === "state") { showState(msg); connected = true; }
      else if (msg.type === "chat") {
        // our own /clear: its confirmation would only clutter the fresh chat
        if (clearing && msg.role !== "user" && /^Conversation cleared/.test(msg.text)) { clearing = false; return; }
        if (clearing && msg.role === "user" && msg.text === "/clear") return;
        addLine(msg.role, msg.text, msg.failed);
      }
      else if (msg.type === "mode") {
        // A7: over budget (or --orb-only): the ring only, for the rest of the run.
        window.__grandpaMode = msg;
        document.dispatchEvent(new CustomEvent("grandpa:mode", { detail: msg }));
      }
    };
    socket.onclose = () => {
      label.textContent = "Reconnecting...";
      ring.title = "Reconnecting...";
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 8000);
    };
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
    input.value = "";
  });
  document.getElementById("yes").addEventListener("click", () => send("yes"));
  document.getElementById("no").addEventListener("click", () => send("no"));

  window.grandpaConnect = function (url) {
    if (socket || !url) return;
    address = url;
    connect();
  };
  if (address) connect();
  else label.textContent = "Waiting for Grandpa...";
})();
