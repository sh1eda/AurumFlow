#!/usr/bin/env python3
"""Build the deterministic D003 XAUUSD tick dataset from verified BI5 partitions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - handled by the public entry points
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]

try:
    from scripts.dukascopy_common import (
        CODE_VERSION,
        Manifest,
        Partition,
        PipelineConfig,
        atomic_write_json,
        canonical_json_hash,
        decode_ticks,
        format_utc,
        generate_partitions,
        group_partitions_by_date,
        inspect_bi5_payload,
        load_config,
        manifest_file_hash,
        parse_utc_boundary,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_file,
    )
    from scripts.verify_dukascopy_downloads import classify_partition
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from dukascopy_common import (  # type: ignore
        CODE_VERSION,
        Manifest,
        Partition,
        PipelineConfig,
        atomic_write_json,
        canonical_json_hash,
        decode_ticks,
        format_utc,
        generate_partitions,
        group_partitions_by_date,
        inspect_bi5_payload,
        load_config,
        manifest_file_hash,
        parse_utc_boundary,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_file,
    )
    from verify_dukascopy_downloads import classify_partition  # type: ignore


CANONICAL_MANIFEST_NAME = "canonical_manifest.json"
CANONICAL_SCHEMA_VERSION = 1
DEFAULT_DATASET_VERSION = "d003-v1"
EXPECTED_D002_CLASSIFICATIONS = {
    "expected_holiday_closure",
    "expected_special_hours_closure",
}


class CanonicalBuildError(RuntimeError):
    """Raised when a canonical build cannot safely produce a complete dataset."""


def canonical_schema() -> Any:
    """Return the exact D003 Arrow schema."""

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
        ],
        metadata={
            b"dataset": b"D003 canonical XAUUSD ticks",
            b"timezone": b"UTC",
            b"timestamp_precision": b"millisecond",
            b"source": b"dukascopy-public-bi5",
            b"schema_version": str(CANONICAL_SCHEMA_VERSION).encode("ascii"),
        },
    )


def schema_manifest() -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in canonical_schema()
    ]


def _atomic_write_parquet(path: Path, table: Any, config: PipelineConfig) -> None:
    """Create a Parquet file atomically without replacing an existing output."""

    if pq is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite completed canonical file: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        pq.write_table(
            table,
            temporary_path,
            compression=str(config.canonical["compression"]),
            version=str(config.canonical["parquet_version"]),
            row_group_size=int(config.canonical["row_group_size"]),
            use_dictionary=False,
            write_statistics=True,
            data_page_version="1.0",
        )
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        if path.exists():
            raise FileExistsError(
                f"refusing to overwrite completed canonical file: {path}"
            )
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _records_to_table(records: list[dict[str, Any]], symbol: str) -> Any:
    if pa is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    return pa.Table.from_arrays(
        [
            pa.array(
                [row["timestamp_ms"] for row in records],
                type=pa.timestamp("ms", tz="UTC"),
            ),
            pa.array([row["bid"] for row in records], type=pa.float64()),
            pa.array([row["ask"] for row in records], type=pa.float64()),
            pa.array([row["bid_volume"] for row in records], type=pa.float32()),
            pa.array([row["ask_volume"] for row in records], type=pa.float32()),
            pa.array([row["mid"] for row in records], type=pa.float64()),
            pa.array([row["spread"] for row in records], type=pa.float64()),
            pa.array([symbol] * len(records), type=pa.string()),
            pa.array([row["partition_timestamp"] for row in records], type=pa.string()),
        ],
        schema=canonical_schema(),
    )


def _row_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identity of an exact tick; provenance is intentionally not part of identity."""

    return (
        row["timestamp_ms"],
        row["bid"],
        row["ask"],
        row["bid_volume"],
        row["ask_volume"],
    )


def _sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (*_row_key(row), row["partition_timestamp"])


