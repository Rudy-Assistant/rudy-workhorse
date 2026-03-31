"""Run a full Lucius Fox audit with optional feedback loop. Portable — uses rudy.paths for all paths."""
import asyncio
import json
import sys
from pathlib import Path

# Add repo root to sys.path dynamically
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudy.agents.lucius_fox import LuciusFox


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run Lucius Fox audit")
    parser.add_argument("--feedback-loop", action="store_true",
                        help="Activate ADR-008 feedback loop after audit")
    parser.add_argument("--session", type=int, default=0,
                        help="Session number for feedback loop")
    parser.add_argument("--task", default="", help="Task description")
    parser.add_argument("--score-file", help="Path to score JSON for feedback loop")
    args = parser.parse_args()

    # Run audit
    lucius = LuciusFox()
    lucius.execute(mode="full_audit")
    print("Lucius audit complete:", lucius.status.get("summary", ""))

    # ADR-008: Activate feedback loop if requested
    if args.feedback_loop and args.score_file:
        from rudy.agents.lucius_openspace_bridge import full_feedback_loop

        score_result = json.loads(Path(args.score_file).read_text(encoding="utf-8"))
        result = asyncio.run(full_feedback_loop(
            score_result=score_result,
            session_number=args.session,
            task_description=args.task,
        ))
        print(f"\nFeedback loop result:")
        print(f"  Severity tier: {result['severity_tier']}")
        print(f"  Action: {result['action']}")
        print(f"  Directives generated: {result['directives_count']}")
        print(f"  OpenSpace: {result['openspace'].get('status', 'unknown')}")

    elif args.feedback_loop:
        print("\nNote: --feedback-loop requires --score-file. Skipping feedback loop.")
        print("Usage: python run_lucius_audit.py --feedback-loop --score-file path/to/score.json --session N")


if __name__ == "__main__":
    main()
