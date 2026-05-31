const GRANDPA_ENDPOINT = 'http://127.0.0.1:8000/v1/browser/snapshot';

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== 'GRANDPA_PAGE_SNAPSHOT') return false;

  fetch(GRANDPA_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...message.snapshot,
      source: 'grandpa-browser-extension',
    }),
  })
    .then(async (response) => {
      const body = await response.json().catch(() => ({}));
      chrome.storage.local.set({
        lastStatus: response.ok ? 'connected' : 'error',
        lastSnapshotAt: Date.now(),
        lastTitle: message.snapshot?.title || '',
        lastError: response.ok ? '' : JSON.stringify(body).slice(0, 200),
      });
      sendResponse({ ok: response.ok, body });
    })
    .catch((error) => {
      chrome.storage.local.set({
        lastStatus: 'offline',
        lastSnapshotAt: Date.now(),
        lastTitle: message.snapshot?.title || '',
        lastError: String(error).slice(0, 200),
      });
      sendResponse({ ok: false, error: String(error) });
    });

  return true;
});
