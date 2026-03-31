---
name: form-fill
version: 1.0.0
description: Fill web and desktop forms with human-convincing behavior
task_type: browse
agent: robin
capabilities:
  - human_simulation.HumanSimulator
  - human_simulation.KeyboardEngine
  - human_simulation.BotDetectionFailsafe
triggers:
  - fill form
  - fill out
  - complete form
  - enter information
---

# Form Fill

Fill forms in browsers or desktop applications using human-convincing input.

## Capabilities
- Tab-based field navigation with human timing
- Dropdown selection via click + scroll
- Checkbox/radio clicking with Bezier mouse
- Text input with realistic WPM and typo injection
- Date picker interaction
- File upload dialogs

## Execution Pattern
```python
from rudy.human_simulation import create_simulator
sim = create_simulator("form-fill")

for field in form_fields:
    # Tab to next field or click it
    sim.click(page, selector=field.selector)
    
    if field.type == "text":
        sim.type_text(page, selector=field.selector, text=field.value)
    elif field.type == "select":
        sim.click(page, selector=field.selector)  # Open dropdown
        sim.click(page, selector=f'option[value="{field.value}"]')
    elif field.type == "checkbox":
        if not field.checked:
            sim.click(page, selector=field.selector)
```

## Security Rules
- NEVER fill password fields — escalate to Batman
- NEVER fill SSN, credit card, or bank account fields
- Safe fields: name, email, phone, address, dates, preferences
- Log all form submissions for audit trail
- Check BotDetectionFailsafe before and during fill

## Anti-Detection
- Vary typing speed between fields (fatigue simulation)
- Include natural pauses between field groups
- Occasionally re-read previous fields (human review behavior)
- SessionManager enforces realistic pacing
