"""Compatibility-first inspection and adoption of existing Python projects."""

from __future__ import annotations

import configparser
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MANAGED_HEADER = "# Managed by Python Agent Forge."
WORKFLOW_PATH = ".github/workflows/python-agent-forge.yml"
PROJECT_PATH = ".codex/project.yml"
ORCHESTRATION_PATH = ".codex/orchestration.yml"
VALIDATE_PATH = "scripts/validate-python.sh"

_CONTRADICTORY_INSTRUCTIONS = re.compile(
    r"(?:do not|don't|never)\s+(?:use\s+)?(?:codex|agents?|worktrees?)|"
    r"agents?\s+(?:may|can|must)\s+merge",
    re.IGNORECASE,
)
_PYTHON_RE = re.compile(r"python_requires\s*=\s*['\"]([^'\"]+)")


class AdoptionError(RuntimeError):
    """A safe-adoption precondition was not met."""


@dataclass
class Inspection:
    """Serializable facts detected without modifying a repository."""

    target: str
    git_repository: bool
    repository: str | None
    base_branch: str | None
    dirty: bool
    packaging: list[str] = field(default_factory=list)
    package_manager: str = "unknown"
    python_constraint: str | None = None
    source_paths: list[str] = field(default_factory=list)
    test_paths: list[str] = field(default_factory=list)
    test_runners: list[str] = field(default_factory=list)
    quality_tools: list[str] = field(default_factory=list)
    ci_workflows: list[str] = field(default_factory=list)
    install_command: str | None = None
    validation_commands: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        """Return portable facts, excluding the absolute inspection path."""
        facts = asdict(self)
        facts.pop("target")
        return facts


