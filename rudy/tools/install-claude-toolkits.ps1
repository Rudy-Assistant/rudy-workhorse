<#
.SYNOPSIS
    Install Claude Code power toolkits — Superpowers, Everything-Claude-Code, MCP servers
.DESCRIPTION
    Run from a regular (non-admin) PowerShell terminal.
    Requires: Node.js 18+, npm, Claude Code CLI (`claude`) on PATH.

    Usage:
        .\install-claude-toolkits.ps1              # Install everything
        .\install-claude-toolkits.ps1 -SkipPlugins  # MCP servers only
        .\install-claude-toolkits.ps1 -SkipMCP       # Plugins only
        .\install-claude-toolkits.ps1 -DryRun        # Preview only
.NOTES
    Author:  Claude (generated for Chris)
    Date:    2026-03-25
#>

param(
    [switch]$SkipPlugins,
    [switch]$SkipMCP,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$Msg); Write-Host "`n==> $Msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$Msg); Write-Host "    OK: $Msg" -ForegroundColor Green }
function Write-Skip { param([string]$Msg); Write-Host "    SKIP: $Msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$Msg); Write-Host "    ERROR: $Msg" -ForegroundColor Red }

function Test-Command {
    param([string]$Cmd)
    $null = Get-Command $Cmd -ErrorAction SilentlyContinue
    return $?
}

function Invoke-Safe {
    param([string]$Description, [string]$Command)
    if ($DryRun) {
        Write-Host "    [DRY RUN] $Description" -ForegroundColor Yellow
        Write-Host "              > $Command" -ForegroundColor DarkGray
        return
    }
    Write-Host "    $Description..." -NoNewline
    try {
        Invoke-Expression $Command 2>&1 | Out-Null
        Write-Host " done" -ForegroundColor Green
    } catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "      $($_.Exception.Message)" -ForegroundColor DarkRed
    }
}

# ─────────────────────────────────────────────
# PREFLIGHT CHECKS
# ─────────────────────────────────────────────
Write-Step "Preflight checks"

if (-not (Test-Command "node")) {
    Write-Err "Node.js not found. Install from https://nodejs.org (v18+)"
    exit 1
}
$nodeVer = (node --version) -replace 'v',''
$nodeMajor = [int]($nodeVer -split '\.')[0]
if ($nodeMajor -lt 18) {
    Write-Err "Node.js $nodeVer found — need v18+. Please upgrade."
    exit 1
}
Write-OK "Node.js v$nodeVer"

if (-not (Test-Command "npm")) {
    Write-Err "npm not found."
    exit 1
}
Write-OK "npm $(npm --version)"

if (-not (Test-Command "claude")) {
    Write-Err "Claude Code CLI not found on PATH. Install: npm install -g @anthropic-ai/claude-code"
    exit 1
}
Write-OK "Claude Code CLI found"

if (-not (Test-Command "git")) {
    Write-Err "Git not found. Install from https://git-scm.com"
    exit 1
}
Write-OK "Git $(git --version)"

# ─────────────────────────────────────────────
# INSTALL PLUGINS (Superpowers + Everything-Claude-Code)
# ─────────────────────────────────────────────
if (-not $SkipPlugins) {

    Write-Step "Installing Superpowers plugin"
    Invoke-Safe "Adding Superpowers marketplace" `
        "claude '/plugin marketplace add obra/superpowers-marketplace' --print 2>&1"
    Write-Host ""
    Write-Host "    NOTE: To complete Superpowers install, open Claude Code and run:" -ForegroundColor Magenta
    Write-Host "      /plugin install superpowers@superpowers-marketplace" -ForegroundColor White
    Write-Host ""

    Write-Step "Installing Everything-Claude-Code plugin"
    Invoke-Safe "Adding Everything-Claude-Code marketplace" `
        "claude '/plugin marketplace add affaan-m/everything-claude-code' --print 2>&1"
    Write-Host ""
    Write-Host "    NOTE: To complete ECC install, open Claude Code and run:" -ForegroundColor Magenta
    Write-Host "      /plugin install everything-claude-code@everything-claude-code" -ForegroundColor White
    Write-Host ""

} else {
    Write-Skip "Plugin installation (--SkipPlugins)"
}

