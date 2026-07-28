# Personal Integrations

Grandpa retains two optional personal integrations:

- Gmail for reading, summarizing, drafting, and confirmed sending.
- Google Calendar for agendas, availability, and confirmed event changes.

Both use installed-app OAuth, store credentials under
`%USERPROFILE%\.grandpa\credentials`, and remain disabled until configured.
They are not social messaging channels and do not enable external analytics.

Install only the integration you need:

```powershell
uv sync --extra gmail
uv sync --extra calendar
```

Never commit OAuth client secrets or token files.
