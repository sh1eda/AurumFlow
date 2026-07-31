"""End-to-end orchestration for the isolated D004 research run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import Sequence

import numpy as np
import pandas as pd
import pyarrow

from .analysis import run_analysis
from .bars import (
    CanonicalFile,
    build_bar_cache,
    load_canonical_manifest,
    read_cached_bars,
    sha256_file,
)
from .config import ResearchConfig
from .features import build_daily_events
from .reporting import write_artifacts, write_json
from .verification import verify_output


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _command(argv: Sequence[str] | None) -> str:
    values = list(argv) if argv is not None else sys.argv
    return " ".join(values)


class RunLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def emit(self, event: str, payload: dict[str, object] | None = None) -> None:
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **(payload or {}),
        }
        self._handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def _select_files(
    files: list[CanonicalFile],
    config: ResearchConfig,
) -> list[CanonicalFile]:
    selected: list[CanonicalFile] = []
    for item in files:
        if config.start_date and item.date < config.start_date - pd.Timedelta(days=1):
            continue
        if config.end_date and item.date > config.end_date + pd.Timedelta(days=1):
            continue
        selected.append(item)
    return selected


def run_research(
    config: ResearchConfig,
    *,
    argv: Sequence[str] | None = None,
) -> dict[str, object]:
    """Run D004 without mutating canonical or production files."""

    config.validate()
    started = time.monotonic()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(config.output_dir / "run.log.jsonl")
    try:
        logger.emit("run_started", {"configuration": config.snapshot()})
        manifest, all_files = load_canonical_manifest(config.dataset_root)
        selected = _select_files(all_files, config)
        if not selected:
            raise ValueError("no canonical source files overlap the requested date range")
        logger.emit(
            "canonical_manifest_loaded",
            {
                "dataset_id": manifest["dataset_id"],
                "selected_files": len(selected),
                "selected_rows": sum(item.row_count for item in selected),
            },
        )
        cache_records = build_bar_cache(
            selected,
            config.output_dir / "cache" / "bars_1m",
            resume=config.resume,
            worker_count=config.worker_count,
            progress=logger.emit,
        )
        bars = read_cached_bars(
            cache_records,
            start_date=config.start_date,
            end_date=config.end_date,
        )
        logger.emit("bar_cache_loaded", {"one_minute_rows": len(bars)})
        daily, fvg_events = build_daily_events(bars, config)
        logger.emit(
            "daily_events_built",
            {
                "candidate_dates": len(daily),
                "core_eligible": int(daily.get("core_eligible", pd.Series(dtype=bool)).sum()),
                "fvg_events": len(fvg_events),
            },
        )
        artifacts = run_analysis(daily, fvg_events, bars, config)
        repository_root = Path(__file__).resolve().parents[2]
        manifest_path = config.dataset_root / "canonical_manifest.json"
        metadata: dict[str, object] = {
            "schema_version": 1,
            "research_id": "D004",
            "research_only": True,
            "production_behavior_changed": False,
            "canonical_dataset": {
                "dataset_id": manifest["dataset_id"],
                "dataset_version": manifest["dataset_version"],
                "manifest_sha256": sha256_file(manifest_path),
                "canonical_file_count": manifest["canonical_file_count"],
                "canonical_row_count": manifest["row_count"],
                "date_range": manifest["date_range"],
            },
            "processed_source_files": len(selected),
            "processed_tick_rows": sum(item.row_count for item in selected),
            "bar_cache_built_files": sum(
                record["status"] == "built" for record in cache_records
            ),
            "bar_cache_reused_files": sum(
                record["status"] == "reused" for record in cache_records
            ),
            "one_minute_bar_rows": int(len(bars)),
            "candidate_dates": int(len(artifacts.daily_events)),
            "core_eligible_dates": int(artifacts.daily_events["core_eligible"].sum()),
            "coverage_status_counts": {
                str(key): int(value)
                for key, value in artifacts.daily_events[
                    "source_data_coverage_status"
                ]
                .value_counts()
                .sort_index()
                .items()
            },
            "processing_reconciliation": {
                "source_files_processed": len(selected),
                "source_files_skipped": 0,
                "source_files_failed": 0,
                "candidate_trading_dates_processed": int(
                    len(artifacts.daily_events)
                ),
                "candidate_trading_dates_failed": 0,
                "core_incomplete_dates": [
                    str(value)
                    for value in artifacts.daily_events.loc[
                        artifacts.daily_events[
                            "source_data_coverage_status"
                        ].eq("core_incomplete"),
                        "trading_date",
                    ]
                ],
                "inference_excluded_dates": [
                    str(value)
                    for value in artifacts.daily_events.loc[
                        ~artifacts.daily_events["core_eligible"].astype(bool),
                        "trading_date",
                    ]
                ],
            },
            "fvg_event_count": int(len(artifacts.fvg_events)),
            "strategy_event_rows": int(len(artifacts.strategy_events)),
            "event_labels_supplied": config.event_labels is not None,
            "command": _command(argv),
            "git_commit": _git_commit(repository_root),
            "python": sys.version,
            "platform": platform.platform(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "pyarrow": pyarrow.__version__,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds_before_write": time.monotonic() - started,
            "verification_status": "pending",
            "exclusion_policy": (
                "Every New York weekday in the selected coverage is retained in "
                "daily_events; incomplete core windows are flagged and excluded "
                "from inferential/strategy tables, never silently dropped."
            ),
        }
        _, report = write_artifacts(
            artifacts,
            config=config,
            metadata=metadata,
        )
        verification = verify_output(config.output_dir, write=True)
        metadata["verification_status"] = verification["status"]
        metadata["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        metadata["total_elapsed_seconds"] = time.monotonic() - started
        # Refresh metadata/report/manifest after the verification status is known.
        _, report = write_artifacts(
            artifacts,
            config=config,
            metadata=metadata,
        )
        verification = verify_output(config.output_dir, write=True)
        if verification["status"] != "PASS":
            raise RuntimeError("independent verification failed")
        if config.report_path:
            config.report_path.parent.mkdir(parents=True, exist_ok=True)
            config.report_path.write_text(report, encoding="utf-8")
        logger.emit(
            "run_completed",
            {
                "verification_status": verification["status"],
                "elapsed_seconds": time.monotonic() - started,
            },
        )
        return {
            "output_dir": str(config.output_dir),
            "report_path": str(config.report_path) if config.report_path else None,
            "metadata": metadata,
            "verification": verification,
        }
    except Exception as exc:
        logger.emit("run_failed", {"error": repr(exc)})
        raise
    finally:
        logger.close()
