"""Independent read-only Codex review interface."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from python_agent_forge.config import ConfigurationError
from python_agent_forge.tasks import TaskManifest


@dataclass(frozen=True)
class ReviewFinding:
    title: str
    body: str
    path: str | None = None
    line: int | None = None
    priority: int = 2


class IndependentReviewer(Protocol):
    def review(
        self, task: TaskManifest, worktree: Path, diff: str, model: str | None
    ) -> list[ReviewFinding]: ...


class OpenAICodexReviewer:
    """Starts a fresh read-only Codex thread for every review cycle."""

    def review(
        self, task: TaskManifest, worktree: Path, diff: str, model: str | None
    ) -> list[ReviewFinding]:
        try:
            module = importlib.import_module("openai_codex")
            client = module.Codex()
            sandbox = module.Sandbox.read_only
        except (ImportError, AttributeError) as error:
            raise ConfigurationError(
                "the optional Codex SDK is required for independent PR review"
            ) from error
        options: dict[str, Any] = {"cwd": str(worktree), "sandbox": sandbox}
        if model:
            options["model"] = model
        thread = client.thread_start(**options)
        prompt = f"""Independently review this task diff.
Task: {task.brief}
Acceptance criteria: {task.acceptance_criteria}
Owned paths: {task.owned_paths}
Return JSON only as {{"findings": [...]}}. Each actionable finding has title,
body, optional path and line, and priority 0-3. Return an empty list when clean.
Do not modify files, branches, remotes, pull requests, or credentials.

Diff:
{diff[-100000:]}
"""
        response = thread.run(prompt)
        output = getattr(response, "final_response", None)
        if not isinstance(output, str):
            raise ConfigurationError("Codex reviewer returned no final response")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise ConfigurationError("Codex reviewer returned invalid JSON") from error
        findings = value.get("findings") if isinstance(value, dict) else None
        if not isinstance(findings, list):
            raise ConfigurationError("Codex reviewer findings must be a list")
        result: list[ReviewFinding] = []
        for item in findings:
            if (
                not isinstance(item, dict)
                or not item.get("title")
                or not item.get("body")
            ):
                raise ConfigurationError("Codex reviewer returned an invalid finding")
            result.append(
                ReviewFinding(
                    title=str(item["title"]),
                    body=str(item["body"]),
                    path=str(item["path"]) if item.get("path") else None,
                    line=int(item["line"]) if item.get("line") else None,
                    priority=int(item.get("priority", 2)),
                )
            )
        return result
