"""
Prompt Registry - Lightweight prompt governance for the Bat Family.

Lucius Fox recommended: Instead of installing Docker + Agenta (heavy infrastructure),
we build a lightweight local prompt registry that covers our immediate needs:
- Versioned prompt storage (JSON files)
- Named prompts with metadata
- Environment support (dev/staging/prod)
- History tracking
- Simple Python API

If/when Docker is installed on Oracle, we can migrate to Agenta.
This module is designed to be compatible with Agenta's SDK patterns.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from rudy.paths import RUDY_DATA  # noqa: E402
REGISTRY_DIR = RUDY_DATA / "prompt-registry"


class PromptRegistry:
    """Local prompt registry with versioning, environments, and history."""

    def __init__(self, registry_dir: Optional[Path] = None):
        self.registry_dir = registry_dir or REGISTRY_DIR
        self.prompts_dir = self.registry_dir / "prompts"
        self.history_dir = self.registry_dir / "history"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def save_prompt(
        self,
        name: str,
        template: str,
        model: str = "qwen2.5:7b",
        environment: str = "dev",
        tags: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Save or update a prompt with automatic versioning."""
        prompt_file = self.prompts_dir / f"{name}.json"

        # Load existing or create new
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            version = existing.get("version", 0) + 1

            # Archive previous version
            archive = self.history_dir / name
            archive.mkdir(exist_ok=True)
            archive_file = archive / f"v{existing.get('version', 0)}.json"
            shutil.copy2(prompt_file, archive_file)
        else:
            version = 1

        prompt_data = {
            "name": name,
            "version": version,
            "template": template,
            "model": model,
            "environment": environment,
            "tags": tags or [],
            "parameters": parameters or {},
            "notes": notes,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "author": "alfred",
        }

        with open(prompt_file, "w", encoding="utf-8") as f:
            json.dump(prompt_data, f, indent=2, ensure_ascii=False)

        return prompt_data

    def get_prompt(self, name: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Get a prompt by name, optionally a specific version."""
        if version is not None:
            # Look in history
            history_file = self.history_dir / name / f"v{version}.json"
            if history_file.exists():
                with open(history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        prompt_file = self.prompts_dir / f"{name}.json"
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def list_prompts(self, tag: Optional[str] = None, environment: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all prompts, optionally filtered by tag or environment."""
        prompts = []
        for f in self.prompts_dir.glob("*.json"):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if tag and tag not in data.get("tags", []):
                continue
            if environment and data.get("environment") != environment:
                continue
            prompts.append(data)
        return sorted(prompts, key=lambda x: x.get("name", ""))

    def get_history(self, name: str) -> List[Dict[str, Any]]:
        """Get version history for a prompt."""
        history_path = self.history_dir / name
        if not history_path.exists():
            return []

        versions = []
        for f in sorted(history_path.glob("v*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                versions.append(json.load(fh))
        return versions

    def render(self, name: str, **kwargs) -> str:
        """Render a prompt template with parameters."""
        prompt = self.get_prompt(name)
        if not prompt:
            raise ValueError(f"Prompt '{name}' not found")
        template = prompt["template"]
        for key, value in kwargs.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        return template

    def export_catalog(self) -> str:
        """Export all prompts as a markdown catalog."""
        prompts = self.list_prompts()
        lines = ["# Prompt Registry Catalog", ""]
        lines.append(f"Generated: {datetime.now().isoformat()}")
        lines.append(f"Total prompts: {len(prompts)}")
        lines.append("")

        for p in prompts:
            lines.append(f"## {p['name']} (v{p['version']})")
            lines.append(f"- **Model**: {p['model']}")
            lines.append(f"- **Environment**: {p['environment']}")
            lines.append(f"- **Tags**: {', '.join(p.get('tags', []))}")
            lines.append(f"- **Updated**: {p.get('updated_at', 'unknown')}")
            if p.get("notes"):
                lines.append(f"- **Notes**: {p['notes']}")
            lines.append(f"- **Template preview**: {p['template'][:100]}...")
            lines.append("")

        return "\n".join(lines)


def seed_registry():
    """Seed the registry with initial Bat Family prompts."""
    reg = PromptRegistry()

    # Robin's core prompts
    reg.save_prompt(
        name="robin-night-shift-system",
        template="You are Robin, the night operator of the Batcave. You monitor system health, execute directives from Alfred, and maintain awareness of the environment. Current mode: {{mode}}. Priority: {{priority}}.",
        model="qwen2.5:7b",
        environment="prod",
        tags=["robin", "system", "core"],
        notes="Robin's main system prompt for night shift mode",
    )

    reg.save_prompt(
        name="robin-directive-execution",
        template="DIRECTIVE FROM ALFRED (Priority: {{priority}})\n\nTask: {{task}}\n\nSteps:\n{{steps}}\n\nIMPORTANT: Follow steps exactly. Use Shell tool (not Snapshot). Write results to file, then read with Get-Content.",
        model="qwen2.5:7b",
        environment="prod",
        tags=["robin", "directive", "core"],
        notes="Template for Alfred->Robin directives. Optimized for 7b model tool selection.",
    )

    reg.save_prompt(
        name="lucius-audit-system",
        template="You are Lucius Fox, the Bat Family's specialist engineer. Run a {{audit_type}} audit of the codebase at {{codebase_path}}. Focus on: code inventory, duplication, dependencies, agent health, documentation freshness.",
        model="local",
        environment="prod",
        tags=["lucius", "audit", "core"],
        notes="Lucius Fox agent system prompt for audit mode",
    )

    reg.save_prompt(
        name="robin-health-report",
        template="Generate a system health report. Check: CPU ({{cpu_pct}}%), RAM ({{ram_pct}}%), Disk ({{disk_pct}}%), Ollama ({{ollama_status}}), Python processes ({{py_count}}). Summarize status and flag any concerns.",
        model="qwen2.5:7b",
        environment="prod",
        tags=["robin", "health", "report"],
        notes="Template for Robin's periodic health reports to Alfred",
    )

    reg.save_prompt(
        name="sentinel-observation",
        template="Observe the environment for friction signals. Categories: environment health (disk, processes, services), coordination gaps (stale messages, silence), code quality (errors, deprecations). Report observations as structured JSON.",
        model="qwen2.5:7b",
        environment="prod",
        tags=["sentinel", "observation", "core"],
        notes="SentinelObserver prompt for passive environmental scanning",
    )

    # Export catalog
    catalog = reg.export_catalog()
    catalog_path = reg.registry_dir / "CATALOG.md"
    with open(catalog_path, "w", encoding="utf-8") as f:
        f.write(catalog)

    return len(reg.list_prompts()), str(catalog_path)


if __name__ == "__main__":
    count, path = seed_registry()
    print(f"OK: Seeded {count} prompts")
    print(f"OK: Catalog at {path}")
