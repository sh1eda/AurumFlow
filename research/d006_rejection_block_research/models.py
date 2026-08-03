"""Structural-only domain models; deliberately no trade or outcome fields."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True)
class RejectionBlock:
    block_id: str
    definition_name: str
    direction: Direction
    timeframe: str
    source_bar_ids: tuple[str, ...]
    expansion_bar_id: str
    creation_timestamp: pd.Timestamp
    confirmation_timestamp: pd.Timestamp
    causal_availability: pd.Timestamp
    distal: float
    proximal: float
    midpoint: float
    range: float
    normalized_range: float
    session: str
    trading_date: str
    context_keys: tuple[str, ...] = ()
    preavailability_interaction: bool = False
    overlap_group_id: Optional[str] = None
    parent_block_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.definition_name not in {
            "single_wick_50_d3_v1",
            "cluster2_wick_50_d3_v1",
        }:
            raise ValueError("definition_name must use the fixed D006 registry")
        expected_source_count = 1 if self.definition_name == "single_wick_50_d3_v1" else 2
        if self.timeframe != "5min" or not isinstance(self.direction, Direction):
            raise ValueError("direction and timeframe must use the fixed D006 registry")
        for name in (
            "creation_timestamp",
            "confirmation_timestamp",
            "causal_availability",
        ):
            stamp = pd.Timestamp(getattr(self, name))
            if str(stamp.tz) != "UTC":
                raise ValueError(f"{name} must be explicit UTC")
        if self.confirmation_timestamp != self.causal_availability:
            raise ValueError("confirmation and causal availability must match")
        if self.creation_timestamp >= self.causal_availability:
            raise ValueError("creation must precede causal availability")
        if (
            len(self.source_bar_ids) != expected_source_count
            or len(set(self.source_bar_ids)) != len(self.source_bar_ids)
            or tuple(sorted(self.source_bar_ids)) != self.source_bar_ids
            or not all(isinstance(value, str) and value for value in self.source_bar_ids)
            or not isinstance(self.expansion_bar_id, str)
            or not self.expansion_bar_id
            or self.expansion_bar_id in self.source_bar_ids
        ):
            raise ValueError("source and expansion candle identities are required")
        if not all(
            isinstance(value, (int, float)) and isfinite(value)
            for value in (self.distal, self.proximal, self.midpoint, self.range, self.normalized_range)
        ) or self.range <= 0 or self.normalized_range <= 0:
            raise ValueError("block ranges must be positive")
        if abs(self.range - abs(self.proximal - self.distal)) > 1e-12:
            raise ValueError("block range does not match its boundaries")
        if abs(self.midpoint - (self.proximal + self.distal) / 2) > 1e-12:
            raise ValueError("block midpoint does not match its boundaries")
        if self.session not in {
            "asia",
            "premarket",
            "ny_observation",
            "ny_afternoon",
            "maintenance",
        }:
            raise ValueError("session must use the frozen D005 registry")
        try:
            parsed_trading_date = pd.Timestamp(self.trading_date)
        except ValueError as error:
            raise ValueError("trading_date must be an ISO calendar date") from error
        if (
            parsed_trading_date.strftime("%Y-%m-%d") != self.trading_date
            or parsed_trading_date.time() != pd.Timestamp("00:00").time()
        ):
            raise ValueError("trading_date must be an ISO calendar date")
        local = self.causal_availability.tz_convert(ZoneInfo("America/New_York"))
        expected_trading_date = local.date()
        if local.hour >= 18:
            expected_trading_date += pd.Timedelta(days=1)
        if expected_trading_date.isoformat() != self.trading_date:
            raise ValueError("trading_date does not match causal availability")
        if not isinstance(self.context_keys, tuple) or self.context_keys != tuple(
            sorted(set(self.context_keys))
        ) or not all(isinstance(value, str) and value for value in self.context_keys):
            raise ValueError("context_keys must be a sorted unique tuple")
        if type(self.preavailability_interaction) is not bool:
            raise ValueError("preavailability_interaction must be boolean")
        if self.parent_block_id == self.block_id:
            raise ValueError("a block cannot be its own parent")

    def with_relationships(
        self, overlap_group_id: Optional[str], parent_block_id: Optional[str]
    ) -> "RejectionBlock":
        return replace(
            self, overlap_group_id=overlap_group_id, parent_block_id=parent_block_id
        )


@dataclass(frozen=True)
class LifecycleRecord:
    block_id: str
    status: str
    active_at: pd.Timestamp
    first_touch_timestamp: Optional[pd.Timestamp]
    mitigation_timestamp: Optional[pd.Timestamp]
    invalidation_timestamp: Optional[pd.Timestamp]
    expiry_timestamp: Optional[pd.Timestamp]
    expiry_deadline: pd.Timestamp
    touch_count: int

    def __post_init__(self) -> None:
        if self.status not in {
            "ACTIVE_UNTOUCHED",
            "ACTIVE_TOUCHED",
            "MITIGATED",
            "INVALIDATED",
            "EXPIRED",
        }:
            raise ValueError("unknown lifecycle status")
        if str(pd.Timestamp(self.active_at).tz) != "UTC":
            raise ValueError("active_at must be explicit UTC")
        if (
            str(pd.Timestamp(self.expiry_deadline).tz) != "UTC"
            or self.expiry_deadline <= self.active_at
        ):
            raise ValueError("expiry_deadline must follow active_at in UTC")
        if self.touch_count < 0:
            raise ValueError("touch_count cannot be negative")
        for name in (
            "first_touch_timestamp",
            "mitigation_timestamp",
            "invalidation_timestamp",
            "expiry_timestamp",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            stamp = pd.Timestamp(value)
            if str(stamp.tz) != "UTC" or stamp < self.active_at:
                raise ValueError(f"{name} violates causal lifecycle ordering")
        terminal = sum(
            value is not None
            for value in (
                self.mitigation_timestamp,
                self.invalidation_timestamp,
                self.expiry_timestamp,
            )
        )
        if terminal > 1:
            raise ValueError("lifecycle terminal states must be mutually exclusive")
        if (self.first_touch_timestamp is None) != (self.touch_count == 0):
            raise ValueError("touch count and first-touch timestamp must agree")
        required_terminal = {
            "MITIGATED": self.mitigation_timestamp,
            "INVALIDATED": self.invalidation_timestamp,
            "EXPIRED": self.expiry_timestamp,
        }
        if self.status in required_terminal and required_terminal[self.status] is None:
            raise ValueError("terminal status requires its matching timestamp")
        if self.status in {"ACTIVE_UNTOUCHED", "ACTIVE_TOUCHED"} and terminal:
            raise ValueError("active status cannot have a terminal timestamp")
        if self.status == "ACTIVE_UNTOUCHED" and self.first_touch_timestamp is not None:
            raise ValueError("untouched status cannot have a touch")
        if self.status in {"ACTIVE_TOUCHED", "MITIGATED"} and self.first_touch_timestamp is None:
            raise ValueError("touched or mitigated status requires a first touch")
        if self.expiry_timestamp is not None and self.expiry_timestamp != self.expiry_deadline:
            raise ValueError("expiry timestamp must equal the frozen deadline")
        terminal_timestamps = tuple(
            value
            for value in (
                self.mitigation_timestamp,
                self.invalidation_timestamp,
                self.expiry_timestamp,
            )
            if value is not None
        )
        if (
            self.first_touch_timestamp is not None
            and terminal_timestamps
            and self.first_touch_timestamp > terminal_timestamps[0]
        ):
            raise ValueError("first touch cannot follow a terminal transition")


@dataclass(frozen=True)
class CombinedStructuralRecord:
    """Outcome-free one-to-one view over detector and lifecycle records."""

    block: RejectionBlock
    lifecycle: LifecycleRecord
    parent_active_at_availability: Optional[bool]

    def __post_init__(self) -> None:
        if self.block.block_id != self.lifecycle.block_id:
            raise ValueError("combined structural identities must match")
        if self.lifecycle.active_at != self.block.causal_availability:
            raise ValueError("combined lifecycle must begin at causal availability")
        if self.block.parent_block_id is None and self.parent_active_at_availability is not None:
            raise ValueError("a non-nested block has no parent activity state")
        if self.block.parent_block_id is not None and type(self.parent_active_at_availability) is not bool:
            raise ValueError("a nested block requires a parent activity state")
