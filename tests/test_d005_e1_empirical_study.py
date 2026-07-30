from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from research.context_engine.bars import closed_bars_asof, normalize_bars
from research.context_engine.config import (
    ContextEngineConfig,
    DisplacementVariant,
    local_bounds,
)
from research.context_engine.features import (
    detect_liquidity_sweeps,
    detect_displacements,
    detect_fvgs,
    premarket_levels,
    true_range_and_prior_atr,
)
from research.d005_e1_context_engine_empirical.analysis import (
    fvg_event_statistics,
    flatten_transitions,
    gate_attribution,
    order_block_event_statistics,
)
from research.d005_e1_context_engine_empirical.config import (
    EmpiricalStudyConfig,
)
from research.d005_e1_context_engine_empirical.outcomes import (
    _ExtremumTree,
    build_forward_outcomes,
)
from research.d005_e1_context_engine_empirical.pmh import (
    build_pmh_pml_inventory,
)
from research.d005_e1_context_engine_empirical.pipeline import (
    StudyAccumulator,
    _chronological_chunks,
    _opposing_levels_for_anchors,
    _slice_timeframes,
)
from research.d005_e1_context_engine_empirical.schedule import (
    build_data_quality_periods,
    event_schedule_from_inventory,
    fixed_observation_schedule,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _bars(
    index: pd.DatetimeIndex,
    closes: np.ndarray | list[float],
    *,
    timeframe: str = "1min",
) -> pd.DataFrame:
    close = np.asarray(closes, dtype=float)
    if not len(close):
        return normalize_bars(
            pd.DataFrame(
                columns=["open", "high", "low", "close"],
                index=index,
                dtype=float,
            ),
            timeframe,
        )
    opening = np.r_[close[0], close[:-1]]
    high = np.maximum(opening, close) + 0.2
    low = np.minimum(opening, close) - 0.2
    return normalize_bars(
        pd.DataFrame(
            {
                "open": opening,
                "high": high,
                "low": low,
                "close": close,
            },
            index=index,
        ),
        timeframe,
    )


def test_e1_spec_and_frozen_research_boundary() -> None:
    spec = (
        REPOSITORY_ROOT
        / "docs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_SPEC.md"
    )
    assert spec.is_file()
    config = EmpiricalStudyConfig()
    config.validate()
    assert config.fixed_clocks == ("08:30", "09:00", "10:00", "12:00")
    assert [item.name for item in config.mapping_variants] == [
        "weekly_4h_1h",
        "daily_1h_15m",
        "4h_15m_5m",
        "1h_5m",
        "1h_5m_optional_1m",
    ]
    assert not config.production_entry_authorization
    assert not config.index_timing_transfer
    assert config.event_schedule_max_per_day_mapping == 12
    assert config.snapshot()["clock_semantics"] == "observation_only"


def test_mapping_slice_uses_exact_recorded_warmup_and_no_future() -> None:
    index = pd.date_range(
        "2025-02-20",
        "2025-03-12",
        freq="1h",
        tz="UTC",
    )
    bars = _bars(index, np.linspace(100.0, 120.0, len(index)), timeframe="1H")
    evaluation = pd.Timestamp("2025-03-10 12:00", tz="UTC")
    sliced = _slice_timeframes(
        {"1H": bars},
        evaluation_at=evaluation,
        warmup_days=8,
    )["1H"]
    assert sliced.index.min() == evaluation - pd.Timedelta(days=8)
    assert sliced.index.max() == evaluation
    assert pd.to_datetime(sliced["available_at"], utc=True).max() > evaluation
    # The engine's closed-bar filter, not this inexpensive index slice,
    # excludes the bar that opens at the evaluation timestamp.
    causal = closed_bars_asof(sliced, evaluation)
    assert pd.to_datetime(causal["available_at"], utc=True).max() <= evaluation


def test_fixed_schedule_respects_new_york_dst_and_closed_bars() -> None:
    local_evaluations = [
        pd.Timestamp("2025-03-07 08:30", tz="America/New_York"),
        pd.Timestamp("2025-03-10 08:30", tz="America/New_York"),
    ]
    bar_opens = pd.DatetimeIndex(
        [stamp.tz_convert("UTC") - pd.Timedelta(minutes=1) for stamp in local_evaluations]
    )
    one_minute = _bars(bar_opens, [100.0, 101.0])
    config = replace(
        EmpiricalStudyConfig(),
        start_date=date(2025, 3, 7),
        end_date=date(2025, 3, 10),
        fixed_clocks=("08:30",),
    )
    schedule, excluded = fixed_observation_schedule(one_minute, config)
    assert excluded.empty
    assert schedule["evaluation_at"].dt.hour.tolist() == [13, 12]
    assert schedule["session_date"].tolist() == ["2025-03-07", "2025-03-10"]


def test_vectorized_data_quality_preserves_date_gap_metrics() -> None:
    index = pd.DatetimeIndex(
        [
            "2025-03-10 12:00:00+00:00",
            "2025-03-10 12:01:00+00:00",
            "2025-03-10 12:04:00+00:00",
        ]
    )
    bars = _bars(index, [100.0, 100.1, 100.2])
    config = replace(
        EmpiricalStudyConfig(),
        start_date=date(2025, 3, 10),
        end_date=date(2025, 3, 10),
    )
    quality = build_data_quality_periods(bars, config).iloc[0]
    assert quality["observed_one_minute_rows"] == 3
    assert quality["maximum_intraday_gap_minutes"] == 3.0
    assert quality["premarket_observed_minutes"] == 3


def test_pmh_date_slicing_matches_full_frame_causal_evidence() -> None:
    session_date = date(2025, 3, 10)
    left, _ = local_bounds(session_date, "00:00", "00:00")
    _, observation_end = local_bounds(session_date, "08:30", "09:00")
    current = pd.date_range(
        left,
        observation_end - pd.Timedelta(minutes=1),
        freq="1min",
    )
    historical = pd.date_range(
        "2025-03-07 05:00",
        periods=60,
        freq="1min",
        tz="UTC",
    )
    index = historical.append(current)
    close = 100 + np.sin(np.arange(len(index)) / 17.0)
    bars = _bars(index, close)
    d005 = ContextEngineConfig()
    levels, _ = premarket_levels(
        bars,
        session_date=session_date,
        config=d005.premarket,
    )
    full_sweeps = detect_liquidity_sweeps(
        levels,
        bars,
        timeframe="1min",
        evaluation_at=observation_end,
        penetration=d005.premarket.sweep_penetration,
        require_reclaim=d005.premarket.require_body_close_reclaim,
    )
    expected_sweeps = {
        str(item.parameters["level_event_id"]): item.available_at
        for item in full_sweeps
    }
    config = replace(
        EmpiricalStudyConfig(),
        start_date=session_date,
        end_date=session_date,
    )
    inventory = build_pmh_pml_inventory(
        bars,
        study_config=config,
        d005_config=d005,
    )
    assert inventory["taxonomy"].tolist() == [
        item.taxonomy for item in levels
    ]
    assert inventory["level"].tolist() == [item.level for item in levels]
    for row in inventory.to_dict("records"):
        assert row["swept"] == (
            row["level_event_id"] in expected_sweeps
        )
        if row["swept"]:
            assert row["sweep_at"] == expected_sweeps[row["level_event_id"]]


def test_event_schedule_merges_triggers_and_deduplicates_timestamps() -> None:
    stamp = pd.Timestamp("2025-03-10 13:00", tz="UTC")
    event_records = [
        {
            "event_type": "market_structure_shift",
            "available_at": stamp,
        },
        {
            "event_type": "displacement",
            "available_at": stamp,
        },
    ]
    transition_records = [
        {
            "from_state": "candidate_poi",
            "to_state": "reaction_confirmed",
            "occurred_at": stamp,
        }
    ]
    empty_index = pd.DatetimeIndex([], tz="UTC")
    timeframes = {
        "1H": _bars(empty_index, []),
        "5min": _bars(empty_index, []),
    }
    config = replace(
        EmpiricalStudyConfig(),
        start_date=date(2025, 3, 10),
        end_date=date(2025, 3, 10),
    )
    variant = config.mapping_variant("1h_5m")
    schedule = event_schedule_from_inventory(
        variant=variant,
        event_records=event_records,
        transition_records=transition_records,
        timeframes=timeframes,
        d005_config=ContextEngineConfig(primary_mapping="1h_5m_1m"),
        study_config=config,
    )
    assert len(schedule) == 1
    assert set(schedule.iloc[0]["trigger_types"]) == {
        "mss_confirmation",
        "displacement_confirmation",
        "reaction_confirmation",
    }
    assert schedule.iloc[0]["uncapped_date_trigger_count"] == 1
    assert schedule.iloc[0]["omitted_date_trigger_count"] == 0


def test_gate_attribution_is_nonexclusive_and_timeout_is_explicit() -> None:
    candidate_at = pd.Timestamp("2025-03-10 12:00", tz="UTC")
    snapshots = pd.DataFrame(
        [
            {
                "snapshot_id": "s1",
                "evaluation_at": candidate_at + pd.Timedelta(minutes=61),
                "session_date": "2025-03-10",
                "mode": "fixed_clock",
                "observation_clock": "08:30",
                "mapping_variant": "1h_5m",
                "state": "invalidated",
                "direction": 0,
                "parent_direction": 0,
                "no_trade_reasons": [
                    "parent_child_direction_conflict",
                    "body_close_mss_absent",
                ],
                "transitions": [
                    {
                        "from_state": "provisional_context",
                        "to_state": "candidate_poi",
                        "occurred_at": candidate_at,
                        "evidence_ids": ["poi"],
                    }
                ],
                "reaction_minutes": 5,
                "confirmation_timeout_bars": 12,
                "balanced_ranging": False,
            }
        ]
    )
    attribution, overlap = gate_attribution(
        snapshots,
        config=EmpiricalStudyConfig(),
    )
    assert set(attribution["gate"]) == {
        "parent_child_conflict",
        "mss_failure",
        "missing_reaction",
        "candidate_timeout",
        "pmh_pml_prerequisite_failure",
    }
    assert len(overlap) == 1


def test_flatten_transitions_adds_observational_timeout() -> None:
    candidate_at = pd.Timestamp("2025-03-10 12:00", tz="UTC")
    snapshot = {
        "snapshot_id": "s1",
        "evaluation_at": candidate_at + pd.Timedelta(minutes=60),
        "session_date": "2025-03-10",
        "timezone": "America/New_York",
        "mode": "event_driven",
        "mapping_variant": "1h_5m",
        "state": "invalidated",
        "direction": 0,
        "parent_direction": 1,
        "no_trade_reasons": ["body_close_mss_absent"],
        "reaction_minutes": 5,
        "confirmation_timeout_bars": 12,
        "transitions": [
            {
                "from_state": "neutral",
                "to_state": "provisional_context",
                "occurred_at": candidate_at - pd.Timedelta(minutes=5),
                "reason": "parent_context",
                "evidence_ids": ["parent"],
            },
            {
                "from_state": "provisional_context",
                "to_state": "candidate_poi",
                "occurred_at": candidate_at,
                "reason": "poi",
                "evidence_ids": ["poi"],
            },
            {
                "from_state": "candidate_poi",
                "to_state": "invalidated",
                "occurred_at": candidate_at + pd.Timedelta(minutes=60),
                "reason": "confirmation_absent",
                "evidence_ids": ["poi"],
            },
        ],
    }
    transitions = flatten_transitions(pd.DataFrame([snapshot]))
    timeout = transitions[transitions["to_state"].eq("timeout")]
    assert len(timeout) == 1
    assert timeout.iloc[0]["elapsed_minutes_from_prior_stage"] == 60.0
    assert timeout.iloc[0]["transition_kind"] == "derived_timeout_observation"


def test_cross_chunk_event_snapshot_deduplication_is_chronological() -> None:
    accumulator = StudyAccumulator(EmpiricalStudyConfig())
    base = {
        "mode": "event_driven",
        "mapping_variant": "1h_5m_optional_1m",
    }
    accumulator.snapshots = [
        {
            **base,
            "evaluation_at": pd.Timestamp("2025-03-10 12:05", tz="UTC"),
            "snapshot_signature": "same",
        },
        {
            **base,
            "evaluation_at": pd.Timestamp("2025-03-10 12:00", tz="UTC"),
            "snapshot_signature": "same",
        },
        {
            **base,
            "evaluation_at": pd.Timestamp("2025-03-10 12:10", tz="UTC"),
            "snapshot_signature": "changed",
        },
    ]
    frame = accumulator.snapshot_frame()
    assert frame["snapshot_signature"].tolist() == ["same", "changed"]
    assert frame["evaluation_at"].tolist() == [
        pd.Timestamp("2025-03-10 12:00", tz="UTC"),
        pd.Timestamp("2025-03-10 12:10", tz="UTC"),
    ]


def test_optional_event_chunks_preserve_all_rows_in_order() -> None:
    frame = pd.DataFrame(
        {
            "evaluation_at": pd.date_range(
                "2025-03-10",
                periods=13,
                freq="1min",
                tz="UTC",
            )
        }
    )
    chunks = _chronological_chunks(frame, 5)
    combined = pd.concat(chunks, ignore_index=True)
    assert len(chunks) == 5
    pd.testing.assert_frame_equal(combined, frame)


def test_preindexed_ob_overlap_matches_time_and_zone_rules() -> None:
    available = pd.Timestamp("2025-03-10 12:00", tz="UTC")
    events = pd.DataFrame(
        [
            {
                "event_id": "ob-overlap",
                "event_type": "order_block",
                "mapping_variant": "1h_5m",
                "direction": 1,
                "available_at": available,
                "interacted_at": available + pd.Timedelta(minutes=5),
                "confirmed_at": available + pd.Timedelta(minutes=5),
                "invalidated_at": pd.NaT,
                "zone_low": 100.0,
                "zone_high": 102.0,
                "variant": "consecutive_block",
            },
            {
                "event_id": "ob-no-overlap",
                "event_type": "order_block",
                "mapping_variant": "1h_5m",
                "direction": -1,
                "available_at": available,
                "interacted_at": pd.NaT,
                "confirmed_at": pd.NaT,
                "invalidated_at": pd.NaT,
                "zone_low": 110.0,
                "zone_high": 112.0,
                "variant": "last_opposing_candle",
            },
            {
                "event_id": "fvg-near",
                "event_type": "raw_fvg",
                "mapping_variant": "1h_5m",
                "direction": 1,
                "available_at": available + pd.Timedelta(minutes=30),
                "zone_low": 101.0,
                "zone_high": 103.0,
            },
            {
                "event_id": "fvg-far",
                "event_type": "raw_fvg",
                "mapping_variant": "1h_5m",
                "direction": -1,
                "available_at": available + pd.Timedelta(minutes=120),
                "zone_low": 110.0,
                "zone_high": 112.0,
            },
            {
                "event_id": "sweep-prior",
                "event_type": "liquidity_sweep",
                "mapping_variant": "1h_5m",
                "direction": 1,
                "available_at": available - pd.Timedelta(minutes=30),
            },
        ]
    )
    statistics, _ = order_block_event_statistics(
        events,
        reaction_minutes_by_variant={"1h_5m": 5},
    )
    indexed = statistics.set_index("event_id")
    assert bool(indexed.loc["ob-overlap", "overlap_with_fvg"])
    assert bool(
        indexed.loc["ob-overlap", "overlap_with_liquidity_event"]
    )
    assert not bool(indexed.loc["ob-no-overlap", "overlap_with_fvg"])
    assert not bool(
        indexed.loc[
            "ob-no-overlap",
            "overlap_with_liquidity_event",
        ]
    )


def test_preindexed_opposing_liquidity_selects_nearest_known_level() -> None:
    index = pd.date_range(
        "2025-03-10 12:00",
        periods=5,
        freq="1min",
        tz="UTC",
    )
    one_minute = _bars(index, [105.0] * len(index))
    events = pd.DataFrame(
        [
            {
                "event_type": "liquidity_level",
                "mapping_variant": "1h_5m",
                "available_at": pd.Timestamp(
                    "2025-03-10 12:01",
                    tz="UTC",
                ),
                "level": 100.0,
            },
            {
                "event_type": "liquidity_level",
                "mapping_variant": "1h_5m",
                "available_at": pd.Timestamp(
                    "2025-03-10 12:02",
                    tz="UTC",
                ),
                "level": 110.0,
            },
            {
                "event_type": "liquidity_level",
                "mapping_variant": "1h_5m",
                "available_at": pd.Timestamp(
                    "2025-03-10 12:02",
                    tz="UTC",
                ),
                "level": 90.0,
            },
        ]
    )
    anchors = pd.DataFrame(
        [
            {
                "source_id": "long",
                "mapping_variant": "1h_5m",
                "anchor_at": pd.Timestamp(
                    "2025-03-10 12:03",
                    tz="UTC",
                ),
                "direction": 1,
            },
            {
                "source_id": "short",
                "mapping_variant": "1h_5m",
                "anchor_at": pd.Timestamp(
                    "2025-03-10 12:03",
                    tz="UTC",
                ),
                "direction": -1,
            },
        ]
    )
    result = _opposing_levels_for_anchors(
        anchors,
        events,
        one_minute,
    ).set_index("source_id")
    assert result.loc["long", "opposing_liquidity_level"] == 110.0
    assert result.loc["short", "opposing_liquidity_level"] == 100.0


def test_forward_outcomes_keep_neutral_unsigned_and_use_elapsed_time() -> None:
    index = pd.DatetimeIndex(
        [
            "2025-03-10 12:00:00+00:00",
            "2025-03-10 12:01:00+00:00",
            "2025-03-10 12:03:00+00:00",
            "2025-03-10 12:04:00+00:00",
        ]
    )
    one_minute = _bars(index, [100.0, 101.0, 104.0, 102.0])
    anchors = pd.DataFrame(
        [
            {
                "anchor_type": "state_transition",
                "source_id": "neutral",
                "anchor_at": pd.Timestamp("2025-03-10 12:01", tz="UTC"),
                "direction": 0,
                "mapping_variant": "1h_5m",
                "mode": "event_driven",
                "session_date": "2025-03-10",
                "invalidation_level": np.nan,
                "opposing_liquidity_level": np.nan,
            },
            {
                "anchor_type": "state_transition",
                "source_id": "long",
                "anchor_at": pd.Timestamp("2025-03-10 12:01", tz="UTC"),
                "direction": 1,
                "mapping_variant": "1h_5m",
                "mode": "event_driven",
                "session_date": "2025-03-10",
                "invalidation_level": np.nan,
                "opposing_liquidity_level": np.nan,
            },
        ]
    )
    config = replace(
        EmpiricalStudyConfig(),
        forward_minutes=(4,),
    )
    outcomes = build_forward_outcomes(anchors, one_minute, config=config)
    neutral = outcomes[outcomes["source_id"].eq("neutral")].iloc[0]
    directional = outcomes[outcomes["source_id"].eq("long")].iloc[0]
    assert np.isnan(neutral["signed_change"])
    assert np.isnan(neutral["mfe"])
    assert neutral["range_expansion"] > 0
    assert directional["time_to_mfe_minutes"] == 3.0


def test_extremum_tree_matches_numpy_ranges_and_first_thresholds() -> None:
    values = np.array([3.0, 1.0, 7.0, 7.0, 2.0, 9.0, 4.0])
    maximum = _ExtremumTree(values, maximum=True)
    minimum = _ExtremumTree(values, maximum=False)
    for left, right in ((0, 7), (1, 5), (3, 7), (4, 6)):
        expected_max = values[left:right].max()
        expected_min = values[left:right].min()
        max_value, max_position = maximum.query(left, right)
        min_value, min_position = minimum.query(left, right)
        assert max_value == expected_max
        assert min_value == expected_min
        assert max_position == left + int(
            np.argmax(values[left:right])
        )
        assert min_position == left + int(
            np.argmin(values[left:right])
        )
    assert maximum.first_threshold(1, 7, 7.0) == 2
    assert minimum.first_threshold(1, 7, 2.0) == 1
    assert maximum.first_threshold(0, 2, 10.0) == -1


def test_fvg_lifecycle_tree_preserves_strict_violation_semantics() -> None:
    index = pd.date_range(
        "2025-03-10 12:00",
        periods=3,
        freq="1min",
        tz="UTC",
    )
    one_minute = _bars(index, [101.0, 101.0, 99.0])
    events = pd.DataFrame(
        [
            {
                "event_id": "fvg",
                "event_type": "raw_fvg",
                "mapping_variant": "1h_5m",
                "available_at": pd.Timestamp(
                    "2025-03-10 12:01",
                    tz="UTC",
                ),
                "direction": 1,
                "zone_low": 100.0,
                "zone_high": 101.0,
                "parameters": "{}",
                "interacted_at": pd.NaT,
                "confirmed_at": pd.NaT,
                "invalidated_at": pd.NaT,
            }
        ]
    )
    statistics = fvg_event_statistics(
        events,
        one_minute,
        config=EmpiricalStudyConfig(),
    )
    assert statistics.iloc[0]["wick_violation_at"] == pd.Timestamp(
        "2025-03-10 12:03",
        tz="UTC",
    )
    assert statistics.iloc[0]["body_close_violation_at"] == pd.Timestamp(
        "2025-03-10 12:03",
        tz="UTC",
    )


def test_vectorized_fvg_detection_matches_three_bar_reference() -> None:
    rng = np.random.default_rng(50051)
    index = pd.date_range("2025-01-01", periods=100, freq="5min", tz="UTC")
    close = 100 + rng.normal(0, 1.2, len(index)).cumsum()
    bars = _bars(index, close, timeframe="5min")
    evaluation = pd.Timestamp(bars["available_at"].iloc[-1])
    actual = detect_fvgs(
        bars,
        timeframe="5min",
        evaluation_at=evaluation,
        minimum_width=0.05,
    )
    causal = closed_bars_asof(bars, evaluation)
    expected: list[tuple[pd.Timestamp, int, float, float]] = []
    for position in range(2, len(causal)):
        if causal["high"].iloc[position - 2] + 0.05 < causal["low"].iloc[position]:
            expected.append(
                (
                    causal.index[position],
                    1,
                    float(causal["high"].iloc[position - 2]),
                    float(causal["low"].iloc[position]),
                )
            )
        elif causal["low"].iloc[position - 2] - 0.05 > causal["high"].iloc[position]:
            expected.append(
                (
                    causal.index[position],
                    -1,
                    float(causal["high"].iloc[position]),
                    float(causal["low"].iloc[position - 2]),
                )
            )
    observed = [
        (item.created_at, int(item.direction), item.zone_low, item.zone_high)
        for item in actual
    ]
    assert observed == expected


def test_vectorized_displacement_detection_matches_loop_reference() -> None:
    rng = np.random.default_rng(123)
    index = pd.date_range("2025-01-01", periods=120, freq="5min", tz="UTC")
    close = 100 + rng.normal(0, 0.8, len(index)).cumsum()
    bars = _bars(index, close, timeframe="5min")
    variant = DisplacementVariant(
        body_range_minimum=0.35,
        true_range_atr_minimum=0.8,
        immediate_retracement_bars=2,
        maximum_immediate_retracement=0.8,
    )
    evaluation = pd.Timestamp(bars["available_at"].iloc[-1])
    actual = detect_displacements(
        bars,
        timeframe="5min",
        variant=variant,
        evaluation_at=evaluation,
    )
    causal = closed_bars_asof(bars, evaluation)
    measures = true_range_and_prior_atr(
        causal,
        lookback=variant.atr_lookback,
        min_periods=variant.atr_min_periods,
    )
    expected: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    for position in range(len(causal)):
        end = position + variant.immediate_retracement_bars
        if end >= len(causal):
            continue
        row = causal.iloc[position]
        body = float(row["close"] - row["open"])
        bar_range = float(row["high"] - row["low"])
        prior_atr = float(measures["prior_atr"].iloc[position])
        true_range = float(measures["true_range"].iloc[position])
        if (
            not np.isfinite(prior_atr)
            or prior_atr <= 0
            or bar_range <= 0
            or body == 0
            or abs(body) / bar_range < variant.body_range_minimum
            or true_range / prior_atr < variant.true_range_atr_minimum
        ):
            continue
        future = causal.iloc[position + 1 : end + 1]
        adverse = (
            max(0.0, float(row["close"] - future["low"].min()))
            if body > 0
            else max(0.0, float(future["high"].max() - row["close"]))
        )
        if adverse / abs(body) > variant.maximum_immediate_retracement:
            continue
        expected.append(
            (
                causal.index[position],
                pd.Timestamp(causal["available_at"].iloc[end]),
                1 if body > 0 else -1,
            )
        )
    observed = [
        (item.created_at, item.available_at, int(item.direction))
        for item in actual
    ]
    assert observed == expected
