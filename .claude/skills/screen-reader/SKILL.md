---
name: screen-reader
version: 1.0.0
description: Read and interpret screen content via OCR and screenshots
task_type: browse
agent: robin
capabilities:
  - Windows-MCP Snapshot (vision mode)
  - EasyOCR
  - pyautogui screenshot
triggers:
  - read screen
  - what's on screen
  - screenshot
  - OCR
  - screen content
---

# Screen Reader

Capture and interpret screen content using vision and OCR.

## Methods
1. **Windows-MCP Snapshot** (preferred): `Snapshot(use_vision=True)` for AI-interpreted content
2. **Windows-MCP Snapshot** (raw): `Snapshot(use_vision=False)` for raw screenshot
3. **EasyOCR**: For text extraction from images
4. **pyautogui**: `screenshot()` for full-screen capture

## Execution Steps
1. Capture screenshot via preferred method
2. If text extraction needed: run EasyOCR on region of interest
3. If understanding needed: use Snapshot with vision=True
4. Parse and structure the extracted content
5. Return structured result

## Use Cases
- Verify UI state after interaction
- Extract data from non-API applications
- Monitor dashboard displays
- Read error dialogs and notifications
- Capture evidence for audit trail

## Output Format
```json
{
  "method": "snapshot_vision|snapshot_raw|easyocr|pyautogui",
  "timestamp": "ISO-8601",
  "text_content": "",
  "structured_data": {},
  "screenshot_path": "",
  "confidence": 0.0,
  "status": "success|partial|error"
}
```
