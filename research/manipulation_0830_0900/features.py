"""Deterministic, causal D004 feature and event definitions."""

from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from research.event_study_0830_0930.structures import find_first_mss

from .bars import aggregate_bars
from .config import (
    HORIZON_WINDOWS,
    LONDON,
    NEW_YORK,
    REFERENCE_WINDOWS,
    SUBWINDOWS,
    ClockWindow,
    ResearchConfig,
    local_timestamp,
    trading_day_bounds,
    utc_bounds,
)


def window_slice(
    bars: pd.DataFrame,
    session_date: date,
    start: str,
    end: str,
    timezone: str = NEW_YORK,
) -> pd.DataFrame:
    """Select a half-open local-clock window from UTC-indexed bars."""

    left, right = utc_bounds(session_date, start, end, timezone)
    return utc_slice(bars, left, right)


def utc_slice(
    bars: pd.DataFrame,
    left: pd.Timestamp,
    right: pd.Timestamp,
) -> pd.DataFrame:
    """Fast half-open slice on a unique, ordered UTC DatetimeIndex."""

    start_position = int(bars.index.searchsorted(left, side="left"))
    end_position = int(bars.index.searchsorted(right, side="left"))
    return bars.iloc[start_position:end_position]


def summarize_window(frame: pd.DataFrame, prefix: str, expected_minutes: int) -> dict[str, object]:
    """Summarize mid-price bars and coverage without filling missing minutes."""

    empty: dict[str, object] = {
        f"{prefix}_open": math.nan,
        f"{prefix}_high": math.nan,
        f"{prefix}_low": math.nan,
        f"{prefix}_close": math.nan,
        f"{prefix}_range": math.nan,
        f"{prefix}_return": math.nan,
        f"{prefix}_return_bps": math.nan,
        f"{prefix}_tick_count": 0,
        f"{prefix}_minute_count": 0,
        f"{prefix}_expected_minutes": expected_minutes,
        f"{prefix}_complete": False,
    }
    if frame.empty:
        return empty
    opening = float(frame["mid_open"].iloc[0])
    high = float(frame["mid_high"].max())
    low = float(frame["mid_low"].min())
    closing = float(frame["mid_close"].iloc[-1])
    raw_return = closing - opening
    return {
        f"{prefix}_open": opening,
        f"{prefix}_high": high,
        f"{prefix}_low": low,
        f"{prefix}_close": closing,
        f"{prefix}_range": high - low,
        f"{prefix}_return": raw_return,
        f"{prefix}_return_bps": (
            10000.0 * math.log(closing / opening)
            if opening > 0 and closing > 0
            else math.nan
        ),
        f"{prefix}_tick_count": int(frame["tick_count"].sum()),
        f"{prefix}_minute_count": int(len(frame)),
        f"{prefix}_expected_minutes": expected_minutes,
        f"{prefix}_complete": bool(len(frame) == expected_minutes),
    }


def _first_time(mask: pd.Series) -> pd.Timestamp | pd.NaT:
    matches = mask[mask]
    return matches.index[0] if not matches.empty else pd.NaT


def classify_sweep(
    window: pd.DataFrame,
    *,
    reference_high: float,
    reference_low: float,
    threshold_price: float,
) -> dict[str, object]:
    """Classify high/low sweeps and causal close re-entry within one window."""

    empty = {
        "high_sweep": False,
        "low_sweep": False,
        "both_side_sweep": False,
        "neither_sweep": True,
        "sweep_type": "neither",
        "high_sweep_time": pd.NaT,
        "low_sweep_time": pd.NaT,
        "high_penetration": math.nan,
        "low_penetration": math.nan,
        "high_reentry": False,
        "low_reentry": False,
        "high_reentry_time": pd.NaT,
        "low_reentry_time": pd.NaT,
        "high_reentry_minutes": math.nan,
        "low_reentry_minutes": math.nan,
    }
    if (
        window.empty
        or not np.isfinite(reference_high)
        or not np.isfinite(reference_low)
        or reference_high < reference_low
        or not np.isfinite(threshold_price)
        or threshold_price < 0
    ):
        return empty
    high_mask = window["mid_high"].ge(reference_high + threshold_price)
    low_mask = window["mid_low"].le(reference_low - threshold_price)
    high_time = _first_time(high_mask)
    low_time = _first_time(low_mask)
    high_sweep = pd.notna(high_time)
    low_sweep = pd.notna(low_time)

    def reentry(
        sweep_time: pd.Timestamp | pd.NaT,
        inside: pd.Series,
    ) -> tuple[bool, pd.Timestamp | pd.NaT, float]:
        if pd.isna(sweep_time):
            return False, pd.NaT, math.nan
        after = inside[inside.index >= sweep_time]
        when = _first_time(after)
        if pd.isna(when):
            return False, pd.NaT, math.nan
        elapsed = float((when - sweep_time).total_seconds() / 60.0)
        return True, when, elapsed

    high_reentry, high_reentry_time, high_minutes = reentry(
        high_time, window["mid_close"].le(reference_high)
    )
    low_reentry, low_reentry_time, low_minutes = reentry(
        low_time, window["mid_close"].ge(reference_low)
    )
    sweep_type = (
        "both"
        if high_sweep and low_sweep
        else "high_only"
        if high_sweep
        else "low_only"
        if low_sweep
        else "neither"
    )
    return {
        "high_sweep": bool(high_sweep),
        "low_sweep": bool(low_sweep),
        "both_side_sweep": bool(high_sweep and low_sweep),
        "neither_sweep": bool(not high_sweep and not low_sweep),
        "sweep_type": sweep_type,
        "high_sweep_time": high_time,
        "low_sweep_time": low_time,
        "high_penetration": (
            max(0.0, float(window["mid_high"].max()) - reference_high)
            if high_sweep
            else 0.0
        ),
        "low_penetration": (
            max(0.0, reference_low - float(window["mid_low"].min()))
            if low_sweep
            else 0.0
        ),
        "high_reentry": high_reentry,
        "low_reentry": low_reentry,
        "high_reentry_time": high_reentry_time,
        "low_reentry_time": low_reentry_time,
        "high_reentry_minutes": high_minutes,
        "low_reentry_minutes": low_minutes,
    }


