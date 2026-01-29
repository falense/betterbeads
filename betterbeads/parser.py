"""Task list parsing and modification for dependencies and general task items."""

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


@dataclass
class GeneralTaskItem:
    """A general task list item (not necessarily referencing an issue)."""

    text: str
    complete: bool
    line_number: int  # 1-indexed line number in the content
    start_pos: int  # Character position in the content
    end_pos: int  # End character position

    def to_markdown(self) -> str:
        """Convert to markdown task list item."""
        checkbox = "[x]" if self.complete else "[ ]"
        return f"- {checkbox} {self.text}"


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

# Pattern to match any task list item (general, not just issue references)
# Matches: - [ ] Any text here, - [x] Completed item, - [X] Also completed
GENERAL_TASK_PATTERN = re.compile(
    r"^- \[([ xX])\] (.+)$",
    re.MULTILINE,
)

# Pattern to find markdown sections by header
SECTION_PATTERN = re.compile(
    r"^(#{1,6}) ([^\n]+)\n(.*?)(?=^#{1,6} |\Z)",
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


def find_all_task_items(content: str) -> list[GeneralTaskItem]:
    """Find all task list items in the content.

    Returns a list of GeneralTaskItem objects with their positions.
    """
    items = []
    lines = content.split("\n")
    current_pos = 0

    for line_num, line in enumerate(lines, start=1):
        match = GENERAL_TASK_PATTERN.match(line)
        if match:
            checkbox, text = match.groups()
            items.append(
                GeneralTaskItem(
                    text=text,
                    complete=checkbox.lower() == "x",
                    line_number=line_num,
                    start_pos=current_pos,
                    end_pos=current_pos + len(line),
                )
            )
        current_pos += len(line) + 1  # +1 for newline

    return items


def toggle_task_by_text(
    content: str,
    pattern: str,
    complete: bool,
    case_sensitive: bool = False,
) -> tuple[str, list[GeneralTaskItem]]:
    """Toggle task items matching a text pattern.

    Args:
        content: The markdown content
        pattern: Text to match (substring match)
        complete: Whether to mark as complete
        case_sensitive: Whether to match case-sensitively

    Returns:
        Tuple of (updated content, list of toggled items)
    """
    items = find_all_task_items(content)
    toggled = []

    search_pattern = pattern if case_sensitive else pattern.lower()

    for item in items:
        item_text = item.text if case_sensitive else item.text.lower()
        if search_pattern in item_text:
            toggled.append(item)

    if not toggled:
        return content, []

    # Apply changes from end to start to preserve positions
    result = content
    for item in reversed(toggled):
        new_line = f"- [{'x' if complete else ' '}] {item.text}"
        result = result[: item.start_pos] + new_line + result[item.end_pos :]

    # Update the toggled items with new state
    for item in toggled:
        item.complete = complete

    return result, toggled


def toggle_task_at_line(
    content: str,
    line_number: int,
    complete: bool,
) -> tuple[str, GeneralTaskItem | None]:
    """Toggle a task item at a specific line number.

    Args:
        content: The markdown content
        line_number: 1-indexed line number
        complete: Whether to mark as complete

    Returns:
        Tuple of (updated content, toggled item or None if not found)
    """
    items = find_all_task_items(content)

    for item in items:
        if item.line_number == line_number:
            new_line = f"- [{'x' if complete else ' '}] {item.text}"
            result = content[: item.start_pos] + new_line + content[item.end_pos :]
            item.complete = complete
            return result, item

    return content, None


@dataclass
class Section:
    """A markdown section with header and content."""

    header: str
    level: int  # Header level (1-6)
    content: str
    start_pos: int
    end_pos: int
    header_start: int  # Position where header line starts
    content_start: int  # Position where content starts (after header line)


def find_section(content: str, header: str) -> Section | None:
    """Find a section by its header text.

    Args:
        content: The markdown content
        header: Header text to find (case-insensitive)

    Returns:
        Section object or None if not found
    """
    for match in SECTION_PATTERN.finditer(content):
        hashes, header_text, section_content = match.groups()
        if header_text.strip().lower() == header.lower():
            # Calculate positions
            start_pos = match.start()
            end_pos = match.end()
            header_line = f"{hashes} {header_text}\n"
            content_start = start_pos + len(header_line)

            return Section(
                header=header_text.strip(),
                level=len(hashes),
                content=section_content,
                start_pos=start_pos,
                end_pos=end_pos,
                header_start=start_pos,
                content_start=content_start,
            )

    return None


def replace_section_content(content: str, header: str, new_content: str) -> str:
    """Replace the content of a section (keeps header).

    Args:
        content: The markdown content
        header: Header text of section to replace
        new_content: New content for the section

    Returns:
        Updated content
    """
    section = find_section(content, header)
    if not section:
        return content

    # Ensure new_content ends with newline if original did
    if new_content and not new_content.endswith("\n"):
        new_content += "\n"

    # Keep the header, replace just the content
    header_line = f"{'#' * section.level} {section.header}\n"

    return (
        content[: section.start_pos]
        + header_line
        + new_content
        + content[section.end_pos :]
    )


def append_to_section(content: str, header: str, text: str) -> str:
    """Append text to the end of a section.

    Args:
        content: The markdown content
        header: Header text of section to append to
        text: Text to append

    Returns:
        Updated content
    """
    section = find_section(content, header)
    if not section:
        return content

    # Insert before the end of section
    new_section_content = section.content.rstrip() + "\n" + text + "\n"

    return replace_section_content(content, header, new_section_content)
