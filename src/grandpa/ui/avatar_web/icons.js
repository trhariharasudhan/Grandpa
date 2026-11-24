// Grandpa's line icons: one stroke style, 24x24, drawn with the text colour.
// Used instead of emoji everywhere in the app and the orb. Built with DOM
// calls (createElementNS), so the pages' strict CSP needs nothing extra.
//
//   GrandpaIcons.make("plus")          -> an <svg> element
//   <span data-icon="plus"></span>      -> filled in by GrandpaIcons.fill()
"use strict";

(function () {
  const NS = "http://www.w3.org/2000/svg";
  // Each icon: a list of [tag, attributes]. Paths are this project's own.
  const ICONS = {
    plus: [["path", { d: "M12 5v14M5 12h14" }]],
    send: [["path", { d: "M12 19V5M6 11l6-6 6 6" }]],
    stop: [["rect", { x: 7, y: 7, width: 10, height: 10, rx: 1.5, fill: "currentColor", stroke: "none" }]],
    mic: [["rect", { x: 9, y: 3, width: 6, height: 11, rx: 3 }], ["path", { d: "M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" }]],
    file: [["path", { d: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" }], ["path", { d: "M14 3v5h5M9 13h6M9 17h4" }]],
    paperclip: [["path", { d: "M20 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8" }]],
    orb: [["circle", { cx: 12, cy: 12, r: 8 }], ["circle", { cx: 12, cy: 12, r: 3.5, opacity: 0.5 }]],
    settings: [["circle", { cx: 12, cy: 12, r: 3 }], ["path", { d: "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" }]],
    menu: [["path", { d: "M4 6h16M4 12h16M4 18h16" }]],
    sidebar: [["rect", { x: 3, y: 4, width: 18, height: 16, rx: 2 }], ["path", { d: "M9 4v16" }]],
    close: [["path", { d: "M6 6l12 12M18 6L6 18" }]],
    more: [["circle", { cx: 5, cy: 12, r: 1.2, fill: "currentColor" }], ["circle", { cx: 12, cy: 12, r: 1.2, fill: "currentColor" }], ["circle", { cx: 19, cy: 12, r: 1.2, fill: "currentColor" }]],
    search: [["circle", { cx: 11, cy: 11, r: 6.5 }], ["path", { d: "M16 16l4.5 4.5" }]],
    edit: [["path", { d: "M4 20h4L19 9l-4-4L4 16z" }], ["path", { d: "M13.5 6.5l4 4" }]],
    "new-chat": [["path", { d: "M12 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" }], ["path", { d: "M18.5 3.5l2 2L13 13l-3 1 1-3z" }]],
    chat: [["path", { d: "M5 5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H10l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" }]],
    folder: [["path", { d: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }]],
    "folder-plus": [["path", { d: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }], ["path", { d: "M12 10v6M9 13h6" }]],
    copy: [["rect", { x: 8, y: 8, width: 12, height: 12, rx: 2 }], ["path", { d: "M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" }]],
    check: [["path", { d: "M5 12.5l4.5 4.5L19 7.5" }]],
    retry: [["path", { d: "M4 12a8 8 0 0 1 14-5.3L20 9M20 4v5h-5" }], ["path", { d: "M20 12a8 8 0 0 1-14 5.3L4 15M4 20v-5h5" }]],
    incognito: [["path", { d: "M3 11h18M6 11l1.5-5h9L18 11" }], ["circle", { cx: 7.5, cy: 16, r: 2.5 }], ["circle", { cx: 16.5, cy: 16, r: 2.5 }], ["path", { d: "M10 16h4" }]],
    pin: [["path", { d: "M9 3h6l-1 6 4 4H6l4-4zM12 13v8" }]],
    trash: [["path", { d: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" }]],
    download: [["path", { d: "M12 4v11M7 10l5 5 5-5M5 20h14" }]],
    chevron: [["path", { d: "M9 6l6 6-6 6" }]],
    "chevron-down": [["path", { d: "M6 9l6 6 6-6" }]],
    sun: [["circle", { cx: 12, cy: 12, r: 4 }], ["path", { d: "M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" }]],
    moon: [["path", { d: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" }]],
    memory: [["path", { d: "M12 4a4 4 0 0 0-4 4 4 4 0 0 0-3 6.5A3.5 3.5 0 0 0 9 20h0a3 3 0 0 0 3-3V4z" }], ["path", { d: "M12 4a4 4 0 0 1 4 4 4 4 0 0 1 3 6.5A3.5 3.5 0 0 1 15 20h0a3 3 0 0 1-3-3" }]],
    command: [["rect", { x: 4, y: 5, width: 16, height: 14, rx: 2 }], ["path", { d: "M8 10l2.5 2L8 14M12.5 14H16" }]],
    app: [["rect", { x: 3, y: 4, width: 18, height: 16, rx: 2 }], ["path", { d: "M3 9h18" }]],
    power: [["path", { d: "M12 3v8" }], ["path", { d: "M7 6.5a7 7 0 1 0 10 0" }]],
    spark: [["path", { d: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" }]],
    warning: [["path", { d: "M12 4l9 16H3z" }], ["path", { d: "M12 10v4M12 17v.5" }]],
  };

  function make(name, size) {
    const parts = ICONS[name];
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size || 18));
    svg.setAttribute("height", String(size || 18));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.8");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "icon-svg");
    (parts || []).forEach(([tag, attrs]) => {
      const node = document.createElementNS(NS, tag);
      Object.keys(attrs).forEach((key) => node.setAttribute(key, String(attrs[key])));
      svg.appendChild(node);
    });
    return svg;
  }

  // Replace the contents of every <… data-icon="name"> with its icon.
  function fill(root) {
    (root || document).querySelectorAll("[data-icon]").forEach((el) => {
      const size = Number(el.getAttribute("data-icon-size")) || undefined;
      const svg = make(el.getAttribute("data-icon"), size);
      el.textContent = "";
      el.appendChild(svg);
    });
  }

  window.GrandpaIcons = { make, fill, names: Object.keys(ICONS) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => fill());
  else fill();
})();
