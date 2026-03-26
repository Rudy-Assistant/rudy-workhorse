# Machine Setup History

## Session: 2026-03-25 (Initial Setup)

### What was done
1. Created and ran `setup-mini-pc.ps1` (as admin via RUN-SETUP.bat):
   - High Performance power plan, all timeouts to Never, hibernate off
   - Lock screen disabled (NoLockScreen registry)
   - Auto-login configured
   - Windows Update forced restarts disabled
   - USB selective suspend disabled
   - RDP enabled as backup
   - RustDesk added to startup
   - Daily health-check Windows scheduled task

2. Created and ran `install-claude-toolkits.ps1`:
   - MCP servers: Context7, Sequential Thinking, Playwright
   - Plugin marketplaces added: Superpowers, Everything-Claude-Code
   - Agent Teams enabled in settings.json

3. Manual installs during session:
   - PowerShell execution policy → RemoteSigned
   - Git for Windows via winget
   - Claude Code CLI via npm
   - Superpowers plugin via `/plugin install`
   - Everything-Claude-Code plugin via `/plugin install`

4. RustDesk fix:
   - Added `approval-mode = 'password'` to RustDesk2.toml
   - Config at: %APPDATA%\RustDesk\config\RustDesk2.toml

5. Cowork setup:
   - Gmail + Google Calendar MCP connectors
   - Chrome extension connected
   - Engineering, Productivity, Operations, Plugin Management plugins
   - Two scheduled tasks (health check, dep audit)
   - Productivity system initialized (TASKS.md, CLAUDE.md, memory/)

### Files on Desktop
- `setup-mini-pc.ps1` — Windows system config script
- `install-claude-toolkits.ps1` — Claude Code toolkit installer
- `RUN-SETUP.bat` — one-click launcher for both
- `claude-code-toolkit-guide.md` — reference doc
- `TASKS.md` — task tracker
- `CLAUDE.md` — working memory
- `dashboard.html` — productivity dashboard
- `memory/` — deep memory directory

### Key paths
- Claude Code config: %APPDATA%\claude\settings.json
- Claude Code skills: %APPDATA%\claude\skills\
- MCP servers: %APPDATA%\claude\mcp_servers.json
- RustDesk config: %APPDATA%\RustDesk\config\RustDesk2.toml
- Cowork scheduled tasks: C:\Users\C\Documents\Claude\Scheduled\
