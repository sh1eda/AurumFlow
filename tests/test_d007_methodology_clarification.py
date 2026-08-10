from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.d007_methodology_clarification import (
    ADDENDUM_PATH,
    ADDENDUM_SHA256,
    D006BlockEvidence,
    GEOMETRY_HYPOTHESES,
    HYPOTHESIS_SPECS,
    INTERACTION_HYPOTHESES,
    MatchedObservation,
    TimedEvidence,
    UPSTREAM_ARTIFACTS,
    ablation_status,
    endpoint_is_registered,
    endpoint_named_years,
    match_without_replacement,
    named_trading_date,
    redundancy_associated,
    select_d006_block,
    select_latest_unambiguous,
    structural_overlap_status,
    verify_upstream_identities,
)
from research.d007_ote_research.guardrails import ControlCandidate
from research.d007_ote_research.models import Direction


ROOT = Path(__file__).resolve().parents[1]


def _stamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2025-01-15 22:59:59+00:00", date(2025, 1, 15)),
        ("2025-01-15 23:00:00+00:00", date(2025, 1, 16)),
        ("2025-01-15 23:00:01+00:00", date(2025, 1, 16)),
        ("2025-07-15 21:59:59+00:00", date(2025, 7, 15)),
        ("2025-07-15 22:00:00+00:00", date(2025, 7, 16)),
        ("2025-12-31 23:30:00+00:00", date(2026, 1, 1)),
        ("2026-01-01 04:59:59+00:00", date(2026, 1, 1)),
        ("2024-03-11 01:00:00+00:00", date(2024, 3, 11)),
    ],
)
def test_named_date_uses_dst_safe_18_new_york_roll(stamp: str, expected: date) -> None:
    assert named_trading_date(stamp) == expected


def test_named_date_rejects_naive_and_control_guardrail_uses_roll() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        named_trading_date("2025-01-15 18:00:00")
    candidate = ControlCandidate(
        candidate_id="after-roll",
        event_at=_stamp("2025-01-15 23:00:00+00:00"),
        named_trading_date=date(2025, 1, 16),
        validation_year=2025,
        session="asia",
        direction=Direction.BULLISH,
        causal_volatility_bucket="normal",
        upstream_mapping="1h_5m",
        elapsed_to_event_bucket="0_to_30",
        endpoint_complete=True,
        ote_touched_at_event=False,
        nearest_unrelated_ote_touch_minutes=120,
    )
    assert candidate.named_trading_date == date(2025, 1, 16)
    with pytest.raises(ValueError, match="18:00"):
        replace(candidate, named_trading_date=date(2025, 1, 15))


def test_endpoint_named_year_and_source_terminal_are_separate_fail_closed_gates() -> None:
    assert set(endpoint_named_years("2025-12-31 21:30:00+00:00")) == {2025}
    assert endpoint_is_registered("2025-12-31 21:30:00+00:00")
    assert endpoint_named_years("2025-12-31 22:30:00+00:00")[-1] == 2026
    assert not endpoint_is_registered("2025-12-31 22:30:00+00:00")
    assert set(endpoint_named_years("2025-12-31 23:30:00+00:00")) == {2026}
    assert not endpoint_is_registered("2025-12-31 23:30:00+00:00")
    with pytest.raises(ValueError, match="five-minute grid"):
        endpoint_is_registered("2025-01-15 10:02:00+00:00")


def _observation(
    observation_id: str,
    event_at: str,
    upstream: tuple[str, ...],
    **changes: object,
) -> MatchedObservation:
    values = {
        "observation_id": observation_id,
        "event_at": _stamp(event_at),
        "upstream_event_ids": upstream,
        "session": "premarket",
        "direction": 1,
        "volatility_bucket": "normal",
        "elapsed_bucket": "30_to_60",
    }
    values.update(changes)
    return MatchedObservation(**values)


