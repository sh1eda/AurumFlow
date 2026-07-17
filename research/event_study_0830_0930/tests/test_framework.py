"""Synthetic-only tests for the isolated event-study framework.

These six tests validate mechanics, causal boundaries and output contracts. They
do not use historical XAUUSD observations and do not validate a trading edge.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from research.event_study_0830_0930.config import StudyConfig
from research.event_study_0830_0930.cli import run
from research.event_study_0830_0930.features import (
    build_five_minute_heatmap_data,
    build_session_features,
)
from research.event_study_0830_0930.io import (
    DataRequirementError,
    classify_event_days,
    load_calendar,
    load_prices,
)
from research.event_study_0830_0930.strategies import simulate_orders
from research.event_study_0830_0930.structures import confirmed_swings, find_fvgs


def _write_prices(path, timestamps: pd.DatetimeIndex, base: float = 2000.0) -> None:
    rows = []
    price = base
    for position, timestamp in enumerate(timestamps):
        change = 0.02 if position % 3 else -0.01
        close = price + change
        rows.append(
            {
                "timestamp": timestamp.isoformat(),
                "open": price,
                "high": max(price, close) + 0.03,
                "low": min(price, close) - 0.03,
                "close": close,
                "spread": 0.0,
            }
        )
        price = close
    pd.DataFrame(rows).to_csv(path, index=False)


def test_rejects_m15_instead_of_upsampling(tmp_path) -> None:
    path = tmp_path / "m15.csv"
    _write_prices(path, pd.date_range("2025-01-02 12:00", periods=4, freq="15min", tz="UTC"))
    with pytest.raises(DataRequirementError, match="one-minute or finer"):
        load_prices(path)


def test_new_york_dst_conversion_uses_iana_rules(tmp_path) -> None:
    path = tmp_path / "dst.csv"
    timestamps = pd.DatetimeIndex(
        [
            "2024-03-08 13:30:00+00:00",
            "2024-03-08 13:31:00+00:00",
            "2024-03-11 12:30:00+00:00",
            "2024-03-11 12:31:00+00:00",
        ]
    )
    _write_prices(path, timestamps)
    loaded = load_prices(path)
    assert loaded.index[0].strftime("%H:%M %z") == "08:30 -0500"
    assert loaded.index[2].strftime("%H:%M %z") == "08:30 -0400"


def test_event_classes_features_and_heatmap(tmp_path) -> None:
    price_path = tmp_path / "prices.csv"
    all_times = pd.date_range("2025-01-02 07:30", "2025-01-02 10:29", freq="1min", tz="America/New_York").append(
        pd.date_range("2025-01-03 07:30", "2025-01-03 10:29", freq="1min", tz="America/New_York")
    )
    _write_prices(price_path, all_times)
    calendar_path = tmp_path / "calendar.csv"
    pd.DataFrame(
        [
            {
                "release_timestamp": "2025-01-02 08:30:00-05:00",
                "event_name": "Employment Situation",
                "importance": "major",
                "category": "labor",
            },
            {
                "release_timestamp": "2025-01-02 10:00:00-05:00",
                "event_name": "ISM Manufacturing",
                "importance": "major",
                "category": "growth",
            },
        ]
    ).to_csv(calendar_path, index=False)
    prices = load_prices(price_path)
    calendar = load_calendar(calendar_path)
    days = classify_event_days(prices["session_date"], calendar)
    assert days.loc[date(2025, 1, 2), "event_class"] == "A_major_0830"
    assert bool(days.loc[date(2025, 1, 2), "important_1000_release"])
    assert days.loc[date(2025, 1, 3), "event_class"] == "C_no_meaningful_0830"
    features = build_session_features(prices, days)
    assert int(features.loc[date(2025, 1, 2), "impulse_0830_0835_bar_count"]) == 5
    assert int(features.loc[date(2025, 1, 2), "reaction_0930_0950_bar_count"]) == 20
    assert bool(features.loc[date(2025, 1, 2), "core_windows_complete"])
    heatmap = build_five_minute_heatmap_data(prices, days)
    assert heatmap["bucket_et"].nunique() == 30
    assert set(heatmap["event_class"]) == {"A_major_0830", "C_no_meaningful_0830"}


def test_fvg_is_known_on_third_candle_and_pivot_after_right_confirmation() -> None:
    index = pd.date_range("2025-01-02 09:00", periods=7, freq="1min", tz="America/New_York")
    bars = pd.DataFrame(
        {
            "open": [10.0, 10.2, 10.8, 10.9, 10.7, 10.8, 10.6],
            "high": [10.2, 10.7, 11.0, 11.2, 10.9, 11.0, 10.8],
            "low": [9.9, 10.1, 10.5, 10.8, 10.5, 10.6, 10.4],
            "close": [10.1, 10.6, 10.9, 11.0, 10.6, 10.7, 10.5],
        },
        index=index,
    )
    fvgs = find_fvgs(bars)
    bullish = fvgs[fvgs["direction"].eq(1)].iloc[0]
    assert bullish["created_at"] == index[2]
    swings = confirmed_swings(bars, width=1)
    swing_high = swings[swings["swing_type"].eq("high")].iloc[0]
    assert swing_high["confirmation_time"] > swing_high["pivot_time"]


def test_same_bar_stop_wins_and_zero_spread_falls_back_to_assumption(tmp_path) -> None:
    price_path = tmp_path / "execution.csv"
    timestamps = pd.date_range("2025-01-02 09:31", periods=3, freq="1min", tz="America/New_York")
    frame = pd.DataFrame(
        [
            {"timestamp": timestamps[0].isoformat(), "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "spread": 0.0},
            {"timestamp": timestamps[1].isoformat(), "open": 100.0, "high": 102.5, "low": 98.5, "close": 101.0, "spread": 0.0},
            {"timestamp": timestamps[2].isoformat(), "open": 101.0, "high": 101.2, "low": 100.8, "close": 101.0, "spread": 0.0},
        ]
    )
    frame.to_csv(price_path, index=False)
    prices = load_prices(price_path)
    orders = pd.DataFrame(
        [
            {
                "order_id": "one",
                "session_date": date(2025, 1, 2),
                "family": "test",
                "structure_scale": "1m",
                "geometry": "market_after_confirmed_mss",
                "direction": 1,
                "created_at": pd.Timestamp("2025-01-02 09:30", tz="America/New_York"),
                "entry_price": None,
                "stop_price": 99.0,
                "opposing_level": 102.0,
                "expiry": pd.Timestamp("2025-01-02 09:34", tz="America/New_York"),
                "event_class": "C_no_meaningful_0830",
                "news_category": "",
                "important_1000_release": False,
                "impulse_size_bucket": "normal",
                "higher_timeframe_bias_alignment": True,
                "directional_relationship_0830_0930": "agreement",
            }
        ]
    )
    outcome = simulate_orders(
        prices,
        orders,
        assumed_spread_price=0.20,
        assumed_slippage_price_per_side=0.05,
        close_before_important_1000=False,
    ).iloc[0]
    assert outcome["exit_reason"] == "stop"
    assert outcome["gross_r"] == pytest.approx(-1.0)
    assert outcome["observed_or_assumed_spread_price"] == pytest.approx(0.20)
    assert outcome["net_r"] == pytest.approx(-1.30)


def test_end_to_end_event_study_writes_registered_outputs(tmp_path) -> None:
    price_path = tmp_path / "prices.csv"
    timestamps = pd.date_range(
        "2025-04-01 03:00", "2025-04-01 10:29", freq="1min", tz="America/New_York"
    )
    _write_prices(price_path, timestamps)
    calendar_path = tmp_path / "calendar.csv"
    pd.DataFrame(
        [
            {
                "release_timestamp": "2025-04-01 08:30:00-04:00",
                "event_name": "Example release",
                "importance": "major",
                "category": "test",
            }
        ]
    ).to_csv(calendar_path, index=False)
    output = tmp_path / "output"
    args = type(
        "Args",
        (),
        {
            "prices": str(price_path),
            "calendar": str(calendar_path),
            "output": str(output),
            "source_timezone": None,
            "calendar_timezone": "America/New_York",
            "run_strategies": True,
            "bootstrap_iterations": 20,
        },
    )()
    run(args)
    expected = {
        "session_features.csv",
        "heatmap_5m.csv",
        "event_test_panel.csv",
        "hypothesis_test_results.csv",
        "heatmap_absolute_movement.svg",
        "heatmap_directional_movement.svg",
        "data_quality_report.md",
        "run_metadata.json",
        "event_study_report.md",
        "candidate_orders.csv",
        "trade_outcomes.csv",
        "strategy_performance.csv",
        "bootstrap_confidence_intervals.csv",
    }
    assert expected.issubset({item.name for item in output.iterdir()})
