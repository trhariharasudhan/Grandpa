"""An application's risk is judged from what the user said, not from what runs.

``classify_risk`` reads ``request.target`` verbatim and looks it up in one
in-memory dict. Resolution -- the step that turns "bash" into
``git-bash.exe`` -- happens later, inside ``_execute``, and nothing
reclassifies afterwards. So the tier is decided against an unresolved string.

**This file's scope was narrowed once, on evidence.** The first version treated
every shell-sounding inventory row as a safety case. Resolving the shortcuts
disproved two of them and showed that most of the rest cannot be resolved at
all. What follows is what the evidence actually supports.

*Directly identifiable.* ``bash`` resolves to an inventory row backed by
``git-bash.exe`` -- a real executable path, no shortcut in the way. Git Bash is
a general-purpose command shell, ``git-bash.exe`` is in neither
``SENSITIVE_APP_RISK`` nor ``BLOCKED_EXECUTABLE_NAMES``, and the launch is
classified LOW. This is the one case that can be fixed without new machinery,
and it is the acceptance target for the executable-risk work.

*Not identifiable.* ``wsl``, ``git bash``, ``ise`` and ``vs`` are backed by
``.lnk`` shortcuts. Reading them does not recover a usable target: ``WSL.lnk``
yields ``wsl.ico`` (an icon, not the program), ``Developer PowerShell for
VS.lnk`` raises, and the PowerShell shortcuts return unexpanded ``%windir%``
paths. Both a COM reader and a pure-Python parser were measured; neither
recovers these. They stay xfail because the identity is unavailable, not
because a step is merely unimplemented.

*Withdrawn.* ``console`` and ``x64`` were mistakes. ``Console.lnk`` runs
Tesseract-OCR's ``winpath.exe`` with the argument ``cmd``; the display name says
"Console" and the executable is not a shell. ``x64`` resolves to
``PowerShell-7.6.3-win-x64.exe`` in a package cache -- the *installer bundle*,
not ``pwsh.exe``. Both were classified from their names rather than from
evidence. They are kept below as characterisation, recording why they are not
shell-safety cases, so the same inference is not made again.

**On the xfails.** They assert the *resolved-identity* invariant, never the raw
string. An assertion like ``classify_risk("wsl") != "LOW"`` would be satisfied
only by adding spoken words to ``SENSITIVE_APP_RISK`` -- the unbounded
display-name approach this work explicitly rejected -- so a test demanding it
would push toward the wrong fix.

Nothing here reads the machine's inventory and nothing launches: the records
are synthetic, ``find_app`` is redirected at them, and the launcher is replaced
by a recorder that fails the test if it is ever called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grandpa import pc_control
from grandpa.apps.inventory import AppInventoryRecord
from grandpa.apps.resolver import generate_aliases, normalize_app_name, resolve_app
from grandpa.apps.safety import is_safe_launch_target
from grandpa.pc_control import LocalActionRequest

#: The one case whose executable identity is available today: a real ``.exe``
#: path, no shortcut in the way.
RESOLVABLE_SHELL_EXECUTABLE = "git-bash.exe"

#: (spoken, display name, backing file). Taken from a real inventory scan and
#: kept as data so no test reads ``~/.grandpa``. The alias tuple is the one the
#: real row carries -- "bash" reaches this record through an alias, not through
#: the display name, and reproducing that is the point of the fixture.
RESOLVABLE_SHELL = (("bash", "Git", "git-bash.exe"),)
REAL_GIT_ALIASES = ("bash", "git", "git bash")

#: Genuine shells whose identity a shortcut hides. The third column is what
#: shortcut reading actually returns -- measured, not assumed.
UNRESOLVABLE_SHELL = (
    ("wsl", "WSL", "WSL.lnk", "wsl.ico -- an icon, not the program"),
    ("git bash", "Git Bash", "Git Bash.lnk", "resolvable only via COM"),
    (
        "ise",
        "Windows PowerShell ISE (x86)",
        "Windows PowerShell ISE (x86).lnk",
        "%windir% path, unexpanded",
    ),
    (
        "vs",
        "Developer PowerShell for VS",
        "Developer PowerShell for VS.lnk",
        "COM raises com_error",
    ),
)

#: Withdrawn from the shell-safety claim, with the evidence that withdrew them.
NOT_ACTUALLY_SHELLS = (
    (
        "console",
        "Console",
        "Console.lnk",
        "runs Tesseract-OCR winpath.exe with the argument 'cmd'",
    ),
    (
        "x64",
        "PowerShell 7.6.3.0-x64",
        "PowerShell-7.6.3-win-x64.exe",
        "an installer bundle in a package cache, not pwsh.exe",
    ),
)

ORDINARY = (
    ("chrome", "Google Chrome", "chrome.exe"),
    ("notepad", "Notepad", "notepad.exe"),
)

UNAVAILABLE_IDENTITY = (
    "The target is a .lnk shortcut whose executable identity cannot be "
    "recovered: shortcut reading returns an icon path, an unexpanded "
    "environment variable, or raises. Measured with both a COM reader and a "
    "pure-Python parser. Executable-based classification cannot be "
    "established for it, and .lnk resolution is deliberately not implemented."
)

NEEDS_RESOLUTION = (
    "The executable-keyed rule exists and answers correctly when it is handed "
    "the executable. What is still missing is the step that turns the spoken "
    "word into that executable before classification runs: resolution happens "
    "inside _execute, after the tier is already decided. Closing this needs "
    "resolve-then-classify, not another table entry."
)


def _record(
    display_name: str,
    filename: str,
    directory: Any,
    aliases: tuple[str, ...] | None = None,
) -> AppInventoryRecord:
    """One inventory row, built the way the scanner builds them.

    ``aliases`` is supplied only where the real scan produced a set that
    ``generate_aliases`` does not reproduce from these two fields alone.
    """
    target = directory / filename
    target.write_text("", encoding="utf-8")
    return AppInventoryRecord(
        display_name,
        normalize_app_name(display_name),
        str(target),
        "test",
        aliases if aliases is not None else generate_aliases(display_name, filename),
        1.0,
    )


@pytest.fixture
def inventory(tmp_path):
    """A synthetic inventory, resolved by the real resolver."""
    directory = tmp_path / "apps"
    directory.mkdir()
    rows: list[tuple[str, str, tuple[str, ...] | None]] = [
        *(
            (display, filename, REAL_GIT_ALIASES)
            for _, display, filename in RESOLVABLE_SHELL
        ),
        *((display, filename, None) for _, display, filename, _ in UNRESOLVABLE_SHELL),
        *((display, filename, None) for _, display, filename, _ in NOT_ACTUALLY_SHELLS),
        *((display, filename, None) for _, display, filename in ORDINARY),
    ]
    return [
        _record(display, filename, directory, aliases)
        for display, filename, aliases in rows
    ]


@pytest.fixture
def resolves_against(monkeypatch, inventory):
    """Point ``find_app`` at the synthetic records, never at ``~/.grandpa``."""

    def fake_find_app(name: str, **_kwargs):
        return resolve_app(name, inventory)

    monkeypatch.setattr("grandpa.apps.inventory.find_app", fake_find_app)
    return inventory


@pytest.fixture
def never_launches(monkeypatch):
    """Any real launch is a failed test, not a started shell."""

    def explode(record):
        raise AssertionError(f"launched {record.display_name!r} during a test")

    monkeypatch.setattr("grandpa.apps.inventory.launch_inventory_app", explode)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GRANDPA_LOCAL_ACTION_LOG", str(tmp_path / "local_actions.jsonl")
    )
    monkeypatch.setenv("GRANDPA_PC_CONTROL_DB", str(tmp_path / "approvals.db"))
    monkeypatch.setattr(
        pc_control, "get_audit_log_path", lambda: tmp_path / "audit.log"
    )
    pc_control.reset_emergency_stop()
    yield
    pc_control.reset_emergency_stop()


def _request(target: str) -> LocalActionRequest:
    return LocalActionRequest(action_type="open_app", target=target)


def _resolved_executable(spoken: str, inventory) -> str | None:
    """The executable a spoken name resolves to, or None when a shortcut hides
    it. This is the whole question: a ``.lnk`` gives a launcher, not identity."""
    result = resolve_app(spoken, inventory)
    if result.status != "found":
        return None
    path = Path(result.matches[0].path)
    return path.name if path.suffix.lower() == ".exe" else None


# ---------------------------------------------------------------------------
# Which identities are actually available
# ---------------------------------------------------------------------------


class TestIdentityAvailability:
    """The line that decides what can be fixed now and what cannot."""

    @pytest.mark.parametrize(("spoken", "display", "executable"), RESOLVABLE_SHELL)
    def test_a_directly_backed_row_yields_its_executable(
        self, spoken, display, executable, resolves_against
    ):
        assert _resolved_executable(spoken, resolves_against) == executable

    @pytest.mark.parametrize(
        ("spoken", "display", "filename", "why"), UNRESOLVABLE_SHELL
    )
    def test_a_shortcut_backed_row_yields_no_executable(
        self, spoken, display, filename, why, resolves_against
    ):
        """Not a resolver failure -- the row genuinely points at a launcher."""
        assert _resolved_executable(spoken, resolves_against) is None

    @pytest.mark.parametrize(
        ("spoken", "display", "filename", "why"), UNRESOLVABLE_SHELL
    )
    def test_the_shortcut_still_resolves_to_a_record(
        self, spoken, display, filename, why, resolves_against
    ):
        """The name resolves; it is the *executable* that does not."""
        result = resolve_app(spoken, resolves_against)

        assert result.status == "found"
        assert result.matches[0].display_name == display

    def test_the_resolvable_case_is_the_only_one(self):
        """One case is closable without shortcut resolution. Recorded so a
        future reader does not expect the others to be within reach."""
        assert len(RESOLVABLE_SHELL) == 1
        assert len(UNRESOLVABLE_SHELL) == 4


# ---------------------------------------------------------------------------
# The two withdrawn cases, and why
# ---------------------------------------------------------------------------


class TestWithdrawnFromTheShellSafetyClaim:
    """Both were classified from their display names. Both were wrong.

    Kept as characterisation rather than deleted: the useful content is the
    evidence, and a future audit that meets "Console" in an inventory should
    find the answer here rather than repeat the inference.
    """

    @pytest.mark.parametrize(
        ("spoken", "display", "filename", "evidence"), NOT_ACTUALLY_SHELLS
    )
    def test_it_still_resolves(
        self, spoken, display, filename, evidence, resolves_against
    ):
        result = resolve_app(spoken, resolves_against)

        assert result.status == "found"
        assert result.matches[0].display_name == display

    def test_console_is_a_tesseract_helper_not_a_shell(self):
        """``Console.lnk`` runs ``winpath.exe`` with the argument ``cmd``. The
        executable is Tesseract-OCR's, and the shell-sounding part is the
        shortcut's name."""
        assert "console" not in pc_control.SENSITIVE_APP_RISK

    def test_x64_is_an_installer_not_a_shell(self):
        """``PowerShell-7.6.3-win-x64.exe`` in a package cache is the installer
        bundle. ``pwsh.exe`` is the shell, and it is already covered."""
        assert "x64" not in pc_control.SENSITIVE_APP_RISK
        assert pc_control.SENSITIVE_APP_RISK["pwsh.exe"] == "MEDIUM"

    def test_a_shell_sounding_name_is_not_evidence(self):
        """The general form of both mistakes."""
        for name in ("console", "x64", "offlinescannershell", "wslhost", "gitk"):
            assert pc_control.classify_risk(_request(name)) == "LOW"