def threshold_to_price(
    mode: str,
    value: float,
    *,
    reference_high: float,
    reference_low: float,
    prior_atr: float,
) -> float:
    midpoint = (reference_high + reference_low) / 2.0
    reference_range = reference_high - reference_low
    if mode == "absolute":
        return value
    if mode == "bps":
        return midpoint * value / 10000.0
    if mode == "atr_fraction":
        return prior_atr * value if np.isfinite(prior_atr) else math.nan
    if mode == "recent_range_fraction":
        return reference_range * value
    raise ValueError(f"unknown threshold mode: {mode}")


def displacement_metrics(window: pd.DataFrame, *, prior_atr: float) -> dict[str, object]:
    """Measure window displacement using only prices observed through its end."""

    if window.empty:
        return {
            "window_max_up_excursion": math.nan,
            "window_max_down_excursion": math.nan,
            "window_body_to_range": math.nan,
            "window_range_atr": math.nan,
            "window_max_directional_excursion": math.nan,
            "window_consecutive_directional_bars": 0,
            "window_speed_price_per_minute": math.nan,
            "window_speed_price_per_second": math.nan,
            "window_tick_rate_mean": math.nan,
            "window_tick_rate_max": math.nan,
        }
    opening = float(window["mid_open"].iloc[0])
    closing = float(window["mid_close"].iloc[-1])
    high = float(window["mid_high"].max())
    low = float(window["mid_low"].min())
    total_range = high - low
    direction = 1 if closing > opening else -1 if closing < opening else 0
    up = high - opening
    down = opening - low
    directional = up if direction > 0 else down if direction < 0 else max(up, down)
    bar_direction = np.sign(
        window["mid_close"].to_numpy() - window["mid_open"].to_numpy()
    )
    longest = 0
    run = 0
    for value in bar_direction:
        if direction and int(value) == direction:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    elapsed_minutes = max(1.0, float(len(window)))
    return {
        "window_max_up_excursion": up,
        "window_max_down_excursion": down,
        "window_body_to_range": abs(closing - opening) / total_range if total_range > 0 else 0.0,
        "window_range_atr": (
            total_range / prior_atr
            if np.isfinite(prior_atr) and prior_atr > 0
            else math.nan
        ),
        "window_max_directional_excursion": directional,
        "window_consecutive_directional_bars": int(longest),
        "window_speed_price_per_minute": abs(closing - opening) / elapsed_minutes,
        "window_speed_price_per_second": abs(closing - opening) / (60.0 * elapsed_minutes),
        "window_tick_rate_mean": float(window["tick_count"].mean()),
        "window_tick_rate_max": int(window["tick_count"].max()),
    }


def classify_displacement_expanding(
    frame: pd.DataFrame,
    *,
    metric: str = "window_range_atr",
    minimum_history: int = 20,
    quantiles: tuple[float, float, float] = (0.25, 0.75, 0.90),
    eligibility_column: str | None = None,
) -> pd.DataFrame:
    """Classify each day against strictly earlier eligible observations."""

    out = frame.sort_values("trading_date").copy()
    values = pd.to_numeric(out[metric], errors="coerce")
    history: list[float] = []
    labels: list[str] = []
    history_counts: list[int] = []
    thresholds: list[tuple[float, float, float]] = []
    percentile_ranks: list[float] = []
    eligibility = (
        out[eligibility_column].astype(bool).tolist()
        if eligibility_column is not None
        else [True] * len(out)
    )
    for value, is_eligible in zip(values, eligibility):
        finite_history = np.asarray(history, dtype=float)
        history_counts.append(int(len(finite_history)))
        if len(finite_history) < minimum_history or not np.isfinite(value):
            labels.append("insufficient_history")
            thresholds.append((math.nan, math.nan, math.nan))
            percentile_ranks.append(math.nan)
        else:
            low, high, extreme = np.quantile(finite_history, quantiles)
            thresholds.append((float(low), float(high), float(extreme)))
            percentile_ranks.append(float((finite_history <= float(value)).mean()))
            labels.append(
                "low"
                if value <= low
                else "normal"
                if value <= high
                else "high"
                if value <= extreme
                else "extreme"
            )
        if np.isfinite(value) and is_eligible:
            history.append(float(value))
    out["displacement_history_count"] = history_counts
    out["displacement_p25_prior"] = [item[0] for item in thresholds]
    out["displacement_p75_prior"] = [item[1] for item in thresholds]
    out["displacement_p90_prior"] = [item[2] for item in thresholds]
    out["displacement_percentile_prior"] = percentile_ranks
    out["displacement_class"] = pd.Series(labels, index=out.index, dtype="string")
    return out


