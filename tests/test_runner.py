from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from python_agent_forge.runner import Orchestrator, status
from python_agent_forge.tasks import TaskManifest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repository(tmp_path: Path, *, repair_limit: int = 2) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    project = {
        "version": 1,
        "base_branch": "main",
        "install_command": "python -c 'pass'",
        "validation_commands": [
            "python -c \"import pathlib; assert pathlib.Path('src').is_dir()\""
        ],
        "autonomous_execution_ready": True,
    }
    policy = {
        "version": 1,
        "max_parallel_tasks": 4,
        "branch_prefix": "codex/",
        "repair_limit": repair_limit,
        "validation_timeout_seconds": 20,
        "require_human_merge_approval": True,
    }
    for relative, value in (
        (".codex/project.yml", project),
        (".codex/orchestration.yml", policy),
    ):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
    (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


class FakeBackend:
    def __init__(
        self,
        tasks: list[dict[str, Any]],
        *,
        bad_scope: bool = False,
        commit_changes: bool = False,
    ) -> None:
        self.tasks = tasks
        self.bad_scope = bad_scope
        self.commit_changes = commit_changes
        self.repairs = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def plan(
        self, target: Path, request: str, base: str, model: str | None
    ) -> dict[str, Any]:
        assert request
        assert base == "main"
        return {"assumptions": ["Keep public behavior stable"], "tasks": self.tasks}

    def implement(self, task: TaskManifest, worktree: Path, model: str | None) -> str:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            relative = "outside.txt" if self.bad_scope else f"src/{task.task_id}.py"
            path = worktree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("implemented = True\n", encoding="utf-8")
            if self.commit_changes:
                _git(worktree, "add", ".")
                _git(worktree, "commit", "-m", f"implement {task.task_id}")
        finally:
            with self.lock:
                self.active -= 1
        return f"thread-{task.task_id}"

    def repair(self, thread_id: str, worktree: Path, feedback: str) -> None:
        self.repairs += 1
        if not self.bad_scope:
            outside = worktree / "outside.txt"
            if outside.exists():
                outside.unlink()
            task_id = thread_id.removeprefix("thread-")
            path = worktree / "src" / f"{task_id}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("implemented = True\n", encoding="utf-8")


def _planned(
    task_id: str, path: str, dependencies: list[str] | None = None
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "brief": f"Implement {task_id}",
        "acceptance_criteria": ["Feature is implemented"],
        "owned_paths": [path],
        "exclusions": [],
        "dependencies": dependencies or [],
        "pr": {"title": f"feat({task_id}): implement feature"},
    }


def test_run_executes_independent_tasks_in_parallel_and_tracks_state(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    backend = FakeBackend(
        [_planned("alpha", "src/alpha.py"), _planned("beta", "src/beta.py")]
    )
    result = Orchestrator(repo, backend, max_parallel=2).run("Implement both features")

    assert result.status == "completed", {
        key: value.error for key, value in result.tasks.items()
    }
    assert backend.max_active == 2
    assert all(task.status == "completed" for task in result.tasks.values())
    alpha_worktree = Path(result.tasks["alpha"].worktree or "")
    assert (alpha_worktree / ".codex/tasks" / result.run_id / "alpha.yml").is_file()
    root_status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert root_status.stdout == ""
    state = status(repo, result.run_id)
    assert state.status == "completed"
    public = state.public_dict()
    assert "target" not in public
    assert all("worktree" not in task for task in public["tasks"].values())
    ignored = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", ".codex/state"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 0


def test_dependencies_are_ordered(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    backend = FakeBackend(
        [
            _planned("first", "src/first.py"),
            _planned("second", "src/second.py", ["first"]),
        ],
        commit_changes=True,
    )
    result = Orchestrator(repo, backend).run("Implement a dependency chain")
    assert result.status == "completed", {
        key: value.error for key, value in result.tasks.items()
    }
    assert backend.max_active == 1
    second = result.tasks["second"]
    assert second.stack_parent_task_id == "first"
    assert second.worktree
    assert (Path(second.worktree) / "src/first.py").is_file()


def test_scope_violation_retries_then_fails(tmp_path: Path) -> None:
    repo = _repository(tmp_path, repair_limit=1)
    backend = FakeBackend([_planned("scoped", "src/**")], bad_scope=True)
    result = Orchestrator(repo, backend).run("Violate scope")
    task = result.tasks["scoped"]
    assert result.status == "failed"
    assert task.status == "failed"
    assert task.attempts == 2
    assert backend.repairs == 1
    assert "out-of-scope" in (task.error or "")


def test_resume_continues_saved_worker_thread(tmp_path: Path) -> None:
    repo = _repository(tmp_path, repair_limit=0)
    backend = FakeBackend([_planned("resume-me", "src/**")], bad_scope=True)
    first = Orchestrator(repo, backend).run("Create a resumable failure")
    assert first.status == "failed"
    backend.bad_scope = False
    resumed = Orchestrator(repo, backend).resume(first.run_id)
    assert resumed.status == "completed", resumed.tasks["resume-me"].error
    assert resumed.tasks["resume-me"].thread_id == "thread-resume-me"
    assert backend.repairs == 1


def test_failed_validation_is_repaired_on_same_thread(tmp_path: Path) -> None:
    repo = _repository(tmp_path, repair_limit=1)
    planned = _planned("repair-me", "src/**")
    planned["validation_commands"] = [
        "python -c \"import pathlib; assert pathlib.Path('src/ok').exists()\""
    ]

    class RepairBackend(FakeBackend):
        def repair(self, thread_id: str, worktree: Path, feedback: str) -> None:
            self.repairs += 1
            path = worktree / "src/ok"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok", encoding="utf-8")

    backend = RepairBackend([planned])
    result = Orchestrator(repo, backend).run("Repair validation")
    assert result.status == "completed"
    assert result.tasks["repair-me"].attempts == 2
    assert backend.repairs == 1


def test_interruption_is_persisted_for_resume(tmp_path: Path) -> None:
    repo = _repository(tmp_path)

    class InterruptBackend(FakeBackend):
        def implement(
            self, task: TaskManifest, worktree: Path, model: str | None
        ) -> str:
            raise KeyboardInterrupt

    backend = InterruptBackend([_planned("pause", "src/**")])
    with pytest.raises(KeyboardInterrupt):
        Orchestrator(repo, backend).run("Interrupt this run")
    saved = status(repo)
    assert saved.status == "interrupted"
    assert saved.tasks["pause"].status == "interrupted"
