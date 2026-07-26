from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import lzma
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import build_dukascopy_canonical as builder
from scripts.build_dukascopy_canonical import (
    CanonicalBuildError,
    _atomic_write_parquet,
    _records_to_table,
    _validate_record,
    build_canonical,
    canonical_schema,
    deduplicate_partition_records,
)
from scripts.dukascopy_common import (
    Manifest,
    Partition,
    atomic_write_bytes,
    atomic_write_json,
    load_config,
    parse_utc_boundary,
    partition_file_path,
    sha256_file,
)
from scripts.validate_canonical_dataset import verify_canonical_dataset


UTC = timezone.utc
REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY / "config" / "dukascopy_data.toml"


@pytest.fixture
def config():
    return load_config(CONFIG_PATH)


def tick_payload(
    *records: tuple[int, int, int, float, float],
) -> bytes:
    decoded = b"".join(struct.pack(">IIIff", *record) for record in records)
    return lzma.compress(decoded, format=lzma.FORMAT_ALONE)


def record_verified(
    manifest: Manifest,
    raw_root: Path,
    partition: Partition,
    payload: bytes,
) -> None:
    path = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(path, payload)
    decoded = lzma.decompress(payload)
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source="dukascopy-public-bi5",
        source_url=f"https://example.invalid/{partition.key}",
        download_timestamp="2026-07-24T20:00:00Z",
        file_path=str(path),
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        status="verified",
        retry_count=0,
        error_details=None,
        record_count=len(decoded) // 20,
    )


def record_empty_closure(manifest: Manifest, partition: Partition) -> None:
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source="dukascopy-public-bi5",
        source_url=f"https://example.invalid/{partition.key}",
        download_timestamp="2026-07-24T20:00:00Z",
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        retry_count=0,
        error_details="empty_payload: compressed response is empty",
        record_count=None,
        evidence_kind="confirmed_empty_payload",
        http_status=200,
        response_byte_length=0,
        final_attempt_timestamp="2026-07-24T20:00:00Z",
    )


def write_d002_audit(
    path: Path,
    *,
    source_manifest_path: Path,
    start: str,
    end: str,
    closures: list[tuple[str, str]],
) -> Path:
    source_sha256 = sha256_file(source_manifest_path)
    payload = {
        "audit_schema_version": 1,
        "task": "D002",
        "mode": "offline_report_only",
        "symbol": "XAUUSD",
        "range": {
            "start_inclusive": start,
            "end_exclusive": end,
        },
        "manifest_mutated": False,
        "verified_bi5_files_mutated": False,
        "integrity_proof": {
            "passed": True,
            "manifest_unchanged": True,
            "manifest_sha256_before": source_sha256,
            "manifest_sha256_after": source_sha256,
        },
        "after_reconciliation": {
            "balanced": True,
            "unresolved": 0,
        },
        "partitions": [
            {
                "partition_timestamp": timestamp,
                "classification": classification,
                "evidence_kind": "confirmed_empty_payload",
            }
            for timestamp, classification in closures
        ],
    }
    atomic_write_json(path, payload)
    return path


