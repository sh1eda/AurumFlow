"""Frozen D006 price-path, geometry, control, and deduplication calculations."""

from __future__ import annotations

from hashlib import sha256
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .config import D006Config
from .models import CombinedStructuralRecord, Direction


OUTCOME_COLUMNS = (
    "event_id",
    "event_at",
    "direction",
    "reference_price",
    "endpoint_at",
    "endpoint_price",
    "direction_aligned_movement",
    "mfe",
    "mae",
    "mfe_mae_ratio",
    "zero_mae",
    "adverse_before_favorable",
    "endpoint_complete",
)


def structural_frame(records: Iterable[CombinedStructuralRecord]) -> pd.DataFrame:
    """Flatten the registered detector/lifecycle join without outcome fields."""

    rows: list[dict[str, object]] = []
    for combined in records:
        block, lifecycle = combined.block, combined.lifecycle
        terminal = next(
            (
                value
                for value in (
                    lifecycle.mitigation_timestamp,
                    lifecycle.invalidation_timestamp,
                    lifecycle.expiry_timestamp,
                )
                if value is not None
            ),
            None,
        )
        rows.append(
            {
                "block_id": block.block_id,
                "definition_name": block.definition_name,
                "direction": block.direction.value,
                "timeframe": block.timeframe,
                "source_bar_ids": list(block.source_bar_ids),
                "expansion_bar_id": block.expansion_bar_id,
                "creation_timestamp": block.creation_timestamp,
                "confirmation_timestamp": block.confirmation_timestamp,
                "causal_availability": block.causal_availability,
                "proximal": block.proximal,
                "midpoint": block.midpoint,
                "distal": block.distal,
                "range": block.range,
                "normalized_range": block.normalized_range,
                "session": block.session,
                "trading_date": block.trading_date,
                "lifecycle_state": lifecycle.status,
                "first_touch_timestamp": lifecycle.first_touch_timestamp,
                "mitigation_timestamp": lifecycle.mitigation_timestamp,
                "invalidation_timestamp": lifecycle.invalidation_timestamp,
                "expiry_timestamp": lifecycle.expiry_timestamp,
                "expiry_deadline": lifecycle.expiry_deadline,
                "terminal_timestamp": terminal,
                "touch_count": lifecycle.touch_count,
                "overlap_group_id": block.overlap_group_id,
                "parent_block_id": block.parent_block_id,
                "parent_active_at_availability": combined.parent_active_at_availability,
                "context_keys": list(block.context_keys),
                "preavailability_interaction": block.preavailability_interaction,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.sort_values(
        ["causal_availability", "definition_name", "creation_timestamp", "direction", "block_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def deduplicate_primary(structures: pd.DataFrame, config: D006Config = D006Config()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply the frozen overlap-group/direction/definition primary rule."""

    if structures.empty:
        return structures.copy(), structures.copy()
    eligible = structures.loc[
        structures["definition_name"].eq(config.primary_definition)
        & structures["first_touch_timestamp"].notna()
        & ~structures["preavailability_interaction"]
    ].copy()
    touch_year = pd.to_datetime(eligible["first_touch_timestamp"], utc=True).dt.year
    eligible = eligible.loc[touch_year.isin(config.validation_years)].copy()
    eligible["dedup_group"] = eligible["overlap_group_id"].fillna(eligible["block_id"])
    ordered = eligible.sort_values(
        ["dedup_group", "direction", "definition_name", "causal_availability", "range", "block_id"],
        kind="mergesort",
    )
    keep = ~ordered.duplicated(["dedup_group", "direction", "definition_name"], keep="first")
    selected = ordered.loc[keep].drop(columns="dedup_group").reset_index(drop=True)
    excluded = ordered.loc[~keep].drop(columns="dedup_group").reset_index(drop=True)
    return selected, excluded


def _available_view(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    result["available_at"] = pd.to_datetime(result["available_at"], utc=True)
    if result["available_at"].duplicated().any():
        raise ValueError("D006 outcomes require unique five-minute availability timestamps")
    return result.set_index("available_at", drop=False).sort_index(kind="mergesort")


def calculate_path_outcomes(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    event_id_column: str,
    event_at_column: str,
    direction_column: str = "direction",
    config: D006Config = D006Config(),
) -> pd.DataFrame:
    """Calculate the exact registered close reference and 60-minute path."""

    available = _available_view(bars)
    rows: list[dict[str, object]] = []
    for event in events.sort_values([event_at_column, event_id_column], kind="mergesort").itertuples(index=False):
        values = event._asdict()
        event_at = pd.Timestamp(values[event_at_column])
        if str(event_at.tz) != "UTC":
            raise ValueError("D006 event timestamps must be explicit UTC")
        direction = str(values[direction_column])
        if direction not in {Direction.BULLISH.value, Direction.BEARISH.value}:
            raise ValueError("D006 outcomes require a frozen direction")
        endpoint_at = event_at + pd.Timedelta(minutes=config.primary_horizon_minutes)
        complete = event_at in available.index and endpoint_at in available.index
        reference = float(available.at[event_at, "close"]) if event_at in available.index else np.nan
        endpoint = float(available.at[endpoint_at, "close"]) if endpoint_at in available.index else np.nan
        movement = np.nan
        mfe = mae = ratio = np.nan
        zero_mae = False
        adverse_before_favorable: bool | None = None
        if complete:
            sign = 1.0 if direction == Direction.BULLISH.value else -1.0
            movement = sign * (endpoint - reference)
            path = available.loc[(available.index > event_at) & (available.index <= endpoint_at)]
            if len(path) != config.primary_horizon_minutes // config.bar_minutes:
                complete = False
            else:
                favorable = (
                    path["high"].to_numpy(dtype=float) - reference
                    if sign > 0
                    else reference - path["low"].to_numpy(dtype=float)
                )
                adverse = (
                    reference - path["low"].to_numpy(dtype=float)
                    if sign > 0
                    else path["high"].to_numpy(dtype=float) - reference
                )
                mfe = float(max(0.0, np.max(favorable)))
                mae = float(max(0.0, np.max(adverse)))
                zero_mae = mae == 0.0
                ratio = np.nan if zero_mae else mfe / mae
                favorable_positions = np.flatnonzero(favorable > 0)
                adverse_positions = np.flatnonzero(adverse > 0)
                if len(favorable_positions) and len(adverse_positions):
                    adverse_before_favorable = bool(adverse_positions[0] < favorable_positions[0])
                elif len(adverse_positions):
                    adverse_before_favorable = True
                elif len(favorable_positions):
                    adverse_before_favorable = False
        rows.append(
            {
                "event_id": str(values[event_id_column]),
                "event_at": event_at,
                "direction": direction,
                "reference_price": reference,
                "endpoint_at": endpoint_at,
                "endpoint_price": endpoint,
                "direction_aligned_movement": movement,
                "mfe": mfe,
                "mae": mae,
                "mfe_mae_ratio": ratio,
                "zero_mae": bool(zero_mae),
                "adverse_before_favorable": adverse_before_favorable,
                "endpoint_complete": bool(complete),
            }
        )
    return pd.DataFrame(rows, columns=OUTCOME_COLUMNS)


def geometry_events(structures: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Construct proximal/midpoint/distal boundary touches with invalidation precedence."""

    available = _available_view(bars)
    rows: list[dict[str, object]] = []
    for block in structures.sort_values(["causal_availability", "block_id"], kind="mergesort").itertuples(index=False):
        availability = pd.Timestamp(block.causal_availability)
        expiry = pd.Timestamp(block.expiry_deadline)
        path = available.loc[(available.index > availability) & (available.index <= expiry)]
        for boundary in ("proximal", "midpoint", "distal"):
            price = float(getattr(block, boundary))
            touch_at: pd.Timestamp | None = None
            invalidated_at: pd.Timestamp | None = None
            for row in path.itertuples(index=False):
                row_at = pd.Timestamp(row.available_at)
                invalid = row.close < block.distal if block.direction == "bullish" else row.close > block.distal
                if invalid:
                    invalidated_at = row_at
                    break
                reached = row.low <= price if block.direction == "bullish" else row.high >= price
                if reached:
                    touch_at = row_at
                    break
            rows.append(
                {
                    "block_id": block.block_id,
                    "definition_name": block.definition_name,
                    "direction": block.direction,
                    "boundary": boundary,
                    "boundary_price": price,
                    "availability": availability,
                    "touch_at": touch_at,
                    "elapsed_minutes": (
                        (touch_at - availability).total_seconds() / 60.0
                        if touch_at is not None
                        else np.nan
                    ),
                    "invalidation_before_touch": invalidated_at is not None,
                    "invalidated_at": invalidated_at,
                    "expired_without_touch": touch_at is None and invalidated_at is None,
                    "lifecycle_minutes": (
                        ((touch_at or invalidated_at or expiry) - availability).total_seconds() / 60.0
                    ),
                }
            )
    return pd.DataFrame(rows)


def causal_volatility_buckets(bars: pd.DataFrame, config: D006Config = D006Config()) -> Mapping[str, str]:
    """Map each named date to the latest fully completed prior D005 daily range bucket."""

    work = bars.loc[bars["session"].ne("maintenance")].copy()
    grouped = work.groupby("trading_date", sort=True)
    daily = grouped.agg(high=("high", "max"), low=("low", "min"), bars=("close", "size"))
    daily["range"] = daily["high"] - daily["low"]
    daily["complete"] = daily["bars"].ge(int(np.ceil(276 * config.minimum_segment_completeness)))
    complete_ranges = daily["range"].where(daily["complete"])
    prior_range = complete_ranges.shift(1)
    prior_median = complete_ranges.shift(2).rolling(
        config.volatility_median_days, min_periods=config.volatility_median_days
    ).median()
    ratio = prior_range / prior_median
    lower, upper = config.volatility_bucket_boundaries
    result: dict[str, str] = {}
    for key, value in ratio.items():
        if pd.isna(value) or not np.isfinite(value):
            result[str(key)] = "unavailable"
        elif value < lower:
            result[str(key)] = "low"
        elif value <= upper:
            result[str(key)] = "normal"
        else:
            result[str(key)] = "high"
    return result


def _merged_forbidden_intervals(structures: pd.DataFrame, minutes: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    margin = pd.Timedelta(minutes=minutes)
    for row in structures.itertuples(index=False):
        availability = pd.Timestamp(row.causal_availability)
        terminal = pd.Timestamp(row.terminal_timestamp) if pd.notna(row.terminal_timestamp) else pd.Timestamp(row.expiry_deadline)
        intervals.append((availability, terminal))
        intervals.append((availability - margin, availability + margin))
        if pd.notna(row.first_touch_timestamp):
            touch = pd.Timestamp(row.first_touch_timestamp)
            intervals.append((touch - margin, touch + margin))
    merged: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def non_block_candidates(
    bars: pd.DataFrame,
    structures: pd.DataFrame,
    volatility: Mapping[str, str],
    config: D006Config = D006Config(),
) -> pd.DataFrame:
    """Build the primary/random-time candidate pool using only causal fields."""

    intervals = _merged_forbidden_intervals(structures, config.control_exclusion_minutes)
    candidates: list[dict[str, object]] = []
    available_set = set(pd.to_datetime(bars["available_at"], utc=True))
    interval_index = 0
    for row in bars.sort_values("available_at", kind="mergesort").itertuples(index=False):
        stamp = pd.Timestamp(row.available_at)
        if stamp.year not in config.validation_years:
            continue
        while interval_index < len(intervals) and intervals[interval_index][1] < stamp:
            interval_index += 1
        if interval_index < len(intervals) and intervals[interval_index][0] <= stamp <= intervals[interval_index][1]:
            continue
        endpoint = stamp + pd.Timedelta(minutes=config.primary_horizon_minutes)
        if endpoint not in available_set:
            continue
        candidates.append(
            {
                "candidate_id": "time-" + stamp.isoformat(),
                "event_at": stamp,
                "direction": "any",
                "year": stamp.year,
                "session": row.session,
                "trading_date": row.trading_date,
                "volatility_bucket": volatility.get(str(row.trading_date), "unavailable"),
            }
        )
    return pd.DataFrame(
        candidates,
        columns=(
            "candidate_id", "event_at", "direction", "year", "session",
            "trading_date", "volatility_bucket",
        ),
    )


def filter_non_rejection_candidates(
    candidates: pd.DataFrame,
    bars: pd.DataFrame,
    structures: pd.DataFrame,
    config: D006Config = D006Config(),
) -> pd.DataFrame:
    """Apply the frozen endpoint and rejection-block exclusions to event controls."""

    if candidates.empty:
        return candidates.copy()
    intervals = _merged_forbidden_intervals(structures, config.control_exclusion_minutes)
    available = set(pd.to_datetime(bars["available_at"], utc=True))
    ordered = candidates.copy()
    ordered["event_at"] = pd.to_datetime(ordered["event_at"], utc=True)
    ordered = ordered.sort_values(["event_at", "candidate_id"], kind="mergesort")
    keep: list[bool] = []
    interval_index = 0
    for stamp in ordered["event_at"]:
        while interval_index < len(intervals) and intervals[interval_index][1] < stamp:
            interval_index += 1
        forbidden = (
            interval_index < len(intervals)
            and intervals[interval_index][0] <= stamp <= intervals[interval_index][1]
        )
        endpoint = stamp + pd.Timedelta(minutes=config.primary_horizon_minutes)
        keep.append(not forbidden and endpoint in available)
    return ordered.loc[keep].reset_index(drop=True)


def match_controls(
    treatments: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    family: str,
    config: D006Config = D006Config(),
) -> pd.DataFrame:
    """Perform frozen exact-strata, no-replacement, lowest-hash matching."""

    required_treatment = {"event_id", "event_at", "direction", "year", "session", "trading_date", "volatility_bucket"}
    required_candidate = {"candidate_id", "event_at", "direction", "year", "session", "trading_date", "volatility_bucket"}
    if not required_treatment.issubset(treatments) or not required_candidate.issubset(candidates):
        raise ValueError("D006 matcher inputs are missing frozen strata")
    used: set[str] = set()
    rows: list[dict[str, object]] = []
    candidate_frame = candidates.copy()
    candidate_frame["event_at"] = pd.to_datetime(candidate_frame["event_at"], utc=True)
    grouped = {
        key: frame.sort_values(["event_at", "candidate_id"], kind="mergesort").reset_index(drop=True)
        for key, frame in candidate_frame.groupby(
            ["year", "session", "volatility_bucket"], sort=True, dropna=False
        )
    }
    for treatment in treatments.sort_values(["event_at", "event_id"], kind="mergesort").itertuples(index=False):
        lower = pd.Timestamp(treatment.event_at) - pd.Timedelta(days=config.control_window_days)
        upper = pd.Timestamp(treatment.event_at) + pd.Timedelta(days=config.control_window_days)
        stratum = grouped.get((treatment.year, treatment.session, treatment.volatility_bucket))
        if stratum is None:
            pool = candidate_frame.iloc[0:0]
        else:
            stamps = stratum["event_at"].array
            start = int(stamps.searchsorted(lower, side="left"))
            stop = int(stamps.searchsorted(upper, side="right"))
            pool = stratum.iloc[start:stop]
            pool = pool.loc[
                pool["trading_date"].ne(treatment.trading_date)
                & pool["direction"].isin(("any", treatment.direction))
                & ~pool["candidate_id"].isin(used)
            ]
        if pool.empty:
            rows.append(
                {
                    "family": family,
                    "treatment_id": treatment.event_id,
                    "treatment_at": treatment.event_at,
                    "direction": treatment.direction,
                    "control_id": None,
                    "control_at": pd.NaT,
                    "matched": False,
                }
            )
            continue
        scored = []
        for candidate in pool.itertuples(index=False):
            material = (
                f"{config.control_hash_seed}|{family}|{treatment.event_id}|"
                f"{pd.Timestamp(candidate.event_at).isoformat()}"
            )
            scored.append((sha256(material.encode("utf-8")).hexdigest(), candidate.candidate_id, candidate.event_at))
        _, control_id, control_at = min(scored)
        used.add(str(control_id))
        rows.append(
            {
                "family": family,
                "treatment_id": treatment.event_id,
                "treatment_at": treatment.event_at,
                "direction": treatment.direction,
                "control_id": str(control_id),
                "control_at": pd.Timestamp(control_at),
                "matched": True,
            }
        )
    return pd.DataFrame(
        rows,
        columns=(
            "family", "treatment_id", "treatment_at", "direction",
            "control_id", "control_at", "matched",
        ),
    )


__all__ = [
    "OUTCOME_COLUMNS",
    "calculate_path_outcomes",
    "causal_volatility_buckets",
    "deduplicate_primary",
    "geometry_events",
    "filter_non_rejection_candidates",
    "match_controls",
    "non_block_candidates",
    "structural_frame",
]
