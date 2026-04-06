"""Tests for credential_vault and preflight (S200).

S199 shipped these as load-bearing discipline-layer modules but only
ran AST-syntax + a manual round-trip log. S200 adds proper unittest
coverage.

All tests use tempdir-isolated state via monkeypatching of
module-level Path constants -- they NEVER touch the real
``rudy-data/vault/credentials.dat`` or
``rudy-data/preflight/*.jsonl``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rudy import credential_vault as cv  # noqa: E402
from rudy import preflight as pf  # noqa: E402


class CredentialVaultTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig_vault_dir = cv.VAULT_DIR
        self._orig_vault_file = cv.VAULT_FILE
        self._orig_legacy = cv.LEGACY_FILE
        cv.VAULT_DIR = tmp / "vault"
        cv.VAULT_FILE = cv.VAULT_DIR / "credentials.dat"
        cv.LEGACY_FILE = tmp / "robin-secrets.json"

    def tearDown(self):
        cv.VAULT_DIR = self._orig_vault_dir
        cv.VAULT_FILE = self._orig_vault_file
        cv.LEGACY_FILE = self._orig_legacy
        self._tmp.cleanup()

    def test_set_get_roundtrip(self):
        cv.set_secret("api_key", "s3cr3t-value")
        self.assertEqual(cv.get_secret("api_key"), "s3cr3t-value")

    def test_get_missing_returns_default(self):
        self.assertIsNone(cv.get_secret("nope"))
        self.assertEqual(cv.get_secret("nope", default="x"), "x")

    def test_list_and_delete(self):
        cv.set_secret("a", "1")
        cv.set_secret("b", "2")
        self.assertIn("a", cv.list_secrets())
        self.assertIn("b", cv.list_secrets())
        self.assertTrue(cv.delete_secret("a"))
        self.assertNotIn("a", cv.list_secrets())
        self.assertFalse(cv.delete_secret("a"))  # idempotent

    def test_status_warns_on_legacy_present(self):
        cv.LEGACY_FILE.write_text(json.dumps({"x": "y"}), encoding="utf-8")
        st = cv.status()
        self.assertTrue(any("legacy" in w.lower() for w in st["warnings"]))

    def test_legacy_fallback_read(self):
        cv.LEGACY_FILE.write_text(
            json.dumps({"only_in_legacy": "fromfile"}), encoding="utf-8")
        self.assertEqual(cv.get_secret("only_in_legacy"), "fromfile")

    def test_migrate_from_legacy(self):
        cv.LEGACY_FILE.write_text(
            json.dumps({"k1": "v1", "k2": "v2"}), encoding="utf-8")
        r = cv.migrate_from_legacy()
        self.assertEqual(sorted(r["migrated"]), ["k1", "k2"])
        self.assertEqual(cv.get_secret("k1"), "v1")
        self.assertEqual(cv.get_secret("k2"), "v2")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig_dir = pf.PREFLIGHT_DIR
        self._orig_ctx = pf.CONTEXT_LOG
        self._orig_blk = pf.BLOCKER_LOG
        pf.PREFLIGHT_DIR = tmp
        pf.CONTEXT_LOG = tmp / "context-log.jsonl"
        pf.BLOCKER_LOG = tmp / "blocker-claims.jsonl"

    def tearDown(self):
        pf.PREFLIGHT_DIR = self._orig_dir
        pf.CONTEXT_LOG = self._orig_ctx
        pf.BLOCKER_LOG = self._orig_blk
        self._tmp.cleanup()

    def test_report_context_writes_log(self):
        pf.report_context(42, note="t")
        lines = pf.CONTEXT_LOG.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["context_pct"], 42)

    def test_assert_session_start_writes_and_returns(self):
        out = pf.assert_session_start(200, 18)
        self.assertTrue(pf.CONTEXT_LOG.exists())
        self.assertIn("session", out)

    def test_claim_blocked_empty_searched_raises(self):
        with self.assertRaises(pf.BlockerClaimWithoutGrepError):
            pf.claim_blocked(reason="x", verbs=["elevate"], searched=[])

    def test_claim_blocked_uncovered_verb_raises(self):
        with self.assertRaises(pf.BlockerClaimWithoutGrepError):
            pf.claim_blocked(
                reason="x",
                verbs=["elevate", "runas"],
                searched=[("ToolSearch", "elevate")],
            )

    def test_claim_blocked_valid_writes_log(self):
        pf.claim_blocked(
            reason="x",
            verbs=["elevate", "runas"],
            searched=[("ToolSearch", "elevate runas uac")],
        )
        self.assertTrue(pf.BLOCKER_LOG.exists())
        lines = pf.BLOCKER_LOG.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
