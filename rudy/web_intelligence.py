"""
Web Intelligence Module — Smart web scraping, article extraction,
change monitoring, and OSINT capabilities.

Capabilities:
  - Article extraction: Clean text from any URL (trafilatura/newspaper)
  - Page change monitoring: Track changes to watched URLs
  - WHOIS/DNS lookups: Domain intelligence
  - Search aggregation: Multi-engine search without API keys
  - Link analysis: Crawl and map site structure
  - Content summarization: Extract key points from articles
  - Price monitoring: Track prices on watched product pages
  - Job listing extraction: Parse job boards for relevant postings
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import urlparse, urljoin

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS = DESKTOP / "rudy-logs"
WATCH_DIR = DESKTOP / "rudy-data" / "web-watch"
WATCH_STATE = WATCH_DIR / "watch-state.json"


def _load_json(path, default=None):
    if Path(path).exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}


def _save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


class ArticleExtractor:
    """Extract clean article text from any URL."""

    def extract(self, url: str) -> dict:
        """
        Extract article content from a URL.
        Tries multiple extractors for best results.
        """
        result = {"url": url, "title": "", "text": "", "author": "",
                  "date": "", "source": "", "success": False}

        # Try trafilatura first (best for news/blog articles)
        try:
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False,
                                           include_tables=True)
                metadata = trafilatura.extract(downloaded, output_format="json",
                                               include_comments=False)
                if text:
                    result["text"] = text
                    result["success"] = True
                    result["extractor"] = "trafilatura"
                    if metadata:
                        try:
                            meta = json.loads(metadata)
                            result["title"] = meta.get("title", "")
                            result["author"] = meta.get("author", "")
                            result["date"] = meta.get("date", "")
                            result["source"] = meta.get("sitename", "")
                        except Exception:
                            pass
                    return result
        except ImportError:
            pass
        except Exception:
            pass

        # Fallback to newspaper3k
        try:
            from newspaper import Article
            article = Article(url)
            article.download()
            article.parse()
            if article.text:
                result["text"] = article.text
                result["title"] = article.title or ""
                result["author"] = ", ".join(article.authors) if article.authors else ""
                result["date"] = str(article.publish_date) if article.publish_date else ""
                result["success"] = True
                result["extractor"] = "newspaper3k"
                return result
        except ImportError:
            pass
        except Exception:
            pass

        # Last resort: requests + beautifulsoup
        try:
            import requests
            from bs4 import BeautifulSoup

            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"
            })
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove script/style
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()

            result["text"] = soup.get_text(separator="\n", strip=True)[:5000]
            result["title"] = soup.title.text if soup.title else ""
            result["success"] = True
            result["extractor"] = "beautifulsoup"
        except Exception as e:
            result["error"] = str(e)[:200]

        return result

    def extract_batch(self, urls: List[str]) -> List[dict]:
        """Extract articles from multiple URLs."""
        return [self.extract(url) for url in urls]


class PageWatcher:
    """
    Monitor web pages for changes.

    Usage:
        watcher = PageWatcher()
        watcher.add_watch("https://example.com/jobs", name="Job Board")
        changes = watcher.check_all()
    """

    def __init__(self):
        WATCH_DIR.mkdir(parents=True, exist_ok=True)
        self.state = _load_json(WATCH_STATE, {"watches": {}, "checks": 0})

    def add_watch(self, url: str, name: str = None,
                  check_interval_hours: int = 6,
                  css_selector: str = None):
        """Add a URL to the watch list."""
        watch_id = hashlib.md5(url.encode()).hexdigest()[:12]
        self.state["watches"][watch_id] = {
            "url": url,
            "name": name or urlparse(url).netloc,
            "css_selector": css_selector,
            "check_interval_hours": check_interval_hours,
            "added": datetime.now().isoformat(),
            "last_check": None,
            "last_hash": None,
            "change_count": 0,
        }
        _save_json(WATCH_STATE, self.state)
        return watch_id

    def remove_watch(self, watch_id: str):
        """Remove a watched URL."""
        self.state["watches"].pop(watch_id, None)
        _save_json(WATCH_STATE, self.state)

    def check_all(self) -> List[dict]:
        """Check all watched URLs for changes."""
        changes = []
        for watch_id, watch in self.state["watches"].items():
            # Skip if checked recently
            if watch.get("last_check"):
                last = datetime.fromisoformat(watch["last_check"])
                interval = timedelta(hours=watch.get("check_interval_hours", 6))
                if datetime.now() - last < interval:
                    continue

            change = self._check_one(watch_id, watch)
            if change:
                changes.append(change)

        self.state["checks"] += 1
        _save_json(WATCH_STATE, self.state)
        return changes

    def _check_one(self, watch_id: str, watch: dict) -> Optional[dict]:
        """Check a single URL for changes."""
        try:
            import requests
            resp = requests.get(watch["url"], timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"
            })
            content = resp.text

            # Apply CSS selector if specified
            if watch.get("css_selector"):
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(content, "html.parser")
                    selected = soup.select(watch["css_selector"])
                    content = "\n".join(str(el) for el in selected)
                except Exception:
                    pass

            content_hash = hashlib.sha256(content.encode()).hexdigest()[:24]

            watch["last_check"] = datetime.now().isoformat()
            old_hash = watch.get("last_hash")
            watch["last_hash"] = content_hash

            if old_hash and old_hash != content_hash:
                watch["change_count"] = watch.get("change_count", 0) + 1

                # Save the new content snapshot
                snapshot_file = WATCH_DIR / f"snapshot-{watch_id}-{int(time.time())}.txt"
                with open(snapshot_file, "w", encoding="utf-8") as f:
                    f.write(content[:50000])

                return {
                    "watch_id": watch_id,
                    "name": watch["name"],
                    "url": watch["url"],
                    "changed": True,
                    "old_hash": old_hash,
                    "new_hash": content_hash,
                    "change_number": watch["change_count"],
                    "snapshot": str(snapshot_file),
                }

            return None
        except Exception as e:
            return {"watch_id": watch_id, "name": watch["name"],
                    "url": watch["url"], "error": str(e)[:200]}

    def list_watches(self) -> List[dict]:
        """List all watched URLs."""
        return [{"id": k, **v} for k, v in self.state["watches"].items()]


class DomainIntel:
    """Domain and IP intelligence lookups."""

    def whois_lookup(self, domain: str) -> dict:
        """WHOIS lookup for a domain."""
        try:
            import whois
            w = whois.whois(domain)
            return {
                "domain": domain,
                "registrar": w.registrar,
                "creation_date": str(w.creation_date),
                "expiration_date": str(w.expiration_date),
                "name_servers": w.name_servers,
                "status": w.status,
                "registrant": w.get("org", w.get("name", "")),
            }
        except ImportError:
            return {"error": "python-whois not installed"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def dns_lookup(self, domain: str) -> dict:
        """DNS record lookup."""
        try:
            import dns.resolver
            records = {}
            for rtype in ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]:
                try:
                    answers = dns.resolver.resolve(domain, rtype)
                    records[rtype] = [str(r) for r in answers]
                except Exception:
                    pass
            return {"domain": domain, "records": records}
        except ImportError:
            return {"error": "dnspython not installed"}

    def ip_whois(self, ip: str) -> dict:
        """IP WHOIS lookup."""
        try:
            from ipwhois import IPWhois
            obj = IPWhois(ip)
            result = obj.lookup_rdap()
            return {
                "ip": ip,
                "asn": result.get("asn"),
                "asn_description": result.get("asn_description"),
                "network_name": result.get("network", {}).get("name"),
                "country": result.get("asn_country_code"),
            }
        except ImportError:
            return {"error": "ipwhois not installed"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def full_domain_report(self, domain: str) -> dict:
        """Complete domain intelligence report."""
        return {
            "domain": domain,
            "timestamp": datetime.now().isoformat(),
            "whois": self.whois_lookup(domain),
            "dns": self.dns_lookup(domain),
        }


class JobMonitor:
    """Monitor job boards for relevant postings."""

    def __init__(self):
        self.state_file = LOGS / "job-monitor-state.json"
        self.state = _load_json(self.state_file, {
            "seen_ids": [],
            "alerts": [],
            "keywords": [
                "corporate counsel", "associate general counsel",
                "in-house counsel", "legal counsel",
                "commercial contracts", "technology transactions",
            ],
            "locations": ["remote", "california", "san francisco", "los angeles"],
        })

    def add_keyword(self, keyword: str):
        if keyword.lower() not in [k.lower() for k in self.state["keywords"]]:
            self.state["keywords"].append(keyword)
            _save_json(self.state_file, self.state)

    def search_indeed_rss(self) -> List[dict]:
        """Search Indeed via RSS (no API key needed)."""
        results = []
        try:
            import feedparser
            for keyword in self.state["keywords"][:5]:
                query = keyword.replace(" ", "+")
                url = f"https://www.indeed.com/rss?q={query}&l=remote"
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    job_id = hashlib.md5(entry.get("link", "").encode()).hexdigest()[:12]
                    if job_id not in self.state["seen_ids"]:
                        results.append({
                            "title": entry.get("title", ""),
                            "company": entry.get("source", {}).get("title", ""),
                            "link": entry.get("link", ""),
                            "summary": entry.get("summary", "")[:300],
                            "date": entry.get("published", ""),
                            "keyword": keyword,
                        })
                        self.state["seen_ids"].append(job_id)
        except ImportError:
            pass
        except Exception:
            pass

        # Trim seen IDs
        if len(self.state["seen_ids"]) > 5000:
            self.state["seen_ids"] = self.state["seen_ids"][-3000:]

        _save_json(self.state_file, self.state)
        return results


class WebIntelligence:
    """Master controller for all web intelligence capabilities."""

    def __init__(self):
        self.extractor = ArticleExtractor()
        self.watcher = PageWatcher()
        self.domain_intel = DomainIntel()
        self.job_monitor = JobMonitor()

    def extract_article(self, url: str) -> dict:
        return self.extractor.extract(url)

    def watch_url(self, url: str, name: str = None, **kwargs) -> str:
        return self.watcher.add_watch(url, name, **kwargs)

    def check_watches(self) -> List[dict]:
        return self.watcher.check_all()

    def investigate_domain(self, domain: str) -> dict:
        return self.domain_intel.full_domain_report(domain)

    def search_jobs(self) -> List[dict]:
        return self.job_monitor.search_indeed_rss()

    def get_status(self) -> dict:
        return {
            "watched_urls": len(self.watcher.list_watches()),
            "job_keywords": self.job_monitor.state["keywords"],
            "total_checks": self.watcher.state.get("checks", 0),
        }


if __name__ == "__main__":
    wi = WebIntelligence()
    print("Web Intelligence Module")
    print(json.dumps(wi.get_status(), indent=2))
