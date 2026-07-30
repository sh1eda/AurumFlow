"""Frozen configuration for the D005_E2 diagnostic."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from zoneinfo import ZoneInfo

from research.context_engine.config import NEW_YORK
from research.d005_e1_context_engine_empirical.config import (
    DEFAULT_MAPPING_VARIANTS,
    MappingVariant,
)


@dataclass(frozen=True)
class ReactionAnchorDiagnosticConfig:
    study_id: str = "D005_E2_REACTION_ANCHOR_DIAGNOSTIC"
    version: str = "D005-E2-v1"
    timezone: str = NEW_YORK
    start_date: date = date(2021, 1, 3)
    end_date: date = date(2025, 12, 31)
    mapping_variants: tuple[MappingVariant, ...] = DEFAULT_MAPPING_VARIANTS
    forward_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)
    day_end_clock: str = "17:00"
    mfe_price_thresholds: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0)
    e1_output: str = (
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
    )
    d005_output: str = "research_outputs/D005_CONTEXT_ENGINE"
    technical_spec: str = (
        "docs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC_SPEC.md"
    )
    uncapped_event_limit: None = None
    deterministic_deduplication: bool = True
    production_entry_authorization: bool = False
    optimization: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "study_type": "causal_anchor_and_direction_diagnostic",
            "production_integration": False,
            "threshold_change": False,
            "state_logic_change": False,
            "canonical_ob_selection": False,
            "timing_signal": False,
        }
    )

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError("E2 must use America/New_York")
        if self.end_date < self.start_date:
            raise ValueError("end date precedes start date")
        if self.uncapped_event_limit is not None:
            raise ValueError("E2 uncapped reconstruction cannot set an event cap")
        if any(value <= 0 for value in self.forward_minutes):
            raise ValueError("forward horizons must be positive")
        if any(value <= 0 for value in self.mfe_price_thresholds):
            raise ValueError("MFE thresholds must be positive")
        if len(set(self.mfe_price_thresholds)) != len(
            self.mfe_price_thresholds
        ):
            raise ValueError("MFE thresholds must be unique")
        if self.production_entry_authorization:
            raise ValueError("E2 cannot authorize entries")
        if self.optimization:
            raise ValueError("E2 is not an optimization study")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["event_cap"] = None
        payload["price_outcome_semantics"] = "descriptive_not_pnl"
        payload["index_timing_transfer"] = False
        payload["pmh_pml_bias_override"] = False
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def mapping_variant(self, name: str) -> MappingVariant:
        return next(item for item in self.mapping_variants if item.name == name)

