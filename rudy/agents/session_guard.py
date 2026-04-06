"""
session_guard.py — structural safeguards for Alfred sessions.

Three independent gates, all callable mechanically:

1. enforce_carry_limit()    — refuses to proceed if any finding has been
                              carried > MAX_CARRIES sessions without an
                              open PR or a Batman waiver.
2. enforce_work_floor()     — refuses to write a handoff while context
                              usage is below MIN_CTX_PCT, forcing the
                              session to actually do work.
3. enforce_delegation()     — refuses to write a handoff unless Robin
                              was either (a) given a directive, OR
                              (b) verified offline. No silent skips.

These exist because reminders and discipline have failed repeatedly.
They are intentionally hard to bypass; the only escape is an explicit
Batman waiver in vault/Protocols/carry-waivers.json.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_CARRIES = 2
MIN_CTX_PCT = 50  # below this, handoff write is REFUSED
WAIVER_PATH = Path("vault/Protocols/carry-waivers.json")
DIRECTIVES_DIR = Path("rudy-data/coordination")

# Lines containing any of these are positive streaks, not carries
POSITIVE_MARKERS = (
    "green",
    "validated",
    "recipe",
    "nerve-check success",
    "consecutive nerve",
    "stable",
    "holding",
)

CARRY_PATTERNS = [
    re.compile(r"(\d+)(?:st|nd|rd|th)\s+carry", re.IGNORECASE),
    re.compile(r"(\d+)\s+sessions?\s+blocking", re.IGNORECASE),
    re.compile(r"(\d+)(?:st|nd|rd|th)\s+consecutive\s+(verification|ritual|carry)", re.IGNORECASE),
]


class SessionGuardViolation(RuntimeError):
    """Raised when any structural gate is violated. Halts the session."""


@dataclass
class Carry:
    finding: str
    count: int
    line: str

    def __str__(self) -> str:
        return f"{self.finding} (carry={self.count}): {self.line.strip()[:120]}"


# ---------- helpers ----------

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
        low = line.lower()
        if any(m in low for m in POSITIVE_MARKERS):
            continue
        for pat in CARRY_PATTERNS:
            m = pat.search(line)
            if not m:
                continue
            count = int(m.group(1))
            if count <= MAX_CARRIES:
                continue
            fm = re.search(r"(F-S\d+-\d+|LG-S\d+-\d+)", line)
            finding = fm.group(1) if fm else line.strip()[:60]
            out.append(Carry(finding=finding, count=count, line=line))
            break
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


def _open_prs(repo_root: Path) -> list[dict]:
    import os
    env = os.environ.copy()
    env["PATH"] = (
        "C:\\Windows\\System32;C:\\Windows;"
        "C:\\Program Files\\Git\\cmd;C:\\Program Files\\Git\\bin;"
        "C:\\Program Files\\GitHub CLI;" + env.get("PATH", "")
    )
    env["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "title,headRefName,body"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        if r.returncode != 0:
            return []
        return json.loads(r.stdout or "[]")
    except Exception:
        return []


def _has_open_pr_for(carry: Carry, prs: list[dict]) -> bool:
    finding = carry.finding.lower()
    for pr in prs:
        haystack = " ".join([
            pr.get("title", ""),
            pr.get("headRefName", ""),
            pr.get("body", ""),
        ]).lower()
        if finding in haystack:
            return True
    return False


# ---------- gate 1: carry limit ----------

def enforce_carry_limit(repo_root: Path, phase: str = "boot") -> list[Carry]:
    handoff = _latest_handoff(repo_root)
    if handoff is None:
        return []
    sm = re.search(r"Session-(\d+)", handoff.name)
    current = int(sm.group(1)) if sm else 0
    carries = _scan_carries(handoff)
    if not carries:
        return []
    waivers = _load_waivers(repo_root)
    prs = _open_prs(repo_root)
    violations = [
        c for c in carries
        if not _waived(c, waivers, current) and not _has_open_pr_for(c, prs)
    ]
    if violations:
        details = "\n  - ".join(str(v) for v in violations)
        raise SessionGuardViolation(
            f"[session_guard:carry:{phase}] {len(violations)} finding(s) exceed "
            f"MAX_CARRIES={MAX_CARRIES} with no open PR and no waiver:\n  - {details}\n"
            f"Resolve by: (1) PR the fix, (2) revert WIP, or (3) add a Batman "
            f"waiver to {WAIVER_PATH}."
        )
    return carries


# ---------- gate 2: minimum work floor ----------

def enforce_work_floor(ctx_pct: int) -> None:
    """
    Refuse to write a handoff if context usage is below MIN_CTX_PCT.
    The session must DO WORK before it can hand off.
    """
    if ctx_pct < MIN_CTX_PCT:
        raise SessionGuardViolation(
            f"[session_guard:work_floor] Context at {ctx_pct}% is below "
            f"MIN_CTX_PCT={MIN_CTX_PCT}%. Handoff write REFUSED. "
            f"Keep working — pick the next priority off the handoff."
        )


# ---------- gate 3: Robin delegation requirement ----------

def enforce_delegation(repo_root: Path, current_session: int) -> None:
    """
    Refuse to write a handoff unless one of:
      (a) A directive file rudy-data/coordination/robin-directive-S{N}-*.md
          exists for the current session, OR
      (b) A file rudy-data/s{N}_robin_offline.flag exists (Robin verified
          offline this session — must be created intentionally).
    """
    # F-S189-002: verify directive files actually exist on disk and are
    # non-empty. Also scan an alternate rudy-data tree at ~/rudy-data/ to
    # catch the dual-tree silent-failure path that bit S188.
    coord = repo_root / DIRECTIVES_DIR
    candidates: list[Path] = []
    if coord.exists():
        candidates.extend(coord.glob(f"robin-directive-S{current_session}-*.md"))
    alt_coord = Path.home() / "rudy-data" / "coordination"
    if alt_coord.exists() and alt_coord.resolve() != coord.resolve():
        candidates.extend(alt_coord.glob(f"robin-directive-S{current_session}-*.md"))
    directive_files = [
        p for p in candidates
        if p.exists() and p.is_file() and p.stat().st_size > 0
    ]
    offline_flag = repo_root / "rudy-data" / f"s{current_session}_robin_offline.flag"
    if directive_files or offline_flag.exists():
        return
    raise SessionGuardViolation(
        f"[session_guard:delegation] Session {current_session} created no "
        f"Robin directive and no offline flag. Alfred is required to either "
        f"DELEGATE work to Robin (drop a directive at "
        f"{DIRECTIVES_DIR}/robin-directive-S{current_session}-*.md) "
        f"or verify Robin offline (touch rudy-data/s{current_session}_robin_offline.flag)."
    )


# ---------- combined entry points ----------

def enforce_boot(repo_root: Path) -> None:
    enforce_carry_limit(repo_root, phase="boot")


# ---------- gate 4: Robin work share ----------

MIN_ROBIN_SHARE_PCT = 50  # Robin must produce >=50% of session commits


def _git_authors_for_session(repo_root: Path, current_session: int) -> dict:
    """
    Returns {'robin': N, 'alfred': N, 'other': N} commit counts on branches
    matching s{N}/* since the previous session's HEAD. Falls back to last 24h.
    """
    import os
    env = os.environ.copy()
    env["PATH"] = (
        "C:\\Windows\\System32;C:\\Windows;"
        "C:\\Program Files\\Git\\cmd;C:\\Program Files\\Git\\bin;" + env.get("PATH", "")
    )
    try:
        r = subprocess.run(
            ["git", "log", "--all", "--since=24 hours ago", "--format=%an"],
            cwd=str(repo_root),
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode != 0:
            return {"robin": 0, "alfred": 0, "other": 0}
        counts = {"robin": 0, "alfred": 0, "other": 0}
        for line in (r.stdout or "").splitlines():
            low = line.lower()
            if "robin" in low:
                counts["robin"] += 1
            elif "alfred" in low:
                counts["alfred"] += 1
            else:
                counts["other"] += 1
        return counts
    except Exception:
        return {"robin": 0, "alfred": 0, "other": 0}


def enforce_robin_share(repo_root: Path, current_session: int) -> dict:
    """
    Refuse handoff if Robin's share of recent commits is below MIN_ROBIN_SHARE_PCT.
    Waivable per-session by creating rudy-data/s{N}_robin_share_waived.flag with
    a justification. The waiver flag MUST be opened intentionally; it is not
    auto-created.
    """
    waiver = repo_root / "rudy-data" / f"s{current_session}_robin_share_waived.flag"
    counts = _git_authors_for_session(repo_root, current_session)
    total = sum(counts.values())
    if total == 0:
        # No commits at all — fall back to delegation gate semantics; if a
        # directive was dropped this is acceptable in early ramp-up.
        return counts
    share = int(round(100 * counts["robin"] / total))
    if share < MIN_ROBIN_SHARE_PCT and not waiver.exists():
        raise SessionGuardViolation(
            f"[session_guard:robin_share] Robin produced {share}% of recent "
            f"commits ({counts['robin']}/{total}); minimum is "
            f"{MIN_ROBIN_SHARE_PCT}%. Either delegate the next priority to "
            f"Robin and re-run, or open "
            f"rudy-data/s{current_session}_robin_share_waived.flag with a "
            f"written justification (Batman expectation: >=50% by S192)."
        )
    return counts


def enforce_handoff(repo_root: Path, ctx_pct: int, current_session: int) -> None:
    enforce_carry_limit(repo_root, phase="handoff")
    enforce_work_floor(ctx_pct)
    enforce_delegation(repo_root, current_session)
    enforce_robin_share(repo_root, current_session)


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    phase = sys.argv[1] if len(sys.argv) > 1 else "boot"
    try:
        if phase == "handoff":
            ctx = int(sys.argv[2])
            sess = int(sys.argv[3])
            enforce_handoff(root, ctx, sess)
        else:
            enforce_boot(root)
        print(json.dumps({"ok": True, "phase": phase}))
    except SessionGuardViolation as exc:
        print(json.dumps({"ok": False, "phase": phase, "error": str(exc)}))
        sys.exit(2)
