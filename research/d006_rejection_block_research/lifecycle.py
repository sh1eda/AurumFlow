"""Separate causal lifecycle state for detected structural blocks."""

from __future__ import annotations

import pandas as pd

from .config import D006Config
from .models import CombinedStructuralRecord, Direction, LifecycleRecord, RejectionBlock
from .schemas import validate_bars


def evaluate_lifecycle(block: RejectionBlock, bars: pd.DataFrame, evaluation_at: object, config: D006Config = D006Config()) -> LifecycleRecord:
    """Apply the fixed invalidation, mitigation, touch, expiry precedence."""

    cutoff = pd.Timestamp(evaluation_at)
    if str(cutoff.tz) != "UTC":
        raise ValueError("lifecycle evaluation timestamp must be explicit UTC")
    if cutoff < block.causal_availability:
        raise ValueError("lifecycle evaluation cannot precede causal availability")
    bars = validate_bars(bars, evaluation_at)
    expiry_at = block.causal_availability + pd.Timedelta(hours=config.lifecycle_expiry_hours)
    first_touch = mitigation = invalidation = expiry = None
    touches = 0
    status = "ACTIVE_UNTOUCHED"
    start = bars.index.searchsorted(block.causal_availability, side="left")
    # No lifecycle transition after the first bar whose availability exceeds
    # expiry can affect the registered state.  Bound the historical scan while
    # preserving the exact precedence used by the synthetic implementation.
    stop = bars.index.searchsorted(expiry_at, side="right") + 1
    eligible = bars.iloc[start:min(stop, len(bars))]
    for timestamp, row in eligible.iterrows():
        available_at = row.available_at
        if available_at > cutoff:
            break
        if available_at > expiry_at:
            expiry, status = expiry_at, "EXPIRED"
            break
        invalid = row.close < block.distal if block.direction is Direction.BULLISH else row.close > block.distal
        midpoint_reached = row.low <= block.midpoint if block.direction is Direction.BULLISH else row.high >= block.midpoint
        lower, upper = sorted((block.distal, block.proximal))
        zone_overlap = row.low <= upper and row.high >= lower
        if invalid:
            invalidation, status = available_at, "INVALIDATED"
            break
        if midpoint_reached:
            mitigation, status = available_at, "MITIGATED"
            first_touch = first_touch or available_at
            touches += 1
            break
        if zone_overlap:
            touches += 1
            if first_touch is None:
                first_touch = available_at
            status = "ACTIVE_TOUCHED"
        if available_at >= expiry_at:
            expiry, status = expiry_at, "EXPIRED"
            break
    if status in {"ACTIVE_UNTOUCHED", "ACTIVE_TOUCHED"} and cutoff >= expiry_at:
        expiry, status = expiry_at, "EXPIRED"
    return LifecycleRecord(
        block.block_id,
        status,
        block.causal_availability,
        first_touch,
        mitigation,
        invalidation,
        expiry,
        expiry_at,
        touches,
    )


def combine_structural_records(
    blocks: list[RejectionBlock], lifecycle_records: list[LifecycleRecord]
) -> list[CombinedStructuralRecord]:
    """Join detector/lifecycle identities without adding outcomes or statistics."""

    block_ids = [block.block_id for block in blocks]
    lifecycle_ids = [record.block_id for record in lifecycle_records]
    if len(block_ids) != len(set(block_ids)) or len(lifecycle_ids) != len(set(lifecycle_ids)):
        raise ValueError("combined structural inputs require unique identities")
    if set(block_ids) != set(lifecycle_ids):
        raise ValueError("detector and lifecycle identities must reconcile one-to-one")
    lifecycle_by_id = {record.block_id: record for record in lifecycle_records}
    combined: list[CombinedStructuralRecord] = []
    for block in blocks:
        parent_active: bool | None = None
        if block.parent_block_id is not None:
            if block.parent_block_id not in lifecycle_by_id:
                raise ValueError("nested block requires its parent lifecycle record")
            parent = lifecycle_by_id[block.parent_block_id]
            terminal = next(
                (
                    value
                    for value in (
                        parent.mitigation_timestamp,
                        parent.invalidation_timestamp,
                        parent.expiry_timestamp,
                    )
                    if value is not None
                ),
                None,
            )
            parent_active = (
                parent.active_at <= block.causal_availability
                and (terminal is None or terminal > block.causal_availability)
            )
        combined.append(
            CombinedStructuralRecord(block, lifecycle_by_id[block.block_id], parent_active)
        )
    return combined
