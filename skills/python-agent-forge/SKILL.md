---
name: python-agent-forge
description: Use when adopting an existing Python repository into Python Agent Forge or when planning, running, checking, resuming, and reviewing multi-agent feature work through Forge's isolated worktrees and PR workflow.
---

# Python Agent Forge

Use the target repository's Forge CLI as the source of truth. Work in the project opened in Codex; the Forge source repository is only needed when the CLI is not installed.

## Safety

- Inspect before modifying: `python-agent-forge inspect TARGET --json`.
- Preserve the target's package manager, Python minimum, tests, CI, and local instructions. Never overwrite existing files silently.
- Require a clean Git worktree before non-local adoption or orchestration.
- Keep secrets, credentials, absolute local paths, and personal data out of tracked manifests and generated files.
- Use one task, branch, isolated worktree, and PR per independent feature. Serialize overlapping paths and dependencies.
- Workers and reviewers may not merge; human approval remains required.

## Adopt an existing project

From the Codex workspace containing the target repository:

```sh
python-agent-forge inspect . --json
python-agent-forge adopt .
```

Use `adopt --local` only for offline/local testing. Inspect the migration diff and confirm generated validation commands match the project. Stop and report unknown layouts, contradictory instructions, dirty state, unsafe paths, or unusable validation instead of guessing.

## Run orchestration

After adoption is reviewed or the project is already configured:

```sh
python-agent-forge run . --request "Describe the feature or fix"
python-agent-forge status .
python-agent-forge resume . RUN_ID
```

For long requests, prefer `--request-file`. Confirm task ownership, exclusions, dependencies, and acceptance criteria when the request has material product or security ambiguity. Let Forge create isolated worktrees, run validation, and enforce scope.

## Handoff

Report the run ID, task statuses, branch names, validation results, review findings, and PR URLs. Do not claim completion until validation, CI, and review requirements pass. If GitHub authentication or CI is unavailable, state the exact blocker and leave branches and worktrees recoverable.
