import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

# Derive paths from script location (scripts/ is inside repo root)
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO = SCRIPTS_DIR.parent
RUDY_DATA = REPO.parent / "rudy-data"
LOG_PATH = RUDY_DATA / "logs" / "launcher-watchdog.log"
PYTHON = Path(sys.executable)
VBS = SCRIPTS_DIR / "hidden-launch.vbs"
LAUNCHER = SCRIPTS_DIR / "launch_cowork.py"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


# Check if launch_cowork.py is running
r = subprocess.run(
    ["powershell", "-Command",
     "Get-WmiObject Win32_Process -Filter \"Name='python.exe'\" | "
     "Where-Object { $_.CommandLine -like '*launch_cowork*' } | "
     "Select-Object ProcessId | ConvertTo-Json"],
    capture_output=True, text=True, timeout=15
)

if r.stdout.strip() and r.stdout.strip() != "null":
    log("Launcher loop running. No action.")
    sys.exit(0)

# Not running — start it
log("Launcher loop NOT running — restarting...")
cmd = f"cmd /c {PYTHON} {LAUNCHER} --loop --interval 2"
if VBS.exists():
    subprocess.Popen(["wscript.exe", str(VBS), cmd], cwd=str(REPO))
    log("Restarted via hidden-launch.vbs")
else:
    subprocess.Popen(
        [str(PYTHON), str(LAUNCHER), "--loop", "--interval", "2"],
        cwd=str(REPO),
        creationflags=0x00000008)
    log("Restarted via direct Popen")

