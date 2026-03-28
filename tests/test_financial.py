"""
Tests for rudy.financial — MarketData, Portfolio, PriceAlerts, Watchlist.

All yfinance / network calls are mocked; these tests verify portfolio logic,
alert triggering, watchlist management, and JSON persistence without
requiring API access.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure log/data dirs exist before import
desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
(desktop / "rudy-data" / "financial").mkdir(parents=True, exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def fin_paths(tmp_path, monkeypatch):
    """Redirect all financial module file paths to tmp_path."""
    import rudy.financial as mod

    monkeypatch.setattr(mod, "FIN_DIR", tmp_path)
    monkeypatch.setattr(mod, "WATCHLIST_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr(mod, "PORTFOLIO_FILE", tmp_path / "portfolio.json")
    monkeypatch.setattr(mod, "ALERTS_FILE", tmp_path / "price-alerts.json")
    return tmp_path


@pytest.fixture
def market(fin_paths):
    """Create a MarketData instance (methods will be mocked per-test)."""
    from rudy.financial import MarketData
    return MarketData()


@pytest.fixture
def portfolio(fin_paths):
    """Create a Portfolio with mocked MarketData."""
    from rudy.financial import Portfolio
    p = Portfolio()
    p.market = MagicMock()
    return p


@pytest.fixture
def alerts(fin_paths):
    """Create a PriceAlerts with mocked MarketData."""
    from rudy.financial import PriceAlerts
    a = PriceAlerts()
    a.market = MagicMock()
    return a


@pytest.fixture
def watchlist(fin_paths):
    """Create a Watchlist with mocked MarketData."""
    from rudy.financial import Watchlist
    w = Watchlist()
    w.market = MagicMock()
    return w


# ── _load_json / _save_json ──────────────────────────────────────

def test_load_json_missing_file(tmp_path):
    from rudy.financial import _load_json
    result = _load_json(tmp_path / "nonexistent.json")
    assert result == {}


def test_load_json_with_default(tmp_path):
    from rudy.financial import _load_json
    result = _load_json(tmp_path / "nonexistent.json", default={"key": "val"})
    assert result == {"key": "val"}


def test_load_json_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    from rudy.financial import _load_json
    result = _load_json(bad, default={"fallback": True})
    assert result == {"fallback": True}


def test_save_and_load_json(tmp_path):
    from rudy.financial import _save_json, _load_json
    path = tmp_path / "sub" / "data.json"
    _save_json(path, {"hello": "world"})
    assert _load_json(path) == {"hello": "world"}


# ── MarketData ───────────────────────────────────────────────────

def test_get_quote_no_yfinance(market):
    """get_quote returns error dict if yfinance not importable."""
    with patch.dict("sys.modules", {"yfinance": None}):
        with patch("builtins.__import__", side_effect=ImportError):
            result = market.get_quote("AAPL")
    # Falls through to ImportError handling
    assert "error" in result or "symbol" in result


def test_get_quote_success(market):
    """get_quote extracts expected fields from yfinance ticker.info."""
    mock_yf = MagicMock()
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "shortName": "Apple Inc.",
        "currentPrice": 175.50,
        "previousClose": 174.00,
        "regularMarketChangePercent": 0.86,
        "regularMarketVolume": 50000000,
        "marketCap": 2700000000000,
        "trailingPE": 28.5,
        "dividendYield": 0.005,
        "fiftyTwoWeekHigh": 200.0,
        "fiftyTwoWeekLow": 130.0,
        "sector": "Technology",
    }
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = market.get_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["name"] == "Apple Inc."
    assert result["price"] == 175.50
    assert result["sector"] == "Technology"
    assert "timestamp" in result


def test_get_batch_quotes(market):
    """get_batch_quotes calls get_quote for each symbol."""
    market.get_quote = MagicMock(side_effect=[
        {"symbol": "AAPL", "price": 175},
        {"symbol": "MSFT", "price": 380},
    ])
    results = market.get_batch_quotes(["AAPL", "MSFT"])
    assert len(results) == 2
    assert results[0]["symbol"] == "AAPL"
    assert results[1]["symbol"] == "MSFT"


def test_get_forex(market):
    """get_forex returns rate info for currency pair."""
    mock_yf = MagicMock()
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "regularMarketPrice": 55.80,
        "previousClose": 55.60,
    }
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        result = market.get_forex("USD", "PHP")

    assert result["pair"] == "USD/PHP"
    assert result["rate"] == 55.80


def test_get_crypto(market):
    """get_crypto delegates to get_quote with -USD suffix."""
    market.get_quote = MagicMock(return_value={"symbol": "BTC-USD", "price": 65000})
    result = market.get_crypto("BTC")
    market.get_quote.assert_called_once_with("BTC-USD")
    assert result["price"] == 65000


# ── Portfolio ────────────────────────────────────────────────────

def test_add_holding(portfolio, fin_paths):
    """add_holding stores holding and transaction."""
    portfolio.add_holding("AAPL", 10, 1750.0, "2024-01-15")

    assert len(portfolio.data["holdings"]) == 1
    h = portfolio.data["holdings"][0]
    assert h["symbol"] == "AAPL"
    assert h["shares"] == 10
    assert h["cost_basis"] == 1750.0

    assert len(portfolio.data["transactions"]) == 1
    t = portfolio.data["transactions"][0]
    assert t["type"] == "buy"
    assert t["price"] == 175.0  # 1750 / 10


def test_remove_holding_all(portfolio):
    """remove_holding(symbol) without shares removes the entire position."""
    portfolio.add_holding("AAPL", 10, 1750.0)
    portfolio.add_holding("MSFT", 5, 1900.0)

    portfolio.remove_holding("AAPL")
    symbols = [h["symbol"] for h in portfolio.data["holdings"]]
    assert "AAPL" not in symbols
    assert "MSFT" in symbols


def test_remove_holding_partial(portfolio):
    """remove_holding(symbol, shares) reduces share count."""
    portfolio.add_holding("AAPL", 10, 1750.0)
    portfolio.remove_holding("AAPL", 3)

    h = portfolio.data["holdings"][0]
    assert h["shares"] == 7


def test_remove_holding_to_zero(portfolio):
    """Removing all shares drops the holding from the list."""
    portfolio.add_holding("AAPL", 10, 1750.0)
    portfolio.remove_holding("AAPL", 10)

    assert len(portfolio.data["holdings"]) == 0


def test_get_snapshot(portfolio):
    """get_snapshot computes P&L from market quotes."""
    portfolio.add_holding("AAPL", 10, 1500.0)
    portfolio.add_holding("MSFT", 5, 1800.0)

    portfolio.market.get_quote.side_effect = [
        {"price": 180.0},   # AAPL: value=1800, cost=1500, pnl=300
        {"price": 400.0},   # MSFT: value=2000, cost=1800, pnl=200
    ]

    snap = portfolio.get_snapshot()
    assert snap["total_value"] == 3800.0
    assert snap["total_cost"] == 3300.0
    assert snap["total_pnl"] == 500.0
    assert len(snap["positions"]) == 2


def test_get_snapshot_zero_price(portfolio):
    """Snapshot handles zero/None prices gracefully."""
    portfolio.add_holding("FAIL", 10, 1000.0)
    portfolio.market.get_quote.return_value = {"price": None}

    snap = portfolio.get_snapshot()
    assert snap["total_value"] == 0
    assert snap["positions"][0]["pnl"] == -1000.0


# ── PriceAlerts ──────────────────────────────────────────────────

def test_add_alert(alerts, fin_paths):
    """add_alert stores alert and persists to JSON."""
    alerts.add_alert("AAPL", 200.0, direction="above", note="target hit")

    assert len(alerts.alerts["active"]) == 1
    a = alerts.alerts["active"][0]
    assert a["symbol"] == "AAPL"
    assert a["target_price"] == 200.0
    assert a["direction"] == "above"
    assert a["note"] == "target hit"

    # Check persistence
    from rudy.financial import ALERTS_FILE, _load_json
    saved = _load_json(ALERTS_FILE)
    assert len(saved["active"]) == 1


def test_check_alerts_triggers_above(alerts):
    """Alert triggers when price >= target (above direction)."""
    alerts.add_alert("AAPL", 200.0, direction="above")
    alerts.market.get_quote.return_value = {"price": 205.0}

    with patch.object(alerts, "_notify"):
        triggered = alerts.check_alerts()

    assert len(triggered) == 1
    assert triggered[0]["triggered_price"] == 205.0
    assert len(alerts.alerts["active"]) == 0
    assert len(alerts.alerts["triggered"]) == 1


def test_check_alerts_triggers_below(alerts):
    """Alert triggers when price <= target (below direction)."""
    alerts.add_alert("AAPL", 150.0, direction="below")
    alerts.market.get_quote.return_value = {"price": 145.0}

    with patch.object(alerts, "_notify"):
        triggered = alerts.check_alerts()

    assert len(triggered) == 1


def test_check_alerts_no_trigger(alerts):
    """Alert stays active when price hasn't reached target."""
    alerts.add_alert("AAPL", 200.0, direction="above")
    alerts.market.get_quote.return_value = {"price": 190.0}

    triggered = alerts.check_alerts()
    assert len(triggered) == 0
    assert len(alerts.alerts["active"]) == 1


