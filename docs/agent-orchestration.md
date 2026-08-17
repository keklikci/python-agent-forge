# Agent Orchestration

For a request with multiple independently deliverable features, Codex must
plan first and create one task manifest, worktree, `codex/<task-slug>` branch,
and PR per feature. Run independent tasks in parallel up to the configured
limit (four by default). Serialize overlapping paths and dependencies.

CI and review are required before human merge approval. Review agents may
request changes but must not merge. Use `scripts/caf-worktree.sh` to create,
list, and remove isolated worktrees.