def representative_fixture(tmp_path: Path, config):
    start_text = "2025-01-07T19:00:00Z"
    end_text = "2025-01-08T00:00:00Z"
    start = parse_utc_boundary(start_text)
    end = parse_utc_boundary(end_text)
    raw_root = tmp_path / "raw"
    source_manifest_path = tmp_path / "source_manifest.json"
    manifest = Manifest(source_manifest_path, config=config, symbol="XAUUSD")

    holiday = Partition(datetime(2025, 1, 7, 19, tzinfo=UTC))
    special_hours = Partition(datetime(2025, 1, 7, 20, tzinfo=UTC))
    first = Partition(datetime(2025, 1, 7, 21, tzinfo=UTC))
    maintenance = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    second = Partition(datetime(2025, 1, 7, 23, tzinfo=UTC))
    record_empty_closure(manifest, holiday)
    record_empty_closure(manifest, special_hours)
    record_verified(
        manifest,
        raw_root,
        first,
        tick_payload(
            (900, 2_650_300, 2_650_100, 1.5, 3.0),
            (100, 2_650_250, 2_650_000, 1.25, 2.5),
            (100, 2_650_250, 2_650_000, 1.25, 2.5),
        ),
    )
    record_empty_closure(manifest, maintenance)
    record_verified(
        manifest,
        raw_root,
        second,
        tick_payload(
            (50, 2_651_000, 2_650_900, 2.0, 4.0),
            (500, 2_651_100, 2_651_000, 2.5, 4.5),
        ),
    )
    manifest.save()
    d002_path = write_d002_audit(
        tmp_path / "d002.json",
        source_manifest_path=source_manifest_path,
        start=start_text,
        end=end_text,
        closures=[
            (holiday.key, "expected_holiday_closure"),
            (special_hours.key, "expected_special_hours_closure"),
        ],
    )
    return {
        "start": start,
        "end": end,
        "raw_root": raw_root,
        "source_manifest_path": source_manifest_path,
        "d002_path": d002_path,
        "output_root": tmp_path / "canonical",
    }


def run_representative_build(tmp_path: Path, config):
    fixture = representative_fixture(tmp_path, config)
    result = build_canonical(
        config=config,
        symbol="XAUUSD",
        start=fixture["start"],
        end=fixture["end"],
        raw_root=fixture["raw_root"],
        manifest_path=fixture["source_manifest_path"],
        canonical_root=fixture["output_root"],
        d002_audit_path=fixture["d002_path"],
        dataset_version="test-d003-v1",
    )
    return fixture, result


def test_builder_emits_exact_schema_utc_ordering_derived_values_and_provenance(
    tmp_path, config
):
    fixture, result = run_representative_build(tmp_path, config)
    assert result["status"] == "complete"
    assert result["processed_partition_count"] == 2
    assert result["skipped_closure_counts"] == {
        "regular_market": 1,
        "holiday": 1,
        "special_hours": 1,
    }
    assert result["duplicate_count"] == 1
    assert result["rejected_record_count"] == 0
    assert result["row_count"] == 4
    assert result["canonical_file_count"] == 1
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    assert parquet_path.relative_to(fixture["output_root"]) == Path(
        "year=2025/month=01/xauusd_ticks_2025-01-07.parquet"
    )
    table = pq.ParquetFile(parquet_path).read()
    assert table.schema == canonical_schema()
    values = table.to_pydict()
    assert values["timestamp_utc"] == sorted(values["timestamp_utc"])
    assert all(value.tzinfo is not None for value in values["timestamp_utc"])
    assert values["mid"] == [
        (bid + ask) / 2 for bid, ask in zip(values["bid"], values["ask"])
    ]
    assert values["spread"] == [
        ask - bid for bid, ask in zip(values["bid"], values["ask"])
    ]
    assert set(values["symbol"]) == {"XAUUSD"}
    assert set(values["source_partition"]) == {
        "2025-01-07T21:00:00Z",
        "2025-01-07T23:00:00Z",
    }


