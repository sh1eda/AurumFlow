"""Frozen, outcome-blind statistical primitives for later D007 execution.

This module intentionally accepts only caller-provided, already constructed
values.  It neither reads market data nor constructs D007 outcomes.  The
functions are reusable with synthetic inputs for structural preflight tests.
"""

from __future__ import annotations

from hashlib import sha256
from math import sqrt
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from research.d007_methodology_clarification import (
    CONTROL_FAMILIES,
    GEOMETRY_HYPOTHESES,
    INTERACTION_HYPOTHESES,
)


CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 7007
BH_ALPHA = 0.05
INCREMENTAL_CONTROL_HYPOTHESES = tuple(CONTROL_FAMILIES[1:])
FAMILY_HYPOTHESES = {
    "geometry": tuple(GEOMETRY_HYPOTHESES),
    "interactions": tuple(INTERACTION_HYPOTHESES),
    "incremental_controls": INCREMENTAL_CONTROL_HYPOTHESES,
}


def _as_float(value: object) -> float | None:
    """Return a finite float, or ``None`` for missing/non-finite input."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _has_minimum_n(row: Mapping[str, object], minimum: int = 2) -> bool:
    value = _as_float(row.get("n"))
    return bool(value is not None and value.is_integer() and value >= minimum)


def robust_summaries(values: Iterable[object]) -> dict[str, float | int | None]:
    """Return preregistered descriptive sensitivities after finite filtering."""

    data = np.asarray(
        [number for value in values if (number := _as_float(value)) is not None],
        dtype=float,
    )
    if not len(data):
        return {
            "n": 0,
            "median": None,
            "q25": None,
            "q75": None,
            "trimmed_mean_1pct": None,
            "absolute_1pct_removed_mean": None,
        }
    ordered = np.sort(data)
    trim = int(np.floor(len(ordered) * 0.01))
    trimmed = ordered[trim : len(ordered) - trim] if trim else ordered
    keep = max(1, int(np.floor(len(data) * 0.99)))
    smallest_absolute = data[np.argsort(np.abs(data), kind="stable")[:keep]]
    return {
        "n": int(len(data)),
        "median": float(np.median(data)),
        "q25": float(np.quantile(data, 0.25, method="linear")),
        "q75": float(np.quantile(data, 0.75, method="linear")),
        "trimmed_mean_1pct": float(np.mean(trimmed)),
        "absolute_1pct_removed_mean": float(np.mean(smallest_absolute)),
    }


def mean_test(values: Iterable[object], confidence: float = CONFIDENCE_LEVEL) -> dict[str, object]:
    """Compute the frozen one-sample Student-t convention for differences."""

    if not 0 < confidence < 1:
        raise ValueError("confidence must be inside (0, 1)")
    supplied = list(values)
    data = np.asarray(
        [number for value in supplied if (number := _as_float(value)) is not None], dtype=float
    )
    first_failure = next(
        (
            "missing_value" if pd.isna(value) else "nonfinite_value"
            for value in supplied
            if _as_float(value) is None
        ),
        None,
    )
    result: dict[str, object] = {
        "input_n": len(supplied),
        "n": len(data),
        "excluded_n": len(supplied) - len(data),
        "first_failure_reason": first_failure,
        "status": "NOT_EVALUATED",
        "mean": float(np.mean(data)) if len(data) else None,
        "std": None,
        "standardized_mean": None,
        "t_statistic": None,
        "ci_lower": None,
        "ci_upper": None,
        "p_value": None,
        "robust": robust_summaries(data),
    }
    if len(data) < 2:
        return result
    std = float(np.std(data, ddof=1))
    result["std"] = std
    if std == 0.0:
        result["status"] = "NOT_EVALUATED_ZERO_VARIANCE"
        return result
    standard_error = std / sqrt(len(data))
    degrees_of_freedom = len(data) - 1
    t_statistic = float(result["mean"]) / standard_error
    critical = float(stats.t.ppf((1 + confidence) / 2, degrees_of_freedom))
    result.update(
        {
            "status": "EVALUATED",
            "standardized_mean": float(result["mean"]) / std,
            "t_statistic": t_statistic,
            "ci_lower": float(result["mean"]) - critical * standard_error,
            "ci_upper": float(result["mean"]) + critical * standard_error,
            "p_value": float(2 * stats.t.sf(abs(t_statistic), degrees_of_freedom)),
        }
    )
    return result


def _paired_differences(
    pairs: pd.DataFrame, treatment: str, control: str
) -> tuple[np.ndarray, dict[str, int | str | None]]:
    if treatment not in pairs or control not in pairs:
        raise KeyError("paired columns must both be present")
    first_failure: str | None = None
    differences: list[float] = []
    excluded = 0
    for treatment_value, control_value in pairs[[treatment, control]].itertuples(index=False, name=None):
        if pd.isna(treatment_value):
            reason = "missing_treatment"
        elif pd.isna(control_value):
            reason = "missing_control"
        elif _as_float(treatment_value) is None:
            reason = "nonfinite_treatment"
        elif _as_float(control_value) is None:
            reason = "nonfinite_control"
        else:
            differences.append(float(treatment_value) - float(control_value))
            continue
        excluded += 1
        if first_failure is None:
            first_failure = reason
    return np.asarray(differences, dtype=float), {
        "input_n": int(len(pairs)),
        "excluded_n": excluded,
        "first_failure_reason": first_failure,
    }


def paired_student_t(
    pairs: pd.DataFrame,
    *,
    treatment: str,
    control: str,
    confidence: float = CONFIDENCE_LEVEL,
) -> dict[str, object]:
    """Compute a two-sided paired Student-t result without trimming effects.

    Rows with a missing or non-finite endpoint are excluded and reported.  A
    cell with fewer than two finite pairs, or zero sample variance, is
    deliberately not inferentially evaluated.
    """

    if not 0 < confidence < 1:
        raise ValueError("confidence must be inside (0, 1)")
    differences, audit = _paired_differences(pairs, treatment, control)
    valid = pairs.loc[
        [
            _as_float(left) is not None and _as_float(right) is not None
            for left, right in pairs[[treatment, control]].itertuples(index=False, name=None)
        ]
    ]
    result: dict[str, object] = {
        **audit,
        "n": int(len(differences)),
        "status": "NOT_EVALUATED",
        "treatment_mean": float(valid[treatment].astype(float).mean()) if len(valid) else None,
        "control_mean": float(valid[control].astype(float).mean()) if len(valid) else None,
        "mean": float(np.mean(differences)) if len(differences) else None,
        "mean_paired_difference": float(np.mean(differences)) if len(differences) else None,
        "median_paired_difference": float(np.median(differences)) if len(differences) else None,
        "std": None,
        "standardized_mean": None,
        "t_statistic": None,
        "ci_lower": None,
        "ci_upper": None,
        "p_value": None,
        "robust": robust_summaries(differences),
    }
    if len(differences) < 2:
        return result
    std = float(np.std(differences, ddof=1))
    result["std"] = std
    if std == 0.0:
        result["status"] = "NOT_EVALUATED_ZERO_VARIANCE"
        return result
    standard_error = std / sqrt(len(differences))
    t_statistic = float(result["mean"]) / standard_error
    degrees_of_freedom = len(differences) - 1
    critical = float(stats.t.ppf((1 + confidence) / 2, degrees_of_freedom))
    result.update(
        {
            "status": "EVALUATED",
            "standardized_mean": float(result["mean"]) / std,
            "t_statistic": t_statistic,
            "ci_lower": float(result["mean"]) - critical * standard_error,
            "ci_upper": float(result["mean"]) + critical * standard_error,
            "p_value": float(2 * stats.t.sf(abs(t_statistic), degrees_of_freedom)),
        }
    )
    return result


def paired_test(
    pairs: pd.DataFrame, *, treatment: str, control: str, confidence: float = CONFIDENCE_LEVEL
) -> dict[str, object]:
    """Compatibility name for the frozen paired Student-t convention."""

    return paired_student_t(pairs, treatment=treatment, control=control, confidence=confidence)


def _binary_pairs(
    treatment: Sequence[object], control: Sequence[object]
) -> tuple[list[tuple[int, int]], int, str | None]:
    if len(treatment) != len(control):
        raise ValueError("paired binary inputs must have the same length")
    valid: list[tuple[int, int]] = []
    first_failure: str | None = None
    excluded = 0
    for left, right in zip(treatment, control, strict=True):
        if pd.isna(left):
            reason = "missing_treatment"
        elif pd.isna(right):
            reason = "missing_control"
        elif left not in (0, 1, False, True):
            reason = "invalid_treatment_binary"
        elif right not in (0, 1, False, True):
            reason = "invalid_control_binary"
        else:
            valid.append((int(left), int(right)))
            continue
        excluded += 1
        if first_failure is None:
            first_failure = reason
    return valid, excluded, first_failure


def exact_mcnemar(
    treatment: Sequence[object], control: Sequence[object]
) -> dict[str, object]:
    """Return the exact two-sided McNemar/binomial result for paired binaries."""

    valid, excluded, first_failure = _binary_pairs(treatment, control)
    band_only = sum(left == 1 and right == 0 for left, right in valid)
    reference_only = sum(left == 0 and right == 1 for left, right in valid)
    discordant = band_only + reference_only
    result: dict[str, object] = {
        "input_n": len(treatment),
        "n": len(valid),
        "excluded_n": excluded,
        "first_failure_reason": first_failure,
        "status": "NOT_EVALUATED" if not valid else "EVALUATED",
        "treatment_only": band_only,
        "control_only": reference_only,
        "discordant": discordant,
        "risk_difference": (float(np.mean([left - right for left, right in valid])) if valid else None),
        "p_value": None,
    }
    if not valid:
        return result
    result["p_value"] = (
        1.0
        if discordant == 0
        else float(stats.binomtest(band_only, discordant, p=0.5, alternative="two-sided").pvalue)
    )
    return result


def mcnemar_test(treatment: Sequence[object], control: Sequence[object]) -> dict[str, object]:
    """Compatibility name for the frozen exact McNemar test."""

    return exact_mcnemar(treatment, control)


def bootstrap_seed(family: str, hypothesis_id: str) -> int:
    """Return the frozen unsigned 32-bit cell seed."""

    if not family or not hypothesis_id:
        raise ValueError("family and hypothesis_id are required")
    digest = sha256(f"{BOOTSTRAP_SEED}|{family}|{hypothesis_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def date_cluster_bootstrap(
    pairs: pd.DataFrame,
    *,
    difference_column: str,
    date_column: str,
    family: str,
    hypothesis_id: str,
) -> dict[str, object]:
    """Perform the frozen 2,000-resample named-date cluster bootstrap."""

    if difference_column not in pairs or date_column not in pairs:
        raise KeyError("difference and date columns must both be present")
    groups: dict[object, list[float]] = {}
    excluded = 0
    first_failure: str | None = None
    for difference, named_date in pairs[[difference_column, date_column]].itertuples(index=False, name=None):
        if pd.isna(named_date):
            reason = "missing_named_date"
        elif _as_float(difference) is None:
            reason = "missing_difference" if pd.isna(difference) else "nonfinite_difference"
        else:
            groups.setdefault(named_date, []).append(float(difference))
            continue
        excluded += 1
        if first_failure is None:
            first_failure = reason
    seed = bootstrap_seed(family, hypothesis_id)
    result: dict[str, object] = {
        "input_n": len(pairs),
        "n": sum(len(values) for values in groups.values()),
        "excluded_n": excluded,
        "first_failure_reason": first_failure,
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": seed,
        "status": "NOT_EVALUATED" if not groups else "EVALUATED",
        "mean": None,
        "ci_lower": None,
        "ci_upper": None,
    }
    if not groups:
        return result
    ordered_dates = sorted(groups, key=lambda item: str(item))
    date_groups = [np.asarray(groups[item], dtype=float) for item in ordered_dates]
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = rng.integers(0, len(date_groups), size=(BOOTSTRAP_RESAMPLES, len(date_groups)), endpoint=False)
    estimates = np.empty(BOOTSTRAP_RESAMPLES, dtype=float)
    for position, selected in enumerate(draws):
        estimates[position] = float(np.mean(np.concatenate([date_groups[index] for index in selected])))
    return {
        **result,
        "mean": float(np.mean(estimates)),
        "ci_lower": float(np.quantile(estimates, 0.025, method="linear")),
        "ci_upper": float(np.quantile(estimates, 0.975, method="linear")),
    }


def trading_date_bootstrap(
    pairs: pd.DataFrame,
    *,
    difference_column: str,
    date_column: str,
    family: str,
    hypothesis_id: str,
) -> dict[str, object]:
    """Compatibility name for :func:`date_cluster_bootstrap`."""

    return date_cluster_bootstrap(
        pairs,
        difference_column=difference_column,
        date_column=date_column,
        family=family,
        hypothesis_id=hypothesis_id,
    )


def benjamini_hochberg(
    results: Mapping[str, Mapping[str, object]], *, family: str
) -> dict[str, dict[str, object]]:
    """Adjust a complete registered family, retaining missing cells in-place."""

    try:
        registered = FAMILY_HYPOTHESES[family]
    except KeyError as error:
        raise ValueError(f"unknown D007 BH family: {family}") from error
    if set(results) != set(registered):
        raise ValueError(f"{family} must retain exactly its registered hypotheses")
    evaluated: list[tuple[str, float]] = []
    for hypothesis_id, row in results.items():
        value = row.get("p_value")
        if value is None or _as_float(value) is None:
            continue
        p_value = float(value)
        if not 0 <= p_value <= 1:
            raise ValueError("p_value must be inside [0, 1]")
        evaluated.append((hypothesis_id, p_value))
    ranked = sorted(evaluated, key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 1.0
    family_size = len(registered)
    for rank, (hypothesis_id, p_value) in reversed(list(enumerate(ranked, start=1))):
        running = min(running, min(1.0, p_value * family_size / rank))
        adjusted[hypothesis_id] = running
    output: dict[str, dict[str, object]] = {}
    for hypothesis_id in registered:
        row = dict(results[hypothesis_id])
        q_value = adjusted.get(hypothesis_id)
        row["q_value"] = q_value
        row["bh_reject"] = bool(q_value is not None and q_value <= BH_ALPHA)
        output[hypothesis_id] = row
    return output


def temporal_stability(
    yearly: Mapping[int, Mapping[str, object]], *, positive: bool = True
) -> dict[str, object]:
    """Apply the frozen four-year sign and opposite-interval summary."""

    required_years = (2022, 2023, 2024, 2025)
    adequate: dict[int, Mapping[str, object]] = {}
    for year in required_years:
        row = yearly.get(year)
        if row is None or not _has_minimum_n(row):
            continue
        mean = _as_float(row.get("mean"))
        if mean is not None:
            adequate[year] = row
    sign_count = sum(
        (_as_float(row.get("mean")) > 0 if positive else _as_float(row.get("mean")) < 0)
        for row in adequate.values()
    )
    opposite = any(
        (_as_float(row.get("ci_upper")) is not None and _as_float(row.get("ci_upper")) < 0)
        if positive
        else (_as_float(row.get("ci_lower")) is not None and _as_float(row.get("ci_lower")) > 0)
        for row in adequate.values()
    )
    return {
        "required_years": required_years,
        "adequate_years": tuple(sorted(adequate)),
        "adequate_year_count": len(adequate),
        "required_sign_years": sign_count,
        "significant_opposite_year": opposite,
        "passed": bool(len(adequate) == 4 and sign_count >= 3 and not opposite),
    }


def direction_stability(
    directions: Mapping[str, Mapping[str, object]], *, positive: bool = True
) -> dict[str, object]:
    """Summarize the required bullish/bearish sign and interval checks."""

    cohorts: dict[str, bool] = {}
    for direction in ("bullish", "bearish"):
        row = directions.get(direction, {})
        mean = _as_float(row.get("mean"))
        lower = _as_float(row.get("ci_lower"))
        upper = _as_float(row.get("ci_upper"))
        computable = _has_minimum_n(row) and mean is not None
        opposite = (upper is not None and upper < 0) if positive else (lower is not None and lower > 0)
        sign = mean > 0 if positive and mean is not None else mean < 0 if mean is not None else False
        cohorts[direction] = bool(computable and sign and not opposite)
    return {"cohorts": cohorts, "passed": all(cohorts.values())}


def noninferiority_stability(
    yearly: Mapping[int, Mapping[str, object]],
    directions: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Require every frozen movement split to be computable and not wholly negative."""

    year_pass = {
        year: bool(
            _has_minimum_n(yearly.get(year, {}))
            and _as_float(yearly.get(year, {}).get("ci_upper")) is not None
            and _as_float(yearly[year].get("ci_upper")) >= 0
        )
        for year in (2022, 2023, 2024, 2025)
    }
    direction_pass = {
        direction: bool(
            _has_minimum_n(directions.get(direction, {}))
            and _as_float(directions.get(direction, {}).get("ci_upper")) is not None
            and _as_float(directions[direction].get("ci_upper")) >= 0
        )
        for direction in ("bullish", "bearish")
    }
    return {
        "years": year_pass,
        "directions": direction_pass,
        "passed": all(year_pass.values()) and all(direction_pass.values()),
    }


