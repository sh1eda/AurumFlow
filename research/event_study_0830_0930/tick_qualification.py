"""Streaming qualification and normalization for the isolated MT5 tick export.

The implementation deliberately avoids the in-memory empirical adapter. Validation
uses pandas' C parser in bounded chunks and retains only compact counters. A second
and final source scan writes canonical ticks and one-minute bid/ask bars when the
structural normalization gate passes.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import warnings
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from pandas.errors import ParserWarning


EXPECTED_COLUMNS = (
    "<DATE>",
    "<TIME>",
    "<BID>",
    "<ASK>",
    "<LAST>",
    "<VOLUME>",
    "<FLAGS>",
)
TIMESTAMP_FORMAT = "%Y.%m.%d %H:%M:%S.%f"
NEW_YORK = "America/New_York"
SPREAD_SCALE = 100  # inspected input prices have two decimal places
SCHEMA_VERSION = "1.0"

WINDOWS = {
    "pre_news_0730_0830": (7 * 60 + 30, 8 * 60 + 30),
    "pre_news_0800_0830": (8 * 60, 8 * 60 + 30),
    "initial_impulse_0830_0835": (8 * 60 + 30, 8 * 60 + 35),
    "extended_impulse_0830_0845": (8 * 60 + 30, 8 * 60 + 45),
    "retracement_0835_0930": (8 * 60 + 35, 9 * 60 + 30),
    "equity_open_reaction_0930_0950": (9 * 60 + 30, 9 * 60 + 50),
    "delivery_0930_1000": (9 * 60 + 30, 10 * 60),
    "secondary_1000_1030": (10 * 60, 10 * 60 + 30),
    "full_study_0730_1030": (7 * 60 + 30, 10 * 60 + 30),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _read_header(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="ascii", newline="") as handle:
        first = handle.readline().rstrip("\r\n")
    return tuple(first.split("\t"))


def _reader(path: Path, chunk_rows: int) -> pd.io.parsers.TextFileReader:
    return pd.read_csv(
        path,
        sep="\t",
        encoding="ascii",
        engine="c",
        chunksize=chunk_rows,
        on_bad_lines="warn",
        index_col=False,
        skip_blank_lines=False,
    )


def _parse_columns(
    frame: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    date_values = frame["<DATE>"].astype("string")
    time_values = frame["<TIME>"].astype("string")
    timestamps = pd.to_datetime(
        date_values + " " + time_values,
        format=TIMESTAMP_FORMAT,
        errors="coerce",
    )
    bid = pd.to_numeric(frame["<BID>"], errors="coerce")
    ask = pd.to_numeric(frame["<ASK>"], errors="coerce")
    last = pd.to_numeric(frame["<LAST>"], errors="coerce")
    volume = pd.to_numeric(frame["<VOLUME>"], errors="coerce")
    flags = frame["<FLAGS>"].astype("string")
    return timestamps, bid, ask, last, volume, flags


def _reconstruct_quote_state(
    frame: pd.DataFrame,
    bid: pd.Series,
    ask: pd.Series,
    flags: pd.Series,
    *,
    previous_bid: float | None,
    previous_ask: float | None,
) -> dict[str, Any]:
    """Reconstruct deterministic MT5 incremental quote updates.

    Bit 2 denotes a bid update and bit 4 an ask update in the observed export. A
    blank opposite side is carried only when a prior quote exists and the flag does
    not claim that the blank side changed. Invalid explicit values never update
    quote state and invalidate their own row.
    """

    bid_text = frame["<BID>"].astype("string")
    ask_text = frame["<ASK>"].astype("string")
    raw_bid_present = frame["<BID>"].notna() & bid_text.str.len().fillna(0).gt(0)
    raw_ask_present = frame["<ASK>"].notna() & ask_text.str.len().fillna(0).gt(0)
    raw_bid_valid = raw_bid_present & bid.notna() & np.isfinite(bid) & bid.gt(0)
    raw_ask_valid = raw_ask_present & ask.notna() & np.isfinite(ask) & ask.gt(0)
    invalid_explicit_bid = raw_bid_present & ~raw_bid_valid
    invalid_explicit_ask = raw_ask_present & ~raw_ask_valid

    flag_values = pd.to_numeric(flags, errors="coerce")
    flag_valid = flag_values.notna() & np.isfinite(flag_values) & flag_values.ge(0)
    flag_int = flag_values.fillna(0).astype("int64")
    flag_array = flag_int.to_numpy(dtype="int64")
    bid_flagged = pd.Series(np.bitwise_and(flag_array, 2) != 0, index=frame.index)
    ask_flagged = pd.Series(np.bitwise_and(flag_array, 4) != 0, index=frame.index)
    blank_claimed_bid_update = ~raw_bid_present & bid_flagged
    blank_claimed_ask_update = ~raw_ask_present & ask_flagged

    bid_state = bid.where(raw_bid_valid).ffill()
    ask_state = ask.where(raw_ask_valid).ffill()
    if previous_bid is not None:
        bid_state = bid_state.fillna(previous_bid)
    if previous_ask is not None:
        ask_state = ask_state.fillna(previous_ask)

    unresolved_bid = bid_state.isna() | ~np.isfinite(bid_state) | bid_state.le(0)
    unresolved_ask = ask_state.isna() | ~np.isfinite(ask_state) | ask_state.le(0)
    unsafe_flag = (
        (~flag_valid & (~raw_bid_present | ~raw_ask_present))
        | blank_claimed_bid_update
        | blank_claimed_ask_update
    )
    quote_valid = ~(
        invalid_explicit_bid
        | invalid_explicit_ask
        | unresolved_bid
        | unresolved_ask
        | unsafe_flag
    )
    reconstructed_bid = ~raw_bid_present & ~bid_flagged & bid_state.notna()
    reconstructed_ask = ~raw_ask_present & ~ask_flagged & ask_state.notna()
    next_bid = (
        float(bid_state.iloc[-1])
        if len(bid_state) and pd.notna(bid_state.iloc[-1])
        else previous_bid
    )
    next_ask = (
        float(ask_state.iloc[-1])
        if len(ask_state) and pd.notna(ask_state.iloc[-1])
        else previous_ask
    )
    return {
        "bid": bid_state,
        "ask": ask_state,
        "quote_valid": quote_valid,
        "raw_bid_valid": raw_bid_valid,
        "raw_ask_valid": raw_ask_valid,
        "raw_bid_missing": ~raw_bid_present,
        "raw_ask_missing": ~raw_ask_present,
        "reconstructed_bid": reconstructed_bid,
        "reconstructed_ask": reconstructed_ask,
        "flag_consistency_violation": unsafe_flag,
        "next_bid": next_bid,
        "next_ask": next_ask,
    }


def _add_counter(counter: Counter[int], values: np.ndarray) -> None:
    if not len(values):
        return
    unique, counts = np.unique(values, return_counts=True)
    counter.update({int(key): int(count) for key, count in zip(unique, counts)})


def _counter_quantile(counter: Counter[int], q: float) -> float | None:
    total = sum(counter.values())
    if total == 0:
        return None
    rank = max(1, int(math.ceil(q * total)))
    cumulative = 0
    for value in sorted(counter):
        cumulative += counter[value]
        if cumulative >= rank:
            return float(value)
    return float(max(counter))


def _counter_mean(counter: Counter[int]) -> float | None:
    total = sum(counter.values())
    if total == 0:
        return None
    return sum(value * count for value, count in counter.items()) / total


def _spread_distribution(counter: Counter[int]) -> list[dict[str, Any]]:
    bins = [
        ("0.00", 0, 0),
        ("0.01-0.05", 1, 5),
        ("0.06-0.10", 6, 10),
        ("0.11-0.20", 11, 20),
        ("0.21-0.30", 21, 30),
        ("0.31-0.50", 31, 50),
        ("0.51-1.00", 51, 100),
        ("1.01-2.00", 101, 200),
        ("2.01-5.00", 201, 500),
        (">5.00", 501, None),
    ]
    total = sum(counter.values())
    result: list[dict[str, Any]] = []
    for label, low, high in bins:
        count = sum(
            frequency
            for value, frequency in counter.items()
            if value >= low and (high is None or value <= high)
        )
        result.append(
            {
                "range_price_units": label,
                "count": int(count),
                "percentage": (100.0 * count / total) if total else None,
            }
        )
    return result


def _interarrival_distribution(counter: Counter[int]) -> list[dict[str, Any]]:
    bins = [
        ("0 ms", 0, 0),
        ("1-100 ms", 1, 100),
        ("101-250 ms", 101, 250),
        ("251-500 ms", 251, 500),
        ("501-1,000 ms", 501, 1_000),
        ("1.001-5 s", 1_001, 5_000),
        ("5.001-30 s", 5_001, 30_000),
        ("30.001-60 s", 30_001, 60_000),
        ("1-5 min", 60_001, 300_000),
        ("5-60 min", 300_001, 3_600_000),
        (">60 min", 3_600_001, None),
    ]
    total = sum(counter.values())
    result: list[dict[str, Any]] = []
    for label, low, high in bins:
        count = sum(
            frequency
            for value, frequency in counter.items()
            if value >= low and (high is None or value <= high)
        )
        result.append(
            {
                "interval": label,
                "count": int(count),
                "percentage": (100.0 * count / total) if total else None,
            }
        )
    return result


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _window_mask(start_minute: int, end_minute: int) -> int:
    mask = 0
    for minute in range(start_minute, end_minute):
        mask |= 1 << minute
    return mask


def _event_coverage(
    minute_counts: Counter[int], source_timezone: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not minute_counts:
        return {}, {}
    source_minutes = np.array(sorted(minute_counts), dtype="int64")
    counts = np.array([minute_counts[int(key)] for key in source_minutes], dtype="int64")
    naive = pd.to_datetime(source_minutes, unit="m")
    localized = naive.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
    utc_index = localized.tz_convert("UTC")
    ny_index = utc_index.tz_convert(NEW_YORK)

    day_masks: dict[date, int] = {}
    day_ticks: Counter[date] = Counter()
    weekday_ticks: Counter[str] = Counter()
    source_weekday_ticks: Counter[str] = Counter()
    for source_ts, ny_ts, tick_count in zip(localized, ny_index, counts):
        day = ny_ts.date()
        minute = ny_ts.hour * 60 + ny_ts.minute
        day_masks[day] = day_masks.get(day, 0) | (1 << minute)
        day_ticks[day] += int(tick_count)
        weekday_ticks[ny_ts.day_name()] += int(tick_count)
        source_weekday_ticks[source_ts.day_name()] += int(tick_count)

    first_day = ny_index[0].date()
    last_day = ny_index[-1].date()
    weekdays = [day for day in _date_range(first_day, last_day) if day.weekday() < 5]
    missing_days = [day.isoformat() for day in weekdays if day not in day_masks]

    windows: dict[str, Any] = {}
    for name, (start_minute, end_minute) in WINDOWS.items():
        required = _window_mask(start_minute, end_minute)
        complete = [
            day.isoformat()
            for day in weekdays
            if day_masks.get(day, 0) & required == required
        ]
        missing = [day.isoformat() for day in weekdays if day.isoformat() not in set(complete)]
        windows[name] = {
            "required_minutes_per_day": end_minute - start_minute,
            "candidate_weekdays": len(weekdays),
            "complete_days": len(complete),
            "complete_percentage": 100.0 * len(complete) / len(weekdays) if weekdays else None,
            "missing_days": missing,
        }

    utc_minute_values = utc_index.as_unit("ns").asi8 // 60_000_000_000
    total_span_minutes = int(utc_minute_values[-1] - utc_minute_values[0] + 1)
    closure_and_gap_minutes = total_span_minutes - len(np.unique(utc_minute_values))
    weekend = {
        "new_york_saturday_ticks": int(weekday_ticks.get("Saturday", 0)),
        "new_york_sunday_ticks": int(weekday_ticks.get("Sunday", 0)),
        "source_clock_saturday_ticks": int(source_weekday_ticks.get("Saturday", 0)),
        "source_clock_sunday_ticks": int(source_weekday_ticks.get("Sunday", 0)),
        "note": (
            "Sunday New York ticks can be legitimate electronic-session reopening data; "
            "weekend counts are reported, not automatically classified as corrupt."
        ),
    }
    coverage = {
        "timezone": NEW_YORK,
        "candidate_weekdays": len(weekdays),
        "dates_with_any_ticks": len(day_masks),
        "missing_weekday_dates": missing_days,
        "windows": windows,
        "observed_source_minutes": len(source_minutes),
        "utc_span_minutes": total_span_minutes,
        "empty_utc_minutes_including_routine_closures": int(closure_and_gap_minutes),
        "missing_timestamp_definition": (
            "Ticks are event-driven, so an absent millisecond is not a missing record. "
            "Qualification reports empty one-minute buckets and registered event-window gaps."
        ),
    }
    return coverage, weekend


def _problem_examples(
    frame: pd.DataFrame,
    mask: pd.Series,
    issue: str,
    limit: int,
    existing: list[dict[str, Any]],
) -> None:
    remaining = limit - len(existing)
    if remaining <= 0 or not bool(mask.any()):
        return
    columns = ["<DATE>", "<TIME>", "<BID>", "<ASK>", "<LAST>", "<VOLUME>", "<FLAGS>"]
    for index, row in frame.loc[mask, columns].head(remaining).iterrows():
        existing.append(
            {
                "issue": issue,
                "approximate_physical_line": int(index) + 2,
                "date": None if pd.isna(row["<DATE>"]) else str(row["<DATE>"]),
                "time": None if pd.isna(row["<TIME>"]) else str(row["<TIME>"]),
                "bid": None if pd.isna(row["<BID>"]) else str(row["<BID>"]),
                "ask": None if pd.isna(row["<ASK>"]) else str(row["<ASK>"]),
            }
        )


def _quality_assessment(metrics: dict[str, Any], timezone_status: str) -> dict[str, Any]:
    rows = max(1, int(metrics["physical_data_rows"]))
    invalid = int(metrics["invalid_required_rows"])
    malformed = int(metrics["malformed_rows"])
    negative = int(metrics["negative_spread_rows"])
    monotonic = int(metrics["monotonicity_violations"])
    invalid_rate = (invalid + malformed) / rows
    negative_rate = negative / rows

    critical: list[str] = []
    warnings_list: list[str] = []
    if monotonic:
        critical.append(f"{monotonic:,} timestamp reversals make order-dependent replay unsafe")
    if invalid_rate > 0.0001:
        critical.append(
            f"Malformed/invalid required rows are {invalid_rate:.4%}, above the 0.01% gate"
        )
    elif invalid or malformed:
        warnings_list.append(
            f"{invalid + malformed:,} malformed or invalid required rows require exclusion"
        )
    if negative_rate > 0.00001:
        critical.append(
            f"Negative-spread rows are {negative_rate:.4%}, above the 0.001% gate"
        )
    elif negative:
        warnings_list.append(f"{negative:,} negative-spread rows require exclusion")
    if timezone_status != "confirmed":
        warnings_list.append(
            "Source timezone is inferred rather than confirmed by broker/feed documentation"
        )
    extreme_spread_rows = next(
        (
            int(item["count"])
            for item in metrics.get("spread", {}).get("distribution", [])
            if item["range_price_units"] == ">5.00"
        ),
        0,
    )
    if extreme_spread_rows:
        warnings_list.append(
            f"{extreme_spread_rows:,} valid quote states have spreads above 5.00 price units; "
            "their timing must be isolated before execution-cost inference"
        )
    zero_spread_rows = int(metrics.get("zero_spread_rows", 0))
    if zero_spread_rows:
        warnings_list.append(
            f"{zero_spread_rows:,} reconstructed quote states have zero spread; execution-cost "
            "research must report a nonzero-cost sensitivity rather than treating them as a "
            "general zero-cost assumption"
        )

    coverage = metrics.get("event_coverage", {}).get("windows", {})
    for name in (
        "initial_impulse_0830_0835",
        "equity_open_reaction_0930_0950",
        "secondary_1000_1030",
    ):
        value = coverage.get(name, {}).get("complete_percentage")
        if value is not None and value < 95.0:
            warnings_list.append(f"{name} complete coverage is only {value:.2f}%")

    score = 100.0
    if timezone_status != "confirmed":
        score -= 10.0
    score -= min(25.0, invalid_rate * 100_000.0)
    score -= min(20.0, negative_rate * 1_000_000.0)
    if monotonic:
        score -= 30.0
    window_percentages = [
        coverage.get(name, {}).get("complete_percentage")
        for name in (
            "initial_impulse_0830_0835",
            "equity_open_reaction_0930_0950",
            "secondary_1000_1030",
        )
    ]
    available = [float(value) for value in window_percentages if value is not None]
    if available:
        score -= min(10.0, max(0.0, 100.0 - min(available)) / 2.0)
    score = max(0, min(100, int(round(score))))

    if critical:
        verdict = "UNUSABLE"
    elif warnings_list:
        verdict = "WARNING"
    else:
        verdict = "READY"
    return {
        "verdict": verdict,
        "quality_score": score,
        "normalization_gate_passed": not critical,
        "critical_reasons": critical,
        "warnings": warnings_list,
        "thresholds": {
            "maximum_invalid_or_malformed_fraction": 0.0001,
            "maximum_negative_spread_fraction": 0.00001,
            "timestamp_reversals_allowed": 0,
        },
    }


def _format_number(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def _render_report(metadata: dict[str, Any]) -> str:
    metrics = metadata["validation"]
    quality = metadata["quality"]
    spread = metrics["spread"]
    ticks = metrics["tick_frequency"]
    coverage = metrics.get("event_coverage", {})
    lines = [
        "# XAUUSD Tick Validation Report",
        "",
        f"Generated: {metadata['generated_at_utc']}  ",
        f"Input: `{metadata['input']['path']}`  ",
        f"Overall verdict: **{quality['verdict']}**  ",
        f"Quality score: **{quality['quality_score']}/100**  ",
        f"Normalization gate: **{'PASS' if quality['normalization_gate_passed'] else 'FAIL'}**",
        "",
        "This report qualifies data only. Stage 1 and all strategy tests were not run.",
        "",
        "## Whole-file streaming results",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Physical data rows | {_format_number(metrics['physical_data_rows'])} |",
        f"| Parsed rows | {_format_number(metrics['parsed_rows'])} |",
        f"| First source timestamp | {metrics['first_timestamp_source']} |",
        f"| Last source timestamp | {metrics['last_timestamp_source']} |",
        f"| First UTC timestamp (assumed mapping) | {metrics.get('first_timestamp_utc', 'n/a')} |",
        f"| Last UTC timestamp (assumed mapping) | {metrics.get('last_timestamp_utc', 'n/a')} |",
        f"| Duplicate timestamp rows | {_format_number(metrics['duplicate_timestamp_rows'])} |",
        f"| Timestamp reversals | {_format_number(metrics['monotonicity_violations'])} |",
        f"| Malformed rows | {_format_number(metrics['malformed_rows'])} |",
        f"| Invalid required rows | {_format_number(metrics['invalid_required_rows'])} |",
        f"| Zero-spread rows | {_format_number(metrics['zero_spread_rows'])} |",
        f"| Negative-spread rows | {_format_number(metrics['negative_spread_rows'])} |",
        f"| Bid-side values reconstructed from prior quote | {_format_number(metrics['reconstructed_bid_rows'])} |",
        f"| Ask-side values reconstructed from prior quote | {_format_number(metrics['reconstructed_ask_rows'])} |",
        f"| Flag/state consistency violations | {_format_number(metrics['flag_consistency_violations'])} |",
        f"| LAST values present | {_format_number(metrics['last_present_rows'])} |",
        f"| VOLUME values present | {_format_number(metrics['volume_present_rows'])} |",
        "",
        "## Spread diagnostics (price units)",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Median | {_format_number(spread['median'], 2)} |",
        f"| Average | {_format_number(spread['average'], 4)} |",
        f"| 95th percentile | {_format_number(spread['p95'], 2)} |",
        f"| 99th percentile | {_format_number(spread['p99'], 2)} |",
        f"| Maximum | {_format_number(spread['maximum'], 2)} |",
        "",
        "| Spread range | Rows | Percentage |",
        "|---|---:|---:|",
    ]
    for item in spread["distribution"]:
        lines.append(
            f"| {item['range_price_units']} | {item['count']:,} | "
            f"{_format_number(item['percentage'], 4)}% |"
        )

    lines.extend(
        [
            "",
            "## Tick frequency",
            "",
            "| Measure | Result |",
            "|---|---:|",
            f"| Populated minutes | {_format_number(ticks['populated_minutes'])} |",
            f"| Mean ticks per populated minute | {_format_number(ticks['ticks_per_minute_mean'], 2)} |",
            f"| Median ticks per populated minute | {_format_number(ticks['ticks_per_minute_median'], 2)} |",
            f"| 95th percentile ticks/minute | {_format_number(ticks['ticks_per_minute_p95'], 2)} |",
            f"| 99th percentile ticks/minute | {_format_number(ticks['ticks_per_minute_p99'], 2)} |",
            f"| Maximum ticks/minute | {_format_number(ticks['ticks_per_minute_max'])} |",
            f"| Median interarrival | {_format_number(ticks['interarrival_median_ms'], 0)} ms |",
            f"| 95th percentile interarrival | {_format_number(ticks['interarrival_p95_ms'], 0)} ms |",
            f"| 99th percentile interarrival | {_format_number(ticks['interarrival_p99_ms'], 0)} ms |",
            f"| Maximum interarrival | {_format_number(ticks['interarrival_max_ms'], 0)} ms |",
            "",
            "`Missing timestamps` are not defined as absent milliseconds because ticks are event-driven. "
            "The coverage section instead reports empty minute buckets and incomplete registered windows.",
            "",
            "## New York event-window coverage",
            "",
            f"Candidate weekdays: **{coverage.get('candidate_weekdays', 0):,}**  ",
            f"Weekday dates with no ticks: **{len(coverage.get('missing_weekday_dates', [])):,}**",
            "",
            "| Window | Complete days | Complete coverage | Missing windows |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, item in coverage.get("windows", {}).items():
        lines.append(
            f"| {name} | {item['complete_days']:,} | "
            f"{_format_number(item['complete_percentage'], 2)}% | {len(item['missing_days']):,} |"
        )

    lines.extend(["", "Missing anchor-window dates:", ""])
    for name in (
        "initial_impulse_0830_0835",
        "equity_open_reaction_0930_0950",
        "secondary_1000_1030",
    ):
        missing_dates = coverage.get("windows", {}).get(name, {}).get("missing_days", [])
        lines.append(
            f"- {name}: " + (", ".join(missing_dates) if missing_dates else "none")
        )

    missing = coverage.get("missing_weekday_dates", [])
    lines.extend(
        [
            "",
            "Missing weekday dates: " + (", ".join(missing) if missing else "none"),
            "",
            "Holiday and scheduled-closure status is not inferred without an exchange calendar; a weekday "
            "with no ticks is reported as a missing date, not automatically called corruption.",
            "",
            "## Weekend observations",
            "",
        ]
    )
    for key, value in metrics.get("weekend_data", {}).items():
        if key != "note":
            lines.append(f"- {key.replace('_', ' ')}: {_format_number(value)}")
    lines.append(f"- Note: {metrics.get('weekend_data', {}).get('note', 'n/a')}")

    lines.extend(["", "## Quality assessment", ""])
    if quality["critical_reasons"]:
        lines.append("Critical reasons:")
        lines.append("")
        lines.extend(f"- {value}" for value in quality["critical_reasons"])
        lines.append("")
    if quality["warnings"]:
        lines.append("Warnings:")
        lines.append("")
        lines.extend(f"- {value}" for value in quality["warnings"])
        lines.append("")
    if not quality["critical_reasons"] and not quality["warnings"]:
        lines.append("No critical defects or warnings were detected.")
        lines.append("")

    outputs = metadata.get("outputs", {})
    lines.extend(
        [
            "## Normalized outputs",
            "",
            f"- Canonical tick dataset: {outputs.get('normalized_ticks', 'not generated')}",
            f"- One-minute bid/ask bars: {outputs.get('minute_bars', 'not generated')}",
            f"- Canonical tick rows: {_format_number(outputs.get('normalized_tick_rows'))}",
            f"- One-minute bars: {_format_number(outputs.get('minute_bar_rows'))}",
            "",
            "The source export was opened read-only and was not overwritten.",
            "",
            "## Research readiness",
            "",
        ]
    )
    readiness = metadata.get("research_readiness", {})
    for key, value in readiness.items():
        lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    verification = metadata.get("derivative_verification")
    if verification:
        lines.extend(
            [
                "",
                "## Derivative verification",
                "",
                f"- Status: {verification['status']}",
                f"- One-minute rows checked: {verification['minute_bar_rows']:,}",
                f"- Tick-count sum: {verification['tick_count_sum']:,}",
                f"- Minute timestamp duplicates: {verification['duplicate_minute_timestamps']:,}",
                f"- Minute timestamp reversals: {verification['minute_timestamp_reversals']:,}",
                f"- OHLC invariant violations: {verification['ohlc_invariant_violations']:,}",
                f"- Open/close negative-spread violations: {verification['open_close_negative_spread_violations']:,}",
                f"- Minutes with maximum spread above 5.00: {verification['extreme_spread_minutes']:,}",
                f"- Extreme-spread minutes inside 08:00–10:30 ET: {verification['extreme_spread_minutes_0800_1030_et']:,}",
            ]
        )
    lines.extend(
        [
            "",
            "No empirical event study, lifecycle classification, entry-geometry test, or backtest was run.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_metadata_and_report(metadata: dict[str, Any], output_dir: Path) -> None:
    metadata["generated_at_utc"] = _utc_now()
    (output_dir / "tick_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "tick_validation_report.md").write_text(
        _render_report(metadata), encoding="utf-8"
    )


def validate_ticks(
    input_path: Path,
    output_dir: Path,
    *,
    source_timezone: str,
    timezone_status: str,
    chunk_rows: int = 1_000_000,
    progress_rows: int = 5_000_000,
) -> dict[str, Any]:
    if _read_header(input_path) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected header {_read_header(input_path)!r}; expected {EXPECTED_COLUMNS!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    quality_dir = output_dir / "external_data" / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)

    parsed_rows = 0
    invalid_required = 0
    negative_spreads = 0
    zero_spreads = 0
    non_cent_prices = 0
    last_present = 0
    last_invalid = 0
    volume_present = 0
    volume_invalid_or_negative = 0
    monotonicity_violations = 0
    duplicate_timestamps = 0
    first_ms: int | None = None
    last_ms: int | None = None
    previous_ms: int | None = None
    previous_bid: float | None = None
    previous_ask: float | None = None
    reconstructed_bid_rows = 0
    reconstructed_ask_rows = 0
    raw_bid_missing_rows = 0
    raw_ask_missing_rows = 0
    flag_consistency_violations = 0
    spread_counter: Counter[int] = Counter()
    interarrival_counter: Counter[int] = Counter()
    minute_counts: Counter[int] = Counter()
    flags_counter: Counter[str] = Counter()
    problem_regions: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    warning_messages: list[str] = []
    next_progress = progress_rows
    started = time.monotonic()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ParserWarning)
        for chunk_number, frame in enumerate(_reader(input_path, chunk_rows), start=1):
            chunk_start = parsed_rows + 1
            parsed_rows += len(frame)
            timestamps, bid, ask, last, volume, flags = _parse_columns(frame)
            timestamp_valid = timestamps.notna()
            quote = _reconstruct_quote_state(
                frame,
                bid,
                ask,
                flags,
                previous_bid=previous_bid,
                previous_ask=previous_ask,
            )
            previous_bid = quote["next_bid"]
            previous_ask = quote["next_ask"]
            bid_state = quote["bid"]
            ask_state = quote["ask"]
            required_valid = timestamp_valid & quote["quote_valid"]
            invalid_mask = ~required_valid
            invalid_count = int(invalid_mask.sum())
            invalid_required += invalid_count
            reconstructed_bid_rows += int(quote["reconstructed_bid"].sum())
            reconstructed_ask_rows += int(quote["reconstructed_ask"].sum())
            raw_bid_missing_rows += int(quote["raw_bid_missing"].sum())
            raw_ask_missing_rows += int(quote["raw_ask_missing"].sum())
            flag_consistency_violations += int(quote["flag_consistency_violation"].sum())

            relation_valid = required_valid
            negative_mask = relation_valid & ask_state.lt(bid_state)
            zero_mask = relation_valid & ask_state.eq(bid_state)
            negative_count = int(negative_mask.sum())
            zero_count = int(zero_mask.sum())
            negative_spreads += negative_count
            zero_spreads += zero_count

            if bool(quote["raw_bid_valid"].any()):
                bid_scaled = (
                    bid.loc[quote["raw_bid_valid"]].to_numpy(dtype="float64") * SPREAD_SCALE
                )
                non_cent_prices += int(
                    np.count_nonzero(np.abs(bid_scaled - np.rint(bid_scaled)) > 1e-6)
                )
            if bool(quote["raw_ask_valid"].any()):
                ask_scaled = (
                    ask.loc[quote["raw_ask_valid"]].to_numpy(dtype="float64") * SPREAD_SCALE
                )
                non_cent_prices += int(
                    np.count_nonzero(np.abs(ask_scaled - np.rint(ask_scaled)) > 1e-6)
                )

            spread_mask = required_valid & ~negative_mask
            if bool(spread_mask.any()):
                spread_units = np.rint(
                    (ask_state.loc[spread_mask].to_numpy(dtype="float64")
                    - bid_state.loc[spread_mask].to_numpy(dtype="float64"))
                    * SPREAD_SCALE
                ).astype("int64")
                _add_counter(spread_counter, spread_units)

            last_raw_present = frame["<LAST>"].notna() & frame["<LAST>"].astype("string").str.len().gt(0)
            volume_raw_present = frame["<VOLUME>"].notna() & frame["<VOLUME>"].astype("string").str.len().gt(0)
            last_present += int(last_raw_present.sum())
            last_invalid += int((last_raw_present & (last.isna() | ~np.isfinite(last))).sum())
            volume_present += int(volume_raw_present.sum())
            volume_invalid_or_negative += int(
                (volume_raw_present & (volume.isna() | ~np.isfinite(volume) | volume.lt(0))).sum()
            )
            flags_counter.update(flags.fillna("<EMPTY>").astype(str).value_counts().to_dict())

            if bool(timestamp_valid.any()):
                valid_ms = (
                    timestamps.loc[timestamp_valid]
                    .to_numpy(dtype="datetime64[ms]")
                    .astype("int64")
                )
                if first_ms is None:
                    first_ms = int(valid_ms[0])
                combined = (
                    np.concatenate(([previous_ms], valid_ms))
                    if previous_ms is not None
                    else valid_ms
                )
                if len(combined) > 1:
                    deltas = np.diff(combined)
                    monotonicity_violations += int(np.count_nonzero(deltas < 0))
                    duplicate_timestamps += int(np.count_nonzero(deltas == 0))
                    _add_counter(interarrival_counter, deltas[deltas >= 0])
                previous_ms = int(valid_ms[-1])
                last_ms = int(valid_ms[-1])
                minute_values = valid_ms // 60_000
                unique_minutes, counts = np.unique(minute_values, return_counts=True)
                minute_counts.update(
                    {int(key): int(count) for key, count in zip(unique_minutes, counts)}
                )

            _problem_examples(frame, invalid_mask, "invalid_required", 100, examples)
            _problem_examples(frame, negative_mask, "negative_spread", 100, examples)
            if invalid_count or negative_count:
                problem_regions.append(
                    {
                        "chunk": chunk_number,
                        "approximate_row_start": chunk_start,
                        "approximate_row_end": parsed_rows,
                        "invalid_required_rows": invalid_count,
                        "negative_spread_rows": negative_count,
                    }
                )

            if parsed_rows >= next_progress:
                elapsed = time.monotonic() - started
                rate = parsed_rows / elapsed if elapsed else 0.0
                print(
                    f"[validate] parsed={parsed_rows:,} elapsed={elapsed:.1f}s "
                    f"rate={rate:,.0f} rows/s",
                    flush=True,
                )
                while next_progress <= parsed_rows:
                    next_progress += progress_rows

        for item in caught:
            if issubclass(item.category, ParserWarning):
                warning_messages.append(str(item.message))

    malformed_lines: list[int] = []
    for message in warning_messages:
        malformed_lines.extend(
            int(value) for value in re.findall(r"Skipping line (\d+)", message)
        )
    malformed_rows = len(malformed_lines)
    physical_rows = parsed_rows + malformed_rows
    if malformed_lines:
        problem_regions.append(
            {
                "chunk": None,
                "approximate_row_start": min(malformed_lines) - 1,
                "approximate_row_end": max(malformed_lines) - 1,
                "malformed_extra_field_rows": malformed_rows,
                "line_numbers": malformed_lines[:100],
            }
        )

    if first_ms is None or last_ms is None:
        raise ValueError("No parseable timestamps were found")

    ticks_per_minute = Counter(minute_counts.values())
    coverage, weekend = _event_coverage(minute_counts, source_timezone)
    first_source = pd.Timestamp(first_ms, unit="ms")
    last_source = pd.Timestamp(last_ms, unit="ms")
    first_utc = first_source.tz_localize(source_timezone).tz_convert("UTC")
    last_utc = last_source.tz_localize(source_timezone).tz_convert("UTC")
    spread_total = sum(spread_counter.values())
    spread_sum_units = sum(value * count for value, count in spread_counter.items())

    validation = {
        "physical_data_rows": physical_rows,
        "parsed_rows": parsed_rows,
        "first_timestamp_source": first_source.isoformat(timespec="milliseconds"),
        "last_timestamp_source": last_source.isoformat(timespec="milliseconds"),
        "first_timestamp_utc": first_utc.isoformat(timespec="milliseconds"),
        "last_timestamp_utc": last_utc.isoformat(timespec="milliseconds"),
        "duplicate_timestamp_rows": duplicate_timestamps,
        "monotonicity_violations": monotonicity_violations,
        "malformed_rows": malformed_rows,
        "invalid_required_rows": invalid_required,
        "zero_spread_rows": zero_spreads,
        "negative_spread_rows": negative_spreads,
        "raw_bid_missing_rows": raw_bid_missing_rows,
        "raw_ask_missing_rows": raw_ask_missing_rows,
        "reconstructed_bid_rows": reconstructed_bid_rows,
        "reconstructed_ask_rows": reconstructed_ask_rows,
        "flag_consistency_violations": flag_consistency_violations,
        "non_cent_price_values": non_cent_prices,
        "last_present_rows": last_present,
        "last_invalid_rows": last_invalid,
        "volume_present_rows": volume_present,
        "volume_invalid_or_negative_rows": volume_invalid_or_negative,
        "flags_distribution": dict(sorted(flags_counter.items())),
        "spread": {
            "observations": spread_total,
            "median": (_counter_quantile(spread_counter, 0.5) or 0.0) / SPREAD_SCALE,
            "average": (spread_sum_units / spread_total / SPREAD_SCALE) if spread_total else None,
            "p95": (_counter_quantile(spread_counter, 0.95) or 0.0) / SPREAD_SCALE,
            "p99": (_counter_quantile(spread_counter, 0.99) or 0.0) / SPREAD_SCALE,
            "maximum": (max(spread_counter) / SPREAD_SCALE) if spread_counter else None,
            "distribution": _spread_distribution(spread_counter),
            "precision": "exact for the detected $0.01 price grid",
        },
        "tick_frequency": {
            "populated_minutes": len(minute_counts),
            "ticks_per_minute_mean": _counter_mean(ticks_per_minute),
            "ticks_per_minute_median": _counter_quantile(ticks_per_minute, 0.5),
            "ticks_per_minute_p95": _counter_quantile(ticks_per_minute, 0.95),
            "ticks_per_minute_p99": _counter_quantile(ticks_per_minute, 0.99),
            "ticks_per_minute_max": max(ticks_per_minute) if ticks_per_minute else None,
            "interarrival_median_ms": _counter_quantile(interarrival_counter, 0.5),
            "interarrival_p95_ms": _counter_quantile(interarrival_counter, 0.95),
            "interarrival_p99_ms": _counter_quantile(interarrival_counter, 0.99),
            "interarrival_max_ms": max(interarrival_counter) if interarrival_counter else None,
            "interarrival_distribution": _interarrival_distribution(interarrival_counter),
        },
        "event_coverage": coverage,
        "weekend_data": weekend,
        "problem_regions": problem_regions,
        "problem_examples": examples,
        "parser_warnings": warning_messages,
        "elapsed_seconds": time.monotonic() - started,
    }
    quality = _quality_assessment(validation, timezone_status)
    previous_scan_count = 0
    previous_metadata_path = output_dir / "tick_metadata.json"
    if previous_metadata_path.exists():
        try:
            previous_metadata = json.loads(previous_metadata_path.read_text(encoding="utf-8"))
            if previous_metadata.get("input", {}).get("path") == _relative(input_path):
                previous_scan_count = int(
                    previous_metadata.get("processing", {}).get("source_scans_completed", 0)
                )
        except (OSError, ValueError, TypeError):
            previous_scan_count = 0

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_now(),
        "phase": "tick_data_qualification",
        "input": {
            "path": _relative(input_path),
            "size_bytes": input_path.stat().st_size,
            "format": "tab-delimited ASCII text with CRLF line endings",
            "columns": list(EXPECTED_COLUMNS),
            "timestamp_format": "%Y.%m.%d %H:%M:%S.%f",
            "original_overwritten": False,
        },
        "timezone": {
            "source_timezone": source_timezone,
            "status": timezone_status,
            "file_contains_timezone_marker": False,
            "normalization_timezone": "UTC",
            "event_timezone": NEW_YORK,
            "evidence": (
                "Tick open at 2025-07-17 13:00 matches the existing broker M15 open at the "
                "same wall time. The earlier repository report inferred Europe/Helsinki from "
                "the UTC+2/UTC+3 session pattern; broker confirmation is absent."
            ),
        },
        "processing": {
            "mode": "streaming/chunked",
            "chunk_rows": chunk_rows,
            "source_scans_completed": previous_scan_count + 1,
            "rescan_note": (
                "One earlier diagnostic pass treated incremental one-sided quote updates as "
                "incomplete snapshots. The corrected pass reconstructs only flag-consistent "
                "unchanged sides from prior quote state."
                if previous_scan_count
                else None
            ),
            "spread_scale": SPREAD_SCALE,
            "rows_retained_in_memory": "one chunk plus compact minute/distribution counters",
        },
        "validation": validation,
        "quality": quality,
        "outputs": {
            "normalized_ticks": None,
            "minute_bars": None,
            "normalized_tick_rows": None,
            "minute_bar_rows": None,
        },
        "research_readiness": {
            "stage_1": (
                "Technically runnable after a point-in-time economic calendar is supplied; "
                "definitive event attribution remains conditional on timezone confirmation."
            ),
            "lifecycle_classification": (
                "Market path data are sufficient after normalization, but lifecycle research "
                "must wait until Stage 1 and the economic-calendar gate are complete."
            ),
            "entry_geometry": (
                "Tick and one-minute bid/ask geometry can be studied later; not authorized in "
                "this qualification phase."
            ),
            "execution_cost_modeling": (
                "Observed bid/ask spreads are available. Broker commission, latency and realized "
                "slippage observations are still required for a complete execution model."
            ),
            "additional_data_required": (
                "Point-in-time U.S. economic releases with actual/consensus/vintage fields; broker "
                "server-timezone confirmation; broker commission and realized slippage/latency; "
                "trade/last/volume data for trade-price studies; and additional full years for the "
                "registered year-by-year stability requirement."
            ),
        },
    }
    _write_metadata_and_report(metadata, output_dir)

    fields = (
        sorted({key for item in problem_regions for key in item})
        if problem_regions
        else [
            "chunk",
            "approximate_row_start",
            "approximate_row_end",
            "invalid_required_rows",
            "negative_spread_rows",
        ]
    )
    with (quality_dir / "tick_corrupt_regions.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in problem_regions:
            writer.writerow(
                {
                    key: json.dumps(value) if isinstance(value, list) else value
                    for key, value in item.items()
                }
            )
    print(
        f"[validate] complete rows={physical_rows:,} verdict={quality['verdict']} "
        f"score={quality['quality_score']}/100",
        flush=True,
    )
    return metadata


def _aggregate_minutes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["minute"] = work["timestamp"].dt.floor("min")
    work["mid"] = (work["bid"] + work["ask"]) / 2.0
    work["spread"] = work["ask"] - work["bid"]
    result = (
        work.groupby("minute", sort=True, observed=True)
        .agg(
            bid_open=("bid", "first"),
            bid_high=("bid", "max"),
            bid_low=("bid", "min"),
            bid_close=("bid", "last"),
            ask_open=("ask", "first"),
            ask_high=("ask", "max"),
            ask_low=("ask", "min"),
            ask_close=("ask", "last"),
            mid_open=("mid", "first"),
            mid_high=("mid", "max"),
            mid_low=("mid", "min"),
            mid_close=("mid", "last"),
            tick_count=("bid", "size"),
            median_spread=("spread", "median"),
            maximum_spread=("spread", "max"),
            last_spread=("spread", "last"),
        )
        .reset_index()
        .rename(columns={"minute": "timestamp"})
    )
    result["source"] = "mt5_local_export"
    result["symbol"] = "XAUUSD"
    bid_ask_columns = [
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
    ]
    midpoint_columns = ["mid_open", "mid_high", "mid_low", "mid_close"]
    spread_columns = ["median_spread", "maximum_spread", "last_spread"]
    result[bid_ask_columns] = result[bid_ask_columns].round(2)
    result[midpoint_columns] = result[midpoint_columns].round(3)
    result[spread_columns] = result[spread_columns].round(2)
    return result


def _last_nonempty_line(path: Path, block_size: int = 8192) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        data = b""
        while position > 0 and data.count(b"\n") < 2:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + data
    lines = [line for line in data.splitlines() if line]
    return lines[-1].decode("utf-8") if lines else ""


def verify_normalized_outputs(output_dir: Path) -> dict[str, Any]:
    metadata_path = output_dir / "tick_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["quality"] = _quality_assessment(
        metadata["validation"], metadata["timezone"]["status"]
    )
    ticks_path = Path(metadata["outputs"]["normalized_ticks"])
    bars_path = Path(metadata["outputs"]["minute_bars"])
    bars = pd.read_csv(bars_path)
    timestamps = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
    timestamp_ms = timestamps.to_numpy(dtype="datetime64[ms]").astype("int64")
    deltas = np.diff(timestamp_ms)

    invariant_violations = 0
    for prefix in ("bid", "ask", "mid"):
        open_values = bars[f"{prefix}_open"]
        high_values = bars[f"{prefix}_high"]
        low_values = bars[f"{prefix}_low"]
        close_values = bars[f"{prefix}_close"]
        invariant_violations += int(
            (
                high_values.lt(low_values)
                | high_values.lt(open_values)
                | high_values.lt(close_values)
                | low_values.gt(open_values)
                | low_values.gt(close_values)
            ).sum()
        )
    negative_open_close = int(
        (
            bars["ask_open"].lt(bars["bid_open"])
            | bars["ask_close"].lt(bars["bid_close"])
        ).sum()
    )
    extreme = bars["maximum_spread"].gt(5.0)
    ny = timestamps.dt.tz_convert(NEW_YORK)
    ny_minutes = ny.dt.hour * 60 + ny.dt.minute
    event_extreme = extreme & ny_minutes.ge(8 * 60) & ny_minutes.lt(10 * 60 + 30)
    extreme_frame = pd.DataFrame(
        {
            "timestamp_utc": timestamps.loc[extreme],
            "timestamp_new_york": ny.loc[extreme],
            "maximum_spread": bars.loc[extreme, "maximum_spread"],
        }
    )
    top_extreme = extreme_frame.nlargest(20, "maximum_spread")
    top_rows = [
        {
            "timestamp_utc": row.timestamp_utc.isoformat(),
            "timestamp_new_york": row.timestamp_new_york.isoformat(),
            "maximum_spread": float(row.maximum_spread),
        }
        for row in top_extreme.itertuples(index=False)
    ]

    with ticks_path.open("r", encoding="utf-8", newline="") as handle:
        tick_header = handle.readline().rstrip("\r\n").split(",")
        tick_first = handle.readline().rstrip("\r\n")
    tick_last = _last_nonempty_line(ticks_path)
    expected_rows = int(metadata["outputs"]["normalized_tick_rows"])
    bar_rows = len(bars)
    checks = {
        "tick_file_exists": ticks_path.is_file(),
        "minute_bar_file_exists": bars_path.is_file(),
        "tick_header_valid": tick_header
        == ["timestamp", "bid", "ask", "flags", "source", "symbol"],
        "minute_row_count_matches_metadata": bar_rows
        == int(metadata["outputs"]["minute_bar_rows"]),
        "tick_count_sum_matches_normalized_rows": int(bars["tick_count"].sum())
        == expected_rows,
        "timestamps_parse_as_utc": bool(timestamps.notna().all()),
        "minute_timestamps_unique": not bool(np.any(deltas == 0)),
        "minute_timestamps_monotonic": not bool(np.any(deltas < 0)),
        "timestamps_are_minute_aligned": bool(
            timestamps.dt.second.eq(0).all() and timestamps.dt.microsecond.eq(0).all()
        ),
        "ohlc_invariants_hold": invariant_violations == 0,
        "open_close_spreads_nonnegative": negative_open_close == 0,
        "first_tick_boundary_matches": tick_first.startswith(
            metadata["validation"]["first_timestamp_utc"].replace("+00:00", "Z")
        ),
        "last_tick_boundary_matches": tick_last.startswith(
            metadata["validation"]["last_timestamp_utc"].replace("+00:00", "Z")
        ),
    }
    verification = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "minute_bar_rows": bar_rows,
        "tick_count_sum": int(bars["tick_count"].sum()),
        "normalized_tick_rows_from_writer": expected_rows,
        "normalized_tick_row_count_note": (
            "Row count is the successful writer counter and is cross-checked to the sum of "
            "one-minute tick_count; the 7.66 GB derivative was not rescanned solely to count lines."
        ),
        "duplicate_minute_timestamps": int(np.count_nonzero(deltas == 0)),
        "minute_timestamp_reversals": int(np.count_nonzero(deltas < 0)),
        "ohlc_invariant_violations": invariant_violations,
        "open_close_negative_spread_violations": negative_open_close,
        "first_minute_utc": timestamps.iloc[0].isoformat(),
        "last_minute_utc": timestamps.iloc[-1].isoformat(),
        "extreme_spread_minutes": int(extreme.sum()),
        "extreme_spread_minutes_0800_1030_et": int(event_extreme.sum()),
        "extreme_spread_maximum": float(bars["maximum_spread"].max()),
        "extreme_spread_minutes_by_new_york_hour": {
            str(int(hour)): int(count)
            for hour, count in ny.loc[extreme].dt.hour.value_counts().sort_index().items()
        },
        "top_extreme_spread_minutes": top_rows,
    }
    metadata["outputs"]["normalized_ticks_size_bytes"] = ticks_path.stat().st_size
    metadata["outputs"]["minute_bars_size_bytes"] = bars_path.stat().st_size
    metadata["derivative_verification"] = verification
    _write_metadata_and_report(metadata, output_dir)
    return metadata


def normalize_ticks(
    input_path: Path,
    output_dir: Path,
    normalized_dir: Path,
    *,
    source_timezone: str,
    chunk_rows: int = 1_000_000,
    progress_rows: int = 5_000_000,
) -> dict[str, Any]:
    metadata_path = output_dir / "tick_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["quality"] = _quality_assessment(
        metadata["validation"], metadata["timezone"]["status"]
    )
    if not metadata["quality"]["normalization_gate_passed"]:
        raise ValueError("Normalization gate failed; no derivative dataset will be written")
    if metadata["timezone"]["source_timezone"] != source_timezone:
        raise ValueError("Normalization timezone differs from validated timezone")

    normalized_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    ticks_path = normalized_dir / f"{stem}.canonical_ticks.csv"
    bars_path = normalized_dir / f"{stem}.1m_bidask.csv"
    ticks_partial = ticks_path.with_suffix(ticks_path.suffix + ".partial")
    bars_partial = bars_path.with_suffix(bars_path.suffix + ".partial")
    for path in (ticks_partial, bars_partial):
        if path.exists():
            path.unlink()

    include_last = metadata["validation"]["last_present_rows"] > 0
    include_volume = metadata["validation"]["volume_present_rows"] > 0
    include_flags = any(
        key != "<EMPTY>" and value > 0
        for key, value in metadata["validation"]["flags_distribution"].items()
    )
    normalized_rows = 0
    bar_rows = 0
    carry = pd.DataFrame(columns=["timestamp", "bid", "ask"])
    started = time.monotonic()
    next_progress = progress_rows
    tick_header = True
    bar_header = True
    previous_bid: float | None = None
    previous_ask: float | None = None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ParserWarning)
        for frame in _reader(input_path, chunk_rows):
            timestamps, bid, ask, last, volume, flags = _parse_columns(frame)
            quote = _reconstruct_quote_state(
                frame,
                bid,
                ask,
                flags,
                previous_bid=previous_bid,
                previous_ask=previous_ask,
            )
            previous_bid = quote["next_bid"]
            previous_ask = quote["next_ask"]
            bid_state = quote["bid"]
            ask_state = quote["ask"]
            valid = timestamps.notna() & quote["quote_valid"] & ask_state.ge(bid_state)
            localized = pd.DatetimeIndex(timestamps.loc[valid]).tz_localize(
                source_timezone, ambiguous="raise", nonexistent="raise"
            )
            utc = localized.tz_convert("UTC")
            bid_values = bid_state.loc[valid].to_numpy(dtype="float64")
            ask_values = ask_state.loc[valid].to_numpy(dtype="float64")
            timestamp_values = np.datetime_as_string(
                utc.tz_localize(None).to_numpy(dtype="datetime64[ms]"),
                unit="ms",
                timezone="UTC",
            )
            canonical = pd.DataFrame(
                {
                    "timestamp": timestamp_values,
                    "bid": bid_values,
                    "ask": ask_values,
                }
            )
            if include_last:
                canonical["last"] = last.loc[valid].to_numpy(dtype="float64")
            if include_volume:
                canonical["volume"] = volume.loc[valid].to_numpy(dtype="float64")
            if include_flags:
                canonical["flags"] = flags.loc[valid].fillna("").to_numpy()
            canonical["source"] = "mt5_local_export"
            canonical["symbol"] = "XAUUSD"
            canonical.to_csv(
                ticks_partial,
                mode="a",
                index=False,
                header=tick_header,
                lineterminator="\n",
            )
            tick_header = False
            normalized_rows += len(canonical)

            bar_input = pd.DataFrame(
                {"timestamp": utc, "bid": bid_values, "ask": ask_values}
            )
            if not carry.empty:
                bar_input = pd.concat([carry, bar_input], ignore_index=True)
            if not bar_input.empty:
                minutes = bar_input["timestamp"].dt.floor("min")
                final_minute = minutes.iloc[-1]
                complete = minutes.ne(final_minute)
                bars = _aggregate_minutes(bar_input.loc[complete])
                carry = bar_input.loc[~complete].copy()
                if not bars.empty:
                    bars.to_csv(
                        bars_partial,
                        mode="a",
                        index=False,
                        header=bar_header,
                        date_format="%Y-%m-%dT%H:%M:%SZ",
                        lineterminator="\n",
                    )
                    bar_header = False
                    bar_rows += len(bars)

            if normalized_rows >= next_progress:
                elapsed = time.monotonic() - started
                rate = normalized_rows / elapsed if elapsed else 0.0
                print(
                    f"[normalize] rows={normalized_rows:,} bars={bar_rows:,} "
                    f"elapsed={elapsed:.1f}s rate={rate:,.0f} rows/s",
                    flush=True,
                )
                while next_progress <= normalized_rows:
                    next_progress += progress_rows

    if not carry.empty:
        bars = _aggregate_minutes(carry)
        bars.to_csv(
            bars_partial,
            mode="a",
            index=False,
            header=bar_header,
            date_format="%Y-%m-%dT%H:%M:%SZ",
            lineterminator="\n",
        )
        bar_rows += len(bars)

    ticks_partial.replace(ticks_path)
    bars_partial.replace(bars_path)
    metadata["processing"]["source_scans_completed"] = (
        int(metadata["processing"]["source_scans_completed"]) + 1
    )
    metadata["processing"]["normalization_elapsed_seconds"] = time.monotonic() - started
    metadata["outputs"] = {
        "normalized_ticks": _relative(ticks_path),
        "normalized_ticks_size_bytes": ticks_path.stat().st_size,
        "minute_bars": _relative(bars_path),
        "minute_bars_size_bytes": bars_path.stat().st_size,
        "normalized_tick_rows": normalized_rows,
        "minute_bar_rows": bar_rows,
        "excluded_rows": metadata["validation"]["physical_data_rows"] - normalized_rows,
    }
    _write_metadata_and_report(metadata, output_dir)
    print(
        f"[normalize] complete ticks={normalized_rows:,} bars={bar_rows:,}", flush=True
    )
    return metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Streaming XAUUSD tick qualification")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="run one full validation scan")
    validate.add_argument("--input", required=True, type=Path)
    validate.add_argument("--output-dir", required=True, type=Path)
    validate.add_argument("--source-timezone", required=True)
    validate.add_argument(
        "--timezone-status", choices=("confirmed", "assumed"), default="assumed"
    )
    validate.add_argument("--chunk-rows", type=int, default=1_000_000)
    validate.add_argument("--progress-rows", type=int, default=5_000_000)

    normalize = subparsers.add_parser(
        "normalize", help="write canonical ticks and one-minute bars after a passing gate"
    )
    normalize.add_argument("--input", required=True, type=Path)
    normalize.add_argument("--output-dir", required=True, type=Path)
    normalize.add_argument("--normalized-dir", required=True, type=Path)
    normalize.add_argument("--source-timezone", required=True)
    normalize.add_argument("--chunk-rows", type=int, default=1_000_000)
    normalize.add_argument("--progress-rows", type=int, default=5_000_000)

    verify = subparsers.add_parser(
        "verify", help="verify completed derivatives without rescanning the tick CSV"
    )
    verify.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        metadata = validate_ticks(
            args.input,
            args.output_dir,
            source_timezone=args.source_timezone,
            timezone_status=args.timezone_status,
            chunk_rows=args.chunk_rows,
            progress_rows=args.progress_rows,
        )
        return 0 if metadata["quality"]["normalization_gate_passed"] else 2
    if args.command == "normalize":
        normalize_ticks(
            args.input,
            args.output_dir,
            args.normalized_dir,
            source_timezone=args.source_timezone,
            chunk_rows=args.chunk_rows,
            progress_rows=args.progress_rows,
        )
        return 0
    if args.command == "verify":
        metadata = verify_normalized_outputs(args.output_dir)
        return 0 if metadata["derivative_verification"]["status"] == "PASS" else 2
    raise RuntimeError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
