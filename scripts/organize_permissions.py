#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Organize permissions in Claude settings.json and settings.local.json files.

Groups permissions by category (MCP, Bash, Skill, Read, Edit, Write) and sorts them alphabetically.

Commands:
    (no args)       Organize permissions in both files
    --merge-local   Merge permissions from settings.local.json into settings.json
"""

import argparse
import json
from pathlib import Path
from collections import defaultdict


def categorize_permission(perm: str) -> str:
    """Categorize a permission string into its type."""
    if perm.startswith("mcp__"):
        return "mcp"
    elif perm.startswith("Bash("):
        return "bash"
    elif perm.startswith("Skill("):
        return "skill"
    elif perm.startswith("Read("):
        return "read"
    elif perm.startswith("Edit("):
        return "edit"
    elif perm.startswith("Write("):
        return "write"
    else:
        return "other"


def sort_permissions(permissions: list[str]) -> list[str]:
    """Sort permissions by category, then alphabetically within each category."""
    # Define category order
    category_order = ["mcp", "bash", "skill", "read", "edit", "write", "other"]

    # Group permissions by category
    groups: dict[str, list[str]] = defaultdict(list)
    for perm in permissions:
        category = categorize_permission(perm)
        groups[category].append(perm)

    # Sort each group alphabetically (case-insensitive)
    for category in groups:
        groups[category].sort(key=str.lower)

    # Combine in order, removing duplicates
    result = []
    seen = set()
    for category in category_order:
        for perm in groups[category]:
            if perm not in seen:
                result.append(perm)
                seen.add(perm)

    return result


# Sections that must be preserved when modifying settings files
PROTECTED_SECTIONS = ["hooks", "env", "enabledPlugins", "extraKnownMarketplaces"]


def verify_preserved_sections(original: dict, modified: dict, file_name: str) -> bool:
    """Verify that protected sections were not removed or modified."""
    errors = []
    for section in PROTECTED_SECTIONS:
        if section in original:
            if section not in modified:
                errors.append(f"Section '{section}' was removed!")
            elif original[section] != modified[section]:
                errors.append(f"Section '{section}' was unexpectedly modified!")

    if errors:
        print(f"  ⚠ SAFETY CHECK FAILED for {file_name}:")
        for error in errors:
            print(f"    - {error}")
        return False
    return True


def organize_settings_file(file_path: Path) -> bool:
    """Organize permissions in a settings file. Returns True if changes were made."""
    if not file_path.exists():
        print(f"  File not found: {file_path}")
        return False

    with open(file_path, "r") as f:
        data = json.load(f)

    # Keep a copy of protected sections for verification
    original_protected = {k: data.get(k) for k in PROTECTED_SECTIONS if k in data}

    if "permissions" not in data:
        print(f"  No permissions section in {file_path.name}")
        return False

    permissions = data["permissions"]
    changes_made = False

    # Organize allow list
    if "allow" in permissions:
        original = permissions["allow"]
        organized = sort_permissions(original)
        if original != organized:
            permissions["allow"] = organized
            changes_made = True
            removed_dupes = len(original) - len(organized)
            print(f"  allow: {len(organized)} permissions" +
                  (f" ({removed_dupes} duplicates removed)" if removed_dupes > 0 else ""))

    # Organize deny list
    if "deny" in permissions:
        original = permissions["deny"]
        organized = sort_permissions(original)
        if original != organized:
            permissions["deny"] = organized
            changes_made = True
            removed_dupes = len(original) - len(organized)
            print(f"  deny: {len(organized)} permissions" +
                  (f" ({removed_dupes} duplicates removed)" if removed_dupes > 0 else ""))

    if changes_made:
        # Verify protected sections are intact before saving
        if not verify_preserved_sections(original_protected,
                                         {k: data.get(k) for k in PROTECTED_SECTIONS if k in data},
                                         file_path.name):
            print(f"  ✗ Aborted saving {file_path.name} - protected sections would be lost!")
            return False

        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        # Show preserved sections
        preserved = [s for s in PROTECTED_SECTIONS if s in data]
        if preserved:
            print(f"  ✓ Saved {file_path.name} (preserved: {', '.join(preserved)})")
        else:
            print(f"  ✓ Saved {file_path.name}")
    else:
        print(f"  No changes needed for {file_path.name}")

    return changes_made


def print_permissions_summary(file_path: Path) -> None:
    """Print a summary of permissions grouped by category."""
    if not file_path.exists():
        return

    with open(file_path, "r") as f:
        data = json.load(f)

    if "permissions" not in data:
        return

    permissions = data["permissions"]

    for list_name in ["allow", "deny"]:
        if list_name not in permissions:
            continue

        print(f"\n  {list_name.upper()} ({len(permissions[list_name])} total):")

        # Group by category
        groups: dict[str, list[str]] = defaultdict(list)
        for perm in permissions[list_name]:
            category = categorize_permission(perm)
            groups[category].append(perm)

        # Print summary
        category_order = ["mcp", "bash", "skill", "read", "edit", "write", "other"]
        for category in category_order:
            if groups[category]:
                print(f"    {category}: {len(groups[category])}")


def find_claude_dir() -> Path | None:
    """Find .claude directory in current or parent directories."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        candidate = parent / ".claude"
        if candidate.is_dir():
            return candidate
    return None


