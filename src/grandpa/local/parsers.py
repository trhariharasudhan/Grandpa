"""Phrase parsers: user text in, a described action out.

Nothing here executes anything. Each parser returns a LocalActionResult saying
what it understood, and ``status="no_match"`` when it understood nothing, so
the assistant answers instead. Keeping them apart from the executor is what
lets ``execute=False`` be a real dry run rather than a promise.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path

from grandpa.local.types import ConfirmationCallback
from grandpa.local_action_result import LocalActionResult

logger = logging.getLogger(__name__)


# "search <anything>" is a Google search, except the explicit google/youtube
# forms and "search my files for X", which belongs to the file assistant.
_WEB_SEARCH_PATTERN = (
    r"search (?!google for\b)(?!youtube for\b)(?!(?:my |all )?files for\b)(.+)"
)


_APP_ALLOWLIST: dict[str, tuple[str, str]] = {
    "notepad": ("notepad", "Notepad"),
    "calculator": ("calculator", "Calculator"),
    "calc": ("calculator", "Calculator"),
    "chrome": ("chrome", "Chrome"),
    "google chrome": ("chrome", "Chrome"),
    "edge": ("edge", "Microsoft Edge"),
    "microsoft edge": ("edge", "Microsoft Edge"),
    "vs code": ("vscode", "VS Code"),
    "vscode": ("vscode", "VS Code"),
    "visual studio code": ("vscode", "VS Code"),
    "file explorer": ("explorer", "File Explorer"),
    "explorer": ("explorer", "File Explorer"),
    "windows explorer": ("explorer", "File Explorer"),
    "control panel": ("control_panel", "Control Panel"),
    "settings": ("settings", "Settings"),
    "windows settings": ("settings", "Settings"),
    "task manager": ("task_manager", "Task Manager"),
}


_EXACT_SPEECH_CORRECTIONS = {
    "calc-you-later": "calculator",
    "note pad": "notepad",
    "visual studio coat": "vscode",
}


def resolve_fuzzy_app(target: str) -> tuple[str | None, float, str | None]:
    target = target.lower().strip()

    # Check exact allowlist
    if target in _APP_ALLOWLIST:
        app_id, label = _APP_ALLOWLIST[target]
        return app_id, 1.0, label

    # Check exact speech corrections
    if target in _EXACT_SPEECH_CORRECTIONS:
        app_id = _EXACT_SPEECH_CORRECTIONS[target]
        for k, (aid, lbl) in _APP_ALLOWLIST.items():
            if aid == app_id:
                return app_id, 1.0, lbl

    # Check exact inventory match
    try:
        from grandpa.apps.inventory import find_app

        res = find_app(target)
        if res.status == "found" and res.score >= 1.0:
            record = res.matches[0]
            return record.canonical_key, 1.0, record.display_name
    except Exception:
        pass

    # Run SequenceMatcher fuzzy check across all keys in _APP_ALLOWLIST
    from difflib import SequenceMatcher

    best_ratio = 0.0
    best_app_id = None
    best_label = None

    for candidate_key, (app_id, label) in _APP_ALLOWLIST.items():
        ratio = SequenceMatcher(None, target, candidate_key).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_app_id = app_id
            best_label = label

    # Check fuzzy inventory match
    try:
        from grandpa.apps.inventory import find_app

        res = find_app(target)
        if res.status in {"found", "ambiguous"} and res.score > best_ratio:
            record = res.matches[0]
            best_ratio = res.score
            best_app_id = record.canonical_key
            best_label = record.display_name
    except Exception:
        pass

    return best_app_id, best_ratio, best_label


_URL_ALLOWLIST: dict[str, tuple[str, str]] = {
    "youtube": ("https://www.youtube.com", "YouTube"),
    "gmail": ("https://mail.google.com", "Gmail"),
}


_DANGEROUS_PATTERNS = (
    r"\bdelete\b",
    r"\bremove\b.*\bfiles?\b",
    r"\berase\b",
    r"\bwipe\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart\b",
    r"\breboot\b",
    r"\blog\s*off\b",
    r"\bsign\s*out\b",
    r"\bregistry\b",
    r"\bregedit\b",
    r"\bpassword\b",
    r"\bcredential",
    r"\boverwrite\b",
    r"\bcommand\s*prompt\b",
    r"\bcmd(?:\.exe)?\b",
    r"\bpowershell\b",
    r"\bterminal\b",
    r"\bmacro\b",
    r"\bautomate\b.*\bloop\b",
    r"\brepeat\b.*\bforever\b",
    r"\bunattended\b",
    r"\bremote\s*control\b",
    r"\bsystem32\b",
    r"\balt\s*\+\s*f4\b",
    r"\bctrl\s*\+\s*x\b",
    r"\bpurchase\b",
    r"\bpayment\b",
    r"\bpay\b",
    r"\bbuy\b",
    r"\bcheckout\b",
    r"\bextract\b.*\bpassword\b",
    r"\bread\b.*\bpassword\b",
    r"\brm\s+-",
    r"\bdel\s+",
)


def _is_browser_navigation(target: str) -> bool:
    """True when acting on this target navigates the browser somewhere new."""
    return target.startswith(("http://", "https://", "chrome://", "about:"))


def _is_trusted_navigation(target: str) -> bool:
    """True only for domains in tools.browser.trusted_domains (default none)."""
    from grandpa.browser.safety import configured_trusted_domains, is_trusted_url

    return is_trusted_url(target, configured_trusted_domains())


def _is_protected_folder(path: str) -> bool:
    """pc_control's protected set -- the one open_folder enforces."""
    from grandpa.pc_control import _is_protected_path, _resolve_path

    try:
        return _is_protected_path(_resolve_path(path))
    except Exception:
        # A path that cannot be resolved cannot be judged safe.
        return True


