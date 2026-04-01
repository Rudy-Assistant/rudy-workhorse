"""
Offline Operations Controller — Autonomous operation during internet outages.

When The Workhorse loses internet connectivity, this module takes over:
  1. Detects the outage (DNS resolution fails, public IP unreachable)
  2. Switches to offline mode (local AI for decisions, no cloud APIs)
  3. Continues critical operations: service monitoring, security, alerts
  4. Queues actions that need internet (emails, webhooks, API calls)
  5. Restores normal operation when connectivity returns
  6. Replays the queued actions

The local AI (Phi-3-Mini or Mistral-7B) provides reasoning capability
during outages — it can triage alerts, decide whether to restart services,
and generate status reports without any cloud dependency.

Design:
  - Heartbeat check every 60 seconds (DNS + HTTP)
  - Graceful degradation: features disable one-by-one as needed
  - Action queue persisted to disk (survives crashes/reboots)
  - Recovery: drains queue in order when connectivity returns
  - All decisions logged for Chris to review later
"""

import json
import socket

import time
from datetime import datetime
from pathlib import Path
from typing import List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

LOGS = RUDY_LOGS
OFFLINE_DIR = RUDY_DATA / "offline"
QUEUE_FILE = OFFLINE_DIR / "action-queue.json"
STATE_FILE = OFFLINE_DIR / "offline-state.json"
DECISION_LOG = OFFLINE_DIR / "decisions.json"

def _load_json(path, default=None):
    if Path(path).exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

class ConnectivityChecker:
    """Check internet connectivity via multiple methods."""

    # DNS servers to test (diverse providers)
    DNS_TARGETS = [
        ("1.1.1.1", 53),       # Cloudflare
        ("8.8.8.8", 53),       # Google
        ("9.9.9.9", 53),       # Quad9
    ]

    # HTTP endpoints to test
    HTTP_TARGETS = [
        "http://clients3.google.com/generate_204",
        "http://www.msftconnecttest.com/connecttest.txt",
    ]

    def check_dns(self) -> bool:
        """Quick DNS socket check."""
        for host, port in self.DNS_TARGETS:
            try:
                sock = socket.create_connection((host, port), timeout=3)
                sock.close()
                return True
            except Exception:
                continue
        return False

    def check_http(self) -> bool:
        """HTTP connectivity check."""
        try:
            import requests
            for url in self.HTTP_TARGETS:
                try:
                    resp = requests.get(url, timeout=5)
                    if resp.status_code in [200, 204]:
                        return True
                except Exception:
                    continue
        except ImportError:
            pass
        return False

    def check_dns_resolution(self) -> bool:
        """Try to resolve a well-known domain."""
        try:
            socket.getaddrinfo("www.google.com", 443, socket.AF_INET, socket.SOCK_STREAM)
            return True
        except Exception:
            return False

    def full_check(self) -> dict:
        """Run all connectivity checks."""
        dns = self.check_dns()
        http = self.check_http() if dns else False
        resolution = self.check_dns_resolution() if dns else False

        online = dns and (http or resolution)
        return {
            "online": online,
            "dns_socket": dns,
            "http": http,
            "dns_resolution": resolution,
            "timestamp": datetime.now().isoformat(),
        }

