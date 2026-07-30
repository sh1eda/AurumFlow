"""Create deterministic failure artifacts from the frozen pipeline evidence."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import numbers
from pathlib import Path
from typing import Any

import pandas as pd

from research.d003_e1_2026_canonical_extension.audit import (
    directory_fingerprint,
    sha256_file,
)
from scripts.build_dukascopy_canonical import canonical_schema
from scripts.dukascopy_common import (
    Manifest,
    generate_partitions,
    load_config,
    parse_utc_boundary,
    partition_file_path,
    partition_url,
)

from .config import D003E2Config


PIPELINE_FILES = (
    "config/dukascopy_data.toml",
    "scripts/download_dukascopy_ticks.py",
    "scripts/dukascopy_common.py",
    "scripts/verify_dukascopy_downloads.py",
    "scripts/research_dukascopy_holiday_calendar.py",
    "scripts/build_dukascopy_canonical.py",
    "scripts/validate_canonical_dataset.py",
)

PROTECTED_DIRECTORIES = {
    "historical_raw": "data/raw/dukascopy/XAUUSD",
    "historical_canonical": "data/canonical/xauusd_ticks",
    "historical_release": "data/releases/d003-v1",
    "d005": "research_outputs/D005_CONTEXT_ENGINE",
    "d005_e1": "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY",
    "d005_e2": "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC",
    "d005_e3": "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY",
    "d005_e4": "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION",
    "d003_e1": "research_outputs/D003_E1_2026_CANONICAL_EXTENSION",
}

PROTECTED_FILES = {
    "source_manifest": "data/manifests/XAUUSD_ticks_manifest.json",
    "d002_calendar": "config/dukascopy_XAUUSD_holiday_calendar.json",
    "d002_audit": (
        "data/reports/D002_XAUUSD_holiday_special_hours_audit.json"
    ),
}


def _json_safe(value: object) -> object:
    """Normalize pandas/numpy missing and scalar values to strict JSON."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is pd.NA:
        return None
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            _json_safe(value),
            indent=2,
            sort_keys=True,
            default=str,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _manifest_entry_status(
    entry: dict[str, Any] | None,
) -> tuple[str, str, int]:
    if entry is None:
        return (
            "transient_download_failure",
            "not_individually_attempted_after_pool_wide_circuit_breaker",
            0,
        )
    status = str(entry.get("status") or "")
    if status == "verified":
        return "downloaded_and_hash_verified", "verified", 1 + int(
            entry.get("retry_count") or 0
        )
    if status == "expected_market_closure":
        return "market_closed", "confirmed_no_data", 1 + int(
            entry.get("retry_count") or 0
        )
    evidence = str(entry.get("evidence_kind") or "")
    if status == "failed" and evidence in {
        "connection_reset",
        "network_failure",
        "timeout",
        "proxy_failure",
        "tls_ssl_failure",
    }:
        return "transient_download_failure", evidence, 1 + int(
            entry.get("retry_count") or 0
        )
    if status == "failed" and entry.get("http_status") is not None:
        return "permanent_http_failure", evidence or "http_failure", 1 + int(
            entry.get("retry_count") or 0
        )
    if status in {"corrupt", "malformed_payload"}:
        return "corrupt_or_undecodable", status, 1 + int(
            entry.get("retry_count") or 0
        )
    return "incomplete", status or "unresolved", int(
        entry.get("retry_count") or 0
    )


