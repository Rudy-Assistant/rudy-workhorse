"""
Proposal Pipeline -- Alfred->Lucius->Robin workflow for feature proposals.

Session 62: Closes the self-sustaining backlog loop.

Flow:
  1. Alfred writes proposal to vault/Roadmap/Proposals/AF-S{N}-{title}.md
  2. Lucius scans for pending proposals during session_start_gate
  3. Lucius approves -> item added to Batcave-Roadmap, proposal marked approved
  4. Robin's InitiativeEngine consumes approved roadmap items by priority

Usage:
    from rudy.proposal_pipeline import (
        write_proposal,       # Alfred calls this
        scan_proposals,       # Lucius gate calls this
        get_approved_items,   # Robin's InitiativeEngine calls this
    )
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger("proposal_pipeline")


def _proposals_dir() -> Path:
    try:
        from rudy.paths import PROPOSALS_DIR
        return PROPOSALS_DIR
    except ImportError:
        return Path(__file__).resolve().parent.parent / "vault" / "Roadmap" / "Proposals"


def _roadmap_dir() -> Path:
    try:
        from rudy.paths import VAULT_ROADMAP
        return VAULT_ROADMAP
    except ImportError:
        return Path(__file__).resolve().parent.parent / "vault" / "Roadmap"


def write_proposal(
    title: str, description: str, justification: str,
    agent: str = "Alfred", session: int = 0, priority: str = "P1",
    effort: str = "Medium", key_files: list[str] | None = None,
    skills: list[str] | None = None,
) -> Path:
    """Write a structured proposal to vault/Roadmap/Proposals/."""
    proposals = _proposals_dir()
    proposals.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    prefix = agent[:2].upper()
    filename = f"{prefix}-S{session}-{slug}.md"
    filepath = proposals / filename
    date_str = datetime.now().strftime("%Y-%m-%d")
    key_files_str = "\n".join(f"- `{f}`" for f in (key_files or []))
    skills_str = ", ".join(skills or ["(none identified)"])
    content = f"""# Proposal: {title}

**Author:** {agent}-S{session}
**Date:** {date_str}
**Status:** pending
**Priority:** {priority}

## Description

{description}

## Justification

{justification}

## Estimated Effort

{effort}

## Key Files

{key_files_str or "(none specified)"}

## Dependencies

(none)

## Relevant Skills

{skills_str}

---

## Lucius Review

**Reviewed by:**
**Decision:**
**Roadmap ID:**
**Notes:**
"""
    filepath.write_text(content, encoding="utf-8")
    log.info("[Proposal] Written: %s", filepath.name)
    return filepath


def scan_proposals() -> list[dict]:
    """Scan vault/Roadmap/Proposals/ for pending proposals."""
    proposals = _proposals_dir()
    if not proposals.exists():
        return []
    pending = []
    for md_file in sorted(proposals.glob("*.md")):
        if md_file.name == "TEMPLATE.md":
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            if "**Status:** pending" not in text:
                continue
            title_match = re.search(r"^# Proposal:\s*(.+)$", text, re.MULTILINE)
            priority_match = re.search(r"\*\*Priority:\*\*\s*(P\d)", text)
            author_match = re.search(r"\*\*Author:\*\*\s*(.+)$", text, re.MULTILINE)
            effort_match = re.search(r"## Estimated Effort\s+(.+?)(?:\n#|\n---|\Z)", text, re.DOTALL)
            pending.append({
                "file": str(md_file), "filename": md_file.name,
                "title": title_match.group(1).strip() if title_match else md_file.stem,
                "priority": priority_match.group(1) if priority_match else "P2",
                "author": author_match.group(1).strip() if author_match else "unknown",
                "effort": effort_match.group(1).strip() if effort_match else "unknown",
            })
        except OSError as e:
            log.warning("[Proposal] Could not read %s: %s", md_file, e)
    pending.sort(key=lambda p: p["priority"])
    log.info("[Proposal] Found %d pending proposal(s)", len(pending))
    return pending


def mark_proposal(filename: str, new_status: str, reviewer: str = "Lucius",
                   notes: str = "") -> bool:
    """Update the status of a proposal markdown file.

    Args:
        filename: Name of the .md file in Proposals/
        new_status: One of 'approved', 'rejected', 'deferred', 'needs-revision'
        reviewer: Who reviewed it (default Lucius)
        notes: Optional review notes appended to Lucius Review section

    Returns:
        True if the file was updated successfully.
    """
    import re
    from rudy.paths import PROPOSALS_DIR

    md_path = PROPOSALS_DIR / filename
    if not md_path.exists():
        log.error("[Proposal] File not found: %s", md_path)
        return False

    text = md_path.read_text(encoding="utf-8")

    # Update status field
    text = re.sub(
        r"\*\*Status:\*\*\s*\S+",
        f"**Status:** {new_status}",
        text,
        count=1,
    )

    # Append reviewer notes if provided
    if notes:
        review_header = "## Lucius Review"
        if review_header in text:
            text = text.replace(
                review_header,
                f"{review_header}\n\n"
                f"**Reviewer:** {reviewer}  \n"
                f"**Date:** {_today()}  \n"
                f"**Decision:** {new_status}  \n"
                f"**Notes:** {notes}\n",
            )

    md_path.write_text(text, encoding="utf-8")
    log.info("[Proposal] Marked %s as '%s' by %s", filename, new_status, reviewer)
    return True


def get_approved_items() -> list[dict]:
    """Return approved proposals sorted by priority (P0 first).

    This is the entry point Robin's InitiativeEngine uses to find
    roadmap items ready for execution.

    Returns:
        List of dicts with keys: title, priority, filename,
        roadmap_id (derived from filename).
    """
    import re
    from rudy.paths import PROPOSALS_DIR

    approved: list[dict] = []
    if not PROPOSALS_DIR.exists():
        return approved

    for md_file in sorted(PROPOSALS_DIR.glob("*.md")):
        if md_file.name == "TEMPLATE.md":
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            if not re.search(r"\*\*Status:\*\*\s*approved", text, re.I):
                continue

            title_match = re.search(r"^#\s+(.+)", text, re.M)
            priority_match = re.search(
                r"\*\*Priority:\*\*\s*(\S+)", text, re.I
            )
            approved.append({
                "title": title_match.group(1).strip() if title_match else md_file.stem,
                "priority": priority_match.group(1).strip() if priority_match else "P2",
                "filename": md_file.name,
                "roadmap_id": md_file.stem,
            })
        except OSError as e:
            log.warning("[Proposal] Could not read %s: %s", md_file, e)

    # Sort by priority string (P0 < P1 < P2)
    approved.sort(key=lambda p: p["priority"])
    log.info("[Proposal] Found %d approved item(s) ready for execution", len(approved))
    return approved
