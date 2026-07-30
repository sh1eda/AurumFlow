"""Research runner for prepared D003-derived one-minute bars."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
from pathlib import Path
import re
from typing import Sequence

import pandas as pd

from .bars import build_timeframes
from .config import ContextEngineConfig, local_bounds
from .engine import ContextEngine, EvaluationResult
from .reporting import persist_research_results, sha256_file


DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def load_one_minute_bars(
    source: Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    lookback_days: int = 120,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read a prepared D003 derivative without mutating it."""

    resolved = source.resolve()
    files = (
        sorted(resolved.rglob("*.parquet"))
        if resolved.is_dir()
        else [resolved]
    )
    selected: list[Path] = []
    lower = start_date - timedelta(days=lookback_days) if start_date else None
    upper = end_date + timedelta(days=1) if end_date else None
    for path in files:
        match = DATE_IN_NAME.search(path.name)
        if match:
            file_date = date.fromisoformat(match.group(1))
            if lower and file_date < lower:
                continue
            if upper and file_date > upper:
                continue
        selected.append(path)
    if not selected:
        raise ValueError(f"no prepared one-minute files selected from {resolved}")
    pieces: list[pd.DataFrame] = []
    file_records: list[dict[str, object]] = []
    for path in selected:
        frame = pd.read_parquet(path, engine="pyarrow")
        if "timestamp_utc" in frame:
            frame.index = pd.DatetimeIndex(
                pd.to_datetime(frame.pop("timestamp_utc"), utc=True),
                name="timestamp_utc",
            )
        pieces.append(frame)
        file_records.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": int(len(frame)),
            }
        )
    combined = pd.concat(pieces, axis=0).sort_index(kind="mergesort")
    if combined.index.has_duplicates:
        raise ValueError("prepared one-minute derivative has duplicate timestamps")
    provenance_payload = "|".join(
        f"{record['path']}:{record['sha256']}" for record in file_records
    )
    provenance = {
        "source": str(resolved),
        "file_count": len(file_records),
        "row_count": int(len(combined)),
        "files": file_records,
        "selection_sha256": hashlib.sha256(
            provenance_payload.encode("utf-8")
        ).hexdigest(),
        "read_only": True,
        "expected_origin": "D003 canonical XAUUSD derivative",
        "requested_start_date": (
            start_date.isoformat() if start_date is not None else None
        ),
        "requested_end_date": (
            end_date.isoformat() if end_date is not None else None
        ),
        "lookback_days": lookback_days,
    }
    return combined, provenance


def evaluation_timestamps(
    frame: pd.DataFrame,
    *,
    clock: str,
    start_date: date | None,
    end_date: date | None,
    timezone: str,
) -> tuple[pd.Timestamp, ...]:
    local_dates = sorted(set(frame.index.tz_convert(timezone).date))
    result: list[pd.Timestamp] = []
    for session_date in local_dates:
        if session_date.weekday() >= 5:
            continue
        if start_date and session_date < start_date:
            continue
        if end_date and session_date > end_date:
            continue
        stamp, _ = local_bounds(session_date, clock, clock, timezone)
        # local_bounds treats equal clocks as an overnight interval; only the
        # left edge is the requested evaluation instant.
        if frame.index.min() <= stamp <= frame.index.max() + pd.Timedelta(minutes=1):
            result.append(stamp)
    return tuple(result)


def run_context_research(
    *,
    one_minute_source: Path,
    output_dir: Path,
    config: ContextEngineConfig,
    start_date: date | None = None,
    end_date: date | None = None,
    evaluation_clock: str = "09:00",
    mapping_names: Sequence[str] = (),
    report_path: Path | None = None,
    command: Sequence[str] = (),
) -> dict[str, object]:
    config.validate()
    one_minute, provenance = load_one_minute_bars(
        one_minute_source,
        start_date=start_date,
        end_date=end_date,
    )
    timeframes = build_timeframes(one_minute)
    evaluations = evaluation_timestamps(
        timeframes["1min"],
        clock=evaluation_clock,
        start_date=start_date,
        end_date=end_date,
        timezone=config.timezone,
    )
    engine = ContextEngine(config)
    names = tuple(mapping_names) or tuple(mapping.name for mapping in config.mappings)
    results: list[EvaluationResult] = []
    for evaluation in evaluations:
        for name in names:
            results.append(
                engine.evaluate(
                    timeframes,
                    evaluation_at=evaluation,
                    mapping_name=name,
                    session_date=evaluation.tz_convert(config.timezone).date(),
                )
            )
    return persist_research_results(
        results,
        output_dir=output_dir,
        config=config,
        input_provenance=provenance,
        command=command,
        report_path=report_path,
    )
