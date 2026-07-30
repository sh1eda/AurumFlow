"""Atomic persistence and reporting for D005_E4."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype

from research.context_engine.reporting import sha256_file
from research.d005_e2_reaction_anchor_diagnostic.reporting import (
    directory_fingerprint,
)

from .config import ReversalReplicationConfig


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
        if (
            column.endswith("_at")
            and not is_bool_dtype(normalized[column])
            and (
                is_datetime64_any_dtype(normalized[column])
                or normalized[column].dtype == object
            )
        ):
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
    config: ReversalReplicationConfig,
) -> dict[str, object]:
    repository = Path.cwd()
    paths: list[tuple[str, Path]] = []
    for relative in (
        Path("research/context_engine"),
        Path("research/d005_e1_context_engine_empirical"),
        Path("research/d005_e2_reaction_anchor_diagnostic"),
        Path("research/d005_e3_early_context_anchor_study"),
        Path("research/d005_e4_1h_5m_reversal_replication"),
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

    def text(value: object) -> str:
        if value is None or (
            isinstance(value, (float, np.floating)) and np.isnan(value)
        ):
            return "NA"
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6g}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    headers = list(selected.columns)
    rows = [
        "| " + " | ".join(text(value) for value in row) + " |"
        for row in selected.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *rows,
        ]
    )


def render_report(
    frames: Mapping[str, pd.DataFrame],
    *,
    summary: Mapping[str, object],
) -> str:
    primary = frames["primary_60m_result"].iloc[0]
    refinement = frames["refinement_60m_result"].iloc[0]
    paired = frames["paired_refinement_summary"].iloc[0]
    classification = summary["classification"]
    comparison = frames["discovery_replication_comparison"]
    endpoint_comparison = comparison[
        comparison["comparison_dimension"].eq("endpoint")
    ]
    lines = [
        "# D005_E4 1H→5m Reversal Replication",
        "",
        "## Boundary",
        "",
        "This is an isolated descriptive replication diagnostic. An anchor is "
        "not an entry. E4 changed no D005 default, threshold, gate, state "
        "transition, production behavior, canonical data, or prior D005–E3 "
        "artifact.",
        "",
        "## 1. Replication-sample independence",
        "",
        "**No genuinely independent replication sample is available.** The "
        "authoritative D003-derived source ends on 2025-12-31. The available "
        "2026 MT5 export was excluded before outcome analysis because it is a "
        "different, non-D003 feed. No 2021–2025 block was reserved before E3.",
        "",
        "E4 therefore uses preregistered rolling-origin validation blocks "
        "2022–2025. Each validation block is disjoint from its own expanding "
        "discovery prefix, but every E4 observation overlaps the E3 discovery "
        "sample. Internal temporal checks cannot establish category 1.",
        "",
        _table(
            frames["sample_independence_assessment"],
            [
                "candidate_design",
                "available",
                "selected",
                "independent_of_e3",
                "reason",
            ],
        ),
        "",
        "## 2. Provenance and reproducibility",
        "",
        f"- D003-derived source files reverified: "
        f"`{summary['source_file_count']}`",
        f"- Source rows: `{summary['source_row_count']}`",
        f"- Source selection SHA-256: `{summary['source_selection_sha256']}`",
        f"- Source hash mismatches: `{summary['source_hash_mismatch_count']}`",
        f"- Configuration fingerprint: `{summary['study_config_fingerprint']}`",
        f"- Implementation fingerprint: `{summary['implementation_sha256']}`",
        f"- D005/E1/E2/E3 fingerprints preserved: "
        f"`{summary['protected_artifacts_preserved']}`",
        f"- Frozen E3 discovery values verified: "
        f"`{summary['frozen_discovery_verified']}`",
        "",
        "## 3. Eligible sequences",
        "",
        f"- E3 sequences audited: `{summary['e3_sequence_count']}`",
        f"- Eligible unique displacement anchors: "
        f"`{summary['eligible_displacement_anchor_count']}`",
        f"- Rolling-origin validation anchors: "
        f"`{summary['validation_displacement_anchor_count']}`",
        f"- Primary 60-minute complete observations: "
        f"`{int(primary['sample_count'])}`",
        f"- Deterministic duplicate anchors removed: "
        f"`{summary['primary_anchor_deduplicated_count']}`",
        "",
        "## 4. Primary displacement result",
        "",
        _table(
            frames["primary_60m_result"],
            [
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_ci_lower",
                "mean_ci_upper",
                "bootstrap_mean_ci_lower",
                "bootstrap_mean_ci_upper",
            ],
        ),
        "",
        "This is the sole preregistered primary endpoint. It is an internal "
        "rolling-origin estimate and is not pooled with E3.",
        "",
        "## 5. Secondary refinement result",
        "",
        _table(
            frames["refinement_60m_result"],
            [
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_ci_lower",
                "mean_ci_upper",
                "bootstrap_mean_ci_lower",
                "bootstrap_mean_ci_upper",
            ],
        ),
        "",
        f"Paired sequences with both 60-minute observations: "
        f"`{int(paired['paired_sequence_count'])}`. Median displacement-to-"
        f"refinement time: "
        f"`{paired['median_displacement_to_refinement_minutes']}` minutes. "
        f"Mean refinement-minus-displacement 60-minute movement: "
        f"`{paired['mean_refinement_minus_displacement_signed_60m']}`.",
        "",
        "Displacement and refinement are paired by sequence and are never "
        "counted as independent observations.",
        "",
        "## 6. MFE/MAE and path risk",
        "",
        f"- Primary mean MFE: `{primary['mean_mfe']}`",
        f"- Primary mean MAE: `{primary['mean_mae']}`",
        f"- Mean-MFE/mean-MAE ratio: "
        f"`{primary['mean_mfe_to_mean_mae']}`",
        f"- Median per-path MFE/MAE ratio: "
        f"`{primary['median_mfe_mae_ratio']}`",
        f"- Adverse-before-favorable probability: "
        f"`{primary['adverse_before_favorable_probability']}`",
        f"- Median time to MFE / MAE: "
        f"`{primary['median_time_to_mfe_minutes']}` / "
        f"`{primary['median_time_to_mae_minutes']}` minutes",
        "",
        "These are descriptive price paths, not trade risk, stops, returns, "
        "expectancy, or P&L.",
        "",
        "## 7. Direction and temporal stability",
        "",
        "Rolling-origin validation:",
        "",
        _table(
            frames["rolling_origin_summary"],
            [
                "replication_fold",
                "discovery_prefix",
                "anchor_year",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_ci_lower",
                "mean_ci_upper",
            ],
        ),
        "",
        "Magnitude contribution by block:",
        "",
        _table(
            frames["temporal_contribution_audit"],
            [
                "replication_fold",
                "anchor_year",
                "block_signed_sum",
                "absolute_net_block_contribution_share",
                "primary_rule_modified_by_this_audit",
            ],
        ),
        "",
        "The frozen three-of-four positive-block rule is not modified after "
        "seeing outcomes. The contribution table nevertheless shows whether "
        "the pooled magnitude is concentrated in one year and must be treated "
        "as an additional stability warning.",
        "",
        "Direction:",
        "",
        _table(
            frames["direction_summaries"],
            [
                "direction",
                "sample_count",
                "mean_signed_movement",
                "median_signed_movement",
                "win_probability",
                "mean_ci_lower",
                "mean_ci_upper",
            ],
        ),
        "",
        "Regime, origin, session, PMH/PML, displacement-strength, latency, "
        "later-refinement, and later-confirmation tables are exploratory "
        "stability diagnostics and do not change inclusion.",
        "",
        "## 8. E3 discovery versus E4 temporal validation",
        "",
        _table(
            endpoint_comparison,
            [
                "metric",
                "discovery_value",
                "replication_value",
                "replication_minus_discovery",
                "pooled_estimate",
            ],
        ),
        "",
        "Composition and latency comparisons remain in "
        "`discovery_replication_comparison.parquet`. No combined estimate is "
        "reported because E4 is not independent of E3.",
        "",
        "## 9. Causal audit",
        "",
        f"- Observations audited: `{summary['causal_audit_count']}`",
        f"- Failed observations: `{summary['causal_audit_failure_count']}`",
        f"- Future-mutation selection invariant: "
        f"`{summary['future_mutation_selection_invariant']}`",
        "",
        "Inclusion used no later refinement, reaction confirmation, "
        "invalidation, MFE, MAE, or price outcome. All source bars used by "
        "anchors were closed and every displacement direction was known at "
        "anchor time.",
        "",
        "## 10. Hard classification",
        "",
        f"**Category {classification['primary_classification_id']}: "
        f"{classification['primary_classification_label']}.**",
        "",
        f"Secondary diagnostic: "
        f"`{classification['secondary_classification']}`.",
        "",
        "```json",
        json.dumps(
            classification["internal_checks"],
            indent=2,
            sort_keys=True,
            default=str,
        ),
        "```",
        "",
        "## 11. Recommendation",
        "",
        f"**{classification['recommendation']}**",
        "",
        "Do not authorize entries, begin entry-geometry research, promote "
        "optional 1m or CISD, add a subgroup filter, promote PMH/PML or a "
        "clock, select a canonical OB, or change production based on E4.",
        "",
    ]
    return "\n".join(lines)


def persist_artifacts(
    *,
    frames: Mapping[str, pd.DataFrame],
    output_dir: Path,
    config: ReversalReplicationConfig,
    source_provenance: Mapping[str, object],
    run_metadata: Mapping[str, object],
    classification: Mapping[str, object],
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    implementation = implementation_provenance(config)
    persisted: dict[str, pd.DataFrame] = {}
    for name, original in frames.items():
        frame = original.copy()
        frame["e4_study_version"] = config.version
        frame["e4_study_config_fingerprint"] = config.fingerprint()
        frame["e4_implementation_sha256"] = implementation[
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
    spec = (Path.cwd() / config.technical_spec).read_text(
        encoding="utf-8"
    )
    _atomic_text(
        spec,
        output_dir / "D005_E4_PREREGISTRATION_SPEC.md",
    )
    primary = persisted["primary_60m_result"].iloc[0]
    causal = persisted["causal_audit_results"]
    summary = {
        "study_id": config.study_id,
        "version": config.version,
        "research_only": True,
        "independent_replication": False,
        "sample_design": config.sample_design,
        "e3_overlap_share": 1.0,
        "production_behavior_changed": False,
        "prior_artifacts_changed": False,
        "canonical_data_changed": False,
        "optimization_performed": False,
        "entry_authorized_count": 0,
        "pnl_calculated": False,
        "optional_1m_primary": False,
        "cisd_included": False,
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
        "protected_artifacts_preserved": run_metadata[
            "protected_artifacts_preserved"
        ],
        "protected_fingerprints": run_metadata[
            "protected_fingerprints_before"
        ],
        "frozen_discovery_verified": run_metadata[
            "frozen_discovery_verified"
        ],
        "e3_sequence_count": len(persisted["sample_selection"]),
        "eligible_displacement_anchor_count": len(
            persisted["displacement_anchors"]
        ),
        "validation_displacement_anchor_count": int(
            persisted["displacement_anchors"][
                "replication_role"
            ].eq("rolling_origin_validation").sum()
        ),
        "primary_60m_observation_count": int(primary["sample_count"]),
        "primary_anchor_deduplicated_count": run_metadata[
            "primary_anchor_deduplication"
        ]["primary_anchor_rows_deduplicated"],
        "causal_audit_count": len(causal),
        "causal_audit_failure_count": int(
            (~causal["all_causal_invariants_pass"]).sum()
        ),
        "future_mutation_selection_invariant": run_metadata[
            "future_mutation_selection_invariant"
        ],
        "secondary_comparison_count": len(
            persisted["secondary_multiplicity_tests"]
        ),
        "classification": dict(classification),
        "recommendation": classification["recommendation"],
        "acceptance_criteria": {
            "isolated_package_and_output": True,
            "protected_fingerprints_preserved": run_metadata[
                "protected_artifacts_preserved"
            ],
            "source_hashes_reverified": (
                run_metadata["source_hash_mismatch_count"] == 0
            ),
            "frozen_discovery_verified": run_metadata[
                "frozen_discovery_verified"
            ],
            "selection_unique": persisted[
                "displacement_anchors"
            ]["sequence_id"].is_unique,
            "selection_not_future_conditioned": bool(
                ~persisted["displacement_anchors"][
                    "anchor_selected_using_later_completion"
                ].any()
            ),
            "paired_by_sequence": persisted[
                "paired_refinement_anchors"
            ]["sequence_id"].is_unique,
            "primary_endpoint_exact": (
                bool(
                    persisted["primary_60m_outcomes"]["horizon"]
                    .eq("60m")
                    .all()
                )
            ),
            "secondary_family_exact": (
                len(persisted["secondary_multiplicity_tests"]) == 13
            ),
            "causal_audit_passed": bool(
                causal["all_causal_invariants_pass"].all()
            ),
            "descriptive_not_pnl": True,
        },
    }
    report = render_report(persisted, summary=summary)
    _atomic_text(
        report,
        output_dir
        / "D005_E4_1H_5M_REVERSAL_REPLICATION_REPORT.md",
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
    "persist_artifacts",
]
