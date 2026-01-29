"""Wrapper around the gh CLI."""

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any


class GhError(Exception):
    """Error from gh CLI."""

    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


@dataclass
class GhResult:
    """Result from gh command."""

    stdout: str
    stderr: str
    returncode: int

    @property
    def success(self) -> bool:
        return self.returncode == 0

    def json(self) -> Any:
        """Parse stdout as JSON."""
        return json.loads(self.stdout)


class GhClient:
    """Client for executing gh commands."""

    def __init__(self, token: str | None = None, repo: str | None = None):
        """Initialize the gh client.

        Args:
            token: Optional GitHub token. If not provided, uses gh auth.
            repo: Optional repo in owner/repo format. If not provided, uses current repo.
        """
        self.token = token
        self.repo = repo
        self._check_gh_installed()

    def _check_gh_installed(self) -> None:
        """Check that gh CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise GhError("gh CLI not found. Install from https://cli.github.com/")
        except FileNotFoundError:
            raise GhError("gh CLI not found. Install from https://cli.github.com/")

    def _get_env(self) -> dict[str, str]:
        """Get environment for gh commands."""
        env = os.environ.copy()
        if self.token:
            env["GH_TOKEN"] = self.token
        return env

    def _get_repo_args(self, repo: str | None = None) -> list[str]:
        """Get repo arguments for gh command."""
        target_repo = repo or self.repo
        if target_repo:
            return ["--repo", target_repo]
        return []

    def run(
        self,
        args: list[str],
        repo: str | None = None,
        check: bool = True,
    ) -> GhResult:
        """Run a gh command.

        Args:
            args: Command arguments (without 'gh' prefix)
            repo: Optional repo override
            check: If True, raise GhError on non-zero exit

        Returns:
            GhResult with stdout, stderr, returncode
        """
        cmd = ["gh"] + args + self._get_repo_args(repo)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=self._get_env(),
        )

        gh_result = GhResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

        if check and not gh_result.success:
            raise GhError(result.stderr.strip() or result.stdout.strip(), result.returncode)

        return gh_result

    def get_current_repo(self) -> str:
        """Get the current repository from git remote."""
        result = self.run(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        return result.stdout.strip()

    # Issue operations

    def issue_view(self, number: int, repo: str | None = None) -> dict[str, Any]:
        """Get issue data."""
        fields = [
            "number",
            "url",
            "title",
            "body",
            "state",
            "author",
            "createdAt",
            "updatedAt",
            "labels",
            "assignees",
            "milestone",
            "comments",
            "projectItems",
        ]
        result = self.run(
            ["issue", "view", str(number), "--json", ",".join(fields)],
            repo=repo,
        )
        return result.json()

    def issue_list(
        self,
        state: str = "open",
        labels: list[str] | None = None,
        assignee: str | None = None,
        limit: int = 30,
        repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """List issues."""
        args = [
            "issue",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,url,title,body,state,labels,assignees,author,createdAt,updatedAt",
        ]
        if labels:
            for label in labels:
                args.extend(["--label", label])
        if assignee:
            args.extend(["--assignee", assignee])

        result = self.run(args, repo=repo)
        return result.json()

    def issue_create(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: str | None = None,
        project: str | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Create an issue."""
        args = ["issue", "create", "--title", title, "--body", body]
        if labels:
            for label in labels:
                args.extend(["--label", label])
        if assignees:
            for assignee in assignees:
                args.extend(["--assignee", assignee])
        if milestone:
            args.extend(["--milestone", milestone])
        if project:
            args.extend(["--project", project])

        result = self.run(args, repo=repo)
        # gh issue create returns the URL, we need to parse the number
        url = result.stdout.strip()
        number = int(url.rstrip("/").split("/")[-1])
        return {"number": number, "url": url}

    def issue_edit(
        self,
        number: int,
        title: str | None = None,
        body: str | None = None,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
        add_assignees: list[str] | None = None,
        remove_assignees: list[str] | None = None,
        milestone: str | None = None,
        repo: str | None = None,
    ) -> GhResult:
        """Edit an issue."""
        args = ["issue", "edit", str(number)]
        if title:
            args.extend(["--title", title])
        if body is not None:
            args.extend(["--body", body])
        if add_labels:
            for label in add_labels:
                args.extend(["--add-label", label])
        if remove_labels:
            for label in remove_labels:
                args.extend(["--remove-label", label])
        if add_assignees:
            for assignee in add_assignees:
                args.extend(["--add-assignee", assignee])
        if remove_assignees:
            for assignee in remove_assignees:
                args.extend(["--remove-assignee", assignee])
        if milestone:
            args.extend(["--milestone", milestone])

        return self.run(args, repo=repo)

    def issue_close(
        self,
        number: int,
        reason: str | None = None,
        comment: str | None = None,
        repo: str | None = None,
    ) -> GhResult:
        """Close an issue."""
        args = ["issue", "close", str(number)]
        if reason:
            args.extend(["--reason", reason])
        if comment:
            args.extend(["--comment", comment])
        return self.run(args, repo=repo)

    def issue_reopen(
        self,
        number: int,
        comment: str | None = None,
        repo: str | None = None,
    ) -> GhResult:
        """Reopen an issue."""
        args = ["issue", "reopen", str(number)]
        if comment:
            args.extend(["--comment", comment])
        return self.run(args, repo=repo)

    def issue_comment(
        self,
        number: int,
        body: str,
        repo: str | None = None,
    ) -> GhResult:
        """Add a comment to an issue."""
        return self.run(
            ["issue", "comment", str(number), "--body", body],
            repo=repo,
        )

    def comment_edit(
        self,
        comment_id: int,
        body: str,
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Edit an issue comment using GraphQL.

        Args:
            comment_id: The numeric ID of the comment (from IC_kwXXXX)
            body: New body content
            repo: Repository (unused, but kept for consistency)

        Returns:
            Dict with updated comment info
        """
        # Convert numeric ID to GraphQL node ID format
        # GitHub issue comment IDs start with IC_ prefix
        # The GraphQL ID is base64 of "012:IssueComment{id}"
        import base64

        node_id = base64.b64encode(f"012:IssueComment{comment_id}".encode()).decode()

        query = """
        mutation($id: ID!, $body: String!) {
          updateIssueComment(input: {id: $id, body: $body}) {
            issueComment {
              id
              body
            }
          }
        }
        """

        result = self.run(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"id={node_id}",
                "-f",
                f"body={body}",
            ]
        )
        data = result.json()
        return data.get("data", {}).get("updateIssueComment", {}).get("issueComment", {})

    # PR operations

    def pr_view(self, number: int, repo: str | None = None) -> dict[str, Any]:
        """Get PR data."""
        fields = [
            "number",
            "url",
            "title",
            "body",
            "state",
            "isDraft",
            "author",
            "createdAt",
            "updatedAt",
            "baseRefName",
            "headRefName",
            "mergeable",
            "labels",
            "assignees",
            "reviewRequests",
            "reviews",
            "comments",
            "milestone",
            "projectItems",
            "additions",
            "deletions",
            "changedFiles",
        ]
        result = self.run(
            ["pr", "view", str(number), "--json", ",".join(fields)],
            repo=repo,
        )
        return result.json()

    def pr_checks(self, number: int, repo: str | None = None) -> list[dict[str, Any]]:
        """Get PR check status."""
        result = self.run(
            ["pr", "checks", str(number), "--json", "name,state,conclusion,detailsUrl"],
            repo=repo,
            check=False,  # May fail if no checks
        )
        if result.success:
            return result.json()
        return []

    def pr_list(
        self,
        state: str = "open",
        labels: list[str] | None = None,
        assignee: str | None = None,
        author: str | None = None,
        limit: int = 30,
        repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """List pull requests."""
        args = [
            "pr",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,url,title,state,isDraft,author,labels,assignees,createdAt,updatedAt,baseRefName,headRefName",
        ]
        if labels:
            for label in labels:
                args.extend(["--label", label])
        if assignee:
            args.extend(["--assignee", assignee])
        if author:
            args.extend(["--author", author])

        result = self.run(args, repo=repo)
        return result.json()

    def pr_create(
        self,
        title: str,
        body: str = "",
        base: str | None = None,
        draft: bool = False,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        reviewers: list[str] | None = None,
        milestone: str | None = None,
        project: str | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        """Create a pull request."""
        args = ["pr", "create", "--title", title, "--body", body]
        if base:
            args.extend(["--base", base])
        if draft:
            args.append("--draft")
        if labels:
            for label in labels:
                args.extend(["--label", label])
        if assignees:
            for assignee in assignees:
                args.extend(["--assignee", assignee])
        if reviewers:
            for reviewer in reviewers:
                args.extend(["--reviewer", reviewer])
        if milestone:
            args.extend(["--milestone", milestone])
        if project:
            args.extend(["--project", project])

        result = self.run(args, repo=repo)
        url = result.stdout.strip()
        number = int(url.rstrip("/").split("/")[-1])
        return {"number": number, "url": url}

    def pr_review(
        self,
        number: int,
        approve: bool = False,
        request_changes: bool = False,
        comment: bool = False,
        body: str | None = None,
        repo: str | None = None,
    ) -> GhResult:
        """Review a pull request."""
        args = ["pr", "review", str(number)]
        if approve:
            args.append("--approve")
        elif request_changes:
            args.append("--request-changes")
        elif comment:
            args.append("--comment")
        if body:
            args.extend(["--body", body])
        return self.run(args, repo=repo)

    def pr_merge(
        self,
        number: int,
        squash: bool = False,
        rebase: bool = False,
        delete_branch: bool = False,
        repo: str | None = None,
    ) -> GhResult:
        """Merge a pull request."""
        args = ["pr", "merge", str(number)]
        if squash:
            args.append("--squash")
        elif rebase:
            args.append("--rebase")
        else:
            args.append("--merge")
        if delete_branch:
            args.append("--delete-branch")
        return self.run(args, repo=repo)

    def pr_ready(self, number: int, repo: str | None = None) -> GhResult:
        """Mark a PR as ready for review."""
        return self.run(["pr", "ready", str(number)], repo=repo)

    # Search

    def search_issues(
        self,
        query: str,
        limit: int = 30,
        repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search issues."""
        target_repo = repo or self.repo
        full_query = query
        if target_repo:
            full_query = f"repo:{target_repo} {query}"

        result = self.run(
            [
                "search",
                "issues",
                full_query,
                "--limit",
                str(limit),
                "--json",
                "number,url,title,state,labels,repository",
            ]
        )
        return result.json()

    def search_prs(
        self,
        query: str,
        limit: int = 30,
        repo: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search pull requests."""
        target_repo = repo or self.repo
        full_query = f"is:pr {query}"
        if target_repo:
            full_query = f"repo:{target_repo} {full_query}"

        result = self.run(
            [
                "search",
                "prs",
                full_query,
                "--limit",
                str(limit),
                "--json",
                "number,url,title,state,labels,repository",
            ]
        )
        return result.json()

    # Project operations

    def project_item_add(
        self,
        project: str,
        url: str,
        owner: str | None = None,
    ) -> GhResult:
        """Add an item to a project."""
        args = ["project", "item-add", project, "--url", url]
        if owner:
            args.extend(["--owner", owner])
        return self.run(args)

    def project_list(
        self,
        owner: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """List projects for an owner."""
        result = self.run(
            ["project", "list", "--owner", owner, "--limit", str(limit), "--format", "json"]
        )
        data = result.json()
        return data.get("projects", [])

    def project_view(
        self,
        number: int,
        owner: str,
    ) -> dict[str, Any]:
        """Get project details."""
        result = self.run(
            ["project", "view", str(number), "--owner", owner, "--format", "json"]
        )
        return result.json()

    def project_field_list(
        self,
        number: int,
        owner: str,
    ) -> list[dict[str, Any]]:
        """List fields in a project."""
        result = self.run(
            ["project", "field-list", str(number), "--owner", owner, "--format", "json"]
        )
        data = result.json()
        return data.get("fields", [])

    def project_item_list(
        self,
        number: int,
        owner: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List items in a project."""
        result = self.run(
            ["project", "item-list", str(number), "--owner", owner, "--limit", str(limit), "--format", "json"]
        )
        data = result.json()
        return data.get("items", [])

    def project_item_edit(
        self,
        item_id: str,
        project_id: str,
        field_id: str,
        value: str | None = None,
        single_select_option_id: str | None = None,
        number_value: float | None = None,
        date_value: str | None = None,
        iteration_id: str | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Edit a project item field.

        Args:
            item_id: The ID of the item to edit
            project_id: The ID of the project
            field_id: The ID of the field to update
            value: Text value for text fields
            single_select_option_id: Option ID for single-select fields (like Status)
            number_value: Number value for number fields
            date_value: Date value (YYYY-MM-DD) for date fields
            iteration_id: Iteration ID for iteration fields
            clear: If True, clear the field value
        """
        args = [
            "project", "item-edit",
            "--id", item_id,
            "--project-id", project_id,
            "--field-id", field_id,
            "--format", "json",
        ]
        if clear:
            args.append("--clear")
        elif single_select_option_id:
            args.extend(["--single-select-option-id", single_select_option_id])
        elif value:
            args.extend(["--text", value])
        elif number_value is not None:
            args.extend(["--number", str(number_value)])
        elif date_value:
            args.extend(["--date", date_value])
        elif iteration_id:
            args.extend(["--iteration-id", iteration_id])

        result = self.run(args)
        return result.json()
