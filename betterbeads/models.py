"""Data models for ght."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class User:
    """GitHub user."""

    login: str
    name: str | None = None


@dataclass
class Milestone:
    """GitHub milestone."""

    title: str
    due_on: str | None = None


@dataclass
class Comment:
    """Issue or PR comment."""

    id: int
    author: str
    body: str
    created_at: str


@dataclass
class Dependency:
    """Issue dependency from task list."""

    number: int
    repo: str | None = None  # None means same repo
    complete: bool = False
    # Enriched fields (filled when fetching full context)
    title: str | None = None
    state: str | None = None
    blocked: bool = False


@dataclass
class Dependent:
    """Issue that depends on this one."""

    number: int
    repo: str | None = None
    title: str | None = None
    state: str | None = None


@dataclass
class LinkedPR:
    """PR linked to an issue."""

    number: int
    title: str
    state: str
    author: str | None = None


@dataclass
class ProjectItem:
    """Issue/PR status in a project."""

    project: str
    status: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class BlockedStatus:
    """Whether an issue is blocked and why."""

    directly: bool = False
    by_dependencies: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class Issue:
    """GitHub issue with full context."""

    number: int
    url: str
    title: str
    body: str
    state: str
    author: User
    created_at: str
    updated_at: str

    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    milestone: Milestone | None = None

    comments: list[Comment] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    dependents: list[Dependent] = field(default_factory=list)
    linked_prs: list[LinkedPR] = field(default_factory=list)
    project_items: list[ProjectItem] = field(default_factory=list)

    blocked: BlockedStatus = field(default_factory=BlockedStatus)
    ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "type": "issue",
            "number": self.number,
            "url": self.url,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "author": {"login": self.author.login, "name": self.author.name},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "labels": self.labels,
            "assignees": self.assignees,
            "milestone": (
                {"title": self.milestone.title, "due_on": self.milestone.due_on}
                if self.milestone
                else None
            ),
            "comments": [
                {
                    "id": c.id,
                    "author": c.author,
                    "body": c.body,
                    "created_at": c.created_at,
                }
                for c in self.comments
            ],
            "dependencies": [
                {
                    "number": d.number,
                    "repo": d.repo,
                    "complete": d.complete,
                    "title": d.title,
                    "state": d.state,
                    "blocked": d.blocked,
                }
                for d in self.dependencies
            ],
            "dependents": [
                {
                    "number": d.number,
                    "repo": d.repo,
                    "title": d.title,
                    "state": d.state,
                }
                for d in self.dependents
            ],
            "linked_prs": [
                {
                    "number": p.number,
                    "title": p.title,
                    "state": p.state,
                    "author": p.author,
                }
                for p in self.linked_prs
            ],
            "project_items": [
                {"project": p.project, "status": p.status, "fields": p.fields}
                for p in self.project_items
            ],
            "blocked": {
                "directly": self.blocked.directly,
                "by_dependencies": self.blocked.by_dependencies,
                "reasons": self.blocked.reasons,
            },
            "ready": self.ready,
        }


@dataclass
class Review:
    """PR review."""

    author: str
    state: str
    body: str | None
    submitted_at: str


@dataclass
class CheckItem:
    """CI check item."""

    name: str
    status: str
    conclusion: str | None = None
    url: str | None = None


@dataclass
class CheckStatus:
    """Overall CI check status."""

    status: str  # "success", "failure", "pending"
    items: list[CheckItem] = field(default_factory=list)


@dataclass
class DiffStats:
    """PR diff statistics."""

    additions: int
    deletions: int
    changed_files: int


@dataclass
class PR:
    """GitHub pull request with full context."""

    number: int
    url: str
    title: str
    body: str
    state: str
    draft: bool
    author: User
    created_at: str
    updated_at: str

    base: str
    head: str
    mergeable: bool | None = None

    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    milestone: Milestone | None = None

    reviews: list[Review] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    checks: CheckStatus = field(default_factory=lambda: CheckStatus(status="unknown"))
    diff_stats: DiffStats = field(default_factory=lambda: DiffStats(0, 0, 0))

    closes_issues: list[int] = field(default_factory=list)
    project_items: list[ProjectItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "type": "pr",
            "number": self.number,
            "url": self.url,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "draft": self.draft,
            "author": {"login": self.author.login, "name": self.author.name},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "base": self.base,
            "head": self.head,
            "mergeable": self.mergeable,
            "labels": self.labels,
            "assignees": self.assignees,
            "reviewers": self.reviewers,
            "milestone": (
                {"title": self.milestone.title, "due_on": self.milestone.due_on}
                if self.milestone
                else None
            ),
            "reviews": [
                {
                    "author": r.author,
                    "state": r.state,
                    "body": r.body,
                    "submitted_at": r.submitted_at,
                }
                for r in self.reviews
            ],
            "comments": [
                {
                    "id": c.id,
                    "author": c.author,
                    "body": c.body,
                    "created_at": c.created_at,
                }
                for c in self.comments
            ],
            "checks": {
                "status": self.checks.status,
                "items": [
                    {
                        "name": c.name,
                        "status": c.status,
                        "conclusion": c.conclusion,
                        "url": c.url,
                    }
                    for c in self.checks.items
                ],
            },
            "diff_stats": {
                "additions": self.diff_stats.additions,
                "deletions": self.diff_stats.deletions,
                "changed_files": self.diff_stats.changed_files,
            },
            "closes_issues": self.closes_issues,
            "project_items": [
                {"project": p.project, "status": p.status, "fields": p.fields}
                for p in self.project_items
            ],
        }


@dataclass
class Operation:
    """Recorded operation for transaction log."""

    id: str
    ts: str
    target: str  # owner/repo
    type: str  # "issue" or "pr"
    num: int
    action: str
    before: dict[str, Any]
    after: dict[str, Any]

    def to_json_line(self) -> str:
        """Convert to single-line JSON for log."""
        import json

        return json.dumps(
            {
                "id": self.id,
                "ts": self.ts,
                "target": self.target,
                "type": self.type,
                "num": self.num,
                "action": self.action,
                "before": self.before,
                "after": self.after,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json_line(cls, line: str) -> "Operation":
        """Parse from JSON line."""
        import json

        data = json.loads(line)
        return cls(
            id=data["id"],
            ts=data["ts"],
            target=data["target"],
            type=data["type"],
            num=data["num"],
            action=data["action"],
            before=data["before"],
            after=data["after"],
        )
