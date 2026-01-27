# ADR 001: ght - GitHub Tool for Agents

## Status
Accepted

## Context
AI agents working with GitHub need to:
1. Make multiple `gh` CLI calls to get complete context
2. Parse different output formats across commands
3. Chain commands for related information (issue + comments + project status)
4. Track and potentially undo their changes

The `gh` CLI is powerful but optimized for human interactive use, not agent automation.

## Decision

### 1. Single-Command Completeness
**Decision**: One command returns all relevant context.

`ght issue 123` returns: title, body, state, labels, assignees, comments, dependencies, project status, blocked status, and ready flag.

**Rationale**: Agents should gather full context in one API round-trip, not chain multiple commands.

### 2. JSON-Only Output
**Decision**: Output is always JSON, no human-readable mode.

**Rationale**: Agents parse structured data. Human-readable output adds complexity without benefit for the target use case.

### 3. Dry-Run Default
**Decision**: All mutations preview changes by default. Require `--execute` (`-x`) to apply.

```bash
ght issue 123 --close           # Shows what would change
ght issue 123 --close -x        # Actually closes
```

**Rationale**: Agents make mistakes. Preview-first prevents accidental changes and enables review before execution.

### 4. Transaction Log
**Decision**: All operations logged to `.ght/history.jsonl` with before/after state.

```jsonl
{"id":"op_f8a2","ts":"2024-01-15T10:30:00Z","target":"owner/repo","type":"issue","num":123,"action":"close","before":{"state":"open"},"after":{"state":"closed"},"dry_run":false}
```

**Rationale**:
- Enables `ght undo` for mistake recovery
- Audit trail for agent actions
- Committed to repo = shared across team

### 5. Git Merge Driver for History
**Decision**: Custom merge driver concatenates and deduplicates history entries.

```gitattributes
.ght/history.jsonl merge=ght-log
```

**Rationale**: Multiple agents/users may operate concurrently. Append-only log with unique IDs merges cleanly.

### 6. Dependencies via Task Lists
**Decision**: Store dependencies as GitHub task lists in issue body.

```markdown
---
## Dependencies
- [ ] #101
- [x] #102
- [ ] owner/repo#103
```

**Rationale**:
- Native GitHub feature
- GitHub auto-checks when referenced issue closes
- Visible in issue body without tooling
- No external storage needed

**Alternatives Considered**:
- Project fields: Requires project setup, not all repos use projects
- Labels (`depends-on:123`): Label pollution, harder to query
- Hidden body markers: Not visible, can be accidentally deleted

### 7. Blocked State Derivation
**Decision**: Blocked status derived from labels + project status + dependencies.

```python
blocked.directly = has_label("blocked") or status == "Blocked"
blocked.by_dependencies = any(dep.incomplete or dep.blocked for dep in deps)
ready = state == "open" and not blocked.directly and not blocked.by_dependencies
```

**Rationale**: Agents need to know "what can I work on?" - this enables `ght issues --ready`.

### 8. Dangerous Operation Confirmation
**Decision**: Operations like `--merge` require `--confirm` flag.

```bash
ght pr 456 --merge                    # Error
ght pr 456 --merge --confirm -x       # Works
```

**Rationale**: Merge is destructive and irreversible. Extra confirmation prevents accidents even with execute flag.

### 9. Cross-Repo Support
**Decision**: Operations support `--repo owner/repo` and cross-repo dependency references.

History logs both source repo (where ght ran) and target repo (where change was made).

**Rationale**: Agents may work across multiple repositories in a project.

## Consequences

### Positive
- Agents get complete context in single calls
- Dry-run default prevents mistakes
- Undo capability enables recovery
- Shared history enables team visibility
- Native GitHub features (task lists) = no external dependencies

### Negative
- More code than thin wrapper
- History file grows indefinitely (could add compaction later)
- Project status updates require complex gh project API (deferred to Phase 5)

### Neutral
- JSON-only may limit human usability (acceptable for agent-focused tool)
- Task list storage visible in issue body (feature, not bug)

## Implementation Notes

### File Structure
```
src/ght/
├── cli.py        # Click commands, ~1300 lines
├── gh.py         # gh wrapper, subprocess calls
├── models.py     # Dataclasses: Issue, PR, Operation
├── parser.py     # Task list parsing
├── history.py    # Transaction log operations
```

### Key Functions
- `parse_issue_data()`: gh JSON → Issue model with derived blocked/ready
- `parse_pr_data()`: gh JSON → PR model with checks aggregation
- `add_dependencies()`: Append task items to issue body
- `append_operation()`: Log to history.jsonl
- `merge_history_files()`: Git merge driver logic

### Command Summary
```
ght issue <n>       View/modify issue
ght issues          List issues
ght create          Create issue
ght pr <n>          View/modify PR
ght prs             List PRs
ght pr-create       Create PR
ght history         View log
ght undo            Undo operation
ght init            Initialize repo
ght merge-log       Git merge driver
```
