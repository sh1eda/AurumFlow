"""Fail-closed, research-only D003-v2 historical bar source.

This module is deliberately not an execution pipeline.  A caller must provide
an explicit repository root and can inject a Parquet-file factory for isolated
fixtures.  The implementation verifies every selected file before values are
read and never selects a file outside D006's frozen half-open interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd

from .config import D006Config, FROZEN_DATA_METADATA_SHA256


UTC = timezone.utc
CANONICAL_ROOT = Path("data/canonical/xauusd_ticks_d003-v2")
RELEASE_ROOT = Path("data/releases/d003-v2")
CANONICAL_MANIFEST = CANONICAL_ROOT / "canonical_manifest.json"
RELEASE_MANIFEST = RELEASE_ROOT / "canonical_manifest.json"
FULL_VERIFICATION = RELEASE_ROOT / "full_verification.json"
PARQUET_CHECKSUMS = RELEASE_ROOT / "parquet_sha256.txt"
RELEASE_CHECKSUMS = RELEASE_ROOT / "release_sha256.txt"
TICK_COLUMNS = ("timestamp_utc", "mid")
CANONICAL_SCHEMA = (
    ("timestamp_utc", "timestamp[ms, tz=UTC]", False),
    ("bid", "double", False),
    ("ask", "double", False),
    ("bid_volume", "float", False),
    ("ask_volume", "float", False),
    ("mid", "double", False),
    ("spread", "double", False),
    ("symbol", "string", False),
    ("source_partition", "string", False),
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


class HistoricalSourceError(RuntimeError):
    """Raised when source provenance or causal bar construction is invalid."""


class _ArrowMetadata(Protocol):
    num_rows: int


class _ArrowFile(Protocol):
    schema_arrow: Any
    metadata: _ArrowMetadata

    def read(self, *, columns: Sequence[str]) -> Any: ...


ParquetFileFactory = Callable[[Path], _ArrowFile]


@dataclass(frozen=True)
class SourceFile:
    """A canonical Parquet member selected solely by its signed manifest."""

    relative_path: str
    sha256: str
    row_count: int
    minimum_timestamp: pd.Timestamp
    maximum_timestamp: pd.Timestamp


@dataclass(frozen=True)
class ReleaseProvenance:
    """Verified release metadata, without opening a market-data payload."""

    metadata_hashes: tuple[tuple[str, str], ...]
    canonical_manifest_sha256: str
    canonical_schema: tuple[tuple[str, str, bool], ...]
    manifest_files: tuple[SourceFile, ...]


@dataclass(frozen=True)
class SourceAudit:
    """Immutable provenance and construction accounting for one source read."""

    metadata_hashes: tuple[tuple[str, str], ...]
    canonical_manifest_sha256: str
    selected_files: tuple[SourceFile, ...]
    source_file_count: int
    source_row_count: int
    observed_tick_count: int
    one_minute_bar_count: int
    five_minute_bar_count: int
    source_interval_start: pd.Timestamp
    source_interval_end: pd.Timestamp
    excluded_2026_and_later: bool = True


@dataclass(frozen=True)
class HistoricalBars:
    """Deterministic tick-derived bars and their immutable audit record."""

    one_minute: pd.DataFrame
    five_minute: pd.DataFrame
    audit: SourceAudit


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HistoricalSourceError(f"invalid JSON metadata: {path}") from exc
    if not isinstance(value, dict):
        raise HistoricalSourceError(f"JSON metadata must be an object: {path}")
    return value


def _parse_checksum_file(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HistoricalSourceError(f"cannot read checksum metadata: {path}") from exc
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or _HEX_SHA256.fullmatch(parts[0]) is None:
            raise HistoricalSourceError(f"invalid checksum entry at {path}:{number}")
        relative = parts[1].strip()
        if not _safe_relative_path(relative) or relative in entries:
            raise HistoricalSourceError(f"invalid checksum path at {path}:{number}")
        entries[relative] = parts[0]
    return entries


def _parse_release_descriptor(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HistoricalSourceError(f"cannot read release descriptor: {path}") from exc
    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if "=" not in line:
            raise HistoricalSourceError(f"invalid release descriptor at line {number}")
        key, value = (piece.strip() for piece in line.split("=", 1))
        if not key or not value or key in values:
            raise HistoricalSourceError(f"invalid release descriptor at line {number}")
        values[key] = value
    return values


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and value == path.as_posix()


def _as_utc_timestamp(value: object, *, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalSourceError(f"invalid UTC timestamp for {label}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() != pd.Timedelta(0):
        raise HistoricalSourceError(f"{label} must be explicit UTC")
    return timestamp.tz_convert("UTC")


def _schema_signature(schema: Any) -> tuple[tuple[str, str, bool], ...]:
    try:
        normalized = schema.remove_metadata()
        return tuple((field.name, str(field.type), field.nullable) for field in normalized)
    except (AttributeError, TypeError) as exc:
        raise HistoricalSourceError("Arrow schema is unavailable") from exc


def _canonical_schema_signature(manifest: Mapping[str, Any]) -> tuple[tuple[str, str, bool], ...]:
    records = manifest.get("canonical_schema")
    if not isinstance(records, list):
        raise HistoricalSourceError("canonical manifest schema is missing")
    result: list[tuple[str, str, bool]] = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise HistoricalSourceError(f"invalid canonical schema record {position}")
        name, kind, nullable = record.get("name"), record.get("type"), record.get("nullable")
        if not isinstance(name, str) or not isinstance(kind, str) or not isinstance(nullable, bool):
            raise HistoricalSourceError(f"invalid canonical schema record {position}")
        result.append((name, kind, nullable))
    signature = tuple(result)
    if signature != CANONICAL_SCHEMA:
        raise HistoricalSourceError("canonical manifest schema mismatch")
    return signature


def _source_file(record: Mapping[str, Any], position: int) -> SourceFile:
    relative = record.get("path")
    checksum = record.get("sha256")
    row_count = record.get("row_count")
    if (
        not isinstance(relative, str)
        or not _safe_relative_path(relative)
        or not relative.startswith(str(CANONICAL_ROOT) + "/")
        or not relative.endswith(".parquet")
        or not isinstance(checksum, str)
        or _HEX_SHA256.fullmatch(checksum) is None
        or not isinstance(row_count, int)
        or row_count <= 0
    ):
        raise HistoricalSourceError(f"invalid canonical file record {position}")
    minimum = _as_utc_timestamp(record.get("min_timestamp"), label=f"files[{position}].min_timestamp")
    maximum = _as_utc_timestamp(record.get("max_timestamp"), label=f"files[{position}].max_timestamp")
    if minimum > maximum:
        raise HistoricalSourceError(f"canonical file interval is reversed: {relative}")
    return SourceFile(relative, checksum, row_count, minimum, maximum)


def _manifest_files(manifest: Mapping[str, Any]) -> tuple[SourceFile, ...]:
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise HistoricalSourceError("canonical manifest has no file records")
    files = tuple(_source_file(record, index) for index, record in enumerate(records) if isinstance(record, dict))
    if len(files) != len(records) or len({item.relative_path for item in files}) != len(files):
        raise HistoricalSourceError("canonical manifest has invalid or duplicate paths")
    if tuple(sorted(files, key=lambda item: item.relative_path)) != files:
        raise HistoricalSourceError("canonical manifest file order is not deterministic")
    return files


def verify_release_metadata(
    repository_root: Path,
    *,
    metadata_contract: Iterable[tuple[str, str]] = FROZEN_DATA_METADATA_SHA256,
) -> ReleaseProvenance:
    """Verify the five frozen metadata hashes and exact D003-v2 contract.

    ``metadata_contract`` is injectable solely to permit isolated temporary
    metadata fixtures.  Production callers must use the default frozen tuple.
    No Parquet payload is opened here.
    """

    root = repository_root.resolve()
    contract = tuple(metadata_contract)
    expected_paths = tuple(path for path, _ in FROZEN_DATA_METADATA_SHA256)
    if tuple(path for path, _ in contract) != expected_paths or len(contract) != 5:
        raise HistoricalSourceError("metadata contract must contain the five D006 paths")
    observed: list[tuple[str, str]] = []
    for relative, expected in contract:
        path = root / relative
        if not path.is_file() or path.is_symlink() or _HEX_SHA256.fullmatch(expected) is None:
            raise HistoricalSourceError(f"missing or invalid frozen metadata: {relative}")
        actual = _sha256_file(path)
        if actual != expected:
            raise HistoricalSourceError(f"frozen metadata hash mismatch: {relative}")
        observed.append((relative, actual))

    canonical_path = root / CANONICAL_MANIFEST
    release_manifest_path = root / RELEASE_MANIFEST
    if canonical_path.read_bytes() != release_manifest_path.read_bytes():
        raise HistoricalSourceError("canonical and release manifest bytes differ")
    manifest = _strict_json(canonical_path)
    schema = _canonical_schema_signature(manifest)
    if (
        manifest.get("status") != "complete"
        or manifest.get("dataset_version") != "d003-v2"
        or manifest.get("symbol") != "XAUUSD"
        or manifest.get("date_range") != {
            "start_inclusive": "2021-01-01T00:00:00Z",
            "end_exclusive": "2026-07-29T00:00:00Z",
        }
        or manifest.get("duplicate_count") != 0
        or manifest.get("rejected_record_count") != 0
    ):
        raise HistoricalSourceError("canonical D003-v2 manifest contract mismatch")
    files = _manifest_files(manifest)
    if manifest.get("canonical_file_count") != len(files):
        raise HistoricalSourceError("canonical manifest file count mismatch")

    verification = _strict_json(root / FULL_VERIFICATION)
    metrics = verification.get("metrics")
    zero_metrics = (
        "timezone_errors", "ordering_errors", "duplicate_ticks", "invalid_prices",
        "invalid_spreads", "invalid_volumes",
    )
    if (
        verification.get("passed") is not True
        or verification.get("errors") != []
        or verification.get("canonical_manifest_sha256") != observed[0][1]
        or verification.get("dataset_version") != "d003-v2"
        or verification.get("symbol") != "XAUUSD"
        or verification.get("date_range") != manifest["date_range"]
        or not isinstance(metrics, dict)
        or any(metrics.get(key) != 0 for key in zero_metrics)
        or metrics.get("canonical_file_count") != len(files)
        or metrics.get("row_count") != manifest.get("row_count")
    ):
        raise HistoricalSourceError("D003-v2 verification status mismatch")

    parquet_checksums = _parse_checksum_file(root / PARQUET_CHECKSUMS)
    manifest_checksums = {item.relative_path: item.sha256 for item in files}
    if parquet_checksums != manifest_checksums:
        raise HistoricalSourceError("Parquet checksum manifest does not match canonical manifest")
    descriptor = _parse_release_descriptor(root / RELEASE_ROOT / "RELEASE.txt")
    if (
        descriptor.get("release_id") != "d003-v2"
        or descriptor.get("symbol") != "XAUUSD"
        or descriptor.get("start_utc") != "2021-01-01T00:00:00Z"
        or descriptor.get("end_utc") != "2026-07-29T00:00:00Z"
        or descriptor.get("verification_passed") != "true"
        or descriptor.get("verification_errors") != "0"
        or descriptor.get("parquet_checksum_manifest_sha256") != observed[3][1]
    ):
        raise HistoricalSourceError("D003-v2 release descriptor mismatch")
    try:
        descriptor_rows = int(descriptor.get("rows", ""))
        descriptor_files = int(descriptor.get("parquet_files", ""))
    except ValueError as exc:
        raise HistoricalSourceError("D003-v2 release counts are invalid") from exc
    if descriptor_rows != manifest.get("row_count") or descriptor_files != len(files):
        raise HistoricalSourceError("D003-v2 release count mismatch")
    return ReleaseProvenance(tuple(observed), observed[0][1], schema, files)


def select_historical_files(provenance: ReleaseProvenance, config: D006Config = D006Config()) -> tuple[SourceFile, ...]:
    """Select only manifest records wholly within D006's pre-2026 interval."""

    start = pd.Timestamp(config.source_start)
    end = pd.Timestamp(config.source_end)
    selected = tuple(
        item
        for item in provenance.manifest_files
        if item.maximum_timestamp >= start and item.minimum_timestamp < end
    )
    if not selected:
        raise HistoricalSourceError("manifest selection produced no D006 source files")
    for item in selected:
        if (
            item.minimum_timestamp >= end
            or item.maximum_timestamp >= end
            or "/year=2026/" in f"/{item.relative_path}"
        ):
            raise HistoricalSourceError(f"selected 2026-or-later source file: {item.relative_path}")
    if tuple(sorted(selected, key=lambda item: item.relative_path)) != selected:
        raise HistoricalSourceError("selected source files are not deterministically ordered")
    return selected


