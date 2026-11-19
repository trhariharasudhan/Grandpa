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
  "uv run --project `"$RepoRoot`" python -m grandpa %*",
  "exit /b %ERRORLEVEL%"
)
Set-Content -Path $Shim -Value $lines -Encoding ASCII
Write-Host "Wrote $Shim -> $RepoRoot"

if (-not $NoPath) {
  Set-UserPath (@($BinDir) + (Get-UserPathEntries))
  $env:Path = "$BinDir;$env:Path"
  Write-Host "Added $BinDir to the front of your user PATH."
  Write-Host "Open a new terminal, then run: grandpa doctor"
}
exit 0
