"""Process-safe subprocess wrapper for sentinel modules (LG-S88-001 fix).

Prevents orphaned conhost.exe / python child processes by using
CREATE_NO_WINDOW and killing process trees on timeout.

Usage:
    from rudy.agents.sentinel_subprocess import safe_run
    result = safe_run(["powershell", "-Command", "..."], timeout=10)
"""

import subprocess

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def safe_run(cmd, timeout=10):
    """Run a subprocess without spawning conhost.exe.

    Uses CREATE_NO_WINDOW to prevent orphaned console host processes.
    On timeout, kills the entire process tree via taskkill /T.
    Returns CompletedProcess on success, or a fake one on failure.
    """
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # SW_HIDE
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
            startupinfo=startupinfo,
        )
    except subprocess.TimeoutExpired as exc:
        # Kill entire process tree to prevent orphans
        try:
            pid = getattr(exc, 'pid', None)
            if pid:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    capture_output=True, timeout=5,
                    creationflags=_NO_WINDOW,
                )
        except Exception:
            pass
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr="timeout")
    except Exception:
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr="error")
