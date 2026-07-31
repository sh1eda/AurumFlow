"""Read-only, fail-closed preflight for the 2026 E4 extension."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from .config import (
    FROZEN_HISTORICAL_HASHES,
    ArtifactRequirement,
    IndependentReplication2026Config,
    artifact_requirements,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _safe_relative_path(path_text: str) -> bool:
    path = PurePosixPath(path_text)
    return bool(path_text) and not path.is_absolute() and ".." not in path.parts


def _parse_checksum_manifest(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"invalid checksum line {line_number} in {path}")
        checksum, relative = parts[0].lower(), parts[1].strip()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError(f"invalid SHA-256 at line {line_number} in {path}")
        if not _safe_relative_path(relative):
            raise ValueError(f"unsafe path at line {line_number} in {path}")
        if relative in records:
            raise ValueError(f"duplicate checksum path {relative!r} in {path}")
        records[relative] = checksum
    if not records:
        raise ValueError(f"empty checksum manifest {path}")
    return records


def _parse_release_descriptor(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"invalid release line {line_number} in {path}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in result:
            raise ValueError(f"invalid release key at line {line_number} in {path}")
        result[key] = value
    return result


def verify_release_integrity(repository_root: Path) -> dict[str, Any]:
    """Verify release metadata without opening any Parquet file."""

    root = repository_root.resolve()
    release_root = root / "data/releases/d003-v2"
    canonical_root = root / "data/canonical/xauusd_ticks_d003-v2"
    paths = {
        "release_descriptor": release_root / "RELEASE.txt",
        "release_canonical_manifest": release_root / "canonical_manifest.json",
        "canonical_manifest": canonical_root / "canonical_manifest.json",
        "full_verification": release_root / "full_verification.json",
        "parquet_checksum_manifest": release_root / "parquet_sha256.txt",
        "release_checksum_manifest": release_root / "release_sha256.txt",
    }
    errors: list[str] = []
    observed_hashes = {
        name: sha256_file(path) if path.is_file() else None
        for name, path in paths.items()
    }
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing release metadata: {name}:{path}")

    release_checksums: dict[str, str] = {}
    parquet_checksums: dict[str, str] = {}
    descriptor: dict[str, str] = {}
    canonical: dict[str, Any] = {}
    release_canonical: dict[str, Any] = {}
    verification: dict[str, Any] = {}
    try:
        if paths["release_checksum_manifest"].is_file():
            release_checksums = _parse_checksum_manifest(
                paths["release_checksum_manifest"]
            )
        if paths["parquet_checksum_manifest"].is_file():
            parquet_checksums = _parse_checksum_manifest(
                paths["parquet_checksum_manifest"]
            )
        if paths["release_descriptor"].is_file():
            descriptor = _parse_release_descriptor(paths["release_descriptor"])
        if paths["canonical_manifest"].is_file():
            canonical = _strict_json(paths["canonical_manifest"])
        if paths["release_canonical_manifest"].is_file():
            release_canonical = _strict_json(
                paths["release_canonical_manifest"]
            )
        if paths["full_verification"].is_file():
            verification = _strict_json(paths["full_verification"])
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(str(exc))

    release_members = {
        "release_canonical_manifest": (
            "data/releases/d003-v2/canonical_manifest.json"
        ),
        "full_verification": (
            "data/releases/d003-v2/full_verification.json"
        ),
        "parquet_checksum_manifest": (
            "data/releases/d003-v2/parquet_sha256.txt"
        ),
    }
    if set(release_checksums) != set(release_members.values()):
        errors.append("release checksum manifest inventory differs from contract")
    for name, relative in release_members.items():
        if release_checksums.get(relative) != observed_hashes[name]:
            errors.append(f"release checksum mismatch: {relative}")

    canonical_hash = observed_hashes["canonical_manifest"]
    release_canonical_hash = observed_hashes["release_canonical_manifest"]
    if canonical_hash != release_canonical_hash:
        errors.append("canonical and release manifest hashes differ")
    if verification.get("canonical_manifest_sha256") != canonical_hash:
        errors.append("verification canonical manifest hash mismatch")
    if descriptor.get("parquet_checksum_manifest_sha256") != observed_hashes[
        "parquet_checksum_manifest"
    ]:
        errors.append("release descriptor Parquet manifest hash mismatch")

    date_range = canonical.get("date_range", {})
    expected_contract = {
        "status": canonical.get("status") == "complete",
        "dataset_version": canonical.get("dataset_version") == "d003-v2",
        "symbol": canonical.get("symbol") == "XAUUSD",
        "start": date_range.get("start_inclusive")
        == "2021-01-01T00:00:00Z",
        "end": date_range.get("end_exclusive") == "2026-07-29T00:00:00Z",
        "verification_passed": verification.get("passed") is True,
        "verification_errors_empty": verification.get("errors") == [],
        "reconciliation_balanced": canonical.get("reconciliation", {}).get(
            "balanced"
        )
        is True,
        "duplicate_count_zero": canonical.get("duplicate_count") == 0,
        "rejected_record_count_zero": canonical.get("rejected_record_count")
        == 0,
        "release_id": descriptor.get("release_id") == "d003-v2",
        "release_symbol": descriptor.get("symbol") == "XAUUSD",
        "release_start": descriptor.get("start_utc")
        == "2021-01-01T00:00:00Z",
        "release_end": descriptor.get("end_utc")
        == "2026-07-29T00:00:00Z",
        "release_verification_passed": descriptor.get(
            "verification_passed"
        )
        == "true",
        "release_verification_errors_zero": descriptor.get(
            "verification_errors"
        )
        == "0",
        "release_duplicate_count_zero": descriptor.get("duplicate_count")
        == "0",
        "release_rejected_record_count_zero": descriptor.get(
            "rejected_record_count"
        )
        == "0",
    }
    for name, passed in expected_contract.items():
        if not passed:
            errors.append(f"canonical contract check failed: {name}")

    if canonical and release_canonical and canonical != release_canonical:
        errors.append("canonical and release manifest JSON differ")
    if verification:
        for key in ("dataset_id", "dataset_version", "symbol", "date_range"):
            if verification.get(key) != canonical.get(key):
                errors.append(f"verification field mismatch: {key}")

    file_records = canonical.get("files", [])
    canonical_checksums: dict[str, str] = {}
    declared_sizes: dict[str, int] = {}
    if not isinstance(file_records, list):
        errors.append("canonical files field is not a list")
        file_records = []
    for index, record in enumerate(file_records):
        if not isinstance(record, dict):
            errors.append(f"invalid canonical file record at index {index}")
            continue
        relative = record.get("path")
        checksum = record.get("sha256")
        byte_size = record.get("byte_size")
        if (
            not isinstance(relative, str)
            or not _safe_relative_path(relative)
            or not relative.startswith(
                "data/canonical/xauusd_ticks_d003-v2/"
            )
            or not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
            or not isinstance(byte_size, int)
        ):
            errors.append(f"invalid canonical file record at index {index}")
            continue
        if relative in canonical_checksums:
            errors.append(f"duplicate canonical file path: {relative}")
            continue
        canonical_checksums[relative] = checksum
        declared_sizes[relative] = byte_size

    if canonical_checksums != parquet_checksums:
        errors.append("Parquet checksum manifest differs from canonical manifest")
    if list(canonical_checksums) != list(parquet_checksums):
        errors.append("Parquet checksum manifest order differs from canonical manifest")
    declared_count = canonical.get("canonical_file_count")
    if declared_count != len(canonical_checksums):
        errors.append("canonical file count does not match file records")
    try:
        if descriptor and int(descriptor.get("parquet_files", "-1")) != len(
            canonical_checksums
        ):
            errors.append("release descriptor Parquet count mismatch")
        if descriptor and int(descriptor.get("rows", "-1")) != canonical.get(
            "row_count"
        ):
            errors.append("release descriptor row count mismatch")
    except ValueError:
        errors.append("release descriptor count is not an integer")
    metrics = verification.get("metrics", {})
    if metrics:
        if metrics.get("canonical_file_count") != declared_count:
            errors.append("verification canonical file count mismatch")
        if metrics.get("row_count") != canonical.get("row_count"):
            errors.append("verification row count mismatch")

    missing_files: list[str] = []
    size_mismatches: list[str] = []
    for relative, expected_size in declared_sizes.items():
        path = root / relative
        if not path.is_file():
            missing_files.append(relative)
        elif path.stat().st_size != expected_size:
            size_mismatches.append(relative)
    if missing_files:
        errors.append(f"declared Parquet files missing: {len(missing_files)}")
    if size_mismatches:
        errors.append(f"declared Parquet file sizes differ: {len(size_mismatches)}")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in canonical_root.rglob("*.parquet")
        if path.is_file()
    } if canonical_root.is_dir() else set()
    if actual_paths != set(canonical_checksums):
        errors.append("actual Parquet path inventory differs from manifest")

    return {
        "metadata_and_manifest_integrity_verified": not errors,
        "errors": errors,
        "observed_sha256": observed_hashes,
        "release_checksum_entry_count": len(release_checksums),
        "parquet_checksum_entry_count": len(parquet_checksums),
        "canonical_file_record_count": len(canonical_checksums),
        "actual_parquet_path_count": len(actual_paths),
        "independent_2026_parquet_path_count": sum(
            1
            for relative in actual_paths
            if "/year=2026/" in f"/{relative}"
        ),
        "missing_declared_file_count": len(missing_files),
        "file_size_mismatch_count": len(size_mismatches),
        "parquet_file_content_hashes_verified": False,
        "parquet_files_opened": 0,
    }


def verify_registered_artifact_directory(path: Path) -> dict[str, Any]:
    """Hash every file registered by one historical artifact manifest."""

    manifest_path = path / "artifact_manifest.json"
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    if not manifest_path.is_file():
        errors.append(f"artifact manifest missing: {manifest_path}")
    else:
        try:
            payload = _strict_json(manifest_path)
            raw_records = payload.get("artifacts")
            if not isinstance(raw_records, list):
                errors.append("artifact manifest records are not a list")
            else:
                records = raw_records
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))

    seen: set[str] = set()
    verified_count = 0
    parquet_files_hashed = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"invalid artifact record at index {index}")
            continue
        relative = record.get("path")
        expected_hash = record.get("sha256")
        expected_size = record.get("bytes")
        if (
            not isinstance(relative, str)
            or PurePosixPath(relative).name != relative
            or relative in seen
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            or not isinstance(expected_size, int)
        ):
            errors.append(f"invalid artifact record at index {index}")
            continue
        seen.add(relative)
        artifact = path / relative
        if not artifact.is_file():
            errors.append(f"registered artifact missing: {relative}")
            continue
        if artifact.stat().st_size != expected_size:
            errors.append(f"registered artifact size mismatch: {relative}")
            continue
        observed_hash = sha256_file(artifact)
        if artifact.suffix == ".parquet":
            parquet_files_hashed += 1
        if observed_hash != expected_hash:
            errors.append(f"registered artifact hash mismatch: {relative}")
            continue
        verified_count += 1

    actual_files = {
        item.name
        for item in path.iterdir()
        if item.is_file() and item.name != "artifact_manifest.json"
    } if path.is_dir() else set()
    if actual_files != seen:
        errors.append("artifact directory inventory differs from manifest")
    return {
        "path": str(path),
        "artifact_manifest_sha256": (
            sha256_file(manifest_path) if manifest_path.is_file() else None
        ),
        "registered_artifact_count": len(records),
        "verified_artifact_count": verified_count,
        "parquet_files_hashed": parquet_files_hashed,
        "all_registered_hashes_verified": not errors,
        "errors": errors,
    }


def _git_commit(repository_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _artifact_status(
    repository_root: Path,
    requirement: ArtifactRequirement,
) -> dict[str, Any]:
    path = repository_root / requirement.path
    present = path.is_file() if requirement.kind == "file" else path.is_dir()
    missing_children: list[str] = []
    child_sha256: dict[str, str | None] = {}
    parquet_file_count: int | None = None
    if present and requirement.required_children:
        missing_children = [
            child
            for child in requirement.required_children
            if not (path / child).is_file()
        ]
        child_sha256 = {
            child: (
                sha256_file(path / child)
                if (path / child).is_file()
                and not child.endswith(".parquet")
                else None
            )
            for child in requirement.required_children
        }
    if present and requirement.kind == "parquet_tree":
        parquet_file_count = sum(1 for _ in path.rglob("*.parquet"))
    complete = bool(
        present
        and not missing_children
        and (
            requirement.kind != "parquet_tree"
            or bool(parquet_file_count)
        )
    )
    return {
        "artifact_name": requirement.name,
        "expected_path": requirement.path,
        "source_of_expectation": requirement.source_of_expectation,
        "tracked_by_git": requirement.tracked_by_git,
        "managed_by_git_lfs": requirement.managed_by_git_lfs,
        "present": present,
        "complete": complete,
        "required_for_2026_replication": requirement.required,
        "safe_restoration_method": requirement.safe_restoration_method,
        "missing_required_children": missing_children,
        "required_child_sha256": child_sha256,
        "parquet_file_count": parquet_file_count,
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def _historical_integrity(repository_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for relative, expected in FROZEN_HISTORICAL_HASHES.items():
        path = repository_root / relative
        observed = sha256_file(path) if path.is_file() else None
        records.append(
            {
                "path": relative,
                "expected_sha256": expected,
                "observed_sha256": observed,
                "verified": observed == expected,
            }
        )
    return {
        "files": records,
        "all_verified": all(record["verified"] for record in records),
    }


def build_preflight_result(
    *,
    repository_root: Path,
    config: IndependentReplication2026Config,
) -> dict[str, Any]:
    """Inspect metadata only and never create an output or load market data."""

    config.validate()
    root = repository_root.resolve()
    artifacts = [
        _artifact_status(root, requirement)
        for requirement in artifact_requirements()
    ]
    required_present = all(
        record["complete"]
        for record in artifacts
        if record["required_for_2026_replication"]
    )
    historical = _historical_integrity(root)
    release_integrity = verify_release_integrity(root)
    protected_integrity: dict[str, dict[str, Any]] = {}
    for requirement in artifact_requirements():
        if requirement.name in {
            "protected_d005_outputs",
            "protected_d005_e1_outputs",
            "protected_d005_e2_outputs",
            "protected_d005_e3_outputs",
            "historical_d005_e4_outputs",
        }:
            protected_integrity[requirement.name] = (
                verify_registered_artifact_directory(root / requirement.path)
            )
    protected_verified = bool(protected_integrity) and all(
        result["all_registered_hashes_verified"]
        for result in protected_integrity.values()
    )
    historical_spec = root / config.historical_spec
    extension_spec = root / config.extension_spec
    output = config.resolved_output(root)
    reasons: list[str] = []
    for record in artifacts:
        if record["required_for_2026_replication"] and not record["complete"]:
            reasons.append(f"MISSING_REQUIRED_ARTIFACT:{record['artifact_name']}")
    if not historical["all_verified"]:
        reasons.append("FROZEN_HISTORICAL_FILE_HASH_MISMATCH")
    if not release_integrity["metadata_and_manifest_integrity_verified"]:
        reasons.append("D003_V2_RELEASE_INTEGRITY_MISMATCH")
    if not protected_verified:
        reasons.append("PROTECTED_ARTIFACT_INTEGRITY_MISMATCH")
    if output.exists():
        reasons.append("FROZEN_2026_OUTPUT_ALREADY_EXISTS")
    reasons.extend(
        [
            "2026_PARQUET_CONTENT_HASH_VERIFICATION_DEFERRED",
            "2026_ANCHOR_INPUT_CONSTRUCTION_NOT_IMPLEMENTED",
            "PARTIAL_2026_TEMPORAL_CLASSIFICATION_RULE_UNREGISTERED",
            "OUTCOME_EXECUTION_NOT_IMPLEMENTED",
        ]
    )
    automation_present = (root / "automation/config.yaml").is_file()
    warnings = []
    if not automation_present:
        warnings.append(
            "UNAVAILABLE_REPOSITORY_VALIDATION_AID:automation/config.yaml"
        )
    return {
        "study_id": config.study_id,
        "version": config.version,
        "preflight_only": True,
        "accepted_interval": {"start": config.start, "end_exclusive": config.end},
        "configuration_fingerprint": config.fingerprint(),
        "git_commit": _git_commit(root),
        "historical_specification": {
            "path": config.historical_spec,
            "sha256": (
                sha256_file(historical_spec)
                if historical_spec.is_file()
                else None
            ),
        },
        "extension_specification": {
            "path": config.extension_spec,
            "sha256": (
                sha256_file(extension_spec)
                if extension_spec.is_file()
                else None
            ),
        },
        "historical_implementation_integrity": historical,
        "release_integrity": release_integrity,
        "protected_artifact_integrity": {
            "all_verified": protected_verified,
            "directories": protected_integrity,
        },
        "automation_validation_aid": {
            "path": "automation/config.yaml",
            "present": automation_present,
            "authoritative_definition_found": False,
            "scientific_replication_dependency": False,
            "blocks_replication_authorization": False,
            "classification": "unavailable_repository_level_validation_aid",
        },
        "artifact_availability": artifacts,
        "all_required_artifacts_present": required_present,
        "output_directory": config.output_dir,
        "output_directory_created": False,
        "a_b_c_classification_rule_registered": False,
        "preflight_opened_2026_parquet_files": 0,
        "authorized_to_calculate_2026_outcomes": False,
        "blocking_reasons": reasons,
        "warnings": warnings,
    }


def render_preflight_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


__all__ = [
    "build_preflight_result",
    "render_preflight_json",
    "sha256_file",
    "verify_registered_artifact_directory",
    "verify_release_integrity",
]
