# Grandpa: product plan (mobile, accounts, server, launch)

Status: **Planned** (recommendations, 2026-11-25). Nothing in this file is built yet unless it says so.

Captain's order: finish Grandpa's core → his own model → his own server → login → mobile everywhere → free launch → paid plans. This plan keeps that order and picks the simplest strong option at each step.

## The principle that decides everything
Grandpa is **local-first**: the models, chats and memory live on the user's PC. So:
- the desktop app needs **no login** to work (it already doesn't);
- the server's job is **accounts, sync, and connecting devices**, not running models for everyone (GPU servers are what make AI products expensive);
- paid plans sell **convenience across devices**, never access to the user's own PC.

## 1. Own model (before login and server)
- Keep fine-tuning Grandpa's models on Colab (Mini first). Goal: reliable tool calls in English, Tamil and Thanglish on a CPU laptop.
- Measure, don't guess: the speed tables in `grandpa doctor` plus a fixed test set of 50 real requests (open an app, set a reminder, answer from a file, ask before a risky action).
- The voice too: finish the Piper training (`notebooks/grandpa_voice_piper_v4`), so Grandpa speaks in **his own voice**. Today he uses the stock Piper voice `en_GB-alan-medium`, plus Meta's MMS voice for Tamil.

## 2. Own server: "Grandpa Cloud" (small, cheap, no GPU)
| Need | Recommended | Why |
|---|---|---|
| Accounts and login | **Supabase Auth** | Google, GitHub, Microsoft and email login built in; free tier; Postgres included |
| Sync (settings, chats you choose to sync, skills) | Supabase Postgres, encrypted per user | One service, row-level security |
| Phone ↔ PC connection | A small relay (FastAPI + WebSocket) on a $5–6/month VPS, or Tailscale at first | The phone talks to the user's own PC through it; the PC does the AI work |
| Website and downloads | Vercel | Already used for the portfolio |
| The Pironman | The user's *home* hub (always on, LAN), not the public server | Matches the Pironman phase |

## 3. Login (after the server exists)
- Sign in with **Google, GitHub, Microsoft, or email (magic link)**, through Supabase Auth (OAuth 2.0 with PKCE). Grandpa never sees passwords.
- The desktop app stays usable signed out. Signing in only switches on sync and mobile.
- The desktop sign-in opens the browser and comes back to the app through a loopback redirect: the standard flow for desktop OAuth.

## 4. Mobile: "all devices" in three steps
1. **Phone as a remote for your PC** (fastest, reuses today's app). Grandpa serves the same web app on the home Wi-Fi. The phone pairs once by scanning a QR code shown in the desktop app, which gives a per-device token. It installs as a PWA, and the PC does all the work.
2. **Outside the home**: the phone reaches the PC through the relay (or Tailscale), still with the paired-device token. No ports are opened on the router.
3. **Store apps**: wrap the same web app with **Capacitor** for Android and iOS to get push notifications, the mic and share-to-Grandpa. One code base for all three.

Security from day one: paired devices are listed in Settings and can be revoked; every risky action still asks on the device that started it; the audit log records which device asked.

## 5. Launch: free first, paid later
- **Free beta** until reach (Captain's plan): everything local is free forever, so trust grows.
- **Then freemium:**
  - *Free*: the full local Grandpa on one PC.
  - *Plus*: sync across devices, phone remote from anywhere, more connectors, priority updates.
  - *Pro*: hosted bigger models for users without a strong PC (pay-as-you-go cost underneath), and teams later.
- **Payments**: **Razorpay** for India (UPI, cards). For international buyers, **Lemon Squeezy** or Paddle as *merchant of record*: they handle global taxes, so you don't have to.
- **Keep the free tier honest**: never move a local feature behind the paywall once it is free.

## 6. Order of work (each step ships something usable)
1. Finish the core and the desktop polish *(now)*.
2. Grandpa's own model v1 and his own voice.
3. Phone as a LAN remote (PWA + QR pairing): no server needed yet.
4. Supabase project with accounts (Google, GitHub, Microsoft, email); the desktop sign-in.
5. The relay for outside-home access; settings and skills sync.
6. Free public beta: website, installer (with the brand icon in `assets/brand`), feedback channel.
7. Capacitor Android app, then iOS.
8. Paid plans (Razorpay and a merchant of record).

## Open decisions (TBD; Captain's call)
- The product name in stores: "Grandpa" or "Grandpa AI".
- Whether synced chats are end-to-end encrypted (recommended) or only encrypted on the server.
- Plus/Pro prices: decide after the beta shows real usage.
