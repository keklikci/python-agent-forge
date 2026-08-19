"""Reviewed, stacked pull-request lifecycle with an explicit human merge gate."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from python_agent_forge.backend import CodexBackend
from python_agent_forge.config import ConfigurationError, OrchestrationPolicy
from python_agent_forge.gitops import (
    changed_paths,
    enforce_scope,
    require_clean_repository,
    run_validations,
)
from python_agent_forge.provider import GitProvider, PullRequest
from python_agent_forge.review import IndependentReviewer, ReviewFinding
from python_agent_forge.state import RunState, TaskState
from python_agent_forge.tasks import TaskGraph, TaskManifest

_TITLE = re.compile(
    r"(?:feat|fix|docs|refactor|test|chore|ci|build)\([a-z0-9-]+\): [a-z0-9].+"
)


class RunLifecycle(Protocol):
    def preflight(self, graph: TaskGraph, base: str) -> None: ...

    def publish(self, graph: TaskGraph, state: RunState) -> None: ...

    def reconcile(self, graph: TaskGraph, state: RunState) -> None: ...


def _pull_request(task: TaskManifest, task_state: TaskState) -> PullRequest:
    if not task_state.pr_number or not task_state.pr_url or not task_state.pr_base:
        raise ConfigurationError(f"task {task.task_id} has incomplete PR state")
    return PullRequest(
        number=task_state.pr_number,
        url=task_state.pr_url,
        branch=task.branch,
        base=task_state.pr_base,
        draft=not task_state.ready_for_human,
    )


def _title(task: TaskManifest) -> str:
    title = str(task.pr.get("title", ""))
    if not title:
        title = f"feat({task.task_id}): {task.brief[0].lower()}{task.brief[1:]}"
    if len(title) > 72 or not _TITLE.fullmatch(title):
        title = f"feat({task.task_id}): {title[0].lower()}{title[1:]}".strip()
        if len(title) > 72 or not _TITLE.fullmatch(title):
            raise ConfigurationError(f"task {task.task_id} has an invalid PR title")
        task.pr["title"] = title
    return title


def _body(task: TaskManifest, base: str, order: list[str]) -> str:
    dependencies = ", ".join(task.dependencies) or "None"
    owned = "\n".join(f"- `{path}`" for path in task.owned_paths)
    excluded = "\n".join(f"- {item}" for item in task.exclusions) or "- None"
    validation = "\n".join(f"- `{item}`" for item in task.validation_commands)
    merge_order = " -> ".join(order)
    return f"""## Summary

{task.brief}

## Implementation changes

- Implements the task acceptance criteria in its isolated worktree.

## Owned and out-of-scope paths

Owned paths:
{owned}

Out of scope:
{excluded}

## Validation

{validation}

## Risks and dependencies

- Base: `{base}`
- Dependencies: {dependencies}
- Merge order: {merge_order}

## Follow-up work

