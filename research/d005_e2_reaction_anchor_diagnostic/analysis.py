"""Descriptive summaries and hard decision classifications for D005_E2."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .directions import direction_mismatch_table


DIRECTION_FIELDS = (
    "parent_direction",
    "liquidity_raid_direction",
    "liquidity_expected_direction",
    "candidate_direction",
    "mss_direction",
    "displacement_direction",
    "refinement_direction",
    "final_d005_direction",
)


def _signature(record: dict[str, object]) -> str:
    payload = "|".join(
        str(record.get(column))
        for column in (
            "mapping_variant",
            "candidate_id",
            "mss_id",
            "displacement_id",
            "refinement_id",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def attach_evidence_signatures(
    sequences: pd.DataFrame,
) -> pd.DataFrame:
    result = sequences.copy()
    result["evidence_signature"] = [
        _signature(record) for record in result.to_dict("records")
    ]
    return result


def build_direction_audit(
    sequences: pd.DataFrame,
    forward: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return row-level directions and every pairwise mismatch table."""

    audit = sequences.copy()
    sixty = forward[forward["horizon"].eq("60m")].copy()
    sixty["realized_anchor_priority"] = sixty["anchor_type"].map(
        {
            "reaction_confirmed_close": 0,
            "refinement_creation_close": 1,
            "displacement_confirmation_close": 2,
            "mss_confirmation_close": 3,
            "poi_or_sweep_close": 4,
        }
    ).fillna(5)
    sixty = (
        sixty.sort_values(
            [
                "sequence_id",
                "population",
                "realized_anchor_priority",
            ],
            kind="mergesort",
        )
        .drop_duplicates(["sequence_id", "population"])
        [
            [
                "sequence_id",
                "population",
                "anchor_type",
                "signed_forward_movement",
            ]
        ]
    )
    audit = audit.merge(
        sixty.rename(
            columns={
                "anchor_type": "realized_anchor_60m",
                "signed_forward_movement": "realized_signed_movement_60m"
            }
        ),
        on=["sequence_id", "population"],
        how="left",
    )
    audit["realized_direction_60m"] = np.sign(
        audit["realized_signed_movement_60m"]
    ).fillna(0).astype(int)
    audit["sweep_expected_mapping_valid"] = (
        ~audit["candidate_type"].eq("liquidity_sweep")
        | audit["candidate_direction"].eq(
            audit["liquidity_expected_direction"]
        )
    )
    audit["sweep_raid_not_used_as_reaction"] = (
        ~audit["candidate_type"].eq("liquidity_sweep")
        | audit["candidate_direction"].ne(
            audit["liquidity_raid_direction"]
        )
    )
    audit["reversal_direction_valid"] = (
        ~audit["outcome"].eq("reversal")
        | ~audit["candidate_type"].eq("liquidity_sweep")
        | audit["candidate_direction"].eq(
            audit["liquidity_expected_direction"]
        )
    )
    audit["continuation_parent_alignment_valid"] = (
        ~audit["outcome"].eq("continuation")
        | audit["parent_direction"].eq(0)
        | audit["candidate_direction"].eq(audit["parent_direction"])
    )
    mismatches = direction_mismatch_table(
        audit,
        direction_columns=DIRECTION_FIELDS + ("realized_direction_60m",),
    )
    return audit, mismatches


def anchor_outcome_summary(forward: pd.DataFrame) -> pd.DataFrame:
    if forward.empty:
        return pd.DataFrame()
    threshold_columns = [
        column for column in forward if column.startswith("mfe_ge_")
    ]
    aggregations: dict[str, tuple[str, str]] = {
        "observations": ("sequence_id", "nunique"),
        "mean_signed_movement": ("signed_forward_movement", "mean"),
        "median_signed_movement": ("signed_forward_movement", "median"),
        "mean_mfe": ("mfe", "mean"),
        "mean_mae": ("mae", "mean"),
        "median_mfe_mae_ratio": ("mfe_mae_ratio", "median"),
        "adverse_before_favorable_rate": (
            "adverse_before_favorable",
            "mean",
        ),
        "median_time_to_mfe_minutes": ("time_to_mfe_minutes", "median"),
        "median_time_to_mae_minutes": ("time_to_mae_minutes", "median"),
    }
    for column in threshold_columns:
        aggregations[f"{column}_rate"] = (column, "mean")
    return (
        forward.groupby(
            [
                "population",
                "mapping_variant",
                "sequence_cohort",
                "outcome",
                "anchor_type",
                "horizon",
            ],
            dropna=False,
        )
        .agg(**aggregations)
        .reset_index()
    )


