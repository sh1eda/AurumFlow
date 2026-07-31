"""Chronological candidate evaluation and deterministic uncertainty estimates."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from .definitions import CANDIDATE_COLUMNS, CONTINUOUS_FEATURES, DECISION_RULES


HORIZON_LABELS = ("30m", "60m", "120m", "session_end_1200")
PRIMARY_HORIZON = "60m"


@dataclass(frozen=True)
class AnalysisResult:
    samples: pd.DataFrame
    partition_specification: dict[str, object]
    frozen_register: dict[str, object]
    baseline_comparison: pd.DataFrame
    candidate_comparison: pd.DataFrame
    standalone_results: pd.DataFrame
    feature_relationships: pd.DataFrame
    neutral_outcome_results: pd.DataFrame
    robustness_results: pd.DataFrame
    sensitivity_results: pd.DataFrame
    holdout_results: pd.DataFrame
    phase1_summary: dict[str, object]


def chronological_partitions(samples: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Assign 50/25/25 whole-session partitions without shuffling."""

    output = samples.copy()
    dates = sorted(output["session_date"].astype(str).unique().tolist())
    if len(dates) < 12:
        raise ValueError("at least 12 chronological sessions are required")
    development_count = max(1, int(math.floor(len(dates) * 0.50)))
    validation_end = max(development_count + 1, int(math.floor(len(dates) * 0.75)))
    validation_end = min(validation_end, len(dates) - 1)
    development_dates = dates[:development_count]
    validation_dates = dates[development_count:validation_end]
    holdout_dates = dates[validation_end:]
    mapping = {
        **{value: "development" for value in development_dates},
        **{value: "validation" for value in validation_dates},
        **{value: "holdout" for value in holdout_dates},
    }
    output["partition"] = output["session_date"].astype(str).map(mapping)
    first = pd.Timestamp(dates[0])
    last = pd.Timestamp(dates[-1])
    coverage_years = (last - first).days / 365.25
    specification: dict[str, object] = {
        "method": "chronological whole-session 50/25/25 split",
        "random_split": False,
        "development": {
            "start": development_dates[0],
            "end": development_dates[-1],
            "sessions": len(development_dates),
            "evaluation_rows": int(output["partition"].eq("development").sum()),
            "purpose": "candidate evidence, composite membership, and baseline freezing",
        },
        "validation": {
            "start": validation_dates[0],
            "end": validation_dates[-1],
            "sessions": len(validation_dates),
            "evaluation_rows": int(output["partition"].eq("validation").sum()),
            "purpose": "definition confirmation and robustness checks",
        },
        "holdout": {
            "start": holdout_dates[0],
            "end": holdout_dates[-1],
            "sessions": len(holdout_dates),
            "evaluation_rows": int(output["partition"].eq("holdout").sum()),
            "purpose": "untouched final evaluation after all definitions are frozen",
        },
        "coverage_years": round(coverage_years, 4),
        "history_confidence_cap_applies": coverage_years < 2.0,
        "holdout_isolation_rule": "No holdout row is passed to baseline fitting, development gates, threshold selection, or Model E family selection.",
    }
    return output, specification


def _sign(value: float, deadband: float = 0.0) -> int:
    return 1 if value > deadband else -1 if value < -deadband else 0


def _mean_map(frame: pd.DataFrame, key: str, outcome: str) -> dict[str, float]:
    grouped = frame.dropna(subset=[outcome]).groupby(key, observed=True)[outcome].mean()
    return {str(index): float(value) for index, value in grouped.items()}


def fit_baselines(development: pd.DataFrame) -> dict[str, object]:
    """Fit simple timing/context baselines on development rows only."""

    models: dict[str, object] = {"fit_partition": "development", "horizons": {}}
    for horizon in HORIZON_LABELS:
        outcome = f"forward_return_bps_{horizon}"
        valid = development.dropna(subset=[outcome]).copy()
        overall = float(valid[outcome].mean()) if not valid.empty else 0.0
        eval_means = _mean_map(valid, "evaluation_clock", outcome)
        dow_means = _mean_map(valid, "day_of_week", outcome)
        news_means = _mean_map(valid, "news_0830", outcome)
        horizon_model: dict[str, object] = {
            "overall_mean": overall,
            "evaluation_time_means": eval_means,
            "day_of_week_means": dow_means,
            "news_means": news_means,
        }
        probe = apply_baselines(valid, {"horizons": {horizon: horizon_model}})
        accuracy: dict[str, float] = {}
        for baseline in (
            "unconditional",
            "evaluation_time",
            "day_of_week",
            "news",
            "additive_timing",
            "prior_momentum",
        ):
            direction = probe[f"baseline_{baseline}_{horizon}"]
            actual = probe[f"direction_{horizon}"]
            mask = direction.ne(0) & actual.ne(0) & actual.notna()
            accuracy[baseline] = float(direction[mask].eq(actual[mask]).mean()) if mask.any() else math.nan
        finite = {key: value for key, value in accuracy.items() if pd.notna(value)}
        best = max(finite, key=finite.get) if finite else "unconditional"
        horizon_model["development_accuracy"] = accuracy
        horizon_model["selected_incremental_baseline"] = best
        models["horizons"][horizon] = horizon_model
    return models