- Human review and merge approval are required. This automation never merges.
"""


def _diff(worktree: Path, start_sha: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(worktree), "diff", f"{start_sha}..HEAD", "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _feedback(findings: list[ReviewFinding]) -> str:
    return "\n".join(
        f"[{finding.priority}] {finding.title}"
        + (f" ({finding.path}:{finding.line})" if finding.path else "")
        + f": {finding.body}"
        for finding in findings
    )


class PullRequestLifecycle:
    """Pushes reviewed draft PRs and stops at the human merge gate."""

    def __init__(
        self,
        target: Path,
        provider: GitProvider,
        reviewer: IndependentReviewer,
        backend: CodexBackend,
        policy: OrchestrationPolicy,
    ) -> None:
        self.target = target
        self.provider = provider
        self.reviewer = reviewer
        self.backend = backend
        self.policy = policy
        self.review_limit = 2

    def preflight(self, graph: TaskGraph, base: str) -> None:
        self.provider.preflight(
            self.target, base, [task.branch for task in graph.tasks]
        )

    @staticmethod
    def _base(
        task: TaskManifest, state: RunState, by_id: dict[str, TaskManifest]
    ) -> str:
        parent = state.tasks[task.task_id].stack_parent_task_id
        return by_id[parent].branch if parent else state.base_branch

    def _validate_repair(
        self, task: TaskManifest, task_state: TaskState, worktree: Path
    ) -> None:
        if not task_state.start_sha:
            raise ConfigurationError(f"task {task.task_id} has no start SHA")
        manifest = next(
            path
            for path in changed_paths(worktree, task_state.start_sha)
            if path.startswith(".codex/tasks/")
        )
        enforce_scope(
            changed_paths(worktree, task_state.start_sha),
            [*task.owned_paths, manifest],
        )
        run_validations(
            worktree,
            task.validation_commands,
            self.policy.validation_timeout_seconds,
        )
        require_clean_repository(worktree)

    def _review(
        self,
        task: TaskManifest,
        task_state: TaskState,
        worktree: Path,
        model: str | None,
    ) -> bool:
        if task_state.review_status == "passed":
            return True
        if not task_state.start_sha or not task_state.thread_id:
            raise ConfigurationError(f"task {task.task_id} lacks review state")
        for cycle in range(self.review_limit + 1):
            task_state.review_attempts += 1
            findings = self.reviewer.review(
                task, worktree, _diff(worktree, task_state.start_sha), model
            )
            if not findings:
                task_state.review_status = "passed"
                return True
            if cycle == self.review_limit:
                task_state.review_status = "failed"
                task_state.error = _feedback(findings)
                return False
            self.backend.repair(task_state.thread_id, worktree, _feedback(findings))
            self._validate_repair(task, task_state, worktree)
            self.provider.push(worktree, task.branch)
        return False

    @staticmethod
    def _record_pr(
        task: TaskManifest,
        task_state: TaskState,
        state: RunState,
        pull_request: PullRequest,
        worktree: Path,
    ) -> bool:
        metadata = {
            **task.pr,
            "number": pull_request.number,
            "url": pull_request.url,
            "base": task_state.pr_base,
            "status": "draft" if pull_request.draft else "ready",
        }
        if task.pr == metadata:
            return False
        task.pr = metadata
        task_state.manifest = asdict(task)
        path = worktree / ".codex/tasks" / state.run_id / f"{task.task_id}.yml"
        task.write(path)
        subprocess.run(
            ["git", "-C", str(worktree), "add", "--", str(path.relative_to(worktree))],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "commit",
                "-m",
                f"chore({task.task_id}): record pull request metadata",
            ],
            check=True,
        )
        return True

    def _checks(
        self, task: TaskManifest, task_state: TaskState, worktree: Path, pr: PullRequest
    ) -> bool:
        if not task_state.thread_id:
            raise ConfigurationError(f"task {task.task_id} has no worker thread")
        for cycle in range(self.review_limit + 1):
            checks = self.provider.checks(pr)
            if checks.passed:
                task_state.ci_status = "passed"
                return True
            if checks.pending:
                task_state.ci_status = "pending"
                return False
            task_state.ci_status = "failed"
            task_state.error = "failed checks: " + ", ".join(checks.failed)
            if cycle == self.review_limit:
                return False
            self.backend.repair(task_state.thread_id, worktree, task_state.error)
            self._validate_repair(task, task_state, worktree)
            self.provider.push(worktree, task.branch)
        return False

    def publish(self, graph: TaskGraph, state: RunState) -> None:
        by_id = graph.by_id()
        order = [task.task_id for task in graph.tasks]
        all_ready = True
        for task in graph.tasks:
            task_state = state.tasks[task.task_id]
            if not task_state.worktree:
                raise ConfigurationError(f"task {task.task_id} has no worktree")
            worktree = Path(task_state.worktree)
            manifest = worktree / ".codex/tasks" / state.run_id / f"{task.task_id}.yml"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "add",
                    "--",
                    str(manifest.relative_to(worktree)),
                ],
                check=True,
            )
            if (
                subprocess.run(
                    ["git", "-C", str(worktree), "diff", "--cached", "--quiet"],
                    check=False,
                ).returncode
                != 0
            ):
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(worktree),
                        "commit",
                        "-m",
                        f"chore({task.task_id}): record task manifest",
                    ],
                    check=True,
                )
            require_clean_repository(worktree)
            base = self._base(task, state, by_id)
            self.provider.push(worktree, task.branch)
            pull_request = self.provider.ensure_pull_request(
                worktree, task.branch, base, _title(task), _body(task, base, order)
            )
            if pull_request.base != base:
                self.provider.retarget(pull_request, base)
            task_state.pr_number = pull_request.number
            task_state.pr_url = pull_request.url
            task_state.pr_base = base
            if self._record_pr(task, task_state, state, pull_request, worktree):
                self.provider.push(worktree, task.branch)
            if not self._review(task, task_state, worktree, state.model):
                all_ready = False
                continue
            if not self._checks(task, task_state, worktree, pull_request):
                all_ready = False
            else:
                self.provider.mark_ready(pull_request)
                task_state.ready_for_human = True
        merged = all(
            state.tasks[task.task_id].pr_number
            and self.provider.is_merged(_pull_request(task, state.tasks[task.task_id]))
            for task in graph.tasks
        )
        state.status = (
            "completed"
            if merged
            else "awaiting_human_merge"
            if all_ready
            else "review_required"
        )

    def reconcile(self, graph: TaskGraph, state: RunState) -> None:
        by_id = graph.by_id()
        for task in graph.tasks:
            task_state = state.tasks[task.task_id]
            if not task_state.pr_number:
                continue
            pull_request = _pull_request(task, task_state)
            parent_id = task_state.stack_parent_task_id
            if not parent_id:
                continue
            parent_task = by_id[parent_id]
            parent_state = state.tasks[parent_id]
            if not parent_state.pr_number:
                continue
            if not self.provider.is_merged(_pull_request(parent_task, parent_state)):
                continue
            if not task_state.worktree or not task_state.thread_id:
                raise ConfigurationError(f"task {task.task_id} cannot be restacked")
            worktree = Path(task_state.worktree)
            conflict = self.provider.restack(worktree, state.base_branch)
            if conflict:
                self.backend.repair(
                    task_state.thread_id,
                    worktree,
                    "Resolve this restack conflict and continue the rebase:\n"
                    + conflict,
                )
                self._validate_repair(task, task_state, worktree)
            self.provider.push(worktree, task.branch, force_with_lease=True)
            self.provider.retarget(pull_request, state.base_branch)
            task_state.pr_base = state.base_branch
