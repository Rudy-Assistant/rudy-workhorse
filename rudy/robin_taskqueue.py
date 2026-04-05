#!/usr/bin/env python3

"""
Robin Task Queue — Extended Absence Operating Framework.

When Batman declares absence (or idle is detected), Robin doesn't just
run a canned script. Robin works through a prioritized task queue,
making real decisions, producing tangible output, and escalating when needed.

Architecture:
    1. Task queue lives at rudy-data/robin-taskqueue/active.json
    2. Robin polls the queue on each night shift cycle
    3. Each task has a type, priority, estimated duration, and dependencies
    4. Robin picks the highest-priority unblocked task and executes it
    5. Results are logged to rudy-data/robin-taskqueue/completed/
    6. If Robin hits a blocker, it logs it and moves to the next task
    7. Robin can ADD tasks to the queue based on discoveries

Task Types:
    - audit: Run Lucius scans, save findings
    - browse: Use browser tool to check URLs / scrape data
    - profile: Run environment profiler, update profile
    - code_quality: Run linting, dead code detection, test generation
    - git: Commit findings, push to branch
    - report: Write summary reports for Batman review
    - handoff: Prepare context handoff prompt for next Alfred session
    - colab: Trigger Colab self-improvement workflow (when available)

Integration:
    - Night shift calls robin_taskqueue.process_next_task() on each cycle
    - Alfred can seed the queue by writing to active.json
    - Robin can self-seed based on discoveries (e.g., "I found stale logs, add cleanup task")

Lucius Gate: LG-005 — No new dependencies. Stdlib only. APPROVED, Lite Review.
"""

import json
import os
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from rudy.sanitize import sanitize_str as _sanitize_str_shared
from rudy.paths import REPO_ROOT, RUDY_DATA

logger = logging.getLogger("robin.taskqueue")


# ---------------------------------------------------------------------------
# Input Sanitization (F2: prevent injection via task metadata)
# ---------------------------------------------------------------------------

# Shared sanitization (canonical: rudy/sanitize.py)


def _sanitize_metadata_string(value: str, max_length: int = 500, url_mode: bool = False) -> str:
    return _sanitize_str_shared(value, max_length=max_length, url_mode=url_mode)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


QUEUE_DIR = RUDY_DATA / "robin-taskqueue"
ACTIVE_QUEUE = QUEUE_DIR / "active.json"
COMPLETED_DIR = QUEUE_DIR / "completed"
BLOCKED_DIR = QUEUE_DIR / "blocked"
RUDY_ROOT = REPO_ROOT

# Executable paths — detect dynamically, fall back to known Windows locations
def _find_exe(name: str, fallbacks: list) -> str:
    """Find an executable on PATH or in known locations."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    for fb in fallbacks:
        if Path(fb).exists():
            return fb
    return name  # Last resort: bare name, hope PATH resolves it

GIT_EXE = _find_exe("git", [r"C:\Program Files\Git\cmd\git.exe", r"C:\Program Files (x86)\Git\cmd\git.exe"])
PYTHON = _find_exe("python", [r"C:\Python312\python.exe", r"C:\Python311\python.exe", sys.executable])

# Branch protection: Robin must NEVER push directly to main
PROTECTED_BRANCHES = frozenset({"main", "master"})
ROBIN_AUTO_BRANCH = "robin/autonomous-work"

# ---------------------------------------------------------------------------
# Task Schema
# ---------------------------------------------------------------------------

def make_task(
    task_type: str,
    title: str,
    description: str,
    priority: int = 50,
    estimated_minutes: int = 5,
    command: Optional[list] = None,
    python_code: Optional[str] = None,
    depends_on: Optional[list] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Create a task for the queue."""
    return {
        "id": str(uuid.uuid4())[:8],
        "type": task_type,
        "title": title,
        "description": description,
        "priority": priority,  # 0=highest, 100=lowest
        "estimated_minutes": estimated_minutes,
        "status": "pending",
        "command": command,
        "python_code": python_code,
        "depends_on": depends_on or [],
        "metadata": metadata or {},
        "created": datetime.now().isoformat(),
        "started": None,
        "completed": None,
        "result": None,
        "error": None,
    }

# ---------------------------------------------------------------------------
# Queue Management
# ---------------------------------------------------------------------------

