"""End-to-end isolated D005_E4 replication."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Sequence

import pandas as pd

from research.context_engine.bars import build_timeframes
from research.context_engine.pipeline import load_one_minute_bars
from research.context_engine.reporting import sha256_file
from research.d005_e3_early_context_anchor_study.outcomes import (
    calculate_forward_outcomes,
)

from .analysis import (
    build_discovery_replication_comparison,
    build_paired_refinement_outcomes,
    build_primary_result,
    build_rolling_origin_summary,
    build_secondary_tests,
    build_stability_summaries,
    build_temporal_contribution_audit,
    classify_replication,
    metric_record,
)
from .config import ReversalReplicationConfig
from .reporting import directory_fingerprint, persist_artifacts
from .selection import (
    build_causal_audit,
    build_eligible_sequences,
    build_paired_anchor_table,
    build_sample_selection,
    future_mutation_invariant,
    select_primary_anchors,
    select_refinement_anchors,
)


def _verify_source_files(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    checked: list[dict[str, object]] = []
    for record in records:
        path = Path(str(record["path"]))
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        digest = sha256_file(path) if exists else None
        checked.append(
            {
                **record,
                "exists": exists,
                "observed_bytes": size,
                "observed_sha256": digest,
                "verified": bool(
                    exists
                    and size == int(record["bytes"])
                    and digest == record["sha256"]
                ),
            }
        )
    return checked


def _verify_frozen_discovery(e3_output: Path) -> dict[str, object]:
    primary = pd.read_parquet(
        e3_output / "multiplicity_adjusted_comparisons.parquet"
    )
    expected = {
        "displacement_confirmation": {
            "sample_count": 1778,
            "mean_rounded": 0.560,
            "q_rounded": 0.0088,
        },
        "refinement_array_creation": {
            "sample_count": 1778,
            "mean_rounded": 0.559,
            "q_rounded": 0.0088,
        },
    }
    observed: dict[str, object] = {}
    for anchor_type, requirement in expected.items():
        cell = primary[
            primary["anchor_type"].eq(anchor_type)
            & primary["mapping_variant"].eq("1h_5m")
            & primary["outcome"].eq("reversal")
        ]
        if len(cell) != 1:
            raise RuntimeError(
                f"Frozen E3 cell missing or duplicated: {anchor_type}"
            )
        row = cell.iloc[0]
        checks = {
            "sample_count": int(row["sample_count"])
            == requirement["sample_count"],
            "mean_rounded": round(
                float(row["mean_signed_movement"]), 3
            )
            == requirement["mean_rounded"],
            "q_rounded": round(float(row["bh_q_value"]), 4)
            == requirement["q_rounded"],
        }
        if not all(checks.values()):
            raise RuntimeError(
                f"Frozen E3 discovery differs for {anchor_type}: {checks}"
            )
        observed[anchor_type] = {
            "sample_count": int(row["sample_count"]),
            "mean_signed_movement": float(
                row["mean_signed_movement"]
            ),
            "bh_q_value": float(row["bh_q_value"]),
            "checks": checks,
        }
    return observed


def _enrich_outcomes(
    outcomes: pd.DataFrame,
    eligible: pd.DataFrame,
    paired: pd.DataFrame,
) -> pd.DataFrame:
    features = eligible[
        [
            "sequence_id",
            "candidate_to_displacement_minutes",
            "candidate_displacement_latency_bin",
            "displacement_strength_bin",
            "true_range_atr",
            "body_range_fraction",
            "later_engine_confirmed",
        ]
    ]
    refinement = paired[
        ["sequence_id", "refinement_subsequently_present"]
    ]
    return outcomes.merge(
        features, on="sequence_id", how="left", validate="many_to_one"
    ).merge(
        refinement, on="sequence_id", how="left", validate="many_to_one"
    )


def _sample_independence(
    config: ReversalReplicationConfig,
    external_exists: bool,
    external_hash: str | None,
) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        [
            {
                "candidate_design": "post_2025_d003_derived",
                "available": False,
                "selected": False,
                "independent_of_e3": True,
                "reason": (
                    "authoritative D003-derived cache ends 2025-12-31"
                ),
                "source_hash": None,
            },
            {
                "candidate_design": "post_2025_mt5_external",
                "available": external_exists,
                "selected": False,
                "independent_of_e3": True,
                "reason": (
                    "excluded before outcomes: not D003-derived and different "
                    "feed provenance"
                ),
                "source_hash": external_hash,
            },
            {
                "candidate_design": "pre_reserved_2021_2025_holdout",
                "available": False,
                "selected": False,
                "independent_of_e3": True,
                "reason": "E3 used every 2021-2025 year",
                "source_hash": None,
            },
            {
                "candidate_design": config.sample_design,
                "available": True,
                "selected": True,
                "independent_of_e3": False,
                "reason": (
                    "validation blocks are fold-separated but overlap E3 "
                    "discovery 100%"
                ),
                "source_hash": None,
            },
        ]
    )


def run_study(
    *,
    output_dir: Path,
    config: ReversalReplicationConfig,
    command: Sequence[str] = (),
) -> dict[str, object]:
    config.validate()
    started = perf_counter()
    output_dir = output_dir.resolve()
    protected = {
        "d005": Path(config.d005_output).resolve(),
        "e1": Path(config.e1_output).resolve(),
        "e2": Path(config.e2_output).resolve(),
        "e3": Path(config.e3_output).resolve(),
    }
    if output_dir in set(protected.values()):
        raise ValueError("E4 output cannot overwrite D005, E1, E2, or E3")
    for name, path in protected.items():
        if not path.is_dir():
            raise FileNotFoundError(
                f"Required protected {name.upper()} output absent: {path}"
            )
    fingerprints_before = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }
    frozen_discovery = _verify_frozen_discovery(protected["e3"])

    e3_source = json.loads(
        (protected["e3"] / "source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    verified_sources = _verify_source_files(list(e3_source["files"]))
    mismatches = [
        record for record in verified_sources if not record["verified"]
    ]
    if mismatches:
        raise RuntimeError(
            "E4 authoritative source hash verification failed: "
            + ", ".join(
                str(record["path"]) for record in mismatches[:10]
            )
        )
    source = Path(str(e3_source["source"]))
    one_minute_raw, provenance = load_one_minute_bars(
        source,
        start_date=config.source_start_date,
        end_date=config.source_end_date,
        lookback_days=120,
    )
    if provenance["selection_sha256"] != e3_source["selection_sha256"]:
        raise RuntimeError("E4 source selection differs from protected E3")
    if int(provenance["row_count"]) != int(e3_source["row_count"]):
        raise RuntimeError("E4 source row count differs from protected E3")
    timeframes = build_timeframes(one_minute_raw)

    e3_anchors = pd.read_parquet(
        protected["e3"] / "anchor_events.parquet"
    )
    e3_sequences = pd.read_parquet(
        protected["e3"] / "unique_sequences.parquet"
    )
    confirmations = pd.read_parquet(
        protected["e2"] / "confirmation_event_inventory.parquet"
    )
    for column in ("created_at", "available_at"):
        confirmations[column] = pd.to_datetime(
            confirmations[column], utc=True, errors="coerce"
        )

    primary_anchors, deduplication = select_primary_anchors(
        e3_anchors, config=config
    )
    selection = build_sample_selection(
        e3_sequences, primary_anchors, config=config
    )
    eligible = build_eligible_sequences(
        e3_sequences,
        primary_anchors,
        confirmations,
        config=config,
    )
    mutation_invariant = future_mutation_invariant(
        e3_anchors, config=config
    )
    refinement_anchors = select_refinement_anchors(
        e3_anchors,
        primary_anchors["sequence_id"],
        config=config,
    )
    refinement_anchors = refinement_anchors.merge(
        primary_anchors[
            [
                "sequence_id",
                "replication_role",
                "replication_fold",
            ]
        ],
        on="sequence_id",
        how="left",
        validate="one_to_one",
    )
    paired_anchors = build_paired_anchor_table(
        primary_anchors, refinement_anchors
    )
    causal_audit = build_causal_audit(
        eligible,
        timeframes=timeframes,
        selection_invariant=mutation_invariant,
    )

    displacement_outcomes = calculate_forward_outcomes(
        primary_anchors, timeframes["1min"], config=config
    )
    refinement_outcomes = calculate_forward_outcomes(
        refinement_anchors, timeframes["1min"], config=config
    )
    displacement_outcomes = _enrich_outcomes(
        displacement_outcomes, eligible, paired_anchors
    )
    refinement_outcomes = _enrich_outcomes(
        refinement_outcomes, eligible, paired_anchors
    )
    primary_outcomes = displacement_outcomes[
        displacement_outcomes["replication_role"].eq(
            "rolling_origin_validation"
        )
        & displacement_outcomes["horizon"].eq(config.primary_horizon)
    ].copy()
    endpoint_availability = primary_anchors[
        [
            "sequence_id",
            "replication_role",
            "replication_fold",
            "anchor_at",
        ]
    ].copy()
    endpoint_ids = set(primary_outcomes["sequence_id"].astype(str))
    endpoint_availability["primary_60m_observed"] = endpoint_availability[
        "sequence_id"
    ].astype(str).isin(endpoint_ids)
    endpoint_availability["missing_endpoint_excluded_from_mean"] = (
        endpoint_availability["replication_role"].eq(
            "rolling_origin_validation"
        )
        & ~endpoint_availability["primary_60m_observed"]
    )

    primary_result = build_primary_result(
        displacement_outcomes, config=config
    )
    secondary_tests = build_secondary_tests(
        displacement_outcomes, refinement_outcomes, config=config
    )
    paired_outcomes, paired_summary = build_paired_refinement_outcomes(
        paired_anchors,
        displacement_outcomes,
        refinement_outcomes,
        config=config,
    )
    refinement_60_validation = refinement_outcomes[
        refinement_outcomes["replication_role"].eq(
            "rolling_origin_validation"
        )
        & refinement_outcomes["horizon"].eq(config.primary_horizon)
    ]
    refinement_result = pd.DataFrame(
        [
            {
                "endpoint": (
                    "secondary_mean_direction_aligned_movement_60m_"
                    "from_refinement"
                ),
                **metric_record(
                    refinement_60_validation,
                    config=config,
                    seed_parts=("refinement_60m",),
                ),
            }
        ]
    )
    stability = build_stability_summaries(
        displacement_outcomes, config=config
    )
    rolling = build_rolling_origin_summary(
        stability["temporal_block_summaries"]
    )
    temporal_contribution = build_temporal_contribution_audit(rolling)

    discovery_forward = pd.read_parquet(
        protected["e3"] / "anchor_forward_outcomes.parquet"
    )
    discovery = discovery_forward[
        discovery_forward["mapping_variant"].eq(config.primary_mapping)
        & discovery_forward["outcome"].eq(config.primary_outcome)
        & discovery_forward["anchor_type"].eq(config.primary_anchor)
        & discovery_forward["horizon"].eq(config.primary_horizon)
        & discovery_forward["main_scope_eligible"].fillna(False)
    ].drop_duplicates("sequence_id")
    comparison_features = eligible[
        ["sequence_id", "candidate_to_displacement_minutes"]
    ]
    discovery = discovery.merge(
        comparison_features,
        on="sequence_id",
        how="left",
        validate="one_to_one",
    )
    comparison = build_discovery_replication_comparison(
        discovery, primary_outcomes, config=config
    )

    external = Path(config.excluded_external_source)
    external_exists = external.is_file()
    external_hash = sha256_file(external) if external_exists else None
    independence = _sample_independence(
        config, external_exists, external_hash
    )
    reproducibility_defect = bool(
        mismatches
        or not mutation_invariant
        or not causal_audit["all_causal_invariants_pass"].all()
    )
    classification = classify_replication(
        primary_result=primary_result,
        primary_outcomes=displacement_outcomes,
        temporal=stability["temporal_block_summaries"],
        direction=stability["direction_summaries"],
        causal_audit=causal_audit,
        reproducibility_defect=reproducibility_defect,
        config=config,
    )

    path_risk = pd.concat(
        [
            displacement_outcomes.assign(
                analysis_anchor="displacement"
            ),
            refinement_outcomes.assign(
                analysis_anchor="refinement"
            ),
        ],
        ignore_index=True,
        sort=False,
    )[
        [
            "sequence_id",
            "replication_role",
            "replication_fold",
            "analysis_anchor",
            "anchor_type",
            "anchor_at",
            "direction",
            "horizon",
            "signed_forward_movement",
            "win",
            "mfe",
            "mae",
            "mfe_mae_ratio",
            "adverse_before_favorable",
            "time_to_mfe_minutes",
            "time_to_mae_minutes",
        ]
    ]
    quality = {
        "data_quality_periods": pd.read_parquet(
            protected["e3"] / "data_quality_periods.parquet"
        ),
        "excluded_evaluations": pd.read_parquet(
            protected["e3"] / "excluded_evaluations.parquet"
        ),
    }
    frames = {
        "sample_independence_assessment": independence,
        "sample_selection": selection,
        "eligible_sequences": eligible,
        "displacement_anchors": primary_anchors,
        "paired_refinement_anchors": paired_anchors,
        "primary_60m_outcomes": primary_outcomes,
        "secondary_horizon_outcomes": pd.concat(
            [
                displacement_outcomes[
                    ~displacement_outcomes["horizon"].eq(
                        config.primary_horizon
                    )
                ],
                refinement_outcomes,
            ],
            ignore_index=True,
            sort=False,
        ),
        "mfe_mae_outcomes": path_risk,
        "endpoint_availability_audit": endpoint_availability,
        "primary_60m_result": primary_result,
        "refinement_60m_result": refinement_result,
        "paired_refinement_outcomes": paired_outcomes,
        "paired_refinement_summary": paired_summary,
        "secondary_multiplicity_tests": secondary_tests,
        "rolling_origin_summary": rolling,
        "temporal_contribution_audit": temporal_contribution,
        "causal_audit_results": causal_audit,
        "discovery_replication_comparison": comparison,
        **stability,
        **quality,
    }

    fingerprints_after_compute = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }
    if fingerprints_after_compute != fingerprints_before:
        raise RuntimeError(
            "A protected D005/E1/E2/E3 artifact changed during E4 computation"
        )
    source_provenance = {
        "authoritative_source": str(source.resolve()),
        "source_role": "hash_verified_d003_derived_e3_source",
        "requested_start_date": config.source_start_date.isoformat(),
        "requested_end_date": config.source_end_date.isoformat(),
        "file_count": len(verified_sources),
        "row_count": int(provenance["row_count"]),
        "selection_sha256": provenance["selection_sha256"],
        "hash_mismatch_count": len(mismatches),
        "read_only": True,
        "files": verified_sources,
        "post_2025_d003_derived_available": False,
        "excluded_external_source": {
            "path": str(external.resolve()),
            "exists": external_exists,
            "sha256": external_hash,
            "used": False,
            "reason": (
                "non-D003 MT5 feed with distinct provenance; excluded "
                "before outcome computation"
            ),
        },
    }
    run_metadata = {
        "command": list(command)
        or [
            sys.executable,
            "-m",
            "research.d005_e4_1h_5m_reversal_replication",
        ],
        "runtime_seconds_before_persistence": perf_counter() - started,
        "source_file_count": len(verified_sources),
        "source_row_count": int(provenance["row_count"]),
        "source_selection_sha256": provenance["selection_sha256"],
        "source_hash_mismatch_count": len(mismatches),
        "protected_paths": {
            name: str(path) for name, path in protected.items()
        },
        "protected_fingerprints_before": fingerprints_before,
        "protected_fingerprints_after_compute": fingerprints_after_compute,
        "protected_artifacts_preserved": True,
        "frozen_discovery_verified": True,
        "frozen_discovery_values": frozen_discovery,
        "primary_anchor_deduplication": deduplication,
        "future_mutation_selection_invariant": mutation_invariant,
        "sample_design": config.sample_design,
        "e3_overlap_share": 1.0,
        "post_2025_d003_derived_available": False,
        "external_source_excluded_before_outcomes": True,
    }
    summary = persist_artifacts(
        frames=frames,
        output_dir=output_dir,
        config=config,
        source_provenance=source_provenance,
        run_metadata=run_metadata,
        classification=classification,
    )
    fingerprints_after = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }
    if fingerprints_after != fingerprints_before:
        raise RuntimeError(
            "A protected D005/E1/E2/E3 artifact changed during E4 persistence"
        )
    return summary


__all__ = ["run_study"]
