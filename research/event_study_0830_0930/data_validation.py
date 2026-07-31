"""Fail-closed validation and quality reporting for empirical market inputs."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd

from .market_data_adapter import BAR_REQUIRED_COLUMNS, TICK_REQUIRED_COLUMNS


EVENT_WINDOWS: dict[str, tuple[str, str]] = {
    "pre_news_0730_0829": ("07:30", "08:30"),
    "pre_news_0800_0829": ("08:00", "08:30"),
    "impulse_0830_0835": ("08:30", "08:35"),
    "impulse_0830_0845": ("08:30", "08:45"),
    "retracement_0835_0929": ("08:35", "09:30"),
    "equity_open_0930_0950": ("09:30", "09:50"),
    "delivery_0930_1000": ("09:30", "10:00"),
    "secondary_1000_1030": ("10:00", "10:30"),
}


class DataQualityError(ValueError):
    """Raised when critical quality thresholds block empirical execution."""


@dataclass(frozen=True)
class ValidationThresholds:
    maximum_missing_minute_percentage: float = 1.0
    maximum_duplicate_timestamps: int = 0
    maximum_invalid_spreads: int = 0
    maximum_bid_above_ask: int = 0
    maximum_invalid_ohlc_rows: int = 0
    maximum_weekend_records: int = 0
    maximum_closure_records: int = 0
    maximum_missing_event_windows: int = 0
    large_gap_minutes: int = 5
    spread_spike_multiple_of_median: float = 10.0
    known_closure_intervals_utc: tuple[tuple[str, str], ...] = ()


def _utc_timestamp_series(frame: pd.DataFrame) -> pd.Series:
    if "timestamp" not in frame:
        raise DataQualityError("Canonical market data has no timestamp column")
    parsed = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
    if parsed.isna().any():
        raise DataQualityError(
            f"Canonical market data contains {int(parsed.isna().sum())} invalid timestamp(s)"
        )
    return parsed


def _is_expected_open_utc(index: pd.DatetimeIndex) -> pd.Series:
    local = index.tz_convert("America/New_York")
    weekday = local.weekday
    minute_of_day = local.hour * 60 + local.minute
    daily_maintenance = (weekday <= 3) & (minute_of_day >= 17 * 60) & (minute_of_day < 18 * 60)
    friday_close = (weekday == 4) & (minute_of_day >= 17 * 60)
    saturday = weekday == 5
    sunday_preopen = (weekday == 6) & (minute_of_day < 18 * 60)
    return pd.Series(~(daily_maintenance | friday_close | saturday | sunday_preopen), index=index)


def _weekend_mask(index: pd.DatetimeIndex) -> pd.Series:
    local = index.tz_convert("America/New_York")
    weekday = local.weekday
    minute_of_day = local.hour * 60 + local.minute
    return pd.Series((weekday == 5) | ((weekday == 6) & (minute_of_day < 18 * 60)), index=index)


def _custom_closure_mask(
    index: pd.DatetimeIndex,
    intervals: tuple[tuple[str, str], ...],
) -> pd.Series:
    mask = pd.Series(False, index=index)
    for start, end in intervals:
        start_at = pd.Timestamp(start)
        end_at = pd.Timestamp(end)
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise DataQualityError("Known closure intervals must use timezone-aware timestamps")
        start_at = start_at.tz_convert("UTC")
        end_at = end_at.tz_convert("UTC")
        if end_at <= start_at:
            raise DataQualityError("Known closure interval end must be after start")
        mask |= (index >= start_at) & (index < end_at)
    return mask


def _coverage_table(actual: pd.DatetimeIndex, expected: pd.DatetimeIndex, frequency: str) -> list[dict]:
    actual_labels = pd.Series(actual.strftime(frequency)).value_counts()
    expected_labels = pd.Series(expected.strftime(frequency)).value_counts()
    labels = sorted(set(expected_labels.index) | set(actual_labels.index))
    records: list[dict] = []
    for label in labels:
        expected_count = int(expected_labels.get(label, 0))
        actual_count = int(actual_labels.get(label, 0))
        records.append(
            {
                "period": str(label),
                "expected_minutes": expected_count,
                "observed_minutes": actual_count,
                "coverage_percentage": round(
                    100.0 * actual_count / expected_count, 6
                )
                if expected_count
                else math.nan,
            }
        )
    return records


def _missing_gap_statistics(missing: pd.DatetimeIndex, large_gap_minutes: int) -> tuple[int, int]:
    if missing.empty:
        return 0, 0
    series = pd.Series(missing).sort_values().reset_index(drop=True)
    groups = series.diff().ne(pd.Timedelta(minutes=1)).cumsum()
    sizes = series.groupby(groups).size()
    return int((sizes >= large_gap_minutes).sum()), int(sizes.max())


def evaluate_event_windows(
    bars: pd.DataFrame,
    session_dates: Iterable[date | str],
) -> pd.DataFrame:
    timestamps = _utc_timestamp_series(bars)
    local = timestamps.dt.tz_convert("America/New_York")
    minute_index = pd.DatetimeIndex(local.dt.floor("min").drop_duplicates())
    records: list[dict] = []
    for raw_date in sorted({str(value) for value in session_dates}):
        session_date = pd.Timestamp(raw_date).date()
        for name, (start, end) in EVENT_WINDOWS.items():
            start_at = pd.Timestamp(f"{session_date.isoformat()} {start}", tz="America/New_York")
            end_at = pd.Timestamp(f"{session_date.isoformat()} {end}", tz="America/New_York")
            expected = pd.date_range(start_at, end_at, freq="1min", inclusive="left")
            present = expected.intersection(minute_index)
            if len(present) == 0:
                status = "entirely_missing"
            elif len(present) < len(expected):
                status = "partially_missing"
            else:
                status = "complete"
            records.append(
                {
                    "session_date": session_date.isoformat(),
                    "window": name,
                    "start_new_york": start,
                    "end_new_york_exclusive": end,
                    "expected_minutes": int(len(expected)),
                    "observed_minutes": int(len(present)),
                    "missing_minutes": int(len(expected) - len(present)),
                    "status": status,
                }
            )
    return pd.DataFrame.from_records(records)


def _event_session_dates(event_clusters: pd.DataFrame | None) -> list[str]:
    if event_clusters is None or event_clusters.empty:
        return []
    relevant = event_clusters[
        event_clusters.get("is_0830", False).astype(bool)
        | event_clusters.get("is_1000", False).astype(bool)
    ]
    if "session_date" in relevant:
        return sorted(relevant["session_date"].astype(str).unique().tolist())
    timestamps = pd.to_datetime(relevant["release_timestamp_utc"], utc=True)
    return sorted(timestamps.dt.tz_convert("America/New_York").dt.date.astype(str).unique().tolist())


def _spread_and_relationships(frame: pd.DataFrame, mode: str) -> tuple[pd.Series, int, int]:
    if mode == "ticks":
        spread = pd.to_numeric(frame["ask"], errors="coerce") - pd.to_numeric(
            frame["bid"], errors="coerce"
        )
        bid_above = int((frame["bid"] > frame["ask"]).sum())
        invalid_spread = int(spread.le(0).sum())
        return spread, bid_above, invalid_spread
    spread = pd.to_numeric(
        frame.get("last_spread", frame["ask_close"] - frame["bid_close"]), errors="coerce"
    )
    comparisons = pd.DataFrame(
        {
            field: frame[f"bid_{field}"] > frame[f"ask_{field}"]
            for field in ("open", "high", "low", "close")
        }
    )
    invalids = pd.DataFrame(
        {
            field: (frame[f"ask_{field}"] - frame[f"bid_{field}"]).le(0)
            for field in ("open", "high", "low", "close")
        }
    )
    return spread, int(comparisons.any(axis=1).sum()), int(invalids.any(axis=1).sum())


def _invalid_ohlc_rows(frame: pd.DataFrame, mode: str) -> int:
    if mode == "ticks":
        return 0
    invalid = pd.Series(False, index=frame.index)
    for side in ("bid", "ask"):
        invalid |= (
            frame[f"{side}_high"].lt(frame[[f"{side}_open", f"{side}_close"]].max(axis=1))
            | frame[f"{side}_low"].gt(frame[[f"{side}_open", f"{side}_close"]].min(axis=1))
            | frame[f"{side}_high"].lt(frame[f"{side}_low"])
        )
    return int(invalid.sum())


def validate_market_data(
    frame: pd.DataFrame,
    *,
    mode: str = "bars",
    event_clusters: pd.DataFrame | None = None,
    thresholds: ValidationThresholds | None = None,
) -> dict:
    limits = thresholds or ValidationThresholds()
    required = set(BAR_REQUIRED_COLUMNS if mode == "bars" else TICK_REQUIRED_COLUMNS)
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise DataQualityError(f"Canonical {mode} data is missing columns: {missing_columns}")
    if frame.empty:
        raise DataQualityError("Canonical market data is empty")

    timestamps = _utc_timestamp_series(frame)
    utc_index = pd.DatetimeIndex(timestamps)
    monotonic = bool(timestamps.is_monotonic_increasing)
    duplicate_count = int(timestamps.duplicated().sum())
    deltas = timestamps.diff().dt.total_seconds()
    positive = deltas[deltas.gt(0)]
    modal_interval = float(positive.mode().iloc[0]) if not positive.empty else math.nan
    if mode == "bars":
        actual_minutes = pd.DatetimeIndex(timestamps.dt.floor("min").drop_duplicates().sort_values())
    else:
        actual_minutes = pd.DatetimeIndex(timestamps.dt.floor("min").drop_duplicates().sort_values())
    full_index = pd.date_range(actual_minutes.min(), actual_minutes.max(), freq="1min")
    weekly_open = _is_expected_open_utc(full_index)
    custom_closed = _custom_closure_mask(full_index, limits.known_closure_intervals_utc)
    expected_minutes = full_index[(weekly_open & ~custom_closed).to_numpy()]
    observed_expected = actual_minutes.intersection(expected_minutes)
    missing_minutes = expected_minutes.difference(observed_expected)
    missing_percentage = (
        100.0 * len(missing_minutes) / len(expected_minutes) if len(expected_minutes) else math.nan
    )
    large_gap_count, maximum_gap_minutes = _missing_gap_statistics(
        missing_minutes, limits.large_gap_minutes
    )

    spread, bid_above_ask, invalid_spread = _spread_and_relationships(frame, mode)
    usable_spread = spread.dropna()
    median_spread = float(usable_spread.median()) if not usable_spread.empty else math.nan
    spread_p95 = float(usable_spread.quantile(0.95)) if not usable_spread.empty else math.nan
    spread_p99 = float(usable_spread.quantile(0.99)) if not usable_spread.empty else math.nan
    maximum_spread = float(usable_spread.max()) if not usable_spread.empty else math.nan
    spike_threshold = (
        median_spread * limits.spread_spike_multiple_of_median
        if math.isfinite(median_spread) and median_spread > 0
        else math.nan
    )
    spread_spike_count = (
        int(usable_spread.gt(spike_threshold).sum()) if math.isfinite(spike_threshold) else 0
    )
    invalid_ohlc = _invalid_ohlc_rows(frame, mode)
    price_columns = (
        ["bid", "ask"]
        if mode == "ticks"
        else [f"{side}_{field}" for side in ("bid", "ask") for field in ("open", "high", "low", "close")]
    )
    non_positive_price_count = int(frame[price_columns].le(0).any(axis=1).sum())
    weekend_count = int(_weekend_mask(utc_index).sum())
    expected_open_mask = _is_expected_open_utc(utc_index)
    custom_closure_records = _custom_closure_mask(
        utc_index, limits.known_closure_intervals_utc
    )
    closure_record_count = int((~expected_open_mask | custom_closure_records).sum())
    round_trip = utc_index.tz_convert("America/New_York").tz_convert("UTC")
    dst_round_trip_errors = int((round_trip.asi8 != utc_index.asi8).sum())
    source_count = int(frame["source"].astype(str).nunique(dropna=False))
    symbol_count = int(frame["symbol"].astype(str).nunique(dropna=False))

    session_dates = _event_session_dates(event_clusters)
    event_window_coverage = evaluate_event_windows(frame, session_dates)
    if event_window_coverage.empty:
        missing_event_window_count = 0
        incomplete_event_sessions = 0
        coverage_records: list[dict] = []
    else:
        incomplete = event_window_coverage["status"].ne("complete")
        missing_event_window_count = int(incomplete.sum())
        incomplete_event_sessions = int(
            event_window_coverage.loc[incomplete, "session_date"].nunique()
        )
        coverage_records = event_window_coverage.to_dict(orient="records")

    critical: list[str] = []
    if not monotonic:
        critical.append("timestamps_not_monotonic")
    if duplicate_count > limits.maximum_duplicate_timestamps:
        critical.append("duplicate_timestamp_threshold_exceeded")
    if mode == "bars" and (not math.isfinite(modal_interval) or modal_interval != 60):
        critical.append("bar_granularity_not_one_minute")
    if bid_above_ask > limits.maximum_bid_above_ask:
        critical.append("bid_above_ask_threshold_exceeded")
    if invalid_spread > limits.maximum_invalid_spreads:
        critical.append("non_positive_spread_threshold_exceeded")
    if invalid_ohlc > limits.maximum_invalid_ohlc_rows:
        critical.append("invalid_ohlc_threshold_exceeded")
    if non_positive_price_count:
        critical.append("non_positive_price_detected")
    if weekend_count > limits.maximum_weekend_records:
        critical.append("weekend_record_threshold_exceeded")
    if closure_record_count > limits.maximum_closure_records:
        critical.append("known_closure_record_threshold_exceeded")
    if source_count != 1:
        critical.append("source_inconsistent")
    elif frame["source"].astype(str).str.strip().eq("").any():
        critical.append("source_missing")
    if symbol_count != 1:
        critical.append("symbol_inconsistent")
    elif frame["symbol"].astype(str).str.strip().eq("").any():
        critical.append("symbol_missing")
    if math.isfinite(missing_percentage) and missing_percentage > limits.maximum_missing_minute_percentage:
        critical.append("missing_minute_threshold_exceeded")
    if missing_event_window_count > limits.maximum_missing_event_windows:
        critical.append("missing_event_window_threshold_exceeded")
    if dst_round_trip_errors:
        critical.append("dst_round_trip_error")

    report = {
        "status": "blocked" if critical else "passed",
        "critical_violations": critical,
        "thresholds": asdict(limits),
        "data_start_utc": timestamps.min().isoformat(),
        "data_end_utc": timestamps.max().isoformat(),
        "row_count": int(len(frame)),
        "mode": mode,
        "timestamp_monotonic": monotonic,
        "timestamp_granularity_seconds": modal_interval,
        "duplicate_count": duplicate_count,
        "expected_open_minutes": int(len(expected_minutes)),
        "observed_open_minutes": int(len(observed_expected)),
        "missing_minute_count": int(len(missing_minutes)),
        "missing_minute_percentage": round(missing_percentage, 8),
        "large_gap_count": large_gap_count,
        "maximum_gap_minutes": maximum_gap_minutes,
        "bid_above_ask_error_count": bid_above_ask,
        "invalid_spread_count": invalid_spread,
        "invalid_ohlc_row_count": invalid_ohlc,
        "non_positive_price_row_count": non_positive_price_count,
        "median_spread": median_spread,
        "spread_p95": spread_p95,
        "spread_p99": spread_p99,
        "maximum_spread": maximum_spread,
        "abnormal_spread_spike_count": spread_spike_count,
        "spread_spike_threshold": spike_threshold,
        "weekend_record_count": weekend_count,
        "known_closure_record_count": closure_record_count,
        "dst_round_trip_error_count": dst_round_trip_errors,
        "source_count": source_count,
        "symbol_count": symbol_count,
        "missing_event_window_count": missing_event_window_count,
        "incomplete_event_session_count": incomplete_event_sessions,
        "event_window_coverage": coverage_records,
        "per_year_coverage": _coverage_table(observed_expected, expected_minutes, "%Y"),
        "per_month_coverage": _coverage_table(observed_expected, expected_minutes, "%Y-%m"),
        "methodology": {
            "internal_timezone": "UTC",
            "analysis_timezone": "America/New_York",
            "known_closure_model": "17:00-18:00 ET Mon-Thu; Fri 17:00-Sun 18:00 ET",
            "custom_known_closure_intervals_utc": list(limits.known_closure_intervals_utc),
            "missing_minutes_filled": False,
            "event_windows_filled": False,
        },
    }
    return report


def refuse_on_critical(report: dict) -> None:
    violations = report.get("critical_violations", [])
    if violations:
        raise DataQualityError(
            "Empirical execution refused because critical validation failed: "
            + ", ".join(str(item) for item in violations)
        )


def quality_report_markdown(report: dict) -> str:
    lines = [
        "# Empirical Data Quality Report",
        "",
        f"Status: **{str(report.get('status', 'unknown')).upper()}**",
        "",
        "This report describes input integrity only. It contains no performance result or edge claim.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for label, key in (
        ("Start UTC", "data_start_utc"),
        ("End UTC", "data_end_utc"),
        ("Rows", "row_count"),
        ("Missing minutes (%)", "missing_minute_percentage"),
        ("Duplicate timestamps", "duplicate_count"),
        ("Invalid spreads", "invalid_spread_count"),
        ("Median spread", "median_spread"),
        ("95th percentile spread", "spread_p95"),
        ("99th percentile spread", "spread_p99"),
        ("Maximum spread", "maximum_spread"),
        ("Weekend records", "weekend_record_count"),
        ("Missing event windows", "missing_event_window_count"),
    ):
        lines.append(f"| {label} | {report.get(key, '')} |")
    lines.extend(["", "## Critical violations", ""])
    violations = report.get("critical_violations", [])
    if violations:
        lines.extend(f"- `{item}`" for item in violations)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Handling boundary",
            "",
            "Missing minutes and event windows were not filled. A blocked status prevents Stage 1.",
            "",
        ]
    )
    return "\n".join(lines)


def write_quality_reports(report: dict, json_path: str | Path, markdown_path: str | Path) -> None:
    json_output = Path(json_path)
    markdown_output = Path(markdown_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    markdown_output.write_text(quality_report_markdown(report), encoding="utf-8")
