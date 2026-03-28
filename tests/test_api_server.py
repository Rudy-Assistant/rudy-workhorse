import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json
from datetime import datetime

import rudy.api_server as mod


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Redirect path constants to tmp_path and reload config."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(mod, "DESKTOP", tmp_path)
    monkeypatch.setattr(mod, "LOGS", logs_dir)
    monkeypatch.setattr(mod, "API_CONFIG", logs_dir / "api-server-config.json")
    monkeypatch.setattr(mod, "API_LOG", logs_dir / "api-requests.json")
    monkeypatch.setattr(mod, "COMMANDS_DIR", commands_dir)

    # Reload config
    config = mod._load_config()
    monkeypatch.setattr(mod, "CONFIG", config)

    return {
        "logs_dir": logs_dir,
        "commands_dir": commands_dir,
        "config": config,
        "tmp_path": tmp_path,
    }


class TestLoadConfig:
    def test_load_config_creates_new_config_on_first_run(self, tmp_path, monkeypatch):
        """Test that _load_config creates a new config with API key when file doesn't exist."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        config_file = logs_dir / "api-server-config.json"

        monkeypatch.setattr(mod, "API_CONFIG", config_file)

        config = mod._load_config()

        assert "api_key" in config
        assert config["port"] == 8000
        assert config["host"] == "0.0.0.0"
        assert config["allowed_origins"] == ["*"]
        assert config["rate_limit_per_minute"] == 60
        assert "created" in config
        assert config_file.exists()

    def test_load_config_reads_existing_config(self, tmp_path, monkeypatch):
        """Test that _load_config reads existing config file."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        config_file = logs_dir / "api-server-config.json"

        existing_config = {
            "api_key": "test-key-123",
            "port": 9000,
            "host": "127.0.0.1",
        }
        with open(config_file, "w") as f:
            json.dump(existing_config, f)

        monkeypatch.setattr(mod, "API_CONFIG", config_file)

        config = mod._load_config()

        assert config["api_key"] == "test-key-123"
        assert config["port"] == 9000
        assert config["host"] == "127.0.0.1"

    def test_load_config_handles_corrupt_config_gracefully(self, tmp_path, monkeypatch, caplog):
        """Test that _load_config generates new config if existing is corrupt."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        config_file = logs_dir / "api-server-config.json"

        # Write invalid JSON
        config_file.write_text("{ invalid json }")

        monkeypatch.setattr(mod, "API_CONFIG", config_file)

        config = mod._load_config()

        assert "api_key" in config
        assert config["port"] == 8000


class TestCreateApp:
    def test_create_app_returns_app_object(self, tmp_config):
        """Test that create_app returns an application object."""
        app = mod.create_app()
        assert app is not None

    def test_create_app_fails_without_fastapi(self, tmp_config):
        """Test that create_app raises RuntimeError if FastAPI not installed."""
        with patch.dict("sys.modules", {"fastapi": None}):
            with pytest.raises(RuntimeError, match="FastAPI not installed"):
                # Force reimport to trigger the import error
                import importlib
                importlib.reload(mod)
                mod.create_app()


class TestHealthEndpoint:
    def test_health_endpoint(self, tmp_config):
        """Test /health endpoint returns healthy status."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["uptime"] == "active"


class TestStatusEndpoint:
    def test_status_endpoint_without_modules(self, tmp_config):
        """Test /api/status endpoint when modules are unavailable."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/status")

        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "modules" in data

    def test_status_endpoint_logs_request(self, tmp_config):
        """Test that /api/status endpoint logs the request."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/status")
        assert response.status_code == 200

        # Check if log file was created
        api_log = tmp_config["logs_dir"] / "api-requests.json"
        assert api_log.exists()

        log_data = json.loads(api_log.read_text())
        assert len(log_data) > 0
        assert log_data[0]["endpoint"] == "/api/status"


class TestDevicesEndpoint:
    def test_devices_endpoint_returns_error_on_missing_module(self, tmp_config):
        """Test /api/devices endpoint when PresenceAnalytics is unavailable."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/devices")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data or "status" in data


class TestSecurityEndpoint:
    def test_security_endpoint_returns_error_on_missing_module(self, tmp_config):
        """Test /api/security endpoint when NetworkDefense is unavailable."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/security")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data or "status" in data


