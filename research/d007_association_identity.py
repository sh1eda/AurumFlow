"""Outcome-blind D004/D006 to D005-E4 association authority.

This module contains only synthetic association semantics and projection
contracts.  It does not load historical rows or calculate D007 outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from research.d007_methodology_clarification import named_trading_date


AUTHORITY_ID = "D007_ASSOCIATION_IDENTITY_CLARIFICATION_V1"
ADDENDUM_PATH = Path("docs/D007_ASSOCIATION_IDENTITY_CLARIFICATION.md")
ADDENDUM_SHA256 = "a885365ff2fb4004792a0af54b9eab4e51ad1b9095ed650d458306050305f2de"
E4_MAPPING = "1h_5m"
D006_DEFINITION = "single_wick_50_d3_v1"
D006_ASSOCIATION_LOOKBACK = pd.Timedelta(minutes=60)

# These are complete, exact projections for the association loader.  The
# tuples extend, but never weaken, the earlier D007 role-specific allowlists.
ASSOCIATION_PROJECTIONS: Mapping[str, tuple[str, ...]] = {
    "d004_daily_events": (
        "trading_date",
        "primary_reference_name",
        "high_sweep",
        "low_sweep",
        "high_sweep_time",
        "low_sweep_time",
        "high_reentry",
        "low_reentry",
        "high_reentry_time",
        "low_reentry_time",
    ),
    "d005_e4_eligible_sequences": (
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
    "d005_e4_displacement_anchors": (
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
    "d006_structural_blocks": (
        "block_id",
        "definition_name",
        "direction",
        "source_bar_ids",
        "expansion_bar_id",
        "confirmation_timestamp",
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
}

ASSOCIATION_ARTIFACT_PATHS: Mapping[str, str] = {
    "d004_daily_events": "research_outputs/D004_XAUUSD_0830_0900/daily_events.parquet",
    "d005_e4_eligible_sequences": "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/eligible_sequences.parquet",
    "d005_e4_displacement_anchors": "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/displacement_anchors.parquet",
    "d006_structural_blocks": "research_outputs/D006_REJECTION_BLOCK_RESEARCH/structural_blocks.parquet",
}

NEWLY_PERMITTED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "d004_daily_events": (
        "primary_reference_name",
        "high_sweep_time",
        "low_sweep_time",
    ),
    "d006_structural_blocks": (
        "source_bar_ids",
        "expansion_bar_id",
        "confirmation_timestamp",
    ),
}

FORBIDDEN_COLUMN_FRAGMENTS = (
    "outcome",
    "later_",
    "retrospective_",
    "mfe",
    "mae",
    "terminal_r",
    "forward_",
)


def _utc(value: object, field: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tz is None:
        raise ValueError(f"{field} must be timezone-aware")
    return stamp.tz_convert("UTC")


def _direction(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be bullish/bearish or -1/1")
    if isinstance(value, str):
        normalized = value.lower()
        value = {"bullish": 1, "bearish": -1}.get(normalized, value)
    if value not in (-1, 1):
        raise ValueError(f"{field} must be bullish/bearish or -1/1")
    return int(value)


def _require_grid(stamp: pd.Timestamp, minutes: int, field: str) -> None:
    if (
        stamp.second
        or stamp.microsecond
        or stamp.nanosecond
        or stamp.minute % minutes
    ):
        raise ValueError(f"{field} must align to the {minutes}-minute grid")


def session_label(value: object) -> str:
    local = _utc(value, "session timestamp").tz_convert(
        ZoneInfo("America/New_York")
    )
    minute = local.hour * 60 + local.minute
    if minute >= 18 * 60:
        return "asia"
    if minute < 8 * 60 + 30:
        return "premarket"
    if minute < 12 * 60:
        return "ny_observation"
    if minute < 17 * 60:
        return "ny_afternoon"
    return "maintenance"


def validate_projection(
    artifact: str, requested_columns: Iterable[str] | None
) -> tuple[str, ...]:
    """Reject implicit/full-table reads and every non-allowlisted column."""

    if artifact not in ASSOCIATION_PROJECTIONS:
        raise ValueError("unknown association artifact")
    if requested_columns is None:
        raise ValueError("full-table reads are forbidden")
    requested = tuple(requested_columns)
    if not requested:
        raise ValueError("an explicit non-empty projection is required")
    if len(requested) != len(set(requested)):
        raise ValueError("projection columns must be unique")
    allowed = ASSOCIATION_PROJECTIONS[artifact]
    unexpected = set(requested) - set(allowed)
    if unexpected:
        raise ValueError(f"forbidden association columns: {sorted(unexpected)}")
    lowered = tuple(column.lower() for column in requested)
    causal_negation_flags = {"anchor_selected_using_later_completion"}
    if any(
        fragment in column
        for column in lowered
        if column not in causal_negation_flags
        for fragment in FORBIDDEN_COLUMN_FRAGMENTS
    ):
        raise ValueError("outcome-bearing columns are forbidden")
    return requested


def verify_association_projection_contract(root: Path) -> dict[str, str]:
    """Authenticate upstream bytes, then inspect only Parquet footer schemas."""

    from pyarrow.parquet import ParquetFile

    from research.d007_methodology_clarification import (
        UPSTREAM_ARTIFACTS,
        verify_upstream_identities,
    )

    authenticated = verify_upstream_identities(root)
    hashes_by_path = {item.path: item.sha256 for item in UPSTREAM_ARTIFACTS}
    observed: dict[str, str] = {}
    for artifact, relative_path in ASSOCIATION_ARTIFACT_PATHS.items():
        path = root / relative_path
        required = set(validate_projection(artifact, ASSOCIATION_PROJECTIONS[artifact]))
        available = set(ParquetFile(path).schema_arrow.names)
        missing = required - available
        if missing:
            raise ValueError(
                f"association projection columns missing for {artifact}: {sorted(missing)}"
            )
        if relative_path not in hashes_by_path:
            raise ValueError("association artifact is absent from the frozen upstream registry")
        if authenticated.get(relative_path) != hashes_by_path[relative_path]:
            raise ValueError("association artifact identity was not authenticated")
        observed[artifact] = hashes_by_path[relative_path]
    return observed


@dataclass(frozen=True)
class E4SequenceIdentity:
    sequence_id: str
    displacement_confirmation_event_id: str
    anchor_event_id: str
    anchor_at: pd.Timestamp
    direction: int
    anchor_session: str
    anchor_year: int
    mapping_variant: str = E4_MAPPING
    main_scope_eligible: bool = True
    anchor_causally_observable: bool = True
    anchor_selected_using_later_completion: bool = False
    anchor_sequence_id: str | None = None
    anchor_mapping_variant: str | None = None
    anchor_direction: int | None = None
    anchor_main_scope_eligible: bool | None = None
    anchor_causal_flag: bool | None = None
    anchor_later_completion_flag: bool | None = None

    def __post_init__(self) -> None:
        if not self.sequence_id or not self.displacement_confirmation_event_id or not self.anchor_event_id:
            raise ValueError("E4 identities must be non-empty")
        for field in (
            "main_scope_eligible",
            "anchor_causally_observable",
            "anchor_selected_using_later_completion",
        ):
            if type(getattr(self, field)) is not bool:
                raise ValueError("E4 causal eligibility flags must be boolean")
        for field in (
            "anchor_main_scope_eligible",
            "anchor_causal_flag",
            "anchor_later_completion_flag",
        ):
            value = getattr(self, field)
            if value is not None and type(value) is not bool:
                raise ValueError("E4 anchor causal eligibility flags must be boolean")
        object.__setattr__(self, "anchor_at", _utc(self.anchor_at, "E4 anchor_at"))
        _require_grid(self.anchor_at, 5, "E4 anchor_at")
        object.__setattr__(self, "direction", _direction(self.direction, "E4 direction"))
        anchor_sequence_id = self.anchor_sequence_id or self.sequence_id
        anchor_mapping = self.anchor_mapping_variant or self.mapping_variant
        anchor_direction = (
            self.direction
            if self.anchor_direction is None
            else _direction(self.anchor_direction, "E4 anchor direction")
        )
        anchor_main_scope = (
            self.main_scope_eligible
            if self.anchor_main_scope_eligible is None
            else self.anchor_main_scope_eligible
        )
        anchor_causal = (
            self.anchor_causally_observable
            if self.anchor_causal_flag is None
            else self.anchor_causal_flag
        )
        anchor_later = (
            self.anchor_selected_using_later_completion
            if self.anchor_later_completion_flag is None
            else self.anchor_later_completion_flag
        )
        object.__setattr__(self, "anchor_sequence_id", anchor_sequence_id)
        object.__setattr__(self, "anchor_mapping_variant", anchor_mapping)
        object.__setattr__(self, "anchor_direction", anchor_direction)
        object.__setattr__(self, "anchor_main_scope_eligible", anchor_main_scope)
        object.__setattr__(self, "anchor_causal_flag", anchor_causal)
        object.__setattr__(self, "anchor_later_completion_flag", anchor_later)
        if (
            anchor_sequence_id != self.sequence_id
            or anchor_mapping != self.mapping_variant
            or anchor_direction != self.direction
            or anchor_main_scope != self.main_scope_eligible
            or anchor_causal != self.anchor_causally_observable
            or anchor_later != self.anchor_selected_using_later_completion
        ):
            raise ValueError("ambiguous_or_invalid_e4_identity: sequence/anchor conflict")
        if self.anchor_session != session_label(self.anchor_at):
            raise ValueError("E4 anchor session mismatch")
        local_year = self.anchor_at.tz_convert(
            ZoneInfo("America/New_York")
        ).year
        if self.anchor_year != local_year:
            raise ValueError("E4 anchor year mismatch")
        if self.mapping_variant != E4_MAPPING:
            raise ValueError("only the frozen 1h_5m mapping is eligible")
        if not self.main_scope_eligible or not self.anchor_causally_observable:
            raise ValueError("E4 sequence must be causally eligible")
        if self.anchor_selected_using_later_completion:
            raise ValueError("retrospectively selected E4 anchors are forbidden")


@dataclass(frozen=True)
class D004EventIdentity:
    event_id: str
    trading_date: date
    side: str
    reference_name: str
    sweep_at: pd.Timestamp
    reentry_at: pd.Timestamp
    available_at: pd.Timestamp
    direction: int
    sweep_completed: bool = True
    reentry_completed: bool = True

    def __post_init__(self) -> None:
        if not self.event_id or self.side not in {"high", "low"} or not self.reference_name:
            raise ValueError("D004 event identity is incomplete")
        object.__setattr__(self, "sweep_at", _utc(self.sweep_at, "D004 sweep_at"))
        object.__setattr__(self, "reentry_at", _utc(self.reentry_at, "D004 reentry_at"))
        object.__setattr__(self, "available_at", _utc(self.available_at, "D004 available_at"))
        _require_grid(self.sweep_at, 1, "D004 sweep_at")
        _require_grid(self.reentry_at, 1, "D004 reentry_at")
        _require_grid(self.available_at, 1, "D004 available_at")
        object.__setattr__(self, "direction", _direction(self.direction, "D004 direction"))
        expected = -1 if self.side == "high" else 1
        if self.direction != expected:
            raise ValueError("D004 side/direction mismatch")
        expected_id = f"d004:{self.trading_date.isoformat()}:{self.side}"
        if self.event_id != expected_id:
            raise ValueError("D004 event ID must use the canonical date/side identity")
        if type(self.sweep_completed) is not bool or type(self.reentry_completed) is not bool:
            raise ValueError("D004 completion flags must be boolean")
        if not self.sweep_completed or not self.reentry_completed:
            raise ValueError("D004 association requires completed sweep and re-entry")
        if self.available_at != self.reentry_at + pd.Timedelta(minutes=1):
            raise ValueError("D004 availability must equal re-entry left edge plus one minute")
        if self.sweep_at >= self.available_at:
            raise ValueError("D004 sweep must precede completed re-entry availability")
        if named_trading_date(self.available_at) != self.trading_date:
            raise ValueError("D004 named trading date mismatch")


@dataclass(frozen=True)
class D006BlockIdentity:
    block_id: str
    definition_name: str
    direction: int
    source_bar_ids: tuple[str, ...]
    expansion_bar_id: str
    confirmation_at: pd.Timestamp
    causal_availability: pd.Timestamp
    first_touch_at: pd.Timestamp
    expiry_deadline: pd.Timestamp
    range_size: float
    lifecycle_state: str = "ACTIVE_TOUCHED"
    mitigation_at: pd.Timestamp | None = None
    invalidation_at: pd.Timestamp | None = None
    expiry_at: pd.Timestamp | None = None
    preavailability_interaction: bool = False

    def __post_init__(self) -> None:
        if not self.block_id or self.definition_name != D006_DEFINITION:
            raise ValueError("only the frozen D006 primary block is eligible")
        if (
            not isinstance(self.source_bar_ids, tuple)
            or not self.source_bar_ids
            or not all(isinstance(value, str) and value for value in self.source_bar_ids)
            or len(set(self.source_bar_ids)) != len(self.source_bar_ids)
            or tuple(sorted(self.source_bar_ids)) != self.source_bar_ids
            or not isinstance(self.expansion_bar_id, str)
            or not self.expansion_bar_id
            or self.expansion_bar_id in self.source_bar_ids
        ):
            raise ValueError("D006 source identities must be non-empty")
        object.__setattr__(self, "direction", _direction(self.direction, "D006 direction"))
        for field in (
            "confirmation_at",
            "causal_availability",
            "first_touch_at",
            "expiry_deadline",
            "mitigation_at",
            "invalidation_at",
            "expiry_at",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _utc(value, f"D006 {field}"))
        _require_grid(self.confirmation_at, 5, "D006 confirmation_at")
        _require_grid(self.causal_availability, 5, "D006 causal_availability")
        _require_grid(self.first_touch_at, 5, "D006 first_touch_at")
        _require_grid(self.expiry_deadline, 5, "D006 expiry_deadline")
        if self.confirmation_at != self.causal_availability:
            raise ValueError("D006 confirmation and causal availability must agree")
        if not self.causal_availability < self.first_touch_at < self.expiry_deadline:
            raise ValueError("D006 first touch must be after availability and before expiry")
        if self.expiry_deadline != self.causal_availability + pd.Timedelta(hours=24):
            raise ValueError("D006 expiry deadline must be exactly 24 hours")
        if not pd.notna(self.range_size) or self.range_size <= 0:
            raise ValueError("D006 range must be positive")
        if type(self.preavailability_interaction) is not bool:
            raise ValueError("D006 preavailability flag must be boolean")
        if self.lifecycle_state not in {
            "ACTIVE_TOUCHED",
            "MITIGATED",
            "INVALIDATED",
            "EXPIRED",
        }:
            raise ValueError("unknown D006 lifecycle state")
        for value in (self.mitigation_at, self.invalidation_at, self.expiry_at):
            if value is not None and not (
                self.causal_availability < value <= self.expiry_deadline
            ):
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
        if terminal_at is not None and self.first_touch_at > terminal_at:
            raise ValueError("D006 first touch cannot follow a terminal timestamp")
        expected_state = terminal_states[0] if terminal_states else "ACTIVE_TOUCHED"
        if self.lifecycle_state != expected_state:
            raise ValueError("D006 lifecycle state/timestamp mismatch")


@dataclass(frozen=True)
class AssociationDecision:
    family: str
    constituent_id: str
    association_id: str | None
    e4_sequence_id: str | None
    e4_displacement_event_id: str | None
    exclusion_reason: str | None
    constituent_event_at: pd.Timestamp
    association_reference_at: pd.Timestamp
    e4_anchor_at: pd.Timestamp | None
    direction: int
    named_date: date
    session: str | None
    e4_named_date: date | None
    e4_validation_year: int | None
    e4_anchor_year: int | None
    elapsed_minutes: float | None
    association_distance_minutes: float | None
    authority_id: str = AUTHORITY_ID

    @property
    def associated(self) -> bool:
        return self.association_id is not None


def _association_id(family: str, constituent_id: str, sequence: E4SequenceIdentity) -> str:
    material = "|".join(
        (
            AUTHORITY_ID,
            family,
            constituent_id,
            sequence.sequence_id,
            sequence.displacement_confirmation_event_id,
        )
    )
    return "d007-assoc-" + sha256(material.encode("utf-8")).hexdigest()


def _decision(
    family: str,
    constituent_id: str,
    constituent_event_at: pd.Timestamp,
    direction: int,
    sequence: E4SequenceIdentity | None,
    reason: str | None,
    *,
    association_reference_at: pd.Timestamp | None = None,
) -> AssociationDecision:
    named = named_trading_date(constituent_event_at)
    reference = (
        constituent_event_at
        if association_reference_at is None
        else association_reference_at
    )
    if sequence is None:
        return AssociationDecision(
            family=family,
            constituent_id=constituent_id,
            association_id=None,
            e4_sequence_id=None,
            e4_displacement_event_id=None,
            exclusion_reason=reason,
            constituent_event_at=constituent_event_at,
            association_reference_at=reference,
            e4_anchor_at=None,
            direction=direction,
            named_date=named,
            session=None,
            e4_named_date=None,
            e4_validation_year=None,
            e4_anchor_year=None,
            elapsed_minutes=None,
            association_distance_minutes=None,
        )
    elapsed = (constituent_event_at - sequence.anchor_at).total_seconds() / 60.0
    association_distance = (reference - sequence.anchor_at).total_seconds() / 60.0
    e4_named = named_trading_date(sequence.anchor_at)
    return AssociationDecision(
        family=family,
        constituent_id=constituent_id,
        association_id=_association_id(family, constituent_id, sequence),
        e4_sequence_id=sequence.sequence_id,
        e4_displacement_event_id=sequence.displacement_confirmation_event_id,
        exclusion_reason=None,
        constituent_event_at=constituent_event_at,
        association_reference_at=reference,
        e4_anchor_at=sequence.anchor_at,
        direction=direction,
        named_date=named,
        session=sequence.anchor_session,
        e4_named_date=e4_named,
        e4_validation_year=e4_named.year,
        e4_anchor_year=sequence.anchor_year,
        elapsed_minutes=elapsed,
        association_distance_minutes=association_distance,
    )


def _validated_e4_universe(
    sequences: Iterable[E4SequenceIdentity],
) -> tuple[E4SequenceIdentity, ...]:
    result = tuple(sequences)
    sequence_ids = tuple(item.sequence_id for item in result)
    if len(sequence_ids) != len(set(sequence_ids)):
        raise ValueError("ambiguous_or_invalid_e4_identity: duplicate sequence_id")
    return result


def associate_d004_to_e4(
    event: D004EventIdentity, sequences: Iterable[E4SequenceIdentity]
) -> AssociationDecision:
    """Select the latest causally prior same-date/direction E4 sequence."""

    all_sequences = _validated_e4_universe(sequences)
    if not all_sequences:
        return _decision("d004", event.event_id, event.available_at, event.direction, None, "no_eligible_e4_sequence")
    directional = tuple(item for item in all_sequences if item.direction == event.direction)
    if not directional:
        return _decision("d004", event.event_id, event.available_at, event.direction, None, "direction_mismatch")
    same_date = tuple(
        item for item in directional if named_trading_date(item.anchor_at) == event.trading_date
    )
    if not same_date:
        return _decision("d004", event.event_id, event.available_at, event.direction, None, "named_date_mismatch")
    causal = tuple(
        item
        for item in same_date
        if pd.Timedelta(0)
        <= event.available_at - item.anchor_at
        <= pd.Timedelta(minutes=1440)
    )
    if not causal:
        return _decision("d004", event.event_id, event.available_at, event.direction, None, "no_prior_e4_in_1440m_window")
    selected = min(
        causal,
        key=lambda item: (
            -item.anchor_at.value,
            item.displacement_confirmation_event_id,
            item.sequence_id,
        ),
    )
    return _decision("d004", event.event_id, event.available_at, event.direction, selected, None)


def d006_block_is_lifecycle_eligible(block: D006BlockIdentity) -> bool:
    at = block.first_touch_at
    if block.preavailability_interaction or at >= block.expiry_deadline:
        return False
    for terminal in (block.mitigation_at, block.invalidation_at, block.expiry_at):
        if terminal is not None and terminal <= at:
            return False
    return True


def associate_d006_to_e4(
    block: D006BlockIdentity, sequences: Iterable[E4SequenceIdentity]
) -> AssociationDecision:
    """Select latest prior E4 anchor in D006's frozen 60-minute context window."""

    if not d006_block_is_lifecycle_eligible(block):
        return _decision(
            "d006", block.block_id, block.first_touch_at, block.direction,
            None, "lifecycle_ineligible_block",
            association_reference_at=block.causal_availability,
        )
    all_sequences = _validated_e4_universe(sequences)
    if not all_sequences:
        return _decision("d006", block.block_id, block.first_touch_at, block.direction, None, "no_eligible_e4_sequence", association_reference_at=block.causal_availability)
    directional = tuple(item for item in all_sequences if item.direction == block.direction)
    if not directional:
        return _decision("d006", block.block_id, block.first_touch_at, block.direction, None, "direction_mismatch", association_reference_at=block.causal_availability)
    block_date = named_trading_date(block.causal_availability)
    block_session = session_label(block.causal_availability)
    same_context = tuple(
        item
        for item in directional
        if named_trading_date(item.anchor_at) == block_date
        and item.anchor_session == block_session
    )
    if not same_context:
        return _decision("d006", block.block_id, block.first_touch_at, block.direction, None, "named_date_or_session_mismatch", association_reference_at=block.causal_availability)
    lower = block.causal_availability - D006_ASSOCIATION_LOOKBACK
    causal = tuple(
        item
        for item in same_context
        if lower <= item.anchor_at < block.causal_availability
    )
    if not causal:
        return _decision("d006", block.block_id, block.first_touch_at, block.direction, None, "no_prior_e4_in_60m_window", association_reference_at=block.causal_availability)
    selected = min(
        causal,
        key=lambda item: (
            -item.anchor_at.value,
            item.displacement_confirmation_event_id,
            item.sequence_id,
        ),
    )
    return _decision(
        "d006", block.block_id, block.first_touch_at, block.direction,
        selected, None, association_reference_at=block.causal_availability,
    )


