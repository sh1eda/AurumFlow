"""Causal fixed-clock and event-driven schedules for D005_E1."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import json
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from research.context_engine.bars import TIMEFRAME_MINUTES
from research.context_engine.config import ContextEngineConfig, local_bounds
from research.context_engine.features import confirmed_swings

from .config import EmpiricalStudyConfig, MappingVariant


def fixed_observation_schedule(
    one_minute: pd.DataFrame,
    config: EmpiricalStudyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return data-qualified fixed observations and explicit exclusions."""

    available = pd.DatetimeIndex(one_minute.index) + pd.Timedelta(minutes=1)
    available_ns = available.as_unit("ns").asi8
    rows: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    for session_date in pd.date_range(
        config.start_date, config.end_date, freq="D"
    ).date:
        if session_date.weekday() >= 5:
            continue
        for clock in config.fixed_clocks:
            evaluation, _ = local_bounds(
                session_date, clock, clock, config.timezone
            )
            position = int(
                np.searchsorted(available_ns, evaluation.value, side="right")
            ) - 1
            latest = (
                pd.Timestamp(available[position]) if position >= 0 else pd.NaT
            )
            qualified = bool(
                position >= 0
                and latest <= evaluation
                and evaluation - latest <= pd.Timedelta(minutes=5)
            )
            record = {
                "evaluation_at": evaluation,
                "session_date": session_date.isoformat(),
                "observation_clock": clock,
                "mode": "fixed_clock",
            }
            if qualified:
                rows.append(record)
            else:
                exclusions.append(
                    {
                        **record,
                        "reason": "no_completed_one_minute_bar_within_5m",
                        "latest_available_at": latest,
                    }
                )
    return (
        pd.DataFrame.from_records(rows),
        pd.DataFrame.from_records(exclusions),
    )


