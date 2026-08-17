# Python Agent Forge

Python repository automation with uv, Ruff, pytest, and parallel PR workflows.
PAF is a GitHub template and
portable bootstrap kit for Python 3.13+ repositories using `uv`, Ruff, pytest,
and isolated worktree-based parallel pull requests.

## Defaults

- Python 3.13 or newer.
- `uv` for environments, dependencies, and command execution.
- Ruff for formatting and linting.
- pytest for tests.
- One task, branch, worktree, and pull request per independently deliverable
  feature; overlapping path ownership is serialized.
- The target repository supplies its own package name, repository identity,
  task identifiers, remote, base branch, model, and allowed paths. Generated
  content uses configurable placeholders and must not contain local paths,
  credentials, tokens, or personal data.

## Start a project

Use this repository as a GitHub template, then run:

```sh
bin/python-agent-forge init .
bin/python-agent-forge check .
scripts/validate-python.sh
```

The template itself is immediately runnable:

```sh
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

## Codex orchestration

For a multi-feature request, Codex plans first, uses one worktree and branch
per independent feature, runs non-overlapping work in parallel (four tasks by
default), opens one PR per feature, and requires CI, review, and human merge
approval. See [docs/agent-orchestration.md](docs/agent-orchestration.md).

## Git conventions

Use a Conventional Commit subject with a lowercase scope, an imperative verb,
and no trailing period. Keep subjects below 72 characters and separate
independent changes into separate commits. Pull requests use the same title
format and document the brief, implementation, owned and out-of-scope paths,
validation, risks, dependencies, and follow-up work.

Commits made with Codex assistance preserve the configured human author and
must be signed with that human's configured signing key. Codex may be recorded
as the committer or co-author according to the repository's local policy; no
identity, email, key, model, or remote is a universal default.
