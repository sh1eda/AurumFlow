"""End-to-end execution of the frozen D006 2021-2025 historical design."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .config import D006Config, PROTECTED_TRACKED_SHA256, SPEC_SHA256, config_fingerprint
from .context import FrozenArtifact, FrozenContextTables, join_block_contexts, load_frozen_context
from .detector import _session_label, _trading_date, detect_rejection_blocks
from .lifecycle import combine_structural_records, evaluate_lifecycle
from .outcomes import (
    calculate_path_outcomes,
    causal_volatility_buckets,
    deduplicate_primary,
    filter_non_rejection_candidates,
    geometry_events,
    match_controls,
    non_block_candidates,
    structural_frame,
)
from .reporting import OUTPUT_DIRECTORY, publish_results, sha256_file, verify_results
from .schemas import (
    CONTROL_KEYS,
    DEFINITION_KEYS,
    DENOMINATOR_KEYS,
    EXCLUSION_KEYS,
    GEOMETRY_KEYS,
    INTERACTION_KEYS,
    SESSION_KEYS,
    YEAR_KEYS,
    validate_aggregate_audit,
)
from .source import HistoricalBars, load_historical_bars
from .statistics import (
    benjamini_hochberg,
    component_disposition,
    mean_test,
    paired_test,
    sample_adequacy,
    temporal_stability,
    trading_date_bootstrap,
)


EXECUTION_AUTHORIZATION = "EXECUTE_FROZEN_D006_2021_2025"
DEFAULT_CONTEXT_PATHS = {
    "d004": (
        "research_outputs/D004_XAUUSD_0830_0900/daily_events.parquet",
        "research_outputs/D004_XAUUSD_0830_0900/artifact_manifest.json",
    ),
    "snapshots": (
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/context_snapshots.parquet",
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/artifact_manifest.json",
    ),
    "anchors": (
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/anchor_events.parquet",
        "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/artifact_manifest.json",
    ),
}


class HistoricalExecutionError(RuntimeError):
    """Raised before publication when any frozen D006 execution invariant fails."""


def _hash_paths(root: Path, paths: tuple[tuple[str, str], ...]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative, expected in paths:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise HistoricalExecutionError(f"protected path missing: {relative}")
        digest = sha256_file(path)
        if digest != expected:
            raise HistoricalExecutionError(f"protected path changed: {relative}")
        observed[relative] = digest
    return observed


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    for column in normalized.columns:
        if normalized[column].dtype == "object":
            normalized[column] = normalized[column].map(
                lambda value: json.dumps(value, sort_keys=True, default=str)
                if isinstance(value, (list, tuple, dict))
                else str(value)
            )
    material = pd.util.hash_pandas_object(normalized, index=True).to_numpy(dtype="uint64").tobytes()
    return sha256(material).hexdigest()


def _decorate_historical_bars(source: HistoricalBars) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_bars = source.five_minute.copy()
    local = pd.to_datetime(all_bars["available_at"], utc=True).dt.tz_convert("America/New_York")
    minutes = local.dt.hour * 60 + local.dt.minute
    all_bars["session"] = np.select(
        [minutes.ge(18 * 60), minutes.lt(8 * 60 + 30), minutes.lt(12 * 60), minutes.lt(17 * 60)],
        ["asia", "premarket", "ny_observation", "ny_afternoon"],
        default="maintenance",
    )
    named = local.dt.date.astype(str)
    after_1800 = minutes.ge(18 * 60)
    named.loc[after_1800] = (pd.to_datetime(named.loc[after_1800]) + pd.Timedelta(days=1)).dt.date.astype(str)
    all_bars["trading_date"] = named.to_numpy()
    complete = all_bars.loc[all_bars["is_complete"]].copy()
    detector_columns = ["open", "high", "low", "close", "available_at", "is_complete", "bar_id"]
    return all_bars, complete.loc[:, detector_columns]


def _session_completeness(all_bars: pd.DataFrame, config: D006Config) -> set[tuple[str, str]]:
    expected = {"asia": 72, "premarket": 102, "ny_observation": 42, "ny_afternoon": 60, "maintenance": 12}
    observed = all_bars.groupby(["trading_date", "session"], sort=True)["is_complete"].sum()
    return {
        (str(day), str(session))
        for (day, session), count in observed.items()
        if int(count) >= int(np.ceil(expected[str(session)] * config.minimum_segment_completeness))
    }


def _context_artifacts(root: Path) -> tuple[FrozenArtifact, FrozenArtifact, FrozenArtifact]:
    return tuple(
        FrozenArtifact(name=Path(paths[0]).name, parquet_path=root / paths[0], manifest_path=root / paths[1])
        for paths in DEFAULT_CONTEXT_PATHS.values()
    )  # type: ignore[return-value]


def _direction_string(value: object) -> str:
    if value in (1, "1", "bullish"):
        return "bullish"
    if value in (-1, "-1", "bearish"):
        return "bearish"
    raise HistoricalExecutionError(f"invalid frozen direction: {value}")


def _event_candidates(
    events: pd.DataFrame,
    bars: pd.DataFrame,
    volatility: Mapping[str, str],
    *,
    id_column: str,
    time_column: str,
    direction_column: str,
) -> pd.DataFrame:
    available = bars.set_index("available_at", drop=False)
    rows: list[dict[str, object]] = []
    for event in events.sort_values([time_column, id_column], kind="mergesort").itertuples(index=False):
        values = event._asdict()
        stamp = pd.Timestamp(values[time_column])
        if stamp not in available.index or stamp.year not in (2022, 2023, 2024, 2025):
            continue
        bar = available.loc[stamp]
        if isinstance(bar, pd.DataFrame):
            raise HistoricalExecutionError("control timestamp maps to duplicate bars")
        direction = _direction_string(values[direction_column])
        rows.append(
            {
                "candidate_id": str(values[id_column]),
                "event_at": stamp,
                "direction": direction,
                "year": stamp.year,
                "session": str(bar["session"]),
                "trading_date": str(bar["trading_date"]),
                "volatility_bucket": volatility.get(str(bar["trading_date"]), "unavailable"),
            }
        )
    return pd.DataFrame(rows, columns=("candidate_id", "event_at", "direction", "year", "session", "trading_date", "volatility_bucket"))


def _treatment_frame(primary: pd.DataFrame, volatility: Mapping[str, str]) -> pd.DataFrame:
    event_at = pd.to_datetime(primary["first_touch_timestamp"], utc=True)
    result = pd.DataFrame(
        {
            "event_id": primary["block_id"].astype(str),
            "event_at": event_at,
            "direction": primary["direction"].astype(str),
            "session": event_at.map(_session_label),
            "trading_date": event_at.map(_trading_date),
        }
    )
    result["year"] = result["event_at"].dt.year
    result["volatility_bucket"] = result["trading_date"].map(volatility).fillna("unavailable")
    # The 120-minute maximum registered endpoint must remain strictly inside its fold.
    fold_end = pd.to_datetime((result["year"] + 1).astype(str) + "-01-01", utc=True)
    result = result.loc[result["event_at"].add(pd.Timedelta(minutes=120)).lt(fold_end)].copy()
    return result.sort_values(["event_at", "event_id"], kind="mergesort").reset_index(drop=True)


def _eligibility_frame(
    structures: pd.DataFrame,
    session_complete: set[tuple[str, str]],
    config: D006Config,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Assign one frozen first-failure reason before any outcome calculation."""

    validation = structures.loc[
        pd.to_datetime(structures["causal_availability"], utc=True).dt.year.isin(config.validation_years)
    ].copy()
    validation["first_failure"] = ""
    availability = pd.to_datetime(validation["causal_availability"], utc=True)
    fold_end = pd.to_datetime((availability.dt.year + 1).astype(str) + "-01-01", utc=True)
    validation.loc[
        availability.add(pd.Timedelta(minutes=config.endpoint_buffer_minutes)).ge(fold_end),
        "first_failure",
    ] = "interval_boundary"
    complete_mask = pd.Series(
        [
            (str(day), str(session)) in session_complete
            for day, session in zip(validation["trading_date"], validation["session"])
        ],
        index=validation.index,
    )
    validation.loc[
        validation["first_failure"].eq("") & ~complete_mask,
        "first_failure",
    ] = "incomplete_session"
    validation.loc[
        validation["first_failure"].eq("") & validation["preavailability_interaction"],
        "first_failure",
    ] = "pre_availability_interaction"
    return validation, validation.loc[validation["first_failure"].eq("")].copy()


