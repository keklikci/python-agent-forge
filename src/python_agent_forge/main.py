"""Command-line bootstrap and validation for Python Agent Forge consumers."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FILES = {
    "AGENTS.md": """# Python Repository Agent Instructions

- Use Python 3.13 or newer and manage dependencies with `uv`.
- Run `uv run ruff format --check .`, `uv run ruff check .`, and `uv run pytest`.
- For multi-feature requests, use one task manifest, worktree, `codex/<task-slug>` branch, and PR per feature. Parallelize independent work up to four tasks; serialize overlapping paths and dependencies.
- Require CI and review before human merge approval. Review agents must not merge.
""",
    ".codex/project.yml": """python: ">=3.13"
package_manager: uv
formatter: ruff
test_runner: pytest
""",
    ".codex/orchestration.yml": """max_parallel_tasks: 4
branch_prefix: codex/
require_ci: true
require_review: true
require_human_merge_approval: true
""",
    ".github/workflows/python.yml": """name: Python
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv python install 3.13
      - run: uv sync --locked
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run pytest
""",
    ".github/PULL_REQUEST_TEMPLATE.md": """## Summary

## Changes

## Scope

- Owned paths:
- Out of scope:

## Validation

- `uv sync`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run pytest`

## Risks and dependencies

- Risks:
- Dependencies:
""",
    "docs/agent-orchestration.md": """# Agent Orchestration

Plan multi-feature requests before implementation. Create one task manifest,
worktree, `codex/<task-slug>` branch, and pull request for each independent
feature. Run independent tasks in parallel (up to four by default), serialize
overlapping paths and dependencies, and require CI, review, and human approval
before merge.
""",
    "scripts/validate-python.sh": """#!/bin/sh
set -eu
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest
""",
}

PRIVATE_PARTS = {".ssh", ".gnupg", ".aws", ".config", "Library"}
SECRET_WORDS = re.compile(r"(?:token|password|secret|credential|api[_-]?key)", re.I)


def _unsafe_target(target: Path) -> str | None:
    resolved = target.expanduser().resolve()
    if any(part in PRIVATE_PARTS for part in resolved.parts):
        return "private path"
    if SECRET_WORDS.search(str(target)):
        return "path resembles a secret-bearing location"
    return None


def init(target: Path) -> int:
    reason = _unsafe_target(target)
    if reason:
        print(f"error: refusing {reason}: {target}", file=sys.stderr)
        return 1
    target.mkdir(parents=True, exist_ok=True)
    created = 0
    for name, content in FILES.items():
        path = target / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if name.endswith(".sh"):
            path.chmod(0o755)
        created += 1
    print(f"init: created {created} files in {target}")
    return 0


def check(target: Path) -> int:
    missing = [name for name in FILES if not (target / name).is_file()]
    if missing:
        print("check: missing " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"check: OK ({target})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python-agent-forge")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("init", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("target_directory", type=Path)
    subparsers.add_parser("help")
    args = parser.parse_args(argv)
    if args.command == "init":
        return init(args.target_directory)
    if args.command == "check":
        return check(args.target_directory)
    if args.command == "help":
        parser.print_help()
        return 0
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
