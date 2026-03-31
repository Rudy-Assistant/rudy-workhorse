# Security Architecture — Phase 2 Roadmap

## Current State

See `memory/context/security-hardening.md` for current security infrastructure.

## Phase 2: Proxmox VE Virtualization

Target host: Hub (AceMagic AM06 Pro) when back online.

### Planned VMs

| VM | Purpose |
|----|--------|
| **Security Onion** | Network security monitoring, IDS/IPS, packet capture, log management |
| **Kali Linux** | Penetration testing, vulnerability assessment |
| **T-Pot** | Honeypot platform — attract and analyze attacks |

### Prerequisites

- Hub must be back online with clean Windows install
- Docker Desktop installed
- Sufficient RAM/storage for VM workloads
- Network bridge configured for monitoring VMs

## Admin Helper

`rudy/admin.py` — self-elevates via PowerShell `Start-Process -Verb RunAs` (UAC prompts disabled, so elevation is silent). Use for schtasks, registry, service operations.
