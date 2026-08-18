from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from python_agent_forge.backend import OpenAICodexBackend
from python_agent_forge.tasks import TaskManifest


def test_official_sdk_adapter_uses_least_privilege_sandboxes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls: list[dict[str, Any]] = []
    resumed: list[str] = []

    class Thread:
        def __init__(self, thread_id: str, response: str = "done") -> None:
            self.id = thread_id
            self.response = response

        def run(self, prompt: str) -> Any:
            assert prompt
            return SimpleNamespace(final_response=self.response)

    planner_response = json.dumps({"assumptions": [], "tasks": []})

    class Codex:
        def thread_start(self, **options: Any) -> Thread:
            calls.append(options)
            response = planner_response if options["sandbox"] == "read-only" else "done"
            return Thread(f"thread-{len(calls)}", response)

        def resume_thread(self, thread_id: str) -> Thread:
            resumed.append(thread_id)
            return Thread(thread_id)

    module = SimpleNamespace(
        Codex=Codex,
        Sandbox=SimpleNamespace(
            read_only="read-only", workspace_write="workspace-write"
        ),
    )
    monkeypatch.setitem(sys.modules, "openai_codex", module)
    backend = OpenAICodexBackend()

    assert backend.plan(tmp_path, "Plan", "main", "model")["tasks"] == []
    task = TaskManifest(
        task_id="feature",
        brief="Implement feature",
        acceptance_criteria=["It works"],
        owned_paths=["src/**"],
        exclusions=[],
        dependencies=[],
        branch="codex/feature",
        validation_commands=["python -c 'pass'"],
    )
    thread_id = backend.implement(task, tmp_path, None)
    backend._threads.clear()
    backend.repair(thread_id, tmp_path, "repair")

    assert calls[0]["sandbox"] == "read-only"
    assert calls[1]["sandbox"] == "workspace-write"
    assert all("full_access" not in options for options in calls)
    assert resumed == [thread_id]
