#!/usr/bin/env python3
"""
Stop hook that prompts the agent to continue working on open issues.

This hook runs when Claude Code finishes a response and checks if there
are more issues to work on. It reads from .betterbeads/config.json to determine
whether to trigger.

Configuration (.betterbeads/config.json):
    {
      "hooks": {
        "session_stop": {
          "enabled": true
        }
      }
    }
"""

import json
import subprocess
import sys
from pathlib import Path


def get_git_root(cwd: str) -> Path | None:
    """Get the git repository root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def load_config(git_root: Path) -> dict:
    """Load bb configuration from .betterbeads/config.json."""
    config_path = git_root / ".bb" / "config.json"
    if not config_path.exists():
        return {}

    try:
        with open(config_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def is_hook_enabled(config: dict) -> bool:
    """Check if the session_stop hook is enabled in config."""
    hooks_config = config.get("hooks", {})
    session_stop_config = hooks_config.get("session_stop", {})
    # Default to False - must be explicitly enabled
    return session_stop_config.get("enabled", False)


def get_repo_name(cwd: str) -> str | None:
    """Get the GitHub repository name (owner/repo)."""
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def get_ready_issues(cwd: str) -> list[dict]:
    """Get issues that are ready for work (not blocked, deps complete)."""
    try:
        result = subprocess.run(
            ["bb", "issues", "--ready", "--limit", "5"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else data.get("issues", [])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def format_issue_brief(issue: dict) -> str:
    """Format a single issue briefly."""
    number = issue.get("number", "?")
    title = issue.get("title", "Untitled")
    return f"  - #{number}: {title}"


def main():
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        hook_input = {}

    cwd = hook_input.get("cwd", ".")

    # Check if we're in a git repo
    git_root = get_git_root(cwd)
    if not git_root:
        sys.exit(0)

    # Load config and check if hook is enabled
    config = load_config(git_root)
    if not is_hook_enabled(config):
        sys.exit(0)

    # Get repo name
    repo_name = get_repo_name(cwd)
    if not repo_name:
        sys.exit(0)

    # Get ready issues
    ready_issues = get_ready_issues(cwd)

    if not ready_issues:
        sys.exit(0)

    # Build output
    lines = []
    lines.append("")
    lines.append("---")
    lines.append(f"## More Work Available in {repo_name}")
    lines.append("")
    lines.append(f"There are {len(ready_issues)} issue(s) ready to work on:")
    lines.append("")
    for issue in ready_issues:
        lines.append(format_issue_brief(issue))
    lines.append("")
    lines.append("Use `bb issue <number>` to view details and continue working.")
    lines.append("")

    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
