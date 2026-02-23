"""CLI interface for ght."""

import functools
import json
import sys
from pathlib import Path
from typing import Any

import click

from . import history
from .gh import GhClient, GhError
from .models import (
    BlockedStatus,
    CheckItem,
    CheckStatus,
    Comment,
    Dependency,
    DiffStats,
    Issue,
    LinkedPR,
    Milestone,
    Operation,
    PR,
    ProjectItem,
    Review,
    User,
)
from .config import get_config
from .parser import add_dependencies, parse_dependencies, remove_dependencies, set_task_complete
from .project import ProjectResolver


def _merge_repo_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    """Callback to merge command-level --repo into context."""
    if value:
        ctx.ensure_object(dict)
        ctx.obj["repo"] = value
    return value


def with_repo_option(f: Any) -> Any:
    """Add --repo option that can be used at command level.

    This allows --repo to be specified either globally (before the command)
    or at the command level (after the command). Command-level takes precedence.

    Example:
        bb --repo owner/repo issue 123  # global
        bb issue --repo owner/repo 123  # command-level (now works!)
    """
    @click.option(
        "--repo",
        "-R",
        default=None,
        help="Repository in owner/repo format",
        expose_value=False,  # Don't add to function signature
        is_eager=True,  # Process before other options
        callback=_merge_repo_callback,
    )
    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return f(*args, **kwargs)

    return wrapper


def output_json(data: Any) -> None:
    """Output data as formatted JSON."""
    click.echo(json.dumps(data, indent=2))


