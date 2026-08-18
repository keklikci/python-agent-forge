"""Ignored mutable state for resumable orchestration runs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from python_agent_forge.config import ConfigurationError


def now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TaskState:
    status: str = "queued"
    thread_id: str | None = None
    worktree: str | None = None
    start_sha: str | None = None
    stack_parent_task_id: str | None = None
    manifest: dict[str, Any] | None = None
    attempts: int = 0
    error: str | None = None
    updated_at: str = field(default_factory=now)


@dataclass
class RunState:
    run_id: str
    target: str
    base_branch: str
    model: str | None
    status: str = "planned"
    assumptions: list[str] = field(default_factory=list)
    tasks: dict[str, TaskState] = field(default_factory=dict)
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("target", None)
        for task in value["tasks"].values():
            task.pop("worktree", None)
            task.pop("start_sha", None)
            task.pop("manifest", None)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunState:
        tasks = {
            task_id: TaskState(**task_value)
            for task_id, task_value in value.pop("tasks", {}).items()
        }
        return cls(tasks=tasks, **value)


class StateStore:
    def __init__(self, target: Path) -> None:
        self.target = target.resolve()
        self.directory = self.target / ".codex/state"

    def ensure_ignored(self) -> None:
        """Ignore state locally without mutating a consumer's tracked files."""
        ignored = subprocess.run(
            [
                "git",
                "-C",
                str(self.target),
                "check-ignore",
                "-q",
                ".codex/state/probe",
            ],
            check=False,
            capture_output=True,
        )
        if ignored.returncode == 0:
            return
        git_dir_result = subprocess.run(
            ["git", "-C", str(self.target), "rev-parse", "--git-path", "info/exclude"],
            check=False,
            capture_output=True,
            text=True,
        )
        exclude_name = git_dir_result.stdout.strip()
        if not exclude_name:
            raise ConfigurationError("cannot locate Git exclude file")
        exclude = Path(exclude_name)
        if not exclude.is_absolute():
            exclude = self.target / exclude
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ".codex/state/" not in existing.splitlines():
            with exclude.open("a", encoding="utf-8") as stream:
                if existing and not existing.endswith("\n"):
                    stream.write("\n")
                stream.write(".codex/state/\n")

    def save(self, state: RunState) -> None:
        self.ensure_ignored()
        self.directory.mkdir(parents=True, exist_ok=True)
        state.updated_at = now()
        destination = self.directory / f"{state.run_id}.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(destination)

    def load(self, run_id: str) -> RunState:
        if not re_safe_id(run_id):
            raise ConfigurationError(f"invalid run ID: {run_id!r}")
        path = self.directory / f"{run_id}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"cannot load run {run_id}: {error}") from error
        return RunState.from_dict(value)

    def latest(self) -> RunState:
        paths = sorted(self.directory.glob("*.json"), reverse=True)
        if not paths:
            raise ConfigurationError("no orchestration runs found")
        return self.load(paths[0].stem)


def re_safe_id(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 80
        and all(character.isalnum() or character in "-_." for character in value)
    )
