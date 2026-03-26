# Workhorse Research Feed System

**Automated intelligence gathering for an AI-focused automation hub.**

This system continuously monitors industry-relevant RSS feeds, scores items by relevance to your interests, and generates both structured JSON and human-readable reports. Designed to run on Windows 11 as part of The Workhorse's always-on automation stack.

---

## Quick Start

### Basic Usage

```bash
# Run a full research feed cycle
python workhorse-research-feed.py

# Quick mode: limited feeds and items (for testing)
python workhorse-research-feed.py --quick

# With debug logging
python workhorse-research-feed.py --debug
```

### Manage Subscriptions

```bash
# List all monitored feeds
python workhorse-subscribe.py list

# Add a new feed
python workhorse-subscribe.py add ai_news https://example.com/feed.xml

# Remove a feed
python workhorse-subscribe.py remove ai_news

# Validate all feeds (check connectivity)
python workhorse-subscribe.py validate

# Export feeds to JSON
python workhorse-subscribe.py export backup.json

# Import feeds from JSON
python workhorse-subscribe.py import backup.json
```

---

## System Overview

### What It Does

1. **Fetches**: Pulls latest entries from 20+ preconfigured RSS feeds covering:
   - AI/ML tools and releases (Claude, GPT, open-source models)
   - Image generation (Stable Diffusion, FLUX, Midjourney)
   - Video generation (Sora, Runway, etc.)
   - Music generation (Suno, Udio)
   - Privacy & security tools
   - Legal technology
   - Home automation & workflow automation

2. **Deduplicates**: Maintains a local cache of seen URLs to avoid reporting the same article twice

3. **Scores**: Ranks items by relevance using keyword matching and category-based multipliers

4. **Reports**: Generates two outputs:
   - **JSON**: Structured data for programmatic use (full details, scores, categories)
   - **Markdown**: Human-readable digest sorted by category and relevance

### Architecture

```
workhorse-research-feed.py
├── FeedFetcher         → Pulls from RSS feeds using feedparser
├── RelevanceScorer     → Keyword matching + category multipliers
├── URLCache            → Deduplication across runs
└── ReportGenerator     → JSON + Markdown output

workhorse-subscribe.py
├── FeedConfigManager   → Manage research-feeds.json
├── FeedValidator       → Test feed connectivity
└── SubscribeCommands   → CLI interface
```

### Output Files

All reports are saved to `rudy-logs/`:

```
rudy-logs/
├── research-feed-2026-03-26.json         # Structured report (high detail)
├── research-digest-2026-03-26.md         # Human digest (markdown)
├── research-feeds.json                   # Active feed subscriptions
├── research-feed-cache.json              # Seen URLs (deduplication)
├── workhorse-research-feed-[date].log    # Execution logs
└── workhorse-research-feed-[date]-[time].log
```

---

## Configuration

### Feed Subscriptions

Feeds are stored in `rudy-logs/research-feeds.json`:

```json
{
  "feeds": {
    "anthropic_blog": "https://www.anthropic.com/blog/rss.xml",
    "hacker_news": "https://news.ycombinator.com/rss",
    "arxiv_cs_ai": "http://arxiv.org/rss/cs.AI",
    ...
  }
}
```

**Default feeds** cover:
- Anthropic, OpenAI, DeepMind blogs
- Hacker News, TechCrunch AI
- arXiv (CS.AI, CS.CV)
- GitHub Trending
- Product Hunt
- PyTorch, Hugging Face blogs
- Mozilla & EFF security blogs
- Krebs on Security
- Legal tech publications
- Home automation hubs

### Relevance Keywords & Scoring

**Keywords** organized by category:
- `ai_ml`: Claude, GPT, LLM, transformer, MCP server, etc. (multiplier: 2.5x)
- `image_gen`: Stable Diffusion, DALL-E, FLUX (multiplier: 2.0x)
- `video_gen`: Sora, Runway, text-to-video (multiplier: 2.0x)
- `music_gen`: Suno, Udio, AI music (multiplier: 1.8x)
- `privacy`: Encryption, VPN, Tor, anonymity (multiplier: 1.5x)
- `legal_tech`: Contract automation, legal AI, due diligence (multiplier: 1.8x)
- `automation`: Home automation, RPA, Zapier, n8n (multiplier: 1.5x)

**Scoring formula:**
```
base_score = number_of_matching_keywords
final_score = base_score * category_multiplier
final_score = recency_boost(final_score)  # Subtract 1% per day old
```

Higher scores = more relevant to your interests.

---

## Modes

### Full Mode (default)

```bash
python workhorse-research-feed.py
```

- Processes all 20+ feeds
- Includes all items from each feed
- Takes ~5-15 minutes depending on feed responsiveness
- Best for comprehensive daily briefings

### Quick Mode

```bash
python workhorse-research-feed.py --quick
```