def build_requested_inventory(
    root: Path, config: D003E2Config
) -> pd.DataFrame:
    pipeline = load_config(root / config.pipeline_config)
    manifest = Manifest(
        root / config.source_manifest,
        config=pipeline,
        symbol=config.symbol,
    )
    raw_root = root / config.raw_root
    partitions = generate_partitions(
        parse_utc_boundary(config.start_inclusive),
        parse_utc_boundary(config.end_exclusive),
    )
    records: list[dict[str, object]] = []
    for partition in partitions:
        entry = manifest.get(partition)
        status, detail, attempts = _manifest_entry_status(entry)
        local_path = partition_file_path(
            raw_root, config.symbol, partition
        )
        records.append(
            {
                "requested_hour": partition.key,
                "deterministic_source_identifier": partition_url(
                    pipeline, config.symbol, partition
                ),
                "final_status": status,
                "status_detail": detail,
                "http_status": (entry or {}).get("http_status"),
                "compressed_byte_count": (entry or {}).get("byte_size"),
                "compressed_sha256": (entry or {}).get("sha256"),
                "download_attempts": attempts,
                "local_source_path": local_path.relative_to(root).as_posix(),
                "local_source_exists": local_path.is_file(),
                "decoding_status": (
                    "validated"
                    if status == "downloaded_and_hash_verified"
                    else "not_decoded_no_payload"
                ),
                "decoded_row_count": (entry or {}).get("record_count"),
                "evidence_kind": (entry or {}).get("evidence_kind"),
                "error_details": (entry or {}).get("error_details"),
                "requested": True,
            }
        )
    for partition, detail in (
        (
            "2026-07-29T12:00:00Z",
            "excluded_by_one_complete_hour_publication_safety_lag",
        ),
        (
            "2026-07-29T13:00:00Z",
            "current_incomplete_hour_at_cutoff_capture",
        ),
    ):
        records.append(
            {
                "requested_hour": partition,
                "deterministic_source_identifier": None,
                "final_status": "excluded_by_cutoff",
                "status_detail": detail,
                "http_status": None,
                "compressed_byte_count": None,
                "compressed_sha256": None,
                "download_attempts": 0,
                "local_source_path": None,
                "local_source_exists": False,
                "decoding_status": "excluded_before_request",
                "decoded_row_count": None,
                "evidence_kind": None,
                "error_details": None,
                "requested": False,
            }
        )
    return pd.DataFrame.from_records(records)


def _log_summary(path: Path) -> dict[str, object]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    names = Counter(str(item.get("event")) for item in events)
    partitions = sorted(
        {
            str(item["partition"])
            for item in events
            if item.get("partition") is not None
        }
    )
    proxy_identities = set()
    for item in events:
        for field in ("previous_proxy_masked", "next_proxy_masked"):
            if item.get(field):
                proxy_identities.add(str(item[field]))
    return {
        "event_count": len(events),
        "events_by_type": dict(sorted(names.items())),
        "partitions_in_log": partitions,
        "unique_masked_proxy_routes_observed": len(proxy_identities),
        "credentials_recorded": False,
        "pool_wide_circuit_breaker_observed": bool(
            names.get("circuit_breaker_pause")
        ),
    }