def _is_known_safe_folder(path: str) -> bool:
    return path in {str(Path.home() / "Downloads"), str(Path("D:\\"))}


def _normalise(text: str) -> str:
    cmd = text.strip().lower()
    cmd = re.sub(r"[?!.,\s]+$", "", cmd)
    cmd = re.sub(r"\s+", " ", cmd)

    # Map switch to / switch / focus on -> focus
    cmd = re.sub(r"\bswitch\s+to\b", "focus", cmd)
    cmd = re.sub(r"\bswitch\b", "focus", cmd)
    cmd = re.sub(r"\bfocus\s+on\b", "focus", cmd)

    # Strip leading fillers
    fillers = [
        r"^please\s+",
        r"^can\s+you\s+",
        r"^could\s+you\s+",
        r"^would\s+you\s+",
        r"^okay\s*",
        r"^ok\s*",
        r"^hey\s+grandpa\s+",
        r"^grandpa\s+",
    ]
    for pattern in fillers:
        cmd = re.sub(pattern, "", cmd).strip()

    # Normalize trailing UI suffixes and map bring to front
    match = re.match(
        r"^(focus|minimize|maximize|restore|close|open|launch|start|show|bring\s+to\s+front|bring\s+to\s+foreground)\s+(.+)$",
        cmd,
    )
    if match:
        action = match.group(1)
        target = match.group(2).strip()
        # Strip articles
        target = re.sub(r"^(the|my|a|an)\s+", "", target).strip()
        # Strip trailing UI suffixes
        suffixes = [
            r"\s+screen$",
            r"\s+window$",
            r"\s+app$",
            r"\s+application$",
            r"\s+program$",
        ]
        for pattern in suffixes:
            target = re.sub(pattern, "", target).strip()
        if action in {"bring to front", "bring to foreground"}:
            action = "focus"
        cmd = f"{action} {target}"

    bring_match = re.match(r"^bring\s+(.+?)\s+to\s+(?:front|foreground)$", cmd)
    if bring_match:
        target = bring_match.group(1).strip()
        target = re.sub(r"^(the|my|a|an)\s+", "", target).strip()
        suffixes = [
            r"\s+screen$",
            r"\s+window$",
            r"\s+app$",
            r"\s+application$",
            r"\s+program$",
        ]
        for pattern in suffixes:
            target = re.sub(pattern, "", target).strip()
        cmd = f"focus {target}"

    return cmd


