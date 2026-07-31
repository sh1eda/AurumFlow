"""Frozen additive configuration for the D005_E4 2026 preflight."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Final


FROZEN_START: Final = "2026-01-01T00:00:00Z"
FROZEN_END: Final = "2026-07-29T00:00:00Z"
FROZEN_OUTPUT: Final = (
    "research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION"
)
HISTORICAL_OUTPUT: Final = (
    "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION"
)

ALLOWED_METRICS: Final = (
    "sample_count",
    "mean_signed_movement",
    "median_signed_movement",
    "win_probability",
    "mean_mfe",
    "mean_mae",
    "mean_mfe_to_mean_mae",
    "median_mfe_mae_ratio",
    "adverse_before_favorable_probability",
    "median_time_to_mfe_minutes",
    "median_time_to_mae_minutes",
    "standard_deviation",
    "standard_error",
    "mean_ci_lower",
    "mean_ci_upper",
    "bootstrap_ci_lower",
    "bootstrap_ci_upper",
    "bootstrap_standard_error",
)

FROZEN_HISTORICAL_HASHES: Final = {
    "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md": (
        "704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b"
    ),
    "research/d005_e4_1h_5m_reversal_replication/config.py": (
        "706755af2947fc9ec3d9cb06ffa179b38970b9c883ed9974dd15520699b8d833"
    ),
    "research/d005_e4_1h_5m_reversal_replication/selection.py": (
        "6db53eb793874825f224bc2b0f9bce411b6474e94b320590d958865e63feddf4"
    ),
    "research/d005_e4_1h_5m_reversal_replication/analysis.py": (
        "f616312bd269840cab7b8ccea181992650c9a975a8d2d00ac1bc4a80a247ed15"
    ),
    "research/d005_e4_1h_5m_reversal_replication/pipeline.py": (
        "a94dd4975933302b94f7a0cb5b8ae12ab46bce4b4d9dd4ea653d87b835a220a8"
    ),
    "research/d005_e4_1h_5m_reversal_replication/reporting.py": (
        "dbd8ec98261c478662d4f7d963bf69359fbb3536934bdb05cac1c5a95108a007"
    ),
    "research/d005_e3_early_context_anchor_study/outcomes.py": (
        "ad293dfce3cfc325f9c6e925c34f18b2ab50ff585bcf88af2604ca9f7fc482a0"
    ),
}


@dataclass(frozen=True)
class ArtifactRequirement:
    """One read-only artifact required before outcome access."""

    name: str
    path: str
    kind: str
    source_of_expectation: str
    required: bool = True
    tracked_by_git: bool = False
    managed_by_git_lfs: bool = False
    safe_restoration_method: str | None = None
    required_children: tuple[str, ...] = ()


def artifact_requirements() -> tuple[ArtifactRequirement, ...]:
    """Return the preregistered, non-discoverable artifact contract."""

    user_source = "D005_E4 2026 replication task and extension specification"
    release_source = "docs/D003_ACCEPTANCE_REPORT.md release bundle contract"
    historical_source = (
        "research/d005_e4_1h_5m_reversal_replication/pipeline.py"
    )
    ignored_source = "README.md and .gitignore local-artifact policy"
    return (
        ArtifactRequirement(
            "canonical_d003_v2_dataset",
            "data/canonical/xauusd_ticks_d003-v2",
            "directory",
            user_source,
            required_children=("canonical_manifest.json",),
        ),
        ArtifactRequirement(
            "canonical_d003_v2_2026_parquet_partitions",
            "data/canonical/xauusd_ticks_d003-v2/year=2026",
            "parquet_tree",
            user_source,
        ),
        ArtifactRequirement(
            "canonical_d003_v2_manifest",
            "data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json",
            "file",
            user_source,
        ),
        ArtifactRequirement(
            "d003_v2_release_bundle",
            "data/releases/d003-v2",
            "directory",
            release_source,
            required_children=(
                "RELEASE.txt",
                "canonical_manifest.json",
                "full_verification.json",
                "parquet_sha256.txt",
                "release_sha256.txt",
            ),
        ),
        ArtifactRequirement(
            "d003_v2_release_descriptor",
            "data/releases/d003-v2/RELEASE.txt",
            "file",
            release_source,
        ),
        ArtifactRequirement(
            "d003_v2_release_manifest",
            "data/releases/d003-v2/release_sha256.txt",
            "file",
            release_source,
        ),
        ArtifactRequirement(
            "d003_v2_parquet_checksum_manifest",
            "data/releases/d003-v2/parquet_sha256.txt",
            "file",
            release_source,
        ),
        ArtifactRequirement(
            "d003_v2_full_verification",
            "data/releases/d003-v2/full_verification.json",
            "file",
            release_source,
        ),
        ArtifactRequirement(
            "protected_d005_outputs",
            "research_outputs/D005_CONTEXT_ENGINE",
            "directory",
            historical_source,
            required_children=(
                "artifact_manifest.json",
                "configuration_snapshot.json",
                "reproducibility_metadata.json",
            ),
        ),
        ArtifactRequirement(
            "protected_d005_e1_outputs",
            "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY",
            "directory",
            historical_source,
            required_children=(
                "artifact_manifest.json",
                "data_quality_periods.parquet",
                "excluded_evaluations.parquet",
                "reproducibility_metadata.json",
            ),
        ),
        ArtifactRequirement(
            "protected_d005_e2_outputs",
            "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC",
            "directory",
            historical_source,
            required_children=(
                "artifact_manifest.json",
                "confirmation_event_inventory.parquet",
                "reproducibility_metadata.json",
            ),
        ),
        ArtifactRequirement(
            "protected_d005_e3_outputs",
            "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY",
            "directory",
            historical_source,
            required_children=(
                "artifact_manifest.json",
                "source_provenance.json",
                "anchor_events.parquet",
                "unique_sequences.parquet",
                "anchor_forward_outcomes.parquet",
                "multiplicity_adjusted_comparisons.parquet",
                "data_quality_periods.parquet",
                "excluded_evaluations.parquet",
            ),
        ),
        ArtifactRequirement(
            "historical_d005_e4_outputs",
            HISTORICAL_OUTPUT,
            "directory",
            historical_source,
            required_children=(
                "artifact_manifest.json",
                "summary.json",
                "primary_60m_result.parquet",
                "discovery_replication_comparison.parquet",
            ),
        ),
        ArtifactRequirement(
            "automation_validation_aid",
            "automation/config.yaml",
            "file",
            (
                "unresolved AGENTS.md repository convention; no tracked "
                "definition or consumer"
            ),
            required=False,
        ),
        ArtifactRequirement(
            "documented_local_artifact_policy",
            "README.md",
            "file",
            ignored_source,
            required=False,
            tracked_by_git=True,
        ),
    )


@dataclass(frozen=True)
class IndependentReplication2026Config:
    """A preflight-only configuration that cannot execute outcomes."""

    independent_replication: bool
    start: str = FROZEN_START
    end: str = FROZEN_END
    study_id: str = "D005_E4_2026_INDEPENDENT_REPLICATION"
    version: str = "D005-E4-2026-extension-v1"
    timezone: str = "America/New_York"
    output_dir: str = FROZEN_OUTPUT
    historical_output_dir: str = HISTORICAL_OUTPUT
    historical_spec: str = (
        "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md"
    )
    extension_spec: str = (
        "docs/D005_E4_2026_INDEPENDENT_REPLICATION_SPEC.md"
    )
    primary_mapping: str = "1h_5m"
    primary_outcome: str = "reversal"
    primary_anchor: str = "displacement_confirmation"
    secondary_anchor: str = "refinement_array_creation"
    primary_horizon: str = "60m"
    forward_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)
    day_end_clock: str = "17:00"
    confidence_level: float = 0.95
    bootstrap_resamples: int = 2000
    bootstrap_seed: int = 50054
    fdr_alpha: float = 0.05
    minimum_validation_n: int = 1000
    minimum_direction_n: int = 200
    maximum_confirmed_share: float = 0.10
    minimum_mean_mfe_mae_ratio: float = 0.75
    minimum_median_path_ratio: float = 0.50
    extreme_removal_fraction: float = 0.01
    requested_metrics: tuple[str, ...] = ALLOWED_METRICS
    historical_selection_authorized: bool = False
    historical_fitting_authorized: bool = False
    parameter_search_authorized: bool = False
    outcome_calculation_authorized: bool = False
    production_integration_authorized: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "research_only": True,
            "price_outcomes_not_pnl": True,
            "a_b_c_classification_blocked": True,
            "partial_year_temporal_rule_unregistered": True,
            "preflight_only": True,
        }
    )

    def validate(self) -> None:
        if not self.independent_replication:
            raise ValueError("explicit --independent-replication is required")
        if self.start != FROZEN_START or self.end != FROZEN_END:
            raise ValueError(
                "only [2026-01-01T00:00:00Z, "
                "2026-07-29T00:00:00Z) is accepted"
            )
        if self.output_dir != FROZEN_OUTPUT:
            raise ValueError("2026 output directory is frozen")
        protected_outputs = {
            HISTORICAL_OUTPUT,
            "research_outputs/D005_CONTEXT_ENGINE",
            "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY",
            "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC",
            "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY",
        }
        if self.output_dir in protected_outputs:
            raise ValueError("2026 output collides with a protected output")
        if self.requested_metrics != ALLOWED_METRICS:
            raise ValueError(
                "metric set is frozen to descriptive price-movement fields"
            )
        if any(
            (
                self.historical_selection_authorized,
                self.historical_fitting_authorized,
                self.parameter_search_authorized,
                self.outcome_calculation_authorized,
                self.production_integration_authorized,
            )
        ):
            raise ValueError(
                "preflight cannot authorize selection, fitting, tuning, "
                "outcomes, or production integration"
            )
        if self.bootstrap_resamples != 2000 or self.bootstrap_seed != 50054:
            raise ValueError("historical bootstrap procedure is immutable")
        if self.primary_mapping != "1h_5m":
            raise ValueError("historical primary mapping is immutable")
        if self.primary_outcome != "reversal":
            raise ValueError("historical outcome label is immutable")
        if self.primary_anchor != "displacement_confirmation":
            raise ValueError("historical primary anchor is immutable")
        if self.secondary_anchor != "refinement_array_creation":
            raise ValueError("historical secondary anchor is immutable")
        if self.primary_horizon != "60m":
            raise ValueError("historical primary horizon is immutable")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["artifact_requirements"] = [
            asdict(requirement) for requirement in artifact_requirements()
        ]
        payload["historical_file_sha256"] = dict(
            FROZEN_HISTORICAL_HASHES
        )
        payload["historical_temporal_check_applicable"] = False
        payload["a_b_c_classification_rule_registered"] = False
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def resolved_output(self, repository_root: Path) -> Path:
        return (repository_root / self.output_dir).resolve()
