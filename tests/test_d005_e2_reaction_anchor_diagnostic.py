from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.context_engine.bars import normalize_bars
from research.d005_e2_reaction_anchor_diagnostic.analysis import (
    attach_evidence_signatures,
    build_direction_audit,
    classify_dominant_cause,
)
from research.d005_e2_reaction_anchor_diagnostic.config import (
    ReactionAnchorDiagnosticConfig,
)
from research.d005_e2_reaction_anchor_diagnostic.directions import (
    classify_outcome,
    direction_mismatch_table,
    expected_post_sweep_direction,
    liquidity_raid_direction,
)
from research.d005_e2_reaction_anchor_diagnostic.outcomes import (
    build_anchor_inventory,
    calculate_forward_outcomes,
    sequence_latency_outcomes,
)
from research.d005_e2_reaction_anchor_diagnostic.reconstruction import (
    _directions_at,
    attach_uncapped_engine_evaluations,
    attach_first_refinement_interaction,
    d005_config_for_mapping_variant,
    engine_evidence_matches_sequence,
)


ROOT = Path(__file__).resolve().parents[1]


def _bars(
    index: pd.DatetimeIndex,
    close: list[float],
    *,
    timeframe: str = "1min",
) -> pd.DataFrame:
    values = np.asarray(close, dtype=float)
    opening = np.r_[values[0], values[:-1]]
    return normalize_bars(
        pd.DataFrame(
            {
                "open": opening,
                "high": np.maximum(opening, values) + 0.2,
                "low": np.minimum(opening, values) - 0.2,
                "close": values,
            },
            index=index,
        ),
        timeframe,
    )


def test_e2_spec_and_uncapped_boundary() -> None:
    assert (
        ROOT / "docs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC_SPEC.md"
    ).is_file()
    config = ReactionAnchorDiagnosticConfig()
    config.validate()
    assert config.uncapped_event_limit is None
    assert config.snapshot()["event_cap"] is None
    assert not config.production_entry_authorization
    assert not config.optimization
    assert config.forward_minutes == (5, 15, 30, 60, 120)
    assert [item.name for item in config.mapping_variants] == [
        "weekly_4h_1h",
        "daily_1h_15m",
        "4h_15m_5m",
        "1h_5m",
        "1h_5m_optional_1m",
    ]
    with pytest.raises(ValueError, match="cannot set an event cap"):
        replace(config, uncapped_event_limit=1).validate()


def test_optional_mapping_reconstruction_uses_one_minute_refinement() -> None:
    variant = ReactionAnchorDiagnosticConfig().mapping_variant(
        "1h_5m_optional_1m"
    )
    mapping = d005_config_for_mapping_variant(variant).mapping(
        variant.d005_mapping
    )
    assert mapping.reaction == "5min"
    assert mapping.refinement == "5min"
    assert mapping.optional_refinement == "1min"


@pytest.mark.parametrize(
    ("taxonomy", "raid", "reaction"),
    [
        ("buy_side_liquidity", 1, -1),
        ("equal_high_liquidity", 1, -1),
        ("premarket_high", 1, -1),
        ("sell_side_liquidity", -1, 1),
        ("equal_low_liquidity", -1, 1),
        ("premarket_low", -1, 1),
        ("ict_fair_value_gap", 0, 0),
    ],
)
def test_liquidity_raid_and_expected_reaction_are_never_conflated(
    taxonomy: str,
    raid: int,
    reaction: int,
) -> None:
    assert liquidity_raid_direction(taxonomy) == raid
    assert expected_post_sweep_direction(taxonomy) == reaction
    if raid:
        assert reaction == -raid


@pytest.mark.parametrize(
    (
        "candidate_type",
        "candidate",
        "parent",
        "pre_child",
        "expected",
    ),
    [
        ("liquidity_sweep", 1, 0, -1, "reversal"),
        ("liquidity_sweep", -1, -1, -1, "continuation"),
        ("raw_fvg", 1, 1, -1, "reversal"),
        ("raw_fvg", 1, 1, 1, "continuation"),
        ("order_block", -1, -1, 0, "continuation"),
    ],
)
def test_reversal_and_continuation_mapping_matches_frozen_d005(
    candidate_type: str,
    candidate: int,
    parent: int,
    pre_child: int,
    expected: str,
) -> None:
    assert (
        classify_outcome(
            candidate_type=candidate_type,
            candidate_direction=candidate,
            parent_direction=parent,
            pre_candidate_child_direction=pre_child,
        )
        == expected
    )


