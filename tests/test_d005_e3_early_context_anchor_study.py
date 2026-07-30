from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.context_engine.config import ORDER_BLOCK_VARIANTS
from research.d005_e3_early_context_anchor_study.analysis import (
    benjamini_hochberg,
    build_direction_family_audit,
    build_primary_comparisons,
    classify_result,
)
from research.d005_e3_early_context_anchor_study.anchors import (
    attach_independent_array_anchors,
    build_anchor_event_table,
    load_uncapped_sequences,
)
from research.d005_e3_early_context_anchor_study.config import (
    PRIMARY_ANCHORS,
    EarlyContextAnchorStudyConfig,
)
from research.d005_e3_early_context_anchor_study.outcomes import (
    build_latency_decay,
    calculate_forward_outcomes,
)


UTC = "UTC"


def _sequence(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "sequence_id": "sequence-1",
        "mapping_variant": "1h_5m",
        "outcome": "reversal",
        "candidate_source": "liquidity_sweep",
        "candidate_type": "liquidity_sweep",
        "candidate_variant": "body_reclaim",
        "candidate_taxonomy": "sell_side_liquidity",
        "candidate_id": "candidate-1",
        "candidate_at": pd.Timestamp("2024-01-02 13:00", tz=UTC),
        "candidate_invalidated_at": pd.NaT,
        "candidate_timeout_at": pd.Timestamp(
            "2024-01-02 14:00", tz=UTC
        ),
        "parent_context_created_at": pd.Timestamp(
            "2024-01-02 12:00", tz=UTC
        ),
        "parent_direction": 1,
        "candidate_direction": 1,
        "parent_candidate_aligned": True,
        "refinement_timeframe": "5min",
        "mss_id": "mss-1",
        "mss_direction": 1,
        "mss_confirmed_at": pd.Timestamp(
            "2024-01-02 13:10", tz=UTC
        ),
        "displacement_id": "disp-1",
        "displacement_direction": 1,
        "displacement_confirmed_at": pd.Timestamp(
            "2024-01-02 13:15", tz=UTC
        ),
        "raw_fvg_id": "raw-1",
        "raw_fvg_at": pd.Timestamp("2024-01-02 13:05", tz=UTC),
        "raw_fvg_direction": 1,
        "raw_fvg_variant": "three_candle_wick_nonoverlap",
        "raw_fvg_taxonomy": "ict_fair_value_gap",
        "qualified_fvg_id": "fvg-1",
        "qualified_fvg_at": pd.Timestamp(
            "2024-01-02 13:20", tz=UTC
        ),
        "qualified_fvg_direction": 1,
        "qualified_fvg_variant": "three_candle_wick_nonoverlap",
        "qualified_fvg_taxonomy": "ict_fair_value_gap",
        "refinement_id": "refine-1",
        "refinement_type": "raw_fvg",
        "refinement_variant": "three_candle_wick_nonoverlap",
        "refinement_direction": 1,
        "refinement_created_at": pd.Timestamp(
            "2024-01-02 13:20", tz=UTC
        ),
        "refinement_interacted_at": pd.Timestamp(
            "2024-01-02 13:25", tz=UTC
        ),
        "refinement_interaction_price": 100.25,
        "d005_reaction_confirmed_at": pd.Timestamp(
            "2024-01-02 13:30", tz=UTC
        ),
        "final_d005_direction": 1,
        "engine_evaluation_id": "engine-1",
        "pmh_pml": False,
        "pmh_pml_prerequisites_met": True,
        "balanced_ranging": False,
        "range_like": False,
        "candidate_session": "ny_observation",
        "candidate_session_date": "2024-01-02",
        "candidate_year": 2024,
        "candidate_dst": False,
        "sequence_status": "core_sequence_complete",
        "main_candidate_eligible": True,
        "later_structurally_complete": True,
        "later_engine_confirmed": True,
        "later_invalidated": False,
        "later_timed_out": False,
        "later_missing_data": False,
        "later_conflicted": False,
        "retrospective_terminal_class": "frozen_engine_confirmed",
        "has_causal_raw_fvg": True,
        "has_causal_qualified_fvg": True,
    }
    for variant in ORDER_BLOCK_VARIANTS:
        prefix = f"qualified_ob_{variant}"
        record[f"{prefix}_id"] = f"ob-{variant}"
        record[f"{prefix}_at"] = pd.Timestamp(
            "2024-01-02 13:21", tz=UTC
        )
        record[f"{prefix}_direction"] = 1
        record[f"{prefix}_variant"] = variant
        record[f"{prefix}_taxonomy"] = "ict_order_block"
        record[f"has_causal_ob_{variant}"] = True
    record.update(overrides)
    return record


