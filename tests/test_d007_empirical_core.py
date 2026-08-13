from __future__ import annotations

from dataclasses import replace

import pandas as pd

from research.d007_methodology_clarification import D006BlockEvidence, named_trading_date
from research.d007_ote_historical_contract.empirical import (
    adequacy_requirements,
    associate_upstream_ids,
    build_5m_bars,
    elapsed_displacement_bucket,
    exact_60m_outcome,
    final_disposition,
    make_candidate,
    match_family,
    reconstruct_frozen_anchor,
    reconstruct_ote_ranges,
    select_d004_reentry,
    select_d006_membership,
    select_e1_context,
    select_e3_liquidity_sweep,
    select_e3_refinement,
    select_redundancy_evidence,
)
from research.d007_ote_research.models import ClosedBar, Direction


def stamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


def bar(at: str, low: float, high: float, close: float | None = None) -> ClosedBar:
    opened = stamp(at)
    return ClosedBar(f"b:{at}", opened, opened + pd.Timedelta(minutes=5), (low + high) / 2, high, low, close if close is not None else (low + high) / 2)


def sequence(identifier: str = "s1", direction: int = 1) -> dict[str, object]:
    return {
        "sequence_id": identifier, "mapping_variant": "1h_5m", "direction": direction,
        "candidate_id": f"c-{identifier}", "mss_id": f"m-{identifier}", "displacement_id": f"d-{identifier}",
        "displacement_confirmation_event_id": f"dc-{identifier}", "anchor_event_id": f"a-{identifier}",
        "candidate_direction": direction, "mss_direction": direction, "displacement_direction": direction,
        "confirmation_event_direction": direction, "main_candidate_eligible": True,
        "displacement_created_at": stamp("2024-05-01 10:00+00:00"),
        "confirmation_event_available_at": stamp("2024-05-01 10:15+00:00"),
        "anchor_at": stamp("2024-05-01 10:00+00:00"),
        "anchor_session": "premarket", "anchor_year": 2024,
    }


def source(direction: int = 1) -> tuple[ClosedBar, ...]:
    if direction == 1:
        return (
            bar("2024-05-01 09:30+00:00", 94, 97), bar("2024-05-01 09:35+00:00", 93, 98),
            bar("2024-05-01 09:40+00:00", 91, 99), bar("2024-05-01 09:45+00:00", 90, 98),
            bar("2024-05-01 09:50+00:00", 92, 100), bar("2024-05-01 09:55+00:00", 94, 102),
            bar("2024-05-01 10:00+00:00", 105, 110), bar("2024-05-01 10:05+00:00", 108, 115),
            bar("2024-05-01 10:10+00:00", 112, 120), bar("2024-05-01 10:15+00:00", 111, 118),
            # This must not be observed while reconstructing the range.
            bar("2024-05-01 10:20+00:00", 110, 999),
        )
    return (
        bar("2024-05-01 09:30+00:00", 103, 106), bar("2024-05-01 09:35+00:00", 102, 107),
        bar("2024-05-01 09:40+00:00", 101, 109), bar("2024-05-01 09:45+00:00", 102, 110),
        bar("2024-05-01 09:50+00:00", 100, 108), bar("2024-05-01 09:55+00:00", 98, 106),
        bar("2024-05-01 10:00+00:00", 90, 105), bar("2024-05-01 10:05+00:00", 85, 100),
        bar("2024-05-01 10:10+00:00", 80, 90), bar("2024-05-01 10:15+00:00", 82, 89),
        bar("2024-05-01 10:20+00:00", 1, 89),
    )


def test_projects_generic_minutes_and_reconstructs_bull_bear_without_future_mutation() -> None:
    minutes = []
    for minute in range(5):
        at = stamp("2024-05-01 09:30+00:00") + pd.Timedelta(minutes=minute)
        minutes.append({"timestamp_utc": at, "open": 100 + minute, "high": 101 + minute, "low": 99 + minute, "close": 100.5 + minute})
    aggregated = build_5m_bars(pd.DataFrame(minutes))
    assert len(aggregated) == 1 and aggregated[0].high == 105 and aggregated[0].available_at == stamp("2024-05-01 09:35+00:00")
    with pd.option_context("mode.chained_assignment", None):
        broken = pd.DataFrame(minutes).drop(index=2)
    try:
        build_5m_bars(broken)
    except ValueError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("partial 5m aggregation was accepted")

    bull = reconstruct_ote_ranges(sequence(), source())
    bear = reconstruct_ote_ranges(sequence("s2", -1), source(-1))
    assert bull[0].origin_price == 90 and bull[0].endpoint_price == 120
    assert bear[0].origin_price == 110 and bear[0].endpoint_price == 80
    assert bull[0].zone_low < bull[0].zone_high and bear[0].zone_low < bear[0].zone_high
    assert reconstruct_ote_ranges(sequence(), source())[0].endpoint_price != 999
    changed = list(source()); changed[-1] = bar("2024-05-01 10:20+00:00", 110, 5000)
    assert reconstruct_ote_ranges(sequence(), changed)[0].endpoint_price == 120
    late_pivot = list(source()); late_pivot[-1] = bar("2024-05-01 10:20+00:00", 1, 999)
    assert reconstruct_frozen_anchor(sequence(), late_pivot).origin_price == 90