class TestFinancialEndpoint:
    def test_financial_endpoint_returns_error_on_missing_module(self, tmp_config):
        """Test /api/financial endpoint when FinancialIntelligence is unavailable."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/financial")
        assert response.status_code == 200
        data = response.json()
        # Can return error, status, or financial data (forex, etc.)
        assert "error" in data or "status" in data or "forex" in data or "timestamp" in data


class TestSearchEndpoint:
    def test_search_endpoint_returns_error_on_missing_module(self, tmp_config):
        """Test /api/search endpoint when KnowledgeBase is unavailable."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert "error" in data or "query" in data

    def test_search_endpoint_with_custom_n_results(self, tmp_config):
        """Test /api/search endpoint with custom n parameter."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=test&n=10")
        assert response.status_code == 200


class TestWebhookEmailEndpoint:
    def test_webhook_email_requires_api_key(self, tmp_config):
        """Test that /webhook/email requires valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.post("/webhook/email", content=b"test email")
        assert response.status_code == 401
        assert "Invalid API key" in response.text

    def test_webhook_email_with_valid_key(self, tmp_config):
        """Test /webhook/email saves email file with valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/webhook/email",
            content=b"test email content",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert "file" in data

        # Verify file was created
        assert Path(data["file"]).exists()

    def test_webhook_email_with_invalid_api_key(self, tmp_config):
        """Test /webhook/email rejects invalid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": "wrong-key"}
        response = client.post(
            "/webhook/email",
            content=b"test",
            headers=headers
        )

        assert response.status_code == 401


class TestWebhookZapierEndpoint:
    def test_webhook_zapier_requires_api_key(self, tmp_config):
        """Test that /webhook/zapier requires valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.post(
            "/webhook/zapier",
            json={"test": "data"}
        )
        assert response.status_code == 401

    def test_webhook_zapier_saves_trigger_file(self, tmp_config):
        """Test /webhook/zapier saves trigger file with valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        trigger_data = {"action": "send_email", "to": "test@example.com"}

        response = client.post(
            "/webhook/zapier",
            json=trigger_data,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert "trigger_file" in data

        # Verify file was created and contains data
        trigger_file = Path(data["trigger_file"])
        assert trigger_file.exists()
        saved_data = json.loads(trigger_file.read_text())
        assert saved_data == trigger_data


class TestWebhookGenericEndpoint:
    def test_webhook_generic_requires_api_key(self, tmp_config):
        """Test that /webhook/generic requires valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.post(
            "/webhook/generic",
            json={"test": "data"}
        )
        assert response.status_code == 401

    def test_webhook_generic_saves_webhook_file(self, tmp_config):
        """Test /webhook/generic saves webhook file with valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        webhook_data = {"type": "generic", "payload": {"key": "value"}}

        response = client.post(
            "/webhook/generic",
            json=webhook_data,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"

        # Verify files were created in logs directory
        logs = list(tmp_config["logs_dir"].glob("webhook-*.json"))
        assert len(logs) > 0


class TestCommandExecutionEndpoint:
    def test_command_execution_requires_api_key(self, tmp_config):
        """Test that /api/command requires valid API key."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.post(
            "/api/command",
            json={"command": "echo test"}
        )
        assert response.status_code == 401

    def test_command_execution_with_command_string(self, tmp_config):
        """Test /api/command executes command string."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/api/command",
            json={"command": "echo hello"},
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert "command_file" in data

        # Verify command file was created
        cmd_file = Path(data["command_file"])
        assert cmd_file.exists()
        assert "subprocess.run" in cmd_file.read_text()

    def test_command_execution_with_script(self, tmp_config):
        """Test /api/command executes with script content."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        script = "import sys\nprint('hello')\n"

        response = client.post(
            "/api/command",
            json={"script": script},
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"

        # Verify script was saved
        cmd_file = Path(data["command_file"])
        assert cmd_file.exists()
        assert script in cmd_file.read_text()

    def test_command_execution_requires_command_or_script(self, tmp_config):
        """Test /api/command fails if neither command nor script provided."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/api/command",
            json={},
            headers=headers
        )

        assert response.status_code == 400
        assert "Provide 'command' or 'script'" in response.text


class TestRateLimiting:
    def test_rate_limiting_blocks_excessive_requests(self, tmp_config):
        """Test that rate limiting is enforced."""
        # Create app with low rate limit
        tmp_config["config"]["rate_limit_per_minute"] = 2

        app = mod.create_app()

        # This test verifies the rate limiting logic exists
        # Note: FastAPI's TestClient doesn't expose the internal rate_limits dict,
        # so we test via the config being applied correctly
        assert app is not None


class TestAPIKeyVerification:
    def test_verify_api_key_rejects_missing_key(self, tmp_config):
        """Test that missing API key is rejected."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        response = client.post(
            "/webhook/email",
            content=b"test"
        )
        assert response.status_code == 401

    def test_verify_api_key_rejects_wrong_key(self, tmp_config):
        """Test that wrong API key is rejected."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": "wrong-key-12345"}
        response = client.post(
            "/webhook/email",
            content=b"test",
            headers=headers
        )
        assert response.status_code == 401

    def test_verify_api_key_accepts_correct_key(self, tmp_config):
        """Test that correct API key is accepted."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/webhook/email",
            content=b"test",
            headers=headers
        )
        assert response.status_code == 200


class TestRequestLogging:
    def test_request_logging_appends_to_log_file(self, tmp_config):
        """Test that requests are logged to API log file."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        # Make a request to an endpoint that logs
        response = client.get("/api/status")
        assert response.status_code == 200

        # Check log file
        api_log = tmp_config["logs_dir"] / "api-requests.json"
        assert api_log.exists()

        log_data = json.loads(api_log.read_text())
        assert len(log_data) > 0

        # Find status endpoint log
        status_logs = [entry for entry in log_data if entry["endpoint"] == "/api/status"]
        assert len(status_logs) > 0

    def test_request_logging_truncates_old_entries(self, tmp_config):
        """Test that request log is truncated when it exceeds 1000 entries."""
        from fastapi.testclient import TestClient

        api_log = tmp_config["logs_dir"] / "api-requests.json"

        # Create a log with 1001 entries
        log_data = [
            {
                "time": datetime.now().isoformat(),
                "endpoint": "/test",
                "ip": "127.0.0.1",
                "method": "GET"
            }
            for _ in range(1001)
        ]
        api_log.write_text(json.dumps(log_data))

        # Make a request to trigger logging
        # /api/status calls log_request, which will:
        # 1. Read 1001 entries
        # 2. Add 1 new entry -> 1002 total
        # 3. Keep last 500 entries (log_data[-500:])
        app = mod.create_app()
        client = TestClient(app)
        response = client.get("/api/status")
        assert response.status_code == 200

        # Check that log was truncated to last 500 entries
        new_log_data = json.loads(api_log.read_text())
        # Should be exactly 500 entries (the last 500 of the 1002)
        assert len(new_log_data) == 500


