"""``grandpa oops`` -- record a problem in one sentence, with the context.

Written for a week of real use. The note is whatever the user types; everything
beside it is collected automatically, because the friction of finding the
numbers is exactly why problems go unreported.

**Which numbers.** Not everything available -- the ones that actually settled
arguments in this project:

* ``speech_window_rms``, ``noise_floor``, ``max_chunk_rms`` and voiced seconds.
  The voice activity contradiction was settled by these four and nothing else:
  a capture reported as "rms 176, never crossed 180" turned out to have speech
  chunks averaging 289, and the whole-buffer figure was the lie. A report that
  says "voice did not hear me" is undiagnosable without them and trivial with
  them.
* ``held_seconds`` and the gate that emptied a transcript. "Heard nothing"
  has at least four distinct causes -- a tap, no audio, every segment dropped,
  a repetition loop -- and they are indistinguishable from the outside.
* the speech model, the LLM model and the configured TTS backend. Two of the
  three have diverged from what actually ran at some point.
* ``scheduler.enabled``, because a reminder that never fired is almost always
  this and not a bug.
* the last command, because "it broke" nearly always means the command before
  this one.
* the platform and version, because identical work on this machine has varied
  105x in wall time and one bug was POSIX-only.

**What it deliberately does not collect.** Anything that costs real time:
no ``doctor`` run, no model load, and in particular no call to
``available_local_engines()`` -- that probes a sidecar whose health check takes
2.25 seconds and always fails. ``oops`` has to be instant or it will not be
used, and the configured backend is the useful fact anyway.

**It must never fail.** A logging command that errors while someone is
reporting a problem is worse than no logging command. Every collector is
individually guarded, the note is written even if every collector fails, and if
the file cannot be written the note is printed so it is not lost.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

#: Everything this module writes lives here, under GRANDPA_HOME -- never a
#: relative path. A relative store is how a ``user_skills.db`` once ended up
#: committed to the repository and then loaded by a test that believed its
#: store was isolated.
_SUBDIR = "diagnostics"

#: One JSON object per line. Append-only, so a crash mid-write costs at most
#: the last line and never the file, and ``--export`` is a concatenation.
_LOG_NAME = "oops.jsonl"

_LAST_COMMAND = "last-command.json"
_LAST_CAPTURE = "last-capture.json"
_LAST_ERROR = "last-error.json"


def diagnostics_dir() -> Path:
    """Resolved at call time, because tests move ``GRANDPA_HOME`` per test."""
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / _SUBDIR


def _redact(value: Any) -> Any:
    """Run the screen redactor over anything that might carry user content.

    The same patterns the screen pipeline uses, so a transcript pasted into a
    note is treated the way a transcript read off the screen would be. Applied
    to the collected context too, not only the note: a command line can carry
    a token in a flag.
    """
    try:
        from grandpa.screen.redaction import redact_screen_text
    except Exception:  # noqa: BLE001 - redaction missing must not lose the note
        return value
    if isinstance(value, str):
        try:
            return redact_screen_text(value).text
        except Exception:  # noqa: BLE001
            return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> bool:
    """Write one small JSON file, atomically, and never raise."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        os.replace(temporary, path)
        return True
    except Exception:  # noqa: BLE001 - a breadcrumb must never break a command
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent or corrupt is simply unknown
        return {}


def _now() -> str:
    try:
        return datetime.now().astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return ""


# =====================================================================
# Breadcrumbs: written by other commands so oops has something to find
# =====================================================================


def command_for_breadcrumb(invoked: str | None) -> list[str]:
    """What to record: the full command line when it is really ours.

    ``sys.argv[1:]`` has the whole command -- ``["reminders", "list"]`` --
    while click's group callback knows only the subcommand, because the rest is
    parsed afterwards. So argv is preferred, but only when it corroborates what
    click actually parsed: under a test runner or any wrapper, argv belongs to
    that process, and a diagnostic naming ``pytest -q`` as the last grandpa
    command is worse than one naming nothing.
    """
    subcommand = str(invoked or "").strip()
    argv = [str(part) for part in sys.argv[1:] if part]
    if subcommand and subcommand in argv:
        # Start at the subcommand, so global flags before it are dropped and a
        # wrapper's own arguments cannot lead.
        return argv[argv.index(subcommand):]
    return [subcommand] if subcommand else []


