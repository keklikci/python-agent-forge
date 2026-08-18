"""Codex backend boundary with a lazy, least-privilege SDK adapter."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Protocol

from python_agent_forge.config import ConfigurationError
from python_agent_forge.tasks import TaskManifest


class CodexBackend(Protocol):
    def plan(
        self, target: Path, request: str, base: str, model: str | None
    ) -> dict[str, Any]: ...

    def implement(
        self, task: TaskManifest, worktree: Path, model: str | None
    ) -> str: ...

    def repair(self, thread_id: str, worktree: Path, feedback: str) -> None: ...


class OpenAICodexBackend:
    """Lazy adapter so inspect/status work without the optional Codex SDK."""

    def __init__(self) -> None:
        self._client: Any = None
        self._sandbox: Any = None
        self._threads: dict[str, Any] = {}

    def _sdk(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            module = importlib.import_module("openai_codex")
            client_type = getattr(module, "Codex")
            self._sandbox = getattr(module, "Sandbox")
        except (ImportError, AttributeError) as error:
            raise ConfigurationError(
                "the optional Codex SDK is unavailable; install and authenticate the "
                "stable Python SDK before run/resume"
            ) from error
        self._client = client_type()
        return self._client

    @staticmethod
    def _output(result: Any) -> str:
        output = getattr(result, "final_response", None)
        if not isinstance(output, str):
            raise ConfigurationError("Codex returned no final output")
        return output

    def _start(self, cwd: Path, sandbox: str, model: str | None) -> Any:
        client = self._sdk()
        sandbox_value = (
            self._sandbox.read_only
            if sandbox == "read-only"
            else self._sandbox.workspace_write
        )
        options: dict[str, Any] = {"cwd": str(cwd), "sandbox": sandbox_value}
        if model:
            options["model"] = model
        # Deliberately no full-access or unrestricted filesystem option.
        return client.thread_start(**options)

    def plan(
        self, target: Path, request: str, base: str, model: str | None
    ) -> dict[str, Any]:
        thread = self._start(target, "read-only", model)
        prompt = f"""Plan this repository request as independent tasks.
Base branch: {base}
Request: {request}
Return JSON only with keys assumptions and tasks. Each task needs task_id,
brief, acceptance_criteria, owned_paths, exclusions, dependencies, and pr.
Use only repository-relative owned paths. Do not modify files or credentials.
"""
        result = thread.run(prompt)
        try:
            value = json.loads(self._output(result))
        except json.JSONDecodeError as error:
            raise ConfigurationError("Codex planner returned invalid JSON") from error
        if not isinstance(value, dict):
            raise ConfigurationError("Codex planner output must be an object")
        return value

    def implement(self, task: TaskManifest, worktree: Path, model: str | None) -> str:
        thread = self._start(worktree, "workspace-write", model)
        prompt = f"""Implement task {task.task_id}: {task.brief}
Acceptance criteria: {task.acceptance_criteria}
Owned paths: {task.owned_paths}
Exclusions: {task.exclusions}
Do not modify paths outside the owned paths. Do not push, merge, change remotes,
or access credentials. Commit completed changes using the repository's configured
identity and signing policy, then leave the worktree ready for validation.
"""
        thread.run(prompt)
        thread_id = str(getattr(thread, "id", ""))
        if not thread_id:
            raise ConfigurationError("Codex worker returned no thread ID")
        self._threads[thread_id] = thread
        return thread_id

    def repair(self, thread_id: str, worktree: Path, feedback: str) -> None:
        thread = self._threads.get(thread_id)
        if thread is None:
            client = self._sdk()
            resume = getattr(client, "resume_thread", None)
            if resume is None:
                raise ConfigurationError(
                    "Codex SDK cannot resume the saved worker thread"
                )
            thread = resume(thread_id)
            self._threads[thread_id] = thread
        thread.run(
            "Repair only the reported scope or validation failure. Do not push, "
            f"merge, change remotes, or access credentials.\n\n{feedback}"
        )
