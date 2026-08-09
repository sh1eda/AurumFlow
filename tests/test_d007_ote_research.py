from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import shutil

import pandas as pd
import pytest

from research.d007_ote_research.config import (
    CRITERION_PROVENANCE,
    D007Config,
    FIXED_CONTROLS,
    FIXED_GEOMETRIES,
    FIXED_MULTIPLE_TESTING,
    ProvenanceCriterion,
    config_fingerprint,
)
from research.d007_ote_research.detector import (
    construct_ote_ranges,
    deduplicate_primary_overlaps,
    deduplicate_ranges,
    no_range_extension_after_availability,
)
from research.d007_ote_research.guardrails import (
    ControlCandidate,
    InteractionEvidence,
    adequacy_status,
    component_disposition,
    conditional_candidate_eligible,
    control_is_eligible,
    endpoint_eligible_from_availability,
    interaction_is_causal,
    select_control,
)
from research.d007_ote_research.lifecycle import (
    evaluate_lifecycle,
    primary_lifecycle_eligible,
)
from research.d007_ote_research.models import (
    ClosedBar,
    Direction,
    FrozenDisplacementAnchor,
    attach_relationships,
)
from research.d007_ote_research.preflight import (
    assert_allowed_changed_paths,
    assert_historical_execution_forbidden,
    assert_validation_year,
    fingerprint_ignored_non_table_artifacts,
    inspect_static_package,
    run_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def _stamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


def _bar(
    opened_at: str,
    open_: float,
    high: float,
    low: float,
    close: float,
    *,
    complete: bool = True,
    suffix: str = "",
) -> ClosedBar:
    opened = _stamp(opened_at)
    return ClosedBar(
        bar_id=f"bar-{opened.isoformat()}-{suffix}",
        opened_at=opened,
        available_at=opened + pd.Timedelta(minutes=5),
        open=open_,
        high=high,
        low=low,
        close=close,
        is_complete=complete,
    )


def _bullish_anchor() -> FrozenDisplacementAnchor:
    return FrozenDisplacementAnchor(
        upstream_event_id="d005-bull-1",
        direction=Direction.BULLISH,
        displacement_created_at=_stamp("2024-01-02 10:00+00:00"),
        displacement_available_at=_stamp("2024-01-02 10:15+00:00"),
        origin_swing_at=_stamp("2024-01-02 09:30+00:00"),
        origin_confirmed_at=_stamp("2024-01-02 09:45+00:00"),
        origin_price=100.0,
    )


def _bullish_source(*, future_high: float = 999.0) -> tuple[ClosedBar, ...]:
    return (
        _bar("2024-01-02 10:00+00:00", 101.0, 112.0, 100.0, 111.0),
        _bar("2024-01-02 10:05+00:00", 111.0, 120.0, 110.0, 119.0),
        _bar("2024-01-02 10:10+00:00", 119.0, 119.5, 115.0, 118.0),
        _bar("2024-01-02 10:15+00:00", 118.0, future_high, 117.0, 118.0),
    )


def _bearish_anchor() -> FrozenDisplacementAnchor:
    return FrozenDisplacementAnchor(
        upstream_event_id="d005-bear-1",
        direction=Direction.BEARISH,
        displacement_created_at=_stamp("2024-01-03 10:00+00:00"),
        displacement_available_at=_stamp("2024-01-03 10:15+00:00"),
        origin_swing_at=_stamp("2024-01-03 09:30+00:00"),
        origin_confirmed_at=_stamp("2024-01-03 09:45+00:00"),
        origin_price=120.0,
    )


def _bearish_source() -> tuple[ClosedBar, ...]:
    return (
        _bar("2024-01-03 10:00+00:00", 119.0, 120.0, 108.0, 109.0),
        _bar("2024-01-03 10:05+00:00", 109.0, 110.0, 100.0, 101.0),
        _bar("2024-01-03 10:10+00:00", 101.0, 105.0, 100.5, 102.0),
    )


def _primary_bullish():
    return construct_ote_ranges(_bullish_anchor(), _bullish_source())[0]


def test_bullish_and_bearish_geometry_is_exact_and_symmetric() -> None:
    bullish, bullish_point = construct_ote_ranges(_bullish_anchor(), _bullish_source())
    bearish, bearish_point = construct_ote_ranges(_bearish_anchor(), _bearish_source())

    assert bullish.geometry_id == "ote_band_62_79"
    assert (bullish.origin_price, bullish.endpoint_price) == (100.0, 120.0)
    assert bullish.proximal == pytest.approx(107.6)
    assert bullish.reference == pytest.approx(105.9)
    assert bullish.distal == pytest.approx(104.2)
    assert bullish.equilibrium == pytest.approx(110.0)
    assert (bullish.zone_low, bullish.zone_high) == pytest.approx((104.2, 107.6))
    assert bullish.range_available_at == _stamp("2024-01-02 10:15+00:00")
    assert bullish.preavailability_interaction is False
    assert bullish_point.proximal == bullish_point.reference == bullish_point.distal

    assert (bearish.origin_price, bearish.endpoint_price) == (120.0, 100.0)
    assert bearish.proximal == pytest.approx(112.4)
    assert bearish.reference == pytest.approx(114.1)
    assert bearish.distal == pytest.approx(115.8)
    assert bearish.equilibrium == pytest.approx(110.0)
    assert (bearish.zone_low, bearish.zone_high) == pytest.approx((112.4, 115.8))
    assert bearish_point.reference == pytest.approx(114.1)


def test_range_availability_is_future_blind_and_ids_are_stable() -> None:
    first = construct_ote_ranges(_bullish_anchor(), _bullish_source(future_high=999.0))
    second = construct_ote_ranges(_bullish_anchor(), _bullish_source(future_high=1500.0))
    assert first == second
    assert [item.range_id for item in first] == [item.range_id for item in second]
    assert all(item.endpoint_price == 120.0 for item in first)
    changed_source_id = list(_bullish_source())
    changed_source_id[1] = replace(
        changed_source_id[1], bar_id="same-prices-different-source-id"
    )
    changed_identity = construct_ote_ranges(
        _bullish_anchor(), changed_source_id
    )
    assert [item.range_id for item in changed_identity] != [
        item.range_id for item in first
    ]
    with pytest.raises(ValueError, match="range extension"):
        no_range_extension_after_availability(first[0], 121.0)
    assert no_range_extension_after_availability(first[0], 120.0) == first[0]


def test_preavailability_interaction_is_flagged_and_excluded() -> None:
    source = list(_bullish_source())
    source[2] = replace(source[2], low=106.0)
    ote_range = construct_ote_ranges(_bullish_anchor(), source)[0]
    assert ote_range.preavailability_interaction is True
    assert primary_lifecycle_eligible(ote_range) is False
    preavailable_bar = source[2]
    record = evaluate_lifecycle(
        ote_range, [preavailable_bar], ote_range.range_available_at
    )
    assert record.touch_count == 0


def test_construction_fails_closed_on_incomplete_or_missing_causal_inputs() -> None:
    incomplete = list(_bullish_source())
    incomplete[1] = replace(incomplete[1], is_complete=False)
    with pytest.raises(ValueError, match="complete closed bars"):
        construct_ote_ranges(_bullish_anchor(), incomplete)
    with pytest.raises(ValueError, match="creation bar"):
        construct_ote_ranges(_bullish_anchor(), _bullish_source()[1:])
    with pytest.raises(ValueError, match="confirmation sequence"):
        construct_ote_ranges(_bullish_anchor(), _bullish_source()[:2])
    missing_middle = (_bullish_source()[0], _bullish_source()[2])
    with pytest.raises(ValueError, match="missing bar"):
        construct_ote_ranges(_bullish_anchor(), missing_middle)
    with pytest.raises(ValueError, match="confirmed before displacement"):
        replace(
            _bullish_anchor(),
            origin_confirmed_at=_stamp("2024-01-02 10:05+00:00"),
        )
    with pytest.raises(ValueError, match="finite"):
        _bar("2024-01-02 10:00+00:00", 100.0, float("nan"), 99.0, 100.0)
    with pytest.raises(ValueError, match="finite"):
        replace(_bullish_anchor(), origin_price=float("inf"))


def test_exact_boundary_inclusion_and_exclusion() -> None:
    ote_range = _primary_bullish()
    exact_proximal = _bar(
        "2024-01-02 10:15+00:00", 108.0, 108.5, ote_range.proximal, 108.0
    )
    record = evaluate_lifecycle(ote_range, [exact_proximal], exact_proximal.available_at)
    assert record.first_touch_at == exact_proximal.available_at
    assert record.touch_count == 1

    outside = _bar(
        "2024-01-02 10:15+00:00",
        108.0,
        108.5,
        ote_range.proximal + 0.0001,
        108.0,
        suffix="outside",
    )
    untouched = evaluate_lifecycle(ote_range, [outside], outside.available_at)
    assert untouched.status == "AVAILABLE"
    assert untouched.touch_count == 0

    exact_distal = _bar(
        "2024-01-02 10:15+00:00",
        104.2,
        ote_range.distal,
        103.9,
        104.1,
        suffix="distal",
    )
    distal = evaluate_lifecycle(ote_range, [exact_distal], exact_distal.available_at)
    assert distal.touch_count == 1


def test_first_touch_repeated_touch_invalidation_and_precedence() -> None:
    ote_range = _primary_bullish()
    first = _bar("2024-01-02 10:15+00:00", 108.0, 108.0, 107.0, 107.5)
    repeated = _bar("2024-01-02 10:20+00:00", 107.0, 107.2, 105.0, 106.0)
    invalidating = _bar("2024-01-02 10:25+00:00", 106.0, 106.5, 99.0, 99.5)
    record = evaluate_lifecycle(
        ote_range, [invalidating, repeated, first], invalidating.available_at
    )
    assert record.status == "INVALIDATED"
    assert record.first_touch_at == first.available_at
    assert record.touch_count == 2
    assert record.repeated_touch_count == 1
    assert record.invalidated_at == invalidating.available_at

    neutral_one = _bar("2024-01-02 10:15+00:00", 122.0, 123.0, 121.0, 122.0)
    neutral_two = _bar("2024-01-02 10:20+00:00", 122.0, 123.0, 121.0, 122.0)
    same_bar = evaluate_lifecycle(
        ote_range, [neutral_one, neutral_two, invalidating], invalidating.available_at
    )
    assert same_bar.status == "INVALIDATED"
    assert same_bar.touch_count == 0
    assert same_bar.first_touch_at is None
    duplicate_availability = replace(neutral_two, bar_id="duplicate-time")
    with pytest.raises(ValueError, match="availability timestamps"):
        evaluate_lifecycle(
            ote_range,
            [neutral_one, neutral_two, duplicate_availability],
            neutral_two.available_at,
        )


def test_expiry_and_incomplete_lifecycle_fail_closed() -> None:
    ote_range = _primary_bullish()
    expiry_path = [
        _bar(opened.isoformat(), 122.0, 123.0, 121.0, 122.0)
        for opened in pd.date_range(
            ote_range.range_available_at,
            ote_range.expiry_deadline - pd.Timedelta(minutes=5),
            freq="5min",
        )
    ]
    expired = evaluate_lifecycle(ote_range, expiry_path, ote_range.expiry_deadline)
    assert expired.status == "EXPIRED"
    assert expired.touch_count == 0
    assert expired.expired_at == ote_range.expiry_deadline

    incomplete = _bar(
        "2024-01-02 10:15+00:00",
        108.0,
        108.0,
        107.0,
        107.5,
        complete=False,
    )
    with pytest.raises(ValueError, match="incomplete"):
        evaluate_lifecycle(ote_range, [incomplete], incomplete.available_at)
    gap = _bar("2024-01-02 10:20+00:00", 122.0, 123.0, 121.0, 122.0)
    with pytest.raises(ValueError, match="missing"):
        evaluate_lifecycle(ote_range, [gap], gap.available_at)


def test_dedup_overlap_nesting_and_same_impulse_geometries() -> None:
    band, point = construct_ote_ranges(_bullish_anchor(), _bullish_source())
    selected, excluded = deduplicate_ranges([point, band, band, point])
    assert [item.geometry_id for item in selected] == [
        "ote_band_62_79",
        "ote_reference_705",
    ]
    assert len(excluded) == 2
    with pytest.raises(ValueError, match="conflicting reconstruction"):
        deduplicate_ranges([band, replace(band, range_id="conflict")])
    with pytest.raises(ValueError, match="conflicting reconstruction"):
        deduplicate_ranges(
            [band, replace(band, preavailability_interaction=True)]
        )

    related = attach_relationships([point, band])
    by_geometry = {item.geometry_id: item for item in related}
    assert by_geometry["ote_band_62_79"].overlap_group_id is not None
    assert by_geometry["ote_reference_705"].overlap_group_id == by_geometry[
        "ote_band_62_79"
    ].overlap_group_id
    assert by_geometry["ote_reference_705"].parent_range_id == band.range_id

    later_band = replace(
        band,
        range_id="later-band",
        upstream_event_id="later-upstream",
        range_available_at=band.range_available_at + pd.Timedelta(minutes=5),
        expiry_deadline=band.expiry_deadline + pd.Timedelta(minutes=5),
        source_bar_ids=("later-source",),
    )
    kept, overlap_excluded = deduplicate_primary_overlaps(
        [later_band, point, band]
    )
    assert [item.range_id for item in kept] == [band.range_id]
    assert [item.range_id for item in overlap_excluded] == ["later-band"]
    kept_again, excluded_again = deduplicate_primary_overlaps(
        [band, later_band, point]
    )
    assert kept_again == kept
    assert excluded_again == overlap_excluded


def _control(
    candidate_id: str,
    event_at: str,
    trading_date: date,
    *,
    direction: Direction = Direction.BULLISH,
    endpoint_complete: bool = True,
    active: bool = False,
    nearest: float | None = 180.0,
    session: str = "premarket",
) -> ControlCandidate:
    return ControlCandidate(
        candidate_id=candidate_id,
        event_at=_stamp(event_at),
        named_trading_date=trading_date,
        validation_year=2024,
        session=session,
        direction=direction,
        causal_volatility_bucket="normal",
        upstream_mapping="1h_5m",
        elapsed_to_event_bucket="30_to_60",
        endpoint_complete=endpoint_complete,
        ote_touched_at_event=active,
        nearest_unrelated_ote_touch_minutes=nearest,
    )


def test_control_eligibility_and_selection_are_causal_and_deterministic() -> None:
    treatment = _control("treatment", "2024-05-01 10:00+00:00", date(2024, 5, 1))
    eligible_a = _control("a", "2024-05-08 10:00+00:00", date(2024, 5, 8))
    eligible_b = _control("b", "2024-05-15 10:00+00:00", date(2024, 5, 15))
    assert control_is_eligible(treatment, eligible_a)
    assert select_control(treatment, [eligible_b, eligible_a], "matched_equilibrium_50") == select_control(
        treatment, [eligible_a, eligible_b], "matched_equilibrium_50"
    )
    same_timestamp = replace(eligible_a, candidate_id="z")
    assert select_control(
        treatment,
        [same_timestamp, eligible_a],
        "matched_equilibrium_50",
    ).candidate_id == "a"
    assert not control_is_eligible(
        treatment, replace(eligible_a, endpoint_complete=False)
    )
    assert not control_is_eligible(
        treatment, replace(eligible_a, ote_touched_at_event=True)
    )
    assert not control_is_eligible(
        treatment,
        replace(eligible_a, nearest_unrelated_ote_touch_minutes=119.9),
    )
    assert not control_is_eligible(treatment, replace(eligible_a, direction=Direction.BEARISH))
    assert not control_is_eligible(treatment, replace(eligible_a, session="asia"))
    assert select_control(
        treatment, [eligible_a], "matched_equilibrium_50", frozenset({"a"})
    ) is None
    with pytest.raises(ValueError, match="outside the fixed"):
        select_control(treatment, [eligible_a], "searched_control")
    with pytest.raises(ValueError, match="finite and non-negative"):
        replace(eligible_a, nearest_unrelated_ote_touch_minutes=float("nan"))
    with pytest.raises(ValueError, match="session"):
        replace(eligible_a, session="searched_session")
    with pytest.raises(ValueError, match="volatility"):
        replace(eligible_a, causal_volatility_bucket="searched_bucket")
    with pytest.raises(ValueError, match="elapsed-event"):
        replace(eligible_a, elapsed_to_event_bucket="searched_elapsed")
    with pytest.raises(ValueError, match="America/New_York"):
        replace(eligible_a, named_trading_date=date(2024, 5, 9))


def test_interaction_causality_blocks_late_evidence_and_d006_is_only_registered() -> None:
    ote_range = _primary_bullish()
    touch = _stamp("2024-01-02 10:30+00:00")
    context = InteractionEvidence(
        "aligned_d005_context",
        "ctx",
        ote_range.range_available_at,
        Direction.BULLISH,
    )
    assert interaction_is_causal(ote_range, context, touch)
    assert not interaction_is_causal(
        ote_range, replace(context, available_at=ote_range.range_available_at + pd.Timedelta(seconds=1)), touch
    )
    refinement = InteractionEvidence(
        "refinement_confirmation", "ref", touch, Direction.BULLISH
    )
    assert interaction_is_causal(ote_range, refinement, touch)
    assert not interaction_is_causal(
        ote_range, replace(refinement, available_at=touch + pd.Timedelta(seconds=1)), touch
    )
    standalone = InteractionEvidence(
        "ote_alone", "touch", touch, Direction.BULLISH
    )
    assert interaction_is_causal(ote_range, standalone, touch)
    assert not interaction_is_causal(
        ote_range,
        replace(standalone, available_at=touch + pd.Timedelta(seconds=1)),
        touch,
    )
    assert not interaction_is_causal(
        ote_range,
        replace(
            standalone,
            available_at=ote_range.range_available_at - pd.Timedelta(seconds=1),
        ),
        touch,
    )
    assert not interaction_is_causal(
        ote_range, replace(standalone, direction=Direction.BEARISH), touch
    )
    negative = InteractionEvidence(
        "against_d005_context_negative_control",
        "neg",
        ote_range.range_available_at,
        Direction.BEARISH,
    )
    assert interaction_is_causal(ote_range, negative, touch)
    with pytest.raises(ValueError, match="outside"):
        InteractionEvidence("searched_combo", "x", touch, Direction.BULLISH)
    assert conditional_candidate_eligible(["aligned_d005_context"])
    assert not conditional_candidate_eligible(
        ["after_d004_manipulation", "d006_rejection_block"]
    )


def test_endpoint_eligibility_uses_timestamps_only_and_forbids_2026() -> None:
    event = _stamp("2024-04-02 10:00+00:00")
    complete = [event + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5)]
    assert endpoint_eligible_from_availability(event, complete)
    assert not endpoint_eligible_from_availability(event, complete[:-1])
    event_2026 = _stamp("2026-04-02 10:00+00:00")
    complete_2026 = [
        event_2026 + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5)
    ]
    assert not endpoint_eligible_from_availability(event_2026, complete_2026)
    utc_cross_year = _stamp("2025-12-31 23:30+00:00")
    utc_cross_year_complete = [
        utc_cross_year + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5)
    ]
    assert endpoint_eligible_from_availability(
        utc_cross_year, utc_cross_year_complete
    )
    cross_year = _stamp("2026-01-01 04:30+00:00")
    cross_year_complete = [
        cross_year + pd.Timedelta(minutes=offset) for offset in range(0, 61, 5)
    ]
    assert not endpoint_eligible_from_availability(
        cross_year, cross_year_complete
    )
    with pytest.raises(ValueError, match="forbids"):
        assert_validation_year(2026)
    for year in (2022, 2023, 2024, 2025):
        assert_validation_year(year)