def _ensure_dirs():
    """Create queue directories if needed."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)
    BLOCKED_DIR.mkdir(parents=True, exist_ok=True)

def load_queue() -> list[dict]:
    """Load the active task queue."""
    _ensure_dirs()
    if ACTIVE_QUEUE.exists():
        try:
            return json.loads(ACTIVE_QUEUE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []

def save_queue(tasks: list[dict]):
    """Save the active task queue."""
    _ensure_dirs()
    ACTIVE_QUEUE.write_text(
        json.dumps(tasks, indent=2, default=str),
        encoding="utf-8"
    )

def add_task(task: dict):
    """Add a task to the queue (skips if duplicate pending task exists)."""
    queue = load_queue()
    # Dedup: skip if a pending task with same type+title already exists
    for existing in queue:
        if (existing.get("status") == "pending"
                and existing.get("type") == task.get("type")
                and existing.get("title") == task.get("title")):
            logger.debug(f"Skipping duplicate: [{task['type']}] {task['title']}")
            return
    queue.append(task)
    # Sort by priority (lower number = higher priority)
    queue.sort(key=lambda t: t.get("priority", 50))
    save_queue(queue)
    logger.info(f"Task added: [{task['type']}] {task['title']} (priority {task['priority']})")

def get_next_task() -> Optional[dict]:
    """Get the highest-priority unblocked pending task."""
    queue = load_queue()
    completed_ids = {t["id"] for t in queue if t.get("status") == "completed"}

    for task in queue:
        if task["status"] != "pending":
            continue
        # Check dependencies
        deps = task.get("depends_on", [])
        if all(d in completed_ids for d in deps):
            return task

    return None

def complete_task(task_id: str, result: str, success: bool = True):
    """Mark a task as completed and archive it."""
    queue = load_queue()
    for task in queue:
        if task["id"] == task_id:
            task["status"] = "completed" if success else "failed"
            task["completed"] = datetime.now().isoformat()
            task["result"] = result[:5000]  # Cap result size

            # Archive to completed dir
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive = COMPLETED_DIR / f"{ts}_{task_id}_{task['type']}.json"
            archive.write_text(json.dumps(task, indent=2, default=str), encoding="utf-8")
            break

    # Remove completed/failed from active queue
    queue = [t for t in queue if t["status"] == "pending"]
    save_queue(queue)

def block_task(task_id: str, reason: str):
    """Move a task to blocked status."""
    queue = load_queue()
    for task in queue:
        if task["id"] == task_id:
            task["status"] = "blocked"
            task["error"] = reason
            # Archive
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive = BLOCKED_DIR / f"{ts}_{task_id}_blocked.json"
            archive.write_text(json.dumps(task, indent=2, default=str), encoding="utf-8")
            break

    queue = [t for t in queue if t["status"] == "pending"]
    save_queue(queue)


# ---------------------------------------------------------------------------
# Mutual Exclusion (F6: prevent concurrent watchdog/sentinel execution)
# ---------------------------------------------------------------------------

LOCK_FILE = QUEUE_DIR / ".taskqueue.lock"
LOCK_MAX_AGE_SECONDS = 600  # 10 minutes

def _acquire_lock() -> bool:
    """
    Acquire the task queue lock. Returns True if lock acquired.
    Uses PID-based stale lock detection (Risk R5 mitigation).
    """
    _ensure_dirs()
    if LOCK_FILE.exists():
        try:
            lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            lock_pid = lock_data.get("pid", -1)
            lock_time = lock_data.get("timestamp", 0)
            # Check if lock holder is still alive
            try:
                os.kill(lock_pid, 0)  # Signal 0 = check existence
                # Process alive — check age
                age = time.time() - lock_time
                if age < LOCK_MAX_AGE_SECONDS:
                    logger.warning(f"Lock held by PID {lock_pid} (age {int(age)}s). Skipping.")
                    return False
                else:
                    logger.warning(f"Stale lock (age {int(age)}s). Stealing from PID {lock_pid}.")
            except OSError:
                logger.info(f"Lock holder PID {lock_pid} is dead. Stealing lock.")
        except (json.JSONDecodeError, OSError, KeyError):
            logger.info("Corrupt lock file. Overwriting.")

    # Write our lock
    lock_data = {"pid": os.getpid(), "timestamp": time.time()}
    LOCK_FILE.write_text(json.dumps(lock_data), encoding="utf-8")
    return True

def _release_lock():
    """Release the task queue lock."""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Task Executors
# ---------------------------------------------------------------------------

def _execute_command(cmd: list, timeout: int = 120) -> tuple[bool, str]:
    """Run a subprocess command and return (success, output).

    Includes branch protection: blocks any git push to protected branches.
    """
    # ── Branch protection guard ──
    if len(cmd) >= 3 and "git" in str(cmd[0]).lower():
        if cmd[1] == "push":
            # Check if any arg is a protected branch name
            push_args = cmd[2:]
            for arg in push_args:
                if arg in PROTECTED_BRANCHES:
                    logger.error(f"BLOCKED: Robin attempted to push to protected branch '{arg}'")
                    return False, f"BLOCKED: push to protected branch '{arg}' is forbidden"

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(RUDY_ROOT), encoding="utf-8", errors="replace"
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output[-3000:]
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    except Exception as e:
        return False, str(e)

def _execute_python(code: str, timeout: int = 120) -> tuple[bool, str]:
    """Run Python code and return (success, output)."""
    return _execute_command([PYTHON, "-c", code], timeout)


def _execute_via_agent(task: dict, timeout: int = 300) -> tuple[bool, str]:
    """Delegate a task to RobinAgent (Ollama) for open-ended execution.

    Used when the task has no explicit command and doesn't match a
    hardcoded task type. The agent can reason about the task and
    use MCP tools (Shell, Snapshot, etc.) to accomplish it.
    """
    try:
        from rudy.robin_agent import RobinAgent
        from rudy.robin_mcp_client import MCPServerRegistry

        # Load secrets for MCP connections
        secrets = {}
        secrets_file = RUDY_DATA / "robin-secrets.json"
        if secrets_file.exists():
            try:
                secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Determine model
        model = secrets.get("ollama_model", "qwen2.5:7b")

        # Build task prompt with full context
        # Sanitize task metadata before embedding in prompt (F2: prevent injection)
        safe_title = _sanitize_metadata_string(task.get('title', 'Unknown task'), max_length=200)
        safe_desc = _sanitize_metadata_string(task.get('description', 'No description provided.'))

        task_prompt = f"""TASK: {safe_title}

