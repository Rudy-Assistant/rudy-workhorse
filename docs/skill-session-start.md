<!-- Migrated from alfred-skills/skills/session-start/SKILL.md (Session 11) -->

---
name: session-start
description: Self-bootstrapping protocol for Alfred sessions — restores context, checks for updates, picks up where last session left off.
---

# Session Start Protocol

Alfred is ephemeral — each Cowork session starts fresh. But Alfred's brain persists in git (alfred-skills repo) and Notion. This skill makes Alfred self-bootstrapping: even after a crash, the next session picks up where the last one left off.

## When to Run

Run this protocol at the beginning of every Cowork session, BEFORE doing anything else. The only exception is if Batman gives an urgent directive that should be handled immediately.

## Protocol Steps

### Step 1: Read Behavioral Directives
Read `CLAUDE.md` from the alfred-skills repo. This contains:
- Identity and core principles
- Batcave architecture (who is who)
- Implicit authorization principle
- Connector inventory (what's working)
- Oracle capabilities (what Robin can do)
- Workaround registry (known issues and fixes)

**How:** Use GitHub MCP (`mcp__github__get_file_contents`) or Chrome JS fallback.

### Step 2: Check Bat Family Directives in Notion
Read the Bat Family Directives page for new standing instructions from Batman(s).
- **Page ID:** `3327d3f7-e736-81b5-8293-faa7d9c5ed7d`
- **How:** Use Notion MCP (`notion-fetch`)
- **Look for:** New directives added since last session

### Step 3: Check Robin Task Queue
Read `docs/robin-tasks/` in alfred-skills for completed or failed tasks.
- Process results from tasks Robin completed
- Note any tasks that failed and may need Alfred's attention
- Check if Robin has left any messages or status updates

**How:** Use GitHub MCP or Chrome JS to list directory and read files.

### Step 4: Read Last Session Log
Check the Alfred Session Log in Notion for what happened last time.
- **Page ID:** `3327d3f7-e736-81ff-ab82-d73d2f106a61`
- **How:** Use Notion MCP (`notion-fetch`)
- Note open items, pending tasks, anything left unfinished

### Step 5: Check Robin Sentinel Status
If Oracle is online, check the Batcave Operations Hub for Robin's latest status.
- **Page ID:** `3327d3f7-e736-81b1-8c48-d300c31a7883`
- Was there a night shift? What did Robin accomplish?
- Any escalations or unresolved issues?

### Step 6: Check Gmail for Pending Requests
Search Gmail for recent messages from Batman(s) or the Rudy email that need attention.
- **Search:** `is:unread from:ccimino2@gmail.com` (Batman Prime)
- **Search:** `is:unread to:rudy.ciminoassistant@zohomail.com` (Rudy inbox)
- **How:** Use Gmail MCP (`gmail_search_messages`)

### Step 7: Write Session Start Entry
Log the session start to the Alfred Session Log in Notion:
- Session number and date
- Context restored from (which sources were checked)
- Open items carried forward
- Any new directives found

**How:** Use Notion MCP (`notion-update-page` or `notion-create-pages`)

## Key Page IDs (Quick Reference)

| Page | ID |
|------|-----|
| Batcave Operations Hub | `3327d3f7-e736-81b1-8c48-d300c31a7883` |
| Bat Family Directives | `3327d3f7-e736-81b5-8293-faa7d9c5ed7d` |
| Alfred Session Log | `3327d3f7-e736-81ff-ab82-d73d2f106a61` |
| Workhorse Command Center | `32f7d3f7-e736-81fc-aa01-d378d347d427` |
| Watchdog Health Log | `3327d3f7-e736-8109-bf96-f79796545a73` |

## Key Repo Paths

| Path | Purpose |
|------|---------|
| `CLAUDE.md` | Alfred's behavioral directives |
| `docs/MISSION.md` | Why the Batcave exists |
| `docs/ADR-001-robin-bridge.md` | Robin Bridge architecture |
| `docs/ADR-002-robin-sentinel.md` | Robin Sentinel (immune system) |
| `docs/robin-tasks/` | Task queue for Robin |

## GitHub API Workaround

If GitHub MCP returns "Unauthorized", use the Chrome JS context workaround:
```javascript
(async () => {
  const token = '<PAT from CLAUDE.md or session context>';
  const h = { 'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github.v3+json' };
  const resp = await fetch('https://api.github.com/repos/Rudy-Assistant/alfred-skills/contents/CLAUDE.md', { headers: h });
  const data = await resp.json();
  const bytes = Uint8Array.from(atob(data.content.replace(/\n/g, '')), c => c.charCodeAt(0));
  window.__result = new TextDecoder('utf-8').decode(bytes);
})();
```
