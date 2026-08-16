"""Fail-closed, outcome-blind Parquet adapters for frozen D007 inputs.

The adapters authenticate a file and inspect only its Parquet footer before
asking the backend to decode an explicit, complete structural projection.
They intentionally have no default input inventory and never discover files.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.d007_association_identity import (
    ASSOCIATION_ARTIFACT_PATHS,
    ASSOCIATION_PROJECTIONS,
    validate_projection,
)
from research.d007_methodology_clarification import ArtifactIdentity, verify_upstream_identities


SOURCE_TERMINAL_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
MARKET_PROJECTION = ("timestamp_utc", "mid_open", "mid_high", "mid_low", "mid_close")
GENERIC_OHLC_COLUMNS = ("timestamp_utc", "open", "high", "low", "close")

# This is the metadata-free Arrow footer signature of every frozen D004 1m
# cache member.  Keep it as primitive values so callers do not need pyarrow at
# import time, and so a supplied reader's footer can be compared exactly.
FROZEN_D004_MARKET_FULL_SCHEMA = (
    ("timestamp_utc", "timestamp[ms, tz=UTC]", True),
    ("bid_open", "double", True), ("bid_high", "double", True),
    ("bid_low", "double", True), ("bid_close", "double", True),
    ("ask_open", "double", True), ("ask_high", "double", True),
    ("ask_low", "double", True), ("ask_close", "double", True),
    ("mid_open", "double", True), ("mid_high", "double", True),
    ("mid_low", "double", True), ("mid_close", "double", True),
    ("tick_count", "int64", True), ("median_spread", "double", True),
    ("maximum_spread", "double", True), ("last_spread", "double", True),
)
FROZEN_D004_MARKET_SCHEMA_SIGNATURE = FROZEN_D004_MARKET_FULL_SCHEMA
# Association-role paths use the authoritative complete projections from the
# addendum.  All other upstream roles retain their frozen registry tuples.
ASSOCIATION_PROJECTIONS_BY_PATH = {
    path: validate_projection(role, ASSOCIATION_PROJECTIONS[role])
    for role, path in ASSOCIATION_ARTIFACT_PATHS.items()
}
FROZEN_UPSTREAM_PROJECTED_SCHEMAS = {
    "research_outputs/D004_XAUUSD_0830_0900/daily_events.parquet": (
        ("trading_date", "date32[day]", True), ("primary_reference_name", "large_string", True),
        ("high_sweep", "bool", True), ("low_sweep", "bool", True),
        ("high_sweep_time", "timestamp[ms, tz=UTC]", True),
        ("low_sweep_time", "timestamp[ms, tz=UTC]", True),
        ("high_reentry", "bool", True), ("low_reentry", "bool", True),
        ("high_reentry_time", "timestamp[ms, tz=UTC]", True),
        ("low_reentry_time", "timestamp[ms, tz=UTC]", True),
    ),
    "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/context_snapshots.parquet": (
        ("snapshot_id", "large_string", True), ("evaluation_at", "timestamp[us, tz=UTC]", True),
        ("mapping_name", "large_string", True), ("mapping_variant", "large_string", True),
        ("optional_1m_refinement", "bool", True), ("parent_timeframe", "large_string", True),
        ("reaction_timeframe", "large_string", True), ("state", "large_string", True),
        ("direction", "int64", True), ("evidence_ids", "list<element: string>", True),
    ),
    "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/anchor_events.parquet": (
        ("anchor_id", "large_string", True), ("anchor_event_id", "large_string", True),
        ("anchor_type", "large_string", True), ("anchor_at", "timestamp[ns, tz=UTC]", True),
        ("direction", "int64", True), ("anchor_price_basis", "large_string", True),
        ("anchor_price_override", "double", True), ("main_scope_eligible", "bool", True),
        ("anchor_causally_observable", "bool", True),
        ("anchor_selected_using_later_completion", "bool", True),
    ),
    "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/eligible_sequences.parquet": (
        ("sequence_id", "large_string", True), ("mapping_variant", "large_string", True),
        ("direction", "int64", True), ("main_scope_eligible", "bool", True),
        ("anchor_causally_observable", "bool", True),
        ("anchor_selected_using_later_completion", "bool", True),
        ("candidate_id", "large_string", True), ("mss_id", "large_string", True),
        ("displacement_id", "large_string", True),
        ("displacement_created_at", "timestamp[us, tz=UTC]", True),
        ("displacement_confirmation_event_id", "large_string", True),
        ("confirmation_event_available_at", "timestamp[us, tz=UTC]", True),
        ("confirmation_event_direction", "int64", True),
    ),
    "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/displacement_anchors.parquet": (
        ("sequence_id", "large_string", True), ("mapping_variant", "large_string", True),
        ("anchor_event_id", "large_string", True), ("anchor_at", "timestamp[ns, tz=UTC]", True),
        ("direction", "int64", True), ("main_scope_eligible", "bool", True),
        ("anchor_causally_observable", "bool", True),
        ("anchor_selected_using_later_completion", "bool", True),
        ("anchor_session", "large_string", True), ("anchor_year", "int32", True),
    ),
    "research_outputs/D006_REJECTION_BLOCK_RESEARCH/structural_blocks.parquet": (
        ("block_id", "large_string", True), ("definition_name", "large_string", True),
        ("direction", "large_string", True), ("source_bar_ids", "list<element: string>", True),
        ("expansion_bar_id", "large_string", True),
        ("confirmation_timestamp", "timestamp[us, tz=UTC]", True),
        ("causal_availability", "timestamp[us, tz=UTC]", True),
        ("range", "double", True), ("lifecycle_state", "large_string", True),
        ("first_touch_timestamp", "timestamp[us, tz=UTC]", True),
        ("mitigation_timestamp", "timestamp[us, tz=UTC]", True),
        ("invalidation_timestamp", "timestamp[us, tz=UTC]", True),
        ("expiry_timestamp", "timestamp[us, tz=UTC]", True),
        ("expiry_deadline", "timestamp[us, tz=UTC]", True),
        ("overlap_group_id", "large_string", True), ("parent_block_id", "large_string", True),
        ("preavailability_interaction", "bool", True),
    ),
}


class FrozenParquetLoadError(ValueError):
    """A frozen input cannot be safely authenticated or projected."""


@dataclass(frozen=True)
class FrozenParquetArtifact:
    """One inventory-recorded Parquet object relative to an immutable root."""

    relative_path: str
    sha256: str
    byte_size: int
    required_columns: tuple[str, ...]
    expected_full_schema: tuple[tuple[str, str, bool], ...] | None = None
    expected_projected_schema: tuple[tuple[str, str, bool], ...] | None = None

    def __post_init__(self) -> None:
        if not self.relative_path or Path(self.relative_path).is_absolute() or ".." in Path(self.relative_path).parts:
            raise ValueError("relative Parquet path must be safe")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256.lower()):
            raise ValueError("Parquet SHA-256 must be a 64-character hexadecimal digest")
        if not isinstance(self.byte_size, int) or self.byte_size < 0:
            raise ValueError("Parquet byte size must be a non-negative integer")
        if not self.required_columns or len(self.required_columns) != len(set(self.required_columns)):
            raise ValueError("Parquet projection must be a nonempty unique tuple")


@dataclass(frozen=True)
class MarketParquetRecord:
    """Authenticated member of the frozen D004 one-minute cache inventory."""

    relative_path: str
    sha256: str
    byte_size: int
    expected_full_schema: tuple[tuple[str, str, bool], ...] = FROZEN_D004_MARKET_FULL_SCHEMA

    def artifact(self) -> FrozenParquetArtifact:
        return FrozenParquetArtifact(
            relative_path=self.relative_path,
            sha256=self.sha256,
            byte_size=self.byte_size,
            required_columns=MARKET_PROJECTION,
            expected_full_schema=self.expected_full_schema,
        )


ParquetFileFactory = Callable[[Path], Any]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise FrozenParquetLoadError("frozen source root is missing or unsafe")
    return root.resolve()


def _safe_inventory_path(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise FrozenParquetLoadError("frozen Parquet path escaped its source root")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FrozenParquetLoadError("frozen Parquet path contains a symlink")
    if not cursor.is_file() or root not in cursor.resolve().parents:
        raise FrozenParquetLoadError("frozen Parquet path is missing or escaped its source root")
    return cursor


def _schema_signature(parquet: Any) -> tuple[tuple[str, str, bool], ...]:
    schema = getattr(parquet, "schema_arrow", None)
    if schema is None:
        raise FrozenParquetLoadError("Parquet backend cannot expose Arrow footer schema")
    try:
        schema = schema.remove_metadata()
        return tuple((field.name, str(field.type), field.nullable) for field in schema)
    except (AttributeError, TypeError) as error:
        raise FrozenParquetLoadError("Parquet backend cannot guarantee footer schema") from error


def _default_parquet_factory(path: Path) -> Any:
    try:
        from pyarrow.parquet import ParquetFile
    except ImportError as error:  # pragma: no cover - test/runtime dependency
        raise FrozenParquetLoadError("pyarrow is required for frozen Parquet projection") from error
    return ParquetFile(path)


def _authenticate_and_open(
    root: Path, artifact: FrozenParquetArtifact, parquet_file_factory: ParquetFileFactory | None
) -> Any:
    path = _safe_inventory_path(_safe_root(root), artifact.relative_path)
    if path.stat().st_size != artifact.byte_size:
        raise FrozenParquetLoadError("frozen Parquet byte-size identity mismatch")
    if _sha256_file(path) != artifact.sha256:
        raise FrozenParquetLoadError("frozen Parquet SHA-256 identity mismatch")
    factory = parquet_file_factory or _default_parquet_factory
    try:
        parquet = factory(path)
    except Exception as error:
        raise FrozenParquetLoadError("Parquet backend could not open authenticated file") from error
    signature = _schema_signature(parquet)
    names = tuple(field[0] for field in signature)
    if artifact.expected_full_schema is not None and signature != artifact.expected_full_schema:
        raise FrozenParquetLoadError("frozen Parquet footer schema drift")
    missing = tuple(column for column in artifact.required_columns if column not in names)
    if missing:
        raise FrozenParquetLoadError(f"frozen Parquet projection columns missing: {list(missing)}")
    if artifact.expected_projected_schema is not None:
        by_name = {field[0]: field for field in signature}
        projected = tuple(by_name[column] for column in artifact.required_columns)
        if projected != artifact.expected_projected_schema:
            raise FrozenParquetLoadError("frozen projected Parquet schema/dtype drift")
    return parquet


def _read_exact_projection(parquet: Any, columns: tuple[str, ...]) -> pd.DataFrame:
    reader = getattr(parquet, "read", None)
    if not callable(reader):
        raise FrozenParquetLoadError("Parquet backend cannot guarantee explicit column projection")
    try:
        table = reader(columns=list(columns))
    except Exception as error:
        raise FrozenParquetLoadError("Parquet backend rejected explicit column projection") from error
    names = tuple(getattr(table, "column_names", ()))
    if names != columns:
        raise FrozenParquetLoadError("projected Parquet result contains extra, missing, or reordered columns")
    to_pandas = getattr(table, "to_pandas", None)
    if not callable(to_pandas):
        raise FrozenParquetLoadError("Parquet backend cannot materialize explicit projection")
    frame = to_pandas()
    if tuple(frame.columns) != columns:
        raise FrozenParquetLoadError("projected Parquet frame contains extra, missing, or reordered columns")
    return frame.copy(deep=True)


def _normalize_utc(frame: pd.DataFrame, timestamp_columns: Sequence[str]) -> pd.DataFrame:
    result = frame.copy(deep=True)
    for name in timestamp_columns:
        if name not in result:
            raise FrozenParquetLoadError(f"timestamp column missing from projection: {name}")
        raw = result[name]
        try:
            parsed = [pd.Timestamp(value) for value in raw]
        except (TypeError, ValueError) as error:
            raise FrozenParquetLoadError(f"{name} contains invalid timestamps") from error
        if any(value.tzinfo is None for value in parsed if not pd.isna(value)):
            raise FrozenParquetLoadError(f"{name} must contain explicit timezone-aware timestamps")
        result[name] = pd.to_datetime(parsed, utc=True)
    return result


def _canonicalize_order(
    frame: pd.DataFrame,
    unique_columns: Sequence[str],
    order_columns: Sequence[str],
) -> pd.DataFrame:
    """Validate identities and apply the frozen stable canonical ordering."""

    if unique_columns:
        if any(column not in frame for column in unique_columns):
            raise FrozenParquetLoadError("unique identity columns missing from projection")
        if frame.duplicated(list(unique_columns)).any():
            raise FrozenParquetLoadError("projected Parquet contains duplicate identities")
    if order_columns:
        if any(column not in frame for column in order_columns):
            raise FrozenParquetLoadError("order columns missing from projection")
        return frame.sort_values(list(order_columns), kind="mergesort").reset_index(drop=True)
    return frame.reset_index(drop=True)


def _registered_byte_size(root: Path, identity: ArtifactIdentity) -> int:
    """Return the signed manifest byte size after full upstream re-authentication."""

    if identity.manifest_path is None:
        raise FrozenParquetLoadError("registered structural artifact has no manifest identity")
    try:
        # This hashes every registered dependency and validates the unique
        # manifest record before this adapter can open any row group.
        verify_upstream_identities(root)
        manifest = json.loads((root / identity.manifest_path).read_text(encoding="utf-8"))
        records = manifest.get("files", manifest.get("artifacts"))
        matches = [
            item for item in records if isinstance(item, dict) and item.get("path") == Path(identity.path).name
        ] if isinstance(records, list) else []
        if len(matches) != 1:
            raise FrozenParquetLoadError("registered structural manifest identity is ambiguous")
        byte_size = matches[0].get("byte_size", matches[0].get("bytes"))
        if not isinstance(byte_size, int) or byte_size < 0:
            raise FrozenParquetLoadError("registered structural manifest lacks a byte size")
        return byte_size
    except FrozenParquetLoadError:
        raise
    except Exception as error:
        raise FrozenParquetLoadError("registered structural identity verification failed") from error


def _projection_for_identity(identity: ArtifactIdentity) -> tuple[str, ...]:
    """Return the exact role projection without widening the upstream registry."""

    return ASSOCIATION_PROJECTIONS_BY_PATH.get(identity.path, identity.required_columns)


def load_structural_artifact(
    repository_root: Path,
    identity: ArtifactIdentity,
    *,
    parquet_file_factory: ParquetFileFactory | None = None,
    expected_full_schema: tuple[tuple[str, str, bool], ...] | None = None,
    expected_byte_size: int | None = None,
    timestamp_columns: Sequence[str] = (),
    unique_columns: Sequence[str] = (),
    order_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Load exactly one registered upstream artifact using its complete allowlist."""

    byte_size = _registered_byte_size(repository_root, identity) if expected_byte_size is None else expected_byte_size
    projection = _projection_for_identity(identity)
    artifact = FrozenParquetArtifact(
        relative_path=identity.path,
        sha256=identity.sha256,
        byte_size=byte_size,
        required_columns=projection,
        expected_full_schema=expected_full_schema,
        expected_projected_schema=FROZEN_UPSTREAM_PROJECTED_SCHEMAS.get(identity.path),
    )
    parquet = _authenticate_and_open(repository_root, artifact, parquet_file_factory)
    frame = _read_exact_projection(parquet, projection)
    frame = _normalize_utc(frame, timestamp_columns)
    return _canonicalize_order(frame, unique_columns, order_columns)


