"""``Grandpa start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import os
import platform
import signal
import socket
import subprocess
import sys
import time

import click
from rich.console import Console

from grandpa.core.config import DEFAULT_CONFIG_DIR, load_config

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"


def _read_pid() -> int | None:
    """Read PID from pid file, return None if not found or stale."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
    except ValueError:
        _PID_FILE.unlink(missing_ok=True)
        return None
    if pid <= 0:
        _PID_FILE.unlink(missing_ok=True)
        return None
    if not _pid_alive(pid):
        _PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


def _pid_alive(pid: int | None) -> bool:
    """Return whether *pid* appears alive without surfacing stale PID errors."""
    if pid is None or pid <= 0:
        return False
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except ImportError:
        return _pid_alive_without_psutil(pid)
    except Exception:
        return False


def _pid_alive_without_psutil(pid: int) -> bool:
    if pid <= 0:
        return False
    if platform.system().lower() == "windows":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except (
        OSError,
        SystemError,
        ValueError,
        OverflowError,
        RuntimeError,
        Exception,
    ):
        return False


def _pid_alive_windows(pid: int) -> bool:
    """Verify a Windows PID without ``os.kill(pid, 0)``."""
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False

        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    except (
        OSError,
        SystemError,
        ValueError,
        OverflowError,
        RuntimeError,
        Exception,
    ):
        return False


def _terminate_pid(pid: int, *, grace_seconds: float = 10.0) -> None:
    """Best-effort terminate that is safe for stale PIDs on Windows."""
    try:
        import psutil

        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=grace_seconds)
        except psutil.TimeoutExpired:
            proc.kill()
        return
    except ImportError:
        pass
    except Exception:
        return

    if platform.system().lower() == "windows":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False
            )
        except Exception:
            pass
        return

    try:
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + grace_seconds
        while time.time() < deadline:
            time.sleep(0.5)
            if not _pid_alive(pid):
                return
        if _pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
    except OSError:
        return


def _connect_host_for_bind(host: str) -> str:
    if host in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _port_in_use(host: str, port: int) -> bool:
    """Return True if something is already accepting TCP connections."""
    try:
        with socket.create_connection(
            (_connect_host_for_bind(host), port),
            timeout=0.5,
        ):
            return True
    except OSError:
        return False


def _daemon_popen_kwargs() -> dict[str, object]:
    kwargs: dict[str, object] = {"start_new_session": True}
    if platform.system().lower() == "windows":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        if creationflags:
            kwargs = {"creationflags": creationflags}
    return kwargs


@click.group()
def daemon() -> None:
    """Manage the Grandpa server daemon."""


@daemon.command()
@click.option("--host", default=None, help="Bind address.")
@click.option("--port", default=None, type=int, help="Port number.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
def start(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the Grandpa server as a background daemon."""
    console = Console(stderr=True)

    existing = _read_pid()
    if existing is not None:
        config = load_config()
        bind_host = host or config.server.host
        bind_port = port or config.server.port
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print(f"  URL: http://{bind_host}:{bind_port}")
        console.print(f"  Log: {_LOG_FILE}")
        console.print("Use 'Grandpa stop' to stop it first, or 'Grandpa restart'.")
        sys.exit(1)

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port or config.server.port
    if _port_in_use(bind_host, bind_port):
        console.print(
            "[red]Cannot start Grandpa server.[/red]\n"
            f"  Port already in use: {bind_host}:{bind_port}\n"
            "  Stop the process using that port or choose another port with --port."
        )
        sys.exit(1)

    # Build command to run Grandpa serve
    cmd = [sys.executable, "-m", "grandpa.cli", "serve"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if engine_key:
        cmd.extend(["--engine", engine_key])
    if model_name:
        cmd.extend(["--model", model_name])
    if agent_name:
        cmd.extend(["--agent", agent_name])

    # Start as background process
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOG_FILE, "a") as log_fh:
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
            **_daemon_popen_kwargs(),
        )
    _write_pid(proc.pid)

    console.print(
        f"[green]Grandpa server started[/green] (PID {proc.pid})\n"
        f"  URL: http://{bind_host}:{bind_port}\n"
        f"  Log: {_LOG_FILE}"
    )


@daemon.command()
def stop() -> None:
    """Stop the running Grandpa server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        sys.exit(1)

    _terminate_pid(pid)
    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the Grandpa server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    ctx.invoke(start)


@daemon.command()
def status() -> None:
    """Show status of the Grandpa server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        return

    uptime_info = ""
    try:
        import psutil

        proc = psutil.Process(pid)
        uptime = time.time() - proc.create_time()
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_info = f"\n  Uptime: {hours}h {minutes}m {seconds}s"
    except Exception:
        pass

    config = load_config()
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: http://{config.server.host}:{config.server.port}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
