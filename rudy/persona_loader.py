#!/usr/bin/env python3

"""
Persona Loader — Declarative persona registry for the Batcave (ADR-017).

Loads persona definitions from persona_config.yaml and provides:
    - PersonaRegistry: discover, get, list, and filter personas
    - build_system_prompt(): construct a LangGraph-compatible system prompt
    - get_persona_config(): return raw config dict for a named persona

Integration with robin_agent_langgraph.py:
    Before: AGENT_SYSTEM_PROMPT was hardcoded for Robin.
    After:  RobinAgentV2 can call get_system_prompt("robin") to get
            persona-aware prompts. Other personas work the same way.

Adding a new persona:
    1. Add a block under `personas:` in persona_config.yaml
    2. The registry discovers it automatically at next load
    3. No Python changes required

Dependencies: PyYAML (already installed)
"""

import logging
import copy
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    # Graceful fallback: if PyYAML is missing, provide a clear error
    yaml = None

logger = logging.getLogger("batcave.persona")


# ---------------------------------------------------------------------------
# Subagent Definition Generator (S55 — AF-S54-001)
# ---------------------------------------------------------------------------

# Skill mapping per persona for Claude Code subagent definitions
_SKILL_MAP = {
    "alfred": [],
    "lucius": [
        "engineering:code-review",
        "engineering:architecture",
        "engineering:tech-debt",
    ],
    "robin": [
        "local-control",
        "code-runner",
        "git-workflow",
    ],
    "sentinel": [
        "system-health",
        "security-checkup",
    ],
}

# Claude Code tool names per persona
_TOOL_MAP = {
    "alfred": ["Read", "Grep", "Glob", "Agent", "WebSearch", "WebFetch"],
    "lucius": ["Read", "Grep", "Glob", "Bash", "Agent"],
    "robin": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent"],
    "sentinel": ["Read", "Grep", "Glob", "Bash"],
}


def generate_subagent_defs(
    registry: Optional["PersonaRegistry"] = None,
    output_dir: Optional[Path] = None,
) -> list[Path]:
    """Generate .claude/agents/*.md from persona_config.yaml.

    Creates Claude Code subagent definition files with YAML frontmatter
    that map 1:1 to persona_config.yaml fields. This makes personas
    native to both Claude Code CLI and Cowork mode.

    Args:
        registry: PersonaRegistry to read from (uses default if None).
        output_dir: Directory to write .md files (defaults to REPO/.claude/agents/).

    Returns:
        List of paths to generated files.
    """
    if registry is None:
        registry = get_registry()

    if output_dir is None:
        try:
            from rudy.paths import REPO_ROOT
            output_dir = REPO_ROOT / ".claude" / "agents"
        except ImportError:
            output_dir = Path(__file__).parent.parent / ".claude" / "agents"

    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []

    for persona in registry.list_all():
        name = persona.name
        tools = _TOOL_MAP.get(name, ["Read", "Grep", "Glob"])
        skills = _SKILL_MAP.get(name, [])

        lines = ["---"]
        lines.append(f"name: {name}")
        desc = f"{persona.role}. {persona.goal}"
        lines.append(f'description: "{desc}"')
        lines.append(f"tools: {', '.join(tools)}")
        lines.append("model: inherit")
        lines.append("memory: project")
        if skills:
            lines.append("skills:")
            for s in skills:
                lines.append(f"  - {s}")
        lines.append("---")
        lines.append("")
        lines.append(f"You are {name.title()}, {persona.role}.")
        lines.append("")
        if persona.backstory:
            lines.append(persona.backstory)
            lines.append("")
        if persona.hard_rules:
            lines.append("HARD RULES:")
            for i, rule in enumerate(persona.hard_rules, 1):
                lines.append(f"{i}. {rule}")
            lines.append("")
        if persona.can_delegate_to:
            names_str = ", ".join(persona.can_delegate_to)
            lines.append(f"You can delegate tasks to: {names_str}")
            lines.append("")

        out_path = output_dir / f"{name}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        generated.append(out_path)
        logger.info(f"Generated subagent def: {out_path.name}")

    logger.info(f"Generated {len(generated)} subagent definitions in {output_dir}")
    return generated


# ---------------------------------------------------------------------------
# Config path (import from paths.py to avoid hardcoding)
# ---------------------------------------------------------------------------

try:
    from rudy.paths import REPO_ROOT
    _DEFAULT_CONFIG = REPO_ROOT / "rudy" / "persona_config.yaml"
except ImportError:
    # Fallback for standalone testing
    _DEFAULT_CONFIG = Path(__file__).parent / "persona_config.yaml"


# ---------------------------------------------------------------------------
# Persona dataclass-like container
# ---------------------------------------------------------------------------

