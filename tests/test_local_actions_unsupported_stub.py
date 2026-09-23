"""An unimplemented local action must not report success or queue an approval."""

from __future__ import annotations

import grandpa.local.audit
import grandpa.local.permissions
import grandpa.local.router as local_actions


def test_highlighted_click_stub_is_unsupported_not_handled(monkeypatch) -> None:
    queued: list[dict] = []

    class _GuardStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def create_pending(self, **kwargs):
            queued.append(kwargs)
            return {
                "id": "guard",
                "status": "pending",
                "kind": kwargs.get("kind", ""),
                "target": kwargs.get("target", ""),
                "source_text": kwargs.get("source_text", ""),
                "expires_at": 0,
            }

        def audit(self, **kwargs) -> None:
            pass

        def get_pending(self, *args):
            return None

        def latest_pending(self):
            return None

        def mark(self, *args) -> None:
            pass

    monkeypatch.setattr(grandpa.local.audit, "LocalActionApprovalStore", _GuardStore)
    monkeypatch.setattr(grandpa.local.audit, "log_attempt", lambda *a, **k: None)

    result = local_actions.handle_local_action("click the highlighted button")

    assert result.status == "unsupported"
    assert not result.should_fallback, "the failure must reach the user, not the LLM"
    assert "not enabled" in result.message
    assert result.pending_action is None
    assert not queued, "an approval was queued for an action that cannot run"
