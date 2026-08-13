from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from research.d007_association_identity import (
    ADDENDUM_PATH,
    ADDENDUM_SHA256,
    ASSOCIATION_PROJECTIONS,
    NEWLY_PERMITTED_COLUMNS,
    D004EventIdentity,
    D006BlockIdentity,
    E4SequenceIdentity,
    associate_d004_to_e4,
    associate_d006_to_e4,
    select_d006_block,
    session_label,
    validate_projection,
    verify_association_projection_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _stamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


def _e4(
    sequence_id: str,
    at: str,
    direction: int = 1,
    **changes: object,
) -> E4SequenceIdentity:
    stamp = _stamp(at)
    values = {
        "sequence_id": sequence_id,
        "displacement_confirmation_event_id": f"disp-{sequence_id}",
        "anchor_event_id": f"anchor-{sequence_id}",
        "anchor_at": stamp,
        "direction": direction,
        "anchor_session": session_label(stamp),
        "anchor_year": 2024,
    }
    values.update(changes)
    return E4SequenceIdentity(**values)


def _d004(**changes: object) -> D004EventIdentity:
    values = {
        "event_id": "d004:2024-05-01:low",
        "trading_date": date(2024, 5, 1),
        "side": "low",
        "reference_name": "0800_0830",
        "sweep_at": _stamp("2024-05-01T12:35:00Z"),
        "reentry_at": _stamp("2024-05-01T12:40:00Z"),
        "available_at": _stamp("2024-05-01T12:41:00Z"),
        "direction": 1,
    }
    values.update(changes)
    return D004EventIdentity(**values)


def _block(block_id: str = "block-a", available: str = "2024-05-01T14:00:00Z", **changes: object) -> D006BlockIdentity:
    available_at = _stamp(available)
    values = {
        "block_id": block_id,
        "definition_name": "single_wick_50_d3_v1",
        "direction": 1,
        "source_bar_ids": (f"source-{block_id}",),
        "expansion_bar_id": f"expansion-{block_id}",
        "confirmation_at": available_at,
        "causal_availability": available_at,
        "first_touch_at": available_at + pd.Timedelta(minutes=30),
        "expiry_deadline": available_at + pd.Timedelta(hours=24),
        "range_size": 2.0,
    }
    values.update(changes)
    return D006BlockIdentity(**values)


def test_d004_exact_unique_association_and_stable_identity() -> None:
    event = _d004()
    sequence = _e4("e4-a", "2024-05-01T12:30:00Z")
    first = associate_d004_to_e4(event, [sequence])
    second = associate_d004_to_e4(event, [sequence])
    assert first.associated
    assert first == second
    assert first.e4_sequence_id == "e4-a"
    assert first.e4_validation_year == 2024
    assert first.e4_anchor_year == 2024
    assert first.association_id == (
        "d007-assoc-"
        "5d2f54524bfbcab23c593dbc25fc4961dfedae75b968464b62200af03610efb2"
    )
    assert first.exclusion_reason is None


def test_d004_no_association_direction_and_named_date_fail_closed() -> None:
    event = _d004()
    assert associate_d004_to_e4(event, []).exclusion_reason == "no_eligible_e4_sequence"
    opposite = _e4("opposite", "2024-05-01T12:30:00Z", -1)
    assert associate_d004_to_e4(event, [opposite]).exclusion_reason == "direction_mismatch"
    next_date = _e4("next-date", "2024-05-02T12:30:00Z")
    assert associate_d004_to_e4(event, [next_date]).exclusion_reason == "named_date_mismatch"
    future = _e4("future", "2024-05-01T13:00:00Z")
    assert associate_d004_to_e4(event, [future]).exclusion_reason == "no_prior_e4_in_1440m_window"


def test_d004_multiple_candidates_use_latest_prior_and_lexical_tie_break() -> None:
    event = _d004()
    older = _e4("older", "2024-05-01T12:15:00Z")
    tie_z = _e4(
        "z",
        "2024-05-01T12:30:00Z",
        displacement_confirmation_event_id="same-event",
    )
    tie_a = _e4(
        "a",
        "2024-05-01T12:30:00Z",
        displacement_confirmation_event_id="same-event",
    )
    latest = associate_d004_to_e4(event, [older, tie_z, tie_a])
    reordered = associate_d004_to_e4(event, [tie_a, older, tie_z])
    assert latest.e4_sequence_id == "a"
    assert reordered == latest


def test_d004_identity_rejects_side_direction_and_stored_date_mismatch() -> None:
    with pytest.raises(ValueError, match="side/direction"):
        _d004(direction=-1)
    with pytest.raises(ValueError, match="named trading date"):
        _d004(
            trading_date=date(2024, 5, 2),
            event_id="d004:2024-05-02:low",
        )
    with pytest.raises(ValueError, match="canonical"):
        _d004(event_id="arbitrary")
    with pytest.raises(ValueError, match="plus one minute"):
        _d004(available_at=_stamp("2024-05-01T12:42:00Z"))
    with pytest.raises(ValueError, match="completed sweep"):
        _d004(sweep_completed=False)
    with pytest.raises(ValueError, match="1-minute grid"):
        _d004(
            reentry_at=_stamp("2024-05-01T12:40:30Z"),
            available_at=_stamp("2024-05-01T12:41:30Z"),
        )
    with pytest.raises(ValueError, match="-1/1"):
        _d004(direction=True)


def test_duplicate_e4_sequence_identity_fails_closed() -> None:
    sequence = _e4("duplicate", "2024-05-01T12:30:00Z")
    with pytest.raises(ValueError, match="duplicate sequence_id"):
        associate_d004_to_e4(_d004(), [sequence, sequence])
    with pytest.raises(ValueError, match="sequence/anchor conflict"):
        _e4(
            "conflict",
            "2024-05-01T12:30:00Z",
            anchor_sequence_id="other",
        )
    with pytest.raises(ValueError, match="sequence/anchor conflict"):
        _e4(
            "conflict",
            "2024-05-01T12:30:00Z",
            anchor_direction=-1,
        )
    with pytest.raises(ValueError, match="flags must be boolean"):
        _e4(
            "bad-flag",
            "2024-05-01T12:30:00Z",
            main_scope_eligible="false",
        )
    with pytest.raises(ValueError, match="-1/1"):
        _e4("bad-direction", "2024-05-01T12:30:00Z", direction=True)


def test_d006_exact_unique_association_and_no_association() -> None:
    block = _block()
    sequence = _e4("e4-a", "2024-05-01T13:45:00Z")
    decision = associate_d006_to_e4(block, [sequence])
    assert decision.associated
    assert decision.e4_sequence_id == "e4-a"
    assert decision.elapsed_minutes == 45.0
    assert decision.association_distance_minutes == 15.0
    assert decision.association_reference_at == block.causal_availability
    assert associate_d006_to_e4(block, []).exclusion_reason == "no_eligible_e4_sequence"


def test_d006_direction_session_and_window_boundaries_are_exact() -> None:
    block = _block()
    opposite = _e4("opposite", "2024-05-01T13:45:00Z", -1)
    assert associate_d006_to_e4(block, [opposite]).exclusion_reason == "direction_mismatch"
    premarket = _e4("premarket", "2024-05-01T12:15:00Z")
    assert associate_d006_to_e4(block, [premarket]).exclusion_reason == "named_date_or_session_mismatch"
    lower_inclusive = _e4("lower", "2024-05-01T13:00:00Z")
    assert associate_d006_to_e4(block, [lower_inclusive]).associated
    upper_exclusive = _e4("same-bar", "2024-05-01T14:00:00Z")
    assert associate_d006_to_e4(block, [upper_exclusive]).exclusion_reason == "no_prior_e4_in_60m_window"
    too_old = _e4("old", "2024-05-01T12:55:00Z")
    assert associate_d006_to_e4(block, [too_old]).exclusion_reason == "no_prior_e4_in_60m_window"


def test_d006_multiple_e4_candidates_use_latest_then_stable_ids() -> None:
    block = _block()
    older = _e4("older", "2024-05-01T13:30:00Z")
    tie_z = _e4("z", "2024-05-01T13:50:00Z", displacement_confirmation_event_id="same-event")
    tie_a = _e4("a", "2024-05-01T13:50:00Z", displacement_confirmation_event_id="same-event")
    first = associate_d006_to_e4(block, [tie_z, older, tie_a])
    reordered = associate_d006_to_e4(block, [tie_a, tie_z, older])
    assert first.e4_sequence_id == "a"
    assert reordered == first


def test_d006_lifecycle_ineligibility_and_terminal_boundaries_fail_closed() -> None:
    sequence = _e4("e4-a", "2024-05-01T13:45:00Z")
    block = _block()
    same_bar = _block(first_touch_at=block.causal_availability)
    assert associate_d006_to_e4(same_bar, [sequence]).associated
    assert associate_d006_to_e4(
        replace(block, preavailability_interaction=True), [sequence]
    ).exclusion_reason == "lifecycle_ineligible_block"
    with pytest.raises(ValueError, match="state/timestamp"):
        replace(block, lifecycle_state="MITIGATED")
    with pytest.raises(ValueError, match="multiple terminal"):
        replace(
            block,
            lifecycle_state="MITIGATED",
            mitigation_at=block.first_touch_at + pd.Timedelta(minutes=1),
            invalidation_at=block.first_touch_at + pd.Timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="expiry timestamp"):
        replace(
            block,
            lifecycle_state="EXPIRED",
            expiry_at=block.expiry_deadline - pd.Timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="unknown"):
        replace(block, lifecycle_state="UNKNOWN")
    with pytest.raises(ValueError, match="before expiry"):
        _block(
            available="2024-04-30T14:30:00Z",
            first_touch_at=_stamp("2024-05-01T14:30:00Z"),
            expiry_deadline=_stamp("2024-05-01T14:30:00Z"),
        )


def test_d006_source_identity_and_duplicate_e4_fail_closed() -> None:
    block = _block()
    with pytest.raises(ValueError, match="source identities"):
        replace(block, source_bar_ids=("z", "a"))
    with pytest.raises(ValueError, match="source identities"):
        replace(block, expansion_bar_id=block.source_bar_ids[0])
    sequence = _e4("duplicate", "2024-05-01T13:45:00Z")
    with pytest.raises(ValueError, match="duplicate sequence_id"):
        associate_d006_to_e4(block, [sequence, sequence])


def test_d006_multiple_blocks_preserve_latest_narrowest_stable_id_precedence() -> None:
    at = _stamp("2024-05-01T14:30:00Z")
    older = _block("older", "2024-05-01T13:00:00Z", first_touch_at=at)
    wide = _block("wide", "2024-05-01T14:00:00Z", first_touch_at=at, range_size=3.0)
    z = _block("z", "2024-05-01T14:00:00Z", first_touch_at=at, range_size=1.0)
    a = _block("a", "2024-05-01T14:00:00Z", first_touch_at=at, range_size=1.0)
    first = select_d006_block([older, wide, z, a], at, 1)
    reordered = select_d006_block([a, z, wide, older], at, 1)
    assert first is not None and first.block_id == "a"
    assert reordered == first
    assert select_d006_block([replace(older, direction=-1)], at, 1) is None


def test_projection_contract_is_explicit_and_outcome_blind() -> None:
    assert NEWLY_PERMITTED_COLUMNS == {
        "d004_daily_events": (
            "primary_reference_name",
            "high_sweep_time",
            "low_sweep_time",
        ),
        "d006_structural_blocks": (
            "source_bar_ids",
            "expansion_bar_id",
            "confirmation_timestamp",
        ),
    }
    for artifact, columns in ASSOCIATION_PROJECTIONS.items():
        assert validate_projection(artifact, columns) == columns
        assert not any("outcome" in column.lower() for column in columns)
    with pytest.raises(ValueError, match="full-table"):
        validate_projection("d004_daily_events", None)
    with pytest.raises(ValueError, match="forbidden"):
        validate_projection("d005_e4_eligible_sequences", ("outcome",))
    with pytest.raises(ValueError, match="forbidden"):
        validate_projection("d004_daily_events", ("horizon_0900_1000_close",))


def test_addendum_identity_is_frozen() -> None:
    assert ADDENDUM_SHA256 != "ADDENDUM_SHA256_PLACEHOLDER"
    path = ROOT / ADDENDUM_PATH
    assert path.is_file()
    from research.d007_methodology_clarification import file_sha256

    assert file_sha256(path) == ADDENDUM_SHA256


def test_authenticated_projection_schemas_are_frozen_without_row_reads() -> None:
    observed = verify_association_projection_contract(ROOT)
    assert set(observed) == set(ASSOCIATION_PROJECTIONS)
    assert all(len(digest) == 64 for digest in observed.values())
