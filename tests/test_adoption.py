from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from python_agent_forge.adoption import (
    AdoptionError,
    _default_worktree_path,
    adopt_local,
    inspect_repository,
)
from python_agent_forge.config import ConfigurationError, ProjectConfig
from python_agent_forge.main import main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "commit.gpgsign", "false")
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_inspect_uv_project_is_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repository(
        tmp_path,
        {
            "pyproject.toml": """[project]
requires-python = ">=3.10"
dependencies = []
[dependency-groups]
dev = ["pytest", "ruff"]
[tool.pytest.ini_options]
testpaths = ["tests"]
[tool.ruff]
line-length = 88
""",
            "uv.lock": "version = 1\n",
            "src/example/__init__.py": "",
            "tests/test_example.py": "def test_ok(): assert True\n",
        },
    )
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert main(["inspect", str(repo), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["package_manager"] == "uv"
    assert result["python_constraint"] == ">=3.10"
    assert result["validation_commands"] == [
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run pytest",
    ]
    assert "target" not in result
    assert before == ""
    assert not (repo / ".codex").exists()


@pytest.mark.parametrize(
    ("files", "manager", "install"),
    [
        (
            {"requirements.txt": "pytest\n"},
            "requirements",
            "uv pip install -r requirements.txt",
        ),
        ({"Pipfile": "[packages]\n"}, "pipenv", "pipenv sync --dev"),
        ({"pdm.lock": ""}, "pdm", "pdm install"),
        (
            {
                "pyproject.toml": "[tool.poetry.dependencies]\npython = '^3.9'\n",
                "poetry.lock": "",
            },
            "poetry",
            "poetry install",
        ),
        (
            {"setup.py": "setup(python_requires='>=3.8')\n"},
            "pip",
            "uv pip install -e .",
        ),
        (
            {"setup.cfg": "[options]\npython_requires = >=3.11\n"},
            "pip",
            "uv pip install -e .",
        ),
    ],
)
def test_detects_dependency_models(
    tmp_path: Path, files: dict[str, str], manager: str, install: str
) -> None:
    facts = inspect_repository(_repository(tmp_path, files))
    assert facts.package_manager == manager
    assert facts.install_command == install


def test_adopt_preserves_files_and_is_idempotent_after_commit(tmp_path: Path) -> None:
    agents = "# Local rules\n\nAlways preserve compatibility.\n"
    workflow = "name: Existing\non: push\njobs: {}\n"
    repo = _repository(
        tmp_path,
        {
            "pyproject.toml": """[project]
requires-python = ">=3.9"
[tool.pytest.ini_options]
testpaths = ["tests"]
""",
            "AGENTS.md": agents,
            ".github/workflows/existing.yml": workflow,
            "tests/test_sample.py": "def test_sample(): assert True\n",
        },
    )

    facts, changes = adopt_local(repo)

    assert facts.python_constraint == ">=3.9"
    assert "AGENTS.md" not in changes
    assert (repo / "AGENTS.md").read_text() == agents
    assert (repo / ".github/workflows/existing.yml").read_text() == workflow
    project = (repo / ".codex/project.yml").read_text()
    assert 'python_constraint: ">=3.9"' in project
    assert str(repo) not in project
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "adopt")

    _, repeated = adopt_local(repo)
    assert repeated == []


def test_existing_ci_covering_validation_is_reused(tmp_path: Path) -> None:
    repo = _repository(
        tmp_path,
        {
            "pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
            "tests/test_sample.py": "def test_sample(): assert True\n",
            ".github/workflows/test.yml": """name: Test
on: push
jobs:
  test:
    steps:
      - run: uv run pytest
""",
        },
    )
    _, changes = adopt_local(repo)
    assert ".github/workflows/python-agent-forge.yml" not in changes


def test_dirty_repository_fails_without_mutation(tmp_path: Path) -> None:
    repo = _repository(tmp_path, {"requirements.txt": "pytest\n"})
    marker = repo / "local.txt"
    marker.write_text("uncommitted", encoding="utf-8")

    with pytest.raises(AdoptionError, match="uncommitted changes"):
        adopt_local(repo)

    assert marker.read_text() == "uncommitted"
    assert not (repo / ".codex").exists()


@pytest.mark.parametrize(
    ("relative", "content", "message"),
    [
        ("AGENTS.md", "Never use Codex agents.\n", "conflict"),
        (".codex/project.yml", "custom_schema: true\n", "unknown"),
    ],
)
def test_unsafe_repository_rules_are_blockers(
    tmp_path: Path, relative: str, content: str, message: str
) -> None:
    repo = _repository(tmp_path, {relative: content})
    facts = inspect_repository(repo)
    assert any(message in blocker for blocker in facts.blockers)
    with pytest.raises(AdoptionError):
        adopt_local(repo)


def test_unknown_layout_gets_safe_not_ready_overlay(tmp_path: Path) -> None:
    repo = _repository(tmp_path, {"README.md": "# Unknown\n"})
    facts, _ = adopt_local(repo)
    assert facts.package_manager == "unknown"
    project = (repo / ".codex/project.yml").read_text()
    assert "autonomous_execution_ready: false" in project
    assert "test_paths: []" in project
    assert "validation_commands: []" in project
    with pytest.raises(ConfigurationError, match="not ready"):
        ProjectConfig.load(repo)


def test_adopted_project_with_empty_test_paths_is_parser_compatible(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path, {"requirements.txt": "pytest\n"})
    adopt_local(repo)

    project = ProjectConfig.load(repo)
    assert project.validation_commands


def test_default_adoption_worktree_is_outside_target(tmp_path: Path) -> None:
    repo = _repository(tmp_path, {"requirements.txt": "pytest\n"})
    worktree = _default_worktree_path(repo)
    assert repo not in worktree.parents
    assert worktree.name == "adopt-agent-forge"


@pytest.mark.parametrize(
    ("files", "runner", "command"),
    [
        ({"tox.ini": "[tox]\n"}, "tox", "uv run tox"),
        ({"noxfile.py": "import nox\n"}, "nox", "uv run nox"),
        (
            {
                "tests/test_unit.py": (
                    "import unittest\nclass TestUnit(unittest.TestCase): pass\n"
                )
            },
            "unittest",
            "uv run python -m unittest discover",
        ),
    ],
)
def test_detects_existing_test_runners(
    tmp_path: Path, files: dict[str, str], runner: str, command: str
) -> None:
    files["requirements.txt"] = ""
    facts = inspect_repository(_repository(tmp_path, files))
    assert runner in facts.test_runners
    assert command in facts.validation_commands