def apply_baselines(samples: pd.DataFrame, models: Mapping[str, object]) -> pd.DataFrame:
    output = samples.copy()
    horizon_models = models.get("horizons", {})
    for horizon, raw_model in horizon_models.items():
        model = dict(raw_model)
        overall = float(model.get("overall_mean", 0.0))
        evaluation_means = dict(model.get("evaluation_time_means", {}))
        dow_means = dict(model.get("day_of_week_means", {}))
        news_means = dict(model.get("news_means", {}))
        eval_prediction = output["evaluation_clock"].astype(str).map(evaluation_means).fillna(overall)
        dow_prediction = output["day_of_week"].astype(str).map(dow_means).fillna(overall)
        news_prediction = output["news_0830"].astype(str).map(news_means).fillna(overall)
        additive = eval_prediction + (dow_prediction - overall) + (news_prediction - overall)
        output[f"baseline_unconditional_{horizon}"] = _sign(overall)
        output[f"baseline_evaluation_time_{horizon}"] = eval_prediction.map(_sign).astype(int)
        output[f"baseline_day_of_week_{horizon}"] = dow_prediction.map(_sign).astype(int)
        output[f"baseline_news_{horizon}"] = news_prediction.map(_sign).astype(int)
        output[f"baseline_additive_timing_{horizon}"] = additive.map(_sign).astype(int)
        output[f"baseline_prior_momentum_{horizon}"] = output["prior_return_120m_bps"].fillna(0).map(_sign).astype(int)
        selected = str(model.get("selected_incremental_baseline", "unconditional"))
        selected_column = f"baseline_{selected}_{horizon}"
        output[f"baseline_selected_{horizon}"] = output[selected_column]
    return output


def _cluster_summary(values: np.ndarray, clusters: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique, inverse = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inverse, weights=values, minlength=len(unique))
    counts = np.bincount(inverse, minlength=len(unique)).astype(float)
    return sums, counts


def bootstrap_mean_ci(
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
    if len(array) < 2 or len(np.unique(labels)) < 2:
        return math.nan, math.nan
    sums, counts = _cluster_summary(array, labels)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sums), size=(resamples, len(sums)))
    sampled = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(sampled, [alpha, 1.0 - alpha])
    return float(lower), float(upper)


def _robust_mad(values: pd.Series) -> float:
    clean = values.dropna().astype(float)
    if clean.empty:
        return math.nan
    median = float(clean.median())
    return float((clean - median).abs().median())


