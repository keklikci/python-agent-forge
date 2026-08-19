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

To remove a prior Forge starter integration before initializing again, run
`bin/python-agent-forge reset TARGET`. It removes only exact Forge-generated
files and preserves customized or user-owned files such as `AGENTS.md`.

## Adopt an existing project

Inspect an existing local Git repository without changing it:

```sh
python-agent-forge inspect ../existing-project
python-agent-forge inspect ../existing-project --json
```

Apply the detected, compatibility-first overlay locally with
`python-agent-forge adopt ../existing-project --local`. Local mode is intended
for review and offline use. Without `--local`, the forge creates an isolated
`codex/adopt-agent-forge` worktree, commits the overlay, pushes it, and opens a
migration pull request. Existing instructions, CI, dependency managers,
lockfiles, Python constraints, and validation tools are preserved. Dirty
repositories and unknown or contradictory configuration stop before mutation.

See [docs/existing-project-adoption.md](docs/existing-project-adoption.md) for
the detection and safety contract.

`check TARGET` validates a complete `init` starter bundle. After adopting an
existing repository, use `check TARGET --adopted` to validate the smaller
compatibility overlay without requiring Forge's starter CI and documentation
files.

See [docs/command-reference.md](docs/command-reference.md) for the compact
CLI command reference and typical workflows.

See [docs/architecture-and-future-hardening.md](docs/architecture-and-future-hardening.md)
for system boundaries, durable versus runtime data, and the future hardening
backlog.

## Run an autonomous task graph

After adoption, request a plan and execute it in isolated worktrees:

```sh
python-agent-forge run . --request "Implement the requested features"
python-agent-forge status . --json
python-agent-forge resume . RUN_ID
```

The planner is read-only. Workers receive workspace-write access only to their
task worktree, and may not push, merge, change remotes, or handle credentials.
The runner validates task IDs, dependencies, path ownership, repository scope,
and configured commands. It executes up to four independent tasks concurrently
and retries the same worker thread after validation failures. Tracked task
manifests live under `.codex/tasks/`; absolute worktree paths, thread IDs,
attempts, and timestamps live only in ignored `.codex/state/` files.

`run` and `resume` use the stable Python Codex SDK, which is installed by
`uv sync` as a Forge runtime dependency. The SDK also installs the matching
Codex CLI runtime. Existing Codex authentication is reused automatically.
`inspect`, `adopt`, and `status` do not contact Codex and can run without an
authenticated session. GitHub pull-request creation and lifecycle management
are intentionally separate from this local orchestration layer.

To authenticate explicitly when no existing Codex session is available:

```sh
uv run python - <<'PY'
from openai_codex import Codex

with Codex() as codex:
    login = codex.login_chatgpt()
    print(login.auth_url)
    print(login.wait().success)
PY
```

The SDK also supports device-code and API-key login flows; see the [Codex
Python SDK getting started guide](https://github.com/openai/codex/blob/main/sdk/python/docs/getting-started.md).

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