def _paired_outcome_table(
    matches: pd.DataFrame,
    treatment_outcomes: pd.DataFrame,
    bars: pd.DataFrame,
    config: D006Config,
) -> pd.DataFrame:
    matched = matches.loc[matches["matched"]].copy()
    if matched.empty:
        return pd.DataFrame(columns=("treatment_id", "control_id", "direction", "treatment_at", "control_at", "trading_date", "treatment_movement", "control_movement", "paired_difference"))
    controls = matched.rename(columns={"control_id": "event_id", "control_at": "event_at"})
    control_outcomes = calculate_path_outcomes(
        controls,
        bars,
        event_id_column="event_id",
        event_at_column="event_at",
        config=config,
    ).rename(columns={"event_id": "control_id", "direction_aligned_movement": "control_movement", "endpoint_complete": "control_endpoint_complete"})
    treatment = treatment_outcomes.rename(columns={"event_id": "treatment_id", "direction_aligned_movement": "treatment_movement", "endpoint_complete": "treatment_endpoint_complete"})
    result = matched.merge(
        treatment[["treatment_id", "treatment_movement", "treatment_endpoint_complete"]],
        on="treatment_id",
        how="left",
        validate="one_to_one",
    ).merge(
        control_outcomes[["control_id", "control_movement", "control_endpoint_complete"]],
        on="control_id",
        how="left",
        validate="one_to_one",
    )
    result = result.loc[result["treatment_endpoint_complete"] & result["control_endpoint_complete"]].copy()
    trading_dates = pd.Series(
        pd.to_datetime(result["treatment_at"], utc=True).dt.tz_convert("America/New_York").dt.date.astype(str),
        index=result.index,
    )
    result["trading_date"] = trading_dates
    result["paired_difference"] = result["treatment_movement"] - result["control_movement"]
    return result


def _control_analysis(
    treatments: pd.DataFrame,
    treatment_outcomes: pd.DataFrame,
    candidate_families: Mapping[str, pd.DataFrame],
    bars: pd.DataFrame,
    config: D006Config,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, object]], dict[str, pd.DataFrame]]:
    matches: dict[str, pd.DataFrame] = {}
    pairs: dict[str, pd.DataFrame] = {}
    tests: dict[str, dict[str, object]] = {}
    for family, candidates in candidate_families.items():
        matched = match_controls(treatments, candidates, family=family, config=config)
        pair_frame = _paired_outcome_table(matched, treatment_outcomes, bars, config)
        matches[family] = matched
        pairs[family] = pair_frame
        tests[family] = paired_test(pair_frame, treatment="treatment_movement", control="control_movement", confidence=config.confidence_level)
    return matches, tests, pairs


