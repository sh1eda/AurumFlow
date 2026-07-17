"""Group simultaneous releases without assigning unsupported single-event causality."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Mapping

import pandas as pd

from .economic_calendar_adapter import EconomicCalendarError


IMPORTANCE_RANK = {"none": 0, "minor": 1, "major": 2}


def _json_records(group: pd.DataFrame) -> str:
    fields = [
        "event_id",
        "event_name",
        "event_type",
        "importance",
        "raw_surprise",
        "standardized_surprise",
        "revision_surprise",
        "surprise_eligible",
        "expected_gold_direction",
    ]
    records: list[dict] = []
    for _, row in group.iterrows():
        record: dict[str, object] = {}
        for field in fields:
            value = row.get(field)
            if pd.isna(value):
                value = None
            elif hasattr(value, "item"):
                value = value.item()
            record[field] = value
        records.append(record)
    return json.dumps(records, sort_keys=True, separators=(",", ":"))


def _dominant_event(
    group: pd.DataFrame,
    dominance_priority: Mapping[str, int] | None,
) -> str:
    priority = dominance_priority or {}
    scored = group.assign(
        _importance=group["importance"].map(IMPORTANCE_RANK).fillna(0).astype(int),
        _domain=group.get("event_type", pd.Series("Other", index=group.index))
        .map(priority)
        .fillna(0)
        .astype(int),
    )
    scores = scored[["_importance", "_domain"]].apply(tuple, axis=1)
    maximum = scores.max()
    winners = scored[scores.map(lambda value: value == maximum)]
    if len(winners) == 1:
        return str(winners.iloc[0]["event_name"])
    return ""


def build_event_clusters(
    events: pd.DataFrame,
    *,
    dominance_priority: Mapping[str, int] | None = None,
) -> pd.DataFrame:
    required = {
        "event_id",
        "release_timestamp_utc",
        "release_timestamp_new_york",
        "event_name",
        "importance",
        "point_in_time_verified",
    }
    missing = sorted(required - set(events.columns))
    if missing:
        raise EconomicCalendarError(f"Canonical events are missing cluster columns: {missing}")
    records: list[dict] = []
    for timestamp, group in events.groupby("release_timestamp_utc", sort=True):
        group = group.copy().sort_values("event_id")
        local = pd.Timestamp(group["release_timestamp_new_york"].iloc[0])
        directions = pd.to_numeric(
            group.get("expected_gold_direction", pd.Series(index=group.index, dtype=float)),
            errors="coerce",
        ).dropna()
        nonzero_directions = set(directions[directions.ne(0)].map(lambda value: int(math.copysign(1, value))))
        directional_conflict = len(nonzero_directions) > 1
        collision = len(group) > 1
        bundle_values = group.get(
            "release_bundle_key", pd.Series("", index=group.index, dtype="object")
        ).fillna("").astype(str)
        single_bundle = bool(bundle_values.ne("").all() and bundle_values.nunique() == 1)
        if not collision:
            dominant = str(group.iloc[0]["event_name"])
            dominance_method = "single_event"
            attribution_status = "single_event"
        elif directional_conflict:
            dominant = ""
            dominance_method = "not_assigned_conflicting_surprises"
            attribution_status = "conflicting_cluster"
        elif single_bundle:
            dominant = ""
            dominance_method = "not_assigned_same_release_components"
            attribution_status = "clean_cluster"
        else:
            dominant = ""
            dominance_method = "not_assigned_independent_simultaneous_releases"
            attribution_status = "ambiguous_cluster"
        standardized = pd.to_numeric(
            group.get("standardized_surprise", pd.Series(index=group.index, dtype=float)),
            errors="coerce",
        )
        eligible = group.get("surprise_eligible", pd.Series(False, index=group.index)).astype(bool)
        all_surprises_available = bool(eligible.all() and standardized.notna().all())
        combined_surprise = float(standardized.sum()) if all_surprises_available else math.nan
        importance_rank = max(IMPORTANCE_RANK.get(str(value), 0) for value in group["importance"])
        importance = next(key for key, value in IMPORTANCE_RANK.items() if value == importance_rank)
        timing = local.strftime("%H:%M")
        digest = hashlib.sha256(
            (pd.Timestamp(timestamp).isoformat() + "|" + "|".join(group["event_id"].astype(str))).encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        records.append(
            {
                "cluster_id": digest,
                "cluster_timestamp": local,
                "release_timestamp_utc": pd.Timestamp(timestamp),
                "release_timestamp_new_york": local,
                "session_date": local.date().isoformat(),
                "release_clock_new_york": timing,
                "is_0830": timing == "08:30",
                "is_1000": timing == "10:00",
                "event_count": int(len(group)),
                "event_ids": json.dumps(group["event_id"].astype(str).tolist()),
                "event_names": json.dumps(group["event_name"].astype(str).tolist()),
                "categories": json.dumps(
                    sorted(group.get("category", pd.Series("", index=group.index)).astype(str).unique())
                ),
                "event_types": json.dumps(
                    group.get("event_type", pd.Series("Other", index=group.index)).astype(str).tolist()
                ),
                "individual_surprises": _json_records(group),
                "combined_standardized_surprise": combined_surprise,
                "combined_surprise_complete": all_surprises_available,
                "dominant_event": dominant,
                "dominant_event_candidate": dominant,
                "dominance_method": dominance_method,
                "directional_conflict": directional_conflict,
                "contains_conflicting_surprises": directional_conflict,
                "attribution_status": attribution_status,
                "exclude_event_specific_analysis": bool(
                    collision
                    and (
                        not dominant
                        or attribution_status in {"conflicting_cluster", "ambiguous_cluster"}
                    )
                ),
                "importance": importance,
                "point_in_time_all_verified": bool(group["point_in_time_verified"].astype(bool).all()),
                "source_count": int(group["source"].nunique(dropna=False))
                if "source" in group
                else 0,
            }
        )
    return pd.DataFrame.from_records(records)


def write_event_clusters(clusters: pd.DataFrame, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        try:
            clusters.to_parquet(output, index=False)
        except ImportError as exc:
            raise EconomicCalendarError(
                "Writing Parquet requires pyarrow from requirements-empirical.txt"
            ) from exc
    else:
        clusters.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z")
