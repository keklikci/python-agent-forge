"""Validated, resumable execution of Codex task graphs in Git worktrees."""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from python_agent_forge.backend import CodexBackend, OpenAICodexBackend
from python_agent_forge.config import (
    ConfigurationError,
    OrchestrationPolicy,
    ProjectConfig,
)
from python_agent_forge.gitops import (
    ExecutionError,
    changed_paths,
    create_worktree,
    enforce_scope,
    head_sha,
    require_clean_repository,
    run_validations,
)
from python_agent_forge.state import RunState, StateStore, TaskState, now
from python_agent_forge.tasks import TaskGraph, TaskManifest

if TYPE_CHECKING:
    from python_agent_forge.lifecycle import RunLifecycle


class OrchestrationError(RuntimeError):
    """A run could not safely proceed or complete."""


def _run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _planner_tasks(
    plan: dict[str, Any], policy: OrchestrationPolicy, project: ProjectConfig
) -> TaskGraph:
    values = plan.get("tasks")
    if not isinstance(values, list) or not values:
        raise ConfigurationError("planner returned no tasks")
    tasks: list[TaskManifest] = []
    for raw in values:
        if not isinstance(raw, dict):
            raise ConfigurationError("planner tasks must be objects")
        value = dict(raw)
        task_id = str(value.get("task_id", ""))
        value.setdefault("branch", f"{policy.branch_prefix}{task_id}")
        value.setdefault("validation_commands", list(project.validation_commands))
        value.setdefault("exclusions", [])
        value.setdefault("dependencies", [])
        value.setdefault("pr", {})
        task = TaskManifest.from_dict(value)
        if not task.branch.startswith(policy.branch_prefix):
            raise ConfigurationError(
                f"task {task.task_id} branch must use {policy.branch_prefix}"
            )
        tasks.append(task)
    return TaskGraph(tasks).validate_and_serialize()


def _manifest_path(worktree: Path, run_id: str, task_id: str) -> Path:
    return worktree / ".codex/tasks" / run_id / f"{task_id}.yml"


def _load_manifests(state: RunState) -> TaskGraph:
    tasks: list[TaskManifest] = []
    for task_id, task_state in state.tasks.items():
        if not task_state.manifest:
            raise ConfigurationError(f"task {task_id} has no saved manifest")
        task = TaskManifest.from_dict(task_state.manifest)
        if task_state.worktree:
            path = _manifest_path(Path(task_state.worktree), state.run_id, task_id)
            tracked = TaskManifest.load(path)
            if tracked != task:
                raise ConfigurationError(
                    f"task {task_id} manifest changed after planning"
                )
        tasks.append(task)
    return TaskGraph(tasks).validate_and_serialize()


