"""Immutable D007 synthetic structural models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import IntEnum
from hashlib import sha256
import math
from typing import Iterable

import pandas as pd

from .config import GeometryDefinition


class Direction(IntEnum):
    BEARISH = -1
    BULLISH = 1


def _utc(value: pd.Timestamp | str, field: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tz is None:
        raise ValueError(f"{field} must be timezone-aware")
    return stamp.tz_convert("UTC")


def stable_id(*parts: object) -> str:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    return sha256(material).hexdigest()[:24]


@dataclass(frozen=True)
class ClosedBar:
    bar_id: str
    opened_at: pd.Timestamp
    available_at: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    is_complete: bool = True

    def __post_init__(self) -> None:
        opened = _utc(self.opened_at, "opened_at")
        available = _utc(self.available_at, "available_at")
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "available_at", available)
        if not self.bar_id:
            raise ValueError("bar_id is required")
        if available <= opened:
            raise ValueError("bar availability must follow bar open")
        if not all(math.isfinite(value) for value in (self.open, self.high, self.low, self.close)):
            raise ValueError("bar OHLC values must be finite")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar violates OHLC bounds")
        if self.high < self.low:
            raise ValueError("bar high cannot be below low")


@dataclass(frozen=True)
class FrozenDisplacementAnchor:
    upstream_event_id: str
    direction: Direction
    displacement_created_at: pd.Timestamp
    displacement_available_at: pd.Timestamp
    origin_swing_at: pd.Timestamp
    origin_confirmed_at: pd.Timestamp
    origin_price: float
    mapping_name: str = "1h_5m"

    def __post_init__(self) -> None:
        for field in (
            "displacement_created_at",
            "displacement_available_at",
            "origin_swing_at",
            "origin_confirmed_at",
        ):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if not self.upstream_event_id:
            raise ValueError("upstream event ID is required")
        if self.mapping_name != "1h_5m":
            raise ValueError("D007 primary anchor requires frozen 1h_5m mapping")
        if self.origin_swing_at > self.origin_confirmed_at:
            raise ValueError("swing confirmation cannot precede its pivot")
        if self.origin_confirmed_at > self.displacement_created_at:
            raise ValueError("range origin must be confirmed before displacement creation")
        if self.displacement_created_at >= self.displacement_available_at:
            raise ValueError("displacement availability must follow creation")
        if not math.isfinite(self.origin_price):
            raise ValueError("range origin price must be finite")


@dataclass(frozen=True)
class OTERange:
    range_id: str
    upstream_event_id: str
    geometry_id: str
    direction: Direction
    origin_price: float
    endpoint_price: float
    origin_at: pd.Timestamp
    origin_available_at: pd.Timestamp
    endpoint_at: pd.Timestamp
    range_available_at: pd.Timestamp
    proximal: float
    reference: float
    distal: float
    equilibrium: float
    zone_low: float
    zone_high: float
    invalidation_price: float
    expiry_deadline: pd.Timestamp
    source_bar_ids: tuple[str, ...]
    preavailability_interaction: bool
    overlap_group_id: str | None = None
    parent_range_id: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "origin_at",
            "origin_available_at",
            "endpoint_at",
            "range_available_at",
            "expiry_deadline",
        ):
            object.__setattr__(self, field, _utc(getattr(self, field), field))
        if self.origin_available_at > self.range_available_at:
            raise ValueError("range cannot predate origin confirmation")
        if self.endpoint_at >= self.range_available_at:
            raise ValueError("range is available only after its endpoint bar closes")
        if self.expiry_deadline != self.range_available_at + timedelta(hours=24):
            raise ValueError("D007 expiry is fixed at 24 elapsed UTC hours")
        if not self.zone_low <= self.zone_high:
            raise ValueError("zone bounds are unordered")
        if not all(
            math.isfinite(value)
            for value in (
                self.origin_price,
                self.endpoint_price,
                self.proximal,
                self.reference,
                self.distal,
                self.equilibrium,
                self.zone_low,
                self.zone_high,
                self.invalidation_price,
            )
        ):
            raise ValueError("D007 range prices must be finite")
        if self.direction == Direction.BULLISH and self.endpoint_price <= self.origin_price:
            raise ValueError("bullish range must rise from origin to endpoint")
        if self.direction == Direction.BEARISH and self.endpoint_price >= self.origin_price:
            raise ValueError("bearish range must fall from origin to endpoint")
        if not self.source_bar_ids:
            raise ValueError("range source bars are required")

    @property
    def magnitude(self) -> float:
        return abs(self.endpoint_price - self.origin_price)


def attach_relationships(ranges: Iterable[OTERange]) -> tuple[OTERange, ...]:
    """Attach deterministic same-direction closed-overlap and nesting identities."""

    ordered = sorted(
        ranges,
        key=lambda item: (
            item.range_available_at,
            item.upstream_event_id,
            item.geometry_id,
            item.range_id,
        ),
    )
    result = list(ordered)
    for direction in Direction:
        positions = [index for index, item in enumerate(result) if item.direction == direction]
        if not positions:
            continue
        parent = {position: position for position in positions}

        def root(position: int) -> int:
            while parent[position] != position:
                parent[position] = parent[parent[position]]
                position = parent[position]
            return position

        def union(left: int, right: int) -> None:
            left_root, right_root = root(left), root(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        for offset, left in enumerate(positions):
            for right in positions[offset + 1 :]:
                a, b = result[left], result[right]
                if max(a.zone_low, b.zone_low) <= min(a.zone_high, b.zone_high):
                    union(left, right)
        components: dict[int, list[int]] = {}
        for position in positions:
            components.setdefault(root(position), []).append(position)
        for members in components.values():
            group_material = tuple(sorted(result[position].range_id for position in members))
            group_id = stable_id("d007-overlap", *group_material) if len(members) > 1 else None
            for position in members:
                child = result[position]
                containers = [
                    result[other]
                    for other in members
                    if other != position
                    and result[other].zone_low <= child.zone_low
                    and result[other].zone_high >= child.zone_high
                    and (
                        result[other].zone_low < child.zone_low
                        or result[other].zone_high > child.zone_high
                    )
                ]
                parent_id = (
                    min(containers, key=lambda item: (item.zone_high - item.zone_low, item.range_id)).range_id
                    if containers
                    else None
                )
                result[position] = replace(
                    child,
                    overlap_group_id=group_id,
                    parent_range_id=parent_id,
                )
    return tuple(result)
