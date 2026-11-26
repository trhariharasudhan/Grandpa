<#
.SYNOPSIS
  Put a "grandpa" command on your PATH that works even when Windows blocks
  .venv\Scripts\grandpa.exe (Smart App Control / Device Guard).

.DESCRIPTION
  Writes a small grandpa.cmd shim to %LOCALAPPDATA%\Grandpa\bin. The shim runs
  `uv run --project <repo> python -m grandpa <args>`, so no unsigned .exe is
  started. The bin folder is added to the front of your user PATH (no admin
  needed). Run it again any time; it only rewrites its own shim.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_launcher.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  # The Grandpa checkout the shim runs. Default: the repo this script is in.
  [string]$RepoRoot = "",
  # Where the shim goes.
  [string]$BinDir = (Join-Path $env:LOCALAPPDATA "Grandpa\bin"),
  # Write the shim but leave PATH alone (used by the tests).
  [switch]$NoPath,
  # Remove the shim and its PATH entry.
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$BinDir = [System.IO.Path]::GetFullPath($BinDir).TrimEnd("\")
$Shim = Join-Path $BinDir "grandpa.cmd"

function Get-UserPathEntries {
  # Read the raw value so entries like %USERPROFILE%\bin stay unexpanded.
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment")
  try {
    $raw = $key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
  } finally {
    $key.Close()
  }
  return @("$raw" -split ";" | Where-Object { $_ -and ($_.TrimEnd("\") -ine $BinDir) })
}

function Set-UserPath([string[]]$Entries) {
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
  try {
    $key.SetValue("Path", ($Entries -join ";"), [Microsoft.Win32.RegistryValueKind]::ExpandString)
  } finally {
    $key.Close()
  }
  # Tell Explorer and new terminals that the environment changed.
  [Environment]::SetEnvironmentVariable("GRANDPA_PATH_REFRESH", "1", "User")
  [Environment]::SetEnvironmentVariable("GRANDPA_PATH_REFRESH", $null, "User")
}

if ($Uninstall) {
  if (Test-Path $Shim) { Remove-Item $Shim }
  $p = $PROFILE.CurrentUserAllHosts
  if ((-not $NoPath) -and (Test-Path $p)) {
    $text = [regex]::Replace((Get-Content $p -Raw), "(?s)\r?\n?# >>> grandpa launcher >>>.*?# <<< grandpa launcher <<<", "")
    Set-Content -Path $p -Value $text.TrimEnd() -Encoding UTF8
  }
  if (-not $NoPath) { Set-UserPath (Get-UserPathEntries) }
  Write-Host "Removed the Grandpa launcher from $BinDir."
  exit 0
}

if (-not $RepoRoot) {
  # Windows PowerShell 5.1 leaves $PSScriptRoot empty inside param() defaults,
  # so the default is worked out here instead.
  $here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
  $RepoRoot = Split-Path -Parent $here
}
$RepoRoot = (Resolve-Path $RepoRoot).Path.TrimEnd("\")
if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
  throw "$RepoRoot is not a Grandpa checkout (no pyproject.toml). Pass -RepoRoot D:\Grandpa."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Warning "uv is not on PATH yet. The launcher needs it: https://docs.astral.sh/uv/getting-started/installation/"
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$lines = @(
  "@echo off",
  "rem Grandpa launcher shim, written by scripts\install_launcher.ps1. No .exe involved.",
  "setlocal",
  "set `"GRANDPA_LAUNCHER=shim`"",
  "if exist `"$RepoRoot\.venv\Scripts\python.exe`" (",
  "  `"$RepoRoot\.venv\Scripts\python.exe`" -m grandpa %*",
  "  exit /b %ERRORLEVEL%",
  ")",
  "uv run --project `"$RepoRoot`" python -m grandpa %*",
  "exit /b %ERRORLEVEL%"
)
Set-Content -Path $Shim -Value $lines -Encoding ASCII
Write-Host "Wrote $Shim -> $RepoRoot"

# PowerShell looks for a function before any program on PATH. A terminal with
# the project's .venv activated (VS Code does this) has .venv\Scripts first on
# PATH, so "grandpa" found the blocked grandpa.exe there before this shim. A
# profile function wins over both. Marked so a rerun replaces it, not adds one.
$Begin = "# >>> grandpa launcher >>>"
$End = "# <<< grandpa launcher <<<"
$ProfilePath = $PROFILE.CurrentUserAllHosts
if (-not $NoPath) {
  $block = @($Begin, "function grandpa { & `"$Shim`" @args }", $End) -join "`r`n"
  $old = if (Test-Path $ProfilePath) { Get-Content $ProfilePath -Raw } else { "" }
  $pattern = "(?s)\r?\n?" + [regex]::Escape($Begin) + ".*?" + [regex]::Escape($End)
  $kept = [regex]::Replace("$old", $pattern, "").TrimEnd()
  New-Item -ItemType Directory -Force -Path (Split-Path $ProfilePath) | Out-Null
  Set-Content -Path $ProfilePath -Value (($kept, $block) -join "`r`n").TrimStart() -Encoding UTF8
  Write-Host "Added a 'grandpa' function to $ProfilePath (works with .venv active)."
}

if (-not $NoPath) {
  Set-UserPath (@($BinDir) + (Get-UserPathEntries))
  $env:Path = "$BinDir;$env:Path"
  Write-Host "Added $BinDir to the front of your user PATH."
  Write-Host "Open a new terminal, then run: grandpa doctor"
}
exit 0
