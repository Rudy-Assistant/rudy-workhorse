# n8n Credential Setup Guide — Rudy Phase 1

After running `rudy-n8n-setup.ps1`, open n8n at `http://localhost:5678` and configure these credentials.

---

## 1. Gmail OAuth2 (Required for email triage + morning briefing)

**Used by:** 02-email-triage, 03-morning-briefing, 04-owner-access-guarantee, 05-daily-backup, 06-boot-recovery

### Setup Steps

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project called "Rudy Assistant"
3. Enable the **Gmail API**
4. Go to **APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Authorized redirect URI: `http://localhost:5678/rest/oauth2-credential/callback`
7. Copy the **Client ID** and **Client Secret**

### In n8n

1. Go to **Credentials > Add Credential > Gmail OAuth2**
2. Name it: `Rudy Gmail OAuth2`
3. Paste Client ID and Client Secret
4. Click **Sign in with Google** and authorize with the Rudy email account
5. Scopes needed: `https://mail.google.com/` (full access)

### Create Rudy's Email Account

If not already done, create a Gmail account for Rudy (e.g., `rudy.assistant.batcave@gmail.com`). This is the account Rudy sends from and receives family commands at.

---

## 2. Anthropic API Key (Required for AI classification + briefings)

**Used by:** 02-email-triage (Claude Haiku for classification), 03-morning-briefing (Claude Sonnet for composition)

### Setup Steps

1. Go to [Anthropic Console](https://console.anthropic.com)
2. Create an API key (or use existing one)
3. Copy the key

### In n8n

The workflows use HTTP Request nodes with the API key as an environment variable. Set it in the n8n environment:

**Option A — Environment variable (recommended):**
```powershell
# Add to system environment variables
[System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "sk-ant-...", "Machine")
# Restart n8n service after setting
nssm restart n8n
```

**Option B — n8n credential:**
1. Create a **Header Auth** credential named `Claude API`
2. Header name: `x-api-key`
3. Header value: your API key
4. Update workflows to use credential instead of env var

---

## 3. OpenWeatherMap API Key (Optional — for morning briefing weather)

**Used by:** 03-morning-briefing

### Setup Steps

1. Go to [OpenWeatherMap](https://openweathermap.org/api)
2. Sign up (free tier is fine — 1000 calls/day)
3. Get your API key from the dashboard

### In n8n

```powershell
[System.Environment]::SetEnvironmentVariable("OPENWEATHER_API_KEY", "your-key-here", "Machine")
[System.Environment]::SetEnvironmentVariable("RUDY_WEATHER_CITY", "Your City,US", "Machine")
nssm restart n8n
```

---

## 4. Post-Setup Verification Checklist

After configuring credentials:

- [ ] Open `http://localhost:5678`
- [ ] Import workflows from `n8n\workflows\` (or they were auto-imported by setup script)
- [ ] Activate `01-watchdog` — wait 5 minutes, check `Desktop\rudy-data\health-latest.json`
- [ ] Manually trigger `03-morning-briefing` — verify email arrives at ccimino2@gmail.com
- [ ] Activate `04-owner-access-guarantee` — check fortress log starts populating
- [ ] Activate remaining workflows one at a time
- [ ] Verify all workflows show green "Active" status

### Quick Test Commands (PowerShell)

```powershell
# Check n8n is running
Invoke-WebRequest -Uri http://localhost:5678/healthz -UseBasicParsing

# Check health file exists (after watchdog runs)
Get-Content "$env:USERPROFILE\Desktop\rudy-data\health-latest.json" | ConvertFrom-Json

# Check n8n workflows
n8n list:workflow
```

---

## Environment Variable Summary

| Variable | Required | Used By | Example |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Email triage, Morning briefing | `sk-ant-api03-...` |
| `OPENWEATHER_API_KEY` | No | Morning briefing | `abc123def456` |
| `RUDY_WEATHER_CITY` | No | Morning briefing | `New York,US` |
| `N8N_ENCRYPTION_KEY` | Auto | n8n internal | Set by setup script |
| `N8N_BASIC_AUTH_USER` | Auto | n8n login | `rudy` |
| `N8N_BASIC_AUTH_PASSWORD` | Auto | n8n login | Set by setup script |
