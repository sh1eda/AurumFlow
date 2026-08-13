from __future__ import annotations

from hashlib import sha256

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from research.d007_methodology_clarification import (
    GEOMETRY_HYPOTHESES,
    INTERACTION_HYPOTHESES,
)
from research.d007_ote_historical_contract.statistics import (
    BOOTSTRAP_RESAMPLES,
    FAMILY_HYPOTHESES,
    benjamini_hochberg,
    bootstrap_seed,
    date_cluster_bootstrap,
    direction_stability,
    exact_mcnemar,
    mean_test,
    paired_student_t,
    positive_effect_passes,
    robust_summaries,
    temporal_stability,
    zero_margin_noninferiority_guard,
)


def test_robust_summaries_match_known_linear_quantiles_and_filter_nonfinite() -> None:
    result = robust_summaries([1.0, 2.0, 3.0, 4.0, np.nan, np.inf, None])
    assert result == {
        "n": 4,
        "median": 2.5,
        "q25": 1.75,
        "q75": 3.25,
        "trimmed_mean_1pct": 2.5,
        "absolute_1pct_removed_mean": 2.0,
    }
    assert robust_summaries([None, np.nan, np.inf])["n"] == 0


def test_paired_student_t_matches_known_result_and_reports_nonfinite_rows() -> None:
    pairs = pd.DataFrame({"ote": [4.0, 6.0, 7.0, np.nan, np.inf], "control": [1.0, 2.0, 2.0, 1.0, 1.0]})
    result = paired_student_t(pairs, treatment="ote", control="control")
    differences = np.array([3.0, 4.0, 5.0])
    expected = stats.ttest_1samp(differences, 0.0)
    assert result["status"] == "EVALUATED"
    assert result["n"] == 3
    assert result["excluded_n"] == 2
    assert result["first_failure_reason"] == "missing_treatment"
    assert result["mean"] == pytest.approx(4.0)
    assert result["std"] == pytest.approx(1.0)
    assert result["t_statistic"] == pytest.approx(expected.statistic)
    assert result["p_value"] == pytest.approx(expected.pvalue)


def test_paired_student_t_fails_closed_for_too_small_and_zero_variance_cells() -> None:
    singleton = paired_student_t(pd.DataFrame({"a": [2.0], "b": [1.0]}), treatment="a", control="b")
    assert singleton["status"] == "NOT_EVALUATED"
    assert singleton["mean"] == 1.0
    assert singleton["p_value"] is None

    constant = paired_student_t(pd.DataFrame({"a": [2.0, 2.0], "b": [1.0, 1.0]}), treatment="a", control="b")
    assert constant["status"] == "NOT_EVALUATED_ZERO_VARIANCE"
    assert constant["std"] == 0.0
    assert constant["t_statistic"] is None
    assert constant["ci_lower"] is None
    assert constant["p_value"] is None
    assert mean_test([1.0, 2.0, np.nan])["first_failure_reason"] == "missing_value"


def test_exact_mcnemar_uses_scipy_probability_ordering_and_zero_discordance() -> None:
    treatment = [1, 1, 1, 0, 0, 1]
    control = [0, 0, 1, 1, 0, 1]
    result = exact_mcnemar(treatment, control)
    assert result["treatment_only"] == 2
    assert result["control_only"] == 1
    assert result["risk_difference"] == pytest.approx(1 / 6)
    assert result["p_value"] == pytest.approx(stats.binomtest(2, 3, p=0.5, alternative="two-sided").pvalue)

    tied = exact_mcnemar([1, 0, 1], [1, 0, 1])
    assert tied["status"] == "EVALUATED"
    assert tied["discordant"] == 0
    assert tied["risk_difference"] == 0.0
    assert tied["p_value"] == 1.0


def test_exact_mcnemar_retains_only_valid_binary_pairs() -> None:
    result = exact_mcnemar([1, None, 2, np.inf], [0, 0, 0, 0])
    assert result["n"] == 1
    assert result["excluded_n"] == 3
    assert result["first_failure_reason"] == "missing_treatment"
    assert result["p_value"] == 1.0
    with pytest.raises(ValueError, match="same length"):
        exact_mcnemar([1], [1, 0])


