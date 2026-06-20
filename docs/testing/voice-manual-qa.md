# Voice Command Manual QA

Use this checklist to verify typed or spoken transcripts through Grandpa's safe
voice command route. These checks should not bypass desktop automation approval.

## Setup

1. Start the Grandpa server or desktop app normally.
2. Open the Voice Assistant page.
3. Use the transcript input to run each command.
4. Confirm actions only when the UI shows a confirmation button.

## Commands

| Command | Expected behavior |
| --- | --- |
| `open notepad` | Routes as a desktop action. If the local action layer classifies it as safe, it should complete with `Done.` Otherwise it should request confirmation. |
| `type hello` | Requests confirmation before typing. It must not type silently. |
| `type hello in notepad` | Requests confirmation before focusing Notepad and typing. Confirming should execute once; confirming the same token again should be blocked. |
| `press enter` | Routes through desktop automation permissions. Confirm if prompted; it must not bypass approval. |
| `remind me tomorrow 7 PM` | Creates a reminder if the reminder parser accepts the phrase. The response should say `Reminder created successfully.` |
| `what is my voice status` | Returns current voice status without microphone, cloud, Ollama, or desktop automation. |
| Unsupported commands | Return `I don't know how to do that yet.` and should appear as `unsupported`. |
| Blocked commands | Return `That action is blocked for safety.` and must not execute. Examples include destructive file/system requests. |

## History

- Each command result should appear in Command History.
- History entries should include timestamp, transcript, assistant response,
  action type, and action status.
- Only the latest 100 commands should be retained.
- Clear history should remove all visible command history without affecting
  reminders, backend state, or pending desktop approvals.

## Confirmation

- A confirmation-required command should return a confirmation token internally
  and show a Confirm Action button in the UI.
- Confirm Action should execute the pending safe action once through the
  existing local action approval system.
- Reusing the same confirmation token should be blocked.

## Safety Notes

- Do not use real destructive commands during manual QA.
- Do not approve any action unless the displayed transcript and action status
  match the command being tested.
- Voice command QA does not require microphone hardware; typed transcripts are
  sufficient.
