"""Synthetic-only tests for empirical ingestion; they do not validate a trading edge."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.event_study_0830_0930.data_validation import (
    DataQualityError,
    evaluate_event_windows,
    refuse_on_critical,
    validate_market_data,
)
from research.event_study_0830_0930.economic_calendar_adapter import (
    GenericEconomicCalendarAdapter,
    add_surprise_features,
    classify_event_name,
    write_canonical_calendar,
)
from research.event_study_0830_0930.event_cluster_builder import build_event_clusters
from research.event_study_0830_0930.empirical_cli import main as empirical_main
from research.event_study_0830_0930.execution_cost_model import (
    DEFAULT_COST_SCENARIOS,
    ExecutionCostModel,
    ExecutionQuote,
)
from research.event_study_0830_0930.market_data_adapter import (
    DukascopyMarketDataAdapter,
    GenericMarketDataAdapter,
    MarketDataError,
    MT5MarketDataAdapter,
    tick_to_minute_bars,
    write_canonical_market,
)
from research.event_study_0830_0930.stage1 import run_stage1


def _bar_frame(timestamps: pd.DatetimeIndex, *, spread: float = 0.20) -> pd.DataFrame:
    rows: list[dict] = []
    for offset, timestamp in enumerate(timestamps):
        bid_open = 2000.0 + offset * 0.01
        bid_close = bid_open + 0.01
        rows.append(
            {
                "timestamp": timestamp,
                "bid_open": bid_open,
                "bid_high": bid_close + 0.02,
                "bid_low": bid_open - 0.02,
                "bid_close": bid_close,
                "ask_open": bid_open + spread,
                "ask_high": bid_close + 0.02 + spread,
                "ask_low": bid_open - 0.02 + spread,
                "ask_close": bid_close + spread,
                "last_spread": spread,
                "source": "synthetic",
                "symbol": "XAUUSD",
            }
        )
    return pd.DataFrame(rows)


def _calendar_frame(timestamp: str = "2025-01-02 08:30:00-05:00") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "event-1",
                "release_timestamp_utc": pd.Timestamp(timestamp).tz_convert("UTC"),
                "release_timestamp_new_york": pd.Timestamp(timestamp).tz_convert(
                    "America/New_York"
                ),
                "event_name": "Consumer Price Index",
                "institution": "BLS",
                "country": "US",
                "category": "inflation",
                "importance": "major",
                "actual": 3.2,
                "consensus": 3.1,
                "previous": 3.0,
                "revised_previous": 3.05,
                "unit": "%",
                "release_version": "original",
                "source": "synthetic-calendar",
                "source_url": "https://example.invalid/release",
                "retrieval_timestamp": pd.Timestamp("2025-01-02 08:31:00-05:00").tz_convert(
                    "UTC"
                ),
                "point_in_time_verified": True,
                "notes": "synthetic fixture",
                "event_type": "CPI",
            }
        ]
    )


def test_dst_transition_uses_iana_rules_for_naive_ticks(tmp_path: Path) -> None:
    path = tmp_path / "dst_ticks.csv"
    pd.DataFrame(
        {
            "timestamp": ["2024-03-08 08:30:00", "2024-03-11 08:30:00"],
            "bid": [2000.0, 2001.0],
            "ask": [2000.2, 2001.2],
            "source": ["synthetic", "synthetic"],
            "symbol": ["XAUUSD", "XAUUSD"],
        }
    ).to_csv(path, index=False)
    result = GenericMarketDataAdapter(
        mode="ticks", source_timezone="America/New_York"
    ).load(path)
    assert result.frame.loc[0, "timestamp"].strftime("%H:%M %z") == "13:30 +0000"
    assert result.frame.loc[1, "timestamp"].strftime("%H:%M %z") == "12:30 +0000"


def test_mt5_tick_export_aliases_are_canonicalized(tmp_path: Path) -> None:
    path = tmp_path / "mt5_ticks.tsv"
    pd.DataFrame(
        {
            "<DATE>": ["2025.01.02", "2025.01.02"],
            "<TIME>": ["08:30:00.000", "08:30:00.500"],
            "<BID>": [2000.0, 2000.1],
            "<ASK>": [2000.2, 2000.3],
        }
    ).to_csv(path, index=False, sep="\t")
    result = MT5MarketDataAdapter(
        mode="ticks",
        source_timezone="America/New_York",
        source="synthetic-mt5",
        symbol="XAUUSD",
    ).load(path)
    assert list(result.frame.columns[:3]) == ["timestamp", "bid", "ask"]
    assert result.frame.iloc[0]["source"] == "synthetic-mt5"
    assert result.frame.iloc[0]["timestamp"].strftime("%H:%M %z") == "13:30 +0000"


def test_dukascopy_tick_aliases_are_canonicalized(tmp_path: Path) -> None:
    path = tmp_path / "dukascopy.csv"
    pd.DataFrame(
        {
            "UTC": ["2025-01-02 13:30:00+00:00"],
            "BidPrice": [2000.0],
            "AskPrice": [2000.2],
            "BidVolume": [1.5],
            "AskVolume": [1.2],
        }
    ).to_csv(path, index=False)
    result = DukascopyMarketDataAdapter(
        mode="ticks",
        source_timezone=None,
        source="synthetic-dukascopy",
        symbol="XAUUSD",
    ).load(path)
    assert result.frame.iloc[0]["bid_size"] == pytest.approx(1.5)
    assert result.frame.iloc[0]["ask_size"] == pytest.approx(1.2)


def test_duplicate_timestamps_block_validation() -> None:
    timestamps = pd.DatetimeIndex(["2025-01-02 12:30:00+00:00"] * 2)
    report = validate_market_data(_bar_frame(timestamps))
    assert report["duplicate_count"] == 1
    with pytest.raises(DataQualityError, match="duplicate_timestamp"):
        refuse_on_critical(report)


def test_missing_minutes_are_reported_and_not_filled() -> None:
    timestamps = pd.DatetimeIndex(
        ["2025-01-02 12:30:00+00:00", "2025-01-02 12:32:00+00:00"]
    )
    report = validate_market_data(_bar_frame(timestamps))
    assert report["missing_minute_count"] == 1
    assert report["observed_open_minutes"] == 2
    assert "missing_minute_threshold_exceeded" in report["critical_violations"]


def test_invalid_bid_ask_relationship_blocks_validation() -> None:
    frame = _bar_frame(pd.date_range("2025-01-02 12:30", periods=2, freq="1min", tz="UTC"))
    frame.loc[1, ["ask_open", "ask_high", "ask_low", "ask_close"]] = 1990.0
    report = validate_market_data(frame)
    assert report["bid_above_ask_error_count"] == 1
    assert report["invalid_spread_count"] == 1
    assert report["status"] == "blocked"


def test_simultaneous_releases_form_collision_cluster(tmp_path: Path) -> None:
    path = tmp_path / "calendar.csv"
    pd.DataFrame(
        [
            {
                "release_timestamp": "2025-01-02 08:30:00-05:00",
                "event_name": "Consumer Price Index",
                "importance": "major",
                "actual": "3.2%",
                "consensus": "3.1%",
                "previous": "3.0%",
                "point_in_time_verified": True,
                "source": "synthetic",
            },
            {
                "release_timestamp": "2025-01-02 08:30:00-05:00",
                "event_name": "Core CPI",
                "importance": "major",
                "actual": "3.3%",
                "consensus": "3.2%",
                "previous": "3.2%",
                "point_in_time_verified": True,
                "source": "synthetic",
            },
        ]
    ).to_csv(path, index=False)
    events = GenericEconomicCalendarAdapter(source_timezone=None).load(path).frame
    clusters = build_event_clusters(add_surprise_features(events))
    assert len(clusters) == 1
    assert int(clusters.iloc[0]["event_count"]) == 2
    assert bool(clusters.iloc[0]["exclude_event_specific_analysis"])


def test_revision_is_separate_from_original_surprise() -> None:
    events = add_surprise_features(_calendar_frame(), minimum_history=1)
    assert events.iloc[0]["raw_surprise"] == pytest.approx(0.1)
    assert events.iloc[0]["revision_surprise"] == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Core Consumer Price Index", "Core CPI"),
        ("Consumer Price Index", "CPI"),
        ("Nonfarm Payrolls", "Nonfarm Payrolls"),
        ("Unemployment Rate", "Unemployment Rate"),
        ("Average Hourly Earnings", "Average Hourly Earnings"),
        ("Core Producer Price Index", "Core PPI"),
        ("Producer Price Index", "PPI"),
        ("Core Retail Sales", "Core Retail Sales"),
        ("Retail Sales", "Retail Sales"),
        ("Gross Domestic Product", "GDP"),
        ("Initial Jobless Claims", "Initial Jobless Claims"),
        ("Durable Goods Orders", "Durable Goods"),
        ("Personal Income", "Personal Income"),
        ("Personal Spending", "Personal Spending"),
        ("PCE Price Index", "PCE"),
        ("Core PCE Price Index", "Core PCE"),
        ("ISM Manufacturing PMI", "ISM Manufacturing"),
        ("ISM Services PMI", "ISM Services"),
        ("Consumer Confidence", "Consumer Confidence"),
        ("JOLTS Job Openings", "JOLTS"),
        ("University of Michigan Consumer Sentiment", "University of Michigan"),
        ("FOMC Rate Decision", "Federal Reserve"),
    ],
)
def test_required_release_classifications(name: str, expected: str) -> None:
    assert classify_event_name(name) == expected


def test_unverified_release_is_timing_only() -> None:
    frame = _calendar_frame()
    frame["point_in_time_verified"] = False
    events = add_surprise_features(frame)
    assert not bool(events.iloc[0]["surprise_eligible"])
    assert pd.isna(events.iloc[0]["raw_surprise"])
    assert events.iloc[0]["surprise_exclusion_reason"] == "point_in_time_not_verified"


def test_canonical_calendar_reloads_with_optional_retrieval_timestamp(tmp_path: Path) -> None:
    frame = _calendar_frame()
    frame["retrieval_timestamp"] = pd.NaT
    path = tmp_path / "canonical_calendar.csv"
    write_canonical_calendar(frame, path)
    reloaded = GenericEconomicCalendarAdapter(source_timezone=None).load(path).frame
    assert pd.isna(reloaded.iloc[0]["retrieval_timestamp"])
    assert reloaded.iloc[0]["event_id"] == "event-1"


def test_tick_to_minute_builds_bid_and_ask_independently() -> None:
    ticks = pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(
                [
                    "2025-01-02 13:30:00+00:00",
                    "2025-01-02 13:30:20+00:00",
                    "2025-01-02 13:30:50+00:00",
                    "2025-01-02 13:31:05+00:00",
                ]
            ),
            "bid": [2000.0, 2000.2, 1999.9, 2000.3],
            "ask": [2000.2, 2000.5, 2000.2, 2000.6],
            "source": "synthetic",
            "symbol": "XAUUSD",
        }
    )
    result = tick_to_minute_bars(ticks)
    first = result.frame.iloc[0]
    assert first["bid_open"] == pytest.approx(2000.0)
    assert first["bid_high"] == pytest.approx(2000.2)
    assert first["ask_high"] == pytest.approx(2000.5)
    assert int(first["tick_count"]) == 3
    assert first["maximum_spread"] == pytest.approx(0.3)
    assert result.metadata["forward_fill"] is False


def test_tick_aggregation_refuses_crossed_quote() -> None:
    ticks = pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(["2025-01-02 13:30:00+00:00"]),
            "bid": [2000.3],
            "ask": [2000.2],
            "source": ["synthetic"],
            "symbol": ["XAUUSD"],
        }
    )
    with pytest.raises(MarketDataError, match="crossed quote"):
        tick_to_minute_bars(ticks)


def test_bid_ask_execution_uses_executable_sides() -> None:
    model = ExecutionCostModel(DEFAULT_COST_SCENARIOS["base"])
    quote = ExecutionQuote(bid=2000.0, ask=2000.2)
    long_entry = model.market_price(side="long", action="entry", quote=quote)
    long_exit = model.market_price(side="long", action="exit", quote=quote)
    short_entry = model.market_price(side="short", action="entry", quote=quote)
    short_exit = model.market_price(side="short", action="exit", quote=quote)
    assert long_entry.price == pytest.approx(2000.23)
    assert long_exit.price == pytest.approx(1999.97)
    assert short_entry.price == pytest.approx(1999.97)
    assert short_exit.price == pytest.approx(2000.23)


def test_news_window_spread_spike_cancels_trade() -> None:
    model = ExecutionCostModel(DEFAULT_COST_SCENARIOS["base"])
    decision = model.market_price(
        side="long",
        action="entry",
        quote=ExecutionQuote(bid=2000.0, ask=2000.8, in_news_window=True),
    )
    assert not decision.executable
    assert decision.reason == "spread_exceeds_maximum"


def test_m15_bid_ask_bars_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "m15.csv"
    _bar_frame(pd.date_range("2025-01-02 12:30", periods=3, freq="15min", tz="UTC")).to_csv(
        path, index=False
    )
    with pytest.raises(MarketDataError, match="M15"):
        GenericMarketDataAdapter(mode="bars").load(path)


def test_event_window_status_distinguishes_partial_and_missing() -> None:
    bars = _bar_frame(
        pd.DatetimeIndex(
            ["2025-01-02 13:30:00+00:00", "2025-01-02 13:31:00+00:00"]
        )
    )
    coverage = evaluate_event_windows(bars, ["2025-01-02"])
    impulse = coverage[coverage["window"].eq("impulse_0830_0835")].iloc[0]
    secondary = coverage[coverage["window"].eq("secondary_1000_1030")].iloc[0]
    assert impulse["status"] == "partially_missing"
    assert secondary["status"] == "entirely_missing"


def test_stage1_writes_timing_outputs_only(tmp_path: Path) -> None:
    bars = _bar_frame(
        pd.date_range("2025-01-02 07:30", "2025-01-02 10:29", freq="1min", tz="America/New_York")
    )
    output = run_stage1(bars, add_surprise_features(_calendar_frame()), tmp_path / "stage1")
    assert (output / "stage1_session_windows.csv").exists()
    assert (output / "stage1_clock_effects.csv").exists()
    assert (output / "stage1_summary.md").exists()
    assert (output / "stage1_results.json").exists()
    assert (output / "event_level_features.csv").exists()
    assert (output / "daily_lifecycle_classification.csv").exists()
    assert (output / "stage1_quality_report.json").exists()
    for required in (
        "window_statistics.csv",
        "category_statistics.csv",
        "cluster_statistics.csv",
        "news_vs_nonnews.csv",
        "spread_analysis.csv",
        "sensitivity_analysis.csv",
        "data_exclusions.csv",
    ):
        assert (output / required).exists()
    results = (output / "stage1_results.json").read_text(encoding="utf-8")
    assert '"actual_consensus_revision_fields_used": false' in results
    assert '"surprise_analysis_enabled": false' in results
    metadata = (output / "stage1_metadata.json").read_text(encoding="utf-8")
    assert '"discretionary_entry_concepts_tested": false' in metadata
    assert '"execution_performance_reported": false' in metadata


def test_empirical_cli_runs_stage1_from_canonical_files(tmp_path: Path) -> None:
    market_path = tmp_path / "market.csv"
    calendar_path = tmp_path / "calendar.csv"
    output = tmp_path / "output"
    write_canonical_market(
        _bar_frame(
            pd.date_range(
                "2025-01-02 07:30",
                "2025-01-02 10:29",
                freq="1min",
                tz="America/New_York",
            )
        ),
        market_path,
    )
    write_canonical_calendar(add_surprise_features(_calendar_frame()), calendar_path)
    exit_code = empirical_main(
        [
            "stage1",
            "--market",
            str(market_path),
            "--calendar",
            str(calendar_path),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert (output / "data_quality_report.json").exists()
    assert (output / "stage1_clock_summary.csv").exists()