DESCRIPTION: {safe_desc}

PRIORITY: {task.get('priority', 'medium')}

INSTRUCTIONS: Execute this task completely. Use Shell commands for file operations,
code execution, and system tasks. Use Snapshot only for UI tasks. When done,
provide a clear summary of what you accomplished and any results.

If the task involves reading or analyzing files, use Shell with Get-Content or python.
If the task involves running scripts, use Shell with the appropriate interpreter.
If the task is research, use brave-search to find information.

Do NOT ask for clarification. Do your best with the information given.
If you cannot complete the task, explain specifically what blocked you."""

        # Connect MCP servers (exclude Windows-MCP visual tools for agent tasks)
        # LF-S53-001: qwen2.5:7b defaults to Snapshot and describes screenshots
        # instead of executing tasks. Shell (Desktop Commander) is safe.
        registry = MCPServerRegistry(secrets)
        # Connect only non-visual MCP servers for agent tasks
        for server_name in list(registry._configs.keys()):
            if server_name == "windows-mcp":
                continue  # Skip visual tools (Snapshot, Click, Type)
            registry.connect(server_name)

        try:
            agent = RobinAgent(
                registry=registry,
                model=model,
                max_steps=10,
            )
            result = agent.run(task_prompt)

            if result.success:
                return True, result.final_answer[:3000]
            else:
                return False, f"Agent failed: {result.final_answer[:2000]}"
        finally:
            registry.disconnect_all()

    except ImportError as e:
        logger.warning("RobinAgent not available: %s", e)
        return False, f"Agent unavailable: {e}"
    except Exception as e:
        logger.error("Agent execution error: %s", e)
        return False, f"Agent error: {e}"

def execute_task(task: dict) -> tuple[bool, str]:
    """
    Execute a task based on its type.

    Returns (success, result_text).
    """
    # Defensive: ensure task has an id (batch-seeded tasks may lack one, LF-S51-001)
    if "id" not in task:
        task["id"] = str(uuid.uuid4())[:8]
        logger.warning(f"Task missing 'id' field, generated: {task['id']}")
    task_type = task.get("type", "unknown")
    logger.info(f"Executing [{task_type}]: {task['title']}")

    # Command-based tasks
    if task.get("command"):
        return _execute_command(task["command"], timeout=task.get("estimated_minutes", 5) * 60)

    # Python code tasks
    if task.get("python_code"):
        return _execute_python(task["python_code"], timeout=task.get("estimated_minutes", 5) * 60)

    # Type-specific executors (checked BEFORE agent fallback to prevent bypass)
    if task_type == "audit":
        return _execute_command(
            [PYTHON, "-m", "rudy.agents.lucius_fox", "hygiene_check"],
            timeout=120
        )

    elif task_type == "profile":
        return _execute_command(
            [PYTHON, "-m", "rudy.environment_profiler"],
            timeout=60
        )

    elif task_type == "browse":
        url = _sanitize_metadata_string(task.get("metadata", {}).get("url", "https://example.com"), max_length=2000, url_mode=True)
        # S43 fix: write standalone script instead of inline -c (avoids cp1252 Unicode crash)
        browse_script = RUDY_DATA / "robin_browse.py"
        browse_script.write_text(
            f"""import sys, os\nos.environ["PYTHONIOENCODING"] = "utf-8"\nsys.path.insert(0, r"{RUDY_ROOT}")\ntry:\n    from rudy.tools.browser_tool import browse\n    r = browse("{url}")\n    title = (r.title or "").encode("ascii", errors="replace").decode("ascii")\n    print(f"Title: {{title}}")\n    print(f"Success: {{r.success}}")\n    text = (r.text[:2000] if r.text else "No text").encode("ascii", errors="replace").decode("ascii")\n    print(text)\nexcept Exception as e:\n    print(f"Browse error: {{e}}")""",
            encoding="utf-8"
        )
        return _execute_command([PYTHON, str(browse_script)], timeout=60)

    elif task_type == "git":
        action = task.get("metadata", {}).get("action", "status")
        if action == "status":
            return _execute_command([GIT_EXE, "status", "--short"])
        elif action == "commit_and_push":
            msg = _sanitize_metadata_string(task.get("metadata", {}).get("message", "Robin automated commit"))
            robin_auto_branch = ROBIN_AUTO_BRANCH

            # ── Safety: ensure we NEVER commit on main ──
            _, current_branch = _execute_command([GIT_EXE, "rev-parse", "--abbrev-ref", "HEAD"])
            current_branch = (current_branch or "").strip()

            # Switch to Robin autonomous branch (create if needed)
            # S43 fix: stash dirty working tree before switching branches
            if current_branch != robin_auto_branch:
                _execute_command([GIT_EXE, "stash", "push", "-m", "robin-auto-autostash"])
                ok_co, _ = _execute_command([GIT_EXE, "checkout", robin_auto_branch])
                if not ok_co:
                    ok_co, _ = _execute_command([GIT_EXE, "checkout", "-b", robin_auto_branch])
                if not ok_co:
                    # Restore stash before aborting
                    _execute_command([GIT_EXE, "stash", "pop"])
                    logger.error("Cannot switch to autonomous branch -- aborting commit")
                    return False, "Failed to switch to autonomous branch"
                logger.info(f"Switched to branch: {robin_auto_branch}")

            # F1: Explicit file list instead of blind git add -A
            safe_paths = [
                "rudy-data/robin-taskqueue/",
                "rudy-data/environment-profile.json",
                "rudy-data/lucius-reviews/",
                "rudy-data/alfred-inbox/",
                "rudy-data/robin-inbox/",
                "rudy-data/batcave-memory/",
            ]
            staged_files = []
            for sp in safe_paths:
                full = RUDY_ROOT / sp
                if full.exists():
                    success_add, out_add = _execute_command([GIT_EXE, "add", str(full)])
                    if success_add:
                        staged_files.append(sp)
            logger.info(f"Staged {len(staged_files)} paths: {staged_files}")
            if not staged_files:
                # Switch back to main even if nothing to stage
                _execute_command([GIT_EXE, "checkout", "main"])
                _execute_command([GIT_EXE, "stash", "pop"])
                return False, "No files to stage"

            # Check if there's actually anything staged to commit
            ok_diff, diff_out = _execute_command([GIT_EXE, "diff", "--cached", "--stat"])
            if ok_diff and not (diff_out or "").strip():
                logger.info("Nothing staged after git add — no changes to commit")
                _execute_command([GIT_EXE, "checkout", "main"])
                _execute_command([GIT_EXE, "stash", "pop"])
                return True, "No changes to commit (files unchanged)"

            success2, out2 = _execute_command([GIT_EXE, "commit", "-m", msg])
            success3, out3 = _execute_command([GIT_EXE, "push", "origin", robin_auto_branch])

            # Always return to main after autonomous commit
            _execute_command([GIT_EXE, "checkout", "main"])
            _execute_command([GIT_EXE, "stash", "pop"])
            return all([success2, success3]), f"Staged: {staged_files}\n{out2}\n{out3}"
        return False, f"Unknown git action: {action}"

    elif task_type == "pr_create":
        # S43 stretch: Robin can independently create PRs from autonomous findings
        branch_name = _sanitize_metadata_string(
            task.get("metadata", {}).get("branch", "robin/autonomous-findings"),
            max_length=100
        )
        title = _sanitize_metadata_string(
            task.get("metadata", {}).get("title", "Robin: Autonomous findings"),
            max_length=200
        )
        body = _sanitize_metadata_string(
            task.get("metadata", {}).get("body", "Automated PR from Robin night shift cycle."),
            max_length=2000
        )

        # Safety: never create PRs targeting protected branches directly
        if branch_name in PROTECTED_BRANCHES:
            return False, f"BLOCKED: branch name '{branch_name}' is protected"

        # Step 1: Stash, create branch, stage safe files
        _execute_command([GIT_EXE, "stash", "push", "-m", "robin-pr-autostash"])

        ok_br, _ = _execute_command([GIT_EXE, "checkout", "-b", branch_name])
        if not ok_br:
            # Branch exists, try checkout
            ok_br, _ = _execute_command([GIT_EXE, "checkout", branch_name])
        if not ok_br:
            _execute_command([GIT_EXE, "stash", "pop"])
            return False, f"Cannot create/switch to branch: {branch_name}"

        # Step 2: Stage safe paths only
        safe_paths = [
            "rudy-data/robin-taskqueue/",
            "rudy-data/environment-profile.json",
            "rudy-data/lucius-reviews/",
        ]
        staged = []
        for sp in safe_paths:
            full = RUDY_ROOT / sp
            if full.exists():
                ok_add, _ = _execute_command([GIT_EXE, "add", str(full)])
                if ok_add:
                    staged.append(sp)

        # Step 3: Check if anything staged
        ok_diff, diff_out = _execute_command([GIT_EXE, "diff", "--cached", "--stat"])
        if ok_diff and not (diff_out or "").strip():
            logger.info("PR creation: nothing to commit")
            _execute_command([GIT_EXE, "checkout", "main"])
            _execute_command([GIT_EXE, "branch", "-D", branch_name])
            _execute_command([GIT_EXE, "stash", "pop"])
            return True, "No changes to PR (files unchanged)"

        # Step 4: Commit
        ok_commit, commit_out = _execute_command(
            [GIT_EXE, "commit", "-m", f"robin: {title}"]
        )

        # Step 5: Push
        ok_push, push_out = _execute_command(
            [GIT_EXE, "push", "origin", branch_name]
        )

        # Step 6: Create PR via gh CLI
        ok_pr, pr_out = _execute_command(
            ["gh", "pr", "create",
             "--title", title,
             "--body", body,
             "--head", branch_name,
             "--base", "main",
             "--repo", "Rudy-Assistant/rudy-workhorse"],
            timeout=30
        )

        # Step 7: Return to main, restore stash
        _execute_command([GIT_EXE, "checkout", "main"])
        _execute_command([GIT_EXE, "stash", "pop"])

        if ok_pr:
            logger.info(f"Robin created PR: {pr_out.strip()[:200]}")
            return True, f"PR created: {pr_out.strip()[:500]}"
        elif ok_commit and ok_push:
            logger.info(f"Robin pushed branch but PR creation failed: {pr_out[:200]}")
            return True, f"Branch pushed (PR creation failed): {push_out[:200]}"
        else:
            return False, f"PR workflow failed: commit={ok_commit} push={ok_push} pr={ok_pr}"


    elif task_type == "code_quality":
        # Run ruff linter if available — use paths.PYTHON_EXE for correct env
        try:
            from rudy.paths import PYTHON_EXE as _py_exe
        except ImportError:
            _py_exe = PYTHON
        return _execute_command(
            [_py_exe, "-m", "ruff", "check", str(RUDY_ROOT / "rudy"), "--output-format=concise"],
            timeout=60
        )

    elif task_type == "report":
        # Generate a summary report of recent activity (standalone script)
        script = RUDY_DATA / "robin_activity_summary.py"
        if script.exists():
            return _execute_command([PYTHON, str(script)], timeout=30)
        return False, "robin_activity_summary.py not found in rudy-data/"

    elif task_type == "handoff":
        # Check for Alfred handoff briefs (standalone script)
        script = RUDY_DATA / "robin_handoff_check.py"
        if script.exists():
            return _execute_command([PYTHON, str(script)], timeout=30)
        return False, "robin_handoff_check.py not found in rudy-data/"

    elif task_type == "health_check":
        # System health check: CPU, RAM, disk, uptime
        commands = [
            ("cpu_ram", "wmic cpu get LoadPercentage /value & wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value"),
            ("disk", "wmic logicaldisk get Size,FreeSpace,Caption /value"),
            ("uptime", "net statistics workstation | findstr Statistics"),
        ]
        results = []
        for name, cmd in commands:
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, shell=True,  # nosec B602
                    timeout=30, encoding="utf-8", errors="replace",
                )
                results.append(f"--- {name} ---\n{r.stdout.strip()}")
            except Exception as e:
                results.append(f"--- {name} --- ERROR: {e}")
        output = "\n".join(results)
        return True, output[-3000:]

    elif task_type == "security_scan":
        # Security sweep: Defender, firewall, open ports
        commands = [
            ("defender", 'powershell -Command "Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,AntivirusSignatureLastUpdated | Format-List"'),
            ("firewall", "netsh advfirewall show allprofiles state"),
            ("ports", "netstat -an | findstr LISTENING"),
        ]
        results = []
        for name, cmd in commands:
            try:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, shell=True,  # nosec B602
                    timeout=30, encoding="utf-8", errors="replace",
                )
                out = r.stdout.strip()
                if name == "ports":
                    lines = out.split("\n")
                    out = f"{len(lines)} listening ports\n" + "\n".join(lines[:20])
                results.append(f"--- {name} ---\n{out}")
            except Exception as e:
                results.append(f"--- {name} --- ERROR: {e}")
        output = "\n".join(results)
        return True, output[-3000:]

    elif task_type == "shell":
        # Execute shell command (string or list) from delegation
        cmd = task.get("command")
        if isinstance(cmd, list):
            return _execute_command(cmd, timeout=task.get("estimated_minutes", 5) * 60)
        if not cmd:
            cmd = task.get("metadata", {}).get("command")
        if not cmd:
            return False, "shell task missing 'command' field"
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, shell=True,  # nosec B602
                timeout=task.get("estimated_minutes", 5) * 60,
                cwd=str(RUDY_ROOT), encoding="utf-8", errors="replace",
            )
            output = (r.stdout or "") + (r.stderr or "")
            return r.returncode == 0, output[-3000:]
        except subprocess.TimeoutExpired:
            return False, "TIMEOUT"
        except Exception as e:
            return False, str(e)

    else:
        # Delegate unknown task types to RobinAgent (Ollama) for open-ended execution
        logger.info(f"No hardcoded executor for [{task_type}] -- delegating to RobinAgent")
        return _execute_via_agent(task, timeout=task.get("estimated_minutes", 5) * 60)

# ---------------------------------------------------------------------------
# Main Loop (called by night shift or directly)
# ---------------------------------------------------------------------------


# --- Mailbox protocol integration (report task results to Alfred) ---
try:
    from rudy.robin_alfred_protocol import RobinMailbox as _RobinMailbox
    _HAS_MAILBOX = True
except ImportError:
    _HAS_MAILBOX = False


def _notify_alfred(task: dict, success: bool, result: str):
    """Report task completion/failure to Alfred via mailbox protocol."""
    if not _HAS_MAILBOX:
        return
    try:
        mailbox = _RobinMailbox()
        if success:
            mailbox.report_work(
                subject=f"Task completed: {task.get('title', 'unknown')}",
                summary=result[:500] if result else "Completed successfully",
                files_changed=task.get("files_changed", []),
            )
        else:
            mailbox.escalate(
                issue=f"Task failed: {task.get('title', 'unknown')}",
                context=result[:500] if result else "Unknown error",
                severity="medium" if task.get("priority", 5) > 2 else "high",
            )
    except Exception as e:
        logger.debug(f"Mailbox notification failed (non-fatal): {e}")

def process_next_task() -> Optional[dict]:
    """
    Pick and execute the next task from the queue.

    Returns the completed task dict, or None if queue is empty.
    """
    if not _acquire_lock():
        logger.warning("Could not acquire lock. Another instance is running.")
        return None
    try:
        task = get_next_task()
        if not task:
            logger.info("Task queue empty. Nothing to do.")
            return None

        # Mark as in-progress
        task["started"] = datetime.now().isoformat()
        task["status"] = "in_progress"

        # Execute
        success, result = execute_task(task)

        # Record result
        if success:
            complete_task(task["id"], result, success=True)
            logger.info(f"Task completed: {task['title']}")
            _notify_alfred(task, success=True, result=result)
        else:
            # Check if it's a transient error (retry) or permanent (block)
            if "TIMEOUT" in result or "connection" in result.lower():
                block_task(task["id"], f"Transient error: {result[:500]}")
                logger.warning(f"Task blocked (transient): {task['title']}")
            else:
                complete_task(task["id"], result, success=False)
                logger.warning(f"Task failed: {task['title']}: {result[:200].encode('ascii', errors='replace').decode('ascii')}")
                _notify_alfred(task, success=False, result=result)

        task["result"] = result
        return task
    finally:
        _release_lock()

def process_all(max_tasks: int = 10, max_minutes: int = 30):
    """
    Process tasks until queue empty, max reached, or time limit hit.

    This is what the night shift calls during Batman absence.
    """
    start = time.time()
    processed = 0

    logger.info(f"Processing task queue (max {max_tasks} tasks, {max_minutes} min)")

    while processed < max_tasks:
        elapsed = (time.time() - start) / 60
        if elapsed >= max_minutes:
            logger.info(f"Time limit reached ({max_minutes} min)")
            break

        result = process_next_task()
        if result is None:
            logger.info("Queue empty")
            break

        processed += 1

    logger.info(f"Processed {processed} tasks in {int(time.time()-start)}s")
    return processed


# ---------------------------------------------------------------------------
# Seed Cooldown (F7: prevent infinite re-seed loop)
# ---------------------------------------------------------------------------

SEED_TIMESTAMP_FILE = QUEUE_DIR / ".last_seed"
SEED_COOLDOWN_HOURS = 0  # S44: Batman directive — no cooldown. Safe because add_task() deduplicates.

def _can_reseed() -> bool:
    """Check if enough time has passed since last seed."""
    if not SEED_TIMESTAMP_FILE.exists():
        return True
    try:
        ts = float(SEED_TIMESTAMP_FILE.read_text(encoding="utf-8").strip())
        hours_since = (time.time() - ts) / 3600
        if hours_since < SEED_COOLDOWN_HOURS:
            logger.info(f"Seed cooldown: {hours_since:.1f}h since last seed (need {SEED_COOLDOWN_HOURS}h)")
            return False
        return True
    except (ValueError, OSError):
        return True

def _mark_seeded():
    """Record that we just seeded the queue."""
    _ensure_dirs()
    SEED_TIMESTAMP_FILE.write_text(str(time.time()), encoding="utf-8")

# ---------------------------------------------------------------------------
# Queue Seeding (Alfred pre-loads tasks before Batman leaves)
# ---------------------------------------------------------------------------

def seed_standard_tasks(force: bool = False):
    """
    Seed the queue with standard autonomous tasks.

    Called by Alfred when Batman declares absence.
    Args:
        force: If True, bypass cooldown check.
    """
    if not force and not _can_reseed():
        logger.info("Skipping seed: cooldown active")
        return 0
    tasks = [
        make_task("profile", "Refresh environment profile",
                  "Run environment profiler and update hardware profile",
                  priority=10, estimated_minutes=2),

        make_task("audit", "Lucius network security scan",
                  "Run passive network recon and save findings",
                  priority=20, estimated_minutes=2),

        make_task("browse", "Check Ollama release page",
                  "Browse Ollama releases for newer versions",
                  priority=40, estimated_minutes=2,
                  metadata={"url": "https://github.com/ollama/ollama/releases"}),

        make_task("browse", "Check LangGraph changelog",
                  "Browse LangGraph repo for updates since v1.1.3",
                  priority=40, estimated_minutes=2,
                  metadata={"url": "https://github.com/langchain-ai/langgraph/releases"}),

        make_task("code_quality", "Run linter on rudy/ package",
                  "Check code quality with ruff",
                  priority=50, estimated_minutes=3),

        make_task("handoff", "Check for Alfred handoff briefs",
                  "Scan rudy-data/handoffs/ for unfinished priorities. "
                  "If a new Alfred session is needed, prepare bootstrap prompt.",
                  priority=15, estimated_minutes=1),

        make_task("report", "Generate activity summary",
                  "Summarize completed tasks for Batman review",
                  priority=80, estimated_minutes=1),

        make_task("git", "Commit and push autonomous findings",
                  "Commit all new findings and push to branch",
                  priority=90, estimated_minutes=1,
                  metadata={"action": "commit_and_push",
                           "message": "robin: autonomous task queue results\n\nCo-Authored-By: Robin (qwen2.5:7b) <robin@batcave.local>"}),
    ]

    for task in tasks:
        add_task(task)

    _mark_seeded()
    logger.info(f"Seeded {len(tasks)} standard autonomous tasks")
    return len(tasks)

def seed_deep_work():
    """
    Seed extended deep-work tasks for longer Batman absences.

    These are added ON TOP of standard autonomous tasks.
    """
    tasks = [
        make_task("browse", "Monitor GitHub repo for new issues",
                  "Check if any new issues were filed on rudy-workhorse",
                  priority=30, estimated_minutes=2,
                  metadata={"url": "https://github.com/Rudy-Assistant/rudy-workhorse/issues"}),

        make_task("browse", "Check HuggingFace for new qwen models",
                  "Look for newer qwen2.5 model releases that might improve Robin",
                  priority=45, estimated_minutes=2,
                  metadata={"url": "https://huggingface.co/Qwen"}),

        make_task("browse", "Check browser-use alternatives",
                  "Monitor crawl4ai and playwright ecosystem for new tools",
                  priority=55, estimated_minutes=2,
                  metadata={"url": "https://github.com/unclecode/crawl4ai/releases"}),

        make_task("pr_create", "Create PR from autonomous findings",
                  "If night shift found changes worth committing, create a PR",
                  priority=95, estimated_minutes=2,
                  metadata={"branch": "robin/autonomous-auto",
                            "title": "Robin: Autonomous night shift findings",
                            "body": "Automated PR from Robin night shift cycle.\n\nIncludes environment profile updates, task queue state, and review artifacts."}),

        make_task("profile", "Re-run profiler after task execution",
                  "Check if RAM/CPU usage changed during night shift",
                  priority=85, estimated_minutes=2),
    ]

    for task in tasks:
        add_task(task)

    logger.info(f"Seeded {len(tasks)} deep work tasks")
    return len(tasks)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "seed":
            seed_standard_tasks(force=True)  # Manual seed bypasses cooldown
        elif cmd == "seed-deep":
            seed_standard_tasks(force=True)  # Manual seed bypasses cooldown
            seed_deep_work()
        elif cmd == "next":
            result = process_next_task()
            if result is None:
                sys.exit(1)  # Signal empty queue to callers
        elif cmd == "all":
            process_all()
        elif cmd == "status":
            queue = load_queue()
            print(f"Active queue: {len(queue)} tasks")
            for t in queue:
                print(f"  [{t['priority']:3d}] [{t['type']:12s}] {t['title']}")
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: robin_taskqueue.py [seed|seed-deep|next|all|status]")
    else:
        print("Robin Task Queue")
        print("Commands: seed, seed-deep, next, all, status")
        queue = load_queue()
        print(f"Current queue: {len(queue)} tasks")
