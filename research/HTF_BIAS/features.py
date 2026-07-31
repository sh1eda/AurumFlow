"""Market qualification, causal HTF features, and neutral forward outcomes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import numpy as np
import pandas as pd

from .definitions import (
    EVALUATION_CLOCKS,
    FORWARD_HORIZONS_MINUTES,
    NEUTRAL_RETURN_BPS,
    NEW_YORK_TIMEZONE,
    SESSION_ENDPOINT_CLOCK,
)


REQUIRED_MARKET_COLUMNS = {
    "timestamp",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "mid_open",
    "mid_high",
    "mid_low",
    "mid_close",
    "median_spread",
    "maximum_spread",
    "source",
    "symbol",
}


class DataQualificationError(ValueError):
    """Raised when the validated derivative no longer satisfies its contract."""


@dataclass(frozen=True)
class BuildResult:
    samples: pd.DataFrame
    exclusions: pd.DataFrame
    data_quality: dict[str, object]
    feature_audit: pd.DataFrame


def _json_scalar(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    return value


def _expected_open_mask(index: pd.DatetimeIndex) -> np.ndarray:
    local = index.tz_convert(NEW_YORK_TIMEZONE)
    weekday = local.weekday
    minute = local.hour * 60 + local.minute
    maintenance = (weekday <= 3) & (minute >= 17 * 60) & (minute < 18 * 60)
    friday_close = (weekday == 4) & (minute >= 17 * 60)
    saturday = weekday == 5
    sunday_preopen = (weekday == 6) & (minute < 18 * 60)
    return np.asarray(~(maintenance | friday_close | saturday | sunday_preopen))


def qualify_market_data(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fail closed on structural defects and return a read-only analytical view."""

    missing = sorted(REQUIRED_MARKET_COLUMNS - set(raw.columns))
    if missing:
        raise DataQualificationError(f"canonical one-minute input is missing columns: {missing}")

    frame = raw.copy()
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    invalid_timestamps = int(timestamps.isna().sum())
    if invalid_timestamps:
        raise DataQualificationError(f"market input has {invalid_timestamps} invalid timestamps")
    duplicate_timestamps = int(timestamps.duplicated().sum())
    if duplicate_timestamps:
        raise DataQualificationError(
            f"market input has {duplicate_timestamps} duplicate one-minute timestamps"
        )
    if not timestamps.is_monotonic_increasing:
        raise DataQualificationError("market timestamps are not monotonically increasing")

    numeric = sorted(
        (REQUIRED_MARKET_COLUMNS - {"timestamp", "source", "symbol"})
        | ({"last_spread"} if "last_spread" in frame else set())
    )
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    non_numeric_rows = int(frame[numeric].isna().any(axis=1).sum())
    if non_numeric_rows:
        raise DataQualificationError(
            f"market input has {non_numeric_rows} rows with non-numeric required prices"
        )

    invalid_ohlc = pd.Series(False, index=frame.index)
    bid_above_ask = pd.Series(False, index=frame.index)
    for side in ("bid", "ask", "mid"):
        invalid_ohlc |= (
            frame[f"{side}_high"].lt(
                frame[[f"{side}_open", f"{side}_close"]].max(axis=1)
            )
            | frame[f"{side}_low"].gt(
                frame[[f"{side}_open", f"{side}_close"]].min(axis=1)
            )
            | frame[f"{side}_high"].lt(frame[f"{side}_low"])
        )
    for field in ("open", "high", "low", "close"):
        bid_above_ask |= frame[f"bid_{field}"].gt(frame[f"ask_{field}"])
    if invalid_ohlc.any():
        raise DataQualificationError(
            f"market input has {int(invalid_ohlc.sum())} OHLC invariant violations"
        )
    if bid_above_ask.any():
        raise DataQualificationError(
            f"market input has {int(bid_above_ask.sum())} bid-above-ask rows"
        )

    frame.index = pd.DatetimeIndex(timestamps, name="timestamp_utc")
    frame.drop(columns=["timestamp"], inplace=True)
    local = frame.index.tz_convert(NEW_YORK_TIMEZONE)
    frame["timestamp_new_york"] = local
    frame["date_new_york"] = local.date
    frame["day_of_week"] = local.weekday

    deltas = frame.index.to_series().diff().dropna().dt.total_seconds().div(60)
    positive_deltas = deltas[deltas.gt(0)]
    modal_minutes = float(positive_deltas.mode().iloc[0]) if not positive_deltas.empty else math.nan
    if modal_minutes != 1.0:
        raise DataQualificationError(
            f"canonical market input is not one-minute data (modal interval {modal_minutes})"
        )

    expected_index = pd.date_range(frame.index[0], frame.index[-1], freq="1min")
    expected_open = expected_index[_expected_open_mask(expected_index)]
    observed = pd.DatetimeIndex(frame.index)
    missing_open = expected_open.difference(observed)
    unexpected_closed = observed[~_expected_open_mask(observed)]
    missing_periods: list[dict[str, object]] = []
    if len(missing_open):
        missing_series = pd.Series(missing_open).sort_values().reset_index(drop=True)
        groups = missing_series.diff().ne(pd.Timedelta(minutes=1)).cumsum()
        for _, group in missing_series.groupby(groups):
            missing_periods.append(
                {
                    "start_utc": group.iloc[0].isoformat(),
                    "end_utc": group.iloc[-1].isoformat(),
                    "minutes": int(len(group)),
                }
            )
        missing_periods = sorted(
            missing_periods, key=lambda item: int(item["minutes"]), reverse=True
        )
    zero_spread = int(frame["median_spread"].le(0).sum())
    extreme_spread = int(frame["maximum_spread"].gt(5.0).sum())

    quality: dict[str, object] = {
        "verdict": "qualified_with_documented_warnings",
        "row_count": int(len(frame)),
        "first_timestamp_utc": frame.index[0].isoformat(),
        "last_timestamp_utc": frame.index[-1].isoformat(),
        "first_timestamp_new_york": local[0].isoformat(),
        "last_timestamp_new_york": local[-1].isoformat(),
        "timestamp_column": "timestamp",
        "canonical_timezone": "UTC",
        "evaluation_timezone": NEW_YORK_TIMEZONE,
        "source_timezone_mapping": "validated Europe/Helsinki IANA mapping; source timezone is strongly supported but not broker-documented",
        "structure": "one-minute bid/ask OHLC plus derived mid OHLC and observed spread summaries",
        "modal_interval_minutes": modal_minutes,
        "duplicate_timestamps": duplicate_timestamps,
        "timestamp_reversals": 0,
        "invalid_ohlc_rows": 0,
        "bid_above_ask_rows": 0,
        "expected_open_minutes_in_file_span": int(len(expected_open)),
        "missing_expected_open_minutes": int(len(missing_open)),
        "missing_expected_open_percentage": round(
            100.0 * len(missing_open) / len(expected_open), 6
        )
        if len(expected_open)
        else None,
        "missing_period_count": int(len(missing_periods)),
        "longest_missing_period_minutes": int(missing_periods[0]["minutes"])
        if missing_periods
        else 0,
        "largest_missing_periods": missing_periods[:20],
        "unexpected_known_closure_minutes": int(len(unexpected_closed)),
        "zero_median_spread_minutes": zero_spread,
        "maximum_spread_above_5_minutes": extreme_spread,
        "symbols": sorted(frame["symbol"].astype(str).unique().tolist()),
        "sources": sorted(frame["source"].astype(str).unique().tolist()),
        "weekend_and_closure_rule": "17:00-18:00 ET Mon-Thu maintenance; Friday 17:00-Sunday 18:00 ET closed",
        "normalization_reused": True,
        "warnings": [
            "Only one year of high-frequency history is available, so year-by-year stability cannot be established.",
            "The broker server timezone is empirically strongly supported but not confirmed by broker documentation.",
            "Zero and extreme observed spread states are retained and evaluated through spread-filter sensitivities.",
            "XAUUSD is a fragmented spot feed rather than a consolidated tape.",
        ],
    }
    return frame, quality


