"""Step 2: Stage, commit, and push to GitHub."""
import subprocess, os

DESKTOP = r"C:\Users\C\Desktop"

def run(cmd, desc, timeout=90):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=DESKTOP, timeout=timeout)
        ok = r.returncode == 0
        print(f"{desc}: {'OK' if ok else 'FAIL'}")
        if r.stdout.strip():
            for line in r.stdout.strip().split('\n')[:5]:
                print(f"  {line}")
        if not ok and r.stderr.strip():
            for line in r.stderr.strip().split('\n')[:3]:
                print(f"  ERR: {line}")
        return ok
    except subprocess.TimeoutExpired:
        print(f"{desc}: TIMEOUT")
        return False

print("=" * 50)
print("  Git Step 2: Commit + Push")
print("=" * 50)

# Check current state
run("git status --short | find /c /v \"\"", "Files to track")
run("git branch --show-current", "Current branch")
run("git remote -v", "Remotes")

# Stage everything
print("\nStaging files...")
run("git add -A", "git add -A")

# Show summary
run("git diff --cached --stat | tail -3", "Staged changes summary")

# Commit
print("\nCommitting...")
commit_msg = (
    "Initial commit: Rudy Workhorse v0.1.0\n\n"
    "- 22+ Python modules (rudy/ package)\n"
    "- 6 autonomous agents (system_master, security, sentinel, taskmaster, research, ops)\n"
    "- Security: DNS blocking, network defense, breach monitoring, intrusion profiling\n"
    "- AI: local LLM inference, NLP, knowledge base, web intelligence\n"
    "- Creative: voice cloning, avatar generation, photo intel, phone check\n"
    "- Infrastructure: multi-provider email, API server, offline ops\n"
    "- CI/CD: lint, smoke tests, release workflows\n"
    "- User apps, scripts, docs, memory system"
)
run(f'git commit -m "{commit_msg}"', "git commit")

# Push
print("\nPushing to GitHub...")
ok = run("git push -u origin main", "git push")
if not ok:
    print("Trying force push (first push to new repo)...")
    run("git push -u origin main --force", "git push --force")

# Verify
print("\nVerification:")
run("git log --oneline -3", "Recent commits")
run("gh repo view rudy-ciminoassist/rudy-workhorse --json name,visibility,url 2>nul", "Repo info")
print("\nDone!")
