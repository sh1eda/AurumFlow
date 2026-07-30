from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.d003_e1_2026_canonical_extension.audit import (
    build_duplicate_report,
    build_gap_report,
    build_schema_audit,
    canonical_json_hash,
    classify_compatibility,
    compare_feeds,
)
from research.d003_e1_2026_canonical_extension.config import (
    ExtensionAuditConfig,
)
from research.d003_e1_2026_canonical_extension import cli
from research.d003_e1_2026_canonical_extension.reporting import write_json


def _minute_frame(
    timestamps: list[str],
    *,
    level: float,
    spread: float,
    tick_count: int,
) -> pd.DataFrame:
    timestamp = pd.to_datetime(pd.Series(timestamps), utc=True)
    close = pd.Series([level + index for index in range(len(timestamp))])
    return pd.DataFrame(
        {
            "timestamp_utc": timestamp,
            "bid_open": close - spread / 2,
            "bid_high": close + 0.5 - spread / 2,
            "bid_low": close - 0.5 - spread / 2,
            "bid_close": close - spread / 2,
            "ask_open": close + spread / 2,
            "ask_high": close + 0.5 + spread / 2,
            "ask_low": close - 0.5 + spread / 2,
            "ask_close": close + spread / 2,
            "mid_open": close,
            "mid_high": close + 0.5,
            "mid_low": close - 0.5,
            "mid_close": close,
            "tick_count": tick_count,
            "median_spread": spread,
            "maximum_spread": spread,
            "last_spread": spread,
        }
    )


def test_frozen_config_preserves_e4_minimums_and_stage_b_gate() -> None:
    config = ExtensionAuditConfig()
    config.validate()
    assert config.minimum_validation_n == 1000
    assert config.minimum_direction_n == 200
    assert config.bootstrap_seed == 50054
    assert config.classification_if_gate_fails == 6
    assert config.snapshot()["allowed_stage_b_compatibility_classes"] == [1, 2]


def test_d003_schema_audit_refuses_missing_native_side_volumes() -> None:
    schema, metadata = build_schema_audit(ExtensionAuditConfig())
    by_name = schema.set_index("column")
    assert not by_name.loc["bid_volume", "reconstructable_without_inference"]
    assert not by_name.loc["ask_volume", "reconstructable_without_inference"]
    assert not by_name.loc["timestamp_utc", "contract_satisfied"]
    assert not metadata["exact_nonnullable_schema_possible_without_fabrication"]


def test_feed_classification_is_three_even_when_numeric_overlap_is_close() -> None:
    schema, metadata = build_schema_audit(ExtensionAuditConfig())
    overlap = pd.DataFrame.from_records(
        [
            {
                "abs_mid_close_diff_median": 0.0,
                "abs_mid_close_diff_p95": 0.0,
                "one_minute_return_correlation": 1.0,
                "median_spread_ratio_mt5_to_d003": 1.0,
                "median_tick_count_ratio_mt5_to_d003": 1.0,
            }
        ]
    )
    result = classify_compatibility(schema, metadata, overlap)
    assert result["classification_id"] == 3
    assert not result["stage_a_passed"]
    assert not result["stage_b_permitted"]


def test_true_overlap_comparison_uses_exact_utc_minutes() -> None:
    config = ExtensionAuditConfig(
        overlap_start="2025-07-17T10:00:00Z",
        overlap_end="2025-07-17T10:04:00Z",
        post_2025_start="2025-07-17T10:04:00Z",
    )
    d003 = _minute_frame(
        [
            "2025-07-17T10:00:00Z",
            "2025-07-17T10:01:00Z",
            "2025-07-17T10:02:00Z",
        ],
        level=3300.0,
        spread=1.0,
        tick_count=100,
    )
    mt5 = _minute_frame(
        [
            "2025-07-17T10:01:00Z",
            "2025-07-17T10:02:00Z",
            "2025-07-17T10:03:00Z",
        ],
        level=3300.1,
        spread=0.2,
        tick_count=200,
    )
    result = compare_feeds(d003, mt5, config)["overlap_summary"].iloc[0]
    assert result["common_minutes"] == 2
    assert result["union_minutes"] == 4
    assert result["coverage_jaccard"] == 0.5
    assert result["d003_only_minutes"] == 1
    assert result["mt5_only_minutes"] == 1


def test_gap_report_separates_weekend_and_daily_session_candidates() -> None:
    frame = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                [
                    "2026-01-02T21:59:00Z",
                    "2026-01-04T23:00:00Z",
                    "2026-01-05T21:59:00Z",
                    "2026-01-05T23:00:00Z",
                ],
                utc=True,
            )
        }
    )
    result = build_gap_report(frame)
    assert "suspected_weekend_market_closure" in set(
        result["gap_classification"]
    )
    assert "suspected_broker_daily_session_gap" in set(
        result["gap_classification"]
    )
    assert str(result["previous_timestamp_utc"].dt.tz) == "UTC"
    assert str(result["next_timestamp_utc"].dt.tz) == "UTC"


def test_duplicate_report_does_not_equate_same_timestamp_with_exact_tick() -> None:
    minutes = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"],
                utc=True,
            )
        }
    )
    result = build_duplicate_report(minutes, {})
    raw = result[result["level"].eq("raw_tick_timestamp")].iloc[0]
    minute = result[
        result["level"].eq("normalized_minute_timestamp")
    ].iloc[0]
    assert not raw["d003_identity_comparable"]
    assert minute["duplicate_count"] == 2


def test_json_writer_normalizes_nan_without_nonstandard_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "value.json"
    write_json(path, {"missing": float("nan"), "value": 1})
    observed = json.loads(path.read_text(encoding="utf-8"))
    assert observed == {"missing": None, "value": 1}


def test_config_fingerprint_is_deterministic() -> None:
    config = ExtensionAuditConfig()
    assert config.fingerprint() == ExtensionAuditConfig().fingerprint()
    assert canonical_json_hash(config.snapshot()) == config.fingerprint()


def test_cli_records_exact_package_reproduction_command(
    tmp_path: Path, monkeypatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run_audit(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {}

    monkeypatch.setattr(cli, "run_audit", fake_run_audit)
    assert cli.main(["--output", str(tmp_path / "output")]) == 0
    assert observed["command"] == [
        cli.sys.executable,
        "-m",
        "research.d003_e1_2026_canonical_extension",
    ]
