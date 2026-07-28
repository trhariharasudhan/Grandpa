from types import SimpleNamespace

from grandpa.voice import diagnostics


def test_voice_doctor_handles_missing_sounddevice(monkeypatch) -> None:
    monkeypatch.setattr(
        diagnostics,
        "_import_sounddevice",
        lambda: (_ for _ in ()).throw(diagnostics.VoiceDependencyError("missing sounddevice")),
    )

    checks = diagnostics.run_voice_doctor()

    sounddevice_check = next(
        check for check in checks if check["name"] == "sounddevice import"
    )
    assert sounddevice_check["status"] == "warn"
    assert "missing sounddevice" in sounddevice_check["message"]


def test_device_list_handles_no_devices(monkeypatch) -> None:
    fake_sounddevice = SimpleNamespace(
        query_devices=lambda: [],
        default=SimpleNamespace(device=(-1, -1)),
    )
    monkeypatch.setattr(diagnostics, "_import_sounddevice", lambda: fake_sounddevice)

    assert diagnostics.list_input_devices() == ()


def test_voice_doctor_reports_tts_checks(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "_stt_checks", lambda: [])

    class FakeSpeechOutputEngine:
        def diagnostics(self):
            return {"status": "ready", "engine": "mock_tts", "voice": "Mock Voice"}

        def speak(self, text, *, interrupt=False, dry_run=False):
            return SimpleNamespace(status="dry_run", message="Speech output queued safely.")

    monkeypatch.setattr(diagnostics, "SpeechOutputEngine", FakeSpeechOutputEngine)

    checks = diagnostics._tts_checks()
    names = {check["name"]: check for check in checks}

    assert names["TTS backend"]["status"] == "pass"
    assert "mock_tts" in names["TTS backend"]["message"]
    assert names["TTS selected voice"]["message"] == "Mock Voice"
    assert names["TTS speech test"]["status"] == "pass"
