# Memory

## Me
Christopher M. Cimino (ccimino2@gmail.com). Attorney — California State Bar #289532. Currently at Axiom (benefit-eligible team member). Birthday: March 27. Based in the US but frequently travels Asia (Philippines, Japan/Kitakyushu/Fukuoka, South Korea/Incheon/Seoul, Thailand). Setting up a dedicated mini PC as an always-on Claude automation hub.

## People
| Who | Context |
|-----|---------|
| **Lewis Cimino** | lrcimino@yahoo.com — family (Chris sent "Ave Maria" email to him) |
| **Patrick Cimino** | Family — had a Microsoft Teams meeting 2026-03-07 |
| **Mark Lehtman** | Professional contact — phone meeting Aug 2025 |
| **Cyrus** | cyrusgsi@gmail.com — meeting via UC Denver Zoom, Sep 2025 |
| **Megan Walsh** | LinkedIn connection — Corporate Counsel, Secondment to Amazon |

## Professional
| Detail | Value |
|--------|-------|
| **Employer** | Axiom (axiomlaw.com) — flexible legal services |
| **Bar** | California State Bar #289532 (renewal payment initiated 2026-03-25) |
| **Role focus** | Corporate Counsel (LinkedIn alerts for associate/general counsel roles) |
| **Job search** | Active — interviewed with Roblox (Oct-Nov 2025), receiving LinkedIn/Indeed alerts for corporate counsel roles |
| **CLE** | Receives myLawCLE webinar notices (wire fraud, trusts) |

## Machine — "The Workhorse"
| Detail | Value |
|--------|-------|
| **Hardware** | Ace Magician AM06 Pro Mini PC |
| **OS** | Windows 11 |
| **Display** | Headless by default (iPad via Orion temporary only) — configured for monitor-less operation |
| **Remote** | RustDesk (password: CMCPassTemp7508!, password-only, unattended) + Tailscale (100.83.49.9) |
| **Local IP** | 192.168.7.25 (DHCP, gateway 192.168.7.1) |
| **ISP** | Xfinity (gateway at 10.0.0.1, no web admin — app only) |
| **Node** | v24.14.1 |
| **Git** | Installed via winget (2.53.0.2) |
| **Claude Code** | Installed globally via npm, Git Bash backend |
| **PowerShell** | ExecutionPolicy = RemoteSigned (CurrentUser) |

