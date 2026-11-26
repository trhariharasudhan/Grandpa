"""Use Grandpa from your phone, privately, through Tailscale.

How it fits together:

* With phone access on, the desktop app serves its page *and* its socket on
  one fixed loopback port (``127.0.0.1:47710``). Nothing listens on the Wi-Fi
  or the hotspot: Windows Firewall never has to open anything.
* ``tailscale serve`` (one click in Settings > Phone) publishes that port as
  ``https://<your-pc>.<tailnet>.ts.net`` -- reachable only from devices signed
  in to *your* Tailscale account, encrypted end to end, over a hotspot, home
  Wi-Fi or mobile data alike. HTTPS also lets the phone's browser use the mic.
* On top of that, each phone is paired once: the PC shows a QR code holding a
  one-time code (10 minutes, a few tries); the phone swaps it for its own
  device key. Only a hash of the key is kept here, and Forget removes it.
* A paired phone may chat and use a short list of safe calls
  (:data:`PHONE_METHODS`); it cannot add MCP servers, API keys or programs.
  Risky actions still ask before they run, on whichever screen asked.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PORT = 47710
PAIR_SECONDS = 600
PAIR_TRIES = 5
MAX_DEVICES = 10
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I

PHONE_METHODS: tuple[str, ...] = (
    "upload_file", "user_name", "get_profile", "set_next_context",
    "list_memories", "add_memory", "forget_memory",
    "list_skills", "skill_instructions",
    "providers_status",
)
"""What a paired phone may call. Chat itself goes over the socket as always."""

TAILSCALE_PATHS = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
)


def _home() -> Path:
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- settings -----------------------------------------------------------------


def settings_path() -> Path:
    return _home() / "phone.json"


def load_settings() -> dict[str, Any]:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    port = data.get("port")
    return {
        "enabled": data.get("enabled") is True,
        "port": port if isinstance(port, int) and 1024 < port < 65536 else DEFAULT_PORT,
    }


def save_settings(enabled: bool, port: int | None = None) -> dict[str, Any]:
    current = load_settings()
    current["enabled"] = bool(enabled)
    if port is not None:
        current["port"] = int(port)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


# --- paired devices -----------------------------------------------------------


@dataclass
class _Pairing:
    code: str
    expires: float
    tries: int = 0


class DeviceRegistry:
    """Paired phones, kept as hashes in ``<grandpa home>/devices.json``."""

    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path = path or (_home() / "devices.json")
        self.clock = clock
        self._lock = threading.Lock()
        self._pairing: _Pairing | None = None

    # storage
    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in data if isinstance(d, dict) and "hash" in d] if isinstance(data, list) else []

    def _save(self, devices: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(devices, indent=2), encoding="utf-8")

    # pairing
    def start_pairing(self) -> dict[str, Any]:
        """A fresh one-time code (the previous one stops working)."""
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        with self._lock:
            self._pairing = _Pairing(code, self.clock() + PAIR_SECONDS)
        return {"code": code, "expires_in": PAIR_SECONDS}

    def claim(self, code: Any, name: Any = "") -> str | None:
        """Swap a valid code for a new device key; ``None`` otherwise."""
        if not isinstance(code, str):
            return None
        with self._lock:
            pairing = self._pairing
            if pairing is None or self.clock() > pairing.expires:
                self._pairing = None
                return None
            if not hmac.compare_digest(code.strip().upper(), pairing.code):
                pairing.tries += 1
                if pairing.tries >= PAIR_TRIES:
                    self._pairing = None  # guessing ends the code
                return None
            self._pairing = None  # one use
            devices = self._load()
            if len(devices) >= MAX_DEVICES:
                return None
            token = secrets.token_urlsafe(32)
            label = str(name or "Phone").strip()[:40] or "Phone"
            devices.append(
                {
                    "id": secrets.token_hex(4),
                    "name": label,
                    "hash": _hash(token),
                    "paired": int(self.clock()),
                    "seen": int(self.clock()),
                }
            )
            self._save(devices)
            return token

    def check(self, token: Any) -> bool:
        if not isinstance(token, str) or len(token) < 20:
            return False
        digest = _hash(token)
        with self._lock:
            devices = self._load()
            for device in devices:
                if hmac.compare_digest(device["hash"], digest):
                    now = int(self.clock())
                    if now - int(device.get("seen", 0)) > 60:
                        device["seen"] = now
                        try:
                            self._save(devices)
                        except OSError:
                            pass
                    return True
        return False

    def devices(self) -> list[dict[str, Any]]:
        return [
            {k: d.get(k) for k in ("id", "name", "paired", "seen")} for d in self._load()
        ]

    def forget(self, device_id: Any) -> bool:
        if not isinstance(device_id, str):
            return False
        with self._lock:
            devices = self._load()
            kept = [d for d in devices if d.get("id") != device_id]
            if len(kept) == len(devices):
                return False
            self._save(kept)
            return True


# --- Tailscale ----------------------------------------------------------------


def tailscale_cli() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in TAILSCALE_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(  # noqa: S603 - fixed program, fixed arguments
        args, capture_output=True, text=True, timeout=timeout, creationflags=flags
    )


def tailscale_status(cli: str | None = None, run: Callable = _run) -> dict[str, Any]:
    """Installed? Signed in? This PC's name on the tailnet."""
    cli = cli or tailscale_cli()
    if not cli:
        return {"installed": False, "running": False, "name": ""}
    try:
        result = run([cli, "status", "--json"])
        data = json.loads(result.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"installed": True, "running": False, "name": ""}
    state = str(data.get("BackendState", ""))
    name = str((data.get("Self") or {}).get("DNSName", "")).rstrip(".")
    return {"installed": True, "running": state == "Running", "state": state, "name": name}


def tailscale_share(port: int, cli: str | None = None, run: Callable = _run) -> dict[str, Any]:
    """``tailscale serve --bg <port>``: https://<name>.ts.net -> 127.0.0.1:<port>.

    Only devices on your own tailnet can open it (``serve``, not ``funnel``).
    """
    cli = cli or tailscale_cli()
    if not cli:
        return {"ok": False, "error": "Tailscale is not installed."}
    if not isinstance(port, int) or not 1024 < port < 65536:
        return {"ok": False, "error": "Bad port."}
    try:
        result = run([cli, "serve", "--bg", str(port)], timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc)}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        return {"ok": False, "error": detail[-1] if detail else "tailscale serve failed"}
    return {"ok": True}


def phone_address(name: str) -> str:
    return f"https://{name}/" if name else ""


def pair_link(name: str, code: str) -> str:
    # the code rides in the #fragment: it never reaches a server log
    return f"https://{name}/index.html#pair={code}" if name else ""


def qr_svg(text: str) -> str:
    """The QR code as an SVG data URI (``segno``); "" if segno is missing."""
    try:
        import segno
    except ImportError:
        return ""
    import base64

    svg = segno.make(text, error="m").svg_inline(scale=6, border=2, dark="#0b0c0c", light="#ffffff")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


__all__ = [
    "DEFAULT_PORT",
    "DeviceRegistry",
    "PHONE_METHODS",
    "load_settings",
    "pair_link",
    "phone_address",
    "qr_svg",
    "save_settings",
    "tailscale_cli",
    "tailscale_share",
    "tailscale_status",
]
