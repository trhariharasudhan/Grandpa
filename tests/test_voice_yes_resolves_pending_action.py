"""A spoken "yes" resolves a pending local action through the voice processor.

VoiceCommandProcessor has its own pending-confirmation block, but it is dead:
it checks for status "pending_confirmation" (local_actions returns
"requires_confirmation") and reads a "command" key that is never set.
Approval works anyway, because "yes" falls through to local_actions' own
confirmation handling, which approves the latest pending action.

Renaming the status and key alone would make that dead block fire and re-issue
the original command, which queues a new pending action and asks again. This
test pins the working behaviour so such a change is caught.
"""

from __future__ import annotations

from functools import partial

import grandpa.local_actions as local_actions
from grandpa.local_action_approvals import LocalActionApprovalStore
from grandpa.voice.assistant import VoiceAssistantResponse, VoiceCommandProcessor


def test_spoken_yes_resolves_a_pending_local_action(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        local_actions,
        "LocalActionApprovalStore",
        partial(LocalActionApprovalStore, tmp_path / "approvals.db"),
    )
    executed: list[tuple[str, str]] = []

    def _record_execution(result, **_kwargs):
        executed.append((result.kind, result.target))
        return local_actions.LocalActionResult(
            status="handled", kind=result.kind, target=result.target, message="done"
        )

    monkeypatch.setattr(local_actions, "_execute", _record_execution)
    monkeypatch.setattr(
        VoiceCommandProcessor,
        "_generate_response",
        lambda self, text, **kwargs: VoiceAssistantResponse(
            "LLM fallback", status="handled", kind="chat"
        ),
    )
    processor = VoiceCommandProcessor()

    request = processor.handle_user_input("close notepad")

    assert request.status == "requires_confirmation"
    assert not executed, "a confirmation-gated action ran before approval"
    assert processor._pending_action is None  # the processor's own block stays dead

    approval = processor.handle_user_input("yes")

    assert executed == [("window", "close|notepad")]
    assert approval.status == "handled"
    assert approval.text != "LLM fallback"
