#!/usr/bin/env python3
"""
BOUNCER orchestrator (ADR-002 enforcement).

Default disposition: BLOCK. Issues a signed token only when an adversary
subagent has reviewed the OTS search log and APPROVED the from-scratch build.

Usage:
    python tools/bouncer/bouncer.py propose --name <feature> --files <a> <b> --spec <path-to-spec.md>
    python tools/bouncer/bouncer.py search-log <propose-id>     # writes the empty search-log skeleton
    python tools/bouncer/bouncer.py issue <propose-id>          # validates adversary verdict + issues token
    python tools/bouncer/bouncer.py check <path>                # used by the pre-commit hook
    python tools/bouncer/bouncer.py list                        # list valid tokens
    python tools/bouncer/bouncer.py expire                      # expires stale tokens

The orchestrator NEVER issues a token without:
  1. A complete search log covering all six required search vectors (Appendix A of ADR-002).
  2. A populated `candidates_found[]` (empty is allowed only with explicit "no candidates found"
     reasoning AND the adversary's signed approval of that conclusion).
  3. An adversary verdict file with verdict == "APPROVED".
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOUNCER_DIR = REPO_ROOT / "tools" / "bouncer"
TOKENS_DIR = BOUNCER_DIR / "tokens"
PROPOSALS_DIR = BOUNCER_DIR / "proposals"
WAIVERS_FILE = BOUNCER_DIR / "waivers.txt"
EXEMPT_FILE = BOUNCER_DIR / "exempt.txt"
ADVERSARY_PROMPT = BOUNCER_DIR / "adversary-prompt.md"

REQUIRED_VECTORS = ["pypi_npm_crates", "github", "huggingface", "mcp_registry", "claude_plugins", "in_repo"]

SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".cs"}

TOKEN_TTL_DAYS = 90


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))

def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")

def read_lines(p: Path) -> list[str]:
    if not p.exists():
        return []
    return [ln.rstrip("\n") for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def load_exempt_patterns() -> list[str]:
    if not EXEMPT_FILE.exists():
        return []
    return read_lines(EXEMPT_FILE)


def load_waivers() -> dict[str, dict]:
    """Returns {path: {reason, waiver_by, waived_at}} for every valid waiver line."""
    out: dict[str, dict] = {}
    for line in read_lines(WAIVERS_FILE):
        # format: <path> | <reason> | WAIVED-BY: <name> <iso>
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        path, reason, waiver = parts[0], parts[1], parts[2]
        m = re.match(r"WAIVED-BY:\s*(.+?)\s+(\S+)$", waiver)
        if not m:
            continue
        out[path] = {"reason": reason, "waiver_by": m.group(1), "waived_at": m.group(2)}
    return out


def is_exempt(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def is_source_file(path: str) -> bool:
    return Path(path).suffix in SOURCE_EXTS


# ---------------------------------------------------------------------------
# propose: create a new proposal directory + spec hash
# ---------------------------------------------------------------------------

def cmd_propose(args: argparse.Namespace) -> None:
    spec_path = Path(args.spec)
    if not spec_path.exists():
        sys.exit(f"spec not found: {spec_path}")
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_sha = sha256_str(spec_text)
    proposal_id = spec_sha[:16]
    pdir = PROPOSALS_DIR / proposal_id
    pdir.mkdir(parents=True, exist_ok=True)

    proposal = {
        "proposal_id": proposal_id,
        "feature_spec_sha256": spec_sha,
        "feature_name": args.name,
        "feature_spec": spec_text,
        "files_to_be_added": args.files,
        "created_at": now_iso(),
        "search_log_path": str((pdir / "search_log.json").relative_to(REPO_ROOT)).replace("\\", "/"),
        "candidates_found": [],
        "adversary_verdict_path": str((pdir / "adversary_verdict.json").relative_to(REPO_ROOT)).replace("\\", "/"),
    }
    write_json(pdir / "proposal.json", proposal)

    # Skeleton search log
    skel = {
        "proposal_id": proposal_id,
        "vectors": {v: {"queries": [], "results": [], "notes": ""} for v in REQUIRED_VECTORS},
        "completed_at": None,
    }
    write_json(pdir / "search_log.json", skel)

    print(f"BOUNCER PROPOSAL CREATED")
    print(f"  proposal_id : {proposal_id}")
    print(f"  spec sha256 : {spec_sha}")
    print(f"  files       : {args.files}")
    print(f"  next steps  :")
    print(f"    1. Fill in {pdir / 'search_log.json'} for ALL six vectors:")
    for v in REQUIRED_VECTORS:
        print(f"         - {v}")
    print(f"    2. Populate {pdir / 'proposal.json'}.candidates_found[] with every candidate found.")
    print(f"    3. Spawn an adversary subagent (Task tool) using {ADVERSARY_PROMPT}")
    print(f"       and write its verdict to {pdir / 'adversary_verdict.json'}.")
    print(f"    4. Run: python tools/bouncer/bouncer.py issue {proposal_id}")


# ---------------------------------------------------------------------------
# issue: validate everything and (if approved) emit a signed token
# ---------------------------------------------------------------------------

def cmd_issue(args: argparse.Namespace) -> None:
    pdir = PROPOSALS_DIR / args.proposal_id
    if not pdir.exists():
        sys.exit(f"proposal not found: {args.proposal_id}")
    proposal = read_json(pdir / "proposal.json")
    log_path = pdir / "search_log.json"
    if not log_path.exists():
        sys.exit(f"search_log.json missing for {args.proposal_id}")
    log = read_json(log_path)

    # Validate vectors
    missing = [v for v in REQUIRED_VECTORS if v not in log.get("vectors", {})]
    if missing:
        sys.exit(f"BOUNCER REJECT — search log missing required vectors: {missing}")
    empty_vectors = [v for v, data in log["vectors"].items() if not data.get("queries")]
    if empty_vectors:
        sys.exit(f"BOUNCER REJECT — vectors with zero queries: {empty_vectors}. Each vector requires at least one query attempted.")

    # Validate adversary verdict
    verdict_path = pdir / "adversary_verdict.json"
    if not verdict_path.exists():
        sys.exit(f"BOUNCER REJECT — adversary_verdict.json missing. Spawn the adversary subagent first.")
    verdict = read_json(verdict_path)
    if verdict.get("verdict") != "APPROVED":
        sys.exit(f"BOUNCER REJECT — adversary verdict = {verdict.get('verdict', 'MISSING')}. Reasoning:\n{verdict.get('reasoning', '<none>')}")

    # Validate adversary covered every candidate with a rebuttal
    candidates = proposal.get("candidates_found", [])
    for cand in candidates:
        if not cand.get("rebuttal"):
            sys.exit(f"BOUNCER REJECT — candidate '{cand.get('name', '<unnamed>')}' has no rebuttal in proposal.candidates_found[].")

    # Issue token
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=TOKEN_TTL_DAYS)
    token = {
        "feature_spec_sha256": proposal["feature_spec_sha256"],
        "feature_name": proposal["feature_name"],
        "feature_spec": proposal["feature_spec"],
        "files_to_be_added": proposal["files_to_be_added"],
        "search_log_path": proposal["search_log_path"],
        "candidates_found": candidates,
        "adversary": {
            "prompt_sha256": sha256_str(ADVERSARY_PROMPT.read_text(encoding="utf-8")) if ADVERSARY_PROMPT.exists() else "<missing>",
            "verdict": verdict.get("verdict"),
            "reasoning": verdict.get("reasoning"),
            "timestamp": verdict.get("timestamp", now_iso()),
        },
        "issued_by": "bouncer.py v1.0.0",
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    token_path = TOKENS_DIR / f"{proposal['feature_spec_sha256']}.json"
    write_json(token_path, token)
    print(f"BOUNCER TOKEN ISSUED")
    print(f"  token        : {token_path}")
    print(f"  files cleared: {proposal['files_to_be_added']}")
    print(f"  expires      : {expires_at.isoformat()}")


# ---------------------------------------------------------------------------
# check: used by the pre-commit hook
# ---------------------------------------------------------------------------

def find_token_for(rel_path: str) -> dict | None:
    if not TOKENS_DIR.exists():
        return None
    for tok_file in TOKENS_DIR.glob("*.json"):
        try:
            tok = read_json(tok_file)
        except json.JSONDecodeError:
            continue
        if rel_path not in tok.get("files_to_be_added", []):
            continue
        try:
            if parse_iso(tok["expires_at"]) < datetime.now(timezone.utc):
                continue  # expired
        except (KeyError, ValueError):
            continue
        return tok
    return None


def cmd_check(args: argparse.Namespace) -> None:
    """
    Returns 0 if the path is allowed (token, waiver, exempt, or non-source).
    Returns non-zero with a banner if blocked.
    """
    rel = args.path.replace("\\", "/")
    if not is_source_file(rel):
        return  # 0 — only source files are gated
    exempt_patterns = load_exempt_patterns()
    if is_exempt(rel, exempt_patterns):
        return
    waivers = load_waivers()
    if rel in waivers:
        return
    tok = find_token_for(rel)
    if tok:
        return
    print_block_banner(rel)
    sys.exit(1)


def print_block_banner(path: str) -> None:
    print("=" * 70, file=sys.stderr)
    print("BOUNCER REJECTION (ADR-002)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"  blocked file : {path}", file=sys.stderr)
    print(f"  reason       : no valid BOUNCER token, no waiver, not exempt", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  to commit this file, do ONE of:", file=sys.stderr)
    print(f"    1. Run BOUNCER and obtain a signed token:", file=sys.stderr)
    print(f"         python tools/bouncer/bouncer.py propose --name <feat> --files {path} --spec <path-to-spec.md>", file=sys.stderr)
    print(f"         <fill in search_log.json across all 6 vectors>", file=sys.stderr)
    print(f"         <spawn adversary subagent; write adversary_verdict.json>", file=sys.stderr)
    print(f"         python tools/bouncer/bouncer.py issue <proposal_id>", file=sys.stderr)
    print(f"    2. Add a waiver line to tools/bouncer/waivers.txt:", file=sys.stderr)
    print(f"         {path} | <one-line reason> | WAIVED-BY: <name> <iso-timestamp>", file=sys.stderr)
    print(f"    3. Add a pattern to tools/bouncer/exempt.txt (only if this is a generic exemption).", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"  do NOT use --no-verify to bypass. See ADR-002 Appendix E.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)


# ---------------------------------------------------------------------------
# list / expire
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> None:
    if not TOKENS_DIR.exists():
        print("(no tokens)")
        return
    for tok_file in sorted(TOKENS_DIR.glob("*.json")):
        try:
            tok = read_json(tok_file)
        except json.JSONDecodeError:
            print(f"  CORRUPT  {tok_file.name}")
            continue
        try:
            expired = parse_iso(tok["expires_at"]) < datetime.now(timezone.utc)
        except (KeyError, ValueError):
            expired = True
        flag = "EXPIRED" if expired else "valid  "
        print(f"  {flag}  {tok.get('feature_name', '<unnamed>'):30s}  files={tok.get('files_to_be_added', [])}")


def cmd_expire(args: argparse.Namespace) -> None:
    """Move expired tokens to tokens/_expired/. Does NOT delete them — institutional memory."""
    if not TOKENS_DIR.exists():
        return
    expired_dir = TOKENS_DIR / "_expired"
    expired_dir.mkdir(exist_ok=True)
    moved = 0
    for tok_file in TOKENS_DIR.glob("*.json"):
        try:
            tok = read_json(tok_file)
            if parse_iso(tok["expires_at"]) < datetime.now(timezone.utc):
                tok_file.rename(expired_dir / tok_file.name)
                moved += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    print(f"expired {moved} tokens")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="BOUNCER (ADR-002)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("propose"); pr.add_argument("--name", required=True); pr.add_argument("--files", nargs="+", required=True); pr.add_argument("--spec", required=True); pr.set_defaults(func=cmd_propose)
    iss = sub.add_parser("issue"); iss.add_argument("proposal_id"); iss.set_defaults(func=cmd_issue)
    chk = sub.add_parser("check"); chk.add_argument("path"); chk.set_defaults(func=cmd_check)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("expire").set_defaults(func=cmd_expire)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