def load_market_bars(
    source_root: Path,
    inventory: Iterable[MarketParquetRecord],
    *,
    parquet_file_factory: ParquetFileFactory | None = None,
) -> pd.DataFrame:
    """Return detached generic 1m OHLC, using only frozen D004 price columns."""

    records = tuple(sorted(inventory, key=lambda item: item.relative_path))
    if not records or len({item.relative_path for item in records}) != len(records):
        raise FrozenParquetLoadError("market inventory must be nonempty with unique paths")
    pieces: list[pd.DataFrame] = []
    for record in records:
        parquet = _authenticate_and_open(source_root, record.artifact(), parquet_file_factory)
        frame = _read_exact_projection(parquet, MARKET_PROJECTION)
        frame = _normalize_utc(frame, ("timestamp_utc",))
        if frame["timestamp_utc"].isna().any():
            raise FrozenParquetLoadError("market timestamps must be non-null")
        frame = _canonicalize_order(frame, ("timestamp_utc",), ("timestamp_utc",))
        if frame["timestamp_utc"].ge(SOURCE_TERMINAL_EXCLUSIVE).any():
            raise FrozenParquetLoadError("market source contains a 2026-or-later timestamp")
        values = frame.loc[:, MARKET_PROJECTION[1:]].apply(pd.to_numeric, errors="coerce")
        if values.isna().any().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise FrozenParquetLoadError("market OHLC values must be finite")
        if (values.le(0).any().any() or values["mid_high"].lt(values[["mid_open", "mid_close"]].max(axis=1)).any() or values["mid_low"].gt(values[["mid_open", "mid_close"]].min(axis=1)).any()):
            raise FrozenParquetLoadError("market OHLC values violate the frozen bar contract")
        pieces.append(frame.rename(columns={"mid_open": "open", "mid_high": "high", "mid_low": "low", "mid_close": "close"}))
    result = pd.concat(pieces, ignore_index=True)
    result = _canonicalize_order(result, ("timestamp_utc",), ("timestamp_utc",))
    return result.loc[:, GENERIC_OHLC_COLUMNS].copy(deep=True)


__all__ = [
    "FROZEN_D004_MARKET_FULL_SCHEMA", "FROZEN_D004_MARKET_SCHEMA_SIGNATURE",
    "ASSOCIATION_PROJECTIONS_BY_PATH", "FROZEN_UPSTREAM_PROJECTED_SCHEMAS",
    "FrozenParquetArtifact", "FrozenParquetLoadError", "GENERIC_OHLC_COLUMNS",
    "MARKET_PROJECTION", "MarketParquetRecord", "SOURCE_TERMINAL_EXCLUSIVE",
    "load_market_bars", "load_structural_artifact",
]
