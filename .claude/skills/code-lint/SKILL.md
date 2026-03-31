---
name: code-lint
version: 1.0.0
description: Code quality checks using ruff and formatting tools
task_type: code_quality
agent: robin
triggers:
  - lint code
  - ruff check
  - code quality
  - format check
---

# Code Lint

Run code quality and formatting checks on Python files in the workhorse repo.

## Capabilities
- Ruff linting (configured in pyproject.toml)
- Ruff formatting check
- Bandit security scanning
- Import sorting verification

## Execution Steps
1. `cd C:\Users\ccimi\rudy-workhorse`
2. Run `C:\Python312\python.exe -m ruff check .` for lint
3. Run `C:\Python312\python.exe -m ruff format --check .` for format
4. Parse output into structured findings
5. Auto-fix safe issues with `--fix` flag if authorized

## Output Format
```json
{
  "lint": {"errors": 0, "warnings": 0, "findings": []},
  "format": {"files_need_formatting": 0, "files": []},
  "security": {"high": 0, "medium": 0, "low": 0, "findings": []},
  "auto_fixed": 0,
  "status": "clean|warnings|errors"
}
```

## Auto-Fix Rules
- F841 (unused variable): auto-fix allowed
- F401 (unused import): auto-fix allowed
- E501 (line too long): auto-fix allowed
- Security findings: NEVER auto-fix, report only
