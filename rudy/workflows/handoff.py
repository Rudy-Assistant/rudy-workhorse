"""
Automated Handoff Protocol — Continuity loop between Alfred sessions.

Closes the gap: Alfred → handoff file → Robin → new session → new Alfred.

Flow:
    1. Alfred drafts a handoff .md to rudy-data/handoffs/ as context grows
    2. Robin scans handoffs/ on activation from passive mode
    3. If Alfred is not active, Robin can bootstrap a new Cowork session
       using the latest handoff as the initial prompt

Usage (Alfred side — in Cowork session):
    from rudy.workflows.handoff import HandoffWriter
    writer = HandoffWriter(session_number=16)
    writer.record_accomplishment("Merged PR #29")
    writer.record_finding("bandit flagged shell=True in robin_taskqueue.py")
    writer.set_priorities(["P0: merge PR #32", "P1: Robin attention"])
    writer.write()  # Writes to rudy-data/handoffs/session-16-handoff.md

Usage (Robin side — on Oracle):
    from rudy.workflows.handoff import HandoffScanner
    scanner = HandoffScanner()
    latest = scanner.get_latest_handoff()
    if latest:
        prompt = scanner.format_bootstrap_prompt(latest)
        # Robin can use this to start a new Cowork session

CLI:
    python -m rudy.workflows.handoff --write 16   # Write handoff for session 16
    python -m rudy.workflows.handoff --latest      # Print latest handoff path
    python -m rudy.workflows.handoff --bootstrap    # Print bootstrap prompt
"""

import json
import re
from datetime import datetime
from pathlib import Path

from rudy.paths import HANDOFFS_DIR, REPO_ROOT


