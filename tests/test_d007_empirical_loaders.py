from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research.d007_association_identity import ASSOCIATION_ARTIFACT_PATHS, ASSOCIATION_PROJECTIONS
from research.d007_methodology_clarification import ArtifactIdentity, UPSTREAM_ARTIFACTS
from research.d007_ote_historical_contract.loaders import (
    ASSOCIATION_PROJECTIONS_BY_PATH,
    FROZEN_D004_MARKET_FULL_SCHEMA,
    FROZEN_UPSTREAM_PROJECTED_SCHEMAS,
    FrozenParquetLoadError,
    GENERIC_OHLC_COLUMNS,
    MARKET_PROJECTION,
    MarketParquetRecord,
    load_market_bars,
    load_structural_artifact,
)


class _TrackedParquet:
    def __init__(self, path: Path, calls: list[tuple[str, tuple[str, ...]]]) -> None:
        self._reader = pq.ParquetFile(path)
        self.schema_arrow = self._reader.schema_arrow
        self._calls = calls
        self._path = path.name

    def read(self, *, columns: list[str]):
        self._calls.append((self._path, tuple(columns)))
        return self._reader.read(columns=columns)


class _DishonestParquet(_TrackedParquet):
    """A backend that claims projection but returns all columns."""

    def read(self, *, columns: list[str]):
        self._calls.append((self._path, tuple(columns)))
        return self._reader.read()


def _write(root: Path, relative: str, frame: pd.DataFrame) -> tuple[Path, str, int]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path, sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _write_table(root: Path, relative: str, table: pa.Table) -> tuple[Path, str, int]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path, sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _market_frame(start: str = "2025-01-02T10:00:00Z") -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=2, freq="min", tz="UTC")
    return pd.DataFrame({
        "timestamp_utc": timestamps,
        "bid_open": [100.0, 101.0], "bid_high": [102.0, 103.0], "bid_low": [99.0, 100.0], "bid_close": [101.0, 102.0],
        "ask_open": [100.2, 101.2], "ask_high": [102.2, 103.2], "ask_low": [99.2, 100.2], "ask_close": [101.2, 102.2],
        "mid_open": [100.1, 101.1], "mid_high": [102.1, 103.1], "mid_low": [99.1, 100.1], "mid_close": [101.1, 102.1],
        "tick_count": [1, 1], "median_spread": [0.2, 0.2], "maximum_spread": [0.2, 0.2], "last_spread": [0.2, 0.2],
        "outcome_return_60m": [999.0, 999.0], "later_revision": [True, True],
    })


def _record(root: Path, relative: str, frame: pd.DataFrame) -> MarketParquetRecord:
    path, digest, size = _write(root, relative, frame)
    signature = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(path).schema_arrow.remove_metadata())
    return MarketParquetRecord(relative, digest, size, signature)


def test_market_reader_projects_only_ohlc_and_returns_detached_generic_shape(tmp_path: Path) -> None:
    record = _record(tmp_path, "year=2025/month=01/a.parquet", _market_frame())
    calls: list[tuple[str, tuple[str, ...]]] = []
    result = load_market_bars(tmp_path, [record], parquet_file_factory=lambda path: _TrackedParquet(path, calls))
    assert calls == [("a.parquet", MARKET_PROJECTION)]
    assert tuple(result.columns) == GENERIC_OHLC_COLUMNS
    assert set(result.columns).isdisjoint({"outcome_return_60m", "later_revision", "mid_open"})
    assert result["timestamp_utc"].dtype.tz is not None
    assert tuple(FROZEN_D004_MARKET_FULL_SCHEMA[0]) == ("timestamp_utc", "timestamp[ms, tz=UTC]", True)


def test_market_rejects_backend_that_returns_extra_columns_despite_projection(tmp_path: Path) -> None:
    record = _record(tmp_path, "bars.parquet", _market_frame())
    calls: list[tuple[str, tuple[str, ...]]] = []
    with pytest.raises(FrozenParquetLoadError, match="extra, missing, or reordered"):
        load_market_bars(tmp_path, [record], parquet_file_factory=lambda path: _DishonestParquet(path, calls))
    assert calls == [("bars.parquet", MARKET_PROJECTION)]


