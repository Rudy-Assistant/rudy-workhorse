#!/usr/bin/env python3
"""
Skill Transfer Protocol — How skills flow between Alfred and Robin.

Directory Structure:
    .claude/skills/           # Shared skill library (git-tracked)
        {skill-name}/
            SKILL.md          # OpenSpace-format skill definition
            .skill_id         # OpenSpace registry ID (auto-generated)

    rudy-data/skill-transfer/ # Transfer staging area (local only)
        pending/              # Skills awaiting transfer
        completed/            # Transfer receipts
        evolution/            # OpenSpace evolution records

Flow:
    1. Alfred creates/improves a skill -> writes SKILL.md to .claude/skills/
    2. OpenSpace registers it -> generates .skill_id
    3. Robin picks up new/changed skills on next poll cycle
    4. Robin executes skill -> OpenSpace captures ExecutionAnalysis
    5. Lucius scores execution -> lucius_openspace_bridge feeds score back
    6. OpenSpace evolves skill (AUTO-FIX / AUTO-IMPROVE)
    7. Both Alfred and Robin benefit from evolved version

Integration:
    - OpenSpace watches OPENSPACE_HOST_SKILL_DIRS for changes
    - peers_delegation.py sends DELEGATE messages with skill_id references
    - robin_taskqueue.py maps skill task_type to Robin's execution engine
"""

import json
import logging
import os
from rudy.paths import REPO_ROOT, RUDY_DATA
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("skill_transfer")

# Paths
REPO_ROOT = Path(os.environ.get(
    "RUDY_REPO", str(REPO_ROOT)
))
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
RUDY_DATA = Path(os.environ.get(
    "RUDY_DATA", str(RUDY_DATA)
))
TRANSFER_DIR = RUDY_DATA / "skill-transfer"
PENDING_DIR = TRANSFER_DIR / "pending"
COMPLETED_DIR = TRANSFER_DIR / "completed"
EVOLUTION_DIR = TRANSFER_DIR / "evolution"


# Robin's task type -> skill mapping
TASK_TYPE_SKILLS = {
    "audit": ["system-audit", "security-sweep"],
    "browse": ["web-fetch", "gui-interact", "form-fill", "screen-reader", "bruce-proxy"],
    "git": ["git-operations"],
    "code_quality": ["code-lint"],
    "report": ["generate-report"],
    "handoff": ["delegate-task"],
    "shell": ["powershell-execute", "app-launcher"],
    "health_check": ["system-health-check", "service-monitor"],
    "security_scan": ["security-sweep"],
    "skill_execute": [],  # Dynamic — any skill by ID
    "profile": ["bruce-proxy"],  # Profile tasks use proxy behavior
}


