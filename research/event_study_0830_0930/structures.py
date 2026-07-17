from __future__ import annotations

import math

import pandas as pd

from .config import StudyConfig


def aggregate_structure_bars(prices: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate closed one-minute bars without crossing New York calendar days."""

    if minutes not in {1, 3}:
        raise ValueError("Registered structure scales are one and three minutes")
    if minutes == 1:
        return prices.copy()
    frames: list[pd.DataFrame] = []
    for _, day in prices.groupby("session_date"):
        aggregated = day[["open", "high", "low", "close"]].resample(
            f"{minutes}min", label="left", closed="left", origin="start_day"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        aggregated["session_date"] = aggregated.index.date
        frames.append(aggregated)
    return pd.concat(frames).sort_index() if frames else prices.iloc[0:0].copy()


def mark_displacement(prices: pd.DataFrame, *, config: StudyConfig | None = None) -> pd.DataFrame:
    """Mark normalized displacement using only baselines observable before each bar."""

    cfg = config or StudyConfig()
    out = prices.copy()
    body = (out["close"] - out["open"]).abs()
    prior_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prior_close).abs(),
            (out["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    prior_atr = true_range.shift(1).rolling(20, min_periods=10).mean()
    minute_key = pd.Series(out.index.strftime("%H:%M"), index=out.index)
    prior_same_time_body = body.groupby(minute_key).transform(
        lambda series: series.shift(1).rolling(
            cfg.same_time_lookback, min_periods=cfg.minimum_history_sessions
        ).median()
    )
    bar_range = (out["high"] - out["low"]).replace(0, math.nan)
    body_fraction = body / bar_range
    direction = (out["close"] > out["open"]).astype(int) - (out["close"] < out["open"]).astype(int)
    bullish_close_location = (out["high"] - out["close"]) / bar_range
    bearish_close_location = (out["close"] - out["low"]) / bar_range
    directional_close = (direction.gt(0) & bullish_close_location.le(cfg.displacement_close_fraction)) | (
        direction.lt(0) & bearish_close_location.le(cfg.displacement_close_fraction)
    )
    out["true_range"] = true_range
    out["prior_atr_20"] = prior_atr
    out["prior_same_time_median_body"] = prior_same_time_body
    out["body_fraction"] = body_fraction
    out["bar_direction"] = direction
    out["displacement"] = (
        body.ge(cfg.displacement_body_multiple * prior_same_time_body)
        & true_range.ge(cfg.displacement_atr_multiple * prior_atr)
        & body_fraction.ge(cfg.displacement_body_fraction)
        & directional_close
    ).fillna(False)
    return out


def confirmed_swings(bars: pd.DataFrame, *, width: int = 2) -> pd.DataFrame:
    """Return pivots with the timestamp when their right-hand confirmation is known."""

    if width < 1:
        raise ValueError("width must be positive")
    records: list[dict] = []
    for position in range(width, len(bars) - width):
        current = bars.iloc[position]
        left = bars.iloc[position - width : position]
        right = bars.iloc[position + 1 : position + width + 1]
        pivot_time = bars.index[position]
        confirmation_time = bars.index[position + width]
        if current["high"] > left["high"].max() and current["high"] > right["high"].max():
            records.append(
                {
                    "pivot_time": pivot_time,
                    "confirmation_time": confirmation_time,
                    "swing_type": "high",
                    "level": float(current["high"]),
                }
            )
        if current["low"] < left["low"].min() and current["low"] < right["low"].min():
            records.append(
                {
                    "pivot_time": pivot_time,
                    "confirmation_time": confirmation_time,
                    "swing_type": "low",
                    "level": float(current["low"]),
                }
            )
    return pd.DataFrame.from_records(records)


def find_first_mss(
    bars: pd.DataFrame,
    *,
    direction: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
    width: int = 2,
    require_displacement: bool = True,
) -> dict | None:
    """Find the first causal close through the latest already-confirmed swing."""

    if direction not in {-1, 1}:
        return None
    swings = confirmed_swings(bars, width=width)
    if swings.empty:
        return None
    swing_type = "high" if direction > 0 else "low"
    candidates = bars[(bars.index >= start) & (bars.index < end)]
    for timestamp, bar in candidates.iterrows():
        eligible = swings[
            swings["swing_type"].eq(swing_type) & swings["confirmation_time"].lt(timestamp)
        ]
        if eligible.empty:
            continue
        swing = eligible.sort_values("confirmation_time").iloc[-1]
        crossed = bar["close"] > swing["level"] if direction > 0 else bar["close"] < swing["level"]
        displaced = bool(bar.get("displacement", False))
        if crossed and (displaced or not require_displacement):
            return {
                "mss_time": timestamp,
                "mss_direction": direction,
                "broken_swing_time": swing["pivot_time"],
                "broken_swing_confirmation_time": swing["confirmation_time"],
                "broken_swing_level": float(swing["level"]),
                "mss_close": float(bar["close"]),
                "mss_displacement": displaced,
            }
    return None


def find_fvgs(
    bars: pd.DataFrame,
    *,
    minimum_width: float = 0.0,
    require_middle_displacement: bool = False,
) -> pd.DataFrame:
    """Detect three-closed-candle wick non-overlap zones causally."""

    records: list[dict] = []
    for position in range(2, len(bars)):
        first = bars.iloc[position - 2]
        middle = bars.iloc[position - 1]
        third = bars.iloc[position]
        created_at = bars.index[position]
        middle_displaced = bool(middle.get("displacement", False))
        if require_middle_displacement and not middle_displaced:
            continue
        if float(first["high"]) + minimum_width <= float(third["low"]):
            low, high, direction = float(first["high"]), float(third["low"]), 1
        elif float(first["low"]) - minimum_width >= float(third["high"]):
            low, high, direction = float(third["high"]), float(first["low"]), -1
        else:
            continue
        records.append(
            {
                "created_at": created_at,
                "direction": direction,
                "zone_low": low,
                "zone_high": high,
                "zone_midpoint": (low + high) / 2,
                "width": high - low,
                "middle_displacement": middle_displaced,
            }
        )
    return pd.DataFrame.from_records(records)


def rejection_zone(bar: pd.Series, *, direction: int, minimum_wick_fraction: float = 0.50) -> dict | None:
    """Return a deterministic wick zone for the first qualifying close-back candle."""

    total = float(bar["high"] - bar["low"])
    if total <= 0 or direction not in {-1, 1}:
        return None
    if direction > 0:
        zone_low, zone_high = float(bar["low"]), float(min(bar["open"], bar["close"]))
        closes_opposite_half = float(bar["close"]) >= float(bar["low"]) + total / 2
    else:
        zone_low, zone_high = float(max(bar["open"], bar["close"])), float(bar["high"])
        closes_opposite_half = float(bar["close"]) <= float(bar["high"]) - total / 2
    if (zone_high - zone_low) / total < minimum_wick_fraction or not closes_opposite_half:
        return None
    return {"zone_low": zone_low, "zone_high": zone_high, "zone_midpoint": (zone_low + zone_high) / 2}
