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
| `close notepad` | Requests confirmation before closing the window. Confirming should execute once; confirming the same action again should be refused. |
| `type hello`, `type hello in notepad`, `press enter`, `press tab`, `press escape`, `copy selected text`, `paste`, `scroll down`, `scroll up`, `move mouse to center` | **No longer handled on this route.** Each returns `I don't know how to do that yet.` as `unsupported`. AD-025 retired the duplicate keyboard/mouse parser that used to stage these here; AD-026 recorded the removal. They must **not** stage a pending action or type anything. |
| `remind me tomorrow 7 PM` | Creates a reminder if the reminder parser accepts the phrase. The response should say `Reminder created successfully.` |
| `what is my voice status` | Returns current voice status without microphone, cloud, Ollama, or desktop automation. |
| Unsupported commands | Return `I don't know how to do that yet.` and should appear as `unsupported`. |
| Blocked commands | Return `That action is blocked for safety.` and must not execute. Examples include destructive file/system requests. |

> **Keyboard and mouse automation is not gone from the product — only from this
> route.** It lives in the structured automation stack (`grandpa/automation/`),
> which reaches the desktop through `pc_control` with risk classification and
> approval. Exercise it through the Voice Operator page, the chat CLI, or
> `grandpa automation`, not through `/v1/voice/command`. Restoring these intents
> on this route is cross-surface parity work (GAP-02), not a regression to fix
> here.

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
