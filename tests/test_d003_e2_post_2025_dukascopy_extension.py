from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import lzma
from pathlib import Path

import pytest

from research.d003_e2_post_2025_dukascopy_extension.config import (
    D003E2Config,
    safe_closed_hour_cutoff,
)
from research.d003_e2_post_2025_dukascopy_extension.reporting import (
    _artifact_manifest,
    assert_isolated_paths,
)
from scripts.build_dukascopy_canonical import (
    _validate_record,
    canonical_schema,
    deduplicate_partition_records,
)
from scripts.dukascopy_common import (
    MalformedPayloadError,
    Partition,
    TICK_STRUCT,
    decode_ticks,
    generate_partitions,
    inspect_bi5_payload,
    load_config,
    partition_url,
)


UTC = timezone.utc


def test_url_construction_uses_xauusd_and_zero_based_month() -> None:
    pipeline = load_config("config/dukascopy_data.toml")
    partition = Partition(datetime(2026, 1, 2, 12, tzinfo=UTC))
    assert partition_url(pipeline, "XAUUSD", partition) == (
        "https://datafeed.dukascopy.com/datafeed/"
        "XAUUSD/2026/00/02/12h_ticks.bi5"
    )


def test_decoder_preserves_native_sides_volumes_and_scale() -> None:
    partition = Partition(datetime(2026, 1, 2, 12, tzinfo=UTC))
    packed = TICK_STRUCT.pack(
        1_234,
        2_650_250,
        2_650_100,
        3.5,
        4.25,
    )
    decoded, count = inspect_bi5_payload(
        lzma.compress(packed), max_compressed_bytes=1_000_000
    )
    rows = list(decode_ticks(decoded, partition=partition, price_scale=1000))

    assert count == 1
    assert rows == [
        {
            "timestamp_ms": int(partition.timestamp.timestamp() * 1000)
            + 1_234,
            "bid": 2650.1,
            "ask": 2650.25,
            "bid_volume": 4.25,
            "ask_volume": 3.5,
            "partition_timestamp": "2026-01-02T12:00:00Z",
        }
    ]


def test_decoder_and_record_validation_reject_invalid_values() -> None:
    out_of_hour = TICK_STRUCT.pack(
        3_600_000, 2_650_250, 2_650_100, 3.5, 4.25
    )
    with pytest.raises(MalformedPayloadError, match="out-of-hour"):
        inspect_bi5_payload(
            lzma.compress(out_of_hour), max_compressed_bytes=1_000_000
        )

    partition = Partition(datetime(2026, 1, 2, 12, tzinfo=UTC))
    invalid, reason = _validate_record(
        {
            "timestamp_ms": int(partition.timestamp.timestamp() * 1000),
            "bid": 2650.25,
            "ask": 2650.10,
            "bid_volume": 4.25,
            "ask_volume": 3.5,
        },
        partition=partition,
    )
    assert invalid is None
    assert reason == "negative_spread"


def test_cutoff_enforces_one_complete_hour_publication_lag() -> None:
    captured = datetime(2026, 7, 29, 13, 21, 38, tzinfo=UTC)
    assert safe_closed_hour_cutoff(captured) == datetime(
        2026, 7, 29, 12, tzinfo=UTC
    )
    config = D003E2Config()
    config.validate()
    assert config.requested_partition_count == 5028


def test_incomplete_and_recently_closed_partitions_are_excluded() -> None:
    config = D003E2Config()
    partitions = generate_partitions(
        datetime.fromisoformat(
            config.start_inclusive.replace("Z", "+00:00")
        ),
        datetime.fromisoformat(
            config.end_exclusive.replace("Z", "+00:00")
        ),
    )
    keys = {partition.key for partition in partitions}
    assert partitions[-1].key == "2026-07-29T11:00:00Z"
    assert "2026-07-29T12:00:00Z" not in keys
    assert "2026-07-29T13:00:00Z" not in keys


def test_candidate_schema_contract_exactly_matches_frozen_d003() -> None:
    observed = [
        (field.name, str(field.type), field.nullable)
        for field in canonical_schema()
    ]
    assert observed == [
        ("timestamp_utc", "timestamp[ms, tz=UTC]", False),
        ("bid", "double", False),
        ("ask", "double", False),
        ("bid_volume", "float", False),
        ("ask_volume", "float", False),
        ("mid", "double", False),
        ("spread", "double", False),
        ("symbol", "string", False),
        ("source_partition", "string", False),
    ]


def test_duplicate_policy_separates_within_and_boundary_duplicates() -> None:
    row = {
        "timestamp_ms": 1,
        "bid": 2650.1,
        "ask": 2650.2,
        "bid_volume": 4.0,
        "ask_volume": 3.0,
        "mid": 2650.15,
        "spread": 0.1,
        "partition_timestamp": "2026-01-02T12:00:00Z",
    }
    key = (1, 2650.1, 2650.2, 4.0, 3.0)
    kept, keys, counts = deduplicate_partition_records(
        [row, row.copy()], previous_partition_keys={key}
    )
    assert kept == []
    assert keys == {key}
    assert counts == {
        "within_partition": 1,
        "across_partition_boundary": 1,
    }


def test_task_paths_cannot_overlap_historical_canonical_tree(
    tmp_path: Path,
) -> None:
    historical = "data/canonical/xauusd_ticks"
    unsafe = replace(
        D003E2Config(),
        output_root=historical,
        raw_root=f"{historical}/raw",
        source_manifest=f"{historical}/source_manifest.json",
        verification_report=f"{historical}/verification.json",
        acquisition_log=f"{historical}/acquisition.jsonl",
    )
    with pytest.raises(ValueError, match="protected historical path"):
        assert_isolated_paths(tmp_path, unsafe)


def test_artifact_manifest_is_deterministic_and_does_not_hash_itself(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.txt").write_text("second\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\n", encoding="utf-8")
    (tmp_path / "artifact_manifest.json").write_text(
        "ignored\n", encoding="utf-8"
    )
    first = _artifact_manifest(tmp_path)
    second = _artifact_manifest(tmp_path)

    assert first == second
    assert [item["path"] for item in first["files"]] == ["a.txt", "b.txt"]

