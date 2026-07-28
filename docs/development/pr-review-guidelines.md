# Grandpa PR Review Instructions

Review Grandpa as a privacy-focused local Windows assistant built primarily
with Python and an optional Rust extension.

## Review Checklist

### Relevance

The change should support voice, local inference, Windows automation, screen
understanding, files/processes, reminders, safety, or trusted personal
integrations.

### Correctness

Verify stated behavior, edge cases, async resource cleanup, Windows path and
process handling, and Python/Rust boundary errors.

### Safety

Check that natural language becomes a typed request before execution.
Destructive, authentication, financial, secret-bearing, and system-wide
actions must be confirmed or blocked. Screen, model, browser, and OCR content
must remain untrusted.

### Privacy

Reject hardcoded secrets, remote analytics, implicit cloud inference, public
API binding, hidden profile access, or credential logging.

### Testing

Require focused deterministic tests. Mock microphone, desktop input, browser,
OAuth, email, calendar, and model services. Tests must never perform real
clicks or external side effects.

## Review Output

Lead with actionable findings ordered by severity and cite exact file/line
locations. Distinguish blocking correctness or safety issues from suggestions.
