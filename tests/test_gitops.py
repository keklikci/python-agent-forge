from __future__ import annotations

import subprocess
from pathlib import Path

from python_agent_forge.gitops import changed_paths, head_sha


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_changed_paths_uses_exact_start_sha_and_preserves_rename_sides(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    original = repo / "src/original.py"
    original.parent.mkdir()
    original.write_text("before = True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    start = head_sha(repo)

    _git(repo, "mv", "src/original.py", "src/renamed.py")
    _git(repo, "commit", "-m", "rename")
    (repo / "src/space name.py").write_text("pending = True\n", encoding="utf-8")

    assert changed_paths(repo, start) == [
        "src/original.py",
        "src/renamed.py",
        "src/space name.py",
    ]
