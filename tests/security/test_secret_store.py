"""E1: credentials at rest go through the secret store, encrypted, never logged."""

from __future__ import annotations

import json
import logging
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from grandpa.security import secret_store as ss
from grandpa.security.secret_store import (
    DpapiFileBackend,
    KeyringBackend,
    PlainFileBackend,
    SecretStore,
    SecretStoreError,
    StoredToken,
)

SECRET = "sk-test-very-secret-value-123"


class MemoryBackend:
    """A secure backend that keeps everything in a dict."""

    label = "fake secure"
    secure = True

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = value

    def delete(self, name):
        return self.data.pop(name, None) is not None

    def names(self):
        return sorted(self.data)


class FakeKeyring(types.ModuleType):
    """Stands in for the ``keyring`` package."""

    def __init__(
        self,
        backend_module: str = "keyring.backends.SecretService",
        priority: float = 5,
    ) -> None:
        super().__init__("keyring")
        self.passwords: dict[tuple[str, str], str] = {}
        backend_cls = type("FakeBackend", (), {"priority": priority})
        backend_cls.__module__ = backend_module
        self._backend = backend_cls()

    def get_keyring(self):
        return self._backend

    def get_password(self, service, user):
        return self.passwords.get((service, user))

    def set_password(self, service, user, value):
        self.passwords[(service, user)] = value

    def delete_password(self, service, user):
        del self.passwords[(service, user)]


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> MemoryBackend:
    backend = MemoryBackend()
    monkeypatch.setattr(ss, "default_backend", lambda: backend)
    return backend


@pytest.fixture
def plain_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PlainFileBackend:
    backend = PlainFileBackend(tmp_path / "secrets")
    monkeypatch.setattr(ss, "default_backend", lambda: backend)
    return backend


# -- backends -------------------------------------------------------------------


def test_keyring_backend_round_trip_with_fake_keyring(tmp_path: Path) -> None:
    keyring = FakeKeyring()
    store = SecretStore(KeyringBackend(keyring, directory=tmp_path))
    store.set("gmail.token", SECRET)
    assert store.get("gmail.token") == SECRET
    assert keyring.passwords[("grandpa", "gmail.token")] == SECRET
    assert store.names() == ["gmail.token"]
    assert SECRET not in (tmp_path / "keyring-names.json").read_text()
    assert store.delete("gmail.token") is True
    assert store.get("gmail.token") is None
    assert store.names() == []
    assert store.secure


def test_dpapi_backend_writes_ciphertext_only(tmp_path: Path) -> None:
    def xor(data: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in data)

    backend = DpapiFileBackend(tmp_path, protect=xor, unprotect=xor)
    store = SecretStore(backend)
    store.set("server.api_key", SECRET)
    raw = (tmp_path / "server.api_key.dpapi").read_bytes()
    assert SECRET.encode() not in raw
    assert store.get("server.api_key") == SECRET
    assert store.names() == ["server.api_key"]
    assert "DPAPI" in store.describe()


@pytest.mark.skipif(sys.platform != "win32", reason="real DPAPI is Windows only")
def test_real_dpapi_round_trip(tmp_path: Path) -> None:
    store = SecretStore(DpapiFileBackend(tmp_path))
    store.set("probe", SECRET)
    assert SECRET.encode() not in (tmp_path / "probe.dpapi").read_bytes()
    assert store.get("probe") == SECRET
    store.set("empty", "")
    assert store.get("empty") == ""


def test_plain_backend_is_reported_as_not_encrypted(tmp_path: Path) -> None:
    store = SecretStore(PlainFileBackend(tmp_path))
    assert not store.secure
    assert "NOT encrypted" in store.describe()


def test_bad_names_are_refused(tmp_path: Path) -> None:
    store = SecretStore(PlainFileBackend(tmp_path))
    with pytest.raises(SecretStoreError):
        store.set("../escape", "x")


def test_backend_errors_never_carry_the_value() -> None:
    class Exploding(MemoryBackend):
        def set(self, name, value):
            raise OSError(f"disk said no to {value}")

    with pytest.raises(SecretStoreError) as info:
        SecretStore(Exploding()).set("x", SECRET)
    assert SECRET not in str(info.value)


