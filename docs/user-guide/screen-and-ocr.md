# Screen and OCR

Screen awareness reads visible Windows state through active-window metadata,
screen capture, OCR, and element location.

```powershell
uv run grandpa screen active
uv run grandpa screen describe --active-window
```

Captured screen text is treated as untrusted input. It cannot grant permission
or bypass confirmation. Sensitive-looking text is redacted from logs, and
screen operations remain bounded to visible user-session content.
