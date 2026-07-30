from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from research.d005_e4_1h_5m_reversal_replication.analysis import (
    build_paired_refinement_outcomes,
    build_secondary_tests,
    build_temporal_contribution_audit,
    classify_replication,
)
from research.d005_e4_1h_5m_reversal_replication.config import (
    ReversalReplicationConfig,
)
from research.d005_e4_1h_5m_reversal_replication.selection import (
    build_causal_audit,
    build_paired_anchor_table,
    future_mutation_invariant,
    select_primary_anchors,
    select_refinement_anchors,
)


UTC = "UTC"


def _anchor(
    sequence_id: str = "s1",
    **overrides: object,
) -> dict[str, object]:
    record: dict[str, object] = {
        "sequence_id": sequence_id,
        "mapping_variant": "1h_5m",
        "outcome": "reversal",
        "anchor_type": "displacement_confirmation",
        "anchor_event_id": f"event-{sequence_id}",
        "anchor_id": f"anchor-{sequence_id}",
        "anchor_at": pd.Timestamp("2024-01-02 13:15", tz=UTC),
        "direction": 1,
        "direction_source": "displacement_direction",
        "main_scope_eligible": True,
        "anchor_causally_observable": True,
        "anchor_selected_using_later_completion": False,
        "volatility_regime": "normal",
        "volatility_ratio": 1.0,
        "anchor_session": "ny_observation",
        "candidate_source": "poi_interaction",
        "pmh_pml": False,
        "later_engine_confirmed": False,
        "later_invalidated": False,
        "later_timed_out": False,
        "later_conflicted": False,
    }
    record.update(overrides)
    return record


def _outcome_rows(
    anchor_type: str,
    *,
    sequence_prefix: str = "s",
) -> pd.DataFrame:
    rows = []
    for index, horizon in enumerate(
        (
            "5m",
            "15m",
            "30m",
            "60m",
            "120m",
            "ny_noon",
            "trading_day_close",
        )
    ):
        rows.append(
            {
                "sequence_id": f"{sequence_prefix}{index}",
                "anchor_type": anchor_type,
                "horizon": horizon,
                "replication_role": "rolling_origin_validation",
                "signed_forward_movement": 1.0 + index / 10,
                "win": True,
                "mfe": 2.0,
                "mae": 1.0,
                "mfe_mae_ratio": 2.0,
                "adverse_before_favorable": False,
                "time_to_mfe_minutes": 10.0,
                "time_to_mae_minutes": 5.0,
            }
        )
    return pd.DataFrame(rows)


def test_config_freezes_non_independent_rolling_origin_design() -> None:
    config = ReversalReplicationConfig()
    config.validate()
    snapshot = config.snapshot()
    assert snapshot["hard_category_one_possible"] is False
    assert snapshot["secondary_confirmatory_family_size"] == 13
    assert snapshot["mapping_pooling"] is False
    assert config.primary_mapping == "1h_5m"
    assert config.primary_horizon == "60m"
    with pytest.raises(ValueError, match="No independent"):
        replace(config, independent_replication=True).validate()


def test_primary_selection_is_causal_unique_and_first_by_time() -> None:
    config = ReversalReplicationConfig()
    rows = [
        _anchor(
            anchor_id="later",
            anchor_event_id="later",
            anchor_at=pd.Timestamp("2024-01-02 13:20", tz=UTC),
        ),
        _anchor(
            anchor_id="first",
            anchor_event_id="first",
            anchor_at=pd.Timestamp("2024-01-02 13:15", tz=UTC),
        ),
        _anchor(
            "wrong-map",
            mapping_variant="1h_5m_optional_1m",
        ),
        _anchor(
            "conditioned",
            anchor_selected_using_later_completion=True,
        ),
        _anchor("neutral", direction=0),
    ]
    selected, counts = select_primary_anchors(
        pd.DataFrame(rows), config=config
    )
    assert selected["sequence_id"].tolist() == ["s1"]
    assert selected.iloc[0]["anchor_id"] == "first"
    assert counts["primary_anchor_rows_before_deduplication"] == 2
    assert counts["primary_anchor_rows_deduplicated"] == 1