def _one_minute_bars() -> pd.DataFrame:
    available = pd.date_range(
        "2024-01-02 11:00",
        "2024-01-02 17:30",
        freq="1min",
        tz=UTC,
    )
    close = 100.0 + np.arange(len(available)) * 0.01
    return pd.DataFrame(
        {
            "available_at": available,
            "open": close - 0.01,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
        }
    )


def test_configuration_preregisters_exact_primary_family() -> None:
    config = EarlyContextAnchorStudyConfig()
    config.validate()
    snapshot = config.snapshot()
    assert config.primary_anchors == PRIMARY_ANCHORS
    assert snapshot["registered_primary_comparisons"] == 60
    assert snapshot["event_cap"] is None
    assert snapshot["mapping_pooling"] is False
    assert snapshot["future_completion_main_conditioning"] is False
    assert config.cisd_enabled is False
    with pytest.raises(ValueError, match="cannot authorize"):
        replace(config, production_entry_authorization=True).validate()


def test_benjamini_hochberg_is_monotone_and_retains_nan() -> None:
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, np.nan])
    assert adjusted[:3] == pytest.approx([0.03, 0.04, 0.04])
    assert np.isnan(adjusted[3])


def test_anchor_inventory_separates_origin_fvg_ob_and_primary_anchors() -> None:
    config = EarlyContextAnchorStudyConfig()
    anchors, counts = build_anchor_event_table(
        pd.DataFrame([_sequence()]), config=config
    )
    types = set(anchors["anchor_type"])
    assert "named_liquidity_sweep" in types
    assert "htf_poi_interaction" not in types
    assert "first_aligned_raw_fvg_creation" in types
    assert "first_context_qualified_fvg_creation" in types
    for variant in ORDER_BLOCK_VARIANTS:
        assert f"qualifying_ob_{variant}_creation" in types
    assert set(PRIMARY_ANCHORS).issubset(types)
    assert not anchors.duplicated(["sequence_id", "anchor_type"]).any()
    assert counts["anchor_rows_deduplicated"] == 0
    assert not anchors["anchor_selected_using_later_completion"].any()
    assert anchors["anchor_causally_observable"].all()


def test_origin_anchors_remain_mutually_exclusive() -> None:
    config = EarlyContextAnchorStudyConfig()
    poi = _sequence(
        sequence_id="poi",
        candidate_source="poi_interaction",
        candidate_type="raw_fvg",
    )
    liquidity = _sequence(sequence_id="liquidity")
    anchors, _ = build_anchor_event_table(
        pd.DataFrame([poi, liquidity]), config=config
    )
    by_sequence = {
        key: set(group["anchor_type"])
        for key, group in anchors.groupby("sequence_id")
    }
    assert "htf_poi_interaction" in by_sequence["poi"]
    assert "named_liquidity_sweep" not in by_sequence["poi"]
    assert "named_liquidity_sweep" in by_sequence["liquidity"]
    assert "htf_poi_interaction" not in by_sequence["liquidity"]