def _is_dangerous(command: str) -> bool:
    if _is_safe_desktop_operator_request(command):
        return False
    return any(re.search(pattern, command) for pattern in _DANGEROUS_PATTERNS)


def _parse_safe_action(command: str) -> LocalActionResult:
    # Parse Chrome Profile Selection command
    action_result = _route_with_action_modules(command)
    if action_result is not None:
        return action_result

    operator_result = _parse_desktop_operator_action(command)
    if operator_result.status != "no_match":
        return operator_result

    window_result = _parse_window_action(command)
    if window_result.status != "no_match":
        return window_result

    browser_result = _parse_browser_action(command)
    if browser_result.status != "no_match":
        return browser_result

    screen_result = _parse_screen_action(command)
    if screen_result.status != "no_match":
        return screen_result

    automation_result = _parse_automation_action(command)
    if automation_result.status != "no_match":
        return automation_result

    pc_control_result = _parse_pc_control_action(command)
    if pc_control_result.status != "no_match":
        return pc_control_result

    agent_plan_result = _parse_agent_plan_action(command)
    if agent_plan_result.status != "no_match":
        return agent_plan_result

    if command in {"what time is it", "what's the time", "time", "current time"}:
        # The clock domain owns this answer. It used to be formatted here, and
        # said less: "It is 1:42 PM." against "It is 1:42 PM on Wednesday,
        # September 16, 2026." A user will notice the difference, which is why
        # it is called out rather than slipped in -- and two of the four phrases
        # above are not claimed by the clock's own parser at all, so unifying
        # here is what makes all four answer the same way.
        from grandpa.core.runtime_context import answer_datetime

        message = answer_datetime("time")
        return LocalActionResult(
            status="handled",
            kind="time",
            target="local_time",
            message=message,
            tts_text=message,
        )

    if command in {
        "show system info",
        "system info",
        "show basic system info",
        "what is my system info",
    }:
        message = _system_info_message()
        return LocalActionResult(
            status="handled",
            kind="system_info",
            target="system_info",
            message=message,
            tts_text="Here is your basic system info.",
        )

    if command in {"find installed apps", "list installed apps", "show installed apps"}:
        return LocalActionResult(
            status="handled",
            kind="app_lookup",
            target="installed_apps",
            message="Finding installed apps.",
            tts_text="Finding installed apps.",
        )

    app_location_match = re.fullmatch(r"where is (.+?) installed", command)
    if app_location_match:
        app_name = app_location_match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="app_lookup",
            target=app_name,
            message=f"Finding where {app_name} is installed.",
            tts_text=f"Finding {app_name}.",
        )

    open_target = _strip_open_prefix(command)
    if open_target is None:
        return LocalActionResult(status="no_match")

    if open_target in _URL_ALLOWLIST:
        url, label = _URL_ALLOWLIST[open_target]
        return LocalActionResult(
            status="handled",
            kind="url",
            target=url,
            message=f"Opening {label}.",
            tts_text=f"Opening {label}.",
        )

    if _looks_like_domain(open_target):
        # "open google.com" is an address, not an application. It used to fall
        # through to fuzzy app matching, which answered "Did you mean Google
        # Chrome?" -- and "open example.com" matched nothing at all, so the same
        # phrasing behaved differently depending on whether a similarly-named
        # program happened to be installed. As a URL it goes through browser
        # navigation, which confirms first.
        url = f"https://{open_target}"
        return LocalActionResult(
            status="handled",
            kind="url",
            target=url,
            message=f"Opening {url}.",
            tts_text=f"Opening {open_target}.",
        )

    folder = _folder_for(open_target)
    if folder is not None:
        return LocalActionResult(
            status="handled",
            kind="folder",
            target=str(folder),
            message=f"Opening {open_target.title()}.",
            tts_text=f"Opening {open_target.title()}.",
        )

    unknown_folder = _unknown_folder_path(open_target)
    if unknown_folder is not None:
        return LocalActionResult(
            status="handled",
            kind="folder",
            target=str(unknown_folder),
            message=f"Opening {unknown_folder}.",
            tts_text="Opening that folder.",
        )

    app_id, confidence, label = resolve_fuzzy_app(open_target)
    if confidence >= 1.0:
        return LocalActionResult(
            status="handled",
            kind="app",
            target=app_id,
            message=f"Opening {label}.",
            tts_text=f"Opening {label}.",
        )
    elif confidence >= 0.8:
        return LocalActionResult(
            status="pending_confirmation",
            kind="app",
            target=app_id,
            message=f"Did you mean {label}?",
            tts_text=f"Did you mean {label}?",
            permission="pending",
            pending_action={"command": f"open {app_id}", "canonical_name": label},
        )

    if open_target.startswith(("http://", "https://")):
        return LocalActionResult(
            status="handled",
            kind="url",
            target=open_target,
            message=f"Opening {open_target}.",
            tts_text="Opening that website.",
        )

    return LocalActionResult(status="no_match")


