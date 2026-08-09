"""Preregistered D006 inference, adequacy, stability, BH, and disposition rules."""

from __future__ import annotations

from hashlib import sha256
from math import sqrt
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
from scipy import stats

from .config import COMPONENT_DISPOSITIONS, D006Config, FIXED_MULTIPLE_TESTING


def robust_summaries(values: Iterable[float]) -> dict[str, float | int | None]:
    data = np.asarray(list(values), dtype=float)
    data = data[np.isfinite(data)]
    if not len(data):
        return {"n": 0, "median": None, "q25": None, "q75": None, "trimmed_mean_1pct": None, "absolute_1pct_removed_mean": None}
    ordered = np.sort(data)
    trim = int(np.floor(len(ordered) * 0.01))
    trimmed = ordered[trim: len(ordered) - trim] if trim and len(ordered) > 2 * trim else ordered
    absolute_order = np.argsort(np.abs(data))
    keep = max(1, int(np.floor(len(data) * 0.99)))
    return {
        "n": int(len(data)),
        "median": float(np.median(data)),
        "q25": float(np.quantile(data, 0.25)),
        "q75": float(np.quantile(data, 0.75)),
        "trimmed_mean_1pct": float(np.mean(trimmed)),
        "absolute_1pct_removed_mean": float(np.mean(data[absolute_order[:keep]])),
    }


def mean_test(values: Iterable[float], confidence: float = 0.95) -> dict[str, object]:
    data = np.asarray(list(values), dtype=float)
    data = data[np.isfinite(data)]
    result: dict[str, object] = {
        "n": int(len(data)),
        "mean": None,
        "std": None,
        "standardized_mean": None,
        "ci_lower": None,
        "ci_upper": None,
        "p_value": None,
        "robust": robust_summaries(data),
    }
    if not len(data):
        return result
    mean = float(np.mean(data))
    result["mean"] = mean
    if len(data) < 2:
        return result
    std = float(np.std(data, ddof=1))
    standard_error = std / sqrt(len(data))
    critical = float(stats.t.ppf((1 + confidence) / 2, len(data) - 1))
    result.update(
        {
            "std": std,
            "standardized_mean": (mean / std if std > 0 else None),
            "ci_lower": mean - critical * standard_error,
            "ci_upper": mean + critical * standard_error,
            "p_value": float(stats.ttest_1samp(data, popmean=0.0).pvalue),
        }
    )
    return result


def paired_test(pairs: pd.DataFrame, *, treatment: str, control: str, confidence: float = 0.95) -> dict[str, object]:
    valid = pairs[[treatment, control]].dropna()
    differences = valid[treatment].to_numpy(dtype=float) - valid[control].to_numpy(dtype=float)
    result = mean_test(differences, confidence)
    result.update(
        {
            "treatment_mean": float(valid[treatment].mean()) if len(valid) else None,
            "control_mean": float(valid[control].mean()) if len(valid) else None,
            "median_paired_difference": float(np.median(differences)) if len(differences) else None,
        }
    )
    return result


def _cell_seed(base_seed: int, label: str) -> int:
    digest = sha256(f"{base_seed}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def trading_date_bootstrap(
    pairs: pd.DataFrame,
    *,
    difference_column: str,
    date_column: str,
    label: str,
    config: D006Config = D006Config(),
) -> dict[str, object]:
    valid = pairs[[difference_column, date_column]].dropna()
    grouped = [group[difference_column].to_numpy(dtype=float) for _, group in valid.groupby(date_column, sort=True)]
    if not grouped:
        return {"resamples": config.bootstrap_resamples, "seed": _cell_seed(config.bootstrap_seed, label), "mean": None, "ci_lower": None, "ci_upper": None}
    rng = np.random.default_rng(_cell_seed(config.bootstrap_seed, label))
    estimates = np.empty(config.bootstrap_resamples, dtype=float)
    for position in range(config.bootstrap_resamples):
        selected = rng.integers(0, len(grouped), size=len(grouped))
        estimates[position] = float(np.mean(np.concatenate([grouped[index] for index in selected])))
    alpha = 1.0 - config.confidence_level
    return {
        "resamples": config.bootstrap_resamples,
        "seed": _cell_seed(config.bootstrap_seed, label),
        "mean": float(np.mean(estimates)),
        "ci_lower": float(np.quantile(estimates, alpha / 2)),
        "ci_upper": float(np.quantile(estimates, 1 - alpha / 2)),
    }


