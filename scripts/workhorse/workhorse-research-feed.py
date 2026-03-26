#!/usr/bin/env python3
"""
Workhorse Research Feed System
Automated intelligence gathering on AI/ML, privacy, legal tech, and automation topics.
Usage:
    python workhorse-research-feed.py [--quick | --full]
    python workhorse-research-feed.py --debug
"""

import os
import sys
import json
import logging
import hashlib
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
    import feedparser
except ImportError:
    print("ERROR: Required packages missing. Install with:")
    print("  pip install requests beautifulsoup4 feedparser")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_FEEDS = {
    "anthropic_blog": "https://www.anthropic.com/blog/rss.xml",
    "hacker_news": "https://news.ycombinator.com/rss",
    "techcrunch_ai": "https://techcrunch.com/tag/ai/feed/",
    "arxiv_cs_ai": "http://arxiv.org/rss/cs.AI",
    "arxiv_cv": "http://arxiv.org/rss/cs.CV",
    "github_trending": "https://github.com/trending?since=weekly&spoken_language_code=",
    "producthunt": "https://www.producthunt.com/feed",
    "openai_blog": "https://openai.com/blog/rss.xml",
    "deepmind_blog": "https://deepmind.com/blog?format=rss",
    "pytorch_blog": "https://pytorch.org/blog/feed.xml",
    "huggingface_blog": "https://huggingface.co/blog/feed.xml",
    "mozilla_security": "https://blog.mozilla.org/security/feed/",
    "eff_news": "https://www.eff.org/rss/updates.xml",
    "krebs_security": "https://krebsonsecurity.com/feed/",
    "legal_tech_insider": "https://www.legaltechleveraged.com/feed/",
    "above_the_law": "https://abovethelaw.com/feed/",
    "legaltech_news": "https://legaltechnews.com/feed/",
    "home_automation_hub": "https://www.smarthomehub.net/feed/",
    "automation_anywhere_blog": "https://www.automationanywhere.com/company/blog/feed",
}

RELEVANCE_KEYWORDS = {
    "ai_ml": [
        "claude", "gpt", "llm", "language model", "transformer", "neural network",
        "machine learning", "deep learning", "ai", "artificial intelligence",
        "mcp server", "anthropic", "openai", "google ai", "deepmind", "meta ai"
    ],
    "image_gen": [
        "stable diffusion", "midjourney", "dall-e", "flux", "image generation",
        "text-to-image", "diffusion model", "generative ai", "image synthesis"
    ],
    "video_gen": [
        "video generation", "text-to-video", "video synthesis", "runway", "sora",
        "video ai", "motion generation", "temporal coherence"
    ],
    "music_gen": [
        "music generation", "suno", "udio", "audio ai", "sound synthesis",
        "music ai", "text-to-music", "ai music"
    ],
    "privacy": [
        "privacy", "encryption", "decryption", "vpn", "tor", "anonymity",
        "data protection", "gdpr", "privacy rights", "surveillance", "security",
        "zero knowledge", "end-to-end", "cryptography"
    ],
    "legal_tech": [
        "legal tech", "contract automation", "ai law", "legal ai", "contract review",
        "due diligence", "legal operations", "legal analytics", "document automation",
        "law practice", "attorney", "counsel", "litigation"
    ],
    "automation": [
        "home automation", "smart home", "iot", "automation", "workflow automation",
        "robotic process automation", "rpa", "zapier", "n8n", "make.com",
        "assistant", "agent"
    ]
}

SCORING_MULTIPLIERS = {
    "ai_ml": 2.5,
    "image_gen": 2.0,
    "video_gen": 2.0,
    "music_gen": 1.8,
    "privacy": 1.5,
    "legal_tech": 1.8,
    "automation": 1.5,
}

REQUEST_TIMEOUT = 10
MAX_ITEMS_PER_FEED = 30

# ============================================================================
# LOGGING
# ============================================================================

