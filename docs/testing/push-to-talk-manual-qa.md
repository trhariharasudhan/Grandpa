# Push-to-Talk Microphone Bridge Manual QA

These checks verify user-initiated browser push-to-talk only. They do not
enable always-on recording, live wake-word microphone detection, background
auto-start, or desktop automation bypasses.

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
