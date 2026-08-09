from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from research.d006_rejection_block_research.source import (
    CANONICAL_SCHEMA,
    HistoricalSourceError,
    load_historical_bars,
    verify_release_metadata,
)


class _Table:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def to_pandas(self) -> pd.DataFrame:
        return self._frame.copy()


class _ParquetFixture:
    def __init__(self, frame: pd.DataFrame, *, schema: tuple[tuple[str, str, bool], ...] = CANONICAL_SCHEMA, rows: int | None = None) -> None:
        self.schema_arrow = _Schema(schema)
        self.metadata = SimpleNamespace(num_rows=len(frame) if rows is None else rows)
        self._frame = frame
        self.read_called = False

    def read(self, *, columns: tuple[str, ...]) -> _Table:
        self.read_called = True
        assert columns == ("timestamp_utc", "mid")
        return _Table(self._frame.loc[:, list(columns)])


class _Schema:
    def __init__(self, fields: tuple[tuple[str, str, bool], ...]) -> None:
        self._fields = fields

    def remove_metadata(self) -> "_Schema":
        return self

    def __iter__(self):
        for name, kind, nullable in self._fields:
            yield SimpleNamespace(name=name, type=kind, nullable=nullable)


def _json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _frame(start: str = "2025-12-31T00:00:00Z", minutes: int = 5) -> pd.DataFrame:
    index = pd.date_range(start, periods=minutes, freq="1min", tz="UTC")
    return pd.DataFrame({"timestamp_utc": index, "mid": [100.0 + value for value in range(minutes)]})


def _fixture(root: Path, frames: list[pd.DataFrame], *, dates: list[str] | None = None) -> tuple[tuple[tuple[str, str], ...], dict[Path, _ParquetFixture]]:
    canonical_root = root / "data/canonical/xauusd_ticks_d003-v2"
    release_root = root / "data/releases/d003-v2"
    records: list[dict[str, Any]] = []
    parquet: dict[Path, _ParquetFixture] = {}
    for position, frame in enumerate(frames):
        date = (dates or [str(frame["timestamp_utc"].iloc[0].date()) for frame in frames])[position]
        relative = f"data/canonical/xauusd_ticks_d003-v2/year={date[:4]}/month={date[5:7]}/xauusd_ticks_{date}.parquet"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"fixture-{position}".encode("ascii")
        path.write_bytes(payload)
        records.append({
            "path": relative, "sha256": sha256(payload).hexdigest(), "row_count": len(frame),
            "min_timestamp": frame["timestamp_utc"].iloc[0].isoformat().replace("+00:00", "Z"),
            "max_timestamp": frame["timestamp_utc"].iloc[-1].isoformat().replace("+00:00", "Z"),
        })
        parquet[path] = _ParquetFixture(frame)
    records.sort(key=lambda row: str(row["path"]))
    canonical = {
        "status": "complete", "dataset_version": "d003-v2", "symbol": "XAUUSD",
        "date_range": {"start_inclusive": "2021-01-01T00:00:00Z", "end_exclusive": "2026-07-29T00:00:00Z"},
        "canonical_schema": [{"name": name, "type": kind, "nullable": nullable} for name, kind, nullable in CANONICAL_SCHEMA],
        "canonical_file_count": len(records), "row_count": sum(int(row["row_count"]) for row in records),
        "duplicate_count": 0, "rejected_record_count": 0, "files": records,
    }
    canonical_path = canonical_root / "canonical_manifest.json"
    _json(canonical_path, canonical)
    release_root.mkdir(parents=True, exist_ok=True)
    (release_root / "canonical_manifest.json").write_bytes(canonical_path.read_bytes())
    canonical_hash = sha256(canonical_path.read_bytes()).hexdigest()
    _json(release_root / "full_verification.json", {
        "passed": True, "errors": [], "canonical_manifest_sha256": canonical_hash,
        "dataset_version": "d003-v2", "symbol": "XAUUSD", "date_range": canonical["date_range"],
        "metrics": {"timezone_errors": 0, "ordering_errors": 0, "duplicate_ticks": 0, "invalid_prices": 0, "invalid_spreads": 0, "invalid_volumes": 0, "canonical_file_count": len(records), "row_count": canonical["row_count"]},
    })
    (release_root / "parquet_sha256.txt").write_text("".join(f"{row['sha256']}  {row['path']}\n" for row in records), encoding="utf-8")
    (release_root / "RELEASE.txt").write_text("\n".join((
        "release_id=d003-v2", "symbol=XAUUSD", "start_utc=2021-01-01T00:00:00Z", "end_utc=2026-07-29T00:00:00Z",
        f"rows={canonical['row_count']}", f"parquet_files={len(records)}", "verification_passed=true", "verification_errors=0",
        f"parquet_checksum_manifest_sha256={sha256((release_root / 'parquet_sha256.txt').read_bytes()).hexdigest()}",
    )) + "\n", encoding="utf-8")
    paths = (
        "data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json",
        "data/releases/d003-v2/canonical_manifest.json", "data/releases/d003-v2/full_verification.json",
        "data/releases/d003-v2/parquet_sha256.txt", "data/releases/d003-v2/release_sha256.txt",
    )
    # The fifth contract member contains the three release-member hashes.
    release_members = (
        "data/releases/d003-v2/canonical_manifest.json", "data/releases/d003-v2/full_verification.json", "data/releases/d003-v2/parquet_sha256.txt",
    )
    release_checksums = "".join(f"{sha256((root / item).read_bytes()).hexdigest()}  {item}\n" for item in release_members)
    (release_root / "release_sha256.txt").write_text(release_checksums, encoding="utf-8")
    return tuple((path, sha256((root / path).read_bytes()).hexdigest()) for path in paths), parquet