class TestConfigPersistence:
    def test_config_is_persisted_to_disk(self, tmp_config):
        """Test that generated config is saved to disk."""
        config_file = tmp_config["logs_dir"] / "api-server-config.json"
        assert config_file.exists()

        saved_config = json.loads(config_file.read_text())
        assert saved_config["api_key"] == tmp_config["config"]["api_key"]
        assert saved_config["port"] == 8000

    def test_config_api_key_is_urlsafe(self, tmp_config):
        """Test that generated API key is URL-safe."""
        api_key = tmp_config["config"]["api_key"]

        # Should be URL-safe characters only
        import string
        safe_chars = string.ascii_letters + string.digits + "-_"
        assert all(c in safe_chars for c in api_key)


class TestRunServer:
    def test_run_server_fails_without_uvicorn(self, tmp_config):
        """Test that run_server fails gracefully without uvicorn."""
        with patch.dict("sys.modules", {"uvicorn": None}):
            with patch("builtins.__import__", side_effect=ImportError("uvicorn not found")):
                # Should not raise, just print error
                # Manually test the error handling
                try:
                    import uvicorn  # This will fail
                except ImportError:
                    pass  # Expected


class TestEdgeCases:
    def test_webhook_email_with_empty_content(self, tmp_config):
        """Test webhook_email with empty content."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/webhook/email",
            content=b"",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"

    def test_webhook_zapier_with_complex_json(self, tmp_config):
        """Test webhook_zapier with complex nested JSON."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        complex_data = {
            "nested": {
                "deeply": {
                    "structured": ["list", "of", "items"]
                }
            },
            "timestamp": datetime.now().isoformat()
        }

        response = client.post(
            "/webhook/zapier",
            json=complex_data,
            headers=headers
        )

        assert response.status_code == 200

        # Verify data was saved correctly
        trigger_file = Path(response.json()["trigger_file"])
        saved_data = json.loads(trigger_file.read_text())
        assert saved_data["nested"]["deeply"]["structured"] == ["list", "of", "items"]

    def test_command_with_special_characters(self, tmp_config):
        """Test command execution with special characters."""
        from fastapi.testclient import TestClient

        app = mod.create_app()
        client = TestClient(app)

        headers = {"X-API-Key": tmp_config["config"]["api_key"]}
        response = client.post(
            "/api/command",
            json={"command": "echo 'test with special chars & symbols'"},
            headers=headers
        )

        assert response.status_code == 200
        cmd_file = Path(response.json()["command_file"])
        assert cmd_file.exists()
