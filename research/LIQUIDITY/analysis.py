"""Chronological Liquidity Phase 1 evaluation and clustered uncertainty."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np
import pandas as pd

from .definitions import DECISION_RULES, PRIMARY_OUTCOME_HORIZON


HORIZONS = ("30m", "60m", "120m", "study_end_1200", "trading_day_end_1700")
EVENT_HORIZONS = ("30m", "60m", "120m")
DISTANCE_BINS = (-math.inf, 0.0, 0.25, 0.50, 1.0, 2.0, math.inf)
DISTANCE_LABELS = ("inside_or_zero", "0_0.25", "0.25_0.50", "0.50_1.0", "1.0_2.0", "over_2.0")


@dataclass(frozen=True)
class LiquidityAnalysisResult:
    anchors: pd.DataFrame
    events: pd.DataFrame
    partition_specification: dict[str, object]
    frozen_baselines: dict[str, object]
    fixed_anchor_results: pd.DataFrame
    interaction_event_results: pd.DataFrame
    level_family_comparison: pd.DataFrame
    robustness_matrix: pd.DataFrame
    sensitivity_analysis: pd.DataFrame
    survival_results: pd.DataFrame
    hypothesis_results: pd.DataFrame
    phase1_summary: dict[str, object]


def chronological_partitions(
    anchors: pd.DataFrame, events: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Assign whole-session 50/25/25 partitions with no random split."""

    dates = sorted(
        set(anchors["session_date"].astype(str).unique())
        | set(events["session_date"].astype(str).unique())
    )
    if len(dates) < 12:
        raise ValueError("at least 12 chronological sessions are required")
    development_count = max(1, int(math.floor(len(dates) * 0.50)))
    validation_end = max(development_count + 1, int(math.floor(len(dates) * 0.75)))
    validation_end = min(validation_end, len(dates) - 1)
    groups = {
        "development": dates[:development_count],
        "validation": dates[development_count:validation_end],
        "holdout": dates[validation_end:],
    }
    mapping = {date: name for name, values in groups.items() for date in values}
    anchor_output = anchors.copy()
    event_output = events.copy()
    anchor_output["partition"] = anchor_output["session_date"].astype(str).map(mapping)
    event_output["partition"] = event_output["session_date"].astype(str).map(mapping)
    coverage_years = (
        pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])
    ).days / 365.2425
    specification: dict[str, object] = {
        "method": "chronological whole-session 50/25/25 split",
        "random_split": False,
        "coverage_years": round(coverage_years, 4),
        "history_confidence_cap_applies": coverage_years < 2.0,
        "holdout_isolation_rule": "Holdout rows do not fit distance, volatility, time, weekday, news, family, state, or event baselines and cannot alter thresholds.",
    }
    purposes = {
        "development": "baseline fitting and definition audit",
        "validation": "frozen-definition confirmation and robustness",
        "holdout": "untouched final evaluation",
    }
    for name, values in groups.items():
        specification[name] = {
            "start": values[0],
            "end": values[-1],
            "sessions": len(values),
            "anchor_rows": int(anchor_output["partition"].eq(name).sum()),
            "event_rows": int(event_output["partition"].eq(name).sum()),
            "purpose": purposes[name],
        }
    return anchor_output, event_output, specification


