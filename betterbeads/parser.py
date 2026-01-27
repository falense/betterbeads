"""Task list parsing and modification for dependencies."""

import re
from dataclasses import dataclass


@dataclass
class TaskItem:
    """A task list item representing a dependency."""

    number: int
    repo: str | None = None  # None means same repo, otherwise "owner/repo"
    complete: bool = False
    description: str | None = None  # Optional text after issue number

    def to_markdown(self) -> str:
        """Convert to markdown task list item."""
        checkbox = "[x]" if self.complete else "[ ]"
        if self.repo:
            ref = f"{self.repo}#{self.number}"
        else:
            ref = f"#{self.number}"

        if self.description:
            return f"- {checkbox} {ref} {self.description}"
        return f"- {checkbox} {ref}"


# Pattern to match task list items with issue references
# Matches: - [ ] #123, - [x] #456, - [ ] owner/repo#789, - [x] owner/repo#101 description
TASK_ITEM_PATTERN = re.compile(
    r"^- \[([ xX])\] (?:([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+))?#(\d+)(.*)$",
    re.MULTILINE,
)

# Pattern to find the Dependencies section
DEPS_SECTION_PATTERN = re.compile(
    r"(^---\n)?^## Dependencies\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)


def parse_task_items(content: str) -> list[TaskItem]:
    """Parse task list items from markdown content.

    Only parses items that reference issues (have #number).
    """
    items = []
    for match in TASK_ITEM_PATTERN.finditer(content):
        checkbox, repo, number, description = match.groups()
        items.append(
            TaskItem(
                number=int(number),
                repo=repo if repo else None,
                complete=checkbox.lower() == "x",
                description=description.strip() if description.strip() else None,
            )
        )
    return items


def parse_dependencies(body: str) -> list[TaskItem]:
    """Parse dependencies from issue body.

    Looks for a ## Dependencies section and extracts task list items.
    """
    match = DEPS_SECTION_PATTERN.search(body)
    if not match:
        return []

    section_content = match.group(2) if match.group(2) else ""
    return parse_task_items(section_content)


def add_dependencies(
    body: str,
    deps: list[int | str],
    separator: str = "---",
    header: str = "## Dependencies",
) -> str:
    """Add dependencies to issue body.

    Args:
        body: Current issue body
        deps: List of issue numbers (int) or "owner/repo#number" (str)
        separator: Separator before dependencies section
        header: Section header

    Returns:
        Updated body with dependencies added
    """
    # Parse new deps
    new_items: list[TaskItem] = []
    for dep in deps:
        if isinstance(dep, int):
            new_items.append(TaskItem(number=dep))
        elif isinstance(dep, str):
            # Parse "owner/repo#123" or "#123" or "123"
            if "#" in dep:
                parts = dep.split("#")
                repo = parts[0] if parts[0] else None
                number = int(parts[1])
                new_items.append(TaskItem(number=number, repo=repo))
            else:
                new_items.append(TaskItem(number=int(dep)))

    # Check if Dependencies section exists
    match = DEPS_SECTION_PATTERN.search(body)

    if match:
        # Section exists, add to it
        existing = parse_task_items(match.group(2) if match.group(2) else "")
        existing_refs = {(item.repo, item.number) for item in existing}

        # Only add items that don't already exist
        items_to_add = [
            item for item in new_items if (item.repo, item.number) not in existing_refs
        ]

        if not items_to_add:
            return body  # Nothing to add

        # Find the end of the task list in the section
        section_start = match.start()
        section_end = match.end()

        # Build new section content
        section_content = match.group(2) if match.group(2) else ""
        new_lines = [item.to_markdown() for item in items_to_add]

        # Append new items
        if section_content.strip():
            new_section = section_content.rstrip() + "\n" + "\n".join(new_lines) + "\n"
        else:
            new_section = "\n".join(new_lines) + "\n"

        # Reconstruct the section
        has_separator = match.group(1) is not None
        if has_separator:
            new_full_section = f"---\n{header}\n{new_section}"
        else:
            new_full_section = f"{header}\n{new_section}"

        return body[:section_start] + new_full_section + body[section_end:]

    else:
        # No section exists, create it
        new_lines = [item.to_markdown() for item in new_items]
        section = f"\n{separator}\n{header}\n" + "\n".join(new_lines) + "\n"

        # Append to body
        return body.rstrip() + section


def remove_dependencies(
    body: str,
    deps: list[int | str],
) -> str:
    """Remove dependencies from issue body.

    Args:
        body: Current issue body
        deps: List of issue numbers (int) or "owner/repo#number" (str) to remove

    Returns:
        Updated body with dependencies removed
    """
    # Parse deps to remove
    to_remove: set[tuple[str | None, int]] = set()
    for dep in deps:
        if isinstance(dep, int):
            to_remove.add((None, dep))
        elif isinstance(dep, str):
            if "#" in dep:
                parts = dep.split("#")
                repo = parts[0] if parts[0] else None
                number = int(parts[1])
                to_remove.add((repo, number))
            else:
                to_remove.add((None, int(dep)))

    match = DEPS_SECTION_PATTERN.search(body)
    if not match:
        return body  # No section, nothing to remove

    section_content = match.group(2) if match.group(2) else ""

    # Remove matching task items line by line
    lines = section_content.split("\n")
    new_lines = []
    for line in lines:
        item_match = TASK_ITEM_PATTERN.match(line)
        if item_match:
            _, repo, number, _ = item_match.groups()
            repo = repo if repo else None
            if (repo, int(number)) in to_remove:
                continue  # Skip this line
        new_lines.append(line)

    new_section_content = "\n".join(new_lines)

    # Reconstruct
    section_start = match.start()
    section_end = match.end()
    has_separator = match.group(1) is not None

    # If section is now empty (only whitespace), remove it entirely
    if not new_section_content.strip():
        return body[:section_start].rstrip() + body[section_end:]

    if has_separator:
        new_full_section = f"---\n## Dependencies\n{new_section_content}"
    else:
        new_full_section = f"## Dependencies\n{new_section_content}"

    return body[:section_start] + new_full_section + body[section_end:]


def set_task_complete(
    body: str,
    number: int,
    repo: str | None = None,
    complete: bool = True,
) -> str:
    """Set a task item's completion status.

    Args:
        body: Issue body
        number: Issue number to update
        repo: Optional repo (None for same repo)
        complete: Whether to mark as complete

    Returns:
        Updated body
    """

    def replace_checkbox(match: re.Match) -> str:
        checkbox, item_repo, item_number, description = match.groups()
        item_repo = item_repo if item_repo else None
        if item_repo == repo and int(item_number) == number:
            new_checkbox = "[x]" if complete else "[ ]"
            if item_repo:
                ref = f"{item_repo}#{item_number}"
            else:
                ref = f"#{item_number}"
            return f"- {new_checkbox} {ref}{description}"
        return match.group(0)

    return TASK_ITEM_PATTERN.sub(replace_checkbox, body)
