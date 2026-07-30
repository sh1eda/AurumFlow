"""Frozen preregistered configuration for D005_E4."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from zoneinfo import ZoneInfo

from research.context_engine.config import NEW_YORK


@dataclass(frozen=True)
class ReversalReplicationConfig:
    study_id: str = "D005_E4_1H_5M_REVERSAL_REPLICATION"
    version: str = "D005-E4-v1"
    timezone: str = NEW_YORK
    source_start_date: date = date(2021, 1, 3)
    source_end_date: date = date(2025, 12, 31)
    calibration_year: int = 2021
    validation_years: tuple[int, ...] = (2022, 2023, 2024, 2025)
    primary_mapping: str = "1h_5m"
    optional_1m_comparator: str = "1h_5m_optional_1m"
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
    minimum_block_n: int = 200
    minimum_positive_blocks: int = 3
    minimum_direction_n: int = 200
    maximum_confirmed_share: float = 0.10
    minimum_mean_mfe_mae_ratio: float = 0.75
    minimum_median_path_ratio: float = 0.50
    extreme_removal_fraction: float = 0.01
    strength_bins: tuple[float, ...] = (1.25, 1.75, 2.50)
    latency_bins_minutes: tuple[float, ...] = (0.0, 60.0, 180.0, 360.0)
    sample_design: str = "rolling_origin_with_full_e3_overlap"
    independent_replication: bool = False
    d005_output: str = "research_outputs/D005_CONTEXT_ENGINE"
    e1_output: str = (
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
    )
    e2_output: str = (
        "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC"
    )
    e3_output: str = (
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY"
    )
    technical_spec: str = (
        "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md"
    )
    excluded_external_source: str = (
        "research/event_study_0830_0930/external_data/normalized/"
        "XAUUSD_202507171300_202607171409.1m_bidask.csv"
    )
    production_entry_authorization: bool = False
    optimization: bool = False
    cisd_enabled: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "study_type": "rolling_origin_narrow_cohort_replication",
            "price_outcomes": "descriptive_not_pnl",
            "production_integration": False,
            "threshold_change": False,
            "state_logic_change": False,
            "mapping_selection": False,
            "optional_1m_primary": False,
            "pmh_pml_promotion": False,
            "clock_promotion": False,
            "subgroup_promotion": False,
        }
    )

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError("E4 must use America/New_York")
        if self.source_end_date < self.source_start_date:
            raise ValueError("end date precedes start date")
        if self.validation_years != (2022, 2023, 2024, 2025):
            raise ValueError("E4 rolling-origin blocks are frozen")
        if self.primary_mapping != "1h_5m":
            raise ValueError("E4 primary mapping is frozen to 1h_5m")
        if self.primary_outcome != "reversal":
            raise ValueError("E4 reversal label is frozen")
        if self.primary_anchor != "displacement_confirmation":
            raise ValueError("E4 primary anchor is frozen")
        if self.secondary_anchor != "refinement_array_creation":
            raise ValueError("E4 secondary anchor is frozen")
        if self.primary_horizon != "60m":
            raise ValueError("E4 primary horizon is frozen")
        if self.forward_minutes != (5, 15, 30, 60, 120):
            raise ValueError("E4 forward horizons are frozen")
        if self.independent_replication:
            raise ValueError(
                "No independent post-2025 D003-derived sample exists"
            )
        if self.bootstrap_resamples < 1000:
            raise ValueError("E4 bootstrap resamples must be at least 1000")
        if self.production_entry_authorization:
            raise ValueError("E4 cannot authorize entries")
        if self.optimization:
            raise ValueError("E4 is not an optimization study")
        if self.cisd_enabled:
            raise ValueError("CISD is outside E4")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source_start_date"] = self.source_start_date.isoformat()
        payload["source_end_date"] = self.source_end_date.isoformat()
        payload["primary_test_family_size"] = 1
        payload["secondary_confirmatory_family_size"] = 13
        payload["mapping_pooling"] = False
        payload["future_completion_main_conditioning"] = False
        payload["event_cap"] = None
        payload["hard_category_one_possible"] = False
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