def _default_parquet_file(path: Path) -> _ArrowFile:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on optional runtime extra
        raise HistoricalSourceError("pyarrow is required to read verified historical bars") from exc
    return pq.ParquetFile(path)


def _table_to_frame(table: Any) -> pd.DataFrame:
    try:
        frame = table.to_pandas()
    except AttributeError as exc:
        raise HistoricalSourceError("Arrow table cannot be converted to a frame") from exc
    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != TICK_COLUMNS:
        raise HistoricalSourceError("selected tick values do not match timestamp_utc/mid contract")
    return frame


def _validate_ticks(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[:, TICK_COLUMNS].copy()
    timestamp_dtype = result["timestamp_utc"].dtype
    timezone_value = getattr(timestamp_dtype, "tz", None)
    if timezone_value is None or str(timezone_value) not in {"UTC", "UTC+00:00"}:
        raise HistoricalSourceError("tick timestamps must be explicit UTC")
    try:
        mid_values = result["mid"].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise HistoricalSourceError("tick mid values must be finite numeric values") from exc
    if result.isna().any().any() or not np.isfinite(mid_values).all():
        raise HistoricalSourceError("tick values must be non-null and finite")
    timestamps = pd.DatetimeIndex(result["timestamp_utc"])
    if timestamps.has_duplicates:
        raise HistoricalSourceError("duplicate tick timestamps are forbidden")
    if not timestamps.is_monotonic_increasing:
        raise HistoricalSourceError("tick timestamps must be strictly ordered")
    return result


def _verify_and_read_file(root: Path, item: SourceFile, factory: ParquetFileFactory) -> pd.DataFrame:
    path = root / item.relative_path
    if not path.is_file() or path.is_symlink() or _sha256_file(path) != item.sha256:
        raise HistoricalSourceError(f"canonical payload hash mismatch: {item.relative_path}")
    parquet_file = factory(path)
    if _schema_signature(parquet_file.schema_arrow) != CANONICAL_SCHEMA:
        raise HistoricalSourceError(f"canonical Arrow schema mismatch: {item.relative_path}")
    if getattr(parquet_file.metadata, "num_rows", None) != item.row_count:
        raise HistoricalSourceError(f"canonical row count mismatch: {item.relative_path}")
    frame = _validate_ticks(_table_to_frame(parquet_file.read(columns=TICK_COLUMNS)))
    if len(frame) != item.row_count:
        raise HistoricalSourceError(f"read row count mismatch: {item.relative_path}")
    if frame["timestamp_utc"].iloc[0] < item.minimum_timestamp or frame["timestamp_utc"].iloc[-1] > item.maximum_timestamp:
        raise HistoricalSourceError(f"canonical payload exceeds manifest interval: {item.relative_path}")
    return frame


def _build_one_minute(ticks: pd.DataFrame) -> pd.DataFrame:
    indexed = ticks.set_index("timestamp_utc")["mid"]
    bars = indexed.resample("1min", label="left", closed="left", origin="epoch").agg(
        open="first", high="max", low="min", close="last"
    ).dropna(how="all")
    bars.index.name = "timestamp_utc"
    if bars.empty:
        raise HistoricalSourceError("verified source contains no one-minute bars")
    return bars


def _decorate_bars(bars: pd.DataFrame, *, minutes: int) -> pd.DataFrame:
    result = bars.copy()
    result["available_at"] = result.index + pd.Timedelta(minutes=minutes)
    result["bar_id"] = [f"d006-{minutes}m-{stamp.isoformat()}" for stamp in result.index]
    if not result.index.is_monotonic_increasing or result.index.has_duplicates:
        raise HistoricalSourceError("constructed bars must be uniquely time ordered")
    if not result["bar_id"].is_monotonic_increasing:
        raise HistoricalSourceError("constructed bar identities must be lexicographically ordered")
    return result


def _build_five_minute(one_minute: pd.DataFrame) -> pd.DataFrame:
    prices = one_minute.loc[:, ["open", "high", "low", "close"]]
    bars = prices.resample("5min", label="left", closed="left", origin="epoch").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).dropna(how="all")
    observed = one_minute["close"].resample("5min", label="left", closed="left", origin="epoch").count()
    bars["observed_minutes"] = observed.reindex(bars.index).astype("int64")
    bars["is_complete"] = bars["observed_minutes"].eq(5)
    bars.index.name = "timestamp_utc"
    return bars


