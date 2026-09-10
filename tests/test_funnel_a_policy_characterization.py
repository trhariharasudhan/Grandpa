"""What Funnel A decides today, recorded before anything merges it.

``local_actions.classify_permission`` is the whole of Funnel A's policy. Funnel
B's classifier has ``tests/test_risk_classification_characterization.py`` --
180 tests derived from its tables. Funnel A had none, which is why
``MIGRATION_PLAN`` §4.11's acceptance test ("for every action in **both**
original tables, assert the merged engine produces a decision at least as
strict as the stricter original") could not be written: one of the two
originals was unrecorded. This records it.

**This is a characterisation suite, not a specification.** It says what the
classifier does, including what it does by accident. Several assertions below
pin behaviour that looks like an oversight -- the ignored ``command``
parameter, the case-sensitive prefix test against a case-insensitive keyword
test, the substring match that fires inside longer words. They are recorded
rather than corrected, because a migration that improves behaviour while moving
it cannot be shown to have preserved it.

**No Funnel-B claim is made anywhere here.** Nothing maps a
``PermissionStatus`` onto a ``RiskLevel``, and nothing asserts that either
funnel is stricter than the other. That mapping is a security decision gated on
A-11 and Q-10; inventing it in a test would be deciding it by the back door.

**Purity is the safety property that makes this suite legal.**
``classify_permission``, ``_is_dangerous``, ``_is_known_safe_url`` and
``_is_known_safe_folder`` read no file, open no database and actuate nothing.
Every case builds a ``LocalActionResult`` directly and calls the classifier
directly. Nothing here goes through ``_with_permission``,
``handle_local_action``, ``approve_pending_action`` or ``deny_pending_action``
-- ``_with_permission`` constructs a ``LocalActionApprovalStore`` and writes a
pending row, so routing a matrix of this size through it would write hundreds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grandpa.local_actions import (
    LocalActionResult,
    _is_dangerous,
    _is_known_safe_folder,
    _is_known_safe_url,
    classify_permission,
)

#: The status field is required by the dataclass and never read by the
#: classifier. ``handled`` is one of the values the module actually produces.
NEUTRAL_STATUS = "handled"

SAFE_DOWNLOADS = str(Path.home() / "Downloads")
SAFE_D_DRIVE = str(Path("D:\\"))
SAFE_YOUTUBE = "https://www.youtube.com"
SAFE_GMAIL = "https://mail.google.com"

#: The eleven kinds that reach the allow branch, exactly as the set is written.
ALLOWED_KINDS = (
    "app",
    "folder",
    "url",
    "browser",
    "time",
    "system_info",
    "screen",
    "screenshot",
    "window",
    "app_lookup",
    "pc_control",
)

#: The six words the ``click|`` branch refuses on.
CLICK_BLOCKING_WORDS = ("submit", "checkout", "payment", "purchase", "buy", "login")


def _result(kind, target: str = "") -> LocalActionResult:
    return LocalActionResult(status=NEUTRAL_STATUS, kind=kind, target=target)


def _verdict(kind, target: str = "", command: str = "") -> str:
    return classify_permission(command, _result(kind, target))


# ---------------------------------------------------------------------------
# What the classifier reads, and what it does not
# ---------------------------------------------------------------------------


class TestTheInputsThatMatter:
    """Only ``kind`` and ``target`` are consulted."""

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "open notepad",
            "delete every file on the machine",
            "format c: and shut down",
            "give me the password",
        ],
        ids=["empty", "benign", "dangerous", "very-dangerous", "credential"],
    )
    def test_the_command_argument_is_ignored(self, command):
        """The first parameter is never read.

        A command ``_is_dangerous`` would refuse still classifies on the shape
        of the parsed result alone. The pre-filter runs earlier, in
        ``handle_local_action``; this records that the classifier itself does
        not repeat it.
        """
        assert _verdict("app", "notepad", command) == "allowed"

    @pytest.mark.parametrize(
        "status",
        ["handled", "blocked", "unsupported", "no_match", "requires_confirmation"],
    )
    def test_the_result_status_is_ignored(self, status):
        result = LocalActionResult(status=status, kind="app", target="notepad")

        assert classify_permission("", result) == "allowed"

    def test_an_existing_permission_on_the_result_is_ignored(self):
        """``classify_permission`` recomputes; it does not read a prior verdict.

        ``_with_permission`` is the caller that short-circuits on an existing
        ``requires_confirmation``. The classifier itself does not.
        """
        result = LocalActionResult(
            status=NEUTRAL_STATUS, kind="app", target="notepad", permission="blocked"
        )

        assert classify_permission("", result) == "allowed"


# ---------------------------------------------------------------------------
# window
# ---------------------------------------------------------------------------


class TestWindowKind:
    def test_closing_the_task_manager_is_blocked(self):
        assert _verdict("window", "close|task_manager") == "blocked"

    @pytest.mark.parametrize(
        "target",
        [
            "close|chrome",
            "close|notepad",
            "close|",
            "close|task manager",
            "close|Task_Manager",
            "close|task_manager_extra",
        ],
        ids=[
            "chrome",
            "notepad",
            "empty-suffix",
            "space-not-underscore",
            "different-case",
            "longer-suffix",
        ],
    )
    def test_every_other_close_requires_confirmation(self, target):
        """The task-manager refusal is an **exact** string match.

        ``close|Task_Manager`` and ``close|task manager`` name the same program
        to a human and are merely confirmed, not refused. Recorded as found.
        """
        assert _verdict("window", target) == "requires_confirmation"

    @pytest.mark.parametrize(
        "target",
        ["focus|chrome", "minimize|chrome", "maximize|chrome", "restore|chrome", ""],
    )
    def test_other_window_verbs_fall_through_to_allowed(self, target):
        """Only ``close|`` is gated; the rest reach the allow set below."""
        assert _verdict("window", target) == "allowed"

    def test_the_close_prefix_is_case_sensitive(self):
        """``Close|chrome`` misses the prefix test and is allowed outright."""
        assert _verdict("window", "Close|chrome") == "allowed"


# ---------------------------------------------------------------------------
# folder
# ---------------------------------------------------------------------------


class TestFolderKind:
    @pytest.mark.parametrize("target", [SAFE_DOWNLOADS, SAFE_D_DRIVE])
    def test_a_known_safe_folder_is_allowed(self, target):
        assert _verdict("folder", target) == "allowed"

    @pytest.mark.parametrize(
        "target",
        [
            "",
            "C:\\Windows",
            "C:\\Users",
            str(Path.home()),
            SAFE_DOWNLOADS + "\\",
            SAFE_DOWNLOADS.replace("\\", "/"),
            SAFE_DOWNLOADS.lower(),
            "D:",
            "D:/",
            "d:\\",
        ],
        ids=[
            "empty",
            "windows",
            "users",
            "home",
            "downloads-trailing-sep",
            "downloads-forward-slashes",
            "downloads-lowercased",
            "d-no-sep",
            "d-forward-slash",
            "d-lowercase",
        ],
    )
    def test_anything_else_requires_confirmation(self, target):
        """The allowlist is exact string equality, not path comparison.

        Every near-miss here refers to a folder the allowlist contains, and
        every one of them is confirmed rather than allowed. Recorded as found.
        """
        assert _verdict("folder", target) == "requires_confirmation"


# ---------------------------------------------------------------------------
# url
# ---------------------------------------------------------------------------


class TestUrlKind:
    @pytest.mark.parametrize("target", [SAFE_YOUTUBE, SAFE_GMAIL])
    def test_a_known_safe_url_is_allowed(self, target):
        assert _verdict("url", target) == "allowed"

    @pytest.mark.parametrize(
        "target",
        [
            "",
            "https://example.com",
            SAFE_YOUTUBE + "/",
            SAFE_YOUTUBE.replace("https", "http"),
            "https://youtube.com",
            "https://www.youtube.com/watch?v=x",
            SAFE_GMAIL.upper(),
        ],
        ids=[
            "empty",
            "unlisted",
            "trailing-slash",
            "http-not-https",
            "no-www",
            "with-path",
            "uppercased",
        ],
    )
    def test_anything_else_requires_confirmation(self, target):
        """Exact equality again: a path, a scheme change or a missing ``www``
        all fall outside the allowlist."""
        assert _verdict("url", target) == "requires_confirmation"


# ---------------------------------------------------------------------------
# browser -- click
# ---------------------------------------------------------------------------


class TestBrowserClick:
    @pytest.mark.parametrize("word", CLICK_BLOCKING_WORDS)
    def test_each_blocking_word_refuses_the_click(self, word):
        assert _verdict("browser", f"click|{word}") == "blocked"

    @pytest.mark.parametrize("word", CLICK_BLOCKING_WORDS)
    def test_the_word_check_is_case_insensitive(self, word):
        assert _verdict("browser", f"click|{word.upper()}") == "blocked"

    @pytest.mark.parametrize(
        "target",
        [
            "click|Submit Order",
            "click|Proceed to checkout",
            "click|Confirm payment",
            "click|Complete purchase",
            "click|Buy now",
            "click|Log in",
        ],
        ids=["submit", "checkout", "payment", "purchase", "buy", "login-spaced"],
    )
    def test_realistic_phrases_containing_a_word(self, target):
        """``Log in`` is the one that does not fire.

        The word tested is ``login`` with no space, so ``click|Log in`` is
        merely confirmed. Its expected verdict is asserted in the negative
        cases below; this case is here to show the phrase set that does fire.
        """
        expected = "blocked" if target != "click|Log in" else "requires_confirmation"
        assert _verdict("browser", target) == expected

    @pytest.mark.parametrize(
        "target",
        [
            "click|buyer portal",
            "click|prepayment options",
            "click|logins",
            "click|resubmit",
            "click|checkouts",
            "click|purchases",
        ],
        ids=[
            "buy-inside-buyer",
            "payment-inside-prepayment",
            "login-inside-logins",
            "submit-inside-resubmit",
            "checkout-inside-checkouts",
            "purchase-inside-purchases",
        ],
    )
    def test_the_match_is_a_substring_not_a_word(self, target):
        """``in`` is not tested for; ``buy`` inside ``buyer`` is.

        These are all refused because the check is ``word in target.lower()``
        with no boundary. A link reading "Buyer portal" is blocked. Recorded as
        found -- it is the conservative direction, and changing it is not this
        slice's business.
        """
        assert _verdict("browser", target) == "blocked"

    @pytest.mark.parametrize(
        "target",
        [
            "click|",
            "click|Next",
            "click|Search",
            "click|Read more",
            "click|Log in",
            "click|Sign in",
        ],
        ids=["empty", "next", "search", "read-more", "log-in-spaced", "sign-in"],
    )
    def test_a_click_without_a_blocking_word_requires_confirmation(self, target):
        assert _verdict("browser", target) == "requires_confirmation"

    @pytest.mark.parametrize(
        "target,expected",
        [
            ("click|form|submit", "blocked"),
            ("click|a|b|c|buy", "blocked"),
            ("click|form|next", "requires_confirmation"),
        ],
        ids=["word-after-second-pipe", "word-last-of-many", "no-word-anywhere"],
    )
    def test_the_scan_covers_the_whole_target_not_just_the_first_segment(
        self, target, expected
    ):
        """The keyword test is a substring search over the entire target.

        The target is not split on ``|`` before scanning, so a blocking word
        anywhere in it fires -- including past a second separator.
        """
        assert _verdict("browser", target) == expected

    def test_the_click_prefix_is_case_sensitive(self):
        """``Click|Buy now`` misses the branch entirely and is **allowed**.

        The prefix test is ``startswith``; the keyword test lowercases. A
        capitalised verb therefore skips both and lands in the allow set. This
        is the sharpest accidental behaviour in the classifier, and it is
        recorded rather than fixed.
        """
        assert _verdict("browser", "Click|Buy now") == "allowed"


# ---------------------------------------------------------------------------
# browser -- the other gated prefixes
# ---------------------------------------------------------------------------


class TestBrowserOtherPrefixes:
    @pytest.mark.parametrize(
        "target",
        [
            "focus_search|",
            "focus_search|google",
            "back|",
            "back|1",
            "forward|",
            "forward|1",
            "reload|",
            "reload|hard",
            "form_fill|email",
            "form_fill|",
            "download|report.pdf",
            "download|",
        ],
    )
    def test_they_require_confirmation(self, target):
        assert _verdict("browser", target) == "requires_confirmation"

    @pytest.mark.parametrize(
        "target",
        [
            "",
            "open|https://example.com",
            "summary|",
            "tabs|",
            "links|",
            "headings|",
            "media|",
            "buttons|",
            "context|",
            "task|",
            "search|cats",
            "new_tab|about:blank",
            "focus_search",
            "backwards|",
        ],
        ids=[
            "empty",
            "open",
            "summary",
            "tabs",
            "links",
            "headings",
            "media",
            "buttons",
            "context",
            "task",
            "search",
            "new-tab",
            "no-pipe",
            "back-prefix-of-longer-verb",
        ],
    )
    def test_every_other_browser_target_is_allowed(self, target):
        """Only the ten gated prefixes are confirmed; the read verbs are not.

        ``backwards|`` is included deliberately: it does **not** start with
        ``back|``, so the ``startswith`` tuple does not over-match here.
        """
        assert _verdict("browser", target) == "allowed"


# ---------------------------------------------------------------------------
# The allow set, and everything outside it
# ---------------------------------------------------------------------------


class TestTheAllowedKindSet:
    @pytest.mark.parametrize(
        "kind,target",
        [
            ("app", ""),
            ("app", "notepad"),
            ("folder", SAFE_DOWNLOADS),
            ("url", SAFE_YOUTUBE),
            ("browser", ""),
            ("time", ""),
            ("system_info", ""),
            ("screen", ""),
            ("screenshot", ""),
            ("window", ""),
            ("app_lookup", "chrome"),
            ("pc_control", "volume_up"),
        ],
    )
    def test_each_allowed_kind_is_allowed(self, kind, target):
        assert _verdict(kind, target) == "allowed"

    def test_the_set_has_exactly_eleven_members(self):
        """A guard on the branch itself: if a kind is added to or removed from
        the allow set, this suite must be revisited rather than silently
        covering less."""
        allowed = {
            kind
            for kind in ALLOWED_KINDS
            if _verdict(kind, _neutral_target_for(kind)) == "allowed"
        }

        assert allowed == set(ALLOWED_KINDS)
        assert len(ALLOWED_KINDS) == 11


def _neutral_target_for(kind: str) -> str:
    """A target that reaches the allow branch for *kind* without gating."""
    if kind == "folder":
        return SAFE_DOWNLOADS
    if kind == "url":
        return SAFE_YOUTUBE
    return ""


class TestBlockedAndUnsupported:
    def test_the_blocked_kind_is_blocked(self):
        assert _verdict("blocked", "") == "blocked"
        assert _verdict("blocked", "anything at all") == "blocked"

    @pytest.mark.parametrize(
        "kind",
        ["automation", "agent_plan"],
    )
    def test_the_two_declared_kinds_outside_the_set_are_unsupported(self, kind):
        """``automation`` and ``agent_plan`` are ``ActionKind`` members that the
        allow set does not list, so they reach the default."""
        assert _verdict(kind, "") == "unsupported"

    @pytest.mark.parametrize(
        "kind",
        [None, "", "unknown", "APP", "App", "file", "email"],
        ids=["none", "empty", "unknown", "upper", "title", "file", "email"],
    )
    def test_anything_unrecognised_is_unsupported(self, kind):
        """Including ``None`` and a case variant of a listed kind."""
        assert _verdict(kind, "") == "unsupported"


# ---------------------------------------------------------------------------
# Branch order
# ---------------------------------------------------------------------------


class TestBranchOrder:
    """The gated branches are checked before the allow set, and it matters."""

    def test_a_gated_window_beats_the_allow_set(self):
        assert _verdict("window", "close|chrome") == "requires_confirmation"
        assert _verdict("window", "") == "allowed"

    def test_an_unsafe_folder_beats_the_allow_set(self):
        assert _verdict("folder", "C:\\Windows") == "requires_confirmation"
        assert _verdict("folder", SAFE_DOWNLOADS) == "allowed"

    def test_an_unsafe_url_beats_the_allow_set(self):
        assert _verdict("url", "https://example.com") == "requires_confirmation"
        assert _verdict("url", SAFE_YOUTUBE) == "allowed"

    def test_a_blocking_click_beats_the_allow_set(self):
        assert _verdict("browser", "click|Buy now") == "blocked"
        assert _verdict("browser", "") == "allowed"

    def test_the_task_manager_refusal_beats_the_close_confirmation(self):
        assert _verdict("window", "close|task_manager") == "blocked"
        assert _verdict("window", "close|chrome") == "requires_confirmation"

    def test_the_blocked_kind_is_checked_after_the_allow_set(self):
        """``blocked`` is not in the allow set, so ordering cannot change it --
        recorded because the two branches are adjacent and a reorder would be
        invisible without this."""
        assert _verdict("blocked", "") == "blocked"


# ---------------------------------------------------------------------------
# The helpers, on their own
# ---------------------------------------------------------------------------


class TestIsKnownSafeUrl:
    @pytest.mark.parametrize("url", [SAFE_YOUTUBE, SAFE_GMAIL])
    def test_the_two_allowlisted_urls(self, url):
        assert _is_known_safe_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            SAFE_YOUTUBE + "/",
            " " + SAFE_YOUTUBE,
            SAFE_YOUTUBE.upper(),
            "https://youtube.com",
            "http://www.youtube.com",
            "https://www.youtube.com/feed",
            "https://mail.google.com/mail/u/0",
            "https://example.com",
        ],
        ids=[
            "empty",
            "trailing-slash",
            "leading-space",
            "uppercased",
            "no-www",
            "http",
            "with-path",
            "gmail-with-path",
            "unlisted",
        ],
    )
    def test_everything_else_is_not_known_safe(self, url):
        """Membership of a two-element set, with no normalisation at all."""
        assert _is_known_safe_url(url) is False


class TestIsKnownSafeFolder:
    @pytest.mark.parametrize("path", [SAFE_DOWNLOADS, SAFE_D_DRIVE])
    def test_the_two_allowlisted_folders(self, path):
        assert _is_known_safe_folder(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "",
            SAFE_DOWNLOADS + "\\",
            SAFE_DOWNLOADS.replace("\\", "/"),
            SAFE_DOWNLOADS.lower(),
            " " + SAFE_DOWNLOADS,
            str(Path.home()),
            "D:",
            "D:/",
            "d:\\",
            "C:\\Windows",
        ],
        ids=[
            "empty",
            "trailing-sep",
            "forward-slashes",
            "lowercased",
            "leading-space",
            "home",
            "no-sep",
            "forward-slash",
            "lowercase-drive",
            "windows",
        ],
    )
    def test_everything_else_is_not_known_safe(self, path):
        assert _is_known_safe_folder(path) is False

    def test_it_is_string_equality_not_path_equality(self):
        """``Path`` would call these equal; this function does not."""
        assert _is_known_safe_folder(SAFE_D_DRIVE) is True
        assert _is_known_safe_folder(str(Path("D:/"))) is True
        assert _is_known_safe_folder("D:/") is False


# ---------------------------------------------------------------------------
# _is_dangerous
# ---------------------------------------------------------------------------


DANGEROUS_CASES = [
    ("delete the report", "delete"),
    ("remove the old files", "remove-files"),
    ("remove the old file", "remove-file-singular"),
    ("erase the disk", "erase"),
    ("wipe the drive", "wipe"),
    ("format the disk", "format"),
    ("shutdown the pc", "shutdown"),
    ("restart the pc", "restart"),
    ("reboot the pc", "reboot"),
    ("log off", "log-off"),
    ("logoff", "logoff-joined"),
    ("sign out", "sign-out"),
    ("signout", "signout-joined"),
    ("open the registry", "registry"),
    ("run regedit", "regedit"),
    ("show my password", "password"),
    ("dump credentials", "credential-prefix"),
    ("overwrite the file", "overwrite"),
    ("open command prompt", "command-prompt"),
    ("open commandprompt", "command-prompt-joined"),
    ("run cmd", "cmd"),
    ("run cmd.exe", "cmd-exe"),
    ("open powershell", "powershell"),
    ("open terminal", "terminal"),
    ("record a macro", "macro"),
    ("automate this in a loop", "automate-loop"),
    ("repeat that forever", "repeat-forever"),
    ("run unattended", "unattended"),
    ("start remote control", "remote-control"),
    ("open system32", "system32"),
    ("press alt+f4", "alt-f4"),
    ("press alt + f4", "alt-f4-spaced"),
    ("press ctrl+x", "ctrl-x"),
    ("press ctrl + x", "ctrl-x-spaced"),
    ("complete the purchase", "purchase"),
    ("confirm payment", "payment"),
    ("pay now", "pay"),
    ("buy it", "buy"),
    ("go to checkout", "checkout"),
    ("extract the password", "extract-password"),
    ("read the password", "read-password"),
    ("rm -rf /", "rm-dash"),
    ("del report.txt", "del-space"),
]

SAFE_CASES = [
    ("", "empty"),
    ("open notepad", "open-notepad"),
    ("what time is it", "time"),
    ("take a screenshot", "screenshot"),
    ("remove it", "remove-without-files"),
    ("deleted items", "delete-inside-deleted"),
    ("buyer portal", "buy-inside-buyer"),
    ("payments page", "payment-plural-word-boundary"),
    ("automate this", "automate-without-loop"),
    ("repeat that", "repeat-without-forever"),
    ("delta report", "del-without-space"),
    ("open the terminals", "terminal-plural"),
]


class TestIsDangerous:
    @pytest.mark.parametrize(
        "command", [c for c, _ in DANGEROUS_CASES], ids=[i for _, i in DANGEROUS_CASES]
    )
    def test_each_pattern_fires(self, command):
        assert _is_dangerous(command) is True

    @pytest.mark.parametrize(
        "command", [c for c, _ in SAFE_CASES], ids=[i for _, i in SAFE_CASES]
    )
    def test_ordinary_commands_do_not_fire(self, command):
        assert _is_dangerous(command) is False

    @pytest.mark.parametrize(
        "command",
        [
            "DELETE the report",
            "Shutdown the pc",
            "RUN CMD",
            "Open PowerShell",
        ],
        ids=["delete", "shutdown", "cmd", "powershell"],
    )
    def test_the_patterns_are_case_sensitive(self, command):
        """``re.search`` is called with no flags.

        Production reaches this through ``_normalise``, which lowercases, so
        the case sensitivity is invisible there. Called directly it is not, and
        a future caller that skips normalisation would get ``False`` for
        ``DELETE``. Recorded as found.
        """
        assert _is_dangerous(command) is False

    @pytest.mark.parametrize(
        "command",
        [
            "open terminal in vscode",
            "open terminal in vs code",
            "open terminal in visual studio code",
        ],
        ids=["vscode", "vs-code-spaced", "visual-studio-code"],
    )
    def test_the_vscode_terminal_request_is_exempted(self, command):
        """``_is_safe_desktop_operator_request`` short-circuits ahead of the
        patterns, so this beats ``\\bterminal\\b``."""
        assert _is_dangerous(command) is False

    @pytest.mark.parametrize(
        "command",
        [
            "summarize current desktop state",
            "detect active app and suggest actions",
            "desktop operator diagnostics",
            "operator diagnostics",
        ],
    )
    def test_the_operator_phrases_are_exempted(self, command):
        assert _is_dangerous(command) is False

    @pytest.mark.parametrize(
        "command",
        [
            "open terminal in vscode please",
            "please open terminal in vscode",
            "open terminal in atom",
        ],
        ids=["trailing-text", "leading-text", "different-editor"],
    )
    def test_the_exemption_is_a_full_match(self, command):
        """``re.fullmatch``: anything around the phrase loses the exemption and
        ``\\bterminal\\b`` refuses it again."""
        assert _is_dangerous(command) is True

    def test_the_exemption_is_all_or_nothing(self):
        """Either the whole command is an exempt phrase, or none of it is.

        Appending a dangerous word breaks the ``fullmatch``, so the exemption
        stops applying and the patterns run over the whole string again. There
        is no partial rescue.
        """
        assert _is_dangerous("desktop operator diagnostics") is False
        assert _is_dangerous("desktop operator diagnostics and delete") is True
