# Sprint: GitHub Integration & Version Control

**Sprint Owner**: Rudy / The Workhorse
**Drafted**: 2026-03-26
**Estimated Duration**: 1 Cowork session (~2 hours)

---

## Last Session Accomplished

- Built 5 new Rudy modules: `phone_check.py`, `photo_intel.py`, `voice_clone.py`, `avatar.py`, `obsolescence_monitor.py`
- Created `user-apps/` folder with 6 double-click launcher scripts
- Created accounts: GitHub (rudy-ciminoassist), HuggingFace (Rudy-C), Docker Hub, PyPI, Zoho Mail
- Deployed token configuration script (`configure-tokens.py`) — sets GITHUB_TOKEN and HF_TOKEN as persistent env vars
- Deployed essentials installer (`install-essentials.py`) — Ollama, Sysinternals, Nmap, GitHub CLI, YARA, LangChain
- Updated CLAUDE.md with all new modules, accounts, session monitoring rules, and service accounts table

## Pre-Sprint Checks (Do First)

1. **Verify deploy script results** — Check `rudy-commands/archive/` for `.result` files from:
   - `configure-tokens.py` (did GitHub + HF tokens get set?)
   - `install-essentials.py` (did Ollama, gh CLI, Nmap install?)
   - `configure-new-accounts.py` (did Git identity + Docker login work?)
   - `deploy-creative-suite.py` (did Coqui TTS, Bark, InsightFace install?)
   - `deploy-phone-photo-modules.py` (did MVT, imagehash, geopy install?)

2. **Verify GitHub PAT** — The token generation was ambiguous (clicked Generate but never saw the confirmation page). Test with:
   ```
   gh auth status
   # or
   curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user
   ```
   If the token doesn't work, regenerate via browser: github.com/settings/tokens → Classic → Generate new.

## Sprint Tasks

### Phase 1: Git Foundation

- [ ] **1.1 — Verify `gh` CLI installed and authenticated**
  - Run `gh auth login` using the PAT if needed
  - Confirm `gh auth status` shows `rudy-ciminoassist`

- [ ] **1.2 — Initialize Rudy repository locally**
  - `cd C:\Users\C\Desktop`
  - `git init rudy-repo`
  - Copy in: `rudy/` package, `scripts/`, `workhorse/`, `user-apps/`, `docs/`, `memory/`, key root scripts
  - Create `.gitignore` (exclude: `rudy-logs/`, `rudy-commands/archive/`, `data/sessions/`, `*.pyc`, `__pycache__`, `.env`, `rudy-data/models/`, browser profiles, any credentials)

- [ ] **1.3 — Create remote repo on GitHub**
  - `gh repo create rudy-workhorse --private --description "Rudy: Autonomous family assistant & Workhorse command center"`
  - Wire up remote: `git remote add origin https://github.com/rudy-ciminoassist/rudy-workhorse.git`

- [ ] **1.4 — Initial commit + push**
  - Stage all, commit with descriptive message
  - `git push -u origin main`

### Phase 2: GitHub MCP Server

- [ ] **2.1 — Add GitHub MCP to Claude Code**
  - Edit Claude Code's MCP config (typically `~/.claude/mcp.json` or project-level)
  - Add GitHub MCP server entry using the PAT
  - Restart Claude Code if needed

- [ ] **2.2 — Verify MCP integration**
  - Test: list repos, create an issue, read repo contents via MCP
  - Update CLAUDE.md: change "GitHub — NOT YET" to "GitHub ✓"

### Phase 3: CI/CD & Automation

- [ ] **3.1 — Create GitHub Actions workflow: lint + syntax check**
  - `.github/workflows/lint.yml` — runs `ruff check` and `py_compile` on every push
  - Ensures no broken modules get committed

- [ ] **3.2 — Create GitHub Actions workflow: module smoke tests**
  - `.github/workflows/test.yml` — imports each `rudy.*` module, runs basic health checks
  - Triggered on push to main and PRs

- [ ] **3.3 — Create release workflow**
  - Tag-based releases (`v0.1.0`, etc.)
  - Auto-generates changelog from commit messages

### Phase 4: Operational Improvements

- [ ] **4.1 — Wire `gh` into Rudy agents**
  - `ResearchIntel` can file issues for discovered tool upgrades
  - `Sentinel` can create issues for anomalies
  - `ObsolescenceMonitor` can open PRs with dependency bumps

- [ ] **4.2 — Add git-based CLAUDE.md versioning**
  - Track CLAUDE.md changes in the repo so memory evolution has history
  - Consider a pre-commit hook that auto-commits CLAUDE.md changes

- [ ] **4.3 — Confirm Ollama status**
  - If `install-essentials.py` succeeded: test `ollama run phi3:mini`
  - If Ollama works: migrate `local_ai.py` from raw `llama-cpp-python` to Ollama backend (simpler model management)

### Phase 5: Verification & Cleanup

- [ ] **5.1 — End-to-end module tests on The Workhorse**
  - Test each new module: `phone_check`, `photo_intel`, `voice_clone`, `avatar`, `obsolescence_monitor`
  - Run each user-app `.cmd` script and verify output

- [ ] **5.2 — Update CLAUDE.md**
  - Record all changes from this sprint
  - Update Pending Setup section
  - Update MCP Servers table

- [ ] **5.3 — Run full ObsolescenceMonitor audit**
  - First real execution of the new module
  - Review recommendations and act on any critical findings

## Key Context for Next Session

- GitHub account: `rudy-ciminoassist` (rudy.ciminoassistant@zohomail.com / CMCPassTemp7508!)
- HuggingFace: `Rudy-C`, token: configured in env vars
- PAT scopes: repo, workflow, gist, read:user — expires 2026-04-25 (if it was actually generated)
- All deploy scripts are in the command runner queue — check results FIRST
- PyPI token: not available (Chris couldn't generate one) — defer
- Remaining accounts (Discord, Replicate, Shodan, etc.): deferred per Chris

## Continuation Prompt

```
Continue building Rudy/Workhorse. Last session: built 5 modules (phone_check, photo_intel,
voice_clone, avatar, obsolescence_monitor), created user-apps folder, set up GitHub/HF/Docker/PyPI
accounts, deployed token config + essentials installer scripts.

This sprint: GitHub Integration. Priority order:
1. Check rudy-commands/archive/ for deploy script results (tokens, installs)
2. Verify GitHub PAT works (may need to regenerate)
3. Init local git repo, create private remote, push initial codebase
4. Add GitHub MCP server to Claude Code config
5. Create CI/CD workflows (lint + smoke tests)
6. Wire gh CLI into Rudy agents for automated issue/PR creation
7. Test all new modules end-to-end
8. Run first ObsolescenceMonitor audit

Read CLAUDE.md for full system state. Deploy scripts via rudy-commands/ folder.
```