def build_dependency_tree(
    number: int,
    client: GhClient,
    repo: str,
    visited: set[tuple[str, int]] | None = None,
    depth: int = 0,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Build a dependency tree for an issue.

    Args:
        number: Issue number
        client: GhClient for fetching data
        repo: Repository in owner/repo format
        visited: Set of already visited (repo, number) tuples to prevent cycles
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        Tree structure with issue info and nested dependencies
    """
    if visited is None:
        visited = set()

    # Prevent cycles and limit depth
    key = (repo, number)
    if key in visited or depth > max_depth:
        return {
            "number": number,
            "repo": repo,
            "cycle": key in visited,
            "truncated": depth > max_depth,
        }

    visited.add(key)

    try:
        data = client.issue_view(number, repo=repo)
        body = data.get("body", "") or ""
        deps_raw = parse_dependencies(body)

        # Get config for blocked labels
        config = get_config()
        blocked_labels = {label.lower() for label in config.blocked_indicators.labels}

        labels = [
            (label.get("name", "") if isinstance(label, dict) else label).lower()
            for label in data.get("labels", [])
        ]
        is_blocked = any(label in blocked_labels for label in labels)

        node = {
            "number": number,
            "repo": repo,
            "title": data.get("title", ""),
            "state": data.get("state", "").lower(),
            "blocked": is_blocked,
            "dependencies": [],
        }

        # Recursively build tree for dependencies
        for dep in deps_raw:
            dep_repo = dep.repo or repo
            child = build_dependency_tree(
                dep.number,
                client,
                dep_repo,
                visited.copy(),  # Copy to allow parallel branches
                depth + 1,
                max_depth,
            )
            child["complete"] = dep.complete
            node["dependencies"].append(child)

        return node

    except GhError:
        return {
            "number": number,
            "repo": repo,
            "error": "Failed to fetch",
        }


def enrich_dependencies(
    dependencies: list[Dependency],
    client: GhClient,
    current_repo: str,
) -> list[Dependency]:
    """Enrich dependencies with title, state, and blocked status.

    Args:
        dependencies: List of dependencies to enrich
        client: GhClient for fetching issue data
        current_repo: Current repo in owner/repo format

    Returns:
        List of enriched Dependency objects
    """
    config = get_config()
    blocked_labels = {label.lower() for label in config.blocked_indicators.labels}

    enriched = []
    for dep in dependencies:
        # Determine which repo to fetch from
        dep_repo = dep.repo or current_repo

        try:
            # Fetch the dependency issue
            dep_data = client.issue_view(dep.number, repo=dep_repo)

            # Extract title and state
            title = dep_data.get("title", "")
            state = dep_data.get("state", "").lower()

            # Check if dependency is blocked
            dep_labels = [
                (label.get("name", "") if isinstance(label, dict) else label).lower()
                for label in dep_data.get("labels", [])
            ]
            is_blocked = any(label in blocked_labels for label in dep_labels)

            enriched.append(Dependency(
                number=dep.number,
                repo=dep.repo,
                complete=dep.complete,
                title=title,
                state=state,
                blocked=is_blocked,
            ))
        except GhError:
            # If fetch fails, keep original without enrichment
            enriched.append(dep)

    return enriched


def get_client(token: str | None, repo: str | None) -> GhClient:
    """Create a GhClient instance."""
    import os

    token = token or os.environ.get("GHT_TOKEN")
    return GhClient(token=token, repo=repo)


def parse_issue_data(data: dict[str, Any], repo: str) -> Issue:
    """Parse gh issue data into Issue model."""
    # Parse author
    author_data = data.get("author") or {}
    author = User(
        login=author_data.get("login", "unknown"),
        name=author_data.get("name"),
    )

    # Parse milestone
    milestone = None
    if data.get("milestone"):
        milestone = Milestone(
            title=data["milestone"].get("title", ""),
            due_on=data["milestone"].get("dueOn"),
        )

    # Parse labels
    labels = [
        label.get("name", "") if isinstance(label, dict) else label
        for label in data.get("labels", [])
    ]

    # Parse assignees
    assignees = [
        a.get("login", "") if isinstance(a, dict) else a
        for a in data.get("assignees", [])
    ]

    # Parse comments
    comments = []
    for c in data.get("comments", []):
        author_info = c.get("author") or {}
        comments.append(
            Comment(
                id=c.get("id", 0),
                author=author_info.get("login", "unknown"),
                body=c.get("body", ""),
                created_at=c.get("createdAt", ""),
            )
        )

    # Parse dependencies from body
    body = data.get("body", "") or ""
    deps_raw = parse_dependencies(body)
    dependencies = [
        Dependency(
            number=d.number,
            repo=d.repo,
            complete=d.complete,
        )
        for d in deps_raw
    ]

    # Parse project items
    project_items = []
    for item in data.get("projectItems", []):
        project_items.append(
            ProjectItem(
                project=item.get("title", "Unknown"),
                status=item.get("status", {}).get("name") if item.get("status") else None,
                fields={},  # Could parse additional fields here
            )
        )

    # Calculate blocked status
    blocked = BlockedStatus()
    config = get_config()
    blocked_labels = {label.lower() for label in config.blocked_indicators.labels}
    if any(label.lower() in blocked_labels for label in labels):
        blocked.directly = True
        blocked.reasons.append("has blocked label")

    # Check if any dependency is blocked or incomplete
    # (Would need to fetch dependency details for full check)
    incomplete_deps = [d for d in dependencies if not d.complete]
    if incomplete_deps:
        blocked.by_dependencies = True
        for d in incomplete_deps:
            ref = f"{d.repo}#{d.number}" if d.repo else f"#{d.number}"
            blocked.reasons.append(f"dependency {ref} is incomplete")

    # Ready = open, not blocked, no incomplete dependencies
    state = data.get("state", "").upper()
    ready = (
        state == "OPEN"
        and not blocked.directly
        and not blocked.by_dependencies
    )

    return Issue(
        number=data.get("number", 0),
        url=data.get("url", ""),
        title=data.get("title", ""),
        body=body,
        state=state.lower(),
        author=author,
        created_at=data.get("createdAt", ""),
        updated_at=data.get("updatedAt", ""),
        labels=labels,
        assignees=assignees,
        milestone=milestone,
        comments=comments,
        dependencies=dependencies,
        dependents=[],  # Would need reverse lookup
        linked_prs=[],  # Would need search
        project_items=project_items,
        blocked=blocked,
        ready=ready,
    )


def parse_pr_data(data: dict[str, Any], repo: str, checks: list[dict] | None = None) -> PR:
    """Parse gh PR data into PR model."""
    # Parse author
    author_data = data.get("author") or {}
    author = User(
        login=author_data.get("login", "unknown"),
        name=author_data.get("name"),
    )

    # Parse milestone
    milestone = None
    if data.get("milestone"):
        milestone = Milestone(
            title=data["milestone"].get("title", ""),
            due_on=data["milestone"].get("dueOn"),
        )

    # Parse labels
    labels = [
        label.get("name", "") if isinstance(label, dict) else label
        for label in data.get("labels", [])
    ]

    # Parse assignees
    assignees = [
        a.get("login", "") if isinstance(a, dict) else a
        for a in data.get("assignees", [])
    ]

    # Parse reviewers from reviewRequests
    reviewers = []
    for req in data.get("reviewRequests", []):
        if req.get("login"):
            reviewers.append(req.get("login"))
        elif req.get("name"):
            reviewers.append(req.get("name"))

    # Parse reviews
    reviews = []
    for r in data.get("reviews", []):
        author_info = r.get("author") or {}
        reviews.append(
            Review(
                author=author_info.get("login", "unknown"),
                state=r.get("state", ""),
                body=r.get("body"),
                submitted_at=r.get("submittedAt", ""),
            )
        )

    # Parse comments
    comments = []
    for c in data.get("comments", []):
        author_info = c.get("author") or {}
        comments.append(
            Comment(
                id=c.get("id", 0),
                author=author_info.get("login", "unknown"),
                body=c.get("body", ""),
                created_at=c.get("createdAt", ""),
            )
        )

    # Parse checks
    check_status = CheckStatus(status="unknown")
    if checks:
        items = []
        all_success = True
        any_failure = False
        any_pending = False
        for c in checks:
            status = c.get("state", "").lower()
            conclusion = c.get("conclusion")
            items.append(
                CheckItem(
                    name=c.get("name", ""),
                    status=status,
                    conclusion=conclusion,
                    url=c.get("detailsUrl"),
                )
            )
            if status == "pending" or status == "in_progress":
                any_pending = True
                all_success = False
            elif status == "failure" or conclusion == "failure":
                any_failure = True
                all_success = False
            elif status != "success" and conclusion != "success":
                all_success = False

        if any_failure:
            check_status = CheckStatus(status="failure", items=items)
        elif any_pending:
            check_status = CheckStatus(status="pending", items=items)
        elif all_success and items:
            check_status = CheckStatus(status="success", items=items)
        else:
            check_status = CheckStatus(status="unknown", items=items)

    # Parse diff stats
    diff_stats = DiffStats(
        additions=data.get("additions", 0),
        deletions=data.get("deletions", 0),
        changed_files=data.get("changedFiles", 0),
    )

    # Parse project items
    project_items = []
    for item in data.get("projectItems", []):
        project_items.append(
            ProjectItem(
                project=item.get("title", "Unknown"),
                status=item.get("status", {}).get("name") if item.get("status") else None,
                fields={},
            )
        )

    # Parse closes issues from body (looks for "closes #123", "fixes #456", etc.)
    import re
    closes_issues = []
    body = data.get("body", "") or ""
    close_patterns = re.findall(
        r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
        body,
        re.IGNORECASE,
    )
    closes_issues = [int(n) for n in close_patterns]

    return PR(
        number=data.get("number", 0),
        url=data.get("url", ""),
        title=data.get("title", ""),
        body=body,
        state=data.get("state", "").lower(),
        draft=data.get("isDraft", False),
        author=author,
        created_at=data.get("createdAt", ""),
        updated_at=data.get("updatedAt", ""),
        base=data.get("baseRefName", ""),
        head=data.get("headRefName", ""),
        mergeable=data.get("mergeable"),
        labels=labels,
        assignees=assignees,
        reviewers=reviewers,
        milestone=milestone,
        reviews=reviews,
        comments=comments,
        checks=check_status,
        diff_stats=diff_stats,
        closes_issues=closes_issues,
        project_items=project_items,
    )


def _auto_check_referencing_issues(
    client: "GhClient",
    closed_number: int,
    repo: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Auto-check task items referencing a closed issue.

    When an issue is closed, this function finds all other open issues that
    reference it in task list items (e.g., `- [ ] #N`) and marks them as
    complete (e.g., `- [x] #N`).

    Args:
        client: GhClient for GitHub operations
        closed_number: The issue number that was just closed
        repo: Repository in owner/repo format
        dry_run: If True, don't make changes, just report what would happen

    Returns:
        Dict with 'updated' list of successfully updated issues and
        'errors' list of failures.
    """
    result: dict[str, Any] = {"updated": [], "errors": []}

    # Search for open issues that might reference this one
    try:
        matches = client.search_issues(f"#{closed_number} in:body is:open", repo=repo)
    except Exception as e:
        result["errors"].append(f"Search failed: {e}")
        return result

    for match in matches:
        match_number = match["number"]
        if match_number == closed_number:
            continue  # Skip self

        try:
            # Fetch full issue body
            issue_data = client.issue_view(match_number, repo=repo)
            old_body = issue_data.get("body", "") or ""

            # Try to check off the task item
            new_body = set_task_complete(old_body, closed_number, repo=None, complete=True)

            if new_body != old_body:
                if dry_run:
                    result["updated"].append({
                        "number": match_number,
                        "action": "would check off"
                    })
                else:
                    client.issue_edit(match_number, body=new_body, repo=repo)
                    result["updated"].append({
                        "number": match_number,
                        "action": "checked off"
                    })
        except Exception as e:
            result["errors"].append({
                "number": match_number,
                "error": str(e)
            })

    return result


@click.group()
@click.option("--token", envvar="GHT_TOKEN", help="GitHub token")
@click.option("--repo", "-R", help="Repository in owner/repo format")
@click.pass_context
def main(ctx: click.Context, token: str | None, repo: str | None) -> None:
    """bb - Better Beads (GitHub Tool for Agents).

    A CLI wrapper around gh for simplified GitHub operations.
    """
    ctx.ensure_object(dict)
    ctx.obj["token"] = token
    ctx.obj["repo"] = repo


@main.command("issue")
@with_repo_option
@click.argument("number", type=int)
@click.option("--close", "do_close", is_flag=True, help="Close the issue")
@click.option("--reopen", "do_reopen", is_flag=True, help="Reopen the issue")
@click.option("--reason", type=click.Choice(["completed", "not planned"]), help="Close reason")
@click.option("--comment", "comment_text", help="Add a comment")
@click.option("--title", help="Set issue title")
@click.option("--body", help="Set issue body")
@click.option("--add-labels", help="Add labels (comma-separated)")
@click.option("--remove-labels", help="Remove labels (comma-separated)")
@click.option("--add-assignees", help="Add assignees (comma-separated)")
@click.option("--remove-assignees", help="Remove assignees (comma-separated)")
@click.option("--add-deps", help="Add dependencies (comma-separated issue numbers)")
@click.option("--remove-deps", help="Remove dependencies (comma-separated issue numbers)")
@click.option("--milestone", help="Set milestone")
@click.option("--status", help="Set project status (e.g., 'In Progress', 'Done')")
@click.option("--set-field", "set_fields", multiple=True, help="Set project field (key=value)")
@click.option("--project", "project_name", help="Project name (required if in multiple projects)")
@click.option("--start", is_flag=True, help="Shortcut: --status 'In Progress' --add-assignees @me")
@click.option("--done", "do_done", is_flag=True, help="Shortcut: --close --status 'Done'")
@click.option("--shortcut", "shortcut_name", help="Apply a configured shortcut by name")
@click.option("--tree", "show_tree", is_flag=True, help="Show dependency tree")
@click.option("--check", "check_text", help="Check (complete) task items matching text")
@click.option("--uncheck", "uncheck_text", help="Uncheck task items matching text")
@click.option("--check-line", "check_line", type=int, help="Check task item at line number")
@click.option("--uncheck-line", "uncheck_line", type=int, help="Uncheck task item at line number")
@click.option("--edit-comment", "edit_comment_id", help="Edit a comment by ID")
@click.option("--section", "section_name", help="Target a specific section for --body or --append")
@click.option("--append", "append_text", help="Append text to issue body (or section if --section used)")
@click.option("--execute", "-x", is_flag=True, help="Execute changes (default is dry-run)")
@click.pass_context
def issue_cmd(
    ctx: click.Context,
    number: int,
    do_close: bool,
    do_reopen: bool,
    reason: str | None,
    comment_text: str | None,
    title: str | None,
    body: str | None,
    add_labels: str | None,
    remove_labels: str | None,
    add_assignees: str | None,
    remove_assignees: str | None,
    add_deps: str | None,
    remove_deps: str | None,
    milestone: str | None,
    status: str | None,
    set_fields: tuple[str, ...],
    project_name: str | None,
    start: bool,
    do_done: bool,
    shortcut_name: str | None,
    show_tree: bool,
    check_text: str | None,
    uncheck_text: str | None,
    check_line: int | None,
    uncheck_line: int | None,
    edit_comment_id: str | None,
    section_name: str | None,
    append_text: str | None,
    execute: bool,
) -> None:
    """View or modify an issue.

    If no modification flags are provided, displays the issue.
    Otherwise, shows a dry-run diff of changes (use --execute to apply).
    """
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    # Expand shortcuts from config
    config = get_config()
    if start:
        start_config = config.shortcuts.get("start")
        if start_config:
            status = status or start_config.status
            if start_config.assignees and not add_assignees:
                add_assignees = ",".join(start_config.assignees)
            if start_config.close:
                do_close = True
            if start_config.labels_add and not add_labels:
                add_labels = ",".join(start_config.labels_add)
        else:
            # Fallback defaults
            status = status or "In Progress"
            add_assignees = add_assignees or "@me"

    if do_done:
        done_config = config.shortcuts.get("done")
        if done_config:
            status = status or done_config.status
            if done_config.close:
                do_close = True
            if done_config.assignees and not add_assignees:
                add_assignees = ",".join(done_config.assignees)
            if done_config.labels_add and not add_labels:
                add_labels = ",".join(done_config.labels_add)
        else:
            # Fallback defaults
            do_close = True
            status = status or "Done"

    # Handle custom shortcut by name
    if shortcut_name:
        shortcut_config = config.shortcuts.get(shortcut_name)
        if not shortcut_config:
            click.echo(f"Error: Unknown shortcut '{shortcut_name}'", err=True)
            click.echo(f"Available shortcuts: {', '.join(config.shortcuts.keys())}", err=True)
            sys.exit(1)
        status = status or shortcut_config.status
        if shortcut_config.close:
            do_close = True
        if shortcut_config.reopen:
            do_reopen = True
        if shortcut_config.assignees and not add_assignees:
            add_assignees = ",".join(shortcut_config.assignees)
        if shortcut_config.labels_add and not add_labels:
            add_labels = ",".join(shortcut_config.labels_add)
        if shortcut_config.labels_remove and not remove_labels:
            remove_labels = ",".join(shortcut_config.labels_remove)

    # Determine target repo
    target_repo = repo or client.get_current_repo()

    # Check if this is a view or modify operation
    is_modification = any([
        do_close, do_reopen, comment_text, title, body,
        add_labels, remove_labels, add_assignees, remove_assignees,
        add_deps, remove_deps, milestone, status, set_fields,
        start, do_done, shortcut_name,
        check_text, uncheck_text, check_line, uncheck_line,
        edit_comment_id, append_text,
    ])

    try:
        # Always fetch current state
        data = client.issue_view(number, repo=repo)
        current_issue = parse_issue_data(data, target_repo)

        if not is_modification:
            # Just viewing
            if show_tree:
                # Build and output dependency tree
                tree = build_dependency_tree(number, client, target_repo)
                output_json(tree)
                return

            # Enrich dependencies with full context
            if current_issue.dependencies:
                current_issue.dependencies = enrich_dependencies(
                    current_issue.dependencies, client, target_repo
                )
            output_json(current_issue.to_dict())
            return

        # Build the changes
        changes: dict[str, Any] = {}
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}

        if do_close:
            before["state"] = current_issue.state
            after["state"] = "closed"
            changes["state"] = {"from": current_issue.state, "to": "closed"}

        if do_reopen:
            before["state"] = current_issue.state
            after["state"] = "open"
            changes["state"] = {"from": current_issue.state, "to": "open"}

        if title:
            before["title"] = current_issue.title
            after["title"] = title
            changes["title"] = {"from": current_issue.title, "to": title}

        if body is not None:
            before["body"] = current_issue.body
            after["body"] = body
            changes["body"] = {"from": "(current)", "to": "(new)"}

        if add_labels:
            labels_to_add = [l.strip() for l in add_labels.split(",")]
            before["labels"] = current_issue.labels
            new_labels = list(set(current_issue.labels + labels_to_add))
            after["labels"] = new_labels
            changes["labels_added"] = labels_to_add

        if remove_labels:
            labels_to_remove = [l.strip() for l in remove_labels.split(",")]
            before["labels"] = current_issue.labels
            new_labels = [l for l in current_issue.labels if l not in labels_to_remove]
            after["labels"] = new_labels
            changes["labels_removed"] = labels_to_remove

        if add_assignees:
            assignees_to_add = [a.strip() for a in add_assignees.split(",")]
            before["assignees"] = current_issue.assignees
            new_assignees = list(set(current_issue.assignees + assignees_to_add))
            after["assignees"] = new_assignees
            changes["assignees_added"] = assignees_to_add

        if remove_assignees:
            assignees_to_remove = [a.strip() for a in remove_assignees.split(",")]
            before["assignees"] = current_issue.assignees
            new_assignees = [a for a in current_issue.assignees if a not in assignees_to_remove]
            after["assignees"] = new_assignees
            changes["assignees_removed"] = assignees_to_remove

        if add_deps:
            deps_to_add = [d.strip() for d in add_deps.split(",")]
            # Parse as ints or strings
            parsed_deps: list[int | str] = []
            for d in deps_to_add:
                if "#" in d:
                    parsed_deps.append(d)
                else:
                    parsed_deps.append(int(d))
            new_body = add_dependencies(current_issue.body, parsed_deps)
            before["body"] = current_issue.body
            after["body"] = new_body
            changes["dependencies_added"] = deps_to_add

        if remove_deps:
            deps_to_remove = [d.strip() for d in remove_deps.split(",")]
            parsed_deps_remove: list[int | str] = []
            for d in deps_to_remove:
                if "#" in d:
                    parsed_deps_remove.append(d)
                else:
                    parsed_deps_remove.append(int(d))
            # Start from modified body if deps were added, else current
            base_body = after.get("body", current_issue.body)
            new_body = remove_dependencies(base_body, parsed_deps_remove)
            before["body"] = current_issue.body
            after["body"] = new_body
            changes["dependencies_removed"] = deps_to_remove

        # Task list toggling
        if check_text or uncheck_text:
            from betterbeads.parser import toggle_task_by_text

            base_body = after.get("body", current_issue.body)
            if check_text:
                new_body, toggled = toggle_task_by_text(base_body, check_text, complete=True)
                if toggled:
                    before["body"] = current_issue.body
                    after["body"] = new_body
                    changes["tasks_checked"] = [{"text": t.text, "line": t.line_number} for t in toggled]
                else:
                    click.echo(f"Warning: No task items matching '{check_text}' found", err=True)
            if uncheck_text:
                base_body = after.get("body", current_issue.body)
                new_body, toggled = toggle_task_by_text(base_body, uncheck_text, complete=False)
                if toggled:
                    before["body"] = current_issue.body
                    after["body"] = new_body
                    changes["tasks_unchecked"] = [{"text": t.text, "line": t.line_number} for t in toggled]
                else:
                    click.echo(f"Warning: No task items matching '{uncheck_text}' found", err=True)

        if check_line or uncheck_line:
            from betterbeads.parser import toggle_task_at_line

            if check_line:
                base_body = after.get("body", current_issue.body)
                new_body, toggled = toggle_task_at_line(base_body, check_line, complete=True)
                if toggled:
                    before["body"] = current_issue.body
                    after["body"] = new_body
                    changes["task_checked_at_line"] = {"text": toggled.text, "line": check_line}
                else:
                    click.echo(f"Warning: No task item found at line {check_line}", err=True)
            if uncheck_line:
                base_body = after.get("body", current_issue.body)
                new_body, toggled = toggle_task_at_line(base_body, uncheck_line, complete=False)
                if toggled:
                    before["body"] = current_issue.body
                    after["body"] = new_body
                    changes["task_unchecked_at_line"] = {"text": toggled.text, "line": uncheck_line}
                else:
                    click.echo(f"Warning: No task item found at line {uncheck_line}", err=True)

        # Section-based editing
        if section_name and body is not None:
            from betterbeads.parser import replace_section_content

            base_body = current_issue.body  # Start from original for section replacement
            new_body = replace_section_content(base_body, section_name, body)
            if new_body == base_body:
                click.echo(f"Warning: Section '{section_name}' not found", err=True)
            else:
                before["body"] = current_issue.body
                after["body"] = new_body
                changes["section_replaced"] = section_name

        if append_text:
            from betterbeads.parser import append_to_section

            base_body = after.get("body", current_issue.body)
            if section_name:
                new_body = append_to_section(base_body, section_name, append_text)
                if new_body == base_body:
                    click.echo(f"Warning: Section '{section_name}' not found", err=True)
                else:
                    before["body"] = current_issue.body
                    after["body"] = new_body
                    changes["appended_to_section"] = {"section": section_name, "text": append_text}
            else:
                # Append to end of body
                new_body = base_body.rstrip() + "\n" + append_text + "\n"
                before["body"] = current_issue.body
                after["body"] = new_body
                changes["appended_to_body"] = append_text

        # Comment editing
        comment_edit_info = None
        if edit_comment_id:
            # Find the comment
            comment_found = None
            for c in current_issue.comments:
                # Handle both numeric ID and full node ID
                if str(c.id) == edit_comment_id or edit_comment_id in str(c.id):
                    comment_found = c
                    break
            if not comment_found:
                click.echo(f"Error: Comment with ID '{edit_comment_id}' not found", err=True)
                click.echo("Available comment IDs:", err=True)
                for c in current_issue.comments:
                    click.echo(f"  {c.id} (by {c.author})", err=True)
                sys.exit(1)

            # The body parameter is used for the new comment content
            if body is None:
                click.echo("Error: --body is required when using --edit-comment", err=True)
                sys.exit(1)

            comment_edit_info = {
                "comment_id": comment_found.id,
                "old_body": comment_found.body,
                "new_body": body,
            }
            before["comment_body"] = comment_found.body
            after["comment_body"] = body
            changes["comment_edited"] = {"id": comment_found.id, "author": comment_found.author}
            # Don't also modify the issue body
            if "body" in after and after["body"] == body:
                del after["body"]
                if "body" in changes:
                    del changes["body"]

        if comment_text:
            changes["comment"] = comment_text

        if milestone:
            before["milestone"] = current_issue.milestone.title if current_issue.milestone else None
            after["milestone"] = milestone
            changes["milestone"] = {"from": before["milestone"], "to": milestone}

        # Project status changes
        project_info = None
        if status or set_fields:
            resolver = ProjectResolver(client)
            project_info = resolver.get_project_info_for_issue(number, target_repo, project_name)
            if not project_info:
                if project_name:
                    click.echo(f"Error: Issue not found in project '{project_name}'", err=True)
                else:
                    click.echo("Error: Issue is not in any project. Add it to a project first.", err=True)
                sys.exit(1)

            # Get current status from project items
            current_status = None
            for pi in current_issue.project_items:
                if pi.project == project_info.project_title:
                    current_status = pi.status
                    break

            if status:
                before["project_status"] = current_status
                after["project_status"] = status
                changes["project_status"] = {"from": current_status, "to": status, "project": project_info.project_title}

            if set_fields:
                parsed_fields = {}
                for field_spec in set_fields:
                    if "=" not in field_spec:
                        click.echo(f"Error: Invalid field format '{field_spec}'. Use key=value.", err=True)
                        sys.exit(1)
                    key, value = field_spec.split("=", 1)
                    parsed_fields[key] = value
                changes["project_fields"] = {"project": project_info.project_title, "fields": parsed_fields}

        # Output dry-run diff
        if not execute:
            output: dict[str, Any] = {
                "dry_run": True,
                "issue": number,
                "repo": target_repo,
                "changes": changes,
            }

            # Preview cascade auto-check if closing
            if do_close:
                cascade_preview = _auto_check_referencing_issues(
                    client, number, target_repo, dry_run=True
                )
                if cascade_preview["updated"]:
                    output["would_auto_check"] = cascade_preview["updated"]

            output_json(output)
            click.echo("\nRun with --execute (-x) to apply changes.", err=True)

            # Log dry-run operation
            op = history.create_operation(
                target=target_repo,
                type="issue",
                num=number,
                action="modify",
                before=before,
                after=after,
                dry_run=True,
            )
            history.append_operation(op)
            return

        # Execute changes
        cascade_updates: list[dict[str, Any]] = []
        cascade_errors: list[Any] = []

        if do_close:
            client.issue_close(number, reason=reason, comment=comment_text, repo=repo)
            comment_text = None  # Don't double-comment

            # Auto-check task items in referencing issues
            cascade_result = _auto_check_referencing_issues(
                client, number, target_repo, dry_run=False
            )
            cascade_updates = cascade_result.get("updated", [])
            cascade_errors = cascade_result.get("errors", [])

        if do_reopen:
            client.issue_reopen(number, comment=comment_text, repo=repo)
            comment_text = None

        if title or add_labels or remove_labels or add_assignees or remove_assignees or milestone:
            client.issue_edit(
                number,
                title=title,
                add_labels=[l.strip() for l in add_labels.split(",")] if add_labels else None,
                remove_labels=[l.strip() for l in remove_labels.split(",")] if remove_labels else None,
                add_assignees=[a.strip() for a in add_assignees.split(",")] if add_assignees else None,
                remove_assignees=[a.strip() for a in remove_assignees.split(",")] if remove_assignees else None,
                milestone=milestone,
                repo=repo,
            )

        # Handle body changes (including dependency modifications)
        if "body" in after:
            client.issue_edit(number, body=after["body"], repo=repo)

        # Handle standalone comment
        if comment_text:
            client.issue_comment(number, comment_text, repo=repo)

        # Handle comment editing
        if comment_edit_info:
            client.comment_edit(
                comment_id=comment_edit_info["comment_id"],
                body=comment_edit_info["new_body"],
                repo=repo,
            )

        # Handle project status changes
        if project_info and status:
            resolver = ProjectResolver(client)
            resolver.set_status(project_info, status)

        if project_info and set_fields:
            resolver = ProjectResolver(client)
            for field_spec in set_fields:
                key, value = field_spec.split("=", 1)
                resolver.set_field(project_info, key, value)

        # Log executed operation
        op = history.create_operation(
            target=target_repo,
            type="issue",
            num=number,
            action="modify",
            before=before,
            after=after,
            dry_run=False,
        )
        history.append_operation(op)

        # Output result
        output: dict[str, Any] = {
            "executed": True,
            "issue": number,
            "repo": target_repo,
            "url": current_issue.url,
            "changes": changes,
            "operation_id": op.id,
        }

        if cascade_updates:
            output["auto_checked"] = cascade_updates

        if cascade_errors:
            output["cascade_errors"] = cascade_errors

        output_json(output)

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("issues")
@with_repo_option
@click.option("--state", type=click.Choice(["open", "closed", "all"]), default="open")
@click.option("--label", "-l", "labels", multiple=True, help="Filter by label")
@click.option("--assignee", "-a", help="Filter by assignee")
@click.option("--mine", is_flag=True, help="Show only issues assigned to me")
@click.option("--limit", default=30, help="Maximum number of issues")
@click.option("--ready", is_flag=True, help="Show only ready issues (not blocked)")
@click.option("--blocked", is_flag=True, help="Show only blocked issues")
@click.pass_context
def issues_cmd(
    ctx: click.Context,
    state: str,
    labels: tuple[str, ...],
    assignee: str | None,
    mine: bool,
    limit: int,
    ready: bool,
    blocked: bool,
) -> None:
    """List issues."""
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    if mine:
        assignee = "@me"

    try:
        data = client.issue_list(
            state=state,
            labels=list(labels) if labels else None,
            assignee=assignee,
            limit=limit,
            repo=repo,
        )

        # Parse into models for filtering
        target_repo = repo or client.get_current_repo()
        issues = []
        for item in data:
            issue = parse_issue_data(item, target_repo)

            # Apply ready/blocked filters
            if ready and not issue.ready:
                continue
            if blocked and not (issue.blocked.directly or issue.blocked.by_dependencies):
                continue

            issues.append(issue)

        output_json([issue.to_dict() for issue in issues])

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("create")
@with_repo_option
@click.argument("title")
@click.option("--body", "-b", default="", help="Issue body")
@click.option("--labels", "-l", help="Labels (comma-separated)")
@click.option("--assignees", "-a", help="Assignees (comma-separated)")
@click.option("--milestone", "-m", help="Milestone")
@click.option("--project", "-p", help="Project to add to")
@click.option("--deps", help="Dependencies (comma-separated issue numbers)")
@click.option("--execute", "-x", is_flag=True, help="Execute (default is dry-run)")
@click.pass_context
def create_cmd(
    ctx: click.Context,
    title: str,
    body: str,
    labels: str | None,
    assignees: str | None,
    milestone: str | None,
    project: str | None,
    deps: str | None,
    execute: bool,
) -> None:
    """Create a new issue."""
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    # Add dependencies to body if specified
    if deps:
        deps_list: list[int | str] = []
        for d in deps.split(","):
            d = d.strip()
            if "#" in d:
                deps_list.append(d)
            else:
                deps_list.append(int(d))
        body = add_dependencies(body, deps_list)

    # Parse labels and assignees
    labels_list = [l.strip() for l in labels.split(",")] if labels else None
    assignees_list = [a.strip() for a in assignees.split(",")] if assignees else None

    target_repo = repo or client.get_current_repo()

    if not execute:
        output = {
            "dry_run": True,
            "action": "create",
            "repo": target_repo,
            "title": title,
            "body": body,
            "labels": labels_list,
            "assignees": assignees_list,
            "milestone": milestone,
            "project": project,
        }
        output_json(output)
        click.echo("\nRun with --execute (-x) to create the issue.", err=True)
        return

    try:
        result = client.issue_create(
            title=title,
            body=body,
            labels=labels_list,
            assignees=assignees_list,
            milestone=milestone,
            project=project,
            repo=repo,
        )

        # Log operation
        op = history.create_operation(
            target=target_repo,
            type="issue",
            num=result["number"],
            action="create",
            before={},
            after={
                "title": title,
                "body": body,
                "labels": labels_list,
                "assignees": assignees_list,
            },
            dry_run=False,
        )
        history.append_operation(op)

        output = {
            "created": True,
            "issue": result["number"],
            "url": result["url"],
            "repo": target_repo,
            "operation_id": op.id,
        }
        output_json(output)

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("history")
@click.option("--limit", "-n", default=20, help="Number of operations to show")
@click.option("--issue", type=int, help="Filter by issue number")
@click.option("--target-repo", help="Filter by target repository")
@click.option("--since", help="Filter by timestamp (ISO format)")
@click.pass_context
def history_cmd(
    ctx: click.Context,
    limit: int,
    issue: int | None,
    target_repo: str | None,
    since: str | None,
) -> None:
    """Show operation history."""
    operations = history.read_history(
        limit=limit,
        issue=issue,
        target_repo=target_repo,
        since=since,
    )

    output = []
    for op in operations:
        output.append({
            "id": op.id,
            "timestamp": op.ts,
            "target": op.target,
            "type": op.type,
            "number": op.num,
            "action": op.action,
            "dry_run": op.dry_run,
        })

    output_json(output)


