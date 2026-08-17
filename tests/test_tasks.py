from __future__ import annotations

from pathlib import Path

import pytest

from python_agent_forge.config import ConfigurationError
from python_agent_forge.tasks import TaskGraph, TaskManifest, scopes_overlap


def _task(
    task_id: str, paths: list[str], dependencies: list[str] | None = None
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        brief=f"Implement {task_id}",
        acceptance_criteria=["It works"],
        owned_paths=paths,
        exclusions=[],
        dependencies=dependencies or [],
        branch=f"codex/{task_id}",
        validation_commands=["python -c 'pass'"],
    )


def test_overlapping_scopes_are_serialized() -> None:
    first = _task("first", ["src/**"])
    second = _task("second", ["src/package/**"])
    graph = TaskGraph([first, second]).validate_and_serialize()
    assert graph.tasks[1].dependencies == ["first"]
    assert scopes_overlap(first.owned_paths, second.owned_paths)


def test_independent_scopes_remain_parallel() -> None:
    first = _task("first", ["src/**"])
    second = _task("second", ["tests/**"])
    TaskGraph([first, second]).validate_and_serialize()
    assert second.dependencies == []


def test_cycles_and_unknown_dependencies_fail() -> None:
    with pytest.raises(ConfigurationError, match="cycle"):
        TaskGraph(
            [_task("first", ["src/a/**"], ["second"]), _task("second", ["src/a/**"])]
        ).validate_and_serialize()
    with pytest.raises(ConfigurationError, match="unknown"):
        TaskGraph([_task("first", ["src/**"], ["missing"])]).validate_and_serialize()


@pytest.mark.parametrize("path", ["/etc/passwd", "../outside", "src/../../outside"])
def test_unsafe_owned_paths_fail(path: str) -> None:
    with pytest.raises(ConfigurationError, match="unsafe owned path"):
        _task("unsafe", [path]).validate()


def test_manifest_round_trip_is_portable(tmp_path: Path) -> None:
    task = _task("portable", ["src/**"])
    path = tmp_path / "portable.yml"
    task.write(path)
    loaded = TaskManifest.load(path)
    assert loaded == task
    assert str(tmp_path) not in path.read_text()
