#!/usr/bin/env python3
"""
SessionStart hook that reviews open GitHub issues and returns work items.

This hook runs when Claude Code starts a session and provides context
about open issues that need work in the current repository.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def check_bb_installed() -> bool:
    """Check if bb is installed and available in PATH."""
    return shutil.which("bb") is not None


def get_installation_instructions() -> list[str]:
    """Return installation instructions for bb."""
    return [
        "### Installation Required",
        "",
        "The `bb` command is not installed. Install it with:",
        "",
        "```bash",
        "uv tool install /home/sondre/Repositories/agent-tools",
        "```",
        "",
        "Or if you have the package published:",
        "```bash",
        "uv tool install betterbeads",
        "```",
        "",
    ]


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


def get_open_issues(cwd: str) -> list[dict]:
    """Get open issues using bb or fall back to gh."""
    # Try bb first
    try:
        result = subprocess.run(
            ["bb", "issues", "--limit", "20"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # bb returns a list directly
            return data if isinstance(data, list) else data.get("issues", [])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    # Fall back to gh
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--state",
                "open",
                "--limit",
                "20",
                "--json",
                "number,title,labels,assignees,state,url",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    return []


def get_ready_issues(cwd: str) -> list[dict]:
    """Get issues that are ready for work (not blocked, deps complete)."""
    try:
        result = subprocess.run(
            ["bb", "issues", "--ready", "--limit", "10"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # bb returns a list directly
            return data if isinstance(data, list) else data.get("issues", [])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def format_issue(issue: dict) -> str:
    """Format a single issue for output."""
    number = issue.get("number", "?")
    title = issue.get("title", "Untitled")
    labels = issue.get("labels", [])
    assignees = issue.get("assignees", [])

    # Handle both bb format (list of strings) and gh format (list of dicts)
    if labels and isinstance(labels[0], dict):
        labels = [l.get("name", "") for l in labels]
    if assignees and isinstance(assignees[0], dict):
        assignees = [a.get("login", "") for a in assignees]

    parts = [f"#{number}: {title}"]
    if labels:
        parts.append(f"  Labels: {', '.join(labels)}")
    if assignees:
        parts.append(f"  Assigned: {', '.join(assignees)}")

    return "\n".join(parts)


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
        # Not a git repo, exit silently
        sys.exit(0)

    # Get repo name
    repo_name = get_repo_name(cwd)
    if not repo_name:
        # Not a GitHub repo, exit silently
        sys.exit(0)

    # Check if bb is installed
    bb_installed = check_bb_installed()

    # Get open issues
    all_issues = get_open_issues(cwd)
    ready_issues = get_ready_issues(cwd)

    if not all_issues:
        lines = [
            f"## GitHub Issues for {repo_name}",
            "",
            "No open issues found.",
            "",
            "**ALWAYS use `bb` for all issue operations** - never use `gh issue` directly.",
            "",
        ]
        # Add installation instructions if bb is not installed
        if not bb_installed:
            lines.extend(get_installation_instructions())
        lines.extend([
            "### Issue Requirement",
            "**All changes must have an accompanying GitHub issue.**",
            "Before starting any work, create an issue with `bb create` to track it.",
        ])
        print("\n".join(lines))
        sys.exit(0)

    # Build output
    lines = [f"## GitHub Issues for {repo_name}"]
    lines.append("")
    lines.append("This project uses GitHub Issues as its issue tracker.")
    lines.append("**ALWAYS use `bb` for all issue operations** - never use `gh issue` directly.")
    lines.append("")

    # Add installation instructions if bb is not installed
    if not bb_installed:
        lines.extend(get_installation_instructions())

    lines.append("### Issue Requirement")
    lines.append("**All changes must have an accompanying GitHub issue.**")
    lines.append("- Before starting work, identify or create the relevant issue")
    lines.append("- If no issue exists for the requested work, create one with `bb create`")
    lines.append("- Reference the issue number in commits")
    lines.append("")

    if ready_issues:
        lines.append(f"### Ready for Work ({len(ready_issues)} issues)")
        lines.append("These issues have no blockers and all dependencies are complete:")
        lines.append("")
        for issue in ready_issues:
            lines.append(format_issue(issue))
            lines.append("")

    # Show other open issues
    ready_numbers = {i.get("number") for i in ready_issues}
    other_issues = [i for i in all_issues if i.get("number") not in ready_numbers]

    if other_issues:
        lines.append(f"### Other Open Issues ({len(other_issues)} issues)")
        lines.append("")
        for issue in other_issues[:10]:  # Limit to avoid overwhelming context
            lines.append(format_issue(issue))
            lines.append("")

    total = len(all_issues)
    if total > 20:
        lines.append(f"... and {total - 20} more open issues")

    print("\n".join(lines))
    sys.exit(0)


if __name__ == "__main__":
    main()
