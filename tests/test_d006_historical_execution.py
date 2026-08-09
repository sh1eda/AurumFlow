from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.d006_rejection_block_research.config import D006Config, SPEC_SHA256, config_fingerprint
from research.d006_rejection_block_research.outcomes import (
    calculate_path_outcomes,
    filter_non_rejection_candidates,
    match_controls,
)
from research.d006_rejection_block_research.pipeline import (
    HistoricalExecutionError,
    _primary_exclusion_counts,
    run_historical_execution,
)
from research.d006_rejection_block_research.reporting import publish_results, verify_results
from research.d006_rejection_block_research.schemas import (
    CONTROL_KEYS,
    DEFINITION_KEYS,
    DENOMINATOR_KEYS,
    EXCLUSION_KEYS,
    GEOMETRY_KEYS,
    INTERACTION_KEYS,
    SESSION_KEYS,
    YEAR_KEYS,
)
from research.d006_rejection_block_research.statistics import benjamini_hochberg, sample_adequacy


def _bars() -> pd.DataFrame:
    index = pd.date_range("2025-01-02T10:00:00Z", periods=50, freq="5min")
    return pd.DataFrame(
        {
            "open": range(100, 150),
            "high": [value + 1.0 for value in range(100, 150)],
            "low": [value - 1.0 for value in range(100, 150)],
            "close": [value + 0.5 for value in range(100, 150)],
            "available_at": index,
            "session": "ny_observation",
            "trading_date": "2025-01-02",
        }
    )


def test_path_outcome_uses_exact_touch_close_and_frozen_60_minute_endpoint() -> None:
    event = pd.DataFrame(
        [{"event_id": "rb", "event_at": pd.Timestamp("2025-01-02T10:00:00Z"), "direction": "bullish"}]
    )
    outcome = calculate_path_outcomes(
        event,
        _bars(),
        event_id_column="event_id",
        event_at_column="event_at",
    ).iloc[0]
    assert outcome["reference_price"] == 100.5
    assert outcome["endpoint_at"] == pd.Timestamp("2025-01-02T11:00:00Z")
    assert outcome["endpoint_price"] == 112.5
    assert outcome["direction_aligned_movement"] == 12.0
    assert bool(outcome["endpoint_complete"])


def test_feature_controls_apply_rb_exclusion_and_hash_matching_is_deterministic() -> None:
    bars = _bars()
    structures = pd.DataFrame(
        [{
            "causal_availability": pd.Timestamp("2025-01-02T10:20:00Z"),
            "terminal_timestamp": pd.Timestamp("2025-01-02T10:40:00Z"),
            "expiry_deadline": pd.Timestamp("2025-01-03T10:20:00Z"),
            "first_touch_timestamp": pd.Timestamp("2025-01-02T10:30:00Z"),
        }]
    )
    candidates = pd.DataFrame(
        [
            {"candidate_id": "forbidden", "event_at": pd.Timestamp("2025-01-02T10:25:00Z"), "direction": "bullish", "year": 2025, "session": "ny_observation", "trading_date": "2025-01-03", "volatility_bucket": "normal"},
            {"candidate_id": "eligible", "event_at": pd.Timestamp("2025-01-02T12:35:00Z"), "direction": "bullish", "year": 2025, "session": "ny_observation", "trading_date": "2025-01-03", "volatility_bucket": "normal"},
        ]
    )
    eligible = filter_non_rejection_candidates(candidates, bars, structures)
    assert list(eligible["candidate_id"]) == ["eligible"]
    treatment = pd.DataFrame(
        [{"event_id": "rb", "event_at": pd.Timestamp("2025-01-02T11:00:00Z"), "direction": "bullish", "year": 2025, "session": "ny_observation", "trading_date": "2025-01-02", "volatility_bucket": "normal"}]
    )
    first = match_controls(treatment, eligible, family="synthetic")
    second = match_controls(treatment, eligible, family="synthetic")
    pd.testing.assert_frame_equal(first, second)
    assert first.iloc[0]["control_id"] == "eligible"


def test_bh_rejects_registry_drift_even_when_no_hypothesis_is_evaluable() -> None:
    with pytest.raises(ValueError, match="exactly 6"):
        benjamini_hochberg({}, family="interactions")


def test_adequacy_keeps_detected_and_lifecycle_denominators_separate() -> None:
    detected = pd.DataFrame(
        [{"direction": "bullish"}, {"direction": "bearish"}]
    )
    eligible = pd.DataFrame(
        [{"direction": "bullish", "first_touch_timestamp": pd.NaT, "session": "asia"}]
    )
    pairs = pd.DataFrame(columns=("treatment_at", "direction"))
    result = sample_adequacy(
        detected,
        eligible,
        pairs,
        0,
        {},
        {},
    )
    assert result["requirements"]["baseline_detected"]["observed"] == 2
    assert result["requirements"]["lifecycle_eligible"]["observed"] == 1
    assert result["requirements"]["untouched"]["observed"] == 1


