# Python Repository Agent Instructions

This repository follows the Python Agent Forge workflow.

- Use Python 3.13 or newer and manage dependencies with `uv`.
- Run `uv run ruff format --check .`, `uv run ruff check .`, and `uv run pytest`.
- Treat `src/**`, `tests/**`, and project configuration as owned paths unless a
  task explicitly narrows scope.
- Never persist local absolute paths, credentials, tokens, or private data.

For a request containing multiple independently deliverable features, act as
the orchestrator: plan the complete request, create one task manifest and PR
per feature, use separate worktrees and `codex/<task-slug>` branches, run
independent tasks in parallel up to the configured limit, and serialize tasks
with overlapping paths. Require CI and review before asking for merge approval.
Review agents may request changes but must not merge. Unless the user requests
a combined PR, do not collapse independent features into one branch or PR.