def test_default_backend_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ss.BACKEND_ENV, "file")
    assert isinstance(ss.default_backend(), PlainFileBackend)
    monkeypatch.setenv(ss.BACKEND_ENV, "dpapi")
    assert isinstance(ss.default_backend(), DpapiFileBackend)
    monkeypatch.delenv(ss.BACKEND_ENV)
    monkeypatch.setattr(ss.sys, "platform", "win32")
    assert isinstance(ss.default_backend(), DpapiFileBackend)
    monkeypatch.setattr(ss.sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring())
    assert isinstance(ss.default_backend(), KeyringBackend)
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring("keyring.backends.fail", 0))
    assert isinstance(ss.default_backend(), PlainFileBackend)


# -- migration ------------------------------------------------------------------


def test_import_file_moves_plaintext_and_logs_no_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    legacy = tmp_path / "token.json"
    legacy.write_text(SECRET, encoding="utf-8")
    store = SecretStore(MemoryBackend())
    with caplog.at_level(logging.DEBUG):
        assert store.import_file("t", legacy) is True
    assert not legacy.exists()
    assert store.get("t") == SECRET
    assert SECRET not in caplog.text


def test_import_file_does_nothing_without_encryption(tmp_path: Path) -> None:
    legacy = tmp_path / "token.json"
    legacy.write_text(SECRET, encoding="utf-8")
    assert (
        SecretStore(PlainFileBackend(tmp_path / "s")).import_file("t", legacy) is False
    )
    assert legacy.exists()


def test_stored_token_migrates_once(tmp_path: Path) -> None:
    legacy = tmp_path / "gmail_token.json"
    legacy.write_text(json.dumps({"refresh_token": SECRET}), encoding="utf-8")
    backend = MemoryBackend()
    token = StoredToken("gmail.token", legacy, SecretStore(backend))
    assert token.load() == {"refresh_token": SECRET}
    assert not legacy.exists()
    token.save({"refresh_token": "new"})
    assert not legacy.exists()
    assert json.loads(backend.data["gmail.token"]) == {"refresh_token": "new"}
    assert token.clear() is True
    assert token.exists() is False


def test_stored_token_keeps_file_when_store_is_plain(tmp_path: Path) -> None:
    legacy = tmp_path / "gmail_token.json"
    token = StoredToken(
        "gmail.token", legacy, SecretStore(PlainFileBackend(tmp_path / "s"))
    )
    token.save({"a": 1})
    assert json.loads(legacy.read_text()) == {"a": 1}
    assert token.load() == {"a": 1}


def test_gmail_token_moves_into_store(
    fake_store: MemoryBackend, tmp_path: Path
) -> None:
    from grandpa.gmail.auth import GmailAuthManager

    secret_file = tmp_path / "client.json"
    secret_file.write_text("{}", encoding="utf-8")
    token = tmp_path / "gmail_token.json"
    token.write_text(
        json.dumps({"account": "hari@example.com", "refresh_token": SECRET})
    )
    manager = GmailAuthManager(token_path=token, client_secret_path=secret_file)

    status = manager.status()
    assert status.ready and status.account == "hari@example.com"
    assert not token.exists()
    assert SECRET in fake_store.data["gmail.token"]
    assert manager.disconnect() is True
    assert "gmail.token" not in fake_store.data


def test_calendar_token_moves_into_store(
    fake_store: MemoryBackend, tmp_path: Path
) -> None:
    from grandpa.calendar.auth import CalendarAuthManager

    secret_file = tmp_path / "client.json"
    secret_file.write_text("{}", encoding="utf-8")
    token = tmp_path / "calendar_token.json"
    token.write_text(json.dumps({"client_id": "cid", "refresh_token": SECRET}))
    manager = CalendarAuthManager(token_path=token, client_secret_path=secret_file)
    assert manager.status().ready
    assert not token.exists()
    assert "calendar.token" in fake_store.data


# -- server API key ---------------------------------------------------------------


def _config_with_key(key: str):
    return types.SimpleNamespace(
        server=types.SimpleNamespace(auth=types.SimpleNamespace(api_key=key))
    )


