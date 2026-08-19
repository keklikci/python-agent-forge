# Existing-project adoption

Python Agent Forge can inspect and adopt an existing local Git repository
without forcing the template's Python or dependency-management defaults onto
it.

`python-agent-forge inspect TARGET [--json]` is read-only. It detects packaging
metadata, uv/Poetry/PDM/Pipenv/requirements workflows, Python constraints,
source and test paths, pytest/unittest/tox/nox, quality tools, GitHub Actions,
repository identity, and the base branch. JSON output deliberately omits the
absolute target path so it is safe to save as project metadata.

`python-agent-forge adopt TARGET --local` writes a small managed overlay for
local review. Omitting `--local` creates the `codex/adopt-agent-forge` branch in
an isolated worktree and opens a migration pull request with `gh`. Use `--base`
when the remote default branch cannot be detected.

Adoption preserves the consumer project's Python constraint and package
manager. It uses `uv sync` only for uv projects, `uv pip` for requirements or
legacy pip projects, and the native command for Poetry, PDM, or Pipenv. Existing
validation and CI remain authoritative; a forge workflow is generated only
when current workflows do not contain every detected validation command.

The operation stops before writing when the worktree is dirty, `AGENTS.md`
contradicts the orchestration safety rules, or `.codex` contains an unknown
schema. Existing unmanaged files are never overwritten. Generated files carry
a managed header and contain only repository-relative paths and portable
identifiers. Re-running adoption after committing its output produces no
changes.

Unknown layouts receive a safe overlay with
`autonomous_execution_ready: false`; configure valid install and validation
commands before autonomous work. Projects with an install command but no
detected tests or linters receive the real bootstrap check
`uv run python -m compileall .` (with the detected runner prefix), so a first
tooling task can add project-specific validation. Re-run adoption after
updating a project so the managed overlay reflects its current layout.