@main.command("undo")
@with_repo_option
@click.argument("operation_id", required=False)
@click.option("--last", "-n", type=int, default=1, help="Undo last N operations")
@click.option(
    "--since-commit",
    is_flag=True,
    help="Undo all operations since the last git commit",
)
@click.option("--execute", "-x", is_flag=True, help="Execute undo (default is dry-run)")
@click.pass_context
def undo_cmd(
    ctx: click.Context,
    operation_id: str | None,
    last: int,
    since_commit: bool,
    execute: bool,
) -> None:
    """Undo an operation."""
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    if operation_id:
        # Undo specific operation
        op = history.get_operation(operation_id)
        if not op:
            click.echo(f"Operation {operation_id} not found", err=True)
            sys.exit(1)
        operations = [op]
    elif since_commit:
        # Undo all operations since the last commit
        commit_ts = history.get_last_commit_timestamp()
        if not commit_ts:
            click.echo("No git commits found", err=True)
            sys.exit(1)
        operations = history.read_history(since=commit_ts)
        # Filter out dry-runs and undo operations
        operations = [
            op for op in operations if not op.dry_run and not op.action.startswith("undo:")
        ]
        if not operations:
            click.echo(f"No operations to undo since last commit ({commit_ts})", err=True)
            sys.exit(0)
        click.echo(f"Found {len(operations)} operation(s) since last commit ({commit_ts})")
    else:
        # Undo last N operations
        operations = history.read_history(limit=last)
        # Filter out dry-runs
        operations = [op for op in operations if not op.dry_run][:last]

    if not operations:
        click.echo("No operations to undo", err=True)
        sys.exit(1)

    for op in operations:
        undo_changes = {}

        # Determine undo actions based on operation
        if "state" in op.before and "state" in op.after:
            if op.after["state"] == "closed" and op.before["state"] == "open":
                undo_changes["action"] = "reopen"
            elif op.after["state"] == "open" and op.before["state"] == "closed":
                undo_changes["action"] = "close"

        if "labels" in op.before:
            added = set(op.after.get("labels", [])) - set(op.before.get("labels", []))
            removed = set(op.before.get("labels", [])) - set(op.after.get("labels", []))
            if added:
                undo_changes["remove_labels"] = list(added)
            if removed:
                undo_changes["add_labels"] = list(removed)

        if "assignees" in op.before:
            added = set(op.after.get("assignees", [])) - set(op.before.get("assignees", []))
            removed = set(op.before.get("assignees", [])) - set(op.after.get("assignees", []))
            if added:
                undo_changes["remove_assignees"] = list(added)
            if removed:
                undo_changes["add_assignees"] = list(removed)

        if "title" in op.before:
            undo_changes["title"] = op.before["title"]

        if "body" in op.before:
            undo_changes["body"] = op.before["body"]

        if not execute:
            output = {
                "dry_run": True,
                "undoing": op.id,
                "target": op.target,
                "type": op.type,
                "number": op.num,
                "undo_changes": undo_changes,
            }
            output_json(output)
            continue

        # Execute undo
        try:
            if undo_changes.get("action") == "reopen":
                client.issue_reopen(op.num, repo=op.target)
            elif undo_changes.get("action") == "close":
                client.issue_close(op.num, repo=op.target)

            if any(k in undo_changes for k in ["add_labels", "remove_labels", "add_assignees", "remove_assignees", "title"]):
                client.issue_edit(
                    op.num,
                    title=undo_changes.get("title"),
                    add_labels=undo_changes.get("add_labels"),
                    remove_labels=undo_changes.get("remove_labels"),
                    add_assignees=undo_changes.get("add_assignees"),
                    remove_assignees=undo_changes.get("remove_assignees"),
                    repo=op.target,
                )

            if "body" in undo_changes:
                client.issue_edit(op.num, body=undo_changes["body"], repo=op.target)

            # Log undo operation
            undo_op = history.create_operation(
                target=op.target,
                type=op.type,
                num=op.num,
                action=f"undo:{op.id}",
                before=op.after,
                after=op.before,
                dry_run=False,
            )
            history.append_operation(undo_op)

            output = {
                "undone": True,
                "original_operation": op.id,
                "undo_operation": undo_op.id,
                "target": op.target,
                "number": op.num,
            }
            output_json(output)

        except GhError as e:
            click.echo(f"Error undoing {op.id}: {e}", err=True)

    if not execute:
        click.echo("\nRun with --execute (-x) to apply undo.", err=True)


