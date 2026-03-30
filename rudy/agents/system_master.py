"""
SystemMaster — Machine Health & Recovery Agent.
Monitors services, processes, disk space, CPU, memory, network, and temperature.
Auto-recovers failed components and alerts on persistent issues.

v1.1: Upgraded with psutil for richer system metrics (CPU%, RAM, uptime, boot time).
"""
import subprocess

import shutil

from datetime import datetime
from . import AgentBase, DESKTOP, LOGS_DIR, PYTHON_EXE

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

class SystemMaster(AgentBase):
    name = "system_master"
    version = "1.1"

    SERVICES = ["RustDesk", "Tailscale"]
    PROCESSES = {
        "command_runner": "rudy-command-runner",
        "listener": "rudy-listener",
        "watchdog": "workhorse-watchdog",
    }
    DISK_WARN_GB = 10
    PYTHON = PYTHON_EXE

    def run(self, **kwargs):
        mode = kwargs.get("mode", "full")

        if mode in ("full", "services"):
            self._check_services()
        if mode in ("full", "processes"):
            self._check_processes()
        if mode in ("full", "system"):
            self._check_system_resources()
            self._check_network_travel()
        if mode in ("full", "disk"):
            self._check_disk()
        if mode in ("full", "logs"):
            self._rotate_logs()
        if mode in ("full", "network"):
            self._check_network()

        # Generate summary
        alerts = len(self.status["critical_alerts"])
        warnings = len(self.status["warnings"])
        actions = len(self.status["actions_taken"])

        summary_parts = [f"{alerts} alerts, {warnings} warnings, {actions} actions"]
        if HAS_PSUTIL:
            summary_parts.append(f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%")
        self.summarize("Health check: " + " | ".join(summary_parts))

    def _run_cmd(self, cmd, timeout=15):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout.strip()
        except Exception as e:
            return False, str(e)

    def _check_services(self):
        self.log.info("Checking Windows services...")
        for svc in self.SERVICES:
            ok, out = self._run_cmd(f'sc query {svc}')
            running = ok and "RUNNING" in out
            if running:
                self.log.info(f"  {svc}: RUNNING")
            else:
                self.alert(f"{svc} is DOWN")
                ok, _ = self._run_cmd(f'net start {svc}')
                if ok:
                    self.action(f"Restarted {svc}")
                else:
                    self.alert(f"Failed to restart {svc}")

    def _check_processes(self):
        self.log.info("Checking Python processes...")

        if HAS_PSUTIL:
            # Use psutil for reliable process detection
            python_procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
                try:
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        cmdline = ' '.join(proc.info['cmdline'] or [])
                        python_procs.append({
                            'pid': proc.info['pid'],
                            'cmdline': cmdline,
                            'cpu': proc.info['cpu_percent'],
                            'mem_mb': round((proc.info['memory_info'].rss if proc.info['memory_info'] else 0) / 1024 / 1024, 1),
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            self.status["python_processes"] = len(python_procs)

            for name, pattern in self.PROCESSES.items():
                found = any(pattern in p['cmdline'] for p in python_procs)
                if found:
                    proc = next(p for p in python_procs if pattern in p['cmdline'])
                    self.log.info(f"  {name}: RUNNING (PID {proc['pid']}, {proc['mem_mb']}MB)")
                else:
                    self.warn(f"{name} is not running")
                    self._restart_process(name)
        else:
            # Fallback to WMI
            ok, out = self._run_cmd(
                'powershell -Command "Get-CimInstance Win32_Process -Filter \\"name=\'python.exe\'\\" | Select-Object ProcessId, CommandLine | Format-List"'
            )
            for name, pattern in self.PROCESSES.items():
                if pattern in (out or ""):
                    self.log.info(f"  {name}: RUNNING")
                else:
                    self.warn(f"{name} is not running")
                    self._restart_process(name)

    def _restart_process(self, name):
        if name == "command_runner":
            self._run_cmd(f'start /B "" "{self.PYTHON}" "{DESKTOP}\\rudy-command-runner.py"')
            self.action(f"Attempted restart of {name}")
        elif name == "listener":
            self._run_cmd(
                f'powershell -Command "Start-Process \'{self.PYTHON}\' -ArgumentList \'{DESKTOP}\\rudy-listener.py\' -WindowStyle Hidden"'
            )
            self.action(f"Attempted restart of {name}")

    def _check_network_travel(self):
        """Check for network changes (travel mode activation)."""
        try:
            from rudy.travel_mode import TravelMode
            tm = TravelMode()
            result = tm.check_network()
            action = result.get("action", "no_change")
            if action != "no_change":
                self.log.warning(f"Network change: {action}")
                mode = tm.state.get("mode", "unknown")
                self.log.info(f"Travel mode: {mode}")
            else:
                self.log.info(f"Network: stable ({tm.state.get('mode', 'unknown')} mode)")
        except Exception as e:
            self.log.error(f"Travel mode check failed: {e}")

    def _check_system_resources(self):
        """Rich system metrics via psutil."""
        if not HAS_PSUTIL:
            self.log.info("psutil not available — skipping system resource check")
            return

        self.log.info("Checking system resources...")

        # CPU
        cpu_pct = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        self.log.info(f"  CPU: {cpu_pct}% across {cpu_count} cores")
        if cpu_pct > 90:
            self.alert(f"CPU at {cpu_pct}%")
        elif cpu_pct > 70:
            self.warn(f"CPU at {cpu_pct}%")
        self.status["cpu_percent"] = cpu_pct

        # Memory
        mem = psutil.virtual_memory()
        self.log.info(f"  RAM: {mem.percent}% used ({mem.used // (1024**3):.1f}/{mem.total // (1024**3):.1f} GB)")
        if mem.percent > 90:
            self.alert(f"RAM at {mem.percent}%")
        elif mem.percent > 80:
            self.warn(f"RAM at {mem.percent}%")
        self.status["ram_percent"] = mem.percent
        self.status["ram_used_gb"] = round(mem.used / (1024**3), 1)
        self.status["ram_total_gb"] = round(mem.total / (1024**3), 1)

        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        uptime_str = f"{uptime.days}d {uptime.seconds // 3600}h {(uptime.seconds % 3600) // 60}m"
        self.log.info(f"  Uptime: {uptime_str} (booted {boot_time.strftime('%Y-%m-%d %H:%M')})")
        self.status["uptime"] = uptime_str
        self.status["boot_time"] = boot_time.isoformat()

        # Top processes by memory
        top_procs = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                if proc.info['memory_info']:
                    top_procs.append((
                        proc.info['name'],
                        proc.info['memory_info'].rss // (1024 * 1024)
                    ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top_procs.sort(key=lambda x: x[1], reverse=True)
        self.status["top_processes"] = [
            {"name": name, "mem_mb": mem_mb}
            for name, mem_mb in top_procs[:5]
        ]

    def _check_disk(self):
        self.log.info("Checking disk space...")
        total, used, free = shutil.disk_usage("C:\\")
        free_gb = free / (1024**3)
        total_gb = total / (1024**3)
        pct = (used / total) * 100
        self.log.info(f"  Disk: {free_gb:.1f} GB free of {total_gb:.1f} GB ({pct:.0f}% used)")

        if free_gb < self.DISK_WARN_GB:
            self.alert(f"Low disk space: {free_gb:.1f} GB free")
        elif free_gb < self.DISK_WARN_GB * 2:
            self.warn(f"Disk space getting low: {free_gb:.1f} GB free")

        self.status["disk_free_gb"] = round(free_gb, 1)
        self.status["disk_pct_used"] = round(pct, 1)

    def _rotate_logs(self):
        self.log.info("Rotating logs...")
        max_lines = 500
        rotated = 0
        for log_file in LOGS_DIR.glob("*.log"):
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) > max_lines:
                    log_file.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
                    rotated += 1
            except Exception:
                pass
        if rotated:
            self.action(f"Rotated {rotated} log files")

    def _check_network(self):
        self.log.info("Checking network...")

        if HAS_PSUTIL:
            net = psutil.net_io_counters()
            self.status["net_bytes_sent"] = net.bytes_sent
            self.status["net_bytes_recv"] = net.bytes_recv

        ok, _ = self._run_cmd("ping -n 1 -w 3000 8.8.8.8")
        if ok:
            self.log.info("  Internet: OK")
        else:
            self.alert("Internet is DOWN")

        ok, _ = self._run_cmd("ping -n 1 -w 3000 100.83.49.9")
        if ok:
            self.log.info("  Tailscale: OK")
        else:
            self.warn("Tailscale IP unreachable")

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    agent = SystemMaster()
    agent.execute(mode=mode)