# ─────────────────────────────────────────────
# INSTALL MCP SERVERS
# ─────────────────────────────────────────────
if (-not $SkipMCP) {

    Write-Step "Installing MCP servers"

    # Context7 — live library documentation
    Invoke-Safe "Context7 (live docs lookup)" `
        "claude mcp add context7 -- npx -y @upstash/context7-mcp@latest"

    # Sequential Thinking — structured reasoning
    Invoke-Safe "Sequential Thinking (structured reasoning)" `
        "claude mcp add sequential-thinking -s local -- npx -y @modelcontextprotocol/server-sequential-thinking"

    # GitHub — repo access (requires GITHUB_TOKEN env var)
    $ghToken = $env:GITHUB_TOKEN
    if ($ghToken) {
        Invoke-Safe "GitHub MCP (repo access)" `
            "claude mcp add github -e GITHUB_TOKEN=$ghToken -- npx -y @modelcontextprotocol/server-github"
        Write-OK "GitHub MCP configured with existing GITHUB_TOKEN"
    } else {
        Write-Host ""
        Write-Host "    GitHub MCP requires a personal access token." -ForegroundColor Yellow
        Write-Host "    Set GITHUB_TOKEN env var, then run:" -ForegroundColor Yellow
        Write-Host "      claude mcp add github -e GITHUB_TOKEN=ghp_xxx -- npx -y @modelcontextprotocol/server-github" -ForegroundColor White
        Write-Host ""
    }

    # Playwright — browser automation for testing
    Invoke-Safe "Playwright MCP (browser testing)" `
        "claude mcp add playwright -- npx -y @anthropic-ai/mcp-server-playwright"

    # Docker — container management (only if Docker is installed)
    if (Test-Command "docker") {
        Invoke-Safe "Docker MCP (container management)" `
            "claude mcp add docker -- npx -y @modelcontextprotocol/server-docker"
    } else {
        Write-Skip "Docker MCP — Docker not installed"
    }

    Write-Step "Verifying MCP servers"
    if (-not $DryRun) {
        Write-Host ""
        claude mcp list
        Write-Host ""
    }

} else {
    Write-Skip "MCP server installation (--SkipMCP)"
}

# ─────────────────────────────────────────────
# ENABLE EXPERIMENTAL FEATURES
# ─────────────────────────────────────────────
Write-Step "Configuring Claude Code settings"

$settingsPath = "$env:APPDATA\claude\settings.json"
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    $settingsDir = Split-Path $settingsPath
    if (-not (Test-Path $settingsDir)) { New-Item -Path $settingsDir -ItemType Directory -Force | Out-Null }
    $settings = [PSCustomObject]@{}
}

# Ensure experimental section exists and agent teams is enabled
if (-not $settings.PSObject.Properties['experimental']) {
    $settings | Add-Member -NotePropertyName "experimental" -NotePropertyValue ([PSCustomObject]@{})
}
$settings.experimental | Add-Member -NotePropertyName "agentTeams" -NotePropertyValue $true -Force

if (-not $DryRun) {
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
    Write-OK "Agent Teams enabled in settings.json"
} else {
    Write-Host "    [DRY RUN] Would enable agentTeams in $settingsPath" -ForegroundColor Yellow
}

# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
Write-Host "`n" -NoNewline
Write-Host "============================================" -ForegroundColor Magenta
Write-Host "  TOOLKIT INSTALLATION COMPLETE" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta
Write-Host @"

  Installed:
    MCP Servers: Context7, Sequential Thinking, Playwright
                 (GitHub — pending token, Docker — if available)
    Plugins:     Superpowers, Everything-Claude-Code (finish in Claude Code)
    Settings:    Agent Teams enabled

  Next steps in Claude Code:
    /plugin install superpowers@superpowers-marketplace
    /plugin install everything-claude-code@everything-claude-code

  Verify everything:
    claude mcp list
    /plugin list

"@ -ForegroundColor White
