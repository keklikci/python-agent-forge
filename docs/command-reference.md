# Command reference

Run these commands from the Forge repository, or use the installed
`python-agent-forge` executable for an adopted target.

| Command | Purpose |
| --- | --- |
| `bin/python-agent-forge init TARGET` | Create the Forge starter files. |
| `bin/python-agent-forge check TARGET` | Check required starter files. |
| `bin/python-agent-forge reset TARGET` | Remove exact Forge starter files, preserving user-owned files. |
| `python-agent-forge inspect TARGET [--json]` | Read-only project detection. |
| `python-agent-forge adopt TARGET --local` | Write and review the adoption overlay locally. |
| `python-agent-forge adopt TARGET [--base BRANCH]` | Create, push, and open the adoption PR. |
| `python-agent-forge run TARGET --request TEXT` | Plan and execute a task graph. |
| `python-agent-forge run TARGET --request-file FILE` | Read the task request from a file. |
| `python-agent-forge status TARGET [RUN_ID] [--json]` | Show a run or the latest run. |
| `python-agent-forge resume TARGET RUN_ID` | Continue an interrupted run. |

## Typical workflows

```sh
# New repository
bin/python-agent-forge init .
bin/python-agent-forge check .
scripts/validate-python.sh

# Existing repository
python-agent-forge inspect TARGET --json
python-agent-forge adopt TARGET --local
python-agent-forge run TARGET --request "Describe the feature"
python-agent-forge status TARGET --json
python-agent-forge resume TARGET RUN_ID
```

`inspect` is read-only. `adopt --local` changes the target and requires a
clean worktree unless explicitly allowed by the Python API. The non-local
`adopt` command uses an isolated worktree and opens a migration PR.

Adoption detects existing tests and linters. If an install command exists but
no tests or linters are detected, it adds the bootstrap check
`uv run python -m compileall .` (or the equivalent project runner), allowing a
tooling-bootstrap task to add project-specific validation. Unknown layouts
remain not ready until install and validation commands are configured.

## Repository validation

```sh
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

If `init` is blocked by a previous Forge setup, run `bin/python-agent-forge
reset TARGET` and then `init` again. Reset removes only files whose contents
exactly match Forge's starter files; it preserves customized or user-owned
files such as `AGENTS.md` and reports them on stderr.
