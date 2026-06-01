const GRANDPA_MAX_ITEMS = 40;
const GRANDPA_MAX_TEXT = 6000;
const GRANDPA_POST_INTERVAL_MS = 5000;
const GRANDPA_COMMAND_INTERVAL_MS = 1200;
const GRANDPA_COMMAND_ENDPOINT = 'http://127.0.0.1:8000/v1/browser/command';

const SENSITIVE_RE = /(password|passcode|secret|token|api[_ -]?key|credential|credit card|card number|cvv|otp|pin|private key|seed phrase|payment|checkout)/i;
const SECRET_VALUE_RE = [
  /\b(?:api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*['"]?[\w\-.]{8,}/gi,
  /\b(?:sk|pk|xoxp|xoxb|ghp|gho|github_pat)_[A-Za-z0-9_\-]{10,}/g,
  /\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b/g,
  /\b(?:\d[ -]*?){13,19}\b/g,
];

let lastPayload = '';
let lastPostedAt = 0;

function isVisible(element) {
  if (!element || !(element instanceof HTMLElement)) return false;
  const style = window.getComputedStyle(element);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  return rect.bottom >= 0 && rect.right >= 0 && rect.top <= window.innerHeight && rect.left <= window.innerWidth;
}

function cleanText(value, max = 180) {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  for (const pattern of SECRET_VALUE_RE) text = text.replace(pattern, '[redacted]');
  if (SENSITIVE_RE.test(text)) text = text.replace(SENSITIVE_RE, '[redacted]');
  return text.slice(0, max);
}

function visibleText(element) {
  return cleanText(element.innerText || element.textContent || '');
}

function collectHeadings() {
  return Array.from(document.querySelectorAll('h1,h2,h3'))
    .filter(isVisible)
    .map(visibleText)
    .filter(Boolean)
    .slice(0, GRANDPA_MAX_ITEMS);
}

function collectLinks() {
  return Array.from(document.querySelectorAll('a[href]'))
    .filter(isVisible)
    .map((element) => ({
      text: visibleText(element),
      href: String(element.href || '').slice(0, 1000),
    }))
    .filter((link) => link.text || link.href)
    .slice(0, GRANDPA_MAX_ITEMS);
}

function collectButtons() {
  return Array.from(document.querySelectorAll('button,[role="button"],input[type="button"],input[type="submit"]'))
    .filter(isVisible)
    .map((element) => cleanText(element.innerText || element.value || element.getAttribute('aria-label') || element.getAttribute('title') || 'button'))
    .filter(Boolean)
    .slice(0, GRANDPA_MAX_ITEMS);
}

function collectInputs() {
  return Array.from(document.querySelectorAll('input,textarea,select'))
    .filter(isVisible)
    .map((element) => {
      const type = String(element.getAttribute('type') || element.tagName || 'text').toLowerCase();
      const label = element.getAttribute('aria-label') || element.getAttribute('placeholder') || element.getAttribute('name') || '';
      return { type, label: cleanText(label) };
    })
    .filter((input) => input.type !== 'password' && input.type !== 'hidden')
    .filter((input) => !SENSITIVE_RE.test(`${input.type} ${input.label}`))
    .slice(0, GRANDPA_MAX_ITEMS);
}

function stableElementId(element, index) {
  const role = element.getAttribute('role') || element.tagName.toLowerCase();
  const text = cleanText(element.innerText || element.value || element.getAttribute('aria-label') || element.getAttribute('title') || '', 60);
  return `${role}:${index}:${text}`.toLowerCase().replace(/[^a-z0-9:_-]+/g, '-').slice(0, 80);
}

function collectElements() {
  return Array.from(document.querySelectorAll('a[href],button,[role="button"],input,textarea,select,h1,h2,h3,video,audio'))
    .filter(isVisible)
    .map((element, index) => {
      const tag = element.tagName.toLowerCase();
      const role = tag === 'a' ? 'link'
        : ['h1', 'h2', 'h3'].includes(tag) ? 'heading'
        : tag === 'video' || tag === 'audio' ? 'media'
        : tag === 'input' || tag === 'textarea' || tag === 'select' ? 'input'
        : 'button';
      const text = cleanText(element.innerText || element.value || element.getAttribute('aria-label') || element.getAttribute('placeholder') || element.getAttribute('title') || role);
      if (SENSITIVE_RE.test(`${role} ${text}`)) return null;
      return { id: stableElementId(element, index), role, text, visible: true };
    })
    .filter(Boolean)
    .slice(0, GRANDPA_MAX_ITEMS * 2);
}

function collectMedia() {
  return Array.from(document.querySelectorAll('video,audio'))
    .filter(isVisible)
    .map((element) => ({
      kind: element.tagName.toLowerCase(),
      paused: !!element.paused,
      muted: !!element.muted,
      duration: Number.isFinite(element.duration) ? element.duration : 0,
      current_time: Number.isFinite(element.currentTime) ? element.currentTime : 0,
      label: cleanText(element.getAttribute('aria-label') || document.title || 'media'),
    }))
    .slice(0, 10);
}

function collectForms() {
  return Array.from(document.querySelectorAll('form'))
    .filter(isVisible)
    .map((form) => {
      const fields = Array.from(form.querySelectorAll('input,textarea,select'))
        .filter(isVisible)
        .map((element) => {
          const type = String(element.getAttribute('type') || element.tagName || 'text').toLowerCase();
          const label = cleanText(element.getAttribute('aria-label') || element.getAttribute('placeholder') || element.getAttribute('name') || '');
          if (type === 'password' || type === 'hidden' || SENSITIVE_RE.test(`${type} ${label}`)) return null;
          return { type, label };
        })
        .filter(Boolean);
      return {
        label: cleanText(form.getAttribute('aria-label') || form.getAttribute('name') || 'form'),
        fields,
        submit_count: form.querySelectorAll('button[type="submit"],input[type="submit"]').length,
      };
    })
    .slice(0, 10);
}

function collectSession() {
  return {
    visibility: document.visibilityState,
    focused: document.hasFocus(),
    origin: location.origin,
    path: location.pathname,
    is_youtube: /(^|\.)youtube\.com$/.test(location.hostname) || /(^|\.)youtu\.be$/.test(location.hostname),
    is_whatsapp: location.hostname === 'web.whatsapp.com',
  };
}

function collectVisibleBodyText() {
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent || !isVisible(parent)) return NodeFilter.FILTER_REJECT;
      if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
      const text = String(node.nodeValue || '').replace(/\s+/g, ' ').trim();
      if (!text) return NodeFilter.FILTER_REJECT;
      if (SENSITIVE_RE.test(text)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const chunks = [];
  while (chunks.join(' ').length < GRANDPA_MAX_TEXT) {
    const node = walker.nextNode();
    if (!node) break;
    chunks.push(cleanText(node.nodeValue, 400));
  }
  return cleanText(chunks.join(' '), GRANDPA_MAX_TEXT);
}

function buildSnapshot() {
  return {
    title: cleanText(document.title, 300),
    url: String(location.href || '').slice(0, 1000),
    headings: collectHeadings(),
    links: collectLinks(),
    buttons: collectButtons(),
    inputs: collectInputs(),
    media: collectMedia(),
    forms: collectForms(),
    elements: collectElements(),
    session: collectSession(),
    visible_text: collectVisibleBodyText(),
    captured_at: Date.now(),
  };
}

function postSnapshot(force = false) {
  const now = Date.now();
  if (!force && now - lastPostedAt < GRANDPA_POST_INTERVAL_MS) return;
  const snapshot = buildSnapshot();
  const payload = JSON.stringify(snapshot);
  if (!force && payload === lastPayload) return;
  lastPayload = payload;
  lastPostedAt = now;
  chrome.runtime.sendMessage({ type: 'GRANDPA_PAGE_SNAPSHOT', snapshot });
}

postSnapshot(true);
window.addEventListener('focus', () => postSnapshot(true));
window.addEventListener('scroll', () => postSnapshot(false), { passive: true });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) postSnapshot(true);
});
setInterval(() => postSnapshot(false), GRANDPA_POST_INTERVAL_MS);