def record_command(argv: list[str] | None = None) -> bool:
    """Remember the command being run, for the next ``oops`` to report.

    Called from the CLI group, guarded on there being a subcommand, so
    ``grandpa --help`` writes nothing. One small file replace, measured at
    2.1ms on this machine -- which is the difference between this and the
    scheduler thread the same argument rejected.
    """
    arguments = [str(part) for part in (argv if argv is not None else sys.argv[1:]) if part]
    if not arguments:
        # Nothing to record, and overwriting a real breadcrumb with an empty
        # one is worse than not writing: the next report would say the last
        # command was nothing. This happens whenever the group runs with the
        # real argv belonging to some other process.
        return False
    if arguments[0] == "oops":
        # Otherwise every report would say the last command was `oops`.
        return False
    return _write_json(
        diagnostics_dir() / _LAST_COMMAND,
        {"at": _now(), "argv": _redact(arguments)},
    )


def record_error(message: str, *, command: str = "") -> bool:
    """Remember the last error a user was shown.

    Hooked into ``safe_cli_error``, which is the single funnel every expected
    CLI failure already goes through, so this needs no new call sites.
    """
    return _write_json(
        diagnostics_dir() / _LAST_ERROR,
        {
            "at": _now(),
            "message": _redact(str(message))[:2000],
            "command": _redact(command),
        },
    )


def record_capture(audio: Any, *, held_seconds: float = 0.0, reason: str = "",
                   model: str = "", transcript_len: int = -1) -> bool:
    """Remember the numbers from one voice capture.

    These are the four that settled the voice activity argument plus the two
    that tell the failure modes apart. Nothing here is the audio itself.
    """
    payload: dict[str, Any] = {
        "at": _now(),
        "held_seconds": round(float(held_seconds or 0.0), 2),
        "reason": str(reason or ""),
        "model": str(model or ""),
    }
    if transcript_len >= 0:
        payload["transcript_chars"] = int(transcript_len)
    for name in (
        "rms_level",
        "speech_window_rms",
        "noise_floor",
        "max_chunk_rms",
        "speech_active_seconds",
        "duration_seconds",
        "sample_rate",
    ):
        try:
            value = getattr(audio, name, None)
            if value is not None:
                payload[name] = round(float(value), 2)
        except Exception:  # noqa: BLE001 - one odd field is not a failure
            continue
    return _write_json(diagnostics_dir() / _LAST_CAPTURE, payload)


# =====================================================================
# Context collection
# =====================================================================


def _safe(collector: Any, default: Any = None) -> Any:
    """Run one collector. Any failure becomes a missing field, never an error."""
    try:
        return collector()
    except Exception as exc:  # noqa: BLE001 - this is the whole point
        return {"unavailable": f"{type(exc).__name__}"} if default is None else default


def _version() -> str:
    import grandpa

    return str(getattr(grandpa, "__version__", "") or "")


def _platform() -> dict[str, Any]:
    return {
        "sys_platform": sys.platform,
        "python": sys.version.split()[0],
    }


def _models() -> dict[str, Any]:
    """Models and the two settings that have diverged from reality before.

    Reads config only. Nothing here loads a model or asks an engine whether it
    is healthy -- that path costs 2.25s and would make this command unusable.
    """
    from grandpa.core.config import load_config

    config = load_config()
    return {
        "stt_model": getattr(config.speech, "model", ""),
        "stt_device": getattr(config.speech, "device", ""),
        "llm_model": getattr(config.intelligence, "default_model", ""),
        "llm_engine": getattr(config.engine, "default", ""),
        "tts_backend_configured": getattr(config.tts, "backend", ""),
        "tts_enabled": getattr(config.tts, "enabled", None),
        "scheduler_enabled": getattr(config.scheduler, "enabled", None),
        "memory_backend": getattr(config.memory, "default_backend", ""),
    }