@main.command("merge-log")
@click.argument("base", type=click.Path(exists=True))
@click.argument("ours", type=click.Path(exists=True))
@click.argument("theirs", type=click.Path(exists=True))
@click.argument("output_path", type=click.Path())
def merge_log_cmd(base: str, ours: str, theirs: str, output_path: str) -> None:
    """Git merge driver for history.jsonl.

    This is called by git during merge conflicts.
    """
    with open(base) as f:
        base_content = f.read()
    with open(ours) as f:
        ours_content = f.read()
    with open(theirs) as f:
        theirs_content = f.read()

    merged = history.merge_history_files(base_content, ours_content, theirs_content)

    with open(output_path, "w") as f:
        f.write(merged)


BB_WORKFLOW_SECTION = """\

## BetterBeads

- Before starting ANY work, create or identify a GitHub issue using `bb`
- Reference the issue number in all commits
- Use `bb` for all GitHub operations, never `gh`
"""

BB_WORKFLOW_MARKER = "## BetterBeads"


def _ensure_global_claude_md() -> bool:
    """Add bb workflow instructions to ~/.claude/CLAUDE.md if not present.

    Returns True if the section was added, False if already present.
    """
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)

    if claude_md.exists():
        content = claude_md.read_text()
        if BB_WORKFLOW_MARKER in content:
            return False
        claude_md.write_text(content.rstrip() + "\n" + BB_WORKFLOW_SECTION)
    else:
        claude_md.write_text(
            "# Global Claude Code Rules\n" + BB_WORKFLOW_SECTION
        )
    return True


