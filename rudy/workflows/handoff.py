"""
Automated Handoff Protocol — Continuity loop between Alfred sessions.

Closes the gap: Alfred → handoff file → Robin → new session → new Alfred.

Flow:
    1. Alfred drafts a handoff .md — written to vault/Handoffs/ (canonical),
       vault/Sessions/, vault/Briefings/Alfred-Session-Log.md, and
       rudy-data/handoffs/ (legacy) via HandoffWriter.write()
    2. Robin scans vault/Handoffs/ and rudy-data/handoffs/ on activation
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
import logging
import re

log = logging.getLogger("rudy.handoff")
from datetime import datetime
from pathlib import Path

from rudy.paths import BATCAVE_VAULT, HANDOFFS_DIR, REPO_ROOT, VAULT_HANDOFFS


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
        self.critical_context: list[str] = []  # "what's actually broken and why"
        self.unresolved_findings: list[dict] = []  # from lucius-findings.json
        self.architecture_refs: list[str] = []  # ADR/doc references for design work
        self.context_estimate: str = "unknown"
        self.compliance_score: int = 100
        self.score_report: dict | None = None  # from lucius_scorer
        self.gate_result = None
        self.session_evidence: dict = {}  # for scorer
        self.registry_stats: dict | None = None  # from registry.json

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

    def add_critical_context(self, text: str):
        """Add a 'what's broken and why it matters' note for the next session."""
        self.critical_context.append(text)

    def add_architecture_ref(self, doc_path: str):
        """Reference an ADR or architecture doc relevant to the work."""
        self.architecture_refs.append(doc_path)

    def set_session_evidence(self, evidence: dict):
        """Set evidence dict for the Lucius scorer."""
        self.session_evidence = evidence

    def load_open_findings(self):
        """Auto-load unresolved findings from lucius-findings.json (C3 isolated)."""
        try:
            from rudy.paths import RUDY_DATA
            findings_path = RUDY_DATA / "lucius-findings.json"
            if findings_path.exists():
                data = json.loads(findings_path.read_text(encoding="utf-8"))
                findings_list = data if isinstance(data, list) else data.get("findings", [])
                self.unresolved_findings = [
                    f for f in findings_list
                    if f.get("status", "open") != "resolved"
                ]
                log.info(f"Loaded {len(self.unresolved_findings)} open findings")
        except Exception as e:
            log.warning(f"Could not load findings: {e}")

    def load_registry_stats(self):
        """Auto-load registry stats from registry.json (C3 isolated)."""
        try:
            registry_path = REPO_ROOT / "registry.json"
            if registry_path.exists():
                data = json.loads(registry_path.read_text(encoding="utf-8"))
                self.registry_stats = data.get("stats", {})
                log.info(f"Loaded registry stats: {self.registry_stats}")
        except Exception as e:
            log.warning(f"Could not load registry stats: {e}")

    def _run_scorer(self):
        """Run Lucius scorer on session evidence (C3 isolated).

        Call this before write() if you have evidence to score.
        """
        if not self.session_evidence:
            return
        try:
            from rudy.agents.lucius_scorer import score_session
            self.score_report = score_session(self.session_evidence)
            self.compliance_score = int(self.score_report.get("total_score", 0))
            log.info(f"Session scored: {self.score_report.get('summary', '?')}")
        except ImportError as e:
            log.warning(f"lucius_scorer import failed: {e}")
        except Exception as e:
            log.error(f"Scorer crashed: {e}")

    def generate_markdown(self) -> str:
        """Generate the handoff markdown document.

        Batman-quality format: Critical Context first, then accomplishments,
        explicit P0/P1/P2 priorities with enough context to act, architecture
        refs, unresolved findings with IDs, scorer report, standing orders.
        """
        lines = [
            f"# Session {self.session_number} Handoff Brief",
            "",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Session started:** {self.started_at.strftime('%Y-%m-%d %H:%M')}",
            f"**Context estimate:** {self.context_estimate}",
        ]

        # Compliance score summary
        if self.score_report:
            sr = self.score_report
            lines.append(
                f"**Compliance:** {sr['total_score']}/100 ({sr['grade']})"
            )
            weak = [
                name for name, d in sr.get("dimensions", {}).items()
                if d.get("pct", 100) < 50
            ]
            if weak:
                lines.append(f"**Weak areas:** {', '.join(weak)}")
        elif self.compliance_score is not None:
            lines.append(f"**Compliance:** {self.compliance_score}/100")

        lines.extend(["", "---", ""])

        # Critical Context — "what's actually broken and why it matters"
        if self.critical_context:
            lines.append("## Critical Context")
            lines.append("")
            for ctx in self.critical_context:
                lines.append(f"- {ctx}")
            lines.append("")

        # Accomplishments
        if self.accomplishments:
            lines.append("## What This Session Accomplished")
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

        # Priorities — explicit P0/P1/P2
        if self.next_priorities:
            lines.append("## Priorities for Next Session")
            lines.append("")
            for p in self.next_priorities:
                lines.append(f"- {p}")
            lines.append("")

        # Architecture references
        if self.architecture_refs:
            lines.append("## Architecture Documents (read if doing design work)")
            lines.append("")
            for ref in self.architecture_refs:
                lines.append(f"- `{ref}`")
            lines.append("")

        # Unresolved findings from tracker
        if self.unresolved_findings:
            lines.append("## Unresolved Findings (from Lucius Tracker)")
            lines.append("")
            for finding in self.unresolved_findings:
                fid = finding.get("id", "?")
                severity = finding.get("severity", "?").upper()
                desc = finding.get("description", finding.get("text", "?"))
                lines.append(f"- **{fid}** [{severity}] {desc}")
            lines.append("")
        elif self.findings:
            lines.append("## Findings (Finding Capture Protocol)")
            lines.append("")
            for f in self.findings:
                lines.append(f"- {f}")
            lines.append("")

        # Registry stats
        if self.registry_stats:
            rs = self.registry_stats
            lines.append("## Registry Snapshot")
            lines.append("")
            lines.append(
                f"**{rs.get('total_lines', '?')} lines** across "
                f"modules | {rs.get('total_agents', '?')} agents | "
                f"{rs.get('total_skills', '?')} skills | "
                f"{rs.get('total_mcps', '?')} MCPs"
            )
            lines.append("")

        # Hard rules notes
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

        # Scorer detailed report
        if self.score_report:
            lines.append("## Session Compliance Score")
            lines.append("")
            lines.append(
                f"**{self.score_report['total_score']}/100 "
                f"({self.score_report['grade']})**"
            )
            lines.append("")
            lines.append("| Dimension | Score | Notes |")
            lines.append("|-----------|-------|-------|")
            for dim, data in self.score_report.get("dimensions", {}).items():
                notes_str = "; ".join(data.get("notes", [])[:2])
                lines.append(
                    f"| {dim} | {data['score']}/{data['max']} | {notes_str} |"
                )
            lines.append("")

        # Standing orders reminder
        lines.extend([
            "## Standing Orders",
            "",
            '"Be productive until I return" means WORK CONTINUOUSLY. '
            "Every response with tool use ends with "
            "`[Context: ~X% | Session N | status]`. "
            "Read CLAUDE.md for full system state.",
            "",
        ])

        # Bootstrap instructions
        lines.extend([
            "## Bootstrap Instructions",
            "",
            "Paste this into a new Cowork session:",
            "",
            "```",
            f"You are Alfred — Chief of Staff to Batman (Chris Cimino). "
            f"Clone `Rudy-Assistant/rudy-workhorse` and **read `CLAUDE.md` first** "
            f"(HARD RULE — Session 22), then `docs/SESSION-HANDOFF.md`. "
            f"Read `docs/MISSION.md`. CLAUDE.md is a compact hot cache (~150 lines); "
            f"deep context lives in `memory/`. This is Session {self.session_number + 1}.",
            "```",
            "",
            "---",
            f"*Generated by Alfred, Session {self.session_number}, "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        ])

        return "\n".join(lines)

    def generate_vault_session_record(self) -> str:
        """Generate a session record formatted for BatcaveVault/Sessions/.

        This is the institutional memory — structured for Obsidian, linked to
        other vault pages. Different from the handoff markdown which is
        Robin-oriented with bootstrap instructions.
        """
        lines = [
            f"# Session {self.session_number} — "
            f"{self.started_at.strftime('%Y-%m-%d')}",
            "",
            f"**Alfred via Cowork** | Context consumed: {self.context_estimate}",
            "",
            "---",
            "",
        ]

        # Summary
        if self.accomplishments:
            lines.append("## Accomplishments")
            lines.append("")
            for a in self.accomplishments:
                lines.append(f"- {a}")
            lines.append("")

        # PRs
        if self.merged_prs or self.open_prs:
            lines.append("## PR Status")
            lines.append("")
            if self.merged_prs:
                lines.append(
                    f"**Merged:** {', '.join(f'#{n}' for n in self.merged_prs)}"
                )
            for pr in self.open_prs:
                lines.append(
                    f"**PR #{pr['number']}** ({pr['status']}): {pr['title']}"
                )
            lines.append("")

        # Findings
        if self.findings:
            lines.append("## Tracked Findings")
            lines.append("")
            for i, f in enumerate(self.findings, 1):
                lines.append(f"{i}. {f}")
            lines.append("")

        # Priorities
        if self.next_priorities:
            lines.append("## Next Session Priorities")
            lines.append("")
            for i, p in enumerate(self.next_priorities, 1):
                lines.append(f"{i}. {p}")
            lines.append("")

        lines.extend([
            "---",
            f"*Alfred, Session {self.session_number}, "
            f"{datetime.now().strftime('%Y-%m-%d')}*",
        ])

        return "\n".join(lines)

    def generate_session_log_entry(self) -> str:
        """Generate a concise entry for vault/Briefings/Alfred-Session-Log.md."""
        lines = [
            "",
            "---",
            "",
            f"## Session {self.session_number} — "
            f"{self.started_at.strftime('%Y-%m-%d')} (Alfred via Cowork)",
            "",
            f"**Context:** {self.context_estimate}",
            "",
            "### Accomplished",
        ]
        for a in self.accomplishments:
            lines.append(f"- {a}")
        if self.findings:
            lines.append("")
            lines.append("### Tracked Findings")
            for f in self.findings:
                lines.append(f"- {f}")
        return "\n".join(lines)

    def _run_post_session_gate(self) -> None:
        """Run post-session gate and set compliance_score.

        ADR-004 v2.1 Phase 1B: Gate integration into handoff workflow.
        Import is inside function body per C3 import isolation.
        """
        try:
            from rudy.agents.lucius_gate import post_session_gate
        except ImportError as e:
            log.warning(f"lucius_gate import failed; skipping post-session gate: {e}")
            self.compliance_score = 0
            self.gate_result = None
            return

        # Parse context estimate to float
        context_pct = None
        if self.context_estimate and self.context_estimate != "unknown":
            try:
                match = re.search(r"(\d+(?:\.\d+)?)", self.context_estimate)
                if match:
                    context_pct = float(match.group(1))
            except (ValueError, AttributeError):
                pass

        try:
            result = post_session_gate(
                session_number=self.session_number,
                context_window_pct=context_pct,
            )
            self.gate_result = result
            if result.passed and not result.degraded:
                self.compliance_score = 100
                log.info(f"Post-session gate PASSED: {result.summary()}")
            elif result.degraded:
                self.compliance_score = 0
                log.warning(f"Post-session gate DEGRADED: {result.summary()}")
            else:
                self.compliance_score = 0
                log.error(f"Post-session gate BLOCKED: {result.summary()}")
        except Exception as e:
            log.error(f"Post-session gate crashed: {e}. Setting compliance_score=0.")
            self.compliance_score = 0
            self.gate_result = None

    def write(self) -> Path:
        """Write handoff to all destinations — rudy-data, vault/Handoffs, vault/Sessions.

        Writes to five locations (four in vault):
            1. rudy-data/handoffs/session-NN-handoff.md — legacy Robin handoff brief
            2. rudy-data/handoffs/session-NN-handoff.json — legacy JSON sidecar
            3. vault/Handoffs/Session-NN-Handoff.md — CANONICAL handoff in Obsidian
            4. vault/Handoffs/Session-NN-Handoff.json — CANONICAL JSON sidecar
            5. vault/Sessions/Session-NN.md — session record for institutional memory
            6. vault/Briefings/Alfred-Session-Log.md — appended session log entry

        Returns the vault handoff file path (canonical), falling back to
        rudy-data path if vault is unavailable.
        """
        if self.context_estimate == "unknown":
            raise ValueError(
                "Context window estimate is required. Call set_context_estimate() "
                "before write(). This is a HARD REQUIREMENT — Robin uses it to "
                "decide whether to start a new session."
            )


        # Auto-load enrichment data (C3 isolated — failures are non-fatal)
        self.load_open_findings()
        self.load_registry_stats()

        # Phase 1B: Run post-session gate
        self._run_post_session_gate()

        # Phase 3: Run scorer if evidence is available
        self._run_scorer()

        content = self.generate_markdown()
        filename_md = f"session-{self.session_number:02d}-handoff.md"
        filename_json = f"session-{self.session_number:02d}-handoff.json"
        vault_filename_md = f"Session-{self.session_number}-Handoff.md"
        vault_filename_json = f"Session-{self.session_number}-Handoff.json"

        # 1. Legacy: rudy-data/handoffs/
        filepath = HANDOFFS_DIR / filename_md
        filepath.write_text(content, encoding="utf-8")

        # JSON sidecar for Robin's programmatic access
        sidecar = {
            "session_number": self.session_number,
            "generated_at": datetime.now().isoformat(),
            "context_estimate": self.context_estimate,
            "accomplishments": self.accomplishments,
            "merged_prs": self.merged_prs,
            "open_prs": self.open_prs,
            "findings": self.findings,
            "next_priorities": self.next_priorities,
            "critical_context": self.critical_context,
            "unresolved_findings_count": len(self.unresolved_findings),
            "architecture_refs": self.architecture_refs,
            "handoff_file": str(filepath),
            "compliance_score": self.compliance_score,
            "score_report": self.score_report,
            "registry_stats": self.registry_stats,
            "gate_result": self.gate_result.to_dict() if self.gate_result else None,
        }
        sidecar_json = json.dumps(sidecar, indent=2, default=str)
        sidecar_path = HANDOFFS_DIR / filename_json
        sidecar_path.write_text(sidecar_json, encoding="utf-8")

        # 2. CANONICAL: vault/Handoffs/ (the most-used folder in Obsidian)
        canonical_path = filepath  # fallback if vault unavailable
        if VAULT_HANDOFFS.exists():
            vault_handoff_md = VAULT_HANDOFFS / vault_filename_md
            vault_handoff_md.write_text(content, encoding="utf-8")
            vault_handoff_json = VAULT_HANDOFFS / vault_filename_json
            # Update sidecar to point to vault path
            sidecar["handoff_file"] = str(vault_handoff_md)
            vault_handoff_json.write_text(
                json.dumps(sidecar, indent=2, default=str), encoding="utf-8"
            )
            canonical_path = vault_handoff_md

        # 3. vault/Sessions/ — institutional memory record
        vault_sessions = BATCAVE_VAULT / "Sessions"
        if vault_sessions.exists():
            vault_record = self.generate_vault_session_record()
            vault_path = vault_sessions / f"Session-{self.session_number}.md"
            vault_path.write_text(vault_record, encoding="utf-8")

        # 4. vault/Briefings/Alfred-Session-Log.md — running log
        session_log = BATCAVE_VAULT / "Briefings" / "Alfred-Session-Log.md"
        if session_log.exists():
            entry = self.generate_session_log_entry()
            with open(session_log, "a", encoding="utf-8") as f:
                f.write(entry + "\n")

        return canonical_path