def _factory(items: dict[Path, _ParquetFixture]):
    return lambda path: items[path]


def test_verified_fixture_builds_epoch_aligned_complete_and_incomplete_bars(tmp_path: Path) -> None:
    # Five observed minutes, followed by a separate two-minute partial bin: no imputation.
    frame = pd.concat([_frame(minutes=5), _frame("2025-12-31T00:05:00Z", 2)], ignore_index=True)
    contract, parquet = _fixture(tmp_path, [frame])
    result = load_historical_bars(tmp_path, parquet_file_factory=_factory(parquet), metadata_contract=contract)
    bars = result.five_minute
    assert bars["observed_minutes"].to_list() == [5, 2]
    assert bars["is_complete"].to_list() == [True, False]
    assert bars["available_at"].to_list() == [pd.Timestamp("2025-12-31T00:05:00Z"), pd.Timestamp("2025-12-31T00:10:00Z")]
    assert bars["bar_id"].to_list() == sorted(bars["bar_id"].to_list())
    assert result.audit.excluded_2026_and_later is True
    assert result.audit.source_file_count == 1
    assert result.audit.source_row_count == 7


def test_metadata_release_hash_schema_and_interval_fail_closed(tmp_path: Path) -> None:
    contract, parquet = _fixture(tmp_path, [_frame()])
    verify_release_metadata(tmp_path, metadata_contract=contract)
    release_manifest = tmp_path / "data/releases/d003-v2/canonical_manifest.json"
    release_manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(HistoricalSourceError, match="hash mismatch"):
        verify_release_metadata(tmp_path, metadata_contract=contract)
    contract, parquet = _fixture(tmp_path / "bad-schema", [_frame()])
    parquet_item = next(iter(parquet.values()))
    parquet_item.schema_arrow = _Schema(CANONICAL_SCHEMA[:-1])
    with pytest.raises(HistoricalSourceError, match="Arrow schema"):
        load_historical_bars(tmp_path / "bad-schema", parquet_file_factory=_factory(parquet), metadata_contract=contract)


