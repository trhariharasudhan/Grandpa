# Local Whisper Speech-to-Text Manual QA

These checks verify user-initiated local speech recognition only. They do not
enable always-on recording, live wake-word microphone capture, or background
voice loops.

## Setup

1. Install speech extras if needed:
   `uv sync --extra speech`
2. Ensure ffmpeg is installed and available on `PATH`.
3. Start Grandpa normally.
4. Open the Voice Assistant page.

## Status

Call `GET /v1/voice/stt/status` or inspect the Push to Talk section.

Expected:

- Engine is `faster_whisper` when installed.
- Model shows the configured Whisper model, such as `base`.
- Ready is true when local STT dependencies are available.
- Device and compute type match local config.

## Test Cases

| Case | Steps | Expected output |
| --- | --- | --- |
| Record voice | Click Start Recording, speak, then Stop Recording. | Transcript appears with detected language and duration. |
| Upload WAV | Send a `.wav` file to `/v1/voice/listen`. | Response includes `transcript`, `language`, and `duration_seconds`. |
| Upload WEBM | Record in browser or upload `.webm`. | Response includes transcript metadata if ffmpeg can decode it. |
| Upload MP3 | Send a `.mp3` file to `/v1/voice/listen`. | Response includes transcript metadata. |
| Upload M4A | Send a `.m4a` file to `/v1/voice/listen`. | Response includes transcript metadata. |
| Empty audio | Upload an empty audio payload. | Friendly recognition failure; no crash. |
| Invalid audio | Upload text/random bytes as audio. | Friendly recognition failure; no traceback. |
| Missing ffmpeg | Temporarily remove ffmpeg from `PATH`, then upload WEBM/M4A. | Friendly setup message explaining ffmpeg is required. |
| Missing model | Configure an unavailable model or block model download. | Friendly setup message explaining the local Whisper model could not be loaded. |

## Command Flow

After a transcript appears, click Send as Command.

Expected:

- The transcript is sent to `/v1/voice/command`.
- Confirmation-required desktop actions still show the existing confirmation
  flow.
- Dangerous actions remain blocked by the safety layer.

## Safety Notes

- Recording is only user initiated.
- Recording stops when Stop Recording is clicked.
- No always-on microphone listener is started.
- Wake-word live microphone mode is not part of this feature.
