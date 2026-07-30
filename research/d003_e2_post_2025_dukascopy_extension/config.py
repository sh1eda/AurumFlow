"""Frozen D003_E2 acquisition boundaries and isolation paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json


UTC = timezone.utc


def safe_closed_hour_cutoff(captured_at: datetime) -> datetime:
    """Exclude the current and immediately preceding UTC partitions."""

    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("capture timestamp must be timezone aware")
    current_hour = captured_at.astimezone(UTC).replace(
        minute=0, second=0, microsecond=0
    )
    return current_hour - timedelta(hours=1)


@dataclass(frozen=True)
class D003E2Config:
    task_id: str = "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION"
    candidate_release_id: str = (
        "d003-post-2025-dukascopy-extension-v1"
    )
    symbol: str = "XAUUSD"
    capture_timestamp: str = "2026-07-29T13:21:38Z"
    start_inclusive: str = "2026-01-01T00:00:00Z"
    end_exclusive: str = "2026-07-29T12:00:00Z"
    requested_partition_count: int = 5028
    output_root: str = (
        "research_outputs/"
        "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION"
    )
    raw_root: str = (
        "research_outputs/"
        "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION/raw_source"
    )
    source_manifest: str = (
        "research_outputs/"
        "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION/"
        "source_manifest.json"
    )
    verification_report: str = (
        "research_outputs/"
        "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION/"
        "d001_verification_report.json"
    )
    acquisition_log: str = (
        "research_outputs/"
        "D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION/"
        "acquisition_log.jsonl"
    )
    pipeline_config: str = "config/dukascopy_data.toml"
    minimum_later_e4_n: int = 1000

    def validate(self) -> None:
        capture = datetime.fromisoformat(
            self.capture_timestamp.replace("Z", "+00:00")
        )
        start = datetime.fromisoformat(
            self.start_inclusive.replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            self.end_exclusive.replace("Z", "+00:00")
        )
        if safe_closed_hour_cutoff(capture) != end:
            raise ValueError("frozen cutoff no longer matches safety rule")
        if int((end - start).total_seconds() // 3600) != (
            self.requested_partition_count
        ):
            raise ValueError("requested partition count changed")

    def snapshot(self) -> dict[str, object]:
        value = asdict(self)
        value.update(
            {
                "source_id": "dukascopy-public-bi5",
                "archive_symbol": "XAUUSD",
                "record_format": ">IIIff",
                "record_size_bytes": 20,
                "price_scale": 1000,
                "mt5_permitted": False,
                "d005_e4_permitted": False,
                "pipeline_behavior_modified": False,
            }
        )
        return value

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.snapshot(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

