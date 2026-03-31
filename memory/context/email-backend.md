# Email Backend (Multi-Provider)

## Provider Status

| Provider | Status | IMAP/SMTP | Priority |
|----------|--------|-----------|----------|
| **Gmail** | Locked out (recovery pending) | imap.gmail.com / smtp.gmail.com | 0 (primary) |
| **Zoho** | Active — SMTP only (rudy.ciminoassistant@zohomail.com / CMCPassTemp7508!) | smtp.zoho.com ONLY | 1 (sending) |
| **Outlook** | Account creation in progress (rudy.ciminoassist@outlook.com / CMCPassTemp7508!) | imap-mail.outlook.com / smtp-mail.outlook.com | 2 (listener) |

**CRITICAL**: Zoho Mail free plan does NOT include IMAP/POP access (paid-only feature since 2023). SMTP sending works. Outlook.com account being created for IMAP receiving.

## Modules

- `rudy/email_multi.py` — failover chain
- `rudy/email_poller.py` — multi-backend polling daemon (replaces IMAP IDLE listener)

## Limitations

- **Zoho SMTP limitations**: Plain text sends work. Attachments with executables (.cmd, .zip containing .cmd) are blocked by Zoho policy (554 5.1.8). Workaround: send script content inline or use Gmail draft MCP.
