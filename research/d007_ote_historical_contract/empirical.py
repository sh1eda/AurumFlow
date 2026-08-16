"""Pure, fail-closed D007 empirical-domain transforms.

This module deliberately accepts already-projected, in-memory structures.  It
does not discover files, read Parquet, or run a historical pipeline.  The
functions make the frozen causal choices explicit so an authorized runner can
compose them without widening a selector after seeing an outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Iterable, Mapping, Sequence

import pandas as pd

from research.d007_association_identity import AssociationDecision, AUTHORITY_ID
from research.d007_methodology_clarification import (
    D006BlockEvidence,
    INTERACTION_HYPOTHESES,
    MatchedObservation,
    VALIDATION_YEARS,
    endpoint_is_registered,
    match_without_replacement,
    named_trading_date,
    select_d006_block,
)
from research.d007_ote_research.config import D007Config
from research.d007_ote_research.detector import (
    construct_ote_ranges,
    deduplicate_primary_overlaps,
    deduplicate_ranges,
)
from research.d007_ote_research.guardrails import adequacy_status, component_disposition
from research.d007_ote_research.lifecycle import LifecycleRecord, evaluate_lifecycle, primary_lifecycle_eligible
from research.d007_ote_research.models import ClosedBar, Direction, FrozenDisplacementAnchor, OTERange


SOURCE_TERMINAL_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
FIVE_MINUTES = pd.Timedelta(minutes=5)
ONE_MINUTE = pd.Timedelta(minutes=1)
E4_ID_FIELDS = (
    "sequence_id", "candidate_id", "mss_id", "displacement_id",
    "displacement_confirmation_event_id", "anchor_event_id",
)
SESSIONS = {"asia", "premarket", "ny_observation", "ny_afternoon", "maintenance"}
VOLATILITY_BUCKETS = {"low", "normal", "high", "unavailable"}
ELAPSED_BUCKETS = ("0_to_30", "30_to_60", "60_to_180", "180_to_1440")


def _utc(value: object, field: str = "timestamp") -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tz is None:
        raise ValueError(f"{field} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _direction(value: object, field: str = "direction") -> Direction:
    if isinstance(value, Direction):
        return value
    if isinstance(value, bool) or value not in (-1, 1):
        raise ValueError(f"{field} must be exactly -1 or 1")
    return Direction(int(value))


def _redundancy_direction(
    value: object, field: str = "evidence direction"
) -> Direction | None:
    """Normalize frozen cross-milestone direction representations.

    D005 structural artifacts use -1/0/+1, where neutral evidence cannot meet
    D007's exact-agreement rule. D006 structural artifacts serialize the same
    bearish/bullish semantics as strings. No other alias is accepted.
    """

    if isinstance(value, bool):
        raise ValueError(f"{field} must be bullish/bearish, neutral, or -1/0/1")
    if isinstance(value, str):
        value = {"bullish": 1, "bearish": -1}.get(value.lower(), value)
    if value == 0:
        return None
    return _direction(value, field)


def _flag(row: Mapping[str, object], name: str, default: bool = False) -> bool:
    value = row.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [name for name in columns if name not in frame]
    if missing:
        raise ValueError(f"missing projected OHLC columns: {missing}")


def build_5m_bars(projected_1m: pd.DataFrame) -> tuple[ClosedBar, ...]:
    """Aggregate a detached generic one-minute OHLC projection to closed 5m bars.

    Timestamps are one-minute bar left edges.  Every five-minute bucket must
    contain exactly five contiguous complete minutes; partial buckets never
    become synthetic closed bars.
    """

    _require_columns(projected_1m, ("timestamp_utc", "open", "high", "low", "close"))
    frame = projected_1m.loc[:, ["timestamp_utc", "open", "high", "low", "close"]].copy(deep=True)
    if frame.empty:
        return ()
    frame["timestamp_utc"] = [_utc(value, "timestamp_utc") for value in frame["timestamp_utc"]]
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError("one-minute timestamps must be unique")
    frame = frame.sort_values("timestamp_utc", kind="mergesort").reset_index(drop=True)
    if any(
        stamp.second or stamp.microsecond or stamp.nanosecond
        for stamp in frame["timestamp_utc"]
    ):
        raise ValueError("one-minute timestamps must align to the minute grid")
    values = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any() or not math.isfinite(float(values.to_numpy().sum())):
        raise ValueError("one-minute OHLC values must be finite")
    if (values["high"] < values[["open", "close"]].max(axis=1)).any() or (values["low"] > values[["open", "close"]].min(axis=1)).any() or (values["high"] < values["low"]).any():
        raise ValueError("one-minute OHLC violates bounds")
    frame["bucket"] = frame["timestamp_utc"].dt.floor("5min")
    bars: list[ClosedBar] = []
    for opened, group in frame.groupby("bucket", sort=True):
        expected = tuple(opened + index * ONE_MINUTE for index in range(5))
        actual = tuple(group["timestamp_utc"])
        if actual != expected:
            # Never synthesize or impute a partial bucket. Its absence lets the
            # frozen construction, lifecycle, and endpoint checks reject only
            # observations that require it.
            continue
        bars.append(ClosedBar(
            bar_id=f"5m:{opened.isoformat()}", opened_at=opened,
            available_at=opened + FIVE_MINUTES, open=float(group.iloc[0]["open"]),
            high=float(group["high"].max()), low=float(group["low"].min()),
            close=float(group.iloc[-1]["close"]), is_complete=True,
        ))
    return tuple(bars)


def reconstruct_frozen_anchor(sequence: Mapping[str, object], bars: Iterable[ClosedBar]) -> FrozenDisplacementAnchor:
    """Reconstruct the sole D007 origin from a causal E4 sequence and width-2 swing.

    Only bars closed by displacement creation are inspected for the swing;
    only the frozen creation-to-availability interval is delegated to the
    existing range detector for endpoint construction.
    """

    if str(sequence.get("mapping_variant", sequence.get("mapping_name", ""))) != "1h_5m":
        raise ValueError("E4 sequence is outside frozen 1h_5m mapping")
    for name in ("sequence_id", "displacement_created_at", "confirmation_event_available_at"):
        if not sequence.get(name):
            raise ValueError(f"E4 sequence missing {name}")
    direction = _direction(sequence.get("direction", sequence.get("candidate_direction")), "E4 direction")
    for name in ("candidate_direction", "mss_direction", "displacement_direction", "confirmation_event_direction"):
        if name in sequence and sequence[name] is not None and _direction(sequence[name], name) != direction:
            raise ValueError("E4 candidate/MSS/displacement directions must agree")
    for name in ("main_candidate_eligible", "main_scope_eligible", "anchor_causally_observable"):
        if name in sequence and not _flag(sequence, name):
            raise ValueError("E4 sequence fails frozen causal eligibility")
    if "anchor_selected_using_later_completion" in sequence and _flag(sequence, "anchor_selected_using_later_completion"):
        raise ValueError("E4 sequence used later completion")
    created = _utc(sequence["displacement_created_at"], "displacement_created_at")
    available = _utc(sequence["confirmation_event_available_at"], "confirmation_event_available_at")
    if available <= created:
        raise ValueError("E4 displacement availability must follow creation")
    ordered = tuple(sorted(bars, key=lambda bar: (bar.opened_at, bar.bar_id)))
    if len({bar.bar_id for bar in ordered}) != len(ordered):
        raise ValueError("five-minute bar IDs must be unique")
    causal = tuple(bar for bar in ordered if bar.available_at <= created)
    if len(causal) < 5:
        raise ValueError("width-2 opposite swing is unavailable")
    candidates: list[tuple[ClosedBar, pd.Timestamp, float]] = []
    for index in range(2, len(causal) - 2):
        pivot = causal[index]
        left, right = causal[index - 2:index], causal[index + 1:index + 3]
        window = (*left, pivot, *right)
        if any(not bar.is_complete for bar in window) or any(
            current.opened_at - prior.opened_at != FIVE_MINUTES
            for prior, current in zip(window, window[1:])
        ):
            continue
        if direction == Direction.BULLISH:
            selected = pivot.low < min(bar.low for bar in (*left, *right))
            price = pivot.low
        else:
            selected = pivot.high > max(bar.high for bar in (*left, *right))
            price = pivot.high
        if selected and causal[index + 2].available_at <= created:
            candidates.append((pivot, causal[index + 2].available_at, price))
    if not candidates:
        raise ValueError("latest causal width-2 confirmed opposite swing is missing")
    pivot, confirmed, price = max(candidates, key=lambda item: (item[0].opened_at, item[0].bar_id))
    return FrozenDisplacementAnchor(
        upstream_event_id=str(sequence["sequence_id"]), direction=direction,
        displacement_created_at=created, displacement_available_at=available,
        origin_swing_at=pivot.opened_at, origin_confirmed_at=confirmed,
        origin_price=price,
    )


def reconstruct_ote_ranges(sequence: Mapping[str, object], bars: Iterable[ClosedBar]) -> tuple[OTERange, ...]:
    """Build and deduplicate the fixed geometry objects for one E4 sequence."""

    anchor = reconstruct_frozen_anchor(sequence, bars)
    ranges = construct_ote_ranges(anchor, bars)
    selected, _ = deduplicate_ranges(ranges)
    return selected


def deduplicate_empirical_primary(ranges: Iterable[OTERange]) -> tuple[OTERange, ...]:
    selected, _ = deduplicate_primary_overlaps(ranges)
    return selected


@dataclass(frozen=True)
class EndpointOutcome:
    event_at: pd.Timestamp
    endpoint_at: pd.Timestamp
    reference_close: float | None
    endpoint_close: float | None
    direction_aligned_movement: float | None
    endpoint_complete: bool
    first_failure: str | None = None


def exact_60m_outcome(event_at: object, direction: int | Direction, bars: Iterable[ClosedBar]) -> EndpointOutcome:
    """Return the frozen thirteen-close 60-minute outcome, or one failure reason."""

    event = _utc(event_at, "event_at")
    endpoint = event + pd.Timedelta(minutes=60)
    try:
        if event >= SOURCE_TERMINAL_EXCLUSIVE or not endpoint_is_registered(event):
            raise ValueError("endpoint_outside_registered_validation_interval")
    except ValueError:
        return EndpointOutcome(event, endpoint, None, None, None, False, "endpoint_outside_registered_validation_interval")
    ordered = tuple(sorted(bars, key=lambda bar: (bar.available_at, bar.bar_id)))
    by_available = {bar.available_at: bar for bar in ordered}
    required = tuple(event + index * FIVE_MINUTES for index in range(13))
    if len(by_available) != len(ordered):
        return EndpointOutcome(event, endpoint, None, None, None, False, "duplicate_endpoint_bar")
    missing = next((stamp for stamp in required if stamp not in by_available), None)
    if missing is not None:
        return EndpointOutcome(event, endpoint, None, None, None, False, "missing_exact_60m_bar")
    chosen = tuple(by_available[stamp] for stamp in required)
    if any(not bar.is_complete for bar in chosen):
        return EndpointOutcome(event, endpoint, None, None, None, False, "incomplete_exact_60m_bar")
    reference, finish = chosen[0].close, chosen[-1].close
    return EndpointOutcome(event, endpoint, reference, finish, int(_direction(direction)) * (finish - reference), True)


def elapsed_displacement_bucket(displacement_available_at: object, event_at: object) -> str | None:
    elapsed = (_utc(event_at, "event_at") - _utc(displacement_available_at, "displacement_available_at")).total_seconds() / 60.0
    if elapsed < 0 or elapsed > 1440:
        return None
    if elapsed < 30:
        return "0_to_30"
    if elapsed < 60:
        return "30_to_60"
    if elapsed < 180:
        return "60_to_180"
    return "180_to_1440"


@dataclass(frozen=True)
class UpstreamAssociation:
    sequence: Mapping[str, object] | None
    first_failure: str | None


@dataclass(frozen=True)
class AssociatedMatchedObservation(MatchedObservation):
    """Matched observation whose stratum year is the exact E4 provenance year."""

    associated_validation_year: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.associated_validation_year not in VALIDATION_YEARS:
            raise ValueError("associated E4 validation year is outside D007")

    @property
    def validation_year(self) -> int:
        return self.associated_validation_year


def associate_upstream_ids(evidence_ids: Iterable[object], sequences: Iterable[Mapping[str, object]]) -> UpstreamAssociation:
    """Associate evidence only by the six frozen E4 identity fields, never time."""

    ids = {str(value) for value in evidence_ids if value is not None and str(value)}
    if not ids:
        return UpstreamAssociation(None, "ambiguous_upstream_association")
    matches: list[Mapping[str, object]] = []
    for sequence in sequences:
        if str(sequence.get("mapping_variant", sequence.get("mapping_name", ""))) != "1h_5m":
            continue
        sequence_ids = {str(sequence[name]) for name in E4_ID_FIELDS if sequence.get(name) is not None and str(sequence[name])}
        if ids & sequence_ids:
            matches.append(sequence)
    if len(matches) != 1:
        return UpstreamAssociation(None, "ambiguous_upstream_association")
    return UpstreamAssociation(matches[0], None)


@dataclass(frozen=True)
class EmpiricalCandidate:
    observation: MatchedObservation
    upstream_event_id: str
    first_failure: str | None = None
    association_id: str | None = None
    association_authority: str | None = None
    association_family: str | None = None
    e4_anchor_at: pd.Timestamp | None = None
    e4_anchor_year: int | None = None
    e4_validation_year: int | None = None
    association_distance_minutes: float | None = None


def make_candidate(*, candidate_id: str, event_at: object, evidence_ids: Iterable[object], sequences: Iterable[Mapping[str, object]], session: str | None, volatility_bucket: str, endpoint_complete: bool, own_ote_touched_at_event: bool, nearest_unrelated_ote_touch_minutes: float | None, evaluation_direction: int | Direction | None = None, association_decision: AssociationDecision | None = None) -> EmpiricalCandidate:
    event = _utc(event_at, "event_at")
    placeholder_event = event.floor("5min")
    association = associate_upstream_ids(evidence_ids, sequences)
    if association_decision is not None:
        if not association_decision.associated:
            association = UpstreamAssociation(None, association_decision.exclusion_reason)
        else:
            matches = [
                row for row in sequences
                if str(row.get("sequence_id", "")) == association_decision.e4_sequence_id
            ]
            association = UpstreamAssociation(
                matches[0] if len(matches) == 1 else None,
                None if len(matches) == 1 else "ambiguous_or_invalid_e4_identity",
            )
    if association.sequence is None:
        # A deliberately unusable observation carries the auditable failure;
        # it is never supplied to the matcher by ``match_family``.
        return EmpiricalCandidate(MatchedObservation(candidate_id, placeholder_event, ("__ineligible__",), "asia", 1, "unavailable", "0_to_30", endpoint_complete=False), "", association.first_failure)
    sequence = association.sequence
    direction = _direction(
        sequence.get("direction", sequence.get("candidate_direction")),
        "associated E4 direction",
    )
    if evaluation_direction is not None and _direction(
        evaluation_direction, "evaluation direction"
    ) != direction:
        return EmpiricalCandidate(
            MatchedObservation(candidate_id, placeholder_event, ("__ineligible__",), "asia", 1, "unavailable", "0_to_30", endpoint_complete=False),
            str(sequence.get("sequence_id", "")),
            "association_provenance_mismatch",
        )
    available = _utc(sequence["confirmation_event_available_at"], "confirmation_event_available_at")
    bucket = elapsed_displacement_bucket(available, event_at)
    anchor_at = _utc(sequence.get("anchor_at"), "E4 anchor_at") if sequence.get("anchor_at") is not None else None
    e4_session = sequence.get("anchor_session")
    e4_anchor_year = sequence.get("anchor_year")
    e4_validation_year = named_trading_date(anchor_at).year if anchor_at is not None else None
    if (
        e4_session not in SESSIONS
        or not isinstance(e4_anchor_year, int)
        or e4_validation_year not in VALIDATION_YEARS
        or volatility_bucket not in VOLATILITY_BUCKETS
        or bucket is None
    ):
        return EmpiricalCandidate(MatchedObservation(candidate_id, placeholder_event, ("__ineligible__",), "asia", 1, "unavailable", "0_to_30", endpoint_complete=False), str(sequence.get("sequence_id", "")), "ineligible_matching_fields")
    if event != placeholder_event:
        return EmpiricalCandidate(
            MatchedObservation(candidate_id, placeholder_event, ("__ineligible__",), "asia", 1, "unavailable", "0_to_30", endpoint_complete=False),
            str(sequence.get("sequence_id", "")),
            "event_not_on_frozen_five_minute_grid",
        )
    if association_decision is not None:
        if (
            association_decision.session != e4_session
            or association_decision.e4_validation_year != e4_validation_year
            or association_decision.e4_anchor_year != e4_anchor_year
            or association_decision.direction != int(direction)
        ):
            return EmpiricalCandidate(MatchedObservation(candidate_id, placeholder_event, ("__ineligible__",), "asia", 1, "unavailable", "0_to_30", endpoint_complete=False), str(sequence.get("sequence_id", "")), "association_provenance_mismatch")
    observation = AssociatedMatchedObservation(
        candidate_id,
        event,
        (str(sequence["sequence_id"]),),
        str(e4_session),
        int(direction),
        volatility_bucket,
        bucket,
        endpoint_complete,
        own_ote_touched_at_event,
        nearest_unrelated_ote_touch_minutes,
        "1h_5m",
        int(e4_validation_year),
    )
    association_id = (
        association_decision.association_id
        if association_decision is not None
        else f"exact-e4:{sequence['sequence_id']}"
    )
    distance = (
        association_decision.association_distance_minutes
        if association_decision is not None
        else (event - anchor_at).total_seconds() / 60.0
    )
    return EmpiricalCandidate(
        observation,
        str(sequence["sequence_id"]),
        association_id=association_id,
        association_authority=AUTHORITY_ID if association_decision is not None else "exact_e4_identity",
        association_family=association_decision.family if association_decision is not None else "exact_e4",
        e4_anchor_at=anchor_at,
        e4_anchor_year=int(e4_anchor_year),
        e4_validation_year=int(e4_validation_year),
        association_distance_minutes=distance,
    )


def match_family(treatments: Iterable[EmpiricalCandidate], candidates: Iterable[EmpiricalCandidate], family: str) -> tuple[tuple[str, str | None], ...]:
    """Use the clarification's exact fixed matcher with no replacement."""

    valid_treatments = [item.observation for item in treatments if item.first_failure is None]
    valid_candidates = [item.observation for item in candidates if item.first_failure is None]
    return match_without_replacement(valid_treatments, valid_candidates, family)