def endpoint_bars(event: str, direction: int = 1) -> tuple[ClosedBar, ...]:
    start = stamp(event)
    return tuple(bar((start + pd.Timedelta(minutes=5 * index - 5)).isoformat(), 90, 120, 100 + direction * index) for index in range(13))


def test_exact_endpoint_has_13_closed_bars_and_terminal_2026_gate() -> None:
    event = stamp("2024-05-01 10:00+00:00")
    outcome = exact_60m_outcome(event, 1, endpoint_bars(str(event)))
    assert outcome.endpoint_complete and outcome.direction_aligned_movement == 12
    missing = exact_60m_outcome(event, 1, endpoint_bars(str(event))[:-1])
    assert missing.first_failure == "missing_exact_60m_bar"
    assert exact_60m_outcome(stamp("2025-12-31 22:00+00:00"), 1, ()).first_failure == "endpoint_outside_registered_validation_interval"
    assert elapsed_displacement_bucket(event, event) == "0_to_30"
    assert elapsed_displacement_bucket(event, event + pd.Timedelta(minutes=30)) == "30_to_60"
    assert elapsed_displacement_bucket(event, event + pd.Timedelta(minutes=60)) == "60_to_180"
    assert elapsed_displacement_bucket(event, event + pd.Timedelta(minutes=180)) == "180_to_1440"
    assert elapsed_displacement_bucket(event, event - pd.Timedelta(seconds=1)) is None
    assert elapsed_displacement_bucket(event, event + pd.Timedelta(minutes=1441)) is None


def test_exact_id_association_and_frozen_matching_no_replacement() -> None:
    s1, s2 = sequence("s1"), sequence("s2")
    s2["confirmation_event_available_at"] = stamp("2024-05-02 10:15+00:00")
    s2["anchor_at"] = stamp("2024-05-02 10:00+00:00")
    assert associate_upstream_ids(["m-s1"], [s1, s2]).sequence is s1
    assert associate_upstream_ids(["unrelated"], [s1]).first_failure == "ambiguous_upstream_association"
    assert associate_upstream_ids(["m-s1", "m-s2"], [s1, s2]).first_failure == "ambiguous_upstream_association"
    treatment = make_candidate(candidate_id="t", event_at="2024-05-01 10:30+00:00", evidence_ids=["s1"], sequences=[s1, s2], session="premarket", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=None)
    control = make_candidate(candidate_id="c", event_at="2024-05-02 10:30+00:00", evidence_ids=["s2"], sequences=[s1, s2], session="premarket", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=120)
    assert match_family([treatment], [control], "matched_context_without_ote") == (("t", "c"),)
    assert match_family([treatment, replace(treatment, observation=replace(treatment.observation, observation_id="t2"))], [control], "matched_context_without_ote") == (("t", "c"), ("t2", None))
    assert treatment.observation.session == "premarket"
    assert treatment.e4_anchor_year == 2024
    caller_mismatch = make_candidate(candidate_id="caller-mismatch", event_at="2024-05-01 10:30+00:00", evidence_ids=["s1"], sequences=[s1], session="ny_afternoon", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=None)
    assert caller_mismatch.observation.session == "premarket"
    ineligible = make_candidate(candidate_id="bad", event_at="2024-05-02 10:30+00:00", evidence_ids=["nope"], sequences=[s1], session="premarket", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=120)
    assert ineligible.first_failure == "ambiguous_upstream_association"
    mismatch = make_candidate(candidate_id="mismatch", event_at="2024-05-02 10:30+00:00", evidence_ids=["s2"], sequences=[s1, s2], session="premarket", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=120, evaluation_direction=-1)
    assert mismatch.first_failure == "association_provenance_mismatch"
    negative_sequence = sequence("negative", direction=-1)
    negative_sequence["confirmation_event_available_at"] = stamp("2024-05-02 10:15+00:00")
    negative_sequence["anchor_at"] = stamp("2024-05-02 10:00+00:00")
    negative = make_candidate(candidate_id="negative", event_at="2024-05-02 10:30+00:00", evidence_ids=["negative"], sequences=[negative_sequence], session="premarket", volatility_bucket="normal", endpoint_complete=True, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=120, evaluation_direction=-1)
    assert negative.observation.direction == -1


