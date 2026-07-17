from __future__ import annotations

import math
from datetime import date

import pandas as pd

from .config import StudyConfig


def _timestamp(session_date: date, clock: str, timezone: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date.isoformat()} {clock}", tz=timezone)


def _window(
    prices: pd.DataFrame,
    session_date: date,
    start: str,
    end: str,
    timezone: str,
) -> pd.DataFrame:
    left = _timestamp(session_date, start, timezone)
    right = _timestamp(session_date, end, timezone)
    return prices[(prices.index >= left) & (prices.index < right)]


def _window_summary(frame: pd.DataFrame, prefix: str, expected_minutes: int) -> dict[str, float | int | bool]:
    if frame.empty:
        return {
            f"{prefix}_open": math.nan,
            f"{prefix}_high": math.nan,
            f"{prefix}_low": math.nan,
            f"{prefix}_midpoint": math.nan,
            f"{prefix}_close": math.nan,
            f"{prefix}_range": math.nan,
            f"{prefix}_log_return": math.nan,
            f"{prefix}_bar_count": 0,
            f"{prefix}_complete": False,
        }
    opening = float(frame["open"].iloc[0])
    closing = float(frame["close"].iloc[-1])
    high = float(frame["high"].max())
    low = float(frame["low"].min())
    return {
        f"{prefix}_open": opening,
        f"{prefix}_high": high,
        f"{prefix}_low": low,
        f"{prefix}_midpoint": (high + low) / 2,
        f"{prefix}_close": closing,
        f"{prefix}_range": high - low,
        f"{prefix}_log_return": math.log(closing / opening) if opening > 0 and closing > 0 else math.nan,
        f"{prefix}_bar_count": int(len(frame)),
        f"{prefix}_complete": len(frame) == expected_minutes,
    }


def _direction(opening: float, closing: float, deadband: float) -> int:
    if pd.isna(opening) or pd.isna(closing):
        return 0
    difference = closing - opening
    if abs(difference) <= deadband:
        return 0
    return 1 if difference > 0 else -1


def _first_true_time(mask: pd.Series) -> pd.Timestamp | pd.NaT:
    matches = mask[mask]
    return matches.index[0] if not matches.empty else pd.NaT


def _consecutive_confirmation(mask: pd.Series, count: int) -> pd.Timestamp | pd.NaT:
    if mask.empty:
        return pd.NaT
    run = mask.astype(int).rolling(count).sum()
    confirmed = run.eq(count)
    return _first_true_time(confirmed)


def _path_features(
    path: pd.DataFrame,
    *,
    direction: int,
    range_high: float,
    range_low: float,
    buffer: float,
    acceptance_closes: int,
    sweep_reentry_minutes: int,
) -> dict:
    empty = {
        "directional_boundary_breach_time": pd.NaT,
        "directional_boundary_acceptance_time": pd.NaT,
        "directional_boundary_reentry_time": pd.NaT,
        "reentry_before_acceptance": False,
        "directional_sweep": False,
        "breach_size": math.nan,
    }
    if path.empty or direction == 0 or pd.isna(range_high) or pd.isna(range_low):
        return empty
    if direction > 0:
        boundary = range_high
        breach_mask = path["high"].ge(boundary + buffer)
        outside_close = path["close"].gt(boundary + buffer)
        breach_size = float((path["high"] - boundary).clip(lower=0).max())
    else:
        boundary = range_low
        breach_mask = path["low"].le(boundary - buffer)
        outside_close = path["close"].lt(boundary - buffer)
        breach_size = float((boundary - path["low"]).clip(lower=0).max())
    breach_time = _first_true_time(breach_mask)
    if pd.isna(breach_time):
        return empty
    after_breach = path[path.index >= breach_time]
    acceptance_time = _consecutive_confirmation(outside_close.loc[after_breach.index], acceptance_closes)
    inside = after_breach["close"].gt(range_low + buffer) & after_breach["close"].lt(range_high - buffer)
    reentry_time = _first_true_time(inside)
    reentry_first = bool(
        pd.notna(reentry_time) and (pd.isna(acceptance_time) or reentry_time < acceptance_time)
    )
    elapsed = (
        (reentry_time - breach_time).total_seconds() / 60
        if pd.notna(reentry_time)
        else math.inf
    )
    return {
        "directional_boundary_breach_time": breach_time,
        "directional_boundary_acceptance_time": acceptance_time,
        "directional_boundary_reentry_time": reentry_time,
        "reentry_before_acceptance": reentry_first,
        "directional_sweep": reentry_first and elapsed <= sweep_reentry_minutes,
        "breach_size": breach_size,
    }