def test_manifest_selection_hard_rejects_2026_before_payload_open(tmp_path: Path) -> None:
    pre_2026, mislabeled = _frame(), _frame("2025-12-31T00:10:00Z")
    contract, parquet = _fixture(tmp_path, [pre_2026, mislabeled], dates=["2025-12-31", "2026-01-01"])
    post_path = next(path for path in parquet if "/year=2026/" in path.as_posix())
    opened = False

    def guarded_factory(path: Path) -> _ParquetFixture:
        nonlocal opened
        if path == post_path:
            opened = True
        return parquet[path]

    with pytest.raises(HistoricalSourceError, match="2026-or-later"):
        load_historical_bars(tmp_path, parquet_file_factory=guarded_factory, metadata_contract=contract)
    assert opened is False


@pytest.mark.parametrize("mutator, message", [
    (lambda frame: frame.iloc[::-1].reset_index(drop=True), "ordered"),
    (lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True), "duplicate"),
    (lambda frame: frame.assign(mid=float("nan")), "finite"),
])
def test_tick_order_duplicate_and_nonfinite_values_fail_closed(tmp_path: Path, mutator, message: str) -> None:
    contract, parquet = _fixture(tmp_path, [_frame()])
    item = next(iter(parquet.values()))
    item._frame = mutator(item._frame)
    item.metadata.num_rows = len(item._frame)
    # The declared row count still verifies before values; test only the value invariant.
    manifest = tmp_path / "data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["files"][0]["row_count"] = len(item._frame)
    payload["row_count"] = len(item._frame)
    _json(manifest, payload)
    release = tmp_path / "data/releases/d003-v2/canonical_manifest.json"
    release.write_bytes(manifest.read_bytes())
    # Rebuild the signed fixture contract after controlled metadata change.
    contract = tuple((path, sha256((tmp_path / path).read_bytes()).hexdigest()) for path, _ in contract)
    verification = tmp_path / "data/releases/d003-v2/full_verification.json"
    verification_payload = json.loads(verification.read_text(encoding="utf-8"))
    verification_payload["canonical_manifest_sha256"] = contract[0][1]
    verification_payload["metrics"]["row_count"] = len(item._frame)
    _json(verification, verification_payload)
    descriptor = tmp_path / "data/releases/d003-v2/RELEASE.txt"
    descriptor.write_text(descriptor.read_text(encoding="utf-8").replace("rows=5", f"rows={len(item._frame)}"), encoding="utf-8")
    checksums = tmp_path / "data/releases/d003-v2/release_sha256.txt"
    members = ("data/releases/d003-v2/canonical_manifest.json", "data/releases/d003-v2/full_verification.json", "data/releases/d003-v2/parquet_sha256.txt")
    checksums.write_text("".join(f"{sha256((tmp_path / path).read_bytes()).hexdigest()}  {path}\n" for path in members), encoding="utf-8")
    contract = tuple((path, sha256((tmp_path / path).read_bytes()).hexdigest()) for path, _ in contract)
    with pytest.raises(HistoricalSourceError, match=message):
        load_historical_bars(tmp_path, parquet_file_factory=_factory(parquet), metadata_contract=contract)


def test_output_is_deterministic_and_source_payload_is_unmodified(tmp_path: Path) -> None:
    contract, parquet = _fixture(tmp_path, [_frame()])
    payload_path = next(iter(parquet))
    before = (sha256(payload_path.read_bytes()).hexdigest(), payload_path.stat().st_mtime_ns)
    first = load_historical_bars(tmp_path, parquet_file_factory=_factory(parquet), metadata_contract=contract)
    second = load_historical_bars(tmp_path, parquet_file_factory=_factory(parquet), metadata_contract=contract)
    pd.testing.assert_frame_equal(first.one_minute, second.one_minute)
    pd.testing.assert_frame_equal(first.five_minute, second.five_minute)
    assert first.audit == second.audit
    assert before == (sha256(payload_path.read_bytes()).hexdigest(), payload_path.stat().st_mtime_ns)
