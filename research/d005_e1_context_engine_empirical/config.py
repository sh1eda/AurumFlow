"""Frozen configuration for the D005_E1 descriptive study."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from zoneinfo import ZoneInfo

from research.context_engine.config import NEW_YORK


@dataclass(frozen=True)
class MappingVariant:
    name: str
    d005_mapping: str
    optional_1m_refinement: bool
    warmup_days: int


DEFAULT_MAPPING_VARIANTS: tuple[MappingVariant, ...] = (
    MappingVariant("weekly_4h_1h", "weekly_4h_1h", False, 180),
    MappingVariant("daily_1h_15m", "daily_1h_15m", False, 45),
    MappingVariant("4h_15m_5m", "4h_15m_5m", False, 20),
    MappingVariant("1h_5m", "1h_5m_1m", False, 8),
    MappingVariant("1h_5m_optional_1m", "1h_5m_1m", True, 8),
)


@dataclass(frozen=True)
class EmpiricalStudyConfig:
    study_id: str = "D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
    version: str = "D005-E1-v1"
    timezone: str = NEW_YORK
    start_date: date = date(2021, 1, 3)
    end_date: date = date(2025, 12, 31)
    fixed_clocks: tuple[str, ...] = ("08:30", "09:00", "10:00", "12:00")
    mapping_variants: tuple[MappingVariant, ...] = DEFAULT_MAPPING_VARIANTS
    forward_minutes: tuple[int, ...] = (15, 30, 60, 120)
    day_end_clock: str = "17:00"
    bootstrap_resamples: int = 1000
    bootstrap_seed: int = 50051
    volatility_lookback_days: int = 20
    low_volatility_ratio: float = 0.75
    high_volatility_ratio: float = 1.25
    event_refinement_lifetime_reaction_bars: int = 12
    event_schedule_max_per_day_mapping: int = 12
    parallel_workers: int = 5
    array_lifecycle_followup_days: int = 30
    event_snapshot_deduplication: bool = True
    d005_source_catalog: str = "research/context_engine/source_rule_catalog.json"
    technical_spec: str = (
        "docs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_SPEC.md"
    )
    production_entry_authorization: bool = False
    index_timing_transfer: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "study_type": "descriptive_forward_price_relevance",
            "optimization": False,
            "production_integration": False,
            "canonical_ob_selection": False,
        }
    )

    def validate(self) -> None:
        if self.timezone != NEW_YORK:
            raise ValueError("E1 must use America/New_York")
        ZoneInfo(self.timezone)
        if self.end_date < self.start_date:
            raise ValueError("end date precedes start date")
        if len(set(self.fixed_clocks)) != len(self.fixed_clocks):
            raise ValueError("fixed clocks must be unique")
        if len({item.name for item in self.mapping_variants}) != len(
            self.mapping_variants
        ):
            raise ValueError("mapping variant names must be unique")
        if any(item.warmup_days < 8 for item in self.mapping_variants):
            raise ValueError("mapping warm-up is too short")
        if any(value <= 0 for value in self.forward_minutes):
            raise ValueError("forward horizons must be positive")
        if self.bootstrap_resamples < 100:
            raise ValueError("bootstrap resamples must be at least 100")
        if self.parallel_workers < 1:
            raise ValueError("parallel workers must be positive")
        if self.event_schedule_max_per_day_mapping < 1:
            raise ValueError("event schedule daily cap must be positive")
        if not 0 < self.low_volatility_ratio < self.high_volatility_ratio:
            raise ValueError("volatility regime thresholds are invalid")
        if self.production_entry_authorization:
            raise ValueError("E1 cannot authorize production entries")
        if self.index_timing_transfer:
            raise ValueError("E1 cannot transfer index timing")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["clock_semantics"] = "observation_only"
        payload["pmh_pml_interval"] = {
            "start": "00:00",
            "end": "08:30",
            "timezone": NEW_YORK,
            "semantics": "[start,end)",
        }
        payload["d004_guardrail"] = (
            "08:30-09:00 New York has no robust standalone directional edge"
        )
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def mapping_variant(self, name: str) -> MappingVariant:
        return next(item for item in self.mapping_variants if item.name == name)
