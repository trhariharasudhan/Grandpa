---
title: Launcher (when Windows blocks grandpa.exe)
description: Start Grandpa without grandpa.exe on machines with Smart App Control or Device Guard
---

# Launcher (when Windows blocks grandpa.exe)

`uv sync` creates `.venv\Scripts\grandpa.exe`. On some laptops Windows refuses
to start it ("This program is blocked by group policy" or "An Application
Control policy has blocked this file"). That comes from Smart App Control or
Device Guard, which block unsigned `.exe` files.

Grandpa does not need that `.exe`. Two launchers start it as
`uv run python -m grandpa ...` instead:

| Launcher | Where it works | Set up |
| --- | --- | --- |
| `grandpa.cmd` in the repo folder | inside `D:\Grandpa` (`.\grandpa.cmd doctor`) | nothing, it ships with the repo |
| `grandpa` shim on your PATH | any terminal, any folder | run `scripts\install_launcher.ps1` once |
| `uv run python -m grandpa ...` | inside `D:\Grandpa` | nothing |

## Install the shim

```powershell
cd D:\Grandpa
powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1
```

This writes `%LOCALAPPDATA%\Grandpa\bin\grandpa.cmd` and puts that folder at the
front of your user PATH (no admin needed). Open a new terminal, then:

```powershell
grandpa doctor
```

Your current folder is kept, so `grandpa` works from anywhere. If the repo is
somewhere else, pass `-RepoRoot C:\path\to\Grandpa`. To remove the shim:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1 -Uninstall
```

## Which launcher is in use

`grandpa doctor` has a **Launcher** line. On Windows it says how Grandpa was
started (`grandpa.cmd`, the shim, `grandpa.exe` or `python -m grandpa`), whether
the shim is on PATH, and whether `.venv\Scripts\grandpa.exe` runs or is blocked.
If the `.exe` is blocked and the shim is missing, the line is a warning that
names the command above.
