# Vision Local Model Manual QA

Vision local model analysis is user-initiated and upload-only. It does not capture the desktop, use a webcam, watch the screen, or start background services.

## Ollama Running With Model Present

1. Start Ollama: `ollama serve`.
2. Install a vision model, for example: `ollama pull llava:latest`.
3. Open Grandpa and go to Voice Assistant.
4. In Vision Mode, upload a PNG, JPG, JPEG, or WEBP image.
5. Optionally edit the prompt.
6. Click Analyze with Local Model.
7. Expected: image metadata appears, plus a local model analysis response.

## Configured Model Present

1. Set a configured model with `GRANDPA_VISION_MODEL`, `GRANDPA_EYES_MODEL`, or `OLLAMA_VISION_MODEL`.
2. Ensure the model is installed in Ollama.
3. Upload an image and click Analyze with Local Model.
4. Expected: Grandpa uses the configured model.

## Model Missing

1. Start Ollama.
2. Do not install `grandpa-eyes` or `llava:latest`.
3. Upload an image and click Analyze with Local Model.
4. Expected: friendly setup guidance, such as `ollama pull grandpa-eyes`.

## Ollama Stopped

1. Stop Ollama.
2. Upload an image and click Analyze with Local Model.
3. Expected: friendly unavailable message: `Ollama is not available. Start it with: ollama serve`.

## Custom Prompt

1. Upload an image.
2. Replace the prompt with a specific question.
3. Click Analyze with Local Model.
4. Expected: the local model analysis reflects the custom prompt if the model is available.

## Fallback Messages

- If no prompt is supplied, Grandpa uses: `Describe this image clearly and mention any visible text.`
- If `grandpa-eyes` is unavailable, Grandpa can fall back to `llava:latest` when installed.
- If no supported model is installed, Grandpa does not crash and returns setup guidance.

## Safety Checks

- No desktop screenshot capture starts.
- No webcam prompt appears.
- No live screen watching starts.
- No Tauri or floating-window behavior is involved.
