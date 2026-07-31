"""Comprehensive Stage 1 timing study using only scheduled timestamps and bid/ask bars.

This module intentionally excludes actual, consensus, revision, surprise, entry-geometry,
and production-strategy logic.  All forward-looking fields are labeled outcomes.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


MINIMUM_GROUP_SAMPLE = 10
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 20_260_717
TARGET_CLOCKS = {"08:30", "09:15", "10:00", "14:00", "14:30"}

ABSOLUTE_0830_WINDOWS = {
    "pre_event_0800_0829": ("08:00", "08:30"),
    "immediate_0830_0834": ("08:30", "08:35"),
    "impulse_0830_0859": ("08:30", "09:00"),
    "pre_open_0900_0929": ("09:00", "09:30"),
    "cash_impulse_0930_0934": ("09:30", "09:35"),
    "cash_window_0930_0959": ("09:30", "10:00"),
    "secondary_1000_1029": ("10:00", "10:30"),
    "full_lifecycle_0830_1030": ("08:30", "10:31"),
}
RELATIVE_WINDOWS = {
    "relative_pre_30m": (-30, 0),
    "relative_pre_5m": (-5, 0),
    "relative_immediate_5m": (0, 5),
    "relative_post_30m": (0, 30),
    "relative_full_60m": (0, 60),
}
LIFECYCLE_THRESHOLDS = {
    "impulse_minutes": 5,
    "material_close_displacement_pre_range_fraction": 0.25,
    "material_impulse_range_pre_range_fraction": 0.75,
    "directionless_close_impulse_range_fraction": 0.25,
    "range_expansion_pre_range_fraction": 1.0,
    "continuation_post_0930_impulse_fraction": 0.25,
    "reversal_post_0930_impulse_fraction": 0.50,
    "secondary_1000_impulse_fraction": 0.50,
    "partial_retracement_lower": 0.25,
    "partial_retracement_upper": 0.75,
}


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _safe_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _sign(value: float, tolerance: float = 1e-12) -> int:
    if not math.isfinite(value) or abs(value) <= tolerance:
        return 0
    return 1 if value > 0 else -1


def prepare_timing_bars(bars: pd.DataFrame) -> pd.DataFrame:
    work = bars.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["timestamp_new_york"] = work["timestamp"].dt.tz_convert("America/New_York")
    work["session_date"] = work["timestamp_new_york"].dt.date.astype(str)
    for field in ("open", "high", "low", "close"):
        if f"mid_{field}" not in work:
            work[f"mid_{field}"] = (work[f"bid_{field}"] + work[f"ask_{field}"]) / 2.0
    if "last_spread" not in work:
        work["last_spread"] = work["ask_close"] - work["bid_close"]
    for column in (
        "bid_open", "bid_high", "bid_low", "bid_close", "ask_open", "ask_high",
        "ask_low", "ask_close", "mid_open", "mid_high", "mid_low", "mid_close",
        "last_spread", "median_spread", "maximum_spread", "tick_count",
    ):
        if column in work:
            work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.sort_values("timestamp_new_york").reset_index(drop=True)
    return work


def _clock_timestamp(session_date: str, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{session_date} {clock}", tz="America/New_York")


def _slice_between(work: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return work[work["timestamp_new_york"].ge(start) & work["timestamp_new_york"].lt(end)]


def _coverage(work: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[int, int, str]:
    expected = int((end - start) / pd.Timedelta(minutes=1))
    observed = int(_slice_between(work, start, end)["timestamp_new_york"].dt.floor("min").nunique())
    status = "complete" if observed == expected else ("entirely_missing" if observed == 0 else "partially_missing")
    return observed, expected, status


def _derive_day_classification(clusters: pd.DataFrame, work: pd.DataFrame) -> pd.DataFrame:
    records: list[dict] = []
    for date in sorted(work["session_date"].unique()):
        day = clusters[clusters["session_date"].astype(str).eq(date)]
        clocks = set(day["release_clock_new_york"].astype(str))
        has_0830, has_0915, has_1000 = "08:30" in clocks, "09:15" in clocks, "10:00" in clocks
        has_fomc = bool(clocks.intersection({"14:00", "14:30"}))
        if has_fomc:
            timing_class = "fomc_day"
        elif has_0830 and has_1000:
            timing_class = "0830_and_1000"
        elif has_0830:
            timing_class = "0830_only"
        elif has_1000:
            timing_class = "1000_only"
        elif len(clocks) > 1 or has_0915:
            timing_class = "mixed_release_day"
        else:
            timing_class = "no_scheduled_release"
        if day["importance"].eq("major").any():
            news_class = "major_news_day"
        elif not day.empty:
            news_class = "minor_news_day"
        else:
            news_class = "non_news_day_inferred"
        records.append({
            "date_et": date,
            "has_0830_release": has_0830,
            "has_0915_release": has_0915,
            "has_1000_release": has_1000,
            "has_fomc_event": has_fomc,
            "timing_class": timing_class,
            "news_day_class": news_class,
            "calendar_completeness_status": "inferred_from_loaded_calendar",
        })
    return pd.DataFrame.from_records(records)


def _normalize_days(
    days: pd.DataFrame | None, clusters: pd.DataFrame, work: pd.DataFrame
) -> pd.DataFrame:
    if days is None or days.empty:
        return _derive_day_classification(clusters, work)
    result = days.copy()
    if "date_et" not in result:
        raise ValueError("Trading-day classification requires date_et")
    result["date_et"] = pd.to_datetime(result["date_et"]).dt.date.astype(str)
    for column in ("has_0830_release", "has_0915_release", "has_1000_release", "has_fomc_event"):
        if column not in result:
            result[column] = False
        result[column] = result[column].astype(str).str.lower().isin({"true", "1", "yes"})
    return result.sort_values("date_et").reset_index(drop=True)


def _build_anchors(clusters: pd.DataFrame, days: pd.DataFrame) -> pd.DataFrame:
    day_map = days.set_index("date_et").to_dict(orient="index")
    records: list[dict] = []
    selected = clusters[clusters["release_clock_new_york"].astype(str).isin(TARGET_CLOCKS)]
    for _, row in selected.iterrows():
        date = str(row["session_date"])
        day = day_map.get(date, {})
        clock = str(row["release_clock_new_york"])
        records.append({
            "anchor_id": str(row["cluster_id"]),
            "cluster_id": str(row["cluster_id"]),
            "anchor_kind": "registered_event",
            "session_date": date,
            "anchor_timestamp_new_york": pd.Timestamp(row["release_timestamp_new_york"]),
            "clock_new_york": clock,
            "importance": str(row.get("importance", "none")),
            "event_count": int(row.get("event_count", 0)),
            "categories": row.get("categories", "[]"),
            "event_names": row.get("event_names", "[]"),
            "attribution_status": str(row.get("attribution_status", "unknown")),
            "exclude_event_specific_analysis": bool(row.get("exclude_event_specific_analysis", False)),
            "timing_class": str(day.get("timing_class", "unclassified")),
            "news_day_class": str(day.get("news_day_class", "registered_news_day")),
            "calendar_completeness_status": str(day.get("calendar_completeness_status", "unknown")),
            "has_0830_release": bool(day.get("has_0830_release", clock == "08:30")),
            "has_1000_release": bool(day.get("has_1000_release", clock == "10:00")),
            "has_fomc_event": bool(day.get("has_fomc_event", clock in {"14:00", "14:30"})),
        })
    for _, day in days.iterrows():
        date = str(day["date_et"])
        common = {
            "session_date": date,
            "importance": "none",
            "event_count": 0,
            "categories": "[]",
            "event_names": "[]",
            "attribution_status": "not_applicable",
            "exclude_event_specific_analysis": False,
            "timing_class": str(day.get("timing_class", "unclassified")),
            "news_day_class": str(day.get("news_day_class", "unclassified")),
            "calendar_completeness_status": str(day.get("calendar_completeness_status", "unknown")),
            "has_0830_release": bool(day.get("has_0830_release", False)),
            "has_1000_release": bool(day.get("has_1000_release", False)),
            "has_fomc_event": bool(day.get("has_fomc_event", False)),
        }
        records.append({
            **common,
            "anchor_id": f"cash-open-{date}",
            "cluster_id": "",
            "anchor_kind": "session_cash_open",
            "anchor_timestamp_new_york": _clock_timestamp(date, "09:30"),
            "clock_new_york": "09:30",
        })
        complete = "complete" in str(day.get("calendar_completeness_status", "")).lower()
        qualified = str(day.get("news_day_class", "")) == "non_news_day_usable_sources_only" and complete
        if qualified:
            records.append({
                **common,
                "anchor_id": f"qualified-nonnews-0830-{date}",
                "cluster_id": "",
                "anchor_kind": "qualified_non_news_0830",
                "anchor_timestamp_new_york": _clock_timestamp(date, "08:30"),
                "clock_new_york": "08:30",
            })
            if not bool(day.get("has_1000_release", False)):
                records.append({
                    **common,
                    "anchor_id": f"qualified-nonnews-1000-{date}",
                    "cluster_id": "",
                    "anchor_kind": "qualified_non_news_1000",
                    "anchor_timestamp_new_york": _clock_timestamp(date, "10:00"),
                    "clock_new_york": "10:00",
                })
    return pd.DataFrame.from_records(records).sort_values(
        ["anchor_timestamp_new_york", "anchor_kind"]
    ).reset_index(drop=True)


def _spread_percentile(value: float, sorted_spreads: np.ndarray) -> float:
    if not math.isfinite(value) or not len(sorted_spreads):
        return math.nan
    return float(np.searchsorted(sorted_spreads, value, side="right") / len(sorted_spreads))


def _window_features(
    frame: pd.DataFrame,
    expected: int,
    sorted_spreads: np.ndarray,
    extreme_threshold: float,
    median_spread_floor: float,
) -> dict:
    if frame.empty:
        return {
            "observed_minutes": 0, "expected_minutes": expected, "coverage_status": "entirely_missing"
        }
    observed = int(frame["timestamp_new_york"].dt.floor("min").nunique())
    coverage = "complete" if observed == expected else "partially_missing"
    first = frame.iloc[0]
    last = frame.iloc[-1]
    start = float(first["mid_open"])
    end = float(last["mid_close"])
    signed_move = end - start
    direction = _sign(signed_move)
    first_return = math.log(float(first["mid_close"]) / start) * 10_000 if start > 0 else math.nan
    cumulative = math.log(end / start) * 10_000 if start > 0 and end > 0 else math.nan
    previous = pd.Series([start, *frame["mid_close"].astype(float).iloc[:-1].tolist()], index=frame.index)
    one_minute = np.log(frame["mid_close"].astype(float) / previous) * 10_000
    high = frame["mid_high"].astype(float)
    low = frame["mid_low"].astype(float)
    high_position = int(np.argmax(high.to_numpy()))
    low_position = int(np.argmin(low.to_numpy()))
    high_excursion = float(high.max() - start)
    low_excursion = float(low.min() - start)
    if direction >= 0:
        mfe, mae = high_excursion, min(0.0, low_excursion)
        executable = float(last["bid_close"] - first["ask_open"])
        favorable = (high - start).to_numpy()
    else:
        mfe, mae = -low_excursion, min(0.0, -high_excursion)
        executable = float(first["bid_open"] - last["ask_close"])
        favorable = (start - low).to_numpy()
    maximum_displacement_position = int(np.argmax(np.abs(np.r_[high_excursion, low_excursion])))
    maximum_displacement_minutes = high_position if maximum_displacement_position == 0 else low_position
    maximum_favorable = max(0.0, float(np.nanmax(favorable)))
    retracement = (
        max(0.0, min(2.0, 1.0 - abs(signed_move) / maximum_favorable))
        if maximum_favorable > 0 else math.nan
    )
    spread = pd.to_numeric(frame.get("median_spread", frame["last_spread"]), errors="coerce")
    max_spread = pd.to_numeric(frame.get("maximum_spread", frame["last_spread"]), errors="coerce")
    median_spread = float(spread.median())
    range_price = float(high.max() - low.min())
    matching = float((np.sign(one_minute) == direction).mean()) if direction else math.nan
    reversal = max(0.0, maximum_favorable - direction * signed_move) if direction else math.nan
    observed_drag = abs(signed_move) - executable
    executable_with_floor = abs(signed_move) - max(observed_drag, median_spread_floor)
    return {
        "observed_minutes": observed,
        "expected_minutes": expected,
        "coverage_status": coverage,
        "first_minute_return_bps": first_return,
        "cumulative_return_bps": cumulative,
        "absolute_return_bps": abs(cumulative),
        "range_price": range_price,
        "range_bps": range_price / start * 10_000 if start > 0 else math.nan,
        "realized_volatility_bps": float(math.sqrt(float(np.square(one_minute).sum()))),
        "tick_count_sum": float(pd.to_numeric(frame.get("tick_count", pd.Series(1, index=frame.index)), errors="coerce").sum()),
        "observations_per_minute": float(pd.to_numeric(frame.get("tick_count", pd.Series(1, index=frame.index)), errors="coerce").mean()),
        "median_spread": median_spread,
        "maximum_spread": float(max_spread.max()),
        "median_spread_percentile": _spread_percentile(median_spread, sorted_spreads),
        "maximum_spread_percentile": _spread_percentile(float(max_spread.max()), sorted_spreads),
        "extreme_spread_minutes": int(max_spread.gt(extreme_threshold).sum()),
        "spread_filter_pass": bool(not max_spread.gt(extreme_threshold).any()),
        "direction": direction,
        "maximum_favorable_excursion_price": mfe,
        "maximum_adverse_excursion_price": mae,
        "directional_persistence": matching,
        "reversal_magnitude_price": reversal,
        "time_to_local_high_minutes": high_position,
        "time_to_local_low_minutes": low_position,
        "time_to_maximum_displacement_minutes": maximum_displacement_minutes,
        "retracement_percentage": retracement,
        "gross_hindsight_direction_move_price": abs(signed_move),
        "executable_hindsight_direction_move_price": executable,
        "observed_spread_cost_drag_price": observed_drag,
        "survives_observed_spread_cost": bool(executable > 0),
        "median_spread_floor_price": median_spread_floor,
        "executable_move_with_median_spread_floor_price": executable_with_floor,
        "survives_median_spread_floor": bool(executable_with_floor > 0),
    }


def _spread_normalization(work: pd.DataFrame, anchor: pd.Timestamp) -> float:
    before = _slice_between(work, anchor - pd.Timedelta(minutes=30), anchor)
    after = _slice_between(work, anchor, anchor + pd.Timedelta(minutes=60))
    if len(before) < 20 or after.empty:
        return math.nan
    baseline = float(pd.to_numeric(before.get("median_spread", before["last_spread"]), errors="coerce").median())
    spreads = pd.to_numeric(after.get("median_spread", after["last_spread"]), errors="coerce").to_numpy()
    threshold = baseline * 1.25
    for position in range(max(0, len(spreads) - 2)):
        if np.all(spreads[position : position + 3] <= threshold):
            return float(position)
    return math.nan


def build_event_level_features(
    work: pd.DataFrame, anchors: pd.DataFrame, extreme_threshold: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sorted_spreads = np.sort(pd.to_numeric(work["last_spread"], errors="coerce").dropna().to_numpy())
    median_spread_floor = float(np.median(sorted_spreads))
    records: list[dict] = []
    exclusions: list[dict] = []
    for _, anchor in anchors.iterrows():
        at = pd.Timestamp(anchor["anchor_timestamp_new_york"])
        clock = str(anchor["clock_new_york"])
        if clock == "08:30":
            definitions = {
                name: (_clock_timestamp(str(anchor["session_date"]), start), _clock_timestamp(str(anchor["session_date"]), end))
                for name, (start, end) in ABSOLUTE_0830_WINDOWS.items()
            }
        else:
            definitions = {
                name: (at + pd.Timedelta(minutes=start), at + pd.Timedelta(minutes=end))
                for name, (start, end) in RELATIVE_WINDOWS.items()
            }
        normalization = _spread_normalization(work, at)
        anchor_records: list[dict] = []
        for window_name, (start, end) in definitions.items():
            frame = _slice_between(work, start, end)
            expected = int((end - start) / pd.Timedelta(minutes=1))
            metrics = _window_features(
                frame, expected, sorted_spreads, extreme_threshold, median_spread_floor
            )
            record = {
                **anchor.to_dict(),
                "anchor_timestamp_new_york": at.isoformat(),
                "window_name": window_name,
                "window_start_new_york": start.isoformat(),
                "window_end_new_york_exclusive": end.isoformat(),
                "window_role": "forward_outcome" if start >= at else "pre_event_baseline",
                "overlap_note": "overlaps_are_intentional_descriptive_views_not_independent_observations",
                "spread_normalization_minutes": normalization,
                **metrics,
            }
            anchor_records.append(record)
            if metrics["coverage_status"] != "complete":
                exclusions.append({
                    "session_date": anchor["session_date"], "anchor_id": anchor["anchor_id"],
                    "clock_new_york": clock, "window_name": window_name,
                    "reason": metrics["coverage_status"], "observed_minutes": metrics["observed_minutes"],
                    "expected_minutes": metrics["expected_minutes"],
                })
        baseline = next((r for r in anchor_records if r["window_name"] in {"pre_event_0800_0829", "relative_pre_30m"}), None)
        baseline_range = _safe_float(baseline.get("range_price")) if baseline else math.nan
        baseline_spread = _safe_float(baseline.get("median_spread")) if baseline else math.nan
        for record in anchor_records:
            record["range_expansion_vs_pre_event"] = (
                _safe_float(record.get("range_price")) / baseline_range if baseline_range > 0 else math.nan
            )
            record["spread_expansion_vs_pre_event"] = (
                _safe_float(record.get("median_spread")) / baseline_spread if baseline_spread > 0 else math.nan
            )
            records.append(record)
    return pd.DataFrame.from_records(records), pd.DataFrame.from_records(exclusions)


def _day_move(work: pd.DataFrame, date: str, start: str, end: str) -> tuple[pd.DataFrame, float, float]:
    frame = _slice_between(work, _clock_timestamp(date, start), _clock_timestamp(date, end))
    if frame.empty:
        return frame, math.nan, math.nan
    return frame, float(frame.iloc[-1]["mid_close"] - frame.iloc[0]["mid_open"]), float(frame["mid_high"].max() - frame["mid_low"].min())


def classify_lifecycle(
    work: pd.DataFrame, clusters: pd.DataFrame, days: pd.DataFrame, extreme_threshold: float,
    *, impulse_minutes: int = 5, continuation_fraction: float = 0.25,
    reversal_fraction: float = 0.50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict] = []
    exclusions: list[dict] = []
    day_map = days.set_index("date_et").to_dict(orient="index")
    at_0830 = clusters[clusters["release_clock_new_york"].astype(str).eq("08:30")]
    for _, cluster in at_0830.iterrows():
        date = str(cluster["session_date"])
        day = day_map.get(date, {})
        pre, _, pre_range = _day_move(work, date, "08:00", "08:30")
        impulse_end = (_clock_timestamp(date, "08:30") + pd.Timedelta(minutes=impulse_minutes)).strftime("%H:%M")
        impulse, impulse_move, impulse_range = _day_move(work, date, "08:30", impulse_end)
        transition, transition_move, _ = _day_move(work, date, impulse_end, "09:30")
        cash, cash_move, _ = _day_move(work, date, "09:30", "10:00")
        secondary, secondary_move, _ = _day_move(work, date, "10:00", "10:30")
        full, full_move, _ = _day_move(work, date, "08:30", "10:31")
        expected = {"pre": 30, "impulse": impulse_minutes, "cash": 30, "secondary": 30, "full": 121}
        observed = {"pre": len(pre), "impulse": len(impulse), "cash": len(cash), "secondary": len(secondary), "full": len(full)}
        incomplete = [name for name in expected if observed[name] != expected[name]]
        if incomplete:
            exclusions.append({
                "session_date": date, "anchor_id": cluster["cluster_id"], "clock_new_york": "08:30",
                "window_name": ",".join(incomplete), "reason": "lifecycle_incomplete",
                "observed_minutes": json.dumps(observed, sort_keys=True),
                "expected_minutes": json.dumps(expected, sort_keys=True),
            })
            continue
        impulse_direction = _sign(impulse_move)
        cash_direction = _sign(cash_move)
        secondary_direction = _sign(secondary_move)
        full_direction = _sign(full_move)
        impulse_abs = abs(impulse_move)
        material = bool(
            pre_range > 0 and impulse_abs >= LIFECYCLE_THRESHOLDS["material_close_displacement_pre_range_fraction"] * pre_range
            and impulse_range >= LIFECYCLE_THRESHOLDS["material_impulse_range_pre_range_fraction"] * pre_range
            and impulse_direction != 0
        )
        directionless_expansion = bool(
            pre_range > 0 and impulse_range >= LIFECYCLE_THRESHOLDS["range_expansion_pre_range_fraction"] * pre_range
            and impulse_abs < LIFECYCLE_THRESHOLDS["directionless_close_impulse_range_fraction"] * impulse_range
        )
        impulse_close = float(impulse.iloc[-1]["mid_close"])
        open_0930 = float(cash.iloc[0]["mid_open"])
        retracement = max(0.0, impulse_direction * (impulse_close - open_0930) / impulse_abs) if impulse_abs > 0 else math.nan
        has_1000 = bool(day.get("has_1000_release", False))
        if directionless_expansion:
            label = "range_expansion_without_direction"
        elif not material:
            label = "unresolved_or_mixed"
        elif has_1000 and secondary_direction == -impulse_direction and abs(secondary_move) >= 0.50 * impulse_abs:
            label = "1000_secondary_reversal"
        elif has_1000 and secondary_direction == impulse_direction and abs(secondary_move) >= 0.50 * impulse_abs:
            label = "1000_secondary_continuation"
        elif cash_direction == impulse_direction and abs(cash_move) >= continuation_fraction * impulse_abs and full_direction == impulse_direction:
            label = "continuation_after_0930"
        elif (cash_direction == -impulse_direction and abs(cash_move) >= reversal_fraction * impulse_abs) or (
            full_direction == -impulse_direction and abs(full_move) >= reversal_fraction * impulse_abs
        ):
            label = "reversal_after_0930"
        elif LIFECYCLE_THRESHOLDS["partial_retracement_lower"] <= retracement <= LIFECYCLE_THRESHOLDS["partial_retracement_upper"] and full_direction == impulse_direction:
            label = "partial_retracement"
        else:
            label = "unresolved_or_mixed"
        max_spread = float(pd.to_numeric(full.get("maximum_spread", full["last_spread"]), errors="coerce").max())
        records.append({
            "session_date": date, "cluster_id_0830": cluster["cluster_id"],
            "importance": cluster.get("importance", "none"), "categories": cluster.get("categories", "[]"),
            "attribution_status": cluster.get("attribution_status", "unknown"),
            "timing_class": day.get("timing_class", "unclassified"), "news_day_class": day.get("news_day_class", "registered_news_day"),
            "has_1000_release": has_1000, "has_fomc_event": bool(day.get("has_fomc_event", False)),
            "impulse_minutes": impulse_minutes, "pre_event_range_price": pre_range,
            "impulse_move_price": impulse_move, "impulse_range_price": impulse_range,
            "impulse_range_vs_pre_event": impulse_range / pre_range if pre_range > 0 else math.nan,
            "impulse_direction": impulse_direction, "transition_move_price": transition_move,
            "retracement_to_0930_fraction": retracement, "cash_open_move_price": cash_move,
            "cash_open_direction": cash_direction, "secondary_1000_move_price": secondary_move,
            "secondary_1000_direction": secondary_direction, "full_lifecycle_move_price": full_move,
            "full_lifecycle_direction": full_direction, "material_impulse": material,
            "maximum_spread": max_spread, "spread_filter_pass": max_spread <= extreme_threshold,
            "lifecycle_label": label,
            "thresholds_exploratory": True,
        })
    return pd.DataFrame.from_records(records), pd.DataFrame.from_records(exclusions)


def _bootstrap_ci(values: Iterable[float], *, salt: str) -> tuple[float, float]:
    clean = np.asarray([float(value) for value in values if math.isfinite(float(value))], dtype=float)
    if len(clean) < 2:
        return math.nan, math.nan
    digest = int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(BOOTSTRAP_SEED + digest)
    sampled = rng.choice(clean, size=(BOOTSTRAP_RESAMPLES, len(clean)), replace=True).mean(axis=1)
    return float(np.quantile(sampled, 0.025)), float(np.quantile(sampled, 0.975))


def _stats(frame: pd.DataFrame, metric: str, *, salt: str) -> dict:
    values = pd.to_numeric(frame.get(metric, pd.Series(dtype=float)), errors="coerce").dropna()
    n = int(len(values))
    low, high = _bootstrap_ci(values, salt=salt)
    return {
        "sample_size": n,
        "sample_adequacy": "adequate" if n >= MINIMUM_GROUP_SAMPLE else "insufficient_sample",
        "mean": float(values.mean()) if n else math.nan,
        "median": float(values.median()) if n else math.nan,
        "standard_deviation": float(values.std(ddof=1)) if n > 1 else math.nan,
        "interquartile_range": float(values.quantile(0.75) - values.quantile(0.25)) if n else math.nan,
        "bootstrap_mean_ci_low": low,
        "bootstrap_mean_ci_high": high,
        "positive_hit_rate": float(values.gt(0).mean()) if n else math.nan,
        "cost_survival_rate": float(frame.loc[values.index, "survives_observed_spread_cost"].astype(bool).mean())
        if n and "survives_observed_spread_cost" in frame else math.nan,
        "median_spread_floor_survival_rate": float(frame.loc[values.index, "survives_median_spread_floor"].astype(bool).mean())
        if n and "survives_median_spread_floor" in frame else math.nan,
    }


def build_window_statistics(features: pd.DataFrame) -> pd.DataFrame:
    complete = features[features["coverage_status"].eq("complete")].copy()
    records: list[dict] = []
    dimensions = ["news_day_class", "timing_class", "importance", "clock_new_york"]
    complete["calendar_quarter"] = pd.PeriodIndex(pd.to_datetime(complete["session_date"]), freq="Q").astype(str)
    for filter_variant, source in (("raw", complete), ("spread_filtered", complete[complete["spread_filter_pass"]])):
        for dimension in dimensions:
            for (group_value, clock, window), group in source.groupby([dimension, "clock_new_york", "window_name"], dropna=False):
                for metric in ("absolute_return_bps", "cumulative_return_bps", "range_bps", "realized_volatility_bps"):
                    records.append({
                        "group_dimension": dimension, "group_value": group_value, "clock_new_york": clock,
                        "window_name": window, "filter_variant": filter_variant, "metric": metric,
                        **_stats(group, metric, salt=f"window|{filter_variant}|{dimension}|{group_value}|{clock}|{window}|{metric}"),
                    })
        for (quarter, clock, window), group in source.groupby(["calendar_quarter", "clock_new_york", "window_name"], dropna=False):
            records.append({
                "group_dimension": "calendar_quarter", "group_value": quarter, "clock_new_york": clock,
                "window_name": window, "filter_variant": filter_variant, "metric": "absolute_return_bps",
                **_stats(group, "absolute_return_bps", salt=f"quarter|{filter_variant}|{quarter}|{clock}|{window}"),
            })
    return pd.DataFrame.from_records(records)


def _attributable_categories(row: pd.Series) -> list[str]:
    if row.get("anchor_kind") != "registered_event" or row.get("attribution_status") in {"ambiguous_cluster", "conflicting_cluster"}:
        return []
    return _json_list(row.get("categories"))


def build_category_statistics(features: pd.DataFrame) -> pd.DataFrame:
    complete = features[features["coverage_status"].eq("complete") & features["anchor_kind"].eq("registered_event")].copy()
    complete["event_category"] = complete.apply(_attributable_categories, axis=1)
    complete = complete.explode("event_category")
    complete = complete[complete["event_category"].notna() & complete["event_category"].ne("")]
    records: list[dict] = []
    for filter_variant, source in (("raw", complete), ("spread_filtered", complete[complete["spread_filter_pass"]])):
        for (category, clock, window), group in source.groupby(["event_category", "clock_new_york", "window_name"]):
            records.append({
                "event_category": category, "clock_new_york": clock, "window_name": window,
                "filter_variant": filter_variant, "metric": "absolute_return_bps",
                **_stats(group, "absolute_return_bps", salt=f"category|{filter_variant}|{category}|{clock}|{window}"),
            })
    return pd.DataFrame.from_records(records)


def build_cluster_statistics(features: pd.DataFrame) -> pd.DataFrame:
    complete = features[features["coverage_status"].eq("complete") & features["anchor_kind"].eq("registered_event")]
    records: list[dict] = []
    for filter_variant, source in (("raw", complete), ("spread_filtered", complete[complete["spread_filter_pass"]])):
        for (attribution, clock, window), group in source.groupby(["attribution_status", "clock_new_york", "window_name"]):
            records.append({
                "attribution_status": attribution, "clock_new_york": clock, "window_name": window,
                "filter_variant": filter_variant, "metric": "absolute_return_bps",
                **_stats(group, "absolute_return_bps", salt=f"cluster|{filter_variant}|{attribution}|{clock}|{window}"),
            })
    return pd.DataFrame.from_records(records)


def _cliffs_delta(left: np.ndarray, right: np.ndarray) -> float:
    if not len(left) or not len(right):
        return math.nan
    return float((np.greater.outer(left, right).sum() - np.less.outer(left, right).sum()) / (len(left) * len(right)))


def _bootstrap_difference(left: np.ndarray, right: np.ndarray, salt: str) -> tuple[float, float]:
    if len(left) < 2 or len(right) < 2:
        return math.nan, math.nan
    digest = int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8], 16)
    rng = np.random.default_rng(BOOTSTRAP_SEED + digest)
    left_means = rng.choice(left, size=(BOOTSTRAP_RESAMPLES, len(left)), replace=True).mean(axis=1)
    right_means = rng.choice(right, size=(BOOTSTRAP_RESAMPLES, len(right)), replace=True).mean(axis=1)
    difference = left_means - right_means
    return float(np.quantile(difference, 0.025)), float(np.quantile(difference, 0.975))


def build_news_vs_nonnews(features: pd.DataFrame) -> pd.DataFrame:
    complete = features[features["coverage_status"].eq("complete")].copy()
    complete["calendar_quarter"] = pd.PeriodIndex(
        pd.to_datetime(complete["session_date"]), freq="Q"
    ).astype(str)
    records: list[dict] = []

    def add_comparison(
        left: np.ndarray,
        right: np.ndarray,
        *,
        comparison_type: str,
        left_group: str,
        right_group: str,
        window: str,
        filter_variant: str,
        period: str = "overall",
        paired: bool = False,
    ) -> None:
        if paired and len(left) == len(right) and len(left) >= 2:
            difference = left - right
            low, high = _bootstrap_ci(
                difference, salt=f"paired|{comparison_type}|{filter_variant}|{period}"
            )
            mean_difference = float(np.mean(difference))
        else:
            low, high = _bootstrap_difference(
                left, right, f"comparison|{comparison_type}|{filter_variant}|{period}"
            )
            mean_difference = (
                float(np.mean(left) - np.mean(right))
                if len(left) and len(right) else math.nan
            )
        records.append({
            "comparison_type": comparison_type,
            "left_group": left_group,
            "right_group": right_group,
            "period": period,
            "window_name": window,
            "filter_variant": filter_variant,
            "news_sample_size": len(left),
            "nonnews_sample_size": len(right),
            "sample_adequacy": (
                "adequate" if min(len(left), len(right)) >= MINIMUM_GROUP_SAMPLE
                else "insufficient_sample"
            ),
            "news_mean_absolute_return_bps": float(np.mean(left)) if len(left) else math.nan,
            "news_median_absolute_return_bps": float(np.median(left)) if len(left) else math.nan,
            "nonnews_mean_absolute_return_bps": float(np.mean(right)) if len(right) else math.nan,
            "nonnews_median_absolute_return_bps": float(np.median(right)) if len(right) else math.nan,
            "mean_difference_bps": mean_difference,
            "bootstrap_difference_ci_low": low,
            "bootstrap_difference_ci_high": high,
            "cliffs_delta_effect_size": _cliffs_delta(left, right),
            "news_exceeds_nonnews_median_hit_rate": (
                float(np.mean(left > np.median(right)))
                if len(left) and len(right) else math.nan
            ),
        })

    for filter_variant, source in (
        ("raw", complete),
        ("spread_filtered", complete[complete["spread_filter_pass"]]),
    ):
        base_0830 = source[source["clock_new_york"].eq("08:30")]
        periods: list[tuple[str, pd.DataFrame]] = [("overall", base_0830)]
        periods.extend((str(period), group) for period, group in base_0830.groupby("calendar_quarter"))
        for period, period_source in periods:
            for window in sorted(period_source["window_name"].unique()):
                part = period_source[period_source["window_name"].eq(window)]
                news = pd.to_numeric(
                    part.loc[part["anchor_kind"].eq("registered_event"), "absolute_return_bps"],
                    errors="coerce",
                ).dropna().to_numpy()
                nonnews = pd.to_numeric(
                    part.loc[part["anchor_kind"].eq("qualified_non_news_0830"), "absolute_return_bps"],
                    errors="coerce",
                ).dropna().to_numpy()
                add_comparison(
                    news,
                    nonnews,
                    comparison_type="0830_registered_news_vs_qualified_nonnews",
                    left_group="registered_0830_news",
                    right_group="qualified_nonnews_0830",
                    window=window,
                    filter_variant=filter_variant,
                    period=period,
                )

        cash = source[source["anchor_kind"].eq("session_cash_open")]
        immediate = cash[cash["window_name"].eq("relative_immediate_5m")]
        add_comparison(
            pd.to_numeric(
                immediate.loc[immediate["has_0830_release"].astype(bool), "absolute_return_bps"],
                errors="coerce",
            ).dropna().to_numpy(),
            pd.to_numeric(
                immediate.loc[
                    immediate["news_day_class"].eq("non_news_day_usable_sources_only"),
                    "absolute_return_bps",
                ],
                errors="coerce",
            ).dropna().to_numpy(),
            comparison_type="0930_on_0830_news_days_vs_qualified_nonnews",
            left_group="0930_on_0830_news_days",
            right_group="0930_on_qualified_nonnews",
            window="relative_immediate_5m",
            filter_variant=filter_variant,
        )
        cash_pivot = cash[
            cash["has_0830_release"].astype(bool)
            & cash["window_name"].isin({"relative_pre_5m", "relative_immediate_5m"})
        ].pivot_table(
            index="anchor_id", columns="window_name", values="absolute_return_bps", aggfunc="first"
        ).dropna()
        add_comparison(
            cash_pivot.get("relative_immediate_5m", pd.Series(dtype=float)).to_numpy(),
            cash_pivot.get("relative_pre_5m", pd.Series(dtype=float)).to_numpy(),
            comparison_type="paired_0930_immediate_vs_prior5_on_0830_days",
            left_group="0930_immediate_5m",
            right_group="0925_0929_prior_5m",
            window="relative_immediate_5m_minus_pre_5m",
            filter_variant=filter_variant,
            paired=True,
        )

        at_1000 = source[
            source["clock_new_york"].eq("10:00")
            & source["window_name"].eq("relative_immediate_5m")
        ]
        add_comparison(
            pd.to_numeric(
                at_1000.loc[at_1000["anchor_kind"].eq("registered_event"), "absolute_return_bps"],
                errors="coerce",
            ).dropna().to_numpy(),
            pd.to_numeric(
                at_1000.loc[at_1000["anchor_kind"].eq("qualified_non_news_1000"), "absolute_return_bps"],
                errors="coerce",
            ).dropna().to_numpy(),
            comparison_type="1000_scheduled_release_vs_qualified_nonnews",
            left_group="registered_1000_release",
            right_group="qualified_nonnews_1000",
            window="relative_immediate_5m",
            filter_variant=filter_variant,
        )
        event_1000 = source[
            source["anchor_kind"].eq("registered_event")
            & source["clock_new_york"].eq("10:00")
            & source["window_name"].isin({"relative_pre_5m", "relative_immediate_5m"})
        ].pivot_table(
            index="anchor_id", columns="window_name", values="absolute_return_bps", aggfunc="first"
        ).dropna()
        add_comparison(
            event_1000.get("relative_immediate_5m", pd.Series(dtype=float)).to_numpy(),
            event_1000.get("relative_pre_5m", pd.Series(dtype=float)).to_numpy(),
            comparison_type="paired_1000_immediate_vs_prior5_on_release_days",
            left_group="1000_immediate_5m",
            right_group="0955_0959_prior_5m",
            window="relative_immediate_5m_minus_pre_5m",
            filter_variant=filter_variant,
            paired=True,
        )

        for clock in ("14:00", "14:30"):
            fomc = source[
                source["anchor_kind"].eq("registered_event")
                & source["clock_new_york"].eq(clock)
                & source["window_name"].isin({"relative_pre_5m", "relative_immediate_5m"})
            ].pivot_table(
                index="anchor_id", columns="window_name", values="absolute_return_bps", aggfunc="first"
            ).dropna()
            add_comparison(
                fomc.get("relative_immediate_5m", pd.Series(dtype=float)).to_numpy(),
                fomc.get("relative_pre_5m", pd.Series(dtype=float)).to_numpy(),
                comparison_type=f"paired_{clock.replace(':', '')}_fomc_immediate_vs_prior5",
                left_group=f"{clock}_immediate_5m",
                right_group=f"{clock}_prior_5m",
                window="relative_immediate_5m_minus_pre_5m",
                filter_variant=filter_variant,
                paired=True,
            )
    return pd.DataFrame.from_records(records)


def build_spread_analysis(features: pd.DataFrame) -> pd.DataFrame:
    complete = features[features["coverage_status"].eq("complete")]
    records: list[dict] = []
    for (kind, clock, window), group in complete.groupby(["anchor_kind", "clock_new_york", "window_name"]):
        spreads = pd.to_numeric(group["median_spread"], errors="coerce").dropna()
        normalization = pd.to_numeric(group["spread_normalization_minutes"], errors="coerce").dropna()
        records.append({
            "anchor_kind": kind, "clock_new_york": clock, "window_name": window,
            "sample_size": len(group), "median_spread_mean": float(spreads.mean()) if len(spreads) else math.nan,
            "median_spread_median": float(spreads.median()) if len(spreads) else math.nan,
            "median_spread_p95": float(spreads.quantile(0.95)) if len(spreads) else math.nan,
            "maximum_spread": float(pd.to_numeric(group["maximum_spread"], errors="coerce").max()),
            "extreme_spread_window_rate": float(group["spread_filter_pass"].astype(bool).eq(False).mean()),
            "spread_normalization_minutes_median": float(normalization.median()) if len(normalization) else math.nan,
            "gross_move_mean_price": float(pd.to_numeric(group["gross_hindsight_direction_move_price"], errors="coerce").mean()),
            "executable_move_mean_price": float(pd.to_numeric(group["executable_hindsight_direction_move_price"], errors="coerce").mean()),
            "cost_survival_rate": float(group["survives_observed_spread_cost"].astype(bool).mean()),
            "median_spread_floor_survival_rate": float(group["survives_median_spread_floor"].astype(bool).mean()),
            "execution_scope": "observed_bid_ask_and_global_median_spread_floor_no_slippage_or_fill_model",
        })
    return pd.DataFrame.from_records(records)


def _sensitivity_summary(frame: pd.DataFrame, sensitivity: str, parameters: dict) -> dict:
    if frame.empty:
        return {"sensitivity_type": sensitivity, "parameters": json.dumps(parameters, sort_keys=True), "sample_size": 0,
                "continuation_rate": math.nan, "reversal_rate": math.nan, "median_impulse_range_vs_pre_event": math.nan}
    labels = frame["lifecycle_label"].astype(str)
    continuation = labels.isin({"continuation_after_0930", "1000_secondary_continuation"})
    reversal = labels.isin({"reversal_after_0930", "1000_secondary_reversal"})
    return {
        "sensitivity_type": sensitivity, "parameters": json.dumps(parameters, sort_keys=True),
        "sample_size": len(frame), "continuation_rate": float(continuation.mean()),
        "reversal_rate": float(reversal.mean()),
        "median_impulse_range_vs_pre_event": float(pd.to_numeric(frame["impulse_range_vs_pre_event"], errors="coerce").median()),
        "spread_filter_pass_rate": float(frame["spread_filter_pass"].astype(bool).mean()),
    }


def _is_dst_mismatch_week(date: str) -> bool:
    at = pd.Timestamp(f"{date} 12:00", tz="America/New_York")
    helsinki = at.tz_convert("Europe/Helsinki")
    ny_offset = at.utcoffset().total_seconds() / 3600
    helsinki_offset = helsinki.utcoffset().total_seconds() / 3600
    return not math.isclose(helsinki_offset - ny_offset, 7.0)


def build_sensitivity_analysis(
    work: pd.DataFrame, clusters: pd.DataFrame, days: pd.DataFrame, lifecycle: pd.DataFrame,
    extreme_threshold: float,
) -> pd.DataFrame:
    records: list[dict] = []
    for minutes in (1, 3, 5, 15, 30):
        variant, _ = classify_lifecycle(work, clusters, days, extreme_threshold, impulse_minutes=minutes)
        records.append(_sensitivity_summary(variant, "impulse_window_minutes", {"minutes": minutes}))
    for continuation in (0.25, 0.50, 0.75):
        for reversal in (0.25, 0.50, 0.75):
            variant, _ = classify_lifecycle(
                work, clusters, days, extreme_threshold, continuation_fraction=continuation, reversal_fraction=reversal
            )
            records.append(_sensitivity_summary(variant, "continuation_reversal_thresholds", {
                "continuation_fraction": continuation, "reversal_fraction": reversal
            }))
    if lifecycle.empty:
        return pd.DataFrame.from_records(records)
    scenarios = {
        "all_eligible_raw": pd.Series(True, index=lifecycle.index),
        "exclude_ambiguous_clusters": ~lifecycle["attribution_status"].isin({"ambiguous_cluster", "conflicting_cluster"}),
        "exclude_extreme_spread": lifecycle["spread_filter_pass"].astype(bool),
        "0830_and_1000_only": lifecycle["has_1000_release"].astype(bool),
        "0830_without_1000": ~lifecycle["has_1000_release"].astype(bool),
        "exclude_fomc_days": ~lifecycle["has_fomc_event"].astype(bool),
        "dst_transition_mismatch_weeks_only": lifecycle["session_date"].map(_is_dst_mismatch_week),
    }
    for name, mask in scenarios.items():
        records.append(_sensitivity_summary(lifecycle[mask], "sample_filter", {"scenario": name}))
    first_date, last_date = lifecycle["session_date"].min(), lifecycle["session_date"].max()
    records.append(_sensitivity_summary(
        lifecycle[~lifecycle["session_date"].isin({first_date, last_date})],
        "sample_filter", {"scenario": "exclude_first_and_last_eligible_lifecycle_dates"},
    ))
    return pd.DataFrame.from_records(records)


def _select_verdict(
    quality: dict, news_comparison: pd.DataFrame, lifecycle: pd.DataFrame, features: pd.DataFrame
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if quality.get("critical_violations"):
        return "BLOCKED_BY_DATA_QUALITY", list(quality["critical_violations"])
    key = news_comparison[
        news_comparison["comparison_type"].eq(
            "0830_registered_news_vs_qualified_nonnews"
        )
        & news_comparison["period"].eq("overall")
        & news_comparison["window_name"].eq("immediate_0830_0834")
    ]
    raw = key[key["filter_variant"].eq("raw")]
    filtered = key[key["filter_variant"].eq("spread_filtered")]
    robust_0830 = bool(
        not raw.empty and not filtered.empty
        and raw.iloc[0]["bootstrap_difference_ci_low"] > 0
        and filtered.iloc[0]["bootstrap_difference_ci_low"] > 0
        and min(raw.iloc[0]["news_sample_size"], raw.iloc[0]["nonnews_sample_size"]) >= MINIMUM_GROUP_SAMPLE
    )
    if not robust_0830:
        reasons.append("08:30 news-versus-qualified-non-news difference is not robust under both raw and spread-filtered samples")
        return "INSUFFICIENT_SIGNAL", reasons
    reasons.append("08:30 absolute movement exceeds qualified non-news in raw and spread-filtered bootstrap intervals")
    quarterly = news_comparison[
        news_comparison["comparison_type"].eq(
            "0830_registered_news_vs_qualified_nonnews"
        )
        & news_comparison["period"].ne("overall")
        & news_comparison["window_name"].eq("immediate_0830_0834")
        & news_comparison["filter_variant"].eq("spread_filtered")
        & news_comparison["sample_adequacy"].eq("adequate")
    ]
    stable_quarters = int(quarterly["bootstrap_difference_ci_low"].gt(0).sum())
    incremental_0930 = news_comparison[
        news_comparison["comparison_type"].eq(
            "paired_0930_immediate_vs_prior5_on_0830_days"
        )
    ]
    incremental_1000 = news_comparison[
        news_comparison["comparison_type"].eq(
            "1000_scheduled_release_vs_qualified_nonnews"
        )
    ]
    robust_0930 = bool(
        len(incremental_0930) == 2
        and incremental_0930["bootstrap_difference_ci_low"].gt(0).all()
    )
    robust_1000 = bool(
        len(incremental_1000) == 2
        and incremental_1000["bootstrap_difference_ci_low"].gt(0).all()
    )
    reasons.append(
        "09:30 immediate movement exceeds the prior five minutes in raw and spread-filtered 08:30-event samples"
        if robust_0930
        else "09:30 incremental effect is not robust in both raw and spread-filtered paired comparisons"
    )
    reasons.append(
        "10:00 scheduled-release movement exceeds qualified non-news controls in raw and spread-filtered samples"
        if robust_1000
        else "10:00 scheduled-release effect is not robust against qualified non-news controls"
    )
    if len(lifecycle) >= 60 and stable_quarters >= 3 and robust_0930 and robust_1000:
        return "PROCEED_TO_LIFECYCLE_RESEARCH", reasons
    reasons.append(
        "only one year of broker data is available and at least one incremental clock effect is not robust"
    )
    return "PROCEED_WITH_CAUTION", reasons


def _summary_markdown(results: dict, lifecycle: pd.DataFrame, news: pd.DataFrame, category: pd.DataFrame) -> str:
    counts = results["counts"]
    labels = lifecycle["lifecycle_label"].value_counts() if not lifecycle.empty else pd.Series(dtype=int)
    continuation = int(labels.get("continuation_after_0930", 0) + labels.get("1000_secondary_continuation", 0))
    reversal = int(labels.get("reversal_after_0930", 0) + labels.get("1000_secondary_reversal", 0))
    key = news[
        (news["comparison_type"] == "0830_registered_news_vs_qualified_nonnews")
        & (news["period"] == "overall")
        & (news["window_name"] == "immediate_0830_0834")
        & (news["filter_variant"] == "spread_filtered")
    ]
    key_text = "Unavailable"
    if not key.empty:
        row = key.iloc[0]
        key_text = (
            f"{row['mean_difference_bps']:.3f} bps mean difference; 95% bootstrap CI "
            f"[{row['bootstrap_difference_ci_low']:.3f}, {row['bootstrap_difference_ci_high']:.3f}]"
        )
    def comparison_text(comparison_type: str) -> str:
        selected = news[
            (news["comparison_type"] == comparison_type)
            & (news["period"] == "overall")
            & (news["filter_variant"] == "spread_filtered")
        ]
        if selected.empty:
            return "Unavailable"
        comparison = selected.iloc[0]
        return (
            f"{comparison['mean_difference_bps']:.3f} bps; 95% bootstrap CI "
            f"[{comparison['bootstrap_difference_ci_low']:.3f}, "
            f"{comparison['bootstrap_difference_ci_high']:.3f}]"
        )
    adequate_categories = category[
        (category["sample_adequacy"] == "adequate")
        & (category["filter_variant"] == "spread_filtered")
        & (category["window_name"].isin(["immediate_0830_0834", "relative_immediate_5m"]))
    ] if not category.empty else pd.DataFrame()
    category_text = ", ".join(sorted(adequate_categories["event_category"].unique())) or "None"
    adequate_0830 = adequate_categories[adequate_categories["clock_new_york"].eq("08:30")]
    category_0830_text = ", ".join(sorted(adequate_0830["event_category"].unique())) or "None"
    return "\n".join([
        "# Stage 1 Timing-Only XAUUSD Event Study",
        "",
        f"Research verdict: **{results['verdict']}**",
        "",
        "This is an unconditional timing and execution-friction study. It is not a strategy backtest, entry test, or production recommendation.",
        "",
        "## Sample",
        "",
        f"- Calendar trading days: {counts['calendar_trading_days']}",
        f"- Core-window eligible trading days: {counts['eligible_trading_days']}",
        f"- Event days: {counts['event_days']} calendar / {counts['eligible_event_days']} core-window eligible",
        f"- Qualified non-news days: {counts['qualified_non_news_days']} calendar / {counts['eligible_qualified_non_news_days']} core-window eligible",
        f"- Eligible 08:30 lifecycle days: {counts['eligible_0830_lifecycle_days']}",
        f"- Eligible registered 10:00 clusters: {counts['eligible_1000_clusters']}",
        f"- Excluded anchor-windows: {counts['excluded_anchor_windows']}",
        f"- Unique dates with at least one exclusion: {counts['excluded_dates']}",
        "",
        "## Main timing evidence",
        "",
        f"- Spread-filtered 08:30 news versus qualified non-news immediate movement: {key_text}.",
        "- Spread-filtered paired 09:30 immediate minus 09:25–09:29 movement on 08:30-event days: "
        f"{comparison_text('paired_0930_immediate_vs_prior5_on_0830_days')}.",
        "- Spread-filtered 09:30 movement on 08:30-event days versus qualified non-news days: "
        f"{comparison_text('0930_on_0830_news_days_vs_qualified_nonnews')}.",
        "- Spread-filtered scheduled 10:00 release movement versus qualified non-news 10:00 controls: "
        f"{comparison_text('1000_scheduled_release_vs_qualified_nonnews')}.",
        "- Spread-filtered paired 10:00 immediate minus 09:55–09:59 movement on release days: "
        f"{comparison_text('paired_1000_immediate_vs_prior5_on_release_days')}.",
        f"- Lifecycle continuation-family observations: {continuation}; reversal-family observations: {reversal}; denominator: {len(lifecycle)}.",
        f"- Event categories meeting the minimum sample in any immediate spread-filtered event window: {category_text}.",
        f"- 08:30 categories meeting the minimum attributable sample: {category_0830_text}.",
        *[f"- Verdict criterion: {reason}." for reason in results["verdict_reasons"]],
        "",
        "The 09:30 and 10:00 measurements are forward outcomes conditioned on earlier scheduled timing. They do not prove causality or an executable entry edge.",
        "",
        "## Deterministic lifecycle rules",
        "",
        "Rules use a fixed five-minute 08:30 impulse, the 08:00–08:29 range, fixed retracement fractions, direction agreement, and fixed post-09:30/10:00 displacement fractions. Thresholds were not estimated from returns and are explicitly marked exploratory.",
        "",
        "## Execution boundary",
        "",
        "Executable movement uses observed ask-at-start/bid-at-end for hindsight-long paths and bid-at-start/ask-at-end for hindsight-short paths. Direction is known only after the labeled window, so this is friction measurement—not a tradable signal. Slippage, queue position, latency, and fill probability are unavailable.",
        "",
        "## Leakage and overlap controls",
        "",
        "Calendar joins use release timestamps only. Actual, consensus, revisions, and surprises are unused. Qualified non-news dates come only from the complete official-source day register. Overlapping windows are intentional descriptive views and are never pooled as independent observations. Future bars appear only in explicitly labeled outcome fields.",
        "",
        "## Limitations",
        "",
        "- One broker feed and approximately one year of market history limit regime and year-over-year inference.",
        "- Official release timing is present, but actual/consensus/revision vintages are absent; surprise conditioning remains disabled.",
        "- Category claims are suppressed for ambiguous or conflicting simultaneous clusters.",
        "- Observed bid/ask bars cannot reproduce tick-ordering, slippage, or executable fills during fast releases.",
        "- Lifecycle labels are retrospective descriptive states and must never be used as contemporaneous features.",
        "",
    ])


def run_comprehensive_stage1(
    bars: pd.DataFrame,
    clusters: pd.DataFrame,
    output: str | Path,
    *,
    day_classification: pd.DataFrame | None,
    structural_quality: dict,
) -> dict:
    destination = Path(output)
    work = prepare_timing_bars(bars)
    days = _normalize_days(day_classification, clusters, work)
    spreads = pd.to_numeric(work.get("maximum_spread", work["last_spread"]), errors="coerce").dropna()
    extreme_threshold = float(spreads.quantile(0.99))
    anchors = _build_anchors(clusters, days)
    features, feature_exclusions = build_event_level_features(work, anchors, extreme_threshold)
    lifecycle, lifecycle_exclusions = classify_lifecycle(work, clusters, days, extreme_threshold)
    eligible_dates: set[str] = set()
    core_exclusions: list[dict] = []
    for date in days["date_et"].astype(str):
        observed, expected, status = _coverage(
            work,
            _clock_timestamp(date, "08:00"),
            _clock_timestamp(date, "10:31"),
        )
        if status == "complete":
            eligible_dates.add(date)
        else:
            core_exclusions.append({
                "session_date": date,
                "anchor_id": f"core-window-{date}",
                "clock_new_york": "08:00-10:30",
                "window_name": "core_0800_1030",
                "reason": f"core_window_{status}",
                "observed_minutes": observed,
                "expected_minutes": expected,
            })
    exclusions = pd.concat(
        [feature_exclusions, lifecycle_exclusions, pd.DataFrame.from_records(core_exclusions)],
        ignore_index=True,
        sort=False,
    )
    window_stats = build_window_statistics(features)
    category_stats = build_category_statistics(features)
    cluster_stats = build_cluster_statistics(features)
    news_nonnews = build_news_vs_nonnews(features)
    spread = build_spread_analysis(features)
    sensitivity = build_sensitivity_analysis(work, clusters, days, lifecycle, extreme_threshold)
    verdict, verdict_reasons = _select_verdict(structural_quality, news_nonnews, lifecycle, features)
    timing_highlights: dict[str, dict] = {}
    for comparison_type in (
        "0830_registered_news_vs_qualified_nonnews",
        "paired_0930_immediate_vs_prior5_on_0830_days",
        "0930_on_0830_news_days_vs_qualified_nonnews",
        "1000_scheduled_release_vs_qualified_nonnews",
        "paired_1000_immediate_vs_prior5_on_release_days",
    ):
        selected = news_nonnews[
            news_nonnews["comparison_type"].eq(comparison_type)
            & news_nonnews["period"].eq("overall")
            & news_nonnews["filter_variant"].eq("spread_filtered")
        ]
        if comparison_type == "0830_registered_news_vs_qualified_nonnews":
            selected = selected[selected["window_name"].eq("immediate_0830_0834")]
        if not selected.empty:
            row = selected.iloc[0]
            timing_highlights[comparison_type] = {
                "left_sample_size": int(row["news_sample_size"]),
                "right_sample_size": int(row["nonnews_sample_size"]),
                "mean_difference_bps": float(row["mean_difference_bps"]),
                "bootstrap_difference_ci_low": float(row["bootstrap_difference_ci_low"]),
                "bootstrap_difference_ci_high": float(row["bootstrap_difference_ci_high"]),
                "cliffs_delta_effect_size": float(row["cliffs_delta_effect_size"]),
            }
    eligible_1000 = features[
        features["anchor_kind"].eq("registered_event") & features["clock_new_york"].eq("10:00")
        & features["window_name"].eq("relative_immediate_5m") & features["coverage_status"].eq("complete")
    ]["anchor_id"].nunique()
    event_days = int(days["news_day_class"].ne("non_news_day_usable_sources_only").sum())
    qualified_nonnews = int(days["news_day_class"].eq("non_news_day_usable_sources_only").sum())
    eligible_days = days[days["date_et"].isin(eligible_dates)]
    eligible_event_days = int(
        eligible_days["news_day_class"].ne("non_news_day_usable_sources_only").sum()
    )
    eligible_nonnews = int(
        eligible_days["news_day_class"].eq("non_news_day_usable_sources_only").sum()
    )
    results = {
        "stage": 1,
        "study": "timing_only",
        "verdict": verdict,
        "verdict_reasons": verdict_reasons,
        "analysis_timezone": "America/New_York",
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "minimum_group_sample": MINIMUM_GROUP_SAMPLE,
        "extreme_spread_threshold_price": extreme_threshold,
        "lifecycle_thresholds": LIFECYCLE_THRESHOLDS,
        "surprise_analysis_enabled": False,
        "actual_consensus_revision_fields_used": False,
        "production_strategy_touched": False,
        "counts": {
            "calendar_trading_days": int(len(days)),
            "eligible_trading_days": int(len(eligible_days)),
            "event_days": event_days,
            "eligible_event_days": eligible_event_days,
            "qualified_non_news_days": qualified_nonnews,
            "eligible_qualified_non_news_days": eligible_nonnews,
            "registered_event_clusters": int(len(clusters)),
            "eligible_0830_lifecycle_days": int(len(lifecycle)),
            "eligible_1000_clusters": int(eligible_1000),
            "excluded_anchor_windows": int(len(exclusions)),
            "excluded_dates": int(exclusions["session_date"].nunique()),
        },
        "lifecycle_counts": lifecycle["lifecycle_label"].value_counts().sort_index().to_dict() if not lifecycle.empty else {},
        "spread_filtered_timing_highlights": timing_highlights,
        "quality_status": structural_quality.get("status"),
        "methodology": {
            "non_news_rule": "news_day_class=non_news_day_usable_sources_only and calendar completeness contains complete",
            "spread_filter": "exclude any observation window whose maximum minute spread exceeds the full-sample 99th percentile; raw results retained",
            "category_attribution": "ambiguous/conflicting clusters excluded from event-category summaries",
            "window_overlap": "intentional descriptive overlap; never counted as independent pooled observations",
            "execution": "observed bid/ask boundary quotes; no slippage or fill model",
        },
    }
    quality_report = {
        "status": "blocked" if verdict == "BLOCKED_BY_DATA_QUALITY" else "passed_with_documented_exclusions",
        "structural_quality": structural_quality,
        "calendar_trading_days": len(days),
        "eligible_core_window_trading_days": len(eligible_days),
        "anchor_count": len(anchors),
        "complete_feature_rows": int(features["coverage_status"].eq("complete").sum()),
        "incomplete_feature_rows": int(features["coverage_status"].ne("complete").sum()),
        "eligible_lifecycle_days": len(lifecycle),
        "exclusion_count": len(exclusions),
        "extreme_spread_threshold_price": extreme_threshold,
        "raw_and_filtered_results_present": True,
        "normalized_inputs_modified": False,
        "surprise_fields_used": False,
        "warnings": [
            "zero-spread minute states retained in raw results; median-spread-floor sensitivity reported",
            "global missing-minute percentage includes holidays and routine broker gaps; event-window coverage is checked separately",
            "two records fall inside the simplified closure model and remain disclosed",
        ],
    }
    destination.mkdir(parents=True, exist_ok=True)
    features.to_csv(destination / "event_level_features.csv", index=False)
    lifecycle.to_csv(destination / "daily_lifecycle_classification.csv", index=False)
    window_stats.to_csv(destination / "window_statistics.csv", index=False)
    category_stats.to_csv(destination / "category_statistics.csv", index=False)
    cluster_stats.to_csv(destination / "cluster_statistics.csv", index=False)
    news_nonnews.to_csv(destination / "news_vs_nonnews.csv", index=False)
    spread.to_csv(destination / "spread_analysis.csv", index=False)
    sensitivity.to_csv(destination / "sensitivity_analysis.csv", index=False)
    exclusions.to_csv(destination / "data_exclusions.csv", index=False)
    (destination / "stage1_results.json").write_text(json.dumps(results, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (destination / "stage1_quality_report.json").write_text(json.dumps(quality_report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (destination / "stage1_summary.md").write_text(_summary_markdown(results, lifecycle, news_nonnews, category_stats), encoding="utf-8")
    return results
