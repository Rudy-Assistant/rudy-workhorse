# Workhorse Research Feed System - Complete Index

**Deployment Date:** 2026-03-26
**Location:** `C:\Users\C\Desktop\`
**Status:** Production Ready

---

## Files Overview

### Core Executables (Ready to Run)

| File | Size | Purpose | Run Command |
|------|------|---------|-------------|
| **workhorse-research-feed.py** | 22 KB | Main research aggregation engine | `python workhorse-research-feed.py [--quick\|--debug]` |
| **workhorse-subscribe.py** | 16 KB | Feed subscription manager | `python workhorse-subscribe.py [list\|add\|remove\|validate\|export\|import]` |
| **validate-research-feed.py** | 4.4 KB | System health check | `python validate-research-feed.py` |
| **research-feed.cmd** | 1 KB | Windows batch launcher | `research-feed.cmd [quick\|full\|validate]` |

### Setup & Automation

| File | Type | Purpose |
|------|------|---------|
| **RESEARCH-FEED-SETUP.ps1** | PowerShell | Windows Task Scheduler setup (run as Admin) |

### Documentation

| File | Size | Best For |
|------|------|----------|
| **RESEARCH-FEED-README.md** | 14 KB | Comprehensive reference guide |
| **research-feed-integration.md** | 11 KB | Quick start & integration examples |
| **RESEARCH-FEED-SUMMARY.txt** | 15 KB | System overview & deployment notes |
| **RESEARCH-FEED-INDEX.md** | This file | File navigation & quick reference |

### Output Directory (Auto-Created)

| Folder | Purpose |
|--------|---------|
| **rudy-logs/** | All reports, logs, and configuration |

---

## Quick Start (5 Steps)

### 1. Verify System
```bash
python validate-research-feed.py
```
Checks Python version, packages, and syntax.

### 2. Run Quick Test
```bash
python workhorse-research-feed.py --quick
```
Takes 30-60 seconds, processes 5 feeds.

### 3. View Results
```bash
type rudy-logs\research-digest-*.md
```
Human-readable summary grouped by category.

### 4. Schedule Automation
```powershell
.\RESEARCH-FEED-SETUP.ps1
```
Creates Windows Task Scheduler entry (run as Administrator).

### 5. Monitor Daily
Reports auto-generated at 6:00 AM in `rudy-logs/`

---

## Essential Commands Reference

### Run Research Feed
```bash
# Quick test (5 feeds, fast)
python workhorse-research-feed.py --quick

# Full comprehensive scan
python workhorse-research-feed.py

# With detailed logging
python workhorse-research-feed.py --debug
```

### Manage Feeds
```bash
# List all monitored feeds
python workhorse-subscribe.py list

# Add a new feed
python workhorse-subscribe.py add my_feed https://example.com/feed.xml

# Check feed health
python workhorse-subscribe.py validate

# Backup feeds
python workhorse-subscribe.py export backup.json

# Restore feeds
python workhorse-subscribe.py import backup.json
```

### System Checks
```bash
# Validate everything
python validate-research-feed.py

# Check logs
type rudy-logs\workhorse-research-feed-*.log

# View report
type rudy-logs\research-digest-*.md

# View structured data
python -m json.tool < rudy-logs\research-feed-*.json | less
```

---

## Output Files

Located in `C:\Users\C\Desktop\rudy-logs/`

| File | Contents | Format | Frequency |
|------|----------|--------|-----------|
| `research-feed-YYYY-MM-DD.json` | Full report with scores | Structured JSON | Daily |
| `research-digest-YYYY-MM-DD.md` | Human-readable summary | Markdown | Daily |
| `research-feeds.json` | Active feed subscriptions | JSON config | When modified |
| `research-feed-cache.json` | Deduplication cache | JSON array | Auto-updated |
| `workhorse-research-feed-*.log` | Execution logs | Plain text | Per run |

---

## System Architecture

```
workhorse-research-feed.py
├─ Fetch         → Pull from 20+ RSS feeds (parallel)
├─ Parse         → Extract title, URL, summary, date
├─ Score         → Keyword matching + multipliers
├─ Deduplicate   → Compare against cache.json
├─ Rank          → Sort by relevance_score
└─ Report        → Generate JSON + Markdown

