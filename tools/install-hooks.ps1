# Install BOUNCER pre-commit hook (Windows / PowerShell).
# Run once from the repo root: powershell -ExecutionPolicy Bypass -File tools/install-hooks.ps1

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel) 2>$null
if (-not $repoRoot) {
    Write-Error "not inside a git repo"
    exit 1
}

$hookSrc = Join-Path $repoRoot "tools/bouncer/hooks/pre-commit"
$hookDst = Join-Path $repoRoot ".git/hooks/pre-commit"

if (-not (Test-Path $hookSrc)) {
    Write-Error "hook source missing: $hookSrc"
    exit 1
}

# Copy the hook in place. Git on Windows runs hooks via Git Bash, so the
# bash shebang is honored.
Copy-Item -Force $hookSrc $hookDst

# Try to mark executable (no-op on NTFS, but harmless)
try { & icacls $hookDst /grant:r "$($env:USERNAME):(RX)" | Out-Null } catch { }

Write-Host "BOUNCER hook installed at $hookDst"
Write-Host ""
Write-Host "smoke test: try to add a new .py file outside tools/ and commit. The commit should be blocked."
Write-Host "to clear: python tools/bouncer/bouncer.py propose --name <feat> --files <path> --spec <spec.md>"