function applyMediaCommand(target) {
  const media = Array.from(document.querySelectorAll('video,audio')).filter(isVisible)[0];
  if (!media) return { ok: false, message: 'No visible media element.' };
  const command = String(target || '').toLowerCase();
  if (command.includes('play')) {
    media.play();
    return { ok: true, message: 'Playing visible media.' };
  }
  if (command.includes('pause')) {
    media.pause();
    return { ok: true, message: 'Paused visible media.' };
  }
  if (command.includes('unmute')) {
    media.muted = false;
    return { ok: true, message: 'Unmuted visible media.' };
  }
  if (command.includes('mute')) {
    media.muted = true;
    return { ok: true, message: 'Muted visible media.' };
  }
  return { ok: false, message: 'Unsupported media command.' };
}

async function pollCommand() {
  try {
    const response = await fetch(`${GRANDPA_COMMAND_ENDPOINT}/next?url=${encodeURIComponent(location.href)}`);
    if (!response.ok) return;
    const body = await response.json();
    const command = body && body.command;
    if (!command || !command.id) return;
    let result = { ok: false, message: 'Unsupported browser command.' };
    if (command.action === 'media') result = applyMediaCommand(command.target);
    await fetch(`${GRANDPA_COMMAND_ENDPOINT}/${encodeURIComponent(command.id)}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: result.ok ? 'completed' : 'failed',
        result,
      }),
    });
    postSnapshot(true);
  } catch {
    // Grandpa backend may be offline; keep the extension quiet.
  }
}

setInterval(pollCommand, GRANDPA_COMMAND_INTERVAL_MS);
