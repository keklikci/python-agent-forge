# Python Agent Forge Handoff

> Python repository automation with uv, Ruff, pytest, and parallel PR workflows.

## Goal

Provide a reusable Python repository bootstrap that gives adopting repositories
a Codex-ready validation workflow and parallel pull-request orchestration
policy. The bootstrap must remain independent of any source repository,
language sibling, hosting organization, model name, or consumer domain.

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

## Portability Boundaries

The following values are defaults, not repository identity or policy that must
be copied blindly:

- The target repository chooses its package name, task identifiers, owner,
  remote, base branch, model, and allowed paths.
- `main`, `codex/`, and four parallel tasks are configurable defaults.
- Generated files must not contain local absolute paths, credentials, tokens,
  personal data, or provider-specific assumptions beyond the documented uv,
  Ruff, pytest, and GitHub Actions contract.
- The orchestration rules apply to any independently deliverable feature; they
  are not limited to Python source changes or a particular product workflow.

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

## Implementation Status (This Repository)

The implementation objective is complete for this repository. The status below
is evidence about this implementation, not a requirement that adopting
repositories share its paths, names, history, or commit identities.

Implemented artifacts and behavior:

- `pyproject.toml`, `src/python_agent_forge/`, and `tests/test_smoke.py` provide
  the Python 3.13+ `src/` layout and smoke test.
- `bin/python-agent-forge` provides `init`, `check`, and `help`; initialization
  does not overwrite existing files and rejects private or secret-bearing
  target paths.
- Initialization generates `AGENTS.md`, `.codex/project.yml`,
  `.codex/orchestration.yml`, `.github/workflows/python-ci.yml`,
  `.github/pull_request_template.md`, `docs/agent-orchestration.md`,
  `scripts/validate-python.sh`, and `scripts/caf-worktree.sh`.
- CI and validation use uv, Ruff, pytest, Python 3.13, and
  `astral-sh/setup-uv`.
- Orchestration policy requires planning, one task/worktree/branch/PR per
  independent feature, parallelism capped at four, serialization of overlaps,
  CI and review, and human approval before merge.

## Verification Checkpoint

Verified on 2026-08-17 with Python 3.13.1:

- `uv sync`
- `uv run ruff format --check .` — passed
- `uv run ruff check .` — passed
- `uv run pytest` — 1 passed
- `sh tests/test_cli.sh` — passed
- `sh tests/test_init.sh` — passed
- `git diff --check` — passed

The working tree was clean at this checkpoint. The latest local commit
preserved the configured human author, used `Codex <codex@openai.com>` as
committer, and contained an SSH signature made with the human signing key.
Adopting repositories must use their own configured human identity and signing
key; the Codex identity is not a universal repository default.

## Follow-up Work

No required implementation work remains. Future changes should preserve the
technical contract, bootstrap artifact list, orchestration rules, and signed
commit attribution described above.
