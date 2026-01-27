"""Transaction log for operations."""

import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Operation


def generate_operation_id() -> str:
    """Generate a unique operation ID."""
    return f"op_{secrets.token_hex(4)}"


def get_timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def find_git_root() -> Path | None:
    """Find the root of the git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except FileNotFoundError:
        pass
    return None


def get_history_path() -> Path | None:
    """Get the path to the history file."""
    git_root = find_git_root()
    if git_root:
        return git_root / ".betterbeads" / "history.jsonl"
    return None


def ensure_history_dir() -> Path | None:
    """Ensure the .betterbeads directory exists."""
    git_root = find_git_root()
    if git_root:
        bb_dir = git_root / ".betterbeads"
        bb_dir.mkdir(exist_ok=True)
        return bb_dir
    return None


def setup_merge_driver() -> bool:
    """Set up the git merge driver for history.jsonl.

    Returns True if successful.
    """
    git_root = find_git_root()
    if not git_root:
        return False

    # Create .gitattributes entry if not present
    gitattributes = git_root / ".gitattributes"
    merge_line = ".betterbeads/history.jsonl merge=ght-log"

    if gitattributes.exists():
        content = gitattributes.read_text()
        if merge_line not in content:
            with open(gitattributes, "a") as f:
                f.write(f"\n{merge_line}\n")
    else:
        gitattributes.write_text(f"{merge_line}\n")

    # Configure merge driver
    try:
        subprocess.run(
            ["git", "config", "merge.betterbeads-log.name", "ght operation log merge"],
            cwd=git_root,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "merge.betterbeads-log.driver", "ght merge-log %O %A %B %P"],
            cwd=git_root,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def append_operation(op: Operation) -> bool:
    """Append an operation to the history log.

    Returns True if successful.
    """
    ensure_history_dir()
    history_path = get_history_path()
    if not history_path:
        return False

    line = op.to_json_line()
    with open(history_path, "a") as f:
        f.write(line + "\n")
    return True


def read_history(
    limit: int | None = None,
    issue: int | None = None,
    target_repo: str | None = None,
    since: str | None = None,
) -> list[Operation]:
    """Read operations from history log.

    Args:
        limit: Maximum number of operations to return (most recent first)
        issue: Filter by issue/PR number
        target_repo: Filter by target repository
        since: Filter by timestamp (ISO format)

    Returns:
        List of operations, most recent first
    """
    history_path = get_history_path()
    if not history_path or not history_path.exists():
        return []

    operations = []
    with open(history_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                op = Operation.from_json_line(line)
                operations.append(op)
            except (json.JSONDecodeError, KeyError):
                continue  # Skip malformed lines

    # Filter
    if issue is not None:
        operations = [op for op in operations if op.num == issue]
    if target_repo:
        operations = [op for op in operations if op.target == target_repo]
    if since:
        operations = [op for op in operations if op.ts >= since]

    # Sort by timestamp descending (most recent first)
    operations.sort(key=lambda op: op.ts, reverse=True)

    # Limit
    if limit:
        operations = operations[:limit]

    return operations


def get_operation(op_id: str) -> Operation | None:
    """Get a specific operation by ID."""
    history_path = get_history_path()
    if not history_path or not history_path.exists():
        return None

    with open(history_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                op = Operation.from_json_line(line)
                if op.id == op_id:
                    return op
            except (json.JSONDecodeError, KeyError):
                continue

    return None


def create_operation(
    target: str,
    type: str,
    num: int,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    dry_run: bool = False,
) -> Operation:
    """Create a new operation record."""
    return Operation(
        id=generate_operation_id(),
        ts=get_timestamp(),
        target=target,
        type=type,
        num=num,
        action=action,
        before=before,
        after=after,
        dry_run=dry_run,
    )


def merge_history_files(base: str, ours: str, theirs: str) -> str:
    """Merge three versions of history.jsonl.

    Used by the git merge driver.

    Args:
        base: Content of the common ancestor
        ours: Content of our version
        theirs: Content of their version

    Returns:
        Merged content
    """
    # Parse all operations from all files
    all_ops: dict[str, Operation] = {}

    for content in [base, ours, theirs]:
        for line in content.strip().split("\n"):
            if not line.strip():
                continue
            try:
                op = Operation.from_json_line(line)
                all_ops[op.id] = op
            except (json.JSONDecodeError, KeyError):
                continue

    # Sort by timestamp
    sorted_ops = sorted(all_ops.values(), key=lambda op: op.ts)

    # Output
    return "\n".join(op.to_json_line() for op in sorted_ops) + "\n"