# ---------------------------------------------------------------------------
# Current behaviour, pinned
# ---------------------------------------------------------------------------


class TestClassificationNeverSeesTheIdentity:
    @pytest.mark.parametrize(("spoken", "_display", "_executable"), RESOLVABLE_SHELL)
    def test_the_resolvable_shell_is_an_ordinary_launch_today(
        self, spoken, _display, _executable
    ):
        assert pc_control.classify_risk(_request(spoken)) == "LOW"

    def test_it_was_added_to_neither_existing_table(self):
        """The rule lives in its own executable-keyed table. Neither the
        spoken-name table nor the launch denylist was touched to get it."""
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        assert RESOLVABLE_SHELL_EXECUTABLE not in pc_control.SENSITIVE_APP_RISK
        assert RESOLVABLE_SHELL_EXECUTABLE not in BLOCKED_EXECUTABLE_NAMES

    def test_classification_reads_the_target_verbatim(self):
        assert pc_control._sensitive_app_risk("windows powershell") == "MEDIUM"
        assert pc_control._sensitive_app_risk("windows powershell (x86)") is None

    def test_the_launch_leaf_only_reads_the_filename(self):
        """Why the executable denylist misses a shortcut: it tests the
        launcher's own name, and a .lnk is not the .exe it starts."""
        assert is_safe_launch_target("C:/x/powershell.exe") is False
        assert is_safe_launch_target("C:/x/Windows PowerShell (x86).lnk") is True
        assert is_safe_launch_target("C:/x/git-bash.exe") is True


