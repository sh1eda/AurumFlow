"""Inference, decomposition, decay, and hard classification for D005_E3."""

from __future__ import annotations

import hashlib
from itertools import combinations
import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from research.d005_e2_reaction_anchor_diagnostic.directions import (
    classify_outcome,
    expected_post_sweep_direction,
    liquidity_raid_direction,
)

from .config import EarlyContextAnchorStudyConfig


SUMMARY_METRICS: dict[str, tuple[str, str]] = {
    "sample_count": ("sequence_id", "nunique"),
    "forward_observations": ("signed_forward_movement", "count"),
    "mean_signed_movement": ("signed_forward_movement", "mean"),
    "median_signed_movement": ("signed_forward_movement", "median"),
    "win_probability": ("win", "mean"),
    "mean_mfe": ("mfe", "mean"),
    "mean_mae": ("mae", "mean"),
    "median_mfe_mae_ratio": ("mfe_mae_ratio", "median"),
    "adverse_before_favorable_probability": (
        "adverse_before_favorable",
        "mean",
    ),
    "median_time_to_mfe_minutes": ("time_to_mfe_minutes", "median"),
    "median_time_to_mae_minutes": ("time_to_mae_minutes", "median"),
    "standard_deviation": ("signed_forward_movement", "std"),
}


def _normal_confidence(
    count: int,
    mean: float,
    standard_deviation: float,
    confidence_level: float,
) -> tuple[float, float, float]:
    if count < 2 or not np.isfinite(standard_deviation):
        return np.nan, np.nan, np.nan
    standard_error = standard_deviation / math.sqrt(count)
    critical = float(
        stats.t.ppf((1.0 + confidence_level) / 2.0, count - 1)
    )
    return (
        standard_error,
        mean - critical * standard_error,
        mean + critical * standard_error,
    )


