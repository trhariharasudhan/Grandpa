# Vision Engine V1

Grandpa Vision Engine builds a local, structured representation of the visible
Windows interface. It combines the existing screenshot, OCR, active-window,
UI Automation, highlighting, and confirmed automation services.

## Architecture

```text
Voice / Chat / CLI
        |
Automation Planner
        |
VisionExtractor
  |-- ScreenCapture (desktop, active window, monitor, region)
  |-- Tesseract OCR (words, lines, paragraphs, bounds)
  `-- Windows UI Automation (controls and hierarchy)
        |
ElementGraphBuilder
        |
HybridElementMatcher
        |
Highlight or confirmed ScreenAutomationService action
        |
Window and result verification
```

No separate screenshot implementation is used. Captures remain in memory unless
the user explicitly runs `vision screenshot` or `vision dump`.

## Commands

```powershell
grandpa vision inspect
grandpa vision describe
grandpa vision read
grandpa vision graph
grandpa vision dump
grandpa vision screenshot
grandpa vision find Login
grandpa vision highlight Save
grandpa vision buttons
grandpa vision controls
```

`inspect`, `describe`, `read`, `graph`, `find`, `buttons`, and `controls` are
read-only. `highlight` draws a temporary rectangle and does not click.

## Element Graph

Each node can include:

- stable graph ID and source (`uia`, `ocr`, or `uia+ocr`);
- control type, name, OCR text, value, and confidence;
- desktop-relative bounding rectangle;
- parent and child IDs;
- enabled, visible, focused, clickable, editable, and scrollable state;
- AutomationId and a private runtime ID.

OCR nodes preserve reading order, line groups, and paragraph groups. Matching
prefers exact text and UI Automation names, then OCR text and fuzzy similarity.
Visible, enabled, clickable nodes rank above hidden or disabled nodes.

## Safety

- OCR-only matches are never treated as verified click targets.
- Low-confidence and near-tied matches return clarification or ambiguity.
- Click preparation uses the existing target-window and confirmation pipeline.
- Search, capture, and highlighting never invoke controls.
- Password, token, OTP, card, and sensitive-screen text is redacted or blocked.
- Graph dumps omit HWND, PID, and UIA runtime IDs by default.
- Scrolling is bounded and stops if the verified foreground window changes.

## Planner Examples

```text
Find Login
Click Continue
Highlight Save
Scroll down until Submit appears
```

The existing automation planner now resolves visible targets through the Vision
Engine. It still requires a verified target window before sending mouse or
keyboard input.

## Developer Notes

`VisionExtractor`, `ElementGraphBuilder`, `HybridElementMatcher`, and
`VisionEngine` accept injected capture/OCR/UIA providers, so tests do not access
the real desktop. UI Automation failures degrade to OCR, and missing OCR
degrades to UI Automation.

## Limitations

- V1 uses deterministic OCR/UIA analysis rather than a multimodal model.
- UI Automation quality depends on the active application's accessibility tree.
- Canvas, games, remote desktops, and protected Windows surfaces may expose
  little or no UIA data.
- OCR-only targets can be highlighted but not clicked automatically.
- `scroll until` uses a bounded number of steps and requires a verified target
  window.
- Region capture is available through the service API; the initial Vision CLI
  exposes active-window, desktop, and monitor capture.