def setup_logging(debug: bool = False) -> logging.Logger:
    """Configure logging to console and file."""
    level = logging.DEBUG if debug else logging.INFO

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console.setFormatter(console_fmt)

    # Create logger
    logger = logging.getLogger("workhorse-research-feed")
    logger.setLevel(level)
    logger.addHandler(console)

    # File handler
    log_dir = Path(__file__).parent / "rudy-logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"workhorse-research-feed-{datetime.now().strftime('%Y%m%d')}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ResearchItem:
    """Represents a single research item from a feed."""
    title: str
    url: str
    source: str
    published_date: Optional[str]
    summary: Optional[str]
    categories: List[str]
    relevance_score: float
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

class URLCache:
    """Manages cache of seen URLs to avoid duplicates."""

    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self.seen_urls: set = set()
        self.load()

    def load(self):
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.seen_urls = set(json.load(f))
            except Exception as e:
                logging.getLogger("workhorse-research-feed").warning(
                    f"Failed to load URL cache: {e}. Starting fresh."
                )
                self.seen_urls = set()

    def save(self):
        """Save cache to disk."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.seen_urls), f, indent=2)
        except Exception as e:
            logging.getLogger("workhorse-research-feed").error(
                f"Failed to save URL cache: {e}"
            )

    def has_seen(self, url: str) -> bool:
        """Check if URL has been seen before."""
        normalized = self._normalize_url(url)
        return normalized in self.seen_urls

    def mark_seen(self, url: str):
        """Mark URL as seen."""
        normalized = self._normalize_url(url)
        self.seen_urls.add(normalized)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for comparison."""
        return url.lower().strip().rstrip('/')


# ============================================================================
# RELEVANCE SCORING
# ============================================================================

class RelevanceScorer:
    """Scores items based on relevance keywords."""

    def __init__(self):
        # Build keyword set with category mapping
        self.keyword_map: Dict[str, List[str]] = {}
        for category, keywords in RELEVANCE_KEYWORDS.items():
            for keyword in keywords:
                if keyword not in self.keyword_map:
                    self.keyword_map[keyword] = []
                self.keyword_map[keyword].append(category)

    def score(self, title: str, summary: str = "") -> tuple[float, List[str]]:
        """
        Score item relevance.
        Returns: (score, matching_categories)
        """
        text = (title + " " + (summary or "")).lower()

        matched_categories = set()
        base_score = 0.0

        for keyword, categories in self.keyword_map.items():
            if keyword in text:
                base_score += 1.0
                for category in categories:
                    matched_categories.add(category)

        # Apply category multipliers
        final_score = base_score
        for category in matched_categories:
            multiplier = SCORING_MULTIPLIERS.get(category, 1.0)
            final_score *= multiplier

        return final_score, sorted(list(matched_categories))

    def recency_boost(self, score: float, date: Optional[str]) -> float:
        """Boost score for recent items."""
        if not date:
            return score

        try:
            # Simple boost: subtract small amount for each day old
            item_date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            days_old = (datetime.now(item_date.tzinfo) - item_date).days
            boost = max(0, 1.0 - (days_old * 0.01))
            return score * boost
        except Exception:
            return score


# ============================================================================
# FEED FETCHING
# ============================================================================

