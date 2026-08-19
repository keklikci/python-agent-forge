# Contributing to Python Agent Forge

Keep the template portable, privacy-safe, and independent of consumer
repositories. Before submitting, run `sh -n scripts/*.sh`, the CLI tests with
`uv run pytest`, `uv sync`, `uv run ruff format --check .`, and
`uv run ruff check .`.

Keep generated bootstrap content portable: configure repository-specific
values at initialization time, and never persist local absolute paths,
credentials, tokens, or personal data. The orchestration contract applies to
any independently deliverable feature, not only Python source changes.

Use signed Conventional Commits with a lowercase scope and a subject shorter
than 72 characters. Preserve the configured human author and signing key for
commits made with Codex assistance; use the repository's own committer and
co-author policy.