def test_structural_adapter_uses_the_registry_complete_allowlist_only(tmp_path: Path) -> None:
    frame = pd.DataFrame({"event_id": ["e1"], "event_at": [pd.Timestamp("2025-01-02T10:00:00Z")], "outcome": [999.0], "later_completion": [True]})
    path, digest, _ = _write(tmp_path, "upstream/events.parquet", frame)
    identity = ArtifactIdentity("TEST", "upstream/events.parquet", digest, None, None, "version.json", "0" * 64, "TEST:1", "schema.json@0", ("event_id", "event_at"), "test")
    calls: list[tuple[str, tuple[str, ...]]] = []
    actual_schema = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(path).schema_arrow.remove_metadata())
    result = load_structural_artifact(tmp_path, identity, parquet_file_factory=lambda item: _TrackedParquet(item, calls), expected_full_schema=actual_schema, expected_byte_size=path.stat().st_size, timestamp_columns=("event_at",), unique_columns=("event_id",), order_columns=("event_at", "event_id"))
    assert calls == [("events.parquet", ("event_id", "event_at"))]
    assert tuple(result.columns) == ("event_id", "event_at")


def test_loader_rejects_missing_projection_schema_drift_hash_and_alternate_path_before_rows(tmp_path: Path) -> None:
    record = _record(tmp_path, "year=2025/month=01/a.parquet", _market_frame())
    with pytest.raises(FrozenParquetLoadError, match="schema drift"):
        load_market_bars(tmp_path, [replace(record, expected_full_schema=FROZEN_D004_MARKET_FULL_SCHEMA)])
    with pytest.raises(FrozenParquetLoadError, match="SHA-256"):
        load_market_bars(tmp_path, [replace(record, sha256="0" * 64)])
    with pytest.raises(FrozenParquetLoadError, match="missing"):
        load_market_bars(tmp_path, [replace(record, relative_path="year=2025/month=01/missing.parquet")])
    link = tmp_path / "year=2025/month=01/link.parquet"
    link.symlink_to(tmp_path / "year=2025/month=01/a.parquet")
    with pytest.raises(FrozenParquetLoadError, match="symlink"):
        load_market_bars(tmp_path, [replace(record, relative_path="year=2025/month=01/link.parquet")])


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (lambda: _market_frame().drop(columns="mid_close"), "projection columns missing"),
        (lambda: pd.concat([_market_frame(), _market_frame().iloc[[0]]], ignore_index=True), "duplicate"),
        (lambda: _market_frame("2026-01-01T00:00:00Z"), "2026-or-later"),
    ],
)
def test_market_missing_columns_duplicate_order_and_terminal_fail_closed(tmp_path: Path, frame, message: str) -> None:
    record = _record(tmp_path, "bars.parquet", frame())
    with pytest.raises(FrozenParquetLoadError, match=message):
        load_market_bars(tmp_path, [record])


def test_market_file_order_and_dst_safe_timestamp_normalization(tmp_path: Path) -> None:
    later = _record(tmp_path, "z.parquet", _market_frame("2025-07-15T21:59:00Z"))
    earlier = _record(tmp_path, "a.parquet", _market_frame("2025-01-15T22:59:00Z"))
    result = load_market_bars(tmp_path, [later, earlier])
    assert result["timestamp_utc"].tolist() == sorted(result["timestamp_utc"].tolist())
    assert result["timestamp_utc"].iloc[0] == pd.Timestamp("2025-01-15T22:59:00Z")


def test_authenticated_rows_are_stably_sorted_by_frozen_keys(tmp_path: Path) -> None:
    market = _market_frame().iloc[::-1].reset_index(drop=True)
    record = _record(tmp_path, "bars.parquet", market)
    loaded_market = load_market_bars(tmp_path, [record])
    assert loaded_market["timestamp_utc"].tolist() == sorted(
        loaded_market["timestamp_utc"].tolist()
    )

    structural = pd.DataFrame(
        {
            "event_id": ["b", "a"],
            "event_at": [
                pd.Timestamp("2025-01-02T10:05:00Z"),
                pd.Timestamp("2025-01-02T10:00:00Z"),
            ],
        }
    )
    path, digest, size = _write(tmp_path, "events.parquet", structural)
    identity = ArtifactIdentity(
        "TEST", "events.parquet", digest, None, None, "version.json", "0" * 64,
        "TEST:1", "schema.json@0", ("event_id", "event_at"), "test",
    )
    signature = tuple(
        (field.name, str(field.type), field.nullable)
        for field in pq.ParquetFile(path).schema_arrow.remove_metadata()
    )
    loaded_structural = load_structural_artifact(
        tmp_path,
        identity,
        expected_full_schema=signature,
        expected_byte_size=size,
        timestamp_columns=("event_at",),
        unique_columns=("event_id",),
        order_columns=("event_at", "event_id"),
    )
    assert loaded_structural["event_id"].tolist() == ["a", "b"]


