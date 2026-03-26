# Research Feed System - Integration Guide

## Quick Reference

### Files Created

| File | Purpose | Size |
|------|---------|------|
| `workhorse-research-feed.py` | Main research aggregation engine | 22 KB |
| `workhorse-subscribe.py` | Feed subscription manager | 16 KB |
| `RESEARCH-FEED-README.md` | Complete documentation | Reference |
| `RESEARCH-FEED-SETUP.ps1` | Windows scheduler setup | Reference |
| `research-feed-integration.md` | This file | Reference |

### Output Location

All reports and logs go to: `C:\Users\C\Desktop\rudy-logs/`

```
research-feed-2026-03-26.json      # Structured report (JSON)
research-digest-2026-03-26.md      # Human-readable digest (Markdown)
research-feeds.json                # Feed configuration
research-feed-cache.json           # URL deduplication cache
workhorse-research-feed-*.log      # Execution logs
```

---

## Getting Started

### 1. Verify Dependencies (One Time)

```powershell
# Run in PowerShell as Administrator
pip install requests beautifulsoup4 feedparser

# Verify
python -c "import requests, feedparser, bs4; print('OK')"
```

### 2. Run First Test

```bash
cd C:\Users\C\Desktop
python workhorse-research-feed.py --quick
```

This should:
- Connect to 5 major feeds
- Fetch items
- Generate `research-feed-*.json` and `research-digest-*.md`
- Show results in console

### 3. View Results

**See today's digest:**
```bash
type rudy-logs\research-digest-*.md | less
```

**Parse JSON programmatically:**
```python
import json
report = json.load(open("rudy-logs/research-feed-2026-03-26.json"))
print(f"Total items: {report['total_items']}")
for item in report['items'][:5]:
    print(f"  {item['title']}")
```

### 4. Configure Feeds (Optional)

```bash
# List current feeds
python workhorse-subscribe.py list

# Add a new feed
python workhorse-subscribe.py add my_feed https://example.com/feed.xml

# Validate all feeds
python workhorse-subscribe.py validate

# Backup feeds
python workhorse-subscribe.py export feeds-backup.json
```

### 5. Schedule Automated Runs

**Option A: Use PowerShell setup script**
```powershell
# Run as Administrator
.\RESEARCH-FEED-SETUP.ps1 -TestRun
```

This creates a daily scheduled task at 6:00 AM.

**Option B: Manual Windows Task Scheduler**
1. Open Task Scheduler
2. Create Basic Task
3. Name: `WorkhorseResearchFeed`
4. Trigger: Daily at 6:00 AM
5. Action:
   - Program: `python.exe`
   - Arguments: `C:\Users\C\Desktop\workhorse-research-feed.py`
   - Start in: `C:\Users\C\Desktop`

**Option C: Add to startup batch**
```batch
REM In your startup script (workhorse-startup.bat):
cd /d C:\Users\C\Desktop
timeout /t 60
python workhorse-research-feed.py >> rudy-logs\research-startup.log 2>&1
```

---

## Usage Examples

### Command Line

```bash
# Full comprehensive scan
python workhorse-research-feed.py

# Quick mode (faster, fewer feeds)
python workhorse-research-feed.py --quick

# With debug output
python workhorse-research-feed.py --debug

# Check feeds for issues
python workhorse-subscribe.py validate

# Add a new feed
python workhorse-subscribe.py add hacker_news_new https://news.ycombinator.com/rss

# Export feeds for backup
python workhorse-subscribe.py export backup-$(date +%Y%m%d).json
```

### Programmatic Usage

**Parse today's report:**
```python
import json
from pathlib import Path
from datetime import datetime

date_str = datetime.now().strftime("%Y-%m-%d")
report_file = Path(f"rudy-logs/research-feed-{date_str}.json")

with open(report_file) as f:
    data = json.load(f)

# Show top 10 items
print(f"Found {data['total_items']} items")
for item in data['items'][:10]:
    print(f"[{item['relevance_score']:.1f}] {item['title']}")
    print(f"     {item['categories']}")
    print()
```

**Monitor for alerts:**
```python
import json
from pathlib import Path
from datetime import datetime

report_file = Path(f"rudy-logs/research-feed-{datetime.now().strftime('%Y-%m-%d')}.json")
data = json.load(open(report_file))

# Alert on high-relevance AI items
for item in data['items']:
    if 'ai_ml' in item['categories'] and item['relevance_score'] > 5.0:
        print(f"🔥 HIGH PRIORITY: {item['title']}")
        print(f"   {item['url']}")
```

**Extract by category:**
```python
import json

data = json.load(open("rudy-logs/research-feed-2026-03-26.json"))

# Group by category
by_cat = {}
for item in data['items']:
    for cat in item['categories']:
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(item)

# Show legal_tech items
print("Legal Tech Updates:")
for item in by_cat.get('legal_tech', [])[:5]:
    print(f"  - {item['title']}")
```

---

## Integration with Cowork / Command Runner

### Via Command Runner Files

If `rudy-command-runner.py` is running:

**Create:** `C:\Users\C\Desktop\rudy-commands\research-feed-run.cmd`
```batch
@echo off
cd /d C:\Users\C\Desktop
python workhorse-research-feed.py
```

**Create:** `C:\Users\C\Desktop\rudy-commands\research-feed-quick.cmd`
```batch
@echo off
cd /d C:\Users\C\Desktop
python workhorse-research-feed.py --quick
```

Then trigger via Cowork's command runner interface.

### Via Zapier / Make Integration

**Scenario 1: Fetch report on demand**

Use Make.com to:
1. Webhook trigger from Slack
2. Execute Windows command (via command runner)
3. Wait for file creation
4. Read JSON report
5. Format and send back to Slack

**Scenario 2: Email digest**

