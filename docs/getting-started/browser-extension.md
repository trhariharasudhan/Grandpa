# Grandpa Browser Extension

Grandpa can read the currently visible Chrome or Edge page through a local-only
Manifest V3 extension. The extension sends safe visible-page snapshots to:

```text
http://127.0.0.1:8000/v1/browser/snapshot
```

It does not collect browser history, hidden tabs, passwords, hidden inputs,
payment fields, or private token-looking values.

## Load In Chrome

1. Start Grandpa locally:

   ```powershell
   uv run grandpa serve
   ```

2. Open Chrome and go to:

   ```text
   chrome://extensions
   ```

3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select:

   ```text
   D:\Grandpa\browser-extension
   ```

6. Open or refresh a normal webpage.
7. Click the Grandpa extension icon to confirm it says connected.

## Load In Microsoft Edge

1. Start Grandpa locally:

   ```powershell
   uv run grandpa serve
   ```

2. Open Edge and go to:

   ```text
   edge://extensions
   ```

3. Enable **Developer mode**.
4. Click **Load unpacked**.
5. Select:

   ```text
   D:\Grandpa\browser-extension
   ```

6. Open or refresh a normal webpage.

## Try Commands

After the extension is connected:

```powershell
uv run grandpa ask "what page am I on?"
uv run grandpa ask "summarize this webpage"
uv run grandpa ask "read visible headings"
uv run grandpa ask "show links on this page"
uv run grandpa ask "what buttons are visible?"
```

## Privacy Notes

- Snapshots are sent only to `127.0.0.1`.
- Only the visible page content script runs.
- Password and hidden fields are skipped.
- Payment, token, API-key, and secret-looking text is redacted.
- Risky browser actions such as clicks and form submissions stay approval-gated.
