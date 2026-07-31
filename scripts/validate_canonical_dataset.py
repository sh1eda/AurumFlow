#!/usr/bin/env python3
"""Independently verify a D003 canonical XAUUSD Parquet dataset and manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - handled by the public entry points
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

try:
    from scripts.dukascopy_common import (
        Manifest,
        Partition,
        PipelineConfig,
        atomic_write_json,
        format_utc,
        generate_partitions,
        load_config,
        parse_utc_boundary,
        resolve_manifest_file_path,
        sha256_file,
    )
    from scripts.verify_dukascopy_downloads import classify_partition
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from dukascopy_common import (  # type: ignore
        Manifest,
        Partition,
        PipelineConfig,
        atomic_write_json,
        format_utc,
        generate_partitions,
        load_config,
        parse_utc_boundary,
        resolve_manifest_file_path,
        sha256_file,
    )
    from verify_dukascopy_downloads import classify_partition  # type: ignore


CANONICAL_COLUMNS = [
    "timestamp_utc",
    "bid",
    "ask",
    "bid_volume",
    "ask_volume",
    "mid",
    "spread",
    "symbol",
    "source_partition",
]
D002_CLASSIFICATIONS = {
    "expected_holiday_closure",
    "expected_special_hours_closure",
}


class CanonicalVerificationError(RuntimeError):
    """Raised when verification cannot inspect the requested artifact."""


def _expected_schema() -> Any:
    if pa is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    return pa.schema(
        [
            pa.field("timestamp_utc", pa.timestamp("ms", tz="UTC"), nullable=False),
            pa.field("bid", pa.float64(), nullable=False),
            pa.field("ask", pa.float64(), nullable=False),
            pa.field("bid_volume", pa.float32(), nullable=False),
            pa.field("ask_volume", pa.float32(), nullable=False),
            pa.field("mid", pa.float64(), nullable=False),
            pa.field("spread", pa.float64(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("source_partition", pa.string(), nullable=False),
        ]
    )


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CanonicalVerificationError(
                    f"duplicate JSON key {key!r} in {path}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalVerificationError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CanonicalVerificationError(f"expected a JSON object in {path}")
    return payload


def _resolve(path_text: str, repository_root: Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else repository_root / path


def _load_d002_independently(
    path: Path | None,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    source_manifest_sha256: str,
    errors: list[str],
) -> tuple[dict[str, str], str | None]:
    if path is None:
        return {}, None
    if not path.is_file():
        errors.append(f"D002 audit missing: {path}")
        return {}, None
    try:
        payload = _strict_json(path)
    except CanonicalVerificationError as exc:
        errors.append(str(exc))
        return {}, None
    actual_sha256 = sha256_file(path)
    if payload.get("task") != "D002" or payload.get("symbol") != symbol:
        errors.append("D002 audit task or symbol mismatch")
    if payload.get("mode") != "offline_report_only":
        errors.append("D002 audit is not offline_report_only")
    if payload.get("manifest_mutated") is not False:
        errors.append("D002 audit does not prove manifest immutability")
    if payload.get("verified_bi5_files_mutated") is not False:
        errors.append("D002 audit does not prove BI5 immutability")
    proof = payload.get("integrity_proof")
    if not isinstance(proof, dict) or proof.get("passed") is not True:
        errors.append("D002 integrity proof did not pass")
    else:
        if proof.get("manifest_unchanged") is not True:
            errors.append("D002 integrity proof does not mark the manifest unchanged")
        if proof.get("manifest_sha256_before") != source_manifest_sha256:
            errors.append("D002 pre-audit manifest SHA256 mismatch")
        if proof.get("manifest_sha256_after") != source_manifest_sha256:
            errors.append("D002 post-audit manifest SHA256 mismatch")
    after = payload.get("after_reconciliation")
    if (
        not isinstance(after, dict)
        or after.get("balanced") is not True
        or after.get("unresolved") != 0
    ):
        errors.append("D002 accepted reconciliation is incomplete")
    audit_range = payload.get("range")
    if isinstance(audit_range, dict):
        try:
            audit_start = parse_utc_boundary(str(audit_range["start_inclusive"]))
            audit_end = parse_utc_boundary(str(audit_range["end_exclusive"]))
            if start < audit_start or end > audit_end:
                errors.append("D002 audit does not cover the canonical range")
        except (KeyError, ValueError):
            errors.append("D002 audit range is invalid")
    else:
        errors.append("D002 audit range is missing")

    overlay: dict[str, str] = {}
    for item in payload.get("partitions", []):
        if not isinstance(item, dict):
            errors.append("D002 audit has a non-object partition")
            continue
        key = item.get("partition_timestamp")
        classification = item.get("classification")
        if not isinstance(key, str) or classification not in D002_CLASSIFICATIONS:
            errors.append("D002 audit has an invalid closure partition")
            continue
        if key in overlay:
            errors.append(f"D002 audit has duplicate partition {key}")
            continue
        if item.get("evidence_kind") != "confirmed_empty_payload":
            errors.append(f"D002 closure lacks confirmed empty evidence: {key}")
        overlay[key] = str(classification)
    return overlay, actual_sha256


def _manifest_schema() -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in _expected_schema()
    ]


def _identity(
    timestamp: datetime,
    bid: float,
    ask: float,
    bid_volume: float,
    ask_volume: float,
) -> tuple[Any, ...]:
    return (
        int(timestamp.timestamp() * 1000),
        bid,
        ask,
        bid_volume,
        ask_volume,
    )


def _path_layout_error(
    path: Path,
    canonical_root: Path,
    partition_date: str,
) -> str | None:
    try:
        relative = path.resolve().relative_to(canonical_root.resolve())
    except ValueError:
        return f"canonical file is outside dataset root: {path}"
    date = datetime.strptime(partition_date, "%Y-%m-%d")
    expected = Path(
        f"year={date.year:04d}/month={date.month:02d}/"
        f"xauusd_ticks_{partition_date}.parquet"
    )
    if relative != expected:
        return f"canonical file layout mismatch: expected {expected}, got {relative}"
    return None


def _derive_source_coverage(
    *,
    config: PipelineConfig,
    source_manifest: Manifest,
    raw_root: Path,
    symbol: str,
    start: datetime,
    end: datetime,
    d002_overlay: Mapping[str, str],
    errors: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    verified: dict[str, str] = {}
    closures: dict[str, str] = {}
    for partition in generate_partitions(start, end):
        result = classify_partition(
            config=config,
            manifest=source_manifest,
            raw_root=raw_root,
            symbol=symbol,
            partition=partition,
        )
        classification = result["classification"]
        if classification == "verified_data":
            if partition.key in d002_overlay:
                errors.append(f"D002 closure overlaps verified BI5: {partition.key}")
            entry = source_manifest.get(partition)
            assert entry is not None
            verified[partition.key] = str(entry["sha256"])
        elif classification == "expected_market_closure":
            closures[partition.key] = classification
        elif partition.key in d002_overlay:
            closures[partition.key] = d002_overlay[partition.key]
        else:
            errors.append(
                f"source partition is neither verified nor an accepted closure: "
                f"{partition.key} ({classification})"
            )
    return verified, closures


def verify_canonical_dataset(
    *,
    config: PipelineConfig,
    canonical_root: Path,
    canonical_manifest_path: Path,
    source_manifest_path: Path | None = None,
    raw_root: Path | None = None,
    d002_audit_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Verify canonical files, manifest reconciliation, and source provenance."""

    if pa is None or pq is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    canonical_root = canonical_root.resolve()
    canonical_manifest_path = canonical_manifest_path.resolve()
    manifest = _strict_json(canonical_manifest_path)
    errors: list[str] = []

    required_keys = {
        "dataset_version",
        "dataset_schema_version",
        "dataset_id",
        "status",
        "symbol",
        "date_range",
        "build_timestamp",
        "git_commit",
        "git_worktree_dirty",
        "builder_sha256",
        "canonical_schema",
        "source_acquisition_manifest",
        "processed_partition_count",
        "skipped_closure_counts",
        "canonical_file_count",
        "row_count",
        "min_timestamp",
        "max_timestamp",
        "duplicate_count",
        "rejected_record_count",
        "files",
        "build_configuration",
        "reconciliation",
    }
    missing_keys = sorted(required_keys - manifest.keys())
    if missing_keys:
        errors.append(f"canonical manifest missing keys: {missing_keys}")
    if manifest.get("status") != "complete":
        errors.append("canonical manifest status is not complete")
    if manifest.get("dataset_schema_version") != 1:
        errors.append("unsupported canonical schema version")
    if manifest.get("builder_sha256") != manifest.get("build_configuration", {}).get(
        "builder_sha256"
    ):
        errors.append("builder SHA256 does not reconcile with build configuration")
    if not isinstance(manifest.get("git_worktree_dirty"), (bool, type(None))):
        errors.append("git_worktree_dirty must be boolean or null")
    if manifest.get("canonical_schema") != _manifest_schema():
        errors.append("canonical manifest schema does not match D003")
    symbol = str(manifest.get("symbol"))
    if symbol != "XAUUSD":
        errors.append(f"canonical symbol is not XAUUSD: {symbol!r}")

    try:
        date_range = manifest["date_range"]
        start = parse_utc_boundary(str(date_range["start_inclusive"]))
        end = parse_utc_boundary(str(date_range["end_exclusive"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalVerificationError(f"invalid canonical date range: {exc}") from exc

    source_descriptor = manifest.get("source_acquisition_manifest")
    if not isinstance(source_descriptor, dict):
        raise CanonicalVerificationError(
            "canonical source_acquisition_manifest is missing"
        )
    effective_source_manifest = source_manifest_path or _resolve(
        str(source_descriptor.get("path")), config.repository_root
    )
    if not effective_source_manifest.is_file():
        raise CanonicalVerificationError(
            f"source acquisition manifest missing: {effective_source_manifest}"
        )
    source_sha256 = sha256_file(effective_source_manifest)
    if source_descriptor.get("sha256") != source_sha256:
        errors.append("source acquisition manifest SHA256 mismatch")
    source_manifest = Manifest(
        effective_source_manifest,
        config=config,
        symbol=symbol,
    )
    effective_raw_root = raw_root or config.path_for("raw_root")

    d002_descriptor = manifest.get("d002_audit")
    effective_d002 = d002_audit_path
    if effective_d002 is None and isinstance(d002_descriptor, dict):
        effective_d002 = _resolve(
            str(d002_descriptor.get("path")), config.repository_root
        )
    d002_overlay, d002_sha256 = _load_d002_independently(
        effective_d002,
        symbol=symbol,
        start=start,
        end=end,
        source_manifest_sha256=source_sha256,
        errors=errors,
    )
    if isinstance(d002_descriptor, dict):
        if d002_descriptor.get("sha256") != d002_sha256:
            errors.append("D002 audit SHA256 mismatch")
    elif d002_sha256 is not None:
        errors.append("canonical manifest omitted the supplied D002 audit")

    verified, closures = _derive_source_coverage(
        config=config,
        source_manifest=source_manifest,
        raw_root=effective_raw_root,
        symbol=symbol,
        start=start,
        end=end,
        d002_overlay=d002_overlay,
        errors=errors,
    )

    manifest_processed: dict[str, str] = {}
    for item in manifest.get("processed_partitions", []):
        if not isinstance(item, dict):
            errors.append("manifest processed_partitions has a non-object item")
            continue
        key = item.get("partition_timestamp")
        checksum = item.get("sha256")
        if not isinstance(key, str) or not isinstance(checksum, str):
            errors.append("manifest has an invalid processed partition")
            continue
        if key in manifest_processed:
            errors.append(f"manifest repeats processed partition: {key}")
        manifest_processed[key] = checksum
    if manifest_processed != verified:
        missing = sorted(set(verified) - set(manifest_processed))
        extra = sorted(set(manifest_processed) - set(verified))
        mismatched = sorted(
            key
            for key in set(verified) & set(manifest_processed)
            if verified[key] != manifest_processed[key]
        )
        errors.append(
            "verified source coverage mismatch: "
            f"missing={len(missing)} extra={len(extra)} checksum_mismatch={len(mismatched)}"
        )
    if manifest.get("processed_partition_count") != len(verified):
        errors.append("processed_partition_count does not match verified source coverage")

    manifest_closures: dict[str, str] = {}
    for item in manifest.get("skipped_closures", []):
        if not isinstance(item, dict):
            errors.append("manifest skipped_closures has a non-object item")
            continue
        key = item.get("partition_timestamp")
        classification = item.get("classification")
        if not isinstance(key, str) or not isinstance(classification, str):
            errors.append("manifest has an invalid skipped closure")
            continue
        if key in manifest_closures:
            errors.append(f"manifest repeats skipped closure: {key}")
        manifest_closures[key] = classification
    if manifest_closures != closures:
        errors.append("manifest closure exclusion does not match D001/D002 evidence")
    expected_closure_counts = {
        "regular_market": sum(
            classification == "expected_market_closure"
            for classification in closures.values()
        ),
        "holiday": sum(
            classification == "expected_holiday_closure"
            for classification in closures.values()
        ),
        "special_hours": sum(
            classification == "expected_special_hours_closure"
            for classification in closures.values()
        ),
    }
    if manifest.get("skipped_closure_counts") != expected_closure_counts:
        errors.append("skipped closure counts do not reconcile")

    file_records = manifest.get("files", [])
    if not isinstance(file_records, list):
        raise CanonicalVerificationError("canonical manifest files must be a list")
    if manifest.get("canonical_file_count") != len(file_records):
        errors.append("canonical_file_count does not match manifest file entries")
    paths = [item.get("path") for item in file_records if isinstance(item, dict)]
    if len(paths) != len(set(paths)):
        errors.append("canonical manifest contains duplicate file paths")
    dates = [item.get("date") for item in file_records if isinstance(item, dict)]
    if dates != sorted(dates):
        errors.append("canonical manifest files are not chronologically ordered")

    discovered_files = {path.resolve() for path in canonical_root.rglob("*.parquet")}
    declared_files: set[Path] = set()
    observed_partitions: set[str] = set()
    row_count = 0
    duplicate_ticks = 0
    invalid_prices = 0
    invalid_spreads = 0
    invalid_volumes = 0
    ordering_errors = 0
    timezone_errors = 0
    empty_files = 0
    minimum_timestamp: datetime | None = None
    maximum_timestamp: datetime | None = None
    previous_file_maximum: datetime | None = None
    previous_boundary_keys: set[tuple[Any, ...]] = set()

    for file_record in file_records:
        if not isinstance(file_record, dict):
            errors.append("canonical manifest has a non-object file record")
            continue
        path_text = file_record.get("path")
        partition_date = file_record.get("date")
        if not isinstance(path_text, str) or not isinstance(partition_date, str):
            errors.append("canonical file record path or date is invalid")
            continue
        path = _resolve(path_text, config.repository_root).resolve()
        declared_files.add(path)
        try:
            layout_error = _path_layout_error(path, canonical_root, partition_date)
        except ValueError:
            layout_error = f"canonical file has invalid date: {partition_date!r}"
        if layout_error:
            errors.append(layout_error)
        if not path.is_file():
            errors.append(f"canonical file missing: {path}")
            continue
        actual_sha256 = sha256_file(path)
        if file_record.get("sha256") != actual_sha256:
            errors.append(f"canonical file SHA256 mismatch: {path}")
        if file_record.get("byte_size") != path.stat().st_size:
            errors.append(f"canonical file byte_size mismatch: {path}")
        try:
            parquet_file = pq.ParquetFile(path)
            table = parquet_file.read()
        except Exception as exc:  # PyArrow raises several format-specific exceptions
            errors.append(f"canonical Parquet is unreadable: {path}: {exc}")
            continue
        if table.schema.remove_metadata() != _expected_schema().remove_metadata():
            errors.append(f"canonical Parquet schema mismatch: {path}")
            continue
        if table.num_rows == 0:
            empty_files += 1
            errors.append(f"canonical Parquet is empty: {path}")
            continue
        if file_record.get("row_count") != table.num_rows:
            errors.append(f"canonical file row_count mismatch: {path}")
        row_count += table.num_rows
        columns = table.to_pydict()
        file_keys: set[tuple[Any, ...]] = set()
        file_minimum: datetime | None = None
        file_maximum: datetime | None = None
        last_timestamp: datetime | None = None
        last_timestamp_keys: set[tuple[Any, ...]] = set()
        file_source_partitions: set[str] = set()
        for index in range(table.num_rows):
            timestamp = columns["timestamp_utc"][index]
            bid = columns["bid"][index]
            ask = columns["ask"][index]
            bid_volume = columns["bid_volume"][index]
            ask_volume = columns["ask_volume"][index]
            mid = columns["mid"][index]
            spread = columns["spread"][index]
            row_symbol = columns["symbol"][index]
            source_partition = columns["source_partition"][index]
            if (
                not isinstance(timestamp, datetime)
                or timestamp.tzinfo is None
                or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp)
            ):
                timezone_errors += 1
                continue
            if last_timestamp is not None and timestamp < last_timestamp:
                ordering_errors += 1
            if index == 0 and previous_file_maximum is not None:
                if timestamp < previous_file_maximum:
                    ordering_errors += 1
            key = _identity(timestamp, bid, ask, bid_volume, ask_volume)
            if key in file_keys:
                duplicate_ticks += 1
            file_keys.add(key)
            if (
                previous_file_maximum is not None
                and timestamp == previous_file_maximum
                and key in previous_boundary_keys
            ):
                duplicate_ticks += 1
            if last_timestamp is None or timestamp != last_timestamp:
                last_timestamp_keys = {key}
            else:
                last_timestamp_keys.add(key)
            last_timestamp = timestamp
            if (
                not math.isfinite(bid)
                or not math.isfinite(ask)
                or bid <= 0
                or ask <= 0
            ):
                invalid_prices += 1
            if (
                not math.isfinite(spread)
                or ask < bid
                or spread < 0
                or spread != ask - bid
            ):
                invalid_spreads += 1
            if not math.isfinite(mid) or mid != (bid + ask) / 2.0:
                invalid_spreads += 1
            if (
                not math.isfinite(bid_volume)
                or not math.isfinite(ask_volume)
                or bid_volume < 0
                or ask_volume < 0
            ):
                invalid_volumes += 1
            if row_symbol != symbol:
                errors.append(f"canonical row symbol mismatch in {path}")
                break
            if not isinstance(source_partition, str):
                errors.append(f"canonical source_partition is not a string in {path}")
                break
            file_source_partitions.add(source_partition)
            observed_partitions.add(source_partition)
            if source_partition not in verified:
                errors.append(
                    f"canonical file includes unverified/closure partition "
                    f"{source_partition}"
                )
                break
            file_minimum = timestamp if file_minimum is None else min(file_minimum, timestamp)
            file_maximum = timestamp if file_maximum is None else max(file_maximum, timestamp)

        declared_source_partitions = set(file_record.get("source_partitions", []))
        if file_source_partitions != declared_source_partitions:
            errors.append(f"canonical file source coverage mismatch: {path}")
        expected_minimum = (
            file_minimum.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            if file_minimum is not None
            else None
        )
        expected_maximum = (
            file_maximum.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            if file_maximum is not None
            else None
        )
        if file_record.get("min_timestamp") != expected_minimum:
            errors.append(f"canonical file min_timestamp mismatch: {path}")
        if file_record.get("max_timestamp") != expected_maximum:
            errors.append(f"canonical file max_timestamp mismatch: {path}")
        minimum_timestamp = (
            file_minimum
            if minimum_timestamp is None
            else min(minimum_timestamp, file_minimum)
        )
        maximum_timestamp = (
            file_maximum
            if maximum_timestamp is None
            else max(maximum_timestamp, file_maximum)
        )
        previous_file_maximum = file_maximum
        previous_boundary_keys = last_timestamp_keys

    if discovered_files != declared_files:
        errors.append(
            "canonical file discovery mismatch: "
            f"undeclared={len(discovered_files - declared_files)} "
            f"missing={len(declared_files - discovered_files)}"
        )
    if observed_partitions != set(verified):
        errors.append(
            "Parquet verified source coverage mismatch: "
            f"missing={len(set(verified) - observed_partitions)} "
            f"extra={len(observed_partitions - set(verified))}"
        )
    if manifest.get("row_count") != row_count:
        errors.append("canonical manifest row_count mismatch")
    actual_minimum = (
        minimum_timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if minimum_timestamp is not None
        else None
    )
    actual_maximum = (
        maximum_timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if maximum_timestamp is not None
        else None
    )
    if manifest.get("min_timestamp") != actual_minimum:
        errors.append("canonical manifest min_timestamp mismatch")
    if manifest.get("max_timestamp") != actual_maximum:
        errors.append("canonical manifest max_timestamp mismatch")
    if duplicate_ticks:
        errors.append(f"canonical dataset contains {duplicate_ticks} duplicate ticks")
    if invalid_prices:
        errors.append(f"canonical dataset contains {invalid_prices} invalid prices")
    if invalid_spreads:
        errors.append(f"canonical dataset contains {invalid_spreads} invalid spreads")
    if invalid_volumes:
        errors.append(f"canonical dataset contains {invalid_volumes} invalid volumes")
    if ordering_errors:
        errors.append(f"canonical dataset contains {ordering_errors} ordering errors")
    if timezone_errors:
        errors.append(f"canonical dataset contains {timezone_errors} non-UTC timestamps")

    reconciliation = manifest.get("reconciliation")
    expected_partition_count = len(generate_partitions(start, end))
    expected_accounted = len(verified) + len(closures)
    expected_reconciliation = {
        "expected_partition_count": expected_partition_count,
        "processed_verified_partitions": len(verified),
        "skipped_closure_partitions": len(closures),
        "unresolved_partitions": expected_partition_count - expected_accounted,
        "accounted_partitions": expected_accounted,
        "balanced": expected_partition_count == expected_accounted,
    }
    if reconciliation != expected_reconciliation:
        errors.append("canonical manifest reconciliation mismatch")
    if manifest.get("duplicate_count") != sum(
        int(item.get("duplicate_counts", {}).get("within_partitions", 0))
        + int(
            item.get("duplicate_counts", {}).get(
                "across_partition_boundaries", 0
            )
        )
        for item in file_records
        if isinstance(item, dict)
    ):
        errors.append("canonical manifest duplicate_count does not reconcile")
    if manifest.get("rejected_record_count") != sum(
        int(item.get("rejected_record_count", 0))
        for item in file_records
        if isinstance(item, dict)
    ):
        errors.append("canonical manifest rejected_record_count does not reconcile")

    report = {
        "report_schema_version": 1,
        "verification_timestamp": format_utc(datetime.now(timezone.utc)),
        "canonical_manifest_path": str(canonical_manifest_path),
        "canonical_manifest_sha256": sha256_file(canonical_manifest_path),
        "dataset_id": manifest.get("dataset_id"),
        "dataset_version": manifest.get("dataset_version"),
        "symbol": symbol,
        "date_range": {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(end),
        },
        "passed": not errors,
        "errors": errors,
        "metrics": {
            "canonical_file_count": len(declared_files),
            "row_count": row_count,
            "min_timestamp": actual_minimum,
            "max_timestamp": actual_maximum,
            "duplicate_ticks": duplicate_ticks,
            "invalid_prices": invalid_prices,
            "invalid_spreads": invalid_spreads,
            "invalid_volumes": invalid_volumes,
            "ordering_errors": ordering_errors,
            "timezone_errors": timezone_errors,
            "empty_parquet_files": empty_files,
            "verified_source_partitions": len(verified),
            "regular_market_closures": expected_closure_counts["regular_market"],
            "holiday_closures": expected_closure_counts["holiday"],
            "special_hours_closures": expected_closure_counts["special_hours"],
        },
        "reconciliation": expected_reconciliation,
    }
    if report_path is not None:
        atomic_write_json(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument("--dataset-root", default="data/canonical/xauusd_ticks")
    parser.add_argument(
        "--canonical-manifest",
        default="data/canonical/xauusd_ticks/canonical_manifest.json",
    )
    parser.add_argument("--source-manifest")
    parser.add_argument("--raw-root")
    parser.add_argument("--d002-audit")
    parser.add_argument("--report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        report = verify_canonical_dataset(
            config=config,
            canonical_root=Path(args.dataset_root),
            canonical_manifest_path=Path(args.canonical_manifest),
            source_manifest_path=(
                Path(args.source_manifest) if args.source_manifest else None
            ),
            raw_root=Path(args.raw_root) if args.raw_root else None,
            d002_audit_path=Path(args.d002_audit) if args.d002_audit else None,
            report_path=Path(args.report) if args.report else None,
        )
        print(f"passed={str(report['passed']).lower()}")
        print(f"rows={report['metrics']['row_count']}")
        print(
            f"canonical_files={report['metrics']['canonical_file_count']}"
        )
        print(f"errors={len(report['errors'])}")
        for error in report["errors"][:20]:
            print(f"error: {error}", file=sys.stderr)
        return 0 if report["passed"] else 2
    except (
        ValueError,
        OSError,
        KeyError,
        CanonicalVerificationError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
