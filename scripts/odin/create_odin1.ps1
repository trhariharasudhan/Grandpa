# Build the grandpa-brain-odin1 Ollama model from the GGUF the notebook exported.
#
#   powershell -ExecutionPolicy Bypass -File scripts\odin\create_odin1.ps1
#
# Needs: Ollama running, qwen3:8b pulled (grandpa-brain is built from it), and
# models\odin\grandpa-brain-odin1.Q4_K_M.gguf in place. It never changes which
# model Grandpa uses by default.
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$models = Join-Path $repo "models"
$gguf = Join-Path $models "odin\grandpa-brain-odin1.Q4_K_M.gguf"
$base = Join-Path $models "Modelfile.brain-odin1"

if (-not (Test-Path -LiteralPath $gguf)) {
    throw "Missing $gguf. Run notebooks\odin_brain_lora.ipynb and copy the .gguf there."
}

# Tool calling depends on the chat template. Reuse the official Qwen3 one
# from the installed base model instead of maintaining a copy here.
$template = & ollama show qwen3:8b --template
if ($LASTEXITCODE -ne 0 -or -not $template) {
    throw "Could not read the qwen3:8b template. Run: ollama pull qwen3:8b"
}

$built = Join-Path $models "Modelfile.brain-odin1.generated"
$lines = Get-Content -LiteralPath $base
$lines += 'TEMPLATE """' + ($template -join "`n") + '"""'
Set-Content -LiteralPath $built -Value $lines -Encoding UTF8

Push-Location $models
try {
    & ollama create grandpa-brain-odin1 -f $built
    if ($LASTEXITCODE -ne 0) { throw "ollama create failed" }
} finally {
    Pop-Location
}
Write-Host "Created grandpa-brain-odin1. Try: ollama run grandpa-brain-odin1 `"lock the screen`""