class FeedFetcher:
    """Fetches and parses RSS feeds."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def fetch_feed(self, feed_url: str, source_name: str, max_items: int = MAX_ITEMS_PER_FEED) -> List[ResearchItem]:
        """Fetch and parse a single RSS feed."""
        items = []

        try:
            self.logger.debug(f"Fetching {source_name}: {feed_url}")
            feed = feedparser.parse(feed_url, timeout=REQUEST_TIMEOUT)

            if feed.bozo and not items:
                self.logger.warning(f"Feed parse error for {source_name}: {feed.bozo_exception}")

            for entry in feed.entries[:max_items]:
                try:
                    item = self._parse_entry(entry, source_name)
                    if item:
                        items.append(item)
                except Exception as e:
                    self.logger.debug(f"Failed to parse entry from {source_name}: {e}")
                    continue

            self.logger.info(f"✓ {source_name}: {len(items)} items")

        except requests.Timeout:
            self.logger.warning(f"Timeout fetching {source_name}")
        except Exception as e:
            self.logger.warning(f"Error fetching {source_name}: {e}")

        return items

    @staticmethod
    def _parse_entry(entry, source_name: str) -> Optional[ResearchItem]:
        """Parse a single feed entry."""
        title = entry.get('title', '').strip()

        # Try multiple ways to get URL
        url = (
            entry.get('link') or
            entry.get('id') or
            entry.get('url', '')
        )

        if not title or not url:
            return None

        summary = entry.get('summary', '') or entry.get('description', '')
        summary = BeautifulSoup(summary, 'html.parser').get_text()[:500].strip()

        published = entry.get('published', '') or entry.get('updated', '')

        return ResearchItem(
            title=title,
            url=url,
            source=source_name,
            published_date=published,
            summary=summary,
            categories=[],  # Will be set by scorer
            relevance_score=0.0  # Will be set by scorer
        )


# ============================================================================
# REPORT GENERATION
# ============================================================================

class ReportGenerator:
    """Generates JSON and markdown reports."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_json_report(self, items: List[ResearchItem], timestamp: str = None) -> Path:
        """Save detailed JSON report."""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d")

        report_path = self.output_dir / f"research-feed-{timestamp}.json"

        # Convert items to dict and sort by relevance
        items_data = sorted(
            [asdict(item) for item in items],
            key=lambda x: x['relevance_score'],
            reverse=True
        )

        report = {
            "generated_at": datetime.now().isoformat(),
            "total_items": len(items),
            "items": items_data
        }

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return report_path

    def save_markdown_report(self, items: List[ResearchItem], timestamp: str = None) -> Path:
        """Save human-readable markdown report."""
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d")

        report_path = self.output_dir / f"research-digest-{timestamp}.md"

        # Sort by relevance
        sorted_items = sorted(items, key=lambda x: x['relevance_score'], reverse=True)

        # Group by category
        by_category: Dict[str, List[ResearchItem]] = {}
        for item in sorted_items:
            for cat in item.categories or ['uncategorized']:
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(item)

        lines = []
        lines.append(f"# Research Digest — {timestamp}\n")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        lines.append(f"**Total Items:** {len(sorted_items)}\n")
        lines.append(f"**Period:** Last 24 hours\n\n")

        lines.append("---\n")

        # Top items
        lines.append("## 🔥 Top Picks\n")
        for i, item in enumerate(sorted_items[:10], 1):
            lines.append(f"{i}. **{item.title}** _(Score: {item.relevance_score:.1f})_")
            lines.append(f"   - Source: {item.source}")
            if item.categories:
                lines.append(f"   - Tags: {', '.join(item.categories)}")
            lines.append(f"   - [Read →]({item.url})\n")

        lines.append("---\n\n")

        # By category
        lines.append("## 📚 By Category\n")
        category_order = [
            "ai_ml", "image_gen", "video_gen", "music_gen",
            "privacy", "legal_tech", "automation", "uncategorized"
        ]

        for category in category_order:
            if category not in by_category:
                continue

            items_in_cat = by_category[category]
            cat_display = category.replace('_', ' ').title()

            lines.append(f"### {cat_display}\n")
            lines.append(f"_{len(items_in_cat)} items_\n")

            for item in items_in_cat[:5]:  # Top 5 per category
                lines.append(f"- **{item.title}**")
                lines.append(f"  - {item.source} | Score: {item.relevance_score:.1f}")
                lines.append(f"  - [{item.url}]({item.url})\n")

        lines.append("---\n")
        lines.append(f"*This digest was auto-generated by workhorse-research-feed.py*\n")

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        return report_path


# ============================================================================
# MAIN ORCHESTRATION
# ============================================================================