def label_hod_lod(
    trading_day: pd.DataFrame,
    window: pd.DataFrame,
    *,
    tick_size: float,
    prior_atr: float,
) -> dict[str, object]:
    """Label first attainment of the final named-session HOD/LOD."""

    if trading_day.empty:
        return {
            "final_hod": math.nan,
            "final_lod": math.nan,
            "hod_time": pd.NaT,
            "lod_time": pd.NaT,
            "window_creates_hod": False,
            "window_creates_lod": False,
            "window_creates_both": False,
            "window_creates_neither": True,
            "window_within_hod_1tick": False,
            "window_within_lod_1tick": False,
            "window_within_hod_5tick": False,
            "window_within_lod_5tick": False,
            "window_within_hod_005atr": False,
            "window_within_lod_005atr": False,
        }
    hod = float(trading_day["mid_high"].max())
    lod = float(trading_day["mid_low"].min())
    hod_time = trading_day["mid_high"].idxmax()
    lod_time = trading_day["mid_low"].idxmin()
    window_high = float(window["mid_high"].max()) if not window.empty else math.nan
    window_low = float(window["mid_low"].min()) if not window.empty else math.nan
    creates_hod = bool(
        np.isfinite(window_high)
        and np.isclose(window_high, hod, rtol=0.0, atol=1e-12)
    )
    creates_lod = bool(
        np.isfinite(window_low)
        and np.isclose(window_low, lod, rtol=0.0, atol=1e-12)
    )
    atr_tolerance = 0.05 * prior_atr if np.isfinite(prior_atr) else math.nan
    return {
        "final_hod": hod,
        "final_lod": lod,
        "hod_time": hod_time,
        "lod_time": lod_time,
        "window_creates_hod": creates_hod,
        "window_creates_lod": creates_lod,
        "window_creates_both": bool(creates_hod and creates_lod),
        "window_creates_neither": bool(not creates_hod and not creates_lod),
        "window_within_hod_1tick": bool(np.isfinite(window_high) and hod - window_high <= tick_size),
        "window_within_lod_1tick": bool(np.isfinite(window_low) and window_low - lod <= tick_size),
        "window_within_hod_5tick": bool(np.isfinite(window_high) and hod - window_high <= 5 * tick_size),
        "window_within_lod_5tick": bool(np.isfinite(window_low) and window_low - lod <= 5 * tick_size),
        "window_within_hod_005atr": bool(
            np.isfinite(window_high)
            and np.isfinite(atr_tolerance)
            and hod - window_high <= atr_tolerance
        ),
        "window_within_lod_005atr": bool(
            np.isfinite(window_low)
            and np.isfinite(atr_tolerance)
            and window_low - lod <= atr_tolerance
        ),
    }


def _mid_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "mid_open": "open",
            "mid_high": "high",
            "mid_low": "low",
            "mid_close": "close",
        }
    )[["open", "high", "low", "close", "tick_count"]].copy()


def _causal_bar_displacement(frame: pd.DataFrame) -> pd.DataFrame:
    out = _mid_frame(frame)
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
    prior_body = body.shift(1).rolling(20, min_periods=10).median()
    bar_range = (out["high"] - out["low"]).replace(0.0, math.nan)
    out["displacement"] = (
        body.ge(1.5 * prior_body)
        & true_range.ge(1.5 * prior_atr)
        & body.div(bar_range).ge(0.65)
    ).fillna(False)
    return out


def mss_features(
    bars: pd.DataFrame,
    session_date: date,
    *,
    swing_width: int,
    window_end: str,
) -> dict[str, object]:
    """Reuse the repository's causal confirmed-swing MSS detector."""

    context = window_slice(bars, session_date, "07:30", "10:00")
    if context.empty:
        return {
            "bullish_mss": False,
            "bearish_mss": False,
            "bullish_mss_time": pd.NaT,
            "bearish_mss_time": pd.NaT,
            "bullish_mss_before_0900": False,
            "bearish_mss_before_0900": False,
        }
    marked = _causal_bar_displacement(context)
    # Shift to bar-close availability; a bar cannot confirm a break at its open.
    marked.index = marked.index + pd.Timedelta(minutes=1)
    start = local_timestamp(session_date, "08:30").tz_convert("UTC")
    end = local_timestamp(session_date, "10:00").tz_convert("UTC")
    signal_end = local_timestamp(session_date, window_end).tz_convert("UTC")
    bullish = find_first_mss(
        marked,
        direction=1,
        start=start,
        end=end,
        width=swing_width,
        require_displacement=False,
    )
    bearish = find_first_mss(
        marked,
        direction=-1,
        start=start,
        end=end,
        width=swing_width,
        require_displacement=False,
    )
    bullish_time = bullish["mss_time"] if bullish else pd.NaT
    bearish_time = bearish["mss_time"] if bearish else pd.NaT
    return {
        "bullish_mss": bullish is not None,
        "bearish_mss": bearish is not None,
        "bullish_mss_time": bullish_time,
        "bearish_mss_time": bearish_time,
        "bullish_mss_before_0900": bool(
            bullish is not None and bullish_time <= signal_end
        ),
        "bearish_mss_before_0900": bool(
            bearish is not None and bearish_time <= signal_end
        ),
    }


