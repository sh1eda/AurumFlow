from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.dukascopy_common import (
    ConfigurationError,
    Manifest,
    Partition,
    expected_closure_rule,
    load_config,
    parse_utc_boundary,
)
from scripts.verify_dukascopy_downloads import classify_partition


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "config" / "dukascopy_data.toml"
CALENDAR_PATH = (
    REPOSITORY_ROOT / "config" / "dukascopy_XAUUSD_holiday_calendar.json"
)


@pytest.fixture(scope="module")
def production_config():
    return load_config(CONFIG_PATH)


def _partition(timestamp: str) -> Partition:
    return Partition(parse_utc_boundary(timestamp))


def _calendar_value() -> dict:
    return json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))


def _load_with_calendar(
    tmp_path: Path,
    calendar: dict | None = None,
    *,
    raw_text: str | None = None,
    configured_end: str = "2026-07-29T00:00:00Z",
):
    calendar_path = tmp_path / "holiday_calendar.json"
    if raw_text is None:
        calendar_path.write_text(
            json.dumps(calendar, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        calendar_path.write_text(raw_text, encoding="utf-8")
    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    config_text = config_text.replace(
        'holiday_calendar_path = '
        '"config/dukascopy_XAUUSD_holiday_calendar.json"',
        f'holiday_calendar_path = "{calendar_path.as_posix()}"',
    )
    config_text = config_text.replace(
        'holiday_calendar_range_end_exclusive = '
        '"2026-07-29T00:00:00Z"',
        f'holiday_calendar_range_end_exclusive = "{configured_end}"',
    )
    config_path = tmp_path / "config" / "dukascopy_data.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(config_text, encoding="utf-8")
    return load_config(config_path)


def test_config_loads_versioned_xauusd_holiday_calendar(
    production_config,
) -> None:
    calendar = production_config.holiday_calendar("XAUUSD")
    assert calendar is not None
    assert calendar.calendar_id == "D002-XAUUSD-2021-2026"
    assert calendar.symbol == "XAUUSD"
    assert len(calendar.event_intervals) == 62
    assert len(calendar.recurring_rules) == 2


def test_explicit_event_interval_is_half_open_at_start_interior_and_end(
    tmp_path: Path,
) -> None:
    calendar = _calendar_value()
    calendar["event_intervals"].append(
        [
            "unit_utc_interval",
            "Synthetic UTC boundary fixture",
            "expected_holiday_closure",
            "2025-02-04T10:00:00Z",
            "2025-02-04T12:00:00Z",
            "high",
            ["dukascopy_general_features"],
        ]
    )
    config = _load_with_calendar(tmp_path, calendar)

    start = expected_closure_rule(
        config, _partition("2025-02-04T10:00:00Z"), symbol="XAUUSD"
    )
    interior = expected_closure_rule(
        config, _partition("2025-02-04T11:00:00Z"), symbol="XAUUSD"
    )
    end = expected_closure_rule(
        config, _partition("2025-02-04T12:00:00Z"), symbol="XAUUSD"
    )

    assert start is not None and start["rule_id"] == "unit_utc_interval"
    assert interior is not None and interior["rule_id"] == "unit_utc_interval"
    assert end is None


def test_holiday_rule_returns_full_versioned_evidence(
    production_config,
) -> None:
    result = expected_closure_rule(
        production_config,
        _partition("2025-04-18T10:00:00Z"),
        symbol="XAUUSD",
    )

    assert result is not None
    assert result["rule_id"] == "good_friday_2025"
    assert result["rule_type"] == "expected_holiday_closure"
    assert result["symbol"] == "XAUUSD"
    assert result["event_label"] == "Good Friday"
    assert result["confidence"] == "high"
    assert result["utc_interval"] == {
        "start_inclusive": "2025-04-17T22:00:00Z",
        "end_exclusive": "2025-04-18T21:00:00Z",
    }
    assert result["source_ids"] == result["evidence_source_ids"]
    assert {item["source_id"] for item in result["sources"]} == set(
        result["source_ids"]
    )


def test_explicit_special_hours_event_is_supported(production_config) -> None:
    result = expected_closure_rule(
        production_config,
        _partition("2025-11-28T20:00:00Z"),
        symbol="XAUUSD",
    )

    assert result is not None
    assert result["rule_id"] == "thanksgiving_friday_2025"
    assert result["rule_type"] == "expected_special_hours_closure"


def test_utc_event_matching_is_independent_of_process_dst_timezone(
    production_config, monkeypatch
) -> None:
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    result = expected_closure_rule(
        production_config,
        _partition("2024-03-29T12:00:00Z"),
        symbol="XAUUSD",
    )

    assert result is not None
    assert result["rule_id"] == "good_friday_2024"
    assert result["calendar_timezone"] == "UTC"
    assert result["utc_interval"]["start_inclusive"] == (
        "2024-03-28T23:00:00Z"
    )


def test_recurring_special_hours_rules_cover_sunday_and_dst_shift(
    production_config,
) -> None:
    sunday = expected_closure_rule(
        production_config,
        _partition("2025-02-02T22:00:00Z"),
        symbol="XAUUSD",
    )
    dst_shift = expected_closure_rule(
        production_config,
        _partition("2025-03-10T21:00:00Z"),
        symbol="XAUUSD",
    )

    assert sunday is not None
    assert sunday["rule_id"] == "xau_sunday_opening_break"
    assert sunday["rule_type"] == "expected_special_hours_closure"
    assert dst_shift is not None
    assert dst_shift["rule_id"] == "xau_us_dst_settlement_shift"


def test_existing_weekly_close_and_maintenance_rules_keep_priority(
    production_config,
) -> None:
    weekly = expected_closure_rule(
        production_config,
        _partition("2025-04-19T12:00:00Z"),
        symbol="XAUUSD",
    )
    maintenance = expected_closure_rule(
        production_config,
        _partition("2025-07-08T21:00:00Z"),
        symbol="XAUUSD",
    )

    assert weekly is not None
    assert weekly["rule_type"] == "symbol_weekly_market_close"
    assert maintenance is not None
    assert maintenance["rule_type"] == "symbol_daily_maintenance"


def test_verifier_classifies_confirmed_empty_holiday_without_manifest_mutation(
    tmp_path: Path,
    production_config,
) -> None:
    partition = _partition("2025-04-18T10:00:00Z")
    manifest_path = tmp_path / "manifest.json"
    manifest = Manifest(
        manifest_path, config=production_config, symbol="XAUUSD"
    )
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
        evidence_kind="confirmed_empty_payload",
        http_status=200,
        response_byte_length=0,
    )
    manifest.save()
    before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    result = classify_partition(
        config=production_config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["classification"] == "expected_market_closure"
    assert result["closure_rule"]["rule_type"] == (
        "expected_holiday_closure"
    )
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value.update(symbol="EURUSD"),
            "symbol",
        ),
        (
            lambda value: value["event_intervals"][0].__setitem__(
                4, value["event_intervals"][0][3]
            ),
            "not increasing",
        ),
        (
            lambda value: value["event_intervals"].append(
                deepcopy(value["event_intervals"][0])
            ),
            "duplicate",
        ),
        (
            lambda value: value["event_intervals"].append(
                [
                    "contradictory_overlap",
                    "Contradictory overlap",
                    "expected_special_hours_closure",
                    value["event_intervals"][0][3],
                    value["event_intervals"][0][4],
                    "high",
                    ["dukascopy_general_features"],
                ]
            ),
            "overlapping",
        ),
        (
            lambda value: value["event_intervals"][0].__setitem__(
                6, ["unknown_source_id"]
            ),
            "unknown sources",
        ),
    ],
)
def test_malformed_calendar_structures_fail_closed(
    tmp_path: Path, mutation, message: str
) -> None:
    calendar = _calendar_value()
    mutation(calendar)
    with pytest.raises(ConfigurationError, match=message):
        _load_with_calendar(tmp_path, calendar)


def test_malformed_calendar_json_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="cannot load"):
        _load_with_calendar(tmp_path, raw_text='{"broken":')


def test_calendar_and_config_range_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigurationError, match="incompatible"):
        _load_with_calendar(
            tmp_path,
            _calendar_value(),
            configured_end="2026-07-28T00:00:00Z",
        )

