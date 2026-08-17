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
