---
name: python-agent-forge
description: Use when adopting an existing Python repository into Python Agent Forge or when planning, running, checking, resuming, and reviewing multi-agent feature work through Forge's isolated worktrees and PR workflow.
---

# Python Agent Forge

Use the target repository's Forge CLI as the source of truth. Work in the project opened in Codex; the Forge source repository is only needed when the CLI is not installed. Preserve the target repository's package manager, Python minimum, tests, CI, lockfiles, and local instructions.

## Safety

- Inspect before modifying: `python-agent-forge inspect TARGET --json`.
- Preserve the target's package manager, Python minimum, tests, CI, and local instructions. Never overwrite existing files silently.
- Require a clean Git worktree before non-local adoption or orchestration.
- Keep secrets, credentials, absolute local paths, and personal data out of tracked manifests and generated files.
- Use one task, branch, isolated worktree, and PR per independent feature. Serialize overlapping paths and dependencies.
- Workers and reviewers may not merge; human approval remains required.

## Start or verify a Forge project

For a new starter repository:

```sh
bin/python-agent-forge init TARGET
bin/python-agent-forge check TARGET
scripts/validate-python.sh
```

If a previous starter setup blocks initialization, use `reset TARGET` first.
Reset removes only exact Forge-generated files and preserves customized or
user-owned files. For an adopted repository, use `check TARGET --adopted`;
the adopted check does not require starter CI, documentation, or helper files.

## Adopt an existing project

From the Codex workspace containing the target repository:

```sh
python-agent-forge inspect . --json
python-agent-forge adopt .
```

Use `adopt --local` for offline or local review. The non-local command creates
an isolated `codex/adopt-agent-forge` worktree, commits and pushes the overlay,
and opens a migration PR. Inspect the migration diff and confirm generated
validation commands match the project before proceeding. Adoption detects
existing tests and linters; if none are found, it may use a compile-only
bootstrap check until project-specific validation is added. Stop and report
unknown layouts, contradictory instructions, dirty state, unsafe paths, or
unusable validation instead of guessing.

## Run orchestration

After adoption is reviewed or the project is already configured:

```sh
python-agent-forge run . --request "Describe the feature or fix"
python-agent-forge status .
python-agent-forge resume . RUN_ID
```

For long requests, prefer `--request-file`. Confirm task ownership, exclusions, dependencies, and acceptance criteria when the request has material product or security ambiguity. Let Forge create isolated worktrees, run validation, and enforce scope.

The planner is read-only. Workers may modify only their assigned worktree and
owned paths; they may not push, merge, change remotes, or handle credentials.
Tracked task manifests belong under `.codex/tasks/`. Keep absolute worktree
paths, thread IDs, attempts, timestamps, temporary logs, credentials, tokens,
and provider responses out of Git; runtime state belongs in ignored
`.codex/state/` files. `run` and `resume` require the stable Python Codex SDK
and an authenticated Codex session, while `inspect`, `adopt`, and `status` can
run without contacting Codex.

Forge's local orchestration is separate from GitHub pull-request lifecycle.
When publishing changes, use the repository's provider workflow for review and
CI; do not present a PR as ready until independent review and CI pass.

## Handoff

Report the run ID, task statuses, branch names, validation results, review findings, and PR URLs. Do not claim completion until validation, CI, and review requirements pass. If GitHub authentication or CI is unavailable, state the exact blocker and leave branches and worktrees recoverable.
