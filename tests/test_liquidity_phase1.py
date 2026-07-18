from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurumflow_research.config import load_config
from aurumflow_research.discovery import ExperimentCatalog, ResearchObjectCatalog
from research.HTF_BIAS.features import (
    DataQualificationError,
    _daily_bars,
    _expected_open_mask,
    _weekly_bars,
    qualify_market_data,
)
from research.LIQUIDITY.analysis import (
    apply_conditional_baselines,
    chronological_partitions,
    fit_conditional_baselines,
    run_liquidity_analysis,
)
from research.LIQUIDITY.levels import (
    _construct_equal_levels,
    _construct_monday_levels,
    _construct_previous_day_levels,
    _construct_previous_week_levels,
    _reach_window_metrics,
    _transition_records_for_level,
    deduplicate_interaction_events,
    generate_seeded_control_level,
    trading_session_date,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _market_fixture(start: str, end: str, *, spread_value: float = 0.20) -> pd.DataFrame:
    local = pd.date_range(
        start, end, freq="1min", inclusive="left", tz="America/New_York"
    )
    utc = local.tz_convert("UTC")
    utc = utc[_expected_open_mask(utc)]
    position = np.arange(len(utc), dtype=float)
    base = 2000.0 + np.sin(position / 90.0) * 0.75 + position * 0.0002
    mid_open = base
    mid_close = base + np.sin(position / 17.0) * 0.02
    mid_high = np.maximum(mid_open, mid_close) + 0.05
    mid_low = np.minimum(mid_open, mid_close) - 0.05
    spread = np.full(len(utc), spread_value)
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


def _qualified(start: str, end: str) -> pd.DataFrame:
    return qualify_market_data(_market_fixture(start, end))[0]


def _shift_bar(frame: pd.DataFrame, timestamp: pd.Timestamp, amount: float) -> None:
    mask = frame["timestamp"].eq(timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"))
    for column in (
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
        "mid_open", "mid_high", "mid_low", "mid_close",
    ):
        frame.loc[mask, column] += amount


def test_previous_day_levels_wait_for_completed_source_day() -> None:
    frame = _qualified("2025-02-03 00:00", "2025-02-05 00:00")
    daily = _daily_bars(frame)
    levels = pd.DataFrame(_construct_previous_day_levels(frame, daily))
    monday = levels[levels["source_period"].eq("2025-02-03")]
    expected = pd.Timestamp("2025-02-04 00:00", tz="America/New_York").tz_convert("UTC")
    assert len(monday) == 2
    assert monday["available_at"].eq(expected).all()
    assert monday["created_at"].le(monday["available_at"]).all()


def test_incomplete_day_is_excluded_from_previous_day_candidates() -> None:
    raw = _market_fixture("2025-02-03 00:00", "2025-02-05 00:00")
    local = pd.to_datetime(raw["timestamp"], utc=True).dt.tz_convert("America/New_York")
    remove = local.dt.date.eq(pd.Timestamp("2025-02-04").date()) & local.dt.hour.ge(10)
    frame, _ = qualify_market_data(raw.loc[~remove].copy())
    daily = _daily_bars(frame)
    levels = pd.DataFrame(_construct_previous_day_levels(frame, daily))
    assert "2025-02-03" in set(levels["source_period"])
    assert "2025-02-04" not in set(levels["source_period"])


def test_partial_or_holiday_week_is_not_a_primary_previous_week() -> None:
    raw = _market_fixture("2025-02-02 18:00", "2025-02-22 00:00")
    local = pd.to_datetime(raw["timestamp"], utc=True).dt.tz_convert("America/New_York")
    holiday_week = local.dt.date.between(
        pd.Timestamp("2025-02-10").date(), pd.Timestamp("2025-02-14").date()
    )
    remove = holiday_week & local.dt.hour.ge(9) & local.dt.hour.lt(16)
    frame, _ = qualify_market_data(raw.loc[~remove].copy())
    daily = _daily_bars(frame)
    weekly = _weekly_bars(frame)
    levels = pd.DataFrame(_construct_previous_week_levels(frame, daily, weekly))
    assert "2025-02-10" not in set(levels["source_period"])


def test_previous_week_levels_are_available_only_after_source_week_completion() -> None:
    frame = _qualified("2025-02-02 18:00", "2025-02-15 00:00")
    daily = _daily_bars(frame)
    weekly = _weekly_bars(frame)
    levels = pd.DataFrame(_construct_previous_week_levels(frame, daily, weekly))
    first = levels[levels["source_period"].eq("2025-02-03")]
    expected = pd.Timestamp("2025-02-08 00:00", tz="America/New_York").tz_convert("UTC")
    assert len(first) == 2
    assert first["available_at"].eq(expected).all()


def test_forming_monday_versions_never_use_later_extreme_and_completed_is_tuesday_only() -> None:
    raw = _market_fixture("2025-02-09 18:00", "2025-02-12 00:00")
    future_spike = pd.Timestamp("2025-02-10 15:00", tz="America/New_York").tz_convert("UTC")
    _shift_bar(raw, future_spike, 100.0)
    frame, _ = qualify_market_data(raw)
    daily = _daily_bars(frame)
    levels = pd.DataFrame(_construct_monday_levels(frame, daily))
    dynamic = levels[
        levels["family"].eq("monday_dynamic")
        & levels["side"].eq("high")
        & pd.to_datetime(levels["available_at"], utc=True).lt(
            pd.Timestamp("2025-02-10 08:30", tz="America/New_York").tz_convert("UTC")
        )
    ]
    completed = levels[levels["family"].eq("monday_completed")]
    assert dynamic["price"].max() < completed["price"].max() - 50
    assert completed["available_at"].eq(
        pd.Timestamp("2025-02-11 00:00", tz="America/New_York").tz_convert("UTC")
    ).all()


def test_equal_high_cluster_waits_for_second_pivot_confirmation() -> None:
    frame = _qualified("2025-02-03 00:00", "2025-02-06 00:00")
    index = pd.date_range("2025-02-03", periods=12, freq="4h", tz="UTC")
    h4 = pd.DataFrame(
        {
            "high": np.linspace(2000, 2002, len(index)),
            "low": np.linspace(1998, 2000, len(index)),
            "available_at": index + pd.Timedelta(hours=4),
        },
        index=index,
    )
    swings = pd.DataFrame(
        [
            {"pivot_at": index[1], "confirmation_at": index[3] + pd.Timedelta(hours=4), "swing_type": "high", "level": 2001.0, "width": 2},
            {"pivot_at": index[5], "confirmation_at": index[7] + pd.Timedelta(hours=4), "swing_type": "high", "level": 2001.2, "width": 2},
        ]
    )
    levels = pd.DataFrame(_construct_equal_levels(frame, h4, swings))
    assert not levels.empty
    assert levels["available_at"].eq(swings.iloc[1]["confirmation_at"]).all()
    assert levels["created_at"].eq(swings.iloc[1]["pivot_at"]).all()


def _simple_path(prices: list[float], *, spread: float = 0.20) -> pd.DataFrame:
    index = pd.date_range("2025-02-03 13:00", periods=len(prices), freq="1min", tz="UTC")
    mid = np.asarray(prices, dtype=float)
    half = spread / 2.0
    return pd.DataFrame(
        {
            "bid_high": mid + 0.05 - half,
            "bid_low": mid - 0.05 - half,
            "bid_close": mid - half,
            "ask_high": mid + 0.05 + half,
            "ask_low": mid - 0.05 + half,
            "ask_close": mid + half,
            "mid_high": mid + 0.05,
            "mid_low": mid - 0.05,
            "mid_close": mid,
            "median_spread": spread,
        },
        index=index,
    )


def _level(path: pd.DataFrame, *, side: str = "high") -> dict[str, object]:
    return {
        "level_id": "L1",
        "family": "previous_day",
        "side": side,
        "variant": "completed_primary",
        "price": 100.0,
        "available_at": path.index[0],
        "natural_expires_at": path.index[-1] + pd.Timedelta(minutes=2),
        "volatility_scale": 2.0,
    }


def test_bid_ask_touch_exceed_close_and_reclaim_are_bar_close_available() -> None:
    path = _simple_path([99.0, 99.8, 100.4, 100.5, 99.6, 99.4])
    records, _ = _transition_records_for_level(path, _level(path), reclaim_window_minutes=30)
    events = pd.DataFrame(records)
    assert {"touch", "exceed", "close_beyond", "reclaim"}.issubset(set(events["event_type"]))
    assert events["event_at"].eq(events["observed_bar_at"] + pd.Timedelta(minutes=1)).all()
    assert events["event_at"].ge(path.index[0]).all()


def test_consumed_requires_unreclaimed_window_and_terminal_close_beyond() -> None:
    path = _simple_path([99.0] + [100.8] * 35)
    records, consumed = _transition_records_for_level(
        path, _level(path), reclaim_window_minutes=30
    )
    assert pd.notna(consumed)
    assert "consumed" in {record["event_type"] for record in records}
    reclaimed_path = _simple_path([99.0] + [100.8] * 10 + [99.0] + [100.8] * 24)
    _, reclaimed_consumed = _transition_records_for_level(
        reclaimed_path, _level(reclaimed_path), reclaim_window_minutes=30
    )
    assert pd.isna(reclaimed_consumed)


def test_first_and_repeated_touch_episodes_are_separate() -> None:
    path = _simple_path([99.0, 100.0, 99.0, 100.0, 99.0])
    records, _ = _transition_records_for_level(path, _level(path))
    touch = [record for record in records if record["event_type"] == "touch"]
    assert [record["interaction_number"] for record in touch] == [1, 2]


def test_touch_tolerance_sensitivity_changes_borderline_interaction() -> None:
    path = _simple_path([99.75, 99.75, 99.75])
    narrow, _ = _transition_records_for_level(path, _level(path), touch_factor=0.25)
    wide, _ = _transition_records_for_level(path, _level(path), touch_factor=1.50)
    assert "touch" not in {record["event_type"] for record in narrow}
    assert "touch" in {record["event_type"] for record in wide}


def test_level_expiration_stops_future_state_revisions() -> None:
    path = _simple_path([99.0, 99.0, 99.0, 100.5, 100.5])
    level = _level(path)
    level["natural_expires_at"] = path.index[3]
    records, _ = _transition_records_for_level(path, level)
    assert all(record["event_at"] <= path.index[3] for record in records)
    assert "touch" not in {record["event_type"] for record in records}


def test_event_clustering_and_overlap_flags_are_deterministic() -> None:
    base = pd.Timestamp("2025-02-03 13:00", tz="UTC")
    events = pd.DataFrame(
        [
            {"event_id": "a", "level_id": "L1", "family": "previous_day", "side": "high", "event_type": "touch", "event_at": base, "level_price": 100.0, "approach_band": 0.5},
            {"event_id": "b", "level_id": "L2", "family": "previous_day", "side": "high", "event_type": "touch", "event_at": base + pd.Timedelta(minutes=10), "level_price": 100.2, "approach_band": 0.5},
            {"event_id": "c", "level_id": "L3", "family": "previous_day", "side": "high", "event_type": "touch", "event_at": base + pd.Timedelta(minutes=40), "level_price": 100.1, "approach_band": 0.5},
        ]
    )
    kept, dropped = deduplicate_interaction_events(events, cooldown_minutes=30)
    assert kept["event_id"].tolist() == ["a", "c"]
    assert dropped["event_id"].tolist() == ["b"]
    assert kept["overlaps_prior_120m"].tolist() == [False, True]


def test_missing_endpoint_invalidates_reach_without_imputation() -> None:
    frame = _qualified("2025-02-03 08:30", "2025-02-03 09:01")
    start = pd.Timestamp("2025-02-03 08:30", tz="America/New_York").tz_convert("UTC")
    endpoint = start + pd.Timedelta(minutes=30)
    result = _reach_window_metrics(
        frame.drop(index=endpoint - pd.Timedelta(minutes=1)),
        start=start,
        endpoint=endpoint,
        level_price=2100.0,
        evaluation_price=2000.0,
    )
    assert pd.isna(result["reached"])


def test_seeded_control_generation_is_order_independent() -> None:
    expected = generate_seeded_control_level(
        anchor_id="A", level_id="L", evaluation_price=2000, level_price=2010, seed=1729
    )
    assert expected == generate_seeded_control_level(
        anchor_id="A", level_id="L", evaluation_price=2000, level_price=2010, seed=1729
    )
    assert expected < 2000


def test_duplicate_timestamps_still_fail_closed_in_reused_adapter() -> None:
    frame = _market_fixture("2025-02-03 08:00", "2025-02-03 10:00")
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True).sort_values("timestamp")
    with pytest.raises(DataQualificationError, match="duplicate"):
        qualify_market_data(duplicate)


def test_future_prices_cannot_revise_already_available_previous_day_levels() -> None:
    raw = _market_fixture("2025-02-03 00:00", "2025-02-06 00:00")
    frame, _ = qualify_market_data(raw)
    levels = pd.DataFrame(_construct_previous_day_levels(frame, _daily_bars(frame)))
    cutoff = pd.Timestamp("2025-02-05 08:30", tz="America/New_York").tz_convert("UTC")
    before = levels[levels["available_at"].le(cutoff)][
        ["source_period", "side", "price", "available_at"]
    ].reset_index(drop=True)

    changed = raw.copy()
    future = pd.to_datetime(changed["timestamp"], utc=True).gt(cutoff)
    for column in (
        "bid_open", "bid_high", "bid_low", "bid_close",
        "ask_open", "ask_high", "ask_low", "ask_close",
        "mid_open", "mid_high", "mid_low", "mid_close",
    ):
        changed.loc[future, column] += 500.0
    changed_frame, _ = qualify_market_data(changed)
    after_levels = pd.DataFrame(
        _construct_previous_day_levels(changed_frame, _daily_bars(changed_frame))
    )
    after = after_levels[after_levels["available_at"].le(cutoff)][
        ["source_period", "side", "price", "available_at"]
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


def test_new_york_anchor_conversion_handles_dst_transition() -> None:
    winter = pd.Timestamp("2026-03-06 08:30", tz="America/New_York").tz_convert("UTC")
    summer = pd.Timestamp("2026-03-09 08:30", tz="America/New_York").tz_convert("UTC")
    assert winter.strftime("%H:%M") == "13:30"
    assert summer.strftime("%H:%M") == "12:30"


def test_evening_and_sunday_events_map_to_following_trading_session() -> None:
    sunday = pd.Timestamp("2025-02-09 18:30", tz="America/New_York")
    monday_daytime = pd.Timestamp("2025-02-10 08:30", tz="America/New_York")
    monday_evening = pd.Timestamp("2025-02-10 18:30", tz="America/New_York")
    assert trading_session_date(sunday) == pd.Timestamp("2025-02-10").date()
    assert trading_session_date(monday_daytime) == pd.Timestamp("2025-02-10").date()
    assert trading_session_date(monday_evening) == pd.Timestamp("2025-02-11").date()


def _analysis_fixtures() -> tuple[pd.DataFrame, pd.DataFrame]:
    anchors: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    dates = pd.bdate_range("2025-01-02", periods=20)
    for day_position, day in enumerate(dates):
        session_date = day.date().isoformat()
        for clock_position, clock in enumerate(("08:30", "09:30")):
            reached = bool((day_position + clock_position) % 3)
            row: dict[str, object] = {
                "anchor_id": f"{session_date}_{clock}",
                "level_id": f"L{day_position % 4}",
                "session_date": session_date,
                "evaluation_clock": clock,
                "evaluation_timestamp_utc": pd.Timestamp(f"{session_date} 13:30", tz="UTC") + pd.Timedelta(hours=clock_position),
                "family": "previous_day" if day_position % 2 else "swing_4h",
                "side": "high" if day_position % 2 else "low",
                "variant": "completed_primary" if day_position % 2 else "width_2",
                "is_primary": True,
                "active_under_primary_lifecycle": True,
                "active_under_immediate_close_lifecycle": True,
                "active_under_natural_expiry_lifecycle": True,
                "prior_touches": day_position % 2,
                "prior_day_range_normalized_distance": 0.4 + (day_position % 4) * 0.2,
                "rolling_volatility_scale": 2.0 + day_position % 3,
                "level_age_sessions": float(day_position % 8),
                "evaluation_maximum_spread": 0.2 + (day_position % 3) * 0.1,
                "day_of_week": int(day.weekday()),
                "news_0830": bool(day_position % 2),
                "confluence_count": 2 if day_position % 3 == 0 else 1,
            }
            for horizon in ("30m", "60m", "120m", "study_end_1200", "trading_day_end_1700"):
                row[f"reached_{horizon}"] = reached
                row[f"matched_control_reached_{horizon}"] = not reached if day_position % 5 == 0 else reached
                row[f"seeded_control_reached_{horizon}"] = reached if day_position % 4 else not reached
                row[f"time_to_reach_minutes_{horizon}"] = 10.0 if reached else np.nan
                row[f"outcome_coverage_{horizon}"] = 1.0
                row[f"reached_{horizon}_touch_0_5x"] = reached
                row[f"matched_control_reached_{horizon}_touch_0_5x"] = not reached if day_position % 5 == 0 else reached
                row[f"reached_{horizon}_touch_1_5x"] = reached
                row[f"matched_control_reached_{horizon}_touch_1_5x"] = reached
            anchors.append(row)
        event: dict[str, object] = {
            "event_id": f"E{day_position}",
            "level_id": f"L{day_position % 4}",
            "session_date": session_date,
            "family": "previous_day" if day_position % 2 else "swing_4h",
            "side": "high" if day_position % 2 else "low",
            "event_type": "touch",
            "exceedance_threshold": 0.30,
            "is_first_interaction": bool(day_position % 2),
            "overlaps_prior_120m": bool(day_position % 3 == 0),
            "day_of_week": int(day.weekday()),
            "news_0830": bool(day_position % 2),
        }
        for horizon in ("30m", "60m", "120m"):
            value = float((day_position % 5) - 2)
            event[f"side_aligned_return_bps_{horizon}"] = value
            event[f"forward_return_bps_{horizon}"] = value
            event[f"absolute_return_bps_{horizon}"] = abs(value)
            event[f"continuation_depth_{horizon}"] = abs(value) / 10
            event[f"returned_original_side_{horizon}"] = value < 0
            event[f"time_beyond_minutes_{horizon}"] = day_position % 10
            event[f"realized_volatility_bps_{horizon}"] = abs(value) + 1
            event[f"opposing_level_reached_{horizon}"] = bool(day_position % 2)
        events.append(event)
    return pd.DataFrame(anchors), pd.DataFrame(events)


def test_holdout_changes_do_not_refit_conditional_baseline() -> None:
    anchors, events = _analysis_fixtures()
    partitioned, _, _ = chronological_partitions(anchors, events)
    model = fit_conditional_baselines(partitioned[partitioned["partition"].eq("development")])
    changed = partitioned.copy()
    holdout = changed["partition"].eq("holdout")
    changed.loc[holdout, "reached_60m"] = ~changed.loc[holdout, "reached_60m"].astype(bool)
    assert json.dumps(model, sort_keys=True) == json.dumps(
        fit_conditional_baselines(changed[changed["partition"].eq("development")]),
        sort_keys=True,
    )
    first = apply_conditional_baselines(partitioned, model)
    second = apply_conditional_baselines(changed, model)
    pd.testing.assert_series_equal(
        first.loc[holdout, "conditional_baseline_rate_60m"],
        second.loc[holdout, "conditional_baseline_rate_60m"],
    )


def test_analysis_outputs_are_deterministic_and_holdout_is_chronological() -> None:
    anchors, events = _analysis_fixtures()
    first = run_liquidity_analysis(anchors, events, bootstrap_resamples=200, seed=99)
    second = run_liquidity_analysis(anchors, events, bootstrap_resamples=200, seed=99)
    assert first.fixed_anchor_results.to_csv(index=False) == second.fixed_anchor_results.to_csv(index=False)
    assert first.interaction_event_results.to_csv(index=False) == second.interaction_event_results.to_csv(index=False)
    assert first.partition_specification["random_split"] is False
    assert first.partition_specification["development"]["end"] < first.partition_specification["holdout"]["start"]


def test_liquidity_manifest_is_discoverable_and_object_is_not_decided() -> None:
    config = load_config(REPOSITORY_ROOT / "config" / "research.toml")
    objects = ResearchObjectCatalog.discover(config.paths.research_objects)
    experiments = ExperimentCatalog.discover(config.paths.research_objects, objects)
    definition = experiments.get("LIQUIDITY_PHASE1")
    assert definition.research_object == "LIQUIDITY"
    assert experiments.load_entry_point(definition).__module__ == "research.LIQUIDITY.experiment"
    liquidity = objects.get("LIQUIDITY")
    assert liquidity.lifecycle.value == "statistical_evaluation"
    assert liquidity.decision.value == "not_evaluated"
