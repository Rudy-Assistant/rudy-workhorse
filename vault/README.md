# BatcaveVault (Local Memory)

This directory holds the **local Obsidian vault** for this Oracle's Batcave instance.

## What goes here

- Obsidian markdown files (directives, briefings, sprint logs, trackers, etc.)
- Knowledge sync documents
- Session handoff notes (local copy)

## What does NOT go here

- Secrets, credentials, API keys (those go in `rudy-data/`)
- Code, scripts, or anything that belongs in the repo proper

## Why is this gitignored?

Each Batcave instance (Hub or Field) maintains its own memory vault.
The vault is **never pushed to the repository** because:

1. Each Oracle may have different operational context
2. Vaults may contain principal-specific information
3. The repo is the **Batcave Template** — portable blueprint, not a memory store

## First-time setup

When bootstrapping a new Oracle, either:

1. **Fresh start**: Create your vault structure here (Alfred will populate it)
2. **Sync from Hub**: Copy the vault from the Hub when coordinating (future sprint)

## Obsidian integration

Point Obsidian's vault path to this directory.
The MCP server config in `claude_desktop_config.json` should reference this path
for the `obsidian` server's `vaults` parameter.