def _cluster_bootstrap_mean_ci(
    values: pd.Series,
    clusters: pd.Series,
    *,
    resamples: int,
    seed: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    valid = values.notna() & clusters.notna()
    array = values[valid].astype(float).to_numpy()
    labels = clusters[valid].astype(str).to_numpy()
    unique, inverse = np.unique(labels, return_inverse=True)
    if len(array) < 2 or len(unique) < 2:
        return math.nan, math.nan
    sums = np.bincount(inverse, weights=array, minlength=len(unique))
    counts = np.bincount(inverse, minlength=len(unique)).astype(float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(unique), size=(resamples, len(unique)))
    estimates = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(estimates, [alpha, 1.0 - alpha])
    return float(lower), float(upper)


def _mad(values: pd.Series) -> float:
    clean = values.dropna().astype(float)
    if clean.empty:
        return math.nan
    median = float(clean.median())
    return float((clean - median).abs().median())


def _distance_band(values: pd.Series) -> pd.Series:
    return pd.cut(
        values.astype(float),
        bins=DISTANCE_BINS,
        labels=DISTANCE_LABELS,
        include_lowest=True,
        ordered=True,
    ).astype("string").fillna("missing")


def fit_conditional_baselines(development: pd.DataFrame) -> dict[str, object]:
    """Fit transparent empirical reach rates on development anchors only."""

    primary = development[
        development["is_primary"] & development["active_under_primary_lifecycle"]
    ].copy()
    primary["distance_band"] = _distance_band(
        primary["prior_day_range_normalized_distance"]
    )
    finite_volatility = primary["rolling_volatility_scale"].dropna().astype(float)
    if finite_volatility.empty:
        volatility_thresholds = [math.nan, math.nan]
        primary["volatility_band"] = "missing"
    else:
        q1, q2 = finite_volatility.quantile([1 / 3, 2 / 3]).tolist()
        volatility_thresholds = [float(q1), float(q2)]
        primary["volatility_band"] = pd.cut(
            primary["rolling_volatility_scale"],
            [-math.inf, q1, q2, math.inf],
            labels=["low", "middle", "high"],
            include_lowest=True,
        ).astype("string").fillna("missing")
    model: dict[str, object] = {
        "fit_partition": "development",
        "distance_bins": list(DISTANCE_BINS),
        "distance_labels": list(DISTANCE_LABELS),
        "volatility_terciles": volatility_thresholds,
        "horizons": {},
        "holdout_rows_used": 0,
    }
    for horizon in HORIZONS:
        outcome = f"reached_{horizon}"
        usable = primary.dropna(subset=[outcome]).copy()
        overall = float(usable[outcome].astype(float).mean()) if not usable.empty else math.nan
        distance_rates = (
            usable.groupby("distance_band", observed=True)[outcome].mean().to_dict()
            if not usable.empty
            else {}
        )
        conditional_rates = (
            usable.groupby(
                ["distance_band", "evaluation_clock", "volatility_band"], observed=True
            )[outcome].agg(["mean", "size"])
            if not usable.empty
            else pd.DataFrame()
        )
        cells: dict[str, dict[str, float | int]] = {}
        if not conditional_rates.empty:
            for key, row in conditional_rates.iterrows():
                cells["|".join(str(value) for value in key)] = {
                    "rate": float(row["mean"]),
                    "n": int(row["size"]),
                }
        model["horizons"][horizon] = {
            "overall_rate": overall,
            "distance_rates": {str(key): float(value) for key, value in distance_rates.items()},
            "conditional_cells": cells,
            "minimum_cell_size": 20,
        }
    return model


def apply_conditional_baselines(
    anchors: pd.DataFrame, model: Mapping[str, object]
) -> pd.DataFrame:
    output = anchors.copy()
    output["distance_band"] = _distance_band(
        output["prior_day_range_normalized_distance"]
    )
    q1, q2 = model["volatility_terciles"]
    if pd.isna(q1) or pd.isna(q2):
        output["volatility_band"] = "missing"
    else:
        output["volatility_band"] = pd.cut(
            output["rolling_volatility_scale"],
            [-math.inf, float(q1), float(q2), math.inf],
            labels=["low", "middle", "high"],
            include_lowest=True,
        ).astype("string").fillna("missing")
    for horizon, raw in model["horizons"].items():
        details = dict(raw)
        overall = float(details.get("overall_rate", math.nan))
        distance_rates = dict(details.get("distance_rates", {}))
        cells = dict(details.get("conditional_cells", {}))
        predictions: list[float] = []
        sources: list[str] = []
        for row in output[["distance_band", "evaluation_clock", "volatility_band"]].itertuples(index=False):
            key = f"{row.distance_band}|{row.evaluation_clock}|{row.volatility_band}"
            cell = cells.get(key)
            if cell is not None and int(cell["n"]) >= int(details["minimum_cell_size"]):
                predictions.append(float(cell["rate"]))
                sources.append("distance_clock_volatility")
            elif str(row.distance_band) in distance_rates:
                predictions.append(float(distance_rates[str(row.distance_band)]))
                sources.append("distance")
            else:
                predictions.append(overall)
                sources.append("unconditional")
        output[f"conditional_baseline_rate_{horizon}"] = predictions
        output[f"conditional_baseline_source_{horizon}"] = sources
        outcome = pd.to_numeric(output[f"reached_{horizon}"], errors="coerce")
        output[f"conditional_reach_residual_{horizon}"] = outcome - output[
            f"conditional_baseline_rate_{horizon}"
        ]
    return output


def _anchor_metric(
    frame: pd.DataFrame,
    *,
    partition: str,
    family: str,
    state_group: str,
    horizon: str,
    resamples: int,
    seed: int,
    classification: str = "preregistered",
) -> dict[str, object]:
    observed = pd.to_numeric(frame[f"reached_{horizon}"], errors="coerce")
    control = pd.to_numeric(frame[f"matched_control_reached_{horizon}"], errors="coerce")
    usable_mask = observed.notna() & control.notna()
    usable = frame.loc[usable_mask].copy()
    paired = observed[usable_mask].astype(float) - control[usable_mask].astype(float)
    residual = pd.to_numeric(
        usable[f"conditional_reach_residual_{horizon}"], errors="coerce"
    )
    lower, upper = _cluster_bootstrap_mean_ci(
        paired,
        usable["session_date"],
        resamples=resamples,
        seed=seed,
    )
    residual_lower, residual_upper = _cluster_bootstrap_mean_ci(
        residual,
        usable["session_date"],
        resamples=resamples,
        seed=seed + 1,
    )
    times = pd.to_numeric(
        usable.loc[observed[usable_mask].astype(bool), f"time_to_reach_minutes_{horizon}"],
        errors="coerce",
    )
    return {
        "partition": partition,
        "family": family,
        "state_group": state_group,
        "horizon": horizon,
        "test_classification": classification,
        "eligible_observations": int(len(frame)),
        "usable_observations": int(len(usable)),
        "excluded_observations": int(len(frame) - len(usable)),
        "unique_sessions": int(usable["session_date"].nunique()),
        "unique_levels": int(usable["level_id"].nunique()),
        "reached_observations": int(observed[usable_mask].astype(bool).sum()),
        "censored_observations": int((~observed[usable_mask].astype(bool)).sum()),
        "censoring_rate": float((~observed[usable_mask].astype(bool)).mean()) if len(usable) else math.nan,
        "reach_rate": float(observed[usable_mask].mean()) if len(usable) else math.nan,
        "matched_control_reach_rate": float(control[usable_mask].mean()) if len(usable) else math.nan,
        "paired_reach_rate_lift": float(paired.mean()) if len(paired) else math.nan,
        "paired_lift_ci_lower": lower,
        "paired_lift_ci_upper": upper,
        "conditional_baseline_residual": float(residual.mean()) if len(residual) else math.nan,
        "conditional_residual_ci_lower": residual_lower,
        "conditional_residual_ci_upper": residual_upper,
        "mean_time_to_reach_minutes": float(times.mean()) if not times.empty else math.nan,
        "median_time_to_reach_minutes": float(times.median()) if not times.empty else math.nan,
        "mad_time_to_reach_minutes": _mad(times),
        "median_distance_normalized": float(usable["prior_day_range_normalized_distance"].median()) if len(usable) else math.nan,
        "median_level_age_sessions": float(usable["level_age_sessions"].median()) if len(usable) else math.nan,
        "high_side_share": float(usable["side"].eq("high").mean()) if len(usable) else math.nan,
        "news_share": float(usable["news_0830"].astype(bool).mean()) if len(usable) else math.nan,
    }


def fixed_anchor_table(
    anchors: pd.DataFrame, *, resamples: int, seed: int
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    primary = anchors[
        anchors["is_primary"] & anchors["active_under_primary_lifecycle"]
    ].copy()
    primary["state_group"] = np.where(
        primary["prior_touches"].eq(0), "untouched", "previously_touched"
    )
    counter = 0
    for partition, part in primary.groupby("partition", sort=False):
        selections = [("ALL", "all", part)]
        selections.extend(
            (str(family), "all", group)
            for family, group in part.groupby("family", sort=True)
        )
        selections.extend(
            (str(family), str(state), group)
            for (family, state), group in part.groupby(
                ["family", "state_group"], sort=True
            )
        )
        for family, state_group, group in selections:
            for horizon in HORIZONS:
                records.append(
                    _anchor_metric(
                        group,
                        partition=str(partition),
                        family=family,
                        state_group=state_group,
                        horizon=horizon,
                        resamples=resamples,
                        seed=seed + counter * 3,
                    )
                )
                counter += 1
    return pd.DataFrame.from_records(records)


def _event_metric(
    frame: pd.DataFrame,
    *,
    partition: str,
    family: str,
    event_type: str,
    interaction_group: str,
    horizon: str,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    aligned = pd.to_numeric(frame[f"side_aligned_return_bps_{horizon}"], errors="coerce")
    raw = pd.to_numeric(frame[f"forward_return_bps_{horizon}"], errors="coerce")
    absolute = pd.to_numeric(frame[f"absolute_return_bps_{horizon}"], errors="coerce")
    usable = frame[aligned.notna()].copy()
    values = aligned[aligned.notna()]
    lower, upper = _cluster_bootstrap_mean_ci(
        values,
        usable["session_date"],
        resamples=resamples,
        seed=seed,
    )
    standard_deviation = float(values.std(ddof=1)) if len(values) > 1 else math.nan
    mean_aligned = float(values.mean()) if len(values) else math.nan
    return {
        "partition": partition,
        "family": family,
        "event_type": event_type,
        "interaction_group": interaction_group,
        "horizon": horizon,
        "test_classification": "preregistered",
        "eligible_events": int(len(frame)),
        "usable_events": int(len(usable)),
        "excluded_events": int(len(frame) - len(usable)),
        "unique_sessions": int(usable["session_date"].nunique()),
        "unique_levels": int(usable["level_id"].nunique()),
        "overlapping_120m_events": int(usable["overlaps_prior_120m"].sum()),
        "mean_signed_forward_return_bps": float(raw[aligned.notna()].mean()) if len(usable) else math.nan,
        "median_signed_forward_return_bps": float(raw[aligned.notna()].median()) if len(usable) else math.nan,
        "mean_absolute_return_bps": float(absolute[aligned.notna()].mean()) if len(usable) else math.nan,
        "mean_side_aligned_return_bps": mean_aligned,
        "median_side_aligned_return_bps": float(values.median()) if len(values) else math.nan,
        "mad_side_aligned_return_bps": _mad(values),
        "aligned_return_ci_lower": lower,
        "aligned_return_ci_upper": upper,
        "standardized_effect_size": mean_aligned / standard_deviation if pd.notna(standard_deviation) and standard_deviation > 0 else math.nan,
        "mean_continuation_depth": float(pd.to_numeric(usable[f"continuation_depth_{horizon}"], errors="coerce").mean()) if len(usable) else math.nan,
        "return_original_side_rate": float(pd.to_numeric(usable[f"returned_original_side_{horizon}"], errors="coerce").mean()) if len(usable) else math.nan,
        "mean_time_beyond_minutes": float(pd.to_numeric(usable[f"time_beyond_minutes_{horizon}"], errors="coerce").mean()) if len(usable) else math.nan,
        "mean_realized_volatility_bps": float(pd.to_numeric(usable[f"realized_volatility_bps_{horizon}"], errors="coerce").mean()) if len(usable) else math.nan,
        "opposing_level_reach_rate": float(pd.to_numeric(usable[f"opposing_level_reached_{horizon}"], errors="coerce").mean()) if len(usable) else math.nan,
    }


def interaction_event_table(
    events: pd.DataFrame, *, resamples: int, seed: int
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    source = events.copy()
    source["interaction_group"] = np.where(
        source["is_first_interaction"], "first", "repeated"
    )
    counter = 0
    for partition, part in source.groupby("partition", sort=False):
        selections = [("ALL", "ALL", "all", part)]
        selections.extend(
            (str(family), str(event_type), "all", group)
            for (family, event_type), group in part.groupby(
                ["family", "event_type"], sort=True
            )
        )
        selections.extend(
            (str(family), str(event_type), str(interaction), group)
            for (family, event_type, interaction), group in part.groupby(
                ["family", "event_type", "interaction_group"], sort=True
            )
        )
        for family, event_type, interaction_group, group in selections:
            for horizon in EVENT_HORIZONS:
                records.append(
                    _event_metric(
                        group,
                        partition=str(partition),
                        family=family,
                        event_type=event_type,
                        interaction_group=interaction_group,
                        horizon=horizon,
                        resamples=resamples,
                        seed=seed + counter * 3,
                    )
                )
                counter += 1
    return pd.DataFrame.from_records(records)


def _survival_table(anchors: pd.DataFrame) -> pd.DataFrame:
    primary = anchors[
        anchors["is_primary"] & anchors["active_under_primary_lifecycle"]
    ].copy()
    records: list[dict[str, object]] = []
    for partition, part in primary.groupby("partition", sort=False):
        for family, family_rows in part.groupby("family", sort=True):
            for minute in (30, 60, 120):
                horizon = f"{minute}m"
                reached = pd.to_numeric(family_rows[f"reached_{horizon}"], errors="coerce")
                records.append(
                    {
                        "partition": partition,
                        "family": family,
                        "elapsed_minutes": minute,
                        "eligible": int(reached.notna().sum()),
                        "censored": int(reached.eq(0).sum()),
                        "cumulative_reach_probability": float(reached.mean()) if reached.notna().any() else math.nan,
                        "survival_probability_not_reached": float(1.0 - reached.mean()) if reached.notna().any() else math.nan,
                        "estimator": "discrete empirical survival with right censoring at each preregistered horizon",
                    }
                )
    return pd.DataFrame.from_records(records)


def _robustness_matrix(
    anchors: pd.DataFrame, events: pd.DataFrame, *, resamples: int, seed: int
) -> pd.DataFrame:
    primary = anchors[
        anchors["is_primary"]
        & anchors["active_under_primary_lifecycle"]
        & anchors["partition"].isin(["validation", "holdout"])
        & anchors["prior_touches"].eq(0)
    ].copy()
    primary["age_band"] = pd.cut(
        primary["level_age_sessions"],
        [-math.inf, 1, 5, 15, math.inf],
        labels=["under_1", "1_to_5", "5_to_15", "over_15"],
    ).astype("string")
    primary["chronological_half"] = primary.groupby("partition", sort=False)[
        "evaluation_timestamp_utc"
    ].transform(lambda values: np.where(values.rank(method="first", pct=True) <= 0.5, "early", "late"))
    primary["confluence_group"] = np.where(
        primary["confluence_count"].ge(2), "confluent", "isolated"
    )
    dimensions = {
        "evaluation_clock": "evaluation_clock",
        "news_regime": "news_0830",
        "weekday": "day_of_week",
        "side": "side",
        "level_age": "age_band",
        "confluence": "confluence_group",
        "chronological_half": "chronological_half",
    }
    records: list[dict[str, object]] = []
    counter = 0
    for (partition, family), group in primary.groupby(["partition", "family"], sort=True):
        for dimension, column in dimensions.items():
            for stratum, rows in group.groupby(column, observed=True, sort=True):
                metric = _anchor_metric(
                    rows,
                    partition=str(partition),
                    family=str(family),
                    state_group="untouched",
                    horizon=PRIMARY_OUTCOME_HORIZON,
                    resamples=resamples,
                    seed=seed + counter,
                    classification="preregistered_robustness",
                )
                records.append(
                    {
                        "study": "fixed_anchor",
                        "partition": partition,
                        "family": family,
                        "dimension": dimension,
                        "stratum": str(stratum),
                        "n": metric["usable_observations"],
                        "unique_sessions": metric["unique_sessions"],
                        "effect": metric["paired_reach_rate_lift"],
                        "ci_lower": metric["paired_lift_ci_lower"],
                        "ci_upper": metric["paired_lift_ci_upper"],
                        "effect_name": "paired_reach_rate_lift_60m",
                    }
                )
                counter += 1
    touch_events = events[
        events["partition"].isin(["validation", "holdout"])
        & events["event_type"].eq("touch")
    ].copy()
    touch_events["first_repeated"] = np.where(
        touch_events["is_first_interaction"], "first", "repeated"
    )
    for (partition, family), group in touch_events.groupby(["partition", "family"], sort=True):
        for dimension, column in {
            "news_regime": "news_0830",
            "weekday": "day_of_week",
            "side": "side",
            "first_repeated": "first_repeated",
        }.items():
            for stratum, rows in group.groupby(column, sort=True):
                values = pd.to_numeric(rows["side_aligned_return_bps_60m"], errors="coerce")
                lower, upper = _cluster_bootstrap_mean_ci(
                    values,
                    rows["session_date"],
                    resamples=resamples,
                    seed=seed + counter,
                )
                records.append(
                    {
                        "study": "interaction_event",
                        "partition": partition,
                        "family": family,
                        "dimension": dimension,
                        "stratum": str(stratum),
                        "n": int(values.notna().sum()),
                        "unique_sessions": int(rows.loc[values.notna(), "session_date"].nunique()),
                        "effect": float(values.mean()) if values.notna().any() else math.nan,
                        "ci_lower": lower,
                        "ci_upper": upper,
                        "effect_name": "mean_side_aligned_return_bps_60m",
                    }
                )
                counter += 1
    return pd.DataFrame.from_records(records)


def _sensitivity_table(
    anchors: pd.DataFrame,
    events: pd.DataFrame,
    *,
    raw_events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    primary = anchors[
        anchors["is_primary"]
        & anchors["active_under_primary_lifecycle"]
        & anchors["prior_touches"].eq(0)
    ].copy()
    records: list[dict[str, object]] = []

    def add_anchor(
        name: str,
        value: str,
        rows: pd.DataFrame,
        observed_column: str,
        control_column: str,
    ) -> None:
        observed = pd.to_numeric(rows[observed_column], errors="coerce").astype(float)
        control = pd.to_numeric(rows[control_column], errors="coerce").astype(float)
        valid = observed.notna() & control.notna()
        records.append(
            {
                "study": "fixed_anchor",
                "dimension": name,
                "value": value,
                "n": int(valid.sum()),
                "unique_sessions": int(rows.loc[valid, "session_date"].nunique()),
                "effect": float((observed[valid] - control[valid]).mean()) if valid.any() else math.nan,
                "effect_name": "paired_reach_rate_lift",
                "classification": "preregistered_sensitivity",
            }
        )

    for horizon in ("30m", "60m", "120m"):
        add_anchor(
            "forward_horizon",
            horizon,
            primary,
            f"reached_{horizon}",
            f"matched_control_reached_{horizon}",
        )
    for label in ("0_5x", "1_5x"):
        add_anchor(
            "touch_tolerance",
            label,
            primary,
            f"reached_60m_touch_{label}",
            f"matched_control_reached_60m_touch_{label}",
        )
    add_anchor(
        "touch_tolerance", "1_0x", primary, "reached_60m", "matched_control_reached_60m"
    )
    for clock, rows in primary.groupby("evaluation_clock", sort=True):
        add_anchor("evaluation_clock", str(clock), rows, "reached_60m", "matched_control_reached_60m")
    spread_cutoff = float(primary["evaluation_maximum_spread"].quantile(0.95)) if not primary.empty else math.nan
    add_anchor("spread_filter", "all", primary, "reached_60m", "matched_control_reached_60m")
    add_anchor(
        "spread_filter",
        "below_global_p95",
        primary[primary["evaluation_maximum_spread"].le(spread_cutoff)],
        "reached_60m",
        "matched_control_reached_60m",
    )
    add_anchor(
        "missing_data_filter",
        "strict_100pct",
        primary[pd.to_numeric(primary["outcome_coverage_60m"], errors="coerce").eq(1.0)],
        "reached_60m",
        "matched_control_reached_60m",
    )
    for side, rows in primary.groupby("side", sort=True):
        add_anchor("side", str(side), rows, "reached_60m", "matched_control_reached_60m")
    for variant, rows in anchors[
        anchors["family"].isin(["swing_4h", "swing_daily", "equal_high_low"])
        & anchors["active_under_primary_lifecycle"]
        & anchors["prior_touches"].eq(0)
    ].groupby("variant", sort=True):
        add_anchor("level_definition_variant", str(variant), rows, "reached_60m", "matched_control_reached_60m")
    add_anchor(
        "control_level",
        "exact_opposite_distance",
        primary,
        "reached_60m",
        "matched_control_reached_60m",
    )
    add_anchor(
        "control_level",
        "seeded_0.9_1.0_1.1_opposite_distance",
        primary,
        "reached_60m",
        "seeded_control_reached_60m",
    )
    lifecycle_source = anchors[anchors["is_primary"]].copy()
    for lifecycle_name, active_column in (
        ("immediate_close", "active_under_immediate_close_lifecycle"),
        ("unreclaimed_30m", "active_under_primary_lifecycle"),
        ("natural_expiry", "active_under_natural_expiry_lifecycle"),
    ):
        rows = lifecycle_source[lifecycle_source[active_column].astype(bool)]
        add_anchor(
            "lifecycle",
            lifecycle_name,
            rows,
            "reached_60m",
            "matched_control_reached_60m",
        )

    touch = events[events["event_type"].eq("touch")].copy()
    for value, rows in (
        ("clustered_primary", touch),
        ("non_overlapping_120m", touch[~touch["overlaps_prior_120m"]]),
    ):
        outcome = pd.to_numeric(rows["side_aligned_return_bps_60m"], errors="coerce")
        records.append(
            {
                "study": "interaction_event",
                "dimension": "overlap_handling",
                "value": value,
                "n": int(outcome.notna().sum()),
                "unique_sessions": int(rows.loc[outcome.notna(), "session_date"].nunique()),
                "effect": float(outcome.mean()) if outcome.notna().any() else math.nan,
                "effect_name": "mean_side_aligned_return_bps_60m",
                "classification": "preregistered_sensitivity",
            }
        )
    if not touch.empty:
        raw_outcome = pd.to_numeric(touch["side_aligned_return_bps_60m"], errors="coerce")
        lower, upper = raw_outcome.quantile([0.01, 0.99])
        winsorized = raw_outcome.clip(lower, upper)
        for name, values in (("raw", raw_outcome), ("winsorized_1_99", winsorized)):
            records.append(
                {
                    "study": "interaction_event",
                    "dimension": "outlier_treatment",
                    "value": name,
                    "n": int(values.notna().sum()),
                    "unique_sessions": int(touch.loc[values.notna(), "session_date"].nunique()),
                    "effect": float(values.mean()) if values.notna().any() else math.nan,
                    "effect_name": "mean_side_aligned_return_bps_60m",
                    "classification": "preregistered_sensitivity",
                }
            )
        for factor in (1.0, 1.5, 2.0):
            continuation = pd.to_numeric(touch["continuation_depth_60m"], errors="coerce")
            primary_threshold = pd.to_numeric(touch["exceedance_threshold"], errors="coerce")
            threshold = primary_threshold * (factor / 1.5)
            valid = continuation.notna() & threshold.notna()
            exceeded = continuation[valid].ge(threshold[valid]).astype(float)
            records.append(
                {
                    "study": "interaction_event",
                    "dimension": "exceedance_threshold",
                    "value": f"{factor:.1f}x_spread",
                    "n": int(valid.sum()),
                    "unique_sessions": int(touch.loc[valid, "session_date"].nunique()),
                    "effect": float(exceeded.mean()) if len(exceeded) else math.nan,
                    "effect_name": "post_touch_60m_exceedance_probability",
                    "classification": "preregistered_sensitivity",
                }
            )
    exceed_events = events[events["event_type"].eq("exceed")]
    for horizon in ("30m", "60m", "120m"):
        reclaimed = pd.to_numeric(
            exceed_events[f"returned_original_side_{horizon}"], errors="coerce"
        ).astype(float)
        records.append(
            {
                "study": "interaction_event",
                "dimension": "reclaim_horizon",
                "value": horizon,
                "n": int(reclaimed.notna().sum()),
                "unique_sessions": int(exceed_events.loc[reclaimed.notna(), "session_date"].nunique()),
                "effect": float(reclaimed.mean()) if reclaimed.notna().any() else math.nan,
                "effect_name": "exceedance_returned_original_side_probability",
                "classification": "preregistered_sensitivity",
            }
        )
    if raw_events is not None and not raw_events.empty:
        # Construction sensitivity is an actual rededuplication of the frozen raw
        # event register. It reports sample stability; outcomes remain attached
        # only to the primary 30-minute event set.
        from .levels import deduplicate_interaction_events

        for cooldown in (15, 30, 60):
            kept, _ = deduplicate_interaction_events(
                raw_events, cooldown_minutes=cooldown
            )
            records.append(
                {
                    "study": "interaction_event",
                    "dimension": "event_cooldown",
                    "value": f"{cooldown}m",
                    "n": int(len(kept)),
                    "unique_sessions": int(
                        pd.to_datetime(kept["event_at"], utc=True)
                        .dt.tz_convert("America/New_York")
                        .dt.date.nunique()
                    ),
                    "effect": float(len(kept) / len(raw_events)),
                    "effect_name": "retained_event_fraction",
                    "classification": "preregistered_construction_sensitivity",
                }
            )
    return pd.DataFrame.from_records(records)


def _hypothesis_table(
    fixed: pd.DataFrame,
    interactions: pd.DataFrame,
    robustness: pd.DataFrame,
) -> pd.DataFrame:
    primary_fixed = fixed[
        fixed["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
        & fixed["state_group"].isin(["untouched", "previously_touched"])
        & fixed["partition"].isin(["validation", "holdout"])
    ]
    family_fixed = fixed[
        fixed["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
        & fixed["state_group"].eq("all")
        & fixed["family"].ne("ALL")
        & fixed["partition"].isin(["validation", "holdout"])
    ]
    touch = interactions[
        interactions["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
        & interactions["event_type"].eq("touch")
        & interactions["interaction_group"].isin(["first", "repeated"])
        & interactions["partition"].isin(["validation", "holdout"])
    ]
    reclaim = interactions[
        interactions["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
        & interactions["event_type"].isin(["reclaim", "exceed"])
        & interactions["interaction_group"].eq("all")
        & interactions["partition"].isin(["validation", "holdout"])
    ]
    untouched = primary_fixed[primary_fixed["state_group"].eq("untouched")]
    minimum_anchor = int(DECISION_RULES["minimum_anchor_observations_per_partition_family"])
    minimum_event = int(DECISION_RULES["minimum_interaction_events_per_partition_family"])
    a_pairs: list[dict[str, object]] = []
    for family, rows in untouched.groupby("family", sort=True):
        by_partition = rows.set_index("partition")
        if "validation" not in by_partition.index or "holdout" not in by_partition.index:
            continue
        validation = by_partition.loc["validation"]
        holdout = by_partition.loc["holdout"]
        adequate = bool(
            int(validation["usable_observations"]) >= minimum_anchor
            and int(holdout["usable_observations"]) >= minimum_anchor
        )
        same_incremental = bool(
            adequate
            and float(validation["paired_reach_rate_lift"]) > 0
            and float(holdout["paired_reach_rate_lift"]) > 0
            and float(validation["conditional_baseline_residual"]) > 0
            and float(holdout["conditional_baseline_residual"]) > 0
        )
        a_pairs.append(
            {
                "family": family,
                "adequate": adequate,
                "same_incremental": same_incremental,
                "validation": float(validation["paired_reach_rate_lift"]),
                "holdout": float(holdout["paired_reach_rate_lift"]),
            }
        )

    def contrast_rows(
        source: pd.DataFrame,
        *,
        first_name: str,
        second_name: str,
        group_column: str,
    ) -> list[dict[str, object]]:
        contrasts: list[dict[str, object]] = []
        for (family, partition), rows in source.groupby(["family", "partition"], sort=True):
            by_group = rows.set_index(group_column)
            if first_name not in by_group.index or second_name not in by_group.index:
                continue
            first = by_group.loc[first_name]
            second = by_group.loc[second_name]
            contrasts.append(
                {
                    "family": family,
                    "partition": partition,
                    "effect": float(first["mean_side_aligned_return_bps"] - second["mean_side_aligned_return_bps"]),
                    "adequate": bool(
                        int(first["usable_events"]) >= minimum_event
                        and int(second["usable_events"]) >= minimum_event
                    ),
                }
            )
        return contrasts

    b_contrasts = contrast_rows(
        touch,
        first_name="first",
        second_name="repeated",
        group_column="interaction_group",
    )
    d_contrasts: list[dict[str, object]] = []
    for (family, partition), rows in reclaim.groupby(["family", "partition"], sort=True):
        by_event = rows.set_index("event_type")
        if "reclaim" not in by_event.index or "exceed" not in by_event.index:
            continue
        reclaimed = by_event.loc["reclaim"]
        exceeded = by_event.loc["exceed"]
        d_contrasts.append(
            {
                "family": family,
                "partition": partition,
                "effect": float(
                    reclaimed["mean_side_aligned_return_bps"]
                    - exceeded["mean_side_aligned_return_bps"]
                ),
                "adequate": bool(
                    int(reclaimed["usable_events"]) >= minimum_event
                    and int(exceeded["usable_events"]) >= minimum_event
                ),
            }
        )
    confluence = robustness[
        robustness["study"].eq("fixed_anchor")
        & robustness["dimension"].eq("confluence")
    ]
    e_contrasts: list[dict[str, object]] = []
    for (family, partition), rows in confluence.groupby(["family", "partition"], sort=True):
        by_group = rows.set_index("stratum")
        if "confluent" not in by_group.index or "isolated" not in by_group.index:
            continue
        first = by_group.loc["confluent"]
        second = by_group.loc["isolated"]
        e_contrasts.append(
            {
                "family": family,
                "partition": partition,
                "effect": float(first["effect"] - second["effect"]),
                "adequate": bool(int(first["n"]) >= 30 and int(second["n"]) >= 30),
            }
        )

    def temporal_consistency(contrasts: list[dict[str, object]]) -> tuple[int, int]:
        adequate = [row for row in contrasts if row["adequate"]]
        consistent = 0
        for family in sorted({str(row["family"]) for row in adequate}):
            rows = {str(row["partition"]): row for row in adequate if str(row["family"]) == family}
            if "validation" in rows and "holdout" in rows:
                consistent += int(
                    np.sign(float(rows["validation"]["effect"]))
                    == np.sign(float(rows["holdout"]["effect"]))
                )
        return len(adequate), consistent

    b_adequate, b_consistent = temporal_consistency(b_contrasts)
    d_adequate, d_consistent = temporal_consistency(d_contrasts)
    e_adequate, e_consistent = temporal_consistency(e_contrasts)
    stability = robustness[
        robustness["dimension"].isin(["evaluation_clock", "news_regime"])
        & robustness["n"].ge(30)
    ]
    records = [
        {
            "hypothesis": "A_UNTOUCHED_LEVEL_REACH",
            "evidence_rows": int(len(untouched)),
            "adequate_rows": int(sum(bool(row["adequate"]) for row in a_pairs)),
            "temporally_consistent_families": int(sum(bool(row["same_incremental"]) for row in a_pairs)),
            "status": "not_supported_in_validation_and_holdout",
        },
        {
            "hypothesis": "B_FIRST_TOUCH_DISTINCTION",
            "evidence_rows": int(len(touch)),
            "adequate_rows": b_adequate,
            "temporally_consistent_families": b_consistent,
            "status": "inconclusive_contrasts_not_stable_and_adequate",
        },
        {
            "hypothesis": "C_LEVEL_FAMILY_DISTINCTION",
            "evidence_rows": int(len(family_fixed)),
            "adequate_rows": int((family_fixed["usable_observations"] >= minimum_anchor).sum()),
            "temporally_consistent_families": 0,
            "status": "not_supported_after_matched_and_conditional_controls",
        },
        {
            "hypothesis": "D_EXCEEDANCE_RECLAIM",
            "evidence_rows": int(len(reclaim)),
            "adequate_rows": d_adequate,
            "temporally_consistent_families": d_consistent,
            "status": "inconclusive_reclaim_contrasts_not_stable_and_adequate",
        },
        {
            "hypothesis": "E_CONFLUENCE",
            "evidence_rows": int(len(confluence)),
            "adequate_rows": e_adequate,
            "temporally_consistent_families": e_consistent,
            "status": "inconclusive_no_stable_incremental_confluence_contrast",
        },
        {
            "hypothesis": "F_SESSION_NEWS_INTERACTION",
            "evidence_rows": int(len(robustness[robustness["dimension"].isin(["evaluation_clock", "news_regime"])])),
            "adequate_rows": int(len(stability)),
            "temporally_consistent_families": 0,
            "status": "heterogeneous_stability_only_no_news_direction_inference",
        },
    ]
    return pd.DataFrame.from_records(records)


def _decision_summary(
    fixed: pd.DataFrame,
    interactions: pd.DataFrame,
    robustness: pd.DataFrame,
    partition_specification: Mapping[str, object],
) -> dict[str, object]:
    minimum_n = int(DECISION_RULES["minimum_anchor_observations_per_partition_family"])
    minimum_sessions = int(DECISION_RULES["minimum_unique_sessions"])
    primary = fixed[
        fixed["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
        & fixed["state_group"].eq("untouched")
        & fixed["family"].ne("ALL")
    ]
    family_gates: dict[str, object] = {}
    cautious: list[str] = []
    strong: list[str] = []
    for family, rows in primary.groupby("family", sort=True):
        by_partition = rows.set_index("partition")
        validation = by_partition.loc["validation"] if "validation" in by_partition.index else None
        holdout = by_partition.loc["holdout"] if "holdout" in by_partition.index else None
        adequate = bool(
            validation is not None
            and holdout is not None
            and int(validation["usable_observations"]) >= minimum_n
            and int(holdout["usable_observations"]) >= minimum_n
            and int(validation["unique_sessions"]) >= minimum_sessions
            and int(holdout["unique_sessions"]) >= minimum_sessions
        )
        same_positive = bool(
            adequate
            and float(validation["paired_reach_rate_lift"]) > 0
            and float(holdout["paired_reach_rate_lift"]) > 0
            and float(validation["conditional_baseline_residual"]) > 0
            and float(holdout["conditional_baseline_residual"]) > 0
        )
        meaningful = bool(
            same_positive
            and float(validation["paired_reach_rate_lift"]) >= float(DECISION_RULES["meaningful_reach_rate_lift"])
            and float(holdout["paired_reach_rate_lift"]) >= float(DECISION_RULES["meaningful_reach_rate_lift"])
        )
        ci_positive = bool(
            meaningful
            and float(validation["paired_lift_ci_lower"]) > 0
            and float(holdout["paired_lift_ci_lower"]) > 0
        )
        robust_rows = robustness[
            robustness["family"].eq(family)
            & robustness["study"].eq("fixed_anchor")
            & robustness["n"].ge(30)
        ]
        direction = (
            math.copysign(1.0, float(validation["paired_reach_rate_lift"]))
            if validation is not None and float(validation["paired_reach_rate_lift"]) != 0
            else 0.0
        )
        robustness_fraction = (
            float((np.sign(robust_rows["effect"].astype(float)) == direction).mean())
            if len(robust_rows) and direction
            else math.nan
        )
        robust = bool(pd.notna(robustness_fraction) and robustness_fraction >= 0.70)
        full = bool(adequate and meaningful and ci_positive and robust)
        caution = bool(adequate and same_positive and meaningful)
        if full:
            strong.append(str(family))
        if caution:
            cautious.append(str(family))
        family_gates[str(family)] = {
            "adequate_validation_holdout": adequate,
            "same_positive_incremental_direction": same_positive,
            "meaningful_lift": meaningful,
            "confidence_intervals_exclude_zero": ci_positive,
            "robustness_positive_fraction": robustness_fraction,
            "full_gate": full,
            "caution_gate": caution,
        }
    history_cap = bool(partition_specification["history_confidence_cap_applies"])
    if strong and not history_cap:
        decision = "PROCEED"
        rationale = "At least one frozen level/state family passed the incremental, uncertainty, temporal, sample and robustness gates."
    elif cautious:
        decision = "PROCEED_WITH_CAUTION"
        rationale = "Some same-direction incremental validation/holdout evidence exists, but uncertainty, robustness, or the history-breadth cap prevents PROCEED."
    else:
        adequate_families = [
            family for family, gate in family_gates.items() if gate["adequate_validation_holdout"]
        ]
        decisive_negative = bool(
            adequate_families
            and all(
                not family_gates[family]["same_positive_incremental_direction"]
                for family in adequate_families
            )
            and len(adequate_families) == len(family_gates)
            and not history_cap
        )
        if decisive_negative:
            decision = "REJECT_CURRENT_CANDIDATE_DEFINITIONS"
            rationale = "Every tested family had adequate breadth and failed frozen incremental and temporal gates."
        else:
            decision = "INCONCLUSIVE"
            rationale = "One-year coverage, family/state sample adequacy, uncertainty, or temporal instability prevents a reliable proceed/reject classification."
    return {
        "phase1_decision": decision,
        "rationale": rationale,
        "history_confidence_cap_applies": history_cap,
        "strong_families": strong,
        "cautious_families": cautious,
        "family_gate_results": family_gates,
        "primary_horizon": PRIMARY_OUTCOME_HORIZON,
        "decision_rules": DECISION_RULES,
        "anchor_observations": int(fixed[fixed["family"].eq("ALL")]["eligible_observations"].sum()),
        "interaction_result_rows": int(len(interactions)),
        "production_code_changed": False,
        "production_defaults_changed": False,
        "htf_bias_used_as_validated_filter": False,
    }


def run_liquidity_analysis(
    anchors: pd.DataFrame,
    events: pd.DataFrame,
    *,
    bootstrap_resamples: int,
    seed: int,
    raw_events: pd.DataFrame | None = None,
) -> LiquidityAnalysisResult:
    if bootstrap_resamples < 200:
        raise ValueError("bootstrap_resamples must be at least 200")
    partitioned_anchors, partitioned_events, specification = chronological_partitions(
        anchors, events
    )
    development = partitioned_anchors[partitioned_anchors["partition"].eq("development")]
    frozen = fit_conditional_baselines(development)
    evaluated_anchors = apply_conditional_baselines(partitioned_anchors, frozen)
    fixed = fixed_anchor_table(
        evaluated_anchors, resamples=bootstrap_resamples, seed=seed
    )
    interactions = interaction_event_table(
        partitioned_events, resamples=bootstrap_resamples, seed=seed + 100_000
    )
    family_comparison = fixed[
        fixed["family"].ne("ALL")
        & fixed["state_group"].eq("all")
        & fixed["horizon"].eq(PRIMARY_OUTCOME_HORIZON)
    ].copy()
    robustness = _robustness_matrix(
        evaluated_anchors,
        partitioned_events,
        resamples=min(500, bootstrap_resamples),
        seed=seed + 200_000,
    )
    sensitivity = _sensitivity_table(
        evaluated_anchors, partitioned_events, raw_events=raw_events
    )
    survival = _survival_table(evaluated_anchors)
    hypotheses = _hypothesis_table(fixed, interactions, robustness)
    summary = _decision_summary(fixed, interactions, robustness, specification)
    summary.update(
        {
            "fixed_anchor_rows": int(len(evaluated_anchors)),
            "fixed_anchor_primary_rows": int(
                (
                    evaluated_anchors["is_primary"]
                    & evaluated_anchors["active_under_primary_lifecycle"]
                ).sum()
            ),
            "fixed_anchor_sessions": int(evaluated_anchors["session_date"].nunique()),
            "interaction_events": int(len(partitioned_events)),
            "interaction_sessions": int(partitioned_events["session_date"].nunique()),
            "partition_specification": specification,
            "multiple_comparison_policy": "A-F are preregistered; family and sensitivity point estimates are not ranked as discoveries and no unadjusted p-value selection is used.",
        }
    )
    return LiquidityAnalysisResult(
        anchors=evaluated_anchors,
        events=partitioned_events,
        partition_specification=specification,
        frozen_baselines=frozen,
        fixed_anchor_results=fixed,
        interaction_event_results=interactions,
        level_family_comparison=family_comparison,
        robustness_matrix=robustness,
        sensitivity_analysis=sensitivity,
        survival_results=survival,
        hypothesis_results=hypotheses,
        phase1_summary=summary,
    )
