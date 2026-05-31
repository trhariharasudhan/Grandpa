function render() {
  chrome.storage.local.get(['lastStatus', 'lastSnapshotAt', 'lastTitle', 'lastError'], (data) => {
    const state = document.getElementById('state');
    const title = document.getElementById('title');
    const error = document.getElementById('error');
    const status = data.lastStatus || 'waiting';
    state.textContent = status === 'connected' ? 'Connected to Grandpa' : `Status: ${status}`;
    state.className = status === 'connected' ? 'ok' : '';
    title.textContent = data.lastTitle ? `Page: ${data.lastTitle}` : 'Open a page to send a snapshot.';
    error.textContent = data.lastError || '';
  });
}

document.getElementById('refresh').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) {
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.dispatchEvent(new Event('focus')),
    });
  }
  setTimeout(render, 500);
});

render();
