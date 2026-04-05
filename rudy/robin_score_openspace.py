"""
Robin Score -> OpenSpace Bridge CLI.

Thin wrapper that Robin calls after scoring a session to feed
results into the OpenSpace skill evolution engine via full_feedback_loop().

Usage:
    python -m rudy.robin_score_openspace --score-file PATH [--session N] [--skills S1 S2]
    python -m rudy.robin_score_openspace --scan  (process all unprocessed scores in coordination/)

Design constraints:
    - Import isolation (C3): Non-stdlib imports inside function bodies.
    - Results written to JSON file (DC stdout workaround LG-S63-001).
    - OracleShell-first (S67): Uses rudy.paths, no hardcoded paths.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("robin.score_openspace")


def _result_path(session_number: int) -> Path:
    """Return path for the bridge result JSON."""
    from rudy.paths import RUDY_DATA
    return RUDY_DATA / "coordination" / f"openspace-bridge-s{session_number}.json"


def _find_score_files() -> list[Path]:
    """Find unprocessed score JSON files in coordination/."""
    from rudy.paths import RUDY_DATA
    coord = RUDY_DATA / "coordination"
    if not coord.exists():
        return []
    score_files = []
    for f in sorted(coord.glob("*-score-s*.json")):
        # Check if bridge result already exists
        # Extract session number from filename like alfred-score-s99.json
        parts = f.stem.split("-score-s")
        if len(parts) == 2:
            try:
                sn = int(parts[1])
                result = _result_path(sn)
                if not result.exists():
                    score_files.append(f)
            except ValueError:
                continue
    return score_files


def feed_score_to_openspace(
    score_file: str,
    session_number: int = 0,
    skill_ids: list[str] | None = None,
    task_desc: str = "",
) -> dict:
    """Read a score JSON and feed it through the OpenSpace bridge.

    Args:
        score_file: Path to score JSON (lucius_scorer format).
        session_number: Session number (auto-detected from filename if 0).
        skill_ids: OpenSpace skill_ids used in the session.
        task_desc: Human-readable session description.

    Returns:
        dict with bridge result (written to JSON file as well).
    """
    from rudy.agents.lucius_openspace_bridge import full_feedback_loop

    score_path = Path(score_file)
    if not score_path.exists():
        return {"status": "error", "error": f"Score file not found: {score_file}"}

    score_result = json.loads(score_path.read_text(encoding="utf-8"))

    # Auto-detect session number from filename if not provided
    if session_number == 0:
        parts = score_path.stem.split("-score-s")
        if len(parts) == 2:
            try:
                session_number = int(parts[1])
            except ValueError:
                pass
        if session_number == 0:
            session_number = score_result.get("evidence", {}).get(
                "session_number", 0
            )

    if not task_desc:
        grade = score_result.get("grade", "?")
        total = score_result.get("total_score", 0)
        task_desc = f"Session {session_number}: scored {total}/100 ({grade})"

    # Run the async bridge
    try:
        result = asyncio.run(full_feedback_loop(
            score_result=score_result,
            skill_ids_used=skill_ids or [],
            task_description=task_desc,
            session_number=session_number,
        ))
    except Exception as e:
        result = {"status": "error", "error": str(e)}

    # Persist result to JSON (DC stdout workaround)
    result_file = _result_path(session_number)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "status": result.get("status", "recorded") if "error" not in result else "error",
        "session_number": session_number,
        "score_file": str(score_path),
        "bridge_result": result,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    result_file.write_text(
        json.dumps(output, indent=2, default=str), encoding="utf-8"
    )
    log.info(
        "Fed S%d score into OpenSpace bridge -> %s",
        session_number, result_file,
    )
    return output


def scan_and_process() -> list[dict]:
    """Scan coordination/ for unprocessed scores and feed them all."""
    score_files = _find_score_files()
    if not score_files:
        log.info("No unprocessed score files found.")
        return []
    results = []
    for sf in score_files:
        log.info("Processing score file: %s", sf.name)
        r = feed_score_to_openspace(str(sf))
        results.append(r)
    return results


def main() -> None:
    """CLI entry point."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [ScoreBridge] %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Robin Score -> OpenSpace Bridge",
    )
    parser.add_argument(
        "--score-file", help="Path to score JSON file",
    )
    parser.add_argument(
        "--session", type=int, default=0, help="Session number",
    )
    parser.add_argument(
        "--skills", nargs="*", help="OpenSpace skill_ids used",
    )
    parser.add_argument(
        "--task", default="", help="Task description",
    )
    parser.add_argument(
        "--scan", action="store_true",
        help="Scan coordination/ for unprocessed scores",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON",
    )
    args = parser.parse_args()

    if args.scan:
        results = scan_and_process()
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            print(f"Processed {len(results)} score files.")
            for r in results:
                s = r.get("session_number", "?")
                st = r.get("status", "?")
                print(f"  S{s}: {st}")
    elif args.score_file:
        result = feed_score_to_openspace(
            score_file=args.score_file,
            session_number=args.session,
            skill_ids=args.skills,
            task_desc=args.task,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"S{result['session_number']}: {result['status']}")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
