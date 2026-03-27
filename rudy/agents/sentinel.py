"""
Sentinel — The Trickle Agent.
Runs every 15 minutes. Lightweight. Curious.

Unlike the Four Horsemen who each own a domain:
  - SystemMaster → health
  - OperationsMonitor → maintenance
  - ResearchIntel → intelligence
  - TaskMaster → coordination

The Sentinel owns *awareness*. It:
  1. Scans for changes since last run (new files, config drift, environment shifts)
  2. Notices opportunities (package updates, stale state, idle resources)
  3. Queues micro-improvements for the other agents or itself
  4. Learns from what happened (reads agent statuses, spots patterns)
  5. Takes small, safe actions (never destructive, never heavy)
  6. Maintains a capability manifest (Session Guardian — ADR-001)
  7. Generates session briefings for Cowork handoff
  8. Detects session inactivity and triggers handoff protocol

Design principles:
  - Never run longer than 30 seconds
  - Never use more than trivial CPU/disk
  - Never modify critical files
  - Always log what it noticed, even if it takes no action
  - Think of it as a heartbeat with curiosity

Session Guardian (ADR-001, 2026-03-27):
  The Sentinel is the anchor of the Session Guardian system.
  It produces two files that Cowork sessions consume:
    - rudy-logs/capability-manifest.json — what tools/skills/modules/packages exist
    - rudy-logs/session-briefing.md — structured context for new sessions
  It also detects Cowork inactivity via command runner timestamps and
  triggers handoff: saves state to disk, generates continuation prompt.
"""
import json
import os
import subprocess
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from . import AgentBase, DESKTOP, LOGS_DIR


