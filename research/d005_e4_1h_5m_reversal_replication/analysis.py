"""Preregistered inference and hard classification for D005_E4."""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from research.d005_e3_early_context_anchor_study.analysis import (
    benjamini_hochberg,
)

from .config import ReversalReplicationConfig


def _cell_seed(
    config: ReversalReplicationConfig,
    *parts: object,
) -> int:
    digest = hashlib.sha256(
        "|".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return (config.bootstrap_seed + int(digest[:8], 16)) % (2**32)


def bootstrap_mean_interval(
    values: Iterable[float],
    *,
    config: ReversalReplicationConfig,
    seed_parts: Sequence[object],
) -> tuple[float, float, float]:
    clean = np.asarray(list(values), dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size < 2:
        return np.nan, np.nan, np.nan
    generator = np.random.default_rng(
        _cell_seed(config, *seed_parts)
    )
    means = np.empty(config.bootstrap_resamples, dtype=float)
    chunk = 50
    for left in range(0, config.bootstrap_resamples, chunk):
        right = min(config.bootstrap_resamples, left + chunk)
        indices = generator.integers(
            0, clean.size, size=(right - left, clean.size)
        )
        means[left:right] = clean[indices].mean(axis=1)
    tail = (1.0 - config.confidence_level) / 2.0
    return (
        float(np.quantile(means, tail)),
        float(np.quantile(means, 1.0 - tail)),
        float(means.std(ddof=1)),
    )


def _mean_interval(
    values: np.ndarray,
    confidence_level: float,
) -> tuple[float, float, float, float]:
    clean = values[np.isfinite(values)]
    if clean.size < 2:
        return np.nan, np.nan, np.nan, np.nan
    standard_deviation = float(clean.std(ddof=1))
    standard_error = standard_deviation / math.sqrt(clean.size)
    critical = float(
        stats.t.ppf(
            (1.0 + confidence_level) / 2.0, clean.size - 1
        )
    )
    mean = float(clean.mean())
    return (
        standard_deviation,
        standard_error,
        mean - critical * standard_error,
        mean + critical * standard_error,
    )


def metric_record(
    frame: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
    seed_parts: Sequence[object],
) -> dict[str, object]:
    unique = frame.drop_duplicates("sequence_id")
    movement = unique["signed_forward_movement"].dropna().to_numpy(
        dtype=float
    )
    count = len(movement)
    mean = float(movement.mean()) if count else np.nan
    median = float(np.median(movement)) if count else np.nan
    standard_deviation, standard_error, lower, upper = _mean_interval(
        movement, config.confidence_level
    )
    bootstrap_lower, bootstrap_upper, bootstrap_se = (
        bootstrap_mean_interval(
            movement, config=config, seed_parts=seed_parts
        )
    )
    test = (
        stats.ttest_1samp(movement, 0.0)
        if count >= 2
        else None
    )
    return {
        "sample_count": count,
        "mean_signed_movement": mean,
        "median_signed_movement": median,
        "win_probability": (
            float(unique["win"].mean()) if len(unique) else np.nan
        ),
        "mean_mfe": (
            float(unique["mfe"].mean()) if len(unique) else np.nan
        ),
        "mean_mae": (
            float(unique["mae"].mean()) if len(unique) else np.nan
        ),
        "mean_mfe_to_mean_mae": (
            float(unique["mfe"].mean() / unique["mae"].mean())
            if len(unique) and float(unique["mae"].mean()) > 0
            else np.nan
        ),
        "median_mfe_mae_ratio": (
            float(unique["mfe_mae_ratio"].median())
            if len(unique)
            else np.nan
        ),
        "adverse_before_favorable_probability": (
            float(unique["adverse_before_favorable"].mean())
            if len(unique)
            else np.nan
        ),
        "median_time_to_mfe_minutes": (
            float(unique["time_to_mfe_minutes"].median())
            if len(unique)
            else np.nan
        ),
        "median_time_to_mae_minutes": (
            float(unique["time_to_mae_minutes"].median())
            if len(unique)
            else np.nan
        ),
        "standard_deviation": standard_deviation,
        "standard_error": standard_error,
        "mean_ci_lower": lower,
        "mean_ci_upper": upper,
        "confidence_level": config.confidence_level,
        "bootstrap_mean_ci_lower": bootstrap_lower,
        "bootstrap_mean_ci_upper": bootstrap_upper,
        "bootstrap_standard_error": bootstrap_se,
        "bootstrap_resamples": config.bootstrap_resamples,
        "t_statistic": (
            float(test.statistic)
            if test is not None and np.isfinite(test.statistic)
            else np.nan
        ),
        "p_value": (
            float(test.pvalue)
            if test is not None and np.isfinite(test.pvalue)
            else np.nan
        ),
    }


def summarize(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    config: ReversalReplicationConfig,
    label: str,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    grouper: str | list[str] = (
        group_columns[0]
        if len(group_columns) == 1
        else list(group_columns)
    )
    for key, group in frame.groupby(grouper, dropna=False):
        keys = key if isinstance(key, tuple) else (key,)
        rows.append(
            {
                **dict(zip(group_columns, keys, strict=True)),
                **metric_record(
                    group,
                    config=config,
                    seed_parts=(label, *keys),
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def build_primary_result(
    displacement_outcomes: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    primary = displacement_outcomes[
        displacement_outcomes["replication_role"].eq(
            "rolling_origin_validation"
        )
        & displacement_outcomes["horizon"].eq(config.primary_horizon)
    ]
    return pd.DataFrame(
        [
            {
                "endpoint": (
                    "mean_direction_aligned_movement_60m_from_"
                    "displacement"
                ),
                "sample_design": config.sample_design,
                "independent_replication": False,
                **metric_record(
                    primary,
                    config=config,
                    seed_parts=("primary", "displacement", "60m"),
                ),
            }
        ]
    )


def build_secondary_tests(
    displacement: pd.DataFrame,
    refinement: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    registered = [
        *[
            (config.primary_anchor, horizon)
            for horizon in (
                "5m",
                "15m",
                "30m",
                "120m",
                "ny_noon",
                "trading_day_close",
            )
        ],
        *[
            (config.secondary_anchor, horizon)
            for horizon in (
                "5m",
                "15m",
                "30m",
                "60m",
                "120m",
                "ny_noon",
                "trading_day_close",
            )
        ],
    ]
    combined = pd.concat(
        [displacement, refinement], ignore_index=True, sort=False
    )
    combined = combined[
        combined["replication_role"].eq("rolling_origin_validation")
    ]
    rows: list[dict[str, object]] = []
    for anchor_type, horizon in registered:
        cell = combined[
            combined["anchor_type"].eq(anchor_type)
            & combined["horizon"].eq(horizon)
        ]
        rows.append(
            {
                "anchor_type": anchor_type,
                "horizon": horizon,
                "comparison_registered": True,
                "primary_endpoint": False,
                **metric_record(
                    cell,
                    config=config,
                    seed_parts=("secondary", anchor_type, horizon),
                ),
            }
        )
    result = pd.DataFrame.from_records(rows)
    result["bh_q_value"] = benjamini_hochberg(result["p_value"])
    result["fdr_alpha"] = config.fdr_alpha
    result["fdr_significant"] = result["bh_q_value"].le(
        config.fdr_alpha
    )
    result["comparison_family_size"] = len(result)
    return result


def build_paired_refinement_outcomes(
    paired_anchors: pd.DataFrame,
    displacement: pd.DataFrame,
    refinement: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    displacement_60 = displacement[
        displacement["horizon"].eq(config.primary_horizon)
    ][
        [
            "sequence_id",
            "signed_forward_movement",
            "mfe",
            "mae",
        ]
    ].rename(
        columns={
            "signed_forward_movement": "displacement_signed_60m",
            "mfe": "displacement_mfe_60m",
            "mae": "displacement_mae_60m",
        }
    )
    refinement_60 = refinement[
        refinement["horizon"].eq(config.primary_horizon)
    ][
        [
            "sequence_id",
            "signed_forward_movement",
            "mfe",
            "mae",
        ]
    ].rename(
        columns={
            "signed_forward_movement": "refinement_signed_60m",
            "mfe": "refinement_mfe_60m",
            "mae": "refinement_mae_60m",
        }
    )
    result = (
        paired_anchors.merge(
            displacement_60,
            on="sequence_id",
            how="left",
            validate="one_to_one",
        )
        .merge(
            refinement_60,
            on="sequence_id",
            how="left",
            validate="one_to_one",
        )
    )
    result["refinement_minus_displacement_signed_60m"] = (
        result["refinement_signed_60m"]
        - result["displacement_signed_60m"]
    )
    validation = result[
        result["replication_role"].eq("rolling_origin_validation")
        & result["refinement_minus_displacement_signed_60m"].notna()
    ]
    values = validation[
        "refinement_minus_displacement_signed_60m"
    ].to_numpy(dtype=float)
    _, standard_error, lower, upper = _mean_interval(
        values, config.confidence_level
    )
    bootstrap_lower, bootstrap_upper, _ = bootstrap_mean_interval(
        values,
        config=config,
        seed_parts=("paired_refinement_difference",),
    )
    summary = pd.DataFrame(
        [
            {
                "paired_sequence_count": len(values),
                "median_displacement_to_refinement_minutes": (
                    float(
                        validation[
                            "displacement_to_refinement_minutes"
                        ].median()
                    )
                    if len(validation)
                    else np.nan
                ),
                "mean_refinement_minus_displacement_signed_60m": (
                    float(values.mean()) if len(values) else np.nan
                ),
                "median_refinement_minus_displacement_signed_60m": (
                    float(np.median(values)) if len(values) else np.nan
                ),
                "standard_error": standard_error,
                "mean_difference_ci_lower": lower,
                "mean_difference_ci_upper": upper,
                "bootstrap_difference_ci_lower": bootstrap_lower,
                "bootstrap_difference_ci_upper": bootstrap_upper,
                "anchors_counted_as_independent_sequences": False,
            }
        ]
    )
    return result, summary


def build_stability_summaries(
    primary_outcomes: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> dict[str, pd.DataFrame]:
    primary = primary_outcomes[
        primary_outcomes["replication_role"].eq(
            "rolling_origin_validation"
        )
        & primary_outcomes["horizon"].eq(config.primary_horizon)
    ]
    summaries = {
        "temporal_block_summaries": summarize(
            primary,
            ["replication_fold", "anchor_year"],
            config=config,
            label="temporal",
        ),
        "direction_summaries": summarize(
            primary,
            ["direction"],
            config=config,
            label="direction",
        ),
        "regime_summaries": summarize(
            primary,
            ["volatility_regime"],
            config=config,
            label="regime",
        ),
        "session_summaries": summarize(
            primary,
            ["anchor_session"],
            config=config,
            label="session",
        ),
        "origin_type_summaries": summarize(
            primary,
            ["candidate_source"],
            config=config,
            label="origin",
        ),
        "pmh_pml_summaries": summarize(
            primary,
            ["pmh_pml"],
            config=config,
            label="pmh_pml",
        ),
        "displacement_strength_summaries": summarize(
            primary,
            ["displacement_strength_bin"],
            config=config,
            label="strength",
        ),
        "latency_bin_summaries": summarize(
            primary,
            ["candidate_displacement_latency_bin"],
            config=config,
            label="latency",
        ),
        "retrospective_refinement_summaries": summarize(
            primary,
            ["refinement_subsequently_present"],
            config=config,
            label="later_refinement",
        ),
        "retrospective_confirmation_summaries": summarize(
            primary,
            ["later_engine_confirmed"],
            config=config,
            label="later_confirmation",
        ),
    }
    return summaries


def build_rolling_origin_summary(
    temporal: pd.DataFrame,
) -> pd.DataFrame:
    result = temporal.copy()
    result["discovery_prefix"] = result["anchor_year"].map(
        {
            2022: "2021",
            2023: "2021-2022",
            2024: "2021-2023",
            2025: "2021-2024",
        }
    )
    result["validation_overlap_with_e3"] = True
    result["validation_disjoint_from_fold_prefix"] = True
    return result[
        [
            "replication_fold",
            "discovery_prefix",
            "anchor_year",
            "sample_count",
            "mean_signed_movement",
            "median_signed_movement",
            "win_probability",
            "mean_ci_lower",
            "mean_ci_upper",
            "bootstrap_mean_ci_lower",
            "bootstrap_mean_ci_upper",
            "validation_overlap_with_e3",
            "validation_disjoint_from_fold_prefix",
        ]
    ]


def build_temporal_contribution_audit(
    rolling: pd.DataFrame,
) -> pd.DataFrame:
    """Describe magnitude concentration without changing frozen criteria."""

    result = rolling[
        [
            "replication_fold",
            "anchor_year",
            "sample_count",
            "mean_signed_movement",
        ]
    ].copy()
    result["block_signed_sum"] = (
        result["sample_count"] * result["mean_signed_movement"]
    )
    absolute_total = float(result["block_signed_sum"].abs().sum())
    result["absolute_net_block_contribution_share"] = (
        result["block_signed_sum"].abs() / absolute_total
        if absolute_total > 0
        else np.nan
    )
    result["primary_rule_modified_by_this_audit"] = False
    return result


def build_discovery_replication_comparison(
    discovery: pd.DataFrame,
    replication: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    discovery_record = metric_record(
        discovery,
        config=config,
        seed_parts=("comparison", "discovery"),
    )
    replication_record = metric_record(
        replication,
        config=config,
        seed_parts=("comparison", "replication"),
    )
    rows: list[dict[str, object]] = []
    metrics = (
        "sample_count",
        "mean_signed_movement",
        "median_signed_movement",
        "win_probability",
        "mean_mfe",
        "mean_mae",
        "mean_ci_lower",
        "mean_ci_upper",
    )
    for metric in metrics:
        discovery_value = discovery_record[metric]
        replication_value = replication_record[metric]
        rows.append(
            {
                "comparison_dimension": "endpoint",
                "metric": metric,
                "discovery_value": discovery_value,
                "replication_value": replication_value,
                "replication_minus_discovery": (
                    float(replication_value) - float(discovery_value)
                    if np.isfinite(float(discovery_value))
                    and np.isfinite(float(replication_value))
                    else np.nan
                ),
                "pooled_estimate": False,
            }
        )
    for dimension, column, values in (
        ("direction_balance", "direction", (-1, 1)),
        (
            "volatility_regime_balance",
            "volatility_regime",
            ("low", "normal", "high", "unavailable"),
        ),
        (
            "origin_balance",
            "candidate_source",
            ("poi_interaction", "liquidity_sweep", "pmh_pml_sweep"),
        ),
    ):
        for value in values:
            discovery_share = float(discovery[column].eq(value).mean())
            replication_share = float(replication[column].eq(value).mean())
            rows.append(
                {
                    "comparison_dimension": dimension,
                    "metric": str(value),
                    "discovery_value": discovery_share,
                    "replication_value": replication_share,
                    "replication_minus_discovery": (
                        replication_share - discovery_share
                    ),
                    "pooled_estimate": False,
                }
            )
    for metric, column in (
        (
            "median_candidate_to_displacement_minutes",
            "candidate_to_displacement_minutes",
        ),
    ):
        discovery_value = float(discovery[column].median())
        replication_value = float(replication[column].median())
        rows.append(
            {
                "comparison_dimension": "latency",
                "metric": metric,
                "discovery_value": discovery_value,
                "replication_value": replication_value,
                "replication_minus_discovery": (
                    replication_value - discovery_value
                ),
                "pooled_estimate": False,
            }
        )
    return pd.DataFrame.from_records(rows)


def _positive_after_extreme_removal(
    values: np.ndarray,
    fraction: float,
) -> tuple[float, int]:
    clean = values[np.isfinite(values)]
    if not clean.size:
        return np.nan, 0
    remove = max(1, int(math.ceil(clean.size * fraction)))
    order = np.argsort(np.abs(clean), kind="mergesort")
    retained = clean[order[:-remove]] if remove < clean.size else np.array([])
    return (
        float(retained.mean()) if retained.size else np.nan,
        remove,
    )


def classify_replication(
    *,
    primary_result: pd.DataFrame,
    primary_outcomes: pd.DataFrame,
    temporal: pd.DataFrame,
    direction: pd.DataFrame,
    causal_audit: pd.DataFrame,
    reproducibility_defect: bool,
    config: ReversalReplicationConfig,
) -> dict[str, object]:
    result = primary_result.iloc[0]
    validation = primary_outcomes[
        primary_outcomes["replication_role"].eq(
            "rolling_origin_validation"
        )
        & primary_outcomes["horizon"].eq(config.primary_horizon)
    ].drop_duplicates("sequence_id")
    movement = validation["signed_forward_movement"].to_numpy(dtype=float)
    never_confirmed = validation[
        ~validation["later_engine_confirmed"].fillna(False)
    ]
    extreme_removed_mean, extreme_removed_count = (
        _positive_after_extreme_removal(
            movement, config.extreme_removal_fraction
        )
    )
    trimmed_mean = (
        float(
            stats.trim_mean(
                movement[np.isfinite(movement)],
                proportiontocut=config.extreme_removal_fraction,
            )
        )
        if np.isfinite(movement).sum()
        else np.nan
    )
    block_sums = validation.groupby("replication_fold")[
        "signed_forward_movement"
    ].sum()
    absolute_block_total = float(block_sums.abs().sum())
    largest_block = (
        str(block_sums.abs().idxmax()) if len(block_sums) else None
    )
    largest_block_share = (
        float(block_sums.abs().max() / absolute_block_total)
        if absolute_block_total > 0
        else np.nan
    )
    block_adequate = bool(
        len(temporal) == len(config.validation_years)
        and temporal["sample_count"].ge(config.minimum_block_n).all()
    )
    positive_blocks = int(
        temporal["mean_signed_movement"].gt(0).sum()
    )
    direction_adequate = bool(
        len(direction) == 2
        and direction["sample_count"].ge(config.minimum_direction_n).all()
    )
    severe_direction_contradiction = bool(
        (direction["mean_ci_upper"] < 0).any()
    )
    never_confirmed_share = (
        len(never_confirmed) / len(validation) if len(validation) else 0.0
    )
    never_confirmed_mean = (
        float(never_confirmed["signed_forward_movement"].mean())
        if len(never_confirmed)
        else np.nan
    )
    checks = {
        "mean_positive": bool(result["mean_signed_movement"] > 0),
        "confidence_interval_above_zero": bool(
            result["mean_ci_lower"] > 0
        ),
        "total_sample_adequate": bool(
            result["sample_count"] >= config.minimum_validation_n
        ),
        "temporal_blocks_adequate": block_adequate,
        "minimum_positive_blocks_met": (
            positive_blocks >= config.minimum_positive_blocks
        ),
        "direction_samples_adequate": direction_adequate,
        "no_severe_direction_contradiction": (
            not severe_direction_contradiction
        ),
        "not_dependent_on_later_confirmation": bool(
            never_confirmed_share
            >= 1.0 - config.maximum_confirmed_share
            and never_confirmed_mean > 0
        ),
        "deduplicated_effect_positive": bool(
            validation["sequence_id"].is_unique
            and result["mean_signed_movement"] > 0
        ),
        "causal_and_direction_invariants_pass": bool(
            causal_audit["all_causal_invariants_pass"].all()
        ),
        "mean_mfe_mae_ratio_adequate": bool(
            result["mean_mfe_to_mean_mae"]
            >= config.minimum_mean_mfe_mae_ratio
        ),
        "median_path_ratio_adequate": bool(
            result["median_mfe_mae_ratio"]
            >= config.minimum_median_path_ratio
        ),
        "positive_after_largest_one_percent_removed": bool(
            extreme_removed_mean > 0
        ),
        "positive_one_percent_trimmed_mean": bool(trimmed_mean > 0),
    }
    internal_pass = all(checks.values())
    if reproducibility_defect or not checks[
        "causal_and_direction_invariants_pass"
    ]:
        identifier = 6
        label = (
            "A reproducibility or implementation defect invalidates "
            "the comparison"
        )
        recommendation = (
            "Repair the verified defect before any further cohort research."
        )
    elif not config.independent_replication:
        identifier = 5
        label = (
            "Replication cannot be judged because the independent sample "
            "is inadequate"
        )
        recommendation = (
            "Acquire a hash-verified post-2025 D003-derived sample and repeat "
            "the frozen E4 design; do not begin entry-geometry research."
        )
    elif internal_pass:
        identifier = 1
        label = "Narrow displacement finding independently replicated"
        recommendation = (
            "Begin a separately approved entry-geometry research study; "
            "do not change production."
        )
    elif bool(result["mean_signed_movement"] > 0):
        identifier = 2
        label = (
            "Direction remains positive but effect is too weak or uncertain "
            "to replicate"
        )
        recommendation = "Replicate again on a larger independent sample."
    elif False:
        identifier = 3
        label = (
            "Effect exists only in a narrower subgroup and fails the "
            "primary replication"
        )
        recommendation = (
            "Treat subgroups as exploratory and preregister a new study."
        )
    else:
        identifier = 4
        label = "Discovery effect does not replicate"
        recommendation = "Stop this cohort."
    return {
        "primary_classification_id": identifier,
        "primary_classification_label": label,
        "recommendation": recommendation,
        "independent_replication_available": config.independent_replication,
        "internal_rolling_origin_checks_pass": internal_pass,
        "internal_checks": checks,
        "diagnostic_values": {
            "validation_sample_count": int(result["sample_count"]),
            "validation_mean_60m": float(
                result["mean_signed_movement"]
            ),
            "validation_ci_lower": float(result["mean_ci_lower"]),
            "validation_ci_upper": float(result["mean_ci_upper"]),
            "positive_validation_blocks": positive_blocks,
            "never_confirmed_share": never_confirmed_share,
            "never_confirmed_mean_60m": never_confirmed_mean,
            "mean_mfe_to_mean_mae": float(
                result["mean_mfe_to_mean_mae"]
            ),
            "median_mfe_mae_ratio": float(
                result["median_mfe_mae_ratio"]
            ),
            "extreme_removed_count": extreme_removed_count,
            "mean_after_largest_one_percent_removed": (
                extreme_removed_mean
            ),
            "one_percent_trimmed_mean": trimmed_mean,
            "largest_absolute_net_block": largest_block,
            "largest_absolute_net_block_contribution_share": (
                largest_block_share
            ),
            "e3_overlap_share": 1.0,
        },
        "secondary_classification": (
            "internal rolling-origin checks passed under the frozen rule; "
            f"largest absolute net block contribution is {largest_block} "
            f"at {largest_block_share:.1%}"
            if internal_pass
            else "internal rolling-origin checks failed"
        ),
    }