def candidate_metric(
    frame: pd.DataFrame,
    *,
    candidate: str,
    direction_column: str,
    horizon: str,
    partition: str,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    outcome = f"forward_return_bps_{horizon}"
    outcome_direction = f"direction_{horizon}"
    required = frame[direction_column].notna() & frame[outcome].notna()
    usable = frame.loc[required].copy()
    directional = usable[usable[direction_column].ne(0)].copy()
    aligned = directional[direction_column].astype(float) * directional[outcome].astype(float)
    lower, upper = bootstrap_mean_ci(
        aligned,
        directional["session_date"],
        resamples=resamples,
        seed=seed,
    )
    accuracy_mask = directional[outcome_direction].ne(0) & directional[outcome_direction].notna()
    correct = directional.loc[accuracy_mask, direction_column].eq(
        directional.loc[accuracy_mask, outcome_direction]
    )
    baseline_column = f"baseline_selected_{horizon}"
    paired = directional[accuracy_mask & directional[baseline_column].ne(0)].copy()
    if not paired.empty:
        candidate_correct = paired[direction_column].eq(paired[outcome_direction]).astype(float)
        baseline_correct = paired[baseline_column].eq(paired[outcome_direction]).astype(float)
        accuracy_lift_values = candidate_correct - baseline_correct
        lift_lower, lift_upper = bootstrap_mean_ci(
            accuracy_lift_values,
            paired["session_date"],
            resamples=resamples,
            seed=seed + 1,
        )
        accuracy_lift = float(accuracy_lift_values.mean())
        aligned_difference = (
            paired[direction_column].astype(float) - paired[baseline_column].astype(float)
        ) * paired[outcome].astype(float)
        incremental_return = float(aligned_difference.mean())
        inc_lower, inc_upper = bootstrap_mean_ci(
            aligned_difference,
            paired["session_date"],
            resamples=resamples,
            seed=seed + 2,
        )
    else:
        accuracy_lift = lift_lower = lift_upper = math.nan
        incremental_return = inc_lower = inc_upper = math.nan

    long_aligned = aligned[directional[direction_column].eq(1)]
    short_aligned = aligned[directional[direction_column].eq(-1)]
    outcome_std = float(directional[outcome].std(ddof=1)) if len(directional) > 1 else math.nan
    mean_aligned = float(aligned.mean()) if not aligned.empty else math.nan
    effect_size = mean_aligned / outcome_std if pd.notna(outcome_std) and outcome_std > 0 else math.nan
    return {
        "candidate": candidate,
        "direction_column": direction_column,
        "partition": partition,
        "horizon": horizon,
        "test_classification": "preregistered",
        "observations_total": int(len(frame)),
        "observations_with_outcome": int(len(usable)),
        "excluded_missing": int(len(frame) - len(usable)),
        "directional_observations": int(len(directional)),
        "neutral_candidate_observations": int(usable[direction_column].eq(0).sum()),
        "long_observations": int(directional[direction_column].eq(1).sum()),
        "short_observations": int(directional[direction_column].eq(-1).sum()),
        "mean_forward_return_bps": float(usable[outcome].mean()) if not usable.empty else math.nan,
        "median_forward_return_bps": float(usable[outcome].median()) if not usable.empty else math.nan,
        "std_forward_return_bps": float(usable[outcome].std(ddof=1)) if len(usable) > 1 else math.nan,
        "mad_forward_return_bps": _robust_mad(usable[outcome]),
        "mean_aligned_return_bps": mean_aligned,
        "median_aligned_return_bps": float(aligned.median()) if not aligned.empty else math.nan,
        "aligned_return_ci_lower": lower,
        "aligned_return_ci_upper": upper,
        "standardized_effect_size": effect_size,
        "directional_accuracy": float(correct.mean()) if not correct.empty else math.nan,
        "directional_accuracy_n": int(len(correct)),
        "near_zero_outcomes": int(directional[outcome_direction].eq(0).sum()),
        "long_mean_aligned_return_bps": float(long_aligned.mean()) if not long_aligned.empty else math.nan,
        "short_mean_aligned_return_bps": float(short_aligned.mean()) if not short_aligned.empty else math.nan,
        "selected_baseline": frame.get(
            f"selected_baseline_name_{horizon}", pd.Series([None])
        ).iloc[0]
        if not frame.empty
        else None,
        "accuracy_lift_vs_selected_baseline": accuracy_lift,
        "accuracy_lift_ci_lower": lift_lower,
        "accuracy_lift_ci_upper": lift_upper,
        "incremental_aligned_return_bps": incremental_return,
        "incremental_return_ci_lower": inc_lower,
        "incremental_return_ci_upper": inc_upper,
        "probabilistic_calibration": "not_applicable_deterministic_context_label",
    }


def _passes_development_gate(metric: Mapping[str, object]) -> bool:
    return bool(
        int(metric["directional_observations"]) >= int(DECISION_RULES["minimum_directional_observations_per_partition"])
        and int(metric["long_observations"]) >= int(DECISION_RULES["minimum_long_and_short_observations"])
        and int(metric["short_observations"]) >= int(DECISION_RULES["minimum_long_and_short_observations"])
        and float(metric["mean_aligned_return_bps"]) > 0
        and float(metric["aligned_return_ci_lower"]) > 0
        and float(metric["standardized_effect_size"]) >= 0.10
        and float(metric["directional_accuracy"]) >= 0.52
        and float(metric["long_mean_aligned_return_bps"]) > 0
        and float(metric["short_mean_aligned_return_bps"]) > 0
    )


def freeze_candidate_register(
    development: pd.DataFrame,
    *,
    baseline_models: Mapping[str, object],
    resamples: int,
    seed: int,
) -> dict[str, object]:
    """Freeze Model E membership using development data and no other partition."""

    evidence: dict[str, object] = {}
    selected: list[str] = []
    for position, (candidate, column) in enumerate(list(CANDIDATE_COLUMNS.items())[:4]):
        metric = candidate_metric(
            development,
            candidate=candidate,
            direction_column=column,
            horizon=PRIMARY_HORIZON,
            partition="development",
            resamples=resamples,
            seed=seed + position * 10,
        )
        passed = _passes_development_gate(metric)
        evidence[candidate] = {**metric, "passes_development_gate": passed}
        if passed:
            selected.append(column)
    return {
        "frozen_before_validation_and_holdout": True,
        "source_partition": "development",
        "primary_horizon": PRIMARY_HORIZON,
        "decision_rules": DECISION_RULES,
        "baseline_models": baseline_models,
        "model_e_selected_direction_columns": selected,
        "model_e_rule": "unweighted majority; tie or no selected families is neutral",
        "development_evidence": evidence,
    }


def apply_frozen_composite(samples: pd.DataFrame, frozen: Mapping[str, object]) -> pd.DataFrame:
    output = samples.copy()
    columns = list(frozen.get("model_e_selected_direction_columns", []))
    if not columns:
        output["candidate_e"] = 0
    else:
        votes = output[columns].fillna(0).astype(int).sum(axis=1)
        output["candidate_e"] = np.sign(votes).astype(int)
    return output


def _baseline_table(samples: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for partition, part in samples.groupby("partition", sort=False):
        for horizon in HORIZON_LABELS:
            outcome = f"direction_{horizon}"
            returns = f"forward_return_bps_{horizon}"
            for baseline in (
                "unconditional",
                "evaluation_time",
                "day_of_week",
                "news",
                "additive_timing",
                "prior_momentum",
            ):
                column = f"baseline_{baseline}_{horizon}"
                mask = part[column].ne(0) & part[outcome].ne(0) & part[outcome].notna()
                aligned = part.loc[mask, column].astype(float) * part.loc[mask, returns].astype(float)
                records.append(
                    {
                        "partition": partition,
                        "horizon": horizon,
                        "baseline": baseline,
                        "observations": int(mask.sum()),
                        "directional_accuracy": float(part.loc[mask, column].eq(part.loc[mask, outcome]).mean()) if mask.any() else math.nan,
                        "mean_aligned_return_bps": float(aligned.mean()) if not aligned.empty else math.nan,
                    }
                )
    return pd.DataFrame.from_records(records)


def _candidate_tables(
    samples: pd.DataFrame,
    *,
    resamples: int,
    seed: int,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for partition, part in samples.groupby("partition", sort=False):
        for horizon_position, horizon in enumerate(HORIZON_LABELS):
            for candidate_position, (candidate, column) in enumerate(CANDIDATE_COLUMNS.items()):
                records.append(
                    candidate_metric(
                        part,
                        candidate=candidate,
                        direction_column=column,
                        horizon=horizon,
                        partition=str(partition),
                        resamples=resamples,
                        seed=seed + horizon_position * 100 + candidate_position * 10 + len(records),
                    )
                )
    return pd.DataFrame.from_records(records)


def _bootstrap_correlation(
    frame: pd.DataFrame,
    x: str,
    y: str,
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    clean = frame.dropna(subset=[x, y, "session_date"])
    clusters = clean["session_date"].astype(str).unique()
    if len(clean) < 10 or len(clusters) < 5:
        return math.nan, math.nan
    labels = clean["session_date"].astype(str).to_numpy()
    _, inverse = np.unique(labels, return_inverse=True)
    ranked_x = clean[x].rank(method="average").to_numpy(dtype=float)
    ranked_y = clean[y].rank(method="average").to_numpy(dtype=float)
    cluster_count = len(clusters)
    counts = np.bincount(inverse, minlength=cluster_count).astype(float)
    sum_x = np.bincount(inverse, weights=ranked_x, minlength=cluster_count)
    sum_y = np.bincount(inverse, weights=ranked_y, minlength=cluster_count)
    sum_x2 = np.bincount(inverse, weights=np.square(ranked_x), minlength=cluster_count)
    sum_y2 = np.bincount(inverse, weights=np.square(ranked_y), minlength=cluster_count)
    sum_xy = np.bincount(inverse, weights=ranked_x * ranked_y, minlength=cluster_count)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, cluster_count, size=(resamples, cluster_count))
    n = counts[draws].sum(axis=1)
    sx = sum_x[draws].sum(axis=1)
    sy = sum_y[draws].sum(axis=1)
    sx2 = sum_x2[draws].sum(axis=1)
    sy2 = sum_y2[draws].sum(axis=1)
    sxy = sum_xy[draws].sum(axis=1)
    numerator = n * sxy - sx * sy
    denominator = np.sqrt((n * sx2 - np.square(sx)) * (n * sy2 - np.square(sy)))
    values = numerator / np.where(denominator > 0, denominator, np.nan)
    values = values[np.isfinite(values)]
    if not len(values):
        return math.nan, math.nan
    return tuple(float(value) for value in np.quantile(values, [0.025, 0.975]))


def _feature_relationship_table(
    samples: pd.DataFrame,
    *,
    resamples: int,
    seed: int,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for partition, part in samples.groupby("partition", sort=False):
        for horizon_position, horizon in enumerate(HORIZON_LABELS):
            outcome = f"forward_return_bps_{horizon}"
            for feature_position, feature in enumerate(CONTINUOUS_FEATURES):
                if feature not in part:
                    continue
                clean = part.dropna(subset=[feature, outcome])
                correlation = (
                    clean[feature].rank(method="average").corr(
                        clean[outcome].rank(method="average")
                    )
                    if len(clean) >= 3
                    else math.nan
                )
                lower, upper = _bootstrap_correlation(
                    clean,
                    feature,
                    outcome,
                    resamples=resamples,
                    seed=seed + horizon_position * 100 + feature_position,
                )
                records.append(
                    {
                        "partition": partition,
                        "horizon": horizon,
                        "feature": feature,
                        "test_classification": "exploratory_family_bh_control_not_applied_point_estimates_not_ranked",
                        "observations": int(len(clean)),
                        "spearman_correlation": float(correlation) if pd.notna(correlation) else math.nan,
                        "bootstrap_ci_lower": lower,
                        "bootstrap_ci_upper": upper,
                    }
                )
    return pd.DataFrame.from_records(records)


def _simple_subgroup_metric(
    frame: pd.DataFrame,
    *,
    direction_column: str,
    horizon: str = PRIMARY_HORIZON,
) -> tuple[int, float, float]:
    outcome = f"forward_return_bps_{horizon}"
    actual_direction = f"direction_{horizon}"
    clean = frame[
        frame[direction_column].ne(0)
        & frame[direction_column].notna()
        & frame[outcome].notna()
    ]
    aligned = clean[direction_column].astype(float) * clean[outcome].astype(float)
    accuracy_mask = clean[actual_direction].ne(0) & clean[actual_direction].notna()
    accuracy = clean.loc[accuracy_mask, direction_column].eq(
        clean.loc[accuracy_mask, actual_direction]
    ).mean()
    return (
        int(len(clean)),
        float(aligned.mean()) if not aligned.empty else math.nan,
        float(accuracy) if pd.notna(accuracy) else math.nan,
    )


def _robustness_table(samples: pd.DataFrame) -> pd.DataFrame:
    evaluation = samples[samples["partition"].isin(["validation", "holdout"])].copy()
    evaluation["quarter"] = pd.PeriodIndex(
        pd.to_datetime(evaluation["session_date"]), freq="Q"
    ).astype(str)
    records: list[dict[str, object]] = []
    for candidate, column in CANDIDATE_COLUMNS.items():
        for partition, part in evaluation.groupby("partition", sort=False):
            strata = {
                "evaluation_time": part["evaluation_clock"].astype(str),
                "news_regime": part["news_0830"].astype(str),
                "news_day_class": part["news_day_class"].astype(str),
                "day_of_week": part["day_of_week"].astype(str),
                "subperiod_quarter": part["quarter"].astype(str),
                "candidate_direction": part[column].astype(str),
            }
            for test_name, labels in strata.items():
                for subgroup in sorted(labels.unique()):
                    group = part[labels.eq(subgroup)]
                    n, mean_aligned, accuracy = _simple_subgroup_metric(
                        group, direction_column=column
                    )
                    records.append(
                        {
                            "candidate": candidate,
                            "partition": partition,
                            "robustness_test": test_name,
                            "subgroup": subgroup,
                            "observations": n,
                            "mean_aligned_return_bps": mean_aligned,
                            "directional_accuracy": accuracy,
                            "adequate_subgroup_sample": n >= 20,
                            "positive_directional_evidence": bool(n >= 20 and pd.notna(mean_aligned) and mean_aligned > 0),
                        }
                    )
            filters = {
                "maximum_spread_le_0.50": part["maximum_spread_prior_30m"].le(0.50),
                "maximum_spread_le_1.00": part["maximum_spread_prior_30m"].le(1.00),
                "complete_outcome_window": part["outcome_coverage_60m"].ge(1.0),
            }
            for name, mask in filters.items():
                n, mean_aligned, accuracy = _simple_subgroup_metric(
                    part[mask], direction_column=column
                )
                records.append(
                    {
                        "candidate": candidate,
                        "partition": partition,
                        "robustness_test": "data_filter",
                        "subgroup": name,
                        "observations": n,
                        "mean_aligned_return_bps": mean_aligned,
                        "directional_accuracy": accuracy,
                        "adequate_subgroup_sample": n >= 20,
                        "positive_directional_evidence": bool(n >= 20 and pd.notna(mean_aligned) and mean_aligned > 0),
                    }
                )
    return pd.DataFrame.from_records(records)


def _distribution_record(
    values: pd.Series,
    clusters: pd.Series,
    *,
    candidate: str,
    partition: str,
    horizon: str,
    outcome: str,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    clean = values.dropna().astype(float)
    cluster_values = clusters.loc[clean.index]
    lower, upper = bootstrap_mean_ci(
        clean,
        cluster_values,
        resamples=resamples,
        seed=seed,
    )
    return {
        "candidate": candidate,
        "partition": partition,
        "horizon": horizon,
        "outcome": outcome,
        "observations": int(len(clean)),
        "mean": float(clean.mean()) if not clean.empty else math.nan,
        "median": float(clean.median()) if not clean.empty else math.nan,
        "standard_deviation": float(clean.std(ddof=1)) if len(clean) > 1 else math.nan,
        "median_absolute_deviation": _robust_mad(clean),
        "bootstrap_mean_ci_lower": lower,
        "bootstrap_mean_ci_upper": upper,
        "test_classification": "preregistered_neutral_outcome_summary",
    }


def _neutral_outcome_table(
    samples: pd.DataFrame,
    *,
    resamples: int,
    seed: int,
) -> pd.DataFrame:
    """Summarize excursion, reach, expansion, and volatility without trade rules."""

    records: list[dict[str, object]] = []
    for partition_position, (partition, part) in enumerate(
        samples.groupby("partition", sort=False)
    ):
        for horizon_position, horizon in enumerate(HORIZON_LABELS):
            unconditional_outcomes = (
                f"forward_return_bps_{horizon}",
                f"absolute_return_bps_{horizon}",
                f"up_excursion_bps_{horizon}",
                f"down_excursion_bps_{horizon}",
                f"range_expansion_bps_{horizon}",
                f"realized_volatility_bps_{horizon}",
                f"reaches_pdh_{horizon}",
                f"reaches_pdl_{horizon}",
                f"reaches_pwh_{horizon}",
                f"reaches_pwl_{horizon}",
                f"reaches_monday_high_{horizon}",
                f"reaches_monday_low_{horizon}",
            )
            for outcome_position, outcome in enumerate(unconditional_outcomes):
                records.append(
                    _distribution_record(
                        part[outcome],
                        part["session_date"],
                        candidate="UNCONDITIONAL",
                        partition=str(partition),
                        horizon=horizon,
                        outcome=outcome.removesuffix(f"_{horizon}"),
                        resamples=resamples,
                        seed=seed
                        + partition_position * 10000
                        + horizon_position * 1000
                        + outcome_position,
                    )
                )
            for candidate_position, (candidate, column) in enumerate(
                CANDIDATE_COLUMNS.items()
            ):
                active = part[part[column].ne(0) & part[column].notna()].copy()
                direction = active[column].astype(int)
                up = active[f"up_excursion_bps_{horizon}"].astype(float)
                down = active[f"down_excursion_bps_{horizon}"].astype(float)
                derived: dict[str, pd.Series] = {
                    "favorable_excursion_bps": pd.Series(
                        np.where(direction.gt(0), up, down), index=active.index
                    ),
                    "adverse_excursion_bps": pd.Series(
                        np.where(direction.gt(0), down, up), index=active.index
                    ),
                    "range_expansion_bps": active[f"range_expansion_bps_{horizon}"],
                    "realized_volatility_bps": active[
                        f"realized_volatility_bps_{horizon}"
                    ],
                    "absolute_return_bps": active[f"absolute_return_bps_{horizon}"],
                }
                derived["net_excursion_bps"] = (
                    derived["favorable_excursion_bps"]
                    - derived["adverse_excursion_bps"]
                )
                upper_reach = active[
                    [
                        f"reaches_pdh_{horizon}",
                        f"reaches_pwh_{horizon}",
                        f"reaches_monday_high_{horizon}",
                    ]
                ].max(axis=1, skipna=True)
                lower_reach = active[
                    [
                        f"reaches_pdl_{horizon}",
                        f"reaches_pwl_{horizon}",
                        f"reaches_monday_low_{horizon}",
                    ]
                ].max(axis=1, skipna=True)
                derived["directional_external_level_reach_rate"] = pd.Series(
                    np.where(direction.gt(0), upper_reach, lower_reach),
                    index=active.index,
                    dtype=float,
                )
                for outcome_position, (outcome, values) in enumerate(derived.items()):
                    records.append(
                        _distribution_record(
                            values,
                            active["session_date"],
                            candidate=candidate,
                            partition=str(partition),
                            horizon=horizon,
                            outcome=outcome,
                            resamples=resamples,
                            seed=seed
                            + partition_position * 10000
                            + horizon_position * 1000
                            + candidate_position * 100
                            + outcome_position,
                        )
                    )
    return pd.DataFrame.from_records(records)


def _sensitivity_table(samples: pd.DataFrame) -> pd.DataFrame:
    alternatives = {
        "MODEL_A_STRUCTURE_ONLY": ("candidate_a", "candidate_a_width3", "swing_width_2_vs_3"),
        "MODEL_B_RANGE_LOCATION_ONLY": ("candidate_b", "candidate_b_reversion", "continuation_vs_reversion_formulation"),
        "MODEL_C_LIQUIDITY_POSITION_ONLY": ("candidate_c", "candidate_c_away", "toward_vs_away_nearest_level"),
        "MODEL_D_DISPLACEMENT_CONTEXT_ONLY": ("candidate_d", "candidate_d_robust_volatility", "atr_mean_vs_robust_median_normalization"),
    }
    development_returns = samples.loc[
        samples["partition"].eq("development"), "forward_return_bps_60m"
    ].dropna()
    frozen_lower, frozen_upper = development_returns.quantile([0.01, 0.99])
    records: list[dict[str, object]] = []
    for partition, part in samples.groupby("partition", sort=False):
        for candidate, (primary, alternate, sensitivity) in alternatives.items():
            for label, column in (("primary", primary), ("alternate", alternate)):
                for horizon in HORIZON_LABELS:
                    n, mean_aligned, accuracy = _simple_subgroup_metric(
                        part, direction_column=column, horizon=horizon
                    )
                    records.append(
                        {
                            "candidate": candidate,
                            "partition": partition,
                            "sensitivity": sensitivity,
                            "formulation": label,
                            "direction_column": column,
                            "horizon": horizon,
                            "observations": n,
                            "mean_aligned_return_bps": mean_aligned,
                            "directional_accuracy": accuracy,
                        }
                    )
        outcome = "forward_return_bps_60m"
        winsorized = part.copy()
        winsorized[outcome] = winsorized[outcome].clip(frozen_lower, frozen_upper)
        for candidate, column in CANDIDATE_COLUMNS.items():
            for label, source in (("raw", part), ("winsorized_1_99", winsorized)):
                n, mean_aligned, accuracy = _simple_subgroup_metric(
                    source, direction_column=column
                )
                records.append(
                    {
                        "candidate": candidate,
                        "partition": partition,
                        "sensitivity": "outlier_treatment",
                        "formulation": label,
                        "direction_column": column,
                        "horizon": PRIMARY_HORIZON,
                        "observations": n,
                        "mean_aligned_return_bps": mean_aligned,
                        "directional_accuracy": accuracy,
                    }
                )
    return pd.DataFrame.from_records(records)


def _decision_summary(
    candidate_results: pd.DataFrame,
    robustness: pd.DataFrame,
    partition_spec: Mapping[str, object],
    frozen: Mapping[str, object],
) -> dict[str, object]:
    primary = candidate_results[candidate_results["horizon"].eq(PRIMARY_HORIZON)].copy()
    adequate = int(DECISION_RULES["minimum_directional_observations_per_partition"])
    candidates: dict[str, object] = {}
    strong_candidates: list[str] = []
    cautious_candidates: list[str] = []
    for candidate in CANDIDATE_COLUMNS:
        rows = primary[primary["candidate"].eq(candidate)].set_index("partition")
        if candidate == "MODEL_E_SIMPLE_COMPOSITE" and "development" in rows.index:
            development_pass = _passes_development_gate(rows.loc["development"].to_dict())
        else:
            development_pass = bool(
                candidate in frozen.get("development_evidence", {})
                and frozen["development_evidence"][candidate].get("passes_development_gate", False)
            )
        validation = rows.loc["validation"] if "validation" in rows.index else None
        holdout = rows.loc["holdout"] if "holdout" in rows.index else None
        validation_positive = bool(
            validation is not None
            and validation["directional_observations"] >= adequate
            and validation["mean_aligned_return_bps"] > 0
        )
        holdout_positive = bool(
            holdout is not None
            and holdout["directional_observations"] >= adequate
            and holdout["mean_aligned_return_bps"] > 0
        )
        holdout_ci_positive = bool(
            holdout is not None and holdout["aligned_return_ci_lower"] > 0
        )
        incremental_positive = bool(
            holdout is not None and holdout["accuracy_lift_ci_lower"] > 0
        )
        robust_rows = robustness[
            robustness["candidate"].eq(candidate)
            & robustness["adequate_subgroup_sample"]
        ]
        robust_fraction = float(robust_rows["positive_directional_evidence"].mean()) if not robust_rows.empty else math.nan
        full_pass = bool(
            development_pass
            and validation_positive
            and holdout_positive
            and holdout_ci_positive
            and incremental_positive
            and pd.notna(robust_fraction)
            and robust_fraction >= 0.70
        )
        cautious = bool(development_pass and validation_positive and holdout_positive)
        if full_pass:
            strong_candidates.append(candidate)
        elif cautious:
            cautious_candidates.append(candidate)
        candidates[candidate] = {
            "development_gate": development_pass,
            "validation_positive": validation_positive,
            "holdout_positive": holdout_positive,
            "holdout_ci_excludes_zero": holdout_ci_positive,
            "holdout_incremental_accuracy_ci_excludes_zero": incremental_positive,
            "adequate_robustness_positive_fraction": robust_fraction,
            "full_proceed_gate": full_pass,
            "caution_gate": cautious,
        }

    history_cap = bool(partition_spec["history_confidence_cap_applies"])
    if strong_candidates and not history_cap:
        decision = "PROCEED"
        rationale = "At least one candidate passed the frozen standalone, incremental, holdout, and robustness gates."
    elif strong_candidates or cautious_candidates:
        decision = "PROCEED_WITH_CAUTION"
        rationale = "Some frozen evidence repeated, but uncertainty, robustness, or the preregistered history-breadth cap prevents PROCEED."
    else:
        all_adequate = bool(
            primary[primary["partition"].isin(["validation", "holdout"])][
                "directional_observations"
            ].ge(adequate).all()
        )
        if all_adequate and not history_cap:
            decision = "REJECT_CURRENT_CANDIDATE_DEFINITIONS"
            rationale = "Adequate validation and holdout samples did not show stable positive evidence for the registered candidates."
        else:
            decision = "INCONCLUSIVE"
            rationale = "The one-year history, candidate-neutral sample loss, and/or uncertainty prevent a reliable accept/reject conclusion."
    return {
        "phase1_decision": decision,
        "rationale": rationale,
        "history_confidence_cap_applies": history_cap,
        "strong_candidates": strong_candidates,
        "cautious_candidates": cautious_candidates,
        "candidate_gate_results": candidates,
        "model_e_selected_direction_columns": frozen.get(
            "model_e_selected_direction_columns", []
        ),
        "multiple_comparison_policy": "A-D and the conditional E are preregistered. Feature correlations and subgroup slices are explicitly exploratory and are not ranked from point estimates.",
        "calibration": "Not applicable: Phase 1 candidates produce deterministic {-1,0,+1} context labels, not probabilities.",
    }


def run_analysis(
    samples: pd.DataFrame,
    *,
    bootstrap_resamples: int,
    seed: int,
) -> AnalysisResult:
    partitioned, specification = chronological_partitions(samples)
    development = partitioned[partitioned["partition"].eq("development")].copy()
    baseline_models = fit_baselines(development)
    with_baselines = apply_baselines(partitioned, baseline_models)
    for horizon, model in baseline_models["horizons"].items():
        with_baselines[f"selected_baseline_name_{horizon}"] = model[
            "selected_incremental_baseline"
        ]
    development_with_baselines = with_baselines[
        with_baselines["partition"].eq("development")
    ].copy()
    frozen = freeze_candidate_register(
        development_with_baselines,
        baseline_models=baseline_models,
        resamples=bootstrap_resamples,
        seed=seed,
    )
    evaluated = apply_frozen_composite(with_baselines, frozen)
    baseline_table = _baseline_table(evaluated)
    candidate_table = _candidate_tables(
        evaluated, resamples=bootstrap_resamples, seed=seed + 1000
    )
    feature_table = _feature_relationship_table(
        evaluated,
        resamples=min(500, bootstrap_resamples),
        seed=seed + 2000,
    )
    neutral_outcomes = _neutral_outcome_table(
        evaluated,
        resamples=min(500, bootstrap_resamples),
        seed=seed + 2500,
    )
    robustness = _robustness_table(evaluated)
    sensitivity = _sensitivity_table(evaluated)
    summary = _decision_summary(candidate_table, robustness, specification, frozen)
    standalone = candidate_table[candidate_table["candidate"].ne("MODEL_E_SIMPLE_COMPOSITE")].copy()
    holdout = candidate_table[candidate_table["partition"].eq("holdout")].copy()
    return AnalysisResult(
        samples=evaluated,
        partition_specification=specification,
        frozen_register=frozen,
        baseline_comparison=baseline_table,
        candidate_comparison=candidate_table,
        standalone_results=standalone,
        feature_relationships=feature_table,
        neutral_outcome_results=neutral_outcomes,
        robustness_results=robustness,
        sensitivity_results=sensitivity,
        holdout_results=holdout,
        phase1_summary=summary,
    )
