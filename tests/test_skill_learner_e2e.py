#!/usr/bin/env python3
"""End-to-end test for the Robin Skill Learner pipeline.

Session 142: Validates the full delegation-aware skill learning
pipeline (DelegationGate -> SkillLearner -> OpenSpace) by seeding
realistic multi-session delegation events that exceed the
MIN_PATTERN_COUNT=3 threshold, then exercising every stage:

    OBSERVE -> CLUSTER -> PROPOSE -> VALIDATE -> DEPLOY

The Ollama PROPOSE stage is mocked so this test runs in CI without
a live LLM. A separate live-Ollama smoke is gated behind
SKILL_LEARNER_LIVE_OLLAMA=1.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rudy import robin_skill_learner as rsl  # noqa: E402


def _make_event(category: str, op: str, session: int, age_h: int = 1) -> dict:
    return {
        "timestamp": (
            datetime.now() - timedelta(hours=age_h)
        ).isoformat(),
        "source": "delegation_gate",
        "category": category,
        "operation": op,
        "disposition": "delegate",
        "session": session,
    }


class SkillLearnerE2ETest(unittest.TestCase):
    """Exercises the full pipeline against a temp filesystem."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmp.name)
        self.openspace = tmp_path / "OpenSpace"
        self.openspace.mkdir()
        self.learner_dir = tmp_path / "skill-learner"
        self.learner_dir.mkdir()

        # Patch module-level paths to point at our temp dirs.
        self._patches = [
            mock.patch.object(rsl, "OPENSPACE_DIR", self.openspace),
            mock.patch.object(
                rsl, "SKILL_LEARNER_DIR", self.learner_dir,
            ),
            mock.patch.object(
                rsl, "DELEGATION_LOG",
                self.learner_dir / "delegation-log.json",
            ),
            mock.patch.object(
                rsl, "SKILL_PROPOSALS",
                self.learner_dir / "skill-proposals.json",
            ),
            mock.patch.object(
                rsl, "DEPLOYED_SKILLS",
                self.learner_dir / "deployed-skills.json",
            ),
            mock.patch.object(
                rsl, "LEARNER_STATE",
                self.learner_dir / "learner-state.json",
            ),
            mock.patch.object(
                rsl, "SENTINEL_LEARNING", self.learner_dir,
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    # ---------- Stage 1: OBSERVE ----------
    def test_normalize_strips_session_prefix_via_regex(self) -> None:
        """F-S141-003(a) regression."""
        self.assertEqual(rsl._normalize_operation("S142: git push"),
                         "git push")
        self.assertEqual(rsl._normalize_operation("s9: lint check"),
                         "lint check")
        self.assertEqual(
            rsl._normalize_operation("S9999: anything goes"),
            "anything goes",
        )
        # Non-session prefixes left intact.
        self.assertEqual(
            rsl._normalize_operation("git push origin main"),
            "git push origin main",
        )

    def test_text_similarity_short_strings_no_false_positive(
        self,
    ) -> None:
        """F-S141-003(d) regression."""
        # Two short strings sharing one word would have scored 0.5
        # under the old Jaccard. Now must be 0.0.
        self.assertEqual(rsl._text_similarity("git push", "git pull"),
                         0.0)
        # Long-enough strings still compute similarity normally.
        a = "deploy artifact to production environment"
        b = "deploy artifact to staging environment safely"
        self.assertGreater(rsl._text_similarity(a, b), 0.4)

    # ---------- Stage 2: CLUSTER ----------
    def test_cluster_threshold_respected(self) -> None:
        events = [
            _make_event("git", "git push origin main", 140),
            _make_event("git", "git push origin main", 141),
            _make_event("git", "git push origin main", 142),
            _make_event("file_io", "rare op", 142),  # below threshold
        ]
        patterns = rsl.cluster_delegation_patterns(events)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["category"], "git")
        self.assertEqual(patterns[0]["frequency"], 3)
        self.assertGreaterEqual(patterns[0]["sessions_seen"], 3)
        # Multi-session bonus pushes confidence above raw 3/10 = 0.3
        self.assertGreaterEqual(patterns[0]["confidence"], 0.5)

    # ---------- Stage 3 + 4 + 5 with mocked Ollama ----------
    def test_full_pipeline_with_mocked_ollama(self) -> None:
        events = [
            _make_event("git", "git push origin main", 140),
            _make_event("git", "git push origin main", 141),
            _make_event("git", "git push origin main", 142),
            _make_event("lint", "ruff check rudy/", 140),
            _make_event("lint", "ruff check rudy/", 141),
            _make_event("lint", "ruff check rudy/", 142),
        ]
        patterns = rsl.cluster_delegation_patterns(events)
        self.assertEqual(len(patterns), 2)

        fake_proposals = [
            {
                "skill_name": "auto_git_push_main",
                "description": "Push to origin/main after CI green",
                "trigger": "post_ci_success",
                "steps": [
                    "verify CI green",
                    "git push origin main",
                ],
                "success_criteria": "remote sha matches local",
                "safety": "dry-run if uncommitted changes present",
                "priority": "high",
            },
            {
                "skill_name": "auto_ruff_lint",
                "description": "Run ruff on rudy/ before commit",
                "trigger": "pre_commit",
                "steps": ["ruff check rudy/ --no-cache"],
                "success_criteria": "exit code 0",
                "safety": "read-only, never autofix without flag",
                "priority": "medium",
            },
        ]

        with mock.patch.object(
            rsl, "_generate_via_ollama", return_value=fake_proposals,
        ):
            proposals = rsl.propose_skills(patterns)

        self.assertEqual(len(proposals), 2)
        for p in proposals:
            self.assertIn("id", p)
            self.assertEqual(p["status"], "proposed")
            self.assertEqual(p["generated_by"], "skill_learner")

        # Validate
        validated = rsl.validate_proposals(proposals)
        self.assertEqual(len(validated), 2)
        for p in validated:
            self.assertEqual(p["status"], "validated")

        # Deploy
        deployed_paths = []
        for p in validated:
            path = rsl.deploy_skill_scaffold(p)
            self.assertIsNotNone(path)
            deployed_paths.append(path)
            self.assertTrue((path / "skill.json").exists())
            self.assertTrue((path / "README.md").exists())
            self.assertTrue((path / "handler.py").exists())
            cfg = json.loads((path / "skill.json").read_text())
            self.assertEqual(cfg["status"], "scaffold")
            self.assertEqual(cfg["source"], "skill_learner")

        # Deployed-skills log persisted
        log_data = json.loads(rsl.DEPLOYED_SKILLS.read_text())
        self.assertEqual(len(log_data), 2)
        names = {entry["skill_name"] for entry in log_data}
        self.assertEqual(
            names, {"auto_git_push_main", "auto_ruff_lint"},
        )

    def test_validate_rejects_missing_safety(self) -> None:
        proposals = [
            {
                "skill_name": "unsafe_skill",
                "description": "no safety field",
                "id": "SKL-X-001",
            },
        ]
        validated = rsl.validate_proposals(proposals)
        self.assertEqual(len(validated), 0)
        self.assertEqual(proposals[0]["status"], "rejected_no_safety")

    def test_run_learning_cycle_no_events(self) -> None:
        """Empty pipeline should exit cleanly."""
        with mock.patch.object(
            rsl, "DELEGATION_METRICS",
            self.learner_dir / "no-such-file.json",
        ), mock.patch.object(
            rsl, "_read_completed_delegations", return_value=[],
        ), mock.patch.object(
            rsl, "_read_delegation_log", return_value=[],
        ):
            summary = rsl.run_learning_cycle(
                session_number=142, max_runtime_secs=5.0,
            )
        self.assertEqual(summary["events_collected"], 0)
        self.assertEqual(summary["result"], "no_delegation_events")


@unittest.skipUnless(
    os.environ.get("SKILL_LEARNER_LIVE_OLLAMA") == "1",
    "Set SKILL_LEARNER_LIVE_OLLAMA=1 to run the live-Ollama smoke",
)
class SkillLearnerLiveOllamaSmoke(unittest.TestCase):
    """Optional live-Ollama smoke. Requires Ollama running locally."""

    def test_generate_via_ollama_returns_list(self) -> None:
        prompt = (
            "Return a JSON array containing exactly one object with "
            'key "skill_name" set to "smoke_test".'
        )
        result = rsl._generate_via_ollama(prompt)
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