def test_check_alerts_no_price(alerts):
    """Alert stays active when price is unavailable."""
    alerts.add_alert("AAPL", 200.0, direction="above")
    alerts.market.get_quote.return_value = {"price": 0}

    triggered = alerts.check_alerts()
    assert len(triggered) == 0
    assert len(alerts.alerts["active"]) == 1


def test_check_alerts_multiple(alerts):
    """Multiple alerts, only some trigger."""
    alerts.add_alert("AAPL", 200.0, direction="above")
    alerts.add_alert("MSFT", 300.0, direction="below")
    alerts.add_alert("GOOGL", 150.0, direction="above")

    alerts.market.get_quote.side_effect = [
        {"price": 210.0},  # AAPL above 200 → triggers
        {"price": 350.0},  # MSFT NOT below 300 → stays
        {"price": 140.0},  # GOOGL NOT above 150 → stays
    ]

    with patch.object(alerts, "_notify"):
        triggered = alerts.check_alerts()

    assert len(triggered) == 1
    assert triggered[0]["symbol"] == "AAPL"
    assert len(alerts.alerts["active"]) == 2


def test_notify_does_not_crash(alerts):
    """_notify is best-effort and never raises even if email fails."""
    triggered = [{
        "symbol": "AAPL",
        "triggered_price": 205.0,
        "target_price": 200.0,
        "direction": "above",
        "note": "sell target",
    }]
    # _notify imports quick_send inside a try/except, so even without
    # the email module available, it should not raise.
    alerts._notify(triggered)  # Should not raise


