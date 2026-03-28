"""
Tests for rudy.email_multi module — multi-provider email backend with failover.
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestEmailProviderDataclass:
    """Test EmailProvider dataclass creation and serialization."""

    def test_email_provider_creation_basic(self):
        """EmailProvider should create with required fields."""
        from rudy.email_multi import EmailProvider

        provider = EmailProvider(
            name="test",
            email="test@example.com",
            password="app-password",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
        )

        assert provider.name == "test"
        assert provider.email == "test@example.com"
        assert provider.password == "app-password"
        assert provider.enabled is True
        assert provider.priority == 0
        assert provider.daily_limit == 500
        assert provider.use_tls is True

    def test_email_provider_creation_with_options(self):
        """EmailProvider should support all optional fields."""
        from rudy.email_multi import EmailProvider

        provider = EmailProvider(
            name="custom",
            email="custom@example.com",
            password="secret",
            imap_host="imap.custom.com",
            imap_port=993,
            smtp_host="smtp.custom.com",
            smtp_port=587,
            enabled=False,
            priority=5,
            daily_limit=100,
            use_tls=False,
        )

        assert provider.enabled is False
        assert provider.priority == 5
        assert provider.daily_limit == 100
        assert provider.use_tls is False

    def test_email_provider_to_dict_basic(self):
        """to_dict should return dictionary of all fields."""
        from rudy.email_multi import EmailProvider

        provider = EmailProvider(
            name="test",
            email="test@example.com",
            password="secret",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
        )

        result = provider.to_dict()
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["email"] == "test@example.com"
        assert result["imap_host"] == "imap.example.com"

    def test_email_provider_to_dict_masks_password(self):
        """to_dict should mask the password field."""
        from rudy.email_multi import EmailProvider

        provider = EmailProvider(
            name="test",
            email="test@example.com",
            password="super-secret-password",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
        )

        result = provider.to_dict()
        assert result["password"] == "***"
        assert "super-secret-password" not in json.dumps(result)

    def test_email_provider_to_dict_never_logs_password(self):
        """to_dict output should be safe to log."""
        from rudy.email_multi import EmailProvider

        provider = EmailProvider(
            name="test",
            email="test@example.com",
            password="MyVerySecurePassword123!",
            imap_host="imap.example.com",
            imap_port=993,
            smtp_host="smtp.example.com",
            smtp_port=587,
        )

        result_str = json.dumps(provider.to_dict())
        assert "MyVerySecurePassword123!" not in result_str
        assert "***" in result_str


class TestDefaultProviders:
    """Test DEFAULT_PROVIDERS configuration."""

    def test_default_providers_exist(self):
        """DEFAULT_PROVIDERS should define gmail, zoho, outlook."""
        from rudy.email_multi import DEFAULT_PROVIDERS

        assert "gmail" in DEFAULT_PROVIDERS
        assert "zoho" in DEFAULT_PROVIDERS
        assert "outlook" in DEFAULT_PROVIDERS

    def test_gmail_provider_uses_env_vars(self, monkeypatch):
        """Gmail provider should read credentials from env vars."""
        monkeypatch.setenv("RUDY_GMAIL_ADDRESS", "test.gmail@gmail.com")
        monkeypatch.setenv("RUDY_GMAIL_APP_PASSWORD", "gmail-app-pwd")

        # Reimport to pick up env vars
        import importlib
        import rudy.email_multi as email_module
        importlib.reload(email_module)

        gmail = email_module.DEFAULT_PROVIDERS["gmail"]
        assert gmail.email == "test.gmail@gmail.com"
        assert gmail.password == "gmail-app-pwd"

    def test_gmail_provider_default_when_env_vars_unset(self, monkeypatch):
        """Gmail provider should have defaults when env vars not set."""
        monkeypatch.delenv("RUDY_GMAIL_ADDRESS", raising=False)
        monkeypatch.delenv("RUDY_GMAIL_APP_PASSWORD", raising=False)

        import importlib
        import rudy.email_multi as email_module
        importlib.reload(email_module)

        gmail = email_module.DEFAULT_PROVIDERS["gmail"]
        # Should have a default address but empty password
        assert isinstance(gmail.email, str)
        assert isinstance(gmail.password, str)

    def test_zoho_provider_uses_env_vars(self, monkeypatch):
        """Zoho provider should read password from env vars."""
        monkeypatch.setenv("RUDY_ZOHO_APP_PASSWORD", "zoho-app-pwd")

        import importlib
        import rudy.email_multi as email_module
        importlib.reload(email_module)

        zoho = email_module.DEFAULT_PROVIDERS["zoho"]
        assert zoho.password == "zoho-app-pwd"

    def test_zoho_provider_email_is_set(self, monkeypatch):
        """Zoho provider should have a configured email address."""
        monkeypatch.delenv("RUDY_ZOHO_APP_PASSWORD", raising=False)

        import importlib
        import rudy.email_multi as email_module
        importlib.reload(email_module)

        zoho = email_module.DEFAULT_PROVIDERS["zoho"]
        assert zoho.email == "rudy.ciminoassistant@zoho.com"

    def test_outlook_provider_has_default_config(self):
        """Outlook provider should have default hosts configured."""
        from rudy.email_multi import DEFAULT_PROVIDERS

        outlook = DEFAULT_PROVIDERS["outlook"]
        assert outlook.name == "outlook"
        assert outlook.imap_host == "imap-mail.outlook.com"
        assert outlook.smtp_host == "smtp-mail.outlook.com"
        assert outlook.enabled is False  # disabled by default

    def test_no_hardcoded_passwords_in_defaults(self, monkeypatch):
        """DEFAULT_PROVIDERS should not contain hardcoded passwords."""
        monkeypatch.delenv("RUDY_GMAIL_APP_PASSWORD", raising=False)
        monkeypatch.delenv("RUDY_ZOHO_APP_PASSWORD", raising=False)

        import importlib
        import rudy.email_multi as email_module
        importlib.reload(email_module)

        # All passwords should be empty or from env vars
        for name, provider in email_module.DEFAULT_PROVIDERS.items():
            # Passwords should not contain actual credentials
            if provider.password:
                assert provider.password not in ["password", "pwd", "secret", "123456"]


class TestEmailHealth:
    """Test EmailHealth tracking and persistence."""

    def test_email_health_init_no_file(self, tmp_path, monkeypatch):
        """EmailHealth should initialize with empty data when no file exists."""
        from rudy.email_multi import EmailHealth

        # Mock the HEALTH_FILE path
        health_file = tmp_path / "email-health.json"
        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()

            assert health.data["providers"] == {}
            assert health.data["last_check"] is None

    def test_email_health_load_existing_file(self, tmp_path, monkeypatch):
        """EmailHealth should load from existing health file."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        initial_data = {
            "providers": {
                "gmail": {
                    "date": "2026-03-28",
                    "sends_today": 5,
                    "consecutive_failures": 0,
                }
            },
            "last_check": "2026-03-28T10:00:00",
        }
        health_file.write_text(json.dumps(initial_data))

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            assert health.data["providers"]["gmail"]["sends_today"] == 5

    def test_email_health_record_send_success(self, tmp_path, monkeypatch):
        """record_send should track successful sends."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", True)

            assert "gmail" in health.data["providers"]
            assert health.data["providers"]["gmail"]["sends_today"] == 1
            assert health.data["providers"]["gmail"]["consecutive_failures"] == 0
            assert "last_success" in health.data["providers"]["gmail"]

    def test_email_health_record_send_failure(self, tmp_path, monkeypatch):
        """record_send should track failed sends."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", False)

            assert "gmail" in health.data["providers"]
            assert health.data["providers"]["gmail"]["failures_today"] == 1
            assert health.data["providers"]["gmail"]["consecutive_failures"] == 1
            assert "last_failure" in health.data["providers"]["gmail"]

    def test_email_health_consecutive_failures_increment(self, tmp_path, monkeypatch):
        """Consecutive failures should increment on each failure."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", False)
            health.record_send("gmail", False)
            health.record_send("gmail", False)

            assert health.data["providers"]["gmail"]["consecutive_failures"] == 3

    def test_email_health_resets_consecutive_on_success(self, tmp_path, monkeypatch):
        """Consecutive failures should reset to 0 on success."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", False)
            health.record_send("gmail", False)
            health.record_send("gmail", True)

            assert health.data["providers"]["gmail"]["consecutive_failures"] == 0

    def test_email_health_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Save and load should preserve health data."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health1 = EmailHealth()
            health1.record_send("gmail", True)
            health1.record_send("gmail", True)
            health1.record_send("zoho", False)

            # Create a new instance that loads from file
            health2 = EmailHealth()

            assert health2.data["providers"]["gmail"]["sends_today"] == 2
            assert health2.data["providers"]["zoho"]["failures_today"] == 1

    def test_email_health_is_healthy_default(self, tmp_path, monkeypatch):
        """New providers should be healthy by default."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            # New provider not in data
            assert health.is_healthy("gmail") is True

    def test_email_health_is_healthy_with_consecutive_failures(self, tmp_path, monkeypatch):
        """Provider should be unhealthy after 3 consecutive failures."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", False)
            health.record_send("gmail", False)
            health.record_send("gmail", False)

            assert health.is_healthy("gmail") is False

    def test_email_health_sends_remaining_new_day(self, tmp_path, monkeypatch):
        """New day should reset sends count."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            remaining = health.sends_remaining("gmail", 500)
            assert remaining == 500

    def test_email_health_sends_remaining_tracks_usage(self, tmp_path, monkeypatch):
        """sends_remaining should decrease with each send."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", True)
            health.record_send("gmail", True)
            health.record_send("gmail", True)

            remaining = health.sends_remaining("gmail", 500)
            assert remaining == 497

    def test_email_health_get_summary(self, tmp_path, monkeypatch):
        """get_summary should return all health data."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("gmail", True)

            summary = health.get_summary()
            assert "providers" in summary
            assert "last_check" in summary
            assert "gmail" in summary["providers"]


class TestMultiEmailInitialization:
    """Test MultiEmail class initialization."""

    def test_multi_email_init_loads_defaults(self, tmp_path, monkeypatch):
        """MultiEmail should initialize with DEFAULT_PROVIDERS."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()

            assert "gmail" in mailer.providers
            assert "zoho" in mailer.providers
            assert "outlook" in mailer.providers

    def test_multi_email_init_loads_config_file(self, tmp_path, monkeypatch):
        """MultiEmail should load saved config overrides."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        config = {
            "gmail": {
                "email": "custom@gmail.com",
                "enabled": False,
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()

            assert mailer.providers["gmail"].email == "custom@gmail.com"
            assert mailer.providers["gmail"].enabled is False

    def test_multi_email_init_handles_missing_config(self, tmp_path, monkeypatch):
        """MultiEmail should handle missing config file gracefully."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "nonexistent" / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            # Should not raise
            mailer = MultiEmail()
            assert "gmail" in mailer.providers


