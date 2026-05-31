const GRANDPA_MAX_ITEMS = 40;
const GRANDPA_MAX_TEXT = 6000;
const GRANDPA_POST_INTERVAL_MS = 5000;

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
