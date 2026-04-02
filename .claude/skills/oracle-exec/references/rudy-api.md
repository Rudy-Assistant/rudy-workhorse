# Rudy Package API Quick Reference

Use this when writing validation or test scripts on Oracle. These are the **actual** method names — do NOT guess.

## persona_loader

```python
from rudy.persona_loader import PersonaRegistry, get_registry, get_persona, get_system_prompt

# Registry (class)
r = PersonaRegistry()          # or get_registry()
r.get("alfred")                # -> Optional[Persona]
r.list_names()                 # -> list[str]  e.g. ["alfred", "lucius", "robin", "sentinel"]
r.list_all()                   # -> list[Persona]  ← NOT get_all_personas()
r.by_category("orchestration") # -> list[Persona]
r.by_tag("security")           # -> list[Persona]
r.who_can_handle("filesystem") # -> list[str]
r.delegation_graph()           # -> dict[str, list[str]]
r.schema_version()             # -> int
r.reload()                     # reloads from YAML

# Convenience functions
get_persona("robin")           # -> Optional[Persona]
get_system_prompt("alfred")    # -> str

# Persona (dataclass)
p = r.get("robin")
p.name                         # str
p.skills                       # list[str]
p.delegates_to                 # list[str]
p.build_system_prompt("")      # -> str
p.to_dict()                    # -> dict

# Generator
from rudy.persona_loader import generate_subagent_defs
generate_subagent_defs()       # writes .claude/agents/*.md
```

## paths

```python
from rudy.paths import REPO_ROOT, RUDY_DATA, VAULT_DIR, LOGS_DIR
# Always import paths — never hardcode.
```