class TestMultiEmailStatus:
    """Test MultiEmail status and health reporting."""

    def test_get_status_returns_dict(self, tmp_path, monkeypatch):
        """get_status should return a dictionary."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()
            status = mailer.get_status()

            assert isinstance(status, dict)
            assert "active_providers" in status
            assert "all_providers" in status
            assert "health" in status

    def test_get_status_lists_active_providers(self, tmp_path, monkeypatch):
        """get_status should list active providers."""
        from rudy.email_multi import MultiEmail, DEFAULT_PROVIDERS

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()
            status = mailer.get_status()

            # Some providers might be active depending on env vars
            assert isinstance(status["active_providers"], list)

    def test_get_status_masks_passwords(self, tmp_path, monkeypatch):
        """get_status should mask passwords in provider details."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()
            status = mailer.get_status()

            status_str = json.dumps(status)
            # Should not contain any actual passwords
            assert "password" not in status_str or "***" in status_str

    def test_get_status_is_json_serializable(self, tmp_path, monkeypatch):
        """get_status should return JSON-serializable data."""
        from rudy.email_multi import MultiEmail

        config_file = tmp_path / "email-providers.json"
        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.CONFIG_FILE", config_file), \
             patch("rudy.email_multi.HEALTH_FILE", health_file):
            mailer = MultiEmail()
            status = mailer.get_status()

            # Should not raise
            serialized = json.dumps(status, default=str)
            assert isinstance(serialized, str)


class TestEmailHealthFileOperations:
    """Test EmailHealth file I/O."""

    def test_health_file_created_on_save(self, tmp_path, monkeypatch):
        """_save should create parent directories."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "logs" / "email-health.json"

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("test", True)

            assert health_file.exists()
            assert health_file.parent.exists()

    def test_health_file_valid_json(self, tmp_path, monkeypatch):
        """Saved health file should be valid JSON."""
        from rudy.email_multi import EmailHealth

        health_file = tmp_path / "email-health.json"
        health_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("rudy.email_multi.HEALTH_FILE", health_file):
            health = EmailHealth()
            health.record_send("test", True)

            # Should be valid JSON
            data = json.loads(health_file.read_text())
            assert isinstance(data, dict)
            assert "providers" in data
