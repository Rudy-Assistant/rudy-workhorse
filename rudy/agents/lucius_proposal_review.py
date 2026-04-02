"""
Lucius Proposal Review -- New module/dependency proposal review (LRR).

Extracted from lucius_fox.py (ADR-005 Phase 2b, Session 73).
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from rudy.paths import RUDY_DATA

log = logging.getLogger("lucius_fox")

REVIEWS_DIR = RUDY_DATA / "lucius-reviews"
REVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def review_proposal(
    proposal: dict,
    inventory: dict = None,
    reviews_dir: Path = None,
) -> dict:
    """Review a new module/dependency proposal (Lucius Review Record).

    Args:
        proposal: Dict with at least 'title' and optionally 'description'.
        inventory: Code inventory dict with 'modules' key (optional).
        reviews_dir: Directory for review output. Defaults to rudy-data/lucius-reviews/.

    Returns:
        LRR dict with review_id, verdict, alternatives_found, recommendation.
    """
    if reviews_dir is None:
        reviews_dir = REVIEWS_DIR
    reviews_dir.mkdir(parents=True, exist_ok=True)

    log.info("Reviewing proposal: %s", proposal.get("title", "untitled"))

    record = {
        "review_id": f"LRR-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "timestamp": datetime.now().isoformat(),
        "proposal": proposal,
        "verdict": "pending",
        "alternatives_found": [],
        "recommendation": "",
        "implementation_spec": None,
        "checks": {
            "duplicates_existing": False,
            "requires_new_dependency": False,
            "architecture_impact": "none",
        },
    }

    title_lower = proposal.get("title", "").lower()
    desc_lower = proposal.get("description", "").lower()

    # Check for overlap with existing modules
    if inventory and "modules" in inventory:
        for path in inventory["modules"]:
            module_name = Path(path).stem.lower()
            if module_name in title_lower or module_name in desc_lower:
                record["checks"]["duplicates_existing"] = True
                record["alternatives_found"].append(path)

    if record["checks"]["duplicates_existing"]:
        record["verdict"] = "request_changes"
        record["recommendation"] = (
            f"Possible overlap with existing modules: "
            f"{record['alternatives_found']}. "
            "Review for consolidation before creating new module."
        )
    else:
        record["verdict"] = "approved_pending_implementation"
        record["recommendation"] = (
            "No obvious overlap. Proceed with implementation."
        )

    review_file = reviews_dir / f"{record['review_id']}.json"
    with open(review_file, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

    log.info("Proposal review: %s", record["verdict"])
    return record
