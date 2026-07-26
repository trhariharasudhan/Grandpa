"""OAuth scaffolding for Grandpa Google Calendar integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR

CALENDAR_CREDENTIALS_DIR = DEFAULT_CONFIG_DIR / "credentials"
CALENDAR_TOKEN_PATH = CALENDAR_CREDENTIALS_DIR / "calendar_token.json"
CALENDAR_CLIENT_SECRET_PATH = CALENDAR_CREDENTIALS_DIR / "calendar_client_secret.json"

READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
FREEBUSY_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"

DEFAULT_SCOPES = (READONLY_SCOPE,)
WRITE_SCOPES = (READONLY_SCOPE, EVENTS_SCOPE, FREEBUSY_SCOPE)


@dataclass(frozen=True)
class CalendarAuthStatus:
    configured: bool
    ready: bool
    account: str = ""
    message: str = ""
    token_path: Path = CALENDAR_TOKEN_PATH
    client_secret_path: Path = CALENDAR_CLIENT_SECRET_PATH


class CalendarAuthManager:
    """Manage local Calendar OAuth token paths without collecting passwords."""

    def __init__(
        self,
        token_path: Path | str = CALENDAR_TOKEN_PATH,
        client_secret_path: Path | str = CALENDAR_CLIENT_SECRET_PATH,
    ) -> None:
        self.token_path = Path(token_path)
        self.client_secret_path = Path(client_secret_path)

    def status(self) -> CalendarAuthStatus:
        if not self.client_secret_path.exists():
            return CalendarAuthStatus(
                configured=False,
                ready=False,
                message=f"Google Calendar is not configured. Place OAuth client secret at {self.client_secret_path}.",
                token_path=self.token_path,
                client_secret_path=self.client_secret_path,
            )
        if not self.token_path.exists():
            return CalendarAuthStatus(
                configured=True,
                ready=False,
                message="Google Calendar OAuth client is configured, but no token is connected. Run `grandpa calendar setup`.",
                token_path=self.token_path,
                client_secret_path=self.client_secret_path,
            )
        account = self._account_from_token()
        return CalendarAuthStatus(
            configured=True,
            ready=True,
            account=account,
            message="Google Calendar is connected.",
            token_path=self.token_path,
            client_secret_path=self.client_secret_path,
        )

    def disconnect(self) -> bool:
        if self.token_path.exists():
            self.token_path.unlink()
            return True
        return False

    def setup(self, *, scopes: tuple[str, ...] = DEFAULT_SCOPES) -> CalendarAuthStatus:
        self._ensure_dependencies()
        if not self.client_secret_path.exists():
            return self.status()
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_path), scopes)
            creds = flow.run_local_server(port=0)
        self._write_token(json.loads(creds.to_json()))
        return self.status()

    def credentials(self, *, scopes: tuple[str, ...] = DEFAULT_SCOPES):
        self._ensure_dependencies()
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.token_path.exists():
            raise CalendarNotConfiguredError("Google Calendar is not connected. Run `grandpa calendar setup`.")
        creds = Credentials.from_authorized_user_file(str(self.token_path), scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._write_token(json.loads(creds.to_json()))
        if not creds.valid:
            raise CalendarNotConfiguredError("Google Calendar authentication expired. Run `grandpa calendar setup` again.")
        return creds

    def _write_token(self, payload: dict) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

    def _account_from_token(self) -> str:
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        return str(data.get("account") or data.get("client_id") or "")

    @staticmethod
    def _ensure_dependencies() -> None:
        missing = []
        for module in ("googleapiclient.discovery", "google_auth_oauthlib.flow", "google.oauth2.credentials"):
            try:
                __import__(module)
            except ModuleNotFoundError as exc:
                missing.append(exc.name or module)
        if missing:
            raise CalendarDependencyError(
                "Google Calendar dependencies are missing. Install with: `uv sync --extra calendar` "
                "or `uv sync --extra channel-calendar`."
            )


class CalendarDependencyError(RuntimeError):
    """Raised when optional Calendar dependencies are missing."""


class CalendarNotConfiguredError(RuntimeError):
    """Raised when Calendar OAuth is not configured."""


__all__ = [
    "CALENDAR_CLIENT_SECRET_PATH",
    "CALENDAR_TOKEN_PATH",
    "DEFAULT_SCOPES",
    "EVENTS_SCOPE",
    "FREEBUSY_SCOPE",
    "CalendarAuthManager",
    "CalendarAuthStatus",
    "CalendarDependencyError",
    "CalendarNotConfiguredError",
    "READONLY_SCOPE",
    "WRITE_SCOPES",
]