Use Zapier to:
1. On schedule (daily 8:00 AM)
2. Execute Python script
3. When file created: `research-digest-*.md`
4. Email file attachment

---

## Feed Management

### View Current Feeds

```bash
python workhorse-subscribe.py list
```

Output:
```
Configured Feeds
================

anthropic_blog
  https://www.anthropic.com/blog/rss.xml

hacker_news
  https://news.ycombinator.com/rss

[... more feeds ...]

Total: 18 feeds
```

### Add Custom Feed

```bash
python workhorse-subscribe.py add my_custom_feed https://example.com/blog/feed.xml
```

### Test Feed Health

```bash
python workhorse-subscribe.py validate
```

Output:
```
Validating 18 feeds...

✓ anthropic_blog...   ✓
✓ hacker_news...      ✓
✓ arxiv_cs_ai...      ✓
...

Valid: 17/18
```

### Bulk Import/Export

**Export all feeds:**
```bash
python workhorse-subscribe.py export my-feeds.json
```

**Restore from backup:**
```bash
python workhorse-subscribe.py import my-feeds.json
```

---

## Report Formats

### JSON Report Structure

```json
{
  "generated_at": "2026-03-26T15:30:45.123456",
  "total_items": 87,
  "items": [
    {
      "title": "Introducing new MCP server for Claude",
      "url": "https://anthropic.com/blog/...",
      "source": "anthropic_blog",
      "published_date": "2026-03-26T10:00:00Z",
      "summary": "We're excited to announce...",
      "categories": ["ai_ml"],
      "relevance_score": 8.5,
      "timestamp": "2026-03-26T15:30:45.123456"
    },
    ...
  ]
}
```

### Markdown Digest Structure

```markdown
# Research Digest — 2026-03-26

Generated: 2026-03-26 15:30:45 UTC
Total Items: 87
Period: Last 24 hours

---

## 🔥 Top Picks

1. **Introducing new MCP server for Claude** _(Score: 8.5)_
   - Source: anthropic_blog
   - Tags: ai_ml
   - [Read →](https://anthropic.com/...)

...

---

## 📚 By Category

### AI/ML

_(12 items)_

- **Introducing new MCP server for Claude**
  - anthropic_blog | Score: 8.5
  - [https://anthropic.com/...](https://anthropic.com/...)
```

---

## Troubleshooting

### Script won't run

**Error:** `ModuleNotFoundError: No module named 'feedparser'`

**Solution:**
```bash
pip install feedparser requests beautifulsoup4
```

### No items in report

**Debug:**
```bash
python workhorse-research-feed.py --debug 2>&1 | grep -i error
```

**Check feeds:**
```bash
python workhorse-subscribe.py validate
```

**Clear cache and retry:**
```bash
rm rudy-logs/research-feed-cache.json
python workhorse-research-feed.py --quick
```

### Scheduled task not running

**Check:**
1. Task Scheduler → Find `WorkhorseResearchFeed`
2. View "History" tab for errors
3. Verify python.exe path: `where python`
4. Run manually: `python C:\Users\C\Desktop\workhorse-research-feed.py`

### Slow performance

**Optimize:**
- Use `--quick` mode: `python workhorse-research-feed.py --quick`
- Reduce feeds: `python workhorse-subscribe.py remove slow_feed`
- Check network: `ping 8.8.8.8`

---

## Maintenance Schedule

| Task | Frequency | Command |
|------|-----------|---------|
| Full research feed run | Daily (automated) | `python workhorse-research-feed.py` |
| Feed health check | Weekly | `python workhorse-subscribe.py validate` |
| Backup feed config | Monthly | `python workhorse-subscribe.py export` |
| Clear old reports | Monthly | `rm rudy-logs/research-*-[date>30days].json` |

---

## Performance Notes

- **Full mode:** 5-15 minutes, ~10 MB bandwidth
- **Quick mode:** 30-60 seconds, ~1 MB bandwidth
- **Cache size:** Grows ~100-200 URLs per day
- **Disk usage:** ~50 MB per month

To save bandwidth, use Quick mode and increase run frequency strategically.

---

## Examples: Real-World Workflows

### Morning Briefing Workflow

1. **6:00 AM:** Scheduled task runs full research feed
2. **6:30 AM:** You wake up, check your briefing:
   ```bash
   cat rudy-logs/research-digest-$(date +%Y-%m-%d).md
   ```
3. **7:00 AM:** See alerts in email (if integrated with Make/Zapier)
4. **Review:** Top 5-10 items while having coffee

### Legal Tech Monitoring

1. Configure feeds for legal tech blogs (already included)
2. Filter results in daily digest
3. Set up Make.com rule: If `categories` contains `legal_tech`, email excerpt
4. Weekly: Review trends in category-specific reports

### AI Model Tracking

1. Follow arXiv (CS.AI, CS.CV) - already configured
2. Follow OpenAI/Anthropic/DeepMind blogs - already configured
3. Add any custom model registry feeds
4. Daily digest automatically highlights new models
5. Programmatically extract images/videos for team Slack

### Personal Research Archive

1. Run research feed daily (automated)
2. All reports stored in `rudy-logs/`
3. Export quarterly backups:
   ```bash
   python workhorse-subscribe.py export backup-q1-2026.json
   ```
4. Full text searchable via JSON reports

---

## Next Steps

1. **Run test:** `python workhorse-research-feed.py --quick`
2. **Review output:** `cat rudy-logs/research-digest-*.md`
3. **Schedule:** `.\RESEARCH-FEED-SETUP.ps1`
4. **Customize:** `python workhorse-subscribe.py add my_feed <url>`
5. **Monitor:** Check logs daily in `rudy-logs/`

---

For complete documentation, see **RESEARCH-FEED-README.md**
