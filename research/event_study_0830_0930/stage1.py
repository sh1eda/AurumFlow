"""Stage 1 timing/volatility study; no discretionary entries or edge claims."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .data_validation import (
    EVENT_WINDOWS,
    ValidationThresholds,
    refuse_on_critical,
    validate_market_data,
    write_quality_reports,
)
from .event_cluster_builder import build_event_clusters
from .stage1_timing_analysis import run_comprehensive_stage1


CLOCK_WINDOWS = {
    "08:30": ("08:30", "08:35", "08:25", "08:30"),
    "09:30": ("09:30", "09:35", "09:25", "09:30"),
    "10:00": ("10:00", "10:05", "09:55", "10:00"),
}


def _prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    work = bars.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["timestamp_new_york"] = work["timestamp"].dt.tz_convert("America/New_York")
    work["session_date"] = work["timestamp_new_york"].dt.date.astype(str)
    for field in ("open", "high", "low", "close"):
        midpoint = f"mid_{field}"
        if midpoint not in work:
            work[midpoint] = (work[f"bid_{field}"] + work[f"ask_{field}"]) / 2.0
    if "last_spread" not in work:
        work["last_spread"] = work["ask_close"] - work["bid_close"]
    return work


def _slice(work: pd.DataFrame, session_date: str, start: str, end: str) -> pd.DataFrame:
    start_at = pd.Timestamp(f"{session_date} {start}", tz="America/New_York")
    end_at = pd.Timestamp(f"{session_date} {end}", tz="America/New_York")
    return work[
        work["timestamp_new_york"].ge(start_at) & work["timestamp_new_york"].lt(end_at)
    ]


def _window_metrics(frame: pd.DataFrame, expected_minutes: int) -> dict:
    if frame.empty:
        return {
            "observed_minutes": 0,
            "expected_minutes": expected_minutes,
            "coverage_status": "entirely_missing",
            "directional_return_bp": math.nan,
            "absolute_return_bp": math.nan,
            "range_price": math.nan,
            "realized_volatility_bp": math.nan,
            "median_spread": math.nan,
            "maximum_spread": math.nan,
        }
    unique_minutes = int(frame["timestamp_new_york"].dt.floor("min").nunique())
    status = "complete" if unique_minutes == expected_minutes else "partially_missing"
    first_open = float(frame.iloc[0]["mid_open"])
    last_close = float(frame.iloc[-1]["mid_close"])
    directional = math.log(last_close / first_open) * 10_000.0 if first_open > 0 else math.nan
    close_returns = frame["mid_close"].astype(float).map(math.log).diff().dropna()
    realized = float(math.sqrt(float((close_returns**2).sum())) * 10_000.0)
    spread_series = pd.to_numeric(
        frame.get("median_spread", frame["last_spread"]), errors="coerce"
    ).dropna()
    maximum_series = pd.to_numeric(
        frame.get("maximum_spread", frame["last_spread"]), errors="coerce"
    ).dropna()
    return {
        "observed_minutes": unique_minutes,
        "expected_minutes": expected_minutes,
        "coverage_status": status,
        "directional_return_bp": directional,
        "absolute_return_bp": abs(directional),
        "range_price": float(frame["mid_high"].max() - frame["mid_low"].min()),
        "realized_volatility_bp": realized,
        "median_spread": float(spread_series.median()) if not spread_series.empty else math.nan,
        "maximum_spread": float(maximum_series.max()) if not maximum_series.empty else math.nan,
    }


def _event_labels(session_date: str, clusters: pd.DataFrame) -> dict:
    day = clusters[clusters["session_date"].astype(str).eq(session_date)]
    at_0830 = day[day["is_0830"].astype(bool)]
    at_1000 = day[day["is_1000"].astype(bool)]
    if at_0830["importance"].eq("major").any():
        event_class = "A_major_0830"
    elif at_0830["importance"].eq("minor").any():
        event_class = "B_minor_0830"
    else:
        event_class = "C_no_meaningful_0830"
    return {
        "event_class": event_class,
        "important_1000_release": bool(at_1000["importance"].eq("major").any()),
        "minor_1000_release": bool(at_1000["importance"].eq("minor").any()),
        "cluster_count_0830": int(len(at_0830)),
        "cluster_count_1000": int(len(at_1000)),
    }


def build_stage1_session_windows(bars: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    work = _prepare_bars(bars)
    records: list[dict] = []
    for session_date in sorted(work["session_date"].unique()):
        labels = _event_labels(session_date, clusters)
        for window, (start, end) in EVENT_WINDOWS.items():
            expected = int(
                (pd.Timestamp(f"{session_date} {end}") - pd.Timestamp(f"{session_date} {start}"))
                / pd.Timedelta(minutes=1)
            )
            records.append(
                {
                    "session_date": session_date,
                    "window": window,
                    "start_new_york": start,
                    "end_new_york_exclusive": end,
                    **labels,
                    **_window_metrics(_slice(work, session_date, start, end), expected),
                }
            )
    return pd.DataFrame.from_records(records)


def build_clock_effects(bars: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    work = _prepare_bars(bars)
    records: list[dict] = []
    for session_date in sorted(work["session_date"].unique()):
        labels = _event_labels(session_date, clusters)
        day_clusters = clusters[clusters["session_date"].astype(str).eq(session_date)]
        for clock, (start, end, prior_start, prior_end) in CLOCK_WINDOWS.items():
            target = _window_metrics(_slice(work, session_date, start, end), 5)
            prior = _window_metrics(_slice(work, session_date, prior_start, prior_end), 5)
            at_clock = day_clusters[day_clusters["release_clock_new_york"].eq(clock)]
            records.append(
                {
                    "session_date": session_date,
                    "clock_new_york": clock,
                    "scheduled_release_at_clock": bool(not at_clock.empty),
                    "major_release_at_clock": bool(at_clock["importance"].eq("major").any()),
                    **labels,
                    **{f"target_{key}": value for key, value in target.items()},
                    "prior_realized_volatility_bp": prior["realized_volatility_bp"],
                    "incremental_realized_volatility_bp": (
                        target["realized_volatility_bp"] - prior["realized_volatility_bp"]
                        if math.isfinite(target["realized_volatility_bp"])
                        and math.isfinite(prior["realized_volatility_bp"])
                        else math.nan
                    ),
                    "prior_absolute_return_bp": prior["absolute_return_bp"],
                    "incremental_absolute_return_bp": (
                        target["absolute_return_bp"] - prior["absolute_return_bp"]
                        if math.isfinite(target["absolute_return_bp"])
                        and math.isfinite(prior["absolute_return_bp"])
                        else math.nan
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def summarize_clock_effects(clock_effects: pd.DataFrame) -> pd.DataFrame:
    if clock_effects.empty:
        return pd.DataFrame()
    complete = clock_effects[clock_effects["target_coverage_status"].eq("complete")]
    metrics = [
        "target_absolute_return_bp",
        "target_directional_return_bp",
        "target_range_price",
        "target_realized_volatility_bp",
        "target_median_spread",
        "target_maximum_spread",
        "incremental_realized_volatility_bp",
        "incremental_absolute_return_bp",
    ]
    summary = (
        complete.groupby(
            ["clock_new_york", "scheduled_release_at_clock", "major_release_at_clock"],
            dropna=False,
        )[metrics]
        .agg(["count", "mean", "median"])
        .reset_index()
    )
    summary.columns = [
        "_".join(str(part) for part in column if str(part))
        if isinstance(column, tuple)
        else str(column)
        for column in summary.columns
    ]
    return summary


def run_stage1(
    bars: pd.DataFrame,
    events: pd.DataFrame,
    output_directory: str | Path,
    *,
    thresholds: ValidationThresholds | None = None,
    day_classification: pd.DataFrame | None = None,
) -> Path:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    clusters = build_event_clusters(events)
    analysis_thresholds = thresholds or ValidationThresholds(
        # This qualified broker feed contains reconstructed zero-spread
        # states, documented holiday gaps, and two closure-boundary records.
        # Stage 1 retains them in raw results and reports filtered/floored
        # sensitivities; negative spreads and bid-above-ask still fail closed.
        maximum_missing_minute_percentage=5.0,
        maximum_invalid_spreads=len(bars),
        maximum_closure_records=10,
    )
    quality = validate_market_data(
        bars,
        mode="bars",
        # Boundary and event-window coverage are handled explicitly by the
        # Stage 1 exclusion table. Structural defects still fail closed.
        event_clusters=None,
        thresholds=analysis_thresholds,
    )
    write_quality_reports(
        quality,
        output / "data_quality_report.json",
        output / "data_quality_report.md",
    )
    refuse_on_critical(quality)

    comprehensive = run_comprehensive_stage1(
        bars,
        clusters,
        output,
        day_classification=day_classification,
        structural_quality=quality,
    )

    session_windows = build_stage1_session_windows(bars, clusters)
    clock_effects = build_clock_effects(bars, clusters)
    clock_summary = summarize_clock_effects(clock_effects)
    session_windows.to_csv(output / "stage1_session_windows.csv", index=False)
    clock_effects.to_csv(output / "stage1_clock_effects.csv", index=False)
    clock_summary.to_csv(output / "stage1_clock_summary.csv", index=False)
    clusters.to_csv(output / "event_clusters.csv", index=False)
    metadata = {
        "stage": 1,
        "study": "timing_and_volatility_only",
        "internal_timezone": "UTC",
        "analysis_timezone": "America/New_York",
        "midpoint_role": "analytical movement only; not executable performance",
        "execution_performance_reported": False,
        "discretionary_entry_concepts_tested": False,
        "session_count": int(session_windows["session_date"].nunique()),
        "event_cluster_count": int(len(clusters)),
        "research_verdict": comprehensive["verdict"],
        "outputs": [
            "data_quality_report.json",
            "data_quality_report.md",
            "stage1_session_windows.csv",
            "stage1_clock_effects.csv",
            "stage1_clock_summary.csv",
            "event_clusters.csv",
            "stage1_summary.md",
            "stage1_results.json",
            "event_level_features.csv",
            "daily_lifecycle_classification.csv",
            "window_statistics.csv",
            "category_statistics.csv",
            "cluster_statistics.csv",
            "news_vs_nonnews.csv",
            "spread_analysis.csv",
            "sensitivity_analysis.csv",
            "data_exclusions.csv",
            "stage1_quality_report.json",
        ],
    }
    (output / "stage1_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
