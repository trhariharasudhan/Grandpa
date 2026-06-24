# Conversation Mode Manual QA

Conversation mode is a user-controlled session state for follow-up voice turns.
It does not start a microphone, background thread, wake-word loop, or auto-start
service.

## Enable

1. Start the Grandpa server.
2. Open the Voice Assistant page.
3. Find **Conversation Mode**.
4. Click **Enable**.
5. Verify:
   - Enabled shows `enabled`
   - Active remains `stopped`
   - Turn count remains `0`

## Start

1. Click **Start**.
2. Verify:
   - Enabled shows `enabled`
   - Active shows `active`
   - Last activity has a timestamp
   - Timeout shows `60s`

## Send Several Commands

1. Enter `what is my voice status`.
2. Click **Run Command**.
3. Enter `tell me more about that`.
4. Click **Run Command**.
5. Verify:
   - Turn count increments for each successful command
   - Last transcript updates to the latest command
   - Last activity updates after each command

## Stop

1. Click **Stop**.
2. Verify:
   - Enabled remains `enabled`
   - Active changes to `stopped`
   - Turn count is preserved

## Disable

1. Click **Disable**.
2. Verify:
   - Enabled shows `disabled`
   - Active shows `stopped`

## Timeout Expiration

1. Start conversation mode.
2. Wait longer than the configured timeout.
3. Refresh the Voice Assistant page or call:

```powershell
curl http://127.0.0.1:8000/v1/voice/conversation-mode/status
```

4. Verify active changes to `false`.

Timeout is checked only when the API is called. No timer loop runs in the
background.
