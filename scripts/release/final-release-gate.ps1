$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ArgsList = @("run", "--python", "3.11", "python", "scripts\release\final_release_gate.py")

Push-Location $Root
try {
  & uv @ArgsList
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