- Processes only 5 key feeds (Anthropic, Hacker News, arXiv CS.AI, TechCrunch, Product Hunt)
- Limits to 5 items per feed
- Final digest shows top 5 items
- Takes ~30-60 seconds
- Best for quick testing or when bandwidth is limited

### Debug Mode

```bash
python workhorse-research-feed.py --debug
```

- Full mode with verbose logging
- Logs all feed parse attempts, errors, deduplication decisions
- Useful for troubleshooting feed issues

---

## Integration with Workhorse

### Scheduled Execution

Add to Windows Task Scheduler for daily runs:

```powershell
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$action = New-ScheduledTaskAction -Execute "python.exe" `
  -Argument "C:\Users\C\Desktop\workhorse-research-feed.py" `
  -WorkingDirectory "C:\Users\C\Desktop"
Register-ScheduledTask -TaskName "WorkhorseResearchFeed" `
  -Trigger $trigger -Action $action -RunLevel Highest
```

Or via `workhorse-startup.bat`:

```batch
REM Add to your startup script:
cd /d C:\Users\C\Desktop
timeout /t 60  REM Wait for network
python workhorse-research-feed.py >> C:\Users\C\Desktop\rudy-logs\research-feed-startup.log 2>&1
```

### Via Command Runner

If you have `rudy-command-runner.py` running:

```bash
# Create C:\Users\C\Desktop\rudy-commands\run-research-feed.cmd
@echo off
cd /d C:\Users\C\Desktop
python workhorse-research-feed.py
```

Then trigger via Cowork or scheduled task.

### Webhook Integration

For programmatic consumption, parse the JSON output:

```python
import json
from pathlib import Path

report_file = Path("rudy-logs") / "research-feed-2026-03-26.json"
with open(report_file) as f:
    data = json.load(f)

print(f"Found {data['total_items']} items")
for item in data['items'][:5]:  # Top 5
    print(f"{item['title']} (score: {item['relevance_score']:.1f})")
    print(f"  Categories: {item['categories']}")
    print(f"  {item['url']}\n")
```

---

## Troubleshooting

### Feeds Not Updating

1. **Check connectivity:**
   ```bash
   python workhorse-subscribe.py validate
   ```

2. **Check for parse errors:**
   ```bash
   python workhorse-research-feed.py --debug 2>&1 | grep -i error
   ```

3. **Check cache file:**
   ```bash
   cat rudy-logs/research-feed-cache.json | python -m json.tool | head -20
   ```

4. **Clear cache if stale:**
   ```bash
   rm rudy-logs/research-feed-cache.json
   ```

### Missing Output Files

- Ensure `rudy-logs/` directory exists (auto-created if missing)
- Check disk space: `dir C:\Users\C\Desktop\rudy-logs`
- Verify write permissions on the directory

### Timeout Errors

- Some feeds are slow to respond. Default timeout is 10 seconds per feed.
- Edit `REQUEST_TIMEOUT = 10` in `workhorse-research-feed.py` to increase
- Run in `--quick` mode to test fewer feeds

### Unicode Issues (Windows)

- Scripts use UTF-8 encoding internally
- Output files are UTF-8 encoded with BOM for Windows compatibility
- If you see garbled text, ensure your editor opens files as UTF-8

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Typical full run time | 5-15 minutes |
| Quick run time | 30-60 seconds |
| Feeds processed (full) | 20+ |
| Items per feed | 30 (configurable) |
| Deduplication cache | ~5000 URLs (grows daily) |
| JSON report size | 200-500 KB |
| Markdown digest size | 50-150 KB |

**Network requirements:**
- Bandwidth: ~5-10 MB per full run
- Concurrent connections: 1-3 (sequential fetching)
- No proxies required (direct HTTPS)

---

## Customization

### Add Custom Keywords

Edit `RELEVANCE_KEYWORDS` in `workhorse-research-feed.py`:

```python
RELEVANCE_KEYWORDS = {
    "my_topic": [
        "keyword1", "keyword2", "keyword3"
    ],
}
```

Then add a multiplier:

```python
SCORING_MULTIPLIERS = {
    "my_topic": 2.0,  # High priority
}
```

Re-run to rescore all items.

### Add New Feed

Via CLI:

```bash
python workhorse-subscribe.py add my_feed https://example.com/feed.xml
```

Or bulk import:

```bash
python workhorse-subscribe.py export current.json
# Edit current.json to add new feeds...
python workhorse-subscribe.py import current.json
```

### Change Output Location

Edit `self.log_dir` in `workhorse-research-feed.py`:

```python
self.log_dir = Path("C:/my/custom/path")  # Change this
```

### Adjust Item Limits

```python
MAX_ITEMS_PER_FEED = 50  # Default: 30 items per feed
```

---

## Security & Privacy

### Data Collected

The system stores:
- Feed URLs and metadata (stored in `research-feeds.json`)
- Article titles, summaries, and URLs (in JSON/markdown reports)
- Timestamps (publication dates)

**Does NOT:**
- Send your data anywhere (offline processing)
- Store passwords or credentials
- Track your reading habits
- Modify any external resources

### Feed Sources

All feeds are from **public RSS endpoints** of major publishers:
- Anthropic, OpenAI, DeepMind
- arXiv (academic preprints)
- Hacker News, Product Hunt
- News sites (TechCrunch, etc.)

No authentication required.

### Cache Privacy

`research-feed-cache.json` contains only normalized URLs (lowercased, no query params). It's used solely to avoid duplicate reports in subsequent runs.

---

## Advanced Usage

### Bulk Export & Backup

```bash
# Export current feeds
python workhorse-subscribe.py export feeds-backup-2026-03-26.json

