"""Configuration management for betterbeads."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ShortcutConfig:
    """Configuration for a shortcut."""

    status: str | None = None
    assignees: list[str] | None = None
    close: bool = False
    reopen: bool = False
    labels_add: list[str] | None = None
    labels_remove: list[str] | None = None


@dataclass
class BlockedIndicators:
    """Configuration for blocked state detection."""

    labels: list[str] = field(default_factory=lambda: ["blocked", "on-hold", "waiting-on-external"])
    statuses: list[str] = field(default_factory=lambda: ["Blocked", "On Hold", "Waiting"])


@dataclass
class DependencyConfig:
    """Configuration for dependency parsing."""

    section_header: str = "## Dependencies"
    separator: str = "---"


@dataclass
class GhtConfig:
    """Main configuration for ght."""

    blocked_indicators: BlockedIndicators = field(default_factory=BlockedIndicators)
    dependencies: DependencyConfig = field(default_factory=DependencyConfig)
    shortcuts: dict[str, ShortcutConfig] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "GhtConfig":
        """Create default configuration with built-in shortcuts."""
        config = cls()
        config.shortcuts = {
            "start": ShortcutConfig(status="In Progress", assignees=["@me"]),
            "done": ShortcutConfig(status="Done", close=True),
        }
        return config


def find_config_file() -> Path | None:
    """Find .betterbeads/config.json starting from cwd and walking up."""
    cwd = Path.cwd()

    # Walk up directory tree
    for directory in [cwd, *cwd.parents]:
        config_path = directory / ".betterbeads" / "config.json"
        if config_path.exists():
            return config_path

        # Stop at git root
        if (directory / ".git").exists():
            break

    return None


def parse_shortcut(data: dict[str, Any]) -> ShortcutConfig:
    """Parse shortcut configuration from dict."""
    assignees = data.get("assignees")
    if isinstance(assignees, str):
        assignees = [assignees]

    labels_add = data.get("labels_add") or data.get("add_labels")
    if isinstance(labels_add, str):
        labels_add = [labels_add]

    labels_remove = data.get("labels_remove") or data.get("remove_labels")
    if isinstance(labels_remove, str):
        labels_remove = [labels_remove]

    return ShortcutConfig(
        status=data.get("status"),
        assignees=assignees,
        close=data.get("close", False),
        reopen=data.get("reopen", False),
        labels_add=labels_add,
        labels_remove=labels_remove,
    )


def load_config(config_path: Path | None = None) -> GhtConfig:
    """Load configuration from file or return defaults.

    Args:
        config_path: Optional explicit path to config file.
                    If not provided, searches for .betterbeads/config.json.

    Returns:
        GhtConfig with loaded or default values.
    """
    config = GhtConfig.default()

    if config_path is None:
        config_path = find_config_file()

    if config_path is None or not config_path.exists():
        return config

    try:
        with open(config_path) as f:
            data = json.load(f)

        if not data:
            return config

        # Parse blocked_indicators
        if "blocked_indicators" in data:
            bi = data["blocked_indicators"]
            config.blocked_indicators = BlockedIndicators(
                labels=bi.get("labels", config.blocked_indicators.labels),
                statuses=bi.get("statuses", config.blocked_indicators.statuses),
            )

        # Parse dependencies
        if "dependencies" in data:
            deps = data["dependencies"]
            config.dependencies = DependencyConfig(
                section_header=deps.get("section_header", config.dependencies.section_header),
                separator=deps.get("separator", config.dependencies.separator),
            )

        # Parse shortcuts (merge with defaults)
        if "shortcuts" in data:
            for name, shortcut_data in data["shortcuts"].items():
                config.shortcuts[name] = parse_shortcut(shortcut_data)

        return config

    except Exception:
        # On any parse error, return defaults
        return GhtConfig.default()


# Global config cache
_config: GhtConfig | None = None


def get_config() -> GhtConfig:
    """Get the current configuration (cached)."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the config cache (for testing)."""
    global _config
    _config = None