def equilibrium_candidates(ranges: Iterable[OTERange], lifecycle: Mapping[str, LifecycleRecord], bars: Iterable[ClosedBar], *, session_by_range: Mapping[str, str], volatility_by_range: Mapping[str, str], sequences: Iterable[Mapping[str, object]]) -> tuple[EmpiricalCandidate, ...]:
    """Create first causal 0.50-touch control candidates on primary ranges only."""

    all_bars = tuple(bars)
    result: list[EmpiricalCandidate] = []
    for item in ranges:
        if item.geometry_id != "ote_band_62_79" or not primary_lifecycle_eligible(item):
            continue
        record = lifecycle.get(item.range_id)
        ordered = sorted((bar for bar in all_bars if item.range_available_at <= bar.available_at < item.expiry_deadline), key=lambda bar: (bar.available_at, bar.bar_id))
        event: ClosedBar | None = None
        for bar in ordered:
            invalid = bar.close < item.origin_price if item.direction == Direction.BULLISH else bar.close > item.origin_price
            if invalid:
                break
            if bar.low <= item.equilibrium <= bar.high:
                event = bar
                break
        if event is None or (record and record.first_touch_at is not None and record.first_touch_at <= event.available_at):
            continue
        result.append(make_candidate(candidate_id=f"equilibrium:{item.range_id}", event_at=event.available_at, evidence_ids=(item.upstream_event_id,), sequences=sequences, session=session_by_range.get(item.range_id, ""), volatility_bucket=volatility_by_range.get(item.range_id, ""), endpoint_complete=exact_60m_outcome(event.available_at, item.direction, all_bars).endpoint_complete, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=None))
    return tuple(result)