# ── Watchlist ────────────────────────────────────────────────────

def test_watchlist_default_tickers(watchlist):
    """Watchlist has default tickers on first init."""
    assert "AAPL" in watchlist.data["tickers"]
    assert "NVDA" in watchlist.data["tickers"]


def test_add_ticker(watchlist, fin_paths):
    """add_ticker adds new symbol and persists."""
    watchlist.add_ticker("TSLA")
    assert "TSLA" in watchlist.data["tickers"]

    from rudy.financial import _load_json, WATCHLIST_FILE
    saved = _load_json(WATCHLIST_FILE)
    assert "TSLA" in saved["tickers"]


def test_add_ticker_uppercase(watchlist):
    """add_ticker normalizes to uppercase."""
    watchlist.add_ticker("tsla")
    assert "TSLA" in watchlist.data["tickers"]


def test_add_ticker_no_duplicate(watchlist):
    """add_ticker doesn't add if already present."""
    count_before = len(watchlist.data["tickers"])
    watchlist.add_ticker("AAPL")  # Already in default list
    assert len(watchlist.data["tickers"]) == count_before


def test_remove_ticker(watchlist):
    """remove_ticker removes the symbol."""
    watchlist.remove_ticker("AAPL")
    assert "AAPL" not in watchlist.data["tickers"]


def test_get_dashboard(watchlist):
    """get_dashboard returns quotes and forex data."""
    watchlist.data["tickers"] = ["AAPL", "MSFT"]
    watchlist.data["forex"] = [("USD", "PHP")]

    watchlist.market.get_batch_quotes.return_value = [
        {"symbol": "AAPL", "price": 175},
        {"symbol": "MSFT", "price": 380},
    ]
    watchlist.market.get_forex.return_value = {"pair": "USD/PHP", "rate": 55.8}

    dashboard = watchlist.get_dashboard()
    assert len(dashboard["quotes"]) == 2
    assert len(dashboard["forex"]) == 1
    assert "timestamp" in dashboard


# ── FinancialIntelligence ────────────────────────────────────────

def test_financial_intelligence_init(fin_paths):
    """FinancialIntelligence initializes all sub-components."""
    from rudy.financial import FinancialIntelligence
    fi = FinancialIntelligence()
    assert fi.market is not None
    assert fi.portfolio is not None
    assert fi.alerts is not None
    assert fi.watchlist is not None


def test_daily_briefing(fin_paths):
    """daily_briefing returns structured report."""
    from rudy.financial import FinancialIntelligence
    fi = FinancialIntelligence()

    # Mock all market calls
    fi.watchlist.market = MagicMock()
    fi.watchlist.market.get_batch_quotes.return_value = []
    fi.watchlist.market.get_forex.return_value = {}
    fi.portfolio.market = MagicMock()
    fi.alerts.market = MagicMock()

    briefing = fi.daily_briefing()
    assert "timestamp" in briefing
    assert "watchlist" in briefing
    assert "portfolio" in briefing
    assert "triggered_alerts" in briefing
