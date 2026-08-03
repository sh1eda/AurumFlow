"""Fail-closed aggregate-only reporting review for D005_E4.

This module intentionally uses only the standard library.  It accepts the
fixed, published aggregate namespace and never discovers, decodes, or emits
event-level data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any, Mapping


E4_OUTPUT_RELATIVE = "research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION"
E5_OUTPUT_RELATIVE = "research_outputs/D005_E5_REPORTING_HARDENING"
E4_FILES = frozenset(
    {
        "artifact_manifest.json",
        "summary.json",
        "run_manifest.json",
        "statistical_validation.json",
        "secondary_diagnostics.json",
        "direction_summary.json",
        "monthly_summary.json",
        "session_summary.json",
        "paired_refinement_summary.json",
        "historical_comparison.json",
        "report.md",
    }
)
E5_FILES = frozenset(
    {"artifact_manifest.json", "audit_report.json", "run_manifest.json", "report.md"}
)
MANIFEST_NAME = "artifact_manifest.json"
QUALIFICATION = "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"
UNAVAILABLE = "UNAVAILABLE_IN_FROZEN_AGGREGATES"
ENDPOINT_REQUIRED_FIELDS = frozenset(
    {
        "structural_primary_cohort_count",
        "structurally_60m_eligible_count",
        "endpoint_complete_count",
        "excluded_count",
        "exclusion_reason_counts",
        "structural_eligibility_clause_result",
        "expected_id_vs_observed_id_equality_clause_result",
        "reported_n_is_deterministic_complete_case_subset",
    }
)
RUNTIME_METADATA_KEYS = frozenset(
    {
        "runtime_metadata",
        "run_started_at",
        "run_finished_at",
        "hostname",
        "pid",
        "elapsed_seconds",
    }
)
REQUIRED_STATUSES = {
    "integrity_status": "INTEGRITY_VERIFIED",
    "adequacy_status": "INDEPENDENT_SAMPLE_INADEQUATE",
    "primary_replication_status": "NOT_EVALUATED",
}


class ReviewError(RuntimeError):
    """Raised when the frozen aggregate-only boundary cannot be proved."""


class ArtifactCollisionError(ReviewError):
    """Raised when a non-identical output package already exists."""


def _strict_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    try:
        def reject_nonfinite(value: str) -> Any:
            raise ReviewError(f"non-finite JSON value in {path.name}: {value}")

        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewError(f"invalid JSON aggregate {path.name}: {error}") from error


def _stable_json(value: Any, *, indent: int | None = None) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(value) for value in item]
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ReviewError("non-finite values cannot be serialized exactly")
            return item
        if item is None or isinstance(item, (str, int, bool)):
            return item
        raise ReviewError(f"unsupported JSON value: {type(item).__name__}")

    return json.dumps(
        normalize(value),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":") if indent is None else None,
        indent=indent,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ReviewError(f"cannot checksum {path.name}: {error}") from error
    return digest.hexdigest()


def _without_runtime_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_runtime_metadata(item)
            for key, item in value.items()
            if str(key) not in RUNTIME_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_without_runtime_metadata(item) for item in value]
    return value


def _fingerprint(value: Mapping[str, Any]) -> str:
    return _sha256_bytes((_stable_json(_without_runtime_metadata(value)) + "\n").encode("utf-8"))


def _safe_child_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ReviewError(f"unsafe artifact path: {value!r}")
    return value


def _reject_symlinks_and_unexpected_files(source: Path) -> dict[str, Path]:
    if source.is_symlink() or not source.is_dir():
        raise ReviewError("E4 aggregate namespace must be a non-symlink directory")
    found: dict[str, Path] = {}
    for item in source.iterdir():
        if item.is_symlink():
            raise ReviewError(f"symlink is forbidden in E4 aggregate namespace: {item.name}")
        if not item.is_file():
            raise ReviewError(f"unexpected non-file in E4 aggregate namespace: {item.name}")
        if item.name not in E4_FILES:
            raise ReviewError(f"unexpected file in E4 aggregate namespace: {item.name}")
        found[item.name] = item
    if set(found) != E4_FILES:
        raise ReviewError(f"E4 aggregate namespace mismatch: expected exactly {sorted(E4_FILES)}")
    return found


def _validate_source_and_output(source: Path, output: Path) -> tuple[Path, Path]:
    if source.is_symlink() or output.is_symlink():
        raise ReviewError("symlink source or output is forbidden")
    resolved_source = source.resolve(strict=True)
    resolved_output = output.resolve(strict=False)
    if resolved_source == resolved_output or resolved_source in resolved_output.parents or resolved_output in resolved_source.parents:
        raise ReviewError("E4 source and E5 output must not overlap")
    return resolved_source, resolved_output


def _verify_e4_manifest(files: Mapping[str, Path], manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise ReviewError("E4 manifest must be an object")
    if manifest.get("manifest_self_excluded") is not True:
        raise ReviewError("E4 manifest must explicitly exclude itself")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ReviewError("E4 manifest artifacts must be a list")
    expected_names = E4_FILES - {MANIFEST_NAME}
    observed_names: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ReviewError("E4 manifest contains a non-object record")
        name = _safe_child_name(str(record.get("path", "")))
        if name in observed_names or name not in expected_names:
            raise ReviewError(f"E4 manifest has unexpected artifact record: {name}")
        observed_names.add(name)
        path = files[name]
        if record.get("bytes") != path.stat().st_size or record.get("sha256") != _sha256_file(path):
            raise ReviewError(f"E4 artifact checksum mismatch: {name}")
    if observed_names != expected_names:
        raise ReviewError("E4 manifest does not checksum the exact aggregate file set")


def _require_statuses(summary: Mapping[str, Any], run_manifest: Mapping[str, Any]) -> None:
    for key, expected in REQUIRED_STATUSES.items():
        if summary.get(key) != expected or run_manifest.get(key) != expected:
            raise ReviewError(f"frozen E4 status mismatch for {key}")


def _load_verified_e4(source: Path) -> dict[str, Any]:
    files = _reject_symlinks_and_unexpected_files(source)
    json_data = {
        name: _strict_json(path)
        for name, path in files.items()
        if name.endswith(".json")
    }
    manifest = json_data[MANIFEST_NAME]
    summary = json_data["summary.json"]
    run_manifest = json_data["run_manifest.json"]
    if not isinstance(summary, Mapping) or not isinstance(run_manifest, Mapping):
        raise ReviewError("E4 summary and run manifest must be objects")
    _verify_e4_manifest(files, manifest)
    _require_statuses(summary, run_manifest)
    summary_without_fingerprint = dict(summary)
    summary_fingerprint = summary_without_fingerprint.pop("deterministic_result_fingerprint", None)
    scientific_core = {
        "study_id": run_manifest.get("study_id"),
        "accepted_interval": run_manifest.get("accepted_interval"),
        "structural_inventory_fingerprint": run_manifest.get("structural_inventory_fingerprint"),
        "result": summary_without_fingerprint,
    }
    recomputed = _fingerprint(scientific_core)
    fingerprints = {
        "summary": summary_fingerprint,
        "run_manifest": run_manifest.get("deterministic_result_fingerprint"),
        "artifact_manifest": manifest.get("scientific_result_fingerprint"),
        "recomputed": recomputed,
    }
    if any(not isinstance(value, str) or value != recomputed for value in fingerprints.values()):
        raise ReviewError("E4 deterministic scientific fingerprint mismatch")
    return {
        "files": files,
        "json": json_data,
        "summary": summary,
        "run_manifest": run_manifest,
        "manifest": manifest,
        "scientific_fingerprint": recomputed,
    }


def _qualified(value: Any) -> dict[str, Any]:
    return {
        "source_value": value,
        "qualification": QUALIFICATION,
    }


def _qualified_tree(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _qualified_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_qualified_tree(item) for item in value]
    return _qualified(value)


def _mapping_value(value: Mapping[str, Any], key: str) -> Any:
    if key not in value:
        raise ReviewError(f"required frozen aggregate field is absent: {key}")
    return value[key]


def classify_endpoint_audit(required_evidence: Mapping[str, Any]) -> str:
    """Classify reporting completeness from the eight fixed evidence fields."""

    if set(required_evidence) != ENDPOINT_REQUIRED_FIELDS:
        raise ReviewError(
            "endpoint audit classification requires the exact eight evidence fields"
        )
    available = sum(value != UNAVAILABLE for value in required_evidence.values())
    if available == len(required_evidence):
        return "AUDIT_COMPLETE"
    if available == 0:
        return "AUDIT_INCOMPLETE"
    return "AUDIT_PARTIALLY_COMPLETE"


def build_audit_report(source: Path) -> dict[str, Any]:
    """Validate frozen E4 aggregates and build a descriptive-only E5 audit."""

    loaded = _load_verified_e4(source)
    summary = loaded["summary"]
    run_manifest = loaded["run_manifest"]
    primary = _mapping_value(summary, "primary_registered_metrics")
    if not isinstance(primary, Mapping):
        raise ReviewError("primary_registered_metrics must be an object")
    endpoint_count = _mapping_value(primary, "sample_count")
    required_coverage = _mapping_value(summary.get("registered_checks", {}), "required_endpoint_coverage")
    implementation_fingerprint = _mapping_value(run_manifest, "outcome_implementation_fingerprint")
    if endpoint_count != 156:
        raise ReviewError("frozen endpoint-complete count must be exactly 156")
    if required_coverage is not False:
        raise ReviewError("frozen required endpoint coverage must be false")
    if not isinstance(implementation_fingerprint, str) or not implementation_fingerprint:
        raise ReviewError("frozen outcome implementation fingerprint is invalid")
    evidence = {
        name: _qualified_tree(value)
        for name, value in sorted(loaded["json"].items())
    }
    endpoint_evidence = {
        "structural_primary_cohort_count": UNAVAILABLE,
        "structurally_60m_eligible_count": UNAVAILABLE,
        "endpoint_complete_count": {
            **_qualified(endpoint_count),
            "source_label": "FROZEN_AGGREGATE_COMPLETE_CASE_SUBSET_COUNT",
        },
        "excluded_count": UNAVAILABLE,
        "exclusion_reason_counts": UNAVAILABLE,
        "structural_eligibility_clause_result": UNAVAILABLE,
        "expected_id_vs_observed_id_equality_clause_result": UNAVAILABLE,
        "reported_n_is_deterministic_complete_case_subset": _qualified(True),
    }
    return {
        "schema_version": "d005-e5-reporting-hardening-v1",
        "source_study_id": _qualified(_mapping_value(run_manifest, "study_id")),
        "source_accepted_interval": _qualified_tree(
            _mapping_value(run_manifest, "accepted_interval")
        ),
        "source_scientific_fingerprint": _qualified(loaded["scientific_fingerprint"]),
        "source_artifact_manifest_sha256": _qualified(
            _sha256_file(loaded["files"][MANIFEST_NAME])
        ),
        "post_outcome_reporting_hardening": True,
        "original_execution_modified": False,
        "blind_replication": False,
        "independent_replication": False,
        "scientific_decision_authorized": False,
        "all_metrics_descriptive_only": True,
        "replication_evidence_claim_permitted": False,
        "frozen_statuses": {key: _qualified(summary[key]) for key in REQUIRED_STATUSES},
        "fixed_decision_tree": {
            "integrity": _qualified(summary["integrity_status"]),
            "adequacy": _qualified(summary["adequacy_status"]),
            "terminal_status": _qualified(summary["primary_replication_status"]),
            "terminates_at": "ADEQUACY_FAILURE",
            "no_downstream_replication_decision_evaluated": True,
            "primary_evaluation": _qualified(summary["primary_replication_status"]),
            "secondary_diagnostics": QUALIFICATION,
            "a_b_c": "BLOCKED_NOT_SEPARATELY_REGISTERED",
        },
        "endpoint_audit": {
            **endpoint_evidence,
            "excluded_reasons": UNAVAILABLE,
            "required_endpoint_coverage": _qualified(required_coverage),
            "individual_structural_eligibility": UNAVAILABLE,
            "expected_vs_observed_endpoint_equality_clause": UNAVAILABLE,
            "audit_completeness_status": classify_endpoint_audit(endpoint_evidence),
            "audit_rule": "COMPLETE_ONLY_IF_ALL_REQUIRED_DENOMINATOR_COUNT_REASON_CLAUSE_SUBSET_EVIDENCE_AVAILABLE__INCOMPLETE_IF_NONE_AVAILABLE_BEYOND_ORIGINAL_CONJUNCTION__OTHERWISE_PARTIAL",
        },
        "refinement_audit": {
            "outcome_implementation_fingerprint": _qualified(implementation_fingerprint),
            "invariant_statements": [
                {
                    "statement": "distinct_timestamp_definitions",
                    "displacement_source_timestamp": "displacement_confirmation_timestamp",
                    "refinement_source_timestamp": "refinement_creation_timestamp",
                    "bound_to_outcome_implementation_fingerprint": _qualified(implementation_fingerprint),
                },
                {
                    "statement": "separate_per_anchor_deduplication",
                    "bound_to_outcome_implementation_fingerprint": _qualified(implementation_fingerprint),
                },
                {
                    "statement": "one_to_one_pairing",
                    "bound_to_outcome_implementation_fingerprint": _qualified(implementation_fingerprint),
                },
                {
                    "statement": "zero_lag_and_zero_difference_structurally_possible",
                    "bound_to_outcome_implementation_fingerprint": _qualified(implementation_fingerprint),
                },
            ],
            "zero_minute_lag_structurally_possible": _qualified(True),
            "zero_paired_difference_structurally_possible": _qualified(True),
            "zero_lag_counts": UNAVAILABLE,
            "distinct_source_counts": UNAVAILABLE,
            "independent_empirical_verification": False,
        },
        "frozen_aggregate_evidence": evidence,
    }


def _report(audit: Mapping[str, Any]) -> str:
    endpoint = audit["endpoint_audit"]
    return "\n".join(
        [
            "1. This is a post-outcome reporting hardening artifact.",
            "2. The original execution was not modified.",
            "3. Outcomes were already known before E5.",
            "4. E5 is not an independent replication.",
            "5. Scientific values are copied exactly from frozen aggregate artifacts.",
            "6. No scientific conclusion may be upgraded by this report.",
            "No numerical result constitutes replication evidence.",
            "",
            "# NOT_EVALUATED",
            "",
            "## D005_E5 Reporting Hardening",
            "",
            "All copied aggregate metrics are descriptive and non-decisional after adequacy failure. This post-outcome artifact is not blind and cannot authorize a replication conclusion.",
            "",
            "## Deterministic decision tree",
            "",
            "```text",
            "Integrity: INTEGRITY_VERIFIED",
            "  -> Adequacy: INDEPENDENT_SAMPLE_INADEQUATE [TERMINATE SCIENTIFIC EVALUATION]",
            "    -> Primary Evaluation: NOT_EVALUATED",
            "      -> Secondary Diagnostics: DESCRIPTIVE_NON_DECISIONAL only",
            "        -> A/B/C: BLOCKED_NOT_SEPARATELY_REGISTERED",
            "```",
            "",
            "## Endpoint audit",
            "",
            f"- Structural primary cohort count: `{endpoint['structural_primary_cohort_count']}`",
            f"- Structurally 60m-eligible count: `{endpoint['structurally_60m_eligible_count']}`",
            f"- Endpoint-complete count: `{endpoint['endpoint_complete_count']['source_value']}` — DESCRIPTIVE AND NON-DECISIONAL (frozen aggregate complete-case subset; not a structural denominator)",
            f"- Excluded count and reasons: `{endpoint['excluded_count']}` / `{endpoint['exclusion_reason_counts']}`",
            f"- Required endpoint coverage: `{str(endpoint['required_endpoint_coverage']['source_value']).lower()}`",
            f"- Structural-eligibility clause: `{endpoint['structural_eligibility_clause_result']}`",
            f"- Expected-ID versus observed-ID equality clause: `{endpoint['expected_id_vs_observed_id_equality_clause_result']}`",
            f"- Audit completeness: `{endpoint['audit_completeness_status']}`",
            "",
            "## Refinement audit",
            "",
            "Invariant statements are bound to the frozen outcome-implementation fingerprint. Displacement uses displacement_confirmation_timestamp; refinement uses refinement_creation_timestamp. Separate per-anchor deduplication, one-to-one pairing, and structural zero-minute-lag/zero-paired-difference possibility are implementation assertions only. Zero-lag counts, distinct-source counts, and independent empirical verification are unavailable from frozen aggregates.",
            "",
            "No numerical result constitutes replication evidence.",
            "",
        ]
    )


def _package_fingerprint(records: list[dict[str, Any]]) -> str:
    return _sha256_bytes((_stable_json(records) + "\n").encode("utf-8"))


def _manifest_from_records(
    records: list[dict[str, Any]], fingerprint: str
) -> dict[str, Any]:
    return {
        "schema_version": "d005-e5-artifact-manifest-v1",
        "deterministic_review_fingerprint": fingerprint,
        "deterministic_package_fingerprint": _package_fingerprint(records),
        "manifest_self_excluded": True,
        "manifest_self_exclusion_reason": "self-referential checksum is circular",
        "artifacts": records,
    }


def _checksum_manifest(directory: Path, fingerprint: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file() or path.name == MANIFEST_NAME:
            continue
        records.append({"path": path.name, "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    return _manifest_from_records(records, fingerprint)


def _expected_manifest(files: Mapping[str, str], fingerprint: str) -> dict[str, Any]:
    records = [
        {
            "path": name,
            "bytes": len(content.encode("utf-8")),
            "sha256": _sha256_bytes(content.encode("utf-8")),
        }
        for name, content in sorted(files.items())
    ]
    return _manifest_from_records(records, fingerprint)


def verify_e5_review(
    output: Path,
    *,
    expected_fingerprint: str | None = None,
    expected_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify an existing E5 package without writing it."""

    if output.is_symlink() or not output.is_dir():
        return {"valid": False, "reason": "missing_or_symlink_output"}
    try:
        found = {item.name: item for item in output.iterdir()}
        if set(found) != E5_FILES or any(item.is_symlink() or not item.is_file() for item in found.values()):
            return {"valid": False, "reason": "unexpected_output_file_set"}
        manifest = _strict_json(found[MANIFEST_NAME])
        run_manifest = _strict_json(found["run_manifest.json"])
        audit = _strict_json(found["audit_report.json"])
        if not isinstance(manifest, Mapping) or not isinstance(run_manifest, Mapping) or not isinstance(audit, Mapping):
            return {"valid": False, "reason": "invalid_output_json"}
        fingerprint = run_manifest.get("deterministic_review_fingerprint")
        scientific_core = {
            "source_scientific_fingerprint": audit.get("source_scientific_fingerprint"),
            "audit": audit,
        }
        if not isinstance(fingerprint, str) or fingerprint != _fingerprint(scientific_core):
            return {"valid": False, "reason": "review_fingerprint_mismatch"}
        observed = _checksum_manifest(output, fingerprint)
        if (
            manifest != observed
            or (expected_fingerprint is not None and fingerprint != expected_fingerprint)
            or (expected_manifest is not None and manifest != expected_manifest)
        ):
            return {"valid": False, "reason": "checksum_or_expected_fingerprint_mismatch"}
        return {
            "valid": True,
            "reason": None,
            "fingerprint": fingerprint,
            "package_fingerprint": manifest["deterministic_package_fingerprint"],
            "manifest": manifest,
        }
    except ReviewError:
        return {"valid": False, "reason": "invalid_output_package"}


