#!/usr/bin/env python3
"""
Workhorse Feed Subscription Manager
Manage RSS feeds for the research feed system.

Usage:
    python workhorse-subscribe.py list                    # Show all monitored feeds
    python workhorse-subscribe.py add <name> <url>       # Add a new feed
    python workhorse-subscribe.py remove <name>          # Remove a feed
    python workhorse-subscribe.py validate               # Test all feeds for connectivity
    python workhorse-subscribe.py import <json_file>     # Bulk import feeds from JSON
    python workhorse-subscribe.py export                 # Export feeds to JSON
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

try:
    import requests
    import feedparser
except ImportError:
    print("ERROR: Required packages missing. Install with:")
    print("  pip install requests feedparser")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

REQUEST_TIMEOUT = 5


# ============================================================================
# LOGGING
# ============================================================================

def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure simple logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logger = logging.getLogger("workhorse-subscribe")
    logger.setLevel(level)

    # Console handler only
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console.setFormatter(fmt)

    logger.addHandler(console)
    return logger


# ============================================================================
# FEED CONFIGURATION MANAGER
# ============================================================================

class FeedConfigManager:
    """Manages the feed configuration file."""

    def __init__(self, config_path: Path, logger: logging.Logger):
        self.config_path = config_path
        self.logger = logger
        self.config: Dict = {"feeds": {}}
        self.load()

    def load(self):
        """Load configuration from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    if 'feeds' not in self.config:
                        self.config['feeds'] = {}
                    self.logger.debug(f"Loaded {len(self.config['feeds'])} feeds from config")
            except Exception as e:
                self.logger.error(f"Failed to load config: {e}")
                self.config = {"feeds": {}}
        else:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.save()

    def save(self):
        """Save configuration to disk."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"Saved config to {self.config_path}")
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")
            raise

    def add_feed(self, name: str, url: str) -> bool:
        """Add a feed to the configuration."""
        # Validate
        if name in self.config['feeds']:
            self.logger.warning(f"Feed '{name}' already exists. Use 'remove' first to replace it.")
            return False

        if not self._validate_url(url):
            self.logger.error(f"Invalid URL: {url}")
            return False

        self.config['feeds'][name] = url
        self.save()
        self.logger.info(f"✓ Added feed: {name}")
        return True

    def remove_feed(self, name: str) -> bool:
        """Remove a feed from the configuration."""
        if name not in self.config['feeds']:
            self.logger.error(f"Feed '{name}' not found")
            return False

        url = self.config['feeds'].pop(name)
        self.save()
        self.logger.info(f"✓ Removed feed: {name}")
        return True

    def list_feeds(self) -> Dict[str, str]:
        """Return all feeds."""
        return self.config.get('feeds', {})

    def get_feed(self, name: str) -> Optional[str]:
        """Get a single feed URL by name."""
        return self.config['feeds'].get(name)

    @staticmethod
    def _validate_url(url: str) -> bool:
        """Basic URL validation."""
        try:
            result = urlparse(url)
            return all([result.scheme in ['http', 'https'], result.netloc])
        except Exception:
            return False


# ============================================================================
# FEED VALIDATOR
# ============================================================================

class FeedValidator:
    """Validates feed connectivity and health."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def validate_feed(self, name: str, url: str, timeout: int = REQUEST_TIMEOUT) -> tuple[bool, str]:
        """
        Validate a single feed.
        Returns: (is_valid, message)
        """
        try:
            # Parse feed
            feed = feedparser.parse(url, timeout=timeout)

            # Check for parse errors
            if feed.bozo and isinstance(feed.bozo_exception, Exception):
                if "401" in str(feed.bozo_exception) or "403" in str(feed.bozo_exception):
                    return False, f"Access denied (401/403)"
                if "404" in str(feed.bozo_exception):
                    return False, f"Not found (404)"

            # Check for entries
            if len(feed.entries) == 0:
                return False, "Feed has no entries"

            # Extract feed title
            feed_title = feed.feed.get('title', 'Unknown')

            return True, f"✓ Valid ({len(feed.entries)} entries) - {feed_title}"

        except requests.Timeout:
            return False, "Timeout"
        except requests.ConnectionError:
            return False, "Connection error"
        except Exception as e:
            return False, f"Parse error: {str(e)[:50]}"

    def validate_all(self, feeds: Dict[str, str]) -> Dict[str, tuple[bool, str]]:
        """Validate all feeds."""
        results = {}
        total = len(feeds)

        for i, (name, url) in enumerate(feeds.items(), 1):
            self.logger.info(f"Validating {i}/{total}: {name}...", end='', flush=True)
            is_valid, msg = self.validate_feed(name, url)
            results[name] = (is_valid, msg)
            status = "✓" if is_valid else "✗"
            self.logger.info(f" {status}")

        return results


# ============================================================================
# CLI COMMANDS
# ============================================================================

