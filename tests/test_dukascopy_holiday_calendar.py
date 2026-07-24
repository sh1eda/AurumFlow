from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.dukascopy_common import parse_utc_boundary
from scripts.research_dukascopy_holiday_calendar import (
    _load_calendar,
    classify_candidate,
    group_contiguous_timestamps,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = (
    REPOSITORY_ROOT / "config" / "dukascopy_XAUUSD_holiday_calendar.json"
)
RANGE_START = parse_utc_boundary("2021-01-01T00:00:00Z")
RANGE_END = parse_utc_boundary("2026-01-01T00:00:00Z")


@pytest.fixture(scope="module")
def calendar() -> dict:
    return _load_calendar(
        CALENDAR_PATH,
        symbol="XAUUSD",
        expected_start=RANGE_START,
        expected_end=RANGE_END,
    )


def candidate(
    timestamp: str,
    *,
    evidence_kind: str = "confirmed_empty_payload",
    http_status: int | None = 200,
    response_byte_length: int | None = 0,
) -> dict:
    return {
        "partition_timestamp": timestamp,
        "evidence_kind": evidence_kind,
        "http_status": http_status,
        "response_byte_length": response_byte_length,
        "retry_count": 0,
        "proxy_identity_masked": "direct",
        "final_attempt_timestamp": "2026-07-24T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("timestamp", "expected_rule"),
    [
        ("2025-02-02T22:00:00Z", "xau_sunday_opening_break"),
        ("2025-07-06T21:00:00Z", "xau_sunday_opening_break"),
    ],
)
def test_sunday_xau_opening_break_handles_winter_and_summer(
    calendar: dict, timestamp: str, expected_rule: str
) -> None:
    result = classify_candidate(candidate(timestamp), calendar)

    assert result["classification"] == "expected_special_hours_closure"
    assert result["rule_id"] == expected_rule
    assert result["applicable_timezone"] == "America/New_York"


@pytest.mark.parametrize(
    "timestamp",
    [
        "2025-03-10T21:00:00Z",
        "2025-03-28T21:00:00Z",
        "2025-10-27T21:00:00Z",
        "2025-10-31T21:00:00Z",
    ],
)
def test_us_eu_dst_gap_is_special_settlement_hour(
    calendar: dict, timestamp: str
) -> None:
    result = classify_candidate(candidate(timestamp), calendar)

    assert result["classification"] == "expected_special_hours_closure"
    assert result["rule_id"] == "xau_us_dst_settlement_shift"


@pytest.mark.parametrize(
    "timestamp",
    [
        "2025-03-07T22:00:00Z",
        "2025-03-31T21:00:00Z",
        "2025-10-24T21:00:00Z",
        "2025-11-03T22:00:00Z",
    ],
)
def test_dst_boundary_hours_outside_gap_do_not_get_special_classification(
    calendar: dict, timestamp: str
) -> None:
    result = classify_candidate(candidate(timestamp), calendar)

    assert result["classification"] == "unexplained_empty_payload"
    assert result["rule_id"] is None


@pytest.mark.parametrize(
    ("timestamp", "rule_id", "closure_type"),
    [
        (
            "2025-04-18T10:00:00Z",
            "good_friday_2025",
            "expected_holiday_closure",
        ),
        (
            "2025-07-04T19:00:00Z",
            "independence_2025",
            "expected_holiday_closure",
        ),
        (
            "2025-11-28T20:00:00Z",
            "thanksgiving_friday_2025",
            "expected_special_hours_closure",
        ),
        (
            "2025-12-24T20:00:00Z",
            "christmas_eve_2025",
            "expected_special_hours_closure",
        ),
        (
            "2025-12-25T12:00:00Z",
            "christmas_2025",
            "expected_holiday_closure",
        ),
        (
            "2025-12-31T23:00:00Z",
            "new_year_2026",
            "expected_holiday_closure",
        ),
    ],
)
def test_recurring_holiday_and_early_close_patterns(
    calendar: dict, timestamp: str, rule_id: str, closure_type: str
) -> None:
    result = classify_candidate(candidate(timestamp), calendar)

    assert result["classification"] == closure_type
    assert result["rule_id"] == rule_id
    assert result["closed_interval"]["start_inclusive"]
    assert result["closed_interval"]["end_exclusive"]
    assert result["confidence"] in {"high", "medium"}
    assert all(source["publication_date"] for source in result["sources"])


@pytest.mark.parametrize(
    "bad_candidate",
    [
        candidate(
            "2025-04-18T10:00:00Z",
            evidence_kind="http_5xx",
            http_status=503,
            response_byte_length=123,
        ),
        candidate(
            "2025-04-18T10:00:00Z",
            evidence_kind="timeout",
            http_status=None,
            response_byte_length=None,
        ),
        candidate(
            "2025-04-18T10:00:00Z",
            evidence_kind="confirmed_empty_payload",
            http_status=200,
            response_byte_length=1,
        ),
        candidate(
            "2025-04-18T10:00:00Z",
            evidence_kind="malformed_nonempty_payload",
            http_status=200,
            response_byte_length=100,
        ),
    ],
)
def test_calendar_match_never_overrides_bad_or_nonempty_evidence(
    calendar: dict, bad_candidate: dict
) -> None:
    result = classify_candidate(bad_candidate, calendar)

    assert result["classification"] == "unexplained_empty_payload"
    assert result["closure_type"] is None
    assert "evidence is absent" in result["classification_reason"]


def test_empty_open_market_hour_remains_unexplained(calendar: dict) -> None:
    result = classify_candidate(candidate("2025-02-04T12:00:00Z"), calendar)

    assert result["classification"] == "unexplained_empty_payload"
    assert result["sources"] == []


def test_event_intervals_are_half_open(calendar: dict) -> None:
    last_good_friday_hour = classify_candidate(
        candidate("2025-04-18T20:00:00Z"), calendar
    )
    end_boundary = classify_candidate(
        candidate("2025-04-18T21:00:00Z"), calendar
    )

    assert last_good_friday_hour["rule_id"] == "good_friday_2025"
    assert end_boundary["classification"] == "unexplained_empty_payload"


def test_grouping_is_hourly_half_open_and_detects_duplicates() -> None:
    grouped = group_contiguous_timestamps(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T03:00:00Z",
        ]
    )

    assert grouped == [
        {
            "start_inclusive": "2025-01-01T00:00:00Z",
            "end_exclusive": "2025-01-01T02:00:00Z",
            "partition_count": 2,
        },
        {
            "start_inclusive": "2025-01-01T03:00:00Z",
            "end_exclusive": "2025-01-01T04:00:00Z",
            "partition_count": 1,
        },
    ]
    with pytest.raises(ValueError, match="duplicates"):
        group_contiguous_timestamps(
            ["2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"]
        )


def test_machine_calendar_has_auditable_sources_for_every_rule() -> None:
    calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    sources = calendar["sources"]

    assert sources
    for source in sources.values():
        assert source["publisher"]
        assert source["publication_date"]
        assert source["applicable_timezone"]
        assert source["url"].startswith("https://")
    for interval in calendar["event_intervals"]:
        assert interval[6]
        assert set(interval[6]) <= set(sources)
    for rule in calendar["recurring_special_hours_rules"]:
        assert rule["source_ids"]
        assert set(rule["source_ids"]) <= set(sources)