def summarize(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Unique-sequence descriptive summary with normal mean interval."""

    if frame.empty:
        return pd.DataFrame()
    unique = frame.drop_duplicates(
        [*group_columns, "sequence_id"], keep="first"
    )
    result = (
        unique.groupby(list(group_columns), dropna=False)
        .agg(**SUMMARY_METRICS)
        .reset_index()
    )
    intervals = [
        _normal_confidence(
            int(row.forward_observations),
            float(row.mean_signed_movement),
            float(row.standard_deviation),
            config.confidence_level,
        )
        for row in result.itertuples()
    ]
    result["standard_error"] = [item[0] for item in intervals]
    result["mean_ci_lower"] = [item[1] for item in intervals]
    result["mean_ci_upper"] = [item[2] for item in intervals]
    result["confidence_level"] = config.confidence_level
    result["mapping_pooled"] = False
    return result


def anchor_forward_summary(
    forward: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    return summarize(
        forward,
        ["mapping_variant", "outcome", "anchor_type", "horizon"],
        config=config,
    )


def build_standard_summaries(
    forward: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> dict[str, pd.DataFrame]:
    primary = forward[forward["horizon"].eq(config.primary_horizon)]
    return {
        "mapping_summaries": summarize(
            primary,
            ["mapping_variant", "outcome", "anchor_type"],
            config=config,
        ),
        "reversal_continuation_summaries": summarize(
            primary,
            ["outcome", "mapping_variant", "anchor_type"],
            config=config,
        ),
        "fvg_summaries": summarize(
            forward[
                forward["anchor_type"].isin(
                    [
                        "first_aligned_raw_fvg_creation",
                        "first_context_qualified_fvg_creation",
                    ]
                )
            ],
            ["mapping_variant", "outcome", "anchor_type", "horizon"],
            config=config,
        ),
        "independent_ob_summaries": summarize(
            forward[
                forward["anchor_type"].str.startswith(
                    "qualifying_ob_", na=False
                )
            ],
            [
                "mapping_variant",
                "outcome",
                "event_variant",
                "anchor_type",
                "horizon",
            ],
            config=config,
        ),
        "pmh_pml_summaries": summarize(
            forward[forward["pmh_pml"].fillna(False)],
            [
                "pmh_pml_prerequisites_met",
                "mapping_variant",
                "outcome",
                "anchor_type",
                "horizon",
            ],
            config=config,
        ),
        "annual_summaries": summarize(
            primary,
            [
                "anchor_year",
                "mapping_variant",
                "outcome",
                "anchor_type",
            ],
            config=config,
        ),
        "volatility_regime_summaries": summarize(
            primary,
            [
                "volatility_regime",
                "mapping_variant",
                "outcome",
                "anchor_type",
            ],
            config=config,
        ),
    }


def _bootstrap_mean_interval(
    values: np.ndarray,
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> tuple[float, float, float]:
    clean = values[np.isfinite(values)]
    if clean.size < 2:
        return np.nan, np.nan, np.nan
    generator = np.random.default_rng(seed)
    means = np.empty(resamples, dtype=float)
    chunk = 50
    for left in range(0, resamples, chunk):
        right = min(resamples, left + chunk)
        indices = generator.integers(
            0, clean.size, size=(right - left, clean.size)
        )
        means[left:right] = clean[indices].mean(axis=1)
    tail = (1.0 - confidence_level) / 2.0
    return (
        float(np.quantile(means, tail)),
        float(np.quantile(means, 1.0 - tail)),
        float(means.std(ddof=1)),
    )


def benjamini_hochberg(p_values: Iterable[float]) -> np.ndarray:
    """Return monotone BH q-values; NaN inputs remain NaN."""

    values = np.asarray(list(p_values), dtype=float)
    result = np.full(values.shape, np.nan, dtype=float)
    valid = np.flatnonzero(np.isfinite(values))
    if not valid.size:
        return result
    order = valid[np.argsort(values[valid], kind="mergesort")]
    ranked = values[order] * len(valid) / np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    result[order] = np.minimum(adjusted, 1.0)
    return result


def _cell_seed(
    config: EarlyContextAnchorStudyConfig,
    *parts: object,
) -> int:
    digest = hashlib.sha256(
        "|".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()
    return (config.bootstrap_seed + int(digest[:8], 16)) % (2**32)


def build_primary_comparisons(
    forward: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Build the registered 60-cell family and apply one BH correction."""

    outcomes = ("reversal", "continuation")
    registered = pd.MultiIndex.from_product(
        [
            config.primary_anchors,
            [item.name for item in config.mapping_variants],
            outcomes,
        ],
        names=["anchor_type", "mapping_variant", "outcome"],
    ).to_frame(index=False)
    registered["comparison_registered"] = True
    source = forward[
        forward["horizon"].eq(config.primary_horizon)
        & forward["anchor_type"].isin(config.primary_anchors)
    ].drop_duplicates(
        ["anchor_type", "mapping_variant", "outcome", "sequence_id"]
    )
    rows: list[dict[str, object]] = []
    for cell in registered.to_dict("records"):
        values = source[
            source["anchor_type"].eq(cell["anchor_type"])
            & source["mapping_variant"].eq(cell["mapping_variant"])
            & source["outcome"].eq(cell["outcome"])
        ]
        movement = values["signed_forward_movement"].dropna().to_numpy(
            dtype=float
        )
        count = movement.size
        mean = float(np.mean(movement)) if count else np.nan
        median = float(np.median(movement)) if count else np.nan
        win = float(np.mean(movement > 0)) if count else np.nan
        test = (
            stats.ttest_1samp(movement, popmean=0.0)
            if count >= 2
            else None
        )
        p_value = (
            float(test.pvalue)
            if test is not None and np.isfinite(test.pvalue)
            else np.nan
        )
        bootstrap_lower, bootstrap_upper, bootstrap_se = (
            _bootstrap_mean_interval(
                movement,
                resamples=config.bootstrap_resamples,
                seed=_cell_seed(
                    config,
                    cell["anchor_type"],
                    cell["mapping_variant"],
                    cell["outcome"],
                ),
                confidence_level=config.confidence_level,
            )
        )
        annual = (
            values.groupby("anchor_year")[
                "signed_forward_movement"
            ]
            .agg(["count", "mean"])
            .reset_index()
        )
        annual_eligible = annual[
            annual["count"].ge(config.annual_minimum_sample)
        ]
        positive_years = int(annual_eligible["mean"].gt(0).sum())
        direction = (
            values.groupby("direction")["signed_forward_movement"]
            .agg(["count", "mean"])
            .reset_index()
        )
        bullish = direction[direction["direction"].eq(1)]
        bearish = direction[direction["direction"].eq(-1)]
        bullish_count = int(bullish["count"].sum())
        bearish_count = int(bearish["count"].sum())
        bullish_mean = (
            float(bullish["mean"].iloc[0])
            if not bullish.empty
            else np.nan
        )
        bearish_mean = (
            float(bearish["mean"].iloc[0])
            if not bearish.empty
            else np.nan
        )
        rows.append(
            {
                **cell,
                "primary_horizon": config.primary_horizon,
                "sample_count": count,
                "mean_signed_movement": mean,
                "median_signed_movement": median,
                "win_probability": win,
                "t_statistic": (
                    float(test.statistic)
                    if test is not None and np.isfinite(test.statistic)
                    else np.nan
                ),
                "p_value": p_value,
                "bootstrap_mean_ci_lower": bootstrap_lower,
                "bootstrap_mean_ci_upper": bootstrap_upper,
                "bootstrap_standard_error": bootstrap_se,
                "bootstrap_resamples": config.bootstrap_resamples,
                "eligible_year_count": len(annual_eligible),
                "positive_year_count": positive_years,
                "bullish_count": bullish_count,
                "bullish_mean": bullish_mean,
                "bearish_count": bearish_count,
                "bearish_mean": bearish_mean,
                "causally_observable": bool(
                    values["anchor_causally_observable"].all()
                )
                if not values.empty
                else True,
                "future_completion_conditioned": False,
                "mapping_pooled": False,
            }
        )
    result = pd.DataFrame.from_records(rows)
    result["bh_q_value"] = benjamini_hochberg(result["p_value"])
    result["sample_adequate"] = result["sample_count"].ge(
        config.primary_minimum_sample
    )
    result["mean_positive"] = result["mean_signed_movement"].gt(0)
    result["median_consistent"] = result[
        "median_signed_movement"
    ].ge(0)
    result["fdr_significant"] = result["bh_q_value"].le(
        config.fdr_alpha
    )
    result["bootstrap_survives"] = result[
        "bootstrap_mean_ci_lower"
    ].gt(0)
    result["annual_stable"] = (
        result["eligible_year_count"].ge(4)
        & result["positive_year_count"].ge(4)
    )
    result["direction_stable"] = (
        result["bullish_count"].ge(config.direction_minimum_sample)
        & result["bearish_count"].ge(config.direction_minimum_sample)
        & result["bullish_mean"].gt(0)
        & result["bearish_mean"].gt(0)
    )
    criteria = [
        "sample_adequate",
        "mean_positive",
        "median_consistent",
        "fdr_significant",
        "bootstrap_survives",
        "annual_stable",
        "direction_stable",
        "causally_observable",
    ]
    result["survives_all_stability_criteria"] = result[criteria].all(
        axis=1
    )
    result["comparison_family_size"] = len(result)
    result["nonempty_comparison_count"] = int(
        result["sample_count"].gt(0).sum()
    )
    result["fdr_alpha"] = config.fdr_alpha
    return result


def build_candidate_decomposition(
    forward: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Decompose the all-candidate 60m result without duplicating principal N."""

    candidate = forward[
        forward["anchor_type"].eq("candidate_context_creation")
        & forward["horizon"].eq(config.primary_horizon)
    ].drop_duplicates("sequence_id")
    rows: list[dict[str, object]] = []
    for record in candidate.to_dict("records"):
        causal = {
            "origin": record["candidate_source"],
            "outcome": record["outcome"],
            "mapping": record["mapping_variant"],
            "direction": str(int(record["direction"])),
            "year": str(int(record["anchor_year"])),
            "volatility_regime": record["volatility_regime"],
            "session": record["anchor_session"],
            "pmh_pml": str(bool(record["pmh_pml"])),
            "balance": (
                "balanced_ranging"
                if record["balanced_ranging"]
                else "non_ranging_or_unresolved"
            ),
            "candidate_event_type": record["candidate_type"],
            "candidate_variant": record["candidate_variant"],
        }
        retrospective = {
            "later_engine_confirmed": str(
                bool(record["later_engine_confirmed"])
            ),
            "later_terminal_class": record[
                "retrospective_terminal_class"
            ],
            "later_raw_fvg": str(
                bool(record["has_causal_raw_fvg"])
            ),
            "later_qualified_fvg": str(
                bool(record["has_causal_qualified_fvg"])
            ),
            "later_ob_consecutive_block": str(
                bool(record["has_causal_ob_consecutive_block"])
            ),
            "later_ob_last_opposing_candle": str(
                bool(record["has_causal_ob_last_opposing_candle"])
            ),
            "later_ob_inefficiency_break_origin": str(
                bool(
                    record[
                        "has_causal_ob_inefficiency_break_origin"
                    ]
                )
            ),
        }
        for dimension, value in causal.items():
            rows.append(
                {
                    **record,
                    "decomposition_dimension": dimension,
                    "decomposition_value": str(value),
                    "conditioning": "causal_at_candidate",
                }
            )
        for dimension, value in retrospective.items():
            rows.append(
                {
                    **record,
                    "decomposition_dimension": dimension,
                    "decomposition_value": str(value),
                    "conditioning": "retrospective",
                }
            )
    expanded = pd.DataFrame.from_records(rows)
    return summarize(
        expanded,
        [
            "conditioning",
            "decomposition_dimension",
            "decomposition_value",
        ],
        config=config,
    )


def build_direction_family_audit(
    sequences: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Audit frozen labels without redefining reversal or continuation."""

    rows: list[dict[str, object]] = []
    liquidity_sources = {"liquidity_sweep", "pmh_pml_sweep"}
    for record in sequences.to_dict("records"):
        candidate_direction = int(record["candidate_direction"])
        parent_direction = int(record["parent_direction"])
        child_direction = int(record["pre_candidate_child_direction"])
        outcome = str(record["outcome"])
        source = str(record["candidate_source"])
        recomputed = classify_outcome(
            candidate_type=str(record["candidate_type"]),
            candidate_direction=candidate_direction,
            parent_direction=parent_direction,
            pre_candidate_child_direction=child_direction,
        )
        if outcome == "continuation":
            parent_status = (
                "parent_neutral_unresolved"
                if parent_direction == 0
                else "aligned"
                if candidate_direction == parent_direction
                else "opposed"
            )
        else:
            parent_status = "not_continuation"
        is_liquidity_reversal = bool(
            outcome == "reversal" and source in liquidity_sources
        )
        raid_direction = liquidity_raid_direction(
            str(record["candidate_taxonomy"])
        )
        expected_direction = expected_post_sweep_direction(
            str(record["candidate_taxonomy"])
        )
        liquidity_away = (
            bool(
                candidate_direction == expected_direction
                and candidate_direction == -raid_direction
                and raid_direction != 0
            )
            if is_liquidity_reversal
            else None
        )
        poi_reversal = bool(
            outcome == "reversal" and source == "poi_interaction"
        )
        rows.append(
            {
                "sequence_id": record["sequence_id"],
                "mapping_variant": record["mapping_variant"],
                "outcome": outcome,
                "candidate_source": source,
                "candidate_direction": candidate_direction,
                "parent_direction": parent_direction,
                "pre_candidate_child_direction": child_direction,
                "frozen_outcome_recomputed": recomputed,
                "frozen_outcome_rule_passed": recomputed == outcome,
                "candidate_parent_aligned_at_candidate": bool(
                    record["parent_candidate_aligned"]
                ),
                "continuation_parent_order_flow_status": parent_status,
                "continuation_prechild_not_opposed": bool(
                    outcome != "continuation"
                    or child_direction in (0, candidate_direction)
                ),
                "liquidity_raid_direction": raid_direction,
                "expected_post_sweep_direction": expected_direction,
                "reversal_liquidity_moves_away_from_sweep": liquidity_away,
                "poi_reversal_direction_preserved": (
                    bool(candidate_direction != 0)
                    if poi_reversal
                    else None
                ),
                "poi_rejection_vector_independently_verifiable": False,
                "poi_rejection_verification_note": (
                    "Frozen E2 retains POI array direction but has no "
                    "independent rejected-POI geometry vector."
                    if poi_reversal
                    else None
                ),
            }
        )
    audit = pd.DataFrame.from_records(rows)
    working = audit.copy()
    working["continuation_parent_aligned"] = working[
        "continuation_parent_order_flow_status"
    ].eq("aligned")
    working["continuation_parent_neutral"] = working[
        "continuation_parent_order_flow_status"
    ].eq("parent_neutral_unresolved")
    working["continuation_parent_opposed"] = working[
        "continuation_parent_order_flow_status"
    ].eq("opposed")
    working["liquidity_reversal_observation"] = working[
        "reversal_liquidity_moves_away_from_sweep"
    ].notna()
    working["liquidity_reversal_away_pass"] = working[
        "reversal_liquidity_moves_away_from_sweep"
    ].fillna(False)
    summary = (
        working.groupby(
            ["mapping_variant", "outcome", "candidate_source"],
            dropna=False,
        )
        .agg(
            sequence_count=("sequence_id", "nunique"),
            frozen_outcome_rule_pass_count=(
                "frozen_outcome_rule_passed",
                "sum",
            ),
            continuation_parent_aligned_count=(
                "continuation_parent_aligned",
                "sum",
            ),
            continuation_parent_neutral_count=(
                "continuation_parent_neutral",
                "sum",
            ),
            continuation_parent_opposed_count=(
                "continuation_parent_opposed",
                "sum",
            ),
            continuation_prechild_not_opposed_count=(
                "continuation_prechild_not_opposed",
                "sum",
            ),
            liquidity_reversal_observations=(
                "liquidity_reversal_observation",
                "sum",
            ),
            liquidity_reversal_away_pass_count=(
                "liquidity_reversal_away_pass",
                "sum",
            ),
            poi_rejection_vector_verifiable_count=(
                "poi_rejection_vector_independently_verifiable",
                "sum",
            ),
        )
        .reset_index()
    )
    return audit, summary


def build_conditioning_audit(
    forward: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    primary = forward[
        forward["horizon"].eq(config.primary_horizon)
        & forward["anchor_type"].isin(config.primary_anchors)
    ]
    rows: list[pd.DataFrame] = []
    cohorts = {
        "all_causally_observable": pd.Series(
            True, index=primary.index
        ),
        "later_structurally_complete": primary[
            "later_structurally_complete"
        ],
        "later_frozen_engine_confirmed": primary[
            "later_engine_confirmed"
        ],
        "later_invalidated": primary["later_invalidated"],
        "later_timed_out": primary["later_timed_out"],
        "later_conflicted": primary["later_conflicted"],
    }
    for cohort, mask in cohorts.items():
        subset = primary[mask.fillna(False)].copy()
        if subset.empty:
            continue
        subset["conditioning_cohort"] = cohort
        subset["conditioning"] = (
            "main_unconditioned"
            if cohort == "all_causally_observable"
            else "retrospective"
        )
        rows.append(subset)
    expanded = pd.concat(rows, ignore_index=True)
    return summarize(
        expanded,
        [
            "conditioning",
            "conditioning_cohort",
            "mapping_variant",
            "outcome",
            "anchor_type",
        ],
        config=config,
    )


def build_cohort_overlap(
    sequences: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Document multi-cohort membership and pairwise sequence overlap."""

    rows: list[dict[str, object]] = []
    for record in sequences.to_dict("records"):
        causal = {
            f"origin:{record['candidate_source']}",
            f"outcome:{record['outcome']}",
            f"mapping:{record['mapping_variant']}",
            (
                "balanced_ranging"
                if record.get("balanced_ranging", False)
                else "non_ranging_or_unresolved"
            ),
        }
        if record.get("pmh_pml", False):
            causal.add("pmh_pml")
        if record.get("candidate_type") == "raw_fvg":
            causal.add("candidate_raw_fvg")
        if record.get("candidate_type") == "order_block":
            causal.add(
                f"candidate_ob:{record.get('candidate_variant')}"
            )
        retrospective = {
            f"terminal:{record['retrospective_terminal_class']}"
        }
        if record.get("has_causal_qualified_fvg", False):
            retrospective.add("later_qualified_fvg")
        for variant in (
            "consecutive_block",
            "last_opposing_candle",
            "inefficiency_break_origin",
        ):
            if record.get(f"has_causal_ob_{variant}", False):
                retrospective.add(f"later_ob:{variant}")
        for cohort in causal:
            rows.append(
                {
                    "sequence_id": record["sequence_id"],
                    "cohort": cohort,
                    "conditioning": "causal_at_candidate",
                }
            )
        for cohort in retrospective:
            rows.append(
                {
                    "sequence_id": record["sequence_id"],
                    "cohort": cohort,
                    "conditioning": "retrospective",
                }
            )
    membership = pd.DataFrame.from_records(rows).drop_duplicates(
        ["sequence_id", "cohort"]
    )
    sets = {
        cohort: set(group["sequence_id"])
        for cohort, group in membership.groupby("cohort")
    }
    overlap_rows = []
    for left, right in combinations(sorted(sets), 2):
        intersection = len(sets[left] & sets[right])
        if not intersection:
            continue
        overlap_rows.append(
            {
                "left_cohort": left,
                "right_cohort": right,
                "left_count": len(sets[left]),
                "right_count": len(sets[right]),
                "overlap_count": intersection,
                "jaccard": intersection
                / len(sets[left] | sets[right]),
            }
        )
    return membership, pd.DataFrame.from_records(overlap_rows)


def latency_decay_summary(
    latency: pd.DataFrame,
    forward: pd.DataFrame,
) -> pd.DataFrame:
    if latency.empty:
        return pd.DataFrame()
    sixty = forward[forward["horizon"].eq("60m")][
        ["anchor_id", "signed_forward_movement", "win"]
    ].drop_duplicates("anchor_id")
    joined = latency.merge(
        sixty.rename(
            columns={
                "anchor_id": "left_anchor_id",
                "signed_forward_movement": "left_forward_mean_source",
                "win": "left_win_source",
            }
        ),
        on="left_anchor_id",
        how="left",
    ).merge(
        sixty.rename(
            columns={
                "anchor_id": "right_anchor_id",
                "signed_forward_movement": "right_forward_mean_source",
                "win": "right_win_source",
            }
        ),
        on="right_anchor_id",
        how="left",
    )
    return (
        joined.groupby(
            ["mapping_variant", "outcome", "latency_stage"],
            dropna=False,
        )
        .agg(
            sequence_count=("sequence_id", "nunique"),
            median_elapsed_minutes=("elapsed_minutes", "median"),
            negative_timestamp_order_count=(
                "timestamp_order_valid",
                lambda values: int((~values).sum()),
            ),
            mean_signed_stage_movement=(
                "signed_stage_movement",
                "mean",
            ),
            median_candidate_to_stage_mfe_consumed=(
                "candidate_to_stage_mfe_consumed",
                "median",
            ),
            median_candidate_to_stage_mae_incurred=(
                "candidate_to_stage_mae_incurred",
                "median",
            ),
            left_forward_observations=(
                "left_forward_mean_source",
                "count",
            ),
            mean_left_forward_movement=(
                "left_forward_mean_source",
                "mean",
            ),
            mean_right_forward_movement=(
                "right_forward_mean_source",
                "mean",
            ),
            left_win_probability=("left_win_source", "mean"),
            right_win_probability=("right_win_source", "mean"),
        )
        .reset_index()
        .assign(
            change_in_forward_mean=lambda frame: (
                frame["mean_right_forward_movement"]
                - frame["mean_left_forward_movement"]
            ),
            change_in_win_probability=lambda frame: (
                frame["right_win_probability"]
                - frame["left_win_probability"]
            ),
            mapping_pooled=False,
        )
    )


def earliest_anchor_criteria(
    primary: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    rows = []
    for anchor_type in config.primary_anchors:
        cells = primary[primary["anchor_type"].eq(anchor_type)]
        survivors = cells[cells["survives_all_stability_criteria"]]
        rows.append(
            {
                "anchor_type": anchor_type,
                "registered_cells": len(cells),
                "nonempty_cells": int(cells["sample_count"].gt(0).sum()),
                "positive_mean_cells": int(
                    cells["mean_positive"].sum()
                ),
                "positive_median_cells": int(
                    cells["median_consistent"].sum()
                ),
                "fdr_significant_positive_cells": int(
                    (cells["mean_positive"] & cells["fdr_significant"]).sum()
                ),
                "bootstrap_surviving_cells": int(
                    cells["bootstrap_survives"].sum()
                ),
                "fully_stable_cells": len(survivors),
                "surviving_mapping_count": survivors[
                    "mapping_variant"
                ].nunique(),
                "surviving_outcome_count": survivors["outcome"].nunique(),
                "broadly_stable": bool(
                    survivors["mapping_variant"].nunique()
                    >= config.broad_minimum_mappings
                    and survivors["outcome"].nunique() == 2
                ),
                "causally_observable": bool(
                    cells["causally_observable"].all()
                ),
                "future_completion_conditioned": False,
            }
        )
    return pd.DataFrame.from_records(rows)


def classify_result(
    *,
    primary: pd.DataFrame,
    criteria: pd.DataFrame,
    forward: pd.DataFrame,
    config: EarlyContextAnchorStudyConfig,
) -> dict[str, object]:
    """Select exactly one preregistered category in priority order."""

    earlier = primary[
        ~primary["anchor_type"].eq("reaction_confirmed")
    ]
    broad = criteria[
        ~criteria["anchor_type"].eq("reaction_confirmed")
        & criteria["broadly_stable"]
    ]
    narrow = earlier[earlier["survives_all_stability_criteria"]]
    candidate = primary[
        primary["anchor_type"].eq("candidate_context_creation")
    ]
    candidate_informative_cells = candidate[
        candidate["mean_positive"] & candidate["median_consistent"]
    ]
    candidate_has_fdr = bool(
        (
            candidate["mean_positive"]
            & candidate["fdr_significant"]
        ).any()
    )
    candidate_information = bool(
        len(candidate_informative_cells) >= 3 and candidate_has_fdr
    )

    candidate_forward = forward[
        forward["anchor_type"].eq("candidate_context_creation")
        & forward["horizon"].eq(config.primary_horizon)
    ].drop_duplicates("sequence_id")
    all_values = candidate_forward[
        "signed_forward_movement"
    ].dropna().to_numpy(dtype=float)
    retrospective_values = candidate_forward[
        candidate_forward["later_engine_confirmed"]
    ]["signed_forward_movement"].dropna().to_numpy(dtype=float)
    all_mean = float(all_values.mean()) if all_values.size else np.nan
    retrospective_mean = (
        float(retrospective_values.mean())
        if retrospective_values.size
        else np.nan
    )
    retro_lower, retro_upper, _ = _bootstrap_mean_interval(
        retrospective_values,
        resamples=config.bootstrap_resamples,
        seed=_cell_seed(config, "retrospective_candidate"),
        confidence_level=config.confidence_level,
    )
    retrospective_explains = bool(
        retrospective_values.size
        >= config.retrospective_minimum_sample
        and retro_lower > 0
        and retrospective_mean - all_mean
        >= config.retrospective_gap_price_units
    )
    any_positive_fdr = bool(
        (
            earlier["mean_positive"] & earlier["fdr_significant"]
        ).any()
    )

    if not broad.empty:
        identifier = 1
        label = "A broadly stable earlier causal anchor exists"
        reason = (
            "At least one earlier anchor survives across three mappings "
            "and both reversal/continuation families."
        )
        recommendation = (
            "Continue only with a separately approved causal replication of "
            f"{', '.join(broad['anchor_type'])}; do not treat it as an entry."
        )
    elif not narrow.empty:
        identifier = 2
        label = "An earlier anchor exists only in a narrow, defensible cohort"
        reason = (
            f"{len(narrow)} primary mapping/outcome cell(s) survived every "
            "preregistered stability condition, but no anchor was broad."
        )
        recommendation = (
            "Isolate the surviving cohort in a new preregistered replication; "
            "do not promote it to production."
        )
    elif candidate_information:
        identifier = 3
        label = (
            "Candidate context contains information, but no operationally "
            "stable anchor exists"
        )
        reason = (
            "Candidate cells contain repeated positive mean/median evidence, "
            "but none satisfies every stability requirement."
        )
        recommendation = (
            "Redesign the context hypothesis before any further operational "
            "testing."
        )
    elif retrospective_explains:
        identifier = 4
        label = (
            "Positive early-anchor results are explained by retrospective "
            "conditioning"
        )
        reason = (
            "The later-confirmed candidate cohort has a positive bootstrap "
            "interval and a mean at least one price unit above the all-anchor "
            "candidate population, while no causal primary cell is stable."
        )
        recommendation = (
            "Stop pursuing this context family as currently framed; do not "
            "use future completion to select an early anchor."
        )
    elif not any_positive_fdr:
        identifier = 5
        label = (
            "No meaningful directional relationship remains after uncapped "
            "and multiplicity-aware analysis"
        )
        reason = (
            "No earlier primary cell has both a positive mean and an "
            "FDR-significant comparison."
        )
        recommendation = "Stop pursuing this context family."
    else:
        identifier = 6
        label = "Evidence remains inconclusive"
        reason = (
            "Some multiplicity-aware evidence remains, but it does not meet "
            "a stable-anchor or conditioning explanation rule."
        )
        recommendation = (
            "Collect independent evidence before changing or extending D005."
        )

    secondary: list[str] = []
    if retrospective_explains:
        secondary.append(
            "later engine confirmation materially amplifies candidate results"
        )
    if not candidate.empty and candidate["mean_positive"].any():
        secondary.append(
            "some candidate cells have positive raw means before full stability checks"
        )
    return {
        "primary_classification_id": identifier,
        "primary_classification_label": label,
        "reason": reason,
        "secondary_classifications": secondary,
        "recommendation": recommendation,
        "diagnostic_values": {
            "broad_earlier_anchor_count": len(broad),
            "stable_earlier_cell_count": len(narrow),
            "candidate_informative_cell_count": len(
                candidate_informative_cells
            ),
            "candidate_has_positive_fdr_cell": candidate_has_fdr,
            "all_candidate_mean_60m": all_mean,
            "later_confirmed_candidate_count": int(
                retrospective_values.size
            ),
            "later_confirmed_candidate_mean_60m": retrospective_mean,
            "later_confirmed_candidate_bootstrap_lower": retro_lower,
            "later_confirmed_candidate_bootstrap_upper": retro_upper,
            "retrospective_conditioning_gap": (
                retrospective_mean - all_mean
                if np.isfinite(retrospective_mean)
                and np.isfinite(all_mean)
                else np.nan
            ),
            "retrospective_conditioning_rule_met": retrospective_explains,
            "positive_fdr_earlier_cell_exists": any_positive_fdr,
            "registered_primary_comparison_count": len(primary),
            "nonempty_primary_comparison_count": int(
                primary["sample_count"].gt(0).sum()
            ),
        },
    }
