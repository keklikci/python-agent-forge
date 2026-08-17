# Python Agent Forge Handoff

> Python repository automation with uv, Ruff, pytest, and parallel PR workflows.

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

## Codex Git Integration Conventions

### Commit messages

Use Conventional Commits with a short lowercase scope:

```text
<type>(<scope>): <imperative summary>
```

Allowed types are `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, and
`build`. Keep the subject under 72 characters, do not end it with a period,
and create separate commits for logically independent changes.

Examples:

```text
feat(init): add Python consumer bootstrap
ci(workflow): validate with uv and Ruff
docs(handoff): define Codex PR orchestration
```

### Pull requests

Use an action-oriented PR title with the same Conventional Commit format as
the primary change. The description must include the task brief, owned paths,
implementation summary, validation commands and results, risks, dependencies,
and follow-up work. Keep one feature per PR unless the user explicitly asks
for a combined PR.

Suggested PR description:

```markdown
## Summary

<one-sentence brief>

## Changes

- <implementation change>

## Scope

- Owned paths: <paths>
- Out of scope: <paths or none>

## Validation

- `uv sync`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run pytest`

## Risks and dependencies

- Risks: <risks or none>
- Dependencies: <dependencies or none>
```

## Next Session Prompt

Implement Python Agent Forge from this handoff. Use Python >=3.13, uv, Ruff,
and pytest. Preserve the Codex worktree-per-feature and one-PR-per-feature
orchestration model. Use Conventional Commits with a scoped subject and
include brief, scope, validation, risks, and dependencies in each PR. Run
validation and stop at the next committable milestone.