def select_d006_block(
    blocks: Iterable[D006BlockIdentity], at: object, direction: int
) -> D006BlockIdentity | None:
    """Preserve latest/narrowest/stable-ID precedence at a D007 event."""

    reference = _utc(at, "D007 association time")
    wanted = _direction(direction, "D007 direction")
    eligible = []
    for block in blocks:
        if block.direction != wanted or block.preavailability_interaction:
            continue
        if block.causal_availability > reference:
            continue
        if block.causal_availability < reference - pd.Timedelta(hours=24):
            continue
        if block.first_touch_at > reference or reference >= block.expiry_deadline:
            continue
        if any(
            terminal is not None and terminal <= reference
            for terminal in (block.mitigation_at, block.invalidation_at, block.expiry_at)
        ):
            continue
        eligible.append(block)
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda block: (-block.causal_availability.value, block.range_size, block.block_id),
    )


__all__ = [
    "ADDENDUM_PATH",
    "ADDENDUM_SHA256",
    "ASSOCIATION_PROJECTIONS",
    "ASSOCIATION_ARTIFACT_PATHS",
    "AUTHORITY_ID",
    "AssociationDecision",
    "D004EventIdentity",
    "D006BlockIdentity",
    "E4SequenceIdentity",
    "NEWLY_PERMITTED_COLUMNS",
    "associate_d004_to_e4",
    "associate_d006_to_e4",
    "d006_block_is_lifecycle_eligible",
    "select_d006_block",
    "session_label",
    "validate_projection",
    "verify_association_projection_contract",
]