@main.command("init")
def init_cmd() -> None:
    """Initialize betterbeads in the current repository."""
    # Ensure .betterbeads directory exists
    bb_dir = history.ensure_history_dir()
    if not bb_dir:
        click.echo("Error: Not in a git repository", err=True)
        sys.exit(1)

    # Set up merge driver
    if history.setup_merge_driver():
        click.echo("Initialized betterbeads:")
        click.echo(f"  - Created {bb_dir}")
        click.echo("  - Configured merge driver for history.jsonl")
    else:
        click.echo(f"Created {bb_dir}")
        click.echo("Warning: Could not configure merge driver", err=True)

    # Add workflow instructions to global CLAUDE.md
    if _ensure_global_claude_md():
        click.echo("  - Added workflow instructions to ~/.claude/CLAUDE.md")
    else:
        click.echo("  - Workflow instructions already in ~/.claude/CLAUDE.md")


# =============================================================================
# PR Commands
# =============================================================================


@main.command("pr")
@with_repo_option
@click.argument("number", type=int)
@click.option("--approve", is_flag=True, help="Approve the PR")
@click.option("--request-changes", is_flag=True, help="Request changes")
@click.option("--comment", "comment_text", help="Add a review comment")
@click.option("--merge", "do_merge", is_flag=True, help="Merge the PR")
@click.option("--squash", is_flag=True, help="Squash merge")
@click.option("--rebase", is_flag=True, help="Rebase merge")
@click.option("--delete-branch", is_flag=True, help="Delete branch after merge")
@click.option("--ready", "mark_ready", is_flag=True, help="Mark as ready for review")
@click.option("--title", help="Set PR title")
@click.option("--body", help="Set PR body")
@click.option("--add-labels", help="Add labels (comma-separated)")
@click.option("--remove-labels", help="Remove labels (comma-separated)")
@click.option("--add-assignees", help="Add assignees (comma-separated)")
@click.option("--remove-assignees", help="Remove assignees (comma-separated)")
@click.option("--add-reviewers", help="Add reviewers (comma-separated)")
@click.option("--status", help="Set project status (e.g., 'In Progress', 'Done')")
@click.option("--set-field", "set_fields", multiple=True, help="Set project field (key=value)")
@click.option("--project", "project_name", help="Project name (required if in multiple projects)")
@click.option("--shortcut", "shortcut_name", help="Apply a configured shortcut by name")
@click.option("--diff", "show_diff", is_flag=True, help="Show full diff")
@click.option("--execute", "-x", is_flag=True, help="Execute changes (default is dry-run)")
@click.option("--confirm", is_flag=True, help="Confirm dangerous operations (merge)")
@click.pass_context
def pr_cmd(
    ctx: click.Context,
    number: int,
    approve: bool,
    request_changes: bool,
    comment_text: str | None,
    do_merge: bool,
    squash: bool,
    rebase: bool,
    delete_branch: bool,
    mark_ready: bool,
    title: str | None,
    body: str | None,
    add_labels: str | None,
    remove_labels: str | None,
    add_assignees: str | None,
    remove_assignees: str | None,
    add_reviewers: str | None,
    status: str | None,
    set_fields: tuple[str, ...],
    project_name: str | None,
    shortcut_name: str | None,
    show_diff: bool,
    execute: bool,
    confirm: bool,
) -> None:
    """View or modify a pull request.

    If no modification flags are provided, displays the PR.
    Otherwise, shows a dry-run diff of changes (use --execute to apply).
    """
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    # Handle custom shortcut by name
    config = get_config()
    if shortcut_name:
        shortcut_config = config.shortcuts.get(shortcut_name)
        if not shortcut_config:
            click.echo(f"Error: Unknown shortcut '{shortcut_name}'", err=True)
            click.echo(f"Available shortcuts: {', '.join(config.shortcuts.keys())}", err=True)
            sys.exit(1)
        status = status or shortcut_config.status
        if shortcut_config.assignees and not add_assignees:
            add_assignees = ",".join(shortcut_config.assignees)
        if shortcut_config.labels_add and not add_labels:
            add_labels = ",".join(shortcut_config.labels_add)
        if shortcut_config.labels_remove and not remove_labels:
            remove_labels = ",".join(shortcut_config.labels_remove)

    target_repo = repo or client.get_current_repo()

    # Check if this is a view or modify operation
    is_modification = any([
        approve, request_changes, comment_text, do_merge, mark_ready,
        title, body, add_labels, remove_labels, add_assignees,
        remove_assignees, add_reviewers, status, set_fields, shortcut_name,
    ])

    try:
        # Always fetch current state
        data = client.pr_view(number, repo=repo)
        checks = client.pr_checks(number, repo=repo)
        current_pr = parse_pr_data(data, target_repo, checks)

        if not is_modification:
            # Just viewing
            output = current_pr.to_dict()

            # Optionally include full diff
            if show_diff:
                diff_result = client.run(["pr", "diff", str(number)], repo=repo, check=False)
                if diff_result.success:
                    output["diff"] = diff_result.stdout

            output_json(output)
            return

        # Check for dangerous operations without --confirm
        if do_merge and not confirm:
            click.echo("Error: --merge requires --confirm flag", err=True)
            sys.exit(1)

        # Build the changes
        changes: dict[str, Any] = {}
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}

        if approve:
            changes["review"] = "approve"
        if request_changes:
            changes["review"] = "request_changes"
        if comment_text:
            changes["comment"] = comment_text

        if do_merge:
            merge_method = "squash" if squash else ("rebase" if rebase else "merge")
            changes["merge"] = merge_method
            if delete_branch:
                changes["delete_branch"] = True

        if mark_ready:
            before["draft"] = current_pr.draft
            after["draft"] = False
            changes["ready"] = True

        if title:
            before["title"] = current_pr.title
            after["title"] = title
            changes["title"] = {"from": current_pr.title, "to": title}

        if body is not None:
            before["body"] = current_pr.body
            after["body"] = body
            changes["body"] = {"from": "(current)", "to": "(new)"}

        if add_labels:
            labels_to_add = [l.strip() for l in add_labels.split(",")]
            before["labels"] = current_pr.labels
            new_labels = list(set(current_pr.labels + labels_to_add))
            after["labels"] = new_labels
            changes["labels_added"] = labels_to_add

        if remove_labels:
            labels_to_remove = [l.strip() for l in remove_labels.split(",")]
            before["labels"] = current_pr.labels
            new_labels = [l for l in current_pr.labels if l not in labels_to_remove]
            after["labels"] = new_labels
            changes["labels_removed"] = labels_to_remove

        if add_assignees:
            assignees_to_add = [a.strip() for a in add_assignees.split(",")]
            changes["assignees_added"] = assignees_to_add

        if remove_assignees:
            assignees_to_remove = [a.strip() for a in remove_assignees.split(",")]
            changes["assignees_removed"] = assignees_to_remove

        if add_reviewers:
            reviewers_to_add = [r.strip() for r in add_reviewers.split(",")]
            changes["reviewers_added"] = reviewers_to_add

        # Project status changes
        project_info = None
        if status or set_fields:
            resolver = ProjectResolver(client)
            project_info = resolver.get_project_info_for_pr(number, target_repo, project_name)
            if not project_info:
                if project_name:
                    click.echo(f"Error: PR not found in project '{project_name}'", err=True)
                else:
                    click.echo("Error: PR is not in any project. Add it to a project first.", err=True)
                sys.exit(1)

            # Get current status from project items
            current_status = None
            for pi in current_pr.project_items:
                if pi.project == project_info.project_title:
                    current_status = pi.status
                    break

            if status:
                before["project_status"] = current_status
                after["project_status"] = status
                changes["project_status"] = {"from": current_status, "to": status, "project": project_info.project_title}

            if set_fields:
                parsed_fields = {}
                for field_spec in set_fields:
                    if "=" not in field_spec:
                        click.echo(f"Error: Invalid field format '{field_spec}'. Use key=value.", err=True)
                        sys.exit(1)
                    key, value = field_spec.split("=", 1)
                    parsed_fields[key] = value
                changes["project_fields"] = {"project": project_info.project_title, "fields": parsed_fields}

        # Output dry-run diff
        if not execute:
            output = {
                "dry_run": True,
                "pr": number,
                "repo": target_repo,
                "changes": changes,
            }
            output_json(output)
            click.echo("\nRun with --execute (-x) to apply changes.", err=True)

            # Log dry-run operation
            op = history.create_operation(
                target=target_repo,
                type="pr",
                num=number,
                action="modify",
                before=before,
                after=after,
                dry_run=True,
            )
            history.append_operation(op)
            return

        # Execute changes
        if approve or request_changes:
            client.pr_review(
                number,
                approve=approve,
                request_changes=request_changes,
                body=comment_text,
                repo=repo,
            )
            comment_text = None  # Don't double-comment

        if mark_ready:
            client.pr_ready(number, repo=repo)

        if title or body is not None or add_labels or remove_labels or add_assignees or remove_assignees or add_reviewers:
            # Use gh pr edit for metadata changes
            edit_args = ["pr", "edit", str(number)]
            if title:
                edit_args.extend(["--title", title])
            if body is not None:
                edit_args.extend(["--body", body])
            if add_labels:
                for label in add_labels.split(","):
                    edit_args.extend(["--add-label", label.strip()])
            if remove_labels:
                for label in remove_labels.split(","):
                    edit_args.extend(["--remove-label", label.strip()])
            if add_assignees:
                for assignee in add_assignees.split(","):
                    edit_args.extend(["--add-assignee", assignee.strip()])
            if remove_assignees:
                for assignee in remove_assignees.split(","):
                    edit_args.extend(["--remove-assignee", assignee.strip()])
            if add_reviewers:
                for reviewer in add_reviewers.split(","):
                    edit_args.extend(["--add-reviewer", reviewer.strip()])
            client.run(edit_args, repo=repo)

        if do_merge:
            client.pr_merge(
                number,
                squash=squash,
                rebase=rebase,
                delete_branch=delete_branch,
                repo=repo,
            )

        # Handle project status changes
        if project_info and status:
            resolver = ProjectResolver(client)
            resolver.set_status(project_info, status)

        if project_info and set_fields:
            resolver = ProjectResolver(client)
            for field_spec in set_fields:
                key, value = field_spec.split("=", 1)
                resolver.set_field(project_info, key, value)

        # Log executed operation
        op = history.create_operation(
            target=target_repo,
            type="pr",
            num=number,
            action="modify",
            before=before,
            after=after,
            dry_run=False,
        )
        history.append_operation(op)

        # Output result
        output = {
            "executed": True,
            "pr": number,
            "repo": target_repo,
            "url": current_pr.url,
            "changes": changes,
            "operation_id": op.id,
        }
        output_json(output)

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("prs")
@with_repo_option
@click.option("--state", type=click.Choice(["open", "closed", "merged", "all"]), default="open")
@click.option("--label", "-l", "labels", multiple=True, help="Filter by label")
@click.option("--assignee", "-a", help="Filter by assignee")
@click.option("--author", help="Filter by author")
@click.option("--mine", is_flag=True, help="Show only my PRs")
@click.option("--review-requested", is_flag=True, help="Show PRs where my review is requested")
@click.option("--limit", default=30, help="Maximum number of PRs")
@click.option("--draft", is_flag=True, help="Show only draft PRs")
@click.option("--ready", is_flag=True, help="Show only ready (non-draft) PRs")
@click.pass_context
def prs_cmd(
    ctx: click.Context,
    state: str,
    labels: tuple[str, ...],
    assignee: str | None,
    author: str | None,
    mine: bool,
    review_requested: bool,
    limit: int,
    draft: bool,
    ready: bool,
) -> None:
    """List pull requests."""
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    if mine:
        author = "@me"

    try:
        data = client.pr_list(
            state=state,
            labels=list(labels) if labels else None,
            assignee=assignee,
            author=author,
            limit=limit,
            repo=repo,
        )

        # Parse into models for filtering
        target_repo = repo or client.get_current_repo()
        prs = []
        for item in data:
            pr = parse_pr_data(item, target_repo)

            # Apply draft/ready filters
            if draft and not pr.draft:
                continue
            if ready and pr.draft:
                continue

            prs.append(pr)

        output_json([pr.to_dict() for pr in prs])

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("pr-create")
@with_repo_option
@click.argument("title")
@click.option("--body", "-b", default="", help="PR body")
@click.option("--base", help="Base branch (default: repo default)")
@click.option("--draft", is_flag=True, help="Create as draft")
@click.option("--labels", "-l", help="Labels (comma-separated)")
@click.option("--assignees", "-a", help="Assignees (comma-separated)")
@click.option("--reviewers", "-r", help="Reviewers (comma-separated)")
@click.option("--milestone", "-m", help="Milestone")
@click.option("--closes", help="Issue numbers this PR closes (comma-separated)")
@click.option("--execute", "-x", is_flag=True, help="Execute (default is dry-run)")
@click.pass_context
def pr_create_cmd(
    ctx: click.Context,
    title: str,
    body: str,
    base: str | None,
    draft: bool,
    labels: str | None,
    assignees: str | None,
    reviewers: str | None,
    milestone: str | None,
    closes: str | None,
    execute: bool,
) -> None:
    """Create a new pull request."""
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    # Add "Closes #X" to body if specified
    if closes:
        close_refs = []
        for num in closes.split(","):
            close_refs.append(f"Closes #{num.strip()}")
        if body:
            body = body + "\n\n" + "\n".join(close_refs)
        else:
            body = "\n".join(close_refs)

    # Parse options
    labels_list = [l.strip() for l in labels.split(",")] if labels else None
    assignees_list = [a.strip() for a in assignees.split(",")] if assignees else None
    reviewers_list = [r.strip() for r in reviewers.split(",")] if reviewers else None

    target_repo = repo or client.get_current_repo()

    if not execute:
        output = {
            "dry_run": True,
            "action": "create_pr",
            "repo": target_repo,
            "title": title,
            "body": body,
            "base": base,
            "draft": draft,
            "labels": labels_list,
            "assignees": assignees_list,
            "reviewers": reviewers_list,
            "milestone": milestone,
        }
        output_json(output)
        click.echo("\nRun with --execute (-x) to create the PR.", err=True)
        return

    try:
        result = client.pr_create(
            title=title,
            body=body,
            base=base,
            draft=draft,
            labels=labels_list,
            assignees=assignees_list,
            reviewers=reviewers_list,
            milestone=milestone,
            repo=repo,
        )

        # Log operation
        op = history.create_operation(
            target=target_repo,
            type="pr",
            num=result["number"],
            action="create",
            before={},
            after={
                "title": title,
                "body": body,
                "draft": draft,
                "labels": labels_list,
                "assignees": assignees_list,
                "reviewers": reviewers_list,
            },
            dry_run=False,
        )
        history.append_operation(op)

        output = {
            "created": True,
            "pr": result["number"],
            "url": result["url"],
            "repo": target_repo,
            "operation_id": op.id,
        }
        output_json(output)

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


