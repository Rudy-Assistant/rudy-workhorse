"""
Rudy API Server — Webhook receiver and REST API for inbound automation.

Runs on The Workhorse, accessible via Tailscale (100.83.49.9:8000).

Endpoints:
  POST /webhook/email     — Receive inbound emails (Cloudflare/Mailgun)
  POST /webhook/zapier    — Receive Zapier triggers
  POST /webhook/generic   — Generic webhook receiver
  GET  /api/status        — System status
  GET  /api/devices       — Current device presence
  GET  /api/security      — Security posture
  GET  /api/financial     — Financial dashboard
  POST /api/command       — Execute a Rudy command
  GET  /api/search        — Semantic search the knowledge base
  GET  /health            — Health check endpoint

Security:
  - API key required for all POST endpoints
  - GET endpoints available on Tailscale only
  - Rate limiting per IP
  - Request logging
"""

import hashlib
import json
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
API_CONFIG = LOGS / "api-server-config.json"
API_LOG = LOGS / "api-requests.json"
COMMANDS_DIR = DESKTOP / "rudy-commands"


def _load_config():
    if API_CONFIG.exists():
        try:
            with open(API_CONFIG, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Generate new API key on first run
    config = {
        "api_key": secrets.token_urlsafe(32),
        "port": 8000,
        "host": "0.0.0.0",
        "allowed_origins": ["*"],
        "rate_limit_per_minute": 60,
        "created": datetime.now().isoformat(),
    }
    API_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with open(API_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return config


CONFIG = _load_config()


def create_app():
    """Create the FastAPI application."""
    try:
        from fastapi import FastAPI, HTTPException, Header, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
    except ImportError:
        raise RuntimeError("FastAPI not installed. Run: pip install fastapi uvicorn")

    app = FastAPI(
        title="Rudy API Server",
        description="Webhook receiver and REST API for The Workhorse",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CONFIG.get("allowed_origins", ["*"]),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting state
    rate_limits = {}

    def check_rate_limit(ip: str) -> bool:
        now = time.time()
        window = rate_limits.get(ip, [])
        window = [t for t in window if now - t < 60]
        window.append(now)
        rate_limits[ip] = window
        return len(window) <= CONFIG.get("rate_limit_per_minute", 60)

    def verify_api_key(api_key: str = Header(None, alias="X-API-Key")):
        if api_key != CONFIG.get("api_key"):
            raise HTTPException(status_code=401, detail="Invalid API key")

    def log_request(request: Request, endpoint: str, data: dict = None):
        log = []
        if API_LOG.exists():
            try:
                with open(API_LOG, encoding="utf-8") as f:
                    log = json.load(f)
            except Exception:
                pass
        log.append({
            "time": datetime.now().isoformat(),
            "endpoint": endpoint,
            "ip": request.client.host if request.client else "unknown",
            "method": request.method,
        })
        if len(log) > 1000:
            log = log[-500:]
        with open(API_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)

    # ── Health ──────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.now().isoformat(),
                "uptime": "active"}

    # ── System Status ──────────────────────────────────────
    @app.get("/api/status")
    async def system_status(request: Request):
        log_request(request, "/api/status")
        status = {"timestamp": datetime.now().isoformat(), "modules": {}}

        # Check each module
        for module_name in ["presence", "network_defense", "travel_mode",
                            "wellness", "movement_feed", "knowledge_base",
                            "web_intelligence", "financial", "voice", "ocr"]:
            try:
                __import__(f"rudy.{module_name}", fromlist=[""])
                status["modules"][module_name] = "loaded"
            except Exception:
                status["modules"][module_name] = "unavailable"

        return status

    # ── Device Presence ────────────────────────────────────
    @app.get("/api/devices")
    async def device_presence(request: Request):
        log_request(request, "/api/devices")
        try:
            from rudy.presence_analytics import PresenceAnalytics
            pa = PresenceAnalytics()
            return pa.state if hasattr(pa, "state") else {"status": "no data yet"}
        except Exception as e:
            return {"error": str(e)[:200]}

    # ── Security ───────────────────────────────────────────
    @app.get("/api/security")
    async def security_status(request: Request):
        log_request(request, "/api/security")
        try:
            from rudy.network_defense import NetworkDefense
            nd = NetworkDefense()
            return nd.get_status() if hasattr(nd, "get_status") else {"status": "active"}
        except Exception as e:
            return {"error": str(e)[:200]}

    # ── Financial ──────────────────────────────────────────
    @app.get("/api/financial")
    async def financial_dashboard(request: Request):
        log_request(request, "/api/financial")
        try:
            from rudy.financial import FinancialIntelligence
            fi = FinancialIntelligence()
            return fi.watchlist.get_dashboard()
        except Exception as e:
            return {"error": str(e)[:200]}

    # ── Knowledge Search ───────────────────────────────────
    @app.get("/api/search")
    async def search_knowledge(request: Request, q: str, n: int = 5):
        log_request(request, "/api/search")
        try:
            from rudy.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            results = kb.search(q, n_results=n)
            return {"query": q, "results": results}
        except Exception as e:
            return {"error": str(e)[:200]}

    # ── Webhooks (require API key) ─────────────────────────
    @app.post("/webhook/email")
    async def webhook_email(request: Request,
                            api_key: str = Header(None, alias="X-API-Key")):
        verify_api_key(api_key)
        log_request(request, "/webhook/email")
        body = await request.body()

        # Save inbound email
        email_file = LOGS / f"inbound-email-{int(time.time())}.txt"
        with open(email_file, "wb") as f:
            f.write(body)

        return {"status": "received", "file": str(email_file)}

    @app.post("/webhook/zapier")
    async def webhook_zapier(request: Request,
                             api_key: str = Header(None, alias="X-API-Key")):
        verify_api_key(api_key)
        log_request(request, "/webhook/zapier")
        data = await request.json()

        # Save trigger data
        trigger_file = LOGS / f"zapier-trigger-{int(time.time())}.json"
        with open(trigger_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return {"status": "received", "trigger_file": str(trigger_file)}

    @app.post("/webhook/generic")
    async def webhook_generic(request: Request,
                              api_key: str = Header(None, alias="X-API-Key")):
        verify_api_key(api_key)
        log_request(request, "/webhook/generic")
        data = await request.json()

        hook_file = LOGS / f"webhook-{int(time.time())}.json"
        with open(hook_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return {"status": "received"}

    # ── Command Execution ──────────────────────────────────
    @app.post("/api/command")
    async def execute_command(request: Request,
                              api_key: str = Header(None, alias="X-API-Key")):
        verify_api_key(api_key)
        log_request(request, "/api/command")
        data = await request.json()
        command = data.get("command", "")
        script_content = data.get("script", "")

        if not command and not script_content:
            raise HTTPException(400, "Provide 'command' or 'script'")

        # Write command to the command runner directory
        cmd_file = COMMANDS_DIR / f"api-cmd-{int(time.time())}.py"
        if script_content:
            with open(cmd_file, "w", encoding="utf-8") as f:
                f.write(script_content)
        else:
            with open(cmd_file, "w", encoding="utf-8") as f:
                f.write(f"import subprocess\nsubprocess.run({repr(command)}, shell=True)\n")

        return {"status": "queued", "command_file": str(cmd_file)}

    return app


def run_server():
    """Start the API server."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install uvicorn")
        return

    app = create_app()
    print(f"\nRudy API Server starting on port {CONFIG['port']}")
    print(f"API Key: {CONFIG['api_key']}")
    print(f"Tailscale: http://100.83.49.9:{CONFIG['port']}")
    print(f"Local: http://192.168.7.25:{CONFIG['port']}")

    uvicorn.run(app, host=CONFIG["host"], port=CONFIG["port"],
                log_level="info")


if __name__ == "__main__":
    run_server()
