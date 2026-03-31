# Machine — Oracle (The Workhorse)

> Oracle = whatever host machine the Batcave is currently running on. Currently: Ace Magician AM06 Pro Mini PC ("Hub").

## Hardware & OS

| Detail | Value |
|--------|-------|
| **Hardware** | Ace Magician AM06 Pro Mini PC |
| **OS** | Windows 11 |
| **Display** | Headless by default (iPad via Orion temporary only) — configured for monitor-less operation |
| **Node** | v24.14.1 |
| **Git** | 2.53.0.2 (installed via winget) |
| **Claude Code** | Installed globally via npm, Git Bash backend |
| **PowerShell** | ExecutionPolicy = RemoteSigned (CurrentUser) |
| **WSL 2** | Ubuntu 24.04 (Noble Numbat), Python 3.12, default version 2 |
| **usbipd-win** | v5.3.0 at C:\Program Files\usbipd-win\ — USB passthrough to WSL |
| **ProtonVPN** | Installed (free tier, 10 countries, unlimited data) |

## Remote Access

| Method | Details |
|--------|----------|
| **RustDesk** | Password: CMCPassTemp7508!, password-only, unattended. v1.4.6+64. |
| **Tailscale** | 100.83.49.9 |
| **SSH** | `ssh C@100.83.49.9` — OpenSSH Server, Tailscale only, auto-start |
| **WinRM** | `Enter-PSSession -ComputerName 100.83.49.9` — PowerShell Remoting, Tailscale only |
| **Tailscale SSH** | `tailscale ssh mini-pc` (if ACLs configured) |
| **Local IP** | 192.168.7.25 (DHCP, gateway 192.168.7.1) |
| **ISP** | Xfinity (gateway at 10.0.0.1, no web admin — app only) |

## Auto-Recovery (Reboot Resilience)

| Layer | What | Trigger |
|-------|------|----------|
| **Layer 1: Windows Services** | RustDesk + Tailscale | Boot (auto-start + auto-restart on crash: 5s/10s/30s) |
| **Layer 2: Task Scheduler** | CommandRunner (logon+45s), Listener (logon+60s) | User logon |
| **Layer 2: Task Scheduler** | RustDesk config enforce (password + config sync) | Boot + 30s |
| **Layer 3: Health Check** | workhorse-healthcheck.ps1 (SYSTEM) | Every 5 minutes |
| **Layer 4: Startup** | workhorse-startup.bat | Logon + 30s delay |

Boot sequence: Windows boots → auto-login → Services start (RustDesk, Tailscale) → 30s: RustDesk config enforced → 45s: CommandRunner starts → 60s: Listener starts → 5min: Health check begins continuous monitoring.

## Health Check System

- **Script**: workhorse-healthcheck.ps1 (runs as SYSTEM every 5 min)
- **Monitors**: RustDesk, Tailscale, CommandRunner, Listener, Internet
- **Auto-restarts** failed services immediately
- **Alerts**: Emails ccimino2@gmail.com after 3+ consecutive failures (via Rudy SMTP)
- **Alert file**: rudy-logs/ALERT-ACTIVE.txt (exists only when something is down)
- **State**: rudy-logs/healthcheck-state.json (tracks consecutive failures per service)
- **Log**: rudy-logs/healthcheck.log (auto-trimmed to 500 lines)

## Connection Resilience Stack

| Layer | Component | Frequency | What It Does |
|-------|-----------|-----------|---------------|
| **1** | RustDesk service auto-restart | On crash | sc.exe failure actions: 5s/10s/30s restart |
| **2** | RustDeskWatchdog v2 | Every 2 min | Service + process check, zombie kill, crash loop detection, full config sync |
| **3** | TailscaleKeepalive | Every 5 min | Connection check, service restart, `tailscale up` |
| **4** | ConnectionMonitor | Every 5 min | 7-point health check, email alerts on critical failures |
| **5** | WorkhorseHealthCheck | Every 5 min | Full service monitoring, auto-restart all services |
| **6** | PhoneHomeBeacon | Every 6 hours | Status email to Chris, Tailscale backup access |
| **7** | OpenSSH Server | Always on | Backup access via SSH (Tailscale) |
| **8** | WinRM | Always on | Backup access via Enter-PSSession (Tailscale) |

## Cascade Failure Prevention (Resilience Sprint 2026-03-27)

Incident: API error → agent crash → RustDesk zombies → config desync → password rejection → no memory in new session → lockout.
Fixes applied: (1) Watchdog v2 kills zombies + syncs config, (2) SSH + WinRM backup access always-on, (3) Image fallback scripts at `rudy/tools/` for offline OCR.
Remaining: Buy HDMI dummy plug, agent crash handler → Notion state dump, Ollama migration for local LLM failover.

