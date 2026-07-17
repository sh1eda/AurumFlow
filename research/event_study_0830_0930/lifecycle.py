from __future__ import annotations

import math

import pandas as pd

from .config import StudyConfig
from .features import _timestamp, _window
from .structures import aggregate_structure_bars, find_first_mss, mark_displacement


def classify_lifecycles(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    structure_minutes: int = 1,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Assign mutually exclusive retrospective outcomes after 10:30.

    The result is for analysis/stratification only. It must never filter an entry
    whose timestamp precedes the classification horizon.
    """

    cfg = config or StudyConfig()
    structural = aggregate_structure_bars(prices, structure_minutes)
    structural = mark_displacement(structural, config=cfg)
    output = features.copy()
    states: list[str] = []
    extensions: list[float] = []
    late_retracements: list[float] = []
    opposite_mss_times: list[pd.Timestamp | pd.NaT] = []

    for session_date, row in output.iterrows():
        path = _window(prices, session_date, cfg.impulse_start, cfg.secondary_end, cfg.timezone)
        post_0930 = _window(prices, session_date, cfg.equity_open, cfg.secondary_end, cfg.timezone)
        direction = int(row["impulse_direction"])
        impulse_range = float(row["impulse_0830_0835_range"])
        impulse_high = float(row["impulse_0830_0835_high"])
        impulse_low = float(row["impulse_0830_0835_low"])
        midpoint = float(row["impulse_midpoint"])
        pre_high = float(row["pre_0730_0829_high"])
        pre_low = float(row["pre_0730_0829_low"])
        buffer = float(row["tick_buffer"])

        if path.empty or direction == 0 or impulse_range <= 0 or any(
            pd.isna(value) for value in (impulse_high, impulse_low, pre_high, pre_low)
        ):
            states.append("6_range_chop")
            extensions.append(math.nan)
            late_retracements.append(math.nan)
            opposite_mss_times.append(pd.NaT)
            continue

        if direction > 0:
            extension = max(0.0, float(path["high"].max()) - impulse_high) / impulse_range
            late_retracement = max(0.0, impulse_high - float(path["low"].min())) / impulse_range
            opposite_boundary_touch = bool(path["low"].le(pre_low - buffer).any())
            directional_pre_break = bool(path["high"].ge(pre_high + buffer).any())
            post_extreme_breach = bool(post_0930["high"].ge(impulse_high + buffer).any())
            post_reentry = bool(post_0930["close"].le(impulse_high).any())
            midpoint_touch = bool(post_0930["low"].le(midpoint).any())
            closes_directional_side = bool(float(path["close"].iloc[-1]) > midpoint)
            new_directional_extreme = bool(path["high"].gt(impulse_high).any())
        else:
            extension = max(0.0, impulse_low - float(path["low"].min())) / impulse_range
            late_retracement = max(0.0, float(path["high"].max()) - impulse_low) / impulse_range
            opposite_boundary_touch = bool(path["high"].ge(pre_high + buffer).any())
            directional_pre_break = bool(path["low"].le(pre_low - buffer).any())
            post_extreme_breach = bool(post_0930["low"].le(impulse_low - buffer).any())
            post_reentry = bool(post_0930["close"].ge(impulse_low).any())
            midpoint_touch = bool(post_0930["high"].ge(midpoint).any())
            closes_directional_side = bool(float(path["close"].iloc[-1]) < midpoint)
            new_directional_extreme = bool(path["low"].lt(impulse_low).any())

        both_pre_sides = bool(
            path["high"].ge(pre_high + buffer).any() and path["low"].le(pre_low - buffer).any()
        )
        both_impulse_sides_post = bool(
            post_0930["high"].ge(impulse_high + buffer).any()
            and post_0930["low"].le(impulse_low - buffer).any()
        )
        structural_day = structural[structural["session_date"].eq(session_date)]
        mss = find_first_mss(
            structural_day,
            direction=-direction,
            start=_timestamp(session_date, cfg.equity_open, cfg.timezone),
            end=_timestamp(session_date, cfg.secondary_end, cfg.timezone),
            width=cfg.swing_width,
            require_displacement=True,
        )
        opposite_mss_time = mss["mss_time"] if mss else pd.NaT
        opposite_mss_times.append(opposite_mss_time)

        full_reversal = bool(
            directional_pre_break and row["reentry_before_acceptance"] and opposite_boundary_touch
        )
        swept_and_reversed = bool(
            post_extreme_breach and post_reentry and pd.notna(opposite_mss_time) and midpoint_touch
        )
        prior_90p = row.get("impulse_prior_90p_range", math.nan)
        exhausted_size = bool(
            (pd.notna(row["impulse_size_adr_share"]) and row["impulse_size_adr_share"] >= cfg.exhaustion_adr_share)
            or (pd.notna(prior_90p) and impulse_range >= prior_90p)
        )
        exhausted = exhausted_size and extension < 0.25 and late_retracement >= 0.50

        if both_pre_sides or both_impulse_sides_post:
            state = "5_double_sided_liquidity_sweep"
        elif full_reversal:
            state = "2_0830_false_breakout_full_reversal"
        elif swept_and_reversed:
            state = "4_0830_impulse_0930_sweep_reversal"
        elif exhausted:
            state = "7_exhausted_move"
        elif (
            cfg.partial_retracement_floor <= late_retracement <= cfg.partial_retracement_cap
            and new_directional_extreme
            and closes_directional_side
        ):
            state = "3_0830_partial_retracement_continuation"
        elif (
            extension >= cfg.continuation_extension
            and late_retracement < cfg.continuation_retracement_cap
            and closes_directional_side
        ):
            state = "1_0830_continuation"
        else:
            state = "6_range_chop"
        states.append(state)
        extensions.append(extension)
        late_retracements.append(late_retracement)

    output[f"lifecycle_state_{structure_minutes}m"] = states
    output["extension_through_1030_impulse_units"] = extensions
    output["retracement_through_1030_impulse_units"] = late_retracements
    output[f"opposite_mss_time_{structure_minutes}m"] = opposite_mss_times
    return output
