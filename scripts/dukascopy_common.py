"""Shared primitives for the Dukascopy historical tick-data pipeline.

The source archive is partitioned by UTC hour.  Each accepted object is retained
verbatim; decompression is used only to validate or decode it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import lzma
import math
import os
from pathlib import Path
import struct
import tempfile
import tomllib
from typing import Any, Iterable, Iterator, Mapping


UTC = timezone.utc
CODE_VERSION = "D001-1"
MANIFEST_SCHEMA_VERSION = 1
TICK_STRUCT = struct.Struct(">IIIff")


class DukascopyError(RuntimeError):
    """Base class for data-pipeline failures."""


class ConfigurationError(DukascopyError):
    """The versioned data-source configuration is invalid."""


class PayloadValidationError(DukascopyError):
    """A downloaded archive object cannot be accepted as a tick partition."""


class EmptyPayloadError(PayloadValidationError):
    """The source returned no compressed ticks."""


class MalformedPayloadError(PayloadValidationError):
    """The compressed object or decoded record stream is malformed."""


class PlaceholderPayloadError(PayloadValidationError):
    """The response resembles an HTML/text placeholder rather than BI5 data."""


@dataclass(frozen=True, order=True)
class Partition:
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("partition timestamp must be timezone-aware")
        normalized = self.timestamp.astimezone(UTC)
        if normalized.minute or normalized.second or normalized.microsecond:
            raise ValueError("partition timestamp must be aligned to a UTC hour")
        object.__setattr__(self, "timestamp", normalized)

    @property
    def key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:00:00Z")


@dataclass(frozen=True)
class SymbolConfig:
    archive_symbol: str
    price_scale: int


@dataclass(frozen=True)
class PipelineConfig:
    path: Path
    repository_root: Path
    version: int
    source: Mapping[str, Any]
    symbols: Mapping[str, SymbolConfig]
    paths: Mapping[str, Path]
    download: Mapping[str, Any]
    partition_rules: Mapping[str, Any]
    validation: Mapping[str, Any]
    canonical: Mapping[str, Any]

    def symbol(self, name: str) -> SymbolConfig:
        try:
            return self.symbols[name.upper()]
        except KeyError as exc:
            supported = ", ".join(sorted(self.symbols))
            raise ConfigurationError(
                f"unsupported symbol {name!r}; configured symbols: {supported}"
            ) from exc

    def path_for(self, name: str) -> Path:
        try:
            configured = self.paths[name]
        except KeyError as exc:
            raise ConfigurationError(f"missing [paths].{name}") from exc
        return configured if configured.is_absolute() else self.repository_root / configured


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    version = int(payload.get("version", 0))
    if version != 1:
        raise ConfigurationError(f"unsupported config version {version}; expected 1")
    required = (
        "source",
        "symbols",
        "paths",
        "download",
        "partition_rules",
        "validation",
        "canonical",
    )
    for section in required:
        if section not in payload:
            raise ConfigurationError(f"missing [{section}] configuration section")
    source = payload["source"]
    if source.get("partition") != "hour" or source.get("timezone") != "UTC":
        raise ConfigurationError("D001 requires hourly UTC source partitions")
    if source.get("record_format") != ">IIIff" or int(
        source.get("record_size_bytes", 0)
    ) != TICK_STRUCT.size:
        raise ConfigurationError("source record contract must be >IIIff (20 bytes)")
    symbols = {
        name.upper(): SymbolConfig(
            archive_symbol=str(values["archive_symbol"]),
            price_scale=int(values["price_scale"]),
        )
        for name, values in payload["symbols"].items()
    }
    for name, symbol in symbols.items():
        if symbol.price_scale <= 0:
            raise ConfigurationError(f"{name} price_scale must be positive")
    return PipelineConfig(
        path=config_path,
        repository_root=config_path.parent.parent,
        version=version,
        source=source,
        symbols=symbols,
        paths={key: Path(value) for key, value in payload["paths"].items()},
        download=payload["download"],
        partition_rules=payload["partition_rules"],
        validation=payload["validation"],
        canonical=payload["canonical"],
    )


def parse_utc_boundary(value: str) -> datetime:
    """Parse a date or timezone-aware ISO timestamp and normalize it to UTC."""

    if len(value) == 10:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid date boundary {value!r}") from exc
        return datetime(
            parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO boundary {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime boundaries must include an explicit UTC offset")
    parsed = parsed.astimezone(UTC)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("boundaries must align to a whole UTC hour")
    return parsed


def generate_partitions(start: datetime, end: datetime) -> list[Partition]:
    """Generate inclusive-start, exclusive-end native hourly partitions."""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("partition boundaries must be timezone-aware")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if any((start.minute, start.second, start.microsecond)) or any(
        (end.minute, end.second, end.microsecond)
    ):
        raise ValueError("partition boundaries must align to UTC hours")
    if end <= start:
        raise ValueError("end boundary must be later than start boundary")
    count = int((end - start).total_seconds() // 3600)
    return [Partition(start + timedelta(hours=i)) for i in range(count)]


def partition_url(config: PipelineConfig, symbol: str, partition: Partition) -> str:
    mapping = config.symbol(symbol)
    timestamp = partition.timestamp
    values = {
        "base_url": str(config.source["base_url"]).rstrip("/"),
        "archive_symbol": mapping.archive_symbol,
        "year": timestamp.year,
        "month_zero": timestamp.month - 1,
        "day": timestamp.day,
        "hour": timestamp.hour,
    }
    return str(config.source["url_template"]).format(**values)


def partition_file_path(
    raw_root: Path, symbol: str, partition: Partition
) -> Path:
    timestamp = partition.timestamp
    return (
        raw_root
        / symbol.upper()
        / f"{timestamp.year:04d}"
        / f"{timestamp.month:02d}"
        / f"{timestamp.day:02d}"
        / f"{timestamp.hour:02d}h_ticks.bi5"
    )


def is_expected_closure(config: PipelineConfig, partition: Partition) -> bool:
    """Apply only explicit, auditable UTC calendar rules from configuration."""

    rules = config.partition_rules
    if rules.get("closure_timezone", "UTC") != "UTC":
        raise ConfigurationError("only UTC closure rules are supported")
    timestamp = partition.timestamp
    if timestamp.weekday() in {int(day) for day in rules.get("full_day_closed_weekdays", [])}:
        return True
    if timestamp.date().isoformat() in set(rules.get("explicit_closed_dates", [])):
        return True
    closed_hours = rules.get("closed_utc_hours_by_weekday", {})
    return timestamp.hour in {
        int(hour) for hour in closed_hours.get(str(timestamp.weekday()), [])
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_bi5_payload(
    compressed: bytes,
    *,
    max_compressed_bytes: int,
    record_size: int = TICK_STRUCT.size,
) -> tuple[bytes, int]:
    """Validate a compressed BI5 object and return decoded bytes and row count."""

    if not compressed:
        raise EmptyPayloadError("compressed response is empty")
    if len(compressed) > max_compressed_bytes:
        raise MalformedPayloadError(
            f"compressed response exceeds {max_compressed_bytes} bytes"
        )
    prefix = compressed[:256].lstrip().lower()
    placeholder_markers = (b"<!doctype", b"<html", b"<?xml", b"access denied", b"not found")
    if any(prefix.startswith(marker) for marker in placeholder_markers):
        raise PlaceholderPayloadError("response resembles an HTML/text placeholder")
    try:
        decoded = lzma.decompress(compressed)
    except lzma.LZMAError as exc:
        raise MalformedPayloadError(f"LZMA decompression failed: {exc}") from exc
    if not decoded:
        raise EmptyPayloadError("compressed object contains zero tick records")
    if len(decoded) % record_size:
        raise MalformedPayloadError(
            f"decoded size {len(decoded)} is not divisible by record size {record_size}"
        )
    record_count = len(decoded) // record_size
    for index, (offset_ms, _ask, _bid, ask_volume, bid_volume) in enumerate(
        TICK_STRUCT.iter_unpack(decoded)
    ):
        if offset_ms >= 3_600_000:
            raise MalformedPayloadError(
                f"record {index} has out-of-hour millisecond offset {offset_ms}"
            )
        if not math.isfinite(ask_volume) or not math.isfinite(bid_volume):
            raise MalformedPayloadError(f"record {index} has non-finite volume")
    return decoded, record_count


def validate_bi5_file(path: Path, *, max_compressed_bytes: int) -> int:
    compressed = path.read_bytes()
    _, rows = inspect_bi5_payload(
        compressed, max_compressed_bytes=max_compressed_bytes
    )
    return rows


def decode_ticks(
    decoded: bytes, *, partition: Partition, price_scale: int
) -> Iterator[dict[str, Any]]:
    base_ms = int(partition.timestamp.timestamp() * 1000)
    for offset_ms, ask_raw, bid_raw, ask_volume, bid_volume in TICK_STRUCT.iter_unpack(
        decoded
    ):
        yield {
            "timestamp_ms": base_ms + offset_ms,
            "bid": bid_raw / price_scale,
            "ask": ask_raw / price_scale,
            "bid_volume": float(bid_volume),
            "ask_volume": float(ask_volume),
            "partition_timestamp": partition.key,
        }


def relative_repository_path(path: Path, repository_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_manifest_file_path(
    file_path: str | None, *, repository_root: Path
) -> Path | None:
    if not file_path:
        return None
    candidate = Path(file_path)
    return candidate if candidate.is_absolute() else repository_root / candidate


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably write bytes beside their destination, then atomically replace it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, encoded)


class Manifest:
    """Atomic JSON manifest with one current record per native partition."""

    def __init__(
        self,
        path: Path,
        *,
        config: PipelineConfig,
        symbol: str,
    ) -> None:
        self.path = path
        self.config = config
        self.symbol = symbol.upper()
        mapping = config.symbol(self.symbol)
        if path.exists():
            self.payload = json.loads(path.read_text(encoding="utf-8"))
            if self.payload.get("symbol") != self.symbol:
                raise ConfigurationError(
                    f"manifest symbol {self.payload.get('symbol')!r} does not match {self.symbol}"
                )
        else:
            self.payload = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "config_version": config.version,
                "code_version": CODE_VERSION,
                "symbol": self.symbol,
                "archive_symbol": mapping.archive_symbol,
                "source": config.source["id"],
                "source_url_template": config.source["url_template"],
                "partition": "hour",
                "timezone": "UTC",
                "partitions": {},
            }

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        return self.payload["partitions"]

    def get(self, partition: Partition) -> dict[str, Any] | None:
        return self.entries.get(partition.key)

    def record(self, partition: Partition, **values: Any) -> dict[str, Any]:
        entry = {
            "symbol": self.symbol,
            "partition_timestamp": partition.key,
            **values,
        }
        self.entries[partition.key] = entry
        return entry

    def save(self) -> None:
        self.payload["partitions"] = dict(sorted(self.entries.items()))
        atomic_write_json(self.path, self.payload)


class StructuredLogger:
    """Small JSON-lines logger suitable for both terminal and generated log files."""

    def __init__(self, *, log_path: Path | None = None, quiet: bool = False) -> None:
        self.logger = logging.getLogger(f"dukascopy.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers.clear()
        self.log_path = log_path
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = log_path.open("a", encoding="utf-8")
        else:
            self._file_handle = None
        self.quiet = quiet

    def emit(self, level: str, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            **fields,
        }
        line = json.dumps(record, sort_keys=True, default=str)
        if not self.quiet:
            print(line, flush=True)
        if self._file_handle is not None:
            self._file_handle.write(line + "\n")
            self._file_handle.flush()

    def close(self) -> None:
        if self._file_handle is not None:
            self._file_handle.close()

    def __enter__(self) -> "StructuredLogger":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def manifest_file_hash(path: Path) -> str:
    return sha256_file(path)


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def group_partitions_by_date(
    partitions: Iterable[Partition],
) -> dict[str, list[Partition]]:
    grouped: dict[str, list[Partition]] = {}
    for partition in partitions:
        grouped.setdefault(partition.timestamp.date().isoformat(), []).append(partition)
    return grouped
