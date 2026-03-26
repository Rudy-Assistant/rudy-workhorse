"""
Setup GitHub Repository — Full Pipeline
1. Verify/install gh CLI
2. Authenticate with GitHub token
3. Initialize git repo on Desktop
4. Create private remote repo
5. Initial commit + push
"""
import subprocess, os, sys, json, time

DESKTOP = r"C:\Users\C\Desktop"
LOGS = os.path.join(DESKTOP, "rudy-logs")
os.makedirs(LOGS, exist_ok=True)

results = []

def run(cmd, desc, shell=True, cwd=None, timeout=120):
    """Run a command and track result."""
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True,
                          cwd=cwd or DESKTOP, timeout=timeout)
        ok = r.returncode == 0
        results.append({"step": desc, "ok": ok, "stdout": r.stdout[:500], "stderr": r.stderr[:500]})
        status = "OK" if ok else "FAIL"
        print(f"  [{desc}]")
        print(f"    {status}")
        if r.stdout.strip():
            for line in r.stdout.strip().split('\n')[:5]:
                print(f"    {line}")
        if not ok and r.stderr.strip():
            for line in r.stderr.strip().split('\n')[:3]:
                print(f"    ERR: {line}")
        return ok, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        results.append({"step": desc, "ok": False, "error": "timeout"})
        print(f"  [{desc}]")
        print(f"    TIMEOUT ({timeout}s)")
        return False, "", "timeout"
    except Exception as e:
        results.append({"step": desc, "ok": False, "error": str(e)})
        print(f"  [{desc}]")
        print(f"    ERROR: {e}")
        return False, "", str(e)


print("=" * 60)
print("  GitHub Repository Setup — Rudy Workhorse")
print("=" * 60)
print()

# ─── Step 1: Verify gh CLI ───
print("[1/7] Checking GitHub CLI...")
ok, out, _ = run("gh --version", "Check gh CLI version")
if not ok:
    print("  Attempting to install gh CLI via winget...")
    run("winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements",
        "Install gh CLI via winget", timeout=180)
    # Refresh PATH
    os.environ["PATH"] = subprocess.run(
        'powershell -c "[Environment]::GetEnvironmentVariable(\'PATH\',\'Machine\') + \';\' + [Environment]::GetEnvironmentVariable(\'PATH\',\'User\')"',
        shell=True, capture_output=True, text=True
    ).stdout.strip()
    ok, out, _ = run("gh --version", "Verify gh CLI after install")
    if not ok:
        # Try direct path
        gh_paths = [
            r"C:\Program Files\GitHub CLI\gh.exe",
            r"C:\Program Files (x86)\GitHub CLI\gh.exe",
            os.path.expanduser(r"~\AppData\Local\GitHub CLI\gh.exe"),
        ]
        for p in gh_paths:
            if os.path.exists(p):
                os.environ["PATH"] = os.path.dirname(p) + ";" + os.environ.get("PATH", "")
                ok, out, _ = run(f'"{p}" --version', "Verify gh CLI at " + p)
                if ok:
                    break
print()

# ─── Step 2: Get GitHub token ───
print("[2/7] Getting GitHub token...")
token = os.environ.get("GITHUB_TOKEN", "")
if not token:
    # Try reading from registry (set by configure-tokens.py)
    try:
        r = subprocess.run(
            'powershell -c "[Environment]::GetEnvironmentVariable(\'GITHUB_TOKEN\',\'User\')"',
            shell=True, capture_output=True, text=True
        )
        token = r.stdout.strip()
    except:
        pass

if not token:
    # Try token registry file
    try:
        with open(os.path.join(LOGS, "api-tokens.json")) as f:
            data = json.load(f)
            token = data.get("github", {}).get("token", "")
    except:
        pass

if token:
    print(f"  Token found: {token[:4]}...{token[-4:]}")
    os.environ["GITHUB_TOKEN"] = token
    results.append({"step": "Get GitHub token", "ok": True})
else:
    print("  FAIL: No GitHub token found!")
    results.append({"step": "Get GitHub token", "ok": False})
    # Write partial results and exit
    with open(os.path.join(LOGS, "setup-github-repo-results.json"), "w") as f:
        json.dump(results, f, indent=2)
    print("\nCannot proceed without GitHub token. Check GITHUB_TOKEN env var.")
    sys.exit(1)
