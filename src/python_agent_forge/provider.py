"""Git hosting provider boundary and safe GitHub CLI implementation."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from python_agent_forge.config import ConfigurationError
from python_agent_forge.gitops import require_clean_repository


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    branch: str
    base: str
    draft: bool
    state: str = "OPEN"


@dataclass(frozen=True)
class CheckSummary:
    passed: bool
    pending: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


class GitProvider(Protocol):
    def preflight(
        self,
        target: Path,
        base: str,
        branches: list[str],
        allow_existing_branches: set[str] | None = None,
    ) -> None: ...

    def push(
        self, worktree: Path, branch: str, *, force_with_lease: bool = False
    ) -> None: ...

    def ensure_pull_request(
        self, worktree: Path, branch: str, base: str, title: str, body: str
    ) -> PullRequest: ...

    def checks(self, pull_request: PullRequest) -> CheckSummary: ...

    def mark_ready(self, pull_request: PullRequest) -> None: ...

    def is_merged(self, pull_request: PullRequest) -> bool: ...

    def retarget(self, pull_request: PullRequest, base: str) -> None: ...

    def restack(self, worktree: Path, base: str) -> str | None: ...


class GhGitHubProvider:
    """GitHub provider using explicit non-shelling ``git`` and ``gh`` calls."""

    def __init__(self, command_runner: Any = subprocess.run) -> None:
        self._run_command = command_runner
        self._target: Path | None = None
        self._repository: str | None = None
        self._remote_shas: dict[str, str] = {}

    def _cwd(self) -> Path:
        if self._target is None:
            raise ConfigurationError("GitHub provider preflight has not run")
        return self._target

    def _repo(self) -> str:
        if self._repository is None:
            raise ConfigurationError("GitHub repository identity is unavailable")
        return self._repository

    def _run(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_command(
            arguments,
            cwd=cwd,
            input=input_text,
            check=check,
            capture_output=True,
            text=True,
        )

    def _json(self, arguments: list[str], *, cwd: Path, check: bool = True) -> Any:
        result = self._run(arguments, cwd=cwd, check=check)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"invalid gh JSON: {' '.join(arguments[:3])}"
            ) from error

    def preflight(
        self,
        target: Path,
        base: str,
        branches: list[str],
        allow_existing_branches: set[str] | None = None,
    ) -> None:
        allow_existing_branches = allow_existing_branches or set()
        require_clean_repository(target)
        self._target = target
        remote = self._run(
            ["git", "remote", "get-url", "origin"], cwd=target
        ).stdout.strip()
        match = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", remote)
        if not match:
            raise ConfigurationError("origin is not a recognizable GitHub repository")
        self._repository = match.group(1)
        self._run(["gh", "auth", "status", "--hostname", "github.com"], cwd=target)
        self._run(["git", "rev-parse", "--verify", base], cwd=target)
        for branch in branches:
            result = self._run(
                ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
                cwd=target,
                check=False,
            )
            if result.returncode == 0:
                self._remote_shas[branch] = result.stdout.split()[0]
                existing = self._find_pull_request(target, branch)
                if existing is None and branch not in allow_existing_branches:
                    raise ConfigurationError(f"remote branch already exists: {branch}")

    def push(
        self, worktree: Path, branch: str, *, force_with_lease: bool = False
    ) -> None:
        arguments = ["git", "push"]
        if force_with_lease:
            expected = self._remote_shas.get(branch)
            if not expected:
                remote = self._run(
                    [
                        "git",
                        "ls-remote",
                        "--heads",
                        "origin",
                        f"refs/heads/{branch}",
                    ],
                    cwd=worktree,
                ).stdout.strip()
                expected = remote.split()[0] if remote else ""
            if not expected:
                raise ConfigurationError(
                    f"cannot force-with-lease without remote SHA for {branch}"
                )
            arguments.append(f"--force-with-lease=refs/heads/{branch}:{expected}")
        arguments.extend(["-u", "origin", branch])
        self._run(arguments, cwd=worktree)
        remote = self._run(
            [
                "git",
                "ls-remote",
                "--heads",
                "origin",
                f"refs/heads/{branch}",
            ],
            cwd=worktree,
        ).stdout.strip()
        if remote:
            self._remote_shas[branch] = remote.split()[0]

    def _find_pull_request(self, cwd: Path, branch: str) -> PullRequest | None:
        value = self._json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                self._repo(),
                "--head",
                branch,
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "number,url,isDraft,baseRefName,state,headRefName",
            ],
            cwd=cwd,
        )
        if not isinstance(value, list) or not value:
            return None
        item = value[0]
        return PullRequest(
            number=int(item["number"]),
            url=str(item["url"]),
            branch=str(item.get("headRefName", branch)),
            base=str(item["baseRefName"]),
            draft=bool(item["isDraft"]),
            state=str(item["state"]),
        )

    def ensure_pull_request(
        self, worktree: Path, branch: str, base: str, title: str, body: str
    ) -> PullRequest:
        existing = self._find_pull_request(worktree, branch)
        if existing:
            return existing
        self._run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                self._repo(),
                "--draft",
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body-file",
                "-",
            ],
            cwd=worktree,
            input_text=body,
        )
        created = self._find_pull_request(worktree, branch)
        if not created:
            raise ConfigurationError(
                f"GitHub did not return the created PR for {branch}"
            )
        return created

    def checks(self, pull_request: PullRequest) -> CheckSummary:
        result = self._run(
            [
                "gh",
                "pr",
                "checks",
                str(pull_request.number),
                "--repo",
                self._repo(),
                "--required",
                "--json",
                "name,bucket,state",
            ],
            cwd=self._cwd(),
            check=False,
        )
        try:
            value = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as error:
            raise ConfigurationError("invalid gh checks JSON") from error
        pending: list[str] = []
        failed: list[str] = []
        for item in value:
            bucket = str(item.get("bucket", item.get("state", ""))).lower()
            name = str(item.get("name", "unknown"))
            if bucket in {"fail", "failed", "cancel", "cancelled"}:
                failed.append(name)
            elif bucket not in {"pass", "success", "successful", "skipping"}:
                pending.append(name)
        if result.returncode == 8 and not pending:
            pending.append("required checks")
        elif result.returncode not in {0, 1, 8}:
            raise ConfigurationError(
                f"gh pr checks failed with exit {result.returncode}"
            )
        return CheckSummary(not pending and not failed, tuple(pending), tuple(failed))

    def mark_ready(self, pull_request: PullRequest) -> None:
        if pull_request.draft:
            self._run(
                [
                    "gh",
                    "pr",
                    "ready",
                    str(pull_request.number),
                    "--repo",
                    self._repo(),
                ],
                cwd=self._cwd(),
            )

    def is_merged(self, pull_request: PullRequest) -> bool:
        value = self._json(
            [
                "gh",
                "pr",
                "view",
                str(pull_request.number),
                "--repo",
                self._repo(),
                "--json",
                "mergedAt",
            ],
            cwd=self._cwd(),
        )
        return bool(value.get("mergedAt"))

    def retarget(self, pull_request: PullRequest, base: str) -> None:
        self._run(
            [
                "gh",
                "pr",
                "edit",
                str(pull_request.number),
                "--repo",
                self._repo(),
                "--base",
                base,
            ],
            cwd=self._cwd(),
        )

    def restack(self, worktree: Path, base: str) -> str | None:
        self._run(["git", "fetch", "origin", base], cwd=worktree)
        result = self._run(
            ["git", "rebase", f"origin/{base}"], cwd=worktree, check=False
        )
        if result.returncode == 0:
            return None
        return (result.stdout + result.stderr)[-8000:]
