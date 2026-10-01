# Push-to-Talk Microphone Bridge Manual QA

These checks verify user-initiated push-to-talk only. They do not enable
always-on recording, live wake-word microphone detection, background
auto-start, or desktop automation bypasses.

There are two push-to-talk paths. They share the name and nothing else.

## Terminal: hold a key

```
grandpa voice push-to-talk
```

Hold SPACE, speak, release. The recording starts on the key going down and ends
on it coming up; every frame in between is kept. The voice activity detector is
configured so it cannot refuse or truncate anything -- no threshold, no noise
floor, no silence timeout -- so this is the path to use when automatic detection
is misbehaving and when a threshold needs to be ruled out as the cause.

| Option | Effect |
| --- | --- |
| `--key ctrl` | Hold a different key. SPACE, CTRL, SHIFT, ALT, F8, F9, F10. A modifier types nothing into whatever has focus. |
| `--no-route` | Print the transcript and stop. Nothing is acted on. |
| `--once` | Handle one hold and exit. |
| `--no-tts` | Print the reply instead of speaking it. |
| `--device N` | Override the stored microphone preference. `grandpa voice --list-microphones` shows the indexes. |

Expected, per hold:

| Step | Expected behavior |
| --- | --- |
| Key down | `Recording...` |
| Key up | `Released after N.Ns. Transcribing...` |
| Speech recognised | `You said: <transcript>`, then the reply |
| Nothing recognisable | Says so with the audio level, and routes nothing. An empty transcription is never read as a command. |
| Key tapped, not held | Says it was a tap and asks for a hold. Nothing is transcribed. |
| No audio captured | Says the device delivered nothing and points at `grandpa voice doctor`. |

Esc or Ctrl+C ends the loop. It never exits silently.

Windows only: the key is read through `GetAsyncKeyState`, which asks what the
keyboard is doing and synthesises nothing, so this requires no actuation
consent. On any other platform the command says so and exits non-zero.

## Browser: click to record

The rest of this document covers the browser bridge, which is a different
thing: it records between two button clicks rather than while a key is held,
and it needs the server running and a page open.

## Setup

1. Start Grandpa normally.
2. Open the Voice Assistant page in a browser that supports `MediaRecorder`.
3. Confirm the backend is reachable.

## Happy Path

| Step | Expected behavior |
| --- | --- |
| Click Start Recording | Browser asks for microphone permission if needed, then recording starts. |
| Speak a short command | Audio is captured only while recording is active. |
| Click Stop Recording | Recording stops, the browser microphone stream is closed, and audio is sent to `/v1/voice/listen`. |
| Transcript appears | The transcript preview fills in if local audio transcription is available. |
| Click Send as Command | The transcript is sent to `/v1/voice/command`. |
| Confirmation needed | Desktop actions that require approval show the existing Confirm Action flow. |

## Commands To Try

- `what is my voice status`
- `open notepad`
- `type hello in notepad`
- `remind me tomorrow at 7 PM to call Arjun`

## Failure Cases

| Case | Expected behavior |
| --- | --- |
| Browser has no `MediaRecorder` | UI shows `Browser recording is not available on this device.` |
| Microphone permission denied | UI shows the browser/device error without starting a recording loop. |
| No local Whisper/faster-whisper | `/v1/voice/listen` returns setup guidance: `uv sync --extra speech`. |
| Unclear or invalid audio | UI shows a friendly recognition failure and allows retry. |
| Empty transcript | Send as Command stays disabled. |

## Safety Notes

- Recording starts only after Start Recording is clicked.
- Recording stops when Stop Recording is clicked.
- The UI sends commands only after Send as Command is clicked.
- Wake-word live microphone mode is not part of this bridge.
- Dangerous or confirmation-required desktop actions must still use the
  existing local action approval flow.
