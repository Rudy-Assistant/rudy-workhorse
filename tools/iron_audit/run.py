#!/usr/bin/env python3
"""
IRON-AUDIT orchestrator (ADR-001 enforcement).

Refuses to print `AUDIT COMPLETE: <sha256>` unless every phase gate passes.
This file is the binding spec; vault/protocols/IRON-AUDIT.md is advisory.

Usage:
    python tools/iron_audit/run.py init <audit_id> --scope <path>...
    python tools/iron_audit/run.py phase <n> [--audit <id>]
    python tools/iron_audit/run.py status [--audit <id>]
    python tools/iron_audit/run.py finalize [--audit <id>]

Phases:
    0  charter (manual; gate: charter.ratified.txt with RATIFIED-BY: line)
    1  inventory (auto)
    2  surface (auto, AST-based)
    3  imports (auto, AST-based)
    4  capabilities (semi-auto: requires charter.capabilities[]; greps with ≥6 synonyms)
    5  adversaries (manual: emits Task prompts for 3 fresh-context subagents)
    6  reconcile (auto, given adversary_*.json present)
    7  verifier (manual: emits Task prompt for verifier subagent)
    8  completeness_check (auto, asserts every artifact and gate)
    9  ratify (manual; gate: report.ratified.txt with RATIFIED-BY: line)

Gate philosophy: every phase has a programmatic precondition the orchestrator
checks BEFORE executing, and a programmatic postcondition the orchestrator
checks AFTER. Failure of either aborts with non-zero exit and a gate-name
in the error. Conversation cannot bypass this — only files on disk advance
the state machine.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AUDITS_ROOT = REPO_ROOT / "vault" / "Audits"
FAILURES_FILE = AUDITS_ROOT / "_failures.json"
DISCIPLINE_DOC = REPO_ROOT / "vault" / "AUDIT-DISCIPLINE.md"
ADR_DOC = REPO_ROOT / "vault" / "protocols" / "IRON-AUDIT.md"

# Default exclusions for the inventory walk.
DEFAULT_EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache"}

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".cs"}


# ---------------------------------------------------------------------------
# Failure modes (raised when a gate fails)
# ---------------------------------------------------------------------------

class GateFailure(RuntimeError):
    def __init__(self, gate: str, detail: str):
        super().__init__(f"GATE FAIL [{gate}]: {detail}")
        self.gate = gate
        self.detail = detail


# ---------------------------------------------------------------------------
# Audit context
# ---------------------------------------------------------------------------

class AuditCtx:
    def __init__(self, audit_id: str):
        self.audit_id = audit_id
        self.dir = AUDITS_ROOT / audit_id
        self.charter = self.dir / "charter.md"
        self.charter_ratified = self.dir / "charter.ratified.txt"
        self.manifest = self.dir / "manifest.json"
        self.surface = self.dir / "surface.json"
        self.imports = self.dir / "imports.json"
        self.capabilities_dir = self.dir / "capabilities"
        self.adversary_a = self.dir / "adversary_a.json"
        self.adversary_b = self.dir / "adversary_b.json"
        self.adversary_c = self.dir / "adversary_c.json"
        self.dispositions = self.dir / "dispositions.csv"
        self.verifier = self.dir / "verifier.json"
        self.completeness = self.dir / "completeness.json"
        self.report = self.dir / "report.md"
        self.report_ratified = self.dir / "report.ratified.txt"

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.capabilities_dir.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_of_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))

def write_json(p: Path, obj: Any) -> None:
    p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def load_charter(ctx: AuditCtx) -> dict:
    """Parse charter.md frontmatter-ish; the charter is YAML-fenced JSON for simplicity."""
    if not ctx.charter.exists():
        raise GateFailure("charter.exists", f"{ctx.charter} missing")
    text = ctx.charter.read_text(encoding="utf-8")
    # Look for a fenced ```json block; everything else is prose.
    m = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
    if not m:
        raise GateFailure("charter.parse", "charter.md must contain a ```json ... ``` fenced block with the machine-readable charter")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise GateFailure("charter.parse", f"charter JSON block invalid: {e}")


def assert_ratified(p: Path, gate: str) -> str:
    if not p.exists():
        raise GateFailure(gate, f"{p} missing — file required with line 'RATIFIED-BY: <name> <iso>'")
    text = p.read_text(encoding="utf-8")
    m = re.search(r"^RATIFIED-BY:\s*(.+)$", text, re.MULTILINE)
    if not m:
        raise GateFailure(gate, f"{p} present but missing 'RATIFIED-BY: <name> <iso>' line")
    return m.group(1).strip()


# ---------------------------------------------------------------------------
# Phase 0: charter ratification
# ---------------------------------------------------------------------------

def phase_0(ctx: AuditCtx) -> None:
    print(f"[phase 0] charter ratification: {ctx.charter}")
    if not ctx.charter.exists():
        # Drop the template
        template = REPO_ROOT / "tools" / "iron_audit" / "templates" / "charter.template.md"
        if template.exists():
            ctx.charter.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  -> dropped charter template at {ctx.charter}; edit + ratify, then re-run phase 0")
        else:
            print(f"  !! template missing; create {ctx.charter} manually with a ```json``` block including: scope[], exclusions[], success_criteria, methodology, adversary_plan, capabilities[], time_budget, token_budget")
        raise GateFailure("charter.exists", "charter not yet authored")
    charter = load_charter(ctx)
    required = ["scope", "exclusions", "success_criteria", "methodology", "adversary_plan", "capabilities", "time_budget", "token_budget"]
    missing = [k for k in required if k not in charter]
    if missing:
        raise GateFailure("charter.fields", f"charter missing required fields: {missing}")
    if not isinstance(charter["capabilities"], list) or not charter["capabilities"]:
        raise GateFailure("charter.capabilities", "charter.capabilities must be a non-empty list of named user-stated capabilities")
    ratifier = assert_ratified(ctx.charter_ratified, "charter.ratified")
    print(f"  ok — charter ratified by {ratifier}")
    print(f"  capabilities to search in phase 4: {len(charter['capabilities'])}")


# ---------------------------------------------------------------------------
# Phase 1: inventory
# ---------------------------------------------------------------------------

def detect_language(path: Path) -> str:
    return path.suffix.lstrip(".") or "none"

def role_guess(path: Path) -> str:
    name = path.name.lower()
    if "test" in name: return "test"
    if name.startswith("__init__"): return "package"
    if name.endswith(".md"): return "doc"
    if name.endswith((".json", ".yaml", ".yml", ".toml", ".ini")): return "config"
    if path.suffix in CODE_EXTENSIONS: return "code"
    return "other"

def walk_scope(scope: list[str], exclusions: list[str]) -> list[Path]:
    excluded = set(DEFAULT_EXCLUDE_DIRS) | set(exclusions)
    out: list[Path] = []
    for s in scope:
        root = (REPO_ROOT / s).resolve()
        if not root.exists():
            continue
        if root.is_file():
            out.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in excluded]
            for f in filenames:
                p = Path(dirpath) / f
                out.append(p)
    return sorted(set(out))

def phase_1(ctx: AuditCtx) -> None:
    print(f"[phase 1] inventory")
    charter = load_charter(ctx)
    files = walk_scope(charter["scope"], charter.get("exclusions", []))
    manifest = []
    for p in files:
        try:
            stat = p.stat()
            manifest.append({
                "path": str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
                "size": stat.st_size,
                "sha256": sha256_of(p),
                "language": detect_language(p),
                "role_guess": role_guess(p),
            })
        except OSError as e:
            raise GateFailure("inventory.read", f"could not read {p}: {e}")
    write_json(ctx.manifest, manifest)
    # Set-equality gate: re-walk and assert
    fs_set = {str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in walk_scope(charter["scope"], charter.get("exclusions", []))}
    manifest_set = {m["path"] for m in manifest}
    if fs_set != manifest_set:
        raise GateFailure("inventory.completeness", f"manifest set != filesystem set; diff={fs_set ^ manifest_set}")
    print(f"  ok — {len(manifest)} files inventoried; set-equality verified")


# ---------------------------------------------------------------------------
# Phase 2: surface
# ---------------------------------------------------------------------------

ANTI_PATTERN_MARKERS = {
    "subprocess": re.compile(r"\bimport\s+subprocess\b|from\s+subprocess\s+import"),
    "eval": re.compile(r"\beval\s*\("),
    "exec": re.compile(r"\bexec\s*\("),
    "shell_true": re.compile(r"shell\s*=\s*True"),
    "pickle_loads": re.compile(r"pickle\.loads"),
}

def surface_for_python(text: str) -> dict:
    out: dict = {"defs": [], "classes": [], "exports": []}
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return {"parse_error": True, "parse_error_msg": str(e)}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            out["defs"].append(node.name)
        elif isinstance(node, ast.ClassDef):
            out["classes"].append(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                out["exports"].append(elt.value)
    return out

def surface_for_generic(text: str) -> dict:
    return {
        "defs": re.findall(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", text, re.MULTILINE),
        "classes": re.findall(r"^(?:export\s+)?class\s+(\w+)", text, re.MULTILINE),
        "exports": re.findall(r"^export\s+(?:const|let|var|function|class)\s+(\w+)", text, re.MULTILINE),
    }

def phase_2(ctx: AuditCtx) -> None:
    print(f"[phase 2] surface map")
    if not ctx.manifest.exists():
        raise GateFailure("phase2.precondition", "manifest.json missing; run phase 1")
    manifest = read_json(ctx.manifest)
    surface = []
    parse_errors = 0
    for m in manifest:
        if m["role_guess"] != "code":
            continue
        p = REPO_ROOT / m["path"]
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise GateFailure("phase2.read", f"could not read {p}: {e}")
        first30 = "\n".join(text.splitlines()[:30])
        if m["language"] == "py":
            sig = surface_for_python(text)
        else:
            sig = surface_for_generic(text)
        flags = [name for name, rx in ANTI_PATTERN_MARKERS.items() if rx.search(text)]
        entry = {
            "path": m["path"],
            "first_30_lines": first30,
            "signatures": sig,
            "anti_patterns": flags,
        }
        if sig.get("parse_error"):
            parse_errors += 1
        surface.append(entry)
    write_json(ctx.surface, surface)
    # Gate: every code file in manifest is in surface
    code_paths = {m["path"] for m in manifest if m["role_guess"] == "code"}
    surface_paths = {s["path"] for s in surface}
    if code_paths != surface_paths:
        raise GateFailure("surface.coverage", f"surface missing code files: {code_paths - surface_paths}")
    # Gate: zero unwaivered parse failures (we don't yet support waivers; just count)
    if parse_errors:
        print(f"  WARN — {parse_errors} parse failures (waiver mechanism TBD; for now, listed in surface.json)")
    print(f"  ok — {len(surface)} surface entries; {parse_errors} parse_error flags")


# ---------------------------------------------------------------------------
# Phase 3: imports
# ---------------------------------------------------------------------------

def imports_for_python(text: str) -> list[str]:
    out: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.append(node.module.split(".")[0])
    return sorted(set(out))

def phase_3(ctx: AuditCtx) -> None:
    print(f"[phase 3] import graph")
    if not ctx.manifest.exists():
        raise GateFailure("phase3.precondition", "manifest.json missing")
    manifest = read_json(ctx.manifest)
    nodes: dict[str, dict] = {}
    for m in manifest:
        if m["role_guess"] != "code":
            continue
        nodes[m["path"]] = {"inbound_count": 0, "outbound_count": 0, "inbound_edges": [], "outbound_edges": []}
    # Outbound (only resolves intra-repo by basename matching for now)
    by_modname: dict[str, str] = {}
    for path in nodes:
        modname = Path(path).stem
        by_modname.setdefault(modname, path)
    for path in nodes:
        if not path.endswith(".py"):
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        outs = imports_for_python(text)
        intra = [by_modname[o] for o in outs if o in by_modname and by_modname[o] != path]
        nodes[path]["outbound_edges"] = intra
        nodes[path]["outbound_count"] = len(intra)
        for tgt in intra:
            nodes[tgt]["inbound_edges"].append(path)
            nodes[tgt]["inbound_count"] += 1
    write_json(ctx.imports, nodes)
    # Gate: every code file is a node
    code_paths = {m["path"] for m in manifest if m["role_guess"] == "code"}
    if set(nodes.keys()) != code_paths:
        raise GateFailure("imports.coverage", f"imports.json missing code files: {code_paths - set(nodes.keys())}")
    print(f"  ok — {len(nodes)} nodes; {sum(n['outbound_count'] for n in nodes.values())} intra-repo edges")


# ---------------------------------------------------------------------------
# Phase 4: capability semantic search (≥6 synonyms required)
# ---------------------------------------------------------------------------

# Default synonyms keyed off common capability words. Auto-augmented from _failures.json on every run.
DEFAULT_SYNONYM_TABLE: dict[str, list[str]] = {
    "delegate":     ["delegate", "delegation", "route", "dispatch", "gate", "enforce", "intercept", "classify", "should_use", "force"],
    "skill":        ["skill", "capability", "tool", "ability", "competence", "inject_skill", "skill_aware", "skill_assess"],
    "ots":          ["ots", "off-the-shelf", "vendor", "library", "package", "dependency", "third-party"],
    "memory":       ["memory", "persist", "state", "checkpoint", "snapshot", "remember"],
    "credentials":  ["credential", "secret", "vault", "keyring", "token", "auth", "login"],
    "subagent":     ["subagent", "task", "spawn", "fresh-context", "isolated"],
    "audit":        ["audit", "review", "inspect", "verify", "validate", "evaluate"],
}

def synonyms_for(capability: str) -> list[str]:
    cap = capability.lower()
    out: list[str] = []
    seen: set[str] = set()
    # 1) The capability's own tokens
    for token in re.split(r"[\s_\-/.]+", cap):
        if token and token not in seen:
            out.append(token); seen.add(token)
    # 2) Default table matches
    for key, vals in DEFAULT_SYNONYM_TABLE.items():
        if key in cap:
            for v in vals:
                if v not in seen:
                    out.append(v); seen.add(v)
    # 3) Failure-record augmentation
    if FAILURES_FILE.exists():
        try:
            failures = read_json(FAILURES_FILE)
            for f in failures:
                if f.get("missed_capability", "").lower() in cap or cap in f.get("missed_capability", "").lower():
                    for s in f.get("missed_synonyms", []):
                        if s not in seen:
                            out.append(s); seen.add(s)
        except json.JSONDecodeError:
            pass
    return out

def grep_repo(term: str, manifest: list[dict]) -> list[dict]:
    rx = re.compile(re.escape(term), re.IGNORECASE)
    hits: list[dict] = []
    for m in manifest:
        if m["role_guess"] not in ("code", "config"):
            continue
        p = REPO_ROOT / m["path"]
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if rx.search(text):
            first30 = "\n".join(text.splitlines()[:30])
            hits.append({"path": m["path"], "first_30_lines": first30})
    return hits

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

def phase_4(ctx: AuditCtx) -> None:
    print(f"[phase 4] capability semantic search")
    charter = load_charter(ctx)
    if not ctx.manifest.exists():
        raise GateFailure("phase4.precondition", "manifest.json missing")
    manifest = read_json(ctx.manifest)
    capabilities = charter["capabilities"]
    for cap in capabilities:
        slug = slugify(cap)
        syns = synonyms_for(cap)
        if len(syns) < 6:
            # Pad with generic discovery terms to ensure ≥6.
            for extra in ["use", "call", "run", "exec", "load", "import"]:
                if extra not in syns:
                    syns.append(extra)
                if len(syns) >= 6:
                    break
        if len(syns) < 6:
            raise GateFailure("phase4.synonyms", f"capability '{cap}' could not generate ≥6 synonyms")
        results = {"capability": cap, "synonyms": syns, "queries": []}
        for term in syns:
            hits = grep_repo(term, manifest)
            results["queries"].append({"term": term, "hit_count": len(hits), "hits": hits})
        write_json(ctx.capabilities_dir / f"{slug}.json", results)
        print(f"  ok — '{cap}' searched with {len(syns)} synonyms")
    # Gate
    if len(list(ctx.capabilities_dir.glob("*.json"))) < len(capabilities):
        raise GateFailure("phase4.coverage", "fewer capability artifacts than charter capabilities")


# ---------------------------------------------------------------------------
# Phase 5: adversaries (manual; emits Task prompts and validates returned artifacts)
# ---------------------------------------------------------------------------

ADVERSARY_PROMPTS = {
    "wrecker": "adversary_wrecker.md",
    "defender": "adversary_defender.md",
    "vendor_first": "adversary_vendor_first.md",
}

def phase_5(ctx: AuditCtx) -> None:
    print(f"[phase 5] adversary panel")
    expected = [ctx.adversary_a, ctx.adversary_b, ctx.adversary_c]
    missing = [str(p) for p in expected if not p.exists()]
    if missing:
        # Emit instructions
        prompts_dir = REPO_ROOT / "tools" / "iron_audit" / "adversary_prompts"
        print("  ! adversary artifacts missing. Spawn THREE fresh-context Task subagents:")
        for name, file in ADVERSARY_PROMPTS.items():
            print(f"    - {name}: system prompt at {prompts_dir / file}")
            print(f"        inputs: {ctx.manifest}, {ctx.surface}, {ctx.imports}, {ctx.capabilities_dir}/")
        print(f"  Each must write its verdict JSON to ctx.adversary_a/b/c. Then re-run phase 5.")
        raise GateFailure("phase5.artifacts", f"missing: {missing}")
    if not ctx.manifest.exists():
        raise GateFailure("phase5.precondition", "manifest missing")
    manifest_paths = {m["path"] for m in read_json(ctx.manifest)}
    for p in expected:
        data = read_json(p)
        if not isinstance(data, list):
            raise GateFailure("phase5.shape", f"{p} must be a list")
        covered = {row["path"] for row in data if "path" in row}
        if covered != manifest_paths:
            raise GateFailure("phase5.coverage", f"{p.name} missing files: {manifest_paths - covered}")
    print("  ok — three adversaries cover 100% of manifest")


# ---------------------------------------------------------------------------
# Phase 6: reconciliation
# ---------------------------------------------------------------------------

def phase_6(ctx: AuditCtx) -> None:
    print(f"[phase 6] reconciliation")
    a = {row["path"]: row for row in read_json(ctx.adversary_a)}
    b = {row["path"]: row for row in read_json(ctx.adversary_b)}
    c = {row["path"]: row for row in read_json(ctx.adversary_c)}
    rows: list[dict] = []
    for path in sorted(set(a) | set(b) | set(c)):
        votes = [a.get(path, {}).get("disposition", "?"), b.get(path, {}).get("disposition", "?"), c.get(path, {}).get("disposition", "?")]
        from collections import Counter
        tally = Counter(votes)
        top, top_count = tally.most_common(1)[0]
        if top_count == 3:
            final = top; agreement = 3; escalated = False; dissent = ""
        elif top_count == 2:
            final = top; agreement = 2; escalated = False
            dissenter = [v for v in votes if v != top][0]
            dissent = f"{dissenter} dissented"
        else:
            final = "ESCALATE"; agreement = 1; escalated = True; dissent = "three-way split"
        rows.append({
            "path": path, "wrecker": votes[0], "defender": votes[1], "vendor_first": votes[2],
            "agreement": agreement, "final_disposition": final, "escalated": escalated, "dissent": dissent,
        })
    # CSV write
    import csv
    with ctx.dispositions.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    escalated_count = sum(1 for r in rows if r["escalated"])
    print(f"  ok — {len(rows)} dispositions; {escalated_count} escalated to Phase 9")


# ---------------------------------------------------------------------------
# Phase 7: verifier (manual; orchestrator validates)
# ---------------------------------------------------------------------------

def phase_7(ctx: AuditCtx) -> None:
    print(f"[phase 7] verifier reads")
    import csv
    with ctx.dispositions.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    deletes = [r["path"] for r in rows if r["final_disposition"] == "DELETE"]
    if not deletes:
        write_json(ctx.verifier, {"verified": [], "note": "no deletes to verify"})
        print("  ok — no deletes; verifier vacuously satisfied")
        return
    if not ctx.verifier.exists():
        prompt_path = REPO_ROOT / "tools" / "iron_audit" / "adversary_prompts" / "verifier.md"
        print(f"  ! verifier.json missing. Spawn ONE fresh-context Task subagent.")
        print(f"    system prompt: {prompt_path}")
        print(f"    inputs: dispositions.csv ({len(deletes)} DELETE rows), manifest.json, imports.json")
        print(f"    instruction: read full body of every DELETE file and every importer; confirm or override")
        raise GateFailure("phase7.artifact", "verifier.json missing")
    data = read_json(ctx.verifier)
    verified_paths = {entry["path"] for entry in data.get("verified", [])}
    missing = set(deletes) - verified_paths
    if missing:
        raise GateFailure("phase7.coverage", f"verifier missed DELETE rows: {missing}")
    # Auto-flip unconfirmed deletes to KEEP
    flips = 0
    for entry in data["verified"]:
        if not entry.get("confirmed", False):
            for r in rows:
                if r["path"] == entry["path"] and r["final_disposition"] == "DELETE":
                    r["final_disposition"] = "KEEP"
                    r["dissent"] = (r.get("dissent", "") + f"; verifier_override: {entry.get('override_reason', 'unconfirmed')}").strip("; ")
                    flips += 1
    if flips:
        with ctx.dispositions.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    print(f"  ok — {len(deletes)} DELETE rows verified; {flips} auto-flipped to KEEP")


# ---------------------------------------------------------------------------
# Phase 8: methodology audit (completeness check)
# ---------------------------------------------------------------------------

def phase_8(ctx: AuditCtx) -> None:
    print(f"[phase 8] completeness check")
    assertions: dict[str, bool] = {}
    assertions["charter_exists"] = ctx.charter.exists()
    assertions["charter_ratified"] = ctx.charter_ratified.exists()
    assertions["manifest_exists"] = ctx.manifest.exists()
    assertions["surface_exists"] = ctx.surface.exists()
    assertions["imports_exists"] = ctx.imports.exists()
    assertions["capabilities_dir_nonempty"] = ctx.capabilities_dir.exists() and any(ctx.capabilities_dir.iterdir())
    assertions["adversary_a"] = ctx.adversary_a.exists()
    assertions["adversary_b"] = ctx.adversary_b.exists()
    assertions["adversary_c"] = ctx.adversary_c.exists()
    assertions["dispositions_exists"] = ctx.dispositions.exists()
    assertions["verifier_exists"] = ctx.verifier.exists()
    if ctx.manifest.exists() and ctx.dispositions.exists():
        manifest_paths = {m["path"] for m in read_json(ctx.manifest)}
        import csv
        with ctx.dispositions.open("r", encoding="utf-8") as fh:
            disp_paths = {r["path"] for r in csv.DictReader(fh)}
        assertions["dispositions_cover_manifest"] = disp_paths == manifest_paths
    else:
        assertions["dispositions_cover_manifest"] = False
    if ctx.charter.exists() and ctx.capabilities_dir.exists():
        charter = load_charter(ctx)
        cap_files = {p.stem for p in ctx.capabilities_dir.glob("*.json")}
        expected = {slugify(c) for c in charter["capabilities"]}
        assertions["capabilities_cover_charter"] = expected.issubset(cap_files)
    else:
        assertions["capabilities_cover_charter"] = False

    bundle_inputs = sorted([
        ctx.charter, ctx.charter_ratified, ctx.manifest, ctx.surface, ctx.imports,
        ctx.adversary_a, ctx.adversary_b, ctx.adversary_c, ctx.dispositions, ctx.verifier,
    ] + sorted(ctx.capabilities_dir.glob("*.json")))
    bundle_h = hashlib.sha256()
    for p in bundle_inputs:
        if p.exists():
            bundle_h.update(p.name.encode())
            bundle_h.update(sha256_of(p).encode())
    bundle_sha = bundle_h.hexdigest()
    completeness = {"assertions": assertions, "bundle_sha256": bundle_sha, "checked_at": now_iso()}
    write_json(ctx.completeness, completeness)
    failed = [k for k, v in assertions.items() if not v]
    if failed:
        raise GateFailure("phase8.assertions", f"failed: {failed}")
    print(f"  ok — all assertions pass; bundle sha256 = {bundle_sha[:16]}...")


# ---------------------------------------------------------------------------
# Phase 9: ratify
# ---------------------------------------------------------------------------

def phase_9(ctx: AuditCtx) -> None:
    print(f"[phase 9] final report + ratification")
    if not ctx.completeness.exists():
        raise GateFailure("phase9.precondition", "completeness.json missing; run phase 8 first")
    completeness = read_json(ctx.completeness)
    if not all(completeness["assertions"].values()):
        raise GateFailure("phase9.precondition", "completeness assertions failing; cannot finalize")
    if not ctx.report.exists():
        # Auto-generate a minimal report.
        import csv
        with ctx.dispositions.open("r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        from collections import Counter
        tally = Counter(r["final_disposition"] for r in rows)
        escalated = [r for r in rows if r["escalated"] in (True, "True", "true")]
        ratifier_line = assert_ratified(ctx.charter_ratified, "charter.ratified")
        body = [
            f"# Audit Report — {ctx.audit_id}",
            f"",
            f"**Bundle sha256:** `{completeness['bundle_sha256']}`",
            f"**Charter ratifier:** {ratifier_line}",
            f"**Generated:** {now_iso()}",
            f"",
            f"## Disposition tally",
            f"",
        ]
        for k, v in tally.most_common():
            body.append(f"- {k}: {v}")
        body.append("")
        body.append(f"## Escalated rows ({len(escalated)})")
        body.append("")
        for r in escalated:
            body.append(f"- `{r['path']}` — wrecker={r['wrecker']} defender={r['defender']} vendor_first={r['vendor_first']}")
            body.append(f"    USER-DECISION: ____")
        body.append("")
        body.append("## Ratification")
        body.append("")
        body.append("To finalize this audit, create `report.ratified.txt` with a line:")
        body.append("")
        body.append("    RATIFIED-BY: <name> <iso-timestamp>")
        body.append("")
        ctx.report.write_text("\n".join(body), encoding="utf-8")
        print(f"  -> wrote report to {ctx.report}")
    ratifier = assert_ratified(ctx.report_ratified, "report.ratified")
    print(f"  ok — report ratified by {ratifier}")


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def finalize(ctx: AuditCtx) -> None:
    # Run all phases (idempotent gate-checks)
    for fn in (phase_0, phase_1, phase_2, phase_3, phase_4, phase_5, phase_6, phase_7, phase_8, phase_9):
        fn(ctx)
    completeness = read_json(ctx.completeness)
    print(f"\nAUDIT COMPLETE: {completeness['bundle_sha256']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    audit_id = args.audit_id or str(uuid.uuid4())
    ctx = AuditCtx(audit_id)
    ctx.ensure_dir()
    print(f"initialized audit {audit_id} at {ctx.dir}")
    print(f"next: edit {ctx.charter} and create {ctx.charter_ratified}, then run: phase 0")

def cmd_phase(args: argparse.Namespace) -> None:
    ctx = AuditCtx(args.audit)
    ctx.ensure_dir()
    fns = [phase_0, phase_1, phase_2, phase_3, phase_4, phase_5, phase_6, phase_7, phase_8, phase_9]
    if args.phase < 0 or args.phase >= len(fns):
        sys.exit(f"invalid phase {args.phase}")
    fns[args.phase](ctx)

def cmd_status(args: argparse.Namespace) -> None:
    ctx = AuditCtx(args.audit)
    files = [ctx.charter, ctx.charter_ratified, ctx.manifest, ctx.surface, ctx.imports,
             ctx.adversary_a, ctx.adversary_b, ctx.adversary_c, ctx.dispositions,
             ctx.verifier, ctx.completeness, ctx.report, ctx.report_ratified]
    for p in files:
        print(f"  {'OK' if p.exists() else '..'}  {p.name}")

def cmd_finalize(args: argparse.Namespace) -> None:
    finalize(AuditCtx(args.audit))


def main() -> None:
    p = argparse.ArgumentParser(description="IRON-AUDIT orchestrator (ADR-001)")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init"); p_init.add_argument("audit_id", nargs="?"); p_init.set_defaults(func=cmd_init)
    p_phase = sub.add_parser("phase"); p_phase.add_argument("phase", type=int); p_phase.add_argument("--audit", required=True); p_phase.set_defaults(func=cmd_phase)
    p_stat = sub.add_parser("status"); p_stat.add_argument("--audit", required=True); p_stat.set_defaults(func=cmd_status)
    p_fin = sub.add_parser("finalize"); p_fin.add_argument("--audit", required=True); p_fin.set_defaults(func=cmd_finalize)
    args = p.parse_args()
    try:
        args.func(args)
    except GateFailure as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