## Claude Code Toolkits
| Toolkit | Status |
|---------|--------|
| **GStack** | Installed (user's original choice) |
| **Superpowers** | Installed via plugin marketplace |
| **Everything-Claude-Code** | Installed via plugin marketplace |
| **Agent Teams** | Enabled (experimental flag in settings.json) |

## MCP Servers (Claude Code CLI)
- Context7 (live library docs)
- Sequential Thinking (structured reasoning)
- Playwright (browser automation)
- GitHub — NOT YET (needs GITHUB_TOKEN)

## Cowork Connectors
- Gmail (connected)
- Google Calendar (connected)
- Chrome extension (connected)
- Canva (connected) — design generation, export, editing
- Notion (connected) — knowledge base: "Rudy — Workhorse Command Center" with Improvement Log + Tool Inventory databases
- Google Drive (suggested — click Connect to replace OneDrive)

## Cowork Plugins
- Engineering (standups, code review, architecture, incidents, docs)
- Productivity (tasks, memory, dashboard)
- Operations (runbooks, vendor reviews, capacity, compliance)
- Plugin Management (create/customize plugins)
- Legal (suggested — contract review, NDA triage, legal briefs, risk assessment)

## Rudy — Family Assistant
| Detail | Value |
|--------|-------|
| **Email** | rudy.ciminoassist@gmail.com |
| **Password** | CMCPassTemp7508! (Google web login) |
| **2FA** | ON — phone SMS to (209) 324-6760. TOTP not yet added. |
| **App Password** | bviu yjdp tufr tnys (created 2026-03-26, needs IMAP enabled) |
| **Listener v2** | rudy-listener.py (IMAP IDLE + poll fallback, self-healing) |
| **Gmail API alt** | rudy-gmail-api.py (HTTPS-only, no IMAP needed) |
| **Command Runner v2** | rudy-command-runner.py (Cowork-to-Windows bridge, rename-before-execute, lock file) |
| **Stealth Browser** | scripts/rudy/rudy-stealth-browser.py |
| **Diagnostics** | scripts/rudy/rudy-diagnose.py |
| **Suno Music** | scripts/rudy/rudy-suno.py (AI music generation CLI + library) |
| **Startup** | workhorse-startup.bat (boots all services: RustDesk, Tailscale, Rudy) |
| **Health Check** | workhorse-healthcheck.ps1 (monitors all services every 5 min, auto-restarts, emails alerts) |
| **Logs** | rudy-logs/ |
| **Sessions** | data/sessions/ (saved browser cookies) |

### Permission Tiers
| Tier | Who | Can Do |
|------|-----|--------|
| **Full** | ccimino2@gmail.com | Everything — email, calendar, files, code, browser |
| **Family** | lrcimino@yahoo.com (Lewis) | Research, document creation, Q&A — no personal data access |
| **Unknown** | Anyone else | Gets polite decline + told to contact Chris |

To add family members: edit `FAMILY_ACCESS` set in `rudy-listener.py`

## Scheduled Tasks
| Task | Schedule |
|------|----------|
| daily-health-check | Every day at 6 AM |
| daily-research-feed | Every day at 6 AM — AI tools, legal tech, privacy, open-source model digest |
| weekly-dependency-audit | Sundays at 3 AM |
| weekly-maintenance | Sundays at 4 AM — temp cleanup, cache purge, log rotation, privacy drift check |
| morning-briefing | Every day at 7:30 AM |
| self-improvement | Mon/Wed/Fri at 10 AM — autonomous capability expansion, tool testing, integration checks |
| market-monitor | Weekdays 8 AM & 4 PM — stock/crypto watchlist, forex rates, price alerts |
| web-watcher | 7 AM / 1 PM / 7 PM daily — page change monitoring, job board scanning |
| knowledge-sync | 3 AM daily — semantic index of all new logs, reports, documents |
| email-health-check | 6 AM daily — test all email providers, report status |

### Auto-Recovery (Reboot Resilience)
| Layer | What | Trigger |
|-------|------|---------|
| **Layer 1: Windows Services** | RustDesk + Tailscale | Boot (auto-start + auto-restart on crash: 5s/10s/30s) |
| **Layer 2: Task Scheduler** | CommandRunner (logon+45s), Listener (logon+60s) | User logon |
| **Layer 2: Task Scheduler** | RustDeskConfigEnforce (password + config sync) | Boot + 30s |
| **Layer 3: Health Check** | workhorse-healthcheck.ps1 (SYSTEM) | Every 5 minutes |
| **Layer 4: Startup** | workhorse-startup.bat | Logon + 30s delay |

Boot sequence: Windows boots → auto-login → Services start (RustDesk, Tailscale) → 30s: RustDesk config enforced → 45s: CommandRunner starts → 60s: Listener starts → 5min: Health check begins continuous monitoring.

### Health Check System
- **Script**: workhorse-healthcheck.ps1 (runs as SYSTEM every 5 min)
- **Monitors**: RustDesk, Tailscale, CommandRunner, Listener, Internet
- **Auto-restarts** failed services immediately
- **Alerts**: Emails ccimino2@gmail.com after 3+ consecutive failures (via Rudy SMTP)
- **Alert file**: rudy-logs/ALERT-ACTIVE.txt (exists only when something is down)
- **State**: rudy-logs/healthcheck-state.json (tracks consecutive failures per service)
- **Log**: rudy-logs/healthcheck.log (auto-trimmed to 500 lines)

### Sub-Agent Architecture
Six agents manage the Workhorse autonomously. All agents are in `rudy/agents/`, write status to `rudy-logs/<agent>-status.json`, and are invocable via the command runner.

| Agent | Domain | Schedule | Key Responsibilities |
|-------|--------|----------|---------------------|
| **SystemMaster** | Health & Recovery | Every 5 min | Service monitoring, process restart, disk space, log rotation, network checks |
| **SecurityAgent** | Defensive Intelligence | Every 30 min | Network anomaly detection, file integrity, breach monitoring, event log analysis |
| **Sentinel** | Awareness & Growth | Every 15 min | Notices changes, spots opportunities, micro-improvements, tracks agent staleness |
| **TaskMaster** | Work Coordination | Daily 7:30 AM | Morning briefings, agent health monitoring, work queue management |
| **ResearchIntel** | Intelligence & Learning | Daily 6 AM + M/W/F 10 AM | RSS feed digests, capability inventory, tool recommendations |
| **OperationsMonitor** | Maintenance & Cleanup | Weekly Sun 4 AM | Temp cleanup, cache purge, result archiving, privacy drift detection, disk audit |

### Security Infrastructure
- **DNS Blocking**: 87,419 malware/tracking domains via hosts file (weekly refresh Sun 2 AM)
- **Breach Monitoring**: 3 family emails checked daily against Have I Been Pwned
- **Threat Intel**: 8 security RSS feeds (Krebs, CISA, NIST NVD, etc.) in ResearchIntel
- **File Integrity**: SHA-256 hashes of critical configs, checked every 30 min
- **Network Monitoring**: Active connection tracking, listening port baseline, anomaly detection
- **Event Log Analysis**: Failed logins, new accounts, service installations
- **Network Defense Module** (`rudy/network_defense.py`): 7-check defensive suite running every 30 min:
  1. ARP Spoofing Detection — gateway MAC lock, duplicate MAC detection, IP-MAC drift
  2. DNS Integrity Monitoring — cross-resolver verification against Cloudflare/Google/Quad9
  3. Outbound Traffic Profiling — new destination flagging, unusual port detection
  4. Rogue Device Detection — alerts on any new MAC appearing on the subnet
  5. SMB/Share Monitoring — detects lateral movement, unexpected file shares
  6. Registry/Config Drift — monitors startup keys, winlogon, security settings
  7. Listening Port Audit — detects new services/backdoors binding to ports
- **Presence Intelligence** (`rudy/presence_analytics.py`): Behavioral device identification via co-occurrence clustering, MAC OUI fingerprinting, activity pattern analysis. Dashboard: `presence-dashboard.jsx`
- **Wellness Monitor** (`rudy/wellness.py`): Family safety — inactivity detection, routine deviation, fall-risk mode
- **Threat Posture**: Family farm at 4101 Kansas Ave, Modesto — elevated counter-espionage stance (DA/attorney family, community-prominent). Unknown devices treated as hostile by default.
- **Planned Hardware**: Flipper Zero (RF scanning), IP security camera (motion detection via OpenCV), Aqara FP2 (fall detection)
- **Phase 2 Roadmap**: Proxmox VE → Security Onion + Kali + T-Pot VMs (see memory/projects/security-architecture.md)

**Admin Helper**: `rudy/admin.py` — self-elevates via PowerShell `Start-Process -Verb RunAs` (UAC prompts disabled, so elevation is silent). Use for schtasks, registry, service operations.

**Invoking agents from Cowork**: Deploy a `.py` file to `rudy-commands/` that imports and runs the agent:
```python
import sys; sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy.agents.system_master import SystemMaster
SystemMaster().execute(mode="full")
```

### Email Backend (Multi-Provider)
| Provider | Status | IMAP/SMTP | Priority |
|----------|--------|-----------|----------|
| **Gmail** | Locked out (recovery pending) | imap.gmail.com / smtp.gmail.com | 0 (primary) |
| **Zoho** | Active (rudy.ciminoassistant@zohomail.com / CMCPassTemp7508!) | imap.zoho.com / smtp.zoho.com | 1 (backup → acting primary) |
| **Outlook** | Not yet configured | imap-mail.outlook.com / smtp-mail.outlook.com | 2 (fallback) |

Module: `rudy/email_multi.py` — automatic failover chain, health tracking, rate limiting.
To configure backup: `mailer.configure_provider("zoho", "rudy.workhorse@zoho.com", "app_password")`

### API Server
- **Module**: `rudy/api_server.py` (FastAPI + uvicorn)
- **Port**: 8000 (Tailscale: http://100.83.49.9:8000)
- **Endpoints**: /health, /api/status, /api/devices, /api/security, /api/financial, /api/search, /webhook/*
- **API Key**: Auto-generated on first run, stored in `rudy-logs/api-server-config.json`
- **Start**: `python -m rudy.api_server` or deploy via command runner

### Rudy Troubleshooting
- Run `python rudy-diagnose.py` for full 8-point diagnostic report
- Run `python rudy-diagnose.py --fix` (as admin) to auto-fix DNS via hosts file
- Auth failures → check app password in rudy-totp-secret.json
- If IMAP stays broken, switch to Gmail API: `python rudy-gmail-api.py --setup`
- Command runner not executing? Check `rudy-command-runner.py` is running

### Stealth Browser Usage
```python
import sys; sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy_stealth_browser import create_stealth_page, save_session, google_sign_in
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    page, ctx, br = create_stealth_page(pw, session_name="google-rudy")
    google_sign_in(page, "rudy.ciminoassist@gmail.com", "CMCPassTemp7508!")
    save_session(ctx, "google-rudy")  # Reuse next time without re-login
    br.close()
```

### Installed Python Capabilities
python-pptx, python-docx, openpyxl, reportlab, PyPDF2, Pillow, svgwrite, qrcode, requests, beautifulsoup4, pandas, matplotlib, playwright, playwright-stealth, 2captcha-python, fake-useragent, pyotp, greenlet, moviepy, manim, opencv-python, imageio

### Installed Python Capabilities — Phase 2 (2026-03-26)
**AI/ML**: chromadb, sentence-transformers, langchain, langchain-community, openai, tiktoken, onnxruntime, scikit-learn, transformers, torch (CPU)
**NLP**: spacy (+ en_core_web_sm), textblob, nltk (+ vader/punkt/wordnet), sumy, rapidfuzz, chardet, ftfy, unidecode
**OCR/Docs**: easyocr, pdfplumber, camelot-py, docx2txt, striprtf, ebooklib, python-magic-bin
**Web Intel**: trafilatura, newspaper3k, goose3, html2text, selenium, undetected-chromedriver, cloudscraper, tldextract, python-whois, dnspython
**Audio/Voice**: openai-whisper, gtts, pyttsx3, pydub, soundfile, librosa, yt-dlp
**Financial**: yfinance, fredapi, alpha-vantage, forex-python
**Networking**: scapy, python-nmap, paramiko, speedtest-cli, shodan, phonenumbers, geopy, ipwhois
**Automation**: fastapi, uvicorn, websockets, aiohttp, celery, redis, apscheduler, python-crontab, watchfiles
**Visualization**: plotly, dash, seaborn, wordcloud, folium
**Data**: sqlalchemy, aiosqlite, peewee, tinydb, duckdb, pyarrow, xlrd
**Utilities**: humanize, tqdm, colorama, click, typer, pydantic, cachetools, retry, structlog, jsonschema

## Rudy Modules (rudy/ package)
| Module | What It Does |
|--------|-------------|
| **presence.py** | Network device scanning (ARP + ping sweep) |
| **presence_analytics.py** | Device classification, co-occurrence clustering, person inference |
| **network_defense.py** | 7-check defensive suite (ARP spoofing, DNS integrity, rogue devices, etc.) |
| **intruder_profiler.py** | Deep profiling of unknown devices, threat scoring, dossier generation |
| **travel_mode.py** | Network change detection, baseline archiving, first-contact recon |
| **movement_feed.py** | Unified activity timeline from all presence/threat/wellness data |
| **wellness.py** | Family safety — inactivity detection, routine deviation, fall-risk |
| **human_simulation.py** | Browser behavior simulation — Gaussian timing, Bezier mouse, keystroke dynamics, bot-detection failsafe |
| **email_multi.py** | Multi-provider email (Gmail/Zoho/Outlook) with automatic failover |
| **knowledge_base.py** | Semantic search engine — ChromaDB + sentence-transformers over all logs/docs |
| **web_intelligence.py** | Article extraction, page change monitoring, WHOIS/DNS, job board monitoring |
| **voice.py** | TTS (gTTS/pyttsx3), STT (Whisper), audio processing (pydub), media download (yt-dlp) |
| **ocr.py** | Image OCR (EasyOCR), PDF extraction (pdfplumber), universal document parser |
| **financial.py** | Market data (yfinance), portfolio tracking, price alerts, forex, watchlist |
| **nlp.py** | Sentiment analysis, entity extraction, text summarization, keyword extraction |
| **api_server.py** | FastAPI webhook receiver & REST API (port 8000, Tailscale accessible) |
| **local_ai.py** | Local LLM inference (Phi-3-Mini/Mistral-7B via llama-cpp-python) — offline reasoning, alert triage, ops decisions |
| **offline_ops.py** | Offline operations controller — connectivity monitoring, action queuing, AI-powered autonomous operation during outages |
| **phone_check.py** | Mobile device security scanning — iOS/Android malware/spyware detection, MVT integration, ADB/libimobiledevice |
| **photo_intel.py** | Photo intelligence — EXIF metadata extraction, GPS geocoding, timeline generation, duplicate detection, vacation reconstructor |
| **voice_clone.py** | Voice cloning — Coqui XTTS v2/OpenVoice/Bark, custom character voices, memorial voice recreation, batch script generation |
| **avatar.py** | Digital avatars — SadTalker talking-head, InsightFace face swap, Wav2Lip lip sync, MoviePy compositing, presenter videos |
| **obsolescence_monitor.py** | Capability audit — package freshness, tool landscape comparison, module health, usage tracking, upgrade recommendations |
| **admin.py** | Admin elevation helper (silent UAC bypass) |

## Creative Content Capabilities
| Service | Access Method | Status | Use Case |
|---------|--------------|--------|----------|
| **Canva** | MCP connector (Cowork) | Suggested — click Connect | Design, graphics, social media, presentations |
| **Hugging Face** | MCP connector (Cowork) | Suggested — click Connect | Image generation (Stable Diffusion, FLUX), text-to-image |
| **MidJourney** | Playwright via The Workhorse (web UI) | Chris has subscription | High-quality art (use stealth browser on midjourney.com, NOT Discord) |
| **Suno** | rudy-suno.py on The Workhorse | Chris has subscription — needs cookie/key setup | AI music generation (songs for niece/nephew) |
| **Replicate** | MCP server (Claude Code CLI) | Needs API token | Run any open-source AI model (SDXL, FLUX, etc.) |
| **Local generation** | Python on The Workhorse | Ready now | SVG art, matplotlib charts, Pillow image manipulation |

### Creative Workflow for Kids Content
1. **Stories**: Claude writes them natively → export as illustrated .docx or .pptx
2. **Art**: Hugging Face MCP or Replicate for image generation, Canva for polished designs
3. **Music**: Suno API for custom songs (birthday songs, lullabies, fun tunes)
4. **Coloring pages**: SVG generation via Python (svgwrite) on The Workhorse
5. **Videos/animations**: MoviePy compositing (stitch art + music → MP4), Canva templates, Manim for educational animations
6. **Video generation**: No local GPU — use Replicate/Hugging Face APIs for AI video (Wan 2.2, CogVideoX, AnimateDiff), MoviePy for compositing locally

## Automation & Integration
| Platform | Status | What It Does |
|----------|--------|-------------|
| **Zapier** | Connected ✓ | Cross-app automation (5000+ apps), triggers, webhooks |
| **Make (Integromat)** | Ready to connect | Visual workflow automation, more complex logic than Zapier |
| **n8n** | Ready to connect | Self-hostable workflow automation, can run on The Workhorse |
| **Command Runner** | Live ✓ | Cowork → Windows bridge (execute .py/.cmd/.ps1 on The Workhorse) |

## Connectors Available (Not Yet Connected)
| Connector | Why Useful |
|-----------|-----------|
| Google Drive | File storage/sharing — replaces OneDrive (Chris prefers Google ecosystem) |
| Notion | Knowledge base for Rudy — persistent memory, project docs, wiki |
| Hugging Face | Access thousands of AI models for image/text/audio generation |
| Make | Advanced workflow automation (more complex than Zapier) |
| n8n | Self-hosted workflow automation (can run on The Workhorse) |

## Rudy Service Accounts
All registered with `rudy.ciminoassistant@zohomail.com` / `CMCPassTemp7508!`

| Service | Status | API Key / Token | Unlocks |
|---------|--------|----------------|---------|
| **GitHub** | Active ✓ | Needs personal access token generated | MCP server, repos, version control |
| **HuggingFace** | Active ✓ | Needs API token from settings | Image gen, model downloads, Cowork MCP |
| **Docker Hub** | Active ✓ | CLI login via `docker login` | Containers, Security Onion, sandboxing |
| **Zoho Mail** | Active ✓ | SMTP/IMAP with password | Email backend (acting primary) |
| **PyPI** | Active ✓ | Needs API token from settings | Package publishing |
| **Discord** | Not yet | — | MidJourney web access, communities |
| **Replicate** | Not yet | — | Pay-per-use AI model API |
| **Shodan** | Not yet | — | Network perimeter intelligence |
| **2captcha** | Not yet | — | CAPTCHA solving for automation |
| **Cloudflare** | Not yet | — | DNS, tunnels, Zero Trust |
| **HIBP API** | Not yet | — | Breach monitoring for family emails |

## Pending Setup
- **GitHub token**: Classic PAT configured (repo, workflow, gist, read:user) — expires 2026-04-25. Env var: GITHUB_TOKEN
- **HuggingFace token**: Write token configured. Username: Rudy-C. Env vars: HF_TOKEN, HUGGING_FACE_HUB_TOKEN
- **Docker CLI auth**: Run `docker login` on The Workhorse with Rudy credentials
- **Rudy Gmail recovery**: Account locked out (too many auth attempts 2026-03-26). If it doesn't recover, create backup account
- **Rudy TOTP**: Add authenticator app so Rudy can handle 2FA programmatically via pyotp
- **Suno setup**: Get Suno cookie or API key → run `python rudy-suno.py setup` on The Workhorse
- **Google Drive MCP**: Click Connect when prompted (replaces OneDrive)
- **Hugging Face MCP**: Click Connect when prompted (image generation)
- **Notion setup**: Connected — create Rudy knowledge base workspace structure
- **Legal plugin**: Install when prompted (contract review, NDA triage, legal briefs)
- BIOS: AC Power Recovery → Power On (no USB keyboard; using smart plug workaround)
- Smart plug for remote power cycling
- Remaining accounts: Discord, Replicate, Shodan, 2captcha, Cloudflare, HIBP, PyPI

## Local AI (Offline Intelligence)
- **Module**: `rudy/local_ai.py` + `rudy/offline_ops.py`
- **Runtime**: llama-cpp-python (GGUF format, CPU-only inference)
- **Primary model**: Phi-3-Mini-4K-Instruct Q4 (2.3GB, ~5-6 tok/s) — fast, good for classification/triage
- **Heavy model**: Mistral-7B-Instruct Q4_K_M (4.4GB, ~2-3 tok/s) — smarter, for complex reasoning
- **Emergency model**: TinyLlama-1.1B Q4 (0.7GB, ~15-20 tok/s) — ultra-fast fallback
- **Models dir**: `rudy-data/models/`
- **Capabilities**: Alert triage, ops decisions, text summarization, intent classification, offline conversation
- **Offline controller**: Detects outages, switches to local AI, queues outbound actions, replays on recovery
- **Usage**: `from rudy.local_ai import OfflineAI; ai = OfflineAI.get(); ai.ask("What should I do?")`

## Remote Access Hardening
Applied 2026-03-26 via harden-remote.py (28/28 succeeded):
- **UAC**: Consent prompts disabled (ConsentPromptBehaviorAdmin=0, PromptOnSecureDesktop=0) — no more screen dimming that blocks RustDesk
- **Auto-login**: AutoAdminLogon=1, DefaultUserName=C, DefaultPassword set — boots straight to desktop
- **Lock screen**: Disabled entirely (NoLockScreen, DisableCAD, InactivityTimeoutSecs=0, no screensaver)
- **Power**: Never sleep, never hibernate, never turn off display, Connected Standby disabled
- **Headless display**: GPU TDR disabled, DWM compositor forced on, monitor simulation enabled, Fast Startup off
- **RustDesk**: Both service and user configs have verification-method=use-permanent-password, approval-mode=password
- **RECOMMENDED**: Buy HDMI dummy plug ($5-10) for bulletproof headless operation (Amazon: "HDMI dummy plug display emulator 4K")

## Privacy & Security Hardening
Applied 2026-03-26 via harden-privacy.py (ran as admin, 45/49 succeeded):
- Telemetry disabled (Security level only), advertising ID off, activity history off
- Cortana/Copilot/Bing web search disabled, silent app installs blocked
- Location/mic/camera default deny, OneDrive sync disabled
- P2P Windows Update delivery off, Wi-Fi Sense disabled
- Windows Defender hardened: PUA protection, network protection, Block at First Sight
- 22 bloatware apps removed (Xbox, Solitaire, Bing, Clipchamp, Teams, Phone Link, etc.)
- Weekly maintenance checks for privacy drift (Windows Update can reset settings)
- Smart App Control: OFF (was blocking unsigned Python scripts; one-way disable, cannot re-enable)
- SmartScreen: OFF (Explorer, Edge, app install control all disabled)

### Installed Python Capabilities
python-pptx, python-docx, openpyxl, reportlab, PyPDF2, Pillow, svgwrite, qrcode, requests, beautifulsoup4, pandas, matplotlib, playwright, playwright-stealth, 2captcha-python, fake-useragent, pyotp, greenlet, moviepy, manim, opencv-python, imageio, psutil, rich, watchdog, schedule, httpx, tenacity, jinja2, arrow, tabulate, python-dotenv, pyyaml, feedparser, markdownify, readability-lxml, cryptography, black, ruff
(+ Phase 2 packages listed above under Stealth Browser section)

## Research & Intelligence
| Component | What It Does |
|-----------|-------------|
| **workhorse-research-feed.py** | Aggregates 20+ RSS feeds (AI, legal tech, privacy, open-source models) |
| **workhorse-subscribe.py** | Manage monitored feeds (add/remove/validate) |
| **daily-research-feed** | Scheduled task: digest at 6 AM daily |
| **self-improvement** | Scheduled task: autonomous capability expansion Mon/Wed/Fri 10 AM |
| **Feed config** | rudy-logs/research-feeds.json |
| **Digests** | rudy-logs/research-digest-[date].md |

## Desktop Directory Structure
```
C:\Users\C\Desktop\
├── CLAUDE.md              — Memory / config (this file)
├── TASKS.md               — Task tracking
├── rudy-command-runner.py — Command runner v2 (stays at root, referenced by tasks)
├── rudy-listener.py       — Email listener (stays at root, referenced by tasks)
├── workhorse-startup.bat  — Boot sequence (stays at root, referenced by tasks)
├── workhorse-healthcheck.ps1 — Health check (stays at root, runs as SYSTEM)
├── enforce-rustdesk-config.ps1 — RustDesk config enforcement (boot task)
├── scripts/
│   ├── rudy/              — Rudy utility scripts (diagnose, suno, stealth, etc.)
│   ├── workhorse/         — System management (maintenance, research feed, watchdog)
│   └── setup-archive/     — Completed one-time setup scripts
├── docs/                  — Documentation, guides, dashboards
├── rudy-commands/         — Command runner watch directory
│   └── archive/           — Old results and scripts
├── rudy-logs/             — All logs, state files, digests
├── rudy/                  — Rudy Python package
│   ├── agents/            — Sub-agent modules (system_master, operations_monitor, research_intel, task_master)
│   ├── admin.py           — Admin elevation helper (silent UAC bypass)
│   └── config/            — Agent configuration (agents-config.json)
├── memory/                — Knowledge base (people, projects, glossary)
├── data/
│   ├── sessions/          — Saved browser sessions
│   └── browser-profile/   — Stealth browser profile
├── workhorse/             — System startup scripts
├── user-apps/             — Pre-configured launcher scripts (.cmd) for end-user tools
└── (audit-reports, briefings, health-reports, projects) — Work output dirs
```

## User Apps
Pre-configured launcher scripts in `user-apps/`. Double-click any `.cmd` to run.

| App | File | What It Does |
|-----|------|-------------|
| **Phone Check** | phone-check.cmd | Plug in phone via USB → auto-scan for malware/spyware |
| **Photo Timeline** | photo-timeline.cmd | Point at photo folder → generates vacation timeline |
| **Voice Clone** | voice-clone.cmd | Clone a voice from audio → generate speech in that voice |
| **Avatar Creator** | avatar-creator.cmd | Create talking-head video from photo + audio |
| **Quick Scan** | quick-scan.cmd | Fast PC security check (services, ports, processes) |
| **Market Check** | market-check.cmd | Watchlist prices + forex rates |

## Cowork Session Monitoring Rules
These rules apply to EVERY Cowork session. Claude must follow them proactively without Chris asking.

### Context Window Management
- **50% Warning**: When the conversation reaches roughly 50% of the context window (estimated by message count, tool calls, and content volume — typically around 30-40 substantive exchanges or heavy tool use), proactively warn Chris: "We're approaching the halfway point of this session's context. I recommend we start a new thread soon to maintain quality."
- **70% Handoff**: At ~70% context usage, STOP new work and draft a continuation prompt. Format:
  ```
  CONTINUATION PROMPT (copy into new thread):
  ---
  Continue building Rudy/Workhorse. Last session accomplished: [bullet summary].
  Next priorities: [explicit list]. Key context: [any critical state].
  Read CLAUDE.md for full system state.
  ---
  ```
- **Signs of context pressure**: Repeating information already covered, forgetting earlier decisions, generating lower-quality code, losing track of file states. If any of these appear, trigger the handoff immediately.

### Session Hygiene
- **Always read CLAUDE.md first** in a new session before doing any work
- **Update CLAUDE.md at the end of every session** with: new modules built, config changes, pending items, any state that the next session needs
- **Never leave orphaned state**: If a deploy script was sent to the command runner but results aren't confirmed, note it in Pending Setup
- **Summarize before handoff**: When recommending a new thread, include a 3-5 bullet recap of what was accomplished and what's next

### Quality Gates
- **Syntax-check all Python** before telling Chris it's done: `python3 -m py_compile <file>`
- **Verify file writes landed**: After writing to the Desktop folder, confirm the file exists and has reasonable size
- **Don't stack too many deploy scripts**: The command runner processes sequentially. Deploy at most 2-3 scripts before waiting for results.
- **Test imports mentally**: Before writing a module that imports from `rudy.X`, verify `rudy/X.py` actually exists

### Communication Standards
- **Be concise in status updates**: Chris wants results, not play-by-play. "Built phone_check.py — 600 lines, 4 classes, covers iOS+Android+MVT. Deployed." is better than a paragraph.
- **Flag blockers immediately**: Don't silently skip something that failed. If a tool is missing or a deploy didn't work, say so.
- **Proactive suggestions**: At the end of each major task, suggest 1-2 next steps Chris might not have thought of
- **Birthday note**: Chris's birthday is March 27 — if it's that date, wish him happy birthday before diving into work

### Security Discipline
- **Never echo passwords/keys in output** unless Chris specifically asks for them
- **Credential rotation reminder**: If a session involves creating new credentials, remind Chris to rotate any that were exposed in chat
- **Sanitize deploy scripts**: Command runner scripts that touch credentials should clean up after themselves


- Wants maximum agency — proactive, autonomous operation
- "Turbocharge" mindset — always looking for new tools, not rote recitation
- Mixed/various coding projects (no single language)
- Prefers things that just work over manual configuration steps
- Headless by default — iPad/Orion is temporary, HDMI dummy plug recommended
- Xfinity ISP — router admin only via app, not web
- Tailscale preferred over static local IP for remote access
- Privacy-conscious — balanced against workflow needs (no unnecessary tracking/cookies/bloatware)
- Prefers Google ecosystem over Microsoft (Drive > OneDrive, Gmail > Outlook)
- Wants Claude to be self-improving and proactive, not idle between prompts
- "Don't reinvent the wheel" — use existing tools, plugins, connectors before building custom

## Next Sprint
**GitHub Integration** — see `sprint-github-integration.md` on Desktop for full plan.
Priority: verify deploy results → confirm GitHub PAT → init repo → push codebase → add GitHub MCP → CI/CD → wire agents → test all modules.

## Pending Deploy Verification (2026-03-26)
These scripts were sent to the command runner but results were NOT confirmed before session ended:
- `configure-tokens.py` — sets GITHUB_TOKEN + HF_TOKEN as env vars
- `install-essentials.py` — Ollama, Sysinternals, Nmap, gh CLI, YARA, LangChain
- `configure-new-accounts.py` — Git identity, Docker login, confirmation email
- `deploy-creative-suite.py` — Coqui TTS, Bark, InsightFace, ONNX
- `deploy-phone-photo-modules.py` — MVT, imagehash, geopy

Check `rudy-commands/archive/` for `.result` files on next session.

## Key Constraints
- No physical keyboard/monitor — headless operation, all input via RustDesk remote
- RustDesk must stay in password-only mode (no manual accept) — UAC prompts disabled to prevent lockout
- Machine must auto-recover from power loss (auto-login + Task Scheduler + watchdog; BIOS AC recovery still pending)
- Scripts on Desktop at C:\Users\C\Desktop\
- Display adapter must stay active even without physical monitor (registry hardened, HDMI dummy plug recommended)