@dataclass(frozen=True)
class Membership:
    interaction: str
    evidence_id: str | None
    event_at: pd.Timestamp | None
    direction: Direction | None
    eligible: bool
    first_failure: str | None = None


def _latest_unambiguous(rows: Iterable[Mapping[str, object]], *, at: object, time_key: str, direction: Direction, require_same: bool) -> Membership:
    deadline = _utc(at)
    usable = [row for row in rows if row.get(time_key) is not None and _utc(row[time_key], time_key) <= deadline]
    if not usable:
        return Membership("", None, None, None, False, "missing_constituent")
    latest = max(_utc(row[time_key], time_key) for row in usable)
    tied = [row for row in usable if _utc(row[time_key], time_key) == latest]
    directions = {_direction(row.get("direction"), "constituent direction") for row in tied}
    if len(directions) != 1:
        return Membership("", None, None, None, False, "conflicting_constituents")
    selected = min(tied, key=lambda row: str(row.get("snapshot_id", row.get("anchor_id", row.get("evidence_id", "")))))
    selected_direction = next(iter(directions))
    if (selected_direction == direction) != require_same:
        return Membership("", None, None, selected_direction, False, "direction_mismatch")
    identity = str(selected.get("snapshot_id", selected.get("anchor_id", selected.get("evidence_id", ""))))
    return Membership("", identity or None, latest, selected_direction, bool(identity), None if identity else "missing_constituent")


