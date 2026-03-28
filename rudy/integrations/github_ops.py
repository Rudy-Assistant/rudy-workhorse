"""
rudy.integrations.github_ops — GitHub Operations for Rudy Agents

Provides a clean interface for agents to interact with GitHub:
- Create/close issues (ObsolescenceMonitor, Sentinel, SecurityAgent)
- Create PRs (dependency bumps, config changes)
- Commit and push changes
- Query repo status
- Manage releases

All operations go through the `gh` CLI or git commands.
"""
import subprocess
import json
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("rudy.github")

DESKTOP = r"C:\Users\C\Desktop"
REPO = "rudy-ciminoassist/rudy-workhorse"


class GitHubOps:
    """GitHub operations wrapper for Rudy agents."""

    def __init__(self, repo: str = REPO, cwd: str = DESKTOP):
        self.repo = repo
        self.cwd = cwd
        self._gh_available = None

    @property
    def gh_available(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        if self._gh_available is None:
            try:
                r = subprocess.run(
                    "gh auth status",
                    shell=True, capture_output=True, text=True, timeout=10
                )
                self._gh_available = r.returncode == 0
            except Exception as e:
                logger.debug(f"gh availability check failed: {e}")
                self._gh_available = False
        return self._gh_available

    def _run_gh(self, args: str, timeout: int = 30) -> tuple[bool, str]:
        """Run a gh CLI command."""
        try:
            r = subprocess.run(
                f"gh {args}",
                shell=True, capture_output=True, text=True,
                cwd=self.cwd, timeout=timeout
            )
            if r.returncode == 0:
                return True, r.stdout.strip()
            else:
                logger.warning(f"gh command failed: {args}\n{r.stderr[:200]}")
                return False, r.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"gh command timed out: {args}")
            return False, "timeout"
        except Exception as e:
            logger.error(f"gh command error: {e}")
            return False, str(e)

    def _run_git(self, args: str, timeout: int = 30) -> tuple[bool, str]:
        """Run a git command."""
        try:
            r = subprocess.run(
                f"git {args}",
                shell=True, capture_output=True, text=True,
                cwd=self.cwd, timeout=timeout
            )
            return r.returncode == 0, r.stdout.strip()
        except Exception as e:
            return False, str(e)

    # ─── Issues ───

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
        assignee: Optional[str] = None
    ) -> Optional[str]:
        """Create a GitHub issue. Returns issue URL or None."""
        if not self.gh_available:
            logger.warning("gh CLI not available — cannot create issue")
            return None

        cmd = f'issue create -R {self.repo} --title "{title}" --body "{body}"'
        if labels:
            cmd += f' --label "{",".join(labels)}"'
        if assignee:
            cmd += f' --assignee "{assignee}"'

        ok, out = self._run_gh(cmd)
        if ok:
            logger.info(f"Created issue: {out}")
            return out  # URL of created issue
        return None

    def close_issue(self, issue_number: int, comment: Optional[str] = None) -> bool:
        """Close an issue by number."""
        if comment:
            self._run_gh(f'issue comment {issue_number} -R {self.repo} --body "{comment}"')
        ok, _ = self._run_gh(f"issue close {issue_number} -R {self.repo}")
        return ok

    def list_issues(self, state: str = "open", labels: Optional[list[str]] = None, limit: int = 20) -> list[dict]:
        """List issues from the repo."""
        cmd = f"issue list -R {self.repo} --state {state} --limit {limit} --json number,title,labels,createdAt,state"
        if labels:
            cmd += f' --label "{",".join(labels)}"'
        ok, out = self._run_gh(cmd)
        if ok and out:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return []
        return []

    # ─── Pull Requests ───

    def create_pr(
        self,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
        labels: Optional[list[str]] = None
    ) -> Optional[str]:
        """Create a pull request. Returns PR URL or None."""
        cmd = f'pr create -R {self.repo} --title "{title}" --body "{body}" --head {branch} --base {base}'
        if labels:
            cmd += f' --label "{",".join(labels)}"'
        ok, out = self._run_gh(cmd)
        if ok:
            logger.info(f"Created PR: {out}")
            return out
        return None

    # ─── Git Operations ───

    def commit_and_push(self, message: str, files: Optional[list[str]] = None) -> bool:
        """Stage files, commit, and push to origin."""
        if files:
            for f in files:
                self._run_git(f'add "{f}"')
        else:
            self._run_git("add -A")

        ok, _ = self._run_git(f'commit -m "{message}"')
        if not ok:
            logger.warning("Nothing to commit or commit failed")
            return False

        ok, _ = self._run_git("push origin main", timeout=60)
        return ok

    def create_branch(self, branch_name: str) -> bool:
        """Create and checkout a new branch."""
        ok, _ = self._run_git(f"checkout -b {branch_name}")
        return ok

    def switch_branch(self, branch_name: str) -> bool:
        """Switch to an existing branch."""
        ok, _ = self._run_git(f"checkout {branch_name}")
        return ok

    def get_status(self) -> dict:
        """Get current git status."""
        _, branch = self._run_git("branch --show-current")
        _, status = self._run_git("status --short")
        _, log = self._run_git("log --oneline -5")
        _, remote = self._run_git("remote -v")

        return {
            "branch": branch,
            "changes": status.split("\n") if status else [],
            "recent_commits": log.split("\n") if log else [],
            "remotes": remote.split("\n") if remote else [],
        }

    # ─── Releases ───

    def create_release(self, tag: str, title: str, notes: str) -> Optional[str]:
        """Create a tagged release."""
        # Create and push tag
        self._run_git(f'tag -a {tag} -m "{title}"')
        self._run_git(f"push origin {tag}", timeout=60)

        # Create GitHub release
        ok, out = self._run_gh(
            f'release create {tag} -R {self.repo} --title "{title}" --notes "{notes}"'
        )
        return out if ok else None

    # ─── Repo Info ───

    def get_repo_info(self) -> Optional[dict]:
        """Get repository metadata."""
        ok, out = self._run_gh(f"repo view {self.repo} --json name,visibility,url,description,defaultBranchRef")
        if ok:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                pass
        return None

    # ─── Agent-Specific Helpers ───

    def file_upgrade_issue(self, package: str, current: str, latest: str, severity: str = "low") -> Optional[str]:
        """ObsolescenceMonitor: File an issue for a package upgrade."""
        labels = ["dependency", f"priority:{severity}"]
        title = f"Upgrade {package}: {current} → {latest}"
        body = (
            f"## Dependency Upgrade\n\n"
            f"**Package**: `{package}`\n"
            f"**Current**: `{current}`\n"
            f"**Latest**: `{latest}`\n"
            f"**Severity**: {severity}\n\n"
            f"Flagged by ObsolescenceMonitor on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        )
        return self.create_issue(title, body, labels=labels)

    def file_security_alert(self, title: str, details: str, severity: str = "medium") -> Optional[str]:
        """SecurityAgent/Sentinel: File a security-related issue."""
        labels = ["security", f"severity:{severity}"]
        body = (
            f"## Security Alert\n\n"
            f"{details}\n\n"
            f"**Severity**: {severity}\n"
            f"**Detected**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"**Agent**: SecurityAgent/Sentinel\n"
        )
        return self.create_issue(title, body, labels=labels)

    def file_anomaly_report(self, anomaly_type: str, description: str) -> Optional[str]:
        """Sentinel: File an anomaly report as an issue."""
        labels = ["anomaly", "triage"]
        title = f"Anomaly: {anomaly_type}"
        body = (
            f"## Anomaly Report\n\n"
            f"**Type**: {anomaly_type}\n"
            f"**Description**: {description}\n"
            f"**Detected**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"**Agent**: Sentinel\n"
        )
        return self.create_issue(title, body, labels=labels)


# Singleton for easy import
_instance = None

def get_github() -> GitHubOps:
    """Get the shared GitHubOps instance."""
    global _instance
    if _instance is None:
        _instance = GitHubOps()
    return _instance