def test_membership_edges_conflicts_d004_and_d006_precedence() -> None:
    range_ = reconstruct_ote_ranges(sequence(), source())[0]
    at = range_.range_available_at
    e1 = {"snapshot_id": "a", "state": "reaction_confirmed", "mapping_name": "1h_5m", "parent_timeframe": "1H", "reaction_timeframe": "5m", "optional_1m_refinement": False, "evaluation_at": at, "direction": 1}
    assert select_e1_context(range_, [e1]).eligible
    assert select_e1_context(range_, [e1], negative=True).first_failure == "direction_mismatch"
    conflict = dict(e1, snapshot_id="b", direction=-1)
    assert select_e1_context(range_, [e1, conflict]).first_failure == "conflicting_constituents"
    sweep = {"anchor_id": "sweep", "anchor_type": "named_liquidity_sweep", "anchor_at": at, "direction": 1, "main_scope_eligible": True, "anchor_causally_observable": True, "anchor_selected_using_later_completion": False, "later_invalidated": True}
    assert select_e3_liquidity_sweep(range_, [sweep]).eligible
    assert select_e3_liquidity_sweep(range_, [dict(sweep, anchor_selected_using_later_completion=True)]).first_failure == "missing_constituent"
    assert select_e3_refinement(range_, at + pd.Timedelta(minutes=5), [dict(sweep, anchor_id="r", anchor_type="refinement_array_creation", anchor_at=at + pd.Timedelta(minutes=5))]).eligible
    d004 = {"trading_date": named_trading_date(at), "low_sweep": True, "low_reentry": True, "low_reentry_time": at - pd.Timedelta(minutes=2)}
    assert select_d004_reentry(range_, [d004]).event_at == at - pd.Timedelta(minutes=1)
    assert select_d004_reentry(range_, [dict(d004, low_reentry_time=at - pd.Timedelta(days=1))]).first_failure == "missing_constituent"
    block = D006BlockEvidence("z", "single_wick_50_d3_v1", 1, at - pd.Timedelta(minutes=10), 3.0, "ACTIVE_TOUCHED", at - pd.Timedelta(minutes=5), expiry_deadline=at + pd.Timedelta(hours=23, minutes=50))
    narrow = D006BlockEvidence("a", "single_wick_50_d3_v1", 1, at - pd.Timedelta(minutes=10), 1.0, "ACTIVE_TOUCHED", at - pd.Timedelta(minutes=5), expiry_deadline=at + pd.Timedelta(hours=23, minutes=50))
    assert select_d006_membership(range_, at, [block, narrow]).evidence_id == "a"
    terminal = replace(narrow, lifecycle_state="INVALIDATED", invalidation_at=at)
    assert not select_d006_membership(range_, at, [terminal]).eligible


def test_redundancy_boundaries_and_adequacy_dispositions_fail_closed() -> None:
    range_ = reconstruct_ote_ranges(sequence(), source())[0]
    touch = range_.range_available_at + pd.Timedelta(hours=2)
    exact_low = {"evidence_id": "low", "available_at": range_.range_available_at - pd.Timedelta(minutes=60), "direction": 1}
    exact_high = {"evidence_id": "high", "available_at": range_.range_available_at + pd.Timedelta(minutes=60), "direction": 1}
    assert select_redundancy_evidence(range_, touch, [exact_low]).signed_minutes == -60
    assert select_redundancy_evidence(range_, touch, [exact_high]).signed_minutes == 60
    outside = dict(exact_low, available_at=range_.range_available_at - pd.Timedelta(minutes=60, seconds=1))
    assert select_redundancy_evidence(range_, touch, [outside]).first_failure == "missing_constituent"
    opposing = dict(exact_low, evidence_id="opposite", direction=-1, available_at=range_.range_available_at + pd.Timedelta(minutes=60))
    assert select_redundancy_evidence(range_, touch, [exact_high, opposing], allow_opposite_direction=True).first_failure == "conflicting_constituents"
    assert adequacy_requirements({})["status"] == "SAMPLE_INADEQUATE"
    adequate = {"constructed_ranges": 1000, "lifecycle_eligible": 800, "first_touches": 500, "untouched_controls": 500, "primary_pairs": 500, "bullish": 200, "bearish": 200, "endpoint_coverage": 1.0}
    adequate.update({f"pairs_{year}": 100 for year in (2022, 2023, 2024, 2025)})
    adequate.update({f"touches_{name}": 50 for name in ("asia", "premarket", "ny_observation", "ny_afternoon")})
    adequate.update({f"interaction_{name}": 500 if name == "ote_alone" else 200 if name not in {"after_d004_manipulation", "d006_rejection_block"} else 100 for name in ("ote_alone", "aligned_d005_context", "after_d004_manipulation", "frozen_liquidity_sweep", "refinement_confirmation", "d006_rejection_block", "against_d005_context_negative_control")})
    adequate.update({"geometry_ote_band_62_79": 200, "geometry_ote_reference_705": 200})
    assert adequacy_requirements(adequate)["status"] == "SAMPLE_ADEQUATE"
    assert final_disposition(integrity_passed=False, adequacy_passed=True, structural_passed=True, primary_ci_upper=1.0, non_redundant_passed=False, conditional_passed=False, geometry_passed=False, yearly_means={2022: 1, 2023: 1, 2024: 1, 2025: 1}) == "REPRODUCIBILITY_DEFECT"
    assert final_disposition(integrity_passed=True, adequacy_passed=True, structural_passed=True, primary_ci_upper=-0.1, non_redundant_passed=False, conditional_passed=False, geometry_passed=False, yearly_means={2022: -1, 2023: -1, 2024: -1, 2025: 1}) == "REJECT_COMPONENT"
