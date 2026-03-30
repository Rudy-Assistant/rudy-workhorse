"""
Financial Intelligence Module — Market data, portfolio tracking, economic alerts.

Capabilities:
  - Stock/crypto price monitoring with alerts
  - Portfolio tracking and P&L reporting
  - Economic indicator monitoring (Fed data)
  - Currency exchange rates
  - News sentiment analysis for watched tickers
  - Price alert notifications via email
"""

import json
import os

from datetime import datetime
from pathlib import Path
from typing import List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

LOGS = RUDY_LOGS
FIN_DIR = RUDY_DATA / "financial"
FIN_DIR.mkdir(parents=True, exist_ok=True)

WATCHLIST_FILE = FIN_DIR / "watchlist.json"
PORTFOLIO_FILE = FIN_DIR / "portfolio.json"
ALERTS_FILE = FIN_DIR / "price-alerts.json"

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

class MarketData:
    """Fetch market data using yfinance (no API key required)."""

    def get_quote(self, symbol: str) -> dict:
        """Get current price and basic info for a ticker."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                "symbol": symbol.upper(),
                "name": info.get("shortName", info.get("longName", symbol)),
                "price": info.get("currentPrice", info.get("regularMarketPrice")),
                "previous_close": info.get("previousClose"),
                "change_pct": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "sector": info.get("sector"),
                "timestamp": datetime.now().isoformat(),
            }
        except ImportError:
            return {"error": "yfinance not installed"}
        except Exception as e:
            return {"error": str(e)[:200], "symbol": symbol}

    def get_history(self, symbol: str, period: str = "1mo",
                    interval: str = "1d") -> dict:
        """Get historical price data."""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period, interval=interval)
            return {
                "symbol": symbol.upper(),
                "period": period,
                "data_points": len(hist),
                "prices": [
                    {
                        "date": str(date.date()),
                        "open": round(row["Open"], 2),
                        "high": round(row["High"], 2),
                        "low": round(row["Low"], 2),
                        "close": round(row["Close"], 2),
                        "volume": int(row["Volume"]),
                    }
                    for date, row in hist.iterrows()
                ],
            }
        except ImportError:
            return {"error": "yfinance not installed"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def get_batch_quotes(self, symbols: List[str]) -> List[dict]:
        """Get quotes for multiple symbols."""
        return [self.get_quote(s) for s in symbols]

    def get_forex(self, from_currency: str = "USD",
                  to_currency: str = "PHP") -> dict:
        """Get forex exchange rate."""
        try:
            import yfinance as yf
            pair = f"{from_currency}{to_currency}=X"
            ticker = yf.Ticker(pair)
            info = ticker.info
            return {
                "pair": f"{from_currency}/{to_currency}",
                "rate": info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            return {"error": str(e)[:200]}

    def get_crypto(self, symbol: str = "BTC") -> dict:
        """Get cryptocurrency price."""
        return self.get_quote(f"{symbol}-USD")

class Portfolio:
    """Track holdings and P&L."""

    def __init__(self):
        self.data = _load_json(PORTFOLIO_FILE, {
            "holdings": [],
            "transactions": [],
            "created": datetime.now().isoformat(),
        })
        self.market = MarketData()

    def add_holding(self, symbol: str, shares: float,
                    cost_basis: float, date: str = None):
        """Add a holding to the portfolio."""
        self.data["holdings"].append({
            "symbol": symbol.upper(),
            "shares": shares,
            "cost_basis": cost_basis,
            "date_acquired": date or datetime.now().strftime("%Y-%m-%d"),
        })
        self.data["transactions"].append({
            "type": "buy",
            "symbol": symbol.upper(),
            "shares": shares,
            "price": cost_basis / shares if shares else 0,
            "date": date or datetime.now().strftime("%Y-%m-%d"),
        })
        _save_json(PORTFOLIO_FILE, self.data)

    def remove_holding(self, symbol: str, shares: float = None):
        """Remove (sell) a holding."""
        symbol = symbol.upper()
        if shares is None:
            self.data["holdings"] = [
                h for h in self.data["holdings"] if h["symbol"] != symbol
            ]
        else:
            for h in self.data["holdings"]:
                if h["symbol"] == symbol:
                    h["shares"] = max(0, h["shares"] - shares)
            self.data["holdings"] = [
                h for h in self.data["holdings"] if h["shares"] > 0
            ]
        _save_json(PORTFOLIO_FILE, self.data)

    def get_snapshot(self) -> dict:
        """Get current portfolio value with P&L."""
        total_value = 0
        total_cost = 0
        positions = []

        for holding in self.data["holdings"]:
            quote = self.market.get_quote(holding["symbol"])
            price = quote.get("price", 0) or 0
            value = price * holding["shares"]
            cost = holding["cost_basis"]
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else 0

            positions.append({
                "symbol": holding["symbol"],
                "shares": holding["shares"],
                "cost_basis": round(cost, 2),
                "current_price": price,
                "market_value": round(value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })

            total_value += value
            total_cost += cost

        return {
            "timestamp": datetime.now().isoformat(),
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_pnl": round(total_value - total_cost, 2),
            "total_pnl_pct": round(((total_value - total_cost) / total_cost * 100) if total_cost else 0, 2),
            "positions": positions,
        }

class PriceAlerts:
    """Price alerts with email notification."""

    def __init__(self):
        self.alerts = _load_json(ALERTS_FILE, {"active": [], "triggered": []})
        self.market = MarketData()

    def add_alert(self, symbol: str, target_price: float,
                  direction: str = "above", note: str = ""):
        """Add a price alert."""
        self.alerts["active"].append({
            "symbol": symbol.upper(),
            "target_price": target_price,
            "direction": direction,  # "above" or "below"
            "note": note,
            "created": datetime.now().isoformat(),
        })
        _save_json(ALERTS_FILE, self.alerts)

    def check_alerts(self) -> List[dict]:
        """Check all active alerts against current prices."""
        triggered = []
        still_active = []

        for alert in self.alerts["active"]:
            quote = self.market.get_quote(alert["symbol"])
            price = quote.get("price", 0)
            if not price:
                still_active.append(alert)
                continue

            fired = False
            if alert["direction"] == "above" and price >= alert["target_price"]:
                fired = True
            elif alert["direction"] == "below" and price <= alert["target_price"]:
                fired = True

            if fired:
                alert["triggered_at"] = datetime.now().isoformat()
                alert["triggered_price"] = price
                triggered.append(alert)
                self.alerts["triggered"].append(alert)
            else:
                still_active.append(alert)

        self.alerts["active"] = still_active
        _save_json(ALERTS_FILE, self.alerts)

        # Send notifications for triggered alerts
        if triggered:
            self._notify(triggered)

        return triggered

    def _notify(self, triggered_alerts: List[dict]):
        """Send email notification for triggered alerts."""
        try:
            from rudy.email_multi import quick_send
            body = "Price Alert(s) Triggered:\n\n"
            for alert in triggered_alerts:
                body += (
                    f"  {alert['symbol']}: ${alert['triggered_price']:.2f} "
                    f"({'above' if alert['direction'] == 'above' else 'below'} "
                    f"${alert['target_price']:.2f})\n"
                    f"  Note: {alert.get('note', '')}\n\n"
                )
            quick_send(
                to="ccimino2@gmail.com",
                subject=f"Price Alert: {', '.join(a['symbol'] for a in triggered_alerts)}",
                body=body,
            )
        except Exception:
            pass  # Best-effort notification

class Watchlist:
    """Curated list of tickers to monitor."""

    def __init__(self):
        self.data = _load_json(WATCHLIST_FILE, {
            "tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META",
                        "NVDA", "RBLX", "BTC-USD", "ETH-USD"],
            "forex": [("USD", "PHP"), ("USD", "JPY"), ("USD", "KRW"), ("USD", "THB")],
        })
        self.market = MarketData()

    def add_ticker(self, symbol: str):
        if symbol.upper() not in self.data["tickers"]:
            self.data["tickers"].append(symbol.upper())
            _save_json(WATCHLIST_FILE, self.data)

    def remove_ticker(self, symbol: str):
        self.data["tickers"] = [t for t in self.data["tickers"] if t != symbol.upper()]
        _save_json(WATCHLIST_FILE, self.data)

    def get_dashboard(self) -> dict:
        """Full watchlist dashboard with prices."""
        quotes = self.market.get_batch_quotes(self.data["tickers"])
        forex_rates = [
            self.market.get_forex(f, t) for f, t in self.data.get("forex", [])
        ]
        return {
            "timestamp": datetime.now().isoformat(),
            "quotes": quotes,
            "forex": forex_rates,
        }

class FinancialIntelligence:
    """Master financial intelligence controller."""

    def __init__(self):
        self.market = MarketData()
        self.portfolio = Portfolio()
        self.alerts = PriceAlerts()
        self.watchlist = Watchlist()

    def daily_briefing(self) -> dict:
        """Generate daily financial briefing."""
        return {
            "timestamp": datetime.now().isoformat(),
            "watchlist": self.watchlist.get_dashboard(),
            "portfolio": self.portfolio.get_snapshot(),
            "triggered_alerts": self.alerts.check_alerts(),
        }

if __name__ == "__main__":
    fi = FinancialIntelligence()
    print("Financial Intelligence Module")
    print(f"  Watchlist: {fi.watchlist.data['tickers']}")
    print(f"  Forex pairs: {fi.watchlist.data.get('forex', [])}")
    print(f"  Portfolio holdings: {len(fi.portfolio.data['holdings'])}")
    print(f"  Active alerts: {len(fi.alerts.alerts['active'])}")