def test_structure_direction_audit_is_causal_at_each_query() -> None:
    swings = pd.DataFrame(
        [
            {
                "swing_type": "high",
                "level": 100.0,
                "confirmation_at": pd.Timestamp(
                    "2025-01-01 01:00", tz="UTC"
                ),
            },
            {
                "swing_type": "low",
                "level": 90.0,
                "confirmation_at": pd.Timestamp(
                    "2025-01-01 02:00", tz="UTC"
                ),
            },
            {
                "swing_type": "high",
                "level": 102.0,
                "confirmation_at": pd.Timestamp(
                    "2025-01-01 03:00", tz="UTC"
                ),
            },
            {
                "swing_type": "low",
                "level": 92.0,
                "confirmation_at": pd.Timestamp(
                    "2025-01-01 04:00", tz="UTC"
                ),
            },
        ]
    )
    query = pd.Series(
        [
            pd.Timestamp("2025-01-01 03:30", tz="UTC"),
            pd.Timestamp("2025-01-01 04:00", tz="UTC"),
        ]
    )
    direction, context = _directions_at(swings, query)
    assert direction.tolist() == [0, 1]
    assert pd.isna(context[0])
    assert context[1] == pd.Timestamp("2025-01-01 04:00", tz="UTC")


def test_first_refinement_interaction_is_after_creation_and_separate() -> None:
    index = pd.date_range(
        "2025-01-01 00:00", periods=8, freq="1min", tz="UTC"
    )
    bars = _bars(index, [100, 101, 102, 103, 104, 103, 102, 101])
    sequence = pd.DataFrame(
        [
            {
                "sequence_id": "s",
                "refinement_timeframe": "1min",
                "refinement_created_at": pd.Timestamp(
                    "2025-01-01 00:04", tz="UTC"
                ),
                "refinement_zone_low": 101.5,
                "refinement_zone_high": 102.5,
                "refinement_direction": 1,
            }
        ]
    )
    result = attach_first_refinement_interaction(
        sequence, timeframes={"1min": bars}
    ).iloc[0]
    assert result["refinement_interacted_at"] > result[
        "refinement_created_at"
    ]
    assert result["refinement_interaction_price"] == pytest.approx(102.5)
    assert np.isfinite(result["refinement_interaction_close"])


def test_uncapped_engine_selection_requires_exact_ordered_evidence() -> None:
    base = {
        "engine_state": "reaction_confirmed",
        "engine_evidence_ids": ["candidate", "mss", "disp", "array"],
        "candidate_id": "candidate",
        "mss_id": "mss",
        "displacement_id": "disp",
        "refinement_id": "array",
    }
    assert engine_evidence_matches_sequence(base)
    assert not engine_evidence_matches_sequence(
        {**base, "engine_evidence_ids": ["candidate", "disp", "mss", "array"]}
    )
    assert not engine_evidence_matches_sequence(
        {**base, "engine_state": "invalidated"}
    )


def test_uncapped_engine_confirmation_join_normalizes_utc_timestamp() -> None:
    stamp = pd.Timestamp("2025-01-01 10:00", tz="UTC")
    sequences = pd.DataFrame(
        [
            {
                "mapping_variant": "1h_5m",
                "refinement_created_at": stamp,
                "candidate_id": "candidate",
                "mss_id": "mss",
                "displacement_id": "disp",
                "refinement_id": "array",
                "d005_reaction_confirmed_at": pd.NaT,
                "final_d005_direction": 1,
            }
        ]
    )
    evaluations = pd.DataFrame(
        [
            {
                "mapping_variant": "1h_5m",
                "evaluation_at": stamp,
                "engine_state": "reaction_confirmed",
                "engine_evidence_ids": [
                    "candidate",
                    "mss",
                    "disp",
                    "array",
                ],
                "engine_reaction_confirmed_at": stamp,
                "engine_direction": -1,
            }
        ]
    )
    result = attach_uncapped_engine_evaluations(
        sequences, evaluations
    ).iloc[0]
    assert result["engine_selected_reaction_confirmed"]
    assert result["d005_reaction_confirmed_at"] == stamp
    assert result["final_d005_direction"] == -1