def _iso_millisecond(timestamp_ms: int) -> str:
    value = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_load_strict(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CanonicalBuildError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalBuildError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CanonicalBuildError(f"expected a JSON object in {path}")
    return payload


def load_d002_overlay(
    path: Path | None,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    source_manifest_sha256: str,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Load the accepted, report-only D002 overlay without mutating its inputs."""

    if path is None:
        return {}, None
    if not path.is_file():
        raise CanonicalBuildError(f"D002 audit does not exist: {path}")
    payload = _json_load_strict(path)
    if payload.get("task") != "D002" or payload.get("symbol") != symbol:
        raise CanonicalBuildError("D002 audit task or symbol does not match this build")
    if payload.get("mode") != "offline_report_only":
        raise CanonicalBuildError("D002 audit is not the accepted offline report-only mode")
    if payload.get("manifest_mutated") is not False:
        raise CanonicalBuildError("D002 audit does not prove the source manifest was unchanged")
    if payload.get("verified_bi5_files_mutated") is not False:
        raise CanonicalBuildError("D002 audit does not prove verified BI5 files were unchanged")
    proof = payload.get("integrity_proof")
    if not isinstance(proof, dict) or proof.get("passed") is not True:
        raise CanonicalBuildError("D002 integrity proof is absent or did not pass")
    if proof.get("manifest_unchanged") is not True:
        raise CanonicalBuildError("D002 integrity proof does not mark the manifest unchanged")
    if {
        proof.get("manifest_sha256_before"),
        proof.get("manifest_sha256_after"),
    } != {source_manifest_sha256}:
        raise CanonicalBuildError(
            "D002 audit source-manifest SHA256 does not match the acquisition manifest"
        )
    audit_range = payload.get("range")
    if not isinstance(audit_range, dict):
        raise CanonicalBuildError("D002 audit range is missing")
    audit_start = parse_utc_boundary(str(audit_range.get("start_inclusive")))
    audit_end = parse_utc_boundary(str(audit_range.get("end_exclusive")))
    if start < audit_start or end > audit_end:
        raise CanonicalBuildError("D002 audit does not cover the requested build range")
    after = payload.get("after_reconciliation")
    if (
        not isinstance(after, dict)
        or after.get("balanced") is not True
        or after.get("unresolved") != 0
    ):
        raise CanonicalBuildError("D002 accepted reconciliation is not balanced and complete")

    overlay: dict[str, dict[str, Any]] = {}
    for item in payload.get("partitions", []):
        if not isinstance(item, dict):
            raise CanonicalBuildError("D002 audit contains a non-object partition")
        key = item.get("partition_timestamp")
        classification = item.get("classification")
        if not isinstance(key, str) or classification not in EXPECTED_D002_CLASSIFICATIONS:
            raise CanonicalBuildError("D002 audit contains an invalid closure partition")
        if key in overlay:
            raise CanonicalBuildError(f"D002 audit contains duplicate partition {key}")
        if item.get("evidence_kind") != "confirmed_empty_payload":
            raise CanonicalBuildError(
                f"D002 closure {key} lacks confirmed empty-payload evidence"
            )
        overlay[key] = item
    return overlay, sha256_file(path)


def _logical_build_timestamp(
    accepted: Iterable[Partition],
    manifest: Manifest,
) -> str:
    timestamps = [
        str(entry["download_timestamp"])
        for partition in accepted
        if (entry := manifest.get(partition)) is not None
        and entry.get("download_timestamp")
    ]
    return max(timestamps, default="1970-01-01T00:00:00Z")


def _git_commit(repository_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _git_worktree_dirty(repository_root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip())


def _validate_record(
    row: Mapping[str, Any],
    *,
    partition: Partition,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and enrich one decoded BI5 row without repairing source values."""

    try:
        timestamp_ms = int(row["timestamp_ms"])
        bid = float(row["bid"])
        ask = float(row["ask"])
        bid_volume = float(row["bid_volume"])
        ask_volume = float(row["ask_volume"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return None, f"malformed_record: {exc}"
    partition_start_ms = int(partition.timestamp.timestamp() * 1000)
    if not partition_start_ms <= timestamp_ms < partition_start_ms + 3_600_000:
        return None, "timestamp_outside_source_partition"
    if not math.isfinite(bid) or not math.isfinite(ask):
        return None, "non_finite_price"
    if bid <= 0 or ask <= 0:
        return None, "non_positive_price"
    if ask < bid:
        return None, "negative_spread"
    if not math.isfinite(bid_volume) or not math.isfinite(ask_volume):
        return None, "non_finite_volume"
    if bid_volume < 0 or ask_volume < 0:
        return None, "negative_volume"
    mid = (bid + ask) / 2.0
    spread = ask - bid
    if not math.isfinite(mid) or not math.isfinite(spread):
        return None, "non_finite_derived_value"
    return (
        {
            "timestamp_ms": timestamp_ms,
            "bid": bid,
            "ask": ask,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "mid": mid,
            "spread": spread,
            "partition_timestamp": partition.key,
        },
        None,
    )


def deduplicate_partition_records(
    records: Iterable[dict[str, Any]],
    *,
    previous_partition_keys: set[tuple[Any, ...]] | None = None,
) -> tuple[list[dict[str, Any]], set[tuple[Any, ...]], dict[str, int]]:
    """Remove exact duplicates and distinguish within/cross-partition removals."""

    previous = previous_partition_keys or set()
    current: set[tuple[Any, ...]] = set()
    kept: list[dict[str, Any]] = []
    counts = {"within_partition": 0, "across_partition_boundary": 0}
    for row in records:
        key = _row_key(row)
        if key in current:
            counts["within_partition"] += 1
            continue
        if key in previous:
            counts["across_partition_boundary"] += 1
            current.add(key)
            continue
        current.add(key)
        kept.append(row)
    return kept, current, counts


def _relative(path: Path, repository_root: Path) -> str:
    return relative_repository_path(path, repository_root)


def _file_path(canonical_root: Path, partition_date: str) -> Path:
    date = datetime.strptime(partition_date, "%Y-%m-%d")
    return (
        canonical_root
        / f"year={date.year:04d}"
        / f"month={date.month:02d}"
        / f"xauusd_ticks_{partition_date}.parquet"
    )


def _source_descriptor(
    partition: Partition,
    manifest: Manifest,
) -> dict[str, str]:
    entry = manifest.get(partition)
    assert entry is not None
    return {
        "partition_timestamp": partition.key,
        "sha256": str(entry["sha256"]),
    }


def _load_previous_partition_keys(
    path: Path,
    last_partition: str,
) -> set[tuple[Any, ...]]:
    if pq is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    table = pq.ParquetFile(path).read(
        columns=[
            "timestamp_utc",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
            "source_partition",
        ]
    )
    values = table.to_pydict()
    result: set[tuple[Any, ...]] = set()
    for index, source_partition in enumerate(values["source_partition"]):
        if source_partition != last_partition:
            continue
        timestamp = values["timestamp_utc"][index]
        result.add(
            (
                int(timestamp.timestamp() * 1000),
                values["bid"][index],
                values["ask"][index],
                values["bid_volume"][index],
                values["ask_volume"][index],
            )
        )
    return result


def _summarize_files(files: list[dict[str, Any]]) -> dict[str, Any]:
    row_count = sum(int(item["row_count"]) for item in files)
    duplicate_counts = {
        "within_partitions": sum(
            int(item["duplicate_counts"]["within_partitions"]) for item in files
        ),
        "across_partition_boundaries": sum(
            int(item["duplicate_counts"]["across_partition_boundaries"])
            for item in files
        ),
    }
    rejected_record_count = sum(int(item["rejected_record_count"]) for item in files)
    minimums = [item["min_timestamp"] for item in files if item["min_timestamp"]]
    maximums = [item["max_timestamp"] for item in files if item["max_timestamp"]]
    return {
        "row_count": row_count,
        "duplicate_counts": duplicate_counts,
        "duplicate_count": sum(duplicate_counts.values()),
        "rejected_record_count": rejected_record_count,
        "min_timestamp": min(minimums, default=None),
        "max_timestamp": max(maximums, default=None),
    }


def _manifest_payload(
    *,
    dataset_version: str,
    dataset_id: str,
    status: str,
    symbol: str,
    start: datetime,
    end: datetime,
    build_timestamp: str,
    git_commit: str,
    source_manifest_path: Path,
    source_manifest_sha256: str,
    d002_audit_path: Path | None,
    d002_audit_sha256: str | None,
    processed_partitions: list[dict[str, str]],
    closures: list[dict[str, str]],
    files: list[dict[str, Any]],
    build_configuration: dict[str, Any],
    input_fingerprint: str,
    repository_root: Path,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closure_counts = {
        "regular_market": sum(
            item["classification"] == "expected_market_closure" for item in closures
        ),
        "holiday": sum(
            item["classification"] == "expected_holiday_closure" for item in closures
        ),
        "special_hours": sum(
            item["classification"] == "expected_special_hours_closure"
            for item in closures
        ),
    }
    summary = _summarize_files(files)
    expected_count = int((end - start).total_seconds() // 3600)
    accounted = len(processed_partitions) + len(closures)
    payload: dict[str, Any] = {
        "dataset_version": dataset_version,
        "dataset_schema_version": CANONICAL_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "status": status,
        "symbol": symbol,
        "date_range": {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(end),
        },
        "build_timestamp": build_timestamp,
        "build_timestamp_basis": "latest selected source acquisition timestamp",
        "git_commit": git_commit,
        "git_worktree_dirty": _git_worktree_dirty(repository_root),
        "builder_sha256": build_configuration["builder_sha256"],
        "canonical_schema": schema_manifest(),
        "source_acquisition_manifest": {
            "path": _relative(source_manifest_path, repository_root),
            "sha256": source_manifest_sha256,
        },
        "d002_audit": (
            {
                "path": _relative(d002_audit_path, repository_root),
                "sha256": d002_audit_sha256,
            }
            if d002_audit_path is not None
            else None
        ),
        "processed_partition_count": len(processed_partitions),
        "processed_partitions": processed_partitions,
        "skipped_closure_counts": closure_counts,
        "skipped_closures": closures,
        "canonical_file_count": len(files),
        "row_count": summary["row_count"],
        "min_timestamp": summary["min_timestamp"],
        "max_timestamp": summary["max_timestamp"],
        "duplicate_count": summary["duplicate_count"],
        "duplicate_counts": summary["duplicate_counts"],
        "rejected_record_count": summary["rejected_record_count"],
        "files": files,
        "build_configuration": build_configuration,
        "input_fingerprint": input_fingerprint,
        "reconciliation": {
            "expected_partition_count": expected_count,
            "processed_verified_partitions": len(processed_partitions),
            "skipped_closure_partitions": len(closures),
            "unresolved_partitions": expected_count - accounted,
            "accounted_partitions": accounted,
            "balanced": expected_count == accounted,
        },
    }
    if failure is not None:
        payload["failure"] = failure
    return payload


def _compatible_existing_manifest(
    existing: Mapping[str, Any],
    *,
    dataset_version: str,
    symbol: str,
    source_manifest_sha256: str,
    d002_audit_sha256: str | None,
    build_configuration: Mapping[str, Any],
) -> bool:
    source = existing.get("source_acquisition_manifest")
    d002 = existing.get("d002_audit")
    return (
        existing.get("dataset_version") == dataset_version
        and existing.get("dataset_schema_version") == CANONICAL_SCHEMA_VERSION
        and existing.get("symbol") == symbol
        and isinstance(source, dict)
        and source.get("sha256") == source_manifest_sha256
        and (
            (d002 is None and d002_audit_sha256 is None)
            or (isinstance(d002, dict) and d002.get("sha256") == d002_audit_sha256)
        )
        and existing.get("build_configuration") == build_configuration
    )


def build_canonical(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    manifest_path: Path,
    processed_root: Path | None = None,
    canonical_root: Path | None = None,
    d002_audit_path: Path | None = None,
    canonical_manifest_path: Path | None = None,
    report_path: Path | None = None,
    dataset_version: str = DEFAULT_DATASET_VERSION,
) -> dict[str, Any]:
    """Build or resume a complete canonical range from accepted source evidence."""

    if pa is None or pq is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    if config.canonical.get("format") != "parquet":
        raise CanonicalBuildError("D003 canonical output format must be parquet")
    if end <= start:
        raise CanonicalBuildError("end must be after start")
    symbol = symbol.upper()
    if symbol != "XAUUSD":
        raise CanonicalBuildError("D003 is defined only for XAUUSD")
    mapping = config.symbol(symbol)
    output_root = canonical_root or processed_root
    if output_root is None:
        output_root = config.repository_root / "data" / "canonical" / "xauusd_ticks"
    output_root = output_root.resolve()
    output_manifest = canonical_manifest_path or output_root / CANONICAL_MANIFEST_NAME
    output_manifest = output_manifest.resolve()

    partitions = generate_partitions(start, end)
    source_manifest = Manifest(manifest_path, config=config, symbol=symbol)
    source_manifest_sha256 = manifest_file_hash(manifest_path)
    d002_overlay, d002_audit_sha256 = load_d002_overlay(
        d002_audit_path,
        symbol=symbol,
        start=start,
        end=end,
        source_manifest_sha256=source_manifest_sha256,
    )

    accepted: list[Partition] = []
    closures: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    for partition in partitions:
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
                raise CanonicalBuildError(
                    f"D002 closure overlaps verified data: {partition.key}"
                )
            accepted.append(partition)
        elif classification == "expected_market_closure":
            closures.append(
                {
                    "partition_timestamp": partition.key,
                    "classification": classification,
                }
            )
        elif partition.key in d002_overlay:
            item = d002_overlay[partition.key]
            closures.append(
                {
                    "partition_timestamp": partition.key,
                    "classification": str(item["classification"]),
                }
            )
        else:
            unresolved.append(
                {
                    "partition_timestamp": partition.key,
                    "classification": classification,
                    "reason": str(result.get("details") or "not verified"),
                }
            )
    if unresolved:
        example = unresolved[0]
        raise CanonicalBuildError(
            "canonical preflight found "
            f"{len(unresolved)} unresolved partitions; first is "
            f"{example['partition_timestamp']} ({example['classification']}): "
            f"{example['reason']}"
        )

    processed_partitions = [
        _source_descriptor(partition, source_manifest) for partition in accepted
    ]
    builder_sha256 = sha256_file(Path(__file__))
    build_configuration = {
        "builder_sha256": builder_sha256,
        "format": "parquet",
        "compression": str(config.canonical["compression"]),
        "parquet_version": str(config.canonical["parquet_version"]),
        "row_group_size": int(config.canonical["row_group_size"]),
        "file_granularity": "UTC day",
        "layout": "year=YYYY/month=MM/xauusd_ticks_YYYY-MM-DD.parquet",
        "timestamp_precision": "millisecond",
        "ordering": [
            "timestamp_utc",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
            "source_partition",
        ],
        "duplicate_identity": [
            "timestamp_utc",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
        ],
        "invalid_record_policy": "fail build; never write the affected file",
    }
    fingerprint_payload = {
        "dataset_version": dataset_version,
        "schema_version": CANONICAL_SCHEMA_VERSION,
        "code_version": CODE_VERSION,
        "config_version": config.version,
        "source_manifest_sha256": source_manifest_sha256,
        "d002_audit_sha256": d002_audit_sha256,
        "symbol": symbol,
        "archive_symbol": mapping.archive_symbol,
        "price_scale": mapping.price_scale,
        "source": config.source["id"],
        "range": [format_utc(start), format_utc(end)],
        "build_configuration": build_configuration,
        "inputs": processed_partitions,
        "closures": closures,
    }
    input_fingerprint = canonical_json_hash(fingerprint_payload)
    dataset_id = input_fingerprint[:20]
    build_timestamp = _logical_build_timestamp(accepted, source_manifest)
    git_commit = _git_commit(config.repository_root)

    existing: dict[str, Any] | None = None
    if output_manifest.exists():
        existing = _json_load_strict(output_manifest)
        if not _compatible_existing_manifest(
            existing,
            dataset_version=dataset_version,
            symbol=symbol,
            source_manifest_sha256=source_manifest_sha256,
            d002_audit_sha256=d002_audit_sha256,
            build_configuration=build_configuration,
        ):
            raise CanonicalBuildError(
                "existing canonical manifest is incompatible; refusing to overwrite it"
            )
        if (
            existing.get("status") == "complete"
            and existing.get("input_fingerprint") == input_fingerprint
        ):
            for item in existing.get("files", []):
                path = config.repository_root / item["path"]
                if not path.is_file() or sha256_file(path) != item["sha256"]:
                    raise CanonicalBuildError(
                        f"completed canonical output is missing or corrupt: {path}"
                    )
            return {
                **existing,
                "dataset_root": str(output_root),
                "metadata_path": str(output_manifest),
                "resumed": True,
                "reused_file_count": len(existing.get("files", [])),
            }

    old_files = {
        str(item["path"]): item
        for item in (existing or {}).get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    files: list[dict[str, Any]] = []
    previous_partition_keys: set[tuple[Any, ...]] = set()
    accepted_by_date = group_partitions_by_date(accepted)

    for partition_date in sorted(accepted_by_date):
        day_partitions = accepted_by_date[partition_date]
        output_path = _file_path(output_root, partition_date)
        output_relative = _relative(output_path, config.repository_root)
        source_descriptors = [
            _source_descriptor(partition, source_manifest)
            for partition in day_partitions
        ]
        source_fingerprint = canonical_json_hash(source_descriptors)
        old_file = old_files.get(output_relative)
        if old_file is not None:
            if (
                old_file.get("source_fingerprint") != source_fingerprint
                or old_file.get("source_partitions") != [
                    item["partition_timestamp"] for item in source_descriptors
                ]
            ):
                raise CanonicalBuildError(
                    f"existing file provenance is incompatible: {output_path}"
                )
            if not output_path.is_file() or sha256_file(output_path) != old_file.get(
                "sha256"
            ):
                raise CanonicalBuildError(
                    f"existing canonical file is missing or corrupt: {output_path}"
                )
            files.append(old_file)
            previous_partition_keys = _load_previous_partition_keys(
                output_path, day_partitions[-1].key
            )
            continue
        if output_path.exists():
            raise CanonicalBuildError(
                f"unmanifested canonical file exists; refusing to overwrite: {output_path}"
            )

        day_records: list[dict[str, Any]] = []
        duplicate_within = 0
        duplicate_across = 0
        rejection_examples: list[dict[str, str]] = []
        rejected_record_count = 0
        for partition in day_partitions:
            entry = source_manifest.get(partition)
            assert entry is not None
            path = resolve_manifest_file_path(
                entry["file_path"], repository_root=config.repository_root
            )
            assert path is not None
            if sha256_file(path) != entry["sha256"]:
                raise CanonicalBuildError(
                    f"raw checksum changed during build: {partition.key}"
                )
            decoded, decoded_rows = inspect_bi5_payload(
                path.read_bytes(),
                max_compressed_bytes=int(config.download["max_compressed_bytes"]),
            )
            if decoded_rows != entry["record_count"]:
                raise CanonicalBuildError(
                    f"raw record count changed during build: {partition.key}"
                )
            valid_partition_records: list[dict[str, Any]] = []
            for row in decode_ticks(
                decoded,
                partition=partition,
                price_scale=mapping.price_scale,
            ):
                normalized, reason = _validate_record(row, partition=partition)
                if normalized is None:
                    rejected_record_count += 1
                    if len(rejection_examples) < 10:
                        rejection_examples.append(
                            {
                                "partition_timestamp": partition.key,
                                "reason": str(reason),
                            }
                        )
                    continue
                valid_partition_records.append(normalized)
            kept, current_keys, counts = deduplicate_partition_records(
                valid_partition_records,
                previous_partition_keys=previous_partition_keys,
            )
            duplicate_within += counts["within_partition"]
            duplicate_across += counts["across_partition_boundary"]
            day_records.extend(kept)
            previous_partition_keys = current_keys

        if rejected_record_count:
            failure_files = [
                *files,
                {
                    "date": partition_date,
                    "path": output_relative,
                    "row_count": 0,
                    "byte_size": 0,
                    "sha256": None,
                    "min_timestamp": None,
                    "max_timestamp": None,
                    "source_partitions": [
                        item["partition_timestamp"] for item in source_descriptors
                    ],
                    "source_fingerprint": source_fingerprint,
                    "duplicate_counts": {
                        "within_partitions": duplicate_within,
                        "across_partition_boundaries": duplicate_across,
                    },
                    "rejected_record_count": rejected_record_count,
                },
            ]
            failed_manifest = _manifest_payload(
                dataset_version=dataset_version,
                dataset_id=dataset_id,
                status="failed",
                symbol=symbol,
                start=start,
                end=end,
                build_timestamp=build_timestamp,
                git_commit=git_commit,
                source_manifest_path=manifest_path,
                source_manifest_sha256=source_manifest_sha256,
                d002_audit_path=d002_audit_path,
                d002_audit_sha256=d002_audit_sha256,
                processed_partitions=processed_partitions,
                closures=closures,
                files=failure_files,
                build_configuration=build_configuration,
                input_fingerprint=input_fingerprint,
                repository_root=config.repository_root,
                failure={
                    "reason": "rejected_records",
                    "rejected_record_count": rejected_record_count,
                    "examples": rejection_examples,
                },
            )
            atomic_write_json(output_manifest, failed_manifest)
            raise CanonicalBuildError(
                f"rejected {rejected_record_count} malformed or invalid records "
                f"for {partition_date}; no Parquet file was written"
            )

        day_records.sort(key=_sort_key)
        if not day_records:
            raise CanonicalBuildError(
                f"verified partitions produced an empty canonical day: {partition_date}"
            )
        table = _records_to_table(day_records, symbol)
        _atomic_write_parquet(output_path, table, config)
        file_record = {
            "date": partition_date,
            "path": output_relative,
            "row_count": len(day_records),
            "byte_size": output_path.stat().st_size,
            "sha256": sha256_file(output_path),
            "min_timestamp": _iso_millisecond(day_records[0]["timestamp_ms"]),
            "max_timestamp": _iso_millisecond(day_records[-1]["timestamp_ms"]),
            "source_partitions": [
                item["partition_timestamp"] for item in source_descriptors
            ],
            "source_fingerprint": source_fingerprint,
            "duplicate_counts": {
                "within_partitions": duplicate_within,
                "across_partition_boundaries": duplicate_across,
            },
            "rejected_record_count": 0,
        }
        files.append(file_record)
        checkpoint = _manifest_payload(
            dataset_version=dataset_version,
            dataset_id=dataset_id,
            status="building",
            symbol=symbol,
            start=start,
            end=end,
            build_timestamp=build_timestamp,
            git_commit=git_commit,
            source_manifest_path=manifest_path,
            source_manifest_sha256=source_manifest_sha256,
            d002_audit_path=d002_audit_path,
            d002_audit_sha256=d002_audit_sha256,
            processed_partitions=processed_partitions,
            closures=closures,
            files=files,
            build_configuration=build_configuration,
            input_fingerprint=input_fingerprint,
            repository_root=config.repository_root,
        )
        atomic_write_json(output_manifest, checkpoint)

    final_manifest = _manifest_payload(
        dataset_version=dataset_version,
        dataset_id=dataset_id,
        status="complete",
        symbol=symbol,
        start=start,
        end=end,
        build_timestamp=build_timestamp,
        git_commit=git_commit,
        source_manifest_path=manifest_path,
        source_manifest_sha256=source_manifest_sha256,
        d002_audit_path=d002_audit_path,
        d002_audit_sha256=d002_audit_sha256,
        processed_partitions=processed_partitions,
        closures=closures,
        files=files,
        build_configuration=build_configuration,
        input_fingerprint=input_fingerprint,
        repository_root=config.repository_root,
    )
    if final_manifest["reconciliation"]["balanced"] is not True:
        raise CanonicalBuildError("canonical manifest reconciliation is not balanced")
    atomic_write_json(output_manifest, final_manifest)
    if report_path is not None:
        atomic_write_json(report_path, final_manifest)
    return {
        **final_manifest,
        "dataset_root": str(output_root),
        "metadata_path": str(output_manifest),
        "resumed": existing is not None,
        "reused_file_count": sum(
            item["path"] in old_files for item in final_manifest["files"]
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--start", required=True, help="inclusive UTC date/hour")
    parser.add_argument("--end", required=True, help="exclusive UTC date/hour")
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument("--raw-root")
    parser.add_argument("--source-manifest")
    parser.add_argument("--d002-audit")
    parser.add_argument("--output-root", default="data/canonical/xauusd_ticks")
    parser.add_argument("--canonical-manifest")
    parser.add_argument("--manifest-copy")
    parser.add_argument("--dataset-version", default=DEFAULT_DATASET_VERSION)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        symbol = args.symbol.upper()
        start = parse_utc_boundary(args.start)
        end = parse_utc_boundary(args.end)
        raw_root = (
            Path(args.raw_root) if args.raw_root else config.path_for("raw_root")
        )
        source_manifest_path = (
            Path(args.source_manifest)
            if args.source_manifest
            else config.path_for("manifests_root") / f"{symbol}_ticks_manifest.json"
        )
        d002_audit_path = (
            Path(args.d002_audit)
            if args.d002_audit
            else config.path_for("reports_root")
            / "D002_XAUUSD_holiday_special_hours_audit.json"
        )
        metadata = build_canonical(
            config=config,
            symbol=symbol,
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=source_manifest_path,
            canonical_root=Path(args.output_root),
            d002_audit_path=d002_audit_path,
            canonical_manifest_path=(
                Path(args.canonical_manifest) if args.canonical_manifest else None
            ),
            report_path=Path(args.manifest_copy) if args.manifest_copy else None,
            dataset_version=args.dataset_version,
        )
        print(f"dataset_root={metadata['dataset_root']}")
        print(f"rows={metadata['row_count']}")
        print(f"canonical_files={metadata['canonical_file_count']}")
        print(f"processed_partitions={metadata['processed_partition_count']}")
        print(f"duplicate_count={metadata['duplicate_count']}")
        print(f"rejected_record_count={metadata['rejected_record_count']}")
        print(f"reused_file_count={metadata['reused_file_count']}")
        return 0
    except (ValueError, OSError, KeyError, CanonicalBuildError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
