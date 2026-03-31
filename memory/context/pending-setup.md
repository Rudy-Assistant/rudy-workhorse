# Pending Setup & Cleanup

## Active

- **Rudy Gmail recovery**: Account locked out (too many auth attempts 2026-03-26). If it doesn't recover, create backup account
- **Rudy TOTP**: Add authenticator app so Rudy can handle 2FA programmatically via pyotp
- **Suno setup**: Get Suno cookie or API key → run `python rudy-suno.py setup` on The Workhorse
- **Hugging Face MCP**: Click Connect when prompted (image generation)
- **Legal plugin**: Install when prompted (contract review, NDA triage, legal briefs)
- **Text messaging (SMS)**: Empower Rudy to send SMS to family. Options: Twilio (paid, ~$0.0079/msg), Vonage, or Google Voice via Playwright. Priority: enables Rudy to reach non-technical family members who don't check email. Evaluate Twilio free trial first.
- BIOS: AC Power Recovery → Power On (no USB keyboard; using smart plug workaround)
- Smart plug for remote power cycling
- Remaining accounts: Discord, Replicate, Shodan, 2captcha, Cloudflare, HIBP, PyPI
- Auto-git-push log (`rudy-logs/auto-git-push.log`) not found — verify the AutoGitPush scheduled task is running

## Completed

- ✅ GitHub token: Classic PAT (ghp_) created + push verified 2026-03-26.
- ✅ HuggingFace token: Write token configured + verified. Username: Rudy-C.
- ✅ Google Drive MCP: Connected 2026-03-27
- ✅ Notion: Connected — Rudy knowledge base workspace structure created
- ✅ Ollama: Installed v0.18.3, phi3:mini active
- ✅ Chocolatey: v2.7.0
- ✅ ADB: v1.0.41 via Chocolatey
- ✅ Coqui TTS: RETIRED → Replaced by Pocket TTS
- ✅ `rudy/CLI_QUICK_REFERENCE.txt` and `rudy/MANIFEST.txt` cleaned

## GitHub PAT Details

- **Type**: Classic PAT (ghp_)
- **Scopes**: repo, workflow, gist, read:user
- **Saved to**: `rudy-logs/github-classic-pat.txt`
- **Push protection**: Disabled on repo (secrets in CLAUDE.md triggered GH013)
- **Expires**: 2026-06-27
- **Also checked**: `GITHUB_TOKEN` env var, `REPO_ROOT/rudy-logs/github-classic-pat.txt`
- **Old fine-grained PAT** (github_pat_): in git config, read-only access. Expires 2026-06-26.