def test_future_fields_cannot_mutate_primary_selection() -> None:
    config = ReversalReplicationConfig()
    frame = pd.DataFrame([_anchor(), _anchor("s2")])
    assert future_mutation_invariant(frame, config=config)


def test_2021_is_calibration_and_later_years_are_validation() -> None:
    config = ReversalReplicationConfig()
    frame = pd.DataFrame(
        [
            _anchor(
                "s2021",
                anchor_at=pd.Timestamp("2021-06-01 12:00", tz=UTC),
            ),
            _anchor(
                "s2025",
                anchor_at=pd.Timestamp("2025-06-01 12:00", tz=UTC),
            ),
        ]
    )
    selected, _ = select_primary_anchors(frame, config=config)
    roles = selected.set_index("sequence_id")["replication_role"]
    assert roles["s2021"] == "calibration_prefix_only"
    assert roles["s2025"] == "rolling_origin_validation"
    assert (
        selected.set_index("sequence_id").at["s2025", "replication_fold"]
        == "RO-2025"
    )


def test_refinement_is_selected_only_for_frozen_primary_ids() -> None:
    config = ReversalReplicationConfig()
    refinements = pd.DataFrame(
        [
            _anchor(
                "s1",
                anchor_type="refinement_array_creation",
                anchor_id="ref-s1",
            ),
            _anchor(
                "not-primary",
                anchor_type="refinement_array_creation",
                anchor_id="ref-other",
            ),
        ]
    )
    selected = select_refinement_anchors(
        refinements, pd.Series(["s1"]), config=config
    )
    assert selected["sequence_id"].tolist() == ["s1"]


def test_paired_anchor_table_does_not_duplicate_sequences() -> None:
    config = ReversalReplicationConfig()
    primary, _ = select_primary_anchors(
        pd.DataFrame([_anchor()]), config=config
    )
    refinement = pd.DataFrame(
        [
            _anchor(
                anchor_type="refinement_array_creation",
                anchor_id="ref",
                anchor_at=pd.Timestamp("2024-01-02 13:20", tz=UTC),
            )
        ]
    )
    refinement = select_refinement_anchors(
        refinement, primary["sequence_id"], config=config
    )
    paired = build_paired_anchor_table(primary, refinement)
    assert paired["sequence_id"].is_unique
    assert paired.iloc[0]["refinement_subsequently_present"]
    assert paired.iloc[0]["displacement_to_refinement_minutes"] == 5


def test_secondary_family_has_exactly_thirteen_tests_and_excludes_primary() -> None:
    config = replace(
        ReversalReplicationConfig(), bootstrap_resamples=1000
    )
    displacement = _outcome_rows("displacement_confirmation")
    refinement = _outcome_rows(
        "refinement_array_creation", sequence_prefix="r"
    )
    result = build_secondary_tests(
        displacement, refinement, config=config
    )
    assert len(result) == 13
    assert not (
        result["anchor_type"].eq("displacement_confirmation")
        & result["horizon"].eq("60m")
    ).any()
    assert (
        result["anchor_type"].eq("refinement_array_creation")
        & result["horizon"].eq("60m")
    ).any()
    assert result["comparison_family_size"].eq(13).all()