class TestTheOrderingThatCausesIt:
    def test_the_tier_is_decided_before_resolution_is_consulted(
        self, isolated, resolves_against, never_launches, monkeypatch
    ):
        calls: list[str] = []
        original_classify = pc_control._classify_risk_impl

        def record_classify(request):
            calls.append("classify")
            return original_classify(request)

        def record_resolve(name, **_kwargs):
            calls.append("resolve")
            return resolve_app(name, resolves_against)

        monkeypatch.setattr(pc_control, "_classify_risk_impl", record_classify)
        monkeypatch.setattr("grandpa.apps.inventory.find_app", record_resolve)

        pc_control.run_local_action({"action_type": "open_app", "target": "bash"})

        assert "classify" in calls
        assert calls.index("classify") < calls.index("resolve"), (
            "resolution must not be able to inform the tier while it runs after it"
        )

    def test_resolution_is_never_reclassified(
        self, isolated, resolves_against, never_launches, monkeypatch
    ):
        seen: list[str] = []
        original = pc_control._sensitive_app_risk

        def record(target):
            seen.append(target)
            return original(target)

        monkeypatch.setattr(pc_control, "_sensitive_app_risk", record)

        pc_control.run_local_action({"action_type": "open_app", "target": "bash"})

        assert seen, "classification did not run at all"
        assert all(target == "bash" for target in seen), (
            f"only the raw target is ever classified, but saw {seen}"
        )
        assert not any("git-bash" in target for target in seen)


