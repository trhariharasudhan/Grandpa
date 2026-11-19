"""Credentials at rest: one place where tokens, passwords and API keys live.

Before this module, secrets sat in plain text in three places: the server API
key in ``config.toml``, the Google OAuth tokens (Gmail, Calendar) as JSON files,
and ``grandpa vault``, whose "encrypted" file had its key in a file right next
to it. Anything that could read the Grandpa folder could read them all.

Now they go through :class:`SecretStore`, which picks the strongest backend the
machine has:

* **Windows** -- DPAPI (``CryptProtectData``, the same call ``win32crypt``
  wraps, made through ``ctypes`` so no extra package is needed). The blob can
  only be decrypted by the same Windows user on the same machine. Files live in
  ``<GRANDPA_HOME>/secrets/<name>.dpapi``.
* **Elsewhere** (Linux, the Pironman) -- the ``keyring`` package when it is
  installed and has a real backend (Secret Service, KWallet).
* **Nothing better available** -- a ``0600`` file. This is no stronger than
  before, and :meth:`SecretStore.describe` and ``grandpa doctor`` say so, so it
  is never silently treated as protected. Plaintext values are never *moved*
  into this backend: migration only happens when the target is secure.

Values are never logged. Names (``server.api_key``, ``gmail.token``) are not
secret and may appear in messages.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "grandpa"
#: Set to ``dpapi``, ``keyring`` or ``file`` to force a backend.
BACKEND_ENV = "GRANDPA_SECRET_BACKEND"

_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
#: Mixed into every DPAPI blob so another program running as the same user
#: cannot decrypt Grandpa's blobs by accident with a bare CryptUnprotectData.
_DPAPI_ENTROPY = b"grandpa-secret-store-v1"


class SecretStoreError(RuntimeError):
    """A secret could not be stored or read."""


def _check_name(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        raise SecretStoreError(
            "Secret names use letters, digits, '.', '_' and '-' (max 128)."
        )
    return name


def secrets_dir() -> Path:
    """``<GRANDPA_HOME>/secrets`` (or ``GRANDPA_SECRETS_DIR``), resolved on every call."""
    override = os.environ.get("GRANDPA_SECRETS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from grandpa.runtime_paths import grandpa_home

    return grandpa_home() / "secrets"


class Backend(Protocol):
    label: str
    secure: bool

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...
    def names(self) -> list[str]: ...


# -- Windows DPAPI ------------------------------------------------------------


def _dpapi_call(data: bytes, *, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData through ctypes."""
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def blob(raw: bytes) -> tuple[DataBlob, Any]:
        buf = ctypes.create_string_buffer(raw, max(len(raw), 1))
        return DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    data_in, _keep_in = blob(data)
    entropy, _keep_entropy = blob(_DPAPI_ENTROPY)
    data_out = DataBlob()
    cryptprotect_ui_forbidden = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy),
        None,
        None,
        cryptprotect_ui_forbidden,
        ctypes.byref(data_out),
    )
    if not ok:
        raise SecretStoreError(
            f"Windows DPAPI {'encrypt' if protect else 'decrypt'} failed "
            f"(error {ctypes.GetLastError()})."  # type: ignore[attr-defined]
        )
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(data_out.pbData)


