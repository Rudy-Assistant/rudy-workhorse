"""Codex Rollback Safety Gate — Prototype (P5-S36).

Reviews git diffs for irreversible or dangerous operations before commit.
Uses OpenAI API for adversarial code review, focused on rollback safety.

Wire into pre_commit_check as an optional Lucius sub-gate.

Usage:
    from rudy.agents.codex_rollback_gate import review_diff
    result = review_diff(diff_text)
    if not result["safe"]:
        print("BLOCKED:", result["findings"])
"""

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("rudy.codex_gate")

# Focus areas for rollback safety review
ROLLBACK_FOCUS = """
Review this git diff for ROLLBACK SAFETY issues only. Flag:
1. Irreversible file deletions or overwrites without backup
2. Database/state mutations without rollback path
3. Force-push, reset --hard, or destructive git operations
4. Config changes that can't be undone easily
5. Credential or secret exposure in committed code
6. Missing error handling around destructive operations

Respond in JSON: {"safe": bool, "findings": [{"severity": "HIGH|MED|LOW", "line": str, "issue": str}]}
If the diff is safe, return {"safe": true, "findings": []}.
"""


def get_current_diff(repo_path: str | None = None) -> str:
    """Get the staged diff from the repo."""
    cwd = repo_path or str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        ["git", "diff", "--cached"],
        capture_output=True, text=True, cwd=cwd,
    )
    if not result.stdout.strip():
        # Fall back to unstaged diff
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, cwd=cwd,
        )
    return result.stdout


def review_diff(diff_text: str, model: str = "gpt-4o-mini") -> dict:
    """Review a diff for rollback safety issues.

    Args:
        diff_text: Git diff output
        model: OpenAI model to use (default: gpt-4o-mini for cost efficiency)

    Returns:
        {"safe": bool, "findings": [...], "model": str, "error": str|None}
    """
    if not diff_text.strip():
        return {"safe": True, "findings": [], "model": model, "error": None}

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        log.warning("OPENAI_API_KEY not set — rollback gate skipped")
        return {
            "safe": True,
            "findings": [],
            "model": model,
            "error": "OPENAI_API_KEY not configured — gate skipped",
        }

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Truncate very large diffs to stay within token limits
        max_chars = 12000
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars] + "\n... [truncated]"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ROLLBACK_FOCUS.strip()},
                {"role": "user", "content": diff_text},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1000,
        )

        content = response.choices[0].message.content
        result = json.loads(content)
        result["model"] = model
        result["error"] = None
        return result

    except ImportError:
        log.error("openai package not installed")
        return {"safe": True, "findings": [], "model": model, "error": "openai not installed"}
    except Exception as e:
        log.error("Codex rollback gate failed: %s", e)
        return {"safe": True, "findings": [], "model": model, "error": str(e)}


def gate_check(repo_path: str | None = None) -> bool:
    """Run the rollback safety gate. Returns True if safe to proceed.

    Designed to be called from pre_commit_check as an optional sub-gate.
    """
    diff = get_current_diff(repo_path)
    if not diff.strip():
        log.info("No diff to review — gate passes")
        return True

    result = review_diff(diff)

    if result.get("error"):
        log.warning("Rollback gate error (non-blocking): %s", result["error"])
        return True  # Non-blocking on error

    if result["safe"]:
        log.info("Rollback gate: SAFE")
        return True

    high_findings = [f for f in result["findings"] if f.get("severity") == "HIGH"]
    if high_findings:
        log.warning("Rollback gate: BLOCKED — %d HIGH findings", len(high_findings))
        for f in high_findings:
            log.warning("  [%s] %s", f.get("severity"), f.get("issue"))
        return False

    # MED/LOW findings are advisory only
    log.info("Rollback gate: PASS with %d advisory findings", len(result["findings"]))
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Test with current repo diff
        diff = get_current_diff()
        if diff:
            print(f"Reviewing {len(diff)} chars of diff...")
            result = review_diff(diff)
            print(json.dumps(result, indent=2))
        else:
            print("No diff found.")
    else:
        # Run as gate
        safe = gate_check()
        sys.exit(0 if safe else 1)
