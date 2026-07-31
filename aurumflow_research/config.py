"""Central TOML configuration with explicit, resolved project paths."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import tomllib
from typing import Any, Mapping


CONFIG_ENVIRONMENT_VARIABLE = "AURUMFLOW_RESEARCH_CONFIG"


class ConfigurationError(ValueError):
    """Raised when central research configuration is missing or invalid."""


@dataclass(frozen=True)
class ProjectSettings:
    name: str
    root: Path
    timezone: str
    random_seed: int


@dataclass(frozen=True)
class PathSettings:
    data: Path
    research_objects: Path
    outputs: Path


@dataclass(frozen=True)
class LoggingSettings:
    level: str
    console: bool


@dataclass(frozen=True)
class FrameworkConfig:
    source_path: Path
    project: ProjectSettings
    paths: PathSettings
    logging: LoggingSettings
    data_sources: Mapping[str, Mapping[str, Any]]
    experiment_defaults: Mapping[str, Any]

    def snapshot(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "project": {
                "name": self.project.name,
                "root": str(self.project.root),
                "timezone": self.project.timezone,
                "random_seed": self.project.random_seed,
            },
            "paths": {
                "data": str(self.paths.data),
                "research_objects": str(self.paths.research_objects),
                "outputs": str(self.paths.outputs),
            },
            "logging": {
                "level": self.logging.level,
                "console": self.logging.console,
            },
            "data_sources": deepcopy(dict(self.data_sources)),
            "experiment_defaults": deepcopy(dict(self.experiment_defaults)),
        }


def _required_table(payload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = payload.get(name)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"missing or invalid [{name}] table")
    return value


def _text(table: Mapping[str, Any], key: str, table_name: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{table_name}.{key} must be a non-empty string")
    return value.strip()


def _resolve(base: Path, configured: str) -> Path:
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def discover_config(start: Path | None = None) -> Path:
    configured = os.environ.get(CONFIG_ENVIRONMENT_VARIABLE)
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise ConfigurationError(
                f"{CONFIG_ENVIRONMENT_VARIABLE} does not point to a file: {path}"
            )
        return path

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "config" / "research.toml"
        if candidate.is_file():
            return candidate
    raise ConfigurationError(
        "could not find config/research.toml; pass --config or set "
        f"{CONFIG_ENVIRONMENT_VARIABLE}"
    )


def load_config(path: Path | str | None = None) -> FrameworkConfig:
    source_path = Path(path).expanduser().resolve() if path else discover_config()
    if not source_path.is_file():
        raise ConfigurationError(f"research configuration does not exist: {source_path}")

    with source_path.open("rb") as handle:
        payload = tomllib.load(handle)

    project = _required_table(payload, "project")
    paths = _required_table(payload, "paths")
    logging = _required_table(payload, "logging")
    data = _required_table(payload, "data")

    root = _resolve(source_path.parent, _text(project, "root", "project"))
    try:
        random_seed = int(project["random_seed"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError("project.random_seed must be an integer") from exc

    level = _text(logging, "level", "logging").upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in valid_levels:
        raise ConfigurationError(f"logging.level must be one of {sorted(valid_levels)}")
    console = logging.get("console", True)
    if not isinstance(console, bool):
        raise ConfigurationError("logging.console must be true or false")

    sources = data.get("sources", {})
    if not isinstance(sources, Mapping):
        raise ConfigurationError("data.sources must be a table")
    for source_name, source in sources.items():
        if not isinstance(source, Mapping) or not isinstance(source.get("driver"), str):
            raise ConfigurationError(
                f"data.sources.{source_name} must be a table with a driver"
            )

    defaults = payload.get("experiment_defaults", {})
    if not isinstance(defaults, Mapping):
        raise ConfigurationError("experiment_defaults must be a table")

    return FrameworkConfig(
        source_path=source_path,
        project=ProjectSettings(
            name=_text(project, "name", "project"),
            root=root,
            timezone=_text(project, "timezone", "project"),
            random_seed=random_seed,
        ),
        paths=PathSettings(
            data=_resolve(root, _text(paths, "data", "paths")),
            research_objects=_resolve(
                root, _text(paths, "research_objects", "paths")
            ),
            outputs=_resolve(root, _text(paths, "outputs", "paths")),
        ),
        logging=LoggingSettings(level=level, console=console),
        data_sources={name: dict(source) for name, source in sources.items()},
        experiment_defaults=deepcopy(dict(defaults)),
    )


def deep_merge(*mappings: Mapping[str, Any]) -> dict[str, Any]:
    """Merge mappings recursively without mutating any input."""

    merged: dict[str, Any] = {}
    for mapping in mappings:
        for key, value in mapping.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
    return merged


def set_dotted_value(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    if not dotted_key or any(not part for part in dotted_key.split(".")):
        raise ConfigurationError("parameter keys must be non-empty dotted names")
    cursor = target
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ConfigurationError(f"cannot set nested parameter below {part!r}")
        cursor = existing
    cursor[parts[-1]] = value


def parse_parameter_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in values:
        key, separator, raw_value = item.partition("=")
        if not separator:
            raise ConfigurationError(f"parameter override must use KEY=VALUE: {item!r}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        set_dotted_value(overrides, key.strip(), value)
    return overrides
