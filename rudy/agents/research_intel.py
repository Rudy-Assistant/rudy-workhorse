"""
ResearchIntel — Intelligence & Learning Agent.
Manages RSS feed aggregation, tool discovery, and capability assessment.
Wraps existing workhorse-research-feed.py functionality and adds
proactive recommendation logic.
"""
import os
import json
import subprocess
from datetime import datetime
from . import AgentBase, DESKTOP, LOGS_DIR


class ResearchIntel(AgentBase):
    name = "research_intel"
    version = "1.0"

    FEED_CONFIG = LOGS_DIR / "research-feeds.json"
    CAPABILITY_FILE = LOGS_DIR / "research-capability.json"

    def run(self, **kwargs):
        mode = kwargs.get("mode", "digest")

        if mode in ("digest", "full"):
            self._generate_digest()

        if mode in ("capability", "full"):
            self._audit_capabilities()

        if mode in ("recommend", "full"):
            self._generate_recommendations()

        self.summarize(f"Research cycle complete (mode={mode})")

    def _run_cmd(self, cmd, timeout=60):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout.strip()
        except:
            return False, ""

    def _generate_digest(self):
        """Run the existing research feed script."""
        self.log.info("Generating research digest...")
        feed_script = DESKTOP / "scripts" / "workhorse" / "workhorse-research-feed.py"
        if not feed_script.exists():
            feed_script = DESKTOP / "workhorse-research-feed.py"

        if feed_script.exists():
            python = r"C:\Users\C\AppData\Local\Programs\Python\Python312\python.exe"
            ok, out = self._run_cmd(f'"{python}" "{feed_script}"', timeout=120)
            if ok:
                self.action("Generated daily research digest")
                self.log.info(f"  Digest output: {out[:200]}")
            else:
                self.warn(f"Research feed script failed: {out[:200]}")
        else:
            self.warn("Research feed script not found")

    def _audit_capabilities(self):
        """Inventory what tools and integrations are available."""
        self.log.info("Auditing capabilities...")
        capabilities = {
            "timestamp": datetime.now().isoformat(),
            "python_packages": [],
            "mcp_servers": [],
            "scheduled_tasks": [],
            "recommendations": [],
        }

        # Check installed Python packages
        ok, out = self._run_cmd("pip list --format=json", timeout=30)
        if ok:
            try:
                packages = json.loads(out)
                capabilities["python_packages"] = [
                    {"name": p["name"], "version": p["version"]}
                    for p in packages
                ]
                self.log.info(f"  {len(packages)} Python packages installed")
            except:
                pass

        # Check scheduled tasks
        ok, out = self._run_cmd('schtasks /query /fo CSV /nh')
        if ok:
            tasks = [line.split(",")[0].strip('"') for line in out.splitlines() if line.strip()]
            capabilities["scheduled_tasks"] = tasks
            self.log.info(f"  {len(tasks)} scheduled tasks found")

        # Write capability file
        try:
            with open(self.CAPABILITY_FILE, "w", encoding="utf-8") as f:
                json.dump(capabilities, f, indent=2)
            self.action("Updated capability inventory")
        except Exception as e:
            self.warn(f"Failed to write capability file: {e}")

    def _generate_recommendations(self):
        """Analyze capabilities and suggest improvements."""
        self.log.info("Generating recommendations...")
        recommendations = []

        # Check if key tools are missing
        ok, out = self._run_cmd("pip list --format=json", timeout=30)
        if ok:
            try:
                packages = {p["name"].lower() for p in json.loads(out)}
            except:
                packages = set()

            desired = {
                "httpx": "Modern async HTTP client",
                "rich": "Beautiful terminal output",
                "schedule": "In-process task scheduling",
                "watchdog": "File system monitoring",
                "psutil": "System resource monitoring",
            }
            for pkg, reason in desired.items():
                if pkg not in packages:
                    recommendations.append(f"Install {pkg}: {reason}")

        if recommendations:
            self.status["recommendations"] = recommendations
            self.log.info(f"  {len(recommendations)} recommendations generated")

    def _run_web_intelligence(self):
        """Check job boards and extract new articles."""
        try:
            from rudy.web_intelligence import WebIntelligence
            wi = WebIntelligence()
            jobs = wi.search_jobs()
            changes = wi.check_watches()
            self.action(f"Web intel: {len(jobs)} new jobs, {len(changes)} page changes")
            return {"new_jobs": len(jobs), "page_changes": len(changes)}
        except Exception as e:
            self.warn(f"Web intelligence failed: {e}")
            return {"error": str(e)[:100]}

    def _run_nlp_analysis(self):
        """NLP analysis on latest research digest."""
        try:
            from rudy.nlp import NLP
            nlp_engine = NLP()
            import glob
            digests = sorted(glob.glob(str(LOGS_DIR / "research-digest-*.md")))
            if digests:
                with open(digests[-1]) as f:
                    text = f.read()[:3000]
                keywords = nlp_engine.summarizer.extract_keywords(text, top_n=15)
                sentiment = nlp_engine.get_sentiment(text[:500])
                self.action(f"NLP: {len(keywords)} keywords, sentiment={sentiment.get('label')}")
                return {"keywords": keywords, "sentiment": sentiment.get("label")}
            return {"status": "no digests found"}
        except Exception as e:
            self.warn(f"NLP analysis failed: {e}")
            return {"error": str(e)[:100]}


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    agent = ResearchIntel()
    agent.execute(mode=mode)