def test_cause_classifier_accepts_object_backed_utc_timestamps() -> None:
    direction_audit = pd.DataFrame(
        [
            {
                "population": "e1_capped",
                "engine_selected_reaction_confirmed": False,
                "sweep_expected_mapping_valid": True,
                "sweep_raid_not_used_as_reaction": True,
                "reversal_direction_valid": True,
                "continuation_parent_alignment_valid": True,
            }
        ]
    )
    sequences = pd.DataFrame(
        [
                {
                    "population": "e1_capped",
                    "engine_selected_reaction_confirmed": False,
                    "candidate_at": pd.Timestamp(
                    "2025-01-01 10:00", tz="UTC"
                ),
                "d005_reaction_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:05", tz="UTC"
                ),
            }
        ],
        dtype=object,
    )
    common = {
        "horizon": "60m",
        "outcome": "reversal",
        "mapping_variant": "1h_5m",
        "candidate_variant": "three_candle",
        "refinement_variant": "three_candle",
        "engine_selected_reaction_confirmed": False,
    }
    forward = pd.DataFrame(
        [
            {
                **common,
                "population": "e1_capped",
                "anchor_type": "poi_or_sweep_close",
                "signed_forward_movement": 1.0,
            },
            {
                **common,
                "population": "e1_capped",
                "anchor_type": "reaction_confirmed_close",
                "signed_forward_movement": -1.0,
            },
        ]
    )
    cap_summary = pd.DataFrame(
        [
            {
                    "population": "e1_capped",
                    "mean_signed_movement_60m": -1.0,
                    "sequence_count": 1,
                    "forward_observations": 1,
                }
        ]
    )
    result = classify_dominant_cause(
        direction_audit=direction_audit,
        sequences=sequences,
        forward=forward,
        cap_summary=cap_summary,
    )
    assert 2 in result["classification_ids"]


def test_anchor_outcomes_are_downstream_only_and_use_price_override() -> None:
    index = pd.date_range(
        "2025-01-02 14:00", periods=130, freq="1min", tz="UTC"
    )
    bars = _bars(index, np.linspace(100.0, 110.0, len(index)).tolist())
    anchor_at = pd.Timestamp(bars["available_at"].iloc[10])
    anchors = pd.DataFrame(
        [
            {
                "sequence_id": "s",
                "population": "e2_uncapped",
                "mapping_variant": "1h_5m",
                "outcome": "continuation",
                "candidate_type": "raw_fvg",
                "candidate_source": "poi_interaction",
                "candidate_variant": "three_candle",
                "candidate_taxonomy": "ict_fair_value_gap",
                "refinement_type": "raw_fvg",
                "refinement_variant": "three_candle",
                "pmh_pml": False,
                "anchor_type": "refinement_interaction_reference",
                "anchor_at": anchor_at,
                "direction": 1,
                "anchor_price_basis": "refinement_interaction_price",
                "anchor_price_override": 99.5,
            }
        ]
    )
    config = replace(
        ReactionAnchorDiagnosticConfig(),
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        forward_minutes=(5,),
    )
    result = calculate_forward_outcomes(
        anchors, bars, config=config
    ).iloc[0]
    assert result["anchor_price"] == 99.5
    assert result["signed_forward_movement"] > 0
    assert result["outcome_is_downstream_only"]
    assert result["observed_until"] <= result["horizon_at"]
    assert result["observed_until"] > result["anchor_at"]


