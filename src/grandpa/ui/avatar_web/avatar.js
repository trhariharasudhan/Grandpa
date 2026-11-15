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

  const BUSY = new Set(["thinking", "working", "listening"]);
  const DRAG_THRESHOLD = 4; // pixels before a press counts as a drag
  let socket = null;
  let retry = 500;
  let connected = false;
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");

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
  // click and opens or closes the panel. A drag never toggles.
  let press = null;
  ring.addEventListener("pointerdown", (event) => {
    press = { x: event.screenX, y: event.screenY, dragging: false };
    ring.setPointerCapture(event.pointerId);
  });
  ring.addEventListener("pointermove", (event) => {
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
  ring.addEventListener("pointerup", (event) => {
    const wasDrag = press && press.dragging;
    press = null;
    try { ring.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
    if (!wasDrag) setOpen(!isOpen());
  });
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
    const words = msg.label || msg.state;
    label.textContent = words;
    ring.title = words;
    actionLine.textContent = msg.state === "working" && msg.action ? msg.action.replace(/_/g, " ") : "";
    const asking = msg.state === "confirm";
    confirmBox.hidden = !asking;
    question.textContent = asking ? msg.question : "";
    if (asking && !isOpen()) setOpen(true); // a question must be seen to be answered
    const busy = BUSY.has(msg.state);
    input.disabled = busy;
    sendButton.disabled = busy;
  }

  function send(text) {
    const cleaned = (text || "").trim();
    if (!cleaned || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "send", text: cleaned.slice(0, 2000) }));
  }

  function connect() {
    if (!address) { label.textContent = "No connection address."; return; }
    socket = new WebSocket(address);
    socket.onopen = () => { retry = 500; connected = false; history.textContent = ""; };
    socket.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === "state") { showState(msg); connected = true; }
      else if (msg.type === "chat") addLine(msg.role, msg.text, msg.failed);
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