class ResearchFeedSystem:
    """Main orchestration class."""

    def __init__(self, debug: bool = False, quick_mode: bool = False):
        self.logger = setup_logging(debug=debug)
        self.debug = debug
        self.quick_mode = quick_mode

        self.base_dir = Path(__file__).parent
        self.log_dir = self.base_dir / "rudy-logs"
        self.log_dir.mkdir(exist_ok=True)

        self.cache = URLCache(self.log_dir / "research-feed-cache.json")
        self.scorer = RelevanceScorer()
        self.fetcher = FeedFetcher(self.logger)
        self.reporter = ReportGenerator(self.log_dir)

        self.feeds = self._load_feed_config()

    def _load_feed_config(self) -> Dict[str, str]:
        """Load feed configuration, falling back to defaults."""
        feed_config_file = self.log_dir / "research-feeds.json"

        if feed_config_file.exists():
            try:
                with open(feed_config_file, 'r', encoding='utf-8') as f:
                    return json.load(f).get('feeds', DEFAULT_FEEDS)
            except Exception as e:
                self.logger.warning(f"Failed to load feed config: {e}. Using defaults.")

        # Save defaults for future use
        try:
            with open(feed_config_file, 'w', encoding='utf-8') as f:
                json.dump({'feeds': DEFAULT_FEEDS}, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save default feed config: {e}")

        return DEFAULT_FEEDS

    def run(self) -> tuple[List[ResearchItem], Path, Path]:
        """Run the full research feed pipeline."""
        self.logger.info("=" * 80)
        self.logger.info("Workhorse Research Feed System")
        self.logger.info(f"Mode: {'QUICK' if self.quick_mode else 'FULL'}")
        self.logger.info("=" * 80)

        # Limit feeds in quick mode
        feeds_to_process = self.feeds
        if self.quick_mode:
            top_feeds = list(self.feeds.items())[:5]
            feeds_to_process = dict(top_feeds)
            self.logger.info(f"QUICK mode: Processing {len(feeds_to_process)} feeds")

        all_items = []

        # Fetch from all feeds
        self.logger.info(f"\nFetching from {len(feeds_to_process)} feeds...")
        for source_name, feed_url in feeds_to_process.items():
            items = self.fetcher.fetch_feed(feed_url, source_name, MAX_ITEMS_PER_FEED)
            all_items.extend(items)

        self.logger.info(f"\nTotal raw items collected: {len(all_items)}")

        # Deduplicate
        before_dedup = len(all_items)
        unique_items = []
        for item in all_items:
            if not self.cache.has_seen(item.url):
                unique_items.append(item)
                self.cache.mark_seen(item.url)

        self.logger.info(f"After deduplication: {len(unique_items)} new items")
        self.cache.save()

        # Score and rank
        self.logger.info("Scoring items by relevance...")
        for item in unique_items:
            score, categories = self.scorer.score(item.title, item.summary)
            score = self.scorer.recency_boost(score, item.published_date)
            item.relevance_score = score
            item.categories = categories

        # Sort by relevance
        unique_items.sort(key=lambda x: x.relevance_score, reverse=True)

        # Limit to top items in quick mode
        if self.quick_mode:
            unique_items = unique_items[:5]
            self.logger.info(f"QUICK mode: Limiting to top 5 items")

        # Generate reports
        self.logger.info("\nGenerating reports...")
        json_path = self.reporter.save_json_report(unique_items)
        md_path = self.reporter.save_markdown_report(unique_items)

        self.logger.info(f"✓ JSON report: {json_path}")
        self.logger.info(f"✓ Markdown digest: {md_path}")

        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"Successfully processed {len(unique_items)} items")
        self.logger.info(f"{'='*80}\n")

        return unique_items, json_path, md_path


# ============================================================================
# CLI
# ============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Workhorse Research Feed: Automated intelligence gathering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python workhorse-research-feed.py          # Full mode (all feeds, all items)
  python workhorse-research-feed.py --quick  # Quick mode (top 5 feeds, top 5 items)
  python workhorse-research-feed.py --debug  # Full mode with debug logging
        """
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Quick mode: limited feeds and items'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Full mode: all feeds and items (default)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    try:
        system = ResearchFeedSystem(
            debug=args.debug,
            quick_mode=args.quick
        )
        items, json_path, md_path = system.run()

        sys.exit(0)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
