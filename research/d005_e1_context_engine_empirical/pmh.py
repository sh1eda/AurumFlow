"""Independent research-only PMH/PML inventory for D005_E1."""

from __future__ import annotations

import pandas as pd

from research.context_engine.config import ContextEngineConfig, local_bounds
from research.context_engine.features import (
    detect_liquidity_sweeps,
    premarket_levels,
)

from .config import EmpiricalStudyConfig


def build_pmh_pml_inventory(
    one_minute: pd.DataFrame,
    *,
    study_config: EmpiricalStudyConfig,
    d005_config: ContextEngineConfig,
) -> pd.DataFrame:
    """Measure PMH/PML on every weekday without granting directional power."""

    records: list[dict[str, object]] = []
    for session_date in pd.date_range(
        study_config.start_date, study_config.end_date, freq="D"
    ).date:
        if session_date.weekday() >= 5:
            continue
        interval_start, _ = local_bounds(
            session_date,
            d005_config.premarket.start,
            d005_config.premarket.start,
            study_config.timezone,
        )
        _, observation_end = local_bounds(
            session_date, "08:30", "09:00", study_config.timezone
        )
        day_bars = one_minute.loc[
            (one_minute.index >= interval_start)
            & (one_minute.index < observation_end)
            & pd.to_datetime(
                one_minute["available_at"],
                utc=True,
            ).le(observation_end)
        ]
        levels, metadata = premarket_levels(
            day_bars,
            session_date=session_date,
            config=d005_config.premarket,
        )
        sweeps = detect_liquidity_sweeps(
            levels,
            day_bars,
            timeframe="1min",
            evaluation_at=observation_end,
            penetration=d005_config.premarket.sweep_penetration,
            require_reclaim=d005_config.premarket.require_body_close_reclaim,
        )
        sweeps_by_level = {
            str(event.parameters.get("level_event_id")): event
            for event in sweeps
            if pd.Timestamp(event.available_at) <= observation_end
        }
        for level in levels:
            sweep = sweeps_by_level.get(level.event_id)
            records.append(
                {
                    "session_date": session_date.isoformat(),
                    "level_event_id": level.event_id,
                    "taxonomy": level.taxonomy,
                    "direction": int(level.direction),
                    "level": level.level,
                    "level_available_at": level.available_at,
                    "swept": sweep is not None,
                    "sweep_event_id": (
                        sweep.event_id if sweep is not None else None
                    ),
                    "sweep_at": (
                        sweep.available_at if sweep is not None else None
                    ),
                    "premarket_complete": bool(metadata["complete"]),
                    "premarket_coverage": float(metadata["coverage"]),
                    "interval_start_utc": metadata["left_utc"],
                    "interval_end_utc": metadata["right_utc"],
                    "independent_bias": False,
                    "research_only": True,
                }
            )
        if not levels:
            records.append(
                {
                    "session_date": session_date.isoformat(),
                    "level_event_id": None,
                    "taxonomy": "premarket_unavailable",
                    "direction": 0,
                    "level": None,
                    "level_available_at": metadata["right_utc"],
                    "swept": False,
                    "sweep_event_id": None,
                    "sweep_at": None,
                    "premarket_complete": bool(metadata["complete"]),
                    "premarket_coverage": float(metadata["coverage"]),
                    "interval_start_utc": metadata["left_utc"],
                    "interval_end_utc": metadata["right_utc"],
                    "independent_bias": False,
                    "research_only": True,
                }
            )
    return pd.DataFrame.from_records(records)