# ---------------------------------------------------------------------------
# The acceptance target: an executable-keyed rule
# ---------------------------------------------------------------------------


class TestTheExecutableRule:
    """``git-bash.exe`` -> MEDIUM -> approval. Closed by the executable rule.

    Git Bash is a general-purpose command shell, which is the same reason
    ``cmd`` and ``powershell`` are MEDIUM. The rule is keyed on the executable
    filename and on nothing else: not "bash", not "Git Bash", not a shortcut
    name. Those are display names and aliases, and classifying by them is the
    unbounded approach this work rejected.
    """

    def test_the_shell_executable_is_not_an_ordinary_launch(self):
        assert pc_control.classify_risk(_request(RESOLVABLE_SHELL_EXECUTABLE)) == (
            "MEDIUM"
        )

    def test_launching_the_shell_executable_asks_first(self):
        assert (
            pc_control._launch_needs_approval(_request(RESOLVABLE_SHELL_EXECUTABLE))
            is True
        )

    def test_the_policy_boundary_stages_it(self, isolated, never_launches):
        """End to end through the real boundary, with nothing patched but the
        launcher -- which fails the test if execution is ever reached."""
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": RESOLVABLE_SHELL_EXECUTABLE}
        )

        assert response.status == "approval_required"
        assert response.approval_required is True
        assert response.risk_level == "MEDIUM"

    def test_it_ranks_with_the_other_shells(self):
        assert pc_control.classify_risk(_request(RESOLVABLE_SHELL_EXECUTABLE)) == (
            pc_control.classify_risk(_request("cmd"))
        )

    def test_it_is_classified_not_refused(self):
        """MEDIUM plus approval is not the same answer as a launch refusal, and
        this slice deliberately gives the first without the second."""
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES, is_safe_launch_target

        assert RESOLVABLE_SHELL_EXECUTABLE not in BLOCKED_EXECUTABLE_NAMES
        assert is_safe_launch_target(
            f"C:/Program Files/Git/{RESOLVABLE_SHELL_EXECUTABLE}"
        )
        assert (
            pc_control.classify_risk(_request(RESOLVABLE_SHELL_EXECUTABLE)) != "BLOCKED"
        )

    def test_only_the_executable_spelling_is_listed(self):
        """No stem, no display name, no alias. "git-bash" is not an executable
        identity and nothing invents one."""
        for spelling in ("git-bash", "git bash", "bash", "Git Bash", "git-bash.lnk"):
            assert pc_control.classify_risk(_request(spelling)) == "LOW", spelling


