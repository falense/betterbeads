# BetterBeads GitHub Context

**ALWAYS use `bb` for all GitHub operations** (issues, PRs, projects) - never use `gh` directly.

## Install bb

If `bb` is not yet installed:

```bash
uv tool install git+https://github.com/falense/betterbeads
```

Or for local development (from the betterbeads repo):

```bash
uv tool install --force --editable .
```

## Issue Requirement

**All work must have an accompanying GitHub issue.**
- Before starting ANY work, identify or create the relevant issue
- If no issue exists, create one with `bb create`
- Reference the issue number in commits

## Finding Work

```bash
bb issues --ready   # Issues with no blockers and all dependencies complete
bb issues           # All open issues
bb issue 123        # Full context for a specific issue
```
