"""Frozen preregistered configuration for D005_E3."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from zoneinfo import ZoneInfo

from research.context_engine.config import NEW_YORK, ORDER_BLOCK_VARIANTS
from research.d005_e1_context_engine_empirical.config import (
    DEFAULT_MAPPING_VARIANTS,
    MappingVariant,
)


PRIMARY_ANCHORS: tuple[str, ...] = (
    "candidate_context_creation",
    "mss_body_close_confirmation",
    "displacement_confirmation",
    "refinement_array_creation",
    "refinement_array_first_interaction",
    "reaction_confirmed",
)


@dataclass(frozen=True)
class EarlyContextAnchorStudyConfig:
    study_id: str = "D005_E3_EARLY_CONTEXT_ANCHOR_STUDY"
    version: str = "D005-E3-v1"
    timezone: str = NEW_YORK
    start_date: date = date(2021, 1, 3)
    end_date: date = date(2025, 12, 31)
    mapping_variants: tuple[MappingVariant, ...] = DEFAULT_MAPPING_VARIANTS
    primary_anchors: tuple[str, ...] = PRIMARY_ANCHORS
    primary_horizon: str = "60m"
    forward_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)
    day_end_clock: str = "17:00"
    bootstrap_resamples: int = 1000
    bootstrap_seed: int = 50053
    confidence_level: float = 0.95
    fdr_alpha: float = 0.05
    primary_minimum_sample: int = 100
    annual_minimum_sample: int = 15
    direction_minimum_sample: int = 25
    broad_minimum_mappings: int = 3
    retrospective_minimum_sample: int = 100
    retrospective_gap_price_units: float = 1.0
    volatility_lookback_days: int = 20
    low_volatility_ratio: float = 0.75
    high_volatility_ratio: float = 1.25
    ob_variants: tuple[str, ...] = ORDER_BLOCK_VARIANTS
    d005_output: str = "research_outputs/D005_CONTEXT_ENGINE"
    e1_output: str = (
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
    )
    e2_output: str = (
        "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC"
    )
    technical_spec: str = (
        "docs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY_SPEC.md"
    )
    production_entry_authorization: bool = False
    optimization: bool = False
    cisd_enabled: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "study_type": "causal_early_anchor_stability",
            "price_outcomes": "descriptive_not_pnl",
            "production_integration": False,
            "threshold_change": False,
            "state_logic_change": False,
            "mapping_selection": False,
            "canonical_ob_selection": False,
            "clock_promotion": False,
            "pmh_pml_promotion": False,
        }
    )

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError("E3 must use America/New_York")
        if self.end_date < self.start_date:
            raise ValueError("end date precedes start date")
        if self.forward_minutes != (5, 15, 30, 60, 120):
            raise ValueError("E3 forward horizons are frozen")
        if len(self.primary_anchors) != 6:
            raise ValueError("E3 must retain six primary anchors")
        if set(self.ob_variants) != set(ORDER_BLOCK_VARIANTS):
            raise ValueError("all independent OB variants are required")
        if self.bootstrap_resamples < 500:
            raise ValueError("bootstrap resamples must be at least 500")
        if not 0 < self.fdr_alpha <= 0.10:
            raise ValueError("FDR alpha is invalid")
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence level is invalid")
        if self.primary_minimum_sample < 30:
            raise ValueError("primary minimum sample is too small")
        if self.production_entry_authorization:
            raise ValueError("E3 cannot authorize entries")
        if self.optimization:
            raise ValueError("E3 is not an optimization study")
        if self.cisd_enabled:
            raise ValueError("CISD is outside the E3 primary study")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["registered_primary_comparisons"] = (
            len(self.primary_anchors)
            * len(self.mapping_variants)
            * 2
        )
        payload["primary_outcomes"] = ["reversal", "continuation"]
        payload["multiplicity_method"] = "benjamini_hochberg"
        payload["mapping_pooling"] = False
        payload["future_completion_main_conditioning"] = False
        payload["event_cap"] = None
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def mapping_variant(self, name: str) -> MappingVariant:
        return next(item for item in self.mapping_variants if item.name == name)