def _is_safe_desktop_operator_request(command: str) -> bool:
    return bool(
        re.fullmatch(r"open terminal in (vs\s*code|vscode|visual studio code)", command)
        or command
        in {
            "summarize current desktop state",
            "detect active app and suggest actions",
            "desktop operator diagnostics",
            "operator diagnostics",
        }
    )


def _parse_desktop_operator_action(command: str) -> LocalActionResult:
    if not _is_safe_desktop_operator_request(command):
        return LocalActionResult(status="no_match")
    try:
        from grandpa.desktop.operator import (
            active_app_actions,
            build_ui_navigation_plan,
            operator_diagnostics,
        )

        if command in {"desktop operator diagnostics", "operator diagnostics"}:
            diagnostics = operator_diagnostics()
            message = (
                "Desktop operator is ready with "
                f"{diagnostics.get('profile_count', 0)} app profile(s), bounded retries, and approval-gated risky actions."
            )
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="desktop_operator|diagnostics",
                message=message,
                tts_text=message,
            )
        if command == "detect active app and suggest actions":
            actions = active_app_actions()
            suggestions = (
                ", ".join(actions.get("suggested_actions") or [])
                or "no app-specific suggestions"
            )
            message = f"Active app: {actions.get('active_app', 'unknown')}. Suggested actions: {suggestions}."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="desktop_operator|active_app",
                message=message,
                tts_text=message,
            )

        plan = build_ui_navigation_plan(command)
        task = plan.get("task", {})
        summary = str(task.get("result_summary") or "Prepared a desktop operator plan.")
        target = f"desktop_operator|{task.get('task_id', 'planned')}"
        if task.get("status") == "waiting_approval":
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target=target,
                message=summary,
                tts_text="Confirmation required for this desktop operator plan.",
                permission="requires_confirmation",
                pending_action={"operator_task": task},
            )
        if task.get("status") == "blocked":
            return LocalActionResult(
                status="blocked",
                kind="blocked",
                target=target,
                message=summary,
                tts_text=summary,
                permission="blocked",
            )
        return LocalActionResult(
            status="handled",
            kind="pc_control",
            target=target,
            message=summary,
            tts_text=summary,
        )
    except Exception as exc:
        logger.debug("Desktop operator routing failed: %s", exc, exc_info=True)
        return LocalActionResult(
            status="error",
            kind="pc_control",
            target="desktop_operator",
            message="Desktop operator is unavailable right now.",
            tts_text="Desktop operator is unavailable right now.",
        )