class HandoffScanner:
    """Robin scans for handoff briefs to determine if a new session is needed.

    Checks vault/Handoffs/ first (canonical), then rudy-data/handoffs/ (legacy).
    """

    def __init__(self):
        self.vault_handoffs = VAULT_HANDOFFS
        self.legacy_handoffs = HANDOFFS_DIR

    def _find_json_sidecars(self) -> list[Path]:
        """Find all JSON sidecars across both locations, newest first."""
        sidecars = []
        # Vault (canonical) — uses PascalCase naming
        if self.vault_handoffs.exists():
            sidecars.extend(self.vault_handoffs.glob("Session-*-Handoff.json"))
        # Legacy — uses lowercase naming
        sidecars.extend(self.legacy_handoffs.glob("session-*-handoff.json"))
        # Sort by modification time, newest first
        return sorted(sidecars, key=lambda p: p.stat().st_mtime, reverse=True)

    def _find_md_files(self) -> list[Path]:
        """Find all handoff markdown files across both locations, newest first."""
        md_files = []
        if self.vault_handoffs.exists():
            md_files.extend(self.vault_handoffs.glob("Session-*-Handoff.md"))
        md_files.extend(self.legacy_handoffs.glob("session-*-handoff.md"))
        return sorted(md_files, key=lambda p: p.stat().st_mtime, reverse=True)

    def get_latest_handoff(self) -> dict | None:
        """Find the most recent handoff JSON sidecar.

        Returns:
            Parsed JSON dict of the latest handoff, or None if no handoffs exist.
        """
        sidecars = self._find_json_sidecars()
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
        md_files = self._find_md_files()
        if not md_files:
            return None

        try:
            return md_files[0].read_text(encoding="utf-8")
        except OSError:
            return None

    def get_all_handoffs(self) -> list[dict]:
        """Get all handoff sidecars, newest first."""
        sidecars = self._find_json_sidecars()
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
                "Clone Rudy-Assistant/rudy-workhorse and read CLAUDE.md first "
                "(HARD RULE), then docs/SESSION-HANDOFF.md. Read docs/MISSION.md. "
                "CLAUDE.md is a compact hot cache; deep context in memory/. "
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
            "Clone `Rudy-Assistant/rudy-workhorse` and **read `CLAUDE.md` first** "
            "(HARD RULE — Session 22), then `docs/SESSION-HANDOFF.md`. "
            "Read `docs/MISSION.md`. CLAUDE.md is a compact hot cache (~150 lines); "
            "deep context lives in `memory/` directory.",
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