def benjamini_hochberg(results: Mapping[str, Mapping[str, object]], *, family: str) -> dict[str, dict[str, object]]:
    registry = next(item for item in FIXED_MULTIPLE_TESTING if item.name == family)
    if len(results) != registry.hypotheses:
        raise ValueError(f"{family} must retain exactly {registry.hypotheses} registered hypotheses")
    evaluated = [(name, float(values["p_value"])) for name, values in results.items() if values.get("p_value") is not None]
    ranked = sorted(evaluated, key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 1.0
    for reverse_rank, (name, p_value) in reversed(list(enumerate(ranked, start=1))):
        candidate = min(1.0, p_value * registry.hypotheses / reverse_rank)
        running = min(running, candidate)
        adjusted[name] = running
    output: dict[str, dict[str, object]] = {}
    for name, values in results.items():
        row = dict(values)
        row["q_value"] = adjusted.get(name)
        row["bh_reject"] = bool(adjusted.get(name, 1.0) <= registry.q) if name in adjusted else False
        output[name] = row
    return output


def temporal_stability(yearly: Mapping[str, Mapping[str, object]], *, positive: bool = True) -> dict[str, object]:
    adequate = [values for values in yearly.values() if int(values.get("n", 0)) >= 2 and values.get("mean") is not None]
    sign_count = sum(float(values["mean"]) > 0 if positive else float(values["mean"]) < 0 for values in adequate)
    significant_opposite = any(
        float(values["ci_upper"]) < 0 if positive else float(values["ci_lower"]) > 0
        for values in adequate
        if values.get("ci_lower") is not None and values.get("ci_upper") is not None
    )
    return {
        "adequate_years": len(adequate),
        "required_sign_years": int(sign_count),
        "significant_opposite_year": bool(significant_opposite),
        "passed": bool(len(adequate) == 4 and sign_count >= 3 and not significant_opposite),
    }


def sample_adequacy(
    baseline_detected: pd.DataFrame,
    baseline_eligible: pd.DataFrame,
    primary_pairs: pd.DataFrame,
    expected_primary_pairs: int,
    interaction_counts: Mapping[str, int],
    geometry_counts: Mapping[str, int],
    config: D006Config = D006Config(),
) -> dict[str, object]:
    touched = baseline_eligible[baseline_eligible["first_touch_timestamp"].notna()]
    matched = primary_pairs
    requirements: dict[str, dict[str, object]] = {}

    def add(name: str, observed: int | float, required: int | float, passed: bool) -> None:
        requirements[name] = {"observed": observed, "required": required, "passed": bool(passed)}

    add("baseline_detected", len(baseline_detected), config.minimum_detected, len(baseline_detected) >= config.minimum_detected)
    for direction in ("bullish", "bearish"):
        count = int(baseline_detected["direction"].eq(direction).sum())
        add(f"baseline_{direction}", count, config.minimum_per_direction, count >= config.minimum_per_direction)
    add("lifecycle_eligible", len(baseline_eligible), config.minimum_lifecycle_eligible, len(baseline_eligible) >= config.minimum_lifecycle_eligible)
    add("touched", len(touched), config.minimum_touched, len(touched) >= config.minimum_touched)
    untouched = int(baseline_eligible["first_touch_timestamp"].isna().sum())
    add("untouched", untouched, config.minimum_untouched_when_compared, untouched >= config.minimum_untouched_when_compared)
    add("primary_pairs", len(matched), config.minimum_primary_pairs, len(matched) >= config.minimum_primary_pairs)
    add(
        "primary_endpoint_coverage",
        len(matched),
        expected_primary_pairs,
        len(matched) == expected_primary_pairs,
    )
    for year in config.validation_years:
        count = int(pd.to_datetime(matched["treatment_at"], utc=True).dt.year.eq(year).sum()) if len(matched) else 0
        add(f"primary_pairs_{year}", count, config.minimum_primary_pairs_per_year, count >= config.minimum_primary_pairs_per_year)
    for direction in ("bullish", "bearish"):
        count = int(matched["direction"].eq(direction).sum()) if len(matched) else 0
        add(f"primary_pairs_{direction}", count, config.minimum_per_direction, count >= config.minimum_per_direction)
    for session in config.required_sessions:
        count = int(touched["session"].eq(session).sum())
        add(f"touched_{session}", count, config.minimum_required_session_touches, count >= config.minimum_required_session_touches)
    for interaction in config.interactions:
        if interaction.name == "rb_alone":
            continue
        observed = int(interaction_counts.get(interaction.name, 0))
        add(f"interaction_{interaction.name}", observed, interaction.minimum_sample, observed >= interaction.minimum_sample)
    proximal = int(geometry_counts.get("proximal", 0))
    for boundary in ("midpoint", "distal"):
        count = int(geometry_counts.get(boundary, 0))
        required_retention = config.minimum_geometry_retention * proximal
        add(f"geometry_{boundary}_count", count, config.minimum_geometry_cohort, count >= config.minimum_geometry_cohort)
        add(f"geometry_{boundary}_retention", count, required_retention, count >= required_retention)
    global_keys = [
        name for name in requirements
        if not name.startswith("interaction_") and not name.startswith("geometry_")
    ]
    status = "SAMPLE_ADEQUATE" if all(requirements[name]["passed"] for name in global_keys) else "SAMPLE_INADEQUATE"
    return {"status": status, "requirements": requirements}


def component_disposition(
    *,
    integrity_passed: bool,
    adequacy_passed: bool,
    structural_passed: bool,
    primary_result: Mapping[str, object],
    non_redundant_passed: bool,
    conditional_passed: bool,
    geometry_passed: bool,
    yearly: Mapping[str, Mapping[str, object]],
) -> str:
    if not integrity_passed:
        disposition = "REPRODUCIBILITY_DEFECT"
    elif not adequacy_passed or not structural_passed:
        disposition = "INSUFFICIENT_EVIDENCE"
    elif non_redundant_passed:
        disposition = "NON_REDUNDANT_COMPONENT_CANDIDATE"
    elif conditional_passed:
        disposition = "CONDITIONAL_CANDIDATE"
    elif geometry_passed:
        disposition = "GEOMETRY_CANDIDATE"
    else:
        upper = primary_result.get("ci_upper")
        nonpositive_years = sum(
            values.get("mean") is not None and float(values["mean"]) <= 0 for values in yearly.values()
        )
        disposition = (
            "REJECT_COMPONENT"
            if upper is not None and float(upper) <= 0 and nonpositive_years >= 3
            else "STRUCTURALLY_VALID_EMPIRICALLY_WEAK"
        )
    if disposition not in COMPONENT_DISPOSITIONS:
        raise AssertionError("D006 disposition escaped the frozen registry")
    return disposition


__all__ = [
    "benjamini_hochberg",
    "component_disposition",
    "mean_test",
    "paired_test",
    "robust_summaries",
    "sample_adequacy",
    "temporal_stability",
    "trading_date_bootstrap",
]
