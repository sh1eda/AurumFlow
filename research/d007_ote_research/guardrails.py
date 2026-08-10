"""Outcome-blind controls, interaction timing, adequacy, and disposition rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import math
from typing import Iterable, Mapping

import pandas as pd

from .config import (
    COMPONENT_DISPOSITIONS,
    D007Config,
    FIXED_CONTROLS,
    FIXED_INTERACTIONS,
)
from .models import Direction, OTERange
from research.d007_methodology_clarification import named_trading_date


CONTROL_SESSIONS = (
    "asia",
    "premarket",
    "ny_observation",
    "ny_afternoon",
    "maintenance",
)
VOLATILITY_BUCKETS = ("low", "normal", "high", "unavailable")
ELAPSED_EVENT_BUCKETS = ("0_to_30", "30_to_60", "60_to_180", "180_to_1440")


@dataclass(frozen=True)
class ControlCandidate:
    candidate_id: str
    event_at: pd.Timestamp
    named_trading_date: date
    validation_year: int
    session: str
    direction: Direction
    causal_volatility_bucket: str
    upstream_mapping: str
    elapsed_to_event_bucket: str
    endpoint_complete: bool
    ote_touched_at_event: bool
    nearest_unrelated_ote_touch_minutes: float | None

    def __post_init__(self) -> None:
        stamp = pd.Timestamp(self.event_at)
        if stamp.tz is None:
            raise ValueError("control timestamp must be timezone-aware")
        object.__setattr__(self, "event_at", stamp.tz_convert("UTC"))
        if not self.candidate_id:
            raise ValueError("control candidate ID is required")
        if self.validation_year != self.named_trading_date.year:
            raise ValueError("control validation year must match named trading date")
        if self.named_trading_date != named_trading_date(self.event_at):
            raise ValueError(
                "control named trading date must match the frozen D007 "
                "18:00 America/New_York roll"
            )
        if self.session not in CONTROL_SESSIONS:
            raise ValueError("control session is outside the frozen D005 vocabulary")
        if not isinstance(self.direction, Direction):
            raise ValueError("control direction must use the frozen Direction enum")
        if self.causal_volatility_bucket not in VOLATILITY_BUCKETS:
            raise ValueError("control volatility bucket is outside the frozen vocabulary")
        if self.upstream_mapping != "1h_5m":
            raise ValueError("control upstream mapping is outside D007 primary")
        if self.elapsed_to_event_bucket not in ELAPSED_EVENT_BUCKETS:
            raise ValueError("control elapsed-event bucket is outside the frozen vocabulary")
        if not isinstance(self.endpoint_complete, bool) or not isinstance(
            self.ote_touched_at_event, bool
        ):
            raise ValueError("control completeness/touch flags must be boolean")
        if self.nearest_unrelated_ote_touch_minutes is not None and (
            not math.isfinite(self.nearest_unrelated_ote_touch_minutes)
            or self.nearest_unrelated_ote_touch_minutes < 0
        ):
            raise ValueError("control OTE separation must be finite and non-negative")


def control_is_eligible(
    treatment: ControlCandidate,
    candidate: ControlCandidate,
    config: D007Config = D007Config(),
) -> bool:
    """Check causal matching fields only; no price endpoint is accepted."""

    if treatment.validation_year not in config.validation_years:
        return False
    if candidate.validation_year not in config.validation_years:
        return False
    if treatment.named_trading_date == candidate.named_trading_date:
        return False
    distance_days = abs(
        (candidate.named_trading_date - treatment.named_trading_date).days
    )
    if distance_days > config.control_window_days:
        return False
    if not candidate.endpoint_complete or candidate.ote_touched_at_event:
        return False
    if (
        candidate.nearest_unrelated_ote_touch_minutes is not None
        and candidate.nearest_unrelated_ote_touch_minutes
        < config.control_exclusion_minutes
    ):
        return False
    return (
        treatment.validation_year == candidate.validation_year
        and treatment.session == candidate.session
        and treatment.direction == candidate.direction
        and treatment.causal_volatility_bucket == candidate.causal_volatility_bucket
        and treatment.upstream_mapping == candidate.upstream_mapping
        and treatment.elapsed_to_event_bucket == candidate.elapsed_to_event_bucket
    )


def select_control(
    treatment: ControlCandidate,
    candidates: Iterable[ControlCandidate],
    family: str,
    used_ids: frozenset[str] = frozenset(),
    config: D007Config = D007Config(),
) -> ControlCandidate | None:
    if family not in FIXED_CONTROLS:
        raise ValueError("control family is outside the fixed D007 registry")
    eligible = [
        item
        for item in candidates
        if item.candidate_id not in used_ids and control_is_eligible(treatment, item, config)
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda item: (
            sha256(
                f"{config.control_seed}|{family}|{treatment.candidate_id}|{item.event_at.isoformat()}".encode()
            ).hexdigest(),
            item.candidate_id,
        ),
    )


@dataclass(frozen=True)
class InteractionEvidence:
    interaction_name: str
    evidence_id: str
    available_at: pd.Timestamp
    direction: Direction

    def __post_init__(self) -> None:
        if self.interaction_name not in {item.name for item in FIXED_INTERACTIONS}:
            raise ValueError("interaction is outside the fixed D007 registry")
        if not self.evidence_id:
            raise ValueError("interaction evidence ID is required")
        if not isinstance(self.direction, Direction):
            raise ValueError("interaction direction must use the frozen Direction enum")
        stamp = pd.Timestamp(self.available_at)
        if stamp.tz is None:
            raise ValueError("interaction timestamp must be timezone-aware")
        object.__setattr__(self, "available_at", stamp.tz_convert("UTC"))


def interaction_is_causal(
    ote_range: OTERange,
    evidence: InteractionEvidence,
    first_touch_at: pd.Timestamp | None,
) -> bool:
    touch_time = pd.Timestamp(first_touch_at) if first_touch_at is not None else None
    if touch_time is not None:
        if touch_time.tz is None:
            raise ValueError("first-touch timestamp must be timezone-aware")
        touch_time = touch_time.tz_convert("UTC")
    if evidence.interaction_name == "ote_alone":
        return bool(
            touch_time is not None
            and touch_time >= ote_range.range_available_at
            and evidence.available_at >= ote_range.range_available_at
            and evidence.available_at <= touch_time
            and evidence.direction == ote_range.direction
        )
    touch_limited = evidence.interaction_name in {
        "refinement_confirmation",
        "d006_rejection_block",
    }
    deadline = touch_time if touch_limited else ote_range.range_available_at
    if deadline is None or evidence.available_at > deadline:
        return False
    if evidence.interaction_name == "against_d005_context_negative_control":
        return evidence.direction != ote_range.direction
    return evidence.direction == ote_range.direction


def conditional_candidate_eligible(passed_interactions: Iterable[str]) -> bool:
    """Only confirmatory positive interactions can support candidacy."""

    eligible = {
        item.name
        for item in FIXED_INTERACTIONS
        if item.role == "confirmatory"
    }
    return bool(set(passed_interactions) & eligible)


def endpoint_eligible_from_availability(
    event_at: pd.Timestamp | str,
    complete_bar_availability: Iterable[pd.Timestamp | str],
    config: D007Config = D007Config(),
) -> bool:
    """Verify endpoint timestamp coverage using no OHLC or outcome value."""

    event = pd.Timestamp(event_at)
    if event.tz is None:
        raise ValueError("event timestamp must be timezone-aware")
    event = event.tz_convert("UTC")
    if named_trading_date(event).year not in config.validation_years:
        return False
    available = {pd.Timestamp(value).tz_convert("UTC") for value in complete_bar_availability}
    required = {
        event + pd.Timedelta(minutes=offset)
        for offset in range(0, config.primary_horizon_minutes + 1, config.bar_minutes)
    }
    if any(
        named_trading_date(stamp).year not in config.validation_years
        for stamp in required
    ):
        return False
    return required.issubset(available)


def adequacy_status(
    counts: Mapping[str, int | float],
    config: D007Config = D007Config(),
) -> str:
    required = {
        "constructed_ranges": config.minimum_constructed_ranges,
        "lifecycle_eligible": config.minimum_lifecycle_eligible,
        "first_touches": config.minimum_first_touches,
        "untouched_controls": config.minimum_untouched_controls,
        "primary_pairs": config.minimum_primary_pairs,
        "bullish": config.minimum_per_direction,
        "bearish": config.minimum_per_direction,
    }
    passed = all(float(counts.get(name, 0)) >= threshold for name, threshold in required.items())
    passed &= float(counts.get("endpoint_coverage", 0.0)) == config.endpoint_coverage_required
    for year in config.validation_years:
        passed &= int(counts.get(f"pairs_{year}", 0)) >= config.minimum_pairs_per_year
    for session in config.required_sessions:
        passed &= int(counts.get(f"touches_{session}", 0)) >= config.minimum_per_required_session
    for interaction in config.interactions:
        passed &= int(counts.get(f"interaction_{interaction.name}", 0)) >= interaction.minimum_pairs
    for geometry in config.geometries:
        passed &= int(counts.get(f"geometry_{geometry.geometry_id}", 0)) >= config.minimum_geometry_cohort
    return "SAMPLE_ADEQUATE" if passed else "SAMPLE_INADEQUATE"


def component_disposition(
    *,
    integrity_passed: bool,
    adequacy_passed: bool,
    structural_passed: bool,
    primary_ci_upper: float | None,
    non_redundant_passed: bool,
    conditional_passed: bool,
    geometry_passed: bool,
    yearly_means: Mapping[int, float | None],
    config: D007Config = D007Config(),
) -> str:
    yearly_coverage = set(yearly_means) == set(config.validation_years) and all(
        value is not None and math.isfinite(value)
        for value in yearly_means.values()
    )
    finite_primary = primary_ci_upper is not None and math.isfinite(primary_ci_upper)
    if not integrity_passed:
        result = "REPRODUCIBILITY_DEFECT"
    elif not adequacy_passed or not structural_passed or not yearly_coverage or not finite_primary:
        result = "INSUFFICIENT_EVIDENCE"
    elif non_redundant_passed:
        result = "NON_REDUNDANT_COMPONENT_CANDIDATE"
    elif conditional_passed:
        result = "CONDITIONAL_CANDIDATE"
    elif geometry_passed:
        result = "GEOMETRY_CANDIDATE"
    else:
        nonpositive = sum(value is not None and value <= 0 for value in yearly_means.values())
        result = (
            "REJECT_COMPONENT"
            if primary_ci_upper <= 0 and nonpositive >= 3
            else "STRUCTURALLY_VALID_EMPIRICALLY_WEAK"
        )
    if result not in COMPONENT_DISPOSITIONS:
        raise AssertionError("unregistered D007 disposition")
    return result