## Remote Access Hardening

Applied 2026-03-26 via harden-remote.py (28/28) + harden-admin-elevated.py (19/19):
- **UAC**: Consent prompts disabled (ConsentPromptBehaviorAdmin=0, PromptOnSecureDesktop=0)
- **Auto-login**: AutoAdminLogon=1, DefaultUserName=C, DefaultPassword set — boots straight to desktop
- **Lock screen**: Disabled entirely (NoLockScreen, DisableCAD, InactivityTimeoutSecs=0, no screensaver)
- **Power**: Never sleep, never hibernate, never turn off display, Connected Standby disabled
- **Headless display**: GPU TDR disabled, DWM compositor forced on, monitor simulation enabled, Fast Startup off
- **RustDesk**: Both service and user configs have verification-method=use-permanent-password, approval-mode=password
- **RustDesk service**: Auto-start + restart on failure (5s/10s/30s) via sc.exe
- **Tailscale service**: Auto-start + restart on failure (5s/10s/30s), SSH enabled
- **Windows Update**: Auto-reboot blocked (NoAutoRebootWithLoggedOnUsers=1, AUOptions=3)
- **Auto-maintenance**: Disabled (MaintenanceDisabled=1, WakeUp=0)
- **NIC power saving**: Disabled (registry + adapter settings) — prevents Wi-Fi drops during idle
- **RustDesk**: v1.4.6+64 (latest stable as of 2026-03-27). Stability fix applied: killed zombie processes, fixed all 4 config locations, set crash recovery policy.
- **RECOMMENDED**: Buy HDMI dummy plug ($5-10) for bulletproof headless operation
- **OpenSSH Server**: Installed + running 2026-03-27. Auto-start. Firewall: Tailscale only (100.64.0.0/10).
- **WinRM (PowerShell Remoting)**: Enabled 2026-03-27. Auto-start. Firewall: Tailscale only.
- **RustDesk Watchdog v2**: Kills zombie processes, kills excess processes (>3), syncs config from canonical source to all 4 locations.

## WSL 2 Tools (Ubuntu 24.04)

**iOS**: usbmuxd, ideviceinfo, idevice_id, idevicepair, idevicesyslog, ideviceprovision, ideviceinstaller, ifuse
**Security**: nmap, masscan, tcpdump, tshark, nikto, netcat, whois, dig, traceroute
**USB Passthrough**: usbipd-win v5.3.0 — `usbipd bind --busid <ID>` then `usbipd attach --wsl`

### iPhone Scan Procedure
1. `usbipd bind --busid 3-2 --force` (admin, one-time)
2. `usbipd attach --wsl --busid 3-2` (admin, each session)
3. In WSL: `usbmuxd && idevice_id -l` (phone must be unlocked + trusted)
4. `ideviceinfo` for full device info, `idevicesyslog` for process monitoring

## Local AI (Offline Intelligence)

- **Module**: `rudy/local_ai.py` + `rudy/offline_ops.py`
- **Primary backend**: Ollama v0.18.3 (HTTP API at `http://localhost:11434`)
- **Fallback backend**: llama-cpp-python (GGUF format, CPU-only inference)
- **Ollama models**: phi3:mini (active, tested 2026-03-27), more via `ollama pull`
- **GGUF models dir**: `rudy-data/models/` (for llama-cpp-python fallback)
- **Capabilities**: Alert triage, ops decisions, text summarization, intent classification, offline conversation
- **Offline controller**: `rudy/offline_ops.py` — detects outages, switches to local AI, queues outbound actions, replays on recovery
- **Auto-routing**: `LocalAI._ensure_loaded()` checks Ollama first, falls back to llama-cpp-python automatically

## Key Constraints

- No physical keyboard/monitor — headless operation, all input via RustDesk remote
- RustDesk must stay in password-only mode (no manual accept) — UAC prompts disabled to prevent lockout
- Machine must auto-recover from power loss (auto-login + Task Scheduler + watchdog; BIOS AC recovery still pending)
- Scripts on Desktop at C:\Users\C\Desktop\
- Display adapter must stay active even without physical monitor (registry hardened, HDMI dummy plug recommended)

## Still Needs Installation

- InsightFace (face analysis for avatars — needs Visual C++ Build Tools)
- Docker (for containerized services — WSL 2 is Docker's backend)
- SadTalker (talking-head video — needs git clone)