class Sentinel(AgentBase):
    name = "sentinel"
    version = "2.0"

    STATE_FILE = LOGS_DIR / "sentinel-state.json"
    OBSERVATIONS_FILE = LOGS_DIR / "sentinel-observations.json"
    MANIFEST_FILE = LOGS_DIR / "capability-manifest.json"
    BRIEFING_FILE = LOGS_DIR / "session-briefing.md"
    CONTINUATION_FILE = LOGS_DIR / "continuation-prompt.md"
    MAX_RUNTIME = 30  # seconds — hard cap

    # Session inactivity thresholds
    INACTIVITY_WARN_MINUTES = 30
    INACTIVITY_HANDOFF_MINUTES = 120

    def run(self, **kwargs):
        self.start = time.time()
        self.observations = []

        state = self._load_state()

        # Each scan is cheap and fast — bail if we're running too long
        self._scan_agent_health(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_environment(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_for_opportunities(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_work_queue(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_presence_analytics(state)
        if not self._time_ok(): return self._finalize(state)

        # === Live Event Awareness ===
        self._scan_remote_sessions(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_incoming_requests(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_device_events(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_service_health(state)
        if not self._time_ok(): return self._finalize(state)

        # === Session Guardian (ADR-001) ===
        self._scan_capabilities(state)
        if not self._time_ok(): return self._finalize(state)

        self._generate_session_briefing(state)
        if not self._time_ok(): return self._finalize(state)

        self._check_session_activity(state)
        if not self._time_ok(): return self._finalize(state)

        self._micro_improve(state)
        self._finalize(state)

    def _time_ok(self) -> bool:
        if not hasattr(self, 'start'):
            self.start = time.time()
        return (time.time() - self.start) < self.MAX_RUNTIME

    def _observe(self, category: str, observation: str, actionable: bool = False):
        """Record something noticed."""
        if not hasattr(self, 'observations'):
            self.observations = []
        entry = {
            "time": datetime.now().isoformat(),
            "category": category,
            "observation": observation,
            "actionable": actionable,
        }
        self.observations.append(entry)
        self.log.info(f"[{category}] {observation}")

    def _load_state(self) -> dict:
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE) as f:
                    return json.load(f)
            except:
                pass
        return {
            "run_count": 0,
            "last_run": None,
            "file_hashes": {},
            "last_agent_statuses": {},
            "improvement_log": [],
            "streak": 0,  # consecutive healthy runs
        }

    def _save_state(self, state: dict):
        state["last_run"] = datetime.now().isoformat()
        state["run_count"] = state.get("run_count", 0) + 1
        with open(self.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)


    # === LIVE EVENT AWARENESS ===

    def _scan_remote_sessions(self, state):
        """Detect active/ended RustDesk remote sessions by checking process state."""
        try:
            # Check if RustDesk has an active session by examining connections
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-NetTCPConnection -OwningProcess "
                 "(Get-Process rustdesk -ErrorAction SilentlyContinue | "
                 "Select -Expand Id) -ErrorAction SilentlyContinue | "
                 "Where-Object {$_.State -eq 'Established' -and $_.RemotePort -ne 0}).Count"],
                capture_output=True, text=True, timeout=10
            )
            active_conns = 0
            if result.returncode == 0 and result.stdout.strip().isdigit():
                active_conns = int(result.stdout.strip())

            was_connected = state.get("rustdesk_session_active", False)

            if active_conns > 0 and not was_connected:
                self._observe("remote_session",
                    "RustDesk session started — someone connected",
                    actionable=True)
                state["rustdesk_session_start"] = datetime.now().isoformat()
            elif active_conns == 0 and was_connected:
                start = state.get("rustdesk_session_start", "unknown")
                self._observe("remote_session",
                    f"RustDesk session ended (started: {start})",
                    actionable=False)

            state["rustdesk_session_active"] = active_conns > 0
            state["rustdesk_connections"] = active_conns

        except Exception as e:
            # Silently skip if powershell call fails — not critical
            pass

    def _scan_incoming_requests(self, state):
        """Detect new pending command runner scripts (incoming work)."""
        try:
            cmd_dir = DESKTOP / "rudy-commands"
            if not cmd_dir.exists():
                return

            # Find .py files without a matching .result (pending work)
            pending = []
            for f in cmd_dir.glob("*.py"):
                if f.name.startswith("_running_"):
                    continue
                result_file = f.with_suffix(".result")
                if not result_file.exists():
                    pending.append(f.name)

            prev_pending = set(state.get("pending_commands", []))
            current_pending = set(pending)

            # Detect new arrivals
            new_commands = current_pending - prev_pending
            if new_commands:
                self._observe("incoming_request",
                    f"New command(s) detected: {', '.join(sorted(new_commands))}",
                    actionable=True)

            # Detect completions
            completed = prev_pending - current_pending
            if completed:
                self._observe("request_completed",
                    f"Command(s) finished: {', '.join(sorted(completed))}",
                    actionable=False)

            state["pending_commands"] = list(current_pending)

        except Exception:
            pass

    def _scan_device_events(self, state):
        """Detect new USB devices and network device changes."""
        try:
            # USB devices: quick WMI query
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class USB -Status OK -ErrorAction SilentlyContinue | "
                 "Select-Object -ExpandProperty InstanceId"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                current_usb = set(result.stdout.strip().splitlines())
                prev_usb = set(state.get("usb_devices", []))

                new_devices = current_usb - prev_usb
                removed_devices = prev_usb - current_usb

                if prev_usb and new_devices:
                    # Only report if we had a baseline
                    for dev in list(new_devices)[:3]:
                        short = dev.split("\\")[-1][:40] if "\\" in dev else dev[:40]
                        self._observe("device_connected",
                            f"USB device connected: {short}",
                            actionable=True)

                if prev_usb and removed_devices:
                    for dev in list(removed_devices)[:3]:
                        short = dev.split("\\")[-1][:40] if "\\" in dev else dev[:40]
                        self._observe("device_disconnected",
                            f"USB device removed: {short}",
                            actionable=False)

                state["usb_devices"] = list(current_usb)

        except Exception:
            pass

        # Network devices: check presence scan results for changes
        try:
            presence_file = LOGS_DIR / "presence-latest.json"
            if presence_file.exists():
                with open(presence_file) as f:
                    data = json.load(f)
                current_macs = set(d.get("mac", "") for d in data.get("devices", []))
                prev_macs = set(state.get("known_network_devices", []))

                if prev_macs:
                    new_macs = current_macs - prev_macs
                    gone_macs = prev_macs - current_macs
                    if new_macs:
                        self._observe("network_device_new",
                            f"{len(new_macs)} new device(s) on network: {', '.join(list(new_macs)[:3])}",
                            actionable=True)
                    if gone_macs and len(gone_macs) <= 3:
                        self._observe("network_device_gone",
                            f"{len(gone_macs)} device(s) left network",
                            actionable=False)

                state["known_network_devices"] = list(current_macs)
        except Exception:
            pass

    def _scan_service_health(self, state):
        """Monitor key services: Ollama, Tailscale, RustDesk, command runner."""
        services_status = {}

        # Ollama
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    models = [m.get("name", "") for m in data.get("models", [])]
                    services_status["ollama"] = f"running ({len(models)} models)"
                else:
                    services_status["ollama"] = "error"
        except Exception:
            services_status["ollama"] = "down"

        # Tailscale
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                ts_data = json.loads(result.stdout)
                self_online = ts_data.get("Self", {}).get("Online", False)
                services_status["tailscale"] = "connected" if self_online else "disconnected"
            else:
                services_status["tailscale"] = "error"
        except Exception:
            services_status["tailscale"] = "unavailable"

        # RustDesk service
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-Service rustdesk -ErrorAction SilentlyContinue).Status"],
                capture_output=True, text=True, timeout=5
            )
            services_status["rustdesk"] = result.stdout.strip().lower() or "not found"
        except Exception:
            services_status["rustdesk"] = "unknown"

        # Command runner (check process)
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "@(Get-Process python* -ErrorAction SilentlyContinue | "
                 "Where-Object {$_.CommandLine -like '*command-runner*'}).Count"],
                capture_output=True, text=True, timeout=5
            )
            count = result.stdout.strip()
            services_status["command_runner"] = f"running ({count} proc)" if count and count != "0" else "not running"
        except Exception:
            services_status["command_runner"] = "unknown"

        # Detect state changes from previous run
        prev_services = state.get("service_health", {})
        for svc, status in services_status.items():
            prev_status = prev_services.get(svc, "unknown")
            if prev_status != "unknown" and status != prev_status:
                is_bad = "down" in status or "error" in status or "not running" in status or "disconnected" in status
                self._observe("service_change",
                    f"{svc}: {prev_status} → {status}",
                    actionable=is_bad)

        state["service_health"] = services_status

    def _scan_presence_analytics(self, state):
        """Ensure presence analytics are fresh; re-run if stale."""
        try:
            analytics_file = LOGS_DIR / "presence-analytics.json"
            if analytics_file.exists():
                with open(analytics_file) as f:
                    data = json.load(f)
                ts = data.get("timestamp", "")
                if ts:
                    age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
                    if age > 3600:
                        self._observe("analytics", f"Presence analytics stale ({age/60:.0f}m old), refreshing")
                        from rudy.presence_analytics import PresenceAnalytics
                        PresenceAnalytics().run()
                    else:
                        scan_count = data.get("scan_count", 0)
                        device_count = data.get("device_count", 0)
                        clusters = len(data.get("clusters", []))
                        self._observe("analytics", f"Analytics healthy: {device_count} devices, {clusters} clusters, {scan_count} scans")
            else:
                self._observe("analytics", "No presence analytics yet — will initialize on next presence scan")
        except Exception as e:
            self._observe("analytics_error", str(e))

    def _file_github_anomalies(self):
        """File actionable observations as GitHub issues (if gh is available)."""
        actionable = [o for o in self.observations if o.get("actionable")]
        if not actionable:
            return

        try:
            from rudy.integrations.github_ops import get_github
            gh = get_github()
            if not gh.gh_available:
                return
            for obs in actionable[:3]:  # Cap at 3 per run
                gh.file_anomaly_report(
                    obs.get("category", "unknown"),
                    obs.get("observation", "No details")
                )
        except Exception:
            pass  # GitHub integration is best-effort

    def _finalize(self, state):
        """Save state and observations."""
        # Update streak
        has_alerts = len(self.status.get("critical_alerts", [])) > 0
        if has_alerts:
            state["streak"] = 0
        else:
            state["streak"] = state.get("streak", 0) + 1

        self._save_state(state)

        # File actionable items to GitHub (best-effort)
        self._file_github_anomalies()

        # Save recent observations (keep last 100)
        all_obs = []
        if self.OBSERVATIONS_FILE.exists():
            try:
                with open(self.OBSERVATIONS_FILE) as f:
                    all_obs = json.load(f)
            except:
                pass
        all_obs.extend(self.observations)
        all_obs = all_obs[-100:]
        with open(self.OBSERVATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_obs, f, indent=2, default=str)

        actionable = sum(1 for o in self.observations if o.get("actionable"))
        self.summarize(
            f"Noticed {len(self.observations)} things ({actionable} actionable). "
            f"Streak: {state.get('streak', 0)} healthy runs."
        )

    # === SCAN MODULES ===

    def _scan_agent_health(self, state):
        """Check if any agent has gone stale or errored since last check."""
        agents = ["system_master", "operations_monitor", "research_intel", "task_master"]
        prev = state.get("last_agent_statuses", {})

        for agent_name in agents:
            status = self.read_status(agent_name)
            agent_status = status.get("status", "unknown")
            last_run = status.get("last_run", "never")

            # Detect status change
            prev_status = prev.get(agent_name, {}).get("status", "unknown")
            if agent_status != prev_status and prev_status != "unknown":
                self._observe("agent_change",
                    f"{agent_name}: {prev_status} → {agent_status}",
                    actionable=(agent_status == "error"))

            # Detect staleness (agent hasn't run when expected)
            if last_run != "never":
                try:
                    last_dt = datetime.fromisoformat(last_run)
                    age_hours = (datetime.now() - last_dt).total_seconds() / 3600
                    # SystemMaster should run every 5min, others less frequently
                    if agent_name == "system_master" and age_hours > 1:
                        self._observe("staleness",
                            f"{agent_name} hasn't run in {age_hours:.1f} hours",
                            actionable=True)
                except:
                    pass

            prev[agent_name] = {"status": agent_status, "last_run": last_run}

        state["last_agent_statuses"] = prev

    def _scan_environment(self, state):
        """Check for environmental changes."""
        # Monitor critical config files for unexpected changes
        critical_files = {
            "CLAUDE.md": DESKTOP / "CLAUDE.md",
            "command_runner": DESKTOP / "rudy-command-runner.py",
            "healthcheck": DESKTOP / "workhorse-healthcheck.ps1",
        }

        prev_hashes = state.get("file_hashes", {})
        for name, path in critical_files.items():
            if path.exists():
                try:
                    current_hash = hashlib.md5(
                        path.read_bytes()
                    ).hexdigest()[:12]
                    prev_hash = prev_hashes.get(name)
                    if prev_hash and current_hash != prev_hash:
                        self._observe("config_change",
                            f"{name} was modified since last check",
                            actionable=False)
                    prev_hashes[name] = current_hash
                except:
                    pass

        state["file_hashes"] = prev_hashes

        # Check disk space trend
        import shutil
        total, used, free = shutil.disk_usage("C:\\")
        free_gb = round(free / (1024**3), 1)
        prev_free = state.get("last_disk_free_gb")
        if prev_free is not None:
            delta = free_gb - prev_free
            if delta < -1:  # Lost more than 1GB since last check
                self._observe("disk_trend",
                    f"Disk shrinking: {prev_free} → {free_gb} GB free ({delta:+.1f} GB)",
                    actionable=(free_gb < 50))
        state["last_disk_free_gb"] = free_gb

    def _scan_for_opportunities(self, state):
        """Look for improvement opportunities."""
        # Check if there are stale files in rudy-commands
        cmd_dir = DESKTOP / "rudy-commands"
        stale_results = 0
        for f in cmd_dir.glob("*.result"):
            age_hours = (datetime.now().timestamp() - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_results += 1
        if stale_results > 5:
            self._observe("cleanup_opportunity",
                f"{stale_results} result files older than 24h in rudy-commands/",
                actionable=True)

        # Check if logs are growing large
        total_log_mb = 0
        for f in LOGS_DIR.glob("*.log"):
            total_log_mb += f.stat().st_size / (1024 * 1024)
        if total_log_mb > 50:
            self._observe("logs_growing",
                f"Total log size: {total_log_mb:.1f} MB — rotation may be needed",
                actionable=True)

        # Check alert file
        alert_file = LOGS_DIR / "ALERT-ACTIVE.txt"
        if alert_file.exists():
            try:
                content = alert_file.read_text().strip()
                self._observe("active_alert",
                    f"Unresolved alert: {content}",
                    actionable=True)
            except:
                pass

    def _scan_work_queue(self, state):
        """Check if the work queue has stale items."""
        queue_file = LOGS_DIR / "task-queue.json"
        if queue_file.exists():
            try:
                with open(queue_file) as f:
                    queue = json.load(f)
                pending = len(queue.get("pending", []))
                if pending > 0:
                    self._observe("work_pending",
                        f"{pending} items in work queue",
                        actionable=False)
            except:
                pass

    # === SESSION GUARDIAN (ADR-001) ===

    def _scan_capabilities(self, state):
        """Build/refresh the capability manifest.

        Composes existing data sources:
          - pip list → installed packages
          - rudy/ directory → available modules
          - agent-domains.json → skills, connectors, scheduled tasks
          - research-capability.json → existing package audit (from ObsolescenceMonitor)

        Only rebuilds every 4th run (~hourly) unless forced.
        """
        run_count = state.get("run_count", 0)
        if run_count % 4 != 0 and self.MANIFEST_FILE.exists():
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
            # (generated by ObsolescenceMonitor — don't duplicate its work)
            cap_file = LOGS_DIR / "research-capability.json"
            if cap_file.exists():
                try:
                    cap = json.loads(cap_file.read_text())
                    pkgs = cap.get("python_packages", [])
                    if isinstance(pkgs, list):
                        manifest["packages"] = [
                            p if isinstance(p, str) else p.get("name", str(p))
                            for p in pkgs[:200]  # Cap to avoid bloat
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
            with open(self.MANIFEST_FILE, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            total = (len(manifest["modules"]) + len(manifest["packages"])
                     + len(manifest["skills"]) + len(manifest["agents"]))
            self._observe("capabilities",
                f"Manifest updated: {len(manifest['modules'])} modules, "
                f"{len(manifest['packages'])} packages, "
                f"{len(manifest['skills'])} skills, "
                f"{len(manifest['agents'])} agents")

        except Exception as e:
            self._observe("capability_error", f"Manifest scan failed: {e}")

    def _generate_session_briefing(self, state):
        """Generate a structured briefing for the next Cowork session.

        Reads agent statuses, pending work, recent observations, and
        produces a markdown file that new sessions should read first.
        Only regenerates every 4th run (~hourly) or when state changes.
        """
        run_count = state.get("run_count", 0)
        if run_count % 4 != 0 and self.BRIEFING_FILE.exists():
            return

        try:
            lines = []
            now = datetime.now()
            lines.append(f"# Session Briefing — {now.strftime('%Y-%m-%d %H:%M')}")
            lines.append(f"*Generated by Sentinel v{self.version}*\n")

            # Machine state
            import shutil
            total, used, free = shutil.disk_usage("C:\\")
            free_gb = round(free / (1024**3), 1)
            lines.append("## Machine State")
            lines.append(f"- Disk: {free_gb} GB free")
            lines.append(f"- Sentinel streak: {state.get('streak', 0)} consecutive healthy runs")
            lines.append(f"- Last Sentinel run: {state.get('last_run', 'unknown')}")
            lines.append("")

            # Agent health summary
            lines.append("## Agent Health")
            agents = ["system_master", "security_agent", "sentinel",
                       "task_master", "research_intel", "operations_monitor"]
            for agent_name in agents:
                status = self.read_status(agent_name)
                s = status.get("status", "unknown")
                last = status.get("last_run", "never")
                summary = status.get("summary", "")[:80]
                icon = "✅" if s == "ok" else "⚠️" if s == "warning" else "❌" if s == "error" else "❓"
                lines.append(f"- {icon} **{agent_name}**: {s} (last: {last})")
                if summary:
                    lines.append(f"  {summary}")
            lines.append("")

            # Pending work
            lines.append("## Pending Work")
            queue_file = LOGS_DIR / "task-queue.json"
            if queue_file.exists():
                try:
                    queue = json.loads(queue_file.read_text())
                    pending = queue.get("pending", [])
                    in_progress = queue.get("in_progress", [])
                    if pending:
                        for item in pending[:5]:
                            desc = item if isinstance(item, str) else item.get("description", str(item))
                            lines.append(f"- [ ] {desc}")
                    if in_progress:
                        for item in in_progress[:3]:
                            desc = item if isinstance(item, str) else item.get("description", str(item))
                            lines.append(f"- [~] {desc} (in progress)")
                    if not pending and not in_progress:
                        lines.append("- No pending tasks")
                except Exception:
                    lines.append("- Could not read task queue")
            else:
                lines.append("- No task queue file")
            lines.append("")

            # Recent crash dumps (from agent crash handler)
            crash_dir = LOGS_DIR / "crash-dumps"
            if crash_dir.exists():
                crash_files = sorted(crash_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
                recent_crashes = [f for f in crash_files if (now.timestamp() - f.stat().st_mtime) < 86400]  # last 24h
                if recent_crashes:
                    lines.append("## Recent Crashes (last 24h)")
                    for cf in recent_crashes[:5]:
                        try:
                            cd = json.loads(cf.read_text(encoding="utf-8"))
                            lines.append(f"- **{cd.get('agent', '?')}** at {cd.get('crash_time', '?')}: "
                                         f"`{cd.get('error_type', '?')}: {cd.get('error_message', '')[:100]}`")
                        except Exception:
                            lines.append(f"- {cf.name} (could not parse)")
                    lines.append("")

            # Crash marker cleanup (clear if no recent crashes)
            marker = LOGS_DIR / "CRASH-DETECTED.txt"
            if marker.exists():
                if not (crash_dir.exists() and any(
                    (now.timestamp() - f.stat().st_mtime) < 3600
                    for f in crash_dir.glob("*.json")
                )):
                    try:
                        marker.unlink()
                    except Exception:
                        pass

            # Dependency health issues (from ResearchIntel)
            dep_health = LOGS_DIR / "dependency-health.json"
            if dep_health.exists():
                try:
                    dh = json.loads(dep_health.read_text(encoding="utf-8"))
                    issues = dh.get("issues", [])
                    if issues:
                        lines.append("## Dependency Issues")
                        for issue in issues[:5]:
                            if issue.get("type") == "superseded":
                                lines.append(
                                    f"- **{issue['package']}** is {issue['status']}: "
                                    f"use `{issue['replacement']}` instead — "
                                    f"{issue.get('replacement_reason', '')[:80]}")
                            elif issue.get("type") == "import_failure":
                                lines.append(
                                    f"- **{issue['module']}** ({issue['description']}): "
                                    f"import failed")
                        lines.append("")
                except Exception:
                    pass

            # Recent observations (last 5 actionable)
            lines.append("## Recent Observations")
            if self.OBSERVATIONS_FILE.exists():
                try:
                    obs = json.loads(self.OBSERVATIONS_FILE.read_text())
                    actionable = [o for o in obs if o.get("actionable")][-5:]
                    if actionable:
                        for o in actionable:
                            lines.append(f"- **{o.get('category', '?')}**: {o.get('observation', '')}")
                    else:
                        lines.append("- No actionable observations")
                except Exception:
                    lines.append("- Could not read observations")
            lines.append("")

            # Available tools reminder
            lines.append("## Reminder: Available Tools")
            lines.append("Before writing custom code, check:")
            lines.append("- `rudy-logs/capability-manifest.json` — full index of modules, packages, skills")
            lines.append("- Cowork skills: 30+ across Engineering, Operations, Productivity, Legal, Plugin Mgmt")
            lines.append("- MCP connectors: Gmail, Google Calendar, Notion, Canva, Chrome")
            lines.append("- rudy/ modules: 31+ (OCR, NLP, financial, voice, network defense, etc.)")
            lines.append("- Agent tool: spawn sub-agents for parallel research/exploration")
            lines.append("")

            # Session activity
            lines.append("## Session Activity")
            runner_log = LOGS_DIR / "command-runner.log"
            if runner_log.exists():
                age_min = (now.timestamp() - runner_log.stat().st_mtime) / 60
                if age_min < 5:
                    lines.append(f"- Command runner: active ({age_min:.0f} min ago)")
                elif age_min < 30:
                    lines.append(f"- Command runner: idle ({age_min:.0f} min since last activity)")
                else:
                    lines.append(f"- Command runner: **inactive** ({age_min:.0f} min since last activity)")
            else:
                lines.append("- Command runner: no log found")

            # Live system state (from scan_service_health + scan_remote_sessions)
            svc_health = state.get("service_health", {})
            if svc_health:
                lines.append("")
                lines.append("## Live Services")
                for svc, status in svc_health.items():
                    icon = "🟢" if any(w in status for w in ["running", "connected"]) else "🔴" if any(w in status for w in ["down", "error", "not running", "disconnected"]) else "🟡"
                    lines.append(f"- {icon} **{svc}**: {status}")

            if state.get("rustdesk_session_active"):
                lines.append(f"- 🖥️ **Remote session**: ACTIVE (since {state.get('rustdesk_session_start', '?')})")

            pending_cmds = state.get("pending_commands", [])
            if pending_cmds:
                lines.append(f"- 📥 **Pending commands**: {', '.join(pending_cmds[:5])}")

            self.BRIEFING_FILE.write_text("\n".join(lines), encoding="utf-8")
            self._observe("briefing", "Session briefing updated")

        except Exception as e:
            self._observe("briefing_error", f"Briefing generation failed: {e}")

    def _check_session_activity(self, state):
        """Detect Cowork session inactivity and trigger handoff if needed.

        Monitors the command runner log — if no new commands have been
        processed for INACTIVITY_WARN_MINUTES, flags it. If inactive for
        INACTIVITY_HANDOFF_MINUTES, generates a continuation prompt and
        optionally activates offline ops.
        """
        try:
            runner_log = LOGS_DIR / "command-runner.log"
            if not runner_log.exists():
                return

            age_min = (time.time() - runner_log.stat().st_mtime) / 60

            prev_inactive = state.get("session_inactive_since")

            if age_min < self.INACTIVITY_WARN_MINUTES:
                # Active — clear any inactivity state
                if prev_inactive:
                    self._observe("session_resumed",
                        "Cowork session activity detected — clearing inactivity flag")
                    state.pop("session_inactive_since", None)
                    state.pop("handoff_triggered", None)
                return

            # Inactive for > warn threshold
            if not prev_inactive:
                state["session_inactive_since"] = datetime.now().isoformat()
                self._observe("session_idle",
                    f"No command runner activity for {age_min:.0f} min",
                    actionable=False)

            # Check if we should trigger handoff
            if age_min >= self.INACTIVITY_HANDOFF_MINUTES and not state.get("handoff_triggered"):
                self._trigger_handoff(state)
                state["handoff_triggered"] = True

        except Exception as e:
            self._observe("activity_error", f"Session activity check failed: {e}")

    def _trigger_handoff(self, state):
        """Generate continuation prompt and flag for offline ops activation."""
        try:
            lines = []
            lines.append("CONTINUATION PROMPT (copy into new Cowork thread):")
            lines.append("---")
            lines.append("Continue building Rudy/Workhorse.")
            lines.append("")

            # Summarize recent work from observations
            if self.OBSERVATIONS_FILE.exists():
                obs = json.loads(self.OBSERVATIONS_FILE.read_text())
                recent = [o for o in obs[-20:] if o.get("actionable")]
                if recent:
                    lines.append("Pending items from recent observations:")
                    for o in recent[-5:]:
                        lines.append(f"  - {o.get('observation', '')}")
                    lines.append("")

            # Machine state
            lines.append(f"Machine state: Sentinel streak {state.get('streak', 0)} healthy runs.")

            # Pending queue
            queue_file = LOGS_DIR / "task-queue.json"
            if queue_file.exists():
                try:
                    queue = json.loads(queue_file.read_text())
                    pending = queue.get("pending", [])
                    if pending:
                        lines.append(f"Work queue: {len(pending)} pending tasks.")
                except Exception:
                    pass

            lines.append("")
            lines.append("Read CLAUDE.md for full system state.")
            lines.append("Read rudy-logs/session-briefing.md for current machine briefing.")
            lines.append("---")

            self.CONTINUATION_FILE.write_text("\n".join(lines), encoding="utf-8")
            self._observe("handoff",
                f"Continuation prompt generated at {self.CONTINUATION_FILE.name}",
                actionable=True)
            self.log.info("Session handoff triggered — continuation prompt written")

        except Exception as e:
            self._observe("handoff_error", f"Handoff failed: {e}")

    def _micro_improve(self, state):
        """Take small, safe improvement actions."""
        # Only attempt micro-improvements every 4th run (~hourly)
        run_count = state.get("run_count", 0)
        if run_count % 4 != 0:
            return

        # Clean up any stale lock files
     