workhorse-subscribe.py
├─ List          → Show current feeds
├─ Add/Remove    → Manage subscriptions
├─ Validate      → Test connectivity
└─ Export/Import → Backup/restore configuration

validate-research-feed.py
├─ Check Python  → Version 3.10+
├─ Check Packages → feedparser, requests, beautifulsoup4
├─ Check Files   → Script syntax and integrity
├─ Check Dirs    → rudy-logs/ exists
└─ Test Imports  → Scripts parse correctly
```

---

## Feed Categories & Scoring

### Coverage Areas (20+ Default Feeds)

| Category | Keyword Examples | Multiplier | Default Feeds |
|----------|------------------|-----------|---|
| **AI/ML** | Claude, GPT, LLM, MCP, transformer | 2.5x | Anthropic, OpenAI, DeepMind, arXiv |
| **Image Gen** | DALL-E, Stable Diffusion, FLUX | 2.0x | Implicit in AI blogs |
| **Video Gen** | Sora, Runway, text-to-video | 2.0x | TechCrunch AI, Product Hunt |
| **Music Gen** | Suno, Udio, AI music | 1.8x | AI tech news |
| **Privacy** | Encryption, VPN, Tor, GDPR | 1.5x | Mozilla, EFF, Krebs |
| **Legal Tech** | Contract automation, legal AI | 1.8x | Legal tech publications |
| **Automation** | RPA, Zapier, n8n, smart home | 1.5x | Automation hubs |

**Scoring Formula:**
```
base_score = count(matching_keywords)
final_score = base_score * category_multiplier * recency_boost
```

Higher score = higher relevance to your interests.

---

## Performance Specs

| Metric | Quick Mode | Full Mode |
|--------|-----------|-----------|
| **Time** | 30-60 seconds | 5-15 minutes |
| **Feeds** | 5 | 20+ |
| **Items per feed** | 5 | 30 |
| **Network** | ~1 MB | ~10 MB |
| **Output size** | ~50 KB | ~250-500 KB |

---

## Integration Patterns

### Windows Task Scheduler
```powershell
.\RESEARCH-FEED-SETUP.ps1
```
Creates daily automated run at 6:00 AM.

### Command Runner (Cowork)
Create: `C:\Users\C\Desktop\rudy-commands\research-feed.cmd`
```batch
@echo off
cd /d C:\Users\C\Desktop
python workhorse-research-feed.py
```

### Startup Script
Add to `workhorse-startup.bat`:
```batch
cd /d C:\Users\C\Desktop
timeout /t 60
python workhorse-research-feed.py >> rudy-logs\startup.log 2>&1
```

### Zapier/Make Automation
1. Schedule trigger (daily)
2. Execute: `python workhorse-research-feed.py`
3. Wait for: `research-digest-*.md`
4. Email or post to Slack

---

## Configuration Files

### research-feeds.json
```json
{
  "feeds": {
    "anthropic_blog": "https://www.anthropic.com/blog/rss.xml",
    "hacker_news": "https://news.ycombinator.com/rss",
    ...
  }
}
```
Managed by `workhorse-subscribe.py`. Edit via CLI.

### research-feed-cache.json
```json
[
  "https://example.com/article1",
  "https://example.com/article2",
  ...
]
```
Auto-maintained. Clear to start fresh deduplication.

---

## Troubleshooting Quick Reference

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'feedparser'` | `pip install feedparser requests beautifulsoup4` |
| No items in report | `python workhorse-subscribe.py validate` |
| Script won't run | `python validate-research-feed.py` |
| Feeds timing out | Use `--quick` mode or increase `REQUEST_TIMEOUT` |
| Duplicate reports | `rm rudy-logs\research-feed-cache.json` and retry |
| Task scheduler not running | Verify Python path: `where python` |

Full troubleshooting: See **RESEARCH-FEED-README.md**

---

## Documentation Map

