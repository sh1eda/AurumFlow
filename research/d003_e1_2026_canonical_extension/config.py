"""Frozen configuration for the D003_E1 extension gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json


@dataclass(frozen=True)
class ExtensionAuditConfig:
    study_id: str = (
        "D003_E1_2026_CANONICAL_EXTENSION_AND_"
        "D005_E4_INDEPENDENT_REPLICATION"
    )
    version: str = "D003-E1-v1"
    candidate_release_id: str = "d003-2026-extension-v1"
    symbol: str = "XAUUSD"
    historical_release_id: str = "d003-v1"
    historical_source: str = "dukascopy-public-bi5"
    post_2025_start: str = "2026-01-01T00:00:00Z"
    overlap_start: str = "2025-07-17T10:00:00Z"
    overlap_end: str = "2026-01-01T00:00:00Z"
    mt5_source_timezone: str = "Europe/Helsinki"
    mt5_timezone_evidence_grade: str = "strongly_supported_not_authenticated"
    historical_canonical_root: str = "data/canonical/xauusd_ticks"
    historical_release_root: str = "data/releases/d003-v1"
    d003_builder: str = "scripts/build_dukascopy_canonical.py"
    d003_verifier: str = "scripts/validate_canonical_dataset.py"
    historical_minute_source: str = (
        "research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m"
    )
    raw_tick_source: str = (
        "data/local/XAUUSD_202507171300_202607171409.csv"
    )
    normalized_tick_source: str = (
        "research/event_study_0830_0930/external_data/normalized/"
        "XAUUSD_202507171300_202607171409.canonical_ticks.csv"
    )
    normalized_minute_source: str = (
        "research/event_study_0830_0930/external_data/normalized/"
        "XAUUSD_202507171300_202607171409.1m_bidask.csv"
    )
    m15_source: str = "data/local/XAUUSDM15.csv"
    m15_utc_source: str = "data/local/XAUUSDM15.utc.csv"
    prior_tick_source: str = "data/local/24-25.csv"
    tick_metadata: str = (
        "research/event_study_0830_0930/tick_metadata.json"
    )
    tick_validation_report: str = (
        "research/event_study_0830_0930/tick_validation_report.md"
    )
    timezone_report: str = (
        "research/event_study_0830_0930/"
        "broker_timezone_validation.md"
    )
    frozen_e4_spec: str = (
        "docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md"
    )
    minimum_validation_n: int = 1000
    minimum_direction_n: int = 200
    confidence_level: float = 0.95
    bootstrap_resamples: int = 2000
    bootstrap_seed: int = 50054
    classification_if_gate_fails: int = 6

    def validate(self) -> None:
        start = datetime.fromisoformat(
            self.overlap_start.replace("Z", "+00:00")
        )
        end = datetime.fromisoformat(
            self.overlap_end.replace("Z", "+00:00")
        )
        post = datetime.fromisoformat(
            self.post_2025_start.replace("Z", "+00:00")
        )
        if start.tzinfo is None or end.tzinfo is None or post.tzinfo is None:
            raise ValueError("all frozen boundaries must be timezone aware")
        if not (start < end <= post):
            raise ValueError("invalid overlap/post-2025 boundary")
        if self.minimum_validation_n != 1000:
            raise ValueError("frozen E4 minimum N changed")
        if self.minimum_direction_n != 200:
            raise ValueError("frozen E4 direction minimum changed")
        if self.bootstrap_seed != 50054:
            raise ValueError("frozen E4 bootstrap seed changed")
        if self.classification_if_gate_fails != 6:
            raise ValueError("feed gate must map to replication category 6")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload.update(
            {
                "frozen_at": (
                    "before_quantitative_overlap_metrics_and_"
                    "post_2025_strategy_outcomes"
                ),
                "allowed_stage_b_compatibility_classes": [1, 2],
                "required_native_fields": [
                    "timestamp_utc",
                    "bid",
                    "ask",
                    "bid_volume",
                    "ask_volume",
                    "mid",
                    "spread",
                    "symbol",
                    "source_partition",
                ],
                "required_feed_identity": self.historical_source,
                "logical_build_timestamp": (
                    "latest controlling source observation"
                ),
                "production_integration": False,
                "canonical_historical_mutation": False,
                "strategy_logic_change": False,
            }
        )
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


UTC = timezone.utc

