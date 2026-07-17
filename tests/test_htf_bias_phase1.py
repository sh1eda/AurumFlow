from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurumflow_research.config import load_config
from aurumflow_research.discovery import ExperimentCatalog, ResearchObjectCatalog
from research.HTF_BIAS.analysis import run_analysis
from research.HTF_BIAS.features import (
    DataQualificationError,
    _daily_bars,
    _expected_open_mask,
    _outcome_window,
    build_phase1_samples,
    confirmed_swings,
    qualify_market_data,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _market_fixture(start: str, end: str) -> pd.DataFrame:
    local = pd.date_range(start, end, freq="1min", inclusive="left", tz="America/New_York")
    utc = local.tz_convert("UTC")
    utc = utc[_expected_open_mask(utc)]
    position = np.arange(len(utc), dtype=float)
    base = 2000.0 + position * 0.001 + np.sin(position / 200.0) * 0.25
    mid_open = base
    mid_close = base + np.sin(position / 17.0) * 0.02
    mid_high = np.maximum(mid_open, mid_close) + 0.05
    mid_low = np.minimum(mid_open, mid_close) - 0.05
    spread = np.full(len(utc), 0.20)
    half = spread / 2.0
    return pd.DataFrame(
        {
            "timestamp": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bid_open": mid_open - half,
            "bid_high": mid_high - half,
            "bid_low": mid_low - half,
            "bid_close": mid_close - half,
            "ask_open": mid_open + half,
            "ask_high": mid_high + half,
            "ask_low": mid_low + half,
            "ask_close": mid_close + half,
            "mid_open": mid_open,
            "mid_high": mid_high,
            "mid_low": mid_low,
            "mid_close": mid_close,
            "tick_count": 10,
            "median_spread": spread,
            "maximum_spread": spread,
            "last_spread": spread,
            "source": "synthetic",
            "symbol": "XAUUSD",
        }
    )


def _calendar_fixture(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date_et": dates,
            "has_0830_release": [position % 2 == 0 for position in range(len(dates))],
            "news_day_class": ["major_news_day" if position % 2 == 0 else "non_news_day_usable_sources_only" for position in range(len(dates))],
            "categories_present": ["[]"] * len(dates),
        }
    )


def _shift_bar(frame: pd.DataFrame, timestamp_utc: str, amount: float) -> None:
    mask = frame["timestamp"].eq(timestamp_utc)
    for column in (
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "mid_open",
        "mid_high",
        "mid_low",
        "mid_close",
    ):
        frame.loc[mask, column] += amount


def test_duplicate_timestamps_fail_closed() -> None:
    frame = _market_fixture("2025-02-03 08:00", "2025-02-03 10:00")
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True).sort_values("timestamp")
    with pytest.raises(DataQualificationError, match="duplicate"):
        qualify_market_data(duplicate)


def test_dst_conversion_uses_new_york_iana_rules() -> None:
    winter = pd.Timestamp("2026-03-06 08:30", tz="America/New_York").tz_convert("UTC")
    summer = pd.Timestamp("2026-03-09 08:30", tz="America/New_York").tz_convert("UTC")
    assert winter.strftime("%H:%M") == "13:30"
    assert summer.strftime("%H:%M") == "12:30"


def test_confirmed_swing_is_unavailable_until_right_side_delay() -> None:
    index = pd.date_range("2025-01-01", periods=5, freq="4h", tz="UTC")
    bars = pd.DataFrame(
        {
            "high": [1.0, 2.0, 5.0, 2.0, 1.0],
            "low": [0.0, 0.0, 1.0, 0.0, 0.0],
            "available_at": index + pd.Timedelta(hours=4),
        },
        index=index,
    )
    swings = confirmed_swings(bars, width=2)
    high = swings[swings["swing_type"].eq("high")].iloc[0]
    assert high["pivot_at"] == index[2]
    assert high["confirmation_at"] == index[4] + pd.Timedelta(hours=4)


def test_monday_range_forms_causally_and_completes_on_tuesday() -> None:
    market = _market_fixture("2025-02-02 18:00", "2025-02-12 13:00")
    spike = pd.Timestamp("2025-02-10 10:00", tz="America/New_York").tz_convert("UTC")
    _shift_bar(market, spike.strftime("%Y-%m-%dT%H:%M:%SZ"), 100.0)
    calendar = _calendar_fixture(["2025-02-10", "2025-02-11"])
    samples = build_phase1_samples(market, calendar).samples.set_index(
        ["session_date", "evaluation_clock"]
    )
    monday = samples.loc[("2025-02-10", "08:30")]
    tuesday = samples.loc[("2025-02-11", "08:30")]
    assert not monday["monday_range_complete"]
    assert tuesday["monday_range_complete"]
    assert tuesday["monday_high"] > monday["monday_high"] + 50
    assert monday["monday_range_available_at"] <= monday["evaluation_timestamp_utc"]