def test_date_cluster_bootstrap_is_exactly_seeded_and_deterministic() -> None:
    pairs = pd.DataFrame(
        {
            "difference": [1.0, 3.0, 10.0, np.nan],
            "named_date": ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-04"],
        }
    )
    first = date_cluster_bootstrap(pairs, difference_column="difference", date_column="named_date", family="geometry", hypothesis_id="geometry_time_to_touch")
    second = date_cluster_bootstrap(pairs, difference_column="difference", date_column="named_date", family="geometry", hypothesis_id="geometry_time_to_touch")
    expected_seed = int.from_bytes(sha256(b"7007|geometry|geometry_time_to_touch").digest()[:8], "big") % (2**32)
    assert bootstrap_seed("geometry", "geometry_time_to_touch") == expected_seed
    assert first == second
    assert first["seed"] == expected_seed
    assert first["resamples"] == BOOTSTRAP_RESAMPLES
    assert first["n"] == 3
    assert first["excluded_n"] == 1
    assert first["first_failure_reason"] == "missing_difference"

    groups = [np.array([1.0, 3.0]), np.array([10.0])]
    draws = np.random.Generator(np.random.PCG64(expected_seed)).integers(0, 2, size=(2000, 2), endpoint=False)
    estimates = np.array([np.concatenate([groups[index] for index in row]).mean() for row in draws])
    assert first["mean"] == pytest.approx(estimates.mean())
    assert first["ci_lower"] == pytest.approx(np.quantile(estimates, 0.025, method="linear"))
    assert first["ci_upper"] == pytest.approx(np.quantile(estimates, 0.975, method="linear"))


def test_bootstrap_is_not_evaluated_without_a_finite_dated_pair() -> None:
    result = date_cluster_bootstrap(
        pd.DataFrame({"difference": [np.nan], "date": [None]}),
        difference_column="difference",
        date_column="date",
        family="geometry",
        hypothesis_id="geometry_touch_incidence",
    )
    assert result["status"] == "NOT_EVALUATED"
    assert result["mean"] is None
    assert result["first_failure_reason"] == "missing_named_date"


def test_bh_uses_registered_full_sizes_with_ties_and_missing_cells() -> None:
    geometry = {
        "geometry_touch_incidence": {"p_value": 0.01},
        "geometry_time_to_touch": {"p_value": np.nan},
        "geometry_directional_movement": {"p_value": 0.01},
    }
    adjusted = benjamini_hochberg(geometry, family="geometry")
    # Ties are ordered by hypothesis ID and the denominator remains the full m=3.
    assert adjusted["geometry_directional_movement"]["q_value"] == pytest.approx(0.015)
    assert adjusted["geometry_touch_incidence"]["q_value"] == pytest.approx(0.015)
    assert adjusted["geometry_time_to_touch"]["q_value"] is None
    assert adjusted["geometry_time_to_touch"]["bh_reject"] is False

    interactions = {name: {"p_value": None} for name in INTERACTION_HYPOTHESES}
    interactions["aligned_d005_context"] = {"p_value": 0.05}
    assert benjamini_hochberg(interactions, family="interactions")["aligned_d005_context"]["q_value"] == pytest.approx(0.3)
    assert tuple(FAMILY_HYPOTHESES["geometry"]) == GEOMETRY_HYPOTHESES
    with pytest.raises(ValueError, match="registered"):
        benjamini_hochberg({"geometry_touch_incidence": {"p_value": 0.1}}, family="geometry")


def test_stability_and_frozen_decision_guards_are_fail_closed() -> None:
    years = {
        2022: {"n": 2, "mean": 1.0, "ci_upper": 2.0},
        2023: {"n": 2, "mean": 1.0, "ci_upper": 2.0},
        2024: {"n": 2, "mean": 1.0, "ci_upper": 2.0},
        2025: {"n": 2, "mean": -0.1, "ci_upper": 0.5},
    }
    assert temporal_stability(years)["passed"] is True
    assert temporal_stability({**years, 2025: {"n": 2, "mean": -0.1, "ci_upper": -0.01}})["passed"] is False
    assert temporal_stability({2022: years[2022]})["passed"] is False
    assert temporal_stability({year: {**row, "n": np.nan} for year, row in years.items()})["passed"] is False
    assert direction_stability({"bullish": {"n": 2, "mean": 1.0, "ci_upper": 2.0}, "bearish": {"n": 2, "mean": 1.0, "ci_upper": 2.0}})["passed"] is True
    assert direction_stability({"bullish": {"n": 2, "mean": 1.0, "ci_upper": 2.0}, "bearish": {"n": 1, "mean": 1.0, "ci_upper": 2.0}})["passed"] is False

    test = {"mean": 1.0, "ci_lower": 0.0}
    assert zero_margin_noninferiority_guard(test, 0.05)
    assert not zero_margin_noninferiority_guard({"mean": -1.0, "ci_lower": 0.0}, 0.05)
    assert not zero_margin_noninferiority_guard({"mean": 1.0, "ci_lower": np.nan}, 0.05)
    assert positive_effect_passes({"mean": 1.0, "ci_lower": 0.1}, {"ci_lower": 0.1}, 0.05)
    assert not positive_effect_passes({"mean": 1.0, "ci_lower": 0.0}, {"ci_lower": 0.1}, 0.05)