class HandoffWriter:
    """Alfred writes structured handoff briefs at end of session or when
    context window is getting full."""

    def __init__(self, session_number: int):
        self.session_number = session_number
        self.started_at = datetime.now()
        self.accomplishments: list[str] = []
        self.findings: list[str] = []
        self.open_prs: list[dict] = []  # {"number": int, "title": str, "status": str}
        self.merged_prs: list[int] = []
        self.next_priorities: list[str] = []
        self.hard_rules_notes: list[str] = []
        self.technical_notes: list[str] = []
        self.context_estimate: str = "unknown"

    def record_accomplishment(self, text: str):
        """Record a session accomplishment."""
        self.accomplishments.append(text)

    def record_finding(self, text: str):
        """Record a finding (per Finding Capture Protocol)."""
        self.findings.append(text)

    def record_open_pr(self, number: int, title: str, status: str = "open"):
        """Record an open PR that needs attention."""
        self.open_prs.append({"number": number, "title": title, "status": status})

    def record_merged_pr(self, number: int):
        """Record a merged PR."""
        self.merged_prs.append(number)

    def set_priorities(self, priorities: list[str]):
        """Set the priority list for the next session."""
        self.next_priorities = priorities

    def add_hard_rules_note(self, note: str):
        """Add a note about hard rules learned or reinforced."""
        self.hard_rules_notes.append(note)

    def add_technical_note(self, note: str):
        """Add a technical note for the next session."""
        self.technical_notes.append(note)

    def set_context_estimate(self, estimate: str):
        """Set context window utilization estimate (e.g. '~60% consumed')."""
        self.context_estimate = estimate

    def generate_markdown(self) -> str:
        """Generate the handoff markdown document."""
        lines = [
            f"# Session {self.session_number} Handoff Brief",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Session started:** {self.started_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Context estimate:** {self.context_estimate}",
            "",
            "---",
            "",
        ]

        # Accomplishments
        if self.accomplishments:
            lines.append("## Session Accomplishments")
            lines.append("")
            for a in self.accomplishments:
                lines.append(f"- {a}")
            lines.append("")

        # PRs
        if self.merged_prs or self.open_prs:
            lines.append("## PR Status")
            lines.append("")
            if self.merged_prs:
                lines.append(f"**Merged:** {', '.join(f'#{n}' for n in self.merged_prs)}")
            for pr in self.open_prs:
                lines.append(
                    f"**PR #{pr['number']}** ({pr['status']}): {pr['title']}"
                )
            lines.append("")

        # Findings
        if self.findings:
            lines.append("## Findings (Finding Capture Protocol)")
            lines.append("")
            for f in self.findings:
                lines.append(f"- {f}")
            lines.append("")

        # Priorities
        if self.next_priorities:
            lines.append("## Next Session Priorities")
            lines.append("")
            for p in self.next_priorities:
                lines.append(f"- {p}")
            lines.append("")

        # Hard rules
        if self.hard_rules_notes:
            lines.append("## Hard Rules Notes")
            lines.append("")
            for n in self.hard_rules_notes:
                lines.append(f"- {n}")
            lines.append("")

        # Technical notes
        if self.technical_notes:
            lines.append("## Technical Notes")
            lines.append("")
            for n in self.technical_notes:
                lines.append(f"- {n}")
            lines.append("")

        # Bootstrap instructions
        lines.extend([
            "## Bootstrap Instructions",
            "",
            "Paste this into a new Cowork session:",
            "",
            "```",
            f"You are Alfred — Chief of Staff to Batman (Chris Cimino). "
            f"Clone Rudy-Assistant/rudy-workhorse and read docs/SESSION-HANDOFF.md "
            f"for full context. This is Session {self.session_number + 1}.",
            "```",
            "",
            "---",
            f"*Generated by Alfred, Session {self.session_number}, "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])

        return "\n".join(lines)

    def write(self) -> Path:
        """Write the handoff file to HANDOFFS_DIR. Returns the file path."""
        content = self.generate_markdown()
        filename = f"session-{self.session_number:02d}-handoff.md"
        filepath = HANDOFFS_DIR / filename
        filepath.write_text(content, encoding="utf-8")

        # Also write a JSON sidecar for Robin's programmatic access
        sidecar = {
            "session_number": self.session_number,
            "generated_at": datetime.now().isoformat(),
            "context_estimate": self.context_estimate,
            "accomplishments": self.accomplishments,
            "merged_prs": self.merged_prs,
            "open_prs": self.open_prs,
            "findings": self.findings,
            "next_priorities": self.next_priorities,
            "handoff_file": str(filepath),
        }
        sidecar_path = HANDOFFS_DIR / f"session-{self.session_number:02d}-handoff.json"
        sidecar_path.write_text(
            json.dumps(sidecar, indent=2, default=str), encoding="utf-8"
        )

        return filepath


class HandoffScanner:
    """Robin scans for handoff briefs to determine if a new session is needed."""

    def __init__(self):
        self.handoffs_dir = HANDOFFS_DIR

    def get_latest_handoff(self) -> dict | None:
        """Find the most recent handoff JSON sidecar.

        Returns:
            Parsed JSON dict of the latest handoff, or None if no handoffs exist.
        """
        sidecars = sorted(
            self.handoffs_dir.glob("session-*-handoff.json"),
            reverse=True,
        )
        if not sidecars:
            return None

        try:
            return json.loads(sidecars[0].read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def get_latest_handoff_md(self) -> str | None:
        """Read the most recent handoff markdown file.

        Returns:
            Content of the latest handoff .md, or None.
        """
        md_files = sorted(
            self.handoffs_dir.glob("session-*-handoff.md"),
            reverse=True,
        )
        if not md_files:
            return None

        try:
            return md_files[0].read_text(encoding="utf-8")
        except OSError:
            return None

    def get_all_handoffs(self) -> list[dict]:
        """Get all handoff sidecars, newest first."""
        sidecars = sorted(
            self.handoffs_dir.glob("session-*-handoff.json"),
            reverse=True,
        )
        results = []
        for path in sidecars:
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return results

    def needs_new_session(self, max_age_hours: float = 24.0) -> bool:
        """Determine if a new Alfred session is needed based on handoff state.

        A new session is needed if:
            1. There are no handoffs at all (first run)
            2. The latest handoff has unfinished priorities
            3. The latest handoff is older than max_age_hours
        """
        latest = self.get_latest_handoff()
        if not latest:
            return True

        # Check age
        try:
            generated = datetime.fromisoformat(latest["generated_at"])
            age_hours = (datetime.now() - generated).total_seconds() / 3600
            if age_hours > max_age_hours:
                return True
        except (KeyError, ValueError):
            return True

        # Check if there are remaining priorities
        if latest.get("next_priorities"):
            return True

        return False

    def format_bootstrap_prompt(self, handoff: dict | None = None) -> str:
        """Format a handoff into a bootstrap prompt for a new Cowork session.

        This is what Robin would paste into a new session to spin up Alfred.
        """
        if handoff is None:
            handoff = self.get_latest_handoff()
        if handoff is None:
            return (
                "You are Alfred — Chief of Staff to Batman (Chris Cimino). "
                "Clone Rudy-Assistant/rudy-workhorse and read docs/SESSION-HANDOFF.md. "
                "No previous handoff found — start fresh."
            )

        session = handoff.get("session_number", "?")
        next_session = session + 1 if isinstance(session, int) else "next"

        parts = [
            f"# Session {next_session} — Auto-Bootstrapped by Robin",
            "",
            f"Previous session: {session}",
            f"Generated: {handoff.get('generated_at', 'unknown')}",
            "",
            "You are Alfred — Chief of Staff to Batman (Chris Cimino). "
            "Clone `Rudy-Assistant/rudy-workhorse` and read `docs/SESSION-HANDOFF.md`.",
            "",
        ]

        if handoff.get("next_priorities"):
            parts.append("## Priorities from Last Session")
            parts.append("")
            for p in handoff["next_priorities"]:
                parts.append(f"- {p}")
            parts.append("")

        if handoff.get("open_prs"):
            parts.append("## Open PRs")
            parts.append("")
            for pr in handoff["open_prs"]:
                parts.append(f"- PR #{pr['number']} ({pr['status']}): {pr['title']}")
            parts.append("")

        if handoff.get("findings"):
            parts.append("## Unresolved Findings")
            parts.append("")
            for f in handoff["findings"]:
                parts.append(f"- {f}")
            parts.append("")

        parts.append("## Standing Orders")
        parts.append('"Be productive until I return" means WORK CONTINUOUSLY.')
        parts.append("")

        return "\n".join(parts)


def _cli():
    """CLI entry point for handoff operations."""
    import sys

    if "--write" in sys.argv:
        idx = sys.argv.index("--write")
        if idx + 1 < len(sys.argv):
            session_num = int(sys.argv[idx + 1])
        else:
            print("Usage: --write <session_number>")
            sys.exit(1)

        writer = HandoffWriter(session_num)
        # Minimal handoff (Alfred populates before calling write())
        path = writer.write()
        print(f"Wrote handoff to: {path}")

    elif "--latest" in sys.argv:
        scanner = HandoffScanner()
        latest = scanner.get_latest_handoff()
        if latest:
            print(f"Latest handoff: session {latest.get('session_number')}")
            print(f"Generated: {latest.get('generated_at')}")
            print(f"Priorities: {latest.get('next_priorities')}")
            print(f"File: {latest.get('handoff_file')}")
        else:
            print("No handoffs found.")

    elif "--bootstrap" in sys.argv:
        scanner = HandoffScanner()
        prompt = scanner.format_bootstrap_prompt()
        print(prompt)

    elif "--needs-session" in sys.argv:
        scanner = HandoffScanner()
        if scanner.needs_new_session():
            print("YES: New Alfred session needed.")
            sys.exit(0)
        else:
            print("NO: No new session needed.")
            sys.exit(1)

    else:
        print("Usage:")
        print("  python -m rudy.workflows.handoff --write <session_number>")
        print("  python -m rudy.workflows.handoff --latest")
        print("  python -m rudy.workflows.handoff --bootstrap")
        print("  python -m rudy.workflows.handoff --needs-session")


if __name__ == "__main__":
    _cli()