def principal_anchor_summary(forward: pd.DataFrame) -> pd.DataFrame:
    if forward.empty:
        return pd.DataFrame()
    aggregations: dict[str, tuple[str, str]] = {
        "observations": ("sequence_id", "nunique"),
        "mean_signed_movement": ("signed_forward_movement", "mean"),
        "median_signed_movement": (
            "signed_forward_movement",
            "median",
        ),
        "mean_mfe": ("mfe", "mean"),
        "mean_mae": ("mae", "mean"),
        "median_mfe_mae_ratio": ("mfe_mae_ratio", "median"),
        "adverse_before_favorable_rate": (
            "adverse_before_favorable",
            "mean",
        ),
        "median_time_to_mfe_minutes": (
            "time_to_mfe_minutes",
            "median",
        ),
        "median_time_to_mae_minutes": (
            "time_to_mae_minutes",
            "median",
        ),
    }
    for column in (
        item for item in forward if item.startswith("mfe_ge_")
    ):
        aggregations[f"{column}_rate"] = (column, "mean")
    return (
        forward.groupby(
            [
                "population",
                "sequence_cohort",
                "outcome",
                "anchor_type",
                "horizon",
            ],
            dropna=False,
        )
        .agg(**aggregations)
        .reset_index()
    )


def latency_summary(latency: pd.DataFrame) -> pd.DataFrame:
    if latency.empty:
        return pd.DataFrame()
    return (
        latency.groupby(
            [
                "population",
                "mapping_variant",
                "outcome",
                "latency_stage",
            ],
            dropna=False,
        )
        .agg(
            observations=("sequence_id", "nunique"),
            median_elapsed_minutes=("elapsed_minutes", "median"),
            negative_timestamp_order_count=(
                "timestamp_order_valid",
                lambda values: int((~values).sum()),
            ),
            mean_signed_stage_movement=(
                "signed_stage_movement",
                "mean",
            ),
            median_candidate_to_stage_mfe_consumed=(
                "candidate_to_stage_mfe_consumed",
                "median",
            ),
            median_candidate_to_stage_mae_consumed=(
                "candidate_to_stage_mae_consumed",
                "median",
            ),
            mean_candidate_to_stage_signed_movement=(
                "candidate_to_stage_signed_movement",
                "mean",
            ),
        )
        .reset_index()
    )


def sequence_funnel(sequences: pd.DataFrame) -> pd.DataFrame:
    return (
        sequences.groupby(
            ["population", "mapping_variant", "sequence_status"],
            dropna=False,
        )
        .size()
        .rename("sequence_count")
        .reset_index()
    )


def weekly_diagnostics(sequences: pd.DataFrame) -> pd.DataFrame:
    weekly = sequences[
        sequences["mapping_variant"].eq("weekly_4h_1h")
    ].copy()
    if weekly.empty:
        return pd.DataFrame()
    structural = (
        weekly.groupby(
            ["population", "sequence_status"], dropna=False
        )
        .agg(
            candidate_count=("sequence_id", "nunique"),
            parent_conflict_count=(
                "parent_direction",
                lambda values: int(
                    (
                        values.ne(0)
                        & values.ne(
                            weekly.loc[values.index, "candidate_direction"]
                        )
                    ).sum()
                ),
            ),
            missing_reaction_bars_count=(
                "observed_reaction_bars_to_timeout",
                lambda values: int(values.fillna(12).lt(12).sum()),
            ),
        )
        .reset_index()
    )
    structural["diagnostic_layer"] = "structural_reconstruction"
    engine = weekly[
        weekly["engine_evaluation_id"].notna()
    ].drop_duplicates("engine_evaluation_id")
    engine_rows: list[dict[str, object]] = []
    for record in engine.to_dict("records"):
        categories = [f"engine_state:{record['engine_state']}"]
        categories.extend(
            f"engine_gate:{reason}"
            for reason in (record.get("engine_no_trade_reasons") or [])
        )
        for category in categories:
            engine_rows.append(
                {
                    "population": "e2_uncapped",
                    "sequence_status": category,
                    "candidate_count": 1,
                    "parent_conflict_count": int(
                        category
                        in {
                            "engine_state:conflict",
                            "engine_gate:parent_child_direction_conflict",
                            "engine_gate:candidate_opposes_parent",
                        }
                    ),
                    "missing_reaction_bars_count": int(
                        category
                        == "engine_gate:missing_required_closed_bar_history"
                    ),
                    "diagnostic_layer": "frozen_engine_replay",
                }
            )
    if not engine_rows:
        return structural
    engine_summary = (
        pd.DataFrame.from_records(engine_rows)
        .groupby(
            ["population", "sequence_status", "diagnostic_layer"],
            dropna=False,
        )
        .sum(numeric_only=True)
        .reset_index()
    )
    return pd.concat(
        [structural, engine_summary],
        ignore_index=True,
        sort=False,
    )