def _parse_user_skill_action(
    command: str, *, confirm: ConfirmationCallback | None = None
) -> LocalActionResult:
    try:
        from grandpa.skill_builder import (
            SkillValidationError,
            create_user_skill,
            list_user_skills,
            run_user_skill,
        )

        if re.fullmatch(r"(list|show) (custom|user) skills", command):
            skills = list_user_skills(limit=20)["skills"]
            if not skills:
                message = "No custom user skills saved yet."
            else:
                names = ", ".join(skill["name"] for skill in skills[:8])
                message = f"Custom skills: {names}."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target="user_skills|list",
                message=message,
                tts_text=message,
            )

        if re.match(
            r"^(create a skill called|remember this workflow|save this automation)",
            command,
        ):
            try:
                created = create_user_skill({"request": command}, confirm=confirm)
            except SkillValidationError as exc:
                # Saving a skill that acts is itself an approval, and this is
                # the person who would give it. Their "no" is an answer, not a
                # parse failure, so it must not fall through to another route.
                return LocalActionResult(
                    status="error",
                    kind="pc_control",
                    target="user_skill|not_saved",
                    message=str(exc),
                    tts_text=str(exc),
                )
            skill = created["skill"]
            message = f"Saved user skill '{skill['name']}' with {len(skill['workflow_steps'])} declarative step(s)."
            return LocalActionResult(
                status="handled",
                kind="pc_control",
                target=f"user_skill|{skill['skill_id']}",
                message=message,
                tts_text=message,
            )

        for skill in list_user_skills(limit=500)["skills"]:
            triggers = {
                str(item).strip().lower() for item in skill.get("trigger_phrases", [])
            }
            if (
                command in triggers
                or command == str(skill.get("name", "")).strip().lower()
            ):
                result = run_user_skill(
                    skill["skill_id"], params={"user_request": command}
                )
                return LocalActionResult(
                    status="handled"
                    if result["ok"]
                    else (
                        "requires_confirmation"
                        if result["status"] == "approval_required"
                        else "error"
                    ),
                    kind="pc_control",
                    target=f"user_skill|{skill['skill_id']}",
                    message=result["message"],
                    tts_text=result["message"],
                    permission="requires_confirmation"
                    if result["status"] == "approval_required"
                    else None,
                )
    except Exception as exc:
        logger.debug("User skill routing failed: %s", exc, exc_info=True)
        return LocalActionResult(status="no_match")
    return LocalActionResult(status="no_match")


def _route_with_action_modules(command: str) -> LocalActionResult | None:
    """Try decomposed low-risk action handlers before legacy parser branches."""
    try:
        from grandpa.actions import route_action

        return route_action(command)
    except Exception:
        logger.debug("Action module router failed; using legacy parser.", exc_info=True)
        return None


def _parse_pc_control_action(command: str) -> LocalActionResult:
    mapping = {
        "list monitors": ("list_monitors", "monitors"),
        "show monitors": ("list_monitors", "monitors"),
        "detect monitors": ("list_monitors", "monitors"),
        "what monitors are connected": ("list_monitors", "monitors"),
        "what process is active": ("active_process", "active"),
        "what app is active": ("active_process", "active"),
        "show active process": ("active_process", "active"),
        "list processes": ("list_processes", "processes"),
        "show running processes": ("list_processes", "processes"),
        "desktop summary": ("desktop_summary", "desktop"),
        "summarize desktop": ("desktop_summary", "desktop"),
        "pc control diagnostics": ("pc_diagnostics", "diagnostics"),
        "show pc diagnostics": ("pc_diagnostics", "diagnostics"),
        "inspect clipboard": ("clipboard_inspect", "clipboard"),
        "clipboard history": ("clipboard_history", "clipboard"),
        "show clipboard history": ("clipboard_history", "clipboard"),
    }
    if command not in mapping:
        return LocalActionResult(status="no_match")
    action_type, target = mapping[command]
    return LocalActionResult(
        status="handled",
        kind="pc_control",
        target=f"{action_type}|{target}",
        message="Checking PC control context.",
        tts_text="Checking PC control context.",
    )


def _parse_agent_plan_action(command: str) -> LocalActionResult:
    if any(
        phrase in command
        for phrase in (
            "set up my coding workspace",
            "setup my coding workspace",
            "start my coding workspace",
            "research python tutorials and summarize",
            "research python tutorials and summarise",
            "organize my downloads folder",
            "organise my downloads folder",
            "check grandpa readiness and report issues",
            "summarize current webpage and save notes",
            "summarise current webpage and save notes",
        )
    ):
        return LocalActionResult(
            status="handled",
            kind="agent_plan",
            target=command,
            message="Building a safe local execution plan.",
            tts_text="Building a safe local execution plan.",
        )
    return LocalActionResult(status="no_match")


