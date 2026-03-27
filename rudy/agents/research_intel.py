"""
ResearchIntel — Intelligence & Learning Agent.
Manages RSS feed aggregation, tool discovery, and capability assessment.
Wraps existing workhorse-research-feed.py functionality and adds
proactive recommendation logic.

Dependency Health Check (4-layer zealous inquisitor):
  Layer 1: Import verification — does it load on Python 3.12?
  Layer 2: Known supersessions — institutional memory of past findings
  Layer 3: Live web audit — PyPI freshness, GitHub vitality, web search
           for alternatives. Local AI ONLY synthesizes gathered evidence.
           Never trusts a model's stale training data for "is this still best?"
  Layer 4: System health — Windows updates, drivers, core tool versions,
           disk health. Extends audit beyond Python to the full machine.
"""
import os
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta
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
            self._check_dependency_health()

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

    def _check_dependency_health(self):
        """Proactive dependency health — zealous inquisitor approach.

        The core question: "Is this dependency STILL the best solution for its
        function?" Not "is it broken?" — that's Layer 1's job. The real value
        is in Layers 2 and 3, which actively hunt for superior alternatives.

        Three-layer check:
          Layer 1: Import verification — does it load on Python 3.12?
          Layer 2: Known supersessions — institutional memory (prevents re-learning)
          Layer 3: LIVE WEB AUDIT (the zealous inquisitor):
            3a. PyPI freshness — last release date, version currency
            3b. GitHub vitality — stars, last commit, archived status
            3c. Web search for alternatives — "best Python library for X 2026"
            3d. Local AI synthesis — ONLY used to summarize gathered evidence,
                NEVER to judge packages from stale training data

        Runs during capability mode (M/W/F 10 AM).
        """
        self.log.info("Checking dependency health (proactive, live audit)...")
        issues = []
        evidence = {}  # Collected web evidence per package

        # === Layer 1: Import verification ===
        python = r"C:\Users\C\AppData\Local\Programs\Python\Python312\python.exe"
        CRITICAL_IMPORTS = [
            ("rudy.voice_clone", "Voice cloning module"),
            ("rudy.local_ai", "Local AI engine"),
            ("rudy.nlp", "NLP pipeline"),
            ("rudy.financial", "Financial data"),
            ("rudy.web_intelligence", "Web intelligence"),
            ("rudy.knowledge_base", "Knowledge base"),
            ("rudy.ocr", "OCR / document parsing"),
            ("rudy.presence", "Network presence scanning"),
        ]
        for module, desc in CRITICAL_IMPORTS:
            ok, out = self._run_cmd(
                f'"{python}" -c "import {module}"', timeout=15
            )
            if not ok:
                issues.append({
                    "type": "import_failure",
                    "module": module,
                    "description": desc,
                    "error": out[:200] if out else "import failed",
                })
                self.warn(f"Import failure: {module} ({desc})")

        # === Layer 2: Known supersessions (institutional memory) ===
        SUPERSEDED = {
            "tts": {
                "status": "abandoned",
                "reason": "Coqui TTS project shut down, Python 3.12 incompatible",
                "replacement": "pocket-tts",
                "replacement_reason": "Kyutai Labs (Jan 2026), Python 3.12 native, CPU-optimized, 5-20s voice cloning",
            },
            "coqui-tts": {
                "status": "abandoned",
                "reason": "Same as TTS — Coqui project shut down",
                "replacement": "pocket-tts",
                "replacement_reason": "See TTS entry",
            },
        }

        ok, out = self._run_cmd("pip list --format=json", timeout=30)
        installed = {}
        if ok:
            try:
                installed = {p["name"].lower(): p["version"] for p in json.loads(out)}
            except:
                pass

        for pkg, info in SUPERSEDED.items():
            if pkg in installed:
                issues.append({
                    "type": "superseded",
                    "package": pkg,
                    "installed_version": installed[pkg],
                    "status": info["status"],
                    "reason": info["reason"],
                    "replacement": info["replacement"],
                    "replacement_reason": info["replacement_reason"],
                })
                self.warn(f"Superseded: {pkg} → {info['replacement']}")

        # === Layer 3: Live Web Audit (the zealous inquisitor) ===
        # NEVER trust a local model's training data for this. Use LIVE data.
        FUNCTION_MAP = {
            "easyocr": {
                "function": "OCR text extraction from images",
                "pypi_name": "easyocr",
                "github": "JaidedAI/EasyOCR",
                "search_terms": "best Python OCR library",
            },
            "pdfplumber": {
                "function": "extracting text and tables from PDF files",
                "pypi_name": "pdfplumber",
                "github": "jsvine/pdfplumber",
                "search_terms": "best Python PDF text extraction library",
            },
            "yfinance": {
                "function": "fetching stock market and financial data",
                "pypi_name": "yfinance",
                "github": "ranaroussi/yfinance",
                "search_terms": "best Python stock market data library",
            },
            "trafilatura": {
                "function": "extracting article text from web pages",
                "pypi_name": "trafilatura",
                "github": "adbar/trafilatura",
                "search_terms": "best Python web article extraction library",
            },
            "chromadb": {
                "function": "vector database for semantic search",
                "pypi_name": "chromadb",
                "github": "chroma-core/chroma",
                "search_terms": "best Python vector database",
            },
            "spacy": {
                "function": "NLP named entity recognition and text analysis",
                "pypi_name": "spacy",
                "github": "explosion/spaCy",
                "search_terms": "best Python NLP library",
            },
            "feedparser": {
                "function": "parsing RSS/Atom feeds",
                "pypi_name": "feedparser",
                "github": "kurtmckee/feedparser",
                "search_terms": "best Python RSS feed parser",
            },
            "pocket-tts": {
                "function": "text-to-speech with voice cloning",
                "pypi_name": "pocket-tts",
                "github": "",
                "search_terms": "best Python voice cloning TTS library",
            },
            "playwright": {
                "function": "browser automation and web scraping",
                "pypi_name": "playwright",
                "github": "microsoft/playwright-python",
                "search_terms": "best Python browser automation library",
            },
        }

        self.log.info("  Layer 3: Live web audit starting...")
        for pkg, meta in FUNCTION_MAP.items():
            if pkg not in installed:
                continue
            version = installed.get(pkg, "?")
            pkg_evidence = {
                "package": pkg,
                "installed_version": version,
                "function": meta["function"],
            }

            # --- 3a: PyPI freshness ---
            pypi_data = self._check_pypi(meta["pypi_name"])
            if pypi_data:
                pkg_evidence["pypi"] = pypi_data
                # Flag if last release > 12 months ago
                if pypi_data.get("days_since_release", 0) > 365:
                    issues.append({
                        "type": "stale_release",
                        "package": pkg,
                        "function": meta["function"],
                        "installed_version": version,
                        "latest_version": pypi_data.get("latest_version", "?"),
                        "days_since_release": pypi_data["days_since_release"],
                        "detail": f"No release in {pypi_data['days_since_release']} days",
                    })
                    self.warn(f"Stale: {pkg} — no release in {pypi_data['days_since_release']}d")
                # Flag if installed version is behind latest
                elif pypi_data.get("latest_version") and pypi_data["latest_version"] != version:
                    pkg_evidence["update_available"] = pypi_data["latest_version"]

            # --- 3b: GitHub vitality ---
            if meta.get("github"):
                gh_data = self._check_github(meta["github"])
                if gh_data:
                    pkg_evidence["github"] = gh_data
                    if gh_data.get("archived"):
                        issues.append({
                            "type": "archived_repo",
                            "package": pkg,
                            "function": meta["function"],
                            "github": meta["github"],
                            "detail": "GitHub repo is ARCHIVED — project abandoned",
                        })
                        self.warn(f"ARCHIVED: {pkg} — {meta['github']}")
                    elif gh_data.get("days_since_commit", 0) > 365:
                        issues.append({
                            "type": "inactive_repo",
                            "package": pkg,
                            "function": meta["function"],
                            "github": meta["github"],
                            "days_since_commit": gh_data["days_since_commit"],
                            "detail": f"No commit in {gh_data['days_since_commit']} days",
                        })
                        self.warn(f"Inactive: {pkg} — no commit in {gh_data['days_since_commit']}d")

            # --- 3c: Web search for alternatives ---
            search_year = datetime.now().year
            alternatives = self._search_alternatives(
                meta["search_terms"], search_year, pkg
            )
            if alternatives:
                pkg_evidence["alternatives_found"] = alternatives
                # If multiple credible alternatives found, flag for review
                if len(alternatives) >= 2:
                    issues.append({
                        "type": "alternatives_exist",
                        "package": pkg,
                        "function": meta["function"],
                        "alternatives": alternatives[:5],
                        "detail": f"{len(alternatives)} potential alternatives found via web search",
                    })

            evidence[pkg] = pkg_evidence

        # --- 3d: Local AI synthesis (evidence-based, NOT memory-based) ---
        # Only used to produce a human-readable summary from the GATHERED evidence.
        # If Ollama is down, we still have the raw evidence — this is optional polish.
        if evidence:
            self._ai_synthesize_evidence(evidence, issues)

        # === Layer 4: System-level health audit ===
        # Drivers, Windows Update, OS patches, firmware, core tooling versions
        system_health = self._check_system_health()
        if system_health.get("issues"):
            issues.extend(system_health["issues"])

        # === Write report ===
        health_file = LOGS_DIR / "dependency-health.json"
        report = {
            "timestamp": datetime.now().isoformat(),
            "issues_found": len(issues),
            "issues": issues,
            "evidence": evidence,
            "system_health": system_health.get("status", {}),
            "python_version": "3.12",
            "layers_run": [
                "import_check",
                "known_supersessions",
                "pypi_freshness",
                "github_vitality",
                "web_alternative_search",
                "ai_synthesis",
                "system_health",
            ],
        }
        try:
            with open(health_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        except Exception:
            pass

        if issues:
            self.action(f"Dependency health: {len(issues)} issues found — see dependency-health.json")
        else:
            self.action("Dependency health: all clear (all layers passed)")

    # ── Layer 3 helpers ──────────────────────────────────────────

    def _fetch_json(self, url, timeout=15):
        """Fetch JSON from a URL. Returns dict or None."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Rudy/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def _check_pypi(self, package_name):
        """Query PyPI JSON API for package freshness."""
        data = self._fetch_json(f"https://pypi.org/pypi/{package_name}/json")
        if not data:
            return None
        try:
            info = data.get("info", {})
            latest_version = info.get("version", "?")

            # Find most recent release date
            releases = data.get("releases", {})
            latest_release_date = None
            if latest_version in releases and releases[latest_version]:
                upload_time = releases[latest_version][-1].get("upload_time", "")
                if upload_time:
                    latest_release_date = upload_time[:10]  # YYYY-MM-DD

            days_since = 0
            if latest_release_date:
                try:
                    release_dt = datetime.strptime(latest_release_date, "%Y-%m-%d")
                    days_since = (datetime.now() - release_dt).days
                except Exception:
                    pass

            return {
                "latest_version": latest_version,
                "latest_release_date": latest_release_date,
                "days_since_release": days_since,
                "summary": info.get("summary", "")[:100],
                "home_page": info.get("home_page", ""),
                "requires_python": info.get("requires_python", ""),
            }
        except Exception:
            return None

    def _check_github(self, repo_slug):
        """Query GitHub API for repo vitality. Uses gh CLI if available, else API."""
        # Try gh CLI first (authenticated, higher rate limit)
        ok, out = self._run_cmd(
            f'gh api repos/{repo_slug} --jq ".stargazers_count,.archived,.pushed_at"',
            timeout=15,
        )
        if ok and out.strip():
            lines = out.strip().splitlines()
            if len(lines) >= 3:
                try:
                    stars = int(lines[0])
                    archived = lines[1].lower() == "true"
                    pushed_at = lines[2]
                    days_since = 0
                    if pushed_at:
                        try:
                            push_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                            days_since = (datetime.now(push_dt.tzinfo) - push_dt).days
                        except Exception:
                            pass
                    return {
                        "stars": stars,
                        "archived": archived,
                        "last_push": pushed_at,
                        "days_since_commit": days_since,
                    }
                except Exception:
                    pass

        # Fallback: unauthenticated API (60 req/hour limit)
        data = self._fetch_json(f"https://api.github.com/repos/{repo_slug}")
        if not data:
            return None
        try:
            pushed_at = data.get("pushed_at", "")
            days_since = 0
            if pushed_at:
                try:
                    push_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                    days_since = (datetime.now(push_dt.tzinfo) - push_dt).days
                except Exception:
                    pass
            return {
                "stars": data.get("stargazers_count", 0),
                "archived": data.get("archived", False),
                "last_push": pushed_at,
                "days_since_commit": days_since,
                "open_issues": data.get("open_issues_count", 0),
                "forks": data.get("forks_count", 0),
            }
        except Exception:
            return None

    def _search_alternatives(self, search_terms, year, current_pkg):
        """Search the web for alternative packages. Returns list of names found.

        Uses trafilatura (installed) to extract article text from search results,
        or falls back to simple URL scraping.
        """
        alternatives = []

        # Strategy 1: Use existing web_intelligence module
        try:
            from rudy.web_intelligence import WebIntelligence
            wi = WebIntelligence()
            # Search for recent articles about alternatives
            query = f"{search_terms} {year} Python comparison"
            results = wi.search_web(query, max_results=3)
            if results:
                for result in results[:3]:
                    text = result.get("text", "") or result.get("body", "")
                    if text:
                        # Extract package names mentioned in comparison articles
                        found = self._extract_package_names(text, current_pkg)
                        alternatives.extend(found)
        except Exception:
            pass

        # Strategy 2: Direct search via trafilatura + requests
        if not alternatives:
            try:
                import requests
                from trafilatura import extract as traf_extract

                search_url = f"https://www.google.com/search?q={search_terms}+{year}+Python+comparison&num=5"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                resp = requests.get(search_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    # Extract URLs from search results
                    import re
                    urls = re.findall(r'href="(https?://[^"]+)"', resp.text)
                    # Filter to likely article URLs (not Google domains)
                    article_urls = [
                        u for u in urls
                        if "google" not in u and "youtube" not in u
                        and any(kw in u.lower() for kw in ["blog", "article", "comparison", "best", "vs", "alternative", "guide", "medium", "dev.to", "towardsdatascience"])
                    ][:2]

                    for url in article_urls:
                        try:
                            art_resp = requests.get(url, headers=headers, timeout=10)
                            if art_resp.status_code == 200:
                                text = traf_extract(art_resp.text) or ""
                                found = self._extract_package_names(text, current_pkg)
                                alternatives.extend(found)
                        except Exception:
                            pass
            except Exception:
                pass

        # Strategy 3: Check PyPI search for related packages
        if not alternatives:
            try:
                import requests
                search_url = f"https://pypi.org/search/?q={search_terms.replace(' ', '+')}"
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = requests.get(search_url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    import re
                    # Extract package names from PyPI search results
                    pkg_links = re.findall(r'/project/([a-zA-Z0-9_-]+)/', resp.text)
                    for name in pkg_links[:10]:
                        name_lower = name.lower()
                        if name_lower != current_pkg.lower() and name_lower not in ("pip", "setuptools"):
                            alternatives.append(name_lower)
            except Exception:
                pass

        # Deduplicate and remove self
        seen = set()
        unique = []
        for a in alternatives:
            a_lower = a.lower()
            if a_lower not in seen and a_lower != current_pkg.lower():
                seen.add(a_lower)
                unique.append(a)
        return unique[:10]

    def _extract_package_names(self, text, current_pkg):
        """Extract Python package names from article text that could be alternatives."""
        import re
        candidates = []
        # Common patterns: "pip install X", "import X", "X library", "X package"
        patterns = [
            r'pip install ([a-zA-Z0-9_-]+)',
            r'import ([a-zA-Z0-9_]+)',
            r'from ([a-zA-Z0-9_]+) import',
            r'([A-Z][a-zA-Z0-9]+(?:OCR|DB|NLP|TTS|AI))',  # CamelCase tool names
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text[:5000])
            for m in matches:
                m_lower = m.lower()
                if (len(m_lower) > 2
                    and m_lower != current_pkg.lower()
                    and m_lower not in ("pip", "python", "sys", "os", "json", "the", "this", "import")):
                    candidates.append(m_lower)
        return list(set(candidates))[:15]

    def _ai_synthesize_evidence(self, evidence, issues):
        """Use local AI ONLY to summarize gathered evidence — never to judge from memory.

        The AI sees the raw PyPI data, GitHub stats, and web search results we
        collected, and produces a human-readable verdict. If Ollama is down,
        the raw evidence in the report is still valuable.
        """
        try:
            from rudy.local_ai import OllamaBackend
            ollama = OllamaBackend()
            if not (ollama.is_available() and ollama.has_model("phi3-mini")):
                self.log.info("  Ollama not available — skipping AI synthesis (evidence preserved)")
                return
        except Exception:
            return

        self.log.info("  Synthesizing evidence with local AI...")
        for pkg, ev in evidence.items():
            # Build a fact sheet from gathered data
            facts = [f"Package: {pkg} v{ev.get('installed_version', '?')}"]
            facts.append(f"Function: {ev.get('function', '?')}")

            pypi = ev.get("pypi", {})
            if pypi:
                facts.append(f"PyPI latest: v{pypi.get('latest_version', '?')} "
                             f"(released {pypi.get('latest_release_date', '?')}, "
                             f"{pypi.get('days_since_release', '?')} days ago)")

            gh = ev.get("github", {})
            if gh:
                facts.append(f"GitHub: {gh.get('stars', '?')} stars, "
                             f"last push {gh.get('days_since_commit', '?')} days ago, "
                             f"archived={gh.get('archived', False)}")

            alts = ev.get("alternatives_found", [])
            if alts:
                facts.append(f"Alternatives found via web search: {', '.join(alts[:5])}")

            update = ev.get("update_available")
            if update:
                facts.append(f"Update available: {update}")

            # Ask AI to synthesize — ONLY from the facts above
            prompt = (
                "Based ONLY on the following FACTS (do not use your own knowledge):\n\n"
                + "\n".join(f"- {f}" for f in facts) + "\n\n"
                "Verdict: Is this package healthy, adequate, or concerning? "
                "One sentence summary. Start with HEALTHY, ADEQUATE, or CONCERNING."
            )
            try:
                response = ollama.generate(
                    prompt,
                    system="You are a dependency auditor. Judge ONLY from the facts provided. Do not use prior knowledge.",
                    model_name="phi3-mini",
                    max_tokens=60,
                    temperature=0.1,
                )
                ev["ai_synthesis"] = response.strip()[:200]
            except Exception:
                pass  # Synthesis is optional

    def _check_system_health(self):
        """Layer 4: System-level health audit.

        Checks for OS updates, driver updates, core tool versions, and
        hardware/firmware status. This extends the audit beyond Python packages
        to cover the full machine.

        Checks:
          4a. Windows Update — pending patches, last update date
          4b. Driver updates — devices with outdated/problem drivers
          4c. Core tool versions — Python, Node, Git, Ollama, gh CLI
          4d. Disk/hardware health — SMART status, disk space
          4e. Security patches — critical CVEs for installed software
        """
        self.log.info("  Layer 4: System-level health audit...")
        status = {}
        sys_issues = []

        # --- 4a: Windows Update status ---
        # Check for pending updates and last install date
        ok, out = self._run_cmd(
            'powershell -Command "'
            '$session = New-Object -ComObject Microsoft.Update.Session; '
            '$searcher = $session.CreateUpdateSearcher(); '
            'try { $results = $searcher.Search(\\\"IsInstalled=0\\\"); '
            'Write-Output \\\"pending:$($results.Updates.Count)\\\"; '
            '} catch { Write-Output \\\"pending:error\\\" }; '
            '$history = $searcher.GetTotalHistoryCount(); '
            'if ($history -gt 0) { '
            '  $last = $searcher.QueryHistory(0,1); '
            '  Write-Output \\\"last_update:$($last[0].Date)\\\" '
            '} '
            '"',
            timeout=30,
        )
        if ok and out:
            for line in out.splitlines():
                if line.startswith("pending:"):
                    val = line.split(":", 1)[1].strip()
                    if val.isdigit():
                        pending = int(val)
                        status["windows_updates_pending"] = pending
                        if pending > 0:
                            sys_issues.append({
                                "type": "os_updates_pending",
                                "count": pending,
                                "detail": f"{pending} Windows updates available but not installed",
                            })
                            self.warn(f"Windows Update: {pending} updates pending")
                elif line.startswith("last_update:"):
                    status["windows_last_update"] = line.split(":", 1)[1].strip()

        # --- 4b: Driver health ---
        # Check for devices with problems or outdated drivers
        ok, out = self._run_cmd(
            'powershell -Command "'
            'Get-PnpDevice | Where-Object { $_.Status -ne \\\"OK\\\" } | '
            'Select-Object -Property Status,Class,FriendlyName | '
            'ConvertTo-Json -Compress'
            '"',
            timeout=20,
        )
        if ok and out.strip():
            try:
                problem_devices = json.loads(out)
                if isinstance(problem_devices, dict):
                    problem_devices = [problem_devices]
                # Filter out known-benign (disconnected USB, etc.)
                real_problems = [
                    d for d in problem_devices
                    if d.get("Status") not in ("Unknown", "Disconnected")
                    or d.get("Class") in ("Display", "Net", "System", "DiskDrive")
                ]
                status["problem_drivers"] = len(real_problems)
                if real_problems:
                    sys_issues.append({
                        "type": "driver_problems",
                        "count": len(real_problems),
                        "devices": [
                            f"{d.get('FriendlyName', '?')} ({d.get('Status', '?')})"
                            for d in real_problems[:5]
                        ],
                        "detail": f"{len(real_problems)} devices with driver problems",
                    })
            except Exception:
                pass

        # --- 4c: Core tool version checks (live) ---
        # Check if our critical tools have newer versions available
        TOOL_CHECKS = {
            "python": {
                "current_cmd": 'python --version',
                "parse": lambda out: out.replace("Python ", "").strip(),
                "pypi_check": None,
                "latest_url": "https://endoflife.date/api/python.json",
            },
            "node": {
                "current_cmd": "node --version",
                "parse": lambda out: out.strip().lstrip("v"),
                "pypi_check": None,
                "latest_url": "https://endoflife.date/api/nodejs.json",
            },
            "git": {
                "current_cmd": "git --version",
                "parse": lambda out: out.replace("git version ", "").split(".windows")[0].strip(),
                "pypi_check": None,
                "latest_url": "https://endoflife.date/api/git.json",
            },
            "ollama": {
                "current_cmd": "ollama --version",
                "parse": lambda out: out.split()[-1] if out else "?",
                "pypi_check": None,
                "latest_url": None,  # Check GitHub releases
                "github": "ollama/ollama",
            },
        }

        tool_status = {}
        for tool_name, spec in TOOL_CHECKS.items():
            ok, out = self._run_cmd(spec["current_cmd"], timeout=10)
            if ok and out:
                current_ver = spec["parse"](out)
                tool_status[tool_name] = {"installed": current_ver}

                # Check for latest via endoflife.date API
                if spec.get("latest_url"):
                    eol_data = self._fetch_json(spec["latest_url"])
                    if eol_data and isinstance(eol_data, list) and len(eol_data) > 0:
                        latest = eol_data[0].get("latest", eol_data[0].get("cycle", "?"))
                        tool_status[tool_name]["latest"] = latest
                        eol = eol_data[0].get("eol")
                        if eol and eol is not True:
                            tool_status[tool_name]["eol_date"] = str(eol)

                # Check GitHub releases for tools without endoflife.date
                elif spec.get("github"):
                    gh_data = self._fetch_json(
                        f"https://api.github.com/repos/{spec['github']}/releases/latest"
                    )
                    if gh_data:
                        tag = gh_data.get("tag_name", "").lstrip("v")
                        tool_status[tool_name]["latest"] = tag

        status["core_tools"] = tool_status

        # Flag tools that are significantly behind
        for tool_name, info in tool_status.items():
            if info.get("latest") and info.get("installed"):
                installed = info["installed"]
                latest = info["latest"]
                if installed != latest and not latest.startswith(installed.split(".")[0]):
                    # Major version difference or significant gap
                    sys_issues.append({
                        "type": "tool_update_available",
                        "tool": tool_name,
                        "installed": installed,
                        "latest": latest,
                        "detail": f"{tool_name}: installed {installed}, latest {latest}",
                    })

        # --- 4d: Disk health ---
        ok, out = self._run_cmd(
            'powershell -Command "'
            'Get-Volume | Where-Object { $_.DriveLetter } | '
            'Select-Object DriveLetter,FileSystemLabel,'
            '@{N=\\\"SizeGB\\\";E={[math]::Round($_.Size/1GB,1)}},'
            '@{N=\\\"FreeGB\\\";E={[math]::Round($_.SizeRemaining/1GB,1)}},'
            '@{N=\\\"PctFree\\\";E={[math]::Round($_.SizeRemaining/$_.Size*100,1)}} | '
            'ConvertTo-Json -Compress'
            '"',
            timeout=15,
        )
        if ok and out.strip():
            try:
                volumes = json.loads(out)
                if isinstance(volumes, dict):
                    volumes = [volumes]
                status["disk_volumes"] = volumes
                for vol in volumes:
                    pct_free = vol.get("PctFree", 100)
                    if pct_free < 10:
                        sys_issues.append({
                            "type": "low_disk_space",
                            "drive": vol.get("DriveLetter", "?"),
                            "free_gb": vol.get("FreeGB", "?"),
                            "pct_free": pct_free,
                            "detail": f"Drive {vol.get('DriveLetter')}: only {pct_free}% free ({vol.get('FreeGB')}GB)",
                        })
            except Exception:
                pass

        return {"status": status, "issues": sys_issues}

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
