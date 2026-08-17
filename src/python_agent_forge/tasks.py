"""Tracked task manifests and safe dependency graph validation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from python_agent_forge.config import ConfigurationError, load_mapping

TASK_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,62})$")


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _scope_root(pattern: str) -> str:
    parts = []
    for part in PurePosixPath(pattern).parts:
        if any(character in part for character in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def scopes_overlap(left: list[str], right: list[str]) -> bool:
    """Conservatively determine whether two owned path sets may overlap."""
    for left_pattern in left:
        for right_pattern in right:
            left_root, right_root = (
                _scope_root(left_pattern),
                _scope_root(right_pattern),
            )
            if not left_root or not right_root:
                return True
            if (
                left_root == right_root
                or left_root.startswith(right_root + "/")
                or right_root.startswith(left_root + "/")
            ):
                return True
    return False


@dataclass
class TaskManifest:
    task_id: str
    brief: str
    acceptance_criteria: list[str]
    owned_paths: list[str]
    exclusions: list[str]
    dependencies: list[str]
    branch: str
    validation_commands: list[str]
    pr: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskManifest:
        required_lists = (
            "acceptance_criteria",
            "owned_paths",
            "exclusions",
            "dependencies",
            "validation_commands",
        )
        for key in required_lists:
            if not isinstance(data.get(key), list) or not all(
                isinstance(value, str) for value in data[key]
            ):
                raise ConfigurationError(f"task {key} must be a list of strings")
        task = cls(
            task_id=str(data.get("task_id", "")),
            brief=str(data.get("brief", "")),
            acceptance_criteria=list(data["acceptance_criteria"]),
            owned_paths=list(data["owned_paths"]),
            exclusions=list(data["exclusions"]),
            dependencies=list(data["dependencies"]),
            branch=str(data.get("branch", "")),
            validation_commands=list(data["validation_commands"]),
            pr=dict(data.get("pr", {})),
        )
        task.validate()
        return task

    @classmethod
    def load(cls, path: Path) -> TaskManifest:
        return cls.from_dict(load_mapping(path))

    def validate(self) -> None:
        if not TASK_ID.fullmatch(self.task_id):
            raise ConfigurationError(f"invalid task ID: {self.task_id!r}")
        if not self.brief or not self.acceptance_criteria:
            raise ConfigurationError(f"task {self.task_id} needs a brief and criteria")
        if not self.owned_paths:
            raise ConfigurationError(f"task {self.task_id} has no owned paths")
        for path in self.owned_paths:
            if not _safe_relative(path):
                raise ConfigurationError(f"unsafe owned path in {self.task_id}: {path}")
        invalid_branch = (
            not self.branch
            or self.branch.startswith(("-", "/"))
            or self.branch.endswith(("/", "."))
            or ".." in self.branch
            or "//" in self.branch
            or not re.fullmatch(r"[A-Za-z0-9._/-]+", self.branch)
        )
        if invalid_branch:
            raise ConfigurationError(f"invalid branch for {self.task_id}")

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


@dataclass
class TaskGraph:
    tasks: list[TaskManifest]

    def validate_and_serialize(self) -> TaskGraph:
        by_id = {task.task_id: task for task in self.tasks}
        if len(by_id) != len(self.tasks):
            raise ConfigurationError("duplicate task IDs")
        for task in self.tasks:
            unknown = set(task.dependencies) - set(by_id)
            if unknown:
                raise ConfigurationError(
                    f"task {task.task_id} has unknown dependencies: {sorted(unknown)}"
                )
        # Add deterministic edges for scopes that could overlap.
        for index, task in enumerate(self.tasks):
            for earlier in self.tasks[:index]:
                if scopes_overlap(task.owned_paths, earlier.owned_paths):
                    if earlier.task_id not in task.dependencies:
                        task.dependencies.append(earlier.task_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ConfigurationError("task dependency graph contains a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in by_id[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in by_id:
            visit(task_id)
        return self

    def by_id(self) -> dict[str, TaskManifest]:
        return {task.task_id: task for task in self.tasks}
