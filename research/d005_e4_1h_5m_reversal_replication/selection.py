"""Outcome-independent E4 cohort selection and causal audit."""

from __future__ import annotations

import json
from typing import Mapping

import numpy as np
import pandas as pd

from .config import ReversalReplicationConfig


SELECTION_KEY = ["sequence_id", "anchor_type"]


def _parameters(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def select_primary_anchors(
    anchor_events: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Select only frozen causal columns; never inspect price outcomes."""

    required = [
        "sequence_id",
        "mapping_variant",
        "outcome",
        "anchor_type",
        "anchor_event_id",
        "anchor_id",
        "anchor_at",
        "direction",
        "direction_source",
        "main_scope_eligible",
        "anchor_causally_observable",
        "anchor_selected_using_later_completion",
        "volatility_regime",
        "volatility_ratio",
        "anchor_session",
        "candidate_source",
        "pmh_pml",
    ]
    frame = anchor_events[required].copy()
    frame["anchor_at"] = pd.to_datetime(
        frame["anchor_at"], utc=True, errors="coerce"
    )
    frame = frame[
        frame["mapping_variant"].eq(config.primary_mapping)
        & frame["outcome"].eq(config.primary_outcome)
        & frame["anchor_type"].eq(config.primary_anchor)
        & frame["main_scope_eligible"].fillna(False).astype(bool)
        & frame["anchor_causally_observable"].fillna(False).astype(bool)
        & ~frame["anchor_selected_using_later_completion"]
        .fillna(True)
        .astype(bool)
        & frame["direction"].ne(0)
        & frame["anchor_at"].notna()
    ].copy()
    before = len(frame)
    frame = (
        frame.sort_values(
            [
                "sequence_id",
                "anchor_at",
                "anchor_event_id",
                "anchor_id",
            ],
            kind="mergesort",
        )
        .drop_duplicates("sequence_id", keep="first")
        .reset_index(drop=True)
    )
    local = frame["anchor_at"].dt.tz_convert(config.timezone)
    frame["anchor_year"] = local.dt.year
    frame["replication_role"] = np.where(
        frame["anchor_year"].isin(config.validation_years),
        "rolling_origin_validation",
        "calibration_prefix_only",
    )
    frame["replication_fold"] = frame["anchor_year"].map(
        {
            year: f"RO-{year}"
            for year in config.validation_years
        }
    ).fillna("CAL-2021")
    return frame, {
        "primary_anchor_rows_before_deduplication": before,
        "primary_anchor_rows_after_deduplication": len(frame),
        "primary_anchor_rows_deduplicated": before - len(frame),
    }


def build_sample_selection(
    sequences: pd.DataFrame,
    primary_anchors: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    """Return one auditable inclusion decision for every E3 sequence."""

    columns = [
        "sequence_id",
        "population",
        "mapping_variant",
        "outcome",
        "candidate_at",
        "candidate_direction",
        "candidate_source",
        "pmh_pml",
        "sequence_status",
        "main_candidate_eligible",
    ]
    result = sequences[columns].drop_duplicates("sequence_id").copy()
    selected = primary_anchors[
        [
            "sequence_id",
            "anchor_id",
            "anchor_at",
            "direction",
            "replication_role",
            "replication_fold",
        ]
    ].rename(
        columns={
            "anchor_id": "selected_displacement_anchor_id",
            "anchor_at": "selected_displacement_at",
            "direction": "selected_direction",
        }
    )
    result = result.merge(selected, on="sequence_id", how="left")
    result["mapping_eligible"] = result["mapping_variant"].eq(
        config.primary_mapping
    )
    result["frozen_reversal_eligible"] = result["outcome"].eq(
        config.primary_outcome
    )
    result["causal_displacement_eligible"] = result[
        "selected_displacement_anchor_id"
    ].notna()
    result["selected_primary_sequence"] = (
        result["mapping_eligible"]
        & result["frozen_reversal_eligible"]
        & result["causal_displacement_eligible"]
    )
    result["selection_reason"] = np.select(
        [
            ~result["mapping_eligible"],
            ~result["frozen_reversal_eligible"],
            ~result["causal_displacement_eligible"],
        ],
        [
            "excluded_nonprimary_mapping",
            "excluded_nonreversal",
            "excluded_no_eligible_causal_displacement",
        ],
        default="included_frozen_primary_cohort",
    )
    return result


def build_eligible_sequences(
    sequences: pd.DataFrame,
    primary_anchors: pd.DataFrame,
    confirmations: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    """Attach only causal sequence evidence and preregistered strength fields."""

    sequence_columns = [
        "sequence_id",
        "population",
        "candidate_id",
        "candidate_at",
        "candidate_direction",
        "candidate_source",
        "candidate_type",
        "candidate_variant",
        "candidate_taxonomy",
        "parent_direction",
        "pre_candidate_child_direction",
        "mss_id",
        "mss_confirmed_at",
        "mss_created_at",
        "mss_direction",
        "displacement_id",
        "displacement_confirmed_at",
        "displacement_created_at",
        "displacement_direction",
        "refinement_id",
        "refinement_created_at",
        "d005_reaction_confirmed_at",
        "candidate_invalidated_at",
        "candidate_timeout_at",
        "refinement_array_invalidated_at",
        "sequence_status",
        "main_candidate_eligible",
        "later_engine_confirmed",
        "later_invalidated",
        "later_timed_out",
        "later_conflicted",
        "retrospective_terminal_class",
        "pmh_pml",
        "pmh_pml_prerequisites_met",
    ]
    result = primary_anchors.merge(
        sequences[sequence_columns].drop_duplicates("sequence_id"),
        on="sequence_id",
        how="left",
        validate="one_to_one",
    )
    displacement = confirmations[
        confirmations["event_type"].eq("displacement")
        & confirmations["timeframe"].eq("5min")
    ][
        [
            "event_id",
            "created_at",
            "available_at",
            "direction",
            "parameters",
        ]
    ].drop_duplicates("event_id")
    displacement = displacement.rename(
        columns={
            "event_id": "displacement_confirmation_event_id",
            "created_at": "confirmation_event_created_at",
            "available_at": "confirmation_event_available_at",
            "direction": "confirmation_event_direction",
            "parameters": "displacement_parameters",
        }
    )
    result = result.merge(
        displacement,
        left_on="displacement_id",
        right_on="displacement_confirmation_event_id",
        how="left",
        validate="many_to_one",
    )
    parsed = result["displacement_parameters"].map(_parameters)
    for field in (
        "true_range_atr",
        "body_range_fraction",
        "immediate_retracement_fraction",
        "prior_atr",
    ):
        result[field] = pd.to_numeric(
            parsed.map(lambda item: item.get(field)), errors="coerce"
        )
    result["candidate_to_displacement_minutes"] = (
        pd.to_datetime(result["anchor_at"], utc=True)
        - pd.to_datetime(result["candidate_at"], utc=True)
    ).dt.total_seconds() / 60.0
    result["displacement_strength_bin"] = pd.cut(
        result["true_range_atr"],
        bins=[-np.inf, 1.25, 1.75, 2.50, np.inf],
        labels=[
            "below_frozen_minimum",
            "1.25_to_1.75",
            "1.75_to_2.50",
            "2.50_or_more",
        ],
        right=False,
    ).astype(str)
    result.loc[
        result["true_range_atr"].isna(), "displacement_strength_bin"
    ] = "unavailable"
    result["candidate_displacement_latency_bin"] = pd.cut(
        result["candidate_to_displacement_minutes"],
        bins=[-np.inf, 0.0, 60.0, 180.0, 360.0, np.inf],
        labels=[
            "negative",
            "0_to_60",
            "60_to_180",
            "180_to_360",
            "360_or_more",
        ],
        right=False,
    ).astype(str)
    result.loc[
        result["candidate_to_displacement_minutes"].isna(),
        "candidate_displacement_latency_bin",
    ] = "unavailable"
    return result


def select_refinement_anchors(
    anchor_events: pd.DataFrame,
    primary_ids: pd.Series,
    *,
    config: ReversalReplicationConfig,
) -> pd.DataFrame:
    """Select refinement only after primary IDs are frozen."""

    frame = anchor_events[
        anchor_events["sequence_id"].isin(set(primary_ids.astype(str)))
        & anchor_events["mapping_variant"].eq(config.primary_mapping)
        & anchor_events["outcome"].eq(config.primary_outcome)
        & anchor_events["anchor_type"].eq(config.secondary_anchor)
        & anchor_events["anchor_causally_observable"].fillna(False)
        & ~anchor_events["anchor_selected_using_later_completion"].fillna(True)
        & anchor_events["direction"].ne(0)
    ].copy()
    return (
        frame.sort_values(
            ["sequence_id", "anchor_at", "anchor_event_id", "anchor_id"],
            kind="mergesort",
        )
        .drop_duplicates("sequence_id", keep="first")
        .reset_index(drop=True)
    )


def build_paired_anchor_table(
    primary: pd.DataFrame,
    refinement: pd.DataFrame,
) -> pd.DataFrame:
    left = primary[
        [
            "sequence_id",
            "anchor_id",
            "anchor_at",
            "direction",
            "replication_role",
            "replication_fold",
            "anchor_year",
        ]
    ].rename(
        columns={
            "anchor_id": "displacement_anchor_id",
            "anchor_at": "displacement_anchor_at",
            "direction": "displacement_direction",
        }
    )
    right = refinement[
        ["sequence_id", "anchor_id", "anchor_at", "direction"]
    ].rename(
        columns={
            "anchor_id": "refinement_anchor_id",
            "anchor_at": "refinement_anchor_at",
            "direction": "refinement_direction",
        }
    )
    result = left.merge(
        right, on="sequence_id", how="left", validate="one_to_one"
    )
    result["refinement_subsequently_present"] = result[
        "refinement_anchor_id"
    ].notna()
    result["displacement_to_refinement_minutes"] = (
        pd.to_datetime(result["refinement_anchor_at"], utc=True)
        - pd.to_datetime(result["displacement_anchor_at"], utc=True)
    ).dt.total_seconds() / 60.0
    return result


def build_causal_audit(
    eligible: pd.DataFrame,
    *,
    timeframes: Mapping[str, pd.DataFrame],
    selection_invariant: bool,
) -> pd.DataFrame:
    result = eligible.copy()
    timestamp_columns = (
        "candidate_at",
        "mss_created_at",
        "mss_confirmed_at",
        "displacement_created_at",
        "displacement_confirmed_at",
        "confirmation_event_created_at",
        "confirmation_event_available_at",
        "anchor_at",
    )
    for column in timestamp_columns:
        result[column] = pd.to_datetime(
            result[column], utc=True, errors="coerce"
        )
    anchor = result["anchor_at"]
    result["evaluation_at"] = anchor
    result["candidate_available_by_anchor"] = result["candidate_at"].le(anchor)
    result["mss_created_by_anchor"] = result["mss_created_at"].le(anchor)
    result["mss_available_by_anchor"] = result["mss_confirmed_at"].le(anchor)
    result["displacement_created_by_anchor"] = result[
        "displacement_created_at"
    ].le(anchor)
    result["displacement_available_equals_anchor"] = result[
        "displacement_confirmed_at"
    ].eq(anchor)
    result["confirmation_inventory_available_equals_anchor"] = result[
        "confirmation_event_available_at"
    ].eq(anchor)
    result["available_at_le_evaluation_at"] = result[
        "confirmation_event_available_at"
    ].le(result["evaluation_at"])
    five_available = set(
        pd.DatetimeIndex(
            pd.to_datetime(timeframes["5min"]["available_at"], utc=True)
        )
        .as_unit("ns")
        .asi8
    )
    one_available = pd.DatetimeIndex(
        pd.to_datetime(timeframes["1min"]["available_at"], utc=True)
    ).as_unit("ns").asi8
    anchor_ns = pd.DatetimeIndex(anchor).as_unit("ns").asi8
    result["completed_5m_bar_available"] = [
        value in five_available for value in anchor_ns
    ]
    result["completed_1m_bar_available"] = [
        int(np.searchsorted(one_available, value, side="right")) > 0
        for value in anchor_ns
    ]
    result["directions_known_and_aligned"] = (
        result["candidate_direction"].ne(0)
        & result["candidate_direction"].eq(result["mss_direction"])
        & result["candidate_direction"].eq(
            result["displacement_direction"]
        )
        & result["candidate_direction"].eq(result["direction"])
        & result["candidate_direction"].eq(
            result["confirmation_event_direction"]
        )
    )
    result["main_inclusion_not_future_conditioned"] = (
        result["main_scope_eligible"].fillna(False)
        & result["anchor_causally_observable"].fillna(False)
        & ~result["anchor_selected_using_later_completion"].fillna(True)
    )
    result["future_mutation_selection_invariant"] = selection_invariant
    checks = [
        "candidate_available_by_anchor",
        "mss_created_by_anchor",
        "mss_available_by_anchor",
        "displacement_created_by_anchor",
        "displacement_available_equals_anchor",
        "confirmation_inventory_available_equals_anchor",
        "available_at_le_evaluation_at",
        "completed_5m_bar_available",
        "completed_1m_bar_available",
        "directions_known_and_aligned",
        "main_inclusion_not_future_conditioned",
        "future_mutation_selection_invariant",
    ]
    result["all_causal_invariants_pass"] = result[checks].all(axis=1)
    return result[
        [
            "sequence_id",
            "replication_role",
            "replication_fold",
            "anchor_at",
            "evaluation_at",
            *checks,
            "all_causal_invariants_pass",
        ]
    ]


def future_mutation_invariant(
    anchor_events: pd.DataFrame,
    *,
    config: ReversalReplicationConfig,
) -> bool:
    baseline, _ = select_primary_anchors(anchor_events, config=config)
    mutated = anchor_events.copy()
    for column in (
        "later_engine_confirmed",
        "later_invalidated",
        "later_timed_out",
        "later_conflicted",
        "has_causal_qualified_fvg",
        "has_causal_ob_consecutive_block",
        "has_causal_ob_last_opposing_candle",
        "has_causal_ob_inefficiency_break_origin",
    ):
        if column in mutated:
            mutated[column] = ~mutated[column].fillna(False).astype(bool)
    for column in (
        "signed_forward_movement",
        "mfe",
        "mae",
    ):
        if column in mutated:
            mutated[column] = np.arange(len(mutated), dtype=float)
    changed, _ = select_primary_anchors(mutated, config=config)
    return baseline["sequence_id"].tolist() == changed[
        "sequence_id"
    ].tolist()
