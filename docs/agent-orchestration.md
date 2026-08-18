# Agent Orchestration

For a request with multiple independently deliverable features, Codex must
plan first and create one task manifest, worktree, `codex/<task-slug>` branch,
and PR per feature. Run independent tasks in parallel up to the configured
limit (four by default). Serialize overlapping paths and dependencies.

CI and review are required before human merge approval. Review agents may
request changes but must not merge. Use `scripts/caf-worktree.sh` to create,
list, and remove isolated worktrees.

The policy is repository- and domain-independent. Package names, task
identifiers, remotes, base branches, models, allowed paths, and concurrency
limits are configuration, not identity. Do not copy local paths, credentials,
tokens, or personal data into task manifests or generated files.

Each pull request should use a scoped Conventional Commit title and describe
its brief, implementation, owned and out-of-scope paths, validation, risks,
dependencies, and follow-up work. Commits made with Codex assistance preserve
the configured human author and are signed with that human's signing key.

See [architecture-and-future-hardening.md](architecture-and-future-hardening.md)
for the durable operating contract and future edge-case backlog.

## Configuration and state

`.codex/project.yml` contains detected repository facts and validation commands.
`.codex/orchestration.yml` contains policy: parallelism, branch prefix, repair
limit, validation timeout, review requirements, and the human merge gate.

Every planned feature is written as a portable tracked manifest at
`.codex/tasks/<run-id>/<task-id>.yml`. Mutable data is separate:
`.codex/state/` is ignored and stores thread IDs, absolute worktree paths,
attempts, timestamps, and current status.

## Execution contract

`python-agent-forge run TARGET (--request TEXT | --request-file FILE)` starts a
read-only planning thread, validates and conservatively serializes its task
graph, then runs ready tasks concurrently in external worktrees. Overlapping or
ambiguous path ownership creates a dependency edge.

Workers have workspace-write access only in their worktree. The runner rejects
out-of-scope changes and invokes validation commands directly without a shell.
A failure is returned to the same thread up to the configured repair limit.
Agents do not push, merge, change remotes, or handle credentials.

`python-agent-forge status TARGET [RUN_ID] [--json]` reads ignored state and
omits local paths from JSON. `python-agent-forge resume TARGET RUN_ID` continues
saved worker threads. Worktrees are retained for inspection and recovery.
GitHub review, checks, PR creation, and stacked-branch lifecycle belong to the
separate GitHub provider layer.
