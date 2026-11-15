// Renders what Python says. Never infers a state from text.
// The WebSocket URL (with its per-run token) arrives in the page's hash:
//   index.html#ws=ws%3A%2F%2F127.0.0.1%3A1234%2Favatar%3Ftoken%3D...
"use strict";

(function () {
  const app = document.getElementById("app");
  const label = document.getElementById("label");
  const actionLine = document.getElementById("action");
  const history = document.getElementById("history");
  const confirmBox = document.getElementById("confirm");
  const question = document.getElementById("question");
  const form = document.getElementById("entry");
  const input = document.getElementById("text");
  const sendButton = document.getElementById("send");

  const BUSY = new Set(["thinking", "working", "listening"]);
  let socket = null;
  let retry = 500;
  let address = new URLSearchParams(location.hash.slice(1)).get("ws");

  function wsUrl() {
    return address;
  }

  function addLine(role, text, failed) {
    const item = document.createElement("li");
    item.className = role + (failed ? " failed" : "");
    item.textContent = text; // text, never HTML
    history.appendChild(item);
    history.scrollTop = history.scrollHeight;
  }

  function showState(msg) {
    app.dataset.state = msg.state;
    document.documentElement.style.setProperty("--glow", msg.colour || "#E5E7EB");
    label.textContent = msg.label || msg.state;
    actionLine.textContent = msg.state === "working" && msg.action ? msg.action.replace(/_/g, " ") : "";
    const asking = msg.state === "confirm";
    confirmBox.hidden = !asking;
    question.textContent = asking ? msg.question : "";
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
    const url = wsUrl();
    if (!url) { label.textContent = "No connection address."; return; }
    socket = new WebSocket(url);
    socket.onopen = () => { retry = 500; history.textContent = ""; };
    socket.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === "state") showState(msg);
      else if (msg.type === "chat") addLine(msg.role, msg.text, msg.failed);
    };
    socket.onclose = () => {
      label.textContent = "Reconnecting...";
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

  // The desktop window hands the address over once the page has loaded
  // (pywebview evaluate_js); a browser tab can use the #ws= hash instead.
  window.grandpaConnect = function (url) {
    if (socket || !url) return;
    address = url;
    connect();
  };
  if (address) connect();
  else label.textContent = "Waiting for Grandpa...";
})();
