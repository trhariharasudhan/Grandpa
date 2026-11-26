"""`grandpa config set` reads a config saved with a BOM (PowerShell, Notepad)."""

from __future__ import annotations

from click.testing import CliRunner


def test_set_works_on_a_config_that_starts_with_a_bom(tmp_path, monkeypatch) -> None:
    from grandpa.cli import cli

    path = tmp_path / "config.toml"
    path.write_bytes(b"\xef\xbb\xbf[speech]\nmodel = \"base.en\"\n")
    monkeypatch.setenv("Grandpa_CONFIG", str(path))
    result = CliRunner().invoke(cli, ["config", "set", "speech.model", "small.en"])
    assert result.exit_code == 0, result.output
    assert 'model = "small.en"' in path.read_text(encoding="utf-8-sig")