def _parse_automation_action(command: str) -> LocalActionResult:
    match = re.fullmatch(r"type (.+?) in (notepad)", command)
    if match:
        text = match.group(1).strip()
        app = match.group(2).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"focus|{app}||type|{text}",
            message=f'Typing "{text}" in {app.title()}.',
            tts_text=f"Typing that in {app.title()}.",
        )

    match = re.fullmatch(r"type (.+)", command)
    if match:
        text = match.group(1).strip()
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"type|{text}",
            message=f'Typing "{text}".',
            tts_text="Typing that.",
        )

    press_map = {
        "press enter": ("press|enter", "Pressed enter."),
        "press tab": ("press|tab", "Pressed tab."),
        "press escape": ("press|escape", "Pressed escape."),
        "press esc": ("press|escape", "Pressed escape."),
    }
    if command in press_map:
        target, message = press_map[command]
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=target,
            message=message,
            tts_text=message,
        )

    if command in {"scroll down", "scroll up"}:
        direction = "down" if command.endswith("down") else "up"
        message = f"Scrolled {direction}."
        return LocalActionResult(
            status="handled",
            kind="automation",
            target=f"scroll|{direction}",
            message=message,
            tts_text=message,
        )

    if command in {"copy selected text", "copy selection"}:
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|ctrl+c",
            message="Copied the selected text.",
            tts_text="Copied the selected text.",
        )

    if command == "paste":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|ctrl+v",
            message="Pasted from the clipboard.",
            tts_text="Pasted from the clipboard.",
        )

    if command == "switch window":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="hotkey|alt+tab",
            message="Switched window.",
            tts_text="Switched window.",
        )

    if command == "focus chrome":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="focus|chrome",
            message="Trying to focus Chrome.",
            tts_text="Trying to focus Chrome.",
        )

    if command == "click the center of the screen":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="click_center",
            message="Clicked the center of the screen.",
            tts_text="Clicked the center of the screen.",
        )

    if command == "move mouse to center":
        return LocalActionResult(
            status="handled",
            kind="automation",
            target="move_center",
            message="Moved the mouse to the center of the screen.",
            tts_text="Moved the mouse to the center.",
        )

    if command == "click the highlighted button":
        return LocalActionResult(
            status="unsupported",
            kind="automation",
            target="click_highlighted",
            message="Clicking highlighted buttons is not enabled yet.",
            tts_text="Highlighted button clicking is not enabled yet.",
            permission="unsupported",
        )

    return LocalActionResult(status="no_match")


def _parse_window_action(command: str) -> LocalActionResult:
    if command in {"list open windows", "what windows are open", "show open windows"}:
        return LocalActionResult(
            status="handled",
            kind="window",
            target="list|windows",
            message="Checking open windows.",
            tts_text="Checking open windows.",
        )

    # First check for active window actions
    match = re.fullmatch(r"(minimize|maximize|restore|close) active window", command)
    if match:
        action = match.group(1)
        return LocalActionResult(
            status="handled",
            kind="window",
            target=f"{action}|active",
            message=_window_pending_message(action, "active"),
            tts_text=_window_tts(action, "active"),
        )

    # General window target action
    match = re.fullmatch(r"(focus|minimize|maximize|restore|close)\s+(.+)", command)
    if match:
        action = match.group(1)
        raw_target = match.group(2).strip()
        if raw_target != "active" and raw_target != "active window":
            app_id, confidence, label = resolve_fuzzy_app(raw_target)
            if confidence >= 1.0:
                return LocalActionResult(
                    status="handled",
                    kind="window",
                    target=f"{action}|{app_id}",
                    message=_window_pending_message(action, app_id),
                    tts_text=_window_tts(action, app_id),
                )
            elif confidence >= 0.8:
                return LocalActionResult(
                    status="pending_confirmation",
                    kind="window",
                    target=f"{action}|{app_id}",
                    message=f"Did you mean {label}?",
                    tts_text=f"Did you mean {label}?",
                    permission="pending",
                    pending_action={
                        "command": f"{action} {app_id}",
                        "canonical_name": label,
                    },
                )
            else:
                return LocalActionResult(status="no_match")

    return LocalActionResult(status="no_match")


