"""
Admin Helper — run commands with elevated privileges.
Since UAC consent prompts are disabled (ConsentPromptBehaviorAdmin=0),
Start-Process -Verb RunAs succeeds silently without a prompt.

Usage:
    from rudy.admin import run_elevated, run_elevated_ps

    # Run a single command elevated
    success, output = run_elevated("schtasks /query /tn WorkhorseHealthCheck")

    # Run a PowerShell script elevated
    success, output = run_elevated_ps("Get-Service RustDesk | Restart-Service")
"""
import subprocess

import os
import time

from rudy.paths import RUDY_LOGS  # noqa: E402

LOG_DIR = RUDY_LOGS

def run_elevated(cmd: str, timeout: int = 60) -> tuple[bool, str]:
    """Run a command with admin elevation. Returns (success, output)."""
    output_file = LOG_DIR / f"_elevated_output_{os.getpid()}.txt"

    # Wrap command to capture output to a file
    wrapped = f'{cmd} > "{output_file}" 2>&1'

    try:
        result = subprocess.run(
            f'powershell -Command "Start-Process cmd -ArgumentList \'/c {wrapped}\' -Verb RunAs -Wait"',
            shell=True, capture_output=True, text=True, timeout=timeout
        )

        time.sleep(1)
        output = ""
        if output_file.exists():
            output = output_file.read_text(encoding="utf-8", errors="replace")
            output_file.unlink(missing_ok=True)

        return result.returncode == 0, output
    except Exception as e:
        return False, str(e)

def run_elevated_ps(script: str, timeout: int = 60) -> tuple[bool, str]:
    """Run a PowerShell script with admin elevation. Returns (success, output)."""
    output_file = LOG_DIR / f"_elevated_ps_output_{os.getpid()}.txt"
    script_file = LOG_DIR / f"_elevated_ps_script_{os.getpid()}.ps1"

    # Write script to temp file, with output capture
    full_script = f'{script}\n'
    script_file.write_text(full_script, encoding="utf-8")

    try:
        result = subprocess.run(
            f'powershell -Command "Start-Process powershell -ArgumentList \'-ExecutionPolicy Bypass -File \\\"{script_file}\\\" *> \\\"{output_file}\\\"\' -Verb RunAs -Wait"',
            shell=True, capture_output=True, text=True, timeout=timeout
        )

        time.sleep(1)
        output = ""
        if output_file.exists():
            output = output_file.read_text(encoding="utf-8", errors="replace")
            output_file.unlink(missing_ok=True)

        script_file.unlink(missing_ok=True)
        return result.returncode == 0, output
    except Exception as e:
        script_file.unlink(missing_ok=True)
        return False, str(e)

def is_elevated() -> bool:
    """Check if we're currently running with admin privileges."""
    try:
        result = subprocess.run("net session", shell=True, capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