def build_data_quality_periods(
    one_minute: pd.DataFrame,
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    """Describe observed minutes, gaps, premarket coverage, and DST by date."""

    local = one_minute.index.tz_convert(config.timezone)
    work = pd.DataFrame(
        {
            "session_date": local.date,
            "stamp_ns": local.as_unit("ns").asi8,
            "premarket": (
                (local.hour * 60 + local.minute) < 8 * 60 + 30
            ),
        }
    )
    work["gap_minutes"] = (
        work.groupby("session_date", sort=False)["stamp_ns"].diff()
        / 60_000_000_000
    )
    observed = (
        work.groupby("session_date", sort=False)
        .agg(
            observed_one_minute_rows=("stamp_ns", "size"),
            maximum_intraday_gap_minutes=("gap_minutes", "max"),
            premarket_observed_minutes=("premarket", "sum"),
        )
        .to_dict("index")
    )
    records: list[dict[str, object]] = []
    previous_offset: float | None = None
    for session_date in pd.date_range(
        config.start_date, config.end_date, freq="D"
    ).date:
        day = observed.get(session_date, {})
        count = int(day.get("observed_one_minute_rows", 0))
        maximum_gap = float(
            day.get("maximum_intraday_gap_minutes", np.nan)
        )
        premarket_count = int(day.get("premarket_observed_minutes", 0))
        premarket_coverage = premarket_count / 510.0
        noon = pd.Timestamp(
            f"{session_date.isoformat()} 12:00",
            tz=config.timezone,
        )
        offset_hours = noon.utcoffset().total_seconds() / 3600.0
        dst_transition = (
            previous_offset is not None and offset_hours != previous_offset
        )
        previous_offset = offset_hours
        records.append(
            {
                "session_date": session_date.isoformat(),
                "weekday": session_date.weekday(),
                "observed_one_minute_rows": count,
                "maximum_intraday_gap_minutes": maximum_gap,
                "premarket_observed_minutes": premarket_count,
                "premarket_coverage": premarket_coverage,
                "premarket_complete": premarket_coverage >= 0.95,
                "utc_offset_hours_at_noon": offset_hours,
                "dst": bool(noon.dst() and noon.dst().total_seconds()),
                "dst_transition": dst_transition,
                "missing_full_date": count == 0,
                "weekend": session_date.weekday() >= 5,
            }
        )
    return pd.DataFrame.from_records(records)


def _parameters(record: Mapping[str, object]) -> dict[str, object]:
    value = record.get("parameters", {})
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _add_trigger(
    triggers: dict[pd.Timestamp, set[str]],
    value: object,
    trigger_type: str,
    *,
    left: pd.Timestamp,
    right: pd.Timestamp,
) -> None:
    if value is None or pd.isna(value):
        return
    stamp = pd.Timestamp(value)
    if stamp.tz is None:
        return
    stamp = stamp.tz_convert("UTC")
    if left <= stamp <= right:
        triggers[stamp].add(trigger_type)


def event_schedule_from_inventory(
    *,
    variant: MappingVariant,
    event_records: Iterable[Mapping[str, object]],
    transition_records: Iterable[Mapping[str, object]],
    timeframes: Mapping[str, pd.DataFrame],
    d005_config: ContextEngineConfig,
    study_config: EmpiricalStudyConfig,
    pmh_sweep_times: Iterable[pd.Timestamp] = (),
) -> pd.DataFrame:
    """Build exact event timestamps from the fixed-pass causal inventory."""

    mapping = d005_config.mapping(variant.d005_mapping)
    left, _ = local_bounds(
        study_config.start_date, "00:00", "00:00", study_config.timezone
    )
    _, right = local_bounds(
        study_config.end_date, "00:00", "23:59", study_config.timezone
    )
    triggers: dict[pd.Timestamp, set[str]] = defaultdict(set)
    for record in event_records:
        event_type = str(record.get("event_type", ""))
        taxonomy = str(record.get("taxonomy", ""))
        if event_type in {
            "market_structure_shift",
            "displacement",
            "context_conflict",
        }:
            _add_trigger(
                triggers,
                record.get("available_at"),
                (
                    "mss_confirmation"
                    if event_type == "market_structure_shift"
                    else "displacement_confirmation"
                    if event_type == "displacement"
                    else "conflict"
                ),
                left=left,
                right=right,
            )
        if event_type == "liquidity_sweep":
            _add_trigger(
                triggers,
                record.get("available_at"),
                "named_liquidity_sweep",
                left=left,
                right=right,
            )
        if event_type in {"raw_fvg", "order_block"}:
            _add_trigger(
                triggers,
                record.get("interacted_at"),
                (
                    "htf_poi_interaction"
                    if str(record.get("timeframe")) == mapping.parent
                    else "refinement_array_interaction"
                ),
                left=left,
                right=right,
            )
            _add_trigger(
                triggers,
                record.get("invalidated_at"),
                "invalidation",
                left=left,
                right=right,
            )
        if record.get("confirmed_at") is not None:
            _add_trigger(
                triggers,
                record.get("confirmed_at"),
                "reaction_or_array_confirmation",
                left=left,
                right=right,
            )

    timeout = pd.Timedelta(
        minutes=TIMEFRAME_MINUTES[mapping.reaction]
        * d005_config.mss.confirmation_timeout_bars
    )
    for record in transition_records:
        target = str(record.get("to_state", ""))
        _add_trigger(
            triggers,
            record.get("occurred_at"),
            (
                "reaction_confirmation"
                if target == "reaction_confirmed"
                else "conflict"
                if target == "conflict"
                else "invalidation"
                if target == "invalidated"
                else "parent_context_transition"
                if target == "provisional_context"
                else "state_transition"
            ),
            left=left,
            right=right,
        )
        if target in {"candidate_poi", "candidate_liquidity_event"}:
            occurred = pd.Timestamp(record["occurred_at"])
            _add_trigger(
                triggers,
                occurred + timeout,
                "candidate_timeout",
                left=left,
                right=right,
            )

    # A newly confirmed parent pivot can change the parent structure read.
    # Reaction pivots are not separately added: actual MSS confirmations are
    # already present in the event inventory and avoid redundant replay.
    parent_swings = confirmed_swings(
        timeframes[mapping.parent],
        width=d005_config.mss.pivot_width,
    )
    for value in (
        parent_swings["confirmation_at"]
        if not parent_swings.empty
        else ()
    ):
        _add_trigger(
            triggers,
            value,
            "parent_context_transition",
            left=left,
            right=right,
        )

    for value in pmh_sweep_times:
        _add_trigger(
            triggers,
            value,
            "pmh_pml_sweep",
            left=left,
            right=right,
        )

    rows = [
        {
            "evaluation_at": stamp,
            "session_date": stamp.tz_convert(
                study_config.timezone
            ).date().isoformat(),
            "mode": "event_driven",
            "observation_clock": None,
            "trigger_types": sorted(values),
            "mapping_variant": variant.name,
        }
        for stamp, values in sorted(triggers.items())
    ]
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return frame
    local_dates = pd.to_datetime(frame["evaluation_at"], utc=True).dt.tz_convert(
        study_config.timezone
    ).dt.date
    frame["_local_date"] = local_dates
    frame["_priority"] = frame["trigger_types"].map(
        lambda values: min(
            (
                0
                if item
                in {
                    "reaction_confirmation",
                    "conflict",
                    "invalidation",
                    "candidate_timeout",
                    "htf_poi_interaction",
                    "named_liquidity_sweep",
                }
                else 1
                for item in values
            ),
            default=1,
        )
    )
    uncapped_counts = frame.groupby("_local_date")[
        "evaluation_at"
    ].transform("size")
    frame["uncapped_date_trigger_count"] = uncapped_counts
    frame["date_schedule_truncated"] = uncapped_counts.gt(
        study_config.event_schedule_max_per_day_mapping
    )
    frame = (
        frame.sort_values(
            ["_local_date", "_priority", "evaluation_at"],
            kind="mergesort",
        )
        .groupby("_local_date", sort=True, group_keys=False)
        .head(study_config.event_schedule_max_per_day_mapping)
        .drop(columns=["_local_date", "_priority"])
        .sort_values("evaluation_at", kind="mergesort")
        .reset_index(drop=True)
    )
    selected_counts = frame.groupby("session_date")[
        "evaluation_at"
    ].transform("size")
    frame["selected_date_trigger_count"] = selected_counts
    frame["omitted_date_trigger_count"] = (
        frame["uncapped_date_trigger_count"]
        - frame["selected_date_trigger_count"]
    )
    return frame
