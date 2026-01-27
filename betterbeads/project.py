"""Project status management helpers."""

from dataclasses import dataclass
from typing import Any

from .gh import GhClient, GhError


@dataclass
class ProjectInfo:
    """Information about a project and item needed for updates."""

    project_id: str
    project_number: int
    project_title: str
    item_id: str
    owner: str


@dataclass
class FieldInfo:
    """Information about a project field."""

    field_id: str
    name: str
    field_type: str
    options: list[dict[str, str]] | None = None  # For single-select fields


class ProjectResolver:
    """Resolves project and field information for status updates."""

    def __init__(self, client: GhClient):
        self.client = client
        self._project_cache: dict[str, dict[str, Any]] = {}
        self._field_cache: dict[int, list[dict[str, Any]]] = {}

    def get_project_info_for_issue(
        self,
        issue_number: int,
        repo: str,
        project_title: str | None = None,
    ) -> ProjectInfo | None:
        """Get project info for an issue.

        Args:
            issue_number: The issue number
            repo: The repo in owner/repo format
            project_title: Optional project title to filter by

        Returns:
            ProjectInfo if found, None otherwise
        """
        owner = repo.split("/")[0]

        # Get issue's project items
        issue_data = self.client.issue_view(issue_number, repo=repo)
        project_items = issue_data.get("projectItems", [])

        if not project_items:
            return None

        # Find matching project
        target_project = None
        for item in project_items:
            title = item.get("title") or item.get("project", {}).get("title", "")
            if project_title is None or title == project_title:
                target_project = item
                break

        if not target_project:
            return None

        project_title_found = target_project.get("title") or target_project.get("project", {}).get("title", "")

        # Find project number by listing projects
        projects = self.client.project_list(owner)
        project_data = None
        for proj in projects:
            if proj.get("title") == project_title_found:
                project_data = proj
                break

        if not project_data:
            return None

        project_number = project_data.get("number")
        project_id = project_data.get("id")

        # Find item ID by listing project items
        items = self.client.project_item_list(project_number, owner)
        item_id = None
        for item in items:
            content = item.get("content", {})
            if (
                content.get("number") == issue_number
                and content.get("repository") == repo
            ):
                item_id = item.get("id")
                break

        if not item_id:
            return None

        return ProjectInfo(
            project_id=project_id,
            project_number=project_number,
            project_title=project_title_found,
            item_id=item_id,
            owner=owner,
        )

    def get_project_info_for_pr(
        self,
        pr_number: int,
        repo: str,
        project_title: str | None = None,
    ) -> ProjectInfo | None:
        """Get project info for a PR. Same logic as issues."""
        owner = repo.split("/")[0]

        # Get PR's project items
        pr_data = self.client.pr_view(pr_number, repo=repo)
        project_items = pr_data.get("projectItems", [])

        if not project_items:
            return None

        # Find matching project
        target_project = None
        for item in project_items:
            title = item.get("title") or item.get("project", {}).get("title", "")
            if project_title is None or title == project_title:
                target_project = item
                break

        if not target_project:
            return None

        project_title_found = target_project.get("title") or target_project.get("project", {}).get("title", "")

        # Find project number by listing projects
        projects = self.client.project_list(owner)
        project_data = None
        for proj in projects:
            if proj.get("title") == project_title_found:
                project_data = proj
                break

        if not project_data:
            return None

        project_number = project_data.get("number")
        project_id = project_data.get("id")

        # Find item ID by listing project items
        items = self.client.project_item_list(project_number, owner)
        item_id = None
        for item in items:
            content = item.get("content", {})
            if (
                content.get("number") == pr_number
                and content.get("repository") == repo
            ):
                item_id = item.get("id")
                break

        if not item_id:
            return None

        return ProjectInfo(
            project_id=project_id,
            project_number=project_number,
            project_title=project_title_found,
            item_id=item_id,
            owner=owner,
        )

    def get_status_field(self, project_number: int, owner: str) -> FieldInfo | None:
        """Get the Status field info for a project."""
        fields = self.client.project_field_list(project_number, owner)

        for field in fields:
            if field.get("name") == "Status":
                return FieldInfo(
                    field_id=field.get("id"),
                    name="Status",
                    field_type=field.get("type"),
                    options=field.get("options"),
                )

        return None

    def get_field_by_name(self, project_number: int, owner: str, field_name: str) -> FieldInfo | None:
        """Get a field by name."""
        fields = self.client.project_field_list(project_number, owner)

        for field in fields:
            if field.get("name") == field_name:
                return FieldInfo(
                    field_id=field.get("id"),
                    name=field_name,
                    field_type=field.get("type"),
                    options=field.get("options"),
                )

        return None

    def resolve_status_option_id(self, status_name: str, status_field: FieldInfo) -> str | None:
        """Resolve a status name to its option ID."""
        if not status_field.options:
            return None

        # Case-insensitive match
        status_lower = status_name.lower()
        for option in status_field.options:
            if option.get("name", "").lower() == status_lower:
                return option.get("id")

        return None

    def set_status(
        self,
        project_info: ProjectInfo,
        status_name: str,
    ) -> dict[str, Any]:
        """Set the status of a project item.

        Args:
            project_info: The project and item info
            status_name: The status name (e.g., "In Progress", "Done")

        Returns:
            The result from project_item_edit

        Raises:
            GhError: If status field not found or status name invalid
        """
        status_field = self.get_status_field(project_info.project_number, project_info.owner)
        if not status_field:
            raise GhError(f"Status field not found in project '{project_info.project_title}'")

        option_id = self.resolve_status_option_id(status_name, status_field)
        if not option_id:
            available = [opt.get("name") for opt in (status_field.options or [])]
            raise GhError(
                f"Status '{status_name}' not found. Available: {', '.join(available)}"
            )

        return self.client.project_item_edit(
            item_id=project_info.item_id,
            project_id=project_info.project_id,
            field_id=status_field.field_id,
            single_select_option_id=option_id,
        )

    def set_field(
        self,
        project_info: ProjectInfo,
        field_name: str,
        value: str,
    ) -> dict[str, Any]:
        """Set a field value on a project item.

        Args:
            project_info: The project and item info
            field_name: The field name
            value: The value to set

        Returns:
            The result from project_item_edit

        Raises:
            GhError: If field not found or value invalid
        """
        field = self.get_field_by_name(project_info.project_number, project_info.owner, field_name)
        if not field:
            raise GhError(f"Field '{field_name}' not found in project '{project_info.project_title}'")

        # Handle different field types
        if field.field_type == "ProjectV2SingleSelectField":
            # Single select - need to resolve option ID
            option_id = None
            value_lower = value.lower()
            for option in (field.options or []):
                if option.get("name", "").lower() == value_lower:
                    option_id = option.get("id")
                    break

            if not option_id:
                available = [opt.get("name") for opt in (field.options or [])]
                raise GhError(
                    f"Value '{value}' not valid for field '{field_name}'. Available: {', '.join(available)}"
                )

            return self.client.project_item_edit(
                item_id=project_info.item_id,
                project_id=project_info.project_id,
                field_id=field.field_id,
                single_select_option_id=option_id,
            )
        elif field.field_type == "ProjectV2Field":
            # Text field
            return self.client.project_item_edit(
                item_id=project_info.item_id,
                project_id=project_info.project_id,
                field_id=field.field_id,
                value=value,
            )
        else:
            # Try as text
            return self.client.project_item_edit(
                item_id=project_info.item_id,
                project_id=project_info.project_id,
                field_id=field.field_id,
                value=value,
            )