def confirmation_cohort_summary(
    sequences: pd.DataFrame,
    forward: pd.DataFrame,
) -> pd.DataFrame:
    """Explode exact cohort labels and summarize their 60m completion anchor."""

    cohort_rows: list[dict[str, object]] = []
    for sequence in sequences.to_dict("records"):
        labels = {
            str(sequence["candidate_source"]),
            f"candidate:{sequence['candidate_type']}",
            f"candidate_variant:{sequence['candidate_variant']}",
            f"refinement:{sequence.get('refinement_type')}",
            f"refinement_variant:{sequence.get('refinement_variant')}",
            f"outcome:{sequence['outcome']}",
        }
        if sequence.get("pmh_pml"):
            labels.add("pmh_pml_sweep_sequence")
        if sequence["candidate_type"] == "liquidity_sweep":
            labels.add("liquidity_sweep_mss_displacement_refinement")
        else:
            labels.add("poi_mss_displacement_refinement")
        if (
            int(sequence.get("parent_direction", 0)) != 0
            and int(sequence.get("parent_direction", 0))
            == int(sequence.get("candidate_direction", 0))
        ):
            labels.add(f"parent_aligned_{sequence['outcome']}")
        for cohort in sorted(labels):
            cohort_rows.append(
                {
                    "sequence_id": sequence["sequence_id"],
                    "population": sequence["population"],
                    "mapping_variant": sequence["mapping_variant"],
                    "outcome": sequence["outcome"],
                    "cohort": cohort,
                }
            )
    cohorts = pd.DataFrame.from_records(cohort_rows)
    completion = forward[
        forward["horizon"].eq("60m")
        & (
            (
                forward["population"].eq("e1_capped")
                & forward["anchor_type"].eq("reaction_confirmed_close")
            )
            | (
                forward["population"].eq("e2_uncapped")
                & forward["anchor_type"].eq(
                    "refinement_creation_close"
                )
            )
        )
    ][
        [
            "sequence_id",
            "population",
            "signed_forward_movement",
            "mfe",
            "mae",
        ]
    ]
    cohorts = cohorts.merge(
        completion,
        on=["sequence_id", "population"],
        how="left",
    )
    return (
        cohorts.groupby(
            ["population", "cohort", "outcome"], dropna=False
        )
        .agg(
            sequence_count=("sequence_id", "nunique"),
            forward_observations=(
                "signed_forward_movement",
                "count",
            ),
            mean_signed_movement_60m=(
                "signed_forward_movement",
                "mean",
            ),
            median_signed_movement_60m=(
                "signed_forward_movement",
                "median",
            ),
            mean_mfe_60m=("mfe", "mean"),
            mean_mae_60m=("mae", "mean"),
        )
        .reset_index()
    )


