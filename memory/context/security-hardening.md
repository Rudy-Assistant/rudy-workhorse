# Security & Privacy Hardening

## Privacy Hardening

Applied 2026-03-26 via harden-privacy.py (ran as admin, 45/49 succeeded):
- Telemetry disabled (Security level only), advertising ID off, activity history off
- Cortana/Copilot/Bing web search disabled, silent app installs blocked
- Location/mic/camera default deny, OneDrive sync disabled
- P2P Windows Update delivery off, Wi-Fi Sense disabled
- Windows Defender hardened: PUA protection, network protection, Block at First Sight
- 22 bloatware apps removed (Xbox, Solitaire, Bing, Clipchamp, Teams, Phone Link, etc.)
- Weekly maintenance checks for privacy drift (Windows Update can reset settings)
- Smart App Control: OFF (was blocking unsigned Python scripts; one-way disable, cannot re-enable)
- SmartScreen: OFF (Explorer, Edge, app install control all disabled)

## Deep Sanitization (2026-03-26)

Applied via sanitize-telemetry.py (9/9) + sanitize-ads-copilot.py (28/31) + hosts-and-tasks (8/8 tasks, all hosts blocked):
- **Telemetry**: DiagTrack + dmwappushservice disabled, CEIP off, App Impact Telemetry off, Error Reporting off, Inventory Collector off, Steps Recorder off, PerfTrack off
- **Ads/Suggestions**: All 15 ContentDeliveryManager keys set to 0 (Start menu ads, silent installs, suggestions, lock screen tips, pre-installed apps)
- **AI Features**: Copilot disabled (policy + user), Windows Recall disabled, Copilot taskbar button hidden
- **Search**: Bing in Start disabled, web search disabled, search highlights off, cloud content search off
- **Taskbar**: Widgets hidden, Task View hidden, Chat hidden, Copilot button hidden, Search box hidden, News/Interests disabled
- **Telemetry Tasks**: 8 Windows scheduled tasks disabled (Compatibility Appraiser, CEIP, DiskDiagnostic, Error Reporting, etc.)
- **Hosts File**: 26+ Microsoft telemetry endpoints + ad networks blocked (vortex, watson, telemetry.microsoft.com, ads.msn.com, etc.)
- **Advertising**: Advertising ID disabled, Tailored Experiences off, tips notifications off

## Security Infrastructure

- **DNS Blocking**: 87,419 malware/tracking domains via hosts file (weekly refresh Sun 2 AM)
- **Breach Monitoring**: 3 family emails checked daily against Have I Been Pwned
- **Threat Intel**: 8 security RSS feeds (Krebs, CISA, NIST NVD, etc.) in ResearchIntel
- **File Integrity**: SHA-256 hashes of critical configs, checked every 30 min
- **Network Monitoring**: Active connection tracking, listening port baseline, anomaly detection
- **Event Log Analysis**: Failed logins, new accounts, service installations
- **Network Defense Module** (`rudy/network_defense.py`): 7-check defensive suite running every 30 min:
  1. ARP Spoofing Detection — gateway MAC lock, duplicate MAC detection, IP-MAC drift
  2. DNS Integrity Monitoring — cross-resolver verification against Cloudflare/Google/Quad9
  3. Outbound Traffic Profiling — new destination flagging, unusual port detection
  4. Rogue Device Detection — alerts on any new MAC appearing on the subnet
  5. SMB/Share Monitoring — detects lateral movement, unexpected file shares
  6. Registry/Config Drift — monitors startup keys, winlogon, security settings
  7. Listening Port Audit — detects new services/backdoors binding to ports
- **Presence Intelligence** (`rudy/presence_analytics.py`): Behavioral device identification via co-occurrence clustering, MAC OUI fingerprinting, activity pattern analysis
- **Wellness Monitor** (`rudy/wellness.py`): Family safety — inactivity detection, routine deviation, fall-risk mode
- **USB Quarantine** (`rudy/usb_quarantine.py`): Full quarantine protocol — every new USB device is fingerprinted, threat scored against known-malicious signatures (Rubber Ducky, O.MG, Flipper Zero, BadUSB), CRITICAL/HIGH auto-blocked and Chris alerted, whitelist for trusted devices
- **Surveillance** (`rudy/surveillance.py`): Video camera integration — OpenCV capture, motion detection, person detection (HOG), snapshot-on-motion, alert pipeline
- **Find My Friends** (`rudy/find_my.py`): iCloud location monitoring for family safety — geofences, routine deviation, stale alerts, speed anomalies
- **Forensic Phone Check** (`rudy/phone_check.py`): USB quarantine integration, network traffic capture, certificate deep inspection, behavioral monitoring, forensic timeline
- **Threat Posture**: Family farm at 4101 Kansas Ave, Modesto — elevated counter-espionage stance (DA/attorney family, community-prominent). Unknown devices treated as hostile by default.
- **Planned Hardware**: Flipper Zero (RF scanning), IP security camera (motion detection via OpenCV), Aqara FP2 (fall detection)

## Stealth & Privacy Tools

| Tool | Status | Purpose |
|------|--------|----------|
| **qBittorrent** | Installed | Torrent client — bind to VPN adapter for IP leak prevention |
| **Windscribe VPN** | Installed (NOT free — 10GB/month cap) | Backup VPN — 11 countries, split tunneling |
| **ProtonVPN** | Installed | FREE VPN — unlimited data, 10 countries, no-logs, no ads |
| **Sandboxie-Plus** | Pending install | File quarantine sandbox — open suspicious files safely |
| **Tor Browser** | Pending install | Anonymous browsing — run inside Sandboxie for double isolation |

## VPN Safety Protocol (CRITICAL)

1. NEVER leave VPN active unattended — will kill remote access (no split tunneling on free ProtonVPN)
2. Use VPN only for specific tasks (torrenting, geo-misdirection, privacy browsing)
3. Always verify RustDesk + Tailscale reconnect after VPN disconnect
4. If Windscribe is used (paid): add RustDesk, Tailscale, python.exe to split tunnel exclusion list

## Phase 2 Roadmap

Proxmox VE → Security Onion + Kali + T-Pot VMs (see `memory/projects/security-architecture.md`)