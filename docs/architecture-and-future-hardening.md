# Architecture and future hardening

Python Agent Forge has two boundaries: a local orchestration engine and an optional GitHub lifecycle layer. The target repository remains the system of record for source code, configuration, task manifests, validation, and review policy.

## Runtime boundaries

```text
Codex skill or CLI
        |
        +-- adoption: inspect and add a compatibility overlay
        |
        +-- runner: plan -> task graph -> isolated worktrees -> validation
        |       |
        |       +-- Codex backend (optional during inspect/adopt/status)
        |       +-- tracked task manifests in .codex/tasks/
        |       +-- ignored runtime state in .codex/state/
        |
        +-- lifecycle: review -> CI -> draft PR -> human merge gate
                |
                +-- GitProvider boundary (GitHub/gh today)
```

The boundaries are deliberate:

- Adoption detects the target's conventions and does not force Forge defaults onto a consumer project.
- The planner is read-only. Workers receive only their assigned worktree and owned paths; they cannot push, merge, change remotes, or handle credentials.
- The runner owns task-graph scheduling, dependency ordering, scope checks, validation, repair attempts, interruption, and resumable state.
- The lifecycle layer owns provider operations, independent review, CI checks, stacked-PR retargeting, and the human merge gate. It never merges.

## Durable versus runtime data

Commit durable intent and reproducibility:

- repository instructions and Forge-managed configuration;
- repository-relative task manifests under `.codex/tasks/`;
- validation commands, acceptance criteria, path ownership, exclusions, and dependency edges;
- architecture and policy documentation.

Keep runtime or sensitive data out of Git:

- absolute worktree paths;
- Codex thread identifiers, attempts, and timestamps;
- authentication material and provider responses that contain private data;
- temporary logs and local caches.

Any new persisted field should be classified as durable or runtime before it is added. Generated content must remain portable across machines and repositories.

## Operating contract

1. Inspect before mutation.
2. Adopt in an isolated migration worktree unless explicitly using local mode.
3. Require a clean source worktree and validate the detected commands.
4. Plan before implementation; validate task IDs, paths, dependencies, and concurrency before starting workers.
5. Keep independent tasks parallel and serialize overlapping paths or prerequisites.
6. Validate scope and commands before review or publication.
7. Require CI and independent review before presenting a PR as ready.
8. Stop at the human merge gate and make recovery state explicit.

## Future hardening backlog

These are concrete reliability cases, not alternate product requirements. Each future change should add a focused fixture or fake-provider test before changing the execution policy.

### Adoption and project detection

- Multiple project roots or `pyproject.toml` files in a monorepo.
- Conflicting lockfiles or package-manager declarations.
- Malformed metadata, missing install commands, or validation commands that require unavailable services.
- Detached HEADs, submodules, linked worktrees, missing remotes, and protected default branches.
- Existing managed headers with partial or manually edited Forge files.
- Adoption interrupted after worktree creation, commit, push, or PR creation.

### Task graphs and workers

- Cyclic dependencies, duplicate task IDs, invalid branch names, and ambiguous overlapping glob ownership.
- A worker commits, changes files outside its scope, or exits after writing but before runtime state is saved.
- Concurrent task preparation fails halfway through, or a process is interrupted while futures are running.
- Validation timeouts, repeated repair failures, stale manifests, and resume after a machine or process restart.

### Provider and review lifecycle

- Authentication expiry between preflight and publication.
- Push succeeds but PR creation, review, or CI polling fails.
- Existing PRs with the same branch, changed base branches, deleted branches, and provider rate limits.
- Stacked PRs after a prerequisite is merged, rebased, closed, or conflicted.
- Review findings that are stale after repair, required checks that disappear, and CI results for the wrong commit.
- Provider operations retried after an unknown remote outcome; retries must be idempotent and must not create duplicate PRs.

### Security and portability

- Secret-like values in planner output, diffs, logs, manifests, and provider errors.
- Symlinks or path traversal that escape a task worktree.
- Repositories with signing requirements, unusual Git identity policy, or non-GitHub hosting.
- Worktree roots on unavailable or non-writable volumes.

Until a case is supported and tested, the safe behavior is to stop, preserve recoverable state, and report the exact blocker. Do not silently broaden scope, disable review, or fall back to unverified credentials.