@main.command("next")
@with_repo_option
@click.option("--label", "-l", "labels", multiple=True, help="Filter by label")
@click.option("--assignee", "-a", help="Filter by assignee (use @me for self)")
@click.option("--status", help="Set project status (default from 'start' shortcut or 'In Progress')")
@click.option("--shortcut", "shortcut_name", default="start", help="Shortcut to apply (default: start)")
@click.option("--execute", "-x", is_flag=True, help="Execute (default is dry-run)")
@click.pass_context
def next_cmd(
    ctx: click.Context,
    labels: tuple[str, ...],
    assignee: str | None,
    status: str | None,
    shortcut_name: str,
    execute: bool,
) -> None:
    """Start working on the next available issue.

    Finds issues that are ready (open, not blocked, no incomplete dependencies)
    and applies the 'start' shortcut to begin work on one.
    """
    token = ctx.obj.get("token")
    repo = ctx.obj.get("repo")
    client = get_client(token, repo)

    target_repo = repo or client.get_current_repo()

    try:
        # Fetch open issues
        data = client.issue_list(
            state="open",
            labels=list(labels) if labels else None,
            assignee=assignee,
            limit=50,  # Fetch enough to find ready issues
            repo=repo,
        )

        # Parse and filter to ready issues only
        ready_issues = []
        for item in data:
            issue = parse_issue_data(item, target_repo)
            if issue.ready:
                ready_issues.append(issue)

        if not ready_issues:
            output = {
                "found": False,
                "message": "No ready issues found",
                "filters": {
                    "labels": list(labels) if labels else None,
                    "assignee": assignee,
                },
            }
            output_json(output)
            click.echo("\nNo issues are ready to work on.", err=True)
            sys.exit(0)

        # Select the first ready issue (oldest by default from API)
        selected = ready_issues[0]

        # Load shortcut configuration
        config = get_config()
        shortcut_config = config.shortcuts.get(shortcut_name)

        # Build changes based on shortcut
        add_assignees: str | None = None
        add_labels: str | None = None
        do_close = False

        if shortcut_config:
            status = status or shortcut_config.status
            if shortcut_config.assignees:
                add_assignees = ",".join(shortcut_config.assignees)
            if shortcut_config.labels_add:
                add_labels = ",".join(shortcut_config.labels_add)
            if shortcut_config.close:
                do_close = True
        else:
            # Default "start" behavior
            status = status or "In Progress"
            add_assignees = "@me"

        # Build changes dict for output
        changes: dict[str, Any] = {}
        before: dict[str, Any] = {}
        after: dict[str, Any] = {}

        if status:
            # Get current status from project items
            current_status = None
            for pi in selected.project_items:
                current_status = pi.status
                break
            before["project_status"] = current_status
            after["project_status"] = status
            changes["project_status"] = {"from": current_status, "to": status}

        if add_assignees:
            assignees_to_add = [a.strip() for a in add_assignees.split(",")]
            before["assignees"] = selected.assignees
            new_assignees = list(set(selected.assignees + assignees_to_add))
            after["assignees"] = new_assignees
            changes["assignees_added"] = assignees_to_add

        if add_labels:
            labels_to_add = [l.strip() for l in add_labels.split(",")]
            before["labels"] = selected.labels
            new_labels = list(set(selected.labels + labels_to_add))
            after["labels"] = new_labels
            changes["labels_added"] = labels_to_add

        if do_close:
            before["state"] = selected.state
            after["state"] = "closed"
            changes["state"] = {"from": selected.state, "to": "closed"}

        # Dry-run output
        if not execute:
            output = {
                "dry_run": True,
                "selected_issue": {
                    "number": selected.number,
                    "title": selected.title,
                    "url": selected.url,
                    "labels": selected.labels,
                    "assignees": selected.assignees,
                },
                "repo": target_repo,
                "shortcut": shortcut_name,
                "changes": changes,
                "ready_count": len(ready_issues),
            }
            output_json(output)
            click.echo("\nRun with --execute (-x) to start working on this issue.", err=True)

            # Log dry-run
            op = history.create_operation(
                target=target_repo,
                type="issue",
                num=selected.number,
                action="next",
                before=before,
                after=after,
                dry_run=True,
            )
            history.append_operation(op)
            return

        # Execute changes
        if add_labels or add_assignees:
            client.issue_edit(
                selected.number,
                add_labels=[l.strip() for l in add_labels.split(",")] if add_labels else None,
                add_assignees=[a.strip() for a in add_assignees.split(",")] if add_assignees else None,
                repo=repo,
            )

        if do_close:
            client.issue_close(selected.number, repo=repo)

        # Handle project status changes
        if status:
            resolver = ProjectResolver(client)
            project_info = resolver.get_project_info_for_issue(selected.number, target_repo, None)
            if project_info:
                resolver.set_status(project_info, status)
                changes["project"] = project_info.project_title

        # Log executed operation
        op = history.create_operation(
            target=target_repo,
            type="issue",
            num=selected.number,
            action="next",
            before=before,
            after=after,
            dry_run=False,
        )
        history.append_operation(op)

        output = {
            "executed": True,
            "selected_issue": {
                "number": selected.number,
                "title": selected.title,
                "url": selected.url,
            },
            "repo": target_repo,
            "changes": changes,
            "operation_id": op.id,
        }
        output_json(output)

    except GhError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.returncode)