def test_independent_verifier_accepts_complete_reconciled_build(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=Path(result["metadata_path"]),
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is True
    assert report["errors"] == []
    assert report["metrics"]["duplicate_ticks"] == 0
    assert report["metrics"]["verified_source_partitions"] == 2
    assert report["metrics"]["regular_market_closures"] == 1
    assert report["metrics"]["holiday_closures"] == 1
    assert report["metrics"]["special_hours_closures"] == 1


def test_resume_reuses_completed_output_without_overwrite(tmp_path, config):
    fixture, first = run_representative_build(tmp_path, config)
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    manifest_path = Path(first["metadata_path"])
    parquet_mtime = parquet_path.stat().st_mtime_ns
    manifest_mtime = manifest_path.stat().st_mtime_ns
    second = build_canonical(
        config=config,
        symbol="XAUUSD",
        start=fixture["start"],
        end=fixture["end"],
        raw_root=fixture["raw_root"],
        manifest_path=fixture["source_manifest_path"],
        canonical_root=fixture["output_root"],
        d002_audit_path=fixture["d002_path"],
        dataset_version="test-d003-v1",
    )
    assert second["resumed"] is True
    assert second["reused_file_count"] == 1
    assert parquet_path.stat().st_mtime_ns == parquet_mtime
    assert manifest_path.stat().st_mtime_ns == manifest_mtime


def test_resume_reuses_checkpoint_after_interrupted_multi_day_build(
    tmp_path, config, monkeypatch
):
    start = parse_utc_boundary("2025-01-07T23:00:00Z")
    end = parse_utc_boundary("2025-01-08T01:00:00Z")
    raw_root = tmp_path / "raw"
    source_manifest_path = tmp_path / "source_manifest.json"
    manifest = Manifest(source_manifest_path, config=config, symbol="XAUUSD")
    for partition in (
        Partition(datetime(2025, 1, 7, 23, tzinfo=UTC)),
        Partition(datetime(2025, 1, 8, 0, tzinfo=UTC)),
    ):
        record_verified(
            manifest,
            raw_root,
            partition,
            tick_payload((100, 2_650_100, 2_650_000, 1.0, 2.0)),
        )
    manifest.save()
    output_root = tmp_path / "canonical"
    original_write = builder._atomic_write_parquet
    calls = 0

    def interrupt_second_file(path, table, active_config):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interruption")
        original_write(path, table, active_config)

    monkeypatch.setattr(builder, "_atomic_write_parquet", interrupt_second_file)
    with pytest.raises(OSError, match="simulated interruption"):
        build_canonical(
            config=config,
            symbol="XAUUSD",
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=source_manifest_path,
            canonical_root=output_root,
            dataset_version="test-d003-v1",
        )
    checkpoint = json.loads((output_root / "canonical_manifest.json").read_text())
    assert checkpoint["status"] == "building"
    assert checkpoint["canonical_file_count"] == 1
    first_path = next(output_root.rglob("*.parquet"))
    first_mtime = first_path.stat().st_mtime_ns

    monkeypatch.setattr(builder, "_atomic_write_parquet", original_write)
    resumed = build_canonical(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=source_manifest_path,
        canonical_root=output_root,
        dataset_version="test-d003-v1",
    )
    assert resumed["status"] == "complete"
    assert resumed["reused_file_count"] == 1
    assert resumed["canonical_file_count"] == 2
    assert first_path.stat().st_mtime_ns == first_mtime


def test_deterministic_parquet_bytes_across_clean_output_roots(tmp_path, config):
    fixture = representative_fixture(tmp_path, config)
    hashes = []
    fingerprints = []
    for name in ("canonical-a", "canonical-b"):
        result = build_canonical(
            config=config,
            symbol="XAUUSD",
            start=fixture["start"],
            end=fixture["end"],
            raw_root=fixture["raw_root"],
            manifest_path=fixture["source_manifest_path"],
            canonical_root=tmp_path / name,
            d002_audit_path=fixture["d002_path"],
            dataset_version="test-d003-v1",
        )
        hashes.append(result["files"][0]["sha256"])
        fingerprints.append(result["input_fingerprint"])
    assert hashes[0] == hashes[1]
    assert fingerprints[0] == fingerprints[1]


def test_duplicate_detection_distinguishes_partition_boundary_removals():
    row = {
        "timestamp_ms": 1,
        "bid": 2.0,
        "ask": 2.1,
        "bid_volume": 3.0,
        "ask_volume": 4.0,
        "mid": 2.05,
        "spread": 0.1,
        "partition_timestamp": "2025-01-01T01:00:00Z",
    }
    key = (1, 2.0, 2.1, 3.0, 4.0)
    kept, _, counts = deduplicate_partition_records(
        [row, dict(row)],
        previous_partition_keys={key},
    )
    assert kept == []
    assert counts == {
        "within_partition": 1,
        "across_partition_boundary": 1,
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"bid": 0.0}, "non_positive_price"),
        ({"bid": 2.2, "ask": 2.1}, "negative_spread"),
        ({"bid_volume": -1.0}, "negative_volume"),
    ],
)
def test_record_validation_rejects_invalid_values(changes, reason):
    partition = Partition(datetime(2025, 1, 7, 21, tzinfo=UTC))
    row = {
        "timestamp_ms": int(partition.timestamp.timestamp() * 1000) + 100,
        "bid": 2.0,
        "ask": 2.1,
        "bid_volume": 3.0,
        "ask_volume": 4.0,
    }
    row.update(changes)
    normalized, actual_reason = _validate_record(row, partition=partition)
    assert normalized is None
    assert actual_reason == reason