def _reminder_counts() -> dict[str, Any]:
    """How many reminders are waiting, and how many are already overdue.

    An overdue count is the single most useful number for the commonest
    reminder complaint, which is that nothing arrived.
    """
    from grandpa.reminders import ReminderStore

    now = datetime.now().astimezone()
    pending = ReminderStore().list(status="pending")
    overdue = [item for item in pending if item.due_at <= now]
    return {"pending": len(pending), "overdue": len(overdue)}


def collect_context() -> dict[str, Any]:
    """Everything worth having, with every field independently guarded."""
    directory = diagnostics_dir()
    return {
        "version": _safe(_version, ""),
        "platform": _safe(_platform, {}),
        "models": _safe(_models),
        "reminders": _safe(_reminder_counts),
        "last_command": _safe(
            lambda: _read_json(directory / _LAST_COMMAND) or {"unavailable": "none recorded"}
        ),
        "last_capture": _safe(
            lambda: _read_json(directory / _LAST_CAPTURE) or {"unavailable": "none recorded"}
        ),
        "last_error": _safe(
            lambda: _read_json(directory / _LAST_ERROR) or {"unavailable": "none recorded"}
        ),
    }


# =====================================================================
# The log
# =====================================================================


@dataclass
class OopsEntry:
    """One recorded problem."""

    note: str = ""
    at: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OopsEntry:
        return cls(
            note=str(raw.get("note", "")),
            at=str(raw.get("at", "")),
            context=raw.get("context") or {},
        )


def log_path() -> Path:
    return diagnostics_dir() / _LOG_NAME


def record(note: str, *, context: dict[str, Any] | None = None) -> tuple[bool, Path]:
    """Append one note plus its context. Returns whether it was written.

    The note is redacted and the context is collected before anything is
    opened, so a failure to collect cannot stop the note being stored.
    """
    entry = {
        "at": _now(),
        "note": _redact(str(note or "").strip()),
        "context": _redact(context if context is not None else _safe(collect_context, {})),
    }
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        return True, path
    except Exception:  # noqa: BLE001 - the caller prints the note instead
        return False, path


def entries() -> list[OopsEntry]:
    """Every recorded note, oldest first. A corrupt line is skipped, not fatal."""
    path = log_path()
    found: list[OopsEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - nothing logged yet is not an error
        return found
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            found.append(OopsEntry.from_dict(json.loads(line)))
        except Exception:  # noqa: BLE001 - one bad line must not hide the rest
            continue
    return found


def export_text(items: list[OopsEntry] | None = None) -> str:
    """One file to hand over. Markdown, because it is read by a person."""
    found = entries() if items is None else items
    lines = [
        "# Grandpa problem log",
        "",
        f"{len(found)} note(s). Collected locally; nothing was sent anywhere.",
        "",
    ]
    for index, entry in enumerate(found, start=1):
        lines.append(f"## {index}. {entry.note or '(no note)'}")
        lines.append("")
        lines.append(f"- when: {entry.at or 'unknown'}")
        for key, value in (entry.context or {}).items():
            if isinstance(value, dict):
                rendered = ", ".join(f"{k}={v}" for k, v in value.items()) or "none"
            else:
                rendered = str(value)
            lines.append(f"- {key}: {rendered}")
        lines.append("")
    return "\n".join(lines)


def export_to(path: Path | str | None = None) -> Path:
    """Write the export beside the log, or wherever asked. Never raises."""
    target = Path(path) if path is not None else diagnostics_dir() / "oops-export.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(export_text(), encoding="utf-8")
    except Exception:  # noqa: BLE001 - reported by the caller
        pass
    return target


__all__ = [
    "OopsEntry",
    "collect_context",
    "command_for_breadcrumb",
    "diagnostics_dir",
    "entries",
    "export_text",
    "export_to",
    "log_path",
    "record",
    "record_capture",
    "record_command",
    "record_error",
]
