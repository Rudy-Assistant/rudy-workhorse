#!/usr/bin/env python3

"""
Robin Task Queue — Extended Absence Operating Framework.

When Batman declares absence (or idle is detected), Robin doesn't just
run a canned script. Robin works through a prioritized task queue,
making real decisions, producing tangible output, and escalating when needed.

Architecture:
    1. Task queue lives at rudy-data/robin-taskqueue/active.json
    2. Robin polls the queue on each NightShift cycle
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
    - NightShift calls robin_taskqueue.process_next_task() on each cycle
    - Alfred can seed the queue by writing to active.json
    - Robin can self-seed based on discoveries (e.g., "I found stale logs, add cleanup task")

Lucius Gate: LG-005 — No new dependencies. Stdlib only. APPROVED, Lite Review.
"""

import json
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("robin.taskqueue")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

QUEUE_DIR = Path(__file__).resolve().parent.parent / "rudy-data" / "robin-taskqueue"
ACTIVE_QUEUE = QUEUE_DIR / "active.json"
COMPLETED_DIR = QUEUE_DIR / "completed"
BLOCKED_DIR = QUEUE_DIR / "blocked"
RUDY_ROOT = Path(__file__).resolve().parent.parent
GIT_EXE = r"C:\Program Files\Git\cmd\git.exe"
PYTHON = r"C:\Python312\python.exe"


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
    """Add a task to the queue."""
    queue = load_queue()
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
# Task Executors
# ---------------------------------------------------------------------------

def _execute_command(cmd: list, timeout: int = 120) -> tuple[bool, str]:
    """Run a subprocess command and return (success, output)."""
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


def execute_task(task: dict) -> tuple[bool, str]:
    """
    Execute a task based on its type.

    Returns (success, result_text).
    """
    task_type = task.get("type", "unknown")
    logger.info(f"Executing [{task_type}]: {task['title']}")

    # Command-based tasks
    if task.get("command"):
        return _execute_command(task["command"], timeout=task.get("estimated_minutes", 5) * 60)

    # Python code tasks
    if task.get("python_code"):
        return _execute_python(task["python_code"], timeout=task.get("estimated_minutes", 5) * 60)

    # Type-specific executors
    if task_type == "audit":
        return _execute_command(
            [PYTHON, "-m", "rudy.agents.lucius_network_security"],
            timeout=120
        )

    elif task_type == "profile":
        return _execute_command(
            [PYTHON, "-m", "rudy.environment_profiler"],
            timeout=60
        )

    elif task_type == "browse":
        url = task.get("metadata", {}).get("url", "https://example.com")
        code = (
            f"import sys; sys.path.insert(0, r'{RUDY_ROOT}'); "
            f"from rudy.tools.browser_tool import browse; "
            f"r = browse('{url}'); "
            f"print(f'Title: {{r.title}}'); "
            f"print(f'Success: {{r.success}}'); "
            f"print(r.text[:2000] if r.text else 'No text')"
        )
        return _execute_python(code, timeout=60)

    elif task_type == "git":
        action = task.get("metadata", {}).get("action", "status")
        if action == "status":
            return _execute_command([GIT_EXE, "status", "--short"])
        elif action == "commit_and_push":
            msg = task.get("metadata", {}).get("message", "Robin automated commit")
            success1, out1 = _execute_command([GIT_EXE, "add", "-A"])
            success2, out2 = _execute_command([GIT_EXE, "commit", "-m", msg])
            success3, out3 = _execute_command([GIT_EXE, "push", "origin", "alfred/robin-logging-nightwatch"])
            return all([success1, success2, success3]), f"{out1}\n{out2}\n{out3}"
        return False, f"Unknown git action: {action}"

    elif task_type == "code_quality":
        # Run ruff linter if available
        return _execute_command(
            [PYTHON, "-m", "ruff", "check", str(RUDY_ROOT / "rudy"), "--output-format=text"],
            timeout=60
        )

    elif task_type == "report":
        # Generate a summary report of recent activity
        code = (
            f"import sys, json, pathlib, datetime; sys.path.insert(0, r'{RUDY_ROOT}'); "
            f"reports = list(pathlib.Path(str(QUEUE_DIR / 'completed')).glob('*.json')); "
            f"print(f'Completed tasks: {{len(reports)}}'); "
            f"for r in sorted(reports)[-5:]: "
            f"  d = json.loads(r.read_text()); "
            f"  print(f\"  [{{d.get('type','?')}}] {{d.get('title','?')}} - {{d.get('status','?')}}\")"
        )
        return _execute_python(code, timeout=30)

    else:
        return False, f"Unknown task type: {task_type}"


# ---------------------------------------------------------------------------
# Main Loop (called by NightShift or directly)
# ---------------------------------------------------------------------------

def process_next_task() -> Optional[dict]:
    """
    Pick and execute the next task from the queue.

    Returns the completed task dict, or None if queue is empty.
    """
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
    else:
        # Check if it's a transient error (retry) or permanent (block)
        if "TIMEOUT" in result or "connection" in result.lower():
            block_task(task["id"], f"Transient error: {result[:500]}")
            logger.warning(f"Task blocked (transient): {task['title']}")
        else:
            complete_task(task["id"], result, success=False)
            logger.warning(f"Task failed: {task['title']}: {result[:200]}")

    task["result"] = result
    return task


def process_all(max_tasks: int = 10, max_minutes: int = 30):
    """
    Process tasks until queue empty, max reached, or time limit hit.

    This is what NightShift calls during Batman absence.
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
# Queue Seeding (Alfred pre-loads tasks before Batman leaves)
# ---------------------------------------------------------------------------

def seed_standard_nightwatch():
    """
    Seed the queue with standard nightwatch tasks.

    Called by Alfred when Batman declares absence.
    """
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

        make_task("report", "Generate activity summary",
                  "Summarize completed tasks for Batman review",
                  priority=80, estimated_minutes=1),

        make_task("git", "Commit and push nightwatch findings",
                  "Commit all new findings and push to branch",
                  priority=90, estimated_minutes=1,
                  metadata={"action": "commit_and_push",
                           "message": "nightwatch: Robin autonomous task queue results\n\nCo-Authored-By: Robin (qwen2.5:7b) <robin@batcave.local>"}),
    ]

    for task in tasks:
        add_task(task)

    logger.info(f"Seeded {len(tasks)} standard nightwatch tasks")
    return len(tasks)


def seed_deep_work():
    """
    Seed extended deep-work tasks for longer Batman absences.

    These are added ON TOP of standard nightwatch tasks.
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

        make_task("profile", "Re-run profiler after task execution",
                  "Check if RAM/CPU usage changed during nightwatch",
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
            seed_standard_nightwatch()
        elif cmd == "seed-deep":
            seed_standard_nightwatch()
            seed_deep_work()
        elif cmd == "next":
            process_next_task()
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
