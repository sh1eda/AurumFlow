"""Stable contracts shared by framework code and independent experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ManifestError(ValueError):
    """Raised when a research manifest violates the framework contract."""


class ResearchLifecycle(StrEnum):
    CANDIDATE_DEFINITION = "candidate_definition"
    OBJECTIVE_DETECTION = "objective_detection"
    FEATURE_ENGINEERING = "feature_engineering"
    STATISTICAL_EVALUATION = "statistical_evaluation"
    ROBUSTNESS_TESTING = "robustness_testing"
    DECIDED = "decided"


class ResearchDecision(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_identifier(value: object, field_name: str) -> str:
    result = _require_text(value, field_name)
    if not _IDENTIFIER.fullmatch(result):
        raise ManifestError(
            f"{field_name} must contain only letters, digits, '.', '_' or '-'"
        )
    return result


def _text_tuple(value: object, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError(f"{field_name} must be a TOML array of strings")
    result = tuple(_require_text(item, field_name) for item in value)
    if not result and not allow_empty:
        raise ManifestError(f"{field_name} must contain at least one item")
    return result


@dataclass(frozen=True)
class ResearchObjectDefinition:
    object_id: str
    title: str
    version: str
    catalog_reference: str
    layer: int
    lifecycle: ResearchLifecycle
    decision: ResearchDecision
    objective: str
    manifest_path: Path

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any], manifest_path: Path
    ) -> "ResearchObjectDefinition":
        try:
            lifecycle = ResearchLifecycle(payload["lifecycle"])
            decision = ResearchDecision(payload["decision"])
            layer = int(payload["layer"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"invalid lifecycle metadata in {manifest_path}: {exc}") from exc

        if layer < 0:
            raise ManifestError(f"layer must be non-negative in {manifest_path}")
        scientific_decisions = {
            ResearchDecision.ACCEPTED,
            ResearchDecision.REJECTED,
            ResearchDecision.INCONCLUSIVE,
        }
        if lifecycle is ResearchLifecycle.DECIDED and decision not in scientific_decisions:
            raise ManifestError("a decided research object must have a scientific decision")
        if lifecycle is not ResearchLifecycle.DECIDED and decision is not ResearchDecision.NOT_EVALUATED:
            raise ManifestError("only decided objects may have a scientific decision")

        return cls(
            object_id=_require_identifier(payload.get("id"), "object.id"),
            title=_require_text(payload.get("title"), "object.title"),
            version=_require_text(payload.get("version"), "object.version"),
            catalog_reference=_require_text(
                payload.get("catalog_reference"), "object.catalog_reference"
            ),
            layer=layer,
            lifecycle=lifecycle,
            decision=decision,
            objective=_require_text(payload.get("objective"), "object.objective"),
            manifest_path=manifest_path,
        )


@dataclass(frozen=True)
class ExperimentDefinition:
    experiment_id: str
    research_object: str
    title: str
    version: str
    entry_point: str
    output_namespace: str
    hypothesis: str
    measurable_definition: str
    required_data: tuple[str, ...]
    success_criteria: tuple[str, ...]
    failure_criteria: tuple[str, ...]
    validation_method: str
    known_limitations: tuple[str, ...]
    default_parameters: Mapping[str, Any]
    manifest_path: Path

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, Any], manifest_path: Path
    ) -> "ExperimentDefinition":
        entry_point = _require_text(payload.get("entry_point"), "experiment.entry_point")
        module_name, separator, attribute = entry_point.partition(":")
        if not separator or not module_name or not attribute:
            raise ManifestError(
                f"experiment.entry_point must use 'module:callable' syntax in {manifest_path}"
            )

        parameters = payload.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ManifestError(f"experiment.parameters must be a table in {manifest_path}")

        return cls(
            experiment_id=_require_identifier(payload.get("id"), "experiment.id"),
            research_object=_require_identifier(
                payload.get("research_object"), "experiment.research_object"
            ),
            title=_require_text(payload.get("title"), "experiment.title"),
            version=_require_text(payload.get("version"), "experiment.version"),
            entry_point=entry_point,
            output_namespace=_require_identifier(
                payload.get("output_namespace"), "experiment.output_namespace"
            ),
            hypothesis=_require_text(payload.get("hypothesis"), "experiment.hypothesis"),
            measurable_definition=_require_text(
                payload.get("measurable_definition"), "experiment.measurable_definition"
            ),
            required_data=_text_tuple(
                payload.get("required_data"), "experiment.required_data", allow_empty=True
            ),
            success_criteria=_text_tuple(
                payload.get("success_criteria"), "experiment.success_criteria"
            ),
            failure_criteria=_text_tuple(
                payload.get("failure_criteria"), "experiment.failure_criteria"
            ),
            validation_method=_require_text(
                payload.get("validation_method"), "experiment.validation_method"
            ),
            known_limitations=_text_tuple(
                payload.get("known_limitations"), "experiment.known_limitations"
            ),
            default_parameters=dict(parameters),
            manifest_path=manifest_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.experiment_id,
            "research_object": self.research_object,
            "title": self.title,
            "version": self.version,
            "entry_point": self.entry_point,
            "output_namespace": self.output_namespace,
            "hypothesis": self.hypothesis,
            "measurable_definition": self.measurable_definition,
            "required_data": list(self.required_data),
            "success_criteria": list(self.success_criteria),
            "failure_criteria": list(self.failure_criteria),
            "validation_method": self.validation_method,
            "known_limitations": list(self.known_limitations),
            "manifest_path": str(self.manifest_path),
        }


@dataclass(frozen=True)
class ExperimentResult:
    """Required evidence returned by every successful experiment entry point."""

    summary: str
    research_status: ResearchDecision
    status_rationale: str
    sample_size: int
    bootstrap_confidence_intervals: Mapping[str, Any]
    robustness_checks: Sequence[str]
    sensitivity_analysis: Sequence[str]
    data_exclusions: Sequence[str]
    limitations: Sequence[str]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    findings: Sequence[str] = field(default_factory=tuple)
    artifacts: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.research_status not in {
            ResearchDecision.ACCEPTED,
            ResearchDecision.REJECTED,
            ResearchDecision.INCONCLUSIVE,
        }:
            raise ValueError(
                "successful experiments must return accepted, rejected, or inconclusive"
            )
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative")
        if not self.summary.strip() or not self.status_rationale.strip():
            raise ValueError("summary and status_rationale must be non-empty")
        if self.research_status in {
            ResearchDecision.ACCEPTED,
            ResearchDecision.REJECTED,
        }:
            missing = []
            if self.sample_size == 0:
                missing.append("sample_size")
            if not self.bootstrap_confidence_intervals:
                missing.append("bootstrap_confidence_intervals")
            if not self.robustness_checks:
                missing.append("robustness_checks")
            if not self.sensitivity_analysis:
                missing.append("sensitivity_analysis")
            if not self.limitations:
                missing.append("limitations")
            if missing:
                raise ValueError(
                    "accepted/rejected results require evidence fields: " + ", ".join(missing)
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "research_status": self.research_status.value,
            "status_rationale": self.status_rationale,
            "sample_size": self.sample_size,
            "bootstrap_confidence_intervals": dict(self.bootstrap_confidence_intervals),
            "robustness_checks": list(self.robustness_checks),
            "sensitivity_analysis": list(self.sensitivity_analysis),
            "data_exclusions": list(self.data_exclusions),
            "limitations": list(self.limitations),
            "metrics": dict(self.metrics),
            "findings": list(self.findings),
            "artifacts": list(self.artifacts),
        }
