# Tier 2/3 Skill Evaluation — Session 31

**Date**: 2026-03-31
**Evaluator**: Alfred (Session 31)

## Tier 2 Results

### CLI-Anything (HKUDS/CLI-Anything)
- **Format**: SKILL.md files, plugin marketplace
- **Install**: `/plugin marketplace add HKUDS/CLI-Anything` or pip
- **Verdict**: SAFE to install. No conflicts with Lucius gate, oracle-git-ops, or Robin
- **Action**: Install next session when needed for GUI automation wrapping
- **Priority**: LOW — no immediate use case

### get-shit-done / GSD v2 (gsd-build/get-shit-done)
- **Format**: Prompts + TypeScript CLI with own agent harness
- **Install**: `npx get-shit-done-cc@latest`
- **Verdict**: DEFER — potential conflicts with Lucius gate governance and oracle-git-ops
  - GSD v2 manages its own git branches and context windows
  - Single-writer state engine may bypass governance gates
  - Multi-phase pipeline may not align with Robin delegation
- **Action**: Do NOT install. Re-evaluate if Lucius gate gets a compatibility layer
- **Priority**: BLOCKED on architectural review

## Tier 3 Results

### agnix (agent-sh/agnix)
- **Format**: CLI tool + LSP, npm package
- **Install**: `npx agnix .` (global install broken on Oracle due to PATH issues)
- **Verdict**: INSTALL — strengthens governance by validating CLAUDE.md, SKILL.md, hooks
- **Status**: Available via npx. Global install deferred (post-install script needs system32 PATH)
- **Priority**: HIGH — run before each commit to validate agent configs

### claude-devtools (matt1398/claude-devtools)
- **Format**: Electron desktop app
- **Install**: Direct download (.exe) or brew
- **Verdict**: INSTALL — read-only observability, zero conflict risk
- **Status**: Needs manual download from GitHub releases
- **Priority**: MEDIUM — deploy for session observability

### Trail of Bits Security Skills (trailofbits/skills)
- **Format**: Plugin package with 17+ security skills
- **Install**: `/plugins marketplace add trailofbits/skills`
- **Verdict**: SAFE to install — analysis-only, no workflow conflicts
- **Priority**: HIGH — CodeQL + Semgrep audit capabilities