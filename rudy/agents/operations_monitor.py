"""
OperationsMonitor — System Maintenance & Cleanup Agent.
Manages disk cleanup, cache purging, log rotation, privacy drift detection,
and result file archiving.
"""
import os
import shutil
import subprocess
import json
import glob
from datetime import datetime, timedelta
from . import AgentBase, DESKTOP, LOGS_DIR


class OperationsMonitor(AgentBase):
    name = "operations_monitor"
    version = "1.0"

    def run(self, **kwargs):
        mode = kwargs.get("mode", "full")

        cleaned = 0
        if mode in ("full", "cleanup"):
            cleaned += self._clean_temp_files()
            cleaned += self._archive_old_results()
            cleaned += self._clean_pycache()

        if mode in ("full", "privacy"):
            self._check_privacy_drift()

        if mode in ("full", "audit"):
            self._audit_disk_usage()

        self.summarize(f"Maintenance complete: cleaned {cleaned} items")

    def _clean_temp_files(self):
        """Remove temp files from various locations."""
        self.log.info("Cleaning temp files...")
        cleaned = 0

        # Clean Windows temp
        temp_dirs = [
            os.path.expandvars(r"%TEMP%"),
            os.path.expandvars(r"%LOCALAPPDATA%\Temp"),
        ]
        for td in temp_dirs:
            if os.path.exists(td):
                for item in os.listdir(td):
                    path = os.path.join(td, item)
                    try:
                        age = datetime.now().timestamp() - os.path.getmtime(path)
                        if age > 86400 * 3:  # Older than 3 days
                            if os.path.isdir(path):
                                shutil.rmtree(path, ignore_errors=True)
                            else:
                                os.unlink(path)
                            cleaned += 1
                    except Exception:
                        pass

        if cleaned:
            self.action(f"Cleaned {cleaned} temp files")
        return cleaned

    def _archive_old_results(self):
        """Move old .result files to archive."""
        self.log.info("Archiving old command results...")
        cmd_dir = DESKTOP / "rudy-commands"
        archive_dir = cmd_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        archived = 0

        for f in cmd_dir.glob("*.result"):
            age = datetime.now().timestamp() - f.stat().st_mtime
            if age > 86400 * 1:  # Older than 1 day
                try:
                    shutil.move(str(f), str(archive_dir / f.name))
                    archived += 1
                except Exception:
                    pass

        # Also clean result.json files
        for f in cmd_dir.glob("*.result.json"):
            age = datetime.now().timestamp() - f.stat().st_mtime
            if age > 86400 * 1:
                try:
                    shutil.move(str(f), str(archive_dir / f.name))
                    archived += 1
                except Exception:
                    pass

        # Clean old archive files (> 7 days)
        old_cleaned = 0
        for f in archive_dir.iterdir():
            try:
                age = datetime.now().timestamp() - f.stat().st_mtime
                if age > 86400 * 7:
                    f.unlink()
                    old_cleaned += 1
            except Exception:
                pass

        if archived or old_cleaned:
            self.action(f"Archived {archived} results, cleaned {old_cleaned} old archive files")
        return archived

    def _clean_pycache(self):
        """Remove __pycache__ directories."""
        cleaned = 0
        for root, dirs, files in os.walk(str(DESKTOP)):
            for d in dirs:
                if d == "__pycache__":
                    try:
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                        cleaned += 1
                    except Exception:
                        pass
        if cleaned:
            self.action(f"Removed {cleaned} __pycache__ directories")
        return cleaned

    def _check_privacy_drift(self):
        """Check if Windows Update has reset privacy settings."""
        self.log.info("Checking privacy settings drift...")
        checks = {
            "Telemetry": (
                r'reg query "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection" /v AllowTelemetry',
                "0x1"  # Security only
            ),
            "AdvertisingID": (
                r'reg query "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo" /v Enabled',
                "0x0"
            ),
            "ActivityHistory": (
                r'reg query "HKLM\SOFTWARE\Policies\Microsoft\Windows\System" /v PublishUserActivities',
                "0x0"
            ),
        }

        drifted = []
        for name, (cmd, expected) in checks.items():
            ok, out = self._run_cmd(cmd)
            if ok and expected in out:
                self.log.info(f"  {name}: OK")
            else:
                drifted.append(name)
                self.warn(f"Privacy drift: {name} may have been reset")

        if drifted:
            self.warn(f"Privacy drift detected in: {', '.join(drifted)}")

    def _audit_disk_usage(self):
        """Report on major disk consumers."""
        self.log.info("Auditing disk usage...")
        total, used, free = shutil.disk_usage("C:\\")

        # Check specific directories
        dirs_to_check = [
            ("rudy-logs", LOGS_DIR),
            ("rudy-commands", DESKTOP / "rudy-commands"),
            ("data", DESKTOP / "data"),
            ("scripts", DESKTOP / "scripts"),
        ]

        sizes = {}
        for name, path in dirs_to_check:
            if path.exists():
                size = sum(
                    f.stat().st_size for f in path.rglob("*") if f.is_file()
                )
                sizes[name] = round(size / (1024*1024), 1)  # MB
                self.log.info(f"  {name}: {sizes[name]:.1f} MB")

        self.status["disk_audit"] = sizes


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    agent = OperationsMonitor()
    agent.execute(mode=mode)
