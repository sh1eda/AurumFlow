"""Immutable D005 evidence, event, and snapshot models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
import json
from typing import Any

import pandas as pd


class Direction(IntEnum):
    BEARISH = -1
    NEUTRAL = 0
    BULLISH = 1


class ContextState(str, Enum):
    NEUTRAL = "neutral"
    PROVISIONAL_CONTEXT = "provisional_context"
    CANDIDATE_POI = "candidate_poi"
    CANDIDATE_LIQUIDITY_EVENT = "candidate_liquidity_event"
    REACTION_CONFIRMED = "reaction_confirmed"
    CONFLICT = "conflict"
    INVALIDATED = "invalidated"


class OutcomeLabel(str, Enum):
    REVERSAL = "reversal"
    CONTINUATION = "continuation"
    NEUTRAL = "neutral"


ALLOWED_TRANSITIONS: dict[ContextState, frozenset[ContextState]] = {
    ContextState.NEUTRAL: frozenset(
        {ContextState.PROVISIONAL_CONTEXT, ContextState.INVALIDATED}
    ),
    ContextState.PROVISIONAL_CONTEXT: frozenset(
        {
            ContextState.CANDIDATE_POI,
            ContextState.CANDIDATE_LIQUIDITY_EVENT,
            ContextState.CONFLICT,
            ContextState.INVALIDATED,
            ContextState.NEUTRAL,
        }
    ),
    ContextState.CANDIDATE_POI: frozenset(
        {
            ContextState.REACTION_CONFIRMED,
            ContextState.CONFLICT,
            ContextState.INVALIDATED,
            ContextState.NEUTRAL,
        }
    ),
    ContextState.CANDIDATE_LIQUIDITY_EVENT: frozenset(
        {
            ContextState.REACTION_CONFIRMED,
            ContextState.CONFLICT,
            ContextState.INVALIDATED,
            ContextState.NEUTRAL,
        }
    ),
    ContextState.REACTION_CONFIRMED: frozenset(
        {ContextState.CONFLICT, ContextState.INVALIDATED, ContextState.NEUTRAL}
    ),
    ContextState.CONFLICT: frozenset(
        {ContextState.NEUTRAL, ContextState.INVALIDATED}
    ),
    ContextState.INVALIDATED: frozenset({ContextState.NEUTRAL}),
}


def validate_transition(current: ContextState, target: ContextState) -> None:
    if current == target:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid D005 state transition: {current.value} -> {target.value}")


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    event_type: str
    direction: Direction
    timeframe: str
    variant: str
    taxonomy: str
    created_at: pd.Timestamp
    available_at: pd.Timestamp
    source_rule_ids: tuple[str, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    level: float | None = None
    zone_low: float | None = None
    zone_high: float | None = None
    interacted_at: pd.Timestamp | None = None
    confirmed_at: pd.Timestamp | None = None
    invalidated_at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        for name in (
            "created_at",
            "available_at",
            "interacted_at",
            "confirmed_at",
            "invalidated_at",
        ):
            value = getattr(self, name)
            if value is None or pd.isna(value):
                continue
            stamp = pd.Timestamp(value)
            if stamp.tz is None:
                raise ValueError(f"{name} must be timezone-aware")
        if pd.Timestamp(self.available_at) < pd.Timestamp(self.created_at):
            raise ValueError("event available_at cannot precede created_at")
        lifecycle = [
            pd.Timestamp(value)
            for value in (
                self.interacted_at,
                self.confirmed_at,
                self.invalidated_at,
            )
            if value is not None and not pd.isna(value)
        ]
        if any(stamp < pd.Timestamp(self.available_at) for stamp in lifecycle):
            raise ValueError("event lifecycle timestamp cannot precede availability")
        if (
            self.interacted_at is not None
            and self.invalidated_at is not None
            and pd.Timestamp(self.invalidated_at) < pd.Timestamp(self.interacted_at)
        ):
            raise ValueError("event invalidation cannot precede interaction")
        if not self.source_rule_ids:
            raise ValueError("event source_rule_ids cannot be empty")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["direction"] = int(self.direction)
        record["source_rule_ids"] = list(self.source_rule_ids)
        record["parameters"] = json.dumps(
            self.parameters, sort_keys=True, separators=(",", ":")
        )
        for name in (
            "created_at",
            "available_at",
            "interacted_at",
            "confirmed_at",
            "invalidated_at",
        ):
            value = record[name]
            record[name] = (
                pd.Timestamp(value).isoformat()
                if value is not None and not pd.isna(value)
                else None
            )
        return record


@dataclass(frozen=True)
class StateTransition:
    from_state: ContextState
    to_state: ContextState
    occurred_at: pd.Timestamp
    reason: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_transition(self.from_state, self.to_state)
        if pd.Timestamp(self.occurred_at).tz is None:
            raise ValueError("transition timestamp must be timezone-aware")

    def to_record(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "occurred_at": pd.Timestamp(self.occurred_at).isoformat(),
            "reason": self.reason,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    evaluation_at: pd.Timestamp
    mapping_name: str
    parent_timeframe: str
    reaction_timeframe: str
    refinement_timeframe: str
    state: ContextState
    direction: Direction
    outcome: OutcomeLabel
    parent_direction: Direction
    child_direction: Direction
    entry_authorized: bool
    no_trade_reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    source_rule_ids: tuple[str, ...]
    variant_ids: tuple[str, ...]
    config_fingerprint: str
    transitions: tuple[StateTransition, ...]
    balanced_ranging: bool = False
    trapped_between_arrays: bool = False
    missing_required_data: bool = False
    overextended: bool = False
    risk_valid: bool = False

    def __post_init__(self) -> None:
        if pd.Timestamp(self.evaluation_at).tz is None:
            raise ValueError("snapshot evaluation_at must be timezone-aware")
        if self.entry_authorized:
            raise ValueError("D005 is research-only and cannot authorize entries")
        if self.state != ContextState.REACTION_CONFIRMED and self.direction != Direction.NEUTRAL:
            raise ValueError("only reaction_confirmed may expose non-neutral direction")
        if self.state in {ContextState.CONFLICT, ContextState.INVALIDATED}:
            if self.outcome != OutcomeLabel.NEUTRAL:
                raise ValueError("conflict/invalidated snapshots must be neutral")
        if self.transitions:
            if self.transitions[0].from_state != ContextState.NEUTRAL:
                raise ValueError("snapshot transition path must start at neutral")
            for previous, current in zip(
                self.transitions, self.transitions[1:], strict=False
            ):
                if previous.to_state != current.from_state:
                    raise ValueError("snapshot transition path is discontinuous")
                if pd.Timestamp(previous.occurred_at) > pd.Timestamp(
                    current.occurred_at
                ):
                    raise ValueError("snapshot transition timestamps are out of order")
            if self.transitions[-1].to_state != self.state:
                raise ValueError("snapshot state does not match transition path")
            if any(
                pd.Timestamp(item.occurred_at) > pd.Timestamp(self.evaluation_at)
                for item in self.transitions
            ):
                raise ValueError("snapshot transition occurs after evaluation")

    def to_record(self) -> dict[str, Any]:
        return {
            "evaluation_at": pd.Timestamp(self.evaluation_at).isoformat(),
            "mapping_name": self.mapping_name,
            "parent_timeframe": self.parent_timeframe,
            "reaction_timeframe": self.reaction_timeframe,
            "refinement_timeframe": self.refinement_timeframe,
            "state": self.state.value,
            "direction": int(self.direction),
            "outcome": self.outcome.value,
            "parent_direction": int(self.parent_direction),
            "child_direction": int(self.child_direction),
            "entry_authorized": self.entry_authorized,
            "no_trade_reasons": list(self.no_trade_reasons),
            "evidence_ids": list(self.evidence_ids),
            "source_rule_ids": list(self.source_rule_ids),
            "variant_ids": list(self.variant_ids),
            "config_fingerprint": self.config_fingerprint,
            "transitions": [item.to_record() for item in self.transitions],
            "balanced_ranging": self.balanced_ranging,
            "trapped_between_arrays": self.trapped_between_arrays,
            "missing_required_data": self.missing_required_data,
            "overextended": self.overextended,
            "risk_valid": self.risk_valid,
        }