# =============================================================================
# Hook Commands (for Claude Code integration)
# =============================================================================


@main.group("hook")
def hook_group() -> None:
    """Claude Code hook commands.

    These commands are designed to be called from Claude Code hooks.
    They read hook input from stdin and output markdown for the agent.
    """
    pass


@hook_group.command("session-start")
@with_repo_option
@click.pass_context
def hook_session_start(ctx: click.Context) -> None:
    """SessionStart hook - show open issues and guidance.

    Reads hook input JSON from stdin, outputs markdown to stdout.
    """
    import shutil

    # Read hook input from stdin
    hook_input = {}
    if not sys.stdin.isatty():
        try:
            hook_input = json.load(sys.stdin)
        except json.JSONDecodeError:
            pass

    cwd = hook_input.get("cwd", ".")

    # Get repo from context (--repo option) or auto-detect
    repo = ctx.obj.get("repo")
    from .gh import GhClient
    client = GhClient(repo=repo)

    if repo:
        repo_name = repo
    else:
        try:
            repo_name = client.get_current_repo()
        except Exception:
            # Not a GitHub repo, exit silently
            sys.exit(0)

    if not repo_name:
        sys.exit(0)

    # Check if bb is properly available (sanity check)
    bb_installed = shutil.which("bb") is not None

    # Get open issues
    all_issues = []
    ready_issues = []

    try:
        data = client.issue_list(state="open", limit=20)
        for item in data:
            issue = parse_issue_data(item, repo_name)
            all_issues.append(issue)
            if issue.ready:
                ready_issues.append(issue)
    except Exception:
        pass

    # Build output
    lines = [f"## GitHub Context for {repo_name}"]
    lines.append("")
    lines.append("**ALWAYS use `bb` for all GitHub operations** (issues, PRs, projects) - never use `gh` directly.")
    lines.append("")

    # Add installation instructions if bb is not installed
    if not bb_installed:
        lines.extend([
            "### Installation Required",
            "",
            "The `bb` command is not installed. Install it with:",
            "",
            "```bash",
            "uv tool install git+https://github.com/falense/betterbeads",
            "```",
            "",
            "Or for local development (from the betterbeads repo):",
            "```bash",
            "uv tool install --force --editable .",
            "```",
            "",
        ])

    lines.append("### Issue Requirement")
    lines.append("**All work must have an accompanying GitHub issue.**")
    lines.append("- Before starting ANY work, identify or create the relevant issue")
    lines.append("- If no issue exists, create one with `bb create`")
    lines.append("- Reference the issue number in commits")
    lines.append("")

    if not all_issues:
        lines.append("No open issues found.")
        lines.append("")
        click.echo("\n".join(lines))
        sys.exit(0)

    if ready_issues:
        lines.append(f"### Ready for Work ({len(ready_issues)} issues)")
        lines.append("These issues have no blockers and all dependencies are complete:")
        lines.append("")
        for issue in ready_issues:
            lines.append(_format_issue_for_hook(issue))
            lines.append("")

    # Show other open issues
    ready_numbers = {i.number for i in ready_issues}
    other_issues = [i for i in all_issues if i.number not in ready_numbers]

    if other_issues:
        lines.append(f"### Other Open Issues ({len(other_issues)} issues)")
        lines.append("")
        for issue in other_issues[:10]:
            lines.append(_format_issue_for_hook(issue))
            lines.append("")

    total = len(all_issues)
    if total > 20:
        lines.append(f"... and {total - 20} more open issues")

    click.echo("\n".join(lines))
    sys.exit(0)


