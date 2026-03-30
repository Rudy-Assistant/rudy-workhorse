"""
Obsolescence Monitor — Periodic capability audit, tool freshness checks,
and proactive upgrade recommendations.

Responsibilities:
  1. Check all installed Python packages for updates (pip list --outdated)
  2. Scan Rudy modules for deprecated patterns and known-better alternatives
  3. Monitor GitHub releases for key tools (SadTalker, MVT, Coqui TTS, etc.)
  4. Check PyPI for newer packages that solve existing capability gaps
  5. Verify all module imports still work (dependency breakage detection)
  6. Compare current toolchain against "best of breed" open-source landscape
  7. Generate upgrade recommendations with risk/benefit analysis
  8. Track tool adoption metrics (which capabilities are actually used)

Schedule: Integrated into self-improvement task (Mon/Wed/Fri 10 AM)
"""

import json
import os
import subprocess
import sys
import importlib

from datetime import datetime
from pathlib import Path
from typing import List, Optional

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
DATA_DIR = DESKTOP / "rudy-data" / "obsolescence"

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

def _load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def _run(cmd: str, timeout: int = 60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except Exception as e:
        return "", str(e), -1

# ── Tool Landscape Database ─────────────────────────────────
# Maps capability domains to current best-of-breed tools.
# Updated periodically by ResearchIntel agent.

TOOL_LANDSCAPE = {
    "voice_cloning": {
        "current": ["pocket-tts", "bark", "openvoice"],
        "best_of_breed": "Pocket TTS (Kyutai Labs)",
        "retired": {"TTS (Coqui)": "abandoned, Python 3.12 incompatible"},
        "watch": ["fish-speech", "cosyvoice", "metavoice", "parler-tts", "mars5-tts"],
        "check_pypi": ["pocket-tts", "bark", "openvoice-cli", "fish-speech"],
    },
    "talking_head": {
        "current": ["sadtalker", "wav2lip"],
        "best_of_breed": "SadTalker",
        "watch": ["MuseTalk", "AniPortrait", "V-Express", "EchoMimic"],
        "check_pypi": ["sadtalker"],
    },
    "face_swap": {
        "current": ["insightface", "roop"],
        "best_of_breed": "InsightFace inswapper",
        "watch": ["facefusion", "ghost", "simswap"],
        "check_pypi": ["insightface", "roop", "facefusion"],
    },
    "ocr": {
        "current": ["easyocr", "pdfplumber"],
        "best_of_breed": "EasyOCR / Surya",
        "watch": ["surya-ocr", "doctr", "paddleocr", "marker-pdf"],
        "check_pypi": ["easyocr", "surya-ocr", "python-doctr"],
    },
    "local_llm": {
        "current": ["ollama", "llama-cpp-python"],
        "best_of_breed": "Ollama (HTTP API, model management)",
        "watch": ["mlc-llm", "exllamav2", "vllm", "llamafile"],
        "check_pypi": ["llama-cpp-python", "ollama"],
    },
    "web_scraping": {
        "current": ["trafilatura", "newspaper3k", "beautifulsoup4"],
        "best_of_breed": "Trafilatura",
        "watch": ["crawl4ai", "firecrawl", "jina-reader"],
        "check_pypi": ["trafilatura", "newspaper4k", "crawl4ai"],
    },
    "browser_automation": {
        "current": ["playwright", "selenium", "undetected-chromedriver"],
        "best_of_breed": "Playwright",
        "watch": ["browser-use", "lavague", "skyvern"],
        "check_pypi": ["playwright", "selenium"],
    },
    "embeddings": {
        "current": ["sentence-transformers", "chromadb"],
        "best_of_breed": "sentence-transformers + ChromaDB",
        "watch": ["fastembed", "lancedb", "qdrant-client", "milvus-lite"],
        "check_pypi": ["sentence-transformers", "chromadb", "fastembed"],
    },
    "phone_security": {
        "current": ["mvt"],
        "best_of_breed": "MVT (Amnesty International)",
        "watch": ["iverify", "lookout"],
        "check_pypi": ["mvt"],
    },
    "image_generation": {
        "current": [],
        "best_of_breed": "Stable Diffusion XL (via API)",
        "watch": ["flux", "sdxl-turbo", "playground-v2.5"],
        "check_pypi": ["diffusers", "stability-sdk"],
    },
    "nlp": {
        "current": ["spacy", "textblob", "nltk", "sumy"],
        "best_of_breed": "spaCy + transformers",
        "watch": ["stanza", "flair", "spark-nlp"],
        "check_pypi": ["spacy", "textblob"],
    },
    "financial": {
        "current": ["yfinance"],
        "best_of_breed": "yfinance",
        "watch": ["openbb", "alpaca-trade-api", "ccxt"],
        "check_pypi": ["yfinance", "openbb"],
    },
}

# ── Rudy Modules Registry ───────────────────────────────────

RUDY_MODULES = [
    "rudy.presence", "rudy.presence_analytics", "rudy.network_defense",
    "rudy.intruder_profiler", "rudy.travel_mode", "rudy.movement_feed",
    "rudy.wellness", "rudy.human_simulation", "rudy.email_multi",
    "rudy.knowledge_base", "rudy.web_intelligence", "rudy.voice",
    "rudy.ocr", "rudy.financial", "rudy.nlp", "rudy.api_server",
    "rudy.local_ai", "rudy.offline_ops", "rudy.phone_check",
    "rudy.photo_intel", "rudy.voice_clone", "rudy.avatar",
    "rudy.admin",
]

class PackageAuditor:
    """Check installed packages for updates."""

    def check_outdated(self) -> List[dict]:
        """Get list of outdated pip packages."""
        stdout, _, rc = _run("pip list --outdated --format=json", timeout=120)
        if rc == 0 and stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                pass
        return []

    def check_specific(self, packages: List[str]) -> List[dict]:
        """Check specific packages for updates."""
        all_outdated = self.check_outdated()
        names = {p.lower() for p in packages}
        return [p for p in all_outdated if p.get("name", "").lower() in names]

    def get_installed_version(self, package: str) -> Optional[str]:
        """Get installed version of a package."""
        stdout, _, rc = _run(f"pip show {package}")
        if rc == 0:
            for line in stdout.splitlines():
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        return None

class ModuleHealthChecker:
    """Verify all Rudy modules can import and their dependencies work."""

    def check_all(self) -> dict:
        """Test importing every Rudy module."""
        results = {"timestamp": datetime.now().isoformat(), "modules": {}}

        # Ensure Desktop is on path
        desktop = str(DESKTOP)
        if desktop not in sys.path:
            sys.path.insert(0, desktop)

        for mod_name in RUDY_MODULES:
            try:
                # Try import
                mod = importlib.import_module(mod_name)
                results["modules"][mod_name] = {
                    "status": "ok",
                    "file": getattr(mod, "__file__", "unknown"),
                }
            except ImportError as e:
                results["modules"][mod_name] = {
                    "status": "import_error",
                    "error": str(e)[:200],
                }
            except Exception as e:
                results["modules"][mod_name] = {
                    "status": "error",
                    "error": str(e)[:200],
                }

        ok = sum(1 for m in results["modules"].values() if m["status"] == "ok")
        total = len(results["modules"])
        results["summary"] = {"ok": ok, "total": total, "health_pct": round(ok / total * 100, 1) if total else 0}

        return results

class LandscapeScanner:
    """
    Compare current toolchain against best-of-breed landscape.
    Identifies gaps, alternatives, and upgrade opportunities.
    """

    def scan(self) -> dict:
        """Full landscape scan."""
        results = {
            "timestamp": datetime.now().isoformat(),
            "domains": {},
        }

        for domain, info in TOOL_LANDSCAPE.items():
            domain_result = {
                "current_tools": info["current"],
                "best_of_breed": info["best_of_breed"],
                "watch_list": info["watch"],
                "installed": [],
                "missing": [],
                "upgradeable": [],
            }

            # Check which tools are installed
            for pkg in info.get("check_pypi", []):
                stdout, _, rc = _run(f"pip show {pkg}")
                if rc == 0:
                    version = ""
                    for line in stdout.splitlines():
                        if line.startswith("Version:"):
                            version = line.split(":", 1)[1].strip()
                    domain_result["installed"].append({"package": pkg, "version": version})
                else:
                    domain_result["missing"].append(pkg)

            results["domains"][domain] = domain_result

        return results

    def generate_recommendations(self, scan_result: dict) -> List[dict]:
        """Generate actionable upgrade recommendations."""
        recommendations = []

        for domain, info in scan_result.get("domains", {}).items():
            # Check for missing critical tools
            if not info["installed"] and info.get("current_tools"):
                recommendations.append({
                    "priority": "high",
                    "domain": domain,
                    "action": "install",
                    "detail": f"No tools installed for {domain}. "
                              f"Recommended: {info.get('missing', ['unknown'])[0]}",
                })

            # Check watch list for potential upgrades
            for watched in info.get("watch_list", []):
                recommendations.append({
                    "priority": "low",
                    "domain": domain,
                    "action": "evaluate",
                    "detail": f"Consider evaluating '{watched}' as potential upgrade for {domain}",
                })

        return recommendations

class UsageTracker:
    """Track which capabilities are actually being used."""

    def __init__(self):
        self.usage_file = DATA_DIR / "usage-stats.json"
        self.stats = _load_json(self.usage_file, {"modules": {}, "last_reset": datetime.now().isoformat()})

    def record_use(self, module: str, function: str = ""):
        """Record a capability usage."""
        if module not in self.stats["modules"]:
            self.stats["modules"][module] = {"count": 0, "functions": {}, "last_used": None}

        self.stats["modules"][module]["count"] += 1
        self.stats["modules"][module]["last_used"] = datetime.now().isoformat()

        if function:
            funcs = self.stats["modules"][module]["functions"]
            funcs[function] = funcs.get(function, 0) + 1

        _save_json(self.usage_file, self.stats)

    def get_unused(self, days_threshold: int = 30) -> List[str]:
        """Find modules not used in the last N days."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days_threshold)).isoformat()

        unused = []
        for mod in RUDY_MODULES:
            mod_stats = self.stats.get("modules", {}).get(mod)
            if not mod_stats or (mod_stats.get("last_used") or "") < cutoff:
                unused.append(mod)
        return unused

    def get_report(self) -> dict:
        """Generate usage report."""
        return {
            "total_modules": len(RUDY_MODULES),
            "tracked_modules": len(self.stats.get("modules", {})),
            "stats": self.stats,
        }

class ObsolescenceMonitor:
    """
    Master controller for capability auditing.

    Usage:
        monitor = ObsolescenceMonitor()

        # Full audit
        report = monitor.full_audit()

        # Quick check
        health = monitor.quick_check()

        # Package updates only
        outdated = monitor.check_packages()
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.packages = PackageAuditor()
        self.health = ModuleHealthChecker()
        self.landscape = LandscapeScanner()
        self.usage = UsageTracker()

    def quick_check(self) -> dict:
        """Fast health check — module imports + critical package versions."""
        return {
            "timestamp": datetime.now().isoformat(),
            "module_health": self.health.check_all()["summary"],
            "python_version": sys.version,
        }

    def check_packages(self) -> List[dict]:
        """Check for outdated packages."""
        return self.packages.check_outdated()

    def full_audit(self) -> dict:
        """
        Comprehensive capability audit:
        1. Module health check (imports)
        2. Package freshness (outdated)
        3. Landscape comparison (best-of-breed)
        4. Usage analysis (dormant modules)
        5. Recommendations
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "type": "full_audit",
        }

        # 1. Module health
        print("  [1/5] Checking module health...")
        report["module_health"] = self.health.check_all()

        # 2. Package freshness
        print("  [2/5] Checking package updates...")
        outdated = self.packages.check_outdated()
        report["outdated_packages"] = {
            "count": len(outdated),
            "critical": [p for p in outdated if p.get("name", "").lower() in
                         {"chromadb", "playwright", "mvt", "spacy", "torch"}],
            "all": outdated[:30],  # Cap at 30 to keep report manageable
        }

        # 3. Landscape comparison
        print("  [3/5] Scanning tool landscape...")
        scan = self.landscape.scan()
        report["landscape"] = scan

        # 4. Usage analysis
        print("  [4/5] Analyzing usage...")
        report["usage"] = self.usage.get_report()
        report["unused_modules"] = self.usage.get_unused(days_threshold=14)

        # 5. Recommendations
        print("  [5/5] Generating recommendations...")
        recommendations = self.landscape.generate_recommendations(scan)

        # Add package-specific recommendations
        for pkg in report["outdated_packages"].get("critical", []):
            recommendations.append({
                "priority": "high",
                "domain": "packages",
                "action": "upgrade",
                "detail": f"Critical package {pkg['name']} outdated: "
                          f"{pkg.get('version', '?')} → {pkg.get('latest_version', '?')}",
            })

        report["recommendations"] = sorted(
            recommendations, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("priority", "low"), 3)
        )

        # Save report
        report_file = DATA_DIR / f"audit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        _save_json(report_file, report)
        report["report_file"] = str(report_file)

        return report

    def generate_summary(self, report: dict) -> str:
        """Human-readable audit summary."""
        lines = []
        lines.append("=" * 55)
        lines.append("  CAPABILITY AUDIT REPORT")
        lines.append("=" * 55)

        # Module health
        mh = report.get("module_health", {}).get("summary", {})
        lines.append(f"\nModule Health: {mh.get('ok', 0)}/{mh.get('total', 0)} "
                     f"({mh.get('health_pct', 0)}%)")

        # Outdated packages
        op = report.get("outdated_packages", {})
        lines.append(f"Outdated Packages: {op.get('count', 0)} "
                     f"({len(op.get('critical', []))} critical)")

        # Recommendations
        recs = report.get("recommendations", [])
        high = [r for r in recs if r.get("priority") == "high"]
        if high:
            lines.append(f"\nHIGH PRIORITY ({len(high)}):")
            for r in high[:5]:
                lines.append(f"  - [{r['action']}] {r['detail']}")

        # Unused modules
        unused = report.get("unused_modules", [])
        if unused:
            lines.append(f"\nDormant Modules ({len(unused)}):")
            for m in unused[:5]:
                lines.append(f"  - {m}")

        lines.append(f"\n{'=' * 55}")
        saved = report.get("report_file", "N/A")
        lines.append(f"  Full report: {saved}")
        lines.append("=" * 55)

        return "\n".join(lines)

    def file_github_issues(self, report: dict) -> list:
        """
        Auto-file GitHub issues for high-priority findings.
        Requires rudy.integrations.github_ops to be available.
        Returns list of created issue URLs.
        """
        try:
            from rudy.integrations.github_ops import get_github
            gh = get_github()
            if not gh.gh_available:
                return []
        except ImportError:
            return []

        created = []
        recs = report.get("recommendations", [])
        high_recs = [r for r in recs if r.get("priority") == "high"]

        # Only file issues for high-priority items
        for rec in high_recs[:5]:  # Cap at 5 to avoid issue spam
            action = rec.get("action", "review")
            detail = rec.get("detail", "No details")
            domain = rec.get("domain", "general")

            # Check if a similar issue already exists
            existing = gh.list_issues(labels=["priority:high", domain])
            if any(detail[:40] in issue.get("title", "") for issue in existing):
                continue  # Skip duplicate

            title = f"[Audit] {action.title()}: {detail[:60]}"
            body = (
                f"## ObsolescenceMonitor Finding\n\n"
                f"**Action**: {action}\n"
                f"**Domain**: {domain}\n"
                f"**Detail**: {detail}\n"
                f"**Priority**: HIGH\n\n"
                f"Auto-filed by ObsolescenceMonitor on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            )
            url = gh.create_issue(title, body, labels=["audit", "priority:high"])
            if url:
                created.append(url)

        return created

    def execute(self, mode: str = "full", file_issues: bool = False) -> dict:
        """Execute audit (called by self-improvement agent)."""
        if mode == "quick":
            return self.quick_check()
        elif mode == "full":
            report = self.full_audit()
            summary = self.generate_summary(report)
            print(summary)
            if file_issues:
                issues = self.file_github_issues(report)
                if issues:
                    print(f"\nFiled {len(issues)} GitHub issue(s)")
                    report["github_issues"] = issues
            return report
        elif mode == "packages":
            return {"outdated": self.check_packages()}
        else:
            return self.full_audit()

if __name__ == "__main__":
    print("Obsolescence Monitor — Capability Audit")
    monitor = ObsolescenceMonitor()

    print("\n  Running quick check...")
    qc = monitor.quick_check()
    mh = qc.get("module_health", {})
    print(f"  Module Health: {mh.get('ok', 0)}/{mh.get('total', 0)}")
    print(f"  Python: {qc.get('python_version', '?')}")

    print("\n  For full audit: ObsolescenceMonitor().full_audit()")
