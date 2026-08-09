"""Deterministic D007 lifecycle and first-touch accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .models import ClosedBar, Direction, OTERange


LIFECYCLE_STATES = (
    "AVAILABLE",
    "TOUCHED_ACTIVE",
    "INVALIDATED",
    "EXPIRED",
)


def primary_lifecycle_eligible(ote_range: OTERange) -> bool:
    """Pre-availability interaction is retained for audit but excluded."""

    return not ote_range.preavailability_interaction


@dataclass(frozen=True)
class LifecycleRecord:
    range_id: str
    status: str
    available_at: pd.Timestamp
    first_touch_at: pd.Timestamp | None
    invalidated_at: pd.Timestamp | None
    expired_at: pd.Timestamp | None
    expiry_deadline: pd.Timestamp
    touch_count: int
    repeated_touch_count: int

    def __post_init__(self) -> None:
        if self.status not in LIFECYCLE_STATES:
            raise ValueError("unknown D007 lifecycle state")
        if self.touch_count < 0 or self.repeated_touch_count != max(0, self.touch_count - 1):
            raise ValueError("D007 touch counts do not reconcile")
        if self.touch_count == 0 and self.first_touch_at is not None:
            raise ValueError("first touch requires a touch count")
        if self.touch_count > 0 and self.first_touch_at is None:
            raise ValueError("touch count requires first-touch timestamp")


def _invalidation(ote_range: OTERange, bar: ClosedBar) -> bool:
    return (
        bar.close < ote_range.invalidation_price
        if ote_range.direction == Direction.BULLISH
        else bar.close > ote_range.invalidation_price
    )


def _touch(ote_range: OTERange, bar: ClosedBar) -> bool:
    return bar.low <= ote_range.zone_high and bar.high >= ote_range.zone_low


def evaluate_lifecycle(
    ote_range: OTERange,
    bars: Iterable[ClosedBar],
    evaluation_at: pd.Timestamp | str,
) -> LifecycleRecord:
    """Apply expiry, invalidation, and inclusive touch precedence in that order."""

    cutoff = pd.Timestamp(evaluation_at)
    if cutoff.tz is None:
        raise ValueError("evaluation timestamp must be timezone-aware")
    cutoff = cutoff.tz_convert("UTC")
    if cutoff < ote_range.range_available_at:
        raise ValueError("lifecycle evaluation cannot precede range availability")
    ordered = tuple(sorted(bars, key=lambda item: (item.available_at, item.bar_id)))
    if len({item.bar_id for item in ordered}) != len(ordered):
        raise ValueError("lifecycle bar IDs must be unique")
    if len({item.available_at for item in ordered}) != len(ordered):
        raise ValueError("lifecycle availability timestamps must be unique")
    first_touch: pd.Timestamp | None = None
    invalidated: pd.Timestamp | None = None
    touch_count = 0
    expired: pd.Timestamp | None = None
    expected_open = ote_range.range_available_at
    last_available = ote_range.range_available_at
    for bar in ordered:
        if bar.available_at > cutoff:
            break
        if bar.opened_at < ote_range.range_available_at:
            continue
        if bar.opened_at != expected_open or bar.available_at - bar.opened_at != pd.Timedelta(
            minutes=5
        ):
            raise ValueError("D007 lifecycle has missing or non-five-minute bars")
        if not bar.is_complete:
            raise ValueError("D007 lifecycle excludes incomplete bars")
        expected_open = bar.available_at
        last_available = bar.available_at
        if bar.available_at >= ote_range.expiry_deadline:
            expired = ote_range.expiry_deadline
            break
        if _invalidation(ote_range, bar):
            invalidated = bar.available_at
            break
        if _touch(ote_range, bar):
            touch_count += 1
            if first_touch is None:
                first_touch = bar.available_at
    if (
        invalidated is None
        and expired is None
        and cutoff > ote_range.range_available_at
        and cutoff < ote_range.expiry_deadline
        and last_available != cutoff
    ):
        raise ValueError("D007 lifecycle is incomplete through evaluation timestamp")
    if invalidated is not None:
        status = "INVALIDATED"
    elif expired is not None or cutoff >= ote_range.expiry_deadline:
        status = "EXPIRED"
        expired = ote_range.expiry_deadline
    elif first_touch is not None:
        status = "TOUCHED_ACTIVE"
    else:
        status = "AVAILABLE"
    return LifecycleRecord(
        range_id=ote_range.range_id,
        status=status,
        available_at=ote_range.range_available_at,
        first_touch_at=first_touch,
        invalidated_at=invalidated,
        expired_at=expired,
        expiry_deadline=ote_range.expiry_deadline,
        touch_count=touch_count,
        repeated_touch_count=max(0, touch_count - 1),
    )
