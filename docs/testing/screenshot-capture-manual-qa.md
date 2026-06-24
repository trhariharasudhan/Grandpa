# Screenshot Capture Foundation Manual QA

This feature supports manual screenshot image ingestion only. It does not capture
the desktop, watch the screen, use a webcam, or run in the background.

## Manual Screenshot Upload

1. Start Grandpa normally.
2. Open the Voice page.
3. In Vision Mode, find Screenshot / Screen Image.
4. Use Windows `Win+Shift+S` to take a screenshot.
5. Save the screenshot as PNG, JPG, JPEG, or WEBP.
6. Upload the saved screenshot.
7. Click Ingest Screenshot.
8. Confirm metadata appears:
   - filename
   - dimensions
   - placeholder analysis

## OCR

1. Upload a screenshot that contains visible text.
2. Click Ingest Screenshot.
3. If OCR dependencies are installed, extracted text should appear.
4. If OCR dependencies are missing, Grandpa should show a friendly unavailable
   message and should not crash.

## Local Model

1. Upload a screenshot.
2. Optionally edit the prompt.
3. Click Ingest Screenshot.
4. If Ollama and a vision model are available, local model analysis should appear.
5. If Ollama or the model is unavailable, Grandpa should show setup guidance.

## Invalid File

1. Upload a text file renamed with an unsupported extension.
2. Click Ingest Screenshot.
3. Expected: Grandpa rejects it with a friendly unsupported image message.

## Empty File

1. Upload an empty PNG/JPG/WEBP file.
2. Click Ingest Screenshot.
3. Expected: Grandpa reports an empty image file and does not crash.