def _window_app_id(target: str) -> str:
    if target in {"vs code", "visual studio code"}:
        return "vscode"
    if target == "file explorer":
        return "explorer"
    if target == "control panel":
        return "control_panel"
    if target == "task manager":
        return "task_manager"
    return target


def _window_pending_message(action: str, target: str) -> str:
    label = "the active window" if target == "active" else _window_label(target)
    if action == "close":
        return f"Close {label}."
    return f"{action.title()} {label}."


def _window_tts(action: str, target: str) -> str:
    label = "the active window" if target == "active" else _window_label(target)
    if action == "close":
        return f"Close {label}."
    return f"{action.title()} {label}."


def _window_label(target: str) -> str:
    if target == "vscode":
        return "VS Code"
    return target.title()


def _parse_screen_action(command: str) -> LocalActionResult:
    if command in {
        "take a screenshot",
        "screenshot",
        "capture screen",
        "capture screenshot",
    }:
        return LocalActionResult(
            status="handled",
            kind="screenshot",
            target="screen",
            message="Taking a screenshot.",
            tts_text="Taking a screenshot.",
        )

    if command in {
        "screen diagnostics",
        "show screen diagnostics",
        "visual diagnostics",
        "visual targeting diagnostics",
        "show visual diagnostics",
        "visual automation diagnostics",
        "screen awareness diagnostics",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="visual_diagnostics"
            if "visual" in command
            else "screen_diagnostics",
            message="Checking visual targeting diagnostics."
            if "visual" in command
            else "Checking screen-awareness diagnostics.",
            tts_text="Checking visual diagnostics."
            if "visual" in command
            else "Checking screen diagnostics.",
        )

    if command in {
        "what window is open",
        "what window is open right now",
        "what app is open",
        "what browser tab am i on",
        "what tab am i on",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="active_window",
            message="Checking the active window.",
            tts_text="Checking the active window.",
        )

    if command in {
        "what is on my screen",
        "read my screen",
        "analyze my screen",
        "describe my screen",
        "screen analysis",
        "what's on my screen",
        "read this error message",
        "read the error message",
        "summarize this page",
        "summarise this page",
        "analyze current screen",
        "analyse current screen",
    }:
        return LocalActionResult(
            status="handled",
            kind="screen",
            target="screen_context",
            message="Analyzing the current screen.",
            tts_text="Analyzing the current screen.",
        )

    return LocalActionResult(status="no_match")