def test_builder_fails_closed_and_reports_rejected_record_count(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T20:00:00Z")
    end = parse_utc_boundary("2025-01-07T21:00:00Z")
    partition = Partition(start)
    raw_root = tmp_path / "raw"
    source_manifest_path = tmp_path / "source_manifest.json"
    manifest = Manifest(source_manifest_path, config=config, symbol="XAUUSD")
    record_verified(
        manifest,
        raw_root,
        partition,
        tick_payload(
            (100, 0, 0, 1.0, 1.0),
            (200, 2_650_000, 2_651_000, 1.0, 1.0),
            (300, 2_650_000, 2_649_000, -1.0, 1.0),
        ),
    )
    manifest.save()
    output_root = tmp_path / "canonical"
    with pytest.raises(CanonicalBuildError, match="rejected 3"):
        build_canonical(
            config=config,
            symbol="XAUUSD",
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=source_manifest_path,
            canonical_root=output_root,
        )
    failed = json.loads((output_root / "canonical_manifest.json").read_text())
    assert failed["status"] == "failed"
    assert failed["rejected_record_count"] == 3
    assert not list(output_root.rglob("*.parquet"))


def test_builder_rejects_malformed_verified_payload_before_output(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T20:00:00Z")
    end = parse_utc_boundary("2025-01-07T21:00:00Z")
    partition = Partition(start)
    raw_root = tmp_path / "raw"
    source_manifest_path = tmp_path / "source_manifest.json"
    manifest = Manifest(source_manifest_path, config=config, symbol="XAUUSD")
    malformed = lzma.compress(b"x", format=lzma.FORMAT_ALONE)
    path = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(path, malformed)
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source="dukascopy-public-bi5",
        source_url="https://example.invalid/malformed",
        download_timestamp="2026-07-24T20:00:00Z",
        file_path=str(path),
        byte_size=len(malformed),
        sha256=sha256_file(path),
        status="verified",
        retry_count=0,
        error_details=None,
        record_count=0,
    )
    manifest.save()
    output_root = tmp_path / "canonical"
    with pytest.raises(CanonicalBuildError, match="malformed_payload"):
        build_canonical(
            config=config,
            symbol="XAUUSD",
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=source_manifest_path,
            canonical_root=output_root,
        )
    assert not output_root.exists()


def test_atomic_parquet_write_cleans_temporary_file_on_failure(
    tmp_path, config, monkeypatch
):
    records = [
        {
            "timestamp_ms": 1_735_947_600_000,
            "bid": 2650.0,
            "ask": 2650.1,
            "bid_volume": 1.0,
            "ask_volume": 2.0,
            "mid": 2650.05,
            "spread": 0.1,
            "partition_timestamp": "2025-01-04T00:00:00Z",
        }
    ]
    table = _records_to_table(records, "XAUUSD")
    destination = tmp_path / "ticks.parquet"

    def fail_write(*_args, **_kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(builder.pq, "write_table", fail_write)
    with pytest.raises(OSError, match="simulated"):
        _atomic_write_parquet(destination, table, config)
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_verifier_detects_corrupted_parquet(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    payload = bytearray(parquet_path.read_bytes())
    payload[len(payload) // 2] ^= 0xFF
    parquet_path.write_bytes(payload)
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=Path(result["metadata_path"]),
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert any("SHA256 mismatch" in error for error in report["errors"])


def test_verifier_detects_empty_parquet_file(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    manifest_path = Path(result["metadata_path"])
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    table = pq.ParquetFile(parquet_path).read()
    rewrite_parquet_and_refresh_file_manifest(
        parquet_path,
        manifest_path,
        table.slice(0, 0),
    )
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=manifest_path,
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert report["metrics"]["empty_parquet_files"] == 1
    assert any("Parquet is empty" in error for error in report["errors"])


def test_verifier_detects_duplicate_tick(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    manifest_path = Path(result["metadata_path"])
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    table = pq.ParquetFile(parquet_path).read()
    duplicate = pa.concat_tables([table.slice(0, 1), table])
    rewrite_parquet_and_refresh_file_manifest(
        parquet_path,
        manifest_path,
        duplicate,
    )
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=manifest_path,
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert report["metrics"]["duplicate_ticks"] == 1
    assert any("duplicate ticks" in error for error in report["errors"])


def test_verifier_detects_manifest_reconciliation_tampering(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    manifest_path = Path(result["metadata_path"])
    payload = json.loads(manifest_path.read_text())
    payload["row_count"] += 1
    payload["reconciliation"]["accounted_partitions"] -= 1
    atomic_write_json(manifest_path, payload)
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=manifest_path,
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert any("row_count mismatch" in error for error in report["errors"])
    assert any("reconciliation mismatch" in error for error in report["errors"])


def rewrite_parquet_and_refresh_file_manifest(
    parquet_path: Path,
    manifest_path: Path,
    table: pa.Table,
) -> None:
    pq.write_table(table, parquet_path)
    payload = json.loads(manifest_path.read_text())
    payload["files"][0]["sha256"] = sha256_file(parquet_path)
    payload["files"][0]["byte_size"] = parquet_path.stat().st_size
    atomic_write_json(manifest_path, payload)


def test_verifier_detects_schema_mismatch_even_with_matching_hash(tmp_path, config):
    fixture, result = run_representative_build(tmp_path, config)
    manifest_path = Path(result["metadata_path"])
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    table = pq.ParquetFile(parquet_path).read()
    altered = table.set_column(
        table.schema.get_field_index("bid"),
        "bid",
        pa.array(table["bid"].to_pylist(), type=pa.float32()),
    )
    rewrite_parquet_and_refresh_file_manifest(parquet_path, manifest_path, altered)
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=manifest_path,
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert any("schema mismatch" in error for error in report["errors"])


@pytest.mark.parametrize(
    ("column", "value", "expected_error"),
    [
        ("bid", 0.0, "invalid prices"),
        ("spread", -1.0, "invalid spreads"),
        ("bid_volume", -1.0, "invalid volumes"),
    ],
)
def test_verifier_detects_invalid_canonical_values(
    tmp_path, config, column, value, expected_error
):
    fixture, result = run_representative_build(tmp_path, config)
    manifest_path = Path(result["metadata_path"])
    parquet_path = next(fixture["output_root"].rglob("*.parquet"))
    table = pq.ParquetFile(parquet_path).read()
    values = table[column].to_pylist()
    values[0] = value
    altered = table.set_column(
        table.schema.get_field_index(column),
        table.schema.field(column),
        pa.array(values, type=table.schema.field(column).type),
    )
    rewrite_parquet_and_refresh_file_manifest(parquet_path, manifest_path, altered)
    report = verify_canonical_dataset(
        config=config,
        canonical_root=fixture["output_root"],
        canonical_manifest_path=manifest_path,
        source_manifest_path=fixture["source_manifest_path"],
        raw_root=fixture["raw_root"],
        d002_audit_path=fixture["d002_path"],
    )
    assert report["passed"] is False
    assert any(expected_error in error for error in report["errors"])
