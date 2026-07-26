"""OAuth scaffolding for Grandpa Gmail integration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from grandpa.core.config import DEFAULT_CONFIG_DIR

GMAIL_CREDENTIALS_DIR = DEFAULT_CONFIG_DIR / "credentials"
GMAIL_TOKEN_PATH = GMAIL_CREDENTIALS_DIR / "gmail_token.json"
GMAIL_CLIENT_SECRET_PATH = GMAIL_CREDENTIALS_DIR / "gmail_client_secret.json"

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

DEFAULT_SCOPES = (READONLY_SCOPE,)
WRITE_SCOPES = (READONLY_SCOPE, MODIFY_SCOPE, COMPOSE_SCOPE, SEND_SCOPE)


@dataclass(frozen=True)
class GmailAuthStatus:
    configured: bool
    ready: bool
    account: str = ""
    message: str = ""
    token_path: Path = GMAIL_TOKEN_PATH
    client_secret_path: Path = GMAIL_CLIENT_SECRET_PATH


class GmailAuthManager:
    """Manage local OAuth token paths without collecting passwords."""

    def __init__(
        self,
        token_path: Path | str = GMAIL_TOKEN_PATH,
        client_secret_path: Path | str = GMAIL_CLIENT_SECRET_PATH,
    ) -> None:
        self.token_path = Path(token_path)
        self.client_secret_path = Path(client_secret_path)

    def status(self) -> GmailAuthStatus:
        if not self.client_secret_path.exists():
            return GmailAuthStatus(
                configured=False,
                ready=False,
                message=f"Gmail is not configured. Place OAuth client secret at {self.client_secret_path}.",
                token_path=self.token_path,
                client_secret_path=self.client_secret_path,
            )
        if not self.token_path.exists():
            return GmailAuthStatus(
                configured=True,
                ready=False,
                message="Gmail OAuth client is configured, but no token is connected. Run `grandpa gmail setup`.",
                token_path=self.token_path,
                client_secret_path=self.client_secret_path,
            )
        account = self._account_from_token()
        return GmailAuthStatus(
            configured=True,
            ready=True,
            account=account,
            message="Gmail is connected.",
            token_path=self.token_path,
            client_secret_path=self.client_secret_path,
        )

    def disconnect(self) -> bool:
        if self.token_path.exists():
            self.token_path.unlink()
            return True
        return False

    def setup(self, *, scopes: tuple[str, ...] = DEFAULT_SCOPES) -> GmailAuthStatus:
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
            raise GmailNotConfiguredError("Gmail is not connected. Run `grandpa gmail setup`.")
        creds = Credentials.from_authorized_user_file(str(self.token_path), scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._write_token(json.loads(creds.to_json()))
        if not creds.valid:
            raise GmailNotConfiguredError("Gmail authentication expired. Run `grandpa gmail setup` again.")
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
            raise GmailDependencyError(
                "Gmail dependencies are missing. Install with: `uv sync --extra gmail` "
                "or `uv sync --extra channel-gmail`."
            )


class GmailDependencyError(RuntimeError):
    """Raised when optional Gmail dependencies are missing."""


class GmailNotConfiguredError(RuntimeError):
    """Raised when Gmail OAuth is not configured."""


__all__ = [
    "COMPOSE_SCOPE",
    "DEFAULT_SCOPES",
    "GMAIL_CLIENT_SECRET_PATH",
    "GMAIL_TOKEN_PATH",
    "GmailAuthManager",
    "GmailAuthStatus",
    "GmailDependencyError",
    "GmailNotConfiguredError",
    "MODIFY_SCOPE",
    "READONLY_SCOPE",
    "SEND_SCOPE",
    "WRITE_SCOPES",
]