def _london_window(prices: pd.DataFrame, session_date: date, cfg: StudyConfig) -> pd.DataFrame:
    london_start = pd.Timestamp(f"{session_date.isoformat()} 08:00", tz=cfg.london_timezone)
    london_end = pd.Timestamp(f"{session_date.isoformat()} 12:00", tz=cfg.london_timezone)
    return prices[(prices.index >= london_start.tz_convert(cfg.timezone)) & (prices.index < london_end.tz_convert(cfg.timezone))]


def build_session_features(
    prices: pd.DataFrame,
    event_days: pd.DataFrame,
    *,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Calculate registered event-window and path features session by session."""

    cfg = config or StudyConfig()
    cfg.validate()
    tick_buffer = max(2 * cfg.minimum_tick_price, 0.0)

    daily = prices.groupby("session_date").agg(
        daily_high=("high", "max"),
        daily_low=("low", "min"),
        daily_close=("close", "last"),
    )
    daily["daily_range"] = daily["daily_high"] - daily["daily_low"]
    daily["prior_adr_20"] = daily["daily_range"].shift(1).rolling(
        cfg.adr_lookback, min_periods=max(10, cfg.adr_lookback // 2)
    ).mean()
    daily["previous_day_high"] = daily["daily_high"].shift(1)
    daily["previous_day_low"] = daily["daily_low"].shift(1)
    daily["prior_3d_return"] = daily["daily_close"].shift(1) / daily["daily_close"].shift(4) - 1
    daily["higher_timeframe_bias"] = daily["prior_3d_return"].apply(
        lambda value: "long" if value > 0 else ("short" if value < 0 else "neutral")
        if pd.notna(value)
        else "unknown"
    )

    records: list[dict] = []
    for session_date, event_row in event_days.iterrows():
        pre = _window(prices, session_date, cfg.pre_news_start, cfg.impulse_start, cfg.timezone)
        pre_secondary = _window(
            prices, session_date, cfg.pre_news_secondary_start, cfg.impulse_start, cfg.timezone
        )
        impulse = _window(prices, session_date, cfg.impulse_start, cfg.impulse_end, cfg.timezone)
        impulse_extended = _window(
            prices, session_date, cfg.impulse_start, cfg.extended_impulse_end, cfg.timezone
        )
        retracement = _window(
            prices, session_date, cfg.impulse_end, cfg.retracement_end, cfg.timezone
        )
        equity = _window(prices, session_date, cfg.equity_open, cfg.equity_reaction_end, cfg.timezone)
        delivery = _window(prices, session_date, cfg.equity_open, cfg.delivery_end, cfg.timezone)
        secondary = _window(prices, session_date, cfg.delivery_end, cfg.secondary_end, cfg.timezone)
        full_path = _window(prices, session_date, cfg.impulse_start, cfg.secondary_end, cfg.timezone)
        post_equity = _window(prices, session_date, cfg.equity_open, cfg.secondary_end, cfg.timezone)
        london = _london_window(prices, session_date, cfg)

        record: dict = {"session_date": session_date, **event_row.to_dict(), "tick_buffer": tick_buffer}
        record.update(_window_summary(pre, "pre_0730_0829", 60))
        record.update(_window_summary(pre_secondary, "pre_0800_0829", 30))
        record.update(_window_summary(impulse, "impulse_0830_0835", 5))
        record.update(_window_summary(impulse_extended, "impulse_0830_0845", 15))
        record.update(_window_summary(retracement, "retrace_0835_0929", 55))
        record.update(_window_summary(equity, "reaction_0930_0950", 20))
        record.update(_window_summary(delivery, "delivery_0930_1000", 30))
        record.update(_window_summary(secondary, "secondary_1000_1030", 30))
        record.update(_window_summary(london, "london_0800_1200_local", 240))

        daily_row = daily.loc[session_date] if session_date in daily.index else pd.Series(dtype=float)
        for key in (
            "prior_adr_20",
            "previous_day_high",
            "previous_day_low",
            "prior_3d_return",
            "higher_timeframe_bias",
        ):
            record[key] = daily_row.get(key, math.nan)

        opening = record["impulse_0830_0835_open"]
        closing = record["impulse_0830_0835_close"]
        direction = _direction(opening, closing, cfg.minimum_tick_price)
        impulse_range = record["impulse_0830_0835_range"]
        impulse_high = record["impulse_0830_0835_high"]
        impulse_low = record["impulse_0830_0835_low"]
        midpoint = (impulse_high + impulse_low) / 2 if pd.notna(impulse_high) else math.nan
        record["impulse_direction"] = direction
        record["impulse_midpoint"] = midpoint
        record["open_0830"] = record["impulse_0830_0835_open"]
        record["open_0930"] = record["reaction_0930_0950_open"]
        record["open_1000"] = record["secondary_1000_1030_open"]
        record["impulse_size_adr_share"] = (
            impulse_range / record["prior_adr_20"]
            if pd.notna(record["prior_adr_20"]) and record["prior_adr_20"] > 0
            else math.nan
        )
        record["impulse_size_pct_adr"] = (
            100 * record["impulse_size_adr_share"]
            if pd.notna(record["impulse_size_adr_share"])
            else math.nan
        )

        if direction > 0 and not retracement.empty and impulse_range > 0:
            retracement_price = max(0.0, impulse_high - float(retracement["low"].min()))
            midpoint_hold = bool(retracement["close"].ge(midpoint - tick_buffer).all())
            midpoint_loss_time = _first_true_time(retracement["close"].lt(midpoint - tick_buffer))
        elif direction < 0 and not retracement.empty and impulse_range > 0:
            retracement_price = max(0.0, float(retracement["high"].max()) - impulse_low)
            midpoint_hold = bool(retracement["close"].le(midpoint + tick_buffer).all())
            midpoint_loss_time = _first_true_time(retracement["close"].gt(midpoint + tick_buffer))
        else:
            retracement_price = math.nan
            midpoint_hold = False
            midpoint_loss_time = pd.NaT
        record["max_retracement_price_0835_0929"] = retracement_price
        record["max_retracement_depth_0835_0929"] = (
            retracement_price / impulse_range
            if pd.notna(retracement_price) and impulse_range > 0
            else math.nan
        )
        record["holds_impulse_midpoint_to_0930"] = midpoint_hold
        record["impulse_midpoint_loss_time"] = midpoint_loss_time
        if not retracement.empty and pd.notna(record["pre_0730_0829_high"]):
            inside = retracement["close"].between(
                record["pre_0730_0829_low"] + tick_buffer,
                record["pre_0730_0829_high"] - tick_buffer,
                inclusive="both",
            )
            record["returns_inside_pre_news_range"] = bool(inside.any())
        else:
            record["returns_inside_pre_news_range"] = False

        record["post_0930_sweeps_0830_high"] = bool(
            not post_equity.empty
            and pd.notna(impulse_high)
            and post_equity["high"].ge(impulse_high + tick_buffer).any()
        )
        record["post_0930_sweeps_0830_low"] = bool(
            not post_equity.empty
            and pd.notna(impulse_low)
            and post_equity["low"].le(impulse_low - tick_buffer).any()
        )
        reaction_direction = _direction(
            record["reaction_0930_0950_open"],
            record["reaction_0930_0950_close"],
            cfg.minimum_tick_price,
        )
        record["reaction_0930_direction"] = reaction_direction
        record["directional_agreement_0830_0930"] = bool(
            direction != 0 and reaction_direction == direction
        )
        record["reaction_0930_continues_0830_direction"] = bool(
            direction != 0 and reaction_direction == direction
        )
        record["reaction_0930_reverses_0830_direction"] = bool(
            direction != 0 and reaction_direction == -direction
        )
        record["directional_relationship_0830_0930"] = (
            "agreement"
            if direction != 0 and reaction_direction == direction
            else "opposition"
            if direction != 0 and reaction_direction == -direction
            else "neutral"
        )
        record.update(
            _path_features(
                full_path,
                direction=direction,
                range_high=record["pre_0730_0829_high"],
                range_low=record["pre_0730_0829_low"],
                buffer=tick_buffer,
                acceptance_closes=cfg.acceptance_closes,
                sweep_reentry_minutes=cfg.sweep_reentry_minutes,
            )
        )
        records.append(record)

    features = pd.DataFrame.from_records(records).set_index("session_date").sort_index()
    features["impulse_same_time_median_range"] = features["impulse_0830_0835_range"].shift(1).rolling(
        cfg.same_time_lookback, min_periods=cfg.minimum_history_sessions
    ).median()
    features["impulse_same_time_multiple"] = (
        features["impulse_0830_0835_range"] / features["impulse_same_time_median_range"]
    )
    features["impulse_prior_90p_range"] = features["impulse_0830_0835_range"].shift(1).rolling(
        cfg.same_time_lookback, min_periods=cfg.minimum_history_sessions
    ).quantile(0.90)
    features["impulse_size_bucket"] = pd.cut(
        features["impulse_same_time_multiple"],
        bins=[-math.inf, 0.75, 1.25, 2.0, math.inf],
        labels=["small", "normal", "large", "extreme"],
    ).astype("string")
    features["impulse_side"] = features["impulse_direction"].map({1: "long", -1: "short", 0: "neutral"})
    features["higher_timeframe_bias_alignment"] = (
        features["impulse_side"].eq(features["higher_timeframe_bias"])
    )
    required_complete = [
        "pre_0730_0829_complete",
        "impulse_0830_0835_complete",
        "retrace_0835_0929_complete",
        "reaction_0930_0950_complete",
        "delivery_0930_1000_complete",
        "secondary_1000_1030_complete",
    ]
    features["core_windows_complete"] = features[required_complete].all(axis=1)
    return features


def build_five_minute_heatmap_data(
    prices: pd.DataFrame,
    event_days: pd.DataFrame,
    *,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Return class-by-five-minute average absolute, directional and range movement."""

    cfg = config or StudyConfig()
    start_clock, end_clock = "08:00", "10:30"
    rows: list[dict] = []
    for session_date, event_row in event_days.iterrows():
        frame = _window(prices, session_date, start_clock, end_clock, cfg.timezone)
        if frame.empty:
            continue
        bars = frame[["open", "high", "low", "close"]].resample(
            "5min", label="left", closed="left"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        for timestamp, bar in bars.iterrows():
            directional_bp = 10000 * math.log(float(bar["close"]) / float(bar["open"]))
            range_bp = 10000 * (float(bar["high"]) - float(bar["low"])) / float(bar["open"])
            rows.append(
                {
                    "session_date": session_date,
                    "event_class": event_row["event_class"],
                    "important_1000_release": bool(event_row["important_1000_release"]),
                    "bucket_et": timestamp.strftime("%H:%M"),
                    "directional_return_bp": directional_bp,
                    "absolute_return_bp": abs(directional_bp),
                    "high_low_range_bp": range_bp,
                }
            )
    raw = pd.DataFrame.from_records(rows)
    if raw.empty:
        return raw
    return (
        raw.groupby(["event_class", "important_1000_release", "bucket_et"], as_index=False)
        .agg(
            sessions=("session_date", "nunique"),
            average_directional_return_bp=("directional_return_bp", "mean"),
            average_absolute_return_bp=("absolute_return_bp", "mean"),
            average_high_low_range_bp=("high_low_range_bp", "mean"),
        )
        .sort_values(["event_class", "important_1000_release", "bucket_et"])
    )