def load_historical_bars(
    repository_root: Path,
    *,
    config: D006Config = D006Config(),
    parquet_file_factory: ParquetFileFactory | None = None,
    metadata_contract: Iterable[tuple[str, str]] = FROZEN_DATA_METADATA_SHA256,
) -> HistoricalBars:
    """Load deterministic pre-2026 bars after fail-closed provenance checks."""

    provenance = verify_release_metadata(repository_root, metadata_contract=metadata_contract)
    selected = select_historical_files(provenance, config)
    root = repository_root.resolve()
    factory = parquet_file_factory or _default_parquet_file
    start, end = pd.Timestamp(config.source_start), pd.Timestamp(config.source_end)
    # The canonical payload contains hundreds of millions of ticks.  Verify and
    # aggregate one signed daily member at a time so memory is bounded by one
    # source file; only the much smaller one-minute derivative is concatenated.
    one_minute_pieces: list[pd.DataFrame] = []
    observed_tick_count = 0
    previous_maximum: pd.Timestamp | None = None
    for item in selected:
        ticks = _verify_and_read_file(root, item, factory)
        if ticks["timestamp_utc"].iloc[0] < start or ticks["timestamp_utc"].iloc[-1] >= end:
            raise HistoricalSourceError("selected ticks violate the frozen D006 interval")
        if previous_maximum is not None and ticks["timestamp_utc"].iloc[0] <= previous_maximum:
            raise HistoricalSourceError("canonical payload members overlap or are out of order")
        previous_maximum = pd.Timestamp(ticks["timestamp_utc"].iloc[-1])
        observed_tick_count += len(ticks)
        one_minute_pieces.append(_build_one_minute(ticks))
    one_minute = pd.concat(one_minute_pieces, axis=0).sort_index(kind="mergesort")
    if one_minute.index.has_duplicates or not one_minute.index.is_monotonic_increasing:
        raise HistoricalSourceError("one-minute source members overlap or are out of order")
    one_minute = _decorate_bars(one_minute, minutes=1)
    five_minute = _decorate_bars(_build_five_minute(one_minute), minutes=5)
    audit = SourceAudit(
        provenance.metadata_hashes,
        provenance.canonical_manifest_sha256,
        selected,
        len(selected),
        sum(item.row_count for item in selected),
        observed_tick_count,
        len(one_minute),
        len(five_minute),
        start,
        end,
    )
    return HistoricalBars(one_minute, five_minute, audit)
