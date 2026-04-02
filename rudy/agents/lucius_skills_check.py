"""
Lucius Skills Check — ADR-004 Toolkit: recommend relevant tools for a task.

Extracted from lucius_fox.py (Session 72, ADR-005 Phase 2b).
Maps keywords to available tools across connectors, skills, plugins, and modules.

Usage:
    from rudy.agents.lucius_skills_check import skills_check, CAPABILITY_INDEX
    result = skills_check(task="send an email with a PDF attachment")
    print(result["summary"])
"""

import logging

log = logging.getLogger("lucius.skills_check")

# The Capability Index — maps keywords to available tools.
# Structured as: category -> list of (keywords, tool_name, tool_type, description)

CAPABILITY_INDEX = {
    "connectors": [
        (["email", "gmail", "inbox", "draft", "message", "send email"],
         "Gmail MCP", "connector", "Search/read/draft emails for ccimino2@gmail.com"),
        (["calendar", "schedule", "meeting", "event", "free time", "rsvp", "availability"],
         "Google Calendar MCP", "connector", "List/create/update events, find free time"),
        (["notion", "knowledge base", "database", "sprint log", "improvement log"],
         "Notion MCP", "connector", "Search/create/update pages & databases"),
        (["canva", "design", "graphic", "social media", "poster", "banner"],
         "Canva MCP", "connector", "Generate/edit/export designs"),
        (["chrome", "browser", "web page", "scrape", "form", "screenshot", "navigate"],
         "Chrome Extension", "connector", "Navigate pages, read content, execute JS"),
        (["google drive", "drive", "file search", "document retrieval"],
         "Google Drive MCP", "connector", "Search files, fetch content"),
        (["github", "repo", "pull request", "issue", "commit", "pr"],
         "GitHub MCP", "connector", "Repo operations, PRs, issues, file contents"),
    ],
    "cowork_skills": [
        (["word", "docx", "report", "memo", "letter", "document"],
         "docx", "skill", "Create/edit Word documents"),
        (["powerpoint", "pptx", "presentation", "slides", "deck"],
         "pptx", "skill", "Create/edit PowerPoint presentations"),
        (["excel", "xlsx", "spreadsheet", "budget", "data table", "financial model"],
         "xlsx", "skill", "Create/edit Excel spreadsheets"),
        (["pdf", "form", "extract", "merge", "split"],
         "pdf", "skill", "Create/extract/merge/split PDFs"),
        (["schedule", "recurring", "cron", "every day at", "scheduled task"],
         "schedule", "skill", "Create scheduled tasks"),
        (["research", "brief", "investigate", "deep dive", "synthesis"],
         "research-brief", "skill", "Deep research with source synthesis"),
        (["code", "script", "run", "execute", "prototype", "algorithm"],
         "code-runner", "skill", "Execute code snippets in sandbox"),
    ],
    "plugins": [
        (["standup", "code review", "architecture", "incident", "debug",
          "deploy", "testing", "tech debt", "system design", "documentation"],
         "Engineering plugin", "plugin",
         "standups, code-review, architecture, incidents, docs"),
        (["task", "memory", "dashboard", "productivity"],
         "Productivity plugin", "plugin",
         "tasks, memory, dashboard"),
        (["runbook", "vendor", "capacity", "compliance", "process", "status report"],
         "Operations plugin", "plugin",
         "runbooks, vendor reviews, capacity, compliance"),
        (["contract", "nda", "legal", "risk assessment", "compliance check"],
         "Legal plugin", "plugin",
         "contract review, NDA triage, legal briefs, risk assessment"),
    ],
    "rudy_modules": [
        (["presence", "device", "network scan", "arp", "wifi"],
         "rudy/presence.py + presence_analytics.py", "module",
         "Network device scanning and classification"),
        (["security", "threat", "defense", "intrusion", "anomaly"],
         "rudy/network_defense.py + security_agent.py", "module",
         "7-check defensive suite, threat detection"),
        (["email", "send", "smtp", "imap", "mail backend"],
         "rudy/email_multi.py", "module",
         "Multi-provider email with automatic failover"),
        (["ai", "llm", "local", "offline", "ollama", "inference"],
         "rudy/local_ai.py + offline_ops.py", "module",
         "Local LLM inference (Ollama/llama-cpp), offline ops"),
        (["voice", "tts", "speech", "whisper", "audio", "clone"],
         "rudy/voice.py + voice_clone.py", "module",
         "TTS, STT, voice cloning"),
        (["ocr", "image text", "pdf extract", "document parse"],
         "rudy/ocr.py", "module",
         "Image OCR (EasyOCR), PDF extraction (pdfplumber)"),
        (["nlp", "sentiment", "entity", "summarize", "keyword"],
         "rudy/nlp.py", "module",
         "Sentiment analysis, entity extraction, summarization"),
        (["web", "scrape", "article", "page change", "whois"],
         "rudy/web_intelligence.py", "module",
         "Article extraction, page monitoring, WHOIS/DNS"),
        (["financial", "market", "stock", "crypto", "forex", "portfolio"],
         "rudy/financial.py", "module",
         "Market data (yfinance), portfolio tracking, alerts"),
        (["phone", "mobile", "malware", "spyware", "forensic"],
         "rudy/phone_check.py", "module",
         "Mobile device security scanning"),
        (["photo", "exif", "gps", "timeline", "image metadata"],
         "rudy/photo_intel.py", "module",
         "EXIF metadata, GPS extraction, timeline"),
        (["usb", "quarantine", "device fingerprint"],
         "rudy/usb_quarantine.py", "module",
         "USB quarantine protocol"),
        (["surveillance", "camera", "motion", "video"],
         "rudy/surveillance.py", "module",
         "Video camera integration, motion detection"),
        (["vpn", "proton", "privacy", "tunnel"],
         "rudy/vpn_manager.py", "module",
         "ProtonVPN control, session timeouts"),
        (["avatar", "face swap", "talking head", "video presenter"],
         "rudy/avatar.py", "module",
         "Digital avatars, face swap, talking-head video"),
        (["knowledge", "semantic search", "chromadb", "index"],
         "rudy/knowledge_base.py", "module",
         "Semantic search over all Rudy data"),
        (["wellness", "family safety", "inactivity", "fall risk"],
         "rudy/wellness.py", "module",
         "Family safety monitoring"),
        (["travel", "network change", "baseline", "portable"],
         "rudy/travel_mode.py", "module",
         "Portable network intelligence"),
        (["find my", "location", "geofence", "icloud"],
         "rudy/find_my.py", "module",
         "iCloud location monitoring for family safety"),
        (["pentest", "penetration", "vulnerability", "port scan", "nmap"],
         "rudy/pentest.py", "module",
         "Penetration testing orchestration"),
        (["handoff", "continuity", "session", "bootstrap"],
         "rudy/workflows/handoff.py", "module",
         "Automated session handoff protocol"),
        (["audit", "quality", "lint", "governance", "registry"],
         "rudy/agents/lucius_fox.py", "module",
         "Code audits, dependency governance, quality gate"),
        (["gate", "mcp", "circuit breaker", "session start"],
         "rudy/agents/lucius_gate.py", "module",
         "Session governance with MCP circuit breakers"),
    ],
}


