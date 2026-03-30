"""
The Workhorse — Scheduled Maintenance
Runs weekly (or on-demand) to keep the system clean and sterile.

Tasks:
  1. Clean temp files older than 24 hours
  2. Clean browser caches (Edge, Chrome — not Playwright session cookies)
  3. Clean old log files (>30 days)
  4. Clean stale command runner results (>7 days)
  5. Flush DNS cache
  6. Report disk usage
  7. Check for Windows Defender definition freshness
  8. Verify privacy registry keys haven't been reset by Windows Update

Usage:
    python workhorse-maintenance.py          # Full run
    python workhorse-maintenance.py --quick  # Just temp + cache cleanup
"""

import os
import sys
import json
import time
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Bootstrap rudy.paths
_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))
from rudy.paths import RUDY_LOGS, DESKTOP  # noqa: E402

LOGDIR = RUDY_LOGS
LOGDIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGDIR / "maintenance.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("maintenance")

quick_mode = "--quick" in sys.argv
results = {"timestamp": datetime.now().isoformat(), "mode": "quick" if quick_mode else "full", "tasks": {}}


def clean_old_files(directory, max_age_days, extensions=None, dry_run=False):
    """Remove files older than max_age_days. Returns (count, bytes_freed)."""
    cutoff = time.time() - (max_age_days * 86400)
    count = 0
    freed = 0
    directory = Path(directory)
    if not directory.exists():
        return 0, 0
    for f in directory.rglob("*"):
        try:
            if not f.is_file():
                continue
            if extensions and f.suffix.lower() not in extensions:
                continue
            if f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                count += 1
                freed += size
        except (PermissionError, OSError):
            pass
    return count, freed


# === 1. Temp files ===
log.info("=" * 40)
log.info("1. Cleaning temp files (>24h old)")
total_freed = 0
for td in [os.environ.get("TEMP", ""), os.environ.get("TMP", ""), r"C:\Windows\Temp"]:
    if td and os.path.exists(td):
        count, freed = clean_old_files(td, max_age_days=1)
        mb = freed / 1024 / 1024
        total_freed += mb
        log.info(f"   {td}: {count} files, {mb:.1f} MB freed")
results["tasks"]["temp_cleanup"] = {"freed_mb": round(total_freed, 1)}

# === 2. Browser caches ===
log.info("2. Cleaning browser caches")
browser_dirs = {
    "Edge Cache": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache"),
    "Edge Code Cache": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Code Cache"),
    "Chrome Cache": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache"),
    "Chrome Code Cache": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Code Cache"),
}
cache_freed = 0
for name, cache_dir in browser_dirs.items():
    if os.path.exists(cache_dir):
        try:
            size = sum(f.stat().st_size for f in Path(cache_dir).rglob("*") if f.is_file())
            shutil.rmtree(cache_dir, ignore_errors=True)
            mb = size / 1024 / 1024
            cache_freed += mb
            log.info(f"   {name}: {mb:.1f} MB cleared")
        except Exception:
            pass

# Also clean Edge/Chrome cookies and site data (NOT Playwright sessions)
cookie_dirs = {
    "Edge Cookies": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cookies"),
    "Chrome Cookies": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cookies"),
}
for name, cookie_file in cookie_dirs.items():
    if os.path.exists(cookie_file):
        try:
            size = os.path.getsize(cookie_file)
            os.unlink(cookie_file)
            mb = size / 1024 / 1024
            cache_freed += mb
            log.info(f"   {name}: {mb:.2f} MB cleared")
        except Exception:
            log.info(f"   {name}: locked (browser running?)")

results["tasks"]["browser_cache"] = {"freed_mb": round(cache_freed, 1)}

if quick_mode:
    log.info(f"\nQuick mode complete. Total freed: {total_freed + cache_freed:.1f} MB")
    results["total_freed_mb"] = round(total_freed + cache_freed, 1)
    (LOGDIR / "maintenance-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    sys.exit(0)

# === 3. Old log rotation ===
log.info("3. Rotating old logs (>30 days)")
log_count, log_freed = clean_old_files(LOGDIR, max_age_days=30, extensions={".log", ".json.old"})
log.info(f"   Removed {log_count} old log files ({log_freed/1024/1024:.1f} MB)")

# === 4. Stale command results ===
log.info("4. Cleaning stale command results (>7 days)")
cmd_dir = DESKTOP / "rudy-commands"
if cmd_dir.exists():
    count, freed = clean_old_files(cmd_dir, max_age_days=7, extensions={".result", ".json"})
    log.info(f"   Removed {count} stale result files ({freed/1024:.1f} KB)")

# === 5. DNS flush ===
log.info("5. Flushing DNS cache")
try:
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10)
    log.info("   DNS cache flushed")
except Exception:
    pass

# === 6. Disk usage report ===
log.info("6. Disk usage report")
try:
    out = subprocess.check_output(
        ["powershell", "-Command",
         "Get-PSDrive -PSProvider FileSystem | Select Name,@{N='Used(GB)';E={[math]::Round($_.Used/1GB,1)}},@{N='Free(GB)';E={[math]::Round($_.Free/1GB,1)}} | Format-Table"],
        text=True, timeout=10
    )
    for line in out.strip().split("\n"):
        if line.strip():
            log.info(f"   {line.strip()}")
    results["tasks"]["disk_usage"] = out.strip()
except Exception:
    pass

# === 7. Defender definitions check ===
log.info("7. Windows Defender status")
try:
    out = subprocess.check_output(
        ["powershell", "-Command",
         "Get-MpComputerStatus | Select RealTimeProtectionEnabled, AntivirusSignatureLastUpdated | Format-List"],
        text=True, timeout=15
    )
    for line in out.strip().split("\n"):
        if line.strip():
            log.info(f"   {line.strip()}")
except Exception:
    log.info("   Could not query Defender status")

# === 8. Verify privacy settings ===
log.info("8. Verifying privacy registry keys")
privacy_checks = {
    "Telemetry": (r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", "0x0"),
    "Advertising ID": (r"HKCU\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", "0x0"),
    "Activity Feed": (r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", "0x0"),
    "Bing Search": (r"HKCU\Software\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", "0x0"),
}
drift_found = False
for name, (key, value, expected) in privacy_checks.items():
    try:
        out = subprocess.check_output(
            ["reg", "query", key, "/v", value],
            text=True, timeout=5, stderr=subprocess.STDOUT
        )
        if expected in out:
            log.info(f"   OK: {name}")
        else:
            log.warning(f"   DRIFT: {name} — may have been reset by Windows Update!")
            drift_found = True
    except Exception:
        log.warning(f"   MISSING: {name} — registry key not set")
        drift_found = True

if drift_found:
    log.warning("   Privacy settings have drifted. Run harden-privacy.py to re-apply.")
    results["privacy_drift"] = True
else:
    results["privacy_drift"] = False

# === Summary ===
grand_total = total_freed + cache_freed + log_freed / 1024 / 1024
results["total_freed_mb"] = round(grand_total, 1)
log.info(f"\nMaintenance complete. Total freed: {grand_total:.1f} MB")
log.info(f"Privacy drift detected: {drift_found}")

(LOGDIR / "maintenance-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