def qualify_calendar(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"date_et", "has_0830_release", "news_day_class", "categories_present"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise DataQualificationError(f"calendar input is missing columns: {missing}")
    calendar = raw.copy()
    calendar["date_et"] = pd.to_datetime(calendar["date_et"], errors="coerce").dt.date
    if calendar["date_et"].isna().any():
        raise DataQualificationError("calendar input contains invalid date_et values")
    if calendar["date_et"].duplicated().any():
        raise DataQualificationError("calendar input contains duplicate date_et rows")
    if calendar["has_0830_release"].dtype != bool:
        calendar["has_0830_release"] = (
            calendar["has_0830_release"].astype(str).str.lower().eq("true")
        )
    return calendar.set_index("date_et", drop=False).sort_index()


def _daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    daily = frame.groupby("date_new_york", sort=True).agg(
        open=("mid_open", "first"),
        high=("mid_high", "max"),
        low=("mid_low", "min"),
        close=("mid_close", "last"),
        observed_minutes=("mid_close", "size"),
        maximum_spread=("maximum_spread", "max"),
    )
    dates = pd.to_datetime(pd.Index(daily.index))
    daily["weekday"] = dates.weekday
    daily["expected_minutes"] = np.select(
        [daily["weekday"].le(3), daily["weekday"].eq(4)],
        [1380, 1020],
        default=0,
    )
    daily["coverage"] = daily["observed_minutes"] / daily["expected_minutes"].replace(0, np.nan)
    daily["eligible"] = daily["weekday"].le(4) & daily["coverage"].ge(0.90)
    local_midnight = pd.DatetimeIndex(dates).tz_localize(NEW_YORK_TIMEZONE)
    daily["available_at"] = local_midnight + pd.Timedelta(days=1)
    daily["range"] = daily["high"] - daily["low"]
    return daily


def _market_week_start(local: pd.DatetimeIndex) -> pd.DatetimeIndex:
    naive_day = local.tz_localize(None).normalize()
    weekday = local.weekday
    start = naive_day - pd.to_timedelta(weekday, unit="D")
    start = start + pd.to_timedelta(np.where(weekday == 6, 7, 0), unit="D")
    return pd.DatetimeIndex(start)


def _weekly_bars(frame: pd.DataFrame) -> pd.DataFrame:
    local = frame.index.tz_convert(NEW_YORK_TIMEZONE)
    work = frame.copy()
    work["market_week_start"] = _market_week_start(local).date
    weekly = work.groupby("market_week_start", sort=True).agg(
        open=("mid_open", "first"),
        high=("mid_high", "max"),
        low=("mid_low", "min"),
        close=("mid_close", "last"),
        observed_minutes=("mid_close", "size"),
        observed_dates=("date_new_york", "nunique"),
    )
    weekly["expected_minutes"] = 6900
    weekly["coverage"] = weekly["observed_minutes"] / weekly["expected_minutes"]
    weekly["eligible"] = weekly["coverage"].ge(0.65)
    starts = pd.DatetimeIndex(pd.to_datetime(weekly.index)).tz_localize(NEW_YORK_TIMEZONE)
    weekly["available_at"] = starts + pd.Timedelta(days=5)
    weekly["range"] = weekly["high"] - weekly["low"]
    weekly["partial_week"] = weekly["coverage"].lt(0.90)
    return weekly


def _aggregate_h4(frame: pd.DataFrame) -> pd.DataFrame:
    aggregated = frame[["mid_open", "mid_high", "mid_low", "mid_close"]].resample(
        "4h", label="left", closed="left", origin="epoch"
    ).agg(
        open=("mid_open", "first"),
        high=("mid_high", "max"),
        low=("mid_low", "min"),
        close=("mid_close", "last"),
    )
    counts = frame["mid_close"].resample(
        "4h", label="left", closed="left", origin="epoch"
    ).size()
    aggregated["observed_minutes"] = counts
    aggregated = aggregated.dropna(subset=["open", "high", "low", "close"])
    aggregated = aggregated[aggregated["observed_minutes"].ge(180)].copy()
    aggregated["available_at"] = aggregated.index + pd.Timedelta(hours=4)
    aggregated["range"] = aggregated["high"] - aggregated["low"]
    return aggregated


def _mark_displacement(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    prior_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prior_close).abs(),
            (out["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    prior_atr = true_range.shift(1).rolling(14, min_periods=10).mean()
    prior_median = true_range.shift(1).rolling(20, min_periods=10).median()
    bar_range = (out["high"] - out["low"]).replace(0, np.nan)
    body = out["close"] - out["open"]
    direction = np.sign(body).astype(int)
    body_fraction = body.abs() / bar_range
    close_from_low = (out["close"] - out["low"]) / bar_range
    directional_close = (
        (direction > 0) & close_from_low.ge(0.75)
    ) | ((direction < 0) & close_from_low.le(0.25))
    primary = (
        body_fraction.ge(0.60)
        & (bar_range / prior_atr).ge(1.25)
        & directional_close
    )
    robust = (
        body_fraction.ge(0.55)
        & (bar_range / prior_median).ge(1.50)
        & directional_close
    )
    out["true_range"] = true_range
    out["prior_atr14"] = prior_atr
    out["prior_median_range20"] = prior_median
    out["body_fraction"] = body_fraction
    out["displacement_direction"] = np.where(primary, direction, 0).astype(int)
    out["robust_displacement_direction"] = np.where(robust, direction, 0).astype(int)
    return out


def confirmed_swings(bars: pd.DataFrame, *, width: int) -> pd.DataFrame:
    """Return pivots only at their right-side bar availability timestamp."""

    if width < 1:
        raise ValueError("swing width must be positive")
    required = {"high", "low", "available_at"}
    if not required.issubset(bars.columns):
        raise ValueError(f"swing bars require columns {sorted(required)}")
    records: list[dict[str, object]] = []
    for position in range(width, len(bars) - width):
        current = bars.iloc[position]
        left = bars.iloc[position - width : position]
        right = bars.iloc[position + 1 : position + width + 1]
        pivot_at = bars.index[position]
        confirmation_at = pd.Timestamp(bars.iloc[position + width]["available_at"])
        if current["high"] > left["high"].max() and current["high"] > right["high"].max():
            records.append(
                {
                    "pivot_at": pivot_at,
                    "confirmation_at": confirmation_at,
                    "swing_type": "high",
                    "level": float(current["high"]),
                    "width": width,
                }
            )
        if current["low"] < left["low"].min() and current["low"] < right["low"].min():
            records.append(
                {
                    "pivot_at": pivot_at,
                    "confirmation_at": confirmation_at,
                    "swing_type": "low",
                    "level": float(current["low"]),
                    "width": width,
                }
            )
    columns = ["pivot_at", "confirmation_at", "swing_type", "level", "width"]
    return pd.DataFrame.from_records(records, columns=columns)


def _structure_at(swings: pd.DataFrame, cutoff: pd.Timestamp) -> dict[str, object]:
    eligible = swings[pd.to_datetime(swings["confirmation_at"], utc=True).le(cutoff)]
    highs = eligible[eligible["swing_type"].eq("high")].tail(2)
    lows = eligible[eligible["swing_type"].eq("low")].tail(2)
    if len(highs) < 2 or len(lows) < 2:
        return {
            "direction": 0,
            "available_at": pd.NaT,
            "last_high": math.nan,
            "last_low": math.nan,
        }
    high_change = float(highs["level"].iloc[-1] - highs["level"].iloc[-2])
    low_change = float(lows["level"].iloc[-1] - lows["level"].iloc[-2])
    direction = 1 if high_change > 0 and low_change > 0 else -1 if high_change < 0 and low_change < 0 else 0
    availability = max(
        pd.Timestamp(highs["confirmation_at"].iloc[-1]),
        pd.Timestamp(lows["confirmation_at"].iloc[-1]),
    )
    return {
        "direction": direction,
        "available_at": availability,
        "last_high": float(highs["level"].iloc[-1]),
        "last_low": float(lows["level"].iloc[-1]),
    }


def _last_row_available(bars: pd.DataFrame, cutoff: pd.Timestamp) -> pd.Series | None:
    eligible = bars[pd.to_datetime(bars["available_at"], utc=True).le(cutoff)]
    return eligible.iloc[-1] if not eligible.empty else None


def _safe_position(price: float, low: float, high: float) -> float:
    width = high - low
    return (price - low) / width if width > 0 else math.nan


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if pd.notna(denominator) and denominator > 0 else math.nan


def _asof_close(frame: pd.DataFrame, timestamp: pd.Timestamp) -> float:
    position = frame.index.searchsorted(timestamp, side="right") - 1
    return float(frame["mid_close"].iloc[position]) if position >= 0 else math.nan


def _outcome_window(
    frame: pd.DataFrame,
    *,
    evaluation_at: pd.Timestamp,
    endpoint: pd.Timestamp,
    evaluation_price: float,
    known_levels: dict[str, float],
    label: str,
) -> tuple[dict[str, object], str | None]:
    expected_minutes = int((endpoint - evaluation_at).total_seconds() // 60)
    if expected_minutes <= 0:
        return {}, "non_positive_outcome_horizon"
    window = frame.loc[(frame.index >= evaluation_at) & (frame.index < endpoint)]
    required_last = endpoint - pd.Timedelta(minutes=1)
    coverage = len(window) / expected_minutes
    if required_last not in window.index or coverage < 0.95:
        return {}, f"incomplete_{label}_outcome_window"
    ending = float(window["mid_close"].iloc[-1])
    forward_bps = 10000.0 * math.log(ending / evaluation_price)
    direction = 1 if forward_bps > NEUTRAL_RETURN_BPS else -1 if forward_bps < -NEUTRAL_RETURN_BPS else 0
    high = float(window["mid_high"].max())
    low = float(window["mid_low"].min())
    minute_returns = np.log(window["mid_close"] / window["mid_close"].shift(1)).dropna()
    result: dict[str, object] = {
        f"forward_return_bps_{label}": forward_bps,
        f"absolute_return_bps_{label}": abs(forward_bps),
        f"direction_{label}": direction,
        f"up_excursion_bps_{label}": 10000.0 * math.log(high / evaluation_price),
        f"down_excursion_bps_{label}": 10000.0 * math.log(evaluation_price / low),
        f"range_expansion_bps_{label}": 10000.0 * math.log(high / low),
        f"realized_volatility_bps_{label}": 10000.0 * math.sqrt(float(np.square(minute_returns).sum())),
        f"outcome_coverage_{label}": coverage,
        f"outcome_available_at_{label}": endpoint,
    }
    for level_name, level in known_levels.items():
        if pd.isna(level):
            result[f"reaches_{level_name}_{label}"] = math.nan
        else:
            result[f"reaches_{level_name}_{label}"] = bool(low <= level <= high)
    return result, None


def _candidate_combine(first: object, second: object) -> int:
    a = int(first) if pd.notna(first) else 0
    b = int(second) if pd.notna(second) else 0
    if a and b and a != b:
        return 0
    return a or b


def _candidate_directions(record: dict[str, object]) -> dict[str, int]:
    candidate_a = _candidate_combine(
        record.get("daily_structure_w2", 0), record.get("h4_structure_w2", 0)
    )
    positions = [
        float(record[name]) - 0.5
        for name in ("prior_day_position", "prior_week_position")
        if pd.notna(record.get(name))
    ]
    centered = float(np.mean(positions)) if positions else math.nan
    candidate_b = 1 if centered > 0.10 else -1 if centered < -0.10 else 0

    price = float(record["evaluation_price"])
    upper: list[float] = []
    lower: list[float] = []
    for prefix, high_name, low_name, touched_high, touched_low in (
        ("pd", "prior_day_high", "prior_day_low", "pdh_touched_before_evaluation", "pdl_touched_before_evaluation"),
        ("pw", "prior_week_high", "prior_week_low", "pwh_touched_before_evaluation", "pwl_touched_before_evaluation"),
        ("monday", "monday_high", "monday_low", "monday_high_taken_before_evaluation", "monday_low_taken_before_evaluation"),
    ):
        if prefix == "monday" and not bool(record.get("monday_range_complete", False)):
            continue
        high = record.get(high_name, math.nan)
        low = record.get(low_name, math.nan)
        if pd.notna(high) and float(high) > price and not bool(record.get(touched_high, False)):
            upper.append(float(high) - price)
        if pd.notna(low) and float(low) < price and not bool(record.get(touched_low, False)):
            lower.append(price - float(low))
    up_distance = min(upper) if upper else math.inf
    down_distance = min(lower) if lower else math.inf
    candidate_c = 0
    if math.isfinite(up_distance) or math.isfinite(down_distance):
        candidate_c = 1 if up_distance < down_distance else -1 if down_distance < up_distance else 0

    candidate_d = _candidate_combine(
        record.get("daily_displacement_direction", 0),
        record.get("h4_displacement_direction", 0),
    )
    alt_a = _candidate_combine(
        record.get("daily_structure_w3", 0), record.get("h4_structure_w3", 0)
    )
    alt_d = _candidate_combine(
        record.get("daily_robust_displacement_direction", 0),
        record.get("h4_robust_displacement_direction", 0),
    )
    return {
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "candidate_c": candidate_c,
        "candidate_d": candidate_d,
        "candidate_a_width3": alt_a,
        "candidate_b_reversion": -candidate_b,
        "candidate_c_away": -candidate_c,
        "candidate_d_robust_volatility": alt_d,
    }


def build_phase1_samples(
    raw_market: pd.DataFrame,
    raw_calendar: pd.DataFrame,
    *,
    evaluation_clocks: Iterable[str] = EVALUATION_CLOCKS,
) -> BuildResult:
    """Build causal evaluation rows; features never read a bar at/after evaluation."""

    frame, data_quality = qualify_market_data(raw_market)
    calendar = qualify_calendar(raw_calendar)
    daily = _daily_bars(frame)
    weekly = _weekly_bars(frame)
    eligible_daily = _mark_displacement(daily[daily["eligible"]].copy())
    h4 = _mark_displacement(_aggregate_h4(frame))
    swing_tables = {
        ("daily", width): confirmed_swings(eligible_daily, width=width)
        for width in (2, 3)
    }
    swing_tables.update(
        {
            ("h4", width): confirmed_swings(h4, width=width)
            for width in (2, 3)
        }
    )

    date_candidates = sorted(
        set(calendar.index)
        & {value for value in frame["date_new_york"].unique() if pd.Timestamp(value).weekday() < 5}
    )
    records: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []

    for session_date in date_candidates:
        calendar_row = calendar.loc[session_date]
        session_day = pd.Timestamp(session_date)
        weekday = int(session_day.weekday())
        week_start_date = (session_day - pd.Timedelta(days=weekday)).date()
        day_start_local = pd.Timestamp(session_date, tz=NEW_YORK_TIMEZONE)
        day_end_local = day_start_local + pd.Timedelta(days=1)
        monday_start_local = pd.Timestamp(week_start_date, tz=NEW_YORK_TIMEZONE)

        for evaluation_clock in evaluation_clocks:
            evaluation_local = pd.Timestamp(
                f"{session_date.isoformat()} {evaluation_clock}", tz=NEW_YORK_TIMEZONE
            )
            evaluation_at = evaluation_local.tz_convert("UTC")
            if evaluation_at not in frame.index:
                exclusions.append(
                    {
                        "session_date": session_date.isoformat(),
                        "evaluation_clock": evaluation_clock,
                        "reason": "missing_evaluation_bar",
                    }
                )
                continue
            evaluation_bar = frame.loc[evaluation_at]
            evaluation_price = float(evaluation_bar["mid_open"])
            record: dict[str, object] = {
                "sample_id": f"{session_date.isoformat()}_{evaluation_clock.replace(':', '')}",
                "session_date": session_date.isoformat(),
                "evaluation_clock": evaluation_clock,
                "evaluation_timestamp_new_york": evaluation_local,
                "evaluation_timestamp_utc": evaluation_at,
                "evaluation_price": evaluation_price,
                "day_of_week": weekday,
                "news_0830": bool(calendar_row["has_0830_release"]),
                "news_day_class": str(calendar_row["news_day_class"]),
                "news_categories": str(calendar_row["categories_present"]),
                "evaluation_median_spread": float(evaluation_bar["median_spread"]),
                "evaluation_maximum_spread": float(evaluation_bar["maximum_spread"]),
                "intraday_cutoff_at": evaluation_at,
            }

            prior_day = daily[
                daily["eligible"] & (pd.to_datetime(daily.index).date < session_date)
            ]
            if not prior_day.empty:
                pd_row = prior_day.iloc[-1]
                pd_range = float(pd_row["range"])
                pd_high = float(pd_row["high"])
                pd_low = float(pd_row["low"])
                record.update(
                    {
                        "prior_day_date": str(prior_day.index[-1]),
                        "prior_day_high": pd_high,
                        "prior_day_low": pd_low,
                        "prior_day_range": pd_range,
                        "prior_day_position": _safe_position(evaluation_price, pd_low, pd_high),
                        "distance_to_pdh_range": _safe_ratio(pd_high - evaluation_price, pd_range),
                        "distance_to_pdl_range": _safe_ratio(evaluation_price - pd_low, pd_range),
                        "prior_day_available_at": pd.Timestamp(pd_row["available_at"]),
                    }
                )
            else:
                record.update(
                    {
                        "prior_day_high": math.nan,
                        "prior_day_low": math.nan,
                        "prior_day_range": math.nan,
                        "prior_day_position": math.nan,
                        "distance_to_pdh_range": math.nan,
                        "distance_to_pdl_range": math.nan,
                        "prior_day_available_at": pd.NaT,
                    }
                )

            prior_week = weekly[
                weekly["eligible"] & (pd.to_datetime(weekly.index).date < week_start_date)
            ]
            if not prior_week.empty:
                pw_row = prior_week.iloc[-1]
                pw_range = float(pw_row["range"])
                pw_high = float(pw_row["high"])
                pw_low = float(pw_row["low"])
                record.update(
                    {
                        "prior_week_start": str(prior_week.index[-1]),
                        "prior_week_high": pw_high,
                        "prior_week_low": pw_low,
                        "prior_week_range": pw_range,
                        "prior_week_position": _safe_position(evaluation_price, pw_low, pw_high),
                        "distance_to_pwh_range": _safe_ratio(pw_high - evaluation_price, pw_range),
                        "distance_to_pwl_range": _safe_ratio(evaluation_price - pw_low, pw_range),
                        "prior_week_partial": bool(pw_row["partial_week"]),
                        "prior_week_available_at": pd.Timestamp(pw_row["available_at"]),
                    }
                )
            else:
                record.update(
                    {
                        "prior_week_high": math.nan,
                        "prior_week_low": math.nan,
                        "prior_week_range": math.nan,
                        "prior_week_position": math.nan,
                        "distance_to_pwh_range": math.nan,
                        "distance_to_pwl_range": math.nan,
                        "prior_week_partial": True,
                        "prior_week_available_at": pd.NaT,
                    }
                )

            current_day_path = frame.loc[
                (frame.index >= day_start_local.tz_convert("UTC"))
                & (frame.index < evaluation_at)
            ]
            record["pdh_touched_before_evaluation"] = bool(
                pd.notna(record["prior_day_high"])
                and not current_day_path.empty
                and current_day_path["mid_high"].max() >= record["prior_day_high"]
            )
            record["pdl_touched_before_evaluation"] = bool(
                pd.notna(record["prior_day_low"])
                and not current_day_path.empty
                and current_day_path["mid_low"].min() <= record["prior_day_low"]
            )

            current_week_path = frame.loc[
                (frame.index >= (monday_start_local - pd.Timedelta(hours=6)).tz_convert("UTC"))
                & (frame.index < evaluation_at)
            ]
            record["pwh_touched_before_evaluation"] = bool(
                pd.notna(record["prior_week_high"])
                and not current_week_path.empty
                and current_week_path["mid_high"].max() >= record["prior_week_high"]
            )
            record["pwl_touched_before_evaluation"] = bool(
                pd.notna(record["prior_week_low"])
                and not current_week_path.empty
                and current_week_path["mid_low"].min() <= record["prior_week_low"]
            )

            monday_end = min(day_end_local if weekday == 0 else monday_start_local + pd.Timedelta(days=1), evaluation_local)
            monday_path = frame.loc[
                (frame.index >= monday_start_local.tz_convert("UTC"))
                & (frame.index < monday_end.tz_convert("UTC"))
            ]
            monday_daily = daily.loc[week_start_date] if week_start_date in daily.index else None
            monday_complete = bool(
                weekday > 0 and monday_daily is not None and monday_daily["eligible"]
            )
            if not monday_path.empty:
                monday_high = float(monday_path["mid_high"].max())
                monday_low = float(monday_path["mid_low"].min())
                monday_available = monday_path.index[-1] + pd.Timedelta(minutes=1)
                record.update(
                    {
                        "monday_high": monday_high,
                        "monday_low": monday_low,
                        "monday_range": monday_high - monday_low,
                        "monday_position": _safe_position(evaluation_price, monday_low, monday_high),
                        "monday_range_complete": monday_complete,
                        "monday_range_partial_or_holiday": not monday_complete,
                        "monday_range_available_at": monday_available,
                    }
                )
            else:
                record.update(
                    {
                        "monday_high": math.nan,
                        "monday_low": math.nan,
                        "monday_range": math.nan,
                        "monday_position": math.nan,
                        "monday_range_complete": False,
                        "monday_range_partial_or_holiday": True,
                        "monday_range_available_at": pd.NaT,
                    }
                )
            post_monday = frame.loc[
                (frame.index >= (monday_start_local + pd.Timedelta(days=1)).tz_convert("UTC"))
                & (frame.index < evaluation_at)
            ]
            record["monday_high_taken_before_evaluation"] = bool(
                monday_complete
                and not post_monday.empty
                and post_monday["mid_high"].max() >= record["monday_high"]
            )
            record["monday_low_taken_before_evaluation"] = bool(
                monday_complete
                and not post_monday.empty
                and post_monday["mid_low"].min() <= record["monday_low"]
            )

            structures: dict[tuple[str, int], dict[str, object]] = {}
            for timeframe in ("daily", "h4"):
                for width in (2, 3):
                    structure = _structure_at(swing_tables[(timeframe, width)], evaluation_at)
                    structures[(timeframe, width)] = structure
                    record[f"{timeframe}_structure_w{width}"] = structure["direction"]
                    record[f"{timeframe}_structure_w{width}_available_at"] = structure["available_at"]
            record["daily_structure_available_at"] = structures[("daily", 2)]["available_at"]
            record["daily_structure_w3_available_at"] = structures[("daily", 3)]["available_at"]
            record["h4_structure_available_at"] = structures[("h4", 2)]["available_at"]
            record["h4_structure_w3_available_at"] = structures[("h4", 3)]["available_at"]
            swing_high = structures[("daily", 2)]["last_high"]
            swing_low = structures[("daily", 2)]["last_low"]
            record["last_confirmed_daily_swing_high"] = swing_high
            record["last_confirmed_daily_swing_low"] = swing_low
            record["swing_range_position"] = (
                _safe_position(evaluation_price, float(swing_low), float(swing_high))
                if pd.notna(swing_high) and pd.notna(swing_low) and swing_high > swing_low
                else math.nan
            )

            latest_daily = _last_row_available(eligible_daily, evaluation_at)
            latest_h4 = _last_row_available(h4, evaluation_at)
            for timeframe, latest in (("daily", latest_daily), ("h4", latest_h4)):
                record[f"{timeframe}_displacement_direction"] = (
                    int(latest["displacement_direction"]) if latest is not None else 0
                )
                record[f"{timeframe}_robust_displacement_direction"] = (
                    int(latest["robust_displacement_direction"]) if latest is not None else 0
                )
                record[f"{timeframe}_displacement_available_at"] = (
                    pd.Timestamp(latest["available_at"]) if latest is not None else pd.NaT
                )
            record["prior_atr14_bps"] = (
                10000.0 * float(latest_daily["prior_atr14"]) / evaluation_price
                if latest_daily is not None and pd.notna(latest_daily["prior_atr14"])
                else math.nan
            )

            prior_120_close = _asof_close(frame, evaluation_at - pd.Timedelta(minutes=120))
            record["prior_return_120m_bps"] = (
                10000.0 * math.log(evaluation_price / prior_120_close)
                if pd.notna(prior_120_close) and prior_120_close > 0
                else math.nan
            )
            record["maximum_spread_prior_30m"] = float(
                frame.loc[
                    (frame.index >= evaluation_at - pd.Timedelta(minutes=30))
                    & (frame.index < evaluation_at),
                    "maximum_spread",
                ].max()
            )
            record.update(_candidate_directions(record))

            known_levels = {
                "pdh": float(record["prior_day_high"]),
                "pdl": float(record["prior_day_low"]),
                "pwh": float(record["prior_week_high"]),
                "pwl": float(record["prior_week_low"]),
                "monday_high": float(record["monday_high"]),
                "monday_low": float(record["monday_low"]),
            }
            outcome_errors: list[str] = []
            for label, minutes in FORWARD_HORIZONS_MINUTES.items():
                outcomes, error = _outcome_window(
                    frame,
                    evaluation_at=evaluation_at,
                    endpoint=evaluation_at + pd.Timedelta(minutes=minutes),
                    evaluation_price=evaluation_price,
                    known_levels=known_levels,
                    label=label,
                )
                record.update(outcomes)
                if error:
                    outcome_errors.append(error)
            session_endpoint_local = pd.Timestamp(
                f"{session_date.isoformat()} {SESSION_ENDPOINT_CLOCK}", tz=NEW_YORK_TIMEZONE
            )
            outcomes, error = _outcome_window(
                frame,
                evaluation_at=evaluation_at,
                endpoint=session_endpoint_local.tz_convert("UTC"),
                evaluation_price=evaluation_price,
                known_levels=known_levels,
                label="session_end_1200",
            )
            record.update(outcomes)
            if error:
                outcome_errors.append(error)
            record["outcome_exclusion_reasons"] = ";".join(sorted(set(outcome_errors)))
            records.append(record)

    samples = pd.DataFrame.from_records(records).sort_values(
        ["evaluation_timestamp_utc", "evaluation_clock"]
    ).reset_index(drop=True)
    exclusions_frame = pd.DataFrame.from_records(
        exclusions, columns=["session_date", "evaluation_clock", "reason"]
    )

    audit_records: list[dict[str, object]] = []
    audit_columns = {
        "prior_day_location": ["prior_day_available_at"],
        "prior_week_location": ["prior_week_available_at"],
        "monday_range": ["monday_range_available_at"],
        "daily_structure_w2": ["daily_structure_available_at"],
        "daily_structure_w3": ["daily_structure_w3_available_at"],
        "h4_structure_w2": ["h4_structure_available_at"],
        "h4_structure_w3": ["h4_structure_w3_available_at"],
        "daily_displacement": ["daily_displacement_available_at"],
        "h4_displacement": ["h4_displacement_available_at"],
        "intraday": ["intraday_cutoff_at"],
    }
    evaluations = pd.to_datetime(samples["evaluation_timestamp_utc"], utc=True)
    for feature_group, columns in audit_columns.items():
        for column in columns:
            availability = pd.to_datetime(samples[column], utc=True, errors="coerce")
            violations = int((availability.notna() & availability.gt(evaluations)).sum())
            audit_records.append(
                {
                    "feature_group": feature_group,
                    "availability_column": column,
                    "non_missing_values": int(availability.notna().sum()),
                    "future_availability_violations": violations,
                    "status": "PASS" if violations == 0 else "FAIL",
                    "first_available_timestamp_utc": availability.min().isoformat()
                    if availability.notna().any()
                    else None,
                }
            )
    feature_audit = pd.DataFrame.from_records(audit_records)
    if feature_audit["future_availability_violations"].sum():
        raise DataQualificationError("feature availability audit found future information")

    complete_weekdays = int(daily["eligible"].sum())
    partial_weekdays = int((daily["weekday"].le(4) & ~daily["eligible"]).sum())
    data_quality.update(
        {
            "calendar_rows": int(len(calendar)),
            "evaluation_rows_constructed": int(len(samples)),
            "evaluation_rows_excluded_missing_anchor": int(len(exclusions_frame)),
            "complete_eligible_new_york_weekdays": complete_weekdays,
            "partial_or_incomplete_new_york_weekdays": partial_weekdays,
            "completed_market_weeks": int(weekly["eligible"].sum()),
            "partial_market_weeks": int(weekly["partial_week"].sum()),
            "first_evaluation_date": samples["session_date"].min() if not samples.empty else None,
            "last_evaluation_date": samples["session_date"].max() if not samples.empty else None,
            "feature_availability_audit": "PASS",
        }
    )
    return BuildResult(
        samples=samples,
        exclusions=exclusions_frame,
        data_quality={key: _json_scalar(value) for key, value in data_quality.items()},
        feature_audit=feature_audit,
    )