def test_object_typed_valid_pmh_pml_prerequisites_remain_eligible(
    tmp_path: Path,
) -> None:
    e2 = tmp_path / "e2"
    e2.mkdir()
    rows = []
    for sequence_id, prerequisite in (
        ("valid", True),
        ("invalid", False),
    ):
        row = _sequence(
            sequence_id=sequence_id,
            candidate_source="pmh_pml_sweep",
            pmh_pml=True,
            pmh_pml_prerequisites_met=prerequisite,
            population="e2_uncapped",
            candidate_invalidated_at=pd.NaT,
            refinement_array_invalidated_at=pd.NaT,
            engine_state="awaiting_reaction",
            engine_selected_reaction_confirmed=False,
        )
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame["pmh_pml_prerequisites_met"] = frame[
        "pmh_pml_prerequisites_met"
    ].astype(object)
    frame.to_parquet(e2 / "candidate_sequences.parquet", index=False)
    result = load_uncapped_sequences(e2).set_index("sequence_id")
    assert bool(result.at["valid", "main_candidate_eligible"])
    assert not bool(result.at["invalid", "main_candidate_eligible"])


def test_independent_arrays_use_causal_availability_not_later_flags(
    tmp_path: Path,
) -> None:
    config = EarlyContextAnchorStudyConfig()
    e1 = tmp_path / "e1"
    e1.mkdir()
    base = {
        "mapping_variant": "1h_5m",
        "timeframe": "5min",
        "direction": 1,
        "created_at": pd.Timestamp("2024-01-02 13:00", tz=UTC),
        "interacted_at": pd.NaT,
        "invalidated_at": pd.NaT,
    }
    fvg = pd.DataFrame(
        [
            {
                **base,
                "event_id": "raw-before-confirmations",
                "available_at": pd.Timestamp(
                    "2024-01-02 13:05", tz=UTC
                ),
                "variant": "three_candle_wick_nonoverlap",
                "taxonomy": "ict_fair_value_gap",
            },
            {
                **base,
                "event_id": "qualified-after-confirmations",
                "available_at": pd.Timestamp(
                    "2024-01-02 13:16", tz=UTC
                ),
                "variant": "three_candle_wick_nonoverlap",
                "taxonomy": "ict_fair_value_gap",
            },
        ]
    )
    obs = []
    for minute, variant in enumerate(ORDER_BLOCK_VARIANTS, start=16):
        obs.append(
            {
                **base,
                "event_id": f"ob-{variant}",
                "available_at": pd.Timestamp(
                    f"2024-01-02 13:{minute}", tz=UTC
                ),
                "variant": variant,
                "taxonomy": "ict_order_block",
            }
        )
    fvg.to_parquet(e1 / "fvg_event_statistics.parquet", index=False)
    pd.DataFrame(obs).to_parquet(
        e1 / "order_block_event_statistics.parquet", index=False
    )
    source = pd.DataFrame(
        [
            {
                key: value
                for key, value in _sequence().items()
                if not key.startswith("raw_fvg")
                and not key.startswith("qualified_fvg")
                and not key.startswith("qualified_ob_")
                and not key.startswith("has_causal_")
            }
        ]
    )
    result = attach_independent_array_anchors(
        source, e1_output=e1, config=config
    ).iloc[0]
    assert result["raw_fvg_id"] == "raw-before-confirmations"
    assert result["qualified_fvg_id"] == "qualified-after-confirmations"
    for variant in ORDER_BLOCK_VARIANTS:
        assert result[f"qualified_ob_{variant}_id"] == f"ob-{variant}"


def test_forward_outcomes_are_downstream_descriptive_and_use_override() -> None:
    config = EarlyContextAnchorStudyConfig()
    anchors, _ = build_anchor_event_table(
        pd.DataFrame([_sequence()]), config=config
    )
    interaction = anchors[
        anchors["anchor_type"].eq(
            "refinement_array_first_interaction"
        )
    ]
    outcomes = calculate_forward_outcomes(
        interaction, _one_minute_bars(), config=config
    )
    row = outcomes[outcomes["horizon"].eq("5m")].iloc[0]
    assert row["anchor_price"] == pytest.approx(100.25)
    assert row["outcome_is_downstream_only"]
    assert not row["pnl_calculated"]
    assert not row["entry_assumed"]
    assert row["observed_until"] > row["anchor_at"]


