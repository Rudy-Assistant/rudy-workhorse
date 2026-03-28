"""
Tests for rudy.web_intelligence — ArticleExtractor, PageWatcher, DomainIntel,
JobMonitor, WebIntelligence.

All network calls (requests, trafilatura, whois, feedparser) are mocked.
Tests verify URL watching logic, change detection, state persistence,
and the job monitor keyword system.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure directories exist before import
desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
(desktop / "rudy-data" / "web-watch").mkdir(parents=True, exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def web_paths(tmp_path, monkeypatch):
    """Redirect all web_intelligence file paths to tmp_path."""
    import rudy.web_intelligence as mod
    monkeypatch.setattr(mod, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(mod, "WATCH_DIR", tmp_path / "web-watch")
    monkeypatch.setattr(mod, "WATCH_STATE", tmp_path / "web-watch" / "watch-state.json")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "web-watch").mkdir(exist_ok=True)
    return tmp_path


# ── _load_json / _save_json ──────────────────────────────────────

def test_load_json_missing(tmp_path):
    from rudy.web_intelligence import _load_json
    assert _load_json(tmp_path / "nope.json") == {}


def test_load_json_with_default(tmp_path):
    from rudy.web_intelligence import _load_json
    assert _load_json(tmp_path / "nope.json", default={"x": 1}) == {"x": 1}


def test_save_and_load(tmp_path):
    from rudy.web_intelligence import _save_json, _load_json
    path = tmp_path / "sub" / "data.json"
    _save_json(path, {"key": "val"})
    assert _load_json(path) == {"key": "val"}


# ── ArticleExtractor ─────────────────────────────────────────────

class TestArticleExtractor:
    def _make(self):
        from rudy.web_intelligence import ArticleExtractor
        return ArticleExtractor()

    def test_extract_with_trafilatura(self):
        ae = self._make()
        mock_traf = MagicMock()
        mock_traf.fetch_url.return_value = "<html>content</html>"
        mock_traf.extract.side_effect = [
            "Article text here",
            json.dumps({"title": "Test Article", "author": "Bob", "date": "2024-01-01", "sitename": "Example"})
        ]

        with patch.dict("sys.modules", {"trafilatura": mock_traf}):
            result = ae.extract("https://example.com/article")

        assert result["success"]
        assert result["text"] == "Article text here"
        assert result["title"] == "Test Article"
        assert result["extractor"] == "trafilatura"

    def test_extract_trafilatura_not_installed(self):
        ae = self._make()
        # With neither trafilatura, newspaper, nor requests available
        with patch.dict("sys.modules", {"trafilatura": None, "newspaper": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = ae.extract("https://example.com/article")
        # Falls through all extractors — may or may not succeed
        assert "url" in result

    def test_extract_batch(self):
        ae = self._make()
        ae.extract = MagicMock(side_effect=[
            {"url": "https://a.com", "success": True},
            {"url": "https://b.com", "success": False},
        ])
        results = ae.extract_batch(["https://a.com", "https://b.com"])
        assert len(results) == 2
        assert results[0]["success"]
        assert not results[1]["success"]


# ── PageWatcher ──────────────────────────────────────────────────

class TestPageWatcher:
    def _make(self, web_paths):
        from rudy.web_intelligence import PageWatcher
        return PageWatcher()

    def test_add_watch(self, web_paths):
        pw = self._make(web_paths)
        watch_id = pw.add_watch("https://example.com", name="Example")
        assert len(watch_id) == 12
        assert watch_id in pw.state["watches"]
        assert pw.state["watches"][watch_id]["name"] == "Example"
        assert pw.state["watches"][watch_id]["url"] == "https://example.com"

    def test_add_watch_default_name(self, web_paths):
        pw = self._make(web_paths)
        watch_id = pw.add_watch("https://example.com/jobs")
        assert pw.state["watches"][watch_id]["name"] == "example.com"

    def test_remove_watch(self, web_paths):
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com")
        pw.remove_watch(wid)
        assert wid not in pw.state["watches"]

    def test_remove_watch_nonexistent(self, web_paths):
        pw = self._make(web_paths)
        pw.remove_watch("fake_id")  # Should not raise

    def test_list_watches(self, web_paths):
        pw = self._make(web_paths)
        pw.add_watch("https://a.com", name="A")
        pw.add_watch("https://b.com", name="B")
        watches = pw.list_watches()
        assert len(watches) == 2
        names = {w["name"] for w in watches}
        assert "A" in names
        assert "B" in names

    def test_check_all_skips_recent(self, web_paths):
        """check_all skips URLs that were checked within their interval."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com", check_interval_hours=6)
        pw.state["watches"][wid]["last_check"] = datetime.now().isoformat()

        changes = pw.check_all()
        assert len(changes) == 0

    def test_check_all_checks_overdue(self, web_paths):
        """check_all processes URLs whose interval has elapsed."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com", check_interval_hours=1)
        pw.state["watches"][wid]["last_check"] = (
            datetime.now() - timedelta(hours=2)
        ).isoformat()

        # Mock _check_one
        pw._check_one = MagicMock(return_value={
            "watch_id": wid, "changed": True
        })

        changes = pw.check_all()
        assert len(changes) == 1
        pw._check_one.assert_called_once()

    def test_check_one_first_check(self, web_paths):
        """First check establishes baseline hash, returns None."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com")
        watch = pw.state["watches"][wid]

        mock_resp = MagicMock()
        mock_resp.text = "<html>Page content</html>"

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = pw._check_one(wid, watch)

        assert result is None  # First check, no previous hash
        assert watch["last_hash"] is not None

    def test_check_one_detects_change(self, web_paths):
        """Change detected when hash differs from last check."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com")
        watch = pw.state["watches"][wid]
        watch["last_hash"] = "old_hash_value"

        mock_resp = MagicMock()
        mock_resp.text = "<html>New content</html>"

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = pw._check_one(wid, watch)

        assert result is not None
        assert result["changed"]
        assert result["old_hash"] == "old_hash_value"
        assert watch["change_count"] == 1

    def test_check_one_no_change(self, web_paths):
        """No change when hash matches."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com")
        watch = pw.state["watches"][wid]

        content = "<html>Same content</html>"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:24]
        watch["last_hash"] = content_hash

        mock_resp = MagicMock()
        mock_resp.text = content

        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_resp

        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = pw._check_one(wid, watch)

        assert result is None

    def test_check_one_error_handling(self, web_paths):
        """Network errors return error dict instead of crashing."""
        pw = self._make(web_paths)
        wid = pw.add_watch("https://example.com")
        watch = pw.state["watches"][wid]

        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Connection timeout")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            result = pw._check_one(wid, watch)

        assert "error" in result
        assert "timeout" in result["error"].lower()

    def test_watch_state_persists(self, web_paths):
        """State is saved to disk after operations."""
        pw = self._make(web_paths)
        pw.add_watch("https://example.com", name="Test")

        from rudy.web_intelligence import _load_json, WATCH_STATE
        saved = _load_json(WATCH_STATE)
        assert len(saved["watches"]) == 1