def test_structural_timestamp_naive_and_duplicate_identity_fail_closed(tmp_path: Path) -> None:
    frame = pd.DataFrame({"event_id": ["e1", "e1"], "event_at": ["2025-01-02T10:00:00", "2025-01-02T10:05:00"]})
    _, digest, _ = _write(tmp_path, "events.parquet", frame)
    identity = ArtifactIdentity("TEST", "events.parquet", digest, None, None, "version.json", "0" * 64, "TEST:1", "schema.json@0", ("event_id", "event_at"), "test")
    with pytest.raises(FrozenParquetLoadError, match="timezone-aware"):
        load_structural_artifact(tmp_path, identity, expected_byte_size=(tmp_path / "events.parquet").stat().st_size, timestamp_columns=("event_at",), unique_columns=("event_id",))


def test_registered_projection_schemas_cover_every_frozen_upstream() -> None:
    assert set(FROZEN_UPSTREAM_PROJECTED_SCHEMAS) == {item.path for item in UPSTREAM_ARTIFACTS}
    for identity in UPSTREAM_ARTIFACTS:
        expected = ASSOCIATION_PROJECTIONS_BY_PATH.get(identity.path, identity.required_columns)
        assert tuple(field[0] for field in FROZEN_UPSTREAM_PROJECTED_SCHEMAS[identity.path]) == expected


