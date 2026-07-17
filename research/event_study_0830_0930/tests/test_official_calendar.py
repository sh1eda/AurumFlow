"""Synthetic integrity tests for the official-calendar research layer."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from research.event_study_0830_0930.economic_calendar_adapter import (
    EconomicCalendarError,
    GenericEconomicCalendarAdapter,
    add_surprise_features,
    classify_event_name,
)
from research.event_study_0830_0930.event_cluster_builder import build_event_clusters
from research.event_study_0830_0930.official_calendar_builder import (
    LOCAL_ZONE,
    RAW_EVENT_MAP,
    _classify_days,
    _event_id,
    _make_row,
    _timestamp,
)


def _base_event(event_id: str, name: str, *, direction: float = math.nan) -> dict:
    local = pd.Timestamp("2026-01-08 08:30", tz=LOCAL_ZONE)
    return {
        "event_id": event_id,
        "release_timestamp_utc": local.tz_convert("UTC"),
        "release_timestamp_new_york": local,
        "event_name": name,
        "importance": "major",
        "point_in_time_verified": True,
        "actual": 1.0,
        "consensus": 0.0,
        "previous": math.nan,
        "revised_previous": math.nan,
        "event_type": name,
        "category": "synthetic",
        "unit": "index",
        "source": "synthetic",
        "source_url": "https://example.invalid",
        "release_bundle_key": "synthetic-bundle",
        "expected_gold_direction": direction,
        "raw_surprise": 1.0,
        "standardized_surprise": 1.0,
        "revision_surprise": math.nan,
        "surprise_eligible": True,
    }


def test_official_calendar_dst_conversion_uses_iana_zone() -> None:
    winter = _timestamp(pd.Timestamp("2026-01-15").date(), "08:30")
    summer = _timestamp(pd.Timestamp("2026-07-15").date(), "08:30")
    assert winter.strftime("%z") == "-0500"
    assert summer.strftime("%z") == "-0400"
    assert winter.tz_convert("UTC").strftime("%H:%M") == "13:30"
    assert summer.tz_convert("UTC").strftime("%H:%M") == "12:30"


def test_duplicate_event_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicates.csv"
    pd.DataFrame(
        {
            "event_id": ["same", "same"],
            "release_timestamp_utc": ["2026-01-08T13:30:00Z", "2026-01-09T13:30:00Z"],
            "event_name": ["CPI", "PPI"],
            "source": ["synthetic", "synthetic"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(EconomicCalendarError, match="duplicate event_id"):
        GenericEconomicCalendarAdapter(source_timezone=None).load(path)


def test_event_ids_are_deterministic_and_reference_period_aware() -> None:
    timestamp = pd.Timestamp("2026-01-09T13:30:00Z")
    first = _event_id("Census", "Housing Starts", timestamp, "initial", "September 2025")
    repeated = _event_id("Census", "Housing Starts", timestamp, "initial", "September 2025")
    other_vintage = _event_id("Census", "Housing Starts", timestamp, "initial", "October 2025")
    assert first == repeated
    assert first != other_vintage


def test_missing_consensus_disables_surprise() -> None:
    event = _base_event("event-a", "CPI")
    event["consensus"] = math.nan
    features = add_surprise_features(pd.DataFrame([event]))
    assert not bool(features.iloc[0]["surprise_eligible"])
    assert pd.isna(features.iloc[0]["raw_surprise"])


def test_simultaneous_conflicting_directions_are_not_force_attributed() -> None:
    events = pd.DataFrame(
        [
            _base_event("event-a", "CPI", direction=-1.0),
            _base_event("event-b", "Core CPI", direction=1.0),
        ]
    )
    cluster = build_event_clusters(events).iloc[0]
    assert int(cluster["event_count"]) == 2
    assert bool(cluster["contains_conflicting_surprises"])
    assert cluster["attribution_status"] == "conflicting_cluster"
    assert cluster["dominant_event_candidate"] == ""


def test_schedule_change_preserves_original_timestamp() -> None:
    row = _make_row(
        day=pd.Timestamp("2026-02-13").date(),
        clock="08:30",
        raw_name="Consumer Price Index",
        component=RAW_EVENT_MAP["Consumer Price Index"][0],
        source_url="https://www.bls.gov/news.release/cpi.toc.htm",
        schedule_source_url="https://www.bls.gov/bls/2025-lapse-revised-release-dates.htm",
        source_type="OFFICIAL_PRIMARY",
        bundle_key="test",
        retrieved_at="2026-07-17T00:00:00+00:00",
        reference_period="January 2026",
    )
    assert row["schedule_change_status"] == "rescheduled"
    assert str(row["original_scheduled_timestamp_local"]).startswith("2026-02-11T08:30")
    assert row["release_timestamp_local"].startswith("2026-02-13T08:30")


def test_fomc_events_have_explicit_classification() -> None:
    assert classify_event_name("FOMC Rate Decision") == "Federal Reserve"
    assert classify_event_name("FOMC Minutes") == "Federal Reserve"


def test_non_news_day_label_carries_coverage_limitation() -> None:
    event = _base_event("event-a", "CPI")
    event.update(
        {
            "release_timestamp_local": "2026-01-08T08:30:00-05:00",
            "event_category": "inflation_cpi",
        }
    )
    events = pd.DataFrame([event])
    clusters = build_event_clusters(events)
    days = _classify_days(events, clusters)
    empty = days[days["date_et"].eq("2026-01-09")].iloc[0]
    assert empty["news_day_class"] == "non_news_day_usable_sources_only"
    assert "0945_pmi_excluded" in empty["calendar_completeness_status"]


def test_prior_only_standardization_does_not_use_future_release() -> None:
    rows = []
    for index, actual in enumerate((1.0, 2.0, 4.0, 8.0, 16.0, 10_000.0)):
        row = _base_event(f"event-{index}", "CPI")
        row["release_timestamp_utc"] = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(days=index)
        row["release_timestamp_new_york"] = row["release_timestamp_utc"].tz_convert(LOCAL_ZONE)
        row["actual"] = actual
        row["consensus"] = 0.0
        row["unit"] = "index"
        rows.append(row)
    frame = pd.DataFrame(rows)
    first_pass = add_surprise_features(frame.iloc[:5], minimum_history=3)
    full_pass = add_surprise_features(frame, minimum_history=3)
    assert full_pass.iloc[4]["standardized_surprise"] == pytest.approx(
        first_pass.iloc[4]["standardized_surprise"]
    )
    assert full_pass.iloc[:3]["standardized_surprise"].isna().all()


def test_official_point_in_time_fields_survive_adapter_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "official.csv"
    pd.DataFrame(
        [
            {
                "event_id": "event-a",
                "release_timestamp_utc": "2026-02-13T13:30:00Z",
                "event_name": "CPI",
                "source": "official_release_archive",
                "original_scheduled_timestamp_local": "2026-02-11T08:30:00-05:00",
                "schedule_change_status": "rescheduled",
                "reference_period": "January 2026",
                "value_status": "official_actual_missing",
                "consensus_status": "consensus_missing",
                "timing_verified": True,
            }
        ]
    ).to_csv(path, index=False)
    row = GenericEconomicCalendarAdapter(source_timezone=None).load(path).frame.iloc[0]
    assert row["reference_period"] == "January 2026"
    assert row["schedule_change_status"] == "rescheduled"
    assert row["original_scheduled_timestamp_local"].startswith("2026-02-11")
    assert str(row["timing_verified"]).lower() == "true"