def positive_effect_passes(
    test: Mapping[str, object], bootstrap: Mapping[str, object], q_value: object
) -> bool:
    """Return the frozen positive-effect decision predicate."""

    mean = _as_float(test.get("mean"))
    lower = _as_float(test.get("ci_lower"))
    bootstrap_lower = _as_float(bootstrap.get("ci_lower"))
    q = _as_float(q_value)
    return bool(mean is not None and lower is not None and bootstrap_lower is not None and q is not None and mean > 0 and lower > 0 and bootstrap_lower > 0 and q <= BH_ALPHA)


def zero_margin_noninferiority_guard(test: Mapping[str, object], q_value: object) -> bool:
    """Apply the registered geometry movement zero-margin guard."""

    lower = _as_float(test.get("ci_lower"))
    mean = _as_float(test.get("mean"))
    q = _as_float(q_value)
    if lower is None or mean is None or q is None:
        return False
    return bool(lower >= 0 and not (mean < 0 and q <= BH_ALPHA))


def zero_margin_guard(test: Mapping[str, object], q_value: object) -> bool:
    """Compatibility name for the registered non-inferiority guard."""

    return zero_margin_noninferiority_guard(test, q_value)


__all__ = [
    "BH_ALPHA",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CONFIDENCE_LEVEL",
    "FAMILY_HYPOTHESES",
    "INCREMENTAL_CONTROL_HYPOTHESES",
    "benjamini_hochberg",
    "bootstrap_seed",
    "date_cluster_bootstrap",
    "direction_stability",
    "exact_mcnemar",
    "mcnemar_test",
    "mean_test",
    "noninferiority_stability",
    "paired_student_t",
    "paired_test",
    "positive_effect_passes",
    "robust_summaries",
    "temporal_stability",
    "trading_date_bootstrap",
    "zero_margin_noninferiority_guard",
    "zero_margin_guard",
]