def ensure_dirs():
    """Create transfer directories if they don't exist."""
    for d in [TRANSFER_DIR, PENDING_DIR, COMPLETED_DIR, EVOLUTION_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def list_skills() -> list[dict]:
    """List all skills in the shared library."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        skill_id_file = skill_dir / ".skill_id"
        skill_id = skill_id_file.read_text().strip() if skill_id_file.exists() else None
        # Parse frontmatter
        meta = _parse_frontmatter(skill_md)
        skills.append({
            "name": skill_dir.name,
            "skill_id": skill_id,
            "path": str(skill_md),
            "agent": meta.get("agent", "any"),
            "task_type": meta.get("task_type", "unknown"),
            "version": meta.get("version", "0.0.0"),
            "description": meta.get("description", ""),
            "modified": datetime.fromtimestamp(
                skill_md.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return skills


def _parse_frontmatter(skill_md: Path) -> dict:
    """Parse YAML-like frontmatter from SKILL.md."""
    meta = {}
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return meta
    end = text.find("---", 3)
    if end == -1:
        return meta
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") or val.startswith("-"):
                continue  # Skip lists
            meta[key] = val
    return meta


def skills_for_task_type(task_type: str) -> list[dict]:
    """Get skills that match a given Robin task type."""
    skill_names = TASK_TYPE_SKILLS.get(task_type, [])
    all_skills = list_skills()
    return [s for s in all_skills if s["name"] in skill_names]


def robin_skills() -> list[dict]:
    """Get all skills tagged for Robin."""
    return [s for s in list_skills() if s["agent"] in ("robin", "any")]


def create_transfer_record(
    skill_name: str,
    from_agent: str,
    to_agent: str,
    action: str,
    details: str = "",
) -> dict:
    """Record a skill transfer event."""
    ensure_dirs()
    record = {
        "id": f"xfer-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{skill_name}",
        "skill_name": skill_name,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "action": action,  # created | updated | evolved | fixed
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    record_path = COMPLETED_DIR / f"{record['id']}.json"
    record_path.write_text(json.dumps(record, indent=2))
    log.info("Transfer recorded: %s -> %s [%s] %s", from_agent, to_agent, action, skill_name)
    return record


def record_evolution(
    skill_name: str,
    evolution_type: str,
    before_version: str,
    after_version: str,
    trigger: str,
    lucius_score: int = None,
) -> dict:
    """Record an OpenSpace evolution event."""
    ensure_dirs()
    record = {
        "skill_name": skill_name,
        "evolution_type": evolution_type,  # AUTO-FIX | AUTO-IMPROVE | AUTO-LEARN
        "before_version": before_version,
        "after_version": after_version,
        "trigger": trigger,
        "lucius_score": lucius_score,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    fname = f"evo-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{skill_name}.json"
    (EVOLUTION_DIR / fname).write_text(json.dumps(record, indent=2))
    log.info("Evolution: %s [%s] %s -> %s", skill_name, evolution_type, before_version, after_version)
    return record


def get_transfer_history(skill_name: str = None, limit: int = 20) -> list[dict]:
    """Get recent transfer records, optionally filtered by skill."""
    ensure_dirs()
    records = []
    for f in sorted(COMPLETED_DIR.glob("xfer-*.json"), reverse=True):
        rec = json.loads(f.read_text())
        if skill_name and rec.get("skill_name") != skill_name:
            continue
        records.append(rec)
        if len(records) >= limit:
            break
    return records


def get_evolution_history(skill_name: str = None, limit: int = 20) -> list[dict]:
    """Get recent evolution records."""
    ensure_dirs()
    records = []
    for f in sorted(EVOLUTION_DIR.glob("evo-*.json"), reverse=True):
        rec = json.loads(f.read_text())
        if skill_name and rec.get("skill_name") != skill_name:
            continue
        records.append(rec)
        if len(records) >= limit:
            break
    return records


# CLI
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        skills = list_skills()
        print(f"Skills in library: {len(skills)}")
        for s in skills:
            agent_tag = f"[{s['agent']}]" if s['agent'] != 'any' else ""
            sid = f" (id:{s['skill_id'][:8]})" if s['skill_id'] else ""
            print(f"  {s['name']:30s} {agent_tag:8s} v{s['version']}{sid}")

    elif cmd == "robin":
        skills = robin_skills()
        print(f"Robin-compatible skills: {len(skills)}")
        for s in skills:
            print(f"  {s['name']:30s} type={s['task_type']:15s} v{s['version']}")

    elif cmd == "map":
        print("Task Type -> Skill Mapping:")
        for tt, skill_names in TASK_TYPE_SKILLS.items():
            available = skills_for_task_type(tt)
            print(f"  {tt:15s} -> {len(available)}/{len(skill_names)} available: {', '.join(s['name'] for s in available)}")

    elif cmd == "history":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        records = get_transfer_history(name)
        print(f"Transfer history: {len(records)} records")
        for r in records:
            print(f"  [{r['timestamp'][:19]}] {r['from_agent']}->{r['to_agent']} {r['action']} {r['skill_name']}")

    else:
        print(f"Usage: {sys.argv[0]} [list|robin|map|history [skill_name]]")
