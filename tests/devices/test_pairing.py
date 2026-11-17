"""D1: the pairing store -- one-use codes, attempt cap, hashed tokens, revoke."""

from __future__ import annotations

import sqlite3

import pytest

from grandpa.devices import DEVICE_TOKEN_PREFIX, DeviceStore, PairingError
from grandpa.devices.pairing import MAX_PAIRING_ATTEMPTS


@pytest.fixture
def store(tmp_path):
    return DeviceStore(tmp_path / "devices.db")


def _wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def test_right_code_pairs_and_token_authenticates(store):
    code = store.start_pairing(now=1000).code
    assert len(code) == 6 and code.isdigit()

    paired = store.complete_pairing(code, "Pixel", now=1010)
    assert paired.token.startswith(DEVICE_TOKEN_PREFIX)
    assert paired.device.name == "Pixel"

    device = store.authenticate(paired.token, now=1020)
    assert device is not None and device.device_id == paired.device.device_id
    assert store.list_devices()[0].last_seen_at == 1020


def test_no_window_refuses(store):
    with pytest.raises(PairingError, match="not open"):
        store.complete_pairing("123456", "Pixel")


def test_code_works_only_once(store):
    code = store.start_pairing(now=1000).code
    store.complete_pairing(code, "Pixel", now=1001)
    with pytest.raises(PairingError, match="not open"):
        store.complete_pairing(code, "Second phone", now=1002)
    assert len(store.list_devices()) == 1


def test_expired_code_refuses(store):
    code = store.start_pairing(now=1000, ttl=300).code
    with pytest.raises(PairingError, match="expired"):
        store.complete_pairing(code, "Pixel", now=1301)
    assert not store.pairing_open(now=1301)


def test_too_many_wrong_codes_close_the_window(store):
    code = store.start_pairing(now=1000).code
    for _ in range(MAX_PAIRING_ATTEMPTS - 1):
        with pytest.raises(PairingError, match="Wrong code"):
            store.complete_pairing(_wrong(code), "x", now=1001)
    with pytest.raises(PairingError, match="Too many"):
        store.complete_pairing(_wrong(code), "x", now=1001)
    # Even the right code is refused now: the window is gone.
    with pytest.raises(PairingError, match="not open"):
        store.complete_pairing(code, "Pixel", now=1002)
    assert store.list_devices() == []


def test_new_window_replaces_old_code(store):
    old = store.start_pairing(now=1000).code
    new = store.start_pairing(now=1001).code
    if old != new:
        with pytest.raises(PairingError, match="Wrong code"):
            store.complete_pairing(old, "x", now=1002)
    store.complete_pairing(new, "Pixel", now=1003)


def test_secrets_are_stored_only_as_hashes(store, tmp_path):
    code = store.start_pairing(now=1000).code
    token = store.complete_pairing(code, "Pixel", now=1001).token
    raw = (tmp_path / "devices.db").read_bytes()
    assert token.encode() not in raw
    with sqlite3.connect(tmp_path / "devices.db") as conn:
        stored = conn.execute("SELECT token_hash FROM devices").fetchone()[0]
    assert stored != token and len(stored) == 64


def test_revoke_stops_the_token(store):
    code = store.start_pairing().code
    paired = store.complete_pairing(code, "Pixel")
    assert store.revoke(paired.device.device_id)
    assert store.authenticate(paired.token) is None
    assert not store.revoke(paired.device.device_id)
    assert store.list_devices() == []
    assert store.list_devices(include_revoked=True)[0].revoked


def test_unknown_and_non_device_tokens_fail(store):
    assert store.authenticate("") is None
    assert store.authenticate("gp_sk_the_api_key") is None
    assert store.authenticate(DEVICE_TOKEN_PREFIX + "made-up") is None


def test_name_is_cleaned_and_capped(store):
    code = store.start_pairing().code
    paired = store.complete_pairing(code, "  My\x00Phone\n" + "x" * 100)
    assert "\x00" not in paired.device.name and "\n" not in paired.device.name
    assert len(paired.device.name) <= 40


def test_every_step_is_logged(store):
    code = store.start_pairing(now=1000).code
    with pytest.raises(PairingError):
        store.complete_pairing(_wrong(code), "x", now=1001)
    paired = store.complete_pairing(code, "Pixel", now=1002)
    store.revoke(paired.device.device_id)
    events = [e["event"] for e in store.events()]
    assert events == ["revoked", "paired", "pair_refused", "pairing_started"]
    assert all(code not in (e["detail"] or "") for e in store.events())