def select_e1_context(range_: OTERange, rows: Iterable[Mapping[str, object]], *, negative: bool = False) -> Membership:
    filtered = [row for row in rows if row.get("state") == "reaction_confirmed" and row.get("mapping_name", row.get("mapping_variant")) == "1h_5m" and row.get("parent_timeframe", "1H") == "1H" and row.get("reaction_timeframe", "5m") == "5m" and not bool(row.get("optional_1m_refinement", False))]
    selected = _latest_unambiguous(filtered, at=range_.range_available_at, time_key="evaluation_at", direction=range_.direction, require_same=not negative)
    return Membership("against_d005_context_negative_control" if negative else "aligned_d005_context", selected.evidence_id, selected.event_at, selected.direction, selected.eligible, selected.first_failure)


def select_e3_liquidity_sweep(range_: OTERange, rows: Iterable[Mapping[str, object]]) -> Membership:
    filtered = [row for row in rows if row.get("anchor_type") == "named_liquidity_sweep" and bool(row.get("main_scope_eligible")) and bool(row.get("anchor_causally_observable")) and not bool(row.get("anchor_selected_using_later_completion"))]
    selected = _latest_unambiguous(filtered, at=range_.range_available_at, time_key="anchor_at", direction=range_.direction, require_same=True)
    return Membership("frozen_liquidity_sweep", selected.evidence_id, selected.event_at, selected.direction, selected.eligible, selected.first_failure)


