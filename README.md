# Better Beads

A GitHub-native task management CLI for AI agents. Inspired by [Beads](https://github.com/steveyegge/beads), but using GitHub Issues and Projects as the source of truth instead of local storage.

## Why Better Beads?

[Beads](https://github.com/steveyegge/beads) solves the right problem: AI agents need persistent, structured memory for complex tasks. But it stores everything locally in `.beads/` files, creating a parallel system to GitHub.

**Better Beads takes a different approach:** Use GitHub itself as the database. Issues, PRs, Projects, and dependencies are already there. We just need a better interface.

| Feature | Beads | Better Beads |
|---------|-------|--------------|
| Storage | Local `.beads/` JSONL | GitHub Issues/PRs |
| Dependencies | Custom format | Native task lists in issue body |
| Project status | Local state | GitHub Projects v2 |
| Collaboration | Git sync required | Already collaborative |
| History/Undo | Local transaction log | `.betterbeads/history.jsonl` + GitHub events |

## Design Principles

1. **Single-call completeness** - One command returns everything needed for context
2. **Structured output** - JSON by default, optimized for agent parsing
3. **Dry-run default** - Preview changes, require `--execute` to apply
4. **Transaction log** - All operations logged for audit and undo
5. **Zero config** - Works out of the box with sensible defaults

## Installation

Requires Python 3.13+ and [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated.

```bash
# Install from GitHub
uv tool install git+https://github.com/falense/betterbeads

# Or install from local clone (editable for development)
uv tool install --force --editable .
```

**Why `--editable`?** UV tools install into an isolated environment. Without it, changes to source code require reinstalling. Editable mode links directly to your source, so changes take effect immediately.

This installs two commands:
- `bb` - primary command (Better Beads)
- `ght` - alias

## Removal

```bash
# Uninstall the tool
uv tool uninstall betterbeads
```

## Quick Start

```bash
# Initialize in your repo
bb init

# View an issue with full context (comments, dependencies, project status)
bb issue 123

# List ready issues (open, not blocked, dependencies complete)
bb issues --ready

# Create an issue with dependencies
bb create "Implement feature X" --deps 101,102 --execute

# Start working on an issue (sets status + assigns you)
bb issue 123 --start --execute

# Mark done (closes + sets project status)
bb issue 123 --done --execute
```

## Commands

### Issues

```bash
bb issue <number>              # View with full context
bb issue <number> --start -x   # Start working (status + assign)
bb issue <number> --done -x    # Complete (close + status)
bb issues                      # List issues
bb issues --ready              # Ready to work on
bb issues --blocked            # Blocked issues
bb create "Title" [options]    # Create issue
bb next                        # Pick a ready issue and start work
bb next -l bug -x              # Start working on next bug
```

### Pull Requests

```bash
bb pr <number>                 # View with reviews, checks, diff stats
bb pr <number> --diff          # Include full diff
bb pr <number> --approve -x    # Approve
bb pr <number> --merge --squash --confirm -x  # Merge
bb prs                         # List PRs
bb pr-create "Title" [opts]    # Create PR
```

### Modifications

All modifications preview by default. Add `--execute` (or `-x`) to apply:

```bash
# Metadata
--title "X"                     # Set title
--body "X"                      # Set body
--milestone "X"                 # Set milestone

# Labels & Assignees
--add-labels bug,urgent
--remove-labels wontfix
--add-assignees alice,bob
--remove-assignees charlie

# Dependencies (stored as task list in issue body)
--add-deps 101,102
--remove-deps 103

# State
--close [--reason completed|"not planned"]
--reopen

# Project Status
--status "In Progress"          # Set project status
--set-field Priority=High       # Set any project field
--project "Sprint 5"            # Specify project (if multiple)

# Shortcuts
--start                         # = --status "In Progress" --add-assignees @me
--done                          # = --close --status "Done"
```

### History & Undo

```bash
bb history                     # View operation log
bb history --issue 123         # Filter by issue
bb undo                        # Undo last operation
bb undo op_f8a2b3c4            # Undo specific operation
```

## Dependencies

Dependencies are stored as task lists in the issue body:

```markdown
Your issue description here...

---
## Dependencies
- [ ] #101
- [x] #102
- [ ] owner/repo#103
```

GitHub automatically checks items when referenced issues close.

### Blocked State

An issue is blocked if:
- Has label: `blocked`, `on-hold`, `waiting-on-external`
- Has project status: `Blocked`, `On Hold`
- Any incomplete dependency is itself blocked

## Configuration

Optional `.betterbeads/config.json`:

```json
{
  "blocked_indicators": {
    "labels": ["blocked", "on-hold", "waiting-on-external"],
    "statuses": ["Blocked", "On Hold"]
  },
  "dependencies": {
    "section_header": "## Dependencies",
    "separator": "---"
  },
  "shortcuts": {
    "start": {
      "status": "In Progress",
      "assignees": ["@me"]
    },
    "done": {
      "close": true,
      "status": "Done"
    }
  },
  "hooks": {
    "session_stop": {
      "enabled": true
    }
  }
}
```

## Output Format

All commands output JSON for easy parsing:

```json
{
  "type": "issue",
  "number": 123,
  "title": "Auth timeout bug",
  "state": "open",
  "labels": ["bug", "auth"],
  "assignees": ["bob"],
  "dependencies": [
    {"number": 101, "complete": true},
    {"number": 102, "complete": false}
  ],
  "project_items": [
    {"project": "Sprint 5", "status": "In Progress"}
  ],
  "blocked": {
    "directly": false,
    "by_dependencies": true,
    "reasons": ["dependency #102 is incomplete"]
  },
  "ready": false
}
```

## Claude Code Plugin

Better Beads includes a Claude Code plugin with:
- **Skill**: Guidance for using `bb` commands
- **SessionStart hook**: Shows open issues when starting a session
- **Stop hook**: Prompts to continue working on ready issues (config-gated)

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for installation
- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated
- For project features: `gh auth refresh -s project`

## License

MIT
