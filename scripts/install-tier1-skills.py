#!/usr/bin/env python3
"""Install Tier 1 skills from the Session 30 skill expansion plan.

Skills installed:
    1. kepano/obsidian-skills -- Obsidian markdown, bases, canvas skills
    2. nextlevelbuilder/ui-ux-pro-max-skill -- UI/UX design skills (SKILL.md only)
    3. czlonkowski/n8n-mcp -- n8n MCP config (generates config snippet)

Run from repo root:
    python scripts/install-tier1-skills.py

This script follows the Build-vs-Buy gate (HARD RULE): each skill is
verified to not duplicate existing capabilities before installation.

Lucius Gate: LG-033 - No new dependencies. Uses git + shutil.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

# Resolve repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

GIT_EXE = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"


def _run(cmd, **kwargs):
    """Run a subprocess and return (returncode, stdout)."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 120)
    r = subprocess.run(cmd, **kwargs)
    return r.returncode, r.stdout.strip()


def _clone_temp(repo_url: str) -> Path:
    """Clone a repo to a temp directory."""
    tmp = Path(tempfile.mkdtemp(prefix="skill-install-"))
    print(f"  Cloning {repo_url} -> {tmp}")
    rc, out = _run([GIT_EXE, "clone", "--depth=1", repo_url, str(tmp)])
    if rc != 0:
        print(f"  ERROR: git clone failed: {out}")
        return None
    return tmp


def _copy_skills(src_dir: Path, dest_prefix: str, skill_names: list = None):
    """Copy skill directories from src to SKILLS_DIR."""
    if not src_dir.exists():
        print(f"  WARNING: Source dir not found: {src_dir}")
        return 0

    copied = 0
    for item in sorted(src_dir.iterdir()):
        if not item.is_dir():
            continue
        if skill_names and item.name not in skill_names:
            continue
        dest = SKILLS_DIR / f"{dest_prefix}-{item.name}"
        if dest.exists():
            print(f"  SKIP (exists): {dest.name}")
            continue
        shutil.copytree(item, dest)
        print(f"  INSTALLED: {dest.name}")
        copied += 1
    return copied


# ---------------------------------------------------------------------------
# Skill 1: kepano/obsidian-skills
# ---------------------------------------------------------------------------

def install_obsidian_skills():
    print("\n=== 1. Obsidian Skills (kepano/obsidian-skills) ===")

    # Check for duplicates
    existing = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir() and "obsidian" in d.name.lower()]
    if existing:
        print(f"  Obsidian skills already present: {existing}")
        return

    tmp = _clone_temp("https://github.com/kepano/obsidian-skills.git")
    if not tmp:
        return

    skills_src = tmp / "skills"
    count = _copy_skills(skills_src, "obsidian")
    print(f"  Installed {count} Obsidian skills.")

    # Cleanup
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Skill 2: UI/UX Pro Max (skill definitions only, skip heavy data files)
# ---------------------------------------------------------------------------

def install_uiux_skills():
    print("\n=== 2. UI/UX Pro Max Skills (nextlevelbuilder/ui-ux-pro-max-skill) ===")

    existing = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir() and "uiux" in d.name.lower()]
    if existing:
        print(f"  UI/UX skills already present: {existing}")
        return

    tmp = _clone_temp("https://github.com/nextlevelbuilder/ui-ux-pro-max-skill.git")
    if not tmp:
        return

    # The skills live in .claude/skills/ within the repo
    skills_src = tmp / ".claude" / "skills"
    if not skills_src.exists():
        # Try alternate locations
        for alt in [tmp / "skills", tmp / "src"]:
            if alt.exists():
                skills_src = alt
                break

    if skills_src.exists():
        count = _copy_skills(skills_src, "uiux")
        print(f"  Installed {count} UI/UX skills.")
    else:
        # Fallback: copy just the SKILL.md files we can find
        skill_mds = list(tmp.rglob("SKILL.md"))
        count = 0
        for sm in skill_mds:
            skill_name = sm.parent.name
            dest = SKILLS_DIR / f"uiux-{skill_name}"
            if dest.exists():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sm, dest / "SKILL.md")
            count += 1
            print(f"  INSTALLED: uiux-{skill_name}")
        print(f"  Installed {count} UI/UX skill definitions.")

    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Skill 3: n8n-MCP (config snippet generation)
# ---------------------------------------------------------------------------

def install_n8n_mcp():
    print("\n=== 3. n8n-MCP (czlonkowski/n8n-mcp) ===")
    print("  n8n-MCP is an MCP server, not a skill file.")
    print("  Generating config snippet for Claude Desktop...")

    config = {
        "mcpServers": {
            "n8n-mcp": {
                "command": "npx",
                "args": ["n8n-mcp"],
                "env": {
                    "MCP_MODE": "stdio",
                    "LOG_LEVEL": "error",
                    "DISABLE_CONSOLE_OUTPUT": "true",
                    "N8N_API_URL": "<YOUR_N8N_URL>",
                    "N8N_API_KEY": "<YOUR_N8N_API_KEY>",
                },
            }
        }
    }

    config_file = REPO_ROOT / "docs" / "n8n-mcp-config.json"
    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"  Config snippet saved to: {config_file}")
    print("  ACTION REQUIRED: Add to Claude Desktop config and set env vars.")
    print("  Windows config: %APPDATA%\\Claude\\claude_desktop_config.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Tier 1 Skill Installation -- Session 30B")
    print("=" * 60)
    print(f"  Repo root: {REPO_ROOT}")
    print(f"  Skills dir: {SKILLS_DIR}")

    install_obsidian_skills()
    install_uiux_skills()
    install_n8n_mcp()

    print("\n" + "=" * 60)
    print("  Installation complete.")
    installed = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()]
    print(f"  Skills in .claude/skills/: {len(installed)}")
    for s in sorted(installed):
        print(f"    - {s}")
    print("=" * 60)


if __name__ == "__main__":
    main()
