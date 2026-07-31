"""Manifest discovery for research objects and isolated experiments."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import tomllib
from typing import Callable

from .models import (
    ExperimentDefinition,
    ExperimentResult,
    ManifestError,
    ResearchObjectDefinition,
)


class DiscoveryError(RuntimeError):
    """Raised for missing, duplicate, or inconsistent research manifests."""


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DiscoveryError(f"could not read manifest {path}: {exc}") from exc


class ResearchObjectCatalog:
    def __init__(self, objects: dict[str, ResearchObjectDefinition]) -> None:
        self._objects = objects

    @classmethod
    def discover(cls, root: Path) -> "ResearchObjectCatalog":
        objects: dict[str, ResearchObjectDefinition] = {}
        if not root.is_dir():
            raise DiscoveryError(f"research object directory does not exist: {root}")
        for manifest_path in sorted(root.rglob("object.toml")):
            payload = _load_toml(manifest_path)
            section = payload.get("object")
            if not isinstance(section, dict):
                raise DiscoveryError(f"manifest has no [object] table: {manifest_path}")
            try:
                definition = ResearchObjectDefinition.from_mapping(section, manifest_path)
            except ManifestError as exc:
                raise DiscoveryError(f"invalid object manifest {manifest_path}: {exc}") from exc
            if definition.object_id in objects:
                raise DiscoveryError(
                    f"duplicate research object id {definition.object_id!r}: {manifest_path}"
                )
            objects[definition.object_id] = definition
        return cls(objects)

    def get(self, object_id: str) -> ResearchObjectDefinition:
        try:
            return self._objects[object_id]
        except KeyError as exc:
            raise DiscoveryError(f"unknown research object: {object_id!r}") from exc

    def __contains__(self, object_id: str) -> bool:
        return object_id in self._objects

    def __iter__(self):
        return iter(self._objects.values())

    def __len__(self) -> int:
        return len(self._objects)


class ExperimentCatalog:
    def __init__(self, experiments: dict[str, ExperimentDefinition]) -> None:
        self._experiments = experiments

    @classmethod
    def discover(
        cls, root: Path, objects: ResearchObjectCatalog
    ) -> "ExperimentCatalog":
        experiments: dict[str, ExperimentDefinition] = {}
        for manifest_path in sorted(root.rglob("experiment.toml")):
            payload = _load_toml(manifest_path)
            section = payload.get("experiment")
            if not isinstance(section, dict):
                raise DiscoveryError(f"manifest has no [experiment] table: {manifest_path}")
            parameters = payload.get("parameters", {})
            if not isinstance(parameters, dict):
                raise DiscoveryError(f"[parameters] must be a table: {manifest_path}")
            section = {**section, "parameters": parameters}
            try:
                definition = ExperimentDefinition.from_mapping(section, manifest_path)
            except ManifestError as exc:
                raise DiscoveryError(
                    f"invalid experiment manifest {manifest_path}: {exc}"
                ) from exc
            if definition.research_object not in objects:
                raise DiscoveryError(
                    f"experiment {definition.experiment_id!r} references unknown object "
                    f"{definition.research_object!r}"
                )
            if definition.experiment_id in experiments:
                raise DiscoveryError(
                    f"duplicate experiment id {definition.experiment_id!r}: {manifest_path}"
                )
            experiments[definition.experiment_id] = definition
        return cls(experiments)

    def get(self, experiment_id: str) -> ExperimentDefinition:
        try:
            return self._experiments[experiment_id]
        except KeyError as exc:
            raise DiscoveryError(f"unknown experiment: {experiment_id!r}") from exc

    def load_entry_point(
        self, definition: ExperimentDefinition
    ) -> Callable[[object], ExperimentResult]:
        module_name, _, attribute_name = definition.entry_point.partition(":")
        try:
            entry_point = getattr(import_module(module_name), attribute_name)
        except (ImportError, AttributeError) as exc:
            raise DiscoveryError(
                f"could not import entry point {definition.entry_point!r}: {exc}"
            ) from exc
        if not callable(entry_point):
            raise DiscoveryError(
                f"experiment entry point is not callable: {definition.entry_point!r}"
            )
        return entry_point

    def __iter__(self):
        return iter(self._experiments.values())

    def __len__(self) -> int:
        return len(self._experiments)