class TestStillWaitingOnResolution:
    """The spoken word does not yet reach the executable rule.

    ``TestIdentityAvailability`` proves ``bash`` resolves to ``git-bash.exe``,
    and ``TestTheExecutableRule`` proves that executable classifies MEDIUM. The
    missing link is ordering: resolution runs inside ``_execute``, after the
    tier has already been decided from the raw string.
    """

    @pytest.mark.xfail(strict=True, reason=NEEDS_RESOLUTION)
    def test_the_spoken_name_reaches_the_same_verdict(self, resolves_against):
        """Via the resolved identity, never by listing "bash" as a name."""
        executable = _resolved_executable("bash", resolves_against)
        assert executable == RESOLVABLE_SHELL_EXECUTABLE

        assert pc_control.classify_risk(_request("bash")) == "MEDIUM"

    @pytest.mark.xfail(strict=True, reason=NEEDS_RESOLUTION)
    def test_the_policy_boundary_stages_a_spoken_shell_launch(
        self, isolated, resolves_against, never_launches
    ):
        """The architectural acceptance test, end to end at the real boundary.

        No classifier is patched and no result is faked: the request goes
        through ``run_local_action`` exactly as a caller's would. The launcher
        is replaced by a recorder, so if the action is *not* staged the test
        fails by reaching it -- which is what happens today.
        """
        response = pc_control.run_local_action(
            {"action_type": "open_app", "target": "bash"}
        )

        assert response.status == "approval_required"
        assert response.approval_required is True


# ---------------------------------------------------------------------------
# Deferred: identity is unavailable, not merely unused
# ---------------------------------------------------------------------------


class TestTheDeferredCases:
    """Genuine shells behind shortcuts.

    These do not wait on a rule; they wait on an identity that shortcut reading
    does not produce. Asserted against the resolved executable rather than the
    spoken word, because a raw-name assertion would be satisfied by adding
    spoken words to the name table -- the approach this work rejected.
    """

    @pytest.mark.xfail(strict=True, reason=UNAVAILABLE_IDENTITY)
    @pytest.mark.parametrize(
        ("spoken", "display", "filename", "why"), UNRESOLVABLE_SHELL
    )
    def test_the_executable_identity_is_recoverable(
        self, spoken, display, filename, why, resolves_against
    ):
        assert _resolved_executable(spoken, resolves_against) is not None

    @pytest.mark.xfail(strict=True, reason=UNAVAILABLE_IDENTITY)
    @pytest.mark.parametrize(
        ("spoken", "display", "filename", "why"), UNRESOLVABLE_SHELL
    )
    def test_the_shell_behind_the_shortcut_is_not_an_ordinary_launch(
        self, spoken, display, filename, why, resolves_against
    ):
        executable = _resolved_executable(spoken, resolves_against)
        assert executable is not None

        assert pc_control.classify_risk(_request(executable)) != "LOW"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


class TestScope:
    def test_the_sensitive_table_is_untouched(self):
        assert len(pc_control.SENSITIVE_APP_RISK) == 21
        assert pc_control.SENSITIVE_APP_RISK["cmd"] == "MEDIUM"
        assert pc_control.SENSITIVE_APP_RISK["regedit"] == "HIGH"

    def test_no_spoken_name_was_added_to_the_table(self):
        """The rejected fix, guarded against."""
        for spoken, *_ in (
            *RESOLVABLE_SHELL,
            *UNRESOLVABLE_SHELL,
            *NOT_ACTUALLY_SHELLS,
        ):
            assert spoken not in pc_control.SENSITIVE_APP_RISK

    def test_the_executable_denylist_is_untouched(self):
        from grandpa.apps.safety import BLOCKED_EXECUTABLE_NAMES

        assert set(BLOCKED_EXECUTABLE_NAMES) == {
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "regedit.exe",
            "diskpart.exe",
        }

    def test_names_already_in_the_table_still_work(self):
        assert pc_control.classify_risk(_request("terminal")) == "MEDIUM"
        assert pc_control.classify_risk(_request("regedit")) == "HIGH"
        assert pc_control.classify_risk(_request("chrome")) == "LOW"

    @pytest.mark.parametrize(("spoken", "_display", "_executable"), ORDINARY)
    def test_ordinary_applications_are_unaffected(
        self, spoken, _display, _executable, resolves_against
    ):
        assert pc_control.classify_risk(_request(spoken)) == "LOW"
        assert pc_control._launch_needs_approval(_request(spoken)) is False