def test_evaluation_bar_is_not_used_by_pre_evaluation_touch_feature() -> None:
    market = _market_fixture("2025-02-02 18:00", "2025-02-05 13:00")
    calendar = _calendar_fixture(["2025-02-04"])
    base = build_phase1_samples(market, calendar).samples
    base_row = base.loc[base["evaluation_clock"].eq("08:30")].iloc[0]
    pdh = float(base_row["prior_day_high"])
    anchor = pd.Timestamp("2025-02-04 08:30", tz="America/New_York").tz_convert("UTC")
    mask = market["timestamp"].eq(anchor.strftime("%Y-%m-%dT%H:%M:%SZ"))
    for column in ("mid_high", "ask_high", "bid_high"):
        market.loc[mask, column] = pdh + 100.0
    sample = build_phase1_samples(market, calendar).samples
    row = sample[sample["evaluation_clock"].eq("08:30")].iloc[0]
    assert row["pdh_touched_before_evaluation"] == base_row["pdh_touched_before_evaluation"]


def test_future_daily_and_weekly_prices_do_not_change_earlier_features() -> None:
    market = _market_fixture("2025-02-02 18:00", "2025-02-22 00:00")
    calendar = _calendar_fixture(["2025-02-18"])
    before = build_phase1_samples(market, calendar).samples.iloc[0]
    changed = market.copy()
    future = pd.to_datetime(changed["timestamp"], utc=True).gt(
        pd.Timestamp("2025-02-18 12:30", tz="UTC")
    )
    for column in (
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
        "mid_open", "mid_high", "mid_low", "mid_close",
    ):
        changed.loc[future, column] += 500.0
    after = build_phase1_samples(changed, calendar).samples.iloc[0]
    causal_columns = [
        "prior_day_high",
        "prior_day_low",
        "prior_week_high",
        "prior_week_low",
        "monday_high",
        "monday_low",
        "daily_structure_w2",
        "h4_structure_w2",
    ]
    pd.testing.assert_series_equal(before[causal_columns], after[causal_columns])


def test_missing_bar_invalidates_horizon_without_imputation() -> None:
    market = _market_fixture("2025-02-03 08:30", "2025-02-03 09:01")
    qualified, _ = qualify_market_data(market)
    evaluation = pd.Timestamp("2025-02-03 08:30", tz="America/New_York").tz_convert("UTC")
    missing_last = qualified.drop(index=evaluation + pd.Timedelta(minutes=29))
    outcome, error = _outcome_window(
        missing_last,
        evaluation_at=evaluation,
        endpoint=evaluation + pd.Timedelta(minutes=30),
        evaluation_price=float(qualified.loc[evaluation, "mid_open"]),
        known_levels={},
        label="30m",
    )
    assert outcome == {}
    assert error == "incomplete_30m_outcome_window"


def test_outcome_horizon_is_half_open_at_boundary() -> None:
    market = _market_fixture("2025-02-03 08:30", "2025-02-03 09:01")
    endpoint = pd.Timestamp("2025-02-03 09:00", tz="America/New_York").tz_convert("UTC")
    _shift_bar(market, endpoint.strftime("%Y-%m-%dT%H:%M:%SZ"), 1000.0)
    qualified, _ = qualify_market_data(market)
    evaluation = pd.Timestamp("2025-02-03 08:30", tz="America/New_York").tz_convert("UTC")
    outcome, error = _outcome_window(
        qualified,
        evaluation_at=evaluation,
        endpoint=endpoint,
        evaluation_price=float(qualified.loc[evaluation, "mid_open"]),
        known_levels={},
        label="30m",
    )
    assert error is None
    assert abs(outcome["forward_return_bps_30m"]) < 10


