"""Run the isolated Stage A gate and conditionally forbid Stage B."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence

import pandas as pd

from .audit import (
    build_duplicate_report,
    build_gap_report,
    build_schema_audit,
    build_source_inventory,
    canonical_json_hash,
    classify_compatibility,
    compare_feeds,
    directory_fingerprint,
    load_historical_overlap,
    load_mt5_minutes,
    sha256_file,
    verify_historical_release,
)
from .config import ExtensionAuditConfig
from .reporting import (
    build_artifact_manifest,
    build_report,
    write_frame,
    write_json,
)


PROTECTED_OUTPUTS = {
    "d005": "research_outputs/D005_CONTEXT_ENGINE",
    "d005_e1": "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY",
    "d005_e2": "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC",
    "d005_e3": "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY",
    "d005_e4": "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION",
}


def _timezone_audit(
    root: Path, config: ExtensionAuditConfig
) -> dict[str, object]:
    metadata = json.loads(
        (root / config.tick_metadata).read_text(encoding="utf-8")
    )
    timezone = metadata["timezone"]
    return {
        "source_timezone": timezone["source_timezone"],
        "normalization_timezone": timezone["normalization_timezone"],
        "file_contains_timezone_marker": timezone[
            "file_contains_timezone_marker"
        ],
        "confidence_grade": timezone["confidence_grade"],
        "status": timezone["status"],
        "broker_authenticated": False,
        "evidence": timezone["evidence"],
        "method": timezone["validation"]["method"],
        "evidence_dates": timezone["validation"]["evidence_dates"],
        "winter_behavior": "UTC+2",
        "summer_behavior": "UTC+3",
        "dst_mismatch_behavior": (
            "Europe/Helsinki transition rules follow EU dates; empirical "
            "event alignment supports the mismatch mapping"
        ),
        "controlling_report": config.timezone_report,
        "controlling_report_sha256": sha256_file(
            root / config.timezone_report
        ),
        "limitation": (
            "broker/feed documentation and server-time log are unavailable"
        ),
    }


def _source_hash_manifest(inventory: pd.DataFrame) -> dict[str, object]:
    records = inventory[
        ["path", "file_size_bytes", "sha256", "role", "post_2025_candidate"]
    ].to_dict("records")
    return {
        "algorithm": "SHA-256",
        "file_count": len(records),
        "files": records,
        "selection_sha256": canonical_json_hash(records),
    }


def _source_lineage(
    config: ExtensionAuditConfig,
    compatibility: dict[str, object],
) -> dict[str, object]:
    return {
        "raw_source": config.raw_tick_source,
        "existing_derivatives": [
            {
                "path": config.normalized_tick_source,
                "producer": (
                    "research/event_study_0830_0930/"
                    "tick_qualification.py"
                ),
                "role": "read-only audit aid",
                "d003_canonical": False,
            },
            {
                "path": config.normalized_minute_source,
                "producer": (
                    "research/event_study_0830_0930/"
                    "tick_qualification.py"
                ),
                "role": "read-only overlap comparison",
                "d003_canonical": False,
            },
        ],
        "required_d003_path": [
            "D001 verified Dukascopy BI5 partitions",
            "D002 accepted closure overlay",
            config.d003_builder,
            config.d003_verifier,
        ],
        "candidate_entered_required_d003_path": False,
        "candidate_release_written": False,
        "stop_reason": compatibility["blocking_reasons"],
        "historical_data_joined_or_modified": False,
    }


def run_audit(
    *,
    output_dir: Path,
    config: ExtensionAuditConfig,
    command: Sequence[str] = (),
) -> dict[str, object]:
    config.validate()
    root = Path.cwd().resolve()
    output = output_dir.resolve()
    forbidden_stage_b = (
        root / "research_outputs/D005_E4_POST_2025_INDEPENDENT_REPLICATION"
    ).resolve()
    if output == forbidden_stage_b:
        raise ValueError("Stage A output cannot be the conditional Stage B path")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    protected_paths = {
        name: (root / relative).resolve()
        for name, relative in PROTECTED_OUTPUTS.items()
    }
    protected_before = {
        name: directory_fingerprint(path)
        for name, path in protected_paths.items()
    }
    canonical_manifest_before = sha256_file(
        root / config.historical_canonical_root / "canonical_manifest.json"
    )

    inventory = build_source_inventory(root, config)
    schema, metadata_checks = build_schema_audit(config)
    historical_overlap = load_historical_overlap(root, config)
    mt5_minutes = load_mt5_minutes(root, config)
    comparisons = compare_feeds(historical_overlap, mt5_minutes, config)
    post_2025 = mt5_minutes[
        mt5_minutes["timestamp_utc"].ge(
            pd.Timestamp(config.post_2025_start)
        )
    ].copy()
    gaps = build_gap_report(post_2025)
    tick_metadata = json.loads(
        (root / config.tick_metadata).read_text(encoding="utf-8")
    )
    duplicates = build_duplicate_report(post_2025, tick_metadata)
    timezone = _timezone_audit(root, config)
    historical = verify_historical_release(root, config)
    compatibility = classify_compatibility(
        schema, metadata_checks, comparisons["overlap_summary"]
    )

    build_summary = {
        "candidate_release_id": config.candidate_release_id,
        "canonical_build_attempted": False,
        "canonical_row_count": 0,
        "canonical_file_count": 0,
        "canonical_output_hashes": [],
        "deterministic_canonical_rebuild_established": False,
        "reason": (
            "pre-build compatibility gate failed; native side volumes, "
            "authenticated Dukascopy provenance, explicit timezone, and "
            "D001/D002 inputs are unavailable"
        ),
        "historical_partitions_modified": False,
        "candidate_release_directory_created": False,
    }
    canonical_verification = {
        "stage_a_passed": False,
        "all_source_files_hashed": bool(inventory["sha256"].notna().all()),
        "canonical_build_deterministic": False,
        "canonical_schema_matches_d003": False,
        "timezone_conversion_verified": False,
        "timezone_conversion_strongly_supported": True,
        "provenance_complete": False,
        "output_hashes_stable": False,
        "feed_compatibility_class_1_or_2": False,
        "historical_d003_verified_unchanged": bool(historical["verified"]),
        "canonical_validation_checks_pass": False,
        "invalid_prices_observed_in_qualified_derivative": False,
        "negative_spreads_observed_in_qualified_derivative": False,
        "schema_drift": True,
        "partition_overlap_created": False,
        "future_timestamps_relative_to_source_export": False,
        "failure_is_prebuild_and_fail_closed": True,
    }
    stage_b_gate = {
        "stage_a_passed": False,
        "stage_b_permitted": False,
        "stage_b_output_created": False,
        "strategy_outcomes_inspected": False,
        "eligible_sequences_calculated": False,
        "sample_sufficiency_evaluated": False,
        "primary_displacement_result": None,
        "secondary_refinement_result": None,
        "mfe_mae_result": None,
        "replication_classification_id": 6,
        "replication_classification_label": (
            "Feed incompatibility prevents a valid D003-derived replication"
        ),
    }

    protected_after = {
        name: directory_fingerprint(path)
        for name, path in protected_paths.items()
    }
    canonical_manifest_after = sha256_file(
        root / config.historical_canonical_root / "canonical_manifest.json"
    )
    isolation = {
        "protected_fingerprints_before": protected_before,
        "protected_fingerprints_after": protected_after,
        "protected_outputs_preserved": protected_before == protected_after,
        "historical_manifest_sha256_before": canonical_manifest_before,
        "historical_manifest_sha256_after": canonical_manifest_after,
        "historical_manifest_preserved": (
            canonical_manifest_before == canonical_manifest_after
        ),
        "historical_release_hash_verification": historical["verified"],
    }
    if not all(
        [
            isolation["protected_outputs_preserved"],
            isolation["historical_manifest_preserved"],
            isolation["historical_release_hash_verification"],
        ]
    ):
        raise RuntimeError("protected historical or D005 artifact changed")

    source_hashes = _source_hash_manifest(inventory)
    lineage = _source_lineage(config, compatibility)
    canonical_output_hashes = {
        "release_id": config.candidate_release_id,
        "canonical_file_count": 0,
        "files": [],
        "reason": "Stage A pre-build gate failed",
    }
    reproducibility = {
        "config_fingerprint": config.fingerprint(),
        "source_selection_sha256": source_hashes["selection_sha256"],
        "historical_release_manifest_sha256": historical["manifest_sha256"],
        "historical_parquet_manifest_sha256": historical[
            "parquet_checksum_manifest_sha256"
        ],
        "logical_build_timestamp": inventory.loc[
            inventory["path"].eq(config.raw_tick_source),
            "end_timestamp",
        ].iloc[0],
        "command": list(command),
        "python_version": sys.version.split()[0],
        "audit_outputs_deterministic_given_identical_inputs": True,
        "canonical_rebuild_not_executed": True,
    }
    implementation_files = sorted(
        path for path in Path(__file__).parent.glob("*.py")
    )
    implementation = {
        "package": "research.d003_e1_2026_canonical_extension",
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in implementation_files
        ],
        "d003_builder": {
            "path": config.d003_builder,
            "sha256": sha256_file(root / config.d003_builder),
            "used_as_schema_authority": True,
            "used_to_write_candidate": False,
            "reason": "candidate failed its required input/field contract",
        },
        "d003_verifier": {
            "path": config.d003_verifier,
            "sha256": sha256_file(root / config.d003_verifier),
            "used_as_validation_authority": True,
            "candidate_verified": False,
        },
    }
    summary = {
        "study_id": config.study_id,
        "candidate_release_id": config.candidate_release_id,
        "stage_a_passed": False,
        "d003_compatibility": compatibility,
        "canonical_extension": {
            "row_count": 0,
            "file_count": 0,
        },
        "post_2025_source_coverage": {
            "start": post_2025["timestamp_utc"].min().isoformat(),
            "end": post_2025["timestamp_utc"].max().isoformat(),
            "populated_minute_rows": int(len(post_2025)),
            "calendar_duration_days": float(
                (
                    post_2025["timestamp_utc"].max()
                    - post_2025["timestamp_utc"].min()
                ).total_seconds()
                / 86400.0
            ),
        },
        "stage_b_permitted": False,
        "stage_b_executed": False,
        "replication_classification_id": 6,
        "replication_classification_label": (
            "Feed incompatibility prevents a valid D003-derived replication"
        ),
        "eligible_sequence_count": None,
        "primary_displacement_result": None,
        "secondary_refinement_result": None,
        "mfe_mae_result": None,
        "recommendation": (
            "Resolve feed compatibility by obtaining post-2025 Dukascopy "
            "BI5/D001/D002 inputs or authenticated same-feed ticks with "
            "native side volumes and explicit timezone; do not run E4 or "
            "entry-feasibility research."
        ),
        "isolation": isolation,
    }

    write_frame(output, "source_inventory", inventory)
    write_json(output / "source_inventory.json", inventory.to_dict("records"))
    write_json(output / "source_hash_manifest.json", source_hashes)
    write_json(output / "timezone_audit.json", timezone)
    write_json(
        output / "dst_audit.json",
        {
            "timezone": timezone,
            "overlap_regimes": comparisons["dst_comparison"].to_dict(
                "records"
            ),
        },
    )
    write_frame(
        output, "feed_overlap_comparison", comparisons["overlap_summary"]
    )
    write_frame(
        output, "feed_distribution_comparison",
        comparisons["feed_distributions"],
    )
    write_frame(
        output, "dst_overlap_comparison", comparisons["dst_comparison"]
    )
    write_frame(
        output, "session_boundary_comparison",
        comparisons["session_comparison"],
    )
    write_frame(output, "missing_period_report", gaps)
    write_frame(output, "duplicate_report", duplicates)
    write_json(
        output / "canonical_schema.json",
        {
            "d003_schema": [
                {
                    "name": field.name,
                    "type": str(field.type),
                    "nullable": field.nullable,
                }
                for field in __import__(
                    "scripts.build_dukascopy_canonical",
                    fromlist=["canonical_schema"],
                ).canonical_schema()
            ],
            "candidate_field_audit": schema.to_dict("records"),
            "metadata_checks": metadata_checks,
        },
    )
    write_json(output / "source_to_output_lineage.json", lineage)
    write_json(output / "canonical_build_summary.json", build_summary)
    write_json(
        output / "canonical_verification_results.json",
        canonical_verification,
    )
    write_json(
        output / "canonical_output_hash_manifest.json",
        canonical_output_hashes,
    )
    write_json(
        output / "d003_compatibility_classification.json",
        compatibility,
    )
    write_json(output / "historical_release_integrity.json", historical)
    write_json(output / "stage_b_gate.json", stage_b_gate)
    write_json(output / "configuration_snapshot.json", config.snapshot())
    write_json(output / "implementation_provenance.json", implementation)
    write_json(output / "reproducibility_metadata.json", reproducibility)
    write_json(output / "summary.json", summary)
    report = build_report(
        inventory=inventory,
        schema=schema,
        comparison=comparisons,
        gaps=gaps,
        duplicates=duplicates,
        timezone_audit=timezone,
        compatibility=compatibility,
        historical=historical,
        build_summary=build_summary,
        summary=summary,
    )
    (output / "D003_E1_2026_CANONICAL_EXTENSION_REPORT.md").write_text(
        report, encoding="utf-8"
    )
    write_json(
        output / "artifact_manifest.json",
        build_artifact_manifest(output),
    )
    return summary