def select_e3_refinement(range_: OTERange, first_touch_at: object | None, rows: Iterable[Mapping[str, object]]) -> Membership:
    if first_touch_at is None:
        return Membership("refinement_confirmation", None, None, None, False, "missing_first_touch")
    filtered = [row for row in rows if row.get("anchor_type") == "refinement_array_creation"]
    selected = _latest_unambiguous(filtered, at=first_touch_at, time_key="anchor_at", direction=range_.direction, require_same=True)
    return Membership("refinement_confirmation", selected.evidence_id, selected.event_at, selected.direction, selected.eligible, selected.first_failure)


def select_d004_reentry(range_: OTERange, rows: Iterable[Mapping[str, object]]) -> Membership:
    time_key, flag_key = (
        ("low_reentry_time", "low_reentry")
        if range_.direction == Direction.BULLISH
        else ("high_reentry_time", "high_reentry")
    )
    candidates: list[Mapping[str, object]] = []
    for row in rows:
        event = row.get(time_key)
        sweep = bool(row.get("low_sweep" if range_.direction == Direction.BULLISH else "high_sweep", False))
        if event is not None and not pd.isna(event) and bool(row.get(flag_key, False)) and sweep:
            available = _utc(event, "D004 reentry") + ONE_MINUTE
            if named_trading_date(available) != named_trading_date(range_.range_available_at):
                continue
            candidates.append({"evidence_id": row.get("trading_date", ""), "anchor_at": available, "direction": int(range_.direction)})
    selected = _latest_unambiguous(candidates, at=range_.range_available_at - pd.Timedelta(nanoseconds=1), time_key="anchor_at", direction=range_.direction, require_same=True)
    return Membership("after_d004_manipulation", selected.evidence_id, selected.event_at, selected.direction, selected.eligible, selected.first_failure)


