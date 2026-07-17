"""Isolated experiment execution with provenance and mandatory reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib import metadata as importlib_metadata
import json
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import traceback
from typing import Any, Callable, Mapping
from uuid import uuid4

from .config import FrameworkConfig, deep_merge
from .data import DataCatalog, RecordingDataAccess
from .models import ExperimentDefinition, ExperimentResult, ResearchDecision
from .reporting import FRAMEWORK_ARTIFACTS, write_report_bundle
from .structured_logging import RunLogger


@dataclass(frozen=True)
class ExperimentContext:
    definition: ExperimentDefinition
    parameters: Mapping[str, Any]
    output_dir: Path
    run_id: str
    started_at: datetime
    random: random.Random
    data: RecordingDataAccess
    logger: RunLogger


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    output_dir: Path
    result: ExperimentResult


class ExperimentRunFailed(RuntimeError):
    def __init__(self, message: str, output_dir: Path) -> None:
        super().__init__(message)
        self.output_dir = output_dir


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _configuration_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _git_metadata(project_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def _runtime_metadata(project_root: Path) -> dict[str, Any]:
    return {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": {
            "aurumflow": _package_version("aurumflow"),
            "pandas": _package_version("pandas"),
        },
        "git": _git_metadata(project_root),
        "command": sys.argv,
    }


class ExperimentRunner:
    def __init__(self, config: FrameworkConfig, data_catalog: DataCatalog) -> None:
        self.config = config
        self.data_catalog = data_catalog

    def _make_output_dir(
        self, definition: ExperimentDefinition, started_at: datetime
    ) -> tuple[str, Path]:
        timestamp = started_at.strftime("%Y%m%dT%H%M%S.%fZ")
        run_id = f"{timestamp}-{uuid4().hex[:8]}"
        output_dir = (
            self.config.paths.outputs
            / definition.research_object
            / definition.output_namespace
            / run_id
        )
        output_dir.mkdir(parents=True, exist_ok=False)
        return run_id, output_dir

    def run(
        self,
        definition: ExperimentDefinition,
        entry_point: Callable[[ExperimentContext], ExperimentResult],
        parameter_overrides: Mapping[str, Any] | None = None,
    ) -> RunOutcome:
        parameters = deep_merge(
            self.config.experiment_defaults,
            definition.default_parameters,
            parameter_overrides or {},
        )
        resolved_configuration = {
            "framework": self.config.snapshot(),
            "experiment_parameters": parameters,
        }
        configuration_hash = _configuration_hash(resolved_configuration)
        started_at = _utc_now()
        monotonic_start = time.monotonic()
        run_id, output_dir = self._make_output_dir(definition, started_at)
        logger = RunLogger(
            path=output_dir / "run.log.jsonl",
            level=self.config.logging.level,
            console=self.config.logging.console,
            run_id=run_id,
            experiment_id=definition.experiment_id,
            research_object=definition.research_object,
        )
        data_access = RecordingDataAccess(self.data_catalog)
        context = ExperimentContext(
            definition=definition,
            parameters=parameters,
            output_dir=output_dir,
            run_id=run_id,
            started_at=started_at,
            random=random.Random(self.config.project.random_seed),
            data=data_access,
            logger=logger,
        )
        runtime = _runtime_metadata(self.config.project.root)
        logger.info(
            "experiment_started",
            "Experiment execution started",
            configuration_hash=configuration_hash,
            random_seed=self.config.project.random_seed,
            output_dir=str(output_dir),
        )

        try:
            result = entry_point(context)
            if not isinstance(result, ExperimentResult):
                raise TypeError(
                    "experiment entry point must return aurumflow_research.ExperimentResult"
                )
            completed_at = _utc_now()
            duration_seconds = time.monotonic() - monotonic_start
            logger.info(
                "experiment_completed",
                "Experiment execution completed",
                research_status=result.research_status.value,
                duration_seconds=duration_seconds,
            )
            run_payload = {
                "run_id": run_id,
                "execution_status": "completed",
                "research_status": result.research_status.value,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "timestamp": completed_at.isoformat(),
                "duration_seconds": duration_seconds,
                "output_location": str(output_dir),
                "configuration_hash": configuration_hash,
            }
            summary = {
                "schema_version": "1.0",
                "experiment": definition.to_dict(),
                "run": run_payload,
                "result": result.to_dict(),
                "inputs": list(data_access.inputs),
                "resolved_configuration": resolved_configuration,
                "artifacts": list(FRAMEWORK_ARTIFACTS),
            }
            execution_metadata = {
                "schema_version": "1.0",
                **run_payload,
                "random_seed": self.config.project.random_seed,
                "runtime": runtime,
                "inputs": list(data_access.inputs),
            }
            research_status = {
                "schema_version": "1.0",
                "experiment_id": definition.experiment_id,
                "research_object": definition.research_object,
                "status": result.research_status.value,
                "rationale": result.status_rationale,
                "timestamp": completed_at.isoformat(),
                "run_id": run_id,
            }
            write_report_bundle(
                output_dir=output_dir,
                summary=summary,
                execution_metadata=execution_metadata,
                research_status=research_status,
                resolved_configuration=resolved_configuration,
            )
            return RunOutcome(run_id=run_id, output_dir=output_dir, result=result)
        except Exception as exc:
            completed_at = _utc_now()
            duration_seconds = time.monotonic() - monotonic_start
            logger.exception(
                "experiment_failed",
                "Experiment execution failed",
                error_type=type(exc).__name__,
                duration_seconds=duration_seconds,
            )
            run_payload = {
                "run_id": run_id,
                "execution_status": "failed",
                "research_status": ResearchDecision.FAILED.value,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "timestamp": completed_at.isoformat(),
                "duration_seconds": duration_seconds,
                "output_location": str(output_dir),
                "configuration_hash": configuration_hash,
            }
            error = {"type": type(exc).__name__, "message": str(exc)}
            summary = {
                "schema_version": "1.0",
                "experiment": definition.to_dict(),
                "run": run_payload,
                "error": error,
                "inputs": list(data_access.inputs),
                "resolved_configuration": resolved_configuration,
                "artifacts": list(FRAMEWORK_ARTIFACTS),
            }
            execution_metadata = {
                "schema_version": "1.0",
                **run_payload,
                "random_seed": self.config.project.random_seed,
                "runtime": runtime,
                "inputs": list(data_access.inputs),
                "error": {**error, "traceback": traceback.format_exc()},
            }
            research_status = {
                "schema_version": "1.0",
                "experiment_id": definition.experiment_id,
                "research_object": definition.research_object,
                "status": ResearchDecision.FAILED.value,
                "rationale": "The experiment did not complete; no research conclusion was made.",
                "timestamp": completed_at.isoformat(),
                "run_id": run_id,
            }
            write_report_bundle(
                output_dir=output_dir,
                summary=summary,
                execution_metadata=execution_metadata,
                research_status=research_status,
                resolved_configuration=resolved_configuration,
            )
            raise ExperimentRunFailed(str(exc), output_dir) from exc
        finally:
            logger.close()