class Persona:
    """A single persona definition loaded from YAML.

    Attributes mirror the YAML schema. All fields are read-only after
    construction. Use PersonaRegistry to access personas.
    """

    __slots__ = (
        "name", "role", "goal", "backstory", "category", "tags",
        "model", "ollama_host", "temperature", "max_steps",
        "num_predict", "context_window",
        "can_delegate_to", "receives_from",
        "tools", "hard_rules", "routing_rules", "_raw",
    )

    def __init__(self, name: str, data: dict, defaults: dict):
        self.name = name
        self._raw = copy.deepcopy(data)

        # Merge defaults: persona values override defaults
        merged = {**defaults, **data}

        self.role = merged.get("role", name.title())
        self.goal = merged.get("goal", "")
        self.backstory = merged.get("backstory", "").strip()
        self.category = merged.get("category", "general")
        self.tags = merged.get("tags", [])
        self.model = merged.get("model", "qwen2.5:7b")
        self.ollama_host = merged.get("ollama_host", "http://localhost:11434")
        self.temperature = merged.get("temperature", 0.3)
        self.max_steps = merged.get("max_steps", 15)
        self.num_predict = merged.get("num_predict", 2048)
        self.context_window = merged.get("context_window", 8192)
        self.can_delegate_to = merged.get("can_delegate_to", [])
        self.receives_from = merged.get("receives_from", [])
        self.tools = merged.get("tools", [])
        self.hard_rules = merged.get("hard_rules", [])
        self.routing_rules = merged.get("routing_rules", [])

    def build_system_prompt(self, tools_prompt: str = "") -> str:
        """Construct a full system prompt for this persona.

        Args:
            tools_prompt: MCP tools listing (from registry.get_tools_prompt())

        Returns:
            Complete system prompt string for LLM consumption.
        """
        sections = [
            f"You are {self.name.title()}, {self.role}.",
            f"Goal: {self.goal}",
            "",
            self.backstory,
        ]

        if self.hard_rules:
            sections.append("\nHARD RULES (violations are scored):")
            for i, rule in enumerate(self.hard_rules, 1):
                sections.append(f"  {i}. {rule}")

        if self.can_delegate_to:
            names = ", ".join(self.can_delegate_to)
            sections.append(f"\nYou can delegate tasks to: {names}")

        if tools_prompt:
            sections.append(f"\nAVAILABLE TOOLS:\n{tools_prompt}")
            sections.append(
                '\nTOOL CALL FORMAT — use EXACTLY this format, one tool per response:\n'
                '<tool_call>\n'
                '{"tool": "server-name.ToolName", "args": {"param": "value"}}\n'
                '</tool_call>\n'
                '\nRULES:\n'
                '1. Call ONE tool per response. Wait for the result.\n'
                '2. After receiving a tool result, analyze it and decide next action.\n'
                '3. When complete, respond with your final answer in plain text.\n'
                '4. Do NOT describe what you would do — actually call the tool.'
            )

        return "\n".join(sections)

    def to_dict(self) -> dict:
        """Serialize persona to a plain dict (for logging/debugging)."""
        return {
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "category": self.category,
            "tags": self.tags,
            "model": self.model,
            "max_steps": self.max_steps,
            "can_delegate_to": self.can_delegate_to,
            "receives_from": self.receives_from,
            "tools": self.tools,
        }

    def __repr__(self) -> str:
        return f"Persona({self.name!r}, role={self.role!r}, category={self.category!r})"


# ---------------------------------------------------------------------------
# Persona Registry
# ---------------------------------------------------------------------------

