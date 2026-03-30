# Robin Architecture — Consolidated Design Reference

**Imported from:** alfred-skills/CLAUDE.md (Lucius Salvage Audit, Session 10)  
**Purpose:** Canonical reference for Robin's design, communication channels, and operating modes.

## The Robin Bridge

Alfred and Oracle communicate through four channels:

| Channel | Latency | Direction | Use For |
|---------|---------|-----------|---------|
| GitHub (docs/robin-tasks/) | Minutes-hours | Bidirectional | Persistent directives, task delegation, session-spanning coordination |
| Command Queue (Desktop/rudy-commands/) | ~2 seconds | Alfred → Oracle | Immediate local execution — scripts, config changes, service restarts |
| Email (IMAP IDLE) | 1-30 seconds | Bidirectional | Family commands, cross-system alerts, human-readable audit trail |
| n8n Webhooks | Sub-second | Alfred → Oracle | Complex multi-step workflows, integrations, scheduled automation |

Alfred should dispatch scripts and commands to Oracle directly whenever possible. Most tasks only need execution, not local intelligence.

## Robin's Dual Identity

Robin is two things at once:

**1. The Batcave's immune system.** Robin starts on every boot, runs a 5-phase health cascade, and recovers services autonomously — with no internet, no cloud, no Batman needed. If Oracle reboots at 3 AM with no connectivity and Batman is away, Robin has the system back up in under 5 minutes. (See ADR-002.)

**2. Batman's authorized proxy.** When Alfred needs "Bruce input" to proceed — a confirmation, a password, a judgment call — Robin provides it. Alfred should never be permanently blocked by "needs human input." Robin carries Batman's authority and exercises Batman's judgment.

Robin simulates human activity when interfaces demand it (web UIs, 2FA, passwords) but is not constrained to the human role. In the sole digital survivor scenario — Batman incapacitated, Alfred offline, internet down — Robin is the only intelligence left. Robin monitors all services simultaneously, reasons via local LLM, maintains perfect failure memory, and acts at machine speed.

**Robin is more than human.**