def select_d006_membership(range_: OTERange, first_touch_at: object | None, blocks: Iterable[D006BlockEvidence]) -> Membership:
    if first_touch_at is None:
        return Membership("d006_rejection_block", None, None, None, False, "missing_first_touch")
    block = select_d006_block(blocks, first_touch_at, int(range_.direction))
    if block is None:
        return Membership("d006_rejection_block", None, None, None, False, "missing_constituent")
    return Membership("d006_rejection_block", block.block_id, block.first_touch_at, Direction(block.direction), True)


@dataclass(frozen=True)
class RedundancyAssociation:
    evidence_id: str | None
    signed_minutes: float | None
    first_failure: str | None


def select_redundancy_evidence(range_: OTERange, first_touch_at: object, rows: Iterable[Mapping[str, object]], *, time_key: str = "available_at", allow_opposite_direction: bool = False) -> RedundancyAssociation:
    touch = _utc(first_touch_at, "first_touch_at")
    candidates: list[tuple[Mapping[str, object], float]] = []
    for row in rows:
        if row.get(time_key) is None:
            continue
        available = _utc(row[time_key], time_key)
        signed = (available - range_.range_available_at).total_seconds() / 60.0
        terminal = next((row.get(name) for name in ("mitigation_at", "invalidation_at", "expiry_at", "invalidated_at", "terminal_at") if row.get(name) is not None), None)
        if not -60 <= signed <= 60 or available > touch or (terminal is not None and _utc(terminal, "terminal") <= range_.range_available_at):
            continue
        row_direction = _redundancy_direction(row.get("direction"))
        if row_direction is None:
            continue
        if not allow_opposite_direction and row_direction != range_.direction:
            continue
        candidates.append((row, signed))
    if not candidates:
        return RedundancyAssociation(None, None, "missing_constituent")
    minimum = min(abs(signed) for _, signed in candidates)
    tied = [(row, signed) for row, signed in candidates if abs(signed) == minimum]
    if len({_redundancy_direction(row.get("direction")) for row, _ in tied}) != 1:
        return RedundancyAssociation(None, None, "conflicting_constituents")
    row, signed = min(tied, key=lambda item: (_utc(item[0][time_key], time_key), str(item[0].get("evidence_id", item[0].get("anchor_id", "")))))
    identity = str(row.get("evidence_id", row.get("anchor_id", "")))
    return RedundancyAssociation(identity or None, signed, None if identity else "missing_constituent")


def adequacy_requirements(counts: Mapping[str, int | float], config: D007Config = D007Config()) -> dict[str, object]:
    """Expose frozen adequacy as individual booleans plus the fail-closed status."""
    status = adequacy_status(counts, config)
    return {"status": status, "adequate": status == "SAMPLE_ADEQUATE", "counts": dict(counts)}


def final_disposition(**kwargs: object) -> str:
    """Delegate to the frozen ordered component-disposition registry."""
    return component_disposition(**kwargs)


__all__ = [
    "AssociatedMatchedObservation", "EmpiricalCandidate", "EndpointOutcome", "Membership", "RedundancyAssociation", "UpstreamAssociation",
    "adequacy_requirements", "associate_upstream_ids", "build_5m_bars", "deduplicate_empirical_primary",
    "elapsed_displacement_bucket", "equilibrium_candidates", "evaluate_lifecycle", "exact_60m_outcome", "final_disposition",
    "make_candidate", "match_family", "reconstruct_frozen_anchor", "reconstruct_ote_ranges",
    "select_d004_reentry", "select_d006_membership", "select_e1_context", "select_e3_liquidity_sweep",
    "select_e3_refinement", "select_redundancy_evidence",
]
