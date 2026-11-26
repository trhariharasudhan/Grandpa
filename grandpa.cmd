@echo off
rem Grandpa launcher for Windows: no .exe involved, so Smart App Control and
rem Device Guard do not block it the way they block .venv\Scripts\grandpa.exe.
rem Runs Grandpa from this folder's project environment; the current folder is kept.
rem To call it from anywhere, run scripts\install_launcher.ps1 once.
setlocal
set "GRANDPA_LAUNCHER=grandpa.cmd"
rem The project's own Python: no uv sync on every start (a sync can remove
rem optional packages the orb needs), and python.exe is signed, so it runs.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m grandpa %*
  exit /b %ERRORLEVEL%
)
where uv >nul 2>nul
if errorlevel 1 (
  echo Grandpa needs uv. Install it: https://docs.astral.sh/uv/getting-started/installation/ 1>&2
  exit /b 9009
)
set "GRANDPA_LAUNCHER=grandpa.cmd"
uv run --project "%~dp0." python -m grandpa %*
exit /b %ERRORLEVEL%