class ActionQueue:
    """
    Persisted queue of actions to execute when connectivity returns.

    Actions are things like: send email, fire webhook, sync data.
    """

    def __init__(self):
        OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
        self.queue = _load_json(QUEUE_FILE, {"actions": [], "replayed": []})

    def add(self, action_type: str, payload: dict, priority: int = 5):
        """Add an action to the queue."""
        self.queue["actions"].append({
            "id": f"{action_type}_{int(time.time())}",
            "type": action_type,
            "payload": payload,
            "priority": priority,  # 1=highest, 10=lowest
            "queued_at": datetime.now().isoformat(),
            "status": "pending",
        })
        _save_json(QUEUE_FILE, self.queue)

    def drain(self) -> List[dict]:
        """Execute all pending actions (called when back online)."""
        results = []
        pending = [a for a in self.queue["actions"] if a["status"] == "pending"]
        pending.sort(key=lambda a: a["priority"])

        for action in pending:
            result = self._execute(action)
            action["status"] = "completed" if result["success"] else "failed"
            action["executed_at"] = datetime.now().isoformat()
            action["result"] = result
            results.append(result)
            self.queue["replayed"].append(action)

        self.queue["actions"] = [
            a for a in self.queue["actions"] if a["status"] == "pending"
        ]

        # Trim replayed history
        if len(self.queue["replayed"]) > 200:
            self.queue["replayed"] = self.queue["replayed"][-100:]

        _save_json(QUEUE_FILE, self.queue)
        return results

    def _execute(self, action: dict) -> dict:
        """Execute a single queued action."""
        action_type = action["type"]
        payload = action["payload"]

        try:
            if action_type == "send_email":
                from rudy.email_multi import quick_send
                return quick_send(**payload)

            elif action_type == "webhook":
                import requests
                resp = requests.post(
                    payload["url"],
                    json=payload.get("data", {}),
                    headers=payload.get("headers", {}),
                    timeout=15,
                )
                return {"success": resp.status_code < 400, "status_code": resp.status_code}

            elif action_type == "sync_knowledge":
                from rudy.knowledge_base import KnowledgeBase
                kb = KnowledgeBase()
                result = kb.index_all()
                return {"success": True, "result": result}

            elif action_type == "check_jobs":
                from rudy.web_intelligence import WebIntelligence
                wi = WebIntelligence()
                jobs = wi.search_jobs()
                return {"success": True, "new_jobs": len(jobs)}

            else:
                return {"success": False, "error": f"Unknown action type: {action_type}"}

        except Exception as e:
            return {"success": False, "error": str(e)[:200]}

    @property
    def pending_count(self) -> int:
        return sum(1 for a in self.queue["actions"] if a["status"] == "pending")

    def get_summary(self) -> dict:
        return {
            "pending": self.pending_count,
            "total_queued": len(self.queue["actions"]),
            "total_replayed": len(self.queue["replayed"]),
        }

class DecisionLogger:
    """Log all AI-assisted decisions made during offline operation."""

    def __init__(self):
        self.decisions = _load_json(DECISION_LOG, {"log": []})

    def log(self, context: str, decision: str, ai_reasoning: str = "",
            action_taken: str = ""):
        self.decisions["log"].append({
            "time": datetime.now().isoformat(),
            "context": context,
            "decision": decision,
            "ai_reasoning": ai_reasoning[:500],
            "action_taken": action_taken,
        })
        if len(self.decisions["log"]) > 500:
            self.decisions["log"] = self.decisions["log"][-300:]
        _save_json(DECISION_LOG, self.decisions)

    def get_recent(self, n: int = 20) -> List[dict]:
        return self.decisions["log"][-n:]

