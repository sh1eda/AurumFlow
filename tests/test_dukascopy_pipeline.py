from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import lzma
from pathlib import Path
import struct

import pytest

from scripts import download_dukascopy_ticks as downloader
from scripts.build_dukascopy_canonical import build_canonical
from scripts.dukascopy_common import (
    EmptyPayloadError,
    MalformedPayloadError,
    Manifest,
    Partition,
    PlaceholderPayloadError,
    StructuredLogger,
    atomic_write_bytes,
    decode_ticks,
    generate_partitions,
    inspect_bi5_payload,
    is_expected_closure,
    load_config,
    parse_utc_boundary,
    partition_file_path,
    partition_url,
    sha256_file,
)
from scripts.download_dukascopy_ticks import (
    HttpResult,
    SourceRequestError,
    download_range,
    fetch_with_retry,
)
from scripts.verify_dukascopy_downloads import classify_partition, verify_range


UTC = timezone.utc
REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY / "config" / "dukascopy_data.toml"


def tick_bytes(
    *records: tuple[int, int, int, float, float],
) -> bytes:
    raw = b"".join(struct.pack(">IIIff", *record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def sample_payload() -> bytes:
    return tick_bytes(
        (100, 2_650_250, 2_650_100, 1.25, 2.5),
        (900, 2_650_300, 2_650_150, 1.5, 3.0),
    )


@pytest.fixture
def config():
    loaded = load_config(CONFIG_PATH)
    loaded.download["throttle_seconds"] = 0.0
    loaded.download["backoff_initial_seconds"] = 0.0
    loaded.download["backoff_max_seconds"] = 0.0
    return loaded


class SequenceTransport:
    def __init__(self, events):
        self.events = list(events)
        self.calls = 0

    def fetch(self, _url, *, timeout, headers):
        assert timeout > 0
        assert "User-Agent" in headers
        self.calls += 1
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "manifests" / "XAUUSD_ticks_manifest.json"


def test_url_generation_uses_native_zero_based_month(config):
    partition = Partition(datetime(2024, 2, 29, 7, tzinfo=UTC))
    assert partition_url(config, "XAUUSD", partition) == (
        "https://datafeed.dukascopy.com/datafeed/XAUUSD/2024/01/29/07h_ticks.bi5"
    )
    assert partition_file_path(Path("raw"), "XAUUSD", partition) == Path(
        "raw/XAUUSD/2024/02/29/07h_ticks.bi5"
    )


def test_utc_boundaries_are_inclusive_start_exclusive_end_and_cover_leap_day():
    start = parse_utc_boundary("2024-02-28")
    end = parse_utc_boundary("2024-03-01")
    partitions = generate_partitions(start, end)
    assert len(partitions) == 48
    assert partitions[0].key == "2024-02-28T00:00:00Z"
    assert partitions[-1].key == "2024-02-29T23:00:00Z"
    with pytest.raises(ValueError, match="explicit UTC offset"):
        parse_utc_boundary("2024-02-29T01:00:00")


def test_weekend_handling_uses_only_configured_calendar_rules(config):
    saturday = Partition(datetime(2025, 1, 11, 12, tzinfo=UTC))
    sunday = Partition(datetime(2025, 1, 12, 12, tzinfo=UTC))
    assert is_expected_closure(config, saturday) is True
    assert is_expected_closure(config, sunday) is False


def test_payload_validation_rejects_empty_malformed_and_placeholder(config):
    limit = config.download["max_compressed_bytes"]
    with pytest.raises(EmptyPayloadError):
        inspect_bi5_payload(b"", max_compressed_bytes=limit)
    with pytest.raises(MalformedPayloadError, match="decompression"):
        inspect_bi5_payload(b"not-lzma", max_compressed_bytes=limit)
    with pytest.raises(PlaceholderPayloadError):
        inspect_bi5_payload(b"<!DOCTYPE html><title>404</title>", max_compressed_bytes=limit)
    malformed = lzma.compress(b"123", format=lzma.FORMAT_ALONE)
    with pytest.raises(MalformedPayloadError, match="not divisible"):
        inspect_bi5_payload(malformed, max_compressed_bytes=limit)


def test_binary_decoding_preserves_bid_ask_precision_and_scaling(config):
    partition = Partition(datetime(2025, 1, 7, 1, tzinfo=UTC))
    decoded, count = inspect_bi5_payload(
        sample_payload(), max_compressed_bytes=config.download["max_compressed_bytes"]
    )
    rows = list(decode_ticks(decoded, partition=partition, price_scale=1000))
    assert count == 2
    assert rows[0]["timestamp_ms"] == int(partition.timestamp.timestamp() * 1000) + 100
    assert rows[0]["bid"] == 2650.1
    assert rows[0]["ask"] == 2650.25
    assert rows[0]["bid_volume"] == 2.5
    assert rows[0]["ask_volume"] == 1.25


def test_retry_logic_uses_exponential_backoff_and_returns_retry_count(config):
    transport = SequenceTransport(
        [
            SourceRequestError("temporary", retryable=True),
            SourceRequestError("still temporary", retryable=True),
            HttpResult(200, sample_payload(), {}),
        ]
    )
    sleeps: list[float] = []
    result, retries = fetch_with_retry(
        "https://example.invalid/partition",
        transport=transport,
        timeout=1,
        user_agent="test",
        max_attempts=4,
        backoff_initial=1,
        backoff_max=8,
        throttle=0,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
        partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    assert result.status == 200
    assert retries == 2
    assert sleeps == [1, 2]


def test_non_retryable_http_failure_stops_immediately():
    transport = SequenceTransport([SourceRequestError("HTTP 404", retryable=False)])
    with pytest.raises(SourceRequestError, match="404"):
        fetch_with_retry(
            "https://example.invalid/missing",
            transport=transport,
            timeout=1,
            user_agent="test",
            max_attempts=4,
            backoff_initial=1,
            backoff_max=8,
            throttle=0,
            sleep=lambda _seconds: None,
            logger=StructuredLogger(quiet=True),
            partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
        )
    assert transport.calls == 1


def test_download_manifest_atomic_write_and_safe_resume(tmp_path, config):
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    transport = SequenceTransport([HttpResult(200, sample_payload(), {})])
    kwargs = dict(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=raw_root,
        manifest_path=path,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    first = download_range(transport=transport, **kwargs)
    second_transport = SequenceTransport([])
    second = download_range(transport=second_transport, **kwargs)
    payload = json.loads(path.read_text())
    entry = payload["partitions"]["2025-01-07T00:00:00Z"]
    raw_file = partition_file_path(
        raw_root, "XAUUSD", Partition(datetime(2025, 1, 7, tzinfo=UTC))
    )
    assert first["downloaded"] == 1
    assert second["resumed_verified"] == 1
    assert second_transport.calls == 0
    assert entry["status"] == "verified"
    assert entry["byte_size"] == raw_file.stat().st_size
    assert entry["sha256"] == sha256_file(raw_file)
    assert entry["record_count"] == 2
    assert not list(raw_file.parent.glob("*.tmp"))


def test_existing_valid_file_is_recovered_without_network(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(raw_file, sample_payload())
    transport = SequenceTransport([])
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=datetime(2025, 1, 7, 1, tzinfo=UTC),
        raw_root=raw_root,
        manifest_path=manifest_path(tmp_path),
        transport=transport,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["recovered_existing"] == 1
    assert summary["unresolved"] == 0
    assert transport.calls == 0


def test_checksum_drift_requires_source_redownload_not_local_adoption(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=datetime(2025, 1, 7, 1, tzinfo=UTC),
        raw_root=raw_root,
        manifest_path=path,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    download_range(
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]), **common
    )
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    different_valid_payload = tick_bytes((50, 2_640_100, 2_640_000, 1.0, 2.0))
    atomic_write_bytes(raw_file, different_valid_payload)
    source_transport = SequenceTransport([HttpResult(200, sample_payload(), {})])
    summary = download_range(transport=source_transport, **common)
    assert source_transport.calls == 1
    assert summary["downloaded"] == 1
    assert raw_file.read_bytes() == sample_payload()


def test_empty_response_is_failed_not_market_closure(tmp_path, config):
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=SequenceTransport([HttpResult(200, b"", {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    entry = json.loads(manifest_path(tmp_path).read_text())["partitions"][
        "2025-01-07T00:00:00Z"
    ]
    assert summary["failed"] == 1
    assert summary["unresolved"] == 1
    assert entry["status"] == "failed"
    assert "empty_payload" in entry["error_details"]


def test_failed_or_missing_selection_redrives_failed_partition(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    download_range(
        transport=SequenceTransport([SourceRequestError("HTTP 404", retryable=False)]),
        **common,
    )
    summary = download_range(
        mode="failed-or-missing",
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        **common,
    )
    assert summary["downloaded"] == 1
    assert summary["unresolved"] == 0


def test_checksum_verification_detects_corruption(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    raw_file = next(raw_root.rglob("*.bi5"))
    atomic_write_bytes(raw_file, sample_payload() + b"tampered")
    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
    )
    assert report["counts"]["corrupt_partition"] == 1
    assert report["counts"]["unresolved"] == 1


def test_verifier_detects_checksum_valid_but_malformed_payload(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    malformed = lzma.compress(b"not-a-20-byte-record", format=lzma.FORMAT_ALONE)
    atomic_write_bytes(raw_file, malformed)
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source=config.source["id"],
        source_url=partition_url(config, "XAUUSD", partition),
        download_timestamp="2025-01-08T00:00:00Z",
        file_path=str(raw_file),
        byte_size=len(malformed),
        sha256=hashlib.sha256(malformed).hexdigest(),
        status="verified",
        retry_count=0,
        error_details=None,
        record_count=None,
    )
    manifest.save()
    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )
    assert result["classification"] == "malformed_payload"


def test_verifier_distinguishes_closure_missing_and_unresolved(tmp_path, config):
    empty_manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    empty_manifest.save()
    saturday = Partition(datetime(2025, 1, 11, 12, tzinfo=UTC))
    monday = Partition(datetime(2025, 1, 13, 12, tzinfo=UTC))
    closure = classify_partition(
        config=config,
        manifest=empty_manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=saturday,
    )
    missing = classify_partition(
        config=config,
        manifest=empty_manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=monday,
    )
    assert closure["classification"] == "expected_market_closure"
    assert missing["classification"] == "missing_partition"


def test_atomic_write_leaves_complete_target_and_no_temporary_file(tmp_path):
    destination = tmp_path / "nested" / "result.bin"
    atomic_write_bytes(destination, b"first")
    atomic_write_bytes(destination, b"second")
    assert destination.read_bytes() == b"second"
    assert list(destination.parent.glob("*.tmp")) == []


def test_cli_returns_nonzero_when_unresolved_failures_remain(monkeypatch, tmp_path):
    monkeypatch.setattr(
        downloader,
        "download_range",
        lambda **_kwargs: {"unresolved": 1},
    )
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--no-log-file",
            "--quiet",
        ]
    )
    assert code == 2


def test_canonical_quality_checks_and_deterministic_output(tmp_path, config):
    pytest.importorskip("pyarrow")
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    payload = tick_bytes(
        (1000, 2_650_100, 2_650_000, 1.0, 2.0),
        (500, 2_649_000, 2_650_000, 1.5, 2.5),  # non-monotonic and crossed
        (500, 2_649_000, 2_650_000, 1.5, 2.5),  # exact duplicate
        (2_000, 2_660_000, 2_650_000, 2.0, 3.0),  # implausible spread
    )
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        transport=SequenceTransport([HttpResult(200, payload, {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    kwargs = dict(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        processed_root=tmp_path / "processed",
    )
    first = build_canonical(**kwargs)
    first_metadata_bytes = Path(first["metadata_path"]).read_bytes()
    first_parquet = Path(first["dataset_root"]) / "date=2025-01-07" / "ticks.parquet"
    first_checksum = hashlib.sha256(first_parquet.read_bytes()).hexdigest()
    second = build_canonical(**kwargs)
    second_checksum = hashlib.sha256(first_parquet.read_bytes()).hexdigest()
    quality = first["quality_statistics"]
    assert first["row_count"] == 4
    assert quality["non_monotonic_timestamps"] == 1
    assert quality["duplicate_records"] == 1
    assert quality["duplicate_timestamps"] == 1
    assert quality["crossed_spreads"] == 2
    assert quality["implausible_spreads"] == 1
    assert first["bid_ask_examples"][0]["timestamp"].endswith("00.500Z")
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert first_metadata_bytes == Path(second["metadata_path"]).read_bytes()
    assert first_checksum == second_checksum


def test_builder_reports_missing_partition_without_imputation(tmp_path, config):
    pytest.importorskip("pyarrow")
    path = manifest_path(tmp_path)
    Manifest(path, config=config, symbol="XAUUSD").save()
    metadata = build_canonical(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
        processed_root=tmp_path / "processed",
    )
    assert metadata["row_count"] == 0
    assert metadata["coverage"]["unresolved_partitions"] == 1
    assert metadata["exclusions"][0]["classification"] == "missing_partition"
