# Deploy Results (Verified 2026-03-26)

| Script | Result | Key Notes |
|--------|--------|-----------|}
| **configure-tokens** | 11/11 ✅ | GitHub PAT + HF token set, Git identity configured |
| **install-essentials** | 9/15 ⚠️ | Ollama FAILED, gh CLI installed later (v2.88.1), Sysinternals/YARA/LangChain OK |
| **configure-new-accounts** | 6/7 ⚠️ | Docker login failed (Docker not installed), Git + HF OK |
| **deploy-creative-suite** | 8/10 ⚠️ | Coqui TTS + InsightFace FAILED, Bark + ONNX OK |
| **deploy-phone-photo** | 7/10 ⚠️ | ADB + libimobiledevice need Chocolatey, MVT/imagehash/geopy OK |
| **setup-github-mcp** | 2/2 ✅ | GitHub MCP in ~/.claude.json + Desktop/.claude/mcp.json |
| **test-and-audit** | 40/44 ✅ | 27/27 imports, 43/44 syntax, 5/5 functional, audit complete |
| **install-langgraph** | 2/2 ✅ | langgraph + checkpoint-sqlite installed, all 3 imports verified |
| **rustdesk-upgrade** | ✅ | v1.4.1 → v1.4.6 via GitHub direct download (winget index stale) |
| **zoho-imap** | 8/9 ⚠️ | Playwright signed in + navigated to settings, IMAP toggle not found (SPA timing) — v2 deployed |
| **git-status-push** | Pending | Deployed, awaiting result |
