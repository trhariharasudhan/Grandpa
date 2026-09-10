"""The fifteen places the two funnels already meet, recorded side by side.

Production routes part of Funnel A through Funnel B. Three tables in
``local_actions`` say which parts: ``_PC_CONTROL_ROUTED_KINDS`` (2 kinds),
``_WINDOW_ROUTED_VERBS`` (5 verbs) and ``_BROWSER_ROUTED_VERBS`` (8 verbs).
For those fifteen seams, and only those, a single user intent is described by
both policy systems at once -- ``classify_permission`` sees the parsed
``LocalActionResult``, and ``classify_risk`` sees the ``LocalActionRequest``
the router builds from it.

This records what each system answers there. It is the last characterisation
step §4.11 can take before the merge itself, because these seams are the only
place both classifiers are defined on the same intent **without anyone having
decided how the two vocabularies correspond**.

**This file asserts no relationship between the two systems, and must never.**
Not equality, not equivalence, not strictness, not "A maps to B". A
``PermissionStatus`` is not a ``RiskLevel``, ``requires_confirmation`` is not
``approval_required``, and deciding otherwise is A-11's and Q-10's business,
not a test's. The rule is enforced structurally rather than by discipline: the
Funnel-A assertions and the Funnel-B assertions live in **separate classes**,
and no test method in this file ever holds both verdicts at once. If a future
edit needs a single test to see both, that edit is the merge, and it belongs to
a slice with a decision behind it.

**Purity.** ``classify_permission``, ``classify_risk`` and ``requires_approval``
read no file, open no database and actuate nothing. The routers that would
execute -- ``_execute_via_pc_control``, ``_route_window``, ``_route_browser`` --
are deliberately not imported: they call ``run_local_action``, which stages
approvals and writes rows. The routing *tables* are read as data; the routing
*code* is not run.

**The derivation below mirrors production and is guarded.** Two of the three
tables map straight onto an action type; the window table does not, because the
router builds ``f"{verb}_window"`` and defaults an empty target to ``active``
at ``local_actions.py:1877-1880``. That derivation is reproduced here, and
``TestTheDerivedActionTypesAreReal`` fails loudly if it ever stops matching --
an action type production no longer produces would classify as ``BLOCKED`` by
the unknown-action fallback rather than silently testing nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.desktop.kernel.risk import requires_approval
from grandpa.local_actions import (
    _BROWSER_ROUTED_VERBS,
    _PC_CONTROL_ROUTED_KINDS,
    _WINDOW_ROUTED_VERBS,
    LocalActionResult,
    classify_permission,
)
from grandpa.pc_control import LocalActionRequest, classify_risk

NEUTRAL_STATUS = "handled"

#: A folder and a URL the Funnel-A allowlists accept, and ones they do not.
#: Both cases are characterised because the kind routes carry a caller-supplied
#: target and the Funnel-A verdict turns on it.
SAFE_FOLDER = str(Path.home() / "Downloads")
UNSAFE_FOLDER = "C:\\Windows"
SAFE_URL = "https://www.youtube.com"
UNSAFE_URL = "https://example.com"


def _window_action_type(verb: str) -> str:
    """``local_actions.py:1878`` -- ``action_type=f"{action}_window"``."""
    return f"{verb}_window"


def _window_target(name: str) -> str:
    """``local_actions.py:1879`` -- ``target=target or "active"``."""
    return name or "active"


WINDOW_VERBS = sorted(_WINDOW_ROUTED_VERBS)
BROWSER_VERBS = sorted(_BROWSER_ROUTED_VERBS)
KIND_ROUTES = sorted(_PC_CONTROL_ROUTED_KINDS.items())


def _a(kind, target: str = "") -> str:
    """The Funnel-A verdict for a parsed result."""
    return classify_permission(
        "", LocalActionResult(status=NEUTRAL_STATUS, kind=kind, target=target)
    )


def _b_risk(action_type: str, target: str = "") -> str:
    """The Funnel-B tier for the request the router would build."""
    return classify_risk(LocalActionRequest(action_type=action_type, target=target))


def _b_approval(action_type: str, target: str = "") -> bool:
    """The Funnel-B approval predicate for that same request."""
    return requires_approval(LocalActionRequest(action_type=action_type, target=target))


# ---------------------------------------------------------------------------
# The tables themselves
# ---------------------------------------------------------------------------


class TestTheRoutingTablesAreWhatTheyWere:
    """Exact contents, so a routing change forces this suite to be re-read.

    A seam added to production without a case here would otherwise be
    characterised by nothing at all.
    """

    def test_there_are_exactly_two_kind_routes(self):
        assert _PC_CONTROL_ROUTED_KINDS == {
            "folder": "open_folder",
            "url": "browser_open",
        }
        assert len(_PC_CONTROL_ROUTED_KINDS) == 2

    def test_there_are_exactly_five_window_verbs(self):
        assert set(_WINDOW_ROUTED_VERBS) == {
            "close",
            "focus",
            "minimize",
            "maximize",
            "restore",
        }
        assert len(_WINDOW_ROUTED_VERBS) == 5

    def test_there_are_exactly_eight_browser_verbs(self):
        assert _BROWSER_ROUTED_VERBS == {
            "buttons": "browser_buttons",
            "context": "browser_context",
            "headings": "browser_headings",
            "links": "browser_links",
            "media": "browser_media",
            "summary": "browser_summary",
            "tabs": "browser_tabs",
            "task": "browser_task",
        }
        assert len(_BROWSER_ROUTED_VERBS) == 8

    def test_list_is_deliberately_not_routed(self):
        """Recorded because its absence is a decision, not an omission.

        ``local_actions.py`` states it: ``list`` is a read, and routing it
        would let the emergency stop block *querying* windows as well as
        changing them.
        """
        assert "list" not in _WINDOW_ROUTED_VERBS

    @pytest.mark.parametrize(
        "verb",
        ["click", "back", "forward", "reload", "focus_search", "form_fill", "download"],
    )
    def test_the_stub_browser_verbs_are_deliberately_not_routed(self, verb):
        """Also a recorded decision: these are terminal stubs, and two of them
        sit in ``APPROVAL_REQUIRED_ACTIONS``."""
        assert verb not in _BROWSER_ROUTED_VERBS


class TestTheDerivedActionTypesAreReal:
    """The window derivation is a mirror of production; this guards it.

    An action type production no longer builds would fall through
    ``classify_risk``'s unknown-action default to ``BLOCKED``. Asserting that
    none of them does is what stops this file from characterising a type that
    no longer exists.
    """

    @pytest.mark.parametrize("verb", WINDOW_VERBS)
    def test_every_window_verb_derives_a_recognised_action_type(self, verb):
        assert _b_risk(_window_action_type(verb), "active") != "BLOCKED"

    @pytest.mark.parametrize("kind,action_type", KIND_ROUTES)
    def test_every_kind_route_names_a_recognised_action_type(self, kind, action_type):
        assert _b_risk(action_type, "") != "BLOCKED"

    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_every_browser_verb_names_a_recognised_action_type(self, verb):
        assert _b_risk(_BROWSER_ROUTED_VERBS[verb], "") != "BLOCKED"


# ===========================================================================
# FUNNEL A -- what local_actions decides at each seam.
# Nothing in this section may mention a RiskLevel or an approval predicate.
# ===========================================================================


class TestFunnelAAtTheKindRoutes:
    def test_a_safe_folder_is_allowed(self):
        assert _a("folder", SAFE_FOLDER) == "allowed"

    def test_an_unsafe_folder_requires_confirmation(self):
        assert _a("folder", UNSAFE_FOLDER) == "requires_confirmation"

    def test_a_safe_url_is_allowed(self):
        assert _a("url", SAFE_URL) == "allowed"

    def test_an_unsafe_url_requires_confirmation(self):
        assert _a("url", UNSAFE_URL) == "requires_confirmation"


class TestFunnelAAtTheWindowRoutes:
    def test_closing_the_task_manager_is_blocked(self):
        assert _a("window", "close|task_manager") == "blocked"

    def test_closing_anything_else_requires_confirmation(self):
        assert _a("window", "close|chrome") == "requires_confirmation"

    @pytest.mark.parametrize("verb", ["focus", "minimize", "maximize", "restore"])
    def test_the_other_four_verbs_are_allowed(self, verb):
        assert _a("window", f"{verb}|chrome") == "allowed"

    @pytest.mark.parametrize("verb", ["focus", "minimize", "maximize", "restore"])
    def test_they_are_allowed_with_an_empty_name_too(self, verb):
        assert _a("window", f"{verb}|") == "allowed"

    def test_closing_with_an_empty_name_still_requires_confirmation(self):
        assert _a("window", "close|") == "requires_confirmation"


class TestFunnelAAtTheBrowserRoutes:
    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_every_routed_browser_verb_is_allowed(self, verb):
        assert _a("browser", f"{verb}|") == "allowed"

    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_they_are_allowed_with_a_suffix_too(self, verb):
        assert _a("browser", f"{verb}|https://example.com") == "allowed"

    def test_none_of_them_is_a_gated_prefix(self):
        """The gated browser prefixes are a disjoint set from the routed ones.

        Stated as a property of the Funnel-A classifier alone: every routed
        verb reaches the allow branch, and the confirmed prefixes are the ones
        production declined to route.
        """
        assert {f"{verb}|" for verb in BROWSER_VERBS}.isdisjoint(
            {
                "click|",
                "focus_search|",
                "back|",
                "forward|",
                "reload|",
                "form_fill|",
                "download|",
            }
        )


# ===========================================================================
# FUNNEL B -- what pc_control decides for the request the router builds.
# Nothing in this section may mention a PermissionStatus.
# ===========================================================================


class TestFunnelBRiskAtTheKindRoutes:
    def test_open_folder_is_low(self):
        assert _b_risk("open_folder", SAFE_FOLDER) == "LOW"

    def test_open_folder_is_low_for_any_target(self):
        assert _b_risk("open_folder", UNSAFE_FOLDER) == "LOW"

    def test_browser_open_is_low(self):
        assert _b_risk("browser_open", SAFE_URL) == "LOW"

    def test_browser_open_is_low_for_any_target(self):
        assert _b_risk("browser_open", UNSAFE_URL) == "LOW"


class TestFunnelBApprovalAtTheKindRoutes:
    @pytest.mark.parametrize(
        "action_type,target",
        [
            ("open_folder", SAFE_FOLDER),
            ("open_folder", UNSAFE_FOLDER),
            ("browser_open", SAFE_URL),
            ("browser_open", UNSAFE_URL),
        ],
    )
    def test_neither_kind_route_is_approval_gated(self, action_type, target):
        assert _b_approval(action_type, target) is False


class TestFunnelBRiskAtTheWindowRoutes:
    @pytest.mark.parametrize("verb", WINDOW_VERBS)
    def test_every_window_verb_is_medium(self, verb):
        assert _b_risk(_window_action_type(verb), "chrome") == "MEDIUM"

    @pytest.mark.parametrize("verb", WINDOW_VERBS)
    def test_the_default_active_target_is_also_medium(self, verb):
        assert _b_risk(_window_action_type(verb), _window_target("")) == "MEDIUM"

    def test_the_empty_target_defaults_to_active(self):
        assert _window_target("") == "active"
        assert _window_target("chrome") == "chrome"


class TestFunnelBApprovalAtTheWindowRoutes:
    @pytest.mark.parametrize("verb", WINDOW_VERBS)
    def test_no_window_verb_is_approval_gated(self, verb):
        assert _b_approval(_window_action_type(verb), "chrome") is False

    @pytest.mark.parametrize("verb", WINDOW_VERBS)
    def test_not_with_the_default_target_either(self, verb):
        assert _b_approval(_window_action_type(verb), _window_target("")) is False


class TestFunnelBRiskAtTheBrowserRoutes:
    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_every_routed_browser_action_is_low(self, verb):
        assert _b_risk(_BROWSER_ROUTED_VERBS[verb], "") == "LOW"

    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_a_suffix_does_not_change_the_tier(self, verb):
        assert _b_risk(_BROWSER_ROUTED_VERBS[verb], "https://example.com") == "LOW"


class TestFunnelBApprovalAtTheBrowserRoutes:
    @pytest.mark.parametrize("verb", BROWSER_VERBS)
    def test_no_routed_browser_action_is_approval_gated(self, verb):
        assert _b_approval(_BROWSER_ROUTED_VERBS[verb], "") is False

    def test_the_two_unrouted_browser_actions_are_the_gated_ones(self):
        """Stated about Funnel B alone: the two browser actions production
        declined to route are exactly the two that sit in
        ``APPROVAL_REQUIRED_ACTIONS``.
        """
        assert _b_approval("browser_form_fill", "email") is True
        assert _b_approval("browser_download", "report.pdf") is True
        assert "form_fill" not in _BROWSER_ROUTED_VERBS
        assert "download" not in _BROWSER_ROUTED_VERBS


# ---------------------------------------------------------------------------
# The rule this file lives under
# ---------------------------------------------------------------------------


class TestNoMappingIsAsserted:
    """A guard on the suite itself, not on the product.

    The two vocabularies are disjoint sets of strings. Recording that they
    share no member is not a mapping -- it is the reason a mapping has to be
    *decided* rather than inferred, and it is why nothing above compares one
    to the other.
    """

    def test_the_two_vocabularies_share_no_value(self):
        funnel_a = {"allowed", "requires_confirmation", "blocked", "unsupported"}
        funnel_b = {"LOW", "MEDIUM", "HIGH", "BLOCKED"}

        assert funnel_a.isdisjoint(funnel_b)

    def test_no_test_in_this_module_holds_both_verdicts(self):
        """Structural: every helper that reaches a classifier is single-sided,
        and the Funnel-A and Funnel-B classes are separate. This asserts the
        helpers stay that way.
        """
        import inspect

        for helper in (_a, _b_risk, _b_approval):
            source = inspect.getsource(helper)
            reaches_a = "classify_permission" in source
            reaches_b = "classify_risk" in source or "requires_approval" in source

            assert not (reaches_a and reaches_b), (
                f"{helper.__name__} reaches both funnels; "
                "a single-sided helper is what keeps this file a "
                "characterisation rather than a merge"
            )
