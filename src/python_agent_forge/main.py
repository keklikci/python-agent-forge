"""Command-line interface for Python Agent Forge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from python_agent_forge.adoption import (
    AdoptionError,
    adopt_in_worktree,
    adopt_local,
    format_inspection,
    inspect_repository,
)
from python_agent_forge.backend import OpenAICodexBackend
from python_agent_forge.config import ConfigurationError
from python_agent_forge.gitops import ExecutionError
from python_agent_forge.lifecycle import PullRequestLifecycle
from python_agent_forge.provider import GhGitHubProvider
from python_agent_forge.review import OpenAICodexReviewer
from python_agent_forge.runner import (
    OrchestrationError,
    Orchestrator,
    format_status,
    status,
    status_json,
)


def _github_orchestrator(
    target: Path,
    *,
    base: str | None = None,
    model: str | None = None,
    max_parallel: int | None = None,
) -> Orchestrator:
    backend = OpenAICodexBackend()
    orchestrator = Orchestrator(
        target,
        backend,
        base=base,
        model=model,
        max_parallel=max_parallel,
    )
    orchestrator.lifecycle = PullRequestLifecycle(
        orchestrator.target,
        GhGitHubProvider(),
        OpenAICodexReviewer(),
        backend,
        orchestrator.policy,
    )
    return orchestrator


FILES = {
    "AGENTS.md": """# Python Repository Agent Instructions

- Use Python 3.13 or newer and manage dependencies with `uv`.
- Run `uv run ruff format --check .`, `uv run ruff check .`, and `uv run pytest`.
- Never persist local absolute paths, credentials, tokens, or private data.
""",
    ".codex/project.yml": """# Managed by Python Agent Forge.
version: 1
python_constraint: ">=3.13"
package_manager: "uv"
install_command: "uv sync"
validation_commands:
  - "uv run ruff format --check ."
  - "uv run ruff check ."
  - "uv run pytest"
""",
    ".codex/orchestration.yml": """# Managed by Python Agent Forge.
version: 1
max_parallel_tasks: 4
branch_prefix: codex/
repair_limit: 2
require_ci: true
require_review: true
require_human_merge_approval: true
""",
    ".github/workflows/python-ci.yml": """name: Python CI
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run pytest
""",
    ".github/pull_request_template.md": """## Summary

## Changes

## Scope

- Owned paths:
- Out of scope:

## Validation

## Risks and dependencies
""",
    "docs/agent-orchestration.md": """# Agent Orchestration

Use one task manifest, worktree, branch, and reviewed pull request per feature.
Human approval is required before merge.
""",
    "scripts/validate-python.sh": """#!/bin/sh
set -eu
uv sync
uv run ruff format --check .
uv run ruff check .
uv run pytest
""",
    "scripts/caf-worktree.sh": """#!/bin/sh
set -eu
printf '%s\n' 'Use python-agent-forge adoption and orchestration commands.'
""",
}

PRIVATE_PARTS = {".ssh", ".gnupg", ".aws", ".config", "Library"}


def _unsafe_target(target: Path) -> str | None:
    resolved = target.expanduser().resolve()
    if any(part in PRIVATE_PARTS for part in resolved.parts):
        return "private path"
    lowered = str(target).lower()
    secret_words = ("token", "password", "secret", "credential", "api_key")
    if any(word in lowered for word in secret_words):
        return "path resembles a secret-bearing location"
    return None


def init(target: Path) -> int:
    reason = _unsafe_target(target)
    if reason:
        print(f"error: refusing {reason}: {target}", file=sys.stderr)
        return 2
    collisions = [name for name in FILES if (target / name).exists()]
    if collisions and os.environ.get("PAF_FORCE") != "1":
        print(f"error: refusing to overwrite {collisions[0]}", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if name.endswith(".sh"):
            path.chmod(0o755)
    print(f"init: created {len(FILES)} files in {target}")
    return 0


def check(target: Path) -> int:
    missing = [name for name in FILES if not (target / name).is_file()]
    if missing:
        print("check: missing " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"check: OK ({target})")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python-agent-forge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  python-agent-forge init <target-directory>
  python-agent-forge check <target-directory>
  python-agent-forge inspect TARGET [--json]
  python-agent-forge adopt TARGET [--base BRANCH] [--local]
  python-agent-forge run TARGET (--request TEXT | --request-file FILE)
  python-agent-forge status TARGET [RUN_ID] [--json]
  python-agent-forge resume TARGET RUN_ID
""",
    )
    subparsers = parser.add_subparsers(dest="command")
    for command in ("init", "check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("target_directory", type=Path)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("target", type=Path)
    inspect_parser.add_argument("--json", action="store_true", dest="as_json")
    adopt_parser = subparsers.add_parser("adopt")
    adopt_parser.add_argument("target", type=Path)
    adopt_parser.add_argument("--base")
    adopt_parser.add_argument("--local", action="store_true")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("target", type=Path)
    request = run_parser.add_mutually_exclusive_group(required=True)
    request.add_argument("--request")
    request.add_argument("--request-file", type=Path)
    run_parser.add_argument("--base")
    run_parser.add_argument("--model")
    run_parser.add_argument("--max-parallel", type=int)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("target", type=Path)
    status_parser.add_argument("run_id", nargs="?")
    status_parser.add_argument("--json", action="store_true", dest="as_json")
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("target", type=Path)
    resume_parser.add_argument("run_id")
    subparsers.add_parser("help")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return init(args.target_directory)
        if args.command == "check":
            return check(args.target_directory)
        if args.command == "inspect":
            facts = inspect_repository(args.target)
            if args.as_json:
                print(json.dumps(facts.public_dict(), indent=2, sort_keys=True))
            else:
                print(format_inspection(facts))
            return 0
        if args.command == "adopt":
            if args.local:
                _, changes = adopt_local(args.target)
                print(f"adopt: updated {len(changes)} files")
            else:
                worktree, changes = adopt_in_worktree(args.target, args.base)
                print(
                    "adopt: opened migration PR from "
                    f"{worktree.name} ({len(changes)} files)"
                )
            return 0
        if args.command == "run":
            request_text = args.request
            if args.request_file:
                request_text = args.request_file.read_text(encoding="utf-8")
            orchestrator = _github_orchestrator(
                args.target,
                base=args.base,
                model=args.model,
                max_parallel=args.max_parallel,
            )
            run_state = orchestrator.run(request_text)
            print(format_status(run_state))
            return 0 if run_state.status in {"completed", "awaiting_human_merge"} else 1
        if args.command == "status":
            run_state = status(args.target, args.run_id)
            print(status_json(run_state) if args.as_json else format_status(run_state))
            return 0
        if args.command == "resume":
            run_state = _github_orchestrator(args.target).resume(args.run_id)
            print(format_status(run_state))
            return 0 if run_state.status in {"completed", "awaiting_human_merge"} else 1
        if args.command == "help":
            parser.print_help()
            return 0
    except (
        AdoptionError,
        ConfigurationError,
        ExecutionError,
        OrchestrationError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
