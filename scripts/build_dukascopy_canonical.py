#!/usr/bin/env python3
"""Build deterministic, feed-specific Parquet data from verified Dukascopy BI5 files."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - handled by main with a useful message
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
        resolve_manifest_file_path,
        sha256_file,
    )
    from verify_dukascopy_downloads import classify_partition  # type: ignore


def _schema() -> Any:
    assert pa is not None
    return pa.schema(
        [
            pa.field("timestamp", pa.timestamp("ms", tz="UTC"), nullable=False),
            pa.field("bid", pa.float64(), nullable=False),
            pa.field("ask", pa.float64(), nullable=False),
            pa.field("bid_volume", pa.float32(), nullable=False),
            pa.field("ask_volume", pa.float32(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("feed", pa.string(), nullable=False),
            pa.field("source_partition", pa.timestamp("ms", tz="UTC"), nullable=False),
        ],
        metadata={
            b"timezone": b"UTC",
            b"feed": b"dukascopy-public-bi5",
            b"timestamp_precision": b"millisecond",
            b"code_version": CODE_VERSION.encode("ascii"),
        },
    )


def _atomic_write_parquet(path: Path, table: Any, config: PipelineConfig) -> None:
    assert pq is not None
    path.parent.mkdir(parents=True, exist_ok=True)
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
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _records_to_table(records: list[dict[str, Any]], symbol: str) -> Any:
    assert pa is not None
    return pa.Table.from_arrays(
        [
            pa.array([row["timestamp_ms"] for row in records], type=pa.timestamp("ms", tz="UTC")),
            pa.array([row["bid"] for row in records], type=pa.float64()),
            pa.array([row["ask"] for row in records], type=pa.float64()),
            pa.array([row["bid_volume"] for row in records], type=pa.float32()),
            pa.array([row["ask_volume"] for row in records], type=pa.float32()),
            pa.array([symbol] * len(records), type=pa.string()),
            pa.array(["dukascopy"] * len(records), type=pa.string()),
            pa.array(
                [
                    int(
                        datetime.fromisoformat(
                            row["partition_timestamp"].replace("Z", "+00:00")
                        ).timestamp()
                        * 1000
                    )
                    for row in records
                ],
                type=pa.timestamp("ms", tz="UTC"),
            ),
        ],
        schema=_schema(),
    )


def _row_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["timestamp_ms"],
        row["bid"],
        row["ask"],
        row["bid_volume"],
        row["ask_volume"],
    )


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["timestamp_ms"],
        row["bid"],
        row["ask"],
        row["bid_volume"],
        row["ask_volume"],
        row["partition_timestamp"],
    )


def _iso_millisecond(timestamp_ms: int) -> str:
    value = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_canonical(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    manifest_path: Path,
    processed_root: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if pa is None or pq is None:
        raise RuntimeError("pyarrow is required; install the project dependencies first")
    if config.canonical.get("format") != "parquet":
        raise RuntimeError("D001 canonical output format must be parquet")
    symbol = symbol.upper()
    mapping = config.symbol(symbol)
    partitions = generate_partitions(start, end)
    manifest = Manifest(manifest_path, config=config, symbol=symbol)

    classifications: dict[str, dict[str, Any]] = {}
    accepted: list[Partition] = []
    exclusions: list[dict[str, str]] = []
    for partition in partitions:
        result = classify_partition(
            config=config,
            manifest=manifest,
            raw_root=raw_root,
            symbol=symbol,
            partition=partition,
        )
        classifications[partition.key] = result
        if result["classification"] == "verified_data":
            accepted.append(partition)
        else:
            exclusions.append(
                {
                    "partition_timestamp": partition.key,
                    "classification": result["classification"],
                    "reason": result.get("details") or "not verified",
                }
            )

    selected_inputs = [
        {
            "partition_timestamp": partition.key,
            "sha256": manifest.get(partition)["sha256"],
        }
        for partition in accepted
    ]
    source_manifest_sha256 = manifest_file_hash(manifest_path)
    fingerprint_payload = {
        "code_version": CODE_VERSION,
        "config_version": config.version,
        "manifest_sha256": source_manifest_sha256,
        "symbol": symbol,
        "archive_symbol": mapping.archive_symbol,
        "price_scale": mapping.price_scale,
        "source": config.source["id"],
        "range": [format_utc(start), format_utc(end)],
        "canonical": dict(config.canonical),
        "validation": dict(config.validation),
        "inputs": selected_inputs,
    }
    input_fingerprint = canonical_json_hash(fingerprint_payload)
    dataset_id = input_fingerprint[:20]
    dataset_root = processed_root / symbol / dataset_id

    statistics: dict[str, Any] = {
        "verified_partitions": len(accepted),
        "excluded_partitions": len(exclusions),
        "row_count": 0,
        "duplicate_records": 0,
        "duplicate_timestamps": 0,
        "non_monotonic_timestamps": 0,
        "crossed_spreads": 0,
        "non_positive_prices": 0,
        "implausible_spreads": 0,
        "malformed_records": 0,
        "large_tick_gaps": 0,
        "maximum_tick_gap_seconds": 0.0,
    }
    examples: list[dict[str, Any]] = []
    output_files: list[dict[str, Any]] = []
    minimum_timestamp_ms: int | None = None
    maximum_timestamp_ms: int | None = None
    previous_source_timestamp_ms: int | None = None
    previous_sorted_timestamp_ms: int | None = None
    spread_limit = float(config.validation["max_spread_absolute"])
    gap_limit_ms = float(config.validation["large_tick_gap_seconds"]) * 1000

    accepted_by_date = group_partitions_by_date(accepted)
    for partition_date in sorted(accepted_by_date):
        day_records: list[dict[str, Any]] = []
        for partition in accepted_by_date[partition_date]:
            entry = manifest.get(partition)
            assert entry is not None
            path = resolve_manifest_file_path(
                entry["file_path"], repository_root=config.repository_root
            )
            assert path is not None
            # Defense in depth: classification already checked this checksum.
            if sha256_file(path) != entry["sha256"]:
                raise RuntimeError(f"raw checksum changed during build: {partition.key}")
            decoded, _rows = inspect_bi5_payload(
                path.read_bytes(),
                max_compressed_bytes=int(config.download["max_compressed_bytes"]),
            )
            for row in decode_ticks(
                decoded, partition=partition, price_scale=mapping.price_scale
            ):
                timestamp_ms = row["timestamp_ms"]
                if (
                    previous_source_timestamp_ms is not None
                    and timestamp_ms < previous_source_timestamp_ms
                ):
                    statistics["non_monotonic_timestamps"] += 1
                previous_source_timestamp_ms = timestamp_ms
                spread = row["ask"] - row["bid"]
                if row["ask"] < row["bid"]:
                    statistics["crossed_spreads"] += 1
                if row["ask"] <= 0 or row["bid"] <= 0:
                    statistics["non_positive_prices"] += 1
                if spread > spread_limit:
                    statistics["implausible_spreads"] += 1
                day_records.append(row)

        day_records.sort(key=_sort_key)
        record_counts = Counter(_row_key(row) for row in day_records)
        timestamp_counts = Counter(row["timestamp_ms"] for row in day_records)
        statistics["duplicate_records"] += sum(
            count - 1 for count in record_counts.values() if count > 1
        )
        statistics["duplicate_timestamps"] += sum(
            count - 1 for count in timestamp_counts.values() if count > 1
        )
        for row in day_records:
            timestamp_ms = row["timestamp_ms"]
            if previous_sorted_timestamp_ms is not None:
                gap_ms = timestamp_ms - previous_sorted_timestamp_ms
                if gap_ms > gap_limit_ms:
                    statistics["large_tick_gaps"] += 1
                    statistics["maximum_tick_gap_seconds"] = max(
                        statistics["maximum_tick_gap_seconds"], gap_ms / 1000
                    )
            previous_sorted_timestamp_ms = timestamp_ms
            minimum_timestamp_ms = (
                timestamp_ms
                if minimum_timestamp_ms is None
                else min(minimum_timestamp_ms, timestamp_ms)
            )
            maximum_timestamp_ms = (
                timestamp_ms
                if maximum_timestamp_ms is None
                else max(maximum_timestamp_ms, timestamp_ms)
            )
            if len(examples) < 5:
                examples.append(
                    {
                        "timestamp": _iso_millisecond(timestamp_ms),
                        "bid": row["bid"],
                        "ask": row["ask"],
                        "bid_volume": row["bid_volume"],
                        "ask_volume": row["ask_volume"],
                    }
                )
        statistics["row_count"] += len(day_records)
        if day_records:
            output_path = dataset_root / f"date={partition_date}" / "ticks.parquet"
            _atomic_write_parquet(
                output_path, _records_to_table(day_records, symbol), config
            )
            output_files.append(
                {
                    "date": partition_date,
                    "path": output_path.relative_to(config.repository_root).as_posix()
                    if output_path.is_relative_to(config.repository_root)
                    else output_path.as_posix(),
                    "row_count": len(day_records),
                    "byte_size": output_path.stat().st_size,
                    "sha256": sha256_file(output_path),
                }
            )

    unresolved_classifications = {
        "missing_partition",
        "corrupt_partition",
        "malformed_payload",
        "unresolved_status",
    }
    unresolved = sum(
        item["classification"] in unresolved_classifications
        for item in classifications.values()
    )
    expected_closures = sum(
        item["classification"] == "expected_market_closure"
        for item in classifications.values()
    )
    download_timestamps = [
        manifest.get(partition).get("download_timestamp")
        for partition in accepted
        if manifest.get(partition) and manifest.get(partition).get("download_timestamp")
    ]
    deterministic_build_timestamp = max(download_timestamps, default="1970-01-01T00:00:00Z")
    metadata: dict[str, Any] = {
        "dataset_schema_version": 1,
        "dataset_id": dataset_id,
        "build_timestamp": deterministic_build_timestamp,
        "code_version": CODE_VERSION,
        "config_version": config.version,
        "input_fingerprint": input_fingerprint,
        "manifest_sha256": source_manifest_sha256,
        "source": {
            "id": config.source["id"],
            "archive_symbol": mapping.archive_symbol,
            "feed": "dukascopy",
            "partition": "hour",
            "raw_format": "BI5/LZMA >IIIff",
        },
        "symbol": symbol,
        "timezone": "UTC",
        "timestamp_precision": "millisecond",
        "coverage": {
            "requested_start_inclusive": format_utc(start),
            "requested_end_exclusive": format_utc(end),
            "actual_first_tick": (
                _iso_millisecond(minimum_timestamp_ms)
                if minimum_timestamp_ms is not None
                else None
            ),
            "actual_last_tick": (
                _iso_millisecond(maximum_timestamp_ms)
                if maximum_timestamp_ms is not None
                else None
            ),
            "expected_partitions": len(partitions),
            "verified_partitions": len(accepted),
            "expected_market_closures": expected_closures,
            "unresolved_partitions": unresolved,
        },
        "row_count": statistics["row_count"],
        "schema": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in _schema()
        ],
        "quality_statistics": statistics,
        "validation_thresholds": dict(config.validation),
        "exclusions": exclusions,
        "bid_ask_examples": examples,
        "files": output_files,
    }
    metadata_path = dataset_root / "dataset_metadata.json"
    atomic_write_json(metadata_path, metadata)
    latest_path = processed_root / symbol / "latest.json"
    atomic_write_json(
        latest_path,
        {
            "dataset_id": dataset_id,
            "metadata_path": metadata_path.relative_to(config.repository_root).as_posix()
            if metadata_path.is_relative_to(config.repository_root)
            else metadata_path.as_posix(),
            "input_fingerprint": input_fingerprint,
        },
    )
    if report_path is not None:
        atomic_write_json(report_path, metadata)
    return {**metadata, "dataset_root": str(dataset_root), "metadata_path": str(metadata_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="inclusive UTC date/hour")
    parser.add_argument("--end", required=True, help="exclusive UTC date/hour")
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument("--raw-root")
    parser.add_argument("--manifest")
    parser.add_argument("--output-root")
    parser.add_argument("--quality-report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        symbol = args.symbol.upper()
        start = parse_utc_boundary(args.start)
        end = parse_utc_boundary(args.end)
        raw_root = Path(args.raw_root) if args.raw_root else config.path_for("raw_root")
        manifest_path = (
            Path(args.manifest)
            if args.manifest
            else config.path_for("manifests_root") / f"{symbol}_ticks_manifest.json"
        )
        processed_root = (
            Path(args.output_root) if args.output_root else config.path_for("processed_root")
        )
        report_path = (
            Path(args.quality_report)
            if args.quality_report
            else config.path_for("reports_root") / f"dukascopy_{symbol}_canonical_quality.json"
        )
        metadata = build_canonical(
            config=config,
            symbol=symbol,
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=manifest_path,
            processed_root=processed_root,
            report_path=report_path,
        )
        coverage = metadata["coverage"]
        print(f"dataset_root={metadata['dataset_root']}")
        print(f"rows={metadata['row_count']}")
        print(f"verified_partitions={coverage['verified_partitions']}")
        print(f"unresolved_partitions={coverage['unresolved_partitions']}")
        return 0 if coverage["unresolved_partitions"] == 0 else 2
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