# ── DomainIntel ──────────────────────────────────────────────────

class TestDomainIntel:
    def _make(self):
        from rudy.web_intelligence import DomainIntel
        return DomainIntel()

    def test_whois_no_module(self):
        di = self._make()
        with patch.dict("sys.modules", {"whois": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = di.whois_lookup("example.com")
        assert "error" in result

    def test_whois_success(self):
        di = self._make()
        mock_whois = MagicMock()
        mock_w = MagicMock()
        mock_w.registrar = "GoDaddy"
        mock_w.creation_date = "2000-01-01"
        mock_w.expiration_date = "2030-01-01"
        mock_w.name_servers = ["ns1.example.com"]
        mock_w.status = "active"
        mock_w.get = MagicMock(return_value="Example Inc.")
        mock_whois.whois.return_value = mock_w

        with patch.dict("sys.modules", {"whois": mock_whois}):
            result = di.whois_lookup("example.com")

        assert result["domain"] == "example.com"
        assert result["registrar"] == "GoDaddy"

    def test_dns_lookup_no_module(self):
        di = self._make()
        with patch.dict("sys.modules", {"dns": None, "dns.resolver": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = di.dns_lookup("example.com")
        assert "error" in result

    def test_ip_whois_no_module(self):
        di = self._make()
        with patch.dict("sys.modules", {"ipwhois": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = di.ip_whois("1.2.3.4")
        assert "error" in result

    def test_full_domain_report(self):
        di = self._make()
        di.whois_lookup = MagicMock(return_value={"registrar": "test"})
        di.dns_lookup = MagicMock(return_value={"records": {}})

        report = di.full_domain_report("example.com")
        assert report["domain"] == "example.com"
        assert "timestamp" in report
        assert "whois" in report
        assert "dns" in report


# ── JobMonitor ───────────────────────────────────────────────────

class TestJobMonitor:
    def _make(self, web_paths):
        from rudy.web_intelligence import JobMonitor
        return JobMonitor()

    def test_default_keywords(self, web_paths):
        jm = self._make(web_paths)
        assert len(jm.state["keywords"]) > 0
        assert any("counsel" in kw for kw in jm.state["keywords"])

    def test_add_keyword(self, web_paths):
        jm = self._make(web_paths)
        jm.add_keyword("software engineer")
        assert "software engineer" in jm.state["keywords"]

    def test_add_keyword_no_duplicate(self, web_paths):
        jm = self._make(web_paths)
        initial_count = len(jm.state["keywords"])
        jm.add_keyword("Corporate Counsel")  # Already exists (case-insensitive)
        assert len(jm.state["keywords"]) == initial_count

    def test_search_indeed_no_feedparser(self, web_paths):
        jm = self._make(web_paths)
        with patch.dict("sys.modules", {"feedparser": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                results = jm.search_indeed_rss()
        assert results == []

    def test_search_indeed_success(self, web_paths):
        jm = self._make(web_paths)
        jm.state["keywords"] = ["test job"]

        mock_feed = MagicMock()
        mock_entry = MagicMock()
        mock_entry.get = MagicMock(side_effect=lambda key, default="": {
            "title": "Senior Test Engineer",
            "link": "https://indeed.com/job/123",
            "summary": "Great job opportunity...",
            "published": "2024-01-15",
        }.get(key, default))
        mock_entry.source = MagicMock()
        mock_entry.source.get = MagicMock(return_value={"title": "Acme Corp"})
        mock_feed.entries = [mock_entry]

        mock_fp = MagicMock()
        mock_fp.parse.return_value = mock_feed

        with patch.dict("sys.modules", {"feedparser": mock_fp}):
            results = jm.search_indeed_rss()

        assert len(results) == 1
        assert results[0]["title"] == "Senior Test Engineer"

    def test_seen_ids_trimmed(self, web_paths):
        jm = self._make(web_paths)
        jm.state["seen_ids"] = list(range(5500))
        jm.state["keywords"] = []  # No keywords = no actual search
        jm.search_indeed_rss()
        assert len(jm.state["seen_ids"]) <= 3000


# ── WebIntelligence (integration) ────────────────────────────────

class TestWebIntelligence:
    def _make(self, web_paths):
        from rudy.web_intelligence import WebIntelligence
        return WebIntelligence()

    def test_init(self, web_paths):
        wi = self._make(web_paths)
        assert wi.extractor is not None
        assert wi.watcher is not None
        assert wi.domain_intel is not None
        assert wi.job_monitor is not None

    def test_get_status(self, web_paths):
        wi = self._make(web_paths)
        status = wi.get_status()
        assert "watched_urls" in status
        assert "job_keywords" in status
        assert "total_checks" in status

    def test_watch_url_delegates(self, web_paths):
        wi = self._make(web_paths)
        wid = wi.watch_url("https://example.com", name="Test")
        assert len(wid) == 12
        assert wi.get_status()["watched_urls"] == 1

    def test_extract_article_delegates(self, web_paths):
        wi = self._make(web_paths)
        wi.extractor.extract = MagicMock(return_value={"success": True})
        result = wi.extract_article("https://example.com")
        assert result["success"]

    def test_investigate_domain_delegates(self, web_paths):
        wi = self._make(web_paths)
        wi.domain_intel.full_domain_report = MagicMock(
            return_value={"domain": "example.com"}
        )
        result = wi.investigate_domain("example.com")
        assert result["domain"] == "example.com"
