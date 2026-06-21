# Continuous Voice Loop Foundation Manual QA

These checks verify the safe continuous voice loop foundation only. They do not
start microphone capture, real hotword detection, background threads, or
always-on services.

## Setup

1. Start Grandpa normally.
2. Open the Voice Assistant page.
3. Use the Wake Word and Continuous Voice Loop sections.

## Test Cases

| Case | Steps | Expected behavior |
| --- | --- | --- |
| Disabled default | Open the Voice page or call `GET /v1/voice/loop/status`. | Loop is disabled, stopped, and in `idle` mode. |
| Disabled wake word error | Leave wake word disabled. Enable the loop, then click Start. | Start returns an error saying wake word must be enabled first. No microphone starts. |
| Enable wake word | In Wake Word, click Enable. | Wake word status shows enabled. |
| Enable loop | In Continuous Voice Loop, click Enable. | Loop enabled is true, running remains false. |
| Start loop | Click Start after wake word is enabled. | Running is true and mode becomes `waiting_for_wake_word`. |
| Simulate wake | Enter `hey grandpa` and click Simulate Wake. | Detected is true and mode becomes `listening_for_command`. |
| Simulate command | Enter `remind me tomorrow at 7 PM to call Arjun` and click Simulate Command. | Command routes through existing voice command handling. Reminder is created if parsing succeeds, then mode returns to `waiting_for_wake_word`. |
| Unsupported command | Enter an unsupported command and click Simulate Command. | Response is friendly unsupported text, and mode returns to `waiting_for_wake_word`. |
| Stop loop | Click Stop. | Running is false and mode becomes `idle`. |

## API Smoke Checks

`POST /v1/voice/loop/simulate-wake`

```json
{
  "text": "hey grandpa"
}
```

`POST /v1/voice/loop/simulate-command`

```json
{
  "transcript": "what is my voice status"
}
```

## Safety Notes

- Do not expect real audio capture in this phase.
- Do not grant microphone permissions for this checklist.
- Do not approve destructive desktop actions.
- Desktop-like commands must still route through the existing local action
  permission layer.
