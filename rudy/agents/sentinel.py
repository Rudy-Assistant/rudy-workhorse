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
from datetime import datetime
from pathlib import Path
from . import AgentBase, DESKTOP, LOGS_DIR


try:
    from rudy.robin_session_monitor import check_and_approve_prompts
except ImportError:
    check_and_approve_prompts = None

class Sentinel(AgentBase):
    name = "sentinel"
    version = "2.0"

    STATE_FILE = LOGS_DIR / "sentinel-state.json"
    OBSERVATIONS_FILE = LOGS_DIR / "sentinel-observations.json"
    MANIFEST_FILE = LOGS_DIR / "capability-manifest.json"
    BRIEFING_FILE = LOGS_DIR / "session-briefing.md"
    CONTINUATION_FILE = LOGS_DIR / "continuation-prompt.md"

    # --- Process-safe subprocess wrapper (LG-S88-001 fix) ---
    # Delegates to shared module for reuse by extracted sentinel_*.py modules
    @staticmethod
    def _safe_run(cmd, timeout=10):
        """Run a subprocess without spawning conhost.exe. See sentinel_subprocess.py."""
        from rudy.agents.sentinel_subprocess import safe_run
        return safe_run(cmd, timeout=timeout)
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
        if not self._time_ok():
            return self._finalize(state)

        self._scan_environment(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_for_opportunities(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_work_queue(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_presence_analytics(state)
        if not self._time_ok():
            return self._finalize(state)

        # === Live Event Awareness ===
        self._scan_remote_sessions(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_incoming_requests(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_device_events(state)
        if not self._time_ok():
            return self._finalize(state)

        self._scan_service_health(state)
        if not self._time_ok():
            return self._finalize(state)

        # === Session Guardian (ADR-001) ===
        self._scan_capabilities(state)
        if not self._time_ok():
            return self._finalize(state)

        self._generate_session_briefing(state)
        if not self._time_ok():
            return self._finalize(state)

        self._check_session_activity(state)
        if not self._time_ok():
            return self._finalize(state)

        # === Behavioral Learning Loop (ADR-018) ===
        self._scan_behavioral_patterns(state)
        if not self._time_ok():
            return self._finalize(state)

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
            except Exception:
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
            result = self._safe_run(
                ["powershell", "-Command",
                 "(Get-NetTCPConnection -OwningProcess "
                 "(Get-Process rustdesk -ErrorAction SilentlyContinue | "
                 "Select -Expand Id) -ErrorAction SilentlyContinue | "
                 "Where-Object {$_.State -eq 'Established' -and $_.RemotePort -ne 0}).Count"],
                timeout=10,
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

        except Exception:
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
        """Detect new USB devices via quarantine protocol.

        Integrates with rudy.usb_quarantine for full device screening:
        - New devices are fingerprinted (VID/PID, class, driver, composite check)
        - Threat scored against known-malicious signatures and behavioral heuristics
        - CRITICAL/HIGH threats are auto-blocked and alert sent to Chris
        - MEDIUM threats prompt for review
        - Whitelisted devices pass through silently
        """
        try:
            from rudy.usb_quarantine import USBQuarantine
            q = USBQuarantine()
            report = q.scan()

            for dev in report.get("new_devices", []):
                name = dev.get("friendly_name") or dev.get("description") or f"USB {dev.get('vid')}:{dev.get('pid')}"
                score = dev.get("threat_score", 0)
                risk = dev.get("risk_level", "UNKNOWN")

                if score >= 50:
                    self._observe("usb_threat",
                        f"USB {risk}: {name} (score={score}) — {dev.get('recommended_action')}",
                        actionable=True)
                else:
                    self._observe("device_connected",
                        f"New USB device: {name} (risk={risk}, score={score})",
                        actionable=score >= 30)

            for action in report.get("actions_taken", []):
                self._observe("usb_action", action, actionable=True)

            # Track device count in state for session briefing
            state["usb_quarantine_last"] = {
                "new": len(report.get("new_devices", [])),
                "threats": len(report.get("threats", [])),
                "known": len(report.get("known_devices", [])),
                "timestamp": report.get("timestamp"),
            }

        except ImportError:
            # Fallback to basic detection if quarantine module not available
            self._scan_device_events_basic(state)
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

    def _scan_device_events_basic(self, state):
        """Basic USB detection fallback (used if usb_quarantine module unavailable)."""
        try:
            result = self._safe_run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class USB -Status OK -ErrorAction SilentlyContinue | "
                 "Select-Object -ExpandProperty InstanceId"],
                timeout=10,
            )
            if result.returncode == 0:
                current_usb = set(result.stdout.strip().splitlines())
                prev_usb = set(state.get("usb_devices", []))
                new_devices = current_usb - prev_usb
                if prev_usb and new_devices:
                    for dev in list(new_devices)[:3]:
                        short = dev.split("\\")[-1][:40] if "\\" in dev else dev[:40]
                        self._observe("device_connected",
                            f"USB device connected (UNSCREENED): {short}",
                            actionable=True)
                state["usb_devices"] = list(current_usb)
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
            result = self._safe_run(
                ["tailscale", "status", "--json"],
                timeout=5,
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
            result = self._safe_run(
                ["powershell", "-Command",
                 "(Get-Service rustdesk -ErrorAction SilentlyContinue).Status"],
                timeout=5,
            )
            services_status["rustdesk"] = result.stdout.strip().lower() or "not found"
        except Exception:
            services_status["rustdesk"] = "unknown"

        # Command runner (check process)
        try:
            result = self._safe_run(
                ["powershell", "-Command",
                 "@(Get-Process python* -ErrorAction SilentlyContinue | "
                 "Where-Object {$_.CommandLine -like '*command-runner*'}).Count"],
                timeout=5,
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
            except Exception:
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
                except Exception:
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
                        path.read_bytes(), usedforsecurity=False
                    ).hexdigest()[:12]
                    prev_hash = prev_hashes.get(name)
                    if prev_hash and current_hash != prev_hash:
                        self._observe("config_change",
                            f"{name} was modified since last check",
                            actionable=False)
                    prev_hashes[name] = current_hash
                except Exception:
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
            except Exception:
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
            except Exception:
                pass

    # === SESSION GUARDIAN (ADR-001) ===

    def _scan_capabilities(self, state):
        """Build/refresh the capability manifest. Delegated to sentinel_capabilities.py (S88)."""
        from rudy.agents.sentinel_capabilities import scan_capabilities
        scan_capabilities(
            manifest_file=self.MANIFEST_FILE,
            run_count=state.get("run_count", 0),
            observe_fn=self._observe,
        )

    def _generate_session_briefing(self, state):
        """Generate session briefing. Delegated to sentinel_briefing.py (S87)."""
        from rudy.agents.sentinel_briefing import generate_session_briefing
        generate_session_briefing(
            state=state,
            briefing_file=self.BRIEFING_FILE,
            observations_file=self.OBSERVATIONS_FILE,
            version=self.version,
            read_status_fn=self.read_status,
            observe_fn=self._observe,
        )

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

            # S80: Check for stalled permission prompts during active session
            if check_and_approve_prompts is not None:
                try:
                    prompt_result = check_and_approve_prompts()
                    if prompt_result and prompt_result.get("action_taken") in (
                        "approved", "approved_retry"
                    ):
                        self._observe("prompt_approved",
                            "Auto-approved Cowork permission prompt",
                            actionable=False)
                except Exception as pe:
                    self._observe("prompt_check_error",
                        f"Prompt check failed: {pe}")

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

            # Robin Session Continuity (Session 66): auto-launch new Cowork session
            try:
                from rudy.robin_cowork_launcher import check_and_launch_if_needed as cowork_launch_check
                launch_result = cowork_launch_check()
                if launch_result and launch_result.get("success"):
                    self._observe("cowork_launch",
                        f"Robin auto-launched Cowork session: {launch_result.get('handoff_used', 'latest')}",
                        actionable=False)
                    self.log.info("Robin auto-launched new Cowork session")
                elif launch_result:
                    self._observe("cowork_launch_failed",
                        f"Cowork launch attempted but failed: {launch_result.get('error')}",
                        actionable=True)
            except Exception as launch_err:
                self.log.warning("Cowork launcher not available: %s", launch_err)

        except Exception as e:
            self._observe("handoff_error", f"Handoff failed: {e}")

    def _scan_behavioral_patterns(self, state):
        """Run the behavioral learning loop (ADR-018).

        Composes ActivityWatch + PM4Py + PrefixSpan + Alfred/Ollama
        to observe user behavior, discover patterns, and propose automations.
        Heavy analysis runs every 6 hours; quick checks every cycle.
        """
        try:
            from rudy.sentinel_learning import run_learning_cycle

            remaining = self.MAX_RUNTIME - (time.time() - self.start)
            if remaining < 5:
                return  # Not enough time for even a quick cycle

            result = run_learning_cycle(
                max_runtime_secs=min(remaining - 2, 25),
                use_alfred=True,
            )

            events = result.get("events_fetched", 0)
            patterns = result.get("patterns_discovered", 0)
            proposals = result.get("proposals_generated", 0)

            if events > 0:
                self._observe(
                    "behavioral_learning",
                    f"Learning cycle: {events} events, {patterns} patterns, {proposals} proposals"
                    + (" (full analysis)" if result.get("full_analysis") else " (quick)"),
                    actionable=proposals > 0,
                )
            elif result.get("result") == "no_events_available":
                self._observe(
                    "behavioral_learning",
                    "ActivityWatch not running or no events — learning loop idle",
                )

        except ImportError as exc:
            self._observe("behavioral_learning", f"Learning module not available: {exc}")
        except Exception as exc:
            self._observe("behavioral_learning", f"Learning cycle error: {exc}")

    def _micro_improve(self, state):
        """Take small, safe improvement actions."""
        # Only attempt micro-improvements every 4th run (~hourly)
        run_count = state.get("run_count", 0)
        if run_count % 4 != 0:
            return

        # Clean up any stale lock files

# ============================================================
# SentinelObserver - Merged from rudy/robin_sentinel.py
# Consolidation date: 2026-03-29T16:50:24.074430
# Original: Passive environmental observer for Robin nightwatch
# ============================================================

class SentinelObserver:
    """
    Passive environmental observer - runs on EVERY Robin cycle.

    Merged into sentinel.py from rudy/robin_sentinel.py per Lucius Fox
    audit finding (triple sentinel duplication).

    Observes friction signals in three categories:
    - Environment health (disk, processes, services)
    - Coordination gaps (stale messages, silence)
    - Code quality (errors, deprecations)

    Does NOT take action. Reports observations for InitiativeEngine.
    """

    MAX_OBSERVATIONS = 500

    def __init__(self):
        self.observations_file = LOGS_DIR / "sentinel-observations-passive.json"
        self.observations = self._load()

    def _load(self):
        if self.observations_file.exists():
            try:
                with open(self.observations_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        # Trim to max
        if len(self.observations) > self.MAX_OBSERVATIONS:
            self.observations = self.observations[-self.MAX_OBSERVATIONS:]
        with open(self.observations_file, "w", encoding="utf-8") as f:
            json.dump(self.observations, f, indent=2, ensure_ascii=False)

    def _record(self, category, signal, details=""):
        self.observations.append({
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "signal": signal,
            "details": details
        })

    def observe(self):
        """Run all passive observation checks."""
        self._observe_environment()
        self._observe_coordination()
        self._observe_code_quality()
        self._observe_lucius_governance()
        self._save()
        return self.observations[-10:]  # Return recent

    def _observe_environment(self):
        """Check disk, process count, service health."""
        import shutil
        # Disk check
        try:
            usage = shutil.disk_usage("C:\\")
            free_pct = (usage.free / usage.total) * 100
            if free_pct < 10:
                self._record("env_health", "low_disk", f"Only {free_pct:.1f}% free")
        except Exception:
            pass

        # Log file sizes
        for log_file in LOGS_DIR.glob("*.log"):
            try:
                size_mb = log_file.stat().st_size / (1024 * 1024)
                if size_mb > 50:
                    self._record("env_health", "large_log", f"{log_file.name}: {size_mb:.1f}MB")
            except Exception:
                pass

    def _observe_coordination(self):
        """Check inbox freshness, stale messages."""
        coord_dir = DESKTOP / "rudy-data"
        coord_dir / "alfred-inbox"
        robin_inbox = coord_dir / "robin-inbox"

        # Check for stale directives in robin-inbox
        for f in robin_inbox.glob("*.json"):
            try:
                age_hours = (datetime.now().timestamp() - f.stat().st_mtime) / 3600
                if age_hours > 1:
                    self._record("coordination", "stale_directive", f"{f.name}: {age_hours:.1f}h old")
            except Exception:
                pass

    def _observe_code_quality(self):
        """Check for error patterns in recent logs."""
        for log_file in LOGS_DIR.glob("*.log"):
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                # Check last 50 lines for errors
                for line in lines[-50:]:
                    if "ERROR" in line or "CRITICAL" in line:
                        self._record("code_quality", "error_in_log", f"{log_file.name}: {line.strip()[:100]}")
                        break  # One per file is enough
            except Exception:
                pass


    # --- Lucius Signal Types (ADR-006 Section 2, P2-S36) ---
    # Constants preserved for backward compat; logic moved to sentinel_governance.py (S88)

    LUCIUS_SIGNALS_FILE = Path(os.environ.get(
        "RUDY_DATA", str(DESKTOP / "rudy-data")
    )) / "coordination" / "lucius-signals.json"
    LUCIUS_SIGNAL_TYPES = {
        "waste_detected", "delegation_violation", "tool_amnesia",
        "score_trend", "finding_stale", "drift_alert",
    }
    MAX_LUCIUS_SIGNALS = 50

    def _emit_lucius_signal(self, signal_type: str, detail: str):
        """Delegated to sentinel_governance.py (S88)."""
        from rudy.agents.sentinel_governance import emit_lucius_signal
        emit_lucius_signal(signal_type, detail)

    def _load_lucius_signals(self) -> list:
        """Delegated to sentinel_governance.py (S88)."""
        from rudy.agents.sentinel_governance import load_lucius_signals
        return load_lucius_signals()

    def _observe_lucius_governance(self):
        """Check for Lucius-relevant signals. Delegated to sentinel_governance.py (S88)."""
        from rudy.agents.sentinel_governance import observe_lucius_governance
        observe_lucius_governance(emit_fn=self._emit_lucius_signal)

    def get_priority_boost(self, area):
        """Return priority boost for an area based on recent observations."""
        recent = [o for o in self.observations[-50:] if o.get("category") == area]
        if len(recent) > 5:
            return 2  # High friction
        elif len(recent) > 2:
            return 1  # Some friction
        return 0
