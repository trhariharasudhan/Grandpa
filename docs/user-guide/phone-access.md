# Use Grandpa from your phone (Tailscale)

Grandpa keeps running on your PC. Your phone opens it in the browser through
Tailscale, a private network made only of *your* signed-in devices. It works
over your phone's hotspot, home Wi-Fi or mobile data, and from anywhere while
the PC is on.

## One-time setup

1. Install Tailscale on the PC: <https://tailscale.com/download/windows>.
   Sign in (Google, Microsoft or GitHub).
2. Install the Tailscale app on the phone (Play Store) and sign in with the
   **same account**. Turn it on.
3. In the Grandpa app on the PC: **Settings > Phone**. Tick **Phone access**,
   then close and reopen the Grandpa app.
4. Settings > Phone again: click **Share with my devices**. (Grandpa runs
   `tailscale serve --bg 47710`: only your tailnet can open it; it is never
   put on the public internet.)
5. Click **Pair a phone** and scan the QR code with the phone's camera. The
   page opens and says "Paired". Use the browser's **Add to Home screen** to
   get an app icon.

## Everyday use

* PC on, Grandpa app open, Tailscale on (both devices): open the home-screen
  icon on the phone.
* A risky action still asks first; you can answer on the phone or the PC.
* Lost the phone? Settings > Phone > **Forget**. Its key stops working at once.

## What a phone can and cannot do

| Can | Cannot |
| --- | --- |
| Chat, stop, retry, switch model | Add MCP servers or API keys |
| Attach files from the phone | Turn on the PC's microphone |
| Use skills, see and edit memory | Pair other devices or change phone settings |

Chats you start on the phone are listed on the phone (each screen keeps its
own chat list); Grandpa's conversation itself is the same one.

## How it is protected

* Grandpa listens only on `127.0.0.1:47710`; Windows Firewall stays closed.
* Tailscale encrypts phone to PC (WireGuard) and admits only your devices.
* Each phone also holds its own key from the one-time QR code (8 characters,
  10 minutes, 5 tries). The PC keeps only a hash of it in `devices.json`.
