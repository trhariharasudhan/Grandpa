# Wake Word Foundation Manual QA

These checks verify the safe wake-word foundation only. They do not start
continuous recording, microphone capture, background services, or a real
hotword model.

## Setup

1. Start the Grandpa server or desktop app normally.
2. Open the Voice Assistant page.
3. Find the Wake Word section.
4. Use the test field to submit typed text.

## Test Cases

| Case | Steps | Expected behavior |
| --- | --- | --- |
| Default status | Open the Voice page or call `GET /v1/voice/wake-word/status`. | Wake word is disabled, not listening, phrase is `hey grandpa`, and no microphone is required. |
| Enable | Click Enable or call `POST /v1/voice/wake-word/enable`. | Enabled is true and listening is true. No microphone capture starts. |
| Disable | Click Disable or call `POST /v1/voice/wake-word/disable`. | Enabled is false and listening is false. |
| Test phrase | Enable, enter `hey grandpa`, then click Test. | Response shows detected true and phrase `hey grandpa`. |
| Uppercase phrase | Enable, enter `HEY GRANDPA`, then click Test. | Response shows detected true. Matching is case insensitive. |
| Invalid phrase | Enable, enter `hello assistant`, then click Test. | Response shows detected false. |
| Disabled detection | Disable, enter `hey grandpa`, then click Test. | Response shows detected false because the session is disabled. |
| Restart persistence | Enable, restart the server or desktop app, then check status. | Enabled state and wake phrase are restored from settings. |

## API Shape

`GET /v1/voice/wake-word/status`

Returns enabled state, listening state, current phrase, last detection time,
and truthful flags showing that always-on listening and microphone access are
not active.

`POST /v1/voice/wake-word/test`

```json
{
  "text": "hey grandpa"
}
```

Expected response when enabled:

```json
{
  "detected": true,
  "phrase": "hey grandpa",
  "last_detection_time": "..."
}
```

## Safety Notes

- Do not expect a real wake-word model in this phase.
- Do not expect background listening after enabling.
- Do not grant or test microphone permissions for this checklist.
- The test endpoint accepts typed text only.
