$ErrorActionPreference = "Stop"

$runtimeRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $runtimeRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $runtimeRoot "requirements.lock"

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.11 -m venv (Join-Path $runtimeRoot ".venv")
}

# FFmpeg is no longer committed: fetch it (checksum-pinned) unless one exists.
& $venvPython (Join-Path $PSScriptRoot "fetch_ffmpeg.py")
if ($LASTEXITCODE -ne 0) { throw "FFmpeg setup failed; see the message above." }

& $venvPython -m pip install --disable-pip-version-check -r $requirements
& $venvPython (Join-Path $PSScriptRoot "apply_f5_compatibility.py")
& $venvPython -m pip check
& $venvPython (Join-Path $PSScriptRoot "validate_runtime.py")
