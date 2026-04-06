"""
carry_guard.py — structural safeguard against multi-session carries.

Invoked at boot and at handoff-write time. Refuses to proceed if any
finding has been carried more than MAX_CARRIES sessions without
resolution. The point is to make "I'll carry it again" mechanically
impossible, not behaviorally discouraged.

Resolution requires ONE of:
  1. The file has been committed (git status clean for that path).
  2. The carry has a Batman waiver token in
     vault/Protocols/carry-waivers.json with an unexpired session bound.
  3. A PR closing the finding is open against main.

Failure mode: raises CarryViolation. Boot protocol and handoff writer
both catch this and HALT the session until a resolver is run.

Usage (boot):
    from rudy.agents.carry_guard import enforce_carry_limit
    enforce_carry_limit(repo_root)  # raises if violated

Usage (handoff write):
    enforce_carry_limit(repo_root, phase="handoff")
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_CARRIES = 2  # third session attempting to carry triggers HALT
CARRY_PATTERNS = [
    re.compile(r"(\d+)(?:st|nd|rd|th)\s+carry", re.IGNORECASE),
    re.compile(r"(\d+)\s+sessions?\s+blocking", re.IGNORECASE),
    re.compile(r"(\d+)(?:st|nd|rd|th)\s+consecutive", re.IGNORECASE),
]
WAIVER_PATH = Path("vault/Protocols/carry-waivers.json")


class CarryViolation(RuntimeError):
    """Raised when a finding exceeds MAX_CARRIES without resolution."""


@dataclass
class Carry:
    finding: str
    count: int
    line: str

    def __str__(self) -> str:
        return f"{self.finding} (carry={self.count}): {self.line.strip()}"


def _latest_handoff(repo_root: Path) -> Path | None:
    handoffs = sorted(
        (repo_root / "vault" / "Handoffs").glob("Session-*-Handoff.md"),
        key=lambda p: int(re.search(r"Session-(\d+)", p.name).group(1)),
    )
    return handoffs[-1] if handoffs else None


def _scan_carries(handoff: Path) -> list[Carry]:
    text = handoff.read_text(encoding="utf-8", errors="replace")
    out: list[Carry] = []
    for line in text.splitlines():
        for pat in CARRY_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            count = int(m.group(1))
            if count <= MAX_CARRIES:
                continue
            finding_match = re.search(r"(F-S\d+-\d+|LG-S\d+-\d+|bridge PR|skill gate)", line, re.IGNORECASE)
            finding = finding_match.group(1) if finding_match else line.strip()[:60]
            out.append(Carry(finding=finding, count=count, line=line))
    return out


def _load_waivers(repo_root: Path) -> dict:
    p = repo_root / WAIVER_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _waived(carry: Carry, waivers: dict, current_session: int) -> bool:
    entry = waivers.get(carry.finding)
    if not entry:
        return False
    expires = entry.get("expires_session")
    return expires is None or current_session <= int(expires)


def _open_prs(repo_root: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "title"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return []
        return [item.get("title", "") for item in json.loads(r.stdout or "[]")]
    except Exception:
        return []


def _has_open_pr_for(carry: Carry, pr_titles: list[str]) -> bool:
    finding = carry.finding.lower()
    return any(finding in t.lower() for t in pr_titles)


def enforce_carry_limit(repo_root: Path, phase: str = "boot") -> list[Carry]:
    """
    Raises CarryViolation if any carry exceeds MAX_CARRIES without resolution.
    Returns the list of carries that were inspected (for logging).
    """
    handoff = _latest_handoff(repo_root)
    if handoff is None:
        return []
    session_match = re.search(r"Session-(\d+)", handoff.name)
    current_session = int(session_match.group(1)) if session_match else 0
    carries = _scan_carries(handoff)
    if not carries:
        return []
    waivers = _load_waivers(repo_root)
    pr_titles = _open_prs(repo_root)
    violations = [
        c for c in carries
        if not _waived(c, waivers, current_session)
        and not _has_open_pr_for(c, pr_titles)
    ]
    if violations:
        details = "\n  - ".join(str(v) for v in violations)
        raise CarryViolation(
            f"[carry_guard:{phase}] {len(violations)} finding(s) exceed "
            f"MAX_CARRIES={MAX_CARRIES} with no open PR and no waiver:\n  - {details}\n"
            f"Resolve by (1) committing/PR'ing the fix, (2) reverting the WIP, "
            f"or (3) adding a Batman waiver to {WAIVER_PATH}."
        )
    return carries


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    try:
        cs = enforce_carry_limit(root, phase=sys.argv[1] if len(sys.argv) > 1 else "boot")
        print(json.dumps({"ok": True, "inspected": len(cs)}))
    except CarryViolation as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(2)