def _run_git(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _git_value(target: Path, *args: str) -> str | None:
    result = _run_git(target, *args)
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _repository_identity(remote: str | None) -> str | None:
    if not remote:
        return None
    match = re.search(r"(?:github\.com[/:])([^/]+/[^/]+?)(?:\.git)?$", remote)
    return match.group(1) if match else None


def _load_pyproject(path: Path, warnings: list[str]) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        warnings.append(f"could not parse pyproject.toml: {error}")
        return {}


def _dependency_names(data: dict[str, Any]) -> set[str]:
    project = data.get("project", {})
    dependencies = list(project.get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        if isinstance(group, list):
            dependencies.extend(group)
    dependencies.extend(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    names: set[str] = set()
    for item in dependencies:
        name = str(item).split(";", 1)[0].strip()
        name = re.split(r"[<>=!~\[ ]", name, maxsplit=1)[0]
        names.add(name.lower().replace("_", "-"))
    return names


def _python_constraint(target: Path, data: dict[str, Any]) -> str | None:
    project_value = data.get("project", {}).get("requires-python")
    if project_value:
        return str(project_value)
    poetry_value = (
        data.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python")
    )
    if poetry_value:
        return str(poetry_value)
    setup_cfg = target / "setup.cfg"
    if setup_cfg.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(setup_cfg, encoding="utf-8")
            if parser.has_option("options", "python_requires"):
                return parser.get("options", "python_requires")
        except configparser.Error:
            pass
    setup_py = target / "setup.py"
    if setup_py.is_file():
        match = _PYTHON_RE.search(setup_py.read_text(encoding="utf-8", errors="ignore"))
        if match:
            return match.group(1)
    return None


def _configured_tools(data: dict[str, Any]) -> set[str]:
    known = {
        "ruff",
        "black",
        "flake8",
        "mypy",
        "pyright",
        "pylint",
        "isort",
        "pytest",
        "coverage",
    }
    return set(data.get("tool", {})) & known


def _ci_contents(target: Path, workflows: list[str]) -> str:
    contents: list[str] = []
    for relative in workflows:
        try:
            contents.append((target / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
    return "\n".join(contents)


def _relative_dirs(target: Path, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if (target / name).is_dir()]


def _detect_instructions(target: Path, blockers: list[str]) -> None:
    instructions = target / "AGENTS.md"
    if not instructions.is_file():
        return
    text = instructions.read_text(encoding="utf-8", errors="ignore")
    if _CONTRADICTORY_INSTRUCTIONS.search(text):
        blockers.append(
            "AGENTS.md contains rules that conflict with forge orchestration"
        )


def _detect_codex_schema(target: Path, blockers: list[str]) -> None:
    for relative in (PROJECT_PATH, ORCHESTRATION_PATH):
        path = target / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        known_keys = ("python:", "task_id:", "version:")
        if MANAGED_HEADER not in text and not any(key in text for key in known_keys):
            blockers.append(f"{relative} uses an unknown, unmanaged schema")


def inspect_repository(target: Path) -> Inspection:
    """Detect project facts without writing to *target*."""
    resolved = target.expanduser().resolve()
    if not resolved.is_dir():
        raise AdoptionError(f"target directory does not exist: {target}")

    warnings: list[str] = []
    blockers: list[str] = []
    git_repository = (
        _run_git(resolved, "rev-parse", "--is-inside-work-tree").returncode == 0
    )
    dirty = False
    base_branch: str | None = None
    repository: str | None = None
    if git_repository:
        dirty = bool(_git_value(resolved, "status", "--porcelain"))
        remote = _git_value(resolved, "remote", "get-url", "origin")
        repository = _repository_identity(remote)
        origin_head = _git_value(
            resolved, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"
        )
        base_branch = origin_head.rsplit("/", 1)[-1] if origin_head else None
        base_branch = base_branch or _git_value(resolved, "branch", "--show-current")
    else:
        blockers.append("target is not a Git repository")

    pyproject = _load_pyproject(resolved / "pyproject.toml", warnings)
    dependencies = _dependency_names(pyproject)
    packaging = [
        name
        for name in ("pyproject.toml", "setup.cfg", "setup.py")
        if (resolved / name).is_file()
    ]
    requirements = sorted(
        path.name for path in resolved.glob("requirements*.txt") if path.is_file()
    )
    packaging.extend(requirements)
    for requirement in requirements:
        for line in (
            (resolved / requirement)
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
        ):
            name = re.split(r"[<>=!~\[ ;]", line.strip(), maxsplit=1)[0]
            if name and not name.startswith(("-", "#")):
                dependencies.add(name.lower().replace("_", "-"))

    if (resolved / "uv.lock").is_file():
        manager = "uv"
    elif (resolved / "poetry.lock").is_file() or "poetry" in pyproject.get("tool", {}):
        manager = "poetry"
    elif (resolved / "pdm.lock").is_file() or "pdm" in pyproject.get("tool", {}):
        manager = "pdm"
    elif (resolved / "Pipfile").is_file():
        manager = "pipenv"
    elif requirements:
        manager = "requirements"
    elif pyproject or any(
        (resolved / name).is_file() for name in ("setup.cfg", "setup.py")
    ):
        manager = "pip"
    else:
        manager = "unknown"
        warnings.append(
            "unknown packaging layout; configure install and validation commands"
        )

    test_paths = _relative_dirs(resolved, ("tests", "test"))
    test_runners: list[str] = []
    if (
        "pytest" in dependencies
        or "pytest" in pyproject.get("tool", {})
        or (resolved / "pytest.ini").is_file()
        or (resolved / "conftest.py").is_file()
    ):
        test_runners.append("pytest")
    if (resolved / "tox.ini").is_file():
        test_runners.append("tox")
    if (resolved / "noxfile.py").is_file():
        test_runners.append("nox")
    if not test_runners and test_paths:
        imports = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for test_path in test_paths
            for path in (resolved / test_path).rglob("test*.py")
        )
        test_runners.append("unittest" if "unittest" in imports else "pytest")

    quality_tools = sorted(_configured_tools(pyproject))
    for filename, tool in (
        ("ruff.toml", "ruff"),
        (".ruff.toml", "ruff"),
        ("mypy.ini", "mypy"),
        (".flake8", "flake8"),
    ):
        if (resolved / filename).is_file() and tool not in quality_tools:
            quality_tools.append(tool)

    if manager == "uv":
        install_command, prefix = "uv sync", "uv run "
    elif manager == "poetry":
        install_command, prefix = "poetry install", "poetry run "
    elif manager == "pdm":
        install_command, prefix = "pdm install", "pdm run "
    elif manager == "pipenv":
        install_command, prefix = "pipenv sync --dev", "pipenv run "
    elif manager == "requirements":
        install_command, prefix = f"uv pip install -r {requirements[0]}", "uv run "
    elif manager == "pip":
        install_command, prefix = "uv pip install -e .", "uv run "
    else:
        install_command, prefix = None, ""

    validation: list[str] = []
    if "ruff" in quality_tools:
        validation.extend([f"{prefix}ruff format --check .", f"{prefix}ruff check ."])
    if "tox" in test_runners:
        validation.append(f"{prefix}tox")
    elif "nox" in test_runners:
        validation.append(f"{prefix}nox")
    elif "pytest" in test_runners:
        validation.append(f"{prefix}pytest")
    elif "unittest" in test_runners:
        validation.append(f"{prefix}python -m unittest discover")
    if not validation:
        warnings.append("no usable validation command was detected")

    workflow_dir = resolved / ".github/workflows"
    workflows = (
        sorted(str(path.relative_to(resolved)) for path in workflow_dir.glob("*.y*ml"))
        if workflow_dir.is_dir()
        else []
    )
    _detect_instructions(resolved, blockers)
    _detect_codex_schema(resolved, blockers)

    source_paths = _relative_dirs(resolved, ("src", "lib", "app"))
    if not source_paths:
        excluded = {
            "tests",
            "test",
            "docs",
            "scripts",
            ".git",
            ".github",
            ".codex",
        }
        source_paths = sorted(
            path.name
            for path in resolved.iterdir()
            if path.is_dir()
            and path.name not in excluded
            and (path / "__init__.py").is_file()
        )
    if not source_paths:
        warnings.append("no conventional Python source path was detected")

    return Inspection(
        target=str(resolved),
        git_repository=git_repository,
        repository=repository,
        base_branch=base_branch,
        dirty=dirty,
        packaging=packaging,
        package_manager=manager,
        python_constraint=_python_constraint(resolved, pyproject),
        source_paths=source_paths,
        test_paths=test_paths,
        test_runners=test_runners,
        quality_tools=sorted(quality_tools),
        ci_workflows=workflows,
        install_command=install_command,
        validation_commands=validation,
        warnings=warnings,
        blockers=blockers,
    )


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _yaml_list(values: list[str], indent: int = 2) -> str:
    if not values:
        return "[]"
    padding = " " * indent
    return "\n".join(f"{padding}- {_yaml_string(value)}" for value in values)


def _yaml_list_field(name: str, values: list[str]) -> str:
    """Render a list in the conservative YAML subset understood by Forge."""
    rendered = _yaml_list(values)
    return f"{name}: {rendered}" if rendered == "[]" else f"{name}:\n{rendered}"


def _project_config(facts: Inspection) -> str:
    repository = facts.repository or "configure-per-repository"
    base = facts.base_branch or "main"
    python = facts.python_constraint or "configure-per-repository"
    install = facts.install_command or "configure-per-repository"
    paths = facts.source_paths + facts.test_paths
    ready = str(bool(facts.install_command and facts.validation_commands)).lower()
    return f"""{MANAGED_HEADER}
version: 1
repository: {_yaml_string(repository)}
base_branch: {_yaml_string(base)}
python_constraint: {_yaml_string(python)}
package_manager: {_yaml_string(facts.package_manager)}
{_yaml_list_field("source_paths", facts.source_paths)}
{_yaml_list_field("test_paths", facts.test_paths)}
{_yaml_list_field("owned_paths", [f"{path}/**" for path in paths])}
install_command: {_yaml_string(install)}
{_yaml_list_field("validation_commands", facts.validation_commands)}
autonomous_execution_ready: {ready}
"""


def _orchestration_config() -> str:
    return f"""{MANAGED_HEADER}
version: 1
max_parallel_tasks: 4
branch_prefix: codex/
repair_limit: 2
ci_timeout_minutes: 30
require_ci: true
require_review: true
require_human_merge_approval: true
"""


def _agents_file(facts: Inspection) -> str:
    validations = "\n".join(
        f"- Run `{command}`." for command in facts.validation_commands
    )
    validations = validations or (
        "- Configure a valid repository validation command before implementation."
    )
    return f"""{MANAGED_HEADER}
# Python Repository Agent Instructions

This repository uses Python Agent Forge. Preserve existing project conventions.

{validations}
- Never persist local absolute paths, credentials, tokens, or private data.
- Require CI, independent review, and human approval before merge.
"""


def _validation_script(facts: Inspection) -> str:
    commands = (
        [facts.install_command] if facts.install_command else []
    ) + facts.validation_commands
    return f"#!/bin/sh\n{MANAGED_HEADER}\nset -eu\n" + "\n".join(commands) + "\n"


def _workflow(facts: Inspection) -> str:
    commands = (
        [facts.install_command] if facts.install_command else []
    ) + facts.validation_commands
    steps = "\n".join(f"      - run: {command}" for command in commands)
    return f"""{MANAGED_HEADER}
name: Python Agent Forge
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
{steps}
"""


def _ci_covers_validation(target: Path, facts: Inspection) -> bool:
    if not facts.ci_workflows or not facts.validation_commands:
        return False
    content = _ci_contents(target, facts.ci_workflows)
    return all(command in content for command in facts.validation_commands)


def _legacy_forge_file(relative: str, text: str) -> bool:
    if relative == PROJECT_PATH:
        return any(key in text for key in ("task_id:", "python:"))
    if relative == ORCHESTRATION_PATH:
        return "version:" in text and "branch_prefix:" in text
    return False


def _write_managed(path: Path, content: str, relative: str) -> bool:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
            return False
        if MANAGED_HEADER not in existing and not _legacy_forge_file(
            relative, existing
        ):
            raise AdoptionError(
                f"refusing to overwrite unmanaged file: {path.as_posix()}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def adopt_local(
    target: Path, *, allow_dirty: bool = False
) -> tuple[Inspection, list[str]]:
    """Write a conservative orchestration overlay to an existing repository."""
    facts = inspect_repository(target)
    root = Path(facts.target)
    if facts.dirty and not allow_dirty:
        raise AdoptionError("target has uncommitted changes; adoption made no changes")
    if facts.blockers:
        raise AdoptionError("; ".join(facts.blockers))

    managed = {
        PROJECT_PATH: _project_config(facts),
        ORCHESTRATION_PATH: _orchestration_config(),
    }
    validation_path = root / VALIDATE_PATH
    if not validation_path.exists() or MANAGED_HEADER in validation_path.read_text(
        encoding="utf-8", errors="ignore"
    ):
        managed[VALIDATE_PATH] = _validation_script(facts)
    if not (root / "AGENTS.md").exists():
        managed["AGENTS.md"] = _agents_file(facts)
    if not _ci_covers_validation(root, facts) and facts.validation_commands:
        managed[WORKFLOW_PATH] = _workflow(facts)

    # Preflight all collisions so an error occurs before the first write.
    for relative, content in managed.items():
        path = root / relative
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if (
                existing != content
                and MANAGED_HEADER not in existing
                and not _legacy_forge_file(relative, existing)
            ):
                raise AdoptionError(f"refusing to overwrite unmanaged file: {relative}")
    changes: list[str] = []
    for relative, content in managed.items():
        path = root / relative
        if _write_managed(path, content, relative):
            changes.append(relative)
            if relative.endswith(".sh"):
                path.chmod(0o755)
    return facts, changes


def _default_worktree_path(target: Path) -> Path:
    git_dir = _git_value(target, "rev-parse", "--git-common-dir")
    if not git_dir:
        raise AdoptionError("could not determine Git directory")
    common = (target / git_dir).resolve()
    # Keep generated worktrees beside the main checkout, never inside it: an
    # in-repository worktree directory would make the clean preflight dirty.
    return common.parent.parent / ".paf-worktrees" / "adopt-agent-forge"


def adopt_in_worktree(target: Path, base: str | None = None) -> tuple[Path, list[str]]:
    """Adopt on an isolated branch and open a GitHub PR through ``gh``."""
    facts = inspect_repository(target)
    if facts.dirty:
        raise AdoptionError("target has uncommitted changes; adoption made no changes")
    if facts.blockers:
        raise AdoptionError("; ".join(facts.blockers))
    selected_base = base or facts.base_branch
    if not selected_base:
        raise AdoptionError("could not detect a base branch; pass --base")
    if not facts.repository:
        raise AdoptionError("origin is not a recognizable GitHub repository")
    branch = "codex/adopt-agent-forge"
    worktree = _default_worktree_path(target)
    if worktree.exists():
        raise AdoptionError(f"adoption worktree already exists: {worktree}")
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree),
            selected_base,
        ],
        check=True,
    )
    try:
        _, changes = adopt_local(worktree)
        if not changes:
            raise AdoptionError("repository is already adopted")
        subprocess.run(["git", "-C", str(worktree), "add", "--", *changes], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "commit",
                "-m",
                "feat(adopt): port existing Python repository safely",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(worktree), "push", "-u", "origin", branch],
            check=True,
        )
        body = (
            "## Summary\n\nAdopt this repository into Python Agent Forge while "
            "preserving its conventions.\n\n"
            "## Validation\n\n"
            + "\n".join(f"- `{item}`" for item in facts.validation_commands)
        )
        subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                facts.repository,
                "--base",
                selected_base,
                "--head",
                branch,
                "--title",
                "feat(adopt): port existing Python repository safely",
                "--body",
                body,
            ],
            cwd=worktree,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        print(f"adoption worktree retained for recovery: {worktree}", file=sys.stderr)
        raise
    return worktree, changes


def format_inspection(facts: Inspection) -> str:
    lines = [
        f"repository: {facts.repository or 'unknown'}",
        f"base branch: {facts.base_branch or 'unknown'}",
        f"package manager: {facts.package_manager}",
        f"Python constraint: {facts.python_constraint or 'unknown'}",
        "validation: " + (", ".join(facts.validation_commands) or "not detected"),
    ]
    lines.extend(f"warning: {warning}" for warning in facts.warnings)
    lines.extend(f"blocker: {blocker}" for blocker in facts.blockers)
    return "\n".join(lines)
