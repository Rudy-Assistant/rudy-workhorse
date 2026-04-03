import subprocess, sys, os, json
from datetime import datetime

LOG = r"C:\Users\ccimi\rudy-data\logs\launcher-watchdog.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a", encoding="utf-8") as f:
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
vbs = r"C:\Users\ccimi\rudy-workhorse\scripts\hidden-launch.vbs"
cmd = ("cmd /c C:\\Python312\\python.exe "
       "C:\\Users\\ccimi\\rudy-workhorse\\scripts\\launch_cowork.py "
       "--loop --interval 2")
if os.path.exists(vbs):
    subprocess.Popen(["wscript.exe", vbs, cmd],
                     cwd=r"C:\Users\ccimi\rudy-workhorse")
    log("Restarted via hidden-launch.vbs")
else:
    subprocess.Popen(
        ["C:\\Python312\\python.exe",
         r"C:\Users\ccimi\rudy-workhorse\scripts\launch_cowork.py",
         "--loop", "--interval", "2"],
        cwd=r"C:\Users\ccimi\rudy-workhorse",
        creationflags=0x00000008)
    log("Restarted via direct Popen")
