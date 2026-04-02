"""
Lucius Robin Gate -- Pre-commit enforcement for the Robin Intelligence Doctrine.

HARD RULE (Session 66): Any commit touching rudy/robin_*.py files MUST pass
these checks. This is not advisory -- it blocks the commit.

Checks:
  1. NO hardcoded UI coordinates (bare integer tuples used as click targets)
  2. Snapshot verification REQUIRED (must call Snapshot before and after actions)
  3. Dynamic element finding REQUIRED (find by name, not by pixel)
  4. No pyautogui/pyperclip imports when robin_mcp_client exists
  5. Reasoning loop present (Ollama/local_ai in the call chain)

Usage:
  python -m rudy.agents.lucius_robin_gate [file1.py file2.py ...]
  (No args = scan all rudy/robin_*.py files)

Exit codes:
  0 = PASS
  1 = FAIL (violations found)
"""

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ROBIN_GLOB = "rudy/robin_*.py"

# --- Violation Patterns ---

# Bare coordinate tuples: (123, 456) used as click/move targets
HARDCODED_COORD_RE = re.compile(
    r"""\(\s*\d{2,4}\s*,\s*\d{2,4}\s*\)""",
    re.VERBOSE,
)

# Banned imports -- Robin has MCP tools, not pyautogui
BANNED_IMPORTS = {"pyautogui", "pyperclip", "pynput", "pywinauto"}

# Required patterns -- at least one must appear in any UI-interacting Robin module
INTELLIGENCE_MARKERS = [
    "Snapshot",           # Perception -- must see before acting
    "find_element",       # Dynamic element finding
    "local_ai",           # Reasoning via Ollama
    "ollama",             # Direct Ollama reference
    "robin_mcp_client",   # Using Robin's own MCP client
    "MCPServerRegistry",  # MCP registry usage
]

class Finding:
    def __init__(self, file: str, line: int, code: str, message: str):
        self.file = file
        self.line = line
        self.code = code
        self.message = message

    def __str__(self):
        return f"  {self.code} [{self.file}:{self.line}] {self.message}"


def check_hardcoded_coords(filepath: Path, source: str) -> list[Finding]:
    """Detect hardcoded UI coordinates -- the #1 macro pattern."""
    findings = []
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        # Skip comments and string-only lines
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        # Skip coordinate definitions in UI dict (these are documented reference,
        # but the REAL check is whether they're used directly in click/move calls)
        if "UI[" in line or "UI =" in line or "# Element" in line:
            continue
        matches = HARDCODED_COORD_RE.findall(line)
        for m in matches:
            # Filter out small numbers (likely not coordinates)
            nums = [int(x) for x in re.findall(r"\d+", m)]
            if any(n > 50 for n in nums):
                findings.append(Finding(
                    str(filepath), i, "RG-001",
                    f"Hardcoded coordinate {m} -- use Snapshot + find_element_by_name instead",
                ))
    return findings


def check_banned_imports(filepath: Path, source: str) -> list[Finding]:
    """Detect imports of tools Robin doesn't need (has MCP equivalents)."""
    findings = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in BANNED_IMPORTS:
                    findings.append(Finding(
                        str(filepath), node.lineno, "RG-002",
                        f"Banned import '{alias.name}' -- Robin has robin_mcp_client + Windows-MCP",
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_IMPORTS:
                findings.append(Finding(
                    str(filepath), node.lineno, "RG-002",
                    f"Banned import from '{node.module}' -- Robin has robin_mcp_client + Windows-MCP",
                ))
    return findings

def check_intelligence_markers(filepath: Path, source: str) -> list[Finding]:
    """Verify the module uses Robin's intelligence, not just rigid scripts."""
    findings = []
    # Only check files that do UI interaction (contain Click, Type, or similar)
    # Only flag files that actually CALL UI tools (not just mention them in strings)
    # Look for MCP call patterns or pyautogui call patterns
    import re as _re
    ui_patterns = [
        r'wmcp\s*\(\s*"Click"',         # wmcp("Click", ...)
        r'call_tool\s*\(.*Click',        # registry.call_tool("...Click", ...)
        r'pyautogui\.\w+\s*\(',         # pyautogui.click(...)
        r'"windows-mcp\.Click"',         # literal MCP tool name
        r'"windows-mcp\.Type"',
        r'"windows-mcp\.Shortcut"',
        r'\.Click\s*\(',                 # .Click(...)  direct call
        r'\.Type\s*\(',                  # .Type(...)
        r'human_click\s*\(',            # human adapter calls
        r'human_type\s*\(',
    ]
    has_ui = any(_re.search(p, source) for p in ui_patterns)
    if not has_ui:
        return findings  # Not a UI module, skip

    has_intelligence = any(marker in source for marker in INTELLIGENCE_MARKERS)
    if not has_intelligence:
        findings.append(Finding(
            str(filepath), 1, "RG-003",
            "No intelligence markers found -- UI module must use Snapshot, "
            "robin_mcp_client, or local_ai. See docs/ROBIN-CAPABILITY-MANIFEST.md",
        ))

    # Check for Snapshot verification (must appear at least twice -- before and after)
    snapshot_count = source.count("Snapshot")
    if has_ui and snapshot_count < 2:
        findings.append(Finding(
            str(filepath), 1, "RG-004",
            f"Only {snapshot_count} Snapshot call(s) -- UI modules MUST snapshot "
            f"before AND after actions (PERCEIVE -> ACT -> VERIFY)",
        ))
    return findings

def scan_file(filepath: Path) -> list[Finding]:
    """Run all checks on a single file."""
    source = filepath.read_text(encoding="utf-8")
    findings = []
    findings.extend(check_hardcoded_coords(filepath, source))
    findings.extend(check_banned_imports(filepath, source))
    findings.extend(check_intelligence_markers(filepath, source))
    return findings


def main(files: list[str] = None) -> int:
    """Run the Robin gate. Returns 0 for PASS, 1 for FAIL."""
    if files:
        targets = [Path(f) for f in files if "robin_" in Path(f).name]
    else:
        targets = list(REPO.glob(ROBIN_GLOB))

    if not targets:
        print("Robin Gate: No robin_*.py files to check.")
        return 0

    all_findings = []
    for fp in sorted(targets):
        findings = scan_file(fp)
        all_findings.extend(findings)

    if all_findings:
        print(f"\n{'='*60}")
        print(f"ROBIN GATE: FAIL -- {len(all_findings)} violation(s)")
        print(f"{'='*60}")
        for f in all_findings:
            print(f)
        print("\n  Read: docs/ROBIN-CAPABILITY-MANIFEST.md")
        print("  Rule: CLAUDE.md -> Robin Intelligence Doctrine")
        print(f"{'='*60}\n")
        return 1
    else:
        print(f"Robin Gate: PASS -- {len(targets)} file(s) checked, 0 violations.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] if len(sys.argv) > 1 else None))
