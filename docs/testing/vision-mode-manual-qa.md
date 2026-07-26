# Vision Mode Manual QA

Vision Mode is a safe foundation only. It accepts user-selected image uploads and returns deterministic placeholder analysis. It does not use live screen capture, webcam input, background watching, or a vision model yet.

## Setup

1. Start the Grandpa server.
2. Use the local vision API at `http://127.0.0.1:8000/v1/vision`.
3. Keep test images in a temporary user-owned directory.

## Test Cases

### Enable

1. Send `POST /v1/vision/enable`.
2. Expected: status changes to enabled.
3. Expected: live capture and webcam remain off.

### Upload PNG

1. Choose a valid `.png` image.
2. Upload it to `POST /v1/vision/analyze`.
3. Expected: filename, format, width, and height appear.
4. Expected analysis: `placeholder analysis`

### Upload JPG

1. Choose a valid `.jpg` or `.jpeg` image.
2. Click Analyze Image.
3. Expected: dimensions, format, and placeholder analysis appear.

### Upload WEBP

1. Choose a valid `.webp` image.
2. Click Analyze Image.
3. Expected: dimensions, format, and placeholder analysis appear.

### Invalid File

1. Choose a text file or unsupported file type.
2. Click Analyze Image.
3. Expected: friendly unsupported type message.

### Empty File

1. Choose an empty image file.
2. Click Analyze Image.
3. Expected: friendly empty file message.

### Disable

1. Click Disable.
2. Expected: status changes to disabled.
3. Expected: no screen capture, webcam, or background watcher starts.
