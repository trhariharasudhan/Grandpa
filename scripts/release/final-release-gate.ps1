param(
  [switch]$SkipAndroid,
  [switch]$SkipTauri,
  [switch]$SkipFrontend,
  [switch]$Quick
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ArgsList = @("run", "--python", "3.11", "python", "scripts\release\final_release_gate.py")
if ($SkipAndroid) { $ArgsList += "--skip-android" }
if ($SkipTauri) { $ArgsList += "--skip-tauri" }
if ($SkipFrontend) { $ArgsList += "--skip-frontend" }
if ($Quick) { $ArgsList += "--quick" }

Push-Location $Root
try {
  & uv @ArgsList
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