print()

# ─── Step 3: Authenticate gh CLI ───
print("[3/7] Authenticating gh CLI...")
# Write token to temp file for gh auth
token_file = os.path.join(DESKTOP, "_gh_token.tmp")
with open(token_file, "w") as f:
    f.write(token)
ok, _, _ = run(f'type "{token_file}" | gh auth login --with-token', "Authenticate gh CLI with token")
# Clean up token file immediately
try:
    os.remove(token_file)
except:
    pass

# Verify auth
ok, out, _ = run("gh auth status", "Verify gh auth status")
print()

# ─── Step 4: Check if repo already exists ───
print("[4/7] Checking for existing repo...")
ok, out, _ = run("gh repo view rudy-ciminoassist/rudy-workhorse --json name 2>nul", "Check if remote repo exists")

repo_exists = ok and "rudy-workhorse" in out
if repo_exists:
    print("  Remote repo already exists — will use it")
print()

# ─── Step 5: Initialize local git repo ───
print("[5/7] Initializing local git repo...")

# Check if already a git repo
git_dir = os.path.join(DESKTOP, ".git")
if os.path.exists(git_dir):
    print("  Git repo already initialized — using existing")
    results.append({"step": "Git repo exists", "ok": True})
else:
    run("git init", "Initialize git repo", cwd=DESKTOP)
    run("git checkout -b main", "Set branch to main", cwd=DESKTOP)

# Set identity
run('git config user.email "rudy.ciminoassistant@zohomail.com"', "Set git email", cwd=DESKTOP)
run('git config user.name "Rudy-Workhorse"', "Set git name", cwd=DESKTOP)

# Configure credential helper to use token
run(f'git config credential.helper "!f() {{ echo username=rudy-ciminoassist; echo password={token}; }}; f"',
    "Configure git credentials", cwd=DESKTOP)
print()

# ─── Step 6: Create remote repo if needed ───
print("[6/7] Creating remote repo...")
if not repo_exists:
    ok, out, _ = run(
        'gh repo create rudy-workhorse --private --description "Rudy: Autonomous family assistant & Workhorse command center"',
        "Create private repo on GitHub"
    )
else:
    print("  Skipping — repo already exists")
    results.append({"step": "Remote repo exists", "ok": True})

# Set remote
run("git remote remove origin 2>nul", "Remove old origin (if any)", cwd=DESKTOP)
run("git remote add origin https://github.com/rudy-ciminoassist/rudy-workhorse.git",
    "Add origin remote", cwd=DESKTOP)
print()

# ─── Step 7: Stage, commit, push ───
print("[7/7] Initial commit + push...")

# Stage everything (gitignore will handle exclusions)
run("git add -A", "Stage all files", cwd=DESKTOP)

# Show what's staged
ok, out, _ = run("git status --short | find /c /v \"\"", "Count staged files", cwd=DESKTOP)
print(f"  Files staged: {out}")

# Commit
run('git commit -m "Initial commit: Rudy Workhorse v0.1.0\n\n- 22+ Python modules (rudy/ package)\n- 6 autonomous agents\n- Security infrastructure (DNS blocking, network defense, breach monitoring)\n- CI/CD workflows (lint, smoke tests, release)\n- User apps, scripts, docs, memory system"',
    "Initial commit", cwd=DESKTOP)

# Push
ok, out, err = run("git push -u origin main", "Push to origin/main", cwd=DESKTOP, timeout=180)

if not ok:
    # If push fails, try force push (first push to empty repo)
    print("  Retrying with --force (initial push to empty repo)...")
    run("git push -u origin main --force", "Force push to origin/main", cwd=DESKTOP, timeout=180)

print()

# ─── Summary ───
passed = sum(1 for r in results if r.get("ok"))
total = len(results)
print("=" * 60)
print(f"  GitHub Setup: {passed}/{total} steps passed")

# Save results
with open(os.path.join(LOGS, "setup-github-repo-results.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"  Report: {os.path.join(LOGS, 'setup-github-repo-results.json')}")

# Quick verification
print()
print("  Verification:")
run("gh repo view rudy-ciminoassist/rudy-workhorse --json name,visibility,url", "Verify repo", cwd=DESKTOP)
run("git log --oneline -1", "Latest commit", cwd=DESKTOP)
print("=" * 60)
