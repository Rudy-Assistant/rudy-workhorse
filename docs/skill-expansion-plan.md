# Skill Expansion Plan -- Session 30B

**Date**: 2026-03-30
**Author**: Alfred (Session 30B)

## Tier 1 -- High Value, Low Risk (Install Now)

### 1. kepano/obsidian-skills

**Status**: Verified. 3 skills with SKILL.md format.
**Skills**: obsidian-markdown, obsidian-bases, json-canvas
**Install method**: Copy skills/ directory to .claude/skills/ in repo
**Fit**: Direct -- Chris migrating to Obsidian (P2 backlog from Session 27-28)
**Risk**: None -- read-only skill definitions, no code execution
**Action**: Copy to .claude/skills/ via install script

### 2. nextlevelbuilder/ui-ux-pro-max-skill

**Status**: Verified. 55.4k stars. 6 sub-skills.
**Skills**: ui-ux-pro-max, design, design-system, brand, ui-styling, banner-design, slides
**Install method**: `npm install -g uipro-cli && uipro init --ai claude` OR copy .claude/skills/
**Fit**: Useful for presence-dashboard.jsx, any future UI work
**Risk**: Low -- skill definitions only. Heavy dataset (CSV files) but optional.
**Action**: Clone and copy .claude/skills/ directory. Skip data CSVs for now.

### 3. czlonkowski/n8n-mcp

**Status**: Verified. 1,396 n8n nodes, workflow management tools.
**Install method**: `npx n8n-mcp` with env vars
**Fit**: Chris already has n8n running (see n8n/ directory in repo)
**Risk**: Low -- MCP server, sandboxed. Needs N8N_API_URL + N8N_API_KEY.
**Action**: Add to Claude Desktop MCP config. Requires env vars from Chris.

## Tier 2 -- High Value, Needs Evaluation

### 4. HKUDS/CLI-Anything

**Status**: Research needed on actual install format.
**Action**: Evaluate by generating a CLI wrapper for one local tool first.
**Deferred**: Needs hands-on testing before committing.

### 5. gsd-build/get-shit-done

**Status**: Spec-driven dev system with 25+ commands.
**Action**: Evaluate whether it complements or conflicts with oracle-git-ops + Lucius gate.
**Deferred**: Heavy -- could conflict with existing workflow.

## Tier 3 -- Cherry-Pick Items from awesome-claude-code

### 6. hesreallyhim/awesome-claude-code (203+ items)

**Top picks**:
- agnix (agent file linter) -- validates CLAUDE.md, SKILL.md, hooks
- claude-devtools (session observability) -- subagent trees, MCP monitoring
- Trail of Bits security skills -- 12+ CodeQL/Semgrep audit skills
- Context Engineering Kit -- multi-agent context patterns
- claudekit -- CLI toolkit with auto-save, 20+ subagents

**Action**: Research individual items. Install agnix and Trail of Bits security skills first.
**Deferred**: Individual evaluation per item.

## Install Script

See `scripts/install-tier1-skills.py` for automated Tier 1 installation.