def test_incomplete_weekday_is_not_an_eligible_prior_day() -> None:
    market = _market_fixture("2025-02-03 00:00", "2025-02-05 00:00")
    timestamps = pd.to_datetime(market["timestamp"], utc=True).dt.tz_convert("America/New_York")
    partial_tuesday = timestamps.dt.date.eq(pd.Timestamp("2025-02-04").date()) & timestamps.dt.hour.ge(12)
    market = market.loc[~partial_tuesday].copy()
    qualified, _ = qualify_market_data(market)
    daily = _daily_bars(qualified)
    assert bool(daily.loc[pd.Timestamp("2025-02-03").date(), "eligible"])
    assert not bool(daily.loc[pd.Timestamp("2025-02-04").date(), "eligible"])


def _analysis_fixture() -> pd.DataFrame:
    records = []
    dates = pd.bdate_range("2025-01-02", periods=16)
    for day_position, date in enumerate(dates):
        for clock_position, clock in enumerate(("08:30", "09:30")):
            base_return = ((day_position + clock_position) % 5 - 2) * 2.0
            row = {
                "session_date": date.date().isoformat(),
                "evaluation_clock": clock,
                "day_of_week": int(date.weekday()),
                "news_0830": bool(day_position % 2),
                "news_day_class": "major_news_day" if day_position % 2 else "non_news_day_usable_sources_only",
                "prior_return_120m_bps": float((day_position % 3) - 1),
                "maximum_spread_prior_30m": 0.3,
                "candidate_a": 1 if day_position % 2 else -1,
                "candidate_b": 1 if day_position % 3 else -1,
                "candidate_c": -1 if day_position % 4 else 1,
                "candidate_d": 1 if day_position % 5 else 0,
                "candidate_a_width3": 1 if day_position % 2 else -1,
                "candidate_b_reversion": -1 if day_position % 3 else 1,
                "candidate_c_away": 1 if day_position % 4 else -1,
                "candidate_d_robust_volatility": 1 if day_position % 5 else 0,
            }
            for horizon in ("30m", "60m", "120m", "session_end_1200"):
                row[f"forward_return_bps_{horizon}"] = base_return
                row[f"absolute_return_bps_{horizon}"] = abs(base_return)
                row[f"direction_{horizon}"] = 1 if base_return > 0.5 else -1 if base_return < -0.5 else 0
                row[f"up_excursion_bps_{horizon}"] = abs(base_return) + 1.0
                row[f"down_excursion_bps_{horizon}"] = abs(base_return) + 0.5
                row[f"range_expansion_bps_{horizon}"] = abs(base_return) + 1.5
                row[f"realized_volatility_bps_{horizon}"] = abs(base_return) + 0.75
                for level in ("pdh", "pdl", "pwh", "pwl", "monday_high", "monday_low"):
                    row[f"reaches_{level}_{horizon}"] = bool(day_position % 2)
                row[f"outcome_coverage_{horizon}"] = 1.0
            records.append(row)
    return pd.DataFrame.from_records(records)


def test_holdout_changes_cannot_change_frozen_development_register() -> None:
    source = _analysis_fixture()
    first = run_analysis(source, bootstrap_resamples=200, seed=123)
    changed = source.copy()
    holdout_dates = sorted(source["session_date"].unique())[-4:]
    mask = changed["session_date"].isin(holdout_dates)
    for horizon in ("30m", "60m", "120m", "session_end_1200"):
        changed.loc[mask, f"forward_return_bps_{horizon}"] *= -100
        changed.loc[mask, f"direction_{horizon}"] *= -1
    second = run_analysis(changed, bootstrap_resamples=200, seed=123)
    assert json.dumps(first.frozen_register, sort_keys=True) == json.dumps(
        second.frozen_register, sort_keys=True
    )


def test_analysis_outputs_are_deterministic_for_fixed_seed() -> None:
    source = _analysis_fixture()
    first = run_analysis(source, bootstrap_resamples=200, seed=321)
    second = run_analysis(source, bootstrap_resamples=200, seed=321)
    assert first.candidate_comparison.to_csv(index=False) == second.candidate_comparison.to_csv(index=False)
    assert first.feature_relationships.to_csv(index=False) == second.feature_relationships.to_csv(index=False)


def test_htf_phase1_manifest_is_discoverable() -> None:
    config = load_config(REPOSITORY_ROOT / "config" / "research.toml")
    objects = ResearchObjectCatalog.discover(config.paths.research_objects)
    experiments = ExperimentCatalog.discover(config.paths.research_objects, objects)
    definition = experiments.get("HTF_BIAS_PHASE1")
    assert definition.research_object == "HTF_BIAS"
    assert experiments.load_entry_point(definition).__module__ == "research.HTF_BIAS.experiment"
