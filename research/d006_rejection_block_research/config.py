"""Frozen, research-only configuration for the D006 structural package."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


UTC = timezone.utc
SPEC_PATH = Path("docs/D006_REJECTION_BLOCK_RESEARCH_SPEC.md")
SPEC_SHA256 = "c0c16fcc250204c2946c0525f600dc5ba4833163bf193d164175824c77948119"

PROTECTED_TRACKED_SHA256 = (
    ("docs/D005_STRATEGY_SOURCE_AUDIT.md", "b9fcbc36efb51ef2a77ef2bfa09dea1df092e007bf18f7d4240d274c0e47fddd"),
    ("research/context_engine/source_rule_catalog.json", "13e71c4a1cfea76c3124ef9473b8f426abae252421ae9c0c619b673a5b8e3d3e"),
    ("research/event_study_0830_0930/concept_definitions.md", "0f6d813243eb658138419d8f7664209de0b1ef192bca7a3c632f9fd141352176"),
    ("research/event_study_0830_0930/structures.py", "915e75a18c484daac25d2200a773bda688aa7975771695031094ff8abe42ce74"),
    ("research/context_engine/config.py", "3b86421d5292987df8d646b67ab198c4a7c8b0e620837bbe2139f1a69bf3084e"),
    ("research/context_engine/bars.py", "44756989dedd90379b70d0530d847bfc228654bf1a82e38b47b2d0e02bd17761"),
    ("research/context_engine/features.py", "018d3671452b626168d2e83d115a3f35a09491fa7a92c2bb6078ba67062f75e1"),
    ("research/context_engine/models.py", "56e7d189cb3a39e27e553fb946d0acfa9096d3719f384986515e4ecdfd62866b"),
    ("docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md", "704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b"),
    ("docs/D005_E5_REPORTING_HARDENING_SPEC.md", "440dcdb7edb344914a5a0dac43659b96ff48fe48dbee7827521084e93f503a15"),
    ("docs/D005_E6_FUTURE_BLIND_REPLICATION_SPEC.md", "1bba4d33adf8cefca81cd7b2cae1d9b3318494c49adb6de3fa1680928ec840fb"),
)

FROZEN_DATA_METADATA_SHA256 = (
    ("data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json", "a687c7acd95a6c4533528ab04a96373fc20000b826167ddd51bc57da34a2346d"),
    ("data/releases/d003-v2/canonical_manifest.json", "a687c7acd95a6c4533528ab04a96373fc20000b826167ddd51bc57da34a2346d"),
    ("data/releases/d003-v2/full_verification.json", "fbf0d909d60f9c906911d06aa21b5f125d4a68dbc2d65e444a559d89a1211efe"),
    ("data/releases/d003-v2/parquet_sha256.txt", "f7d941278428a5e7a2f6890a22bf76e9da2af120f419242b5ba817125354173f"),
    ("data/releases/d003-v2/release_sha256.txt", "dac7f92993882f989dc04321d2df969efc383c7924edab5bc9bc9ac41a3266df"),
)

FIXED_CONTROLS = (
    "matched_non_block",
    "matched_displacement_without_rb",
    "matched_context_without_rb",
    "matched_time_session_volatility",
    "direction_balanced",
    "random_time_placebo",
)

COMPONENT_DISPOSITIONS = (
    "REPRODUCIBILITY_DEFECT",
    "INSUFFICIENT_EVIDENCE",
    "NON_REDUNDANT_COMPONENT_CANDIDATE",
    "CONDITIONAL_CANDIDATE",
    "GEOMETRY_CANDIDATE",
    "REJECT_COMPONENT",
    "STRUCTURALLY_VALID_EMPIRICALLY_WEAK",
)


@dataclass(frozen=True)
class DefinitionProfile:
    """A pre-registered rejection-bar grouping, not a tunable parameter set."""

    name: str
    rejection_bar_count: int


@dataclass(frozen=True)
class InteractionSpec:
    """A pre-registered contextual comparison, never a discovered interaction."""

    name: str
    eligibility: str
    timing: str
    direction: str
    context: str
    minimum_sample: int
    classification: str


@dataclass(frozen=True)
class ControlSpec:
    """A deterministic causal control population and frozen matcher contract."""

    name: str
    population: str
    event_timestamp: str
    exact_strata: str
    candidate_window: str
    exclusions: str
    selection: str
    role: str


@dataclass(frozen=True)
class MultipleTestingFamily:
    name: str
    hypotheses: int
    adjustment: str
    q: float = 0.05


FIXED_INTERACTIONS = (
    InteractionSpec("rb_alone", "lifecycle-eligible blocks with a first causal touch", "at first causal touch", "block direction", "none", 500, "confirmatory"),
    InteractionSpec("aligned_d005_context", "latest D005 reaction_confirmed snapshot with all evidence available", "at or before block availability", "exact agreement", "D005 context direction", 200, "confirmatory"),
    InteractionSpec("after_d004_manipulation", "causal D004 sweep-reentry state completed on the same named trading date", "strictly before block availability", "exact agreement with D004 reaction", "D004 manipulation state; retrospective day labels forbidden", 100, "exploratory"),
    InteractionSpec("frozen_liquidity_sweep", "latest frozen liquidity-sweep evidence not already invalidated", "available no later than block availability", "exact agreement", "frozen D005 liquidity-sweep state", 200, "confirmatory"),
    InteractionSpec("displacement_confirmation", "distinct frozen D005 displacement; D006 expansion cannot self-satisfy", "within 60 minutes at or before block availability", "exact agreement", "frozen D005 displacement confirmation", 200, "confirmatory"),
    InteractionSpec("refinement_confirmation", "frozen D005 refinement-array creation or confirmation", "available no later than first touch", "exact agreement", "frozen D005 refinement state", 200, "confirmatory"),
    InteractionSpec("against_d005_context_negative_control", "latest non-neutral D005 reaction_confirmed snapshot", "at or before block availability", "exact disagreement", "D005 context direction", 200, "negative_control"),
)
FIXED_CONTROLS_REGISTRY = (
    ControlSpec("matched_non_block", "complete five-minute candle with no active or touched rejection block", "candle available_at", "validation year; D005 session; direction; causal volatility bucket", "plus or minus 30 calendar days", "different named trading date; no RB availability/touch within 120 minutes; endpoint complete", "without replacement; lowest SHA-256 of seed 6006, family, treatment block ID, candidate timestamp", "primary"),
    ControlSpec("matched_displacement_without_rb", "distinct frozen D005 displacement confirmation with no active or touched rejection block", "frozen displacement causal timestamp", "validation year; D005 session; direction; causal volatility bucket", "plus or minus 30 calendar days", "different named trading date; no RB availability/touch within 120 minutes; endpoint complete", "without replacement; same fixed SHA-256 rule", "incremental_secondary"),
    ControlSpec("matched_context_without_rb", "frozen D005 reaction_confirmed snapshot with no active or touched rejection block", "snapshot evaluation timestamp", "validation year; D005 session; direction; causal volatility bucket", "plus or minus 30 calendar days", "different named trading date; no RB availability/touch within 120 minutes; endpoint complete", "without replacement; same fixed SHA-256 rule", "incremental_secondary"),
    ControlSpec("matched_time_session_volatility", "audit view of primary eligible non-block controls", "candle available_at", "validation year; D005 session; direction; causal volatility bucket", "plus or minus 30 calendar days", "same exclusions as primary", "same selected primary pairs", "audit"),
    ControlSpec("direction_balanced", "primary matched cohort reweighted to exact bullish/bearish balance", "unchanged primary timestamps", "direction", "none", "cannot change primary paired sample", "deterministic equal-direction weights", "audit"),
    ControlSpec("random_time_placebo", "eligible non-event time", "candle available_at", "validation year; D005 session; direction; causal volatility bucket", "plus or minus 30 calendar days", "different named trading date; no RB availability/touch within 120 minutes; endpoint complete", "one per treatment without replacement; same fixed SHA-256 rule", "incremental_secondary"),
)
FIXED_MULTIPLE_TESTING = (
    MultipleTestingFamily("primary", 1, "unadjusted"),
    MultipleTestingFamily("definition_sensitivity", 1, "BH"),
    MultipleTestingFamily("interactions", 6, "BH"),
    MultipleTestingFamily("incremental_controls", 4, "BH"),
    MultipleTestingFamily("geometry", 10, "BH"),
)

@dataclass(frozen=True)
class D006Config:
    """All D006 constants are fixed to prevent an implicit parameter search."""

    version: str = "d006-v1"
    research_only: bool = True
    production_authorized: bool = False
    outcome_authorized: bool = False
    output_authorized: bool = False
    source_start: datetime = datetime(2021, 1, 1, tzinfo=UTC)
    source_end: datetime = datetime(2026, 1, 1, tzinfo=UTC)
    calibration_year: int = 2021
    validation_years: tuple[int, ...] = (2022, 2023, 2024, 2025)
    endpoint_buffer_minutes: int = 120
    primary_horizon_minutes: int = 60
    primary_definition: str = "single_wick_50_d3_v1"
    primary_reference: str = "first_touch_bar_close"
    minimum_segment_completeness: float = 0.95
    control_window_days: int = 30
    control_exclusion_minutes: int = 120
    volatility_median_days: int = 20
    volatility_bucket_boundaries: tuple[float, float] = (0.75, 1.25)
    control_hash_seed: int = 6006
    final_holdout: bool = False
    timeframe: str = "5min"
    bar_minutes: int = 5
    atr_period: int = 14
    atr_min_periods: int = 10
    wick_fraction_minimum: float = 0.50
    swing_left_lookback: int = 2
    candidate_tr_to_prior_atr_minimum: float = 1.0
    confirmation_bars: int = 3
    confirmation_body_fraction_minimum: float = 0.60
    confirmation_tr_to_prior_atr_minimum: float = 1.25
    lifecycle_expiry_hours: int = 24
    confidence_level: float = 0.95
    bootstrap_resamples: int = 2000
    bootstrap_seed: int = 6006
    fdr_alpha: float = 0.05
    minimum_detected: int = 1000
    minimum_per_direction: int = 200
    minimum_lifecycle_eligible: int = 800
    minimum_touched: int = 500
    minimum_untouched_when_compared: int = 200
    minimum_primary_pairs: int = 500
    minimum_primary_pairs_per_year: int = 100
    minimum_required_session_touches: int = 50
    minimum_geometry_cohort: int = 200
    minimum_geometry_retention: float = 0.60
    endpoint_coverage_required: bool = True
    required_sessions: tuple[str, ...] = (
        "asia",
        "premarket",
        "ny_observation",
        "ny_afternoon",
    )
    source_columns: tuple[str, ...] = (
        "timestamp_utc",
        "bid",
        "ask",
        "bid_volume",
        "ask_volume",
        "mid",
        "spread",
        "symbol",
        "source_partition",
    )
    controls: tuple[str, ...] = FIXED_CONTROLS
    control_registry: tuple[ControlSpec, ...] = FIXED_CONTROLS_REGISTRY
    component_dispositions: tuple[str, ...] = COMPONENT_DISPOSITIONS
    protected_tracked_sha256: tuple[tuple[str, str], ...] = PROTECTED_TRACKED_SHA256
    frozen_data_metadata_sha256: tuple[tuple[str, str], ...] = FROZEN_DATA_METADATA_SHA256
    definitions: tuple[DefinitionProfile, ...] = field(
        default=(
            DefinitionProfile("single_wick_50_d3_v1", 1),
            DefinitionProfile("cluster2_wick_50_d3_v1", 2),
        )
    )
    interactions: tuple[InteractionSpec, ...] = FIXED_INTERACTIONS
    multiple_testing: tuple[MultipleTestingFamily, ...] = FIXED_MULTIPLE_TESTING

    def __post_init__(self) -> None:
        if self.version != "d006-v1":
            raise ValueError("D006 version is fixed")
        if self.source_start.tzinfo != UTC or self.source_end.tzinfo != UTC:
            raise ValueError("D006 interval metadata must be explicit UTC")
        if self.timeframe != "5min" or self.bar_minutes != 5:
            raise ValueError("D006 permits only exact five-minute bars")
        if self.research_only is not True or any(
            (self.production_authorized, self.outcome_authorized, self.output_authorized)
        ):
            raise ValueError("D006 is research-only with no production, outcome, or output authority")
        if (
            self.source_start != datetime(2021, 1, 1, tzinfo=UTC)
            or self.source_end != datetime(2026, 1, 1, tzinfo=UTC)
            or self.calibration_year != 2021
            or self.validation_years != (2022, 2023, 2024, 2025)
            or self.endpoint_buffer_minutes != 120
            or self.primary_horizon_minutes != 60
            or self.primary_definition != "single_wick_50_d3_v1"
            or self.primary_reference != "first_touch_bar_close"
            or self.minimum_segment_completeness != 0.95
            or self.control_window_days != 30
            or self.control_exclusion_minutes != 120
            or self.volatility_median_days != 20
            or self.volatility_bucket_boundaries != (0.75, 1.25)
            or self.control_hash_seed != 6006
            or self.final_holdout
        ):
            raise ValueError("D006 historical intervals are fixed and exclude 2026")
        if (
            self.atr_period,
            self.atr_min_periods,
            self.wick_fraction_minimum,
            self.swing_left_lookback,
            self.candidate_tr_to_prior_atr_minimum,
            self.confirmation_bars,
            self.confirmation_body_fraction_minimum,
            self.confirmation_tr_to_prior_atr_minimum,
            self.lifecycle_expiry_hours,
        ) != (14, 10, 0.50, 2, 1.0, 3, 0.60, 1.25, 24):
            raise ValueError("D006 rejection-block parameters are fixed without a grid")
        expected = (
            DefinitionProfile("single_wick_50_d3_v1", 1),
            DefinitionProfile("cluster2_wick_50_d3_v1", 2),
        )
        if self.definitions != expected:
            raise ValueError("D006 definition family is fixed and has no grid")
        if self.interactions != FIXED_INTERACTIONS or self.multiple_testing != FIXED_MULTIPLE_TESTING:
            raise ValueError("D006 interactions and multiple-testing families are fixed")
        if (
            self.controls != FIXED_CONTROLS
            or self.control_registry != FIXED_CONTROLS_REGISTRY
            or tuple(item.name for item in self.control_registry) != self.controls
            or self.component_dispositions != COMPONENT_DISPOSITIONS
        ):
            raise ValueError("D006 controls and component dispositions are fixed")
        if self.required_sessions != (
            "asia",
            "premarket",
            "ny_observation",
            "ny_afternoon",
        ) or self.source_columns != (
            "timestamp_utc",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
            "mid",
            "spread",
            "symbol",
            "source_partition",
        ):
            raise ValueError("D006 sessions and source contract are fixed")
        if (
            self.minimum_detected,
            self.minimum_per_direction,
            self.minimum_lifecycle_eligible,
            self.minimum_touched,
            self.minimum_untouched_when_compared,
            self.minimum_primary_pairs,
            self.minimum_primary_pairs_per_year,
            self.minimum_required_session_touches,
            self.minimum_geometry_cohort,
            self.minimum_geometry_retention,
            self.endpoint_coverage_required,
        ) != (1000, 200, 800, 500, 200, 500, 100, 50, 200, 0.60, True):
            raise ValueError("D006 sample-adequacy thresholds are fixed")
        if (
            self.bootstrap_resamples != 2000
            or self.bootstrap_seed != 6006
            or self.confidence_level != 0.95
            or self.fdr_alpha != 0.05
        ):
            raise ValueError("D006 statistical conventions are fixed")
        if self.protected_tracked_sha256 != PROTECTED_TRACKED_SHA256:
            raise ValueError("D006 tracked provenance fingerprints are fixed")
        if self.frozen_data_metadata_sha256 != FROZEN_DATA_METADATA_SHA256:
            raise ValueError("D006 data metadata fingerprints are fixed")


def config_fingerprint(config: D006Config = D006Config()) -> str:
    """Return a stable fingerprint of the entire fixed configuration."""

    payload = {"config": asdict(config), "spec_sha256": SPEC_SHA256}
    encoded = json.dumps(payload, default=lambda value: value.isoformat(), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()