def _association_table(role: str) -> pa.Table:
    if role == "d004_daily_events":
        fields = [
            pa.field("trading_date", pa.date32()),
            pa.field("primary_reference_name", pa.large_string()),
            pa.field("high_sweep", pa.bool_()),
            pa.field("low_sweep", pa.bool_()),
            pa.field("high_sweep_time", pa.timestamp("ms", tz="UTC")),
            pa.field("low_sweep_time", pa.timestamp("ms", tz="UTC")),
            pa.field("high_reentry", pa.bool_()),
            pa.field("low_reentry", pa.bool_()),
            pa.field("high_reentry_time", pa.timestamp("ms", tz="UTC")),
            pa.field("low_reentry_time", pa.timestamp("ms", tz="UTC")),
        ]
        values: dict[str, object] = {
            "trading_date": pd.Timestamp("2025-01-02").date(),
            "primary_reference_name": "asia_range",
            "high_sweep": True, "low_sweep": False,
            "high_sweep_time": pd.Timestamp("2025-01-02T08:35:00Z"),
            "low_sweep_time": None,
            "high_reentry": True, "low_reentry": False,
            "high_reentry_time": pd.Timestamp("2025-01-02T08:40:00Z"),
            "low_reentry_time": None,
        }
    elif role == "d006_structural_blocks":
        fields = [
            pa.field("block_id", pa.large_string()),
            pa.field("definition_name", pa.large_string()),
            pa.field("direction", pa.large_string()),
            pa.field("source_bar_ids", pa.list_(pa.field("element", pa.string()))),
            pa.field("expansion_bar_id", pa.large_string()),
            pa.field("confirmation_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("causal_availability", pa.timestamp("us", tz="UTC")),
            pa.field("range", pa.float64()),
            pa.field("lifecycle_state", pa.large_string()),
            pa.field("first_touch_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("mitigation_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("invalidation_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("expiry_timestamp", pa.timestamp("us", tz="UTC")),
            pa.field("expiry_deadline", pa.timestamp("us", tz="UTC")),
            pa.field("overlap_group_id", pa.large_string()),
            pa.field("parent_block_id", pa.large_string()),
            pa.field("preavailability_interaction", pa.bool_()),
        ]
        available = pd.Timestamp("2025-01-02T08:40:00Z")
        values = {
            "block_id": "block-1", "definition_name": "single_wick_50_d3_v1",
            "direction": "bullish", "source_bar_ids": ["bar-1"],
            "expansion_bar_id": "bar-2", "confirmation_timestamp": available,
            "causal_availability": available, "range": 1.5, "lifecycle_state": "active",
            "first_touch_timestamp": None, "mitigation_timestamp": None,
            "invalidation_timestamp": None, "expiry_timestamp": None,
            "expiry_deadline": available + pd.Timedelta(hours=24),
            "overlap_group_id": None, "parent_block_id": None,
            "preavailability_interaction": False,
        }
    else:  # pragma: no cover - test helper guard
        raise AssertionError(f"unsupported association role: {role}")
    fields.extend((pa.field("outcome_return_60m", pa.float64()), pa.field("retrospective_label", pa.string())))
    values.update({"outcome_return_60m": 999.0, "retrospective_label": "forbidden"})
    return pa.Table.from_pylist([values], schema=pa.schema(fields))


@pytest.mark.parametrize("role", ("d004_daily_events", "d006_structural_blocks"))
def test_association_roles_use_exact_authoritative_projection_without_forbidden_columns(tmp_path: Path, role: str) -> None:
    relative = ASSOCIATION_ARTIFACT_PATHS[role]
    path, digest, size = _write_table(tmp_path, relative, _association_table(role))
    registry_identity = next(item for item in UPSTREAM_ARTIFACTS if item.path == relative)
    identity = replace(registry_identity, sha256=digest)
    calls: list[tuple[str, tuple[str, ...]]] = []
    signature = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(path).schema_arrow.remove_metadata())

    result = load_structural_artifact(
        tmp_path, identity, parquet_file_factory=lambda item: _TrackedParquet(item, calls),
        expected_full_schema=signature, expected_byte_size=size,
    )

    expected = ASSOCIATION_PROJECTIONS[role]
    assert calls == [(path.name, expected)]
    assert tuple(result.columns) == expected
    assert {"outcome_return_60m", "retrospective_label"}.isdisjoint(calls[0][1])


@pytest.mark.parametrize("role", ("d004_daily_events", "d006_structural_blocks"))
def test_association_roles_reject_full_table_missing_columns_and_projected_schema_drift(tmp_path: Path, role: str) -> None:
    relative = ASSOCIATION_ARTIFACT_PATHS[role]
    path, digest, size = _write_table(tmp_path, relative, _association_table(role))
    registry_identity = next(item for item in UPSTREAM_ARTIFACTS if item.path == relative)
    identity = replace(registry_identity, sha256=digest)
    signature = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(path).schema_arrow.remove_metadata())
    calls: list[tuple[str, tuple[str, ...]]] = []

    with pytest.raises(FrozenParquetLoadError, match="extra, missing, or reordered"):
        load_structural_artifact(
            tmp_path, identity, parquet_file_factory=lambda item: _DishonestParquet(item, calls),
            expected_full_schema=signature, expected_byte_size=size,
        )
    assert calls == [(path.name, ASSOCIATION_PROJECTIONS[role])]

    missing_column = "primary_reference_name" if role == "d004_daily_events" else "source_bar_ids"
    missing_root = tmp_path / "missing"
    missing_path, missing_digest, missing_size = _write_table(
        missing_root, relative, _association_table(role).drop([missing_column]),
    )
    missing_identity = replace(identity, sha256=missing_digest)
    missing_signature = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(missing_path).schema_arrow.remove_metadata())
    missing_calls: list[tuple[str, tuple[str, ...]]] = []
    with pytest.raises(FrozenParquetLoadError, match="projection columns missing"):
        load_structural_artifact(
            missing_root, missing_identity,
            parquet_file_factory=lambda item: _TrackedParquet(item, missing_calls),
            expected_full_schema=missing_signature, expected_byte_size=missing_size,
        )
    assert missing_calls == []

    drifted = _association_table(role).set_column(
        1, "primary_reference_name" if role == "d004_daily_events" else "definition_name",
        pa.array(["wrong-type"], type=pa.string()),
    )
    drifted_root = tmp_path / "drifted"
    drifted_path, drifted_digest, drifted_size = _write_table(drifted_root, relative, drifted)
    drifted_identity = replace(identity, sha256=drifted_digest)
    drifted_signature = tuple((field.name, str(field.type), field.nullable) for field in pq.ParquetFile(drifted_path).schema_arrow.remove_metadata())
    with pytest.raises(FrozenParquetLoadError, match="projected Parquet schema/dtype drift"):
        load_structural_artifact(
            drifted_root, drifted_identity, expected_full_schema=drifted_signature,
            expected_byte_size=drifted_size,
        )