def _redundancy(
    primary: pd.DataFrame,
    anchors: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> dict[str, dict[str, object]]:
    mapping = {
        "liquidity_sweep": ("named_liquidity_sweep",),
        "mss": ("mss_body_close_confirmation",),
        "displacement": ("displacement_confirmation",),
        "refinement": ("refinement_array_creation",),
        "raw_fvg": ("first_aligned_raw_fvg_creation",),
        "qualified_fvg": ("first_context_qualified_fvg_creation",),
        "order_block": tuple(sorted(value for value in anchors["anchor_type"].dropna().unique() if str(value).startswith("qualifying_ob_"))),
    }
    output: dict[str, dict[str, object]] = {}
    for name, anchor_types in mapping.items():
        subset = anchors.loc[anchors["anchor_type"].isin(anchor_types)]
        temporally_overlapped: set[str] = set()
        price_eligible: set[str] = set()
        price_overlapped: set[str] = set()
        timing_differences: list[float] = []
        for block in primary.itertuples(index=False):
            candidates = subset.loc[
                subset["available_at"].between(
                    pd.Timestamp(block.causal_availability) - pd.Timedelta(minutes=60),
                    pd.Timestamp(block.causal_availability) + pd.Timedelta(minutes=60),
                    inclusive="both",
                )
            ]
            ordered_candidates = candidates.assign(
                _absolute_minutes=(
                    candidates["available_at"] - pd.Timestamp(block.causal_availability)
                ).abs().dt.total_seconds() / 60.0
            ).sort_values(["_absolute_minutes", "available_at", "context_id"], kind="mergesort")
            if len(ordered_candidates):
                nearest = ordered_candidates.iloc[0]
                temporally_overlapped.add(block.block_id)
                timing_differences.append(
                    (pd.Timestamp(nearest["available_at"]) - pd.Timestamp(block.causal_availability)).total_seconds() / 60.0
                )
            for anchor in ordered_candidates.itertuples(index=False):
                if pd.notna(anchor.anchor_price):
                    price_eligible.add(block.block_id)
                if pd.notna(anchor.anchor_price) and min(block.distal, block.proximal) <= float(anchor.anchor_price) <= max(block.distal, block.proximal):
                    price_overlapped.add(block.block_id)
                    break
        denominator = len(primary)
        output[name] = {
            "overlap_count": len(temporally_overlapped),
            "denominator": denominator,
            "overlap_rate": len(temporally_overlapped) / denominator if denominator else None,
            "price_eligible_count": len(price_eligible),
            "price_overlap_count": len(price_overlapped),
            "price_overlap_rate": (
                len(price_overlapped) / len(price_eligible) if price_eligible else None
            ),
            "median_signed_minutes": float(np.median(timing_differences)) if timing_differences else None,
        }
    context_overlapped: set[str] = set()
    context_differences: list[float] = []
    for block in primary.itertuples(index=False):
        candidates = snapshots.loc[
            snapshots["available_at"].between(
                pd.Timestamp(block.causal_availability) - pd.Timedelta(minutes=60),
                pd.Timestamp(block.causal_availability) + pd.Timedelta(minutes=60),
                inclusive="both",
            )
        ].copy()
        if candidates.empty:
            continue
        candidates["_absolute_minutes"] = (
            candidates["available_at"] - pd.Timestamp(block.causal_availability)
        ).abs().dt.total_seconds() / 60.0
        nearest = candidates.sort_values(
            ["_absolute_minutes", "available_at", "context_id"], kind="mergesort"
        ).iloc[0]
        context_overlapped.add(block.block_id)
        context_differences.append(
            (pd.Timestamp(nearest["available_at"]) - pd.Timestamp(block.causal_availability)).total_seconds() / 60.0
        )
    denominator = len(primary)
    output["d005_context"] = {
        "overlap_count": len(context_overlapped),
        "denominator": denominator,
        "overlap_rate": len(context_overlapped) / denominator if denominator else None,
        "price_eligible_count": 0,
        "price_overlap_count": 0,
        "price_overlap_rate": None,
        "median_signed_minutes": float(np.median(context_differences)) if context_differences else None,
    }
    return output


def _geometry_analysis(
    baseline: pd.DataFrame,
    bars: pd.DataFrame,
    config: D006Config,
) -> tuple[pd.DataFrame, dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    events = geometry_events(baseline, bars)
    touched = events.loc[events["touch_at"].notna()].copy()
    touched["geometry_event_id"] = touched["block_id"].astype(str) + "|" + touched["boundary"].astype(str)
    path = calculate_path_outcomes(
        touched.rename(columns={"geometry_event_id": "event_id", "touch_at": "event_at"}),
        bars,
        event_id_column="event_id",
        event_at_column="event_at",
        config=config,
    )
    touched = touched.merge(
        path,
        left_on=["geometry_event_id", "touch_at", "direction"],
        right_on=["event_id", "event_at", "direction"],
        how="left",
        validate="one_to_one",
    )
    geometry: dict[str, dict[str, object]] = {}
    for boundary in ("proximal", "midpoint", "distal"):
        cohort = events.loc[events["boundary"].eq(boundary)]
        hits = touched.loc[touched["boundary"].eq(boundary)]
        valid = hits.loc[hits["endpoint_complete"]]
        geometry[boundary] = {
            "eligible": len(cohort),
            "touched": len(hits),
            "endpoint_complete": len(valid),
            "touch_rate": len(hits) / len(cohort) if len(cohort) else None,
            "median_minutes_to_touch": float(hits["elapsed_minutes"].median()) if len(hits) else None,
            "invalidation_before_touch_rate": float(cohort["invalidation_before_touch"].mean()) if len(cohort) else None,
            "mean_movement": float(valid["direction_aligned_movement"].mean()) if len(valid) else None,
            "mean_mfe": float(valid["mfe"].mean()) if len(valid) else None,
            "mean_mae": float(valid["mae"].mean()) if len(valid) else None,
            "mean_mfe_mae_ratio": float(valid["mfe_mae_ratio"].mean()) if valid["mfe_mae_ratio"].notna().any() else None,
            "zero_mae_count": int(valid["zero_mae"].sum()) if len(valid) else 0,
            "adverse_before_favorable_rate": float(valid["adverse_before_favorable"].dropna().mean()) if valid["adverse_before_favorable"].notna().any() else None,
            "expiry_rate": float(cohort["expired_without_touch"].mean()) if len(cohort) else None,
            "median_lifecycle_minutes": float(cohort["lifecycle_minutes"].median()) if len(cohort) else None,
            "improvement_passed": False,
        }
    tests: dict[str, dict[str, object]] = {}
    metrics = {
        "touch_rate": ("touch_at", lambda value: value.notna().astype(float)),
        "time_to_touch": ("elapsed_minutes", lambda value: value),
        "invalidation_before_touch": ("invalidation_before_touch", lambda value: value.astype(float)),
        "movement": ("direction_aligned_movement", lambda value: value),
        "mfe_mae_ratio": ("mfe_mae_ratio", lambda value: value),
    }
    proximal = touched.loc[touched["boundary"].eq("proximal")].set_index("block_id")
    all_proximal = events.loc[events["boundary"].eq("proximal")].set_index("block_id")
    for boundary in ("midpoint", "distal"):
        boundary_touched = touched.loc[touched["boundary"].eq(boundary)].set_index("block_id")
        all_boundary = events.loc[events["boundary"].eq(boundary)].set_index("block_id")
        for metric, (column, transform) in metrics.items():
            left, right = (all_boundary, all_proximal) if metric in {"touch_rate", "invalidation_before_touch"} else (boundary_touched, proximal)
            common = left.index.intersection(right.index)
            differences = transform(left.loc[common, column]) - transform(right.loc[common, column])
            tests[f"{boundary}_vs_proximal_{metric}"] = mean_test(differences.dropna(), config.confidence_level)
    adjusted = benjamini_hochberg(tests, family="geometry")
    for boundary in ("midpoint", "distal"):
        movement = adjusted[f"{boundary}_vs_proximal_movement"]
        ratio = adjusted[f"{boundary}_vs_proximal_mfe_mae_ratio"]
        retention = geometry[boundary]["touched"] >= config.minimum_geometry_retention * max(1, geometry["proximal"]["touched"])
        directions_ok = all(
            int(touched.loc[touched["boundary"].eq(boundary) & touched["direction"].eq(direction), "endpoint_complete"].sum()) >= config.minimum_per_direction
            for direction in ("bullish", "bearish")
        )
        common_geometry = boundary_touched.index.intersection(proximal.index)
        yearly_ratio = {}
        for year in config.validation_years:
            common_year = common_geometry[
                pd.to_datetime(
                    boundary_touched.loc[common_geometry, "touch_at"], utc=True
                ).dt.year.to_numpy()
                == year
            ]
            differences = (
                boundary_touched.loc[common_year, "mfe_mae_ratio"]
                - proximal.loc[common_year, "mfe_mae_ratio"]
            )
            yearly_ratio[str(year)] = mean_test(differences.dropna(), config.confidence_level)
        ratio_stability = temporal_stability(yearly_ratio)
        geometry[boundary]["temporal_stability"] = ratio_stability
        geometry[boundary]["improvement_passed"] = bool(
            geometry[boundary]["touched"] >= config.minimum_geometry_cohort
            and retention
            and directions_ok
            and movement.get("ci_lower") is not None
            and float(movement["ci_lower"]) >= 0
            and ratio.get("mean") is not None
            and float(ratio["mean"]) > 0
            and ratio.get("q_value") is not None
            and float(ratio["q_value"]) <= config.fdr_alpha
            and geometry[boundary]["adverse_before_favorable_rate"] is not None
            and geometry["proximal"]["adverse_before_favorable_rate"] is not None
            and geometry[boundary]["adverse_before_favorable_rate"] < geometry["proximal"]["adverse_before_favorable_rate"]
            and ratio_stability["passed"]
        )
    return touched, geometry, adjusted


def _aggregate_audit(
    structures: pd.DataFrame,
    session_complete: set[tuple[str, str]],
    treatments: pd.DataFrame,
    treatment_outcomes: pd.DataFrame,
    primary_matches: pd.DataFrame,
    primary_pairs: pd.DataFrame,
    all_matches: Mapping[str, pd.DataFrame],
    all_pairs: Mapping[str, pd.DataFrame],
    interaction_audits: Mapping[str, Mapping[str, int]],
    geometry: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    validation = structures.loc[
        pd.to_datetime(structures["causal_availability"], utc=True).dt.year.isin(
            {int(value) for value in YEAR_KEYS}
        )
    ].copy()
    validation["first_failure"] = ""
    fold_end = pd.to_datetime((pd.to_datetime(validation["causal_availability"], utc=True).dt.year + 1).astype(str) + "-01-01", utc=True)
    validation.loc[pd.to_datetime(validation["causal_availability"], utc=True).add(pd.Timedelta(minutes=120)).ge(fold_end), "first_failure"] = "interval_boundary"
    incomplete_session = [
        (day, session) not in session_complete
        for day, session in zip(validation["trading_date"], validation["session"])
    ]
    validation.loc[validation["first_failure"].eq("") & pd.Series(incomplete_session, index=validation.index), "first_failure"] = "incomplete_session"
    validation.loc[validation["first_failure"].eq("") & validation["preavailability_interaction"], "first_failure"] = "pre_availability_interaction"
    eligible = validation.loc[validation["first_failure"].eq("")].copy()
    exclusions = {key: int(validation["first_failure"].eq(key).sum()) for key in EXCLUSION_KEYS}
    primary_exclusions = _primary_exclusion_counts(
        treatments, treatment_outcomes, primary_matches, primary_pairs
    )
    states = eligible["lifecycle_state"].replace({"ACTIVE_UNTOUCHED": "ACTIVE_CENSORED", "ACTIVE_TOUCHED": "ACTIVE_CENSORED"})
    expected = len(treatments)
    matched = int(primary_matches["matched"].sum()) if len(primary_matches) else 0
    reconciliation: dict[str, dict[str, int]] = {}
    for key in CONTROL_KEYS:
        match = all_matches.get(key, pd.DataFrame())
        candidate_count = len(match)
        matched_count = int(match["matched"].sum()) if len(match) else 0
        pair_count = len(all_pairs.get(key, pd.DataFrame()))
        reconciliation[key] = {
            "candidate_count": candidate_count,
            "matched_count": matched_count,
            "unmatched_count": candidate_count - matched_count,
            "endpoint_complete_pair_count": min(pair_count, matched_count),
        }
    geometry_audit = {
        key: {
            "eligible_count": int(values["eligible"]),
            "touched_count": int(values["touched"]),
            "endpoint_complete_count": int(values["endpoint_complete"]),
        }
        for key, values in geometry.items()
    }
    audit = {
        "detected": len(validation),
        "duplicate_id_excluded": exclusions["duplicate_identity"],
        "lifecycle_eligible": len(eligible),
        "endpoint_eligible": expected,
        "endpoint_complete_count": len(primary_pairs),
        "touched": int(eligible["first_touch_timestamp"].notna().sum()),
        "untouched": int(eligible["first_touch_timestamp"].isna().sum()),
        "invalidated": int(states.eq("INVALIDATED").sum()),
        "mitigated": int(states.eq("MITIGATED").sum()),
        "expired": int(states.eq("EXPIRED").sum()),
        "active_censored": int(states.eq("ACTIVE_CENSORED").sum()),
        "overlapping": int(validation["overlap_group_id"].map(validation["overlap_group_id"].value_counts()).gt(1).sum()),
        "nested": int(validation["parent_block_id"].notna().sum()),
        "bullish": int(validation["direction"].eq("bullish").sum()),
        "bearish": int(validation["direction"].eq("bearish").sum()),
        "preavailability_count": exclusions["pre_availability_interaction"],
        "endpoint_coverage_complete": bool(expected == len(primary_pairs)),
        "expected_primary_pairs": expected,
        "observed_primary_pairs": len(primary_pairs),
        "controls_expected": expected,
        "controls_observed": len(primary_pairs),
        "controls_matched": len(primary_pairs),
        "controls_unmatched": expected - len(primary_pairs),
        "by_definition": {key: int(validation["definition_name"].eq(key).sum()) for key in DEFINITION_KEYS},
        "by_year": {key: int(pd.to_datetime(validation["causal_availability"], utc=True).dt.year.eq(int(key)).sum()) for key in YEAR_KEYS},
        "by_session": {key: int(validation["session"].eq(key).sum()) for key in SESSION_KEYS},
        "by_direction": {key: int(validation["direction"].eq(key).sum()) for key in ("bullish", "bearish")},
        "by_terminal_state": {key: int(states.eq(key).sum()) for key in ("MITIGATED", "INVALIDATED", "EXPIRED", "ACTIVE_CENSORED")},
        "exclusions_by_reason": exclusions,
        "primary_exclusions_by_reason": primary_exclusions,
        "treatment_control_reconciliation": reconciliation,
        "interactions": {key: dict(interaction_audits[key]) for key in INTERACTION_KEYS},
        "geometry": geometry_audit,
        "denominator_definitions": {key: f"Frozen D006 {key} denominator as specified in D006 v1" for key in DENOMINATOR_KEYS},
    }
    validate_aggregate_audit(audit)
    return audit


def _primary_exclusion_counts(
    treatments: pd.DataFrame,
    treatment_outcomes: pd.DataFrame,
    primary_matches: pd.DataFrame,
    primary_pairs: pd.DataFrame,
) -> dict[str, int]:
    """Reconcile one first-failure reason for every absent primary pair."""

    treatment_ids = set(treatments["event_id"].astype(str))
    endpoint_complete_ids = set(
        treatment_outcomes.loc[treatment_outcomes["endpoint_complete"], "event_id"].astype(str)
    )
    matched_ids = set(
        primary_matches.loc[primary_matches["matched"], "treatment_id"].astype(str)
    )
    paired_ids = set(primary_pairs["treatment_id"].astype(str))
    if not (paired_ids <= matched_ids <= treatment_ids and endpoint_complete_ids <= treatment_ids):
        raise HistoricalExecutionError("primary exclusion identity sets do not reconcile")
    counts = {key: 0 for key in EXCLUSION_KEYS}
    counts["incomplete_endpoint"] = len(treatment_ids - endpoint_complete_ids) + len(
        (matched_ids & endpoint_complete_ids) - paired_ids
    )
    counts["missing_control"] = len(endpoint_complete_ids - matched_ids)
    if sum(counts.values()) != len(treatment_ids) - len(paired_ids):
        raise HistoricalExecutionError("primary first-failure exclusions do not reconcile")
    return counts


def run_historical_execution(
    root: Path,
    *,
    authorization: str,
    output_relative: Path = OUTPUT_DIRECTORY,
    config: D006Config = D006Config(),
) -> Path:
    """Execute the single authorized D006 historical run and publish atomically."""

    if authorization != EXECUTION_AUTHORIZATION:
        raise HistoricalExecutionError("explicit frozen historical authorization is required")
    if output_relative != OUTPUT_DIRECTORY:
        raise HistoricalExecutionError("D006 historical output namespace is fixed")
    root = root.resolve()
    output = root / output_relative
    if output.exists():
        raise HistoricalExecutionError("D006 output already exists; overwrite/resume is forbidden")
    protected_before = _hash_paths(root, PROTECTED_TRACKED_SHA256)
    source = load_historical_bars(root, config=config)
    source_bars_all, detector_bars = _decorate_historical_bars(source)
    if pd.to_datetime(source_bars_all["available_at"], utc=True).max() >= pd.Timestamp(config.source_end):
        raise HistoricalExecutionError("2026 bar escaped the frozen source boundary")
    evaluation_at = pd.Timestamp(detector_bars["available_at"].iloc[-1])
    first_blocks = detect_rejection_blocks(detector_bars, evaluation_at, config)
    second_blocks = detect_rejection_blocks(detector_bars, evaluation_at, config)
    first_lifecycle = [evaluate_lifecycle(block, detector_bars, evaluation_at, config) for block in first_blocks]
    second_lifecycle = [evaluate_lifecycle(block, detector_bars, evaluation_at, config) for block in second_blocks]
    first_records = combine_structural_records(first_blocks, first_lifecycle)
    second_records = combine_structural_records(second_blocks, second_lifecycle)
    structures = structural_frame(first_records)
    reproducibility_match = _frame_fingerprint(structures) == _frame_fingerprint(structural_frame(second_records))
    if not reproducibility_match:
        raise HistoricalExecutionError("historical detector/lifecycle bytes are not reproducible")

    session_complete = _session_completeness(source_bars_all, config)
    validation_structures, eligible_structures = _eligibility_frame(
        structures, session_complete, config
    )
    all_bars = source_bars_all.loc[source_bars_all["is_complete"]].copy()
    volatility = causal_volatility_buckets(all_bars, config)
    baseline_detected = validation_structures.loc[
        validation_structures["definition_name"].eq(config.primary_definition)
    ].copy()
    baseline_all = eligible_structures.loc[
        eligible_structures["definition_name"].eq(config.primary_definition)
    ].copy()
    primary, dedup_excluded = deduplicate_primary(eligible_structures, config)
    treatments = _treatment_frame(primary, volatility)
    treatment_outcomes = calculate_path_outcomes(treatments, all_bars, event_id_column="event_id", event_at_column="event_at", config=config)

    context_tables: FrozenContextTables = load_frozen_context(*_context_artifacts(root))
    join_input = primary.loc[primary["block_id"].isin(treatments["event_id"])].copy()
    join_input["direction"] = join_input["direction"].map({"bullish": 1, "bearish": -1})
    context_join = join_block_contexts(join_input, context_tables)

    nonblock = non_block_candidates(all_bars, structures, volatility, config)
    displacement_candidates = filter_non_rejection_candidates(
        _event_candidates(context_tables.anchors.loc[context_tables.anchors["anchor_type"].eq("displacement_confirmation")], all_bars, volatility, id_column="context_id", time_column="available_at", direction_column="direction"),
        all_bars, structures, config,
    )
    context_candidates = filter_non_rejection_candidates(
        _event_candidates(context_tables.snapshots, all_bars, volatility, id_column="context_id", time_column="available_at", direction_column="direction"),
        all_bars, structures, config,
    )
    random_candidates = nonblock.copy()
    candidate_families = {
        "matched_non_block": nonblock,
        "matched_displacement_without_rb": displacement_candidates,
        "matched_context_without_rb": context_candidates,
        "random_time_placebo": random_candidates,
    }
    matches, control_tests, control_pairs = _control_analysis(treatments, treatment_outcomes, candidate_families, all_bars, config)
    matches["matched_time_session_volatility"] = matches["matched_non_block"].copy()
    control_tests["matched_time_session_volatility"] = dict(control_tests["matched_non_block"])
    control_pairs["matched_time_session_volatility"] = control_pairs["matched_non_block"].copy()
    matches["direction_balanced"] = matches["matched_non_block"].copy()
    control_pairs["direction_balanced"] = control_pairs["matched_non_block"].copy()
    balanced_direction_means = [
        primary_direction["paired_difference"].mean()
        for direction in ("bullish", "bearish")
        if len(primary_direction := control_pairs["matched_non_block"].loc[
            control_pairs["matched_non_block"]["direction"].eq(direction)
        ])
    ]
    control_tests["direction_balanced"] = {
        "n": len(control_pairs["matched_non_block"]),
        "mean": float(np.mean(balanced_direction_means)) if len(balanced_direction_means) == 2 else None,
        "audit": "equal_weight_bullish_bearish_primary_pairs",
        "q_value": None,
    }
    primary_matches = matches["matched_non_block"]
    primary_pairs = control_pairs["matched_non_block"]

    sensitivity_structures = eligible_structures.loc[
        eligible_structures["definition_name"].eq("cluster2_wick_50_d3_v1")
    ].copy()
    sensitivity_config = config
    sensitivity_primary = sensitivity_structures.loc[
        sensitivity_structures["first_touch_timestamp"].notna()
    ].copy()
    sensitivity_primary["dedup_group"] = sensitivity_primary["overlap_group_id"].fillna(
        sensitivity_primary["block_id"]
    )
    sensitivity_primary = sensitivity_primary.sort_values(
        ["dedup_group", "direction", "causal_availability", "range", "block_id"],
        kind="mergesort",
    )
    sensitivity_primary = sensitivity_primary.loc[
        ~sensitivity_primary.duplicated(["dedup_group", "direction"], keep="first")
    ].drop(columns="dedup_group")
    sensitivity_treatments = _treatment_frame(sensitivity_primary, volatility)
    sensitivity_outcomes = calculate_path_outcomes(
        sensitivity_treatments,
        all_bars,
        event_id_column="event_id",
        event_at_column="event_at",
        config=sensitivity_config,
    )
    sensitivity_matches = match_controls(
        sensitivity_treatments,
        nonblock,
        family="definition_sensitivity",
        config=sensitivity_config,
    )
    sensitivity_pairs = _paired_outcome_table(
        sensitivity_matches, sensitivity_outcomes, all_bars, sensitivity_config
    )
    definition_sensitivity = benjamini_hochberg(
        {
            "cluster2_wick_50_d3_v1": paired_test(
                sensitivity_pairs,
                treatment="treatment_movement",
                control="control_movement",
                confidence=config.confidence_level,
            )
        },
        family="definition_sensitivity",
    )

    # Fixed interaction construction and constituent-feature controls.
    interaction_candidates = {
        "aligned_d005_context": context_candidates,
        "against_d005_context_negative_control": context_candidates,
        "after_d004_manipulation": filter_non_rejection_candidates(_event_candidates(context_tables.d004_events, all_bars, volatility, id_column="context_id", time_column="available_at", direction_column="direction"), all_bars, structures, config),
        "frozen_liquidity_sweep": filter_non_rejection_candidates(_event_candidates(context_tables.anchors.loc[context_tables.anchors["anchor_type"].eq("named_liquidity_sweep") & context_tables.anchors["invalidation_observable"]], all_bars, volatility, id_column="context_id", time_column="available_at", direction_column="direction"), all_bars, structures, config),
        "displacement_confirmation": displacement_candidates,
        "refinement_confirmation": filter_non_rejection_candidates(_event_candidates(context_tables.anchors.loc[context_tables.anchors["anchor_type"].eq("refinement_array_creation")], all_bars, volatility, id_column="context_id", time_column="available_at", direction_column="direction"), all_bars, structures, config),
    }
    interaction_results: dict[str, dict[str, object]] = {
        "rb_alone": {**paired_test(primary_pairs, treatment="treatment_movement", control="control_movement", confidence=config.confidence_level), "classification": "confirmatory", "status": "EVALUATED"}
    }
    interaction_audits: dict[str, dict[str, int]] = {
        "rb_alone": {"candidate_count": len(treatments), "eligible_count": len(treatments), "endpoint_complete_count": len(primary_pairs), "matched_count": int(primary_matches["matched"].sum()), "excluded_count": 0}
    }
    interaction_pairs: dict[str, pd.DataFrame] = {}
    joined = treatments.merge(context_join, left_on="event_id", right_on="block_id", how="left", validate="one_to_one")
    for interaction in config.interactions[1:]:
        cohort = joined.loc[joined[interaction.name].fillna(False)].copy()
        matched = match_controls(cohort[treatments.columns], interaction_candidates[interaction.name], family=f"interaction:{interaction.name}", config=config)
        outcomes = treatment_outcomes.loc[treatment_outcomes["event_id"].isin(cohort["event_id"])]
        pairs = _paired_outcome_table(matched, outcomes, all_bars, config)
        pairs["interaction"] = interaction.name
        interaction_pairs[interaction.name] = pairs
        result = paired_test(pairs, treatment="treatment_movement", control="control_movement", confidence=config.confidence_level)
        result.update({"classification": interaction.classification, "status": "EVALUATED" if len(pairs) >= interaction.minimum_sample else "NOT_EVALUATED"})
        interaction_results[interaction.name] = result
        interaction_audits[interaction.name] = {
            "candidate_count": len(joined),
            "eligible_count": len(cohort),
            "endpoint_complete_count": len(pairs),
            "matched_count": int(matched["matched"].sum()) if len(matched) else 0,
            "excluded_count": len(joined) - len(cohort),
        }
    interaction_adjusted = benjamini_hochberg({key: interaction_results[key] for key in INTERACTION_KEYS if key != "rb_alone"}, family="interactions")
    for key, values in interaction_adjusted.items():
        interaction_results[key] = values

    redundancy = _redundancy(primary, context_tables.anchors, context_tables.snapshots)
    geometry_table, geometry, geometry_tests = _geometry_analysis(baseline_all, all_bars, config)

    # Primary, control, yearly, direction, and bootstrap inference.
    primary_test = paired_test(primary_pairs, treatment="treatment_movement", control="control_movement", confidence=config.confidence_level)
    bootstrap = trading_date_bootstrap(primary_pairs, difference_column="paired_difference", date_column="trading_date", label="primary", config=config)
    yearly = {
        str(year): mean_test(primary_pairs.loc[pd.to_datetime(primary_pairs["treatment_at"], utc=True).dt.year.eq(year), "paired_difference"], config.confidence_level)
        for year in config.validation_years
    }
    direction_results = {
        direction: mean_test(primary_pairs.loc[primary_pairs["direction"].eq(direction), "paired_difference"], config.confidence_level)
        for direction in ("bullish", "bearish")
    }
    paired_strata = primary_pairs.merge(
        treatments[["event_id", "session", "volatility_bucket"]],
        left_on="treatment_id",
        right_on="event_id",
        how="left",
        validate="one_to_one",
    )
    session_results = {
        session: mean_test(
            paired_strata.loc[paired_strata["session"].eq(session), "paired_difference"],
            config.confidence_level,
        )
        for session in SESSION_KEYS
    }
    volatility_results = {
        bucket: mean_test(
            paired_strata.loc[
                paired_strata["volatility_bucket"].eq(bucket), "paired_difference"
            ],
            config.confidence_level,
        )
        for bucket in ("low", "normal", "high", "unavailable")
    }
    temporal = temporal_stability(yearly)
    incremental_keys = ("matched_displacement_without_rb", "matched_context_without_rb", "matched_time_session_volatility", "random_time_placebo")
    incremental_adjusted = benjamini_hochberg({key: control_tests[key] for key in incremental_keys}, family="incremental_controls")
    for key, values in incremental_adjusted.items():
        control_tests[key] = values

    interaction_counts = {key: values["endpoint_complete_count"] for key, values in interaction_audits.items()}
    geometry_counts = {key: int(values["touched"]) for key, values in geometry.items()}
    adequacy_baseline = baseline_all.copy()
    touched_mask = adequacy_baseline["first_touch_timestamp"].notna()
    adequacy_baseline.loc[touched_mask, "session"] = pd.to_datetime(
        adequacy_baseline.loc[touched_mask, "first_touch_timestamp"], utc=True
    ).map(_session_label)
    adequacy = sample_adequacy(
        baseline_detected,
        adequacy_baseline,
        primary_pairs,
        len(treatments),
        interaction_counts,
        geometry_counts,
        config,
    )
    all_matches = dict(matches)
    audit = _aggregate_audit(structures, session_complete, treatments, treatment_outcomes, primary_matches, primary_pairs, all_matches, control_pairs, interaction_audits, geometry)
    integrity_passed = bool(
        reproducibility_match
        and all(pd.to_datetime(structures["causal_availability"], utc=True).dt.year.lt(2026))
    )
    structural_passed = bool(
        integrity_passed
        and adequacy["status"] == "SAMPLE_ADEQUATE"
        and all(
            int(
                pd.to_datetime(baseline_detected["causal_availability"], utc=True)
                .dt.year.eq(year)
                .sum()
            )
            > 0
            for year in config.validation_years
        )
        and int(baseline_detected["direction"].eq("bullish").sum()) >= config.minimum_per_direction
        and int(baseline_detected["direction"].eq("bearish").sum()) >= config.minimum_per_direction
    )
    primary_passed = bool(
        structural_passed
        and primary_test.get("mean") is not None and float(primary_test["mean"]) > 0
        and primary_test.get("ci_lower") is not None and float(primary_test["ci_lower"]) > 0
        and primary_test.get("p_value") is not None and float(primary_test["p_value"]) < 0.05
        and bootstrap.get("ci_lower") is not None and float(bootstrap["ci_lower"]) > 0
        and temporal["passed"]
    )
    direction_stable = all(
        values.get("mean") is not None and float(values["mean"]) > 0
        for values in direction_results.values()
    )
    incremental_positive = any(
        values.get("bh_reject")
        and values.get("mean") is not None
        and float(values["mean"]) > 0
        for key, values in incremental_adjusted.items()
        if key in {"matched_displacement_without_rb", "matched_context_without_rb"}
    )
    non_redundant_passed = bool(
        primary_passed
        and direction_stable
        and incremental_positive
        and all(values["overlap_rate"] != 1.0 for values in redundancy.values())
    )
    conditional_checks: dict[str, dict[str, object]] = {}
    for interaction in config.interactions[1:]:
        pairs = interaction_pairs[interaction.name]
        yearly_interaction = {
            str(year): mean_test(
                pairs.loc[
                    pd.to_datetime(pairs["treatment_at"], utc=True).dt.year.eq(year),
                    "paired_difference",
                ],
                config.confidence_level,
            )
            for year in config.validation_years
        }
        direction_interaction = {
            direction: mean_test(
                pairs.loc[pairs["direction"].eq(direction), "paired_difference"],
                config.confidence_level,
            )
            for direction in ("bullish", "bearish")
        }
        temporal_interaction = temporal_stability(yearly_interaction)
        directions_interaction_ok = all(
            values.get("mean") is not None and float(values["mean"]) > 0
            for values in direction_interaction.values()
        )
        conditional_checks[interaction.name] = {
            "temporal": temporal_interaction,
            "directions": direction_interaction,
            "passed": bool(
                interaction.classification != "exploratory"
                and interaction_results[interaction.name].get("status") == "EVALUATED"
                and interaction_results[interaction.name].get("bh_reject")
                and interaction_results[interaction.name].get("mean") is not None
                and float(interaction_results[interaction.name]["mean"]) > 0
                and temporal_interaction["passed"]
                and directions_interaction_ok
            ),
        }
    conditional_passed = bool(
        structural_passed
        and any(values["passed"] for values in conditional_checks.values())
    )
    geometry_passed = structural_passed and (geometry["midpoint"]["improvement_passed"] or geometry["distal"]["improvement_passed"])
    disposition = component_disposition(
        integrity_passed=integrity_passed,
        adequacy_passed=adequacy["status"] == "SAMPLE_ADEQUATE",
        structural_passed=structural_passed,
        primary_result=primary_test,
        non_redundant_passed=non_redundant_passed,
        conditional_passed=conditional_passed,
        geometry_passed=geometry_passed,
        yearly=yearly,
    )

    protected_after = _hash_paths(root, PROTECTED_TRACKED_SHA256)
    if protected_before != protected_after:
        raise HistoricalExecutionError("protected tracked inputs changed during execution")
    mode = "DECISIONAL_PREREGISTERED_HISTORICAL" if adequacy["status"] == "SAMPLE_ADEQUATE" else "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"
    for values in control_tests.values():
        values["mode"] = mode
    for values in interaction_results.values():
        values["mode"] = mode
        if adequacy["status"] != "SAMPLE_ADEQUATE":
            values["status"] = "NOT_EVALUATED"
    for values in geometry.values():
        values["mode"] = mode
    primary_status = "PASSED" if primary_passed else "FAILED" if adequacy["status"] == "SAMPLE_ADEQUATE" else "NOT_EVALUATED"
    source_audit = asdict(source.audit)
    source_audit.update({"selected_file_count": source.audit.source_file_count, "selected_row_count": source.audit.source_row_count, "selected_2026_rows": 0})
    stability = {
        **{f"year_{key}": value for key, value in yearly.items()},
        **{f"direction_{key}": value for key, value in direction_results.items()},
        **{f"session_{key}": value for key, value in session_results.items()},
        **{f"volatility_{key}": value for key, value in volatility_results.items()},
    }
    for values in stability.values():
        values["mode"] = mode
    result = {
        "spec_sha256": SPEC_SHA256,
        "config_fingerprint": config_fingerprint(config),
        "integrity": {"status": "INTEGRITY_VERIFIED" if integrity_passed else "REPRODUCIBILITY_DEFECT", "reproducibility_match": reproducibility_match, "selected_2026_rows": 0, "protected_inputs_preserved": True},
        "source_audit": source_audit,
        "aggregate_audit": audit,
        "primary_structural_claim": {"status": "PASSED" if structural_passed else "NOT_EVALUATED" if adequacy["status"] != "SAMPLE_ADEQUATE" else "FAILED", "stable_ordered_bytes": reproducibility_match},
        "sample_adequacy": adequacy,
        "primary_empirical_claim": {**primary_test, "status": primary_status, "mode": mode, "bootstrap_ci_lower": bootstrap.get("ci_lower"), "bootstrap_ci_upper": bootstrap.get("ci_upper"), "temporal_stability_passed": temporal["passed"]},
        "controls": control_tests,
        "interactions": interaction_results,
        "redundancy": redundancy,
        "geometry": geometry,
        "stability": stability,
        "statistical_validation": {"mode": mode, "primary": primary_test, "bootstrap": bootstrap, "temporal_stability": temporal, "yearly": yearly, "directions": direction_results, "sessions": session_results, "volatility": volatility_results, "definition_sensitivity_bh": definition_sensitivity, "incremental_bh": incremental_adjusted, "interaction_bh": interaction_adjusted, "interaction_stability": conditional_checks, "geometry_bh": geometry_tests},
        "component_disposition": disposition,
        "recommendation": "Carry this disposition only into later preregistered composite research; do not change production defaults or claim production suitability.",
        "run_manifest": {"version": config.version, "authorization": EXECUTION_AUTHORIZATION, "source_interval": [pd.Timestamp(config.source_start), pd.Timestamp(config.source_end)], "calibration_year": config.calibration_year, "validation_years": list(config.validation_years), "final_holdout": None, "excluded_outcome_known_interval": ["2026-01-01T00:00:00Z", "2026-07-29T00:00:00Z"], "future_blind_interval": None, "protected_hashes": protected_after, "structural_fingerprint": _frame_fingerprint(structures), "reproducibility_match": reproducibility_match},
    }
    tables = {
        "structural_blocks.parquet": structures,
        "primary_treatments.parquet": treatments,
        "primary_pairs.parquet": primary_pairs,
        "definition_sensitivity_pairs.parquet": sensitivity_pairs,
        "control_matches.parquet": pd.concat([frame.assign(control_family=key) for key, frame in matches.items()], ignore_index=True),
        "interaction_pairs.parquet": pd.concat(interaction_pairs.values(), ignore_index=True) if interaction_pairs else pd.DataFrame(),
        "context_joins.parquet": context_join,
        "geometry_events.parquet": geometry_table,
        "dedup_exclusions.parquet": dedup_excluded,
    }
    published = publish_results(root, result=result, tables=tables, output_relative=output_relative)
    verify_results(published)
    return published


__all__ = ["EXECUTION_AUTHORIZATION", "HistoricalExecutionError", "run_historical_execution"]