def test_latency_keeps_negative_timestamp_order_as_auditable_data() -> None:
    config = EarlyContextAnchorStudyConfig()
    sequence = _sequence(
        refinement_interacted_at=pd.Timestamp(
            "2024-01-02 13:35", tz=UTC
        ),
        d005_reaction_confirmed_at=pd.Timestamp(
            "2024-01-02 13:30", tz=UTC
        ),
    )
    anchors, _ = build_anchor_event_table(
        pd.DataFrame([sequence]), config=config
    )
    latency = build_latency_decay(anchors, _one_minute_bars())
    row = latency[
        latency["latency_stage"].eq(
            "first_interaction_to_reaction_confirmed"
        )
    ].iloc[0]
    assert row["elapsed_minutes"] == -5
    assert not row["timestamp_order_valid"]


def test_primary_comparisons_register_empty_cells_without_mapping_pooling() -> None:
    config = replace(
        EarlyContextAnchorStudyConfig(), bootstrap_resamples=500
    )
    rows = []
    for index in range(4):
        rows.append(
            {
                "sequence_id": f"s{index}",
                "anchor_type": "candidate_context_creation",
                "mapping_variant": "1h_5m",
                "outcome": "reversal",
                "horizon": "60m",
                "signed_forward_movement": float(index - 1),
                "anchor_year": 2024,
                "direction": 1 if index % 2 else -1,
                "anchor_causally_observable": True,
            }
        )
    result = build_primary_comparisons(
        pd.DataFrame(rows), config=config
    )
    assert len(result) == 60
    assert result["comparison_family_size"].eq(60).all()
    assert not result["mapping_pooled"].any()
    assert not result["future_completion_conditioned"].any()


def test_direction_family_audit_preserves_frozen_semantics_and_limits() -> None:
    liquidity = _sequence(
        candidate_source="liquidity_sweep",
        candidate_taxonomy="sell_side_liquidity",
        candidate_direction=1,
        liquidity_raid_direction=-1,
        liquidity_expected_direction=1,
        pre_candidate_child_direction=-1,
        outcome="reversal",
    )
    continuation = _sequence(
        sequence_id="continuation",
        candidate_source="poi_interaction",
        candidate_type="raw_fvg",
        candidate_direction=1,
        parent_direction=-1,
        pre_candidate_child_direction=0,
        outcome="continuation",
        parent_candidate_aligned=False,
    )
    audit, summary = build_direction_family_audit(
        pd.DataFrame([liquidity, continuation])
    )
    assert audit["frozen_outcome_rule_passed"].all()
    reversal = audit[audit["outcome"].eq("reversal")].iloc[0]
    assert reversal["reversal_liquidity_moves_away_from_sweep"]
    continued = audit[audit["outcome"].eq("continuation")].iloc[0]
    assert (
        continued["continuation_parent_order_flow_status"] == "opposed"
    )
    assert not continued[
        "poi_rejection_vector_independently_verifiable"
    ]
    assert summary["sequence_count"].sum() == 2


def test_hard_classification_returns_exactly_category_five_when_no_signal() -> None:
    config = replace(
        EarlyContextAnchorStudyConfig(), bootstrap_resamples=500
    )
    primary = pd.DataFrame(
        [
            {
                "anchor_type": anchor,
                "sample_count": 10,
                "mean_positive": False,
                "median_consistent": False,
                "fdr_significant": False,
                "survives_all_stability_criteria": False,
            }
            for anchor in PRIMARY_ANCHORS
        ]
    )
    criteria = pd.DataFrame(
        [
            {"anchor_type": anchor, "broadly_stable": False}
            for anchor in PRIMARY_ANCHORS
        ]
    )
    forward = pd.DataFrame(
        [
            {
                "sequence_id": "s1",
                "anchor_type": "candidate_context_creation",
                "horizon": "60m",
                "signed_forward_movement": -1.0,
                "later_engine_confirmed": False,
            }
        ]
    )
    classification = classify_result(
        primary=primary,
        criteria=criteria,
        forward=forward,
        config=config,
    )
    assert classification["primary_classification_id"] == 5
    assert isinstance(
        classification["secondary_classifications"], list
    )


def test_output_path_is_isolated_from_all_protected_studies() -> None:
    config = EarlyContextAnchorStudyConfig()
    assert "D005_E3_EARLY_CONTEXT_ANCHOR_STUDY" not in {
        config.d005_output,
        config.e1_output,
        config.e2_output,
    }
