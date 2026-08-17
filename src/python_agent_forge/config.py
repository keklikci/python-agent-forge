"""Repository configuration and orchestration policy loading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """A repository configuration is missing or unsafe."""


def _scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value.startswith(('"', "'")):
        try:
            return json.loads(value) if value.startswith('"') else value[1:-1]
        except json.JSONDecodeError as error:
            raise ConfigurationError(f"invalid quoted value: {value}") from error
    if value == "[]":
        return []
    return value


def load_mapping(path: Path) -> dict[str, Any]:
    """Load the conservative YAML subset emitted by the forge."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"cannot read {path.name}: {error}") from error
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value

    result: dict[str, Any] = {}
    active_list: str | None = None
    active_map: str | None = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 2 and line.startswith("- ") and active_list:
            result[active_list].append(_scalar(line[2:]))
            continue
        if indent == 2 and active_map and ":" in line:
            key, raw_value = line.split(":", 1)
            result[active_map][key.strip()] = _scalar(raw_value)
            continue
        if indent:
            raise ConfigurationError(f"unsupported YAML at {path.name}:{line_number}")
        if ":" not in line:
            raise ConfigurationError(f"invalid YAML at {path.name}:{line_number}")
        key, raw_value = line.split(":", 1)
        key, raw_value = key.strip(), raw_value.strip()
        active_list = active_map = None
        if not raw_value:
            # Task manifests only use nested mappings for PR metadata.
            if key == "pr":
                result[key] = {}
                active_map = key
            else:
                result[key] = []
                active_list = key
        else:
            result[key] = _scalar(raw_value)
    return result


@dataclass(frozen=True)
class ProjectConfig:
    """Detected repository facts used during execution."""

    base_branch: str
    validation_commands: tuple[str, ...]
    install_command: str | None = None
    ready: bool = True

    @classmethod
    def load(cls, target: Path) -> ProjectConfig:
        path = target / ".codex/project.yml"
        if not path.is_file():
            raise ConfigurationError("missing .codex/project.yml; run adopt first")
        data = load_mapping(path)
        commands = data.get("validation_commands")
        if not isinstance(commands, list) or not all(
            isinstance(item, str) and item for item in commands
        ):
            raise ConfigurationError("validation_commands must be a non-empty list")
        ready = data.get("autonomous_execution_ready", True)
        if not ready or "configure-per-repository" in commands:
            raise ConfigurationError("project is not ready for autonomous execution")
        base = data.get("base_branch", "main")
        if not isinstance(base, str) or not base:
            raise ConfigurationError("base_branch must be configured")
        install = data.get("install_command")
        return cls(base, tuple(commands), install if isinstance(install, str) else None)


@dataclass(frozen=True)
class OrchestrationPolicy:
    """Repository execution policy, separate from detected project facts."""

    max_parallel_tasks: int = 4
    branch_prefix: str = "codex/"
    repair_limit: int = 2
    validation_timeout_seconds: int = 900
    require_human_merge_approval: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, target: Path) -> OrchestrationPolicy:
        path = target / ".codex/orchestration.yml"
        if not path.is_file():
            raise ConfigurationError(
                "missing .codex/orchestration.yml; run adopt first"
            )
        data = load_mapping(path)
        parallel = data.get("max_parallel_tasks", 4)
        repair_limit = data.get("repair_limit", 2)
        if not isinstance(parallel, int) or not 1 <= parallel <= 4:
            raise ConfigurationError("max_parallel_tasks must be between 1 and 4")
        if not isinstance(repair_limit, int) or not 0 <= repair_limit <= 10:
            raise ConfigurationError("repair_limit must be between 0 and 10")
        branch_prefix = data.get("branch_prefix", "codex/")
        if not isinstance(branch_prefix, str) or not re.fullmatch(
            r"[a-z0-9._/-]+/", branch_prefix
        ):
            raise ConfigurationError("branch_prefix is invalid")
        known = {
            "version",
            "max_parallel_tasks",
            "branch_prefix",
            "repair_limit",
            "validation_timeout_seconds",
            "require_human_merge_approval",
        }
        return cls(
            max_parallel_tasks=parallel,
            branch_prefix=branch_prefix,
            repair_limit=repair_limit,
            validation_timeout_seconds=int(data.get("validation_timeout_seconds", 900)),
            require_human_merge_approval=bool(
                data.get("require_human_merge_approval", True)
            ),
            extra={key: value for key, value in data.items() if key not in known},
        )
