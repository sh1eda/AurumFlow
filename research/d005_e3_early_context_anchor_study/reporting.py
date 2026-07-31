"""Atomic persistence and research-only reporting for D005_E3."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from research.context_engine.reporting import sha256_file
from research.d005_e2_reaction_anchor_diagnostic.reporting import (
    directory_fingerprint,
)

from .config import EarlyContextAnchorStudyConfig


def _atomic_json(payload: object, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _atomic_text(text: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)


def _atomic_parquet(frame: pd.DataFrame, target: Path) -> None:
    normalized = frame.copy()
    for column in normalized:
        if column.endswith("_at"):
            normalized[column] = pd.to_datetime(
                normalized[column], utc=True, errors="coerce"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    normalized.to_parquet(
        temporary,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )
    os.replace(temporary, target)


def implementation_provenance(
    config: EarlyContextAnchorStudyConfig,
) -> dict[str, object]:
    repository = Path.cwd()
    paths: list[tuple[str, Path]] = []
    for relative in (
        Path("research/context_engine"),
        Path("research/d005_e1_context_engine_empirical"),
        Path("research/d005_e2_reaction_anchor_diagnostic"),
        Path("research/d005_e3_early_context_anchor_study"),
    ):
        for path in sorted((repository / relative).glob("*.py")):
            paths.append((str(relative / path.name), path))
    spec = repository / config.technical_spec
    if spec.is_file():
        paths.append((config.technical_spec, spec))
    records = [
        {
            "path": label,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in paths
    ]
    combined = "|".join(
        f"{record['path']}:{record['sha256']}" for record in records
    )
    return {
        "files": records,
        "implementation_sha256": hashlib.sha256(
            combined.encode("utf-8")
        ).hexdigest(),
    }


def _table(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    limit: int = 40,
) -> str:
    if frame.empty:
        return "_No observations._"
    selected = frame[
        [column for column in columns if column in frame.columns]
    ].head(limit)

    def value_text(value: object) -> str:
        if value is None or (
            isinstance(value, (float, np.floating)) and np.isnan(value)
        ):
            return "NA"
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6g}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    headers = list(selected.columns)
    rows = [
        "| " + " | ".join(value_text(value) for value in row) + " |"
        for row in selected.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *rows,
        ]
    )


def _anchor_order(config: EarlyContextAnchorStudyConfig) -> dict[str, int]:
    return {
        name: index for index, name in enumerate(config.primary_anchors)
    }


def render_report(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: EarlyContextAnchorStudyConfig,
    summary: Mapping[str, object],
) -> str:
    primary = frames["multiplicity_adjusted_comparisons"].copy()
    primary["_order"] = primary["anchor_type"].map(_anchor_order(config))
    primary = primary.sort_values(
        ["_order", "mapping_variant", "outcome"]
    )
    anchors = frames["anchor_forward_summary"]
    principal = anchors[
        anchors["horizon"].eq(config.primary_horizon)
        & anchors["anchor_type"].isin(config.primary_anchors)
    ].sort_values(["anchor_type", "mapping_variant", "outcome"])
    latency = frames["latency_decay_summary"].sort_values(
        ["mapping_variant", "outcome", "latency_stage"]
    )
    criteria = frames["earliest_anchor_criteria"]
    candidate = frames["candidate_anchor_decomposition"].sort_values(
        [
            "conditioning",
            "decomposition_dimension",
            "decomposition_value",
        ]
    )
    classification = summary["classification"]
    decay = summary["latency_decay_diagnostic"]
    lines = [
        "# D005_E3 Early Context Anchor Study",
        "",
        "## Boundary and fixed prior findings",
        "",
        "This isolated study treats every anchor as a descriptive observation "
        "timestamp, never as an entry. It changed no D005 default, threshold, "
        "state transition, production behavior, canonical data, or prior "
        "D005/E1/E2 artifact.",
        "",
        "Accepted E2 conclusions remain fixed: direction labels passed, no "
        "sign inversion was found, reaction confirmation was late (about "
        "70 minutes in capped E1), the E1 cap distorted the pooled result, "
        "and earlier candidate outcomes exceeded reaction-confirmed outcomes.",
        "",
        "## 1. Reproducibility",
        "",
        f"- Source files reverified: `{summary['source_file_count']}`",
        f"- Source rows: `{summary['source_row_count']}`",
        f"- Source selection SHA-256: `{summary['source_selection_sha256']}`",
        f"- Source hash mismatches: `{summary['source_hash_mismatch_count']}`",
        f"- Configuration fingerprint: `{summary['study_config_fingerprint']}`",
        f"- Implementation fingerprint: `{summary['implementation_sha256']}`",
        f"- Missing full dates: `{summary['missing_full_date_count']}`",
        f"- New York DST transition dates: `{summary['dst_transition_date_count']}`",
        f"- Fixed-clock exclusions retained: `{summary['excluded_evaluation_count']}`",
        f"- Protected D005/E1/E2 fingerprints preserved: "
        f"`{summary['protected_artifacts_preserved']}`",
        "",
        "The complete per-file paths, sizes, and hashes are in "
        "`source_provenance.json`; gaps, premarket coverage, excluded dates, "
        "and DST partitions remain in the copied machine-readable quality "
        "tables.",
        "",
        "## 2. Event and sequence counts",
        "",
        "```json",
        json.dumps(
            summary["counts"], indent=2, sort_keys=True, default=str
        ),
        "```",
        "",
        "POI interactions and named liquidity sweeps are distinct anchor "
        "families. Raw FVG, fully context-qualified FVG, and all three OB "
        "taxonomies are also distinct. Principal sample keys are unique "
        "`sequence_id + anchor_type` pairs.",
        "",
        "## 3. Anchor-level 60-minute results",
        "",
        _table(
            principal,
            [
                "anchor_type",
                "mapping_variant",
                "outcome",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_mfe",
                "mean_mae",
                "mean_ci_lower",
                "mean_ci_upper",
            ],
            limit=60,
        ),
        "",
        "All horizons, noon/day-close observations, MFE/MAE ordering, and "
        "time-to-extreme fields are in `anchor_forward_outcomes.parquet` and "
        "`anchor_forward_summary.parquet`.",
        "",
        "## 4. Latency decay",
        "",
        f"- Largest aggregate forward-mean deterioration stage: "
        f"`{decay['largest_deterioration_stage']}`",
        f"- Mean deterioration at that stage: "
        f"`{decay['largest_deterioration']}` XAUUSD price units",
        f"- Diagnostic pattern: `{decay['pattern']}`",
        f"- Non-sequential pairs excluded from the pattern label: "
        f"`{decay.get('nonsequential_stages_excluded_from_pattern', [])}`",
        "",
        _table(
            latency,
            [
                "mapping_variant",
                "outcome",
                "latency_stage",
                "sequence_count",
                "median_elapsed_minutes",
                "negative_timestamp_order_count",
                "mean_signed_stage_movement",
                "median_candidate_to_stage_mfe_consumed",
                "median_candidate_to_stage_mae_incurred",
                "change_in_forward_mean",
                "change_in_win_probability",
            ],
            limit=80,
        ),
        "",
        "## 5. Candidate-anchor decomposition",
        "",
        "Causal-at-candidate dimensions and later-outcome-conditioned "
        "dimensions are explicitly separated. Retrospective rows cannot "
        "promote an anchor.",
        "",
        _table(
            candidate,
            [
                "conditioning",
                "decomposition_dimension",
                "decomposition_value",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_ci_lower",
                "mean_ci_upper",
            ],
            limit=80,
        ),
        "",
        "## 6. Mapping, reversal, and continuation findings",
        "",
        "All five mappings remain independent; no pooled mapping score was "
        "created. Weekly rows include structurally complete sequences even "
        "where frozen-engine confirmation was absent. Reversal and "
        "continuation remain separate throughout all primary comparisons.",
        "",
        "The frozen E2 outcome rule reproduced for every sequence. Liquidity "
        "reversals are explicitly checked against the direction away from the "
        "swept pool. For POI reversals, array direction is preserved, but the "
        "frozen artifacts contain no independent rejected-POI geometry vector; "
        "that narrower verification is therefore unavailable rather than "
        "inferred. Frozen continuation is based on non-opposition to the "
        "pre-candidate child direction, not universal alignment to a non-neutral "
        "parent; aligned, neutral, and opposed parent cases are disclosed.",
        "",
        _table(
            frames["direction_family_summary"].sort_values(
                ["mapping_variant", "outcome", "candidate_source"]
            ),
            [
                "mapping_variant",
                "outcome",
                "candidate_source",
                "sequence_count",
                "frozen_outcome_rule_pass_count",
                "continuation_parent_aligned_count",
                "continuation_parent_neutral_count",
                "continuation_parent_opposed_count",
                "liquidity_reversal_observations",
                "liquidity_reversal_away_pass_count",
                "poi_rejection_vector_verifiable_count",
            ],
            limit=40,
        ),
        "",
        "Continuation adverse excursion and temporary retracement are measured "
        "by `mean_mae`, adverse-before-favorable probability, and time-to-MAE "
        "in the reversal/continuation summary and forward-path artifacts.",
        "",
        _table(
            frames["mapping_summaries"].sort_values(
                ["mapping_variant", "outcome", "anchor_type"]
            ),
            [
                "mapping_variant",
                "outcome",
                "anchor_type",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
            ],
            limit=60,
        ),
        "",
        "## 7. Multiplicity-adjusted stability",
        "",
        f"Registered family: `{summary['registered_primary_comparison_count']}` "
        "two-sided comparisons at the 60-minute horizon. All p-values share "
        "one Benjamini-Hochberg correction at q=0.05.",
        "",
        _table(
            primary,
            [
                "anchor_type",
                "mapping_variant",
                "outcome",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "p_value",
                "bh_q_value",
                "bootstrap_mean_ci_lower",
                "bootstrap_mean_ci_upper",
                "annual_stable",
                "direction_stable",
                "survives_all_stability_criteria",
            ],
            limit=60,
        ),
        "",
        "Earliest-useful-anchor assessment:",
        "",
        _table(
            criteria,
            [
                "anchor_type",
                "nonempty_cells",
                "fdr_significant_positive_cells",
                "fully_stable_cells",
                "surviving_mapping_count",
                "surviving_outcome_count",
                "broadly_stable",
            ],
        ),
        "",
        "## 8. Causal-conditioning audit",
        "",
        "The main population includes every eligible causally observable "
        "anchor and never requires later completion. Later structural "
        "completion, engine confirmation, invalidation, timeout, and conflict "
        "are reported only as retrospective cohorts. Cohort membership and "
        "pairwise overlap are recorded separately so descriptive overlap "
        "cannot inflate principal N.",
        "",
        _table(
            frames["causal_conditioning_audit"].sort_values(
                ["conditioning", "conditioning_cohort", "anchor_type"]
            ),
            [
                "conditioning",
                "conditioning_cohort",
                "mapping_variant",
                "outcome",
                "anchor_type",
                "sample_count",
                "mean_signed_movement",
            ],
            limit=60,
        ),
        "",
        "## 9. Hard classification",
        "",
        f"**Category {classification['primary_classification_id']}: "
        f"{classification['primary_classification_label']}.**",
        "",
        classification["reason"],
        "",
        f"Recommendation: **{classification['recommendation']}**",
        "",
        "Secondary qualifications:",
        "",
    ]
    secondary = classification["secondary_classifications"]
    lines.extend(
        [f"- {item}" for item in secondary]
        if secondary
        else ["- None."]
    )
    lines.extend(
        [
            "",
            "```json",
            json.dumps(
                classification["diagnostic_values"],
                indent=2,
                sort_keys=True,
                default=str,
            ),
            "```",
            "",
            "## 10. Acceptance boundary",
            "",
            "No entries were authorized; no stops, targets, P&L, returns, "
            "expectancy, optimization, mapping selection, canonical OB "
            "selection, CISD promotion, PMH/PML promotion, clock promotion, "
            "production integration, or future-selected main anchor was "
            "introduced.",
            "",
        ]
    )
    return "\n".join(lines)


def latency_decay_diagnostic(
    latency_summary: pd.DataFrame,
) -> dict[str, object]:
    if latency_summary.empty:
        return {
            "largest_deterioration_stage": None,
            "largest_deterioration": None,
            "pattern": "unavailable",
        }
    aggregate = (
        latency_summary.groupby("latency_stage", dropna=False)
        .agg(
            change_in_forward_mean=("change_in_forward_mean", "mean"),
            stage_count=("sequence_count", "sum"),
            negative_timestamp_order_count=(
                "negative_timestamp_order_count",
                "sum",
            ),
        )
        .reset_index()
    )
    excluded = aggregate[
        aggregate["negative_timestamp_order_count"].gt(0)
    ]["latency_stage"].astype(str).tolist()
    finite = aggregate[
        np.isfinite(aggregate["change_in_forward_mean"])
        & aggregate["negative_timestamp_order_count"].eq(0)
    ].sort_values("change_in_forward_mean")
    if finite.empty:
        return {
            "largest_deterioration_stage": None,
            "largest_deterioration": None,
            "pattern": "unavailable",
        }
    worst = finite.iloc[0]
    negative = finite[finite["change_in_forward_mean"].lt(0)]
    total_deterioration = float(
        -negative["change_in_forward_mean"].sum()
    )
    largest = float(-min(float(worst["change_in_forward_mean"]), 0.0))
    share = largest / total_deterioration if total_deterioration else 0.0
    pattern = (
        "discrete_collapse"
        if share >= 0.50 and largest > 0
        else "gradual_or_mixed_decay"
    )
    return {
        "largest_deterioration_stage": str(worst["latency_stage"]),
        "largest_deterioration": float(worst["change_in_forward_mean"]),
        "deterioration_share_at_largest_stage": share,
        "pattern": pattern,
        "nonsequential_stages_excluded_from_pattern": excluded,
    }


def persist_artifacts(
    *,
    frames: Mapping[str, pd.DataFrame],
    output_dir: Path,
    config: EarlyContextAnchorStudyConfig,
    run_metadata: Mapping[str, object],
    source_provenance: Mapping[str, object],
    classification: Mapping[str, object],
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    implementation = implementation_provenance(config)
    persisted: dict[str, pd.DataFrame] = {}
    for name, original in frames.items():
        frame = original.copy()
        frame["e3_study_version"] = config.version
        frame["e3_study_config_fingerprint"] = config.fingerprint()
        frame["e3_implementation_sha256"] = implementation[
            "implementation_sha256"
        ]
        persisted[name] = frame
        _atomic_parquet(frame, output_dir / f"{name}.parquet")
    _atomic_json(config.snapshot(), output_dir / "configuration_snapshot.json")
    _atomic_json(
        source_provenance, output_dir / "source_provenance.json"
    )
    _atomic_json(
        implementation, output_dir / "implementation_provenance.json"
    )
    reproducibility = {
        **dict(run_metadata),
        "study_id": config.study_id,
        "study_version": config.version,
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
    }
    _atomic_json(
        reproducibility, output_dir / "reproducibility_metadata.json"
    )
    _atomic_json(
        {
            "tables": {
                f"{name}.parquet": [
                    {"column": column, "dtype": str(dtype)}
                    for column, dtype in frame.dtypes.items()
                ]
                for name, frame in persisted.items()
            }
        },
        output_dir / "feature_schema.json",
    )
    sequences = persisted["unique_sequences"]
    anchors = persisted["anchor_events"]
    data_quality = persisted["data_quality_periods"]
    primary = persisted["multiplicity_adjusted_comparisons"]
    latency_diagnostic = latency_decay_diagnostic(
        persisted["latency_decay_summary"]
    )
    counts = {
        "unique_uncapped_sequences": int(sequences["sequence_id"].nunique()),
        "main_candidate_eligible_sequences": int(
            sequences["main_candidate_eligible"].sum()
        ),
        "anchor_rows_before_deduplication": int(
            run_metadata["anchor_deduplication"][
                "anchor_rows_before_deduplication"
            ]
        ),
        "anchor_rows_after_deduplication": int(len(anchors)),
        "anchor_rows_deduplicated": int(
            run_metadata["anchor_deduplication"][
                "anchor_rows_deduplicated"
            ]
        ),
        "accepted_e2_candidate_deduplication": dict(
            run_metadata["accepted_e2_candidate_deduplication"]
        ),
        "anchor_counts": {
            str(key): int(value)
            for key, value in anchors["anchor_type"].value_counts().items()
        },
        "sequence_status_counts": {
            str(key): int(value)
            for key, value in sequences["sequence_status"].value_counts().items()
        },
        "mapping_sequence_counts": {
            str(key): int(value)
            for key, value in sequences[
                "mapping_variant"
            ].value_counts().items()
        },
        "ob_variant_event_counts": dict(
            run_metadata["ob_variant_event_counts"]
        ),
        "raw_fvg_event_count": int(run_metadata["raw_fvg_event_count"]),
    }
    summary = {
        "study_id": config.study_id,
        "version": config.version,
        "research_only": True,
        "production_behavior_changed": False,
        "prior_artifacts_changed": False,
        "canonical_data_changed": False,
        "optimization_performed": False,
        "entry_authorized_count": 0,
        "pnl_calculated": False,
        "cisd_included": False,
        "mapping_score_pooled": False,
        "source_file_count": run_metadata["source_file_count"],
        "source_row_count": run_metadata["source_row_count"],
        "source_selection_sha256": run_metadata[
            "source_selection_sha256"
        ],
        "source_hash_mismatch_count": run_metadata[
            "source_hash_mismatch_count"
        ],
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
        "protected_artifacts_preserved": bool(
            run_metadata["protected_artifacts_preserved"]
        ),
        "protected_fingerprints": run_metadata[
            "protected_fingerprints_before"
        ],
        "missing_full_date_count": int(
            data_quality["missing_full_date"].fillna(False).sum()
        ),
        "dst_transition_date_count": int(
            data_quality["dst_transition"].fillna(False).sum()
        ),
        "excluded_evaluation_count": int(
            len(persisted["excluded_evaluations"])
        ),
        "counts": counts,
        "direction_audit": {
            "sequence_count": int(
                len(persisted["direction_family_audit"])
            ),
            "frozen_outcome_rule_failure_count": int(
                (
                    ~persisted["direction_family_audit"][
                        "frozen_outcome_rule_passed"
                    ]
                ).sum()
            ),
            "liquidity_reversal_observation_count": int(
                persisted["direction_family_audit"][
                    "reversal_liquidity_moves_away_from_sweep"
                ].notna().sum()
            ),
            "liquidity_reversal_away_failure_count": int(
                (
                    persisted["direction_family_audit"][
                        "reversal_liquidity_moves_away_from_sweep"
                    ].eq(False)
                ).sum()
            ),
            "poi_rejection_vector_independently_verifiable": False,
        },
        "registered_primary_comparison_count": int(len(primary)),
        "nonempty_primary_comparison_count": int(
            primary["sample_count"].gt(0).sum()
        ),
        "primary_fdr_significant_count": int(
            primary["fdr_significant"].sum()
        ),
        "primary_stable_cell_count": int(
            primary["survives_all_stability_criteria"].sum()
        ),
        "latency_decay_diagnostic": latency_diagnostic,
        "classification": dict(classification),
        "recommendation": classification["recommendation"],
        "acceptance_criteria": {
            "isolated_package_and_output": True,
            "protected_fingerprints_preserved": bool(
                run_metadata["protected_artifacts_preserved"]
            ),
            "all_source_hashes_reverified": (
                int(run_metadata["source_hash_mismatch_count"]) == 0
            ),
            "five_mappings_independent": (
                sequences["mapping_variant"].nunique() == 5
            ),
            "three_ob_variants_independent": (
                set(config.ob_variants)
                == set(run_metadata["ob_variant_event_counts"])
            ),
            "main_sample_not_future_conditioned": bool(
                ~anchors["anchor_selected_using_later_completion"].any()
            ),
            "outcomes_descriptive_not_pnl": True,
            "registered_multiplicity_family_exact": len(primary) == 60,
        },
    }
    report = render_report(
        persisted, config=config, summary=summary
    )
    _atomic_text(
        report,
        output_dir / "D005_E3_EARLY_CONTEXT_ANCHOR_STUDY_REPORT.md",
    )
    _atomic_json(summary, output_dir / "summary.json")
    artifacts = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "artifact_manifest.json"
    ]
    _atomic_json(
        {
            "study_id": config.study_id,
            "version": config.version,
            "study_config_fingerprint": config.fingerprint(),
            "implementation_sha256": implementation[
                "implementation_sha256"
            ],
            "artifacts": artifacts,
        },
        output_dir / "artifact_manifest.json",
    )
    return summary


__all__ = [
    "directory_fingerprint",
    "implementation_provenance",
    "persist_artifacts",
]
