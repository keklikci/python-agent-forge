from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path

from python_agent_forge.config import OrchestrationPolicy
from python_agent_forge.gitops import head_sha
from python_agent_forge.lifecycle import PullRequestLifecycle
from python_agent_forge.provider import CheckSummary, PullRequest
from python_agent_forge.review import ReviewFinding
from python_agent_forge.state import RunState, TaskState
from python_agent_forge.tasks import TaskGraph, TaskManifest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _worktree(tmp_path: Path, name: str) -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    start = head_sha(repo)
    return repo, start


def _task(task_id: str, dependency: str | None = None) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        brief=f"Implement {task_id}",
        acceptance_criteria=["It works"],
        owned_paths=["src/**"],
        exclusions=["docs/**"],
        dependencies=[dependency] if dependency else [],
        branch=f"codex/{task_id}",
        validation_commands=["python -c 'pass'"],
        pr={"title": f"feat({task_id}): implement feature"},
    )


def _commit_task(worktree: Path, task: TaskManifest, run_id: str) -> None:
    source = worktree / "src" / f"{task.task_id}.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("implemented = True\n", encoding="utf-8")
    task.write(worktree / ".codex/tasks" / run_id / f"{task.task_id}.yml")
    _git(worktree, "add", ".")
    _git(worktree, "commit", "-m", f"implement {task.task_id}")


class FakeProvider:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, bool]] = []
        self.ready: list[int] = []
        self.retargets: list[tuple[int, str]] = []
        self.restacked: list[str] = []
        self.check_results = [
            CheckSummary(False, failed=("tests",)),
            CheckSummary(True),
        ]
        self.merged: set[int] = set()

    def preflight(self, target: Path, base: str, branches: list[str]) -> None:
        pass

    def push(
        self, worktree: Path, branch: str, *, force_with_lease: bool = False
    ) -> None:
        self.pushes.append((branch, force_with_lease))

    def ensure_pull_request(
        self, worktree: Path, branch: str, base: str, title: str, body: str
    ) -> PullRequest:
        assert "Merge order" in body
        return PullRequest(10, "https://example.test/10", branch, base, True)

    def checks(self, pull_request: PullRequest) -> CheckSummary:
        return self.check_results.pop(0) if self.check_results else CheckSummary(True)

    def mark_ready(self, pull_request: PullRequest) -> None:
        self.ready.append(pull_request.number)

    def is_merged(self, pull_request: PullRequest) -> bool:
        return pull_request.number in self.merged

    def retarget(self, pull_request: PullRequest, base: str) -> None:
        self.retargets.append((pull_request.number, base))

    def restack(self, worktree: Path, base: str) -> str | None:
        self.restacked.append(base)
        return None


class FakeBackend:
    def __init__(self) -> None:
        self.repairs = 0

    def repair(self, thread_id: str, worktree: Path, feedback: str) -> None:
        self.repairs += 1
        path = worktree / "src" / f"repair-{self.repairs}.py"
        path.write_text("fixed = True\n", encoding="utf-8")
        _git(worktree, "add", ".")
        _git(worktree, "commit", "-m", f"fix repair {self.repairs}")


class FakeReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def review(
        self, task: TaskManifest, worktree: Path, diff: str, model: str | None
    ) -> list[ReviewFinding]:
        self.calls += 1
        return (
            [ReviewFinding("Fix behavior", "The edge case is missing", "src/a.py", 1)]
            if self.calls == 1
            else []
        )


def test_publish_repairs_review_and_ci_then_marks_draft_ready(tmp_path: Path) -> None:
    worktree, start = _worktree(tmp_path, "feature")
    task = _task("feature")
    _commit_task(worktree, task, "run")
    task_state = TaskState(
        status="completed",
        thread_id="thread-feature",
        worktree=str(worktree),
        start_sha=start,
        manifest=asdict(task),
    )
    state = RunState(
        "run", str(worktree), "main", "model", tasks={"feature": task_state}
    )
    provider, backend = FakeProvider(), FakeBackend()
    lifecycle = PullRequestLifecycle(
        worktree, provider, FakeReviewer(), backend, OrchestrationPolicy()
    )

    lifecycle.publish(TaskGraph([task]), state)

    assert state.status == "awaiting_human_merge"
    assert task_state.review_status == "passed"
    assert task_state.ci_status == "passed"
    assert task_state.ready_for_human
    assert task_state.pr_number == 10
    assert backend.repairs == 2
    assert provider.ready == [10]
    manifest = worktree / ".codex/tasks/run/feature.yml"
    assert '"number": 10' in manifest.read_text()


def test_reconcile_retargets_after_prerequisite_merge(tmp_path: Path) -> None:
    first_worktree, first_start = _worktree(tmp_path, "first")
    second_worktree, second_start = _worktree(tmp_path, "second")
    first, second = _task("first"), _task("second", "first")
    _commit_task(first_worktree, first, "run")
    _commit_task(second_worktree, second, "run")
    states = {
        "first": TaskState(
            status="completed",
            worktree=str(first_worktree),
            start_sha=first_start,
            manifest=asdict(first),
            pr_number=1,
            pr_url="url/1",
            pr_base="main",
            ready_for_human=True,
        ),
        "second": TaskState(
            status="completed",
            thread_id="thread-second",
            worktree=str(second_worktree),
            start_sha=second_start,
            stack_parent_task_id="first",
            manifest=asdict(second),
            pr_number=2,
            pr_url="url/2",
            pr_base="codex/first",
        ),
    }
    state = RunState("run", str(tmp_path), "main", None, tasks=states)
    provider = FakeProvider()
    provider.merged.add(1)
    lifecycle = PullRequestLifecycle(
        tmp_path, provider, FakeReviewer(), FakeBackend(), OrchestrationPolicy()
    )
    lifecycle.reconcile(TaskGraph([first, second]), state)
    assert states["second"].pr_base == "main"
    assert provider.restacked == ["main"]
    assert provider.retargets == [(2, "main")]
    assert provider.pushes[-1] == ("codex/second", True)
