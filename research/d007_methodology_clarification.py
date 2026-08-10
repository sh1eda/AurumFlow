"""Outcome-blind D007 methodology clarification helpers and registries.

This module contains no market-data loader, outcome calculation, inference,
adequacy evaluation, report writer, or historical execution surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Iterable

import pandas as pd


ADDENDUM_ID = "D007_METHODOLOGY_CLARIFICATION_V1"
ADDENDUM_PATH = Path("docs/D007_METHODOLOGY_CLARIFICATION.md")
ADDENDUM_SHA256 = "b5637a24ce9cb97c35e68636d17fe2359396397422652d1ff5b2d3c2811f087b"
NEW_YORK_TIMEZONE = "America/New_York"
NAMED_DATE_ROLLOVER_HOUR = 18
VALIDATION_YEARS = (2022, 2023, 2024, 2025)
SOURCE_TERMINAL_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
PRIMARY_D006_DEFINITION = "single_wick_50_d3_v1"
CONTROL_FAMILIES = (
    "matched_equilibrium_50",
    "matched_context_without_ote",
    "matched_displacement_availability",
)
INTERACTION_HYPOTHESES = (
    "aligned_d005_context",
    "after_d004_manipulation",
    "frozen_liquidity_sweep",
    "refinement_confirmation",
    "d006_rejection_block",
    "against_d005_context_negative_control",
)
GEOMETRY_HYPOTHESES = (
    "geometry_touch_incidence",
    "geometry_time_to_touch",
    "geometry_directional_movement",
)
REDUNDANCY_FEATURES = (
    "d005_displacement",
    "d005_displacement_strength",
    "body_close_mss",
    "refinement_array",
    "raw_fvg",
    "qualified_fvg",
    "liquidity_sweep",
    "d005_context",
    "d006_rejection_block",
    "equilibrium_position",
    "continuous_retracement_depth",
    "availability_to_touch_time",
)
REDUNDANCY_WINDOW_MINUTES = 60
MINIMUM_ABLATION_PAIRS = 200
BH_ADJUSTED_ALPHA = 0.05


@dataclass(frozen=True)
class ArtifactIdentity:
    milestone: str
    path: str
    sha256: str
    manifest_path: str | None
    manifest_sha256: str | None
    version_authority_path: str
    version_authority_sha256: str
    version: str
    schema_identity: str
    required_columns: tuple[str, ...]
    role: str


UPSTREAM_ARTIFACTS = (
    ArtifactIdentity(
        "D004",
        "research_outputs/D004_XAUUSD_0830_0900/daily_events.parquet",
        "43016a97f1f5ee00826eda52ee49fdb75e14c1eafcc93b5338cbd190248f6fd4",
        "research_outputs/D004_XAUUSD_0830_0900/artifact_manifest.json",
        "f50eafbea19638dd295e731d8a6334183698283eb8192b7b49bef26d46a98c98",
        "research_outputs/D004_XAUUSD_0830_0900/reproducibility_metadata.json",
        "c29fa7de14e51970ab51bc71f53c73d50ea470e8c1e6fc2d970273826a980133",
        "D004_XAUUSD_0830_0900:d003-v1:3ef1612c3ac73469e0b0",
        "research_outputs/D004_XAUUSD_0830_0900/daily_event_schema.json@b8980e89a579024ba43cc53228f1157453efdd0701a3714175a7ff0fc2f50d3c",
        (
            "trading_date",
            "high_sweep",
            "low_sweep",
            "high_reentry",
            "low_reentry",
            "high_reentry_time",
            "low_reentry_time",
        ),
        "after_d004_manipulation constituent and redundancy evidence",
    ),
    ArtifactIdentity(
        "D005-E1",
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/context_snapshots.parquet",
        "23f4fda9250b53c3fdf9d4227ac9f81a9a40c7258ebd179767c8cad72c157674",
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/artifact_manifest.json",
        "61d47faee0ae4c228afef9378e71da5bbec41594fb1a815492c0585b2103dbd0",
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/artifact_manifest.json",
        "61d47faee0ae4c228afef9378e71da5bbec41594fb1a815492c0585b2103dbd0",
        "D005-E1-v1:85541774f54e218c2052d6798c7c4d8bd24ab9ae4bb43f172eeef7fbfeda2cc7",
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/feature_schema.json@b2ed7fde6c960005388dcc027f6c6c20e82d88ee92e602c5adbd8508eb834330",
        (
            "snapshot_id",
            "evaluation_at",
            "mapping_name",
            "mapping_variant",
            "optional_1m_refinement",
            "parent_timeframe",
            "reaction_timeframe",
            "state",
            "direction",
            "evidence_ids",
        ),
        "reaction-confirmed context and negative-control constituents",
    ),
    ArtifactIdentity(
        "D005-E3",
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/anchor_events.parquet",
        "f516f41c60eab94da6c5fb48a124e9a37dc325715868ca3e0f56a56b60cc1373",
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/artifact_manifest.json",
        "535ecb2a7c9ddcd1802e0013302025404bfbd0996f3a6d6887a6e71672f1af92",
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/artifact_manifest.json",
        "535ecb2a7c9ddcd1802e0013302025404bfbd0996f3a6d6887a6e71672f1af92",
        "D005-E3-v1:f08e9116897f6d9b4fff6dc8449e9cddfa0fb96d077f2147149d7ca54d289b83",
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/feature_schema.json@fcd2efc15c4851a8e6a290190fad1af6a4d184134c9c99273577ff1eedaaab7d",
        (
            "anchor_id",
            "anchor_event_id",
            "anchor_type",
            "anchor_at",
            "direction",
            "anchor_price_basis",
            "anchor_price_override",
            "main_scope_eligible",
            "anchor_causally_observable",
            "anchor_selected_using_later_completion",
        ),
        "liquidity, MSS, FVG, refinement, and redundancy anchors",
    ),
    ArtifactIdentity(
        "D005-E4",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/eligible_sequences.parquet",
        "059e7053e46f753f5cede6714f2de5ea3a5a0ee47ae7d781cdd55d6af1c00b40",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/artifact_manifest.json",
        "f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/artifact_manifest.json",
        "f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445",
        "D005-E4-v1:34e044c602ca0e7aa5a467273e20538171b0363b6c72f6ed9415dc281d825880",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/feature_schema.json@993648cd2a026628d92936c7137a5670aa0b8d4fbf1a47ef9a6b8cc4f1fcdc7b",
        (
            "sequence_id",
            "mapping_variant",
            "direction",
            "main_scope_eligible",
            "anchor_causally_observable",
            "anchor_selected_using_later_completion",
            "candidate_id",
            "mss_id",
            "displacement_id",
            "displacement_created_at",
            "displacement_confirmation_event_id",
            "confirmation_event_available_at",
            "confirmation_event_direction",
        ),
        "primary upstream sequence and exact control-to-upstream association",
    ),
    ArtifactIdentity(
        "D005-E4",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/displacement_anchors.parquet",
        "d6a45058c11f32a7cb476d2ec578c50f53c017b080f3537002c1624049e42ce0",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/artifact_manifest.json",
        "f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/artifact_manifest.json",
        "f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445",
        "D005-E4-v1:34e044c602ca0e7aa5a467273e20538171b0363b6c72f6ed9415dc281d825880",
        "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/feature_schema.json@993648cd2a026628d92936c7137a5670aa0b8d4fbf1a47ef9a6b8cc4f1fcdc7b",
        (
            "sequence_id",
            "mapping_variant",
            "anchor_event_id",
            "anchor_at",
            "direction",
            "main_scope_eligible",
            "anchor_causally_observable",
            "anchor_selected_using_later_completion",
            "anchor_session",
            "anchor_year",
        ),
        "matched displacement-availability constituents",
    ),
    ArtifactIdentity(
        "D006",
        "research_outputs/D006_REJECTION_BLOCK_RESEARCH/structural_blocks.parquet",
        "3dbb0a64c46e8df52400b21f821739ba6cd74ed8797d6bd4d24a38034fa4451c",
        "research_outputs/D006_REJECTION_BLOCK_RESEARCH/artifact_manifest.json",
        "6973d0e2c5805c3e033f56727b13407db1d7a5455c89095d9ff3a4cca5082ff5",
        "research_outputs/D006_REJECTION_BLOCK_RESEARCH/run_manifest.json",
        "6ac0befd5c98a562fec745aa9dc2af10817d4943af7f633194b23ccf5fed9d98",
        "d006-v1:5d5ed7f803e2bb648345100edccac038e3a16fa1651a84b1fbcbf617d1ea4b0a",
        "research/d006_rejection_block_research/schemas.py@7dab75f08b2eb9ce8727cf04299a365966882b23ad463f2dfed75e62b91cfdea",
        (
            "block_id",
            "definition_name",
            "direction",
            "causal_availability",
            "range",
            "lifecycle_state",
            "first_touch_timestamp",
            "mitigation_timestamp",
            "invalidation_timestamp",
            "expiry_timestamp",
            "expiry_deadline",
            "overlap_group_id",
            "parent_block_id",
            "preavailability_interaction",
        ),
        "descriptive-only rejection-block interaction and redundancy evidence",
    ),
)


@dataclass(frozen=True)
class HypothesisSpec:
    hypothesis_id: str
    analysis_unit: str
    estimand: str
    test: str
    sidedness: str
    family: str
    minimum_n: int
    decision_role: str


HYPOTHESIS_SPECS = (
    HypothesisSpec("geometry_touch_incidence", "eligible upstream event with both fixed geometries", "paired band-minus-0.705 touch probability", "exact McNemar/binomial discordance test", "two-sided", "geometry", 200, "geometry access benefit"),
    HypothesisSpec("geometry_time_to_touch", "upstream event touched by both geometries", "mean 0.705-minus-band elapsed minutes", "paired Student t", "two-sided", "geometry", 200, "geometry access benefit"),
    HypothesisSpec("geometry_directional_movement", "upstream event touched by both geometries with complete endpoints", "mean band-minus-0.705 direction-aligned movement", "paired Student t", "two-sided", "geometry", 200, "zero-margin non-inferiority guard"),
    HypothesisSpec("aligned_d005_context", "matched OTE-plus-context/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 200, "confirmatory positive"),
    HypothesisSpec("after_d004_manipulation", "matched OTE-plus-D004/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 100, "exploratory only"),
    HypothesisSpec("frozen_liquidity_sweep", "matched OTE-plus-sweep/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 200, "confirmatory positive"),
    HypothesisSpec("refinement_confirmation", "matched OTE-plus-refinement/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 200, "confirmatory positive"),
    HypothesisSpec("d006_rejection_block", "matched OTE-plus-D006/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 100, "exploratory descriptive only"),
    HypothesisSpec("against_d005_context_negative_control", "matched OTE-against-context/constituent-only pair", "mean paired movement difference", "paired Student t", "two-sided", "interactions", 200, "negative-control diagnostic"),
)


def _utc(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tz is None:
        raise ValueError("timestamp must be timezone-aware")
    return stamp.tz_convert("UTC")


def _require_five_minute_grid(stamp: pd.Timestamp) -> None:
    if stamp.second or stamp.microsecond or stamp.nanosecond or stamp.minute % 5:
        raise ValueError("timestamp must align to the frozen five-minute grid")


def named_trading_date(value: object) -> date:
    """Return the D007 18:00-to-17:59:59.999... New York named date."""

    local = _utc(value).tz_convert(NEW_YORK_TIMEZONE)
    named = local.date()
    if local.hour >= NAMED_DATE_ROLLOVER_HOUR:
        named += pd.Timedelta(days=1)
    return named


def endpoint_named_years(event_at: object) -> tuple[int, ...]:
    event = _utc(event_at)
    _require_five_minute_grid(event)
    stamps = tuple(event + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5))
    return tuple(named_trading_date(stamp).year for stamp in stamps)


def endpoint_is_registered(event_at: object) -> bool:
    event = _utc(event_at)
    _require_five_minute_grid(event)
    required = tuple(event + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5))
    return bool(
        all(named_trading_date(stamp).year in VALIDATION_YEARS for stamp in required)
        and all(stamp < SOURCE_TERMINAL_EXCLUSIVE for stamp in required)
    )


@dataclass(frozen=True)
class MatchedObservation:
    observation_id: str
    event_at: pd.Timestamp
    upstream_event_ids: tuple[str, ...]
    session: str
    direction: int
    volatility_bucket: str
    elapsed_bucket: str
    endpoint_complete: bool = True
    own_ote_touched_at_event: bool = False
    nearest_unrelated_ote_touch_minutes: float | None = None
    upstream_mapping: str = "1h_5m"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_at", _utc(self.event_at))
        _require_five_minute_grid(self.event_at)
        if not self.observation_id:
            raise ValueError("observation ID is required")
        if isinstance(self.direction, bool) or self.direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        if self.session not in {"asia", "premarket", "ny_observation", "ny_afternoon", "maintenance"}:
            raise ValueError("session is outside the frozen D005 vocabulary")
        if self.volatility_bucket not in {"low", "normal", "high", "unavailable"}:
            raise ValueError("volatility bucket is outside the frozen vocabulary")
        if self.elapsed_bucket not in {"0_to_30", "30_to_60", "60_to_180", "180_to_1440"}:
            raise ValueError("elapsed bucket is outside the frozen vocabulary")
        if self.upstream_mapping != "1h_5m":
            raise ValueError("upstream mapping is outside D007 primary")
        if not isinstance(self.endpoint_complete, bool) or not isinstance(
            self.own_ote_touched_at_event, bool
        ):
            raise ValueError("completeness/touch flags must be boolean")
        if self.nearest_unrelated_ote_touch_minutes is not None and (
            not math.isfinite(self.nearest_unrelated_ote_touch_minutes)
            or self.nearest_unrelated_ote_touch_minutes < 0
        ):
            raise ValueError("OTE separation must be finite and non-negative")
        if any(not item for item in self.upstream_event_ids):
            raise ValueError("upstream event IDs must be nonempty")

    @property
    def named_date(self) -> date:
        return named_trading_date(self.event_at)

    @property
    def validation_year(self) -> int:
        return self.named_date.year


def control_is_eligible(treatment: MatchedObservation, candidate: MatchedObservation) -> bool:
    if len(treatment.upstream_event_ids) != 1 or len(candidate.upstream_event_ids) != 1:
        return False
    if treatment.upstream_event_ids[0] == candidate.upstream_event_ids[0]:
        return False
    if treatment.named_date == candidate.named_date:
        return False
    if abs((candidate.named_date - treatment.named_date).days) > 30:
        return False
    if treatment.validation_year not in VALIDATION_YEARS or candidate.validation_year != treatment.validation_year:
        return False
    if not candidate.endpoint_complete or candidate.own_ote_touched_at_event:
        return False
    if (
        candidate.nearest_unrelated_ote_touch_minutes is not None
        and candidate.nearest_unrelated_ote_touch_minutes < 120
    ):
        return False
    return (
        candidate.session == treatment.session
        and candidate.direction == treatment.direction
        and candidate.volatility_bucket == treatment.volatility_bucket
        and candidate.elapsed_bucket == treatment.elapsed_bucket
    )


def match_without_replacement(
    treatments: Iterable[MatchedObservation],
    candidates: Iterable[MatchedObservation],
    family: str,
) -> tuple[tuple[str, str | None], ...]:
    registered_families = set(CONTROL_FAMILIES) | {
        f"interaction:{item}" for item in INTERACTION_HYPOTHESES
    }
    if family not in registered_families:
        raise ValueError("unregistered control family")
    ordered_treatments = tuple(treatments)
    ordered_candidates = tuple(candidates)
    treatment_ids = [item.observation_id for item in ordered_treatments]
    candidate_ids = [item.observation_id for item in ordered_candidates]
    if len(treatment_ids) != len(set(treatment_ids)) or len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("duplicate stable observation ID")
    if set(treatment_ids) & set(candidate_ids):
        raise ValueError("treatment and candidate IDs must be disjoint")
    ordered_candidates = tuple(sorted(ordered_candidates, key=lambda item: (item.event_at, item.observation_id)))
    used: set[str] = set()
    rows: list[tuple[str, str | None]] = []
    for treatment in sorted(ordered_treatments, key=lambda item: (item.event_at, item.observation_id)):
        eligible = [
            item
            for item in ordered_candidates
            if item.observation_id not in used and control_is_eligible(treatment, item)
        ]
        if not eligible:
            rows.append((treatment.observation_id, None))
            continue
        selected = min(
            eligible,
            key=lambda item: (
                sha256(
                    f"7007|{family}|{treatment.observation_id}|{item.event_at.isoformat()}".encode()
                ).hexdigest(),
                item.observation_id,
            ),
        )
        used.add(selected.observation_id)
        rows.append((treatment.observation_id, selected.observation_id))
    return tuple(rows)


@dataclass(frozen=True)
class D006BlockEvidence:
    block_id: str
    definition_name: str
    direction: int
    causal_availability: pd.Timestamp
    range_size: float
    lifecycle_state: str
    first_touch_at: pd.Timestamp | None
    expiry_deadline: pd.Timestamp
    mitigation_at: pd.Timestamp | None = None
    invalidation_at: pd.Timestamp | None = None
    expiry_at: pd.Timestamp | None = None
    preavailability_interaction: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "causal_availability", _utc(self.causal_availability))
        object.__setattr__(self, "expiry_deadline", _utc(self.expiry_deadline))
        for name in ("first_touch_at", "mitigation_at", "invalidation_at", "expiry_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _utc(value))
        if not isinstance(self.block_id, str) or not self.block_id.strip():
            raise ValueError("D006 block ID is required")
        if isinstance(self.direction, bool) or self.direction not in (-1, 1):
            raise ValueError("D006 direction must be -1 or 1")
        if isinstance(self.range_size, bool) or not math.isfinite(self.range_size) or self.range_size <= 0:
            raise ValueError("D006 range must be finite and positive")
        if not isinstance(self.preavailability_interaction, bool):
            raise ValueError("D006 preavailability flag must be boolean")
        if self.lifecycle_state not in {
            "ACTIVE_UNTOUCHED", "ACTIVE_TOUCHED", "MITIGATED", "INVALIDATED", "EXPIRED"
        }:
            raise ValueError("unknown D006 lifecycle state")
        if self.expiry_deadline != self.causal_availability + pd.Timedelta(hours=24):
            raise ValueError("D006 expiry deadline must equal availability plus 24 hours")
        if self.first_touch_at is not None and not (
            self.causal_availability < self.first_touch_at < self.expiry_deadline
        ):
            raise ValueError("D006 first touch must be after availability and before expiry")
        for value in (self.mitigation_at, self.invalidation_at, self.expiry_at):
            if value is not None and not (self.causal_availability < value <= self.expiry_deadline):
                raise ValueError("D006 terminal timestamp is outside its lifecycle")
        if self.expiry_at is not None and self.expiry_at != self.expiry_deadline:
            raise ValueError("D006 expiry timestamp must equal its deadline")
        terminal_states = tuple(
            name
            for name, value in (
                ("MITIGATED", self.mitigation_at),
                ("INVALIDATED", self.invalidation_at),
                ("EXPIRED", self.expiry_at),
            )
            if value is not None
        )
        if len(terminal_states) > 1:
            raise ValueError("D006 lifecycle cannot have multiple terminal timestamps")
        terminal_at = next(
            (
                value
                for value in (self.mitigation_at, self.invalidation_at, self.expiry_at)
                if value is not None
            ),
            None,
        )
        if self.mitigation_at is not None and self.first_touch_at is None:
            raise ValueError("D006 mitigation requires a first touch")
        if self.first_touch_at is not None and terminal_at is not None and self.first_touch_at > terminal_at:
            raise ValueError("D006 first touch cannot follow a terminal timestamp")
        expected_state = (
            terminal_states[0]
            if terminal_states
            else "ACTIVE_TOUCHED"
            if self.first_touch_at is not None
            else "ACTIVE_UNTOUCHED"
        )
        if self.lifecycle_state != expected_state:
            raise ValueError("D006 lifecycle state/timestamp mismatch")


def d006_block_is_active_at(block: D006BlockEvidence, at: object, direction: int) -> bool:
    event = _utc(at)
    if (
        block.definition_name != PRIMARY_D006_DEFINITION
        or block.direction != direction
        or block.preavailability_interaction
        or block.causal_availability > event
        or block.causal_availability < event - pd.Timedelta(hours=24)
        or event >= block.expiry_deadline
        or block.first_touch_at is None
        or block.first_touch_at > event
    ):
        return False
    terminal = tuple(
        stamp for stamp in (block.mitigation_at, block.invalidation_at, block.expiry_at) if stamp is not None
    )
    return not terminal or min(terminal) > event


def select_d006_block(
    blocks: Iterable[D006BlockEvidence], at: object, direction: int
) -> D006BlockEvidence | None:
    eligible = [block for block in blocks if d006_block_is_active_at(block, at, direction)]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda block: (-block.causal_availability.value, block.range_size, block.block_id),
    )


@dataclass(frozen=True)
class TimedEvidence:
    evidence_id: str
    available_at: pd.Timestamp
    direction: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_at", _utc(self.available_at))
        if not self.evidence_id:
            raise ValueError("evidence ID is required")
        if isinstance(self.direction, bool) or self.direction not in (-1, 1):
            raise ValueError("evidence direction must be -1 or 1")


def select_latest_unambiguous(
    evidence: Iterable[TimedEvidence], at: object, *, strict: bool = False
) -> TimedEvidence | None:
    deadline = _utc(at)
    if strict:
        candidates = [item for item in evidence if item.available_at < deadline]
    else:
        candidates = [item for item in evidence if item.available_at <= deadline]
    if not candidates:
        return None
    if len({item.evidence_id for item in candidates}) != len(candidates):
        return None
    latest_at = max(item.available_at for item in candidates)
    latest = [item for item in candidates if item.available_at == latest_at]
    if len({item.direction for item in latest}) != 1:
        return None
    return min(latest, key=lambda item: item.evidence_id)


def redundancy_associated(feature_at: object, reference_at: object) -> bool:
    delta = (_utc(feature_at) - _utc(reference_at)).total_seconds() / 60.0
    return -REDUNDANCY_WINDOW_MINUTES <= delta <= REDUNDANCY_WINDOW_MINUTES


def structural_overlap_status(overlap_count: int, denominator: int) -> str:
    if denominator <= 0 or overlap_count < 0 or overlap_count > denominator:
        raise ValueError("invalid structural-overlap count/denominator")
    return "FULL_STRUCTURAL_OVERLAP" if overlap_count == denominator else "NOT_FULL_STRUCTURAL_OVERLAP"


def ablation_status(
    *,
    n: int,
    mean_difference: float,
    t_interval_lower: float,
    t_interval_upper: float,
    bootstrap_lower: float,
    q_value: float,
    stable: bool,
) -> str:
    values = (mean_difference, t_interval_lower, t_interval_upper, bootstrap_lower, q_value)
    if n < MINIMUM_ABLATION_PAIRS or not all(math.isfinite(value) for value in values):
        return "INCONCLUSIVE"
    if (
        mean_difference > 0
        and t_interval_lower > 0
        and bootstrap_lower > 0
        and q_value <= BH_ADJUSTED_ALPHA
        and stable
    ):
        return "NON_REDUNDANT"
    if t_interval_upper <= 0:
        return "FULLY_ACCOUNTED"
    return "INCONCLUSIVE"


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _safe_dependency_path(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe D007 clarification dependency path: {relative}")
    root = root.resolve()
    cursor = root
    for part in relative_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"missing or unsafe D007 clarification dependency: {relative}")
    if not cursor.is_file() or root not in cursor.resolve().parents:
        raise ValueError(f"missing or unsafe D007 clarification dependency: {relative}")
    return cursor


def _manifest_record(identity: ArtifactIdentity, root: Path) -> dict[str, object]:
    if identity.manifest_path is None:
        raise ValueError(f"missing manifest identity for {identity.path}")
    payload = json.loads(_safe_dependency_path(root, identity.manifest_path).read_text(encoding="utf-8"))
    records = payload.get("files", payload.get("artifacts"))
    if not isinstance(records, list):
        raise ValueError(f"invalid upstream manifest records: {identity.manifest_path}")
    matches = [item for item in records if isinstance(item, dict) and item.get("path") == Path(identity.path).name]
    if len(matches) != 1:
        raise ValueError(f"missing or duplicate upstream manifest record: {identity.path}")
    return matches[0]


def _verify_version_authority(identity: ArtifactIdentity, root: Path) -> None:
    payload = json.loads(
        _safe_dependency_path(root, identity.version_authority_path).read_text(encoding="utf-8")
    )
    version, fingerprint = identity.version.split(":", 1)
    if identity.milestone == "D004":
        dataset_version, dataset_id = fingerprint.split(":", 1)
        canonical = payload.get("canonical_dataset", {})
        if payload.get("research_id") != "D004" or canonical.get("dataset_version") != dataset_version or canonical.get("dataset_id") != dataset_id:
            raise ValueError("D004 version authority mismatch")
    elif identity.milestone.startswith("D005"):
        if payload.get("version") != version or payload.get("study_config_fingerprint") != fingerprint:
            raise ValueError(f"{identity.milestone} version authority mismatch")
    elif identity.milestone == "D006":
        if payload.get("version") != version or payload.get("structural_fingerprint") != fingerprint:
            raise ValueError("D006 version authority mismatch")


def verify_upstream_identities(root: Path) -> dict[str, str]:
    """Hash registered artifacts only; no Parquet row is decoded."""

    import pyarrow.parquet as pq

    artifact_paths = [identity.path for identity in UPSTREAM_ARTIFACTS]
    if len(artifact_paths) != len(set(artifact_paths)):
        raise ValueError("duplicate upstream artifact identity")
    expected: dict[str, str] = {}
    for identity in UPSTREAM_ARTIFACTS:
        expected[identity.path] = identity.sha256
        if identity.manifest_path and identity.manifest_sha256:
            expected[identity.manifest_path] = identity.manifest_sha256
        expected[identity.version_authority_path] = identity.version_authority_sha256
        schema_path, schema_hash = identity.schema_identity.split("@", 1)
        expected[schema_path] = schema_hash
    observed: dict[str, str] = {}
    for relative, digest in sorted(expected.items()):
        path = _safe_dependency_path(root, relative)
        actual = file_sha256(path)
        if actual != digest:
            raise ValueError(f"D007 clarification dependency drift: {relative}")
        observed[relative] = actual
    for identity in UPSTREAM_ARTIFACTS:
        artifact = _safe_dependency_path(root, identity.path)
        record = _manifest_record(identity, root)
        recorded_bytes = record.get("byte_size", record.get("bytes"))
        if record.get("sha256") != identity.sha256 or recorded_bytes != artifact.stat().st_size:
            raise ValueError(f"upstream manifest record mismatch: {identity.path}")
        columns = set(pq.ParquetFile(artifact).schema_arrow.names)
        missing = set(identity.required_columns) - columns
        if missing:
            raise ValueError(f"upstream projected schema mismatch: {identity.path}: {sorted(missing)}")
        _verify_version_authority(identity, root)
    return observed


__all__ = [
    "ADDENDUM_ID",
    "ADDENDUM_PATH",
    "ADDENDUM_SHA256",
    "ablation_status",
    "CONTROL_FAMILIES",
    "D006BlockEvidence",
    "GEOMETRY_HYPOTHESES",
    "HYPOTHESIS_SPECS",
    "INTERACTION_HYPOTHESES",
    "MatchedObservation",
    "REDUNDANCY_FEATURES",
    "TimedEvidence",
    "UPSTREAM_ARTIFACTS",
    "control_is_eligible",
    "d006_block_is_active_at",
    "endpoint_is_registered",
    "endpoint_named_years",
    "match_without_replacement",
    "named_trading_date",
    "redundancy_associated",
    "select_d006_block",
    "select_latest_unambiguous",
    "structural_overlap_status",
    "verify_upstream_identities",
]
