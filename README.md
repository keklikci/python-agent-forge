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
