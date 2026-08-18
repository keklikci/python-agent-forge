from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from python_agent_forge.provider import GhGitHubProvider, PullRequest


class CommandRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.list_calls = 0

    def __call__(
        self, arguments: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((arguments, kwargs))
        stdout = ""
        returncode = 0
        if arguments[:4] == ["git", "remote", "get-url", "origin"]:
            stdout = "git@github.com:owner/repo.git\n"
        elif arguments[:3] == ["git", "status", "--porcelain"]:
            stdout = ""
        elif arguments[:3] == ["git", "ls-remote", "--exit-code"]:
            returncode = 2
        elif arguments[:3] == ["gh", "pr", "list"]:
            self.list_calls += 1
            stdout = (
                "[]"
                if self.list_calls == 1
                else json.dumps(
                    [
                        {
                            "number": 12,
                            "url": "https://github.com/owner/repo/pull/12",
                            "isDraft": True,
                            "baseRefName": "main",
                            "headRefName": "codex/feature",
                            "state": "OPEN",
                        }
                    ]
                )
            )
        elif arguments[:3] == ["gh", "pr", "checks"]:
            stdout = json.dumps(
                [
                    {"name": "tests", "bucket": "pass", "state": "SUCCESS"},
                    {"name": "lint", "bucket": "pending", "state": "QUEUED"},
                ]
            )
            returncode = 1
        elif arguments[:3] == ["gh", "pr", "view"]:
            stdout = '{"mergedAt":null}'
        return subprocess.CompletedProcess(arguments, returncode, stdout, "")


def _repository(tmp_path: Path) -> Path:
    """Create a real clean repository for the provider's local preflight."""
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Fixture"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "fixture@example"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"],
        check=True,
    )
    marker = tmp_path / "README.md"
    marker.write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "fixture"], check=True)
    return tmp_path


def test_gh_provider_creates_draft_idempotently_and_never_merges(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    recorder = CommandRecorder()
    provider = GhGitHubProvider(recorder)
    provider.preflight(repo, "main", ["codex/feature"])
    pr = provider.ensure_pull_request(
        repo,
        "codex/feature",
        "main",
        "feat(feature): implement feature",
        "body",
    )
    assert pr.number == 12
    create = next(
        call for call in recorder.calls if call[0][:3] == ["gh", "pr", "create"]
    )
    assert "--draft" in create[0]
    assert create[1]["input"] == "body"
    assert all(call[0][:3] != ["gh", "pr", "merge"] for call in recorder.calls)


def test_gh_provider_parses_nonzero_pending_checks(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    recorder = CommandRecorder()
    provider = GhGitHubProvider(recorder)
    provider.preflight(repo, "main", [])
    summary = provider.checks(PullRequest(12, "url", "branch", "main", True))
    assert not summary.passed
    assert summary.pending == ("lint",)
    assert summary.failed == ()