@hook_group.command("session-stop")
@with_repo_option
@click.pass_context
def hook_session_stop(ctx: click.Context) -> None:
    """Stop hook - prompt to continue working on ready issues.

    Only outputs if enabled in .betterbeads/config.json:
    {"hooks": {"session_stop": {"enabled": true}}}
    """
    # Read hook input from stdin
    hook_input = {}
    if not sys.stdin.isatty():
        try:
            hook_input = json.load(sys.stdin)
        except json.JSONDecodeError:
            pass

    cwd = hook_input.get("cwd", ".")

    # Load config and check if hook is enabled
    config = get_config()
    hooks_config = config.raw.get("hooks", {}) if hasattr(config, "raw") else {}
    session_stop_config = hooks_config.get("session_stop", {})
    if not session_stop_config.get("enabled", False):
        sys.exit(0)

    # Get repo from context (--repo option) or auto-detect
    repo = ctx.obj.get("repo")
    from .gh import GhClient
    client = GhClient(repo=repo)

    if repo:
        repo_name = repo
    else:
        try:
            repo_name = client.get_current_repo()
        except Exception:
            sys.exit(0)

    if not repo_name:
        sys.exit(0)

    # Get ready issues
    ready_issues = []
    try:
        data = client.issue_list(state="open", limit=10)
        for item in data:
            issue = parse_issue_data(item, repo_name)
            if issue.ready:
                ready_issues.append(issue)
    except Exception:
        pass

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
    for issue in ready_issues[:5]:
        lines.append(f"  - #{issue.number}: {issue.title}")
    lines.append("")
    lines.append("Use `bb issue <number>` to view details and continue working.")
    lines.append("")

    click.echo("\n".join(lines))
    sys.exit(0)


def _format_issue_for_hook(issue: Issue) -> str:
    """Format an issue for hook output."""
    parts = [f"#{issue.number}: {issue.title}"]
    if issue.labels:
        parts.append(f"  Labels: {', '.join(issue.labels)}")
    if issue.assignees:
        parts.append(f"  Assigned: {', '.join(issue.assignees)}")
    return "\n".join(parts)


if __name__ == "__main__":
    main()