def merge_local_settings(settings_file: Path, local_settings_file: Path) -> None:
    """Merge permissions from settings.local.json into settings.json."""
    if not local_settings_file.exists():
        print(f"Error: {local_settings_file.name} not found")
        return

    if not settings_file.exists():
        print(f"Error: {settings_file.name} not found")
        return

    # Load both files
    with open(settings_file, "r") as f:
        settings = json.load(f)

    # Keep a copy of protected sections for verification
    original_protected = {k: settings.get(k) for k in PROTECTED_SECTIONS if k in settings}

    with open(local_settings_file, "r") as f:
        local_settings = json.load(f)

    if "permissions" not in local_settings:
        print("No permissions in settings.local.json to merge")
        return

    # Ensure permissions section exists in main settings
    if "permissions" not in settings:
        settings["permissions"] = {}

    local_perms = local_settings["permissions"]
    main_perms = settings["permissions"]

    merged_count = {"allow": 0, "deny": 0}

    # Merge allow and deny lists
    for list_name in ["allow", "deny"]:
        if list_name not in local_perms:
            continue

        if list_name not in main_perms:
            main_perms[list_name] = []

        # Get existing permissions as set for deduplication
        existing = set(main_perms[list_name])
        new_perms = []

        for perm in local_perms[list_name]:
            if perm not in existing:
                new_perms.append(perm)
                existing.add(perm)

        if new_perms:
            main_perms[list_name].extend(new_perms)
            merged_count[list_name] = len(new_perms)
            print(f"  Added {len(new_perms)} new {list_name} permissions:")
            for perm in new_perms:
                print(f"    + {perm}")

    # Organize the merged permissions
    for list_name in ["allow", "deny"]:
        if list_name in main_perms:
            main_perms[list_name] = sort_permissions(main_perms[list_name])

    # Verify protected sections are intact before saving
    if not verify_preserved_sections(original_protected,
                                     {k: settings.get(k) for k in PROTECTED_SECTIONS if k in settings},
                                     settings_file.name):
        print(f"  ✗ Aborted saving {settings_file.name} - protected sections would be lost!")
        return

    # Save the updated settings
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    # Show preserved sections
    preserved = [s for s in PROTECTED_SECTIONS if s in settings]
    if preserved:
        print(f"\n✓ Saved merged permissions to {settings_file.name} (preserved: {', '.join(preserved)})")
    else:
        print(f"\n✓ Saved merged permissions to {settings_file.name}")

    # Clear the local settings permissions
    local_settings["permissions"] = {"allow": [], "deny": []}

    # Remove empty lists
    if not local_settings["permissions"]["allow"]:
        del local_settings["permissions"]["allow"]
    if not local_settings["permissions"]["deny"]:
        del local_settings["permissions"]["deny"]
    if not local_settings["permissions"]:
        del local_settings["permissions"]

    # If local settings is now empty, remove the file
    if not local_settings or local_settings == {}:
        local_settings_file.unlink()
        print(f"✓ Removed empty {local_settings_file.name}")
    else:
        with open(local_settings_file, "w") as f:
            json.dump(local_settings, f, indent=2)
            f.write("\n")
        print(f"✓ Cleared permissions from {local_settings_file.name}")

    # Print summary
    total = merged_count["allow"] + merged_count["deny"]
    if total > 0:
        print(f"\nMerged {total} permissions total")
    else:
        print("\nNo new permissions to merge (all already existed)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organize permissions in Claude settings files"
    )
    parser.add_argument(
        "--merge-local",
        action="store_true",
        help="Merge permissions from settings.local.json into settings.json",
    )
    args = parser.parse_args()

    claude_dir = find_claude_dir()
    if claude_dir is None:
        print("Error: Could not find .claude directory")
        return

    print(f"Found .claude directory: {claude_dir}\n")

    settings_file = claude_dir / "settings.json"
    local_settings_file = claude_dir / "settings.local.json"

    if args.merge_local:
        print("Merging settings.local.json into settings.json:")
        merge_local_settings(settings_file, local_settings_file)
        return

    # Default: organize both files
    print("Organizing settings.json:")
    organize_settings_file(settings_file)

    print("\nOrganizing settings.local.json:")
    organize_settings_file(local_settings_file)

    # Print summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    if settings_file.exists():
        print(f"\n{settings_file.name}:")
        print_permissions_summary(settings_file)

    if local_settings_file.exists():
        print(f"\n{local_settings_file.name}:")
        print_permissions_summary(local_settings_file)


if __name__ == "__main__":
    main()