def test_api_key_moves_out_of_config_toml(
    fake_store: MemoryBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandpa.cli import serve

    config_toml = tmp_path / "config.toml"
    config_toml.write_text(f'[server.auth]\napi_key = "{SECRET}"\n', encoding="utf-8")
    monkeypatch.setattr(serve, "_config_path", lambda: config_toml)
    monkeypatch.delenv("GRANDPA_API_KEY", raising=False)
    monkeypatch.delenv("Grandpa_API_KEY", raising=False)

    key = serve._resolve_api_key(
        _config_with_key(SECRET), Console(file=None, quiet=True)
    )

    assert key == SECRET
    assert fake_store.data["server.api_key"] == SECRET
    assert SECRET not in config_toml.read_text(encoding="utf-8")
    # Next start: config is blank, the store answers.
    assert serve._resolve_api_key(_config_with_key(""), Console(quiet=True)) == SECRET


def test_env_api_key_wins(
    fake_store: MemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandpa.cli import serve

    fake_store.data["server.api_key"] = "stored"
    monkeypatch.setenv("GRANDPA_API_KEY", "from-env")
    assert (
        serve._resolve_api_key(_config_with_key(""), Console(quiet=True)) == "from-env"
    )


def test_api_key_stays_in_config_without_encryption(
    plain_store: PlainFileBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandpa.cli import serve

    config_toml = tmp_path / "config.toml"
    config_toml.write_text('[server.auth]\napi_key = "abc"\n', encoding="utf-8")
    monkeypatch.setattr(serve, "_config_path", lambda: config_toml)
    monkeypatch.delenv("GRANDPA_API_KEY", raising=False)
    monkeypatch.delenv("Grandpa_API_KEY", raising=False)
    assert serve._resolve_api_key(_config_with_key("abc"), Console(quiet=True)) == "abc"
    assert "abc" in config_toml.read_text(encoding="utf-8")


def test_generated_api_key_goes_to_store_not_config(
    fake_store: MemoryBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from grandpa.cli import serve

    config_toml = tmp_path / "config.toml"
    monkeypatch.setattr(serve, "_config_path", lambda: config_toml)
    key = serve._generate_and_persist_api_key(Console(quiet=True))
    assert fake_store.data["server.api_key"] == key
    assert not config_toml.exists()


# -- vault CLI and doctor ------------------------------------------------------------


def test_vault_cli_round_trip_and_list_hides_values(fake_store: MemoryBackend) -> None:
    from grandpa.cli.vault_cmd import vault

    runner = CliRunner()
    assert runner.invoke(vault, ["set", "MY_API_KEY", SECRET]).exit_code == 0
    got = runner.invoke(vault, ["get", "MY_API_KEY"])
    assert SECRET in got.output
    listed = runner.invoke(vault, ["list"])
    assert "MY_API_KEY" in listed.output
    assert SECRET[:4] + "****" not in listed.output and SECRET not in listed.output
    assert "Removed" in runner.invoke(vault, ["remove", "MY_API_KEY"]).output


def test_old_fernet_vault_is_migrated(
    fake_store: MemoryBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fernet = pytest.importorskip("cryptography.fernet")
    from grandpa.cli import vault_cmd

    key = fernet.Fernet.generate_key()
    vault_file, key_file = tmp_path / "vault.enc", tmp_path / ".vault_key"
    key_file.write_bytes(key)
    vault_file.write_bytes(
        fernet.Fernet(key).encrypt(json.dumps({"A": SECRET}).encode())
    )
    monkeypatch.setattr(vault_cmd, "_VAULT_FILE", vault_file)
    monkeypatch.setattr(vault_cmd, "_VAULT_KEY_FILE", key_file)

    assert vault_cmd.migrate_legacy_vault(SecretStore()) == 1
    assert fake_store.data["A"] == SECRET
    assert not vault_file.exists() and not key_file.exists()


def test_doctor_line(
    monkeypatch: pytest.MonkeyPatch, fake_store: MemoryBackend
) -> None:
    from grandpa.cli import doctor_cmd, vault_cmd

    monkeypatch.setattr(vault_cmd, "plaintext_leftovers", lambda: [])
    result = doctor_cmd._check_credentials_at_rest()
    assert result.status == "ok" and "encrypted" in result.message

    monkeypatch.setattr(
        vault_cmd, "plaintext_leftovers", lambda: ["config.toml [server.auth] api_key"]
    )
    result = doctor_cmd._check_credentials_at_rest()
    assert result.status == "warn" and "vault migrate" in (result.details or "")


def test_doctor_line_plain(monkeypatch: pytest.MonkeyPatch, plain_store) -> None:
    from grandpa.cli import doctor_cmd

    result = doctor_cmd._check_credentials_at_rest()
    assert result.status == "warn" and "NOT encrypted" in result.message