def test_control_matching_covers_none_one_ties_association_and_replacement() -> None:
    first = _observation("t1", "2024-05-01 12:00+00:00", ("u1",))
    second = _observation("t2", "2024-05-02 12:00+00:00", ("u2",))
    candidate = _observation("c1", "2024-05-08 12:00+00:00", ("u3",))
    assert match_without_replacement([first], [], "matched_context_without_ote") == (("t1", None),)
    assert match_without_replacement([first], [candidate], "matched_context_without_ote") == (("t1", "c1"),)
    matched = match_without_replacement([second, first], [candidate], "matched_context_without_ote")
    assert matched == (("t1", "c1"), ("t2", None))

    equal_b = replace(candidate, observation_id="b")
    equal_a = replace(candidate, observation_id="a")
    assert match_without_replacement([first], [equal_b, equal_a], "matched_context_without_ote") == (("t1", "a"),)
    ambiguous = replace(candidate, observation_id="ambiguous", upstream_event_ids=("u3", "u4"))
    same_upstream = replace(candidate, observation_id="same", upstream_event_ids=("u1",))
    too_close = replace(candidate, observation_id="close", nearest_unrelated_ote_touch_minutes=119.999)
    assert match_without_replacement([first], [ambiguous, same_upstream, too_close], "matched_context_without_ote") == (("t1", None),)
    exact_boundary = replace(candidate, observation_id="boundary", nearest_unrelated_ote_touch_minutes=120.0)
    assert match_without_replacement([first], [exact_boundary], "matched_displacement_availability") == (("t1", "boundary"),)
    with pytest.raises(ValueError, match="unregistered"):
        match_without_replacement([first], [candidate], "interaction:not_registered")
    with pytest.raises(ValueError, match="duplicate"):
        match_without_replacement([first, replace(first)], [candidate], "matched_context_without_ote")
    with pytest.raises(ValueError, match="finite"):
        replace(candidate, nearest_unrelated_ote_touch_minutes=float("nan"))


def _block(block_id: str, available: str, **changes: object) -> D006BlockEvidence:
    available_at = _stamp(available)
    values = {
        "block_id": block_id,
        "definition_name": "single_wick_50_d3_v1",
        "direction": 1,
        "causal_availability": available_at,
        "range_size": 2.0,
        "lifecycle_state": "ACTIVE_TOUCHED",
        "first_touch_at": _stamp("2024-05-01 10:30+00:00"),
        "expiry_deadline": available_at + pd.Timedelta(hours=24),
    }
    values.update(changes)
    return D006BlockEvidence(**values)


def test_d006_selection_is_active_directional_and_deterministic() -> None:
    at = _stamp("2024-05-01 11:00+00:00")
    older = _block("older", "2024-05-01 09:00+00:00")
    latest_wide = _block("wide", "2024-05-01 10:00+00:00", range_size=3.0)
    latest_narrow_z = _block("z", "2024-05-01 10:00+00:00", range_size=1.0)
    latest_narrow_a = _block("a", "2024-05-01 10:00+00:00", range_size=1.0)
    assert select_d006_block([older, latest_wide, latest_narrow_z, latest_narrow_a], at, 1).block_id == "a"
    assert select_d006_block([replace(older, direction=-1)], at, 1) is None
    assert select_d006_block([replace(older, definition_name="cluster2_wick_50_d3_v1")], at, 1) is None
    assert select_d006_block([replace(older, preavailability_interaction=True)], at, 1) is None
    assert select_d006_block(
        [replace(older, lifecycle_state="INVALIDATED", invalidation_at=at)], at, 1
    ) is None
    assert select_d006_block(
        [replace(older, lifecycle_state="MITIGATED", mitigation_at=at)], at, 1
    ) is None
    expired = replace(
        older, lifecycle_state="EXPIRED", expiry_at=older.expiry_deadline
    )
    assert select_d006_block([expired], older.expiry_deadline, 1) is None
    exact_24h = _block(
        "boundary",
        "2024-04-30 11:00+00:00",
        first_touch_at=_stamp("2024-04-30 11:05+00:00"),
        expiry_deadline=at,
    )
    assert select_d006_block([exact_24h], at, 1) is None
    assert select_d006_block([exact_24h], at - pd.Timedelta(microseconds=1), 1) is not None
    assert select_d006_block(
        [replace(older, lifecycle_state="ACTIVE_UNTOUCHED", first_touch_at=None)], at, 1
    ) is None
    with pytest.raises(ValueError, match="block ID"):
        replace(older, block_id="")
    with pytest.raises(ValueError, match="24 hours"):
        replace(older, expiry_deadline=older.expiry_deadline + pd.Timedelta(hours=1))
    with pytest.raises(ValueError, match="state/timestamp"):
        replace(older, lifecycle_state="MITIGATED", mitigation_at=None)
    with pytest.raises(ValueError, match="cannot follow"):
        replace(
            older,
            lifecycle_state="MITIGATED",
            mitigation_at=older.first_touch_at - pd.Timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="cannot follow"):
        replace(
            older,
            lifecycle_state="INVALIDATED",
            invalidation_at=older.first_touch_at - pd.Timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="boolean"):
        replace(older, preavailability_interaction="false")


