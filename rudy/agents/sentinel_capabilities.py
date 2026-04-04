"""Capability scanning and manifest management for Sentinel.

Extracted from sentinel.py (S88, ADR-005 Phase 2).
Builds and refreshes the capability manifest from multiple sources.
"""
import json
from datetime import datetime
from pathlib import Path

from . import DESKTOP, LOGS_DIR


def scan_capabilities(manifest_file, run_count, observe_fn) -> None:
    """Build/refresh the capability manifest.

    Composes existing data sources:
      - pip list → installed packages
      - rudy/ directory → available modules
      - agent-domains.json → skills, connectors, scheduled tasks
      - research-capability.json → existing package audit (from ObsolescenceMonitor)

    Only rebuilds every 4th run (~hourly) unless forced.

    Args:
        manifest_file: Path object or string for the manifest JSON file.
        run_count: Current run count (for the every-4th-run check).
        observe_fn: Callable to report observations. Called with (category, message).
    """
    manifest_file = Path(manifest_file)

    if run_count % 4 != 0 and manifest_file.exists():
        return  # Reuse cached manifest

    try:
        manifest = {
            "generated": datetime.now().isoformat(),
            "version": "1.0",
            "modules": [],
            "packages": [],
            "skills": [],
            "connectors": [],
            "scheduled_tasks": [],
            "agents": [],
            "user_apps": [],
        }

        # 1. Scan rudy/ modules
        rudy_dir = DESKTOP / "rudy"
        if rudy_dir.is_dir():
            for f in sorted(rudy_dir.glob("*.py")):
                if f.name.startswith("_"):
                    continue
                manifest["modules"].append({
                    "name": f.stem,
                    "path": f"rudy/{f.name}",
                    "size_kb": round(f.stat().st_size / 1024, 1),
                })
            # Also scan rudy/tools/
            tools_dir = rudy_dir / "tools"
            if tools_dir.is_dir():
                for f in sorted(tools_dir.glob("*.py")):
                    if f.name.startswith("_"):
                        continue
                    manifest["modules"].append({
                        "name": f"tools/{f.stem}",
                        "path": f"rudy/tools/{f.name}",
                        "size_kb": round(f.stat().st_size / 1024, 1),
                    })

        # 2. Read agent-domains.json for skills, connectors, tasks
        domains_file = rudy_dir / "config" / "agent-domains.json"
        if domains_file.exists():
            try:
                domains = json.loads(domains_file.read_text())
                all_skills = set()
                all_connectors = set()
                all_tasks = set()
                for domain in domains.get("domains", {}).values():
                    for s in domain.get("cowork_skills", []):
                        all_skills.add(s)
                    for c in domain.get("connectors", []):
                        all_connectors.add(c)
                    for t in domain.get("scheduled_tasks", []):
                        all_tasks.add(t)
                manifest["skills"] = sorted(all_skills)
                manifest["connectors"] = sorted(all_connectors)
                manifest["scheduled_tasks"] = sorted(all_tasks)
            except Exception:
                pass

        # 3. Read installed packages from existing research-capability.json
        cap_file = LOGS_DIR / "research-capability.json"
        if cap_file.exists():
            try:
                cap = json.loads(cap_file.read_text())
                pkgs = cap.get("python_packages", [])
                if isinstance(pkgs, list):
                    manifest["packages"] = [
                        p if isinstance(p, str) else p.get("name", str(p))
                        for p in pkgs[:200]
                    ]
            except Exception:
                pass

        # 4. Scan agents
        agents_dir = DESKTOP / "rudy" / "agents"
        if agents_dir.is_dir():
            for f in sorted(agents_dir.glob("*.py")):
                if f.name.startswith("_") or f.name in ("runner.py", "orchestrator.py", "workflow_engine.py"):
                    continue
                manifest["agents"].append(f.stem)

        # 5. Scan user apps
        apps_dir = DESKTOP / "user-apps"
        if apps_dir.is_dir():
            for f in sorted(apps_dir.glob("*.cmd")):
                manifest["user_apps"].append(f.stem)

        # Write manifest
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        observe_fn("capabilities",
            f"Manifest updated: {len(manifest['modules'])} modules, "
            f"{len(manifest['packages'])} packages, "
            f"{len(manifest['skills'])} skills, "
            f"{len(manifest['agents'])} agents")

    except Exception as e:
        observe_fn("capability_error", f"Manifest scan failed: {e}")