def detect_fvgs(
    bars: pd.DataFrame,
    *,
    resolution_minutes: int,
    minimum_width: float = 0.0,
) -> pd.DataFrame:
    """Detect wick-non-overlap FVGs at bar-close availability."""

    if resolution_minutes not in {1, 5, 15}:
        raise ValueError("FVG resolution must be 1, 5, or 15 minutes")
    mid = _mid_frame(bars)
    records: list[dict[str, object]] = []
    delta = pd.Timedelta(minutes=resolution_minutes)
    for position in range(2, len(mid)):
        first = mid.iloc[position - 2]
        middle = mid.iloc[position - 1]
        third = mid.iloc[position]
        available_at = mid.index[position] + delta
        middle_range = float(middle["high"] - middle["low"])
        middle_body = abs(float(middle["close"] - middle["open"]))
        if float(first["high"]) + minimum_width < float(third["low"]):
            low = float(first["high"])
            high = float(third["low"])
            direction = "bullish"
        elif float(first["low"]) - minimum_width > float(third["high"]):
            low = float(third["high"])
            high = float(first["low"])
            direction = "bearish"
        else:
            continue
        records.append(
            {
                "creation_bar_open": mid.index[position],
                "creation_time": available_at,
                "direction": direction,
                "zone_low": low,
                "zone_high": high,
                "width": high - low,
                "middle_body_to_range": (
                    middle_body / middle_range if middle_range > 0 else 0.0
                ),
                "resolution_minutes": resolution_minutes,
            }
        )
    return pd.DataFrame.from_records(records)


def analyze_fvg_path(
    fvg: dict[str, object],
    future: pd.DataFrame,
    *,
    prior_atr: float,
    expiration_minutes: int,
    same_event_end: pd.Timestamp | None = None,
    risk_buffer: float = 0.01,
) -> dict[str, object]:
    """Measure touch/fill/invalidation and geometry excursions after creation."""

    created = pd.Timestamp(fvg["creation_time"])
    expires = created + pd.Timedelta(minutes=expiration_minutes)
    path = future[(future.index >= created) & (future.index < expires)]
    low = float(fvg["zone_low"])
    high = float(fvg["zone_high"])
    width = high - low
    direction = str(fvg["direction"])
    record: dict[str, object] = {
        **fvg,
        "width_atr": width / prior_atr if np.isfinite(prior_atr) and prior_atr > 0 else math.nan,
        "expiration_time": expires,
        "first_touch_time": pd.NaT,
        "fill_percentage": 0.0,
        "full_fill": False,
        "invalidation": False,
        "invalidation_time": pd.NaT,
        "expired_unfilled": False,
    }
    if path.empty or width <= 0:
        record["expired_unfilled"] = True
        for geometry in ("proximal", "midpoint", "depth_75", "distal"):
            record[f"{geometry}_entry_price"] = math.nan
            record[f"{geometry}_stop_price"] = math.nan
            record[f"{geometry}_risk_price"] = math.nan
            record[f"{geometry}_touch_time"] = pd.NaT
            record[f"{geometry}_mfe_r"] = math.nan
            record[f"{geometry}_mae_r"] = math.nan
            record[f"{geometry}_terminal_r"] = math.nan
            record[f"full_horizon_{geometry}_mfe_r"] = math.nan
            record[f"full_horizon_{geometry}_mae_r"] = math.nan
            record[f"full_horizon_{geometry}_terminal_r"] = math.nan
            record[f"same_event_{geometry}_mfe_r"] = math.nan
            record[f"same_event_{geometry}_mae_r"] = math.nan
            record[f"same_event_{geometry}_terminal_r"] = math.nan
            record[f"{geometry}_repository_default_terminal_r"] = math.nan
            record[f"{geometry}_conservative_terminal_r"] = math.nan
        return record
    if direction == "bullish":
        touch_mask = path["mid_low"].le(high)
        first_touch = _first_time(touch_mask)
        minimum = float(path["mid_low"].min())
        fill = float(np.clip((high - minimum) / width, 0.0, 1.0))
        full = minimum <= low
        invalid_mask = path["mid_close"].lt(low)
    else:
        touch_mask = path["mid_high"].ge(low)
        first_touch = _first_time(touch_mask)
        maximum = float(path["mid_high"].max())
        fill = float(np.clip((maximum - low) / width, 0.0, 1.0))
        full = maximum >= high
        invalid_mask = path["mid_close"].gt(high)
    invalid_time = _first_time(invalid_mask)
    record.update(
        {
            "first_touch_time": first_touch,
            "fill_percentage": fill,
            "full_fill": bool(full),
            "invalidation": bool(pd.notna(invalid_time)),
            "invalidation_time": invalid_time,
            "expired_unfilled": bool(not full),
        }
    )
    fractions = {
        "proximal": 0.0,
        "midpoint": 0.5,
        "depth_75": 0.75,
        "distal": 1.0,
    }
    for geometry, depth in fractions.items():
        entry = high - depth * width if direction == "bullish" else low + depth * width
        stop = low - risk_buffer if direction == "bullish" else high + risk_buffer
        risk = abs(entry - stop)
        if direction == "bullish":
            touched = path["mid_low"].le(entry)
        else:
            touched = path["mid_high"].ge(entry)
        touch = _first_time(touched)
        after = path[path.index >= touch] if pd.notna(touch) else path.iloc[0:0]
        record[f"{geometry}_entry_price"] = entry
        record[f"{geometry}_stop_price"] = stop
        record[f"{geometry}_risk_price"] = risk
        record[f"{geometry}_touch_time"] = touch
        if after.empty:
            record[f"{geometry}_mfe_r"] = math.nan
            record[f"{geometry}_mae_r"] = math.nan
            record[f"{geometry}_terminal_r"] = math.nan
        elif direction == "bullish":
            record[f"{geometry}_mfe_r"] = (
                float(after["mid_high"].max()) - entry
            ) / risk
            record[f"{geometry}_mae_r"] = (
                entry - float(after["mid_low"].min())
            ) / risk
            record[f"{geometry}_terminal_r"] = (
                float(after["mid_close"].iloc[-1]) - entry
            ) / risk
        else:
            record[f"{geometry}_mfe_r"] = (
                entry - float(after["mid_low"].min())
            ) / risk
            record[f"{geometry}_mae_r"] = (
                float(after["mid_high"].max()) - entry
            ) / risk
            record[f"{geometry}_terminal_r"] = (
                entry - float(after["mid_close"].iloc[-1])
            ) / risk
        terminal_r = record[f"{geometry}_terminal_r"]
        record[f"{geometry}_repository_default_terminal_r"] = terminal_r
        record[f"{geometry}_conservative_terminal_r"] = (
            float(terminal_r) - 0.40 / risk - 0.01
            if np.isfinite(terminal_r)
            else math.nan
        )
        record[f"full_horizon_{geometry}_mfe_r"] = record[f"{geometry}_mfe_r"]
        record[f"full_horizon_{geometry}_mae_r"] = record[f"{geometry}_mae_r"]
        record[f"full_horizon_{geometry}_terminal_r"] = record[
            f"{geometry}_terminal_r"
        ]
        event_after = (
            after[after.index < same_event_end]
            if same_event_end is not None
            else after.iloc[0:0]
        )
        if event_after.empty:
            record[f"same_event_{geometry}_mfe_r"] = math.nan
            record[f"same_event_{geometry}_mae_r"] = math.nan
            record[f"same_event_{geometry}_terminal_r"] = math.nan
        elif direction == "bullish":
            record[f"same_event_{geometry}_mfe_r"] = (
                float(event_after["mid_high"].max()) - entry
            ) / risk
            record[f"same_event_{geometry}_mae_r"] = (
                entry - float(event_after["mid_low"].min())
            ) / risk
            record[f"same_event_{geometry}_terminal_r"] = (
                float(event_after["mid_close"].iloc[-1]) - entry
            ) / risk
        else:
            record[f"same_event_{geometry}_mfe_r"] = (
                entry - float(event_after["mid_low"].min())
            ) / risk
            record[f"same_event_{geometry}_mae_r"] = (
                float(event_after["mid_high"].max()) - entry
            ) / risk
            record[f"same_event_{geometry}_terminal_r"] = (
                entry - float(event_after["mid_close"].iloc[-1])
            ) / risk
    return record


