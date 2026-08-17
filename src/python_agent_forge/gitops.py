"""Safe Git, worktree, scope, and validation helpers."""

from __future__ import annotations

import fnmatch
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from python_agent_forge.config import ConfigurationError


class ExecutionError(RuntimeError):
    """A worker violated scope or failed repository validation."""


def _git(
    target: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def require_clean_repository(target: Path) -> None:
    result = _git(target, "status", "--porcelain")
    if result.stdout.strip():
        raise ConfigurationError("target repository has uncommitted changes")


def worktree_root(target: Path) -> Path:
    common = _git(target, "rev-parse", "--git-common-dir").stdout.strip()
    if not common:
        raise ConfigurationError("cannot locate common Git directory")
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (target / common_path).resolve()
    return common_path.parent.parent / ".paf-worktrees"


def create_worktree(
    target: Path, run_id: str, task_id: str, branch: str, base: str
) -> Path:
    destination = worktree_root(target) / run_id / task_id
    if destination.exists():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(target, "worktree", "add", "-b", branch, str(destination), base)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or str(error)
        raise ExecutionError(
            f"cannot create worktree for {task_id}: {detail}"
        ) from error
    return destination


def changed_paths(worktree: Path, base: str) -> list[str]:
    committed = _git(worktree, "diff", "--name-status", "-z", base, "--").stdout
    tokens = committed.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index]
        index += 1
        if index >= len(tokens):
            break
        paths.add(tokens[index])
        index += 1
        if status.startswith(("R", "C")) and index < len(tokens):
            paths.add(tokens[index])
            index += 1

    pending = _git(worktree, "status", "--porcelain=v1", "-z", "-uall").stdout
    tokens = pending.split("\0")
    index = 0
    while index < len(tokens) and tokens[index]:
        entry = tokens[index]
        index += 1
        status, path = entry[:2], entry[3:]
        if path:
            paths.add(path)
        if ("R" in status or "C" in status) and index < len(tokens):
            if tokens[index]:
                paths.add(tokens[index])
            index += 1
    return sorted(paths)


def head_sha(worktree: Path) -> str:
    value = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    if not value:
        raise ExecutionError("cannot determine task start SHA")
    return value


def _matches(path: str, pattern: str) -> bool:
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return PurePosixPath(path).match(pattern)


def enforce_scope(paths: list[str], owned_paths: list[str]) -> None:
    violations = [
        path
        for path in paths
        if not any(_matches(path, pattern) for pattern in owned_paths)
    ]
    if violations:
        raise ExecutionError("out-of-scope changes: " + ", ".join(violations))


@dataclass(frozen=True)
class ValidationResult:
    command: str
    returncode: int
    output: str


def run_validations(
    worktree: Path, commands: list[str], timeout_seconds: int
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for command in commands:
        if not command or any(character in command for character in "\n\r"):
            raise ConfigurationError(f"unsafe validation command: {command!r}")
        try:
            arguments = shlex.split(command)
        except ValueError as error:
            raise ConfigurationError(
                f"invalid validation command: {command}"
            ) from error
        if not arguments:
            raise ConfigurationError("validation command cannot be empty")
        try:
            completed = subprocess.run(
                arguments,
                cwd=worktree,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ExecutionError(
                f"validation could not run: {command}: {error}"
            ) from error
        output = (completed.stdout + completed.stderr)[-8000:]
        result = ValidationResult(command, completed.returncode, output)
        results.append(result)
        if completed.returncode:
            raise ExecutionError(
                f"validation failed ({command}, exit {completed.returncode}):\n{output}"
            )
    return results