def _historical_integrity(
    root: Path, output: Path
) -> dict[str, object]:
    baseline = json.loads(
        (output / "historical_freeze_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    after = {
        name: directory_fingerprint(root / path)
        for name, path in PROTECTED_DIRECTORIES.items()
    }
    after.update(
        {
            name: sha256_file(root / path)
            for name, path in PROTECTED_FILES.items()
        }
    )
    before = baseline["fingerprints"]
    comparisons = {
        name: {
            "before": before[name],
            "after": after[name],
            "preserved": before[name] == after[name],
        }
        for name in sorted(before)
    }
    return {
        "passed": all(item["preserved"] for item in comparisons.values()),
        "comparisons": comparisons,
    }


def _artifact_manifest(output: Path) -> dict[str, object]:
    records = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "artifact_manifest.json":
            continue
        records.append(
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "manifest_version": 1,
        "artifact_count": len(records),
        "files": records,
    }


def assert_isolated_paths(root: Path, config: D003E2Config) -> None:
    """Refuse task paths that could overwrite a protected historical tree."""

    root = root.resolve()
    output = (root / config.output_root).resolve()
    task_paths = {
        name: (root / getattr(config, name)).resolve()
        for name in (
            "output_root",
            "raw_root",
            "source_manifest",
            "verification_report",
            "acquisition_log",
        )
    }
    for name, path in task_paths.items():
        if name != "output_root" and not path.is_relative_to(output):
            raise ValueError(f"{name} must remain inside the isolated output root")
    protected_paths = [
        (root / path).resolve()
        for path in (*PROTECTED_DIRECTORIES.values(), *PROTECTED_FILES.values())
    ]
    for name, path in task_paths.items():
        for protected in protected_paths:
            if (
                path == protected
                or path.is_relative_to(protected)
                or protected.is_relative_to(path)
            ):
                raise ValueError(
                    f"{name} overlaps protected historical path {protected}"
                )


def finalize_failed_acquisition(
    *, root: Path, config: D003E2Config
) -> dict[str, object]:
    config.validate()
    root = root.resolve()
    assert_isolated_paths(root, config)
    output = (root / config.output_root).resolve()
    verifier = json.loads(
        (root / config.verification_report).read_text(encoding="utf-8")
    )
    historical_verifier_path = (
        output / "historical_d003_independent_verification.json"
    )
    historical_verifier = (
        json.loads(historical_verifier_path.read_text(encoding="utf-8"))
        if historical_verifier_path.is_file()
        else None
    )
    inventory = build_requested_inventory(root, config)
    requested = inventory[inventory["requested"]].copy()
    status_counts = requested["final_status"].value_counts().to_dict()
    attempted = requested["download_attempts"].gt(0)
    log_summary = _log_summary(root / config.acquisition_log)
    raw_files = sorted(
        path
        for path in (root / config.raw_root).rglob("*.bi5")
        if path.is_file()
    )
    source_hashes = {
        "source_id": "dukascopy-public-bi5",
        "raw_file_count": len(raw_files),
        "files": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in raw_files
        ],
        "source_manifest": {
            "path": config.source_manifest,
            "sha256": sha256_file(root / config.source_manifest),
        },
        "acquisition_log": {
            "path": config.acquisition_log,
            "sha256": sha256_file(root / config.acquisition_log),
        },
    }
    decoded = requested.loc[
        attempted,
        [
            "requested_hour",
            "final_status",
            "download_attempts",
            "compressed_byte_count",
            "compressed_sha256",
            "decoding_status",
            "decoded_row_count",
            "evidence_kind",
        ],
    ].copy()
    status_table = (
        inventory.groupby(
            ["requested", "final_status"], dropna=False, observed=True
        )
        .agg(
            partition_count=("requested_hour", "size"),
            individually_attempted=(
                "download_attempts",
                lambda values: int(values.gt(0).sum()),
            ),
            downloaded_bytes=(
                "compressed_byte_count",
                lambda values: int(values.fillna(0).sum()),
            ),
            decoded_rows=(
                "decoded_row_count",
                lambda values: int(values.fillna(0).sum()),
            ),
        )
        .reset_index()
    )
    schema = {
        "historical_d003_schema": [
            {
                "name": field.name,
                "type": str(field.type),
                "nullable": field.nullable,
            }
            for field in canonical_schema()
        ],
        "candidate_schema_observed": None,
        "compatible": None,
        "reason": "no authentic BI5 payload or canonical candidate exists",
        "pipeline_contract_unchanged": True,
    }
    closure_candidates = Counter()
    closure_sources: set[str] = set()
    for item in verifier["partitions"]:
        rule = item.get("closure_rule")
        if not item.get("closure_rule_matched") or not isinstance(rule, dict):
            continue
        closure_candidates[str(rule.get("rule_type") or "unknown")] += 1
        if rule.get("source_url"):
            closure_sources.add(str(rule["source_url"]))
    gap_report = {
        "requested_partition_count": config.requested_partition_count,
        "verified_partitions": 0,
        "regular_market_closures": 0,
        "holiday_closures": 0,
        "special_hours_closures": 0,
        "empty_valid_hours": 0,
        "failed_acquisition_hours": int(
            status_counts.get("transient_download_failure", 0)
        ),
        "individually_attempted_failed_hours": int(attempted.sum()),
        "unattempted_after_circuit_breaker": int((~attempted).sum()),
        "configured_but_unconfirmed_closure_candidates": {
            "total": sum(closure_candidates.values()),
            "by_rule_type": dict(sorted(closure_candidates.items())),
            "controlling_status": (
                "not accepted as closures because no source evidence was "
                "obtained"
            ),
            "reference_sources": sorted(closure_sources),
        },
        "known_holiday_partition_classifications": {
            "accepted": 0,
            "candidate_empty_payloads": 0,
            "d002_executed": False,
            "reason": (
                "D001 produced no confirmed-empty payloads; calendar facts "
                "alone cannot convert a missing download into a closure"
            ),
        },
        "unexpected_gap": {
            "start": config.start_inclusive,
            "end": config.end_exclusive,
            "hours": config.requested_partition_count,
            "reason": "authentic archive access unavailable",
        },
        "partial_boundary_days": [
            {
                "date": "2026-07-29",
                "requested_hours": 12,
                "reason": "safe cutoff at 12:00Z",
            }
        ],
        "excluded_cutoff_hours": 2,
    }
    boundary = {
        "historical_last_canonical_timestamp": (
            "2025-12-31T21:58:59.943Z"
        ),
        "candidate_first_decoded_timestamp": None,
        "candidate_last_decoded_timestamp": None,
        "candidate_first_canonical_timestamp": None,
        "candidate_last_canonical_timestamp": None,
        "historical_overlap_created": False,
        "boundary_compatibility_verified": False,
        "reason": "no source or candidate output",
    }
    lineage = {
        "source": "dukascopy-public-bi5",
        "requested_range": [
            config.start_inclusive,
            config.end_exclusive,
        ],
        "d001_download": {
            "executed": True,
            "accepted_files": 0,
            "failed_partitions": int(attempted.sum()),
            "pool_routes_exhausted": 10,
        },
        "d001_independent_verification": {
            "executed": True,
            "passed": False,
            "reconciliation": verifier["reconciliation"],
        },
        "d002": {
            "executed": False,
            "reason": "no confirmed-empty candidate; D001 gate failed",
        },
        "d003_build": {
            "executed": False,
            "reason": "D001 gate failed",
        },
        "d003_independent_verification": {
            "executed": False,
            "reason": "no canonical candidate",
        },
        "mt5_used": False,
    }
    build = {
        "release_id": config.candidate_release_id,
        "attempted": False,
        "row_count": 0,
        "file_count": 0,
        "first_canonical_timestamp": None,
        "last_canonical_timestamp": None,
        "duplicate_count": 0,
        "rejected_record_count": 0,
        "reason": "D001 acquisition and verification gate failed",
    }
    canonical_verification = {
        "executed": False,
        "passed": False,
        "errors": ["no canonical candidate exists"],
        "reason": "authentic source acquisition failed before D003",
    }
    output_hashes = {
        "release_id": config.candidate_release_id,
        "canonical_file_count": 0,
        "files": [],
        "stable_second_build": False,
        "reason": "no canonical output",
    }
    freeze = _historical_integrity(root, output)
    implementation = {
        "pipeline_files": [
            {
                "path": path,
                "sha256": sha256_file(root / path),
            }
            for path in PIPELINE_FILES
        ],
        "reporting_package": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(Path(__file__).parent.glob("*.py"))
        ],
        "frozen_pipeline_modified": False,
    }
    summary = {
        "task_id": config.task_id,
        "acquisition_period": {
            "start_inclusive": config.start_inclusive,
            "end_exclusive": config.end_exclusive,
            "capture_timestamp": config.capture_timestamp,
        },
        "requested_partitions": config.requested_partition_count,
        "successful_partitions": 0,
        "reused_partitions": 0,
        "unavailable_partitions": 0,
        "failed_partitions": config.requested_partition_count,
        "individually_attempted_failed_partitions": int(attempted.sum()),
        "not_individually_attempted_after_circuit_breaker": int(
            (~attempted).sum()
        ),
        "corrupt_partitions": 0,
        "excluded_cutoff_partitions": 2,
        "decoded_source_rows": 0,
        "canonical_rows": 0,
        "canonical_files": 0,
        "first_canonical_timestamp": None,
        "last_canonical_timestamp": None,
        "schema_compatibility": "not_evaluable_no_source",
        "source_hashes_verified": 0,
        "output_hashes_verified": 0,
        "d001_verifier_passed": False,
        "independent_canonical_verifier_executed": False,
        "historical_freeze_integrity_passed": freeze["passed"],
        "historical_independent_verifier": (
            {
                "executed": True,
                "passed": historical_verifier["passed"],
                "row_count": historical_verifier["metrics"]["row_count"],
                "canonical_file_count": historical_verifier["metrics"][
                    "canonical_file_count"
                ],
                "error_count": len(historical_verifier["errors"]),
            }
            if historical_verifier is not None
            else {"executed": False, "passed": None}
        ),
        "hard_classification_id": 4,
        "hard_classification_label": (
            "Dukascopy acquisition unavailable or incomplete beyond an "
            "acceptable level"
        ),
        "d005_e4_may_proceed": False,
        "recommendation": (
            "Resolve authentic Dukascopy archive network routing and rerun "
            "D003_E2 with the same frozen cutoff/design or a newly approved "
            "cutoff; do not run E4."
        ),
    }

    inventory.to_parquet(
        output / "requested_partition_inventory.parquet", index=False
    )
    status_table.to_parquet(
        output / "download_status_table.parquet", index=False
    )
    decoded.to_parquet(
        output / "decoded_partition_inventory.parquet", index=False
    )
    _write_json(output / "source_hash_manifest.json", source_hashes)
    _write_json(
        output / "corrupt_unavailable_partition_report.json",
        {
            "corrupt_partitions": 0,
            "legitimately_unavailable_partitions": 0,
            "failed_partitions": config.requested_partition_count,
            "attempted_failures": decoded.to_dict("records"),
            "unattempted_count": int((~attempted).sum()),
            "failure_mode": "connection_reset_all_configured_routes",
        },
    )
    _write_json(output / "gap_and_closure_report.json", gap_report)
    _write_json(output / "schema_comparison.json", schema)
    _write_json(output / "boundary_overlap_audit.json", boundary)
    _write_json(output / "source_to_output_lineage.json", lineage)
    _write_json(output / "canonical_build_summary.json", build)
    _write_json(
        output / "canonical_verification_report.json",
        canonical_verification,
    )
    _write_json(output / "output_hash_manifest.json", output_hashes)
    _write_json(
        output / "historical_freeze_integrity_report.json", freeze
    )
    _write_json(output / "configuration_snapshot.json", config.snapshot())
    _write_json(output / "implementation_fingerprint.json", implementation)
    _write_json(
        output / "reproducibility_metadata.json",
        {
            "config_fingerprint": config.fingerprint(),
            "source_manifest_sha256": source_hashes[
                "source_manifest"
            ]["sha256"],
            "acquisition_log_sha256": source_hashes[
                "acquisition_log"
            ]["sha256"],
            "log_summary": log_summary,
            "requested_inventory_rows": len(inventory),
            "frozen_pipeline_modified": False,
            "canonical_rebuild_possible": False,
        },
    )
    _write_json(output / "summary.json", summary)
    report = f"""# D003_E2 Post-2025 Dukascopy BI5 Extension

## Hard result

**Category 4 — Dukascopy acquisition unavailable or incomplete beyond an acceptable level.**

The frozen downloader obtained no HTTP response body from direct access or
any of the ten configured proxy routes. All observed failures were connection
resets. No failure was classified as a market closure.

## Frozen range

- Capture: `{config.capture_timestamp}`
- Start inclusive: `{config.start_inclusive}`
- End exclusive: `{config.end_exclusive}`
- Requested partitions: `{config.requested_partition_count}`
- Excluded cutoff partitions: `2`

## Acquisition

- Verified BI5 partitions: `0`
- Reused partitions: `0`
- Individually attempted and fully retried failures: `{int(attempted.sum())}`
- Remaining requested hours blocked after the pool-wide circuit breaker:
  `{int((~attempted).sum())}`
- Compressed source bytes: `0`
- Source SHA-256 values: `0`
- Decoded rows: `0`

Five chronological partitions plus one independent pilot partition were each
fully retried. The persistent full-range process exercised all ten configured
proxy routes, observed a reset on every route, and entered its configured
900-second pool-wide circuit breaker. The run was stopped at that terminal
evidence rather than repeating an unavailable route.

## D001 verification

`5028 expected = 0 verified + 0 closures + 5022 missing + 0 corrupt + 6 unresolved`

The reconciliation is arithmetically balanced but fails the completeness
gate. No D002 candidate empty payload exists.

The calendar rules matched `{sum(closure_candidates.values())}` requested
hours as possible maintenance/weekend candidates
(`{dict(sorted(closure_candidates.items()))}`), but none was accepted as a
closure without controlling source evidence.

## D002 and D003

D002 was not run because no source payload or confirmed-empty candidate
passed D001. D003 construction and independent canonical verification were
not run because there is no verified source set.

- Canonical rows: `0`
- Canonical files: `0`
- First/last canonical timestamp: `not available`
- Schema compatibility: `not evaluable`
- Stable output hashes: `not available`

## Freeze integrity

Historical and prior-study fingerprints preserved: `{freeze['passed']}`.
No historical raw BI5, manifest, D002 artifact, canonical partition, D003
release, D003_E1 artifact, or D005–E4 artifact changed.

The independent verifier also revalidated the frozen historical release:
`{historical_verifier['passed'] if historical_verifier else 'not run'}`.

## Decision

The frozen post-2025 E4 replication may **not** proceed. Resolve authentic
Dukascopy archive routing and rerun this acquisition task. The MT5 feed remains
excluded.
"""
    (output / "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION_REPORT.md").write_text(
        report, encoding="utf-8"
    )
    _write_json(output / "artifact_manifest.json", _artifact_manifest(output))
    return summary
