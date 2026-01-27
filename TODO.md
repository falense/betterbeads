# ght - Implementation Status

## Completed

### Phase 1: Core Foundation
- [x] Project setup with uv
- [x] CLI structure (Click)
- [x] gh command wrapper (`src/ght/gh.py`)
- [x] Data models (`src/ght/models.py`)
- [x] Transaction log infrastructure (`src/ght/history.py`)
- [x] Git merge driver for history.jsonl
- [x] `ght init` command

### Phase 2: Issue Operations
- [x] `ght issue <n>` - view with full context
- [x] `ght issues` - list with filters (`--state`, `--label`, `--assignee`, `--mine`)
- [x] `ght issues --ready` - filter by ready status (not blocked, deps complete)
- [x] `ght issues --blocked` - filter by blocked status
- [x] `ght create "Title"` - create issue with options
- [x] Issue modifications (labels, assignees, state, comments)
- [x] Dry-run / execute flow (`-x` flag)
- [x] `ght history` - view operation log
- [x] `ght undo` - undo operations

### Phase 3: Dependencies
- [x] Parse dependencies from task list in issue body
- [x] `--add-deps` / `--remove-deps` flags
- [x] Ready/blocked status derived from dependencies
- [x] GitHub auto-checks task items when referenced issue closes

### Phase 4: PR Operations
- [x] `ght pr <n>` - view with full context (reviews, checks, diff stats)
- [x] `ght pr <n> --diff` - include full diff
- [x] `ght prs` - list with filters (`--state`, `--mine`, `--draft`, `--ready`)
- [x] `ght pr-create "Title"` - create PR with options
- [x] PR modifications (labels, assignees, reviewers)
- [x] `--approve`, `--request-changes` for reviews
- [x] `--merge --squash/--rebase --confirm` for merging
- [x] `--closes` to link issues in PR body
- [x] Parse `Closes #X` from PR body

## Remaining

### Phase 5: Project Status Updates ✅
- [x] `--status "In Progress"` - set project status field
- [x] `--set-field key=value` - set arbitrary project field
- [x] Auto-detect project from issue
- [x] Handle multiple projects (require `--project "Name"`)

### Phase 6: Shortcuts ✅
- [x] `--start` shortcut = `--status "In Progress" --add-assignees @me`
- [x] `--done` shortcut = `--close --status "Done"`
- [ ] Configurable shortcuts in `.ght/config.json` (deferred to Phase 8)

### Phase 7: Search & Polish
- [ ] `ght search "query"` - unified search (skipped)
- [ ] `--type issue|pr` filter for search (skipped)
- [x] Enrich dependency info (fetch titles/state for each dep)
- [x] `ght issue <n> --tree` - dependency tree view
- [x] Cross-repo dependency display

### Phase 8: Configuration ✅
- [x] `.ght/config.json` support
- [x] Configurable blocked indicators (labels, statuses)
- [x] Configurable dependency section header
- [x] Configurable shortcuts (start, done)

## Known Limitations

1. **Dependency enrichment**: Dependencies show number but not title/state unless viewed individually
2. **Cross-repo deps**: Supported in storage but not enriched with remote data
3. **Project field IDs**: gh project commands require complex ID lookups - needs abstraction
4. **Rate limiting**: No explicit handling, relies on gh CLI behavior

## File Structure

```
ght/
├── __init__.py      # Package init, version
├── cli.py           # Click CLI commands (1300+ lines)
├── gh.py            # gh command wrapper
├── models.py        # Dataclasses (Issue, PR, Operation, etc.)
├── parser.py        # Task list parsing for dependencies
├── history.py       # Transaction log operations
├── config.py        # Configuration management
└── py.typed         # Type hints marker

.ght/
├── history.jsonl    # Transaction log (committed, shared)
└── config.json      # Configuration
```

## Testing Checklist

### Issue Operations
- [x] View issue with comments, deps, project items
- [x] List issues with filters
- [x] Create issue with labels, assignees, deps
- [x] Add/remove labels
- [x] Add/remove assignees
- [x] Close/reopen with comments
- [x] Add dependencies via `--add-deps`
- [x] Undo label changes
- [x] Undo state changes

### PR Operations
- [x] View PR with reviews, checks, diff stats
- [x] View PR with full diff
- [x] List PRs with filters
- [x] Dry-run approval
- [x] Parse closes_issues from body

### History/Undo
- [x] Operations logged to history.jsonl
- [x] Dry-runs logged with dry_run: true
- [x] Undo specific operation by ID
- [x] Undo last N operations