def test_interaction_conflict_and_redundancy_window_boundaries() -> None:
    at = _stamp("2024-05-01 10:00+00:00")
    conflict = (
        TimedEvidence("bull", at, 1),
        TimedEvidence("bear", at, -1),
    )
    assert select_latest_unambiguous(conflict, at) is None
    tied = (TimedEvidence("z", at, 1), TimedEvidence("a", at, 1))
    assert select_latest_unambiguous(tied, at).evidence_id == "a"
    assert select_latest_unambiguous(tied, at, strict=True) is None
    assert redundancy_associated(at - pd.Timedelta(minutes=60), at)
    assert redundancy_associated(at + pd.Timedelta(minutes=60), at)
    assert not redundancy_associated(at - pd.Timedelta(minutes=60, seconds=1), at)
    assert not redundancy_associated(at + pd.Timedelta(minutes=60, seconds=1), at)


def test_redundancy_decision_threshold_boundaries_are_exact() -> None:
    assert structural_overlap_status(200, 200) == "FULL_STRUCTURAL_OVERLAP"
    assert structural_overlap_status(199, 200) == "NOT_FULL_STRUCTURAL_OVERLAP"
    passing = dict(
        n=200,
        mean_difference=1.0,
        t_interval_lower=0.1,
        t_interval_upper=1.9,
        bootstrap_lower=0.05,
        q_value=0.05,
        stable=True,
    )
    assert ablation_status(**passing) == "NON_REDUNDANT"
    assert ablation_status(**{**passing, "q_value": 0.0500001}) == "INCONCLUSIVE"
    assert ablation_status(**{**passing, "t_interval_lower": 0.0}) == "INCONCLUSIVE"
    assert ablation_status(**{**passing, "n": 199}) == "INCONCLUSIVE"
    accounted = {
        **passing,
        "mean_difference": -1.0,
        "t_interval_lower": -2.0,
        "t_interval_upper": 0.0,
    }
    assert ablation_status(**accounted) == "FULLY_ACCOUNTED"


def test_registries_are_closed_and_provenance_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert {item.hypothesis_id for item in HYPOTHESIS_SPECS} == set(GEOMETRY_HYPOTHESES) | set(INTERACTION_HYPOTHESES)
    assert len(INTERACTION_HYPOTHESES) == 6
    assert len(GEOMETRY_HYPOTHESES) == 3
    assert len({item.path for item in UPSTREAM_ARTIFACTS}) == len(UPSTREAM_ARTIFACTS)
    assert all(item.required_columns and len(item.sha256) == 64 for item in UPSTREAM_ARTIFACTS)
    assert all(len(item.version_authority_sha256) == 64 for item in UPSTREAM_ARTIFACTS)
    assert all("outcome" not in item.required_columns for item in UPSTREAM_ARTIFACTS)
    with pytest.raises(ValueError, match="missing or unsafe"):
        verify_upstream_identities(tmp_path)
    import research.d007_methodology_clarification as clarification

    monkeypatch.setattr(clarification, "UPSTREAM_ARTIFACTS", (UPSTREAM_ARTIFACTS[0],) * 2)
    with pytest.raises(ValueError, match="duplicate upstream artifact identity"):
        verify_upstream_identities(tmp_path)


def test_addendum_identity_is_frozen() -> None:
    assert ADDENDUM_SHA256 != "ADDENDUM_SHA256_PLACEHOLDER"
    assert (ROOT / ADDENDUM_PATH).is_file()
    from research.d007_methodology_clarification import file_sha256

    assert file_sha256(ROOT / ADDENDUM_PATH) == ADDENDUM_SHA256
