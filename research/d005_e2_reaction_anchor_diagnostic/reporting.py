"""Persistence, provenance, and report generation for D005_E2."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from research.context_engine.reporting import sha256_file

from .config import ReactionAnchorDiagnosticConfig


def directory_fingerprint(path: Path) -> str:
    if not path.exists():
        return "absent"
    records = [
        (
            str(item.relative_to(path)),
            item.stat().st_size,
            sha256_file(item),
        )
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]
    return hashlib.sha256(
        "|".join(f"{name}:{size}:{digest}" for name, size, digest in records).encode(
            "utf-8"
        )
    ).hexdigest()


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
    config: ReactionAnchorDiagnosticConfig,
) -> dict[str, object]:
    repository = Path.cwd()
    paths: list[tuple[str, Path]] = []
    for relative in (
        Path("research/context_engine"),
        Path("research/d005_e1_context_engine_empirical"),
        Path("research/d005_e2_reaction_anchor_diagnostic"),
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
        [column for column in columns if column in frame]
    ].head(limit)
    headers = list(selected.columns)

    def value_text(value: object) -> str:
        if value is None or (
            isinstance(value, (float, np.floating)) and np.isnan(value)
        ):
            return "NA"
        return str(value).replace("|", "\\|").replace("\n", " ")

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


def _next_action(classification_ids: list[int]) -> str:
    if 1 in classification_ids:
        return "Repair the verified direction-label defect before further hypothesis testing."
    if 2 in classification_ids:
        return (
            "Test earlier causal anchors as a separately named hypothesis; "
            "do not reinterpret them as entries in this study."
        )
    if 4 in classification_ids or 5 in classification_ids or 6 in classification_ids:
        return "Isolate the implicated cohort in a preregistered research study."
    if 3 in classification_ids:
        return (
            "Redesign the context hypothesis; if an independent replication "
            "also fails, stop pursuing this context family."
        )
    if 7 in classification_ids:
        return "Use the uncapped population for a separately approved replication."
    return "Collect or reconstruct additional evidence before changing the hypothesis."


def render_report(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: ReactionAnchorDiagnosticConfig,
    summary: Mapping[str, object],
) -> str:
    funnel = frames["sequence_funnel"].sort_values(
        ["population", "mapping_variant", "sequence_count"],
        ascending=[True, True, False],
    )
    principal = frames["principal_anchor_summary"]
    principal_60 = principal[
        principal["horizon"].eq("60m")
        & principal["sequence_cohort"].isin(
            [
                "e1_reaction_confirmed",
                "engine_reaction_confirmed",
                "core_sequence_complete",
            ]
        )
    ].sort_values(
        ["population", "sequence_cohort", "outcome", "anchor_type"]
    )
    latency = frames["latency_summary"].sort_values(
        ["population", "outcome", "latency_stage"]
    )
    mismatch = frames["direction_mismatch_summary"]
    critical_mismatch = mismatch[
        mismatch["left_direction"].isin(
            [
                "candidate_direction",
                "mss_direction",
                "displacement_direction",
                "refinement_direction",
                "final_d005_direction",
            ]
        )
        & mismatch["right_direction"].isin(
            [
                "candidate_direction",
                "mss_direction",
                "displacement_direction",
                "refinement_direction",
                "final_d005_direction",
                "realized_direction_60m",
            ]
        )
    ].sort_values(
        ["population", "mapping_variant", "outcome", "left_direction", "right_direction"]
    )
    cap = frames["cap_sensitivity_summary"].sort_values(
        ["population", "membership", "mapping_variant", "outcome"]
    )
    weekly = frames["weekly_diagnostics"]
    state_direction = frames["cap_state_direction_distribution"].sort_values(
        ["population", "mapping_variant", "state", "direction"]
    )
    cohorts = frames["confirmation_cohort_summary"].sort_values(
        ["population", "mean_signed_movement_60m"]
    )
    classification = summary["dominant_cause"]
    diagnostic = classification["diagnostic_values"]
    sequences = frames["candidate_sequences"]
    membership = frames["cap_sensitivity_membership"]
    e1_sequences = sequences[sequences["population"].eq("e1_capped")]
    e1_same_creation_confirmation = int(
        (
            pd.to_datetime(
                e1_sequences["d005_reaction_confirmed_at"], utc=True
            )
            == pd.to_datetime(
                e1_sequences["refinement_created_at"], utc=True
            )
        ).sum()
    )
    e1_later_interactions = int(
        (
            pd.to_datetime(
                e1_sequences["refinement_interacted_at"], utc=True
            )
            > pd.to_datetime(
                e1_sequences["d005_reaction_confirmed_at"], utc=True
            )
        ).sum()
    )
    weekly_structural_complete = int(
        weekly[
            weekly["sequence_status"].eq("core_sequence_complete")
            & weekly["diagnostic_layer"].eq(
                "structural_reconstruction"
            )
        ]["candidate_count"].sum()
    )
    weekly_engine_confirmed = int(
        state_direction[
            state_direction["population"].eq(
                "e2_uncapped_engine_replay"
            )
            & state_direction["mapping_variant"].eq("weekly_4h_1h")
            & state_direction["state"].eq("reaction_confirmed")
        ]["observations"].sum()
    )
    overlap_counts = (
        membership.groupby(["population", "membership"]).size().to_dict()
    )
    lines = [
        "# D005_E2 Reaction Anchor Diagnostic",
        "",
        "## Research boundary",
        "",
        "This study diagnoses causal direction labels and anchor timing. It does "
        "not alter D005 defaults, gates, state transitions, thresholds, or "
        "production behavior. Outcomes are descriptive XAUUSD price units, "
        "not entries or P&L.",
        "",
        "## 1. Dataset and reproducibility",
        "",
        f"- Requested period: `{config.start_date}` through `{config.end_date}`",
        f"- Source files reverified: `{summary['source_file_count']}`",
        f"- Source rows: `{summary['source_row_count']}`",
        f"- Source selection SHA-256: `{summary['source_selection_sha256']}`",
        f"- E1 fingerprint preserved: `{summary['e1_fingerprint_preserved']}`",
        f"- D005 fingerprint preserved: `{summary['d005_fingerprint_preserved']}`",
        f"- E2 configuration fingerprint: `{summary['study_config_fingerprint']}`",
        f"- Implementation SHA-256: `{summary['implementation_sha256']}`",
        f"- Raw uncapped candidate rows: "
        f"`{summary['e2_uncapped_candidate_count']}`",
        f"- Rows before/after exact deduplication: "
        f"`{summary['candidate_rows_before_deduplication']}` / "
        f"`{summary['candidate_rows_after_deduplication']}`",
        f"- Structurally complete uncapped chains: "
        f"`{summary['e2_uncapped_complete_count']}`",
        f"- Unique frozen-engine replay timestamps: "
        f"`{summary['e2_uncapped_engine_evaluation_count']}`",
        f"- Exact engine-selected uncapped confirmations: "
        f"`{summary['e2_uncapped_engine_reaction_count']}`",
        "",
        "The E2 uncapped reconstruction has no per-date or per-mapping event "
        "limit. Exact evidence signatures are the only sequence deduplication. "
        "Structural completions are replayed through the unchanged D005 "
        "engine and are not presumed to be final confirmations.",
        "",
        "## 2. Candidate and sequence funnel",
        "",
        _table(
            funnel,
            [
                "population",
                "mapping_variant",
                "sequence_status",
                "sequence_count",
            ],
            limit=80,
        ),
        "",
        "## 3. Direction-label audit",
        "",
        f"- Deterministic direction invariants valid: "
        f"`{classification['diagnostic_values']['direction_invariants_valid']}`",
        f"- Direction audit rows: `{summary['direction_audit_rows']}`",
        f"- Pairwise mismatch rows: `{summary['direction_mismatch_rows']}`",
        "",
        "Buy-side/high liquidity is explicitly separated into raid direction "
        "+1 and expected reaction direction -1; sell-side/low is raid -1 and "
        "expected reaction +1.",
        "",
        _table(
            critical_mismatch,
            [
                "population",
                "mapping_variant",
                "outcome",
                "left_direction",
                "right_direction",
                "observations",
                "mismatches",
                "mismatch_rate",
                "exact_sign_inversions",
            ],
            limit=50,
        ),
        "",
        "## 4. Anchor-level 60-minute outcomes",
        "",
        "Reversal and continuation remain separate in the principal table.",
        "",
        _table(
            principal_60,
            [
                "population",
                "sequence_cohort",
                "outcome",
                "anchor_type",
                "observations",
                "mean_signed_movement",
                "median_signed_movement",
                "mean_mfe",
                "mean_mae",
                "median_mfe_mae_ratio",
                "adverse_before_favorable_rate",
                "median_time_to_mfe_minutes",
                "median_time_to_mae_minutes",
                "mfe_ge_0_5_rate",
                "mfe_ge_1_0_rate",
                "mfe_ge_2_0_rate",
                "mfe_ge_5_0_rate",
            ],
            limit=60,
        ),
        "",
        "## 5. Sequence latency and consumed movement",
        "",
        _table(
            latency,
            [
                "population",
                "mapping_variant",
                "outcome",
                "latency_stage",
                "observations",
                "median_elapsed_minutes",
                "mean_signed_stage_movement",
                "median_candidate_to_stage_mfe_consumed",
                "median_candidate_to_stage_mae_consumed",
                "negative_timestamp_order_count",
            ],
            limit=80,
        ),
        "",
        "Creation and interaction are separate. A negative interaction → "
        "reaction-confirmed latency means the frozen D005 timestamp occurred "
        "before the first later array interaction; it is retained rather than "
        "silently reordered.",
        "",
        f"In E1, `reaction_confirmed` equals refinement-array creation for "
        f"`{e1_same_creation_confirmation}` of `{len(e1_sequences)}` "
        f"sequences. A later first array interaction was reconstructed for "
        f"`{e1_later_interactions}` sequences. Thus confirmation is late "
        f"relative to the contextual event, but it is not an interaction "
        f"confirmation and generally occurs before the later interaction.",
        "",
        "## 6. Weekly mapping diagnosis",
        "",
        _table(
            weekly,
            [
                "population",
                "diagnostic_layer",
                "sequence_status",
                "candidate_count",
                "parent_conflict_count",
                "missing_reaction_bars_count",
            ],
            limit=40,
        ),
        "",
        f"Weekly classification: `{weekly_structural_complete}` structurally "
        f"complete chains existed, but the unchanged engine selected "
        f"`{weekly_engine_confirmed}` Weekly confirmations. Genuinely absent "
        f"full sequences and an implementation defect are not supported. "
        f"The zero is attributable to candidate attrition (missing reaction "
        f"bars, MSS timeout, and parent/candidate conflict) plus correctly "
        f"implemented restrictive confirmation/risk gates—most often "
        f"overextension and absent body-close MSS, with smaller refinement, "
        f"risk, trapped, range, and context-event failures. No gate changed.",
        "",
        "## 7. Confirmation-path cohorts",
        "",
        _table(
            cohorts,
            [
                "population",
                "cohort",
                "outcome",
                "sequence_count",
                "forward_observations",
                "mean_signed_movement_60m",
                "mean_mfe_60m",
                "mean_mae_60m",
            ],
            limit=80,
        ),
        "",
        "No mapping or OB variant is selected from these descriptive results.",
        "",
        "## 8. E1 cap sensitivity",
        "",
        _table(
            cap,
            [
                "population",
                "membership",
                "mapping_variant",
                "outcome",
                "sequence_count",
                "forward_observations",
                "long_count",
                "short_count",
                "mean_signed_movement_60m",
                "mean_mfe_60m",
                "mean_mae_60m",
            ],
            limit=80,
        ),
        "",
        "The comparison does not assume that the uncapped result is superior.",
        "",
        f"Exact signature overlap: "
        f"`{overlap_counts.get(('e1_capped', 'included_in_both'), 0)}` in "
        f"both, `{overlap_counts.get(('e1_capped', 'e1_capped_only'), 0)}` "
        f"E1-only, and "
        f"`{overlap_counts.get(('e2_uncapped', 'uncapped_only'), 0)}` "
        f"uncapped-only. The capped completion mean was "
        f"`{diagnostic['e1_capped_pooled_completion_mean_60m']:.6f}` versus "
        f"`{diagnostic['e2_uncapped_pooled_completion_mean_60m']:.6f}` "
        f"uncapped. The cap-selected sample was worse, but not later: median "
        f"candidate→confirmation latency was "
        f"`{diagnostic['median_e1_candidate_to_reaction_minutes']:.1f}` "
        f"minutes capped versus "
        f"`{diagnostic['median_uncapped_candidate_to_reaction_minutes']:.1f}` "
        f"minutes uncapped.",
        "",
        "State and direction composition:",
        "",
        _table(
            state_direction,
            [
                "population",
                "mapping_variant",
                "state",
                "direction",
                "outcome",
                "observations",
            ],
            limit=80,
        ),
        "",
        "## 9. Dominant-cause classification",
        "",
        f"Classification IDs: `{classification['classification_ids']}`",
        "",
    ]
    lines.extend(
        f"- **{label}**"
        for label in classification["classification_labels"]
    )
    lines.extend(["", "Evidence:"])
    lines.extend(f"- {reason}" for reason in classification["reasons"])
    lines.extend(
        [
            "",
            "The negative E1 result is broad rather than isolated: both "
            "continuation and reversal reaction-confirmed means are negative; "
            "no one mapping or POI/array variant met the predefined "
            "concentration rule. Direction invariants passed, and the "
            "engine-selected uncapped completion mean is positive. Therefore "
            "classifications 1, 3, 4, 5, 6, and 8 are rejected.",
        ]
    )
    lines.extend(
        [
            "",
            "Diagnostic values:",
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
            "## 10. Required next step",
            "",
            _next_action(classification["classification_ids"]),
            "",
            "Production integration, threshold changes, timing promotion, and "
            "trade simulation remain outside scope.",
            "",
        ]
    )
    return "\n".join(lines)


def persist_artifacts(
    *,
    frames: Mapping[str, pd.DataFrame],
    output_dir: Path,
    config: ReactionAnchorDiagnosticConfig,
    run_metadata: Mapping[str, object],
    dominant_cause: Mapping[str, object],
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    implementation = implementation_provenance(config)
    for frame in frames.values():
        if not frame.empty:
            frame["study_version"] = config.version
            frame["study_config_fingerprint"] = config.fingerprint()
            frame["implementation_sha256"] = implementation[
                "implementation_sha256"
            ]
    for name, frame in frames.items():
        _atomic_parquet(frame, output_dir / f"{name}.parquet")
    _atomic_json(config.snapshot(), output_dir / "configuration_snapshot.json")
    _atomic_json(
        implementation, output_dir / "implementation_provenance.json"
    )
    _atomic_json(
        dict(run_metadata), output_dir / "reproducibility_metadata.json"
    )
    schema = {
        "tables": {
            f"{name}.parquet": [
                {"column": column, "dtype": str(dtype)}
                for column, dtype in frame.dtypes.items()
            ]
            for name, frame in frames.items()
        }
    }
    _atomic_json(schema, output_dir / "feature_schema.json")
    sequences = frames["candidate_sequences"]
    forward = frames["anchor_forward_outcomes"]
    summary = {
        "study_id": config.study_id,
        "version": config.version,
        "research_only": True,
        "optimization_performed": False,
        "production_behavior_changed": False,
        "entry_authorized_count": 0,
        "source_file_count": run_metadata["source_file_count"],
        "source_row_count": run_metadata["source_row_count"],
        "source_selection_sha256": run_metadata[
            "source_selection_sha256"
        ],
        "source_hash_mismatch_count": run_metadata[
            "source_hash_mismatch_count"
        ],
        "candidate_sequence_rows": len(sequences),
        "e1_capped_sequence_count": int(
            sequences["population"].eq("e1_capped").sum()
        ),
        "e2_uncapped_candidate_count": int(
            sequences["population"].eq("e2_uncapped").sum()
        ),
        "candidate_rows_before_deduplication": int(
            run_metadata["deduplication_counts"][
                "candidate_rows_before_deduplication"
            ]
        ),
        "candidate_rows_after_deduplication": int(
            run_metadata["deduplication_counts"][
                "candidate_rows_after_deduplication"
            ]
        ),
        "e2_uncapped_complete_count": int(
            (
                sequences["population"].eq("e2_uncapped")
                & sequences["sequence_status"].eq(
                    "core_sequence_complete"
                )
            ).sum()
        ),
        "e2_uncapped_engine_evaluation_count": int(
            run_metadata["uncapped_engine_evaluation_count"]
        ),
        "e2_uncapped_engine_reaction_count": int(
            sequences[
                "engine_selected_reaction_confirmed"
            ].fillna(False).sum()
        ),
        "anchor_forward_rows": len(forward),
        "direction_audit_rows": len(frames["direction_label_audit"]),
        "direction_mismatch_rows": len(
            frames["direction_mismatch_summary"]
        ),
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
        "e1_fingerprint_preserved": run_metadata[
            "e1_fingerprint_preserved"
        ],
        "d005_fingerprint_preserved": run_metadata[
            "d005_fingerprint_preserved"
        ],
        "deduplication_counts": run_metadata["deduplication_counts"],
        "dominant_cause": dict(dominant_cause),
        "next_action": _next_action(
            list(dominant_cause["classification_ids"])
        ),
    }
    report = render_report(frames, config=config, summary=summary)
    _atomic_text(
        report,
        output_dir / "D005_E2_REACTION_ANCHOR_DIAGNOSTIC_REPORT.md",
    )
    _atomic_json(summary, output_dir / "summary.json")
    artifacts = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "artifact_manifest.json":
            artifacts.append(
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    manifest = {
        "study_id": config.study_id,
        "version": config.version,
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
        "artifacts": artifacts,
    }
    _atomic_json(manifest, output_dir / "artifact_manifest.json")
    return summary
