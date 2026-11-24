// A small, safe Markdown renderer for Grandpa's replies.
// It never parses strings as HTML: every node is built with createElement/textContent,
// so text from the model can never become markup or script.
// Supported: headings, paragraphs, **bold**, *italic*, `code`, ``` fences,
// - / * / 1. lists, > quotes, --- rules, http(s) links.
// Also: tables, and code blocks with a header (language, Copy) and light
// syntax colours. Highlights (one colour per kind, see app.css): "Label:" at
// a line start, good words (connected, done, a tick...) and bad words
// (failed, error, a cross...).
"use strict";

(function () {
  const GOOD = /(\u2713|\u2714|\b(?:done|ok|OK|connected|Connected|active|Active|ready|Ready|installed|Installed|enabled|Enabled|success|passed)\b)/;
  const BAD = /(\u2717|\u2718|\b(?:failed|Failed|error|Error|not installed|not available|not connected|disabled|Disabled|blocked|Blocked)\b)/;
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

  // --- code blocks ----------------------------------------------------------
  const KEYWORDS = new Set(("and as assert async await break case catch class const continue def del " +
    "elif else except export false False finally for from function if import in is lambda let new " +
    "none None nonlocal not null or pass raise return self static switch this throw true True try " +
    "typeof var void while with yield param foreach echo").split(" "));
  const TOKEN = /("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`[^`\n]*`|#[^\n]*|\/\/[^\n]*|\b\d+(?:\.\d+)?\b|\$?[A-Za-z_][\w-]*)/g;

  function highlight(code, text, lang) {
    const hashComments = !/^(js|javascript|ts|typescript|json|css|c|cpp|java|go|rust)$/i.test(lang || "");
    let last = 0;
    let m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(text))) {
      const t = m[0];
      let cls = null;
      if (t[0] === '"' || t[0] === "'" || t[0] === "`") cls = "tok-str";
      else if ((t[0] === "#" && hashComments) || t.startsWith("//")) cls = "tok-com";
      else if (/^\d/.test(t)) cls = "tok-num";
      else if (KEYWORDS.has(t)) cls = "tok-key";
      else if (t[0] === "$") cls = "tok-var";
      if (!cls) continue;
      if (m.index > last) code.appendChild(document.createTextNode(text.slice(last, m.index)));
      code.appendChild(el("span", cls, t));
      last = m.index + t.length;
    }
    if (last < text.length) code.appendChild(document.createTextNode(text.slice(last)));
  }

  function codeBlock(text, lang) {
    const box = el("div", "code-block");
    const head = el("div", "code-head");
    head.appendChild(el("span", "code-lang", lang || "text"));
    const copy = el("button", "code-copy");
    copy.type = "button";
    copy.title = "Copy code";
    if (window.GrandpaIcons) copy.appendChild(window.GrandpaIcons.make("copy", 14));
    copy.appendChild(el("span", null, "Copy"));
    copy.addEventListener("click", () => {
      const done = (ok) => {
        copy.lastChild.textContent = ok ? "Copied" : "Copy failed";
        setTimeout(() => { copy.lastChild.textContent = "Copy"; }, 1500);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
      else done(false);
    });
    head.appendChild(copy);
    box.appendChild(head);
    const pre = el("pre");
    const code = el("code");
    if (lang) code.dataset.lang = lang;
    if (text.length < 20000) highlight(code, text, lang); else code.textContent = text;
    pre.appendChild(code);
    box.appendChild(pre);
    return box;
  }

  // --- tables ---------------------------------------------------------------
  function cells(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  }
  function isTableStart(lines, i) {
    return i + 1 < lines.length && /\|/.test(lines[i]) &&
      /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1]);
  }
  function table(root, lines, i) {
    const wrap = root.appendChild(el("div", "table-wrap"));
    const t = wrap.appendChild(el("table"));
    const headRow = t.appendChild(el("thead")).appendChild(el("tr"));
    cells(lines[i]).forEach((c) => inline(headRow.appendChild(el("th")), c));
    const body = t.appendChild(el("tbody"));
    i += 2;
    while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) {
      const row = body.appendChild(el("tr"));
      cells(lines[i]).forEach((c) => inline(row.appendChild(el("td")), c));
      i += 1;
    }
    return i;
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
        root.appendChild(codeBlock(body.join("\n"), fence[2]));
        continue;
      }
      if (!line.trim()) { endPara(); i += 1; continue; }
      const heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        endPara();
        inline(root.appendChild(el("h" + Math.min(heading[1].length + 1, 4))), heading[2]);
        i += 1; continue;
      }
      if (isTableStart(lines, i)) {
        endPara();
        i = table(root, lines, i);
        continue;
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
