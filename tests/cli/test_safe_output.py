from grandpa.cli.safe_output import safe_cli_error


def test_safe_cli_error_falls_back_when_stderr_wrapper_is_invalid(
    monkeypatch, capsys
) -> None:
    def broken_echo(*_args, **_kwargs):
        raise OSError("Windows error 6")

    monkeypatch.setattr("grandpa.cli.safe_output.click.echo", broken_echo)

    safe_cli_error("Microphone unavailable")

    assert "Microphone unavailable" in capsys.readouterr().out
