---
name: generate-report
version: 1.0.0
description: Generate structured status and summary reports
task_type: report
agent: robin
triggers:
  - generate report
  - status report
  - daily summary
  - system summary
---

# Generate Report

Compile data from multiple sources into structured reports.

## Report Types

### daily-health
Combines system-health-check + security-sweep into a daily briefing.

### session-summary
Summarizes an Alfred session's accomplishments, findings, and pending items.

### registry-diff
Compares current registry.json against previous snapshot, highlights changes.

### delegation-log
Summarizes all Alfred→Robin delegations: completed, failed, pending.

## Execution Steps
1. Identify report type from request
2. Gather required data (run prerequisite skills if needed)
3. Format into markdown report
4. Save to `vault/reports/{date}-{type}.md`
5. Return summary + file path

## Output Format
```json
{
  "report_type": "daily-health|session-summary|registry-diff|delegation-log",
  "generated_at": "ISO-8601",
  "file_path": "vault/reports/...",
  "summary": "One-paragraph summary",
  "highlights": [],
  "action_items": []
}
```
