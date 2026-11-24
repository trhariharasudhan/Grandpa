// A small, safe Markdown renderer for Grandpa's replies.
// It never parses strings as HTML: every node is built with createElement/textContent,
// so text from the model can never become markup or script.
// Supported: headings, paragraphs, **bold**, *italic*, `code`, ``` fences,
// - / * / 1. lists, > quotes, --- rules, http(s) links.
// Highlights (one colour per kind, see app.css): "Label:" at a line start,
// good words (connected, done, ✓...) and bad words (failed, error, ✗...).
"use strict";

(function () {
  const GOOD = /(✓|✔|\b(?:done|ok|OK|connected|Connected|active|Active|ready|Ready|installed|Installed|enabled|Enabled|success|passed)\b)/;
  const BAD = /(✗|✘|\b(?:failed|Failed|error|Error|not installed|not available|not connected|disabled|Disabled|blocked|Blocked)\b)/;
  const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_|https?:\/\/[^\s<>()\]]+)/;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Plain text with good/bad words coloured.
  function words(parent, text) {
    let rest = text;
    while (rest) {
      const g = GOOD.exec(rest);
      const b = BAD.exec(rest);
      const m = !g ? b : !b ? g : (b.index < g.index ? b : g);
      if (!m) { parent.appendChild(document.createTextNode(rest)); return; }
      if (m.index) parent.appendChild(document.createTextNode(rest.slice(0, m.index)));
      parent.appendChild(el("span", m === b ? "bad" : "good", m[0]));
      rest = rest.slice(m.index + m[0].length);
    }
  }

  function inline(parent, text) {
    let rest = text;
    while (rest) {
      const m = INLINE.exec(rest);
      if (!m) { words(parent, rest); return; }
      if (m.index) words(parent, rest.slice(0, m.index));
      const t = m[0];
      if (t.startsWith("**")) inline(parent.appendChild(el("strong")), t.slice(2, -2));
      else if (t.startsWith("`")) parent.appendChild(el("code", null, t.slice(1, -1)));
      else if (t.startsWith("http")) {
        const a = el("a", null, t);
        a.href = t; a.target = "_blank"; a.rel = "noopener noreferrer";
        parent.appendChild(a);
      } else inline(parent.appendChild(el("em")), t.slice(1, -1));
      rest = rest.slice(m.index + t.length);
    }
  }

  // "Model: x" -> the label coloured, the rest normal.
  function lineWithLabel(parent, text) {
    const m = /^([A-Z][\w /()'-]{0,28}):(\s.*)$/.exec(text);
    if (m) {
      parent.appendChild(el("span", "label-key", m[1]));
      parent.appendChild(document.createTextNode(":"));
      inline(parent, m[2]);
    } else inline(parent, text);
  }

  function render(source, asMarkdown) {
    const root = el("div", "md");
    const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
    if (asMarkdown === false) {
      lines.forEach((line, i) => { if (i) root.appendChild(el("br")); lineWithLabel(root, line); });
      return root;
    }
    let i = 0;
    let para = null;
    const endPara = () => { para = null; };
    while (i < lines.length) {
      const line = lines[i];
      const fence = /^\s*(```+|~~~+)\s*([\w+-]*)\s*$/.exec(line);
      if (fence) {
        endPara();
        const closer = fence[1];
        const body = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith(closer)) { body.push(lines[i]); i += 1; }
        i += 1;
        const pre = el("pre");
        const code = el("code", null, body.join("\n"));
        if (fence[2]) code.dataset.lang = fence[2];
        pre.appendChild(code);
        root.appendChild(pre);
        continue;
      }
      if (!line.trim()) { endPara(); i += 1; continue; }
      const heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        endPara();
        inline(root.appendChild(el("h" + Math.min(heading[1].length + 1, 4))), heading[2]);
        i += 1; continue;
      }
      if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { endPara(); root.appendChild(el("hr")); i += 1; continue; }
      if (/^\s*>/.test(line)) {
        endPara();
        const quote = root.appendChild(el("blockquote"));
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          if (quote.childNodes.length) quote.appendChild(el("br"));
          inline(quote, lines[i].replace(/^\s*>\s?/, ""));
          i += 1;
        }
        continue;
      }
      const item = /^\s*([-*•]|\d{1,3}[.)])\s+(.*)$/.exec(line);
      if (item) {
        endPara();
        const ordered = /\d/.test(item[1]);
        const list = root.appendChild(el(ordered ? "ol" : "ul"));
        if (ordered) list.start = parseInt(item[1], 10) || 1;
        while (i < lines.length) {
          const next = /^\s*([-*•]|\d{1,3}[.)])\s+(.*)$/.exec(lines[i]);
          if (!next || /\d/.test(next[1]) !== ordered) break;
          lineWithLabel(list.appendChild(el("li")), next[2]);
          i += 1;
        }
        continue;
      }
      if (!para) para = root.appendChild(el("p"));
      else para.appendChild(el("br"));
      lineWithLabel(para, line);
      i += 1;
    }
    return root;
  }

  window.GrandpaMarkdown = { render };
})();