def cap_sensitivity(
    sequences: pd.DataFrame,
    forward: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    capped = sequences[sequences["population"].eq("e1_capped")].copy()
    uncapped = sequences[
        sequences["population"].eq("e2_uncapped")
        & sequences["engine_selected_reaction_confirmed"].fillna(False)
    ].copy()
    capped_signatures = set(capped["evidence_signature"])
    uncapped_signatures = set(uncapped["evidence_signature"])
    membership_rows = []
    for population, frame in (("e1_capped", capped), ("e2_uncapped", uncapped)):
        other = (
            uncapped_signatures if population == "e1_capped" else capped_signatures
        )
        for record in frame.to_dict("records"):
            membership_rows.append(
                {
                    "population": population,
                    "sequence_id": record["sequence_id"],
                    "evidence_signature": record["evidence_signature"],
                    "membership": (
                        "included_in_both"
                        if record["evidence_signature"] in other
                        else "e1_capped_only"
                        if population == "e1_capped"
                        else "uncapped_only"
                    ),
                    "mapping_variant": record["mapping_variant"],
                    "direction": record["final_d005_direction"],
                    "outcome": record["outcome"],
                    "candidate_type": record["candidate_type"],
                    "candidate_variant": record["candidate_variant"],
                    "refinement_type": record["refinement_type"],
                    "refinement_variant": record["refinement_variant"],
                }
            )
    membership = pd.DataFrame.from_records(membership_rows)
    completion = forward[
        forward["horizon"].eq("60m")
        & (
            (
                forward["population"].eq("e1_capped")
                & forward["anchor_type"].eq("reaction_confirmed_close")
            )
            | (
                forward["population"].eq("e2_uncapped")
                & forward["anchor_type"].eq("reaction_confirmed_close")
            )
        )
    ][
        [
            "population",
            "sequence_id",
            "signed_forward_movement",
            "mfe",
            "mae",
        ]
    ]
    joined = membership.merge(
        completion, on=["population", "sequence_id"], how="left"
    )
    summary = (
        joined.groupby(
            ["population", "membership", "mapping_variant", "outcome"],
            dropna=False,
        )
        .agg(
            sequence_count=("sequence_id", "nunique"),
            forward_observations=(
                "signed_forward_movement",
                "count",
            ),
            long_count=("direction", lambda values: int(values.eq(1).sum())),
            short_count=("direction", lambda values: int(values.eq(-1).sum())),
            mean_signed_movement_60m=(
                "signed_forward_movement",
                "mean",
            ),
            median_signed_movement_60m=(
                "signed_forward_movement",
                "median",
            ),
            mean_mfe_60m=("mfe", "mean"),
            mean_mae_60m=("mae", "mean"),
        )
        .reset_index()
    )
    return membership, summary


def cap_state_direction_distribution(
    sequences: pd.DataFrame,
    engine_evaluations: pd.DataFrame,
) -> pd.DataFrame:
    """Keep capped confirmations and uncapped replay states comparable."""

    capped = sequences[
        sequences["population"].eq("e1_capped")
    ][["sequence_id", "mapping_variant", "final_d005_direction", "outcome"]].copy()
    capped = (
        capped.groupby(
            ["mapping_variant", "final_d005_direction", "outcome"],
            dropna=False,
        )
        .agg(observations=("sequence_id", "nunique"))
        .reset_index()
        .rename(columns={"final_d005_direction": "direction"})
    )
    capped["population"] = "e1_capped"
    capped["state"] = "reaction_confirmed"
    if engine_evaluations.empty:
        return capped
    uncapped = (
        engine_evaluations.groupby(
            [
                "mapping_variant",
                "engine_state",
                "engine_direction",
                "engine_outcome",
            ],
            dropna=False,
        )
        .agg(observations=("engine_evaluation_id", "nunique"))
        .reset_index()
        .rename(
            columns={
                "engine_state": "state",
                "engine_direction": "direction",
                "engine_outcome": "outcome",
            }
        )
    )
    uncapped["population"] = "e2_uncapped_engine_replay"
    columns = [
        "population",
        "mapping_variant",
        "state",
        "direction",
        "outcome",
        "observations",
    ]
    return pd.concat(
        [capped[columns], uncapped[columns]],
        ignore_index=True,
    )


def classify_dominant_cause(
    *,
    direction_audit: pd.DataFrame,
    sequences: pd.DataFrame,
    forward: pd.DataFrame,
    cap_summary: pd.DataFrame,
) -> dict[str, object]:
    """Apply transparent hard classification tests to observed evidence."""

    def mean_at(
        population: str,
        anchor: str,
        outcome: str | None = None,
        *,
        engine_selected_only: bool = False,
    ) -> float:
        rows = forward[
            forward["population"].eq(population)
            & forward["anchor_type"].eq(anchor)
            & forward["horizon"].eq("60m")
        ]
        if outcome is not None:
            rows = rows[rows["outcome"].eq(outcome)]
        if engine_selected_only:
            rows = rows[
                rows["engine_selected_reaction_confirmed"].fillna(False)
            ]
        if rows.empty:
            return np.nan
        return float(rows["signed_forward_movement"].mean())

    direction_population = direction_audit[
        direction_audit["population"].eq("e1_capped")
        | direction_audit[
            "engine_selected_reaction_confirmed"
        ].fillna(False)
    ]
    deterministic_direction_valid = bool(
        direction_population[
            [
                "sweep_expected_mapping_valid",
                "sweep_raid_not_used_as_reaction",
                "reversal_direction_valid",
                "continuation_parent_alignment_valid",
            ]
        ]
        .fillna(True)
        .all()
        .all()
    )
    capped_event = mean_at("e1_capped", "poi_or_sweep_close")
    capped_reaction = mean_at(
        "e1_capped", "reaction_confirmed_close"
    )
    uncapped_event = mean_at("e2_uncapped", "poi_or_sweep_close")
    uncapped_completion = mean_at(
        "e2_uncapped",
        "reaction_confirmed_close",
        engine_selected_only=True,
    )
    uncapped_selected_event = mean_at(
        "e2_uncapped",
        "poi_or_sweep_close",
        engine_selected_only=True,
    )
    reversal = mean_at(
        "e1_capped", "reaction_confirmed_close", "reversal"
    )
    continuation = mean_at(
        "e1_capped", "reaction_confirmed_close", "continuation"
    )
    classifications: list[int] = []
    reasons: list[str] = []
    if not deterministic_direction_valid:
        classifications.append(1)
        reasons.append("one or more deterministic direction invariants failed")
    capped_timing = sequences[
        sequences["population"].eq("e1_capped")
        & sequences["candidate_at"].notna()
        & sequences["d005_reaction_confirmed_at"].notna()
    ]
    median_candidate_to_reaction_minutes = (
        (
            pd.to_datetime(
                capped_timing["d005_reaction_confirmed_at"],
                utc=True,
            )
            - pd.to_datetime(capped_timing["candidate_at"], utc=True)
        )
        .dt.total_seconds()
        .div(60)
        .median()
        if not capped_timing.empty
        else np.nan
    )
    uncapped_timing = sequences[
        sequences["engine_selected_reaction_confirmed"].fillna(False)
        & sequences["candidate_at"].notna()
        & sequences["d005_reaction_confirmed_at"].notna()
    ]
    median_uncapped_candidate_to_reaction_minutes = (
        (
            pd.to_datetime(
                uncapped_timing["d005_reaction_confirmed_at"],
                utc=True,
            )
            - pd.to_datetime(uncapped_timing["candidate_at"], utc=True)
        )
        .dt.total_seconds()
        .div(60)
        .median()
        if not uncapped_timing.empty
        else np.nan
    )
    if (
        np.isfinite(capped_event)
        and np.isfinite(capped_reaction)
        and capped_event > 0
        and capped_reaction < 0
        and np.isfinite(median_candidate_to_reaction_minutes)
        and median_candidate_to_reaction_minutes > 0
    ):
        classifications.append(2)
        reasons.append(
            "the capped candidate anchor was positive while the later "
            "reaction-confirmed anchor was negative at 60m"
        )
    if (
        np.isfinite(uncapped_selected_event)
        and np.isfinite(uncapped_completion)
        and uncapped_selected_event <= 0
        and uncapped_completion <= 0
    ):
        classifications.append(3)
        reasons.append(
            "both uncapped candidate and completion anchors lacked positive "
            "60m directional relationship"
        )
    completion_rows = forward[
        forward["population"].eq("e1_capped")
        & forward["anchor_type"].eq("reaction_confirmed_close")
        & forward["horizon"].eq("60m")
    ]

    def concentrated_in(field: str) -> tuple[bool, str | None, float]:
        usable = completion_rows[
            completion_rows[field].notna()
        ]
        if usable.empty or usable["signed_forward_movement"].mean() >= 0:
            return False, None, np.nan
        grouped = usable.groupby(field)["signed_forward_movement"].agg(
            ["sum", "count"]
        )
        negative = grouped[grouped["sum"].lt(0)].copy()
        if negative.empty:
            return False, None, np.nan
        dominant = negative["sum"].idxmin()
        total_negative = float(-negative["sum"].sum())
        share = (
            float(-negative.loc[dominant, "sum"] / total_negative)
            if total_negative > 0
            else np.nan
        )
        remainder = usable[usable[field].ne(dominant)]
        remainder_mean = (
            float(remainder["signed_forward_movement"].mean())
            if not remainder.empty
            else np.nan
        )
        return (
            bool(
                np.isfinite(share)
                and share >= 0.60
                and np.isfinite(remainder_mean)
                and remainder_mean >= 0
            ),
            str(dominant),
            share,
        )

    mapping_concentrated, dominant_mapping, mapping_share = concentrated_in(
        "mapping_variant"
    )
    if mapping_concentrated:
        classifications.append(4)
        reasons.append(
            "one mapping contributed at least 60% of negative signed "
            "movement and the remaining mappings were non-negative: "
            f"{dominant_mapping}"
        )
    outcome_concentrated, dominant_outcome, outcome_share = concentrated_in(
        "outcome"
    )
    if outcome_concentrated:
        classifications.append(5)
        reasons.append(
            "one outcome class contributed at least 60% of negative signed "
            "movement and the other class was non-negative: "
            f"{dominant_outcome}"
        )
    variant_findings: list[tuple[str, str, float]] = []
    for field in ("candidate_variant", "refinement_variant"):
        concentrated, value, share = concentrated_in(field)
        if concentrated and value is not None:
            variant_findings.append((field, value, share))
    if variant_findings:
        classifications.append(6)
        reasons.append(
            "a POI/array variant met the 60% negative-contribution "
            "concentration rule while all alternatives were non-negative: "
            + ", ".join(
                f"{field}={value}" for field, value, _ in variant_findings
            )
        )
    capped_mean = cap_summary[
        cap_summary["population"].eq("e1_capped")
    ]["mean_signed_movement_60m"]
    uncapped_mean = cap_summary[
        cap_summary["population"].eq("e2_uncapped")
    ]["mean_signed_movement_60m"]
    capped_weight = cap_summary[
        cap_summary["population"].eq("e1_capped")
    ]["forward_observations"]
    uncapped_weight = cap_summary[
        cap_summary["population"].eq("e2_uncapped")
    ]["forward_observations"]
    capped_pooled = (
        float(np.average(capped_mean, weights=capped_weight))
        if len(capped_mean) and capped_weight.sum()
        else np.nan
    )
    uncapped_pooled = (
        float(np.average(uncapped_mean, weights=uncapped_weight))
        if len(uncapped_mean) and uncapped_weight.sum()
        else np.nan
    )
    if (
        np.isfinite(capped_pooled)
        and np.isfinite(uncapped_pooled)
        and (
            np.sign(capped_pooled) != np.sign(uncapped_pooled)
            or abs(capped_pooled - uncapped_pooled)
            > max(0.5, abs(uncapped_pooled))
        )
    ):
        classifications.append(7)
        reasons.append(
            "capped and uncapped completion-anchor 60m means differed in "
            "sign or by more than the documented E2 materiality rule"
        )
    if not classifications:
        classifications.append(8)
        reasons.append("no hard diagnostic classification test was met")
    return {
        "classification_ids": sorted(set(classifications)),
        "classification_labels": [
            {
                1: "Direction-label implementation defect",
                2: "Reaction confirmation is causally correct but systematically late",
                3: "Context thesis has no positive forward directional relationship",
                4: "Negative result is concentrated in one mapping",
                5: "Negative result is concentrated in reversal or continuation sequences",
                6: "Negative result is caused by specific POI/array variants",
                7: "Capped sampling materially distorted D005_E1",
                8: "Evidence remains inconclusive",
            }[identifier]
            for identifier in sorted(set(classifications))
        ],
        "reasons": reasons,
        "diagnostic_values": {
            "direction_invariants_valid": deterministic_direction_valid,
            "e1_candidate_mean_signed_60m": capped_event,
            "e1_reaction_mean_signed_60m": capped_reaction,
            "uncapped_candidate_mean_signed_60m": uncapped_event,
            "uncapped_selected_candidate_mean_signed_60m": (
                uncapped_selected_event
            ),
            "uncapped_completion_mean_signed_60m": uncapped_completion,
            "median_e1_candidate_to_reaction_minutes": (
                median_candidate_to_reaction_minutes
            ),
            "median_uncapped_candidate_to_reaction_minutes": (
                median_uncapped_candidate_to_reaction_minutes
            ),
            "e1_reversal_reaction_mean_signed_60m": reversal,
            "e1_continuation_reaction_mean_signed_60m": continuation,
            "e1_capped_pooled_completion_mean_60m": capped_pooled,
            "e2_uncapped_pooled_completion_mean_60m": uncapped_pooled,
            "cap_priority_selected_worse_completion_outcomes": bool(
                np.isfinite(capped_pooled)
                and np.isfinite(uncapped_pooled)
                and capped_pooled < uncapped_pooled
            ),
            "cap_priority_selected_later_confirmations": bool(
                np.isfinite(median_candidate_to_reaction_minutes)
                and np.isfinite(
                    median_uncapped_candidate_to_reaction_minutes
                )
                and median_candidate_to_reaction_minutes
                > median_uncapped_candidate_to_reaction_minutes
            ),
            "dominant_mapping": dominant_mapping,
            "dominant_mapping_negative_contribution_share": mapping_share,
            "dominant_outcome": dominant_outcome,
            "dominant_outcome_negative_contribution_share": outcome_share,
            "dominant_variant_findings": variant_findings,
        },
    }