def test_causal_audit_requires_closed_bars_and_aligned_directions() -> None:
    stamp = pd.Timestamp("2024-01-02 13:15", tz=UTC)
    eligible = pd.DataFrame(
        [
            {
                "sequence_id": "s1",
                "replication_role": "rolling_origin_validation",
                "replication_fold": "RO-2024",
                "candidate_at": stamp - pd.Timedelta(minutes=30),
                "mss_created_at": stamp - pd.Timedelta(minutes=15),
                "mss_confirmed_at": stamp - pd.Timedelta(minutes=10),
                "displacement_created_at": stamp
                - pd.Timedelta(minutes=5),
                "displacement_confirmed_at": stamp,
                "confirmation_event_created_at": stamp
                - pd.Timedelta(minutes=5),
                "confirmation_event_available_at": stamp,
                "anchor_at": stamp,
                "candidate_direction": 1,
                "mss_direction": 1,
                "displacement_direction": 1,
                "direction": 1,
                "confirmation_event_direction": 1,
                "main_scope_eligible": True,
                "anchor_causally_observable": True,
                "anchor_selected_using_later_completion": False,
            }
        ]
    )
    for column in (
        "candidate_at",
        "mss_created_at",
        "mss_confirmed_at",
        "displacement_created_at",
        "displacement_confirmed_at",
        "confirmation_event_created_at",
        "confirmation_event_available_at",
        "anchor_at",
    ):
        eligible[column] = pd.Series(
            eligible[column], dtype="datetime64[us, UTC]"
        )
    timeframes = {
        "1min": pd.DataFrame(
            {
                "available_at": pd.Series(
                    [stamp], dtype="datetime64[ns, UTC]"
                )
            }
        ),
        "5min": pd.DataFrame(
            {
                "available_at": pd.Series(
                    [stamp], dtype="datetime64[ns, UTC]"
                )
            }
        ),
    }
    audit = build_causal_audit(
        eligible, timeframes=timeframes, selection_invariant=True
    )
    assert audit.iloc[0]["all_causal_invariants_pass"]


def test_causal_direction_mismatch_fails_audit() -> None:
    stamp = pd.Timestamp("2024-01-02 13:15", tz=UTC)
    eligible = pd.DataFrame(
        [
            {
                "sequence_id": "s1",
                "replication_role": "rolling_origin_validation",
                "replication_fold": "RO-2024",
                "candidate_at": stamp,
                "mss_created_at": stamp,
                "mss_confirmed_at": stamp,
                "displacement_created_at": stamp,
                "displacement_confirmed_at": stamp,
                "confirmation_event_created_at": stamp,
                "confirmation_event_available_at": stamp,
                "anchor_at": stamp,
                "candidate_direction": 1,
                "mss_direction": -1,
                "displacement_direction": 1,
                "direction": 1,
                "confirmation_event_direction": 1,
                "main_scope_eligible": True,
                "anchor_causally_observable": True,
                "anchor_selected_using_later_completion": False,
            }
        ]
    )
    timeframes = {
        "1min": pd.DataFrame({"available_at": [stamp]}),
        "5min": pd.DataFrame({"available_at": [stamp]}),
    }
    audit = build_causal_audit(
        eligible, timeframes=timeframes, selection_invariant=True
    )
    assert not audit.iloc[0]["all_causal_invariants_pass"]
    assert not audit.iloc[0]["directions_known_and_aligned"]


def test_paired_refinement_difference_uses_unique_sequence_pairs() -> None:
    config = replace(
        ReversalReplicationConfig(), bootstrap_resamples=1000
    )
    paired = pd.DataFrame(
        [
            {
                "sequence_id": "s1",
                "replication_role": "rolling_origin_validation",
                "displacement_to_refinement_minutes": 5.0,
            },
            {
                "sequence_id": "s2",
                "replication_role": "rolling_origin_validation",
                "displacement_to_refinement_minutes": 10.0,
            },
        ]
    )
    displacement = pd.DataFrame(
        [
            {
                "sequence_id": key,
                "horizon": "60m",
                "signed_forward_movement": value,
                "mfe": 2.0,
                "mae": 1.0,
            }
            for key, value in (("s1", 1.0), ("s2", 2.0))
        ]
    )
    refinement = pd.DataFrame(
        [
            {
                "sequence_id": key,
                "horizon": "60m",
                "signed_forward_movement": value,
                "mfe": 2.0,
                "mae": 1.0,
            }
            for key, value in (("s1", 0.5), ("s2", 1.5))
        ]
    )
    outcomes, summary = build_paired_refinement_outcomes(
        paired,
        displacement,
        refinement,
        config=config,
    )
    assert outcomes["sequence_id"].is_unique
    assert summary.iloc[0]["paired_sequence_count"] == 2
    assert (
        summary.iloc[0][
            "mean_refinement_minus_displacement_signed_60m"
        ]
        == pytest.approx(-0.5)
    )


