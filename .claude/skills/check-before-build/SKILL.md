---
name: check-before-build
description: "Query the Workhorse capability manifest before writing custom code. MANDATORY before creating any new Python file, shell script, or automation. Invoke this skill when you're about to write a new script, module, or tool — or when you catch yourself thinking 'I need to build X.' Also use when the user asks 'do we already have something for...', 'what tools do we have for...', or 'is there a module that...'. This skill exists because Claude has a strong tendency to write fresh code for problems already solved by the 100+ installed packages, 31+ rudy modules, 30+ Cowork skills, 5 MCP connectors, and 6 sub-agents on this system."
---

# Check Before Build — Capability Lookup

You're about to write custom code. Stop. Search first.

The Workhorse has an extensive toolkit that is routinely forgotten or overlooked. This skill forces a structured lookup before any new code is written, because the best code is code you don't have to write.

## When This Fires

- You're about to create a new `.py`, `.ps1`, `.cmd`, or `.sh` file
- You're writing more than ~30 lines of code for a task that sounds like it could be generic
- The user asks "do we have…", "is there a tool for…", "can Rudy already…"
- You find yourself importing a library to build something from scratch

## Step 1: Check the Capability Manifest

Read `rudy-logs/capability-manifest.json` from the Desktop mount. This is a machine-readable index of everything available on the Workhorse, generated hourly by the Sentinel agent. It contains:

- All `rudy/` modules and what they do
- All installed pip packages
- All Cowork skills (with trigger descriptions)
- All MCP connectors
- All scheduled tasks
- All sub-agents
- All user-apps

Search this manifest for keywords related to what you're about to build. Be creative with synonyms — if you need "text extraction," also check for "OCR," "parse," "pdf," "scrape," "extract."

If the manifest doesn't exist yet (Sentinel hasn't run), fall back to Steps 2-4.

## Step 2: Check Rudy Modules

These are purpose-built modules in `rudy/` on the Desktop. Key ones people forget:

| Need | Module | What It Already Does |
|------|--------|---------------------|
| Email | `email_multi.py` | Multi-provider send with failover (Gmail/Zoho/Outlook) |
| Web scraping | `web_intelligence.py` | Article extraction, page monitoring, WHOIS, job boards |
| OCR / PDF text | `ocr.py` + `tools/ocr_fallback.py` | EasyOCR, pdfplumber, universal doc parser |
| Screenshots | `tools/screenshot_reader.py`, `tools/screen_capture.py` | Playwright + desktop capture with OCR |
| Voice / audio | `voice.py` | TTS, STT (Whisper), audio processing, media download |
| Network scan | `presence.py`, `network_defense.py` | ARP sweep, 7-check defense suite |
| Market data | `financial.py` | yfinance, forex, portfolio, price alerts |
| NLP | `nlp.py` | Sentiment, entity extraction, summarization, keywords |
| Semantic search | `knowledge_base.py` | ChromaDB + sentence-transformers over all docs |
| Local AI | `local_ai.py` | Ollama / llama-cpp inference, offline reasoning |
| Device security | `phone_check.py` | iOS/Android malware scan |
| Photo analysis | `photo_intel.py` | EXIF, GPS, timeline, duplicates |
| VPN | `vpn_manager.py` | ProtonVPN control with safety interlocks |
| Git ops | `integrations/github_ops.py`, `integrations/git_auto.py` | Issue filing, PR management, auto-push |
| Admin tasks | `admin.py` | Silent UAC elevation for system operations |
| Browser automation | `human_simulation.py` | Anti-detection browsing (Gaussian timing, Bezier mouse) |

## Step 3: Check Cowork Skills and Connectors

Before building custom, remember you have live API access:

**Connectors** (use directly, no code needed):
- **Gmail** — search, read, draft, labels for ccimino2@gmail.com
- **Google Calendar** — events, free time, RSVP
- **Notion** — pages, databases, persistent memory
- **Canva** — design generation, export, editing
- **Chrome** — navigate, read pages, fill forms, execute JS

**Skills** (invoke via Skill tool):
- docx, pptx, xlsx, pdf — document creation/manipulation
- schedule — create recurring tasks
- 10 engineering skills (code review, architecture, debugging, etc.)
- 9 operations skills (runbooks, status reports, vendor reviews, etc.)
- 4 productivity skills (tasks, memory, dashboard)
- 9 legal skills (contract review, NDA triage, briefs, etc.)

## Step 4: Check Installed Packages

The Workhorse has 100+ pip packages across AI/ML, NLP, web intel, audio, financial, networking, and automation. Before `pip install`ing anything, check if it's already there. Common ones people forget:

- **trafilatura** / **newspaper3k** / **goose3** — article extraction (don't write a custom scraper)
- **rapidfuzz** — fuzzy string matching (don't write a custom matcher)
- **chromadb** + **sentence-transformers** — vector search (don't build custom embeddings)
- **plotly** / **dash** / **seaborn** — visualization (don't write matplotlib from scratch)
- **feedparser** — RSS parsing (don't write a custom XML parser)
- **humanize** — human-readable formatting (don't write custom formatters)
- **pdfplumber** / **camelot-py** — PDF table extraction (don't regex PDFs)
- **yfinance** — market data (don't scrape finance sites)

## Step 5: Decision

After searching, one of three things is true:

1. **Exact match exists** — Use it. Import the module, invoke the skill, or call the connector. Done.
2. **Partial match exists** — Extend or wrap the existing tool. Write a thin adapter, not a new system.
3. **Nothing fits** — Now you may write custom code. But document why in a brief comment at the top: `# No existing tool covers X because Y. Checked: manifest, rudy/Z.py, skill-W.`

The goal is not to prevent all new code — it's to prevent *redundant* code. The Workhorse's power comes from its integrated toolkit, and every duplicate weakens that integration.