# Later, restore from backup
python workhorse-subscribe.py import feeds-backup-2026-03-26.json
```

### Programmatic Feed Management

```python
from pathlib import Path
from workhorse_subscribe import FeedConfigManager
import logging

logger = logging.getLogger(__name__)
config_path = Path("rudy-logs/research-feeds.json")
manager = FeedConfigManager(config_path, logger)

# Add multiple feeds
for name, url in my_feeds.items():
    manager.add_feed(name, url)
```

### Custom Report Processing

```python
import json
from pathlib import Path

# Load today's report
report = json.load(open("rudy-logs/research-feed-2026-03-26.json"))

# Find top items by category
by_category = {}
for item in report['items']:
    for cat in item['categories']:
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(item)

# Send alerts for high-scoring items
for item in report['items']:
    if item['relevance_score'] > 5.0:
        send_alert(item['title'], item['url'])
```

---

## Logs

All execution logs are stored in `rudy-logs/`:

```
workhorse-research-feed-20260326.log    # Daily log (appended)
workhorse-research-feed-20260326-143022.log  # Timestamped per run
```

**Log levels:**
- `INFO`: Feed fetches, counts, report generation
- `DEBUG`: Feed parse details, keyword matches, scores
- `WARNING`: Feed timeouts, parse failures
- `ERROR`: Fatal errors (missing dependencies, etc.)

**View logs:**

```bash
# Last 50 lines
tail -50 rudy-logs/workhorse-research-feed-20260326.log

# Search for errors
grep ERROR rudy-logs/workhorse-research-feed-*.log
```

---

## Requirements

**Python:** 3.10+
**Installed packages:**
- `requests` (HTTP fetching)
- `beautifulsoup4` (HTML parsing)
- `feedparser` (RSS/Atom parsing)

**Install:**

```bash
pip install requests beautifulsoup4 feedparser
```

**Disk space:** ~50 MB for all logs and cache files

**Network:** Outbound HTTPS (port 443) to RSS feed hosts

---

## Maintenance

### Weekly Cleanup

The system maintains its own cache, but you can manually prune old reports:

```bash
# Keep only last 30 days of reports
Get-ChildItem rudy-logs/research-*.json -mtime +30 | Remove-Item
```

### Monthly Feed Audit

```bash
# Validate all feeds and remove dead ones
python workhorse-subscribe.py validate

# Remove any that fail:
python workhorse-subscribe.py remove dead_feed_name
```

### Backup Current Configuration

```bash
# Weekly backup
python workhorse-subscribe.py export "backup-$(Get-Date -Format yyyyMMdd).json"

# Store in your cloud sync folder:
cp backup-*.json /path/to/OneDrive
```

---

## Future Enhancements

Potential additions:
- **Summarization**: Use Claude API to auto-summarize articles
- **Alerts**: Email/Slack notifications for high-priority items
- **Full-text search**: Elasticsearch integration for historical queries
- **Machine learning**: Learn from reading patterns to improve scoring
- **Multi-language**: Translate feeds from other languages
- **Content curation**: Manual star-rating system to refine relevance

---

## Support & Troubleshooting

**Problem:** Script fails with "No module named 'feedparser'"

**Solution:**
```bash
pip install feedparser
```

---

**Problem:** Getting 0 items from feeds

**Solution:**
1. Check internet connectivity: `ping google.com`
2. Validate feeds: `python workhorse-subscribe.py validate`
3. Check logs: `tail -50 rudy-logs/workhorse-research-feed-*.log`
4. Try `--debug` mode for detailed output

---

**Problem:** Reports generated but empty categories

**Solution:**
- Keywords may need adjustment. Edit `RELEVANCE_KEYWORDS` in the script.
- Run `--debug` to see which keywords matched.
- Consider adding domain-specific keywords for your interests.

---

## License & Attribution

These scripts are part of The Workhorse automation system. Use freely for personal/research purposes.

**Dependencies:**
- feedparser (LGPL)
- requests (Apache 2.0)
- beautifulsoup4 (MIT)

---

**Last updated:** 2026-03-26
**Version:** 1.0
**Maintainer:** Christopher M. Cimino
