<#
.SYNOPSIS
  One-command Grandpa setup on Windows.

.DESCRIPTION
  Run from the Grandpa checkout (for example D:\Grandpa):

    powershell -ExecutionPolicy Bypass -File scripts\install.ps1

  Steps, each skipped when already done (safe to run again):
    1. uv          - installs it from astral.sh if it is missing
    2. Python 3.11 - uv python install 3.11
    3. Packages    - uv sync with the voice, screen, server, piper,
                     tamil-voice and scheduler extras
    4. Ollama      - checks it is installed and running (starts it if it can)
    5. Launcher    - scripts\install_launcher.ps1 (no grandpa.exe, so Smart
                     App Control / Device Guard do not block it)
    6. Wizard      - grandpa setup --yes: config, Ollama models
                     (grandpa models setup), offline voice downloads
    7. Shortcut    - "Grandpa" on the desktop, using the launcher shim
    8. Doctor      - grandpa doctor, ending with the exact fix per item

  Nothing here needs admin rights.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -DryRun

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -SkipModels -SkipVoice
#>
[CmdletBinding()]
param(
  # Print every step without changing anything.
  [switch]$DryRun,
  # Do not build the Ollama models.
  [switch]$SkipModels,
  # Do not download the offline voices.
  [switch]$SkipVoice,
  # Do not create the desktop shortcut.
  [switch]$NoShortcut,
  # Optional extras for uv sync.
  [string[]]$Extras = @("voice", "screen", "server", "piper", "tamil-voice", "scheduler")
)

$ErrorActionPreference = "Stop"
$here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$RepoRoot = (Resolve-Path (Join-Path $here "..")).Path.TrimEnd("\")
$Shim = Join-Path $env:LOCALAPPDATA "Grandpa\bin\grandpa.cmd"
$script:Problems = @()

function Step([string]$Title) { Write-Host ""; Write-Host "== $Title" -ForegroundColor Cyan }
function Ok([string]$Text) { Write-Host "   ok  $Text" -ForegroundColor Green }
function Problem([string]$Text, [string]$Fix) {
  Write-Host "   !!  $Text" -ForegroundColor Yellow
  Write-Host "       Fix: $Fix"
  $script:Problems += "$Text -> $Fix"
}
function Run([string]$Exe, [string[]]$CmdArgs) {
  Write-Host "   > $Exe $($CmdArgs -join ' ')"
  if ($DryRun) { return 0 }
  # Out-Host: the command's output is shown, not returned with the exit code.
  & $Exe @CmdArgs | Out-Host
  return $LASTEXITCODE
}

if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
  throw "$RepoRoot is not a Grandpa checkout (no pyproject.toml)."
}
Set-Location $RepoRoot
Write-Host "Grandpa install in $RepoRoot" -ForegroundColor Cyan
if ($DryRun) { Write-Host "(dry run: nothing will change)" }

# 1. uv ----------------------------------------------------------------------
Step "1/8 uv"
if (Get-Command uv -ErrorAction SilentlyContinue) {
  Ok "uv is installed ($((uv --version) 2>$null))"
} else {
  Write-Host "   > irm https://astral.sh/uv/install.ps1 | iex"
  if (-not $DryRun) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  }
  if ($DryRun -or (Get-Command uv -ErrorAction SilentlyContinue)) {
    Ok "uv installed"
  } else {
    throw "uv did not install. Install it by hand: https://docs.astral.sh/uv/getting-started/installation/"
  }
}

# 2. Python ------------------------------------------------------------------
Step "2/8 Python 3.11"
if ((Run "uv" @("python", "install", "3.11")) -ne 0) {
  throw "uv could not install Python 3.11."
}
Ok "Python 3.11 ready"

# 3. Packages ----------------------------------------------------------------
Step "3/8 Packages"
$syncArgs = @("sync", "--link-mode=copy")
# A new environment gets 3.11; an existing .venv keeps its Python.
if (-not (Test-Path (Join-Path $RepoRoot ".venv"))) { $syncArgs += @("--python", "3.11") }
foreach ($extra in $Extras) { $syncArgs += @("--extra", $extra) }
if ((Run "uv" $syncArgs) -ne 0) {
  throw "uv sync failed. Read the error above, then run this script again."
}
Ok "Dependencies installed"

# 4. Ollama ------------------------------------------------------------------
Step "4/8 Ollama"
function Test-Ollama {
  try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
    return $true
  } catch { return $false }
}
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  Problem "Ollama is not installed" "winget install Ollama.Ollama  (or https://ollama.com/download/windows), then run this script again"
} elseif (Test-Ollama) {
  Ok "Ollama is running"
} else {
  Write-Host "   > ollama serve  (in the background)"
  if (-not $DryRun) {
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden
    foreach ($i in 1..15) { if (Test-Ollama) { break }; Start-Sleep -Seconds 1 }
  }
  if ($DryRun -or (Test-Ollama)) { Ok "Ollama started" } else {
    Problem "Ollama is installed but not answering" "Start the Ollama app (or run: ollama serve), then run this script again"
  }
}

# 5. Launcher ----------------------------------------------------------------
Step "5/8 Launcher (runs without the blocked .exe)"
$hostExe = (Get-Process -Id $PID).Path
$launcherArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
  (Join-Path $RepoRoot "scripts\install_launcher.ps1"), "-RepoRoot", $RepoRoot)
if ((Run $hostExe $launcherArgs) -ne 0) {
  Problem "The launcher shim was not installed" "powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1"
} else {
  $env:Path = "$(Split-Path -Parent $Shim);$env:Path"
  Ok "grandpa command installed ($Shim)"
}

# 6. First-run wizard --------------------------------------------------------
Step "6/8 First-run wizard (config, models, voices)"
$wizard = @("run", "python", "-m", "grandpa", "setup", "--yes", "--no-doctor")
if ($SkipModels) { $wizard += "--skip-models" }
if ($SkipVoice) { $wizard += "--skip-voice" }
if ((Run "uv" $wizard) -ne 0) {
  Problem "The setup wizard reported a problem (see above)" "uv run python -m grandpa setup"
} else {
  Ok "Config, models and voices ready"
}

# 7. Desktop shortcut --------------------------------------------------------
Step "7/8 Desktop shortcut"
if ($NoShortcut) {
  Ok "Skipped (-NoShortcut)"
} else {
  $desktop = [Environment]::GetFolderPath("Desktop")
  $lnk = Join-Path $desktop "Grandpa.lnk"
  $target = if (Test-Path $Shim) { $Shim } else { Join-Path $RepoRoot "grandpa.cmd" }
  Write-Host "   > $lnk -> $target"
  if (-not $DryRun) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnk)
    # cmd /k keeps the window open after Grandpa exits, so errors stay readable.
    $shortcut.TargetPath = "$env:ComSpec"
    $shortcut.Arguments = "/k `"`"$target`"`""
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.Description = "Grandpa, your local assistant"
    $shortcut.Save()
  }
  Ok "Shortcut on the desktop: Grandpa"
}

# 8. Doctor ------------------------------------------------------------------
Step "8/8 Doctor"
Run "uv" @("run", "python", "-m", "grandpa", "doctor") | Out-Null

Write-Host ""
if ($script:Problems.Count -eq 0) {
  Write-Host "Grandpa is installed. Open a new terminal and run: grandpa" -ForegroundColor Green
  exit 0
}
Write-Host "Grandpa is installed, with $($script:Problems.Count) thing(s) left to do:" -ForegroundColor Yellow
foreach ($p in $script:Problems) { Write-Host "  - $p" }
exit 1