class Orchestrator:
    def __init__(
        self,
        target: Path,
        backend: CodexBackend | None = None,
        *,
        base: str | None = None,
        model: str | None = None,
        max_parallel: int | None = None,
        lifecycle: RunLifecycle | None = None,
    ) -> None:
        self.target = target.resolve()
        self.project = ProjectConfig.load(self.target)
        self.policy = OrchestrationPolicy.load(self.target)
        if max_parallel is not None and not 1 <= max_parallel <= 4:
            raise ConfigurationError("--max-parallel must be between 1 and 4")
        self.max_parallel = max_parallel or self.policy.max_parallel_tasks
        self.base = base or self.project.base_branch
        self.model = model
        self.backend = backend or OpenAICodexBackend()
        self.lifecycle = lifecycle
        self.store = StateStore(self.target)
        self._state_lock = threading.Lock()

    def run(self, request: str) -> RunState:
        if not request.strip():
            raise ConfigurationError("request cannot be empty")
        require_clean_repository(self.target)
        plan = self.backend.plan(self.target, request, self.base, self.model)
        blockers = plan.get("blockers", [])
        if blockers:
            if not isinstance(blockers, list) or not all(
                isinstance(value, str) for value in blockers
            ):
                raise ConfigurationError("planner blockers must be a list of strings")
            raise OrchestrationError("planning blocked: " + "; ".join(blockers))
        graph = _planner_tasks(plan, self.policy, self.project)
        if self.lifecycle:
            self.lifecycle.preflight(graph, self.base)
        run_id = _run_id()
        assumptions = plan.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(value, str) for value in assumptions
        ):
            raise ConfigurationError("planner assumptions must be a list of strings")
        state = RunState(
            run_id=run_id,
            target=str(self.target),
            base_branch=self.base,
            model=self.model,
            status="running",
            assumptions=assumptions,
            tasks={
                task.task_id: TaskState(manifest=asdict(task)) for task in graph.tasks
            },
        )
        self.store.save(state)
        for task in graph.tasks:
            if not task.dependencies:
                self._prepare_task(task, state, graph.by_id())
        return self._execute(graph, state)

    def resume(self, run_id: str) -> RunState:
        state = self.store.load(run_id)
        graph = _load_manifests(state)
        if self.lifecycle:
            resume_preflight = getattr(self.lifecycle, "resume_preflight", None)
            if resume_preflight is None:
                self.lifecycle.preflight(graph, state.base_branch)
            else:
                resume_preflight(
                    graph,
                    state.base_branch,
                    {
                        task.manifest["branch"]
                        for task in state.tasks.values()
                        if task.manifest and task.manifest.get("branch")
                    },
                )
            self.lifecycle.reconcile(graph, state)
        state.status = "running"
        for task_state in state.tasks.values():
            if task_state.status in {"failed", "blocked", "interrupted", "running"}:
                task_state.status = "queued"
                task_state.error = None
        self.store.save(state)
        return self._execute(graph, state)

    def _save(self, state: RunState) -> None:
        with self._state_lock:
            self.store.save(state)

    def _prepare_task(
        self, task: TaskManifest, state: RunState, by_id: dict[str, TaskManifest]
    ) -> None:
        task_state = state.tasks[task.task_id]
        if task_state.worktree:
            return
        base = state.base_branch
        if task.dependencies:
            parent_id = task.dependencies[-1]
            if parent_id not in by_id:
                raise ConfigurationError(f"unknown stack parent: {parent_id}")
            parent_state = state.tasks[parent_id]
            if parent_state.status != "completed" or not parent_state.worktree:
                raise OrchestrationError(f"stack parent {parent_id} is not complete")
            parent_worktree = Path(parent_state.worktree)
            require_clean_repository(parent_worktree)
            base = head_sha(parent_worktree)
            task_state.stack_parent_task_id = parent_id
        worktree = create_worktree(
            self.target, state.run_id, task.task_id, task.branch, base
        )
        task_state.worktree = str(worktree)
        task_state.start_sha = head_sha(worktree)
        task.write(_manifest_path(worktree, state.run_id, task.task_id))
        self._save(state)

    def _task(self, task: TaskManifest, state: RunState, task_state: TaskState) -> None:
        task_state.status = "running"
        task_state.updated_at = now()
        self._save(state)
        if not task_state.worktree or not task_state.start_sha:
            raise OrchestrationError(f"task {task.task_id} is missing prepared state")
        worktree = Path(task_state.worktree)
        if task_state.thread_id:
            self.backend.repair(
                task_state.thread_id,
                worktree,
                "Resume this interrupted task and complete its acceptance criteria.",
            )
        else:
            task_state.thread_id = self.backend.implement(task, worktree, state.model)
        for attempt in range(self.policy.repair_limit + 1):
            task_state.attempts += 1
            try:
                manifest = f".codex/tasks/{state.run_id}/{task.task_id}.yml"
                enforce_scope(
                    changed_paths(worktree, task_state.start_sha),
                    [*task.owned_paths, manifest],
                )
                run_validations(
                    worktree,
                    task.validation_commands,
                    self.policy.validation_timeout_seconds,
                )
                task_state.status = "completed"
                task_state.error = None
                task_state.updated_at = now()
                self._save(state)
                return
            except (ExecutionError, ConfigurationError) as error:
                task_state.error = str(error)
                if attempt >= self.policy.repair_limit:
                    task_state.status = "failed"
                    task_state.updated_at = now()
                    self._save(state)
                    return
                if not task_state.thread_id:
                    raise OrchestrationError(
                        "worker has no resumable thread"
                    ) from error
                self.backend.repair(task_state.thread_id, worktree, str(error))

    def _execute(self, graph: TaskGraph, state: RunState) -> RunState:
        by_id = graph.by_id()
        running: dict[Future[None], str] = {}
        try:
            with ThreadPoolExecutor(max_workers=self.max_parallel) as executor:
                while True:
                    completed = {
                        task_id
                        for task_id, task_state in state.tasks.items()
                        if task_state.status == "completed"
                    }
                    failed = {
                        task_id
                        for task_id, task_state in state.tasks.items()
                        if task_state.status == "failed"
                    }
                    ready: list[tuple[TaskManifest, TaskState]] = []
                    for task_id, task_state in state.tasks.items():
                        task = by_id[task_id]
                        if task_state.status != "queued":
                            continue
                        if set(task.dependencies) & failed:
                            task_state.status = "blocked"
                            task_state.error = "dependency failed"
                        elif (
                            set(task.dependencies) <= completed
                            and len(running) + len(ready) < self.max_parallel
                        ):
                            try:
                                self._prepare_task(task, state, by_id)
                            except (
                                ConfigurationError,
                                ExecutionError,
                                OrchestrationError,
                            ) as error:
                                task_state.status = "failed"
                                task_state.error = str(error)
                                self._save(state)
                                continue
                            ready.append((task, task_state))
                    for task, task_state in ready:
                        future = executor.submit(self._task, task, state, task_state)
                        running[future] = task.task_id
                    if not running:
                        if all(
                            item.status in {"completed", "failed", "blocked"}
                            for item in state.tasks.values()
                        ):
                            break
                        raise OrchestrationError("task graph made no progress")
                    done, _ = wait(running, return_when=FIRST_COMPLETED)
                    for future in done:
                        task_id = running.pop(future)
                        try:
                            future.result()
                        except Exception as error:
                            task_state = state.tasks[task_id]
                            task_state.status = "failed"
                            task_state.error = str(error)
                            task_state.updated_at = now()
                            self._save(state)
        except KeyboardInterrupt:
            state.status = "interrupted"
            for task_state in state.tasks.values():
                if task_state.status == "running":
                    task_state.status = "interrupted"
            self._save(state)
            raise
        state.status = (
            "completed"
            if all(item.status == "completed" for item in state.tasks.values())
            else "failed"
        )
        if state.status == "completed" and self.lifecycle:
            self.lifecycle.publish(graph, state)
        self._save(state)
        return state


def status(target: Path, run_id: str | None = None) -> RunState:
    store = StateStore(target)
    return store.load(run_id) if run_id else store.latest()


def format_status(state: RunState) -> str:
    lines = [f"run: {state.run_id}", f"status: {state.status}"]
    for task_id, task in sorted(state.tasks.items()):
        line = f"{task_id}: {task.status} (attempts: {task.attempts})"
        if task.error:
            line += f" - {task.error}"
        lines.append(line)
    return "\n".join(lines)


def status_json(state: RunState) -> str:
    return json.dumps(state.public_dict(), indent=2, sort_keys=True)
