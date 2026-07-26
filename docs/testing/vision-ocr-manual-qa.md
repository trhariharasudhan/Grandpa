# Vision OCR Manual QA

Vision OCR is a safe, user-initiated upload feature. It does not capture the desktop, use a webcam, watch the screen, call Ollama, or call LLaVA.

## Setup

1. Start the Grandpa server.
2. Use the local vision API at `http://127.0.0.1:8000/v1/vision`.
3. Keep test images in a temporary user-owned directory.

## Upload Image With Text

1. Enable Vision Mode with `POST /v1/vision/enable`.
2. Upload a PNG, JPG, JPEG, or WEBP image containing readable text.
3. Send it to `POST /v1/vision/ocr`.
4. Expected if OCR dependencies are installed: text appears in the OCR result.
5. Expected if OCR dependencies are missing: a friendly unavailable message appears.

## Upload Image Without Text

1. Upload a valid image without text.
2. Click Extract Text.
3. Expected: OCR result is empty or says no text was detected.

## Invalid File

1. Upload a non-image file renamed as `.png`, or another invalid image.
2. Click Extract Text.
3. Expected: friendly invalid image error.

## Empty File

1. Upload an empty image file.
2. Click Extract Text.
3. Expected: friendly empty image error.

## OCR Dependency Missing

1. Run without `pytesseract` installed.
2. Upload a valid image.
3. Click Extract Text.
4. Expected: `OCR is not available. Install OCR dependencies to extract text.`

## Safety Checks

- No desktop screenshot capture starts.
- No webcam prompt appears.
- No live screen watching starts.
- No OCR dependency is required for the app to run.
