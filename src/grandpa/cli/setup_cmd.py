"""``grandpa setup``: the first-run wizard (P1).

One command takes a fresh checkout to a working Grandpa: a config file, your
name, the Ollama models, the offline voices, then a doctor summary that says
the exact fix for anything still missing. Every step checks first and does
nothing when it is already done, so running it again is safe.

``scripts/install.ps1`` runs it as ``grandpa setup --yes`` after installing uv,
Python and the dependencies. Run by hand, it asks before each download.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

import click
from rich.console import Console

from grandpa.core.config import DEFAULT_CONFIG_PATH


@dataclass
class StepResult:
    """What one wizard step did."""

    name: str
    status: str  # "done", "skipped", "failed"
    message: str
    fix: Optional[str] = None


Confirm = Callable[[str], bool]


def _cli() -> str:
    from grandpa.cli.doctor_cmd import cli_prefix

    return cli_prefix()


def step_config(console: Console, ctx: click.Context) -> StepResult:
    """Write ~/.grandpa/config.toml for this hardware, once."""
    if DEFAULT_CONFIG_PATH.exists():
        return StepResult("Config", "done", f"Already at {DEFAULT_CONFIG_PATH}")
    from grandpa.cli.init_cmd import init

    try:
        ctx.invoke(
            init,
            force=False,
            config=None,
            full_config=False,
            engine="ollama",
            no_download=True,
            skip_scan=True,
            host=None,
            from_bare_grandpa=True,
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            return StepResult(
                "Config", "failed", "Could not write the config", f"{_cli()} init"
            )
    return StepResult("Config", "done", f"Written to {DEFAULT_CONFIG_PATH}")


def step_profile(console: Console, interactive: bool) -> StepResult:
    """Ask for the name Grandpa calls you (skipped with --yes)."""
    from grandpa.profile import ensure_profile

    if not interactive:
        return StepResult(
            "Profile", "skipped", "Not asked (--yes)", f"{_cli()} profile"
        )
    try:
        ensure_profile(console=console, interactive=True)
    except Exception as exc:  # a broken profile must not stop the wizard
        return StepResult("Profile", "failed", str(exc), f"{_cli()} profile")
    return StepResult("Profile", "done", "Saved")


def _ollama() -> tuple[object, set[str] | None]:
    from grandpa.cli.model import _ollama_client, _ollama_tags

    client = _ollama_client()
    return client, _ollama_tags(client)


def step_models(console: Console, confirm: Confirm) -> StepResult:
    """Build every missing Ollama role (the same plan as ``grandpa models setup``)."""
    from grandpa.intelligence.odin_registry import plan_setup, run_setup

    client, tags = _ollama()
    if tags is None:
        return StepResult(
            "Models",
            "failed",
            "Ollama is not reachable",
            "Install Ollama from https://ollama.com/download/windows, start it "
            f"(ollama serve), then run {_cli()} setup again",
        )
    plan = plan_setup(tags)
    if not plan.runnable:
        return StepResult("Models", "done", "Every Ollama role is installed")
    for step in plan.runnable:
        console.print(f"  {step.role}: {step.command}")
    if not confirm(f"Build {len(plan.runnable)} Ollama model(s) now?"):
        return StepResult(
            "Models", "skipped", "Not built", f"{_cli()} models setup --yes"
        )
    run_setup(plan, client)
    failed = [s.role for s in plan.runnable if not s.done]
    if failed:
        return StepResult(
            "Models",
            "failed",
            "Not built: " + ", ".join(failed),
            f"{_cli()} models setup --yes",
        )
    return StepResult("Models", "done", f"Built {len(plan.runnable)} model(s)")


def step_voices(console: Console, confirm: Confirm) -> List[StepResult]:
    """Fetch the offline voices: Piper English (~60 MB) and MMS Tamil (~114 MB)."""
    from grandpa.speech import piper_tts, tamil_tts

    results: List[StepResult] = []

    if not piper_tts.piper_installed():
        results.append(
            StepResult(
                "English voice (Piper)",
                "skipped",
                "piper-tts is not installed",
                "uv sync --extra piper",
            )
        )
    elif piper_tts.voice_path() is not None:
        results.append(StepResult("English voice (Piper)", "done", "Already there"))
    elif confirm(f"Download the English voice {piper_tts.DEFAULT_VOICE} (~60 MB)?"):
        try:
            where = piper_tts.download_voice()
            results.append(StepResult("English voice (Piper)", "done", str(where)))
        except Exception as exc:
            results.append(
                StepResult(
                    "English voice (Piper)",
                    "failed",
                    f"Download failed: {exc}",
                    "uv run python -m grandpa.speech.piper_tts download",
                )
            )
    else:
        results.append(
            StepResult(
                "English voice (Piper)",
                "skipped",
                "Not downloaded",
                "uv run python -m grandpa.speech.piper_tts download",
            )
        )

    if not tamil_tts.sherpa_installed():
        results.append(
            StepResult(
                "Tamil voice (MMS)",
                "skipped",
                "sherpa-onnx is not installed",
                "uv sync --extra tamil-voice",
            )
        )
    elif tamil_tts.model_ready():
        results.append(StepResult("Tamil voice (MMS)", "done", "Already there"))
    elif confirm("Download the Tamil voice (~114 MB)?"):
        try:
            where = tamil_tts.download()
            results.append(StepResult("Tamil voice (MMS)", "done", str(where)))
        except Exception as exc:
            results.append(
                StepResult(
                    "Tamil voice (MMS)",
                    "failed",
                    f"Download failed: {exc}",
                    "uv run python -m grandpa.speech.tamil_tts download",
                )
            )
    else:
        results.append(
            StepResult(
                "Tamil voice (MMS)",
                "skipped",
                "Not downloaded",
                "uv run python -m grandpa.speech.tamil_tts download",
            )
        )
    return results


_MARKS = {"done": "[green]ok[/green]", "skipped": "[yellow]--[/yellow]"}


def _print_results(console: Console, results: List[StepResult]) -> None:
    console.print()
    console.print("[bold]Setup summary[/bold]")
    for r in results:
        mark = _MARKS.get(r.status, "[red]!![/red]")
        console.print(f"  {mark} {r.name}: {r.message}")
        if r.fix and r.status != "done":
            console.print(f"     [dim]Fix: {r.fix}[/dim]")


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Do every step without asking (used by scripts/install.ps1).",
)
@click.option("--skip-models", is_flag=True, default=False, help="Skip Ollama models.")
@click.option("--skip-voice", is_flag=True, default=False, help="Skip voice downloads.")
@click.option(
    "--no-doctor", is_flag=True, default=False, help="Skip the final doctor check."
)
@click.pass_context
def setup(
    ctx: click.Context, yes: bool, skip_models: bool, skip_voice: bool, no_doctor: bool
) -> None:
    """First-run wizard: config, profile, models, voices, then a health check."""
    console = Console()
    console.print("[bold]Grandpa setup[/bold]  (safe to run again)")

    def confirm(question: str) -> bool:
        return True if yes else click.confirm(question, default=True)

    results: List[StepResult] = [step_config(console, ctx)]
    results.append(step_profile(console, interactive=not yes))
    if skip_models:
        results.append(StepResult("Models", "skipped", "--skip-models"))
    else:
        console.print("\n[bold]Ollama models[/bold]")
        results.append(step_models(console, confirm))
    if skip_voice:
        results.append(StepResult("Voices", "skipped", "--skip-voice"))
    else:
        console.print("\n[bold]Offline voices[/bold]")
        results.extend(step_voices(console, confirm))

    _print_results(console, results)

    if not no_doctor:
        from grandpa.cli.doctor_cmd import doctor

        console.print()
        try:
            ctx.invoke(doctor, as_json=False)
        except (SystemExit, click.exceptions.Exit):
            pass

    if any(r.status == "failed" for r in results):
        raise SystemExit(1)