class _FileBackend:
    """One file per secret under ``secrets_dir()``; subclasses pick the codec."""

    suffix = ".secret"
    label = "plain file"
    secure = False

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory if self._directory is not None else secrets_dir()

    def _encode(self, value: str) -> bytes:
        return value.encode("utf-8")

    def _decode(self, raw: bytes) -> str:
        return raw.decode("utf-8")

    def _path(self, name: str) -> Path:
        return self.directory / f"{_check_name(name)}{self.suffix}"

    def get(self, name: str) -> str | None:
        path = self._path(name)
        if not path.exists():
            return None
        return self._decode(path.read_bytes())

    def set(self, name: str, value: str) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(self._encode(value))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def names(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(
            p.name[: -len(self.suffix)]
            for p in self.directory.glob(f"*{self.suffix}")
            if p.is_file()
        )


class PlainFileBackend(_FileBackend):
    """Last resort: protected only by file permissions. Reported as such."""


class DpapiFileBackend(_FileBackend):
    """Windows: each value encrypted with DPAPI for the current user."""

    suffix = ".dpapi"
    label = "Windows DPAPI"
    secure = True

    def __init__(
        self,
        directory: Path | None = None,
        *,
        protect: Callable[[bytes], bytes] | None = None,
        unprotect: Callable[[bytes], bytes] | None = None,
    ) -> None:
        super().__init__(directory)
        self._protect = protect or (lambda b: _dpapi_call(b, protect=True))
        self._unprotect = unprotect or (lambda b: _dpapi_call(b, protect=False))

    def _encode(self, value: str) -> bytes:
        return self._protect(value.encode("utf-8"))

    def _decode(self, raw: bytes) -> str:
        return self._unprotect(raw).decode("utf-8")


class KeyringBackend:
    """The ``keyring`` package (Secret Service, KWallet, Credential Manager).

    keyring cannot list what it holds, so the *names* are kept in
    ``secrets/keyring-names.json``. Names are not secret; values never touch it.
    """

    label = "keyring"
    secure = True

    def __init__(
        self, module: Any | None = None, directory: Path | None = None
    ) -> None:
        if module is None:
            import keyring as module  # type: ignore[no-redef]
        self._keyring = module
        self._directory = directory
        backend = getattr(module, "get_keyring", lambda: None)()
        if backend is not None:
            self.label = f"keyring ({type(backend).__name__})"

    @property
    def _index(self) -> Path:
        base = self._directory if self._directory is not None else secrets_dir()
        return base / "keyring-names.json"

    def _read_index(self) -> list[str]:
        try:
            return sorted(set(json.loads(self._index.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            return []

    def _write_index(self, names: list[str]) -> None:
        self._index.parent.mkdir(parents=True, exist_ok=True)
        self._index.write_text(json.dumps(sorted(set(names))), encoding="utf-8")

    def get(self, name: str) -> str | None:
        return self._keyring.get_password(KEYRING_SERVICE, _check_name(name))

    def set(self, name: str, value: str) -> None:
        self._keyring.set_password(KEYRING_SERVICE, _check_name(name), value)
        self._write_index([*self._read_index(), name])

    def delete(self, name: str) -> bool:
        _check_name(name)
        existed = self.get(name) is not None
        if existed:
            self._keyring.delete_password(KEYRING_SERVICE, name)
        self._write_index([n for n in self._read_index() if n != name])
        return existed

    def names(self) -> list[str]:
        return self._read_index()


def _usable_keyring() -> Any | None:
    """The keyring module if it has a real backend, else None."""
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0))
        module = type(backend).__module__
    except Exception:
        return None
    if priority <= 0 or module.endswith((".fail", ".null")):
        return None
    return keyring


def default_backend() -> Backend:
    """The strongest backend this machine has, or the one forced by env."""
    forced = os.environ.get(BACKEND_ENV, "").strip().lower()
    if forced == "file":
        return PlainFileBackend()
    if forced == "dpapi" or (not forced and sys.platform == "win32"):
        return DpapiFileBackend()
    module = _usable_keyring()
    if module is not None:
        return KeyringBackend(module)
    if forced == "keyring":
        logger.warning(
            "%s=keyring but no usable keyring backend; using a file.", BACKEND_ENV
        )
    return PlainFileBackend()


class SecretStore:
    """Get, set and delete named secrets. Never logs a value."""

    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend if backend is not None else default_backend()

    @property
    def secure(self) -> bool:
        return bool(self.backend.secure)

    def describe(self) -> str:
        if self.secure:
            return f"encrypted ({self.backend.label})"
        return "NOT encrypted: plain file protected only by file permissions"

    def get(self, name: str) -> str | None:
        try:
            return self.backend.get(name)
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreError(
                f"Could not read secret '{name}': {type(exc).__name__}"
            ) from None

    def set(self, name: str, value: str) -> None:
        try:
            self.backend.set(name, value)
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreError(
                f"Could not store secret '{name}': {type(exc).__name__}"
            ) from None

    def delete(self, name: str) -> bool:
        try:
            return self.backend.delete(name)
        except SecretStoreError:
            raise
        except Exception as exc:
            raise SecretStoreError(
                f"Could not delete secret '{name}': {type(exc).__name__}"
            ) from None

    def names(self) -> list[str]:
        try:
            return self.backend.names()
        except Exception:
            return []

    def import_file(self, name: str, path: Path) -> bool:
        """Move a plaintext file's content into the store, once.

        Only when the store is encrypted: moving a secret from one plain file to
        another gains nothing and would hide where it is. The file is deleted
        only after the stored value reads back identical.
        """
        if not self.secure or not path.is_file():
            return False
        value = path.read_text(encoding="utf-8")
        self.set(name, value)
        if self.get(name) != value:
            raise SecretStoreError(
                f"Secret '{name}' did not read back; kept {path.name}."
            )
        path.unlink()
        logger.info(
            "Moved %s into the %s secret store as '%s'.",
            path.name,
            self.backend.label,
            name,
        )
        return True


class StoredToken:
    """A JSON credential (an OAuth token) that used to be a plain file.

    With an encrypted store the value lives there and the old file is moved in
    on first use. With only the plain-file fallback, the old file stays exactly
    where it was, so nothing changes on machines that have nothing better.
    """

    def __init__(
        self, name: str, legacy_path: Path, store: SecretStore | None = None
    ) -> None:
        self.name = _check_name(name)
        self.legacy_path = Path(legacy_path)
        self._store = store

    @property
    def store(self) -> SecretStore:
        return self._store if self._store is not None else SecretStore()

    def _migrated_store(self) -> SecretStore | None:
        store = self.store
        if not store.secure:
            return None
        if self.legacy_path.is_file():
            store.import_file(self.name, self.legacy_path)
        return store

    def exists(self) -> bool:
        store = self._migrated_store()
        if store is None:
            return self.legacy_path.is_file()
        return store.get(self.name) is not None

    def load(self) -> dict | None:
        store = self._migrated_store()
        if store is None:
            raw = (
                self.legacy_path.read_text(encoding="utf-8")
                if self.legacy_path.is_file()
                else None
            )
        else:
            raw = store.get(self.name)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def save(self, payload: dict) -> None:
        text = json.dumps(payload, indent=2)
        store = self.store
        if store.secure:
            store.set(self.name, text)
            if self.legacy_path.is_file():
                self.legacy_path.unlink()
            return
        self.legacy_path.parent.mkdir(parents=True, exist_ok=True)
        self.legacy_path.write_text(text, encoding="utf-8")
        try:
            os.chmod(self.legacy_path, 0o600)
        except OSError:
            pass

    def clear(self) -> bool:
        removed = False
        if self.legacy_path.is_file():
            self.legacy_path.unlink()
            removed = True
        store = self.store
        if store.secure:
            removed = store.delete(self.name) or removed
        return removed


__all__ = [
    "BACKEND_ENV",
    "DpapiFileBackend",
    "KeyringBackend",
    "PlainFileBackend",
    "SecretStore",
    "SecretStoreError",
    "StoredToken",
    "default_backend",
    "secrets_dir",
]