class PersonaRegistry:
    """Registry of all personas loaded from YAML config.

    Usage:
        registry = PersonaRegistry()          # loads default config
        robin = registry.get("robin")         # get a single persona
        executors = registry.by_category("execution")  # filter
        all_names = registry.list_names()     # ['alfred', 'lucius', ...]
        registry.reload()                     # hot-reload from disk
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = Path(config_path) if config_path else _DEFAULT_CONFIG
        self._personas: dict[str, Persona] = {}
        self._defaults: dict = {}
        self._schema_version: int = 0
        self._load()

    def _load(self) -> None:
        """Parse YAML and populate the persona map."""
        if yaml is None:
            raise ImportError(
                "PyYAML is required for persona_loader. "
                "Install with: pip install pyyaml"
            )

        if not self._config_path.exists():
            logger.warning(f"Persona config not found: {self._config_path}")
            return

        with open(self._config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or not isinstance(raw, dict):
            logger.warning("Persona config is empty or malformed")
            return

        self._defaults = raw.get("defaults", {})
        self._schema_version = raw.get("schema_version", 1)

        personas_block = raw.get("personas", {})
        if not isinstance(personas_block, dict):
            logger.warning("'personas' key missing or not a mapping")
            return

        self._personas.clear()
        for name, data in personas_block.items():
            if not isinstance(data, dict):
                logger.warning(f"Skipping malformed persona: {name}")
                continue
            self._personas[name] = Persona(name, data, self._defaults)

        logger.info(
            f"Loaded {len(self._personas)} personas from {self._config_path.name} "
            f"(schema v{self._schema_version}): {list(self._personas.keys())}"
        )

    def reload(self) -> None:
        """Hot-reload config from disk. Safe to call anytime."""
        self._load()

    def get(self, name: str) -> Optional[Persona]:
        """Get a persona by name (case-insensitive)."""
        return self._personas.get(name.lower())

    def list_names(self) -> list[str]:
        """Return sorted list of all persona names."""
        return sorted(self._personas.keys())

    def list_all(self) -> list[Persona]:
        """Return all personas as a list."""
        return list(self._personas.values())

    def by_category(self, category: str) -> list[Persona]:
        """Filter personas by category."""
        return [p for p in self._personas.values() if p.category == category]

    def by_tag(self, tag: str) -> list[Persona]:
        """Filter personas by tag."""
        return [p for p in self._personas.values() if tag in p.tags]

    def who_can_handle(self, task_type: str) -> list[str]:
        """Return persona names whose routing_rules match a task type."""
        matches = []
        for p in self._personas.values():
            for rule in p.routing_rules:
                cond = rule.get("condition", "")
                if task_type in cond:
                    matches.append(rule.get("route_to", p.name))
        return list(set(matches))

    def delegation_graph(self) -> dict[str, list[str]]:
        """Return the full delegation adjacency map.

        Returns:
            {"alfred": ["robin", "lucius"], "lucius": ["robin"], ...}
        """
        return {p.name: p.can_delegate_to for p in self._personas.values()}

    @property
    def schema_version(self) -> int:
        return self._schema_version

    def __len__(self) -> int:
        return len(self._personas)

    def __contains__(self, name: str) -> bool:
        return name.lower() in self._personas

    def __repr__(self) -> str:
        return f"PersonaRegistry({len(self)} personas: {self.list_names()})"


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_registry: Optional[PersonaRegistry] = None


def get_registry(config_path: Optional[Path] = None) -> PersonaRegistry:
    """Get or create the singleton PersonaRegistry.

    Thread-safe for read access (Python GIL). Call reload() to refresh.
    """
    global _registry
    if _registry is None or config_path is not None:
        _registry = PersonaRegistry(config_path)
    return _registry


def get_persona(name: str) -> Optional[Persona]:
    """Convenience: get a persona from the default registry."""
    return get_registry().get(name)


def get_system_prompt(name: str, tools_prompt: str = "") -> str:
    """Convenience: build a system prompt for a named persona.

    Returns a generic fallback if persona not found.
    """
    persona = get_persona(name)
    if persona:
        return persona.build_system_prompt(tools_prompt)

    logger.warning(f"Persona '{name}' not found, using generic prompt")
    return (
        f"You are {name.title()}, an AI assistant in the Batcave system.\n"
        f"Execute tasks carefully and report results.\n"
        f"{tools_prompt}"
    )


# ---------------------------------------------------------------------------
# CLI: quick inspection and validation
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    registry = get_registry()
    print(f"\n{registry}\n")
    print(f"Schema version: {registry.schema_version}")
    print(f"Delegation graph: {registry.delegation_graph()}\n")

    for name in registry.list_names():
        p = registry.get(name)
        print(f"--- {p.name.upper()} ---")
        print(f"  Role:       {p.role}")
        print(f"  Category:   {p.category}")
        print(f"  Model:      {p.model}")
        print(f"  Tags:       {p.tags}")
        print(f"  Delegates:  {p.can_delegate_to}")
        print(f"  Hard rules: {len(p.hard_rules)}")
        print(f"  Tools:      {len(p.tools)}")
        print()

    # Validate delegation graph (no broken references)
    all_names = set(registry.list_names())
    errors = 0
    for p in registry.list_all():
        for target in p.can_delegate_to:
            if target not in all_names:
                print(f"  ERROR: {p.name} delegates to '{target}' which doesn't exist")
                errors += 1
        for source in p.receives_from:
            if source not in all_names:
                print(f"  ERROR: {p.name} receives from '{source}' which doesn't exist")
                errors += 1

    if errors:
        print(f"\n{errors} validation error(s) found!")
        sys.exit(1)
    else:
        print("All delegation references valid.")
        sys.exit(0)