### For First-Time Users
1. Start: **research-feed-integration.md** (Getting Started section)
2. Then: **RESEARCH-FEED-README.md** (Configuration section)
3. Refer: **RESEARCH-FEED-SUMMARY.txt** (System overview)

### For Operators
1. Quick reference: **RESEARCH-FEED-SUMMARY.txt** (Scheduling, Performance)
2. Troubleshooting: **RESEARCH-FEED-README.md** (Troubleshooting section)
3. Integration: **research-feed-integration.md** (Workflows section)

### For Developers/Customization
1. Architecture: **RESEARCH-FEED-README.md** (System Overview)
2. Code reference: Read source code comments in `*.py` files
3. Extension: **RESEARCH-FEED-README.md** (Advanced Usage section)

---

## Deployment Checklist

- [ ] Run `python validate-research-feed.py` (verify all systems)
- [ ] Run `python workhorse-research-feed.py --quick` (test)
- [ ] Review `rudy-logs/research-digest-*.md` (check output)
- [ ] Run `python workhorse-subscribe.py list` (see feeds)
- [ ] Run `.\RESEARCH-FEED-SETUP.ps1` (enable scheduling)
- [ ] Verify task in Task Scheduler (WorkhorseResearchFeed)
- [ ] Wait for 6:00 AM tomorrow (first automated run)
- [ ] Check `rudy-logs/` for new reports

---

## Regular Maintenance

### Daily
- Check `rudy-logs/research-digest-[today].md` for updates
- Read top items to stay current

### Weekly
```bash
python workhorse-subscribe.py validate
```
Ensure feeds are responsive.

### Monthly
```bash
python workhorse-subscribe.py export backup-2026-03-26.json
```
Backup configuration.

### As Needed
```bash
python workhorse-subscribe.py add my_feed https://example.com/rss.xml
```
Add new feeds covering emerging interests.

---

## Dependencies

**Python:** 3.10+
**Packages:** requests, beautifulsoup4, feedparser

**Install:**
```bash
pip install requests beautifulsoup4 feedparser
```

**Verify:**
```bash
python -c "import requests, bs4, feedparser; print('OK')"
```

---

## Performance Tips

- Use `--quick` mode for testing
- Run at off-peak hours (3-4 AM) to avoid network contention
- Clear cache monthly for fresh deduplication
- Remove inactive feeds with `workhorse-subscribe.py remove`
- Reduce `MAX_ITEMS_PER_FEED` if bandwidth limited

---

## Support Resources

| Resource | Link/Command |
|----------|--------------|
| Full Documentation | `RESEARCH-FEED-README.md` |
| Quick Reference | `research-feed-integration.md` |
| System Status | `python validate-research-feed.py` |
| Feed Health | `python workhorse-subscribe.py validate` |
| Execution Logs | `type rudy-logs\workhorse-research-feed-*.log` |
| Owner/Contact | Christopher M. Cimino (ccimino2@gmail.com) |

---

## Version Info

| Attribute | Value |
|-----------|-------|
| Version | 1.0 |
| Created | 2026-03-26 |
| Status | Production Ready |
| Python | 3.10+ |
| Platforms | Windows 11 (tested), Cross-platform capable |
| License | Personal/Research use |

---

## File Structure

```
C:\Users\C\Desktop\
├── workhorse-research-feed.py       (Main engine)
├── workhorse-subscribe.py            (Feed manager)
├── validate-research-feed.py         (System check)
├── research-feed.cmd                 (Batch launcher)
├── RESEARCH-FEED-SETUP.ps1          (Scheduler setup)
├── RESEARCH-FEED-README.md          (Full docs)
├── research-feed-integration.md      (Quick reference)
├── RESEARCH-FEED-SUMMARY.txt        (System overview)
├── RESEARCH-FEED-INDEX.md           (This file)
└── rudy-logs/                        (Auto-created)
    ├── research-feed-2026-03-26.json
    ├── research-digest-2026-03-26.md
    ├── research-feeds.json
    ├── research-feed-cache.json
    └── workhorse-research-feed-*.log
```

---

**Last Updated:** 2026-03-26
**Next Review:** Weekly (feed health check)