def _prior_atr(pre_window: pd.DataFrame, lookback: int) -> float:
    if pre_window.empty:
        return math.nan
    bars = aggregate_bars(pre_window, 15)
    previous_close = bars["mid_close"].shift(1)
    true_range = pd.concat(
        [
            bars["mid_high"] - bars["mid_low"],
            (bars["mid_high"] - previous_close).abs(),
            (bars["mid_low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    available = true_range.dropna().tail(lookback)
    return float(available.mean()) if len(available) >= max(5, lookback // 2) else math.nan


def _daily_level_summary(frame: pd.DataFrame, prefix: str) -> dict[str, object]:
    if frame.empty:
        return {
            f"{prefix}_open": math.nan,
            f"{prefix}_high": math.nan,
            f"{prefix}_low": math.nan,
            f"{prefix}_close": math.nan,
        }
    return {
        f"{prefix}_open": float(frame["mid_open"].iloc[0]),
        f"{prefix}_high": float(frame["mid_high"].max()),
        f"{prefix}_low": float(frame["mid_low"].min()),
        f"{prefix}_close": float(frame["mid_close"].iloc[-1]),
    }


def _candidate_dates(bars: pd.DataFrame, config: ResearchConfig) -> list[date]:
    local_dates = pd.DatetimeIndex(bars.index).tz_convert(config.timezone).date
    first = config.start_date or min(local_dates)
    last = config.end_date or max(local_dates)
    return [
        value.date()
        for value in pd.date_range(first, last, freq="D")
        if value.weekday() < 5
    ]


def _load_event_labels(path: Path | None, timezone: str) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame()
    if not path.is_file():
        raise ValueError(f"event-label file does not exist: {path}")
    frame = (
        pd.read_parquet(path)
        if path.suffix.lower() in {".parquet", ".pq"}
        else pd.read_csv(path)
    )
    if "trading_date" not in frame:
        raise ValueError("event labels require a trading_date column")
    parsed_dates = pd.to_datetime(frame["trading_date"], errors="coerce")
    if parsed_dates.isna().any():
        raise ValueError("event labels contain invalid trading_date values")
    frame = frame.copy()
    frame["trading_date"] = parsed_dates.dt.date
    if "event_timestamp" in frame:
        timestamps = pd.to_datetime(frame["event_timestamp"], errors="coerce")
        if timestamps.isna().any():
            raise ValueError("event labels contain invalid event_timestamp values")
        index = pd.DatetimeIndex(timestamps)
        if index.tz is None:
            raise ValueError(
                "event_timestamp labels must carry an explicit timezone; "
                "volatility is never used to infer events"
            )
        frame["event_timestamp"] = index.tz_convert(timezone)
    return frame


def _join_event_labels(daily: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    out = daily.copy()
    out["macro_event_labeled"] = False
    out["macro_event_categories"] = ""
    out["macro_event_labels"] = ""
    if labels.empty:
        return out
    category_column = "category" if "category" in labels else None
    label_column = (
        "event_label"
        if "event_label" in labels
        else "event_name"
        if "event_name" in labels
        else None
    )
    grouped = labels.groupby("trading_date", sort=True)
    for row_index, trading_date in out["trading_date"].items():
        if trading_date not in grouped.groups:
            continue
        group = grouped.get_group(trading_date)
        out.at[row_index, "macro_event_labeled"] = True
        if category_column:
            out.at[row_index, "macro_event_categories"] = " | ".join(
                sorted(set(group[category_column].dropna().astype(str)))
            )
        if label_column:
            out.at[row_index, "macro_event_labels"] = " | ".join(
                sorted(set(group[label_column].dropna().astype(str)))
            )
    return out


def build_daily_events(
    bars: pd.DataFrame,
    config: ResearchConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the machine-readable daily event dataset and FVG event dataset."""

    config.validate()
    records: list[dict[str, object]] = []
    fvg_records: list[dict[str, object]] = []
    primary_reference = next(
        item for item in REFERENCE_WINDOWS if item.name == config.reference_range
    )
    for session_date in _candidate_dates(bars, config):
        trading_left, trading_right = trading_day_bounds(session_date, config.timezone)
        trading_day = utc_slice(bars, trading_left, trading_right)
        primary = window_slice(
            bars, session_date, config.window_start, config.window_end, config.timezone
        )
        before = window_slice(bars, session_date, "08:00", "08:30", config.timezone)
        pre_for_atr = utc_slice(bars, trading_left, primary.index.min()) if not primary.empty else window_slice(
            bars, session_date, "00:00", "08:30", config.timezone
        )
        prior_atr = _prior_atr(pre_for_atr, config.atr_lookback_bars)
        record: dict[str, object] = {
            "trading_date": session_date,
            "source_data_coverage_status": (
                "complete"
                if len(primary) == 30 and len(trading_day) >= int(1380 * 0.95)
                else "core_complete_day_partial"
                if len(primary) == 30
                else "core_incomplete"
            ),
            "trading_day_minute_count": int(len(trading_day)),
            "trading_day_coverage_fraction": len(trading_day) / 1380.0,
            "prior_atr_15m_20": prior_atr,
        }
        record.update(summarize_window(primary, "window", 30))
        record.update(displacement_metrics(primary, prior_atr=prior_atr))
        record["tick_rate_acceleration"] = (
            float(primary["tick_count"].mean() / before["tick_count"].mean())
            if not primary.empty
            and not before.empty
            and float(before["tick_count"].mean()) > 0
            else math.nan
        )
        record["window_closing_location"] = (
            (float(primary["mid_close"].iloc[-1]) - float(primary["mid_low"].min()))
            / (float(primary["mid_high"].max()) - float(primary["mid_low"].min()))
            if not primary.empty
            and float(primary["mid_high"].max()) > float(primary["mid_low"].min())
            else math.nan
        )
        for subwindow in SUBWINDOWS:
            sub = window_slice(
                bars,
                session_date,
                subwindow.start,
                subwindow.end,
                config.timezone,
            )
            record.update(summarize_window(sub, f"subwindow_{subwindow.name}", subwindow.minutes))
        reference_frames: dict[str, pd.DataFrame] = {}
        for reference in REFERENCE_WINDOWS:
            ref = window_slice(
                bars,
                session_date,
                reference.start,
                reference.end,
                config.timezone,
            )
            reference_frames[reference.name] = ref
            record.update(
                _daily_level_summary(ref, f"reference_{reference.name}")
            )
        selected_ref = reference_frames[primary_reference.name]
        reference_high = (
            float(selected_ref["mid_high"].max()) if not selected_ref.empty else math.nan
        )
        reference_low = (
            float(selected_ref["mid_low"].min()) if not selected_ref.empty else math.nan
        )
        primary_threshold = threshold_to_price(
            config.primary_sweep_threshold_mode,
            config.primary_sweep_threshold,
            reference_high=reference_high,
            reference_low=reference_low,
            prior_atr=prior_atr,
        )
        sweep = classify_sweep(
            primary,
            reference_high=reference_high,
            reference_low=reference_low,
            threshold_price=primary_threshold,
        )
        record.update(sweep)
        record["primary_reference_name"] = primary_reference.name
        record["primary_sweep_threshold_mode"] = config.primary_sweep_threshold_mode
        record["primary_sweep_threshold_value"] = config.primary_sweep_threshold
        record["primary_sweep_threshold_price"] = primary_threshold
        record["distance_from_reference_high_at_0900"] = (
            float(primary["mid_close"].iloc[-1]) - reference_high
            if not primary.empty and np.isfinite(reference_high)
            else math.nan
        )
        record["distance_from_reference_low_at_0900"] = (
            float(primary["mid_close"].iloc[-1]) - reference_low
            if not primary.empty and np.isfinite(reference_low)
            else math.nan
        )
        for horizon in HORIZON_WINDOWS:
            path = window_slice(
                bars, session_date, horizon.start, horizon.end, config.timezone
            )
            record.update(summarize_window(path, f"horizon_{horizon.name}", horizon.minutes))
            if path.empty:
                record[f"horizon_{horizon.name}_mfe_up"] = math.nan
                record[f"horizon_{horizon.name}_mae_down"] = math.nan
            else:
                opening = float(path["mid_open"].iloc[0])
                record[f"horizon_{horizon.name}_mfe_up"] = (
                    float(path["mid_high"].max()) - opening
                )
                record[f"horizon_{horizon.name}_mae_down"] = (
                    opening - float(path["mid_low"].min())
                )
        record.update(
            label_hod_lod(
                trading_day,
                primary,
                tick_size=config.tick_size,
                prior_atr=prior_atr,
            )
        )
        record.update(mss_features(
            bars,
            session_date,
            swing_width=config.swing_width,
            window_end=config.window_end,
        ))

        # Deterministic named liquidity levels.  Prior-day levels are attached
        # after all current-day records exist.
        midnight = window_slice(bars, session_date, "00:00", "00:01", config.timezone)
        record["new_york_midnight_open"] = (
            float(midnight["mid_open"].iloc[0]) if not midnight.empty else math.nan
        )
        record["daily_open_1800"] = (
            float(trading_day["mid_open"].iloc[0]) if not trading_day.empty else math.nan
        )
        asia_left = local_timestamp(
            session_date - timedelta(days=1), "20:00", config.timezone
        ).tz_convert("UTC")
        asia_right = local_timestamp(session_date, "00:00", config.timezone).tz_convert("UTC")
        asia = utc_slice(bars, asia_left, asia_right)
        record.update(_daily_level_summary(asia, "asia_2000_0000_new_york"))
        london_left = local_timestamp(session_date, "08:00", LONDON).tz_convert("UTC")
        london_right = local_timestamp(session_date, "12:00", LONDON).tz_convert("UTC")
        london = utc_slice(bars, london_left, london_right)
        record.update(_daily_level_summary(london, "london_0800_1200_local"))
        premarket = window_slice(bars, session_date, "00:00", "08:30", config.timezone)
        record.update(_daily_level_summary(premarket, "premarket_0000_0830"))

        # FVGs are detected on deterministic 1m/5m/15m bars.  A formation is
        # usable only at the close of its third candle.
        signal_left, signal_right = utc_bounds(
            session_date, config.window_start, config.window_end, config.timezone
        )
        fvg_future = utc_slice(trading_day, signal_left, trading_right)
        for resolution in config.bar_resolutions:
            context = window_slice(bars, session_date, "07:30", config.window_end)
            resolution_bars = aggregate_bars(context, resolution)
            detected = detect_fvgs(
                resolution_bars,
                resolution_minutes=resolution,
                minimum_width=config.tick_size,
            )
            in_window = (
                detected[
                    detected["creation_time"].gt(signal_left)
                    & detected["creation_time"].le(signal_right)
                ]
                if not detected.empty
                else detected
            )
            record[f"fvg_{resolution}m_count"] = int(len(in_window))
            record[f"bullish_fvg_{resolution}m"] = bool(
                not in_window.empty and in_window["direction"].eq("bullish").any()
            )
            record[f"bearish_fvg_{resolution}m"] = bool(
                not in_window.empty and in_window["direction"].eq("bearish").any()
            )
            for fvg in in_window.to_dict(orient="records"):
                fvg_record = analyze_fvg_path(
                    fvg,
                    fvg_future,
                    prior_atr=prior_atr,
                    expiration_minutes=config.fvg_expiration_minutes,
                    same_event_end=signal_right,
                    risk_buffer=config.tick_size,
                )
                fvg_record["trading_date"] = session_date
                fvg_records.append(fvg_record)
        records.append(record)

    daily = pd.DataFrame.from_records(records).sort_values("trading_date").reset_index(drop=True)
    if daily.empty:
        return daily, pd.DataFrame()

    # Previous named trading-session levels are completed at 17:00 and shifted;
    # they are never constructed from the current session.
    observed_session = daily["trading_day_minute_count"].gt(0)
    daily["previous_day_high"] = (
        pd.to_numeric(daily["final_hod"], errors="coerce")
        .where(observed_session)
        .ffill()
        .shift(1)
    )
    daily["previous_day_low"] = (
        pd.to_numeric(daily["final_lod"], errors="coerce")
        .where(observed_session)
        .ffill()
        .shift(1)
    )
    daily["previous_day_source_date"] = (
        daily["trading_date"].where(observed_session).ffill().shift(1)
    )
    window_high = pd.to_numeric(daily["window_high"], errors="coerce")
    window_low = pd.to_numeric(daily["window_low"], errors="coerce")
    threshold = pd.to_numeric(
        daily["primary_sweep_threshold_price"], errors="coerce"
    )
    level_pairs = {
        "previous_day": ("previous_day_high", "previous_day_low"),
        "london_0800_1200_local": (
            "london_0800_1200_local_high",
            "london_0800_1200_local_low",
        ),
        "asia_2000_0000_new_york": (
            "asia_2000_0000_new_york_high",
            "asia_2000_0000_new_york_low",
        ),
        "premarket_0000_0830": (
            "premarket_0000_0830_high",
            "premarket_0000_0830_low",
        ),
    }
    for label, (high_column, low_column) in level_pairs.items():
        high_level = pd.to_numeric(daily[high_column], errors="coerce")
        low_level = pd.to_numeric(daily[low_column], errors="coerce")
        daily[f"window_sweeps_{label}_high"] = (
            high_level.notna() & window_high.ge(high_level + threshold)
        )
        daily[f"window_sweeps_{label}_low"] = (
            low_level.notna() & window_low.le(low_level - threshold)
        )
    for label, column in {
        "new_york_midnight_open": "new_york_midnight_open",
        "daily_open_1800": "daily_open_1800",
    }.items():
        level = pd.to_numeric(daily[column], errors="coerce")
        daily[f"window_crosses_{label}"] = (
            level.notna() & window_low.le(level) & window_high.ge(level)
        )
    signal_end_times = pd.to_datetime(daily["trading_date"].astype(str)).map(
        lambda value: local_timestamp(value.date(), "09:00").tz_convert("UTC")
    )
    hod_times = pd.to_datetime(daily["hod_time"], utc=True, errors="coerce")
    lod_times = pd.to_datetime(daily["lod_time"], utc=True, errors="coerce")
    daily["sweeps_prior_session_extreme_before_final_hod_lod"] = (
        daily["window_sweeps_previous_day_high"] & hod_times.ge(signal_end_times)
    ) | (
        daily["window_sweeps_previous_day_low"] & lod_times.ge(signal_end_times)
    )
    daily["window_direction"] = np.sign(
        pd.to_numeric(daily["window_return"], errors="coerce")
    ).astype("Int64")
    post_return = pd.to_numeric(
        daily["horizon_0900_1200_return"], errors="coerce"
    )
    daily["post_0900_1200_direction"] = np.sign(post_return).astype("Int64")
    window_range = pd.to_numeric(daily["window_range"], errors="coerce")
    window_close = pd.to_numeric(daily["window_close"], errors="coerce")
    window_open = pd.to_numeric(daily["window_open"], errors="coerce")
    post_low_30 = pd.to_numeric(
        daily["horizon_0900_0930_low"], errors="coerce"
    )
    post_high_30 = pd.to_numeric(
        daily["horizon_0900_0930_high"], errors="coerce"
    )
    post_low_120 = pd.to_numeric(
        daily["horizon_0900_1200_low"], errors="coerce"
    )
    post_high_120 = pd.to_numeric(
        daily["horizon_0900_1200_high"], errors="coerce"
    )
    retraces_half = (
        daily["window_direction"].eq(1)
        & post_low_30.le(window_close - 0.5 * window_range)
    ) | (
        daily["window_direction"].eq(-1)
        & post_high_30.ge(window_close + 0.5 * window_range)
    )
    daily["high_sweep_bearish_expansion_outcome"] = (
        daily["high_sweep"] & daily["post_0900_1200_direction"].eq(-1)
    )
    daily["high_sweep_bullish_continuation_outcome"] = (
        daily["high_sweep"] & daily["post_0900_1200_direction"].eq(1)
    )
    daily["low_sweep_bullish_expansion_outcome"] = (
        daily["low_sweep"] & daily["post_0900_1200_direction"].eq(1)
    )
    daily["low_sweep_bearish_continuation_outcome"] = (
        daily["low_sweep"] & daily["post_0900_1200_direction"].eq(-1)
    )
    daily["both_sweep_directional_expansion_outcome"] = (
        daily["both_side_sweep"]
        & daily["post_0900_1200_direction"].ne(0)
    )
    daily["opposite_side_subsequently_attacked"] = np.where(
        daily["high_sweep"] & ~daily["low_sweep"],
        pd.to_numeric(daily["horizon_0900_1700_low"], errors="coerce").le(
            pd.to_numeric(
                daily[f"reference_{primary_reference.name}_low"], errors="coerce"
            )
        ),
        np.where(
            daily["low_sweep"] & ~daily["high_sweep"],
            pd.to_numeric(daily["horizon_0900_1700_high"], errors="coerce").ge(
                pd.to_numeric(
                    daily[f"reference_{primary_reference.name}_high"], errors="coerce"
                )
            ),
            False,
        ),
    ).astype(bool)
    daily["core_eligible"] = (
        daily["window_complete"].astype(bool)
        & pd.to_numeric(
            daily[f"reference_{primary_reference.name}_high"], errors="coerce"
        ).notna()
        & pd.to_numeric(
            daily[f"reference_{primary_reference.name}_low"], errors="coerce"
        ).notna()
        & pd.to_numeric(daily["horizon_0900_0930_open"], errors="coerce").notna()
    )
    daily = classify_displacement_expanding(
        daily,
        minimum_history=config.displacement_history_days,
        quantiles=config.displacement_quantiles,
        eligibility_column="core_eligible",
    )
    daily["displacement_high_or_extreme"] = daily["displacement_class"].isin(
        ["high", "extreme"]
    )
    daily["large_impulse_retraces_half_window"] = (
        daily["displacement_high_or_extreme"] & retraces_half
    )
    daily["large_impulse_retracement_then_continuation_outcome"] = (
        daily["large_impulse_retraces_half_window"]
        & daily["post_0900_1200_direction"].eq(daily["window_direction"])
    )
    daily["large_impulse_full_reversal_outcome"] = (
        daily["displacement_high_or_extreme"]
        & (
            (
                daily["window_direction"].eq(1)
                & post_low_120.le(window_open)
            )
            | (
                daily["window_direction"].eq(-1)
                & post_high_120.ge(window_open)
            )
        )
    )
    daily = _join_event_labels(daily, _load_event_labels(config.event_labels, config.timezone))
    fvg_frame = pd.DataFrame.from_records(fvg_records)
    if not fvg_frame.empty:
        fvg_frame = fvg_frame.sort_values(
            ["trading_date", "resolution_minutes", "creation_time", "direction"]
        ).reset_index(drop=True)
    return daily, fvg_frame
