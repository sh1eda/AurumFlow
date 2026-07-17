from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from research.event_study_0830_0930.timezone_validation import (
    EVENTS,
    MODEL_FIXED_UTC2,
    MODEL_FIXED_UTC3,
    MODEL_HELSINKI,
    ReleaseEvent,
    analyze,
    candidate_source_time,
    confidence_grade,
    run,
)


def _event(official_et: str, regime: str) -> ReleaseEvent:
    return ReleaseEvent("synthetic", official_et, "Synthetic release", "test", regime, "")


def test_candidate_mappings_cover_winter_summer_and_dst_mismatch() -> None:
    winter = _event("2026-01-09 08:30", "winter_standard_time")
    summer = _event("2025-08-01 08:30", "summer_both_dst")
    mismatch = _event("2026-03-11 08:30", "spring_dst_mismatch")

    assert candidate_source_time(winter, MODEL_HELSINKI) == pd.Timestamp(
        "2026-01-09 15:30"
    )
    assert candidate_source_time(winter, MODEL_FIXED_UTC2) == pd.Timestamp(
        "2026-01-09 15:30"
    )
    assert candidate_source_time(winter, MODEL_FIXED_UTC3) == pd.Timestamp(
        "2026-01-09 16:30"
    )
    assert candidate_source_time(summer, MODEL_HELSINKI) == pd.Timestamp(
        "2025-08-01 15:30"
    )
    assert candidate_source_time(summer, MODEL_FIXED_UTC3) == pd.Timestamp(
        "2025-08-01 15:30"
    )
    assert candidate_source_time(summer, MODEL_FIXED_UTC2) == pd.Timestamp(
        "2025-08-01 14:30"
    )
    assert candidate_source_time(mismatch, MODEL_HELSINKI) == pd.Timestamp(
        "2026-03-11 14:30"
    )
    assert candidate_source_time(mismatch, MODEL_FIXED_UTC2) == pd.Timestamp(
        "2026-03-11 14:30"
    )
    assert candidate_source_time(mismatch, MODEL_FIXED_UTC3) == pd.Timestamp(
        "2026-03-11 15:30"
    )


def _synthetic_bars(events: tuple[ReleaseEvent, ...]) -> pd.DataFrame:
    pieces = []
    for event in events:
        center = candidate_source_time(event, MODEL_HELSINKI)
        index = pd.date_range(center - pd.Timedelta("35min"), periods=105, freq="min")
        frame = pd.DataFrame(
            {
                "source_time": index,
                "tick_count": 100,
                "mid_range": 1.0,
                "maximum_spread": 0.2,
            },
            index=index,
        )
        frame.loc[center, ["tick_count", "mid_range", "maximum_spread"]] = [
            300,
            8.0,
            0.5,
        ]
        pieces.append(frame)
    return pd.concat(pieces).sort_index()


def test_cross_regime_analysis_strongly_supports_helsinki() -> None:
    events = (
        ReleaseEvent("winter", "2026-01-09 08:30", "Winter", "test", "winter_standard_time", ""),
        ReleaseEvent("summer", "2025-08-01 08:30", "Summer", "test", "summer_both_dst", ""),
        ReleaseEvent("mismatch", "2026-03-11 08:30", "Mismatch", "test", "spring_dst_mismatch", ""),
        ReleaseEvent("fall", "2025-10-28 10:00", "Fall", "test", "fall_dst_mismatch", ""),
    )
    bars = _synthetic_bars(events)
    _, _, aggregates = analyze(bars, events)

    assert confidence_grade(aggregates) == "STRONGLY SUPPORTED"
    assert aggregates[MODEL_HELSINKI]["alignment_rate_percent"] == 100.0
    assert aggregates[MODEL_FIXED_UTC2]["regimes"]["summer_both_dst"][
        "median_absolute_error_minutes"
    ] == 60.0
    assert aggregates[MODEL_FIXED_UTC3]["regimes"]["winter_standard_time"][
        "median_absolute_error_minutes"
    ] == 60.0


def test_run_does_not_mutate_normalized_inputs(tmp_path: Path) -> None:
    event = EVENTS[3]
    center = candidate_source_time(event, MODEL_HELSINKI)
    index = pd.date_range(center - pd.Timedelta("35min"), periods=105, freq="min")
    bars = pd.DataFrame(
        {
            "timestamp": index.tz_localize("Europe/Helsinki").tz_convert("UTC"),
            "mid_high": 2.0,
            "mid_low": 1.0,
            "tick_count": 100,
            "maximum_spread": 0.2,
        }
    )
    bars.loc[bars["timestamp"] == center.tz_localize("Europe/Helsinki").tz_convert("UTC"), [
        "mid_high",
        "tick_count",
        "maximum_spread",
    ]] = [9.0, 300, 0.5]
    bars_path = tmp_path / "bars.csv"
    bars.to_csv(bars_path, index=False)
    ticks_path = tmp_path / "ticks.csv"
    ticks_path.write_text("unchanged\n", encoding="utf-8")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "timezone": {},
                "quality": {
                    "warnings": [
                        "Source timezone is inferred rather than confirmed by broker/feed documentation"
                    ]
                },
                "research_readiness": {},
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.md"
    bars_before = bars_path.stat()
    ticks_before = ticks_path.stat()

    result = run(
        minute_bars_path=bars_path,
        canonical_ticks_path=ticks_path,
        metadata_path=metadata_path,
        report_path=report_path,
    )

    assert result["normalized_datasets_unchanged"] is True
    assert bars_path.stat().st_mtime_ns == bars_before.st_mtime_ns
    assert bars_path.stat().st_size == bars_before.st_size
    assert ticks_path.stat().st_mtime_ns == ticks_before.st_mtime_ns
    assert ticks_path.stat().st_size == ticks_before.st_size
    assert report_path.exists()