def test_anchor_inventory_never_merges_creation_and_interaction() -> None:
    sequence = pd.DataFrame(
        [
            {
                "sequence_id": "s",
                "population": "e1_capped",
                "mapping_variant": "1h_5m",
                "outcome": "reversal",
                "candidate_type": "liquidity_sweep",
                "candidate_source": "liquidity_sweep",
                "candidate_variant": "reclaim",
                "candidate_taxonomy": "buy_side_liquidity",
                "refinement_type": "raw_fvg",
                "refinement_variant": "three_candle",
                "pmh_pml": False,
                "candidate_at": pd.Timestamp(
                    "2025-01-01 10:00", tz="UTC"
                ),
                "mss_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:05", tz="UTC"
                ),
                "displacement_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:10", tz="UTC"
                ),
                "refinement_created_at": pd.Timestamp(
                    "2025-01-01 10:11", tz="UTC"
                ),
                "refinement_interacted_at": pd.Timestamp(
                    "2025-01-01 10:20", tz="UTC"
                ),
                "d005_reaction_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:11", tz="UTC"
                ),
                "refinement_interaction_price": 100.0,
                "refinement_interaction_close": 99.8,
                "final_d005_direction": -1,
                "candidate_direction": -1,
            }
        ]
    )
    anchors = build_anchor_inventory(sequence)
    times = anchors.set_index("anchor_type")["anchor_at"]
    assert (
        times["refinement_creation_close"]
        != times["refinement_interaction_close"]
    )
    assert (
        times["reaction_confirmed_close"]
        == times["refinement_creation_close"]
    )


def test_latency_retains_negative_interaction_to_confirmation_order() -> None:
    index = pd.date_range(
        "2025-01-01 10:00", periods=40, freq="1min", tz="UTC"
    )
    bars = _bars(index, np.linspace(100, 104, len(index)).tolist())
    sequence = pd.DataFrame(
        [
            {
                "sequence_id": "s",
                "population": "e1_capped",
                "mapping_variant": "1h_5m",
                "outcome": "continuation",
                "candidate_type": "raw_fvg",
                "candidate_variant": "fvg",
                "refinement_type": "raw_fvg",
                "refinement_variant": "fvg",
                "candidate_at": pd.Timestamp(
                    "2025-01-01 10:01", tz="UTC"
                ),
                "mss_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:05", tz="UTC"
                ),
                "displacement_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:10", tz="UTC"
                ),
                "refinement_created_at": pd.Timestamp(
                    "2025-01-01 10:11", tz="UTC"
                ),
                "refinement_interacted_at": pd.Timestamp(
                    "2025-01-01 10:20", tz="UTC"
                ),
                "d005_reaction_confirmed_at": pd.Timestamp(
                    "2025-01-01 10:11", tz="UTC"
                ),
                "final_d005_direction": 1,
                "candidate_direction": 1,
            }
        ]
    )
    latency = sequence_latency_outcomes(sequence, bars)
    row = latency[
        latency["latency_stage"].eq(
            "first_interaction_to_reaction_confirmed"
        )
    ].iloc[0]
    assert row["elapsed_minutes"] == -9
    assert not row["timestamp_order_valid"]


def test_direction_mismatch_tables_detect_exact_sign_inversion() -> None:
    frame = pd.DataFrame(
        [
            {
                "population": "e1_capped",
                "mapping_variant": "1h_5m",
                "outcome": "reversal",
                "candidate_direction": 1,
                "mss_direction": -1,
            },
            {
                "population": "e1_capped",
                "mapping_variant": "1h_5m",
                "outcome": "reversal",
                "candidate_direction": 1,
                "mss_direction": 1,
            },
        ]
    )
    result = direction_mismatch_table(
        frame,
        direction_columns=("candidate_direction", "mss_direction"),
    ).iloc[0]
    assert result["observations"] == 2
    assert result["mismatches"] == 1
    assert result["exact_sign_inversions"] == 1


def test_evidence_signature_is_exact_and_deterministic() -> None:
    frame = pd.DataFrame(
        [
            {
                "mapping_variant": "1h_5m",
                "candidate_id": "c",
                "mss_id": "m",
                "displacement_id": "d",
                "refinement_id": "r",
            },
            {
                "mapping_variant": "1h_5m",
                "candidate_id": "c",
                "mss_id": "m",
                "displacement_id": "d",
                "refinement_id": "r2",
            },
        ]
    )
    first = attach_evidence_signatures(frame)
    second = attach_evidence_signatures(frame)
    assert first["evidence_signature"].tolist() == second[
        "evidence_signature"
    ].tolist()
    assert first["evidence_signature"].nunique() == 2