class SubscribeCommands:
    """CLI command handlers."""

    def __init__(self, config_manager: FeedConfigManager, logger: logging.Logger):
        self.config = config_manager
        self.logger = logger
        self.validator = FeedValidator(logger)

    def cmd_list(self, args):
        """List all monitored feeds."""
        feeds = self.config.list_feeds()

        if not feeds:
            self.logger.info("No feeds configured. Use 'add' to add feeds.")
            return 0

        self.logger.info(f"\n{'Configured Feeds':^80}")
        self.logger.info("=" * 80)

        for name, url in sorted(feeds.items()):
            self.logger.info(f"\n{name}")
            self.logger.info(f"  {url}")

        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"Total: {len(feeds)} feeds\n")
        return 0

    def cmd_add(self, args):
        """Add a new feed."""
        if not args.name or not args.url:
            self.logger.error("Usage: add <name> <url>")
            return 1

        name = args.name.lower().replace(' ', '_')
        url = args.url.strip()

        # Validate before adding
        is_valid, msg = self.validator.validate_feed(name, url, timeout=10)
        if not is_valid:
            self.logger.warning(f"Feed validation failed: {msg}")
            response = input("Add anyway? (y/N): ").strip().lower()
            if response != 'y':
                return 1

        success = self.config.add_feed(name, url)
        return 0 if success else 1

    def cmd_remove(self, args):
        """Remove a feed."""
        if not args.name:
            self.logger.error("Usage: remove <name>")
            return 1

        name = args.name.lower().replace(' ', '_')

        # Confirm
        url = self.config.get_feed(name)
        if url:
            self.logger.info(f"Removing: {name}")
            self.logger.info(f"  {url}")
            response = input("Confirm removal? (y/N): ").strip().lower()
            if response != 'y':
                self.logger.info("Cancelled.")
                return 1

        success = self.config.remove_feed(name)
        return 0 if success else 1

    def cmd_validate(self, args):
        """Validate all feeds."""
        feeds = self.config.list_feeds()

        if not feeds:
            self.logger.warning("No feeds configured.")
            return 0

        self.logger.info(f"\nValidating {len(feeds)} feeds...\n")

        results = self.validator.validate_all(feeds)

        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"{'Validation Results':^80}")
        self.logger.info("=" * 80)

        valid_count = 0
        for name in sorted(results.keys()):
            is_valid, msg = results[name]
            status = "✓" if is_valid else "✗"
            self.logger.info(f"{status} {name:30} {msg}")
            if is_valid:
                valid_count += 1

        self.logger.info(f"{'='*80}")
        self.logger.info(f"Valid: {valid_count}/{len(feeds)}\n")

        return 0 if valid_count == len(feeds) else 1

    def cmd_export(self, args):
        """Export feeds to JSON file."""
        feeds = self.config.list_feeds()

        if not feeds:
            self.logger.warning("No feeds to export.")
            return 0

        output_file = args.output or Path.cwd() / "research-feeds-export.json"

        export_data = {
            "metadata": {
                "version": 1,
                "exported_from": "workhorse-subscribe.py",
                "timestamp": Path(__file__).stem
            },
            "feeds": feeds
        }

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"✓ Exported {len(feeds)} feeds to {output_file}\n")
            return 0
        except Exception as e:
            self.logger.error(f"Failed to export: {e}")
            return 1

    def cmd_import(self, args):
        """Import feeds from JSON file."""
        if not args.file:
            self.logger.error("Usage: import <json_file>")
            return 1

        import_file = Path(args.file)

        if not import_file.exists():
            self.logger.error(f"File not found: {import_file}")
            return 1

        try:
            with open(import_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            feeds_to_import = data.get('feeds', {})

            if not feeds_to_import:
                self.logger.warning("No feeds found in import file.")
                return 1

            self.logger.info(f"Found {len(feeds_to_import)} feeds to import:")
            for name in feeds_to_import.keys():
                self.logger.info(f"  - {name}")

            response = input(f"\nImport {len(feeds_to_import)} feeds? (y/N): ").strip().lower()
            if response != 'y':
                self.logger.info("Cancelled.")
                return 1

            added = 0
            skipped = 0

            for name, url in feeds_to_import.items():
                name = name.lower().replace(' ', '_')
                if self.config.get_feed(name):
                    self.logger.info(f"  ⊘ {name} (already exists)")
                    skipped += 1
                else:
                    if self.config.add_feed(name, url):
                        added += 1

            self.logger.info(f"\n✓ Imported {added} feeds, {skipped} skipped\n")
            return 0

        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON: {e}")
            return 1
        except Exception as e:
            self.logger.error(f"Import failed: {e}")
            return 1


# ============================================================================
# MAIN
# ============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Workhorse Feed Subscription Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  list                          Show all monitored feeds
  add <name> <url>             Add a new feed
  remove <name>                Remove a feed
  validate                      Test all feeds for connectivity
  export [output_file]          Export feeds to JSON
  import <json_file>            Bulk import feeds from JSON

Examples:
  python workhorse-subscribe.py list
  python workhorse-subscribe.py add ai_daily https://example.com/feed.xml
  python workhorse-subscribe.py validate
  python workhorse-subscribe.py export backup.json
  python workhorse-subscribe.py import backup.json
        """
    )

    parser.add_argument('command', nargs='?', default='list')
    parser.add_argument('name', nargs='?')
    parser.add_argument('url', nargs='?')
    parser.add_argument('--output', '-o', help='Output file for export')
    parser.add_argument('--file', '-f', help='Input file for import')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')

    args = parser.parse_args()

    logger = setup_logging(verbose=args.verbose)

    # Setup paths
    base_dir = Path(__file__).parent
    log_dir = base_dir / "rudy-logs"
    log_dir.mkdir(exist_ok=True)
    config_path = log_dir / "research-feeds.json"

    # Initialize manager
    config_manager = FeedConfigManager(config_path, logger)
    commands = SubscribeCommands(config_manager, logger)

    # Route command
    try:
        if args.command == 'list':
            return commands.cmd_list(args)
        elif args.command == 'add':
            return commands.cmd_add(args)
        elif args.command == 'remove':
            return commands.cmd_remove(args)
        elif args.command == 'validate':
            return commands.cmd_validate(args)
        elif args.command == 'export':
            return commands.cmd_export(args)
        elif args.command == 'import':
            return commands.cmd_import(args)
        else:
            logger.error(f"Unknown command: {args.command}")
            logger.info("Use 'python workhorse-subscribe.py --help' for usage.")
            return 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        return 130
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