def test_adequacy_and_disposition_fail_closed() -> None:
    assert adequacy_status({}) == "SAMPLE_INADEQUATE"
    config = D007Config()
    adequate = {
        "constructed_ranges": 1000,
        "lifecycle_eligible": 800,
        "first_touches": 500,
        "untouched_controls": 200,
        "primary_pairs": 500,
        "bullish": 200,
        "bearish": 200,
        "endpoint_coverage": 1.0,
        **{f"pairs_{year}": 100 for year in config.validation_years},
        **{
            f"touches_{session}": 50 for session in config.required_sessions
        },
        **{
            f"interaction_{item.name}": item.minimum_pairs
            for item in config.interactions
        },
        **{
            f"geometry_{item.geometry_id}": 200
            for item in config.geometries
        },
    }
    assert adequacy_status(adequate) == "SAMPLE_ADEQUATE"
    assert adequacy_status({**adequate, "interaction_aligned_d005_context": 199}) == "SAMPLE_INADEQUATE"
    assert adequacy_status({**adequate, "geometry_ote_reference_705": 199}) == "SAMPLE_INADEQUATE"
    assert component_disposition(
        integrity_passed=False,
        adequacy_passed=False,
        structural_passed=False,
        primary_ci_upper=None,
        non_redundant_passed=False,
        conditional_passed=False,
        geometry_passed=False,
        yearly_means={},
    ) == "REPRODUCIBILITY_DEFECT"
    assert component_disposition(
        integrity_passed=True,
        adequacy_passed=False,
        structural_passed=False,
        primary_ci_upper=None,
        non_redundant_passed=False,
        conditional_passed=False,
        geometry_passed=False,
        yearly_means={},
    ) == "INSUFFICIENT_EVIDENCE"
    assert component_disposition(
        integrity_passed=True,
        adequacy_passed=True,
        structural_passed=True,
        primary_ci_upper=0.0,
        non_redundant_passed=False,
        conditional_passed=False,
        geometry_passed=False,
        yearly_means={2022: -1.0, 2023: 0.0, 2024: -0.2, 2025: 0.1},
    ) == "REJECT_COMPONENT"
    assert component_disposition(
        integrity_passed=True,
        adequacy_passed=True,
        structural_passed=True,
        primary_ci_upper=0.0,
        non_redundant_passed=False,
        conditional_passed=False,
        geometry_passed=False,
        yearly_means={2022: -1.0, 2023: 0.0, 2024: -0.2},
    ) == "INSUFFICIENT_EVIDENCE"
    assert component_disposition(
        integrity_passed=True,
        adequacy_passed=True,
        structural_passed=True,
        primary_ci_upper=float("nan"),
        non_redundant_passed=False,
        conditional_passed=False,
        geometry_passed=False,
        yearly_means={2022: -1.0, 2023: 0.0, 2024: -0.2, 2025: 0.1},
    ) == "INSUFFICIENT_EVIDENCE"