def test_primary_first_failure_counts_missing_controls_and_incomplete_paths() -> None:
    treatments = pd.DataFrame({"event_id": ["a", "b", "c", "d", "e"]})
    outcomes = pd.DataFrame(
        {"event_id": ["a", "b", "c", "d", "e"], "endpoint_complete": [True, True, True, True, False]}
    )
    matches = pd.DataFrame(
        {"treatment_id": ["a", "b", "c", "d", "e"], "matched": [True, True, True, False, True]}
    )
    pairs = pd.DataFrame({"treatment_id": ["a", "b"]})
    counts = _primary_exclusion_counts(treatments, outcomes, matches, pairs)
    assert counts["incomplete_endpoint"] == 2  # c's control path and e's treatment path
    assert counts["missing_control"] == 1  # d
    assert sum(counts.values()) == 3


def _zero_audit() -> dict[str, object]:
    return {
        "detected": 0, "duplicate_id_excluded": 0, "lifecycle_eligible": 0,
        "endpoint_eligible": 0, "endpoint_complete_count": 0, "touched": 0,
        "untouched": 0, "invalidated": 0, "mitigated": 0, "expired": 0,
        "active_censored": 0, "overlapping": 0, "nested": 0, "bullish": 0,
        "bearish": 0, "preavailability_count": 0, "endpoint_coverage_complete": True,
        "expected_primary_pairs": 0, "observed_primary_pairs": 0,
        "controls_expected": 0, "controls_observed": 0, "controls_matched": 0,
        "controls_unmatched": 0,
        "by_definition": {key: 0 for key in DEFINITION_KEYS},
        "by_year": {key: 0 for key in YEAR_KEYS},
        "by_session": {key: 0 for key in SESSION_KEYS},
        "by_direction": {"bullish": 0, "bearish": 0},
        "by_terminal_state": {key: 0 for key in ("MITIGATED", "INVALIDATED", "EXPIRED", "ACTIVE_CENSORED")},
        "exclusions_by_reason": {key: 0 for key in EXCLUSION_KEYS},
        "primary_exclusions_by_reason": {key: 0 for key in EXCLUSION_KEYS},
        "treatment_control_reconciliation": {key: {"candidate_count": 0, "matched_count": 0, "unmatched_count": 0, "endpoint_complete_pair_count": 0} for key in CONTROL_KEYS},
        "interactions": {key: {"candidate_count": 0, "eligible_count": 0, "endpoint_complete_count": 0, "matched_count": 0, "excluded_count": 0} for key in INTERACTION_KEYS},
        "geometry": {key: {"eligible_count": 0, "touched_count": 0, "endpoint_complete_count": 0} for key in GEOMETRY_KEYS},
        "denominator_definitions": {key: "frozen denominator" for key in DENOMINATOR_KEYS},
    }


def test_reporting_is_atomic_manifest_bound_and_refuses_overwrite(tmp_path: Path) -> None:
    empty_test = {"n": 0, "mean": None, "ci_lower": None, "ci_upper": None}
    result = {
        "spec_sha256": SPEC_SHA256,
        "config_fingerprint": config_fingerprint(),
        "integrity": {"status": "INTEGRITY_VERIFIED", "reproducibility_match": True, "selected_2026_rows": 0, "protected_inputs_preserved": True},
        "source_audit": {"selected_file_count": 0, "selected_row_count": 0},
        "aggregate_audit": _zero_audit(),
        "primary_structural_claim": {"status": "NOT_EVALUATED", "stable_ordered_bytes": True},
        "sample_adequacy": {"status": "SAMPLE_INADEQUATE", "requirements": {}},
        "primary_empirical_claim": {**empty_test, "status": "NOT_EVALUATED", "mode": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"},
        "controls": {key: empty_test for key in CONTROL_KEYS},
        "interactions": {key: {**empty_test, "classification": "confirmatory", "status": "NOT_EVALUATED"} for key in INTERACTION_KEYS},
        "redundancy": {}, "geometry": {key: {"eligible": 0, "touched": 0} for key in GEOMETRY_KEYS},
        "stability": {}, "statistical_validation": {"mode": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"},
        "component_disposition": "INSUFFICIENT_EVIDENCE",
        "recommendation": "Later preregistered component research only.",
        "run_manifest": {"version": "d006-v1"},
    }
    output = publish_results(tmp_path, result=result, tables={"empty.parquet": pd.DataFrame()})
    assert verify_results(output)["verified"] is True
    with pytest.raises(FileExistsError, match="overwrite"):
        publish_results(tmp_path, result=result, tables={"empty.parquet": pd.DataFrame()})


def test_historical_pipeline_requires_exact_authorization_before_any_read(tmp_path: Path) -> None:
    with pytest.raises(HistoricalExecutionError, match="authorization"):
        run_historical_execution(tmp_path, authorization="wrong", config=D006Config())
