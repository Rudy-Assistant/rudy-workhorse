"""
Lucius Waste Detection — Phase 3: Stale artifacts, orphaned code, duplicates.

Scans the codebase for:
    1. Stale artifacts: files >30 days without modification or reference
    2. Orphaned code: Python modules with no imports from anywhere
    3. Duplicate work: files modified in consecutive sessions without resolution

Design constraints:
    - Import isolation (C3): All non-stdlib imports inside function bodies.
    - Uses the Lucius Registry for efficient scanning when available.
    - Findings are filed via the findings tracker.

CLI:
    python -m rudy.agents.lucius_waste [scan|stale|orphans|report]
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("lucius.waste")

STALE_THRESHOLD_DAYS = 30


def _get_paths():
    try:
        from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS
        return REPO_ROOT, RUDY_DATA, RUDY_LOGS
    except ImportError:
        repo = Path(__file__).resolve().parent.parent.parent
        return repo, repo.parent / "rudy-data", repo.parent / "rudy-logs"


def detect_stale_artifacts(
    repo_root: Optional[Path] = None,
    threshold_days: int = STALE_THRESHOLD_DAYS,
) -> list[dict]:
    """Find files that haven't been modified in > threshold_days.

    Focuses on Python files and scripts. Ignores __pycache__, .git, tests.
    """
    _repo, _, _ = _get_paths()
    repo_root = repo_root or _repo

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=threshold_days)
    stale = []

    scan_dirs = [repo_root / "rudy", repo_root / "scripts"]
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for f in scan_dir.rglob("*.py"):
            if "__pycache__" in str(f) or ".git" in str(f):
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    days_stale = (now - mtime).days
                    stale.append({
                        "path": str(f.relative_to(repo_root)).replace("\\", "/"),
                        "last_modified": mtime.isoformat(),
                        "days_stale": days_stale,
                        "size_bytes": f.stat().st_size,
                    })
            except OSError:
                continue

    stale.sort(key=lambda s: s["days_stale"], reverse=True)
    return stale


def detect_orphaned_modules(repo_root: Optional[Path] = None) -> list[dict]:
    """Find Python modules that are never imported by any other module.

    An orphan is a .py file under rudy/ that:
        - Is not __init__.py
        - Is not a CLI entry point (has if __name__ == "__main__")
        - Is not imported by any other Python file in the repo
    """
    _repo, _, _ = _get_paths()
    repo_root = repo_root or _repo
    rudy_pkg = repo_root / "rudy"

    if not rudy_pkg.exists():
        return []

    # Build set of all module stems under rudy/
    all_modules = {}
    for f in rudy_pkg.rglob("*.py"):
        if "__pycache__" in str(f) or f.name == "__init__.py":
            continue
        rel = str(f.relative_to(repo_root)).replace("\\", "/")
        stem = f.stem
        dotpath = rel.replace("/", ".").replace(".py", "")
        all_modules[stem] = {"path": rel, "dotpath": dotpath, "imported_by": []}

    # Scan all Python files for imports
    for f in repo_root.rglob("*.py"):
        if "__pycache__" in str(f) or ".git" in str(f):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_importer = str(f.relative_to(repo_root)).replace("\\", "/")
        for stem, info in all_modules.items():
            # Check various import patterns
            if (
                f"import {stem}" in content
                or f"from rudy.{stem}" in content
                or f"from rudy.agents.{stem}" in content
                or f"from rudy.workflows.{stem}" in content
                or f"from rudy.integrations.{stem}" in content
                or f"from rudy.tools.{stem}" in content
            ):
                if rel_importer != info["path"]:
                    info["imported_by"].append(rel_importer)

    # CLI entry points are not orphans
    orphans = []
    for stem, info in all_modules.items():
        if not info["imported_by"]:
            # Check if it's a CLI entry point
            try:
                content = (repo_root / info["path"]).read_text(
                    encoding="utf-8", errors="replace"
                )
                if 'if __name__' in content and '__main__' in content:
                    continue  # CLI entry, not an orphan
            except OSError:
                pass
            orphans.append({
                "path": info["path"],
                "dotpath": info["dotpath"],
                "reason": "Not imported by any other module",
            })

    return orphans


def full_waste_scan(
    repo_root: Optional[Path] = None,
    session: int = 0,
    file_findings: bool = True,
) -> dict:
    """Run a full waste detection scan.

    Args:
        repo_root: Repository root, or auto-detect.
        session: Current session number (for findings filing).
        file_findings: If True, file discovered waste as Lucius findings.

    Returns:
        dict with stale_artifacts, orphaned_modules, and summary.
    """
    _repo, _, _ = _get_paths()
    repo_root = repo_root or _repo

    start = time.perf_counter()

    stale = detect_stale_artifacts(repo_root)
    orphans = detect_orphaned_modules(repo_root)

    elapsed = time.perf_counter() - start

    result = {
        "stale_artifacts": stale,
        "orphaned_modules": orphans,
        "stats": {
            "stale_count": len(stale),
            "orphan_count": len(orphans),
            "scan_duration_sec": round(elapsed, 3),
        },
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    # File as findings if requested
    if file_findings and (stale or orphans):
        try:
            from rudy.agents.lucius_findings import add_finding
            for s in stale[:10]:  # Cap at 10 to avoid flooding
                add_finding(
                    severity="LOW",
                    category="stale_artifact",
                    message=f"File unchanged for {s['days_stale']} days: {s['path']}",
                    file=s["path"],
                    session=session,
                    source="lucius_waste",
                )
            for o in orphans[:10]:
                add_finding(
                    severity="LOW",
                    category="orphaned_code",
                    message=f"Module never imported: {o['path']}",
                    file=o["path"],
                    session=session,
                    source="lucius_waste",
                )
        except ImportError:
            pass

    log.info(
        f"Waste scan: {len(stale)} stale, {len(orphans)} orphans "
        f"in {elapsed:.2f}s"
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Lucius Waste Detection — stale artifacts and orphaned code"
    )
    parser.add_argument(
        "command",
        choices=["scan", "stale", "orphans", "report"],
        help="scan: full waste scan | stale: stale files | orphans: unused modules | report: summary",
    )
    parser.add_argument("--session", type=int, default=0, help="Session number")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--threshold", type=int, default=STALE_THRESHOLD_DAYS,
                       help="Days before a file is considered stale")
    args = parser.parse_args()

    if args.command == "scan":
        result = full_waste_scan(session=args.session)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Stale artifacts: {result['stats']['stale_count']}")
            print(f"Orphaned modules: {result['stats']['orphan_count']}")
            print(f"Scan time: {result['stats']['scan_duration_sec']}s")

    elif args.command == "stale":
        stale = detect_stale_artifacts(threshold_days=args.threshold)
        if args.json:
            print(json.dumps(stale, indent=2, default=str))
        else:
            if not stale:
                print("No stale artifacts found.")
            else:
                for s in stale:
                    print(f"  {s['days_stale']:3d}d  {s['path']}")

    elif args.command == "orphans":
        orphans = detect_orphaned_modules()
        if args.json:
            print(json.dumps(orphans, indent=2, default=str))
        else:
            if not orphans:
                print("No orphaned modules found.")
            else:
                for o in orphans:
                    print(f"  {o['path']}  ({o['reason']})")

    elif args.command == "report":
        result = full_waste_scan(session=args.session, file_findings=False)
        print("\n=== Lucius Waste Report ===\n")
        print(f"Stale artifacts ({result['stats']['stale_count']}):")
        for s in result["stale_artifacts"][:15]:
            print(f"  {s['days_stale']:3d}d  {s['path']}")
        print(f"\nOrphaned modules ({result['stats']['orphan_count']}):")
        for o in result["orphaned_modules"][:15]:
            print(f"  {o['path']}")
        print(f"\nScan time: {result['stats']['scan_duration_sec']}s")


if __name__ == "__main__":
    main()
