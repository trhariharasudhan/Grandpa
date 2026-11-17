"""D1: ``grandpa devices`` pair / list / revoke / log."""

from __future__ import annotations

import re

import pytest
from click.testing import CliRunner

from grandpa.cli import devices_cmd
from grandpa.devices import DeviceStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "devices.db"
    monkeypatch.setattr(devices_cmd, "DeviceStore", lambda: DeviceStore(db))
    monkeypatch.setattr(devices_cmd, "_lan_address", lambda: "192.168.1.20")
    return DeviceStore(db)


def test_pair_prints_code_and_address(store):
    result = CliRunner().invoke(devices_cmd.devices, ["pair", "--no-wait"])
    assert result.exit_code == 0, result.output
    code = re.search(r"Pairing code: (\d{6})", result.output).group(1)
    assert "http://192.168.1.20:" in result.output
    assert "/v1/devices/pair" in result.output
    assert store.pairing_open()
    store.complete_pairing(code, "Pixel")


def test_list_and_revoke(store):
    code = store.start_pairing().code
    device_id = store.complete_pairing(code, "Pixel").device.device_id
    runner = CliRunner()

    listed = runner.invoke(devices_cmd.devices, ["list"])
    assert device_id in listed.output and "Pixel" in listed.output

    revoked = runner.invoke(devices_cmd.devices, ["revoke", device_id])
    assert revoked.exit_code == 0 and "Revoked" in revoked.output
    assert "No paired devices" in runner.invoke(devices_cmd.devices, ["list"]).output

    again = runner.invoke(devices_cmd.devices, ["revoke", device_id])
    assert again.exit_code != 0

    log = runner.invoke(devices_cmd.devices, ["log"])
    assert "revoked" in log.output and "paired" in log.output