class OfflineController:
    """
    Master controller for offline operation.

    Usage:
        controller = OfflineController()

        # Periodic check (call every 60 seconds from health monitor)
        status = controller.heartbeat()

        if not status["online"]:
            # We're offline — use local AI for decisions
            decision = controller.ai_decide(
                "RustDesk has been down for 15 minutes"
            )

            # Queue an email to send when we're back online
            controller.queue_action("send_email", {
                "to": "ccimino2@gmail.com",
                "subject": "Workhorse was offline",
                "body": "Internet was down for 30 minutes. All services maintained."
            })
    """

    def __init__(self):
        OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
        self.checker = ConnectivityChecker()
        self.queue = ActionQueue()
        self.logger = DecisionLogger()
        self.state = _load_json(STATE_FILE, {
            "mode": "online",
            "offline_since": None,
            "last_check": None,
            "outage_count": 0,
            "total_offline_minutes": 0,
        })
        self._ai = None

    def _get_ai(self):
        """Lazy-load the local AI."""
        if self._ai is None:
            try:
                from rudy.local_ai import OfflineAI
                self._ai = OfflineAI.get()
            except Exception:
                pass
        return self._ai

    def heartbeat(self) -> dict:
        """
        Called periodically. Checks connectivity and manages mode transitions.
        Returns current status.
        """
        check = self.checker.full_check()
        was_offline = self.state["mode"] == "offline"
        now_online = check["online"]

        self.state["last_check"] = check["timestamp"]

        if was_offline and now_online:
            # RECOVERY — back online
            self._handle_recovery()
        elif not was_offline and not now_online:
            # OUTAGE — just went offline
            self._handle_outage_start()
        elif was_offline and not now_online:
            # Still offline — update duration
            if self.state.get("offline_since"):
                duration = (datetime.now() - datetime.fromisoformat(
                    self.state["offline_since"]
                )).total_seconds() / 60
                self.state["current_outage_minutes"] = round(duration, 1)

        _save_json(STATE_FILE, self.state)

        return {
            "online": now_online,
            "mode": self.state["mode"],
            "offline_since": self.state.get("offline_since"),
            "current_outage_minutes": self.state.get("current_outage_minutes", 0),
            "queued_actions": self.queue.pending_count,
            "connectivity": check,
        }

    def _handle_outage_start(self):
        """Transition to offline mode."""
        self.state["mode"] = "offline"
        self.state["offline_since"] = datetime.now().isoformat()
        self.state["outage_count"] = self.state.get("outage_count", 0) + 1
        self.state["current_outage_minutes"] = 0

        self.logger.log(
            context="Internet connectivity lost",
            decision="Entering offline mode",
            action_taken="Switched to local AI, queuing outbound actions",
        )

        # Queue a notification for when we come back
        self.queue.add("send_email", {
            "to": "ccimino2@gmail.com",
            "subject": "Workhorse: Internet Outage Detected",
            "body": (
                f"Internet connectivity lost at {datetime.now().isoformat()}.\n"
                f"Switching to offline mode with local AI.\n"
                f"All critical services will continue running.\n"
                f"This email was queued and sent upon recovery."
            ),
        }, priority=2)

    def _handle_recovery(self):
        """Transition back to online mode."""
        outage_duration = self.state.get("current_outage_minutes", 0)
        self.state["mode"] = "online"
        self.state["total_offline_minutes"] = (
            self.state.get("total_offline_minutes", 0) + outage_duration
        )
        self.state["offline_since"] = None
        self.state["current_outage_minutes"] = 0

        self.logger.log(
            context=f"Internet restored after {outage_duration:.0f} minutes",
            decision="Returning to online mode, draining action queue",
            action_taken=f"Replaying {self.queue.pending_count} queued actions",
        )

        # Drain the queue
        self.queue.drain()

    def ai_decide(self, situation: str) -> dict:
        """Use local AI to make a decision about a situation."""
        ai = self._get_ai()
        if ai and ai.ensure_ready():
            response = ai.ask(situation, role="ops")
            decision = {
                "situation": situation,
                "ai_available": True,
                "response": response,
                "time": datetime.now().isoformat(),
            }
        else:
            decision = {
                "situation": situation,
                "ai_available": False,
                "response": "AI unavailable — using default heuristics",
                "time": datetime.now().isoformat(),
            }

        self.logger.log(
            context=situation,
            decision=decision.get("response", ""),
            ai_reasoning=decision.get("response", ""),
        )
        return decision

    def queue_action(self, action_type: str, payload: dict, priority: int = 5):
        """Queue an action for when connectivity returns."""
        self.queue.add(action_type, payload, priority)

    def get_status(self) -> dict:
        """Full offline controller status."""
        return {
            "mode": self.state["mode"],
            "online": self.state["mode"] == "online",
            "offline_since": self.state.get("offline_since"),
            "outage_count": self.state.get("outage_count", 0),
            "total_offline_minutes": self.state.get("total_offline_minutes", 0),
            "queue": self.queue.get_summary(),
            "ai_health": self._get_ai().ai.get_health() if self._get_ai() else {"status": "not_loaded"},
            "recent_decisions": self.logger.get_recent(5),
        }

# Convenience function for other modules
def is_online() -> bool:
    """Quick check: are we online?"""
    return ConnectivityChecker().check_dns()

def get_controller() -> OfflineController:
    """Get the singleton offline controller."""
    return OfflineController()

if __name__ == "__main__":
    print("Offline Operations Controller")
    controller = OfflineController()
    status = controller.heartbeat()
    print(f"\n  Mode: {status['mode']}")
    print(f"  Online: {status['online']}")
    print(f"  Queued actions: {status['queued_actions']}")
    print(f"  Connectivity: {json.dumps(status['connectivity'], indent=2)}")
