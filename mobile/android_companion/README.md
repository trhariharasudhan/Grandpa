# Grandpa Android Companion

This is the local-first Flutter companion app for Grandpa.

It connects to the desktop backend over the local LAN WebSocket endpoint:

```text
ws://<desktop-lan-ip>:8000/v1/mobile/ws
```

Current implementation includes pairing, secure trusted-token persistence, QR pairing support, reconnect-safe WebSocket messaging, device heartbeat, battery/network status, Android notification-listener hooks, local push notifications from Grandpa, remote commands, and phone microphone speech relay.

The notification listener is consent-first: Android will show system notification-access settings, and Grandpa only receives redacted summaries after the user explicitly enables access. Clipboard sync and risky commands remain approval-gated on the desktop side.

## Run

```powershell
flutter pub get
flutter run
```

## Build

```powershell
flutter build apk
```

If Flutter reports that it cannot access `C:\flutter\bin\cache\lockfile`, fix SDK folder permissions or move the SDK to a user-writable path before running `flutter analyze` or `flutter build apk`.
