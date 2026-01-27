---
name: betterbeads
description: |
  Better Beads (bb) - use for all GitHub issue and PR operations.
  Provides complete context in single calls, tracks dependencies between issues,
  and includes undo capability. Use when: viewing/creating/modifying issues,
  viewing/creating/merging PRs, checking what's ready to work on, managing
  issue dependencies, or undoing GitHub operations. Keywords: github, issue,
  issues, PR, pull request, blocked, dependencies, ready, milestone, label, bb.
---

# Better Beads (bb) - GitHub Tool for Agents

`bb` is a CLI wrapper around `gh` optimized for AI agents. It provides complete context in single calls and safe mutations with dry-run defaults.

Alias: `ght` also works as a command alias.

## Key Principles

1. **Single-call completeness** - One command returns all needed context
2. **JSON output only** - Structured data for parsing
3. **Dry-run default** - Preview changes, use `-x` or `--execute` to apply
4. **Transaction log** - All operations logged for undo capability
5. **Dependency tracking** - Track and visualize issue dependencies

## Quick Reference

### Viewing Issues

```bash
# Get full issue context (comments, deps, project status, blocked/ready)
bb issue 123

# List issues
bb issues                    # Open issues
bb issues --ready            # Ready to work on (not blocked, deps complete)
bb issues --blocked          # Blocked issues
bb issues --mine             # Assigned to me
bb issues --label bug        # Filter by label
```

### Creating Issues

```bash
# Always use -x to execute (dry-run is default)
bb create "Title" --body "Description" -x
bb create "Title" --labels bug,urgent --assignees alice -x
bb create "Title" --deps 101,102 -x    # With dependencies
```

### Modifying Issues

```bash
# Labels and assignees
bb issue 123 --add-labels bug -x
bb issue 123 --remove-labels question -x
bb issue 123 --add-assignees alice,bob -x

# Comments and state
bb issue 123 --comment "Found the cause" -x
bb issue 123 --close --reason completed -x
bb issue 123 --reopen -x

# Dependencies
bb issue 123 --add-deps 101,102 -x
bb issue 123 --remove-deps 103 -x
```

### Pull Requests

```bash
# View PR with full context
bb pr 456
bb pr 456 --diff             # Include full diff

# List PRs
bb prs                       # Open PRs
bb prs --mine                # My PRs
bb prs --ready               # Non-draft PRs

# Create PR
bb pr-create "Title" --body "Description" -x
bb pr-create "Fix bug" --closes 123 -x    # Links to issue

# Review and merge
bb pr 456 --approve -x
bb pr 456 --approve --comment "LGTM" -x
bb pr 456 --request-changes --comment "See comments" -x
bb pr 456 --merge --squash --delete-branch --confirm -x
```

### History and Undo

```bash
bb history                   # View recent operations
bb history --issue 123       # Filter by issue
bb undo                      # Preview undo of last operation
bb undo -x                   # Execute undo
bb undo op_abc123 -x         # Undo specific operation
```

## Understanding Output

### Issue Response

```json
{
  "type": "issue",
  "number": 123,
  "title": "Auth timeout bug",
  "state": "open",
  "blocked": {
    "directly": false,
    "by_dependencies": true,
    "reasons": ["dependency #101 is incomplete"]
  },
  "ready": false,
  "dependencies": [
    {"number": 101, "complete": false, "title": "Design API", "blocked": false}
  ]
}
```

### Blocked vs Ready

- **Blocked**: Has blocking label (`blocked`, `on-hold`) OR has incomplete blocked dependency
- **Ready**: Open AND not blocked AND all dependencies complete

## Best Practices

1. **Always check `--ready` first** to find actionable work
2. **Use dry-run** (default) to preview changes before `-x`
3. **Add dependencies** when creating related issues
4. **Use `--closes`** when creating PRs that fix issues
5. **Check history** if you need to undo an operation

## Common Workflows

### Start Working on an Issue

```bash
# Find ready work
bb issues --ready

# View full context
bb issue 123

# Assign to yourself
bb issue 123 --add-assignees @me -x
```

### Complete an Issue via PR

```bash
# Create PR that closes the issue
bb pr-create "Fix auth timeout" --closes 123 -x

# After review, merge
bb pr 456 --merge --squash --delete-branch --confirm -x
```

### Track Dependencies

```bash
# Create parent issue
bb create "Implement auth" -x

# Create subtasks with dependencies
bb create "Design auth API" --deps 100 -x
bb create "Implement tokens" --deps 100 -x

# Check what's blocked
bb issues --blocked
```