def skills_check(task: str) -> dict:
    """Recommend relevant tools for a task.

    ADR-004 Toolkit: At session start or mid-session, list relevant
    skills, connectors, modules, and plugins for the current task.

    Args:
        task: Natural language description of the task or goal.

    Returns:
        dict with 'recommendations', 'summary', and 'total_matches'.
    """
    if not task:
        log.warning("skills_check called with empty task")
        return {
            "recommendations": [],
            "summary": "No task provided. Pass task='describe your task' to get recommendations.",
            "total_matches": 0,
        }

    task_lower = task.lower()
    task_words = set(task_lower.split())

    recommendations = []
    seen_tools = set()

    for category, entries in CAPABILITY_INDEX.items():
        for keywords, tool_name, tool_type, description in entries:
            if tool_name in seen_tools:
                continue

            score = 0
            matched_keywords = []
            for kw in keywords:
                if kw in task_lower:
                    score += 2  # phrase match = strong signal
                    matched_keywords.append(kw)
                elif any(w in task_words for w in kw.split()):
                    score += 1  # word overlap = weaker signal
                    matched_keywords.append(kw)

            if score > 0:
                seen_tools.add(tool_name)
                recommendations.append({
                    "tool": tool_name,
                    "type": tool_type,
                    "category": category,
                    "description": description,
                    "score": score,
                    "matched": matched_keywords,
                })

    recommendations.sort(key=lambda r: r["score"], reverse=True)

    if recommendations:
        top = recommendations[:5]
        summary_parts = [
            f"Found {len(recommendations)} relevant tool(s) for: \"{task}\""
        ]
        summary_parts.append("")
        summary_parts.append("Top recommendations:")
        for r in top:
            summary_parts.append(
                f"  [{r['type'].upper()}] {r['tool']} -- {r['description']}"
            )
        summary_parts.append("")
        summary_parts.append(
            "REMINDER: Check these BEFORE writing custom code (HARD RULE)."
        )
        summary = "\n".join(summary_parts)
    else:
        summary = (
            f"No existing tools matched for: \"{task}\". "
            f"If this is a generic capability, search the MCP registry and "
            f"pip packages before building custom."
        )

    log.info(f"skills_check: {len(recommendations)} matches for '{task}'")

    return {
        "task": task,
        "recommendations": recommendations,
        "summary": summary,
        "total_matches": len(recommendations),
    }
