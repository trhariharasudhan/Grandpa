$ErrorActionPreference = "Stop"

$runtimeRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $runtimeRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Missing voice_runtime\.venv. Run scripts\setup.ps1 first."
}

& $venvPython (Join-Path $PSScriptRoot "run_service.py")