def _write_files(stage: Path, files: Mapping[str, str]) -> None:
    for name, content in sorted(files.items()):
        if name not in E5_FILES - {MANIFEST_NAME}:
            raise ReviewError(f"unsafe E5 output artifact: {name}")
        (stage / name).write_text(content, encoding="utf-8")


def _publish_e5_review(
    source: Path, output: Path, *, verify_only: bool = False
) -> dict[str, Any]:
    """Build or verify after fixed namespaces have been resolved."""

    source, output = _validate_source_and_output(Path(source), Path(output))
    audit = build_audit_report(source)
    scientific_core = {
        "source_scientific_fingerprint": audit["source_scientific_fingerprint"],
        "audit": audit,
    }
    fingerprint = _fingerprint(scientific_core)
    run_manifest = {
        "schema_version": "d005-e5-run-manifest-v1",
        "source_study_id": audit["source_study_id"],
        "source_accepted_interval": audit["source_accepted_interval"],
        "source_scientific_fingerprint": audit["source_scientific_fingerprint"],
        "deterministic_review_fingerprint": fingerprint,
        "scientific_decision_authorized": False,
        "all_metrics_descriptive_only": True,
        "replication_evidence_claim_permitted": False,
    }
    files = {
        "audit_report.json": _stable_json(audit, indent=2) + "\n",
        "run_manifest.json": _stable_json(run_manifest, indent=2) + "\n",
        "report.md": _report(audit),
    }
    expected_manifest = _expected_manifest(files, fingerprint)
    if verify_only:
        verified = verify_e5_review(
            output,
            expected_fingerprint=fingerprint,
            expected_manifest=expected_manifest,
        )
        if not verified["valid"]:
            raise ReviewError(f"verify-only E5 package failed: {verified['reason']}")
        return {
            "published": False,
            "reused_existing": True,
            "output_dir": str(output),
            **verified,
        }
    if output.exists():
        verified = verify_e5_review(
            output,
            expected_fingerprint=fingerprint,
            expected_manifest=expected_manifest,
        )
        if verified["valid"]:
            return {"published": False, "reused_existing": True, "output_dir": str(output), **verified}
        raise ArtifactCollisionError(f"refusing to overwrite existing E5 package: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / f".{output.name}.publish.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ArtifactCollisionError(f"E5 publication is already in progress: {output}") from error
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        _write_files(stage, files)
        manifest = _checksum_manifest(stage, fingerprint)
        if manifest != expected_manifest:
            raise ReviewError("staged E5 manifest differs from deterministic expectation")
        (stage / MANIFEST_NAME).write_text(_stable_json(manifest, indent=2) + "\n", encoding="utf-8")
        if output.exists():
            verified = verify_e5_review(
                output,
                expected_fingerprint=fingerprint,
                expected_manifest=expected_manifest,
            )
            if verified["valid"]:
                return {"published": False, "reused_existing": True, "output_dir": str(output), **verified}
            raise ArtifactCollisionError(f"refusing to overwrite existing E5 package: {output}")
        os.rename(stage, output)
        verified = verify_e5_review(
            output,
            expected_fingerprint=fingerprint,
            expected_manifest=expected_manifest,
        )
        if not verified["valid"]:
            raise ReviewError("published E5 package failed verification")
        return {"published": True, "reused_existing": False, "output_dir": str(output), **verified}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        lock.rmdir()


def publish_e5_review(
    repository_root: Path, *, verify_only: bool = False
) -> dict[str, Any]:
    """Publish only from the fixed E4 namespace into the fixed E5 namespace."""

    root = Path(repository_root).resolve()
    return _publish_e5_review(
        root / E4_OUTPUT_RELATIVE,
        root / E5_OUTPUT_RELATIVE,
        verify_only=verify_only,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review fixed E4 aggregate artifacts only")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args(argv)
    root = arguments.repository_root.resolve()
    try:
        result = publish_e5_review(root, verify_only=arguments.verify_only)
    except (ReviewError, OSError) as error:
        print(f"D005_E5 reporting hardening failed closed: {error}", file=sys.stderr)
        return 2
    print(f"output_dir={result['output_dir']}")
    print("primary_replication_status=NOT_EVALUATED")
    return 0


__all__ = [
    "E4_FILES",
    "E4_OUTPUT_RELATIVE",
    "E5_OUTPUT_RELATIVE",
    "ENDPOINT_REQUIRED_FIELDS",
    "QUALIFICATION",
    "UNAVAILABLE",
    "ReviewError",
    "ArtifactCollisionError",
    "build_audit_report",
    "classify_endpoint_audit",
    "publish_e5_review",
    "verify_e5_review",
    "main",
]