def test_configuration_and_provenance_are_fixed_and_unsupported_fails_closed() -> None:
    config = D007Config()
    assert config.geometries == FIXED_GEOMETRIES
    assert config.controls == FIXED_CONTROLS
    assert [
        (item.name, item.hypotheses, item.adjustment)
        for item in config.multiple_testing
    ] == [
        ("primary", 1, "unadjusted"),
        ("interactions", 6, "BH"),
        ("incremental_controls", 2, "BH"),
        ("geometry", 3, "BH"),
    ]
    assert config.multiple_testing == FIXED_MULTIPLE_TESTING
    assert config.validation_years == (2022, 2023, 2024, 2025)
    assert "furthest_directional_extreme_endpoint" in {
        item.criterion_id for item in config.provenance
    }
    assert {
        item.criterion_id: item.classification for item in config.provenance
    }["bootstrap_and_control_seed_7007"] == (
        "NEW_D007_PREREGISTERED_OPERATIONALIZATION"
    )
    assert config_fingerprint() == config_fingerprint(config)
    with pytest.raises(ValueError, match="version is fixed"):
        D007Config(version="d007-v2")
    with pytest.raises(ValueError, match="lifecycle, endpoint"):
        D007Config(lifecycle_expiry_hours=12)
    with pytest.raises(ValueError, match="lifecycle, endpoint"):
        D007Config(confidence_level=0.90)
    with pytest.raises(ValueError, match="adequacy thresholds"):
        D007Config(minimum_primary_pairs=499)
    with pytest.raises(ValueError, match="matching variables"):
        D007Config(matching_variables=("direction",))
    with pytest.raises(ValueError, match="required sessions"):
        D007Config(required_sessions=("premarket",))
    with pytest.raises(ValueError, match="data-metadata hashes"):
        D007Config(frozen_data_metadata_sha256=())
    with pytest.raises(ValueError, match="ignored-artifact aggregate"):
        D007Config(frozen_ignored_artifact_count=241)
    unsupported = replace(
        CRITERION_PROVENANCE[0], classification="UNSUPPORTED"
    )
    with pytest.raises(ValueError, match="unsupported provenance"):
        D007Config(provenance=(unsupported,) + CRITERION_PROVENANCE[1:])
    with pytest.raises(ValueError, match="unknown D007 provenance"):
        ProvenanceCriterion("bad", "SOURCEISH", "none")


