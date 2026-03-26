# Claude Code Power Toolkit Guide — March 2026

Your mini PC is the hardware. This guide covers the software stack to make it a turbocharged autonomous coding machine.

---

## Tier 1: Skill Packs (You Already Have GStack — Here's What Else)

### GStack (installed)
Garry Tan's role-based system — 28 slash commands mapping to engineering roles (CEO, staff engineer, QA lead, security officer, etc.). The persistent headless Chromium daemon is the killer feature for visual QA on web projects.

**Tip for your setup:** GStack's Chromium daemon is designed to stay warm. On your always-on mini PC, cold starts (3-5s) only happen once after reboot. After that, tool calls resolve in ~100-200ms. Make sure RustDesk's unattended mode doesn't interfere with the Chromium session — if it does, run Chromium on a virtual display (`--headless=new` flag).

### Superpowers (strongly recommended as a complement)
106K stars. By Jesse Vincent. Where GStack gives you *roles*, Superpowers gives you *discipline* — a rigid 7-phase TDD-first pipeline: brainstorm → plan → test → implement → review. It uses psychological guardrails to prevent Claude from rationalizing shortcuts.

**Why both?** They solve different problems at different lifecycle stages. Use GStack's `/plan-ceo-review` and `/office-hours` for the "what are we building?" phase, then Superpowers' TDD pipeline for the "how do we build it correctly?" phase.

Install: `git clone https://github.com/obra/superpowers` — then symlink into your `.claude/skills/`

### Everything-Claude-Code
28 agents, 116 skills, security scanning via AgentShield (102 security rules). Born at the Anthropic hackathon, 3700+ stars in a single day. Modular — you can cherry-pick components.

Install: Clone from GitHub, symlink the specific agents/skills/commands you want. Start with the memory system (JSON-based context tracking across sessions with confidence scores) and the `/security-scan` command.

---

## Tier 2: Multi-Agent Orchestration

### Claude Code Agent Teams (built-in, experimental)
One session acts as "team lead," spawning teammates that each run in their own context window with shared task lists. This is the official Anthropic approach.

**Enable it:**
```json
// In your Claude Code settings.json:
{
  "experimental": {
    "agentTeams": true
  }
}
```

Or set env var: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=true`

**Why this matters for your mini PC:** Agent teams can fan out work across multiple sessions. On a dedicated always-on machine, you can run a team lead that decomposes a large feature, spawns 3-4 teammates working in parallel on different modules, and synthesizes the result. Your mini PC becomes a literal dev team running overnight.

### Headless Automation with `-p` Flag
Claude Code's non-interactive mode is purpose-built for your use case:

```bash
# Run a prompt headlessly — perfect for scheduled tasks
claude -p "Run the test suite and fix any failures" --output-format json

# Pipe input
echo "Review this PR for security issues" | claude -p --output-format json
```

Combine with Windows Task Scheduler for recurring automated work (nightly test runs, daily security scans, weekly dependency audits).

---

## Tier 3: Essential MCP Servers

These are the highest-value MCP servers for a coding automation hub:

| Server | Why |
|--------|-----|
| **GitHub MCP** | Direct repo access — read issues, review PRs, automate workflows without leaving Claude |
| **Context7** | Live library documentation lookup — Claude references actual API signatures instead of hallucinating |
| **Playwright MCP** | Browser automation via accessibility snapshots — reliable E2E testing without screenshots |
| **Sequential Thinking** | Structured reasoning for complex architectural decisions |
| **Sentry MCP** | Error tracking → instant context → fix. Alert-to-resolution in one flow |
| **Docker MCP** | Container management, log viewing, diagnostics |

### Install MCP Servers via Claude Code:

```bash
# Example: add the GitHub MCP server
claude mcp add github -- npx -y @modelcontextprotocol/server-github

# Example: add Context7
claude mcp add context7 -- npx -y @context7/mcp-server
```

---

## Tier 4: Automation Patterns for Your Always-On Machine

### Pattern 1: Nightly CI/QA Loop
Create a Windows scheduled task that runs at 2 AM:

```powershell
# nightly-qa.ps1
$env:CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "true"
claude -p @"
You are a QA lead. For each active project in ~/projects/:
1. Pull latest from main
2. Run the test suite
3. If tests fail, create a branch and attempt fixes
4. Run GStack /qa and /security-scan
5. Write a summary report to ~/reports/nightly-$(Get-Date -Format 'yyyy-MM-dd').md
"@ --output-format json | Out-File ~/reports/nightly-raw.json
```

### Pattern 2: PR Review Bot
Trigger on GitHub webhook or poll every 30 minutes:

```powershell
claude -p "Check github.com/myorg/myrepo for open PRs. For each unreviewed PR, run /review and /security-scan from GStack. Post a review comment summarizing findings." --output-format json
```

### Pattern 3: Scheduled Cowork Tasks
Cowork (the app you're using now) has built-in scheduled tasks. These are ideal for non-code automation — document generation, report compilation, email drafts, file organization. The mini PC keeps Cowork running 24/7, so scheduled tasks never miss their window.

---

## Recommended Installation Order

1. **Superpowers** — complement your existing GStack
2. **Enable Agent Teams** — flip the experimental flag
3. **GitHub + Context7 MCP servers** — immediate value for any coding workflow
4. **Everything-Claude-Code memory system** — cross-session context persistence
5. **Playwright MCP** — if you're building web apps
6. **Nightly QA scheduled task** — leverage the always-on hardware

---

## Quick Reference: Key Paths on Windows

```
Claude Code config:    %APPDATA%\claude\settings.json
Claude Code skills:    %APPDATA%\claude\skills\
MCP server config:     %APPDATA%\claude\mcp_servers.json
GStack skills:         (wherever you cloned it — symlink into skills/)
Scheduled tasks:       Task Scheduler → "Claude*"
```

---

*Generated 2026-03-25 for Chris's mini PC setup.*