def test_temporal_contribution_audit_is_descriptive_only() -> None:
    rolling = pd.DataFrame(
        [
            {
                "replication_fold": "RO-2022",
                "anchor_year": 2022,
                "sample_count": 100,
                "mean_signed_movement": 0.1,
            },
            {
                "replication_fold": "RO-2023",
                "anchor_year": 2023,
                "sample_count": 100,
                "mean_signed_movement": 0.9,
            },
        ]
    )
    audit = build_temporal_contribution_audit(rolling)
    shares = audit.set_index("replication_fold")[
        "absolute_net_block_contribution_share"
    ]
    assert shares["RO-2022"] == pytest.approx(0.1)
    assert shares["RO-2023"] == pytest.approx(0.9)
    assert not audit["primary_rule_modified_by_this_audit"].any()


def _classification_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    primary_result = pd.DataFrame(
        [
            {
                "sample_count": 4,
                "mean_signed_movement": 1.0,
                "mean_ci_lower": 0.1,
                "mean_ci_upper": 1.9,
                "mean_mfe_to_mean_mae": 2.0,
                "median_mfe_mae_ratio": 2.0,
            }
        ]
    )
    primary_outcomes = pd.DataFrame(
        [
            {
                "sequence_id": f"s{index}",
                "replication_role": "rolling_origin_validation",
                "replication_fold": f"RO-202{index + 2}",
                "horizon": "60m",
                "signed_forward_movement": float(index + 1),
                "later_engine_confirmed": False,
            }
            for index in range(4)
        ]
    )
    temporal = pd.DataFrame(
        [
            {
                "sample_count": 1,
                "mean_signed_movement": 1.0,
            }
            for _ in range(4)
        ]
    )
    direction = pd.DataFrame(
        [
            {
                "sample_count": 2,
                "mean_ci_upper": 2.0,
            },
            {
                "sample_count": 2,
                "mean_ci_upper": 2.0,
            },
        ]
    )
    causal = pd.DataFrame(
        [{"all_causal_invariants_pass": True}]
    )
    return (
        primary_result,
        primary_outcomes,
        temporal,
        direction,
        causal,
    )


def test_overlap_forces_hard_category_five_even_when_internal_signal_positive() -> None:
    config = replace(
        ReversalReplicationConfig(),
        minimum_validation_n=1,
        minimum_block_n=1,
        minimum_direction_n=1,
        bootstrap_resamples=1000,
    )
    primary, outcomes, temporal, direction, causal = (
        _classification_inputs()
    )
    result = classify_replication(
        primary_result=primary,
        primary_outcomes=outcomes,
        temporal=temporal,
        direction=direction,
        causal_audit=causal,
        reproducibility_defect=False,
        config=config,
    )
    assert result["primary_classification_id"] == 5
    assert not result["independent_replication_available"]


def test_reproducibility_defect_overrides_independence_category() -> None:
    config = replace(
        ReversalReplicationConfig(), bootstrap_resamples=1000
    )
    primary, outcomes, temporal, direction, causal = (
        _classification_inputs()
    )
    result = classify_replication(
        primary_result=primary,
        primary_outcomes=outcomes,
        temporal=temporal,
        direction=direction,
        causal_audit=causal,
        reproducibility_defect=True,
        config=config,
    )
    assert result["primary_classification_id"] == 6


def test_output_directory_name_is_isolated() -> None:
    config = ReversalReplicationConfig()
    output = "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION"
    assert output not in {
        config.d005_output,
        config.e1_output,
        config.e2_output,
        config.e3_output,
    }