def test_static_preflight_has_no_history_outcome_or_output_path(tmp_path: Path) -> None:
    changed = [
        "docs/D007_OTE_RESEARCH_SPEC.md",
        "tests/test_d007_ote_research.py",
        "research/d007_ote_research/config.py",
    ]
    result = run_preflight(ROOT, changed)
    assert result.source_hashes
    assert result.protected_hashes
    assert result.data_metadata_hashes
    assert result.raw_source_hashes
    assert result.ignored_artifact_count == 242
    assert result.ignored_artifact_fingerprint == (
        "59e41b2c69a9837dedbcbc3436dfbee815339b7413a3bba54650a7f3ed0e1777"
    )
    assert fingerprint_ignored_non_table_artifacts(ROOT) == (
        result.ignored_artifact_count,
        result.ignored_artifact_fingerprint,
    )
    assert result.spec_hash_status == "VERIFIED"
    assert result.spec_sha256 == "adb093f40b0a3a43a6174e81763e3625d38e88ba223f4b392076a240918d364f"
    assert len(result.config_fingerprint) == 64
    assert len(result.implementation_fingerprint) == 64
    assert result.accessed_market_data is False
    assert result.accessed_historical_outcomes is False
    assert result.wrote_outputs is False

    copied = tmp_path / "package"
    shutil.copytree(ROOT / "research/d007_ote_research", copied)
    assert inspect_static_package(copied) == inspect_static_package(
        ROOT / "research/d007_ote_research"
    )
    (copied / "outcomes.py").write_text("VALUE = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="module surface"):
        inspect_static_package(copied)
    (copied / "outcomes.py").unlink()
    (copied / "detector.py").write_text(
        "import pandas as pd\npd.read_parquet('forbidden')\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="forbidden"):
        inspect_static_package(copied)

    with pytest.raises(ValueError, match="outside D007"):
        assert_allowed_changed_paths(["xauusd_signal/strategy.py"])
    with pytest.raises(PermissionError, match="not authorized"):
        assert_historical_execution_forbidden()


def test_spec_freezes_required_methodology_and_no_production_authority() -> None:
    spec = (ROOT / "docs/D007_OTE_RESEARCH_SPEC.md").read_text(encoding="utf-8")
    for phrase in (
        "DIRECT_SOURCE_DEFINITION",
        "INHERITED_FROZEN_PROJECT_CONVENTION",
        "NEW_D007_PREREGISTERED_OPERATIONALIZATION",
        "UNSUPPORTED",
        "0.62-0.79",
        "0.705",
        "matched_equilibrium_50",
        "REPRODUCIBILITY_DEFECT",
        "INSUFFICIENT_EVIDENCE",
        "NON_REDUNDANT_COMPONENT_CANDIDATE",
        "CONDITIONAL_CANDIDATE",
        "GEOMETRY_CANDIDATE",
        "REJECT_COMPONENT",
        "STRUCTURALLY_VALID_EMPIRICALLY_WEAK",
        "automation/config.yaml",
        "2026 is forbidden",
    ):
        assert phrase in spec
    assert "No disposition authorizes production use." in spec
