# Voice E2E Manual QA

This checklist verifies the browser/server voice stack without Tauri. It does
not require always-on recording or a real wake-word microphone loop.

## Start Server

1. From `D:\Grandpa`, start the backend:

```powershell
uv run grandpa serve
```

2. Open [http://127.0.0.1:8000](http://127.0.0.1:8000/).
3. Open the Voice Assistant page.

## Healthcheck

1. Run:

```powershell
uv run grandpa doctor --voice
```

2. Verify the output lists checks as `PASS`, `WARN`, or `FAIL`.
3. In the Voice Assistant page, click **Run Voice Doctor**.
4. Verify the same checks appear in the runtime panel.

## STT Status

1. Confirm the page shows STT engine, model, and ready state.
2. If local Whisper is not installed, verify browser transcript mode still works.

## Wake Word And Loop

1. Click **Enable** in Wake Word.
2. Click **Enable** in Continuous Voice Loop.
3. Click **Start** in Continuous Voice Loop.
4. Enter `hey grandpa` in the simulate wake field.
5. Click **Simulate Wake**.
6. Verify mode changes to `listening_for_command`.

## Push To Talk

1. Click **Start Recording**.
2. Allow browser microphone permission if prompted.
3. Speak a short phrase.
4. Click **Stop Recording**.
5. Verify a transcript appears.
6. Click **Send as Command**.
7. Verify the assistant response and action status update.

## Confirmation Flow

1. Type `type hello in notepad`.
2. Click **Run Command**.
3. Verify a confirmation button appears.
4. Click **Confirm Action** only if you intentionally want to run the mocked or allowed action in your environment.

## History And Context

1. Check Command History after running commands.
2. Check Recent Conversation.
3. Click **View Context**.
4. Verify recent messages appear in role order.
5. Click **Clear history**.
6. Click **Clear conversation**.
7. Verify history and context reset.

## Troubleshooting

### Port 8000 Busy

Find and stop the process using the port, then restart the server.

```powershell
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

### Missing faster-whisper

Local audio transcription requires speech extras:

```powershell
uv sync --extra speech
```

Browser transcript and typed transcript commands should still work without it.

### Missing ffmpeg

Install ffmpeg and make sure `ffmpeg.exe` is on `PATH`. MP3, WEBM, and M4A
transcription may fail without it.

### Microphone Permission

Check browser site permissions and Windows microphone privacy settings. Typed
transcript commands do not require microphone permission.

### No Transcript

Try a shorter recording, speak clearly, or type the transcript manually.

### Unsupported Command

Unsupported commands should return a friendly fallback such as:

```text
I don't know how to do that yet.
```
