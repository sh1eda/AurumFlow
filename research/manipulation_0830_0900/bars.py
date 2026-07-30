"""Incremental deterministic candle construction from the D003 tick dataset."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


TICK_COLUMNS = ("timestamp_utc", "bid", "ask", "mid", "spread")
PRICE_NAMES = ("bid", "ask", "mid")
BAR_COLUMNS = tuple(
    column
    for name in PRICE_NAMES
    for column in (f"{name}_open", f"{name}_high", f"{name}_low", f"{name}_close")
) + (
    "tick_count",
    "median_spread",
    "maximum_spread",
    "last_spread",
)


class BarBuildError(RuntimeError):
    """Raised when canonical input cannot produce a trustworthy bar cache."""


@dataclass(frozen=True)
class CanonicalFile:
    date: date
    path: Path
    sha256: str
    row_count: int


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def load_canonical_manifest(dataset_root: Path) -> tuple[dict, list[CanonicalFile]]:
    manifest_path = dataset_root / "canonical_manifest.json"
    if not manifest_path.is_file():
        raise BarBuildError(f"canonical manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_version") != "d003-v1":
        raise BarBuildError(
            f"D004 requires dataset_version d003-v1, got {manifest.get('dataset_version')!r}"
        )
    files: list[CanonicalFile] = []
    root_parent = dataset_root.parents[2] if len(dataset_root.parents) >= 3 else dataset_root.parent
    for record in manifest.get("files", []):
        declared = Path(record["path"])
        candidates = (root_parent / declared, dataset_root / declared.name)
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            raise BarBuildError(f"manifested canonical file is missing: {declared}")
        files.append(
            CanonicalFile(
                date=date.fromisoformat(record["date"]),
                path=path,
                sha256=str(record["sha256"]),
                row_count=int(record["row_count"]),
            )
        )
    files.sort(key=lambda item: (item.date, str(item.path)))
    if len(files) != int(manifest.get("canonical_file_count", -1)):
        raise BarBuildError("canonical manifest file count does not reconcile")
    return manifest, files


def _price_ohlc(ticks: pd.DataFrame, name: str) -> pd.DataFrame:
    return ticks[name].resample(
        "1min", label="left", closed="left", origin="epoch"
    ).ohlc().rename(
        columns={
            "open": f"{name}_open",
            "high": f"{name}_high",
            "low": f"{name}_low",
            "close": f"{name}_close",
        }
    )


def ticks_to_one_minute(ticks: pd.DataFrame) -> pd.DataFrame:
    """Build UTC-aligned half-open one-minute OHLC from sorted canonical ticks."""

    missing = set(TICK_COLUMNS) - set(ticks.columns)
    if missing:
        raise BarBuildError(f"tick frame is missing columns: {sorted(missing)}")
    frame = ticks.loc[:, TICK_COLUMNS].copy()
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp_utc"), utc=True))
    if index.hasnans:
        raise BarBuildError("canonical tick timestamps contain nulls")
    if not index.is_monotonic_increasing:
        raise BarBuildError("canonical tick timestamps are not ordered")
    frame.index = index
    pieces = [_price_ohlc(frame, name) for name in PRICE_NAMES]
    spread = frame["spread"].resample(
        "1min", label="left", closed="left", origin="epoch"
    ).agg(["median", "max", "last"])
    spread.columns = ["median_spread", "maximum_spread", "last_spread"]
    tick_count = frame["mid"].resample(
        "1min", label="left", closed="left", origin="epoch"
    ).size().rename("tick_count")
    bars = pd.concat([*pieces, tick_count, spread], axis=1)
    bars = bars[bars["tick_count"].gt(0)].copy()
    bars.index.name = "timestamp_utc"
    bars["tick_count"] = bars["tick_count"].astype("int64")
    validate_bars(bars, resolution_minutes=1)
    return bars


def aggregate_bars(one_minute: pd.DataFrame, resolution_minutes: int) -> pd.DataFrame:
    """Aggregate deterministic UTC-aligned 5m/15m bars from one-minute bars."""

    if resolution_minutes == 1:
        result = one_minute.copy()
        validate_bars(result, resolution_minutes=1)
        return result
    if resolution_minutes not in {5, 15}:
        raise ValueError("supported bar resolutions are 1, 5 and 15 minutes")
    aggregations: dict[str, str] = {}
    for name in PRICE_NAMES:
        aggregations.update(
            {
                f"{name}_open": "first",
                f"{name}_high": "max",
                f"{name}_low": "min",
                f"{name}_close": "last",
            }
        )
    aggregations.update(
        {
            "tick_count": "sum",
            "median_spread": "median",
            "maximum_spread": "max",
            "last_spread": "last",
        }
    )
    result = one_minute.resample(
        f"{resolution_minutes}min",
        label="left",
        closed="left",
        origin="epoch",
    ).agg(aggregations)
    result = result[result["tick_count"].gt(0)].copy()
    result.index.name = "timestamp_utc"
    result["tick_count"] = result["tick_count"].astype("int64")
    validate_bars(result, resolution_minutes=resolution_minutes)
    return result


def validate_bars(frame: pd.DataFrame, *, resolution_minutes: int) -> None:
    """Fail closed on timestamp alignment, missing values, or OHLC inconsistency."""

    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        raise BarBuildError(f"bar frame is missing columns: {sorted(missing)}")
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None or str(index.tz) not in {"UTC", "UTC+00:00"}:
        raise BarBuildError("bar timestamps must be timezone-aware UTC")
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise BarBuildError("bar timestamps must be unique and ordered")
    if len(index):
        aligned = (
            (index.second.to_numpy() == 0)
            & (index.microsecond.to_numpy() == 0)
            & (index.nanosecond.to_numpy() == 0)
            & (index.minute.to_numpy() % resolution_minutes == 0)
        )
        if not bool(aligned.all()):
            raise BarBuildError(f"{resolution_minutes}m timestamps are not left aligned")
    numeric = frame.loc[:, BAR_COLUMNS]
    if numeric.isna().any().any():
        raise BarBuildError("bar frame contains missing values")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise BarBuildError("bar frame contains non-finite values")
    for name in PRICE_NAMES:
        opening = frame[f"{name}_open"]
        high = frame[f"{name}_high"]
        low = frame[f"{name}_low"]
        closing = frame[f"{name}_close"]
        invalid = (
            high.lt(low)
            | high.lt(pd.concat([opening, closing], axis=1).max(axis=1))
            | low.gt(pd.concat([opening, closing], axis=1).min(axis=1))
        )
        if invalid.any():
            raise BarBuildError(
                f"{name} OHLC invariants fail on {int(invalid.sum())} bar(s)"
            )
    if frame["tick_count"].le(0).any():
        raise BarBuildError("bar tick count must be positive")
    if frame[["median_spread", "maximum_spread", "last_spread"]].lt(0).any().any():
        raise BarBuildError("bar spreads cannot be negative")
    if frame["maximum_spread"].lt(frame["median_spread"]).any():
        raise BarBuildError("maximum spread cannot be below median spread")


def _cache_path(cache_root: Path, item: CanonicalFile) -> Path:
    return (
        cache_root
        / f"year={item.date.year:04d}"
        / f"month={item.date.month:02d}"
        / f"bars_1m_{item.date.isoformat()}.parquet"
    )


def _atomic_parquet(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    frame.reset_index().to_parquet(
        temporary,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )
    os.replace(temporary, target)


def _read_cache(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, engine="pyarrow")
    timestamp = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp_utc"), utc=True))
    frame.index = timestamp
    frame.index.name = "timestamp_utc"
    validate_bars(frame, resolution_minutes=1)
    return frame


def _build_one(
    item: CanonicalFile,
    cache_root: Path,
    checkpoint_record: dict | None,
    resume: bool,
) -> dict[str, object]:
    target = _cache_path(cache_root, item)
    if resume and checkpoint_record and target.is_file():
        expected = checkpoint_record.get("cache_sha256")
        if (
            checkpoint_record.get("source_sha256") == item.sha256
            and expected
            and sha256_file(target) == expected
        ):
            cached = _read_cache(target)
            if len(cached) == int(checkpoint_record.get("bar_count", -1)):
                return {**checkpoint_record, "status": "reused"}
    table = pq.read_table(item.path, columns=list(TICK_COLUMNS))
    if table.num_rows != item.row_count:
        raise BarBuildError(
            f"row count mismatch for {item.path}: {table.num_rows} != {item.row_count}"
        )
    ticks = table.to_pandas()
    bars = ticks_to_one_minute(ticks)
    _atomic_parquet(bars, target)
    return {
        "date": item.date.isoformat(),
        "source_path": str(item.path),
        "source_sha256": item.sha256,
        "source_row_count": item.row_count,
        "cache_path": str(target),
        "cache_sha256": sha256_file(target),
        "bar_count": int(len(bars)),
        "first_bar_utc": bars.index.min().isoformat() if len(bars) else None,
        "last_bar_utc": bars.index.max().isoformat() if len(bars) else None,
        "status": "built",
    }


def _write_checkpoint(path: Path, records: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [records[key] for key in sorted(records)],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_bar_cache(
    files: Iterable[CanonicalFile],
    cache_root: Path,
    *,
    resume: bool,
    worker_count: int,
    progress: Callable[[str, dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    """Incrementally build/reuse deterministic daily one-minute cache files."""

    selected = sorted(files, key=lambda item: item.date)
    checkpoint_path = cache_root / "checkpoint.json"
    prior: dict[str, dict[str, object]] = {}
    if resume and checkpoint_path.is_file():
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        prior = {str(item["date"]): item for item in payload.get("records", [])}
    current: dict[str, dict[str, object]] = {}

    def completed(record: dict[str, object]) -> None:
        key = str(record["date"])
        current[key] = record
        _write_checkpoint(checkpoint_path, current)
        if progress:
            progress("bar_cache_file", record)

    if worker_count == 1:
        for item in selected:
            record = _build_one(
                item,
                cache_root,
                prior.get(item.date.isoformat()),
                resume,
            )
            completed(record)
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _build_one,
                    item,
                    cache_root,
                    prior.get(item.date.isoformat()),
                    resume,
                ): item
                for item in selected
            }
            pending: dict[str, dict[str, object]] = {}
            for future in as_completed(futures):
                record = future.result()
                pending[str(record["date"])] = record
                # Checkpoint in source-date order for deterministic content.
                for item in selected:
                    key = item.date.isoformat()
                    if key in current:
                        continue
                    if key not in pending:
                        break
                    completed(pending.pop(key))
    return [current[key] for key in sorted(current)]


def read_cached_bars(
    records: Iterable[dict[str, object]],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Load the compact bar derivative, never the full tick dataset."""

    frames: list[pd.DataFrame] = []
    source_start = start_date - timedelta(days=1) if start_date else None
    source_end = end_date + timedelta(days=1) if end_date else None
    for record in sorted(records, key=lambda item: str(item["date"])):
        record_date = date.fromisoformat(str(record["date"]))
        if source_start and record_date < source_start:
            continue
        if source_end and record_date > source_end:
            continue
        frames.append(_read_cache(Path(str(record["cache_path"]))))
    if not frames:
        return pd.DataFrame(columns=BAR_COLUMNS, index=pd.DatetimeIndex([], tz="UTC"))
    result = pd.concat(frames).sort_index()
    if result.index.has_duplicates:
        raise BarBuildError("daily bar caches overlap at one or more timestamps")
    validate_bars(result, resolution_minutes=1)
    return result
