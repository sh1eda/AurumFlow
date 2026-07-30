"""Causal feature and event detection for the D005 context engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .bars import TIMEFRAME_MINUTES, closed_bars_asof
from .config import (
    BalanceVariant,
    DisplacementVariant,
    MSSVariant,
    PremarketConfig,
    local_bounds,
)
from .models import Direction, EvidenceEvent


def _event_id(*parts: object) -> str:
    encoded = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _parameters(**values: object) -> dict[str, object]:
    """Normalize event parameters to stable JSON-compatible values."""

    return json.loads(json.dumps(values, sort_keys=True, default=str))


def true_range_and_prior_atr(
    bars: pd.DataFrame, *, lookback: int, min_periods: int
) -> pd.DataFrame:
    prior_close = bars["close"].shift(1)
    true_range = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - prior_close).abs(),
            (bars["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    prior_atr = true_range.shift(1).rolling(lookback, min_periods=min_periods).mean()
    return pd.DataFrame({"true_range": true_range, "prior_atr": prior_atr})


def confirmed_swings(bars: pd.DataFrame, *, width: int) -> pd.DataFrame:
    """Return pivots only at the close of their right-side confirmation bar."""

    if width < 1:
        raise ValueError("swing width must be positive")
    columns = ("pivot_at", "confirmation_at", "swing_type", "level", "width")
    window_size = 2 * width + 1
    if len(bars) < window_size:
        return pd.DataFrame.from_records((), columns=columns)
    highs = bars["high"].to_numpy(dtype=float, copy=False)
    lows = bars["low"].to_numpy(dtype=float, copy=False)
    high_windows = np.lib.stride_tricks.sliding_window_view(highs, window_size)
    low_windows = np.lib.stride_tricks.sliding_window_view(lows, window_size)
    high_centers = high_windows[:, width]
    low_centers = low_windows[:, width]
    high_mask = (
        (high_centers > high_windows[:, :width].max(axis=1))
        & (high_centers > high_windows[:, width + 1 :].max(axis=1))
    )
    low_mask = (
        (low_centers < low_windows[:, :width].min(axis=1))
        & (low_centers < low_windows[:, width + 1 :].min(axis=1))
    )
    available = pd.to_datetime(bars["available_at"], utc=True).array
    records: list[dict[str, object]] = []
    for window_position in range(len(high_windows)):
        position = window_position + width
        confirmation = pd.Timestamp(available[position + width])
        if high_mask[window_position]:
            records.append(
                {
                    "pivot_at": bars.index[position],
                    "confirmation_at": confirmation,
                    "swing_type": "high",
                    "level": float(highs[position]),
                    "width": width,
                }
            )
        if low_mask[window_position]:
            records.append(
                {
                    "pivot_at": bars.index[position],
                    "confirmation_at": confirmation,
                    "swing_type": "low",
                    "level": float(lows[position]),
                    "width": width,
                }
            )
    return pd.DataFrame.from_records(records, columns=columns)


def structure_direction(
    swings: pd.DataFrame, evaluation_at: pd.Timestamp
) -> tuple[Direction, dict[str, object]]:
    """Classify HH/HL, LH/LL, or neutral using only confirmed pivots."""

    if swings.empty:
        return Direction.NEUTRAL, {}
    cutoff = pd.Timestamp(evaluation_at).tz_convert("UTC")
    eligible = swings[
        pd.to_datetime(swings["confirmation_at"], utc=True).le(cutoff)
    ]
    highs = eligible[eligible["swing_type"].eq("high")].tail(2)
    lows = eligible[eligible["swing_type"].eq("low")].tail(2)
    if len(highs) < 2 or len(lows) < 2:
        return Direction.NEUTRAL, {}
    high_change = float(highs["level"].iloc[-1] - highs["level"].iloc[-2])
    low_change = float(lows["level"].iloc[-1] - lows["level"].iloc[-2])
    direction = (
        Direction.BULLISH
        if high_change > 0 and low_change > 0
        else Direction.BEARISH
        if high_change < 0 and low_change < 0
        else Direction.NEUTRAL
    )
    return direction, {
        "last_high": float(highs["level"].iloc[-1]),
        "last_low": float(lows["level"].iloc[-1]),
        "available_at": max(
            pd.Timestamp(highs["confirmation_at"].iloc[-1]),
            pd.Timestamp(lows["confirmation_at"].iloc[-1]),
        ),
    }


def detect_displacements(
    bars: pd.DataFrame,
    *,
    timeframe: str,
    variant: DisplacementVariant,
    evaluation_at: pd.Timestamp,
) -> tuple[EvidenceEvent, ...]:
    """Detect ATR/body displacement after its retracement check is observable."""

    causal = closed_bars_asof(bars, evaluation_at)
    measures = true_range_and_prior_atr(
        causal,
        lookback=variant.atr_lookback,
        min_periods=variant.atr_min_periods,
    )
    if causal.empty:
        return ()
    openings = causal["open"].to_numpy(dtype=float, copy=False)
    highs = causal["high"].to_numpy(dtype=float, copy=False)
    lows = causal["low"].to_numpy(dtype=float, copy=False)
    closes = causal["close"].to_numpy(dtype=float, copy=False)
    bar_ranges = highs - lows
    bodies = closes - openings
    prior_atrs = measures["prior_atr"].to_numpy(dtype=float, copy=False)
    true_ranges = measures["true_range"].to_numpy(dtype=float, copy=False)
    with np.errstate(divide="ignore", invalid="ignore"):
        body_fractions = np.abs(bodies) / bar_ranges
        atr_fractions = true_ranges / prior_atrs
    eligible = (
        np.isfinite(prior_atrs)
        & (prior_atrs > 0)
        & (bar_ranges > 0)
        & (bodies != 0)
        & (body_fractions >= variant.body_range_minimum)
        & (atr_fractions >= variant.true_range_atr_minimum)
    )
    retracement_bars = variant.immediate_retracement_bars
    final_positions = np.arange(len(causal)) + retracement_bars
    eligible &= final_positions < len(causal)
    adverse = np.zeros(len(causal), dtype=float)
    if retracement_bars:
        future_low = np.full(len(causal), np.inf)
        future_high = np.full(len(causal), -np.inf)
        for offset in range(1, retracement_bars + 1):
            valid_length = len(causal) - offset
            future_low[:valid_length] = np.minimum(
                future_low[:valid_length], lows[offset:]
            )
            future_high[:valid_length] = np.maximum(
                future_high[:valid_length], highs[offset:]
            )
        bullish = bodies > 0
        adverse[bullish] = np.maximum(
            0.0, closes[bullish] - future_low[bullish]
        )
        adverse[~bullish] = np.maximum(
            0.0, future_high[~bullish] - closes[~bullish]
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        retracements = adverse / np.abs(bodies)
    eligible &= retracements <= variant.maximum_immediate_retracement
    available = pd.DatetimeIndex(
        pd.to_datetime(causal["available_at"], utc=True)
    )
    events: list[EvidenceEvent] = []
    for position in np.flatnonzero(eligible):
        body = float(bodies[position])
        prior_atr = float(prior_atrs[position])
        body_fraction = float(body_fractions[position])
        atr_fraction = float(atr_fractions[position])
        retracement = float(retracements[position])
        direction = Direction.BULLISH if body > 0 else Direction.BEARISH
        end_position = int(final_positions[position])
        available_at = pd.Timestamp(available[end_position])
        events.append(
            EvidenceEvent(
                event_id=_event_id(
                    "displacement", timeframe, variant.name, causal.index[position]
                ),
                event_type="displacement",
                direction=direction,
                timeframe=timeframe,
                variant=variant.name,
                taxonomy="reaction_confirmation",
                created_at=causal.index[position],
                available_at=available_at,
                confirmed_at=available_at,
                source_rule_ids=("A13",),
                parameters=_parameters(
                    body_range_fraction=body_fraction,
                    true_range_atr=atr_fraction,
                    prior_atr=prior_atr,
                    immediate_retracement_fraction=retracement,
                    threshold_body_range=variant.body_range_minimum,
                    threshold_true_range_atr=variant.true_range_atr_minimum,
                    maximum_immediate_retracement=variant.maximum_immediate_retracement,
                    immediate_retracement_bars=variant.immediate_retracement_bars,
                ),
            )
        )
    return tuple(events)


def detect_mss(
    bars: pd.DataFrame,
    *,
    timeframe: str,
    variant: MSSVariant,
    evaluation_at: pd.Timestamp,
    start_at: pd.Timestamp | None = None,
) -> tuple[EvidenceEvent, ...]:
    """Detect body-close or wick MSS against a previously confirmed swing."""

    causal = closed_bars_asof(bars, evaluation_at)
    swings = confirmed_swings(causal, width=variant.pivot_width)
    events: list[EvidenceEvent] = []
    start = (
        pd.Timestamp(start_at).tz_convert("UTC")
        if start_at is not None
        else causal.index.min()
        if not causal.empty
        else pd.Timestamp(evaluation_at).tz_convert("UTC")
    )
    if causal.empty or swings.empty:
        return ()
    bar_times = causal.index.as_unit("ns").asi8
    available_times = pd.to_datetime(causal["available_at"], utc=True)
    available_ns = pd.DatetimeIndex(available_times).as_unit("ns").asi8
    start_ns = start.value
    closes = causal["close"].to_numpy(dtype=float, copy=False)
    highs = causal["high"].to_numpy(dtype=float, copy=False)
    lows = causal["low"].to_numpy(dtype=float, copy=False)
    for direction, swing_type in (
        (Direction.BULLISH, "high"),
        (Direction.BEARISH, "low"),
    ):
        candidates = swings[swings["swing_type"].eq(swing_type)].reset_index(
            drop=True
        )
        if candidates.empty:
            continue
        confirmations = pd.DatetimeIndex(
            pd.to_datetime(candidates["confirmation_at"], utc=True)
        ).as_unit("ns").asi8
        known_positions = np.searchsorted(confirmations, bar_times, side="right") - 1
        eligible = (known_positions >= 0) & (available_ns >= start_ns)
        safe_positions = np.maximum(known_positions, 0)
        levels = candidates["level"].to_numpy(dtype=float)[safe_positions]
        observed = (
            closes
            if variant.body_close_required
            else highs
            if direction == Direction.BULLISH
            else lows
        )
        broken = (
            observed > levels
            if direction == Direction.BULLISH
            else observed < levels
        )
        for position in np.flatnonzero(eligible & broken):
            pivot = candidates.iloc[int(known_positions[position])]
            level = float(pivot["level"])
            bar_at = causal.index[position]
            available_at = pd.Timestamp(available_times.iloc[position])
            events.append(
                EvidenceEvent(
                    event_id=_event_id(
                        "mss", timeframe, variant.name, direction, bar_at, level
                    ),
                    event_type="market_structure_shift",
                    direction=direction,
                    timeframe=timeframe,
                    variant=variant.name,
                    taxonomy="reaction_confirmation",
                    created_at=bar_at,
                    available_at=available_at,
                    confirmed_at=available_at,
                    source_rule_ids=("A11", "A12"),
                    parameters=_parameters(
                        pivot_width=variant.pivot_width,
                        body_close_required=variant.body_close_required,
                        broken_pivot_at=pivot["pivot_at"],
                        broken_pivot_confirmation=pivot["confirmation_at"],
                        confirmation_timeout_bars=variant.confirmation_timeout_bars,
                    ),
                    level=level,
                )
            )
    return tuple(events)


def detect_fvgs(
    bars: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_at: pd.Timestamp,
    minimum_width: float = 0.0,
) -> tuple[EvidenceEvent, ...]:
    """Detect raw three-candle wick non-overlap at the third bar close."""

    causal = closed_bars_asof(bars, evaluation_at)
    if len(causal) < 3:
        return ()
    highs = causal["high"].to_numpy(dtype=float, copy=False)
    lows = causal["low"].to_numpy(dtype=float, copy=False)
    bullish = highs[:-2] + minimum_width < lows[2:]
    bearish = lows[:-2] - minimum_width > highs[2:]
    positions = np.flatnonzero(bullish | bearish) + 2
    available = pd.DatetimeIndex(
        pd.to_datetime(causal["available_at"], utc=True)
    )
    events: list[EvidenceEvent] = []
    for position in positions:
        relative = position - 2
        if bullish[relative]:
            direction = Direction.BULLISH
            low, high = float(highs[position - 2]), float(lows[position])
        else:
            direction = Direction.BEARISH
            low, high = float(highs[position]), float(lows[position - 2])
        available_at = pd.Timestamp(available[position])
        events.append(
            EvidenceEvent(
                event_id=_event_id("fvg", timeframe, direction, causal.index[position]),
                event_type="raw_fvg",
                direction=direction,
                timeframe=timeframe,
                variant="three_candle_wick_nonoverlap",
                taxonomy="ict_fair_value_gap",
                created_at=causal.index[position],
                available_at=available_at,
                source_rule_ids=("A04",),
                parameters=_parameters(
                    minimum_width=minimum_width,
                    context_qualified=False,
                    liquidity_qualified=False,
                    mss_qualified=False,
                    displacement_qualified=False,
                    parent_aligned=False,
                    ifvg_wick_variant="ifvg_wick_violation",
                    ifvg_close_variant="ifvg_body_close_violation",
                ),
                zone_low=low,
                zone_high=high,
            )
        )
    return tuple(events)


def qualify_fvgs(
    fvgs: Sequence[EvidenceEvent],
    *,
    liquidity_events: Sequence[EvidenceEvent],
    mss_events: Sequence[EvidenceEvent],
    displacement_events: Sequence[EvidenceEvent],
    parent_direction: Direction,
    context_events: Sequence[EvidenceEvent] | None = None,
) -> tuple[EvidenceEvent, ...]:
    """Attach independent context flags without changing raw FVG geometry."""

    qualified: list[EvidenceEvent] = []
    qualifying_context = (
        tuple(context_events)
        if context_events is not None
        else tuple(liquidity_events)
    )
    for fvg in fvgs:
        available = pd.Timestamp(fvg.available_at)
        direction = fvg.direction
        prior_liquidity = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in liquidity_events
        )
        prior_mss = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in mss_events
        )
        prior_displacement = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in displacement_events
        )
        prior_context = any(
            event.direction == direction
            and pd.Timestamp(
                event.interacted_at
                if event.interacted_at is not None
                else event.available_at
            )
            <= available
            for event in qualifying_context
        )
        parent_aligned = parent_direction in (Direction.NEUTRAL, direction)
        flags = {
            **fvg.parameters,
            "liquidity_qualified": prior_liquidity,
            "mss_qualified": prior_mss,
            "displacement_qualified": prior_displacement,
            "candidate_context_qualified": prior_context,
            "parent_aligned": parent_aligned,
            "context_qualified": (
                prior_context and prior_mss and prior_displacement and parent_aligned
            ),
            "source_a05_high_probability_variant": (
                prior_liquidity
                and prior_mss
                and prior_displacement
                and parent_aligned
            ),
        }
        qualified.append(
            replace(
                fvg,
                parameters=flags,
                confirmed_at=available if flags["context_qualified"] else None,
            )
        )
    return tuple(qualified)


def detect_order_blocks(
    bars: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_at: pd.Timestamp,
    displacement_events: Sequence[EvidenceEvent],
    fvg_events: Sequence[EvidenceEvent],
    lookback_bars: int,
) -> tuple[EvidenceEvent, ...]:
    """Emit the three approved OB variants as independent records."""

    causal = closed_bars_asof(bars, evaluation_at)
    by_created = {pd.Timestamp(event.created_at): event for event in displacement_events}
    fvg_keys = {
        (pd.Timestamp(event.created_at), event.direction) for event in fvg_events
    }
    events: list[EvidenceEvent] = []
    for position, bar_at in enumerate(causal.index):
        displacement = by_created.get(pd.Timestamp(bar_at))
        if displacement is None or position == 0:
            continue
        direction = displacement.direction
        start = max(0, position - lookback_bars)
        prior = causal.iloc[start:position]
        if prior.empty:
            continue
        opposite = (
            prior["close"].lt(prior["open"])
            if direction == Direction.BULLISH
            else prior["close"].gt(prior["open"])
        )

        consecutive_positions: list[int] = []
        for local_position in range(len(prior) - 1, -1, -1):
            if not bool(opposite.iloc[local_position]):
                break
            consecutive_positions.append(local_position)
        if consecutive_positions:
            block = prior.iloc[sorted(consecutive_positions)]
            events.append(
                _ob_event(
                    variant="consecutive_block",
                    taxonomy="ict_order_block",
                    timeframe=timeframe,
                    direction=direction,
                    origin_at=block.index[0],
                    available_at=displacement.available_at,
                    zone_low=float(block["low"].min()),
                    zone_high=float(block["high"].max()),
                    parameters={
                        "candle_count": len(block),
                        "displacement_event_id": displacement.event_id,
                    },
                )
            )

        opposite_rows = prior.loc[opposite]
        if not opposite_rows.empty:
            origin = opposite_rows.iloc[-1]
            origin_at = opposite_rows.index[-1]
            events.append(
                _ob_event(
                    variant="last_opposing_candle",
                    taxonomy="ict_order_block",
                    timeframe=timeframe,
                    direction=direction,
                    origin_at=origin_at,
                    available_at=displacement.available_at,
                    zone_low=float(origin["low"]),
                    zone_high=float(origin["high"]),
                    parameters={
                        "displacement_event_id": displacement.event_id,
                        "search_lookback_bars": lookback_bars,
                    },
                )
            )

        has_fvg = (pd.Timestamp(bar_at), direction) in fvg_keys
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        broke = (
            float(causal.iloc[position]["close"]) > prior_high
            if direction == Direction.BULLISH
            else float(causal.iloc[position]["close"]) < prior_low
        )
        if has_fvg and broke:
            origin = prior.iloc[-1]
            events.append(
                _ob_event(
                    variant="inefficiency_break_origin",
                    taxonomy="smc_supply_demand_zone",
                    timeframe=timeframe,
                    direction=direction,
                    origin_at=prior.index[-1],
                    available_at=displacement.available_at,
                    zone_low=float(origin["low"]),
                    zone_high=float(origin["high"]),
                    parameters={
                        "displacement_event_id": displacement.event_id,
                        "fvg_created_with_impulse": True,
                        "structure_or_zone_break": True,
                        "origin_candle_may_share_impulse_direction": True,
                    },
                )
            )
    unique = {event.event_id: event for event in events}
    return tuple(unique.values())


def qualify_order_blocks(
    order_blocks: Sequence[EvidenceEvent],
    *,
    liquidity_events: Sequence[EvidenceEvent],
    mss_events: Sequence[EvidenceEvent],
    displacement_events: Sequence[EvidenceEvent],
    parent_direction: Direction,
    context_events: Sequence[EvidenceEvent] | None = None,
) -> tuple[EvidenceEvent, ...]:
    """Attach auditable context flags without merging OB variants."""

    qualified: list[EvidenceEvent] = []
    qualifying_context = (
        tuple(context_events)
        if context_events is not None
        else tuple(liquidity_events)
    )
    for order_block in order_blocks:
        available = pd.Timestamp(order_block.available_at)
        direction = order_block.direction
        prior_liquidity = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in liquidity_events
        )
        prior_mss = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in mss_events
        )
        prior_displacement = any(
            event.direction == direction
            and pd.Timestamp(event.available_at) <= available
            for event in displacement_events
        )
        prior_context = any(
            event.direction == direction
            and pd.Timestamp(
                event.interacted_at
                if event.interacted_at is not None
                else event.available_at
            )
            <= available
            for event in qualifying_context
        )
        parent_aligned = parent_direction in (Direction.NEUTRAL, direction)
        context_qualified = bool(
            prior_context
            and prior_mss
            and prior_displacement
            and parent_aligned
        )
        flags = {
            **order_block.parameters,
            "raw_detected": True,
            "liquidity_qualified": prior_liquidity,
            "mss_qualified": prior_mss,
            "displacement_qualified": prior_displacement,
            "candidate_context_qualified": prior_context,
            "parent_aligned": parent_aligned,
            "context_qualified": context_qualified,
            "source_a08_liquidity_supported_variant": bool(
                prior_liquidity
                and prior_mss
                and prior_displacement
                and parent_aligned
            ),
        }
        qualified.append(
            replace(
                order_block,
                parameters=flags,
                confirmed_at=available if context_qualified else None,
            )
        )
    return tuple(qualified)


def _ob_event(
    *,
    variant: str,
    taxonomy: str,
    timeframe: str,
    direction: Direction,
    origin_at: pd.Timestamp,
    available_at: pd.Timestamp,
    zone_low: float,
    zone_high: float,
    parameters: dict[str, object],
) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=_event_id("ob", variant, timeframe, direction, origin_at, available_at),
        event_type="order_block",
        direction=direction,
        timeframe=timeframe,
        variant=variant,
        taxonomy=taxonomy,
        created_at=pd.Timestamp(origin_at),
        available_at=pd.Timestamp(available_at),
        source_rule_ids=("A07", "A08"),
        parameters=_parameters(
            **parameters,
            raw_detected=True,
            liquidity_qualified=False,
            mss_qualified=False,
            displacement_qualified=False,
            candidate_context_qualified=False,
            parent_aligned=False,
            context_qualified=False,
            source_a08_liquidity_supported_variant=False,
        ),
        zone_low=zone_low,
        zone_high=zone_high,
    )


def apply_zone_interactions(
    events: Sequence[EvidenceEvent],
    bars: pd.DataFrame,
    *,
    evaluation_at: pd.Timestamp,
) -> tuple[EvidenceEvent, ...]:
    """Record first causal interaction and body-close invalidation per zone."""

    causal = closed_bars_asof(bars, evaluation_at)
    available = pd.DatetimeIndex(
        pd.to_datetime(causal["available_at"], utc=True)
    )
    available_ns = available.as_unit("ns").asi8
    highs = causal["high"].to_numpy(dtype=float, copy=False)
    lows = causal["low"].to_numpy(dtype=float, copy=False)
    closes = causal["close"].to_numpy(dtype=float, copy=False)
    result: list[EvidenceEvent] = []
    for event in events:
        if event.zone_low is None or event.zone_high is None:
            result.append(event)
            continue
        start = int(
            np.searchsorted(
                available_ns, pd.Timestamp(event.available_at).value, side="right"
            )
        )
        interacted: pd.Timestamp | None = None
        invalidated: pd.Timestamp | None = None
        overlap_positions = np.flatnonzero(
            (highs[start:] >= float(event.zone_low))
            & (lows[start:] <= float(event.zone_high))
        )
        failure_positions = np.flatnonzero(
            closes[start:] < float(event.zone_low)
            if event.direction == Direction.BULLISH
            else closes[start:] > float(event.zone_high)
        )
        interaction_position = (
            start + int(overlap_positions[0]) if overlap_positions.size else None
        )
        failure_position = (
            start + int(failure_positions[0]) if failure_positions.size else None
        )
        # An invalidation ends the active path; a later overlap is not a valid
        # interaction with the already-failed zone.
        if interaction_position is not None and (
            failure_position is None or interaction_position <= failure_position
        ):
            interacted = pd.Timestamp(available[interaction_position])
        if failure_position is not None:
            invalidated = pd.Timestamp(available[failure_position])
        result.append(
            replace(
                event,
                interacted_at=interacted,
                invalidated_at=invalidated,
            )
        )
    return tuple(result)


def swing_liquidity_levels(
    swings: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_at: pd.Timestamp,
) -> tuple[EvidenceEvent, ...]:
    cutoff = pd.Timestamp(evaluation_at).tz_convert("UTC")
    events: list[EvidenceEvent] = []
    for _, row in swings.iterrows():
        available = pd.Timestamp(row["confirmation_at"])
        if available > cutoff:
            continue
        is_high = row["swing_type"] == "high"
        events.append(
            EvidenceEvent(
                event_id=_event_id(
                    "liquidity_level", timeframe, row["swing_type"], row["pivot_at"]
                ),
                event_type="liquidity_level",
                direction=Direction.BEARISH if is_high else Direction.BULLISH,
                timeframe=timeframe,
                variant="confirmed_swing",
                taxonomy="buy_side_liquidity" if is_high else "sell_side_liquidity",
                created_at=pd.Timestamp(row["pivot_at"]),
                available_at=available,
                source_rule_ids=("A09",),
                parameters=_parameters(
                    pivot_width=int(row["width"]),
                    side="high" if is_high else "low",
                ),
                level=float(row["level"]),
            )
        )
    return tuple(events)


def equal_liquidity_levels(
    swings: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_at: pd.Timestamp,
    atr: float,
    tolerance_atr: float,
) -> tuple[EvidenceEvent, ...]:
    """Build causal equal-high/low clusters from adjacent confirmed pivots."""

    if not np.isfinite(atr) or atr <= 0 or tolerance_atr < 0:
        return ()
    cutoff = pd.Timestamp(evaluation_at).tz_convert("UTC")
    eligible = swings[
        pd.to_datetime(swings["confirmation_at"], utc=True).le(cutoff)
    ]
    events: list[EvidenceEvent] = []
    tolerance = atr * tolerance_atr
    for swing_type in ("high", "low"):
        candidates = eligible[eligible["swing_type"].eq(swing_type)]
        for position in range(1, len(candidates)):
            first = candidates.iloc[position - 1]
            second = candidates.iloc[position]
            if abs(float(second["level"]) - float(first["level"])) > tolerance:
                continue
            available = max(
                pd.Timestamp(first["confirmation_at"]),
                pd.Timestamp(second["confirmation_at"]),
            )
            is_high = swing_type == "high"
            events.append(
                EvidenceEvent(
                    event_id=_event_id(
                        "equal_liquidity",
                        timeframe,
                        swing_type,
                        first["pivot_at"],
                        second["pivot_at"],
                        tolerance_atr,
                    ),
                    event_type="liquidity_level",
                    direction=Direction.BEARISH if is_high else Direction.BULLISH,
                    timeframe=timeframe,
                    variant="adjacent_confirmed_pivots_atr_tolerance",
                    taxonomy=(
                        "equal_high_liquidity"
                        if is_high
                        else "equal_low_liquidity"
                    ),
                    created_at=pd.Timestamp(second["pivot_at"]),
                    available_at=available,
                    source_rule_ids=("A09",),
                    parameters=_parameters(
                        first_pivot_at=first["pivot_at"],
                        second_pivot_at=second["pivot_at"],
                        atr=atr,
                        tolerance_atr=tolerance_atr,
                        absolute_tolerance=tolerance,
                    ),
                    level=(
                        float(first["level"]) + float(second["level"])
                    )
                    / 2.0,
                )
            )
    return tuple(events)


def detect_liquidity_sweeps(
    levels: Sequence[EvidenceEvent],
    bars: pd.DataFrame,
    *,
    timeframe: str,
    evaluation_at: pd.Timestamp,
    penetration: float,
    require_reclaim: bool,
) -> tuple[EvidenceEvent, ...]:
    causal = closed_bars_asof(bars, evaluation_at)
    available = pd.DatetimeIndex(
        pd.to_datetime(causal["available_at"], utc=True)
    )
    available_ns = available.as_unit("ns").asi8
    highs = causal["high"].to_numpy(dtype=float, copy=False)
    lows = causal["low"].to_numpy(dtype=float, copy=False)
    closes = causal["close"].to_numpy(dtype=float, copy=False)
    sweeps: list[EvidenceEvent] = []
    for level in levels:
        if level.level is None:
            continue
        start = int(
            np.searchsorted(
                available_ns, pd.Timestamp(level.available_at).value, side="right"
            )
        )
        is_high = level.taxonomy in {
            "buy_side_liquidity",
            "equal_high_liquidity",
            "premarket_high",
        }
        penetrated = (
            highs[start:] >= level.level + penetration
            if is_high
            else lows[start:] <= level.level - penetration
        )
        reclaimed = (
            closes[start:] < level.level
            if is_high
            else closes[start:] > level.level
        )
        matched = penetrated & reclaimed if require_reclaim else penetrated
        positions = np.flatnonzero(matched)
        if positions.size:
            position = start + int(positions[0])
            bar_at = causal.index[position]
            available_at = pd.Timestamp(available[position])
            sweeps.append(
                EvidenceEvent(
                    event_id=_event_id(
                        "sweep", level.event_id, timeframe, bar_at, penetration
                    ),
                    event_type="liquidity_sweep",
                    direction=level.direction,
                    timeframe=timeframe,
                    variant="penetration_body_reclaim"
                    if require_reclaim
                    else "penetration_only",
                    taxonomy=level.taxonomy,
                    created_at=bar_at,
                    available_at=available_at,
                    interacted_at=available_at,
                    source_rule_ids=("A10",),
                    parameters=_parameters(
                        level_event_id=level.event_id,
                        penetration=penetration,
                        reclaim_required=require_reclaim,
                        reclaimed=bool(reclaimed[position - start]),
                    ),
                    level=level.level,
                )
            )
    return tuple(sweeps)


def premarket_levels(
    one_minute: pd.DataFrame,
    *,
    session_date: date,
    config: PremarketConfig,
) -> tuple[tuple[EvidenceEvent, ...], dict[str, object]]:
    """Build PMH/PML from the configurable DST-safe half-open interval."""

    left, right = local_bounds(session_date, config.start, config.end, config.timezone)
    completed = one_minute[
        (one_minute.index >= left)
        & (one_minute.index < right)
        & pd.to_datetime(one_minute["available_at"], utc=True).le(right)
    ]
    expected = int((right - left).total_seconds() // 60)
    coverage = len(completed) / expected if expected else 0.0
    metadata = {
        "left_utc": left,
        "right_utc": right,
        "expected_minutes": expected,
        "observed_minutes": int(len(completed)),
        "coverage": coverage,
        "complete": coverage >= config.minimum_coverage,
    }
    if completed.empty or coverage < config.minimum_coverage:
        return (), metadata
    common = {
        "timeframe": "1min",
        "variant": "0000_0830_new_york",
        "created_at": left,
        "available_at": right,
        "source_rule_ids": ("B06", "C07"),
        "parameters": _parameters(
            timezone=config.timezone,
            start=config.start,
            end=config.end,
            interval_semantics="[start,end)",
            coverage=coverage,
            research_only=True,
            independent_bias=False,
        ),
    }
    high = EvidenceEvent(
        event_id=_event_id("pmh", session_date, config.start, config.end),
        event_type="premarket_level",
        direction=Direction.BEARISH,
        taxonomy="premarket_high",
        level=float(completed["high"].max()),
        **common,
    )
    low = EvidenceEvent(
        event_id=_event_id("pml", session_date, config.start, config.end),
        event_type="premarket_level",
        direction=Direction.BULLISH,
        taxonomy="premarket_low",
        level=float(completed["low"].min()),
        **common,
    )
    return (high, low), metadata


def classify_balanced(
    bars: pd.DataFrame,
    *,
    evaluation_at: pd.Timestamp,
    variant: BalanceVariant,
) -> dict[str, object]:
    causal = closed_bars_asof(bars, evaluation_at).tail(variant.lookback_bars)
    if len(causal) < variant.lookback_bars:
        return {
            "balanced": False,
            "reason": "insufficient_balance_history",
            "range_high": math.nan,
            "range_low": math.nan,
        }
    changes = causal["close"].diff().abs().dropna()
    path = float(changes.sum())
    efficiency = (
        abs(float(causal["close"].iloc[-1] - causal["close"].iloc[0])) / path
        if path > 0
        else 0.0
    )
    measures = true_range_and_prior_atr(
        causal,
        lookback=min(variant.lookback_bars - 1, 14),
        min_periods=min(10, variant.lookback_bars - 1),
    )
    atr = float(measures["true_range"].iloc[:-1].mean())
    range_high = float(causal["high"].max())
    range_low = float(causal["low"].min())
    range_atr = (range_high - range_low) / atr if atr > 0 else math.inf
    tolerance = max((range_high - range_low) * 0.10, 1e-12)
    high_touches = int(causal["high"].ge(range_high - tolerance).sum())
    low_touches = int(causal["low"].le(range_low + tolerance).sum())
    range_like = bool(
        efficiency <= variant.maximum_efficiency_ratio
        and range_atr <= variant.maximum_range_atr
    )
    boundaries_resolved = bool(
        high_touches >= variant.minimum_boundary_touches
        and low_touches >= variant.minimum_boundary_touches
        and range_high > range_low
    )
    balanced = range_like and boundaries_resolved
    return {
        "balanced": balanced,
        "reason": "qualified" if balanced else "threshold_failure",
        "range_high": range_high,
        "range_low": range_low,
        "efficiency_ratio": efficiency,
        "range_atr": range_atr,
        "high_touches": high_touches,
        "low_touches": low_touches,
        "range_like": range_like,
        "boundaries_resolved": boundaries_resolved,
        "variant": variant.name,
    }


def trapped_between_opposing_arrays(
    *,
    price: float,
    atr: float,
    events: Sequence[EvidenceEvent],
    maximum_distance_atr: float,
) -> bool:
    if not np.isfinite(atr) or atr <= 0:
        return False
    active = [
        event
        for event in events
        if event.zone_low is not None
        and event.zone_high is not None
        and event.invalidated_at is None
    ]
    bullish_below = [
        event
        for event in active
        if event.direction == Direction.BULLISH
        and float(event.zone_high) <= price
        and (price - float(event.zone_high)) / atr <= maximum_distance_atr
    ]
    bearish_above = [
        event
        for event in active
        if event.direction == Direction.BEARISH
        and float(event.zone_low) >= price
        and (float(event.zone_low) - price) / atr <= maximum_distance_atr
    ]
    return bool(bullish_below and bearish_above)


def latest_prior_atr(
    bars: pd.DataFrame,
    *,
    evaluation_at: pd.Timestamp,
    lookback: int = 14,
    min_periods: int = 10,
) -> float:
    causal = closed_bars_asof(bars, evaluation_at)
    if causal.empty:
        return math.nan
    measures = true_range_and_prior_atr(
        causal, lookback=lookback, min_periods=min_periods
    )
    value = measures["prior_atr"].iloc[-1]
    return float(value) if pd.notna(value) else math.nan


def events_as_records(events: Iterable[EvidenceEvent]) -> list[dict[str, object]]:
    return [event.to_record() for event in events]
