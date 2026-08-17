# Python Agent Forge Handoff

## Goal

Build a separate Python sibling to C++ Agent Forge that gives consumer
repositories a Codex-ready bootstrap, validation workflow, and parallel PR
orchestration policy.

## Technical Contract

- Require Python 3.13 or newer through `pyproject.toml`.
- Use `uv` for dependency synchronization and command execution.
- Use Ruff as the sole formatter and linter: `uv run ruff format --check .`
  and `uv run ruff check .`.
- Use pytest as the standard test runner: `uv run pytest`.
- Use a `src/` layout with a minimal starter package and smoke test.
- Configure GitHub Actions with `astral-sh/setup-uv` and Python 3.13.

## Codex Orchestration Contract

For a multi-feature request, plan before implementation; create one task,
worktree, `codex/<task-slug>` branch, and PR for every independent feature;
run non-overlapping tasks in parallel (default four); serialize overlaps and
dependencies; require CI and review; and require human approval before merge.

## Required Bootstrap Artifacts

Generate `AGENTS.md`, `.codex/project.yml`, `.codex/orchestration.yml`, Python
CI, a PR template, orchestration documentation, `validate-python.sh`, and a
worktree helper. The CLI must provide `init`, `check`, and `help`, avoid
overwrites by default, and reject private paths or likely secrets.

## Next Session Prompt

Implement Python Agent Forge from this handoff. Use Python >=3.13, uv, Ruff,
and pytest. Preserve the Codex worktree-per-feature and one-PR-per-feature
orchestration model. Run validation and stop at the next committable milestone.