def _parse_browser_action(command: str) -> LocalActionResult:
    if command in {
        "what page am i on",
        "what webpage am i on",
        "what browser page am i on",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="context|active",
            message="Checking the active browser page.",
            tts_text="Checking the active browser page.",
        )

    if command in {
        "what tabs are open",
        "what browser tabs are open",
        "list browser tabs",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="tabs|recent",
            message="Checking recent browser tabs.",
            tts_text="Checking recent browser tabs.",
        )

    if command in {"browser diagnostics", "show browser diagnostics", "browser status"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="diagnostics|browser",
            message="Checking browser diagnostics.",
            tts_text="Checking browser diagnostics.",
        )

    if command in {
        "summarize this webpage",
        "summarise this webpage",
        "summarize current webpage",
        "summarize this web page",
        "summarize this page",
        "summarise this page",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="summary|visible",
            message="Summarizing the visible webpage.",
            tts_text="Summarizing the visible webpage.",
        )

    if command in {
        "read the visible headings",
        "read visible headings",
        "what headings are visible",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="headings|visible",
            message="Reading visible browser headings.",
            tts_text="Reading visible browser headings.",
        )

    if command in {
        "show links on this page",
        "show page links",
        "what links are visible",
        "read visible links",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="links|visible",
            message="Reading visible browser links.",
            tts_text="Reading visible browser links.",
        )

    if command in {
        "what buttons are visible",
        "what buttons are visible?",
        "show visible buttons",
        "read visible buttons",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="buttons|visible",
            message="Reading visible browser buttons.",
            tts_text="Reading visible browser buttons.",
        )

    if command in {
        "focus the search box",
        "focus search box",
        "focus the browser search box",
    }:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="focus_search|visible",
            message="Focusing the visible browser search box.",
            tts_text="Focusing the visible browser search box.",
        )

    if command in {"click the first video", "click first video"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="click|first video",
            message="Clicking the first visible video.",
            tts_text="Clicking the first visible video.",
        )

    if command in {"browser back", "go back", "back in browser"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="back|visible",
            message="Going back in the visible browser.",
            tts_text="Going back in the visible browser.",
        )

    if command in {"browser forward", "go forward", "forward in browser"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="forward|visible",
            message="Going forward in the visible browser.",
            tts_text="Going forward in the visible browser.",
        )

    if command in {"reload browser", "reload page", "refresh page"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="reload|visible",
            message="Reloading the visible browser page.",
            tts_text="Reloading the visible browser page.",
        )

    match = re.fullmatch(r"search google for (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Searching Google for {query}.",
            tts_text=f"Searching Google for {query}.",
        )

    match = re.fullmatch(_WEB_SEARCH_PATTERN, command)
    if match:
        query = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Searching Google for {query}.",
            tts_text=f"Searching Google for {query}.",
        )

    match = re.fullmatch(r"open youtube and search for (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(
            query
        )
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Opening YouTube and searching for {query}.",
            tts_text=f"Opening YouTube and searching for {query}.",
        )

    match = re.fullmatch(r"open youtube and search (.+)", command)
    if match:
        query = match.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(
            query
        )
        return LocalActionResult(
            status="handled",
            kind="browser",
            target=url,
            message=f"Opening YouTube and searching for {query}.",
            tts_text=f"Opening YouTube and searching for {query}.",
        )

    if command in {"open a new tab", "new tab", "open new tab"}:
        return LocalActionResult(
            status="handled",
            kind="browser",
            target="about:blank",
            message="Opening a new browser tab.",
            tts_text="Opening a new browser tab.",
        )

    return LocalActionResult(status="no_match")


_DOMAIN_RE = re.compile(
    r"^(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)*"
    r"\.(com|org|net|io|dev|co|edu|gov|uk|ai|app|me)(/\S*)?$",
    re.IGNORECASE,
)


def _looks_like_domain(value: str) -> bool:
    """True when this names a website rather than an application.

    Kept narrow on purpose -- a known suffix, no spaces. A bare IP address is
    excluded: "open 192.168.1.1" is as likely to be a typo as an intention, and
    guessing a URL from it is not an improvement on saying nothing.
    """
    candidate = str(value or "").strip()
    return " " not in candidate and bool(_DOMAIN_RE.match(candidate))


def _strip_open_prefix(command: str) -> str | None:
    for prefix in ("open my ", "open ", "launch ", "start ", "show my ", "show "):
        if command.startswith(prefix):
            return command[len(prefix) :].strip()
    return None


def _unknown_folder_path(target: str) -> Path | None:
    if re.match(r"^[a-z]:[\\/]", target, re.I):
        return Path(target)
    if target.startswith(("~\\", "~/")):
        return Path.home() / target[2:]
    return None


def _folder_for(target: str) -> Path | None:
    if target in {"downloads", "downloads folder", "download folder"}:
        return Path.home() / "Downloads"
    if target in {"d drive", "d:", "d drive folder", "d folder"}:
        return Path("D:\\")
    return None


def _system_info_message() -> str:
    """Ask the diagnostics domain, which owns this answer now.

    The lines used to be built here, which meant the action layer had no way to
    answer "system info" at all: its nearest catalogued action, pc_diagnostics,
    discloses the username and full paths, and list_processes adds every
    running executable. Someone asking what kind of computer this is should not
    hand over who is using it.
    """
    from grandpa.desktop.control.diagnostics import system_info_message

    return system_info_message()
