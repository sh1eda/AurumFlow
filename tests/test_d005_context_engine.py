from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.context_engine.bars import (
    BarValidationError,
    build_timeframes,
    closed_bars_asof,
    normalize_bars,
)
from research.context_engine.config import (
    ContextEngineConfig,
    DisplacementVariant,
    MSSVariant,
    PremarketConfig,
    local_bounds,
)
from research.context_engine.engine import ContextEngine, EvaluationResult
from research.context_engine.features import (
    apply_zone_interactions,
    classify_balanced,
    confirmed_swings,
    detect_displacements,
    detect_liquidity_sweeps,
    detect_fvgs,
    detect_mss,
    detect_order_blocks,
    equal_liquidity_levels,
    premarket_levels,
    qualify_fvgs,
    qualify_order_blocks,
    structure_direction,
    trapped_between_opposing_arrays,
)
from research.context_engine.models import (
    ContextSnapshot,
    ContextState,
    Direction,
    EvidenceEvent,
    OutcomeLabel,
    StateTransition,
    validate_transition,
)
from research.context_engine.reporting import persist_research_results


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _bars(
    prices: list[float],
    *,
    start: str = "2025-01-06 00:00",
    frequency: str = "1h",
    timeframe: str = "1H",
    high_padding: float = 0.20,
    low_padding: float = 0.20,
) -> pd.DataFrame:
    index = pd.date_range(start, periods=len(prices), freq=frequency, tz="UTC")
    close = np.asarray(prices, dtype=float)
    opening = np.r_[close[0], close[:-1]]
    frame = pd.DataFrame(
        {
            "open": opening,
            "high": np.maximum(opening, close) + high_padding,
            "low": np.minimum(opening, close) - low_padding,
            "close": close,
        },
        index=index,
    )
    return normalize_bars(frame, timeframe)


def _oscillating_trend(
    *,
    bullish: bool,
    periods: int,
    start: str,
    frequency: str,
    timeframe: str,
) -> pd.DataFrame:
    if bullish:
        prices = [100.0 + 1.2 * position + (2.0 if position % 2 else 0.0) for position in range(periods)]
    else:
        prices = [130.0 - 1.2 * position - (2.0 if position % 2 else 0.0) for position in range(periods)]
    index = pd.date_range(start, periods=periods, freq=frequency, tz="UTC")
    close = np.asarray(prices, dtype=float)
    # Isolate each synthetic candle so alternating closes form unambiguous
    # confirmed pivots rather than sharing transition highs/lows.
    return normalize_bars(
        pd.DataFrame(
            {
                "open": close,
                "high": close + 0.20,
                "low": close - 0.20,
                "close": close,
            },
            index=index,
        ),
        timeframe,
    )


def _minimum_timeframes(
    *,
    parent_bullish: bool,
    child_bullish: bool,
    evaluation: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    parent = _oscillating_trend(
        bullish=parent_bullish,
        periods=14,
        start="2025-01-05 00:00",
        frequency="1h",
        timeframe="1H",
    )
    child = _oscillating_trend(
        bullish=child_bullish,
        periods=30,
        start="2025-01-05 10:00",
        frequency="5min",
        timeframe="5min",
    )
    one = _bars(
        [100 + 0.01 * position for position in range(120)],
        start="2025-01-05 10:00",
        frequency="1min",
        timeframe="1min",
        high_padding=0.02,
        low_padding=0.02,
    )
    return {"1H": parent, "5min": child, "1min": one}


def test_technical_spec_exists_before_implementation_artifacts() -> None:
    spec = REPOSITORY_ROOT / "docs/D005_CONTEXT_ENGINE_TECHNICAL_SPEC.md"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "Acceptance criteria" in text
    assert "Parent-veto model" in text


def test_config_has_exact_parent_child_mappings_and_optional_1m_default_off() -> None:
    config = ContextEngineConfig()
    mappings = {
        item.name: (item.parent, item.reaction, item.refinement, item.optional_refinement)
        for item in config.mappings
    }
    assert mappings == {
        "weekly_4h_1h": ("1W", "4H", "1H", None),
        "daily_1h_15m": ("1D", "1H", "15min", None),
        "4h_15m_5m": ("4H", "15min", "5min", None),
        "1h_5m_1m": ("1H", "5min", "5min", "1min"),
    }
    assert not config.optional_1m_refinement
    assert config.mapping("1h_5m_1m").optional_refinement is None
    enabled = replace(config, optional_1m_refinement=True)
    assert enabled.mapping("1h_5m_1m").optional_refinement == "1min"


def test_optional_1m_refinement_executes_as_a_separate_variant() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    config = ContextEngineConfig(
        primary_mapping="1h_5m_1m",
        optional_1m_refinement=True,
        mss=MSSVariant(pivot_width=1),
        balance=replace(ContextEngineConfig().balance, lookback_bars=10),
    )
    result = ContextEngine(config).evaluate(
        _minimum_timeframes(
            parent_bullish=True,
            child_bullish=True,
            evaluation=evaluation,
        ),
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    )
    assert result.snapshot.refinement_timeframe == "1min"
    assert not result.snapshot.entry_authorized


def test_config_rejects_fixed_offset_or_non_new_york_timezone() -> None:
    with pytest.raises(ValueError, match="America/New_York"):
        ContextEngineConfig(timezone="UTC").validate()


def test_premarket_bounds_use_iana_dst_and_half_open_duration() -> None:
    winter_left, winter_right = local_bounds(date(2025, 3, 7), "00:00", "08:30")
    summer_left, summer_right = local_bounds(date(2025, 3, 10), "00:00", "08:30")
    autumn_dst_left, autumn_dst_right = local_bounds(
        date(2025, 10, 31), "00:00", "08:30"
    )
    autumn_standard_left, autumn_standard_right = local_bounds(
        date(2025, 11, 3), "00:00", "08:30"
    )
    assert winter_left == pd.Timestamp("2025-03-07 05:00", tz="UTC")
    assert winter_right == pd.Timestamp("2025-03-07 13:30", tz="UTC")
    assert summer_left == pd.Timestamp("2025-03-10 04:00", tz="UTC")
    assert summer_right == pd.Timestamp("2025-03-10 12:30", tz="UTC")
    assert winter_right - winter_left == pd.Timedelta(minutes=510)
    assert summer_right - summer_left == pd.Timedelta(minutes=510)
    assert autumn_dst_left == pd.Timestamp("2025-10-31 04:00", tz="UTC")
    assert autumn_dst_right == pd.Timestamp("2025-10-31 12:30", tz="UTC")
    assert autumn_standard_left == pd.Timestamp("2025-11-03 05:00", tz="UTC")
    assert autumn_standard_right == pd.Timestamp("2025-11-03 13:30", tz="UTC")


def test_premarket_excludes_0830_bar_and_requires_coverage() -> None:
    index = pd.date_range(
        "2025-03-10 00:00",
        "2025-03-10 08:31",
        freq="1min",
        inclusive="left",
        tz="America/New_York",
    ).tz_convert("UTC")
    prices = np.full(len(index), 2000.0)
    bars = _bars(
        prices.tolist(),
        start=str(index[0]),
        frequency="1min",
        timeframe="1min",
        high_padding=0.1,
        low_padding=0.1,
    )
    at_0830 = pd.Timestamp("2025-03-10 08:30", tz="America/New_York").tz_convert("UTC")
    bars.loc[at_0830, ["open", "high", "low", "close"]] = [3000, 3001, 2999, 3000]
    levels, metadata = premarket_levels(
        bars,
        session_date=date(2025, 3, 10),
        config=PremarketConfig(),
    )
    assert metadata["complete"]
    assert len(levels) == 2
    pmh = next(event for event in levels if event.taxonomy == "premarket_high")
    assert pmh.level == pytest.approx(2000.1)
    assert pmh.available_at == at_0830
    incomplete, metadata = premarket_levels(
        bars.iloc[:-100],
        session_date=date(2025, 3, 10),
        config=PremarketConfig(),
    )
    assert not metadata["complete"]
    assert incomplete == ()


def test_premarket_high_and_low_use_the_correct_sweep_side() -> None:
    stamp = pd.Timestamp("2025-03-10 12:30", tz="UTC")
    high_level = EvidenceEvent(
        event_id="pmh",
        event_type="premarket_level",
        direction=Direction.BEARISH,
        timeframe="1min",
        variant="test",
        taxonomy="premarket_high",
        created_at=stamp - pd.Timedelta(hours=8, minutes=30),
        available_at=stamp,
        source_rule_ids=("B06",),
        level=2000.0,
    )
    low_level = EvidenceEvent(
        event_id="pml",
        event_type="premarket_level",
        direction=Direction.BULLISH,
        timeframe="1min",
        variant="test",
        taxonomy="premarket_low",
        created_at=stamp - pd.Timedelta(hours=8, minutes=30),
        available_at=stamp,
        source_rule_ids=("B06",),
        level=1990.0,
    )
    bars = _bars(
        [1999.0, 1991.0],
        start="2025-03-10 12:30",
        frequency="1min",
        timeframe="1min",
    )
    bars.iloc[0, bars.columns.get_loc("high")] = 2000.2
    bars.iloc[0, bars.columns.get_loc("close")] = 1999.0
    sweeps = detect_liquidity_sweeps(
        (high_level, low_level),
        bars,
        timeframe="1min",
        evaluation_at=bars["available_at"].iloc[-1],
        penetration=0.1,
        require_reclaim=True,
    )
    assert len(sweeps) == 1
    assert sweeps[0].direction == Direction.BEARISH
    assert sweeps[0].parameters["level_event_id"] == "pmh"


def test_raw_fvg_geometry_is_separate_from_context_qualification() -> None:
    bars = _bars([100.0, 100.2, 102.0], frequency="5min", timeframe="5min")
    bars.iloc[0, bars.columns.get_loc("high")] = 100.4
    bars.iloc[2, bars.columns.get_loc("low")] = 101.0
    evaluation = pd.Timestamp(bars["available_at"].iloc[-1])
    fvgs = detect_fvgs(
        bars, timeframe="5min", evaluation_at=evaluation, minimum_width=0.0
    )
    assert len(fvgs) == 1
    raw = fvgs[0]
    assert raw.event_type == "raw_fvg"
    assert raw.parameters["context_qualified"] is False
    qualified = qualify_fvgs(
        fvgs,
        liquidity_events=(),
        mss_events=(),
        displacement_events=(),
        parent_direction=Direction.BULLISH,
    )
    assert qualified[0].parameters["context_qualified"] is False
    assert "ifvg_wick_variant" in qualified[0].parameters
    assert "ifvg_close_variant" in qualified[0].parameters


def test_fvg_is_available_only_at_third_bar_close() -> None:
    bars = _bars([100.0, 100.2, 102.0], frequency="5min", timeframe="5min")
    bars.iloc[0, bars.columns.get_loc("high")] = 100.4
    bars.iloc[2, bars.columns.get_loc("low")] = 101.0
    before_close = bars.index[-1] + pd.Timedelta(minutes=4)
    after_close = bars.index[-1] + pd.Timedelta(minutes=5)
    assert detect_fvgs(
        bars, timeframe="5min", evaluation_at=before_close
    ) == ()
    assert len(
        detect_fvgs(bars, timeframe="5min", evaluation_at=after_close)
    ) == 1


def _impulse_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    prices = [100.0 + 0.03 * np.sin(position) for position in range(18)]
    bars = _bars(
        prices,
        start="2025-01-06 00:00",
        frequency="15min",
        timeframe="15min",
        high_padding=0.15,
        low_padding=0.15,
    )
    # Two bearish origin candles, then a bullish inefficiency/structure impulse.
    bars.iloc[13, bars.columns.get_loc("open")] = 100.4
    bars.iloc[13, bars.columns.get_loc("close")] = 100.0
    bars.iloc[13, bars.columns.get_loc("high")] = 100.45
    bars.iloc[13, bars.columns.get_loc("low")] = 99.95
    bars.iloc[14, bars.columns.get_loc("open")] = 100.5
    bars.iloc[14, bars.columns.get_loc("close")] = 100.3
    bars.iloc[14, bars.columns.get_loc("high")] = 100.55
    bars.iloc[14, bars.columns.get_loc("low")] = 100.25
    bars.iloc[15, bars.columns.get_loc("open")] = 100.8
    bars.iloc[15, bars.columns.get_loc("close")] = 104.0
    bars.iloc[15, bars.columns.get_loc("high")] = 104.2
    bars.iloc[15, bars.columns.get_loc("low")] = 100.7
    bars.iloc[16, bars.columns.get_loc("open")] = 104.0
    bars.iloc[16, bars.columns.get_loc("close")] = 103.7
    bars.iloc[16, bars.columns.get_loc("high")] = 104.1
    bars.iloc[16, bars.columns.get_loc("low")] = 103.0
    bars.iloc[17, bars.columns.get_loc("open")] = 103.7
    bars.iloc[17, bars.columns.get_loc("close")] = 103.9
    bars.iloc[17, bars.columns.get_loc("high")] = 104.0
    bars.iloc[17, bars.columns.get_loc("low")] = 103.4
    return bars, pd.Timestamp(bars["available_at"].iloc[-1])


def test_three_order_block_definitions_emit_independent_taxonomies() -> None:
    bars, evaluation = _impulse_fixture()
    variant = DisplacementVariant(
        atr_lookback=10,
        atr_min_periods=8,
        immediate_retracement_bars=2,
        maximum_immediate_retracement=0.50,
    )
    displacements = detect_displacements(
        bars,
        timeframe="15min",
        variant=variant,
        evaluation_at=evaluation,
    )
    assert any(event.created_at == bars.index[15] for event in displacements)
    fvgs = detect_fvgs(
        bars, timeframe="15min", evaluation_at=evaluation
    )
    obs = detect_order_blocks(
        bars,
        timeframe="15min",
        evaluation_at=evaluation,
        displacement_events=displacements,
        fvg_events=fvgs,
        lookback_bars=6,
    )
    variants = {event.variant for event in obs}
    assert {
        "consecutive_block",
        "last_opposing_candle",
        "inefficiency_break_origin",
    }.issubset(variants)
    taxonomy = {event.variant: event.taxonomy for event in obs}
    assert taxonomy["consecutive_block"] == "ict_order_block"
    assert taxonomy["last_opposing_candle"] == "ict_order_block"
    assert taxonomy["inefficiency_break_origin"] == "smc_supply_demand_zone"
    assert all(event.event_id for event in obs)


def test_order_block_context_flags_do_not_merge_variants() -> None:
    bars, evaluation = _impulse_fixture()
    variant = DisplacementVariant(
        atr_lookback=10,
        atr_min_periods=8,
        immediate_retracement_bars=0,
    )
    displacements = detect_displacements(
        bars, timeframe="15min", variant=variant, evaluation_at=evaluation
    )
    fvgs = detect_fvgs(bars, timeframe="15min", evaluation_at=evaluation)
    obs = detect_order_blocks(
        bars,
        timeframe="15min",
        evaluation_at=evaluation,
        displacement_events=displacements,
        fvg_events=fvgs,
        lookback_bars=6,
    )
    qualified = qualify_order_blocks(
        obs,
        liquidity_events=(),
        mss_events=(),
        displacement_events=displacements,
        parent_direction=Direction.BULLISH,
    )
    assert {event.variant for event in qualified} == {
        event.variant for event in obs
    }
    assert all(event.parameters["raw_detected"] for event in qualified)
    assert all(not event.parameters["context_qualified"] for event in qualified)
    assert all(event.confirmed_at is None for event in qualified)


def test_order_block_interaction_and_invalidation_are_independent_per_event() -> None:
    bars, evaluation = _impulse_fixture()
    variant = DisplacementVariant(
        atr_lookback=10,
        atr_min_periods=8,
        immediate_retracement_bars=0,
    )
    displacements = detect_displacements(
        bars, timeframe="15min", variant=variant, evaluation_at=evaluation
    )
    fvgs = detect_fvgs(bars, timeframe="15min", evaluation_at=evaluation)
    obs = detect_order_blocks(
        bars,
        timeframe="15min",
        evaluation_at=evaluation,
        displacement_events=displacements,
        fvg_events=fvgs,
        lookback_bars=6,
    )
    future = _bars(
        [103.0, 100.4, 99.0],
        start="2025-01-06 04:30",
        frequency="15min",
        timeframe="15min",
    )
    interacted = apply_zone_interactions(
        obs, future, evaluation_at=future["available_at"].iloc[-1]
    )
    assert any(event.interacted_at is not None for event in interacted)
    assert any(event.invalidated_at is not None for event in interacted)
    assert len({event.event_id for event in interacted}) == len(interacted)


def test_mss_body_close_variant_rejects_wick_only_break() -> None:
    close = np.asarray([1.0, 2.0, 5.0, 2.0, 1.0, 2.0, 4.5])
    index = pd.date_range(
        "2025-01-06 00:00", periods=len(close), freq="5min", tz="UTC"
    )
    bars = normalize_bars(
        pd.DataFrame(
            {
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
            },
            index=index,
        ),
        "5min",
    )
    bars.iloc[-1, bars.columns.get_loc("high")] = 5.5
    bars.iloc[-1, bars.columns.get_loc("close")] = 4.5
    evaluation = pd.Timestamp(bars["available_at"].iloc[-1])
    body = detect_mss(
        bars,
        timeframe="5min",
        variant=MSSVariant(pivot_width=2, body_close_required=True),
        evaluation_at=evaluation,
    )
    wick = detect_mss(
        bars,
        timeframe="5min",
        variant=MSSVariant(
            name="wick_variant", pivot_width=2, body_close_required=False
        ),
        evaluation_at=evaluation,
    )
    assert not any(event.direction == Direction.BULLISH for event in body)
    assert any(event.direction == Direction.BULLISH for event in wick)


def test_displacement_waits_for_retracement_confirmation_bars() -> None:
    bars, evaluation = _impulse_fixture()
    variant = DisplacementVariant(
        atr_lookback=10,
        atr_min_periods=8,
        immediate_retracement_bars=2,
    )
    before = pd.Timestamp(bars["available_at"].iloc[16])
    assert not any(
        event.created_at == bars.index[15]
        for event in detect_displacements(
            bars, timeframe="15min", variant=variant, evaluation_at=before
        )
    )
    after = detect_displacements(
        bars, timeframe="15min", variant=variant, evaluation_at=evaluation
    )
    event = next(event for event in after if event.created_at == bars.index[15])
    assert event.available_at == bars["available_at"].iloc[17]
    assert event.parameters["immediate_retracement_bars"] == 2


def test_confirmed_swing_and_structure_are_causal() -> None:
    close = np.asarray([1, 3, 1, 4, 2, 5, 3, 6, 4], dtype=float)
    index = pd.date_range(
        "2025-01-06 00:00", periods=len(close), freq="1h", tz="UTC"
    )
    bars = normalize_bars(
        pd.DataFrame(
            {
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
            },
            index=index,
        ),
        "1H",
    )
    swings = confirmed_swings(bars, width=1)
    first_high = swings[swings["swing_type"].eq("high")].iloc[0]
    assert first_high["confirmation_at"] == bars["available_at"].iloc[2]
    before = structure_direction(swings, bars["available_at"].iloc[4])[0]
    after = structure_direction(swings, bars["available_at"].iloc[-1])[0]
    assert before == Direction.NEUTRAL
    assert after == Direction.BULLISH


def test_equal_liquidity_requires_confirmed_pivots_and_atr_tolerance() -> None:
    close = np.asarray([1.0, 3.0, 1.0, 3.05, 1.1, 4.0, 2.0])
    index = pd.date_range(
        "2025-01-06 00:00", periods=len(close), freq="1h", tz="UTC"
    )
    bars = normalize_bars(
        pd.DataFrame(
            {
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
            },
            index=index,
        ),
        "1H",
    )
    swings = confirmed_swings(bars, width=1)
    before_second_confirmation = bars["available_at"].iloc[3]
    before = equal_liquidity_levels(
        swings,
        timeframe="1H",
        evaluation_at=before_second_confirmation,
        atr=1.0,
        tolerance_atr=0.1,
    )
    after = equal_liquidity_levels(
        swings,
        timeframe="1H",
        evaluation_at=bars["available_at"].iloc[-1],
        atr=1.0,
        tolerance_atr=0.1,
    )
    assert before == ()
    assert any(event.taxonomy == "equal_high_liquidity" for event in after)


def test_balanced_classifier_requires_boundaries_and_low_efficiency() -> None:
    prices = [100, 101, 99, 101, 99, 100, 101, 99, 101, 99] * 2
    bars = _bars(prices, frequency="1h", timeframe="1H")
    result = classify_balanced(
        bars,
        evaluation_at=bars["available_at"].iloc[-1],
        variant=ContextEngineConfig().balance,
    )
    assert result["balanced"]
    trending = _bars(
        list(np.linspace(100, 120, 20)),
        frequency="1h",
        timeframe="1H",
    )
    result = classify_balanced(
        trending,
        evaluation_at=trending["available_at"].iloc[-1],
        variant=ContextEngineConfig().balance,
    )
    assert not result["balanced"]


def test_trapped_between_opposing_arrays_is_explicit() -> None:
    stamp = pd.Timestamp("2025-01-06 12:00", tz="UTC")
    bullish = EvidenceEvent(
        event_id="bull",
        event_type="raw_fvg",
        direction=Direction.BULLISH,
        timeframe="4H",
        variant="raw",
        taxonomy="ict_fair_value_gap",
        created_at=stamp,
        available_at=stamp,
        source_rule_ids=("A04",),
        zone_low=98.0,
        zone_high=99.5,
    )
    bearish = EvidenceEvent(
        event_id="bear",
        event_type="raw_fvg",
        direction=Direction.BEARISH,
        timeframe="4H",
        variant="raw",
        taxonomy="ict_fair_value_gap",
        created_at=stamp,
        available_at=stamp,
        source_rule_ids=("A04",),
        zone_low=100.5,
        zone_high=102.0,
    )
    assert trapped_between_opposing_arrays(
        price=100.0,
        atr=1.0,
        events=(bullish, bearish),
        maximum_distance_atr=1.0,
    )


def test_parent_veto_conflict_is_neutral_and_logged() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    config = ContextEngineConfig(
        primary_mapping="1h_5m_1m",
        mss=MSSVariant(pivot_width=1),
        balance=replace(ContextEngineConfig().balance, lookback_bars=10),
    )
    result = ContextEngine(config).evaluate(
        _minimum_timeframes(
            parent_bullish=True,
            child_bullish=False,
            evaluation=evaluation,
        ),
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    )
    assert result.snapshot.state == ContextState.CONFLICT
    assert result.snapshot.direction == Direction.NEUTRAL
    assert result.snapshot.outcome == OutcomeLabel.NEUTRAL
    assert not result.snapshot.entry_authorized
    assert "parent_child_direction_conflict" in result.snapshot.no_trade_reasons
    assert len(result.conflict_events) == 1
    assert result.conflict_events[0].parameters["weighted_scoring_used"] is False


def test_missing_required_data_fails_closed() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    result = ContextEngine(
        replace(ContextEngineConfig(), primary_mapping="1h_5m_1m")
    ).evaluate(
        {"1H": _bars([1, 2, 3], timeframe="1H")},
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    )
    assert result.snapshot.state == ContextState.NEUTRAL
    assert result.snapshot.missing_required_data
    assert not result.snapshot.entry_authorized


def test_pmh_pml_cannot_override_valid_parent_or_authorize_entry() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    config = ContextEngineConfig(
        primary_mapping="1h_5m_1m",
        mss=MSSVariant(pivot_width=1),
        balance=replace(ContextEngineConfig().balance, lookback_bars=10),
    )
    timeframes = _minimum_timeframes(
        parent_bullish=True,
        child_bullish=True,
        evaluation=evaluation,
    )
    result = ContextEngine(config).evaluate(
        timeframes,
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    )
    assert result.snapshot.parent_direction == Direction.BULLISH
    assert result.snapshot.direction in (Direction.NEUTRAL, Direction.BULLISH)
    assert not result.snapshot.entry_authorized
    assert all(
        event.taxonomy not in {"premarket_high", "premarket_low"}
        for event in result.liquidity_events
    )


def test_reaction_confirmed_requires_the_complete_conservative_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    candidate = EvidenceEvent(
        event_id="parent-poi",
        event_type="raw_fvg",
        direction=Direction.BULLISH,
        timeframe="1H",
        variant="three_candle_wick_nonoverlap",
        taxonomy="ict_fair_value_gap",
        created_at=evaluation - pd.Timedelta(hours=2),
        available_at=evaluation - pd.Timedelta(hours=1),
        source_rule_ids=("A04",),
        parameters={"context_qualified": False},
        zone_low=100.0,
        zone_high=101.0,
    )
    entry_array = EvidenceEvent(
        event_id="entry-array",
        event_type="raw_fvg",
        direction=Direction.BULLISH,
        timeframe="5min",
        variant="three_candle_wick_nonoverlap",
        taxonomy="ict_fair_value_gap",
        created_at=evaluation - pd.Timedelta(minutes=10),
        available_at=evaluation - pd.Timedelta(minutes=5),
        source_rule_ids=("A04",),
        parameters={"context_qualified": False},
        zone_low=102.0,
        zone_high=102.5,
    )
    mss = EvidenceEvent(
        event_id="mss",
        event_type="market_structure_shift",
        direction=Direction.BULLISH,
        timeframe="5min",
        variant="body_close_pivot_w1",
        taxonomy="reaction_confirmation",
        created_at=evaluation - pd.Timedelta(minutes=25),
        available_at=evaluation - pd.Timedelta(minutes=20),
        confirmed_at=evaluation - pd.Timedelta(minutes=20),
        source_rule_ids=("A11", "A12"),
    )
    displacement = EvidenceEvent(
        event_id="displacement",
        event_type="displacement",
        direction=Direction.BULLISH,
        timeframe="5min",
        variant="atr_body_baseline",
        taxonomy="reaction_confirmation",
        created_at=evaluation - pd.Timedelta(minutes=15),
        available_at=evaluation - pd.Timedelta(minutes=10),
        confirmed_at=evaluation - pd.Timedelta(minutes=10),
        source_rule_ids=("A13",),
    )

    monkeypatch.setattr(
        "research.context_engine.engine.structure_direction",
        lambda swings, evaluation_at: (
            Direction.BULLISH,
            {"available_at": evaluation - pd.Timedelta(days=1)},
        ),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.classify_balanced",
        lambda *args, **kwargs: {
            "balanced": False,
            "range_like": False,
            "boundaries_resolved": False,
            "range_high": 110.0,
            "range_low": 90.0,
        },
    )
    monkeypatch.setattr(
        "research.context_engine.engine.detect_fvgs",
        lambda bars, *, timeframe, **kwargs: (
            (candidate,) if timeframe == "1H" else (entry_array,)
        ),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.apply_zone_interactions",
        lambda events, bars, **kwargs: tuple(
            replace(
                event,
                interacted_at=evaluation - pd.Timedelta(minutes=30),
            )
            for event in events
        ),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.detect_order_blocks",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.detect_mss",
        lambda bars, *, timeframe, **kwargs: (mss,) if timeframe == "5min" else (),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.detect_displacements",
        lambda bars, *, timeframe, **kwargs: (
            (displacement,) if timeframe == "5min" else ()
        ),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.swing_liquidity_levels",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.equal_liquidity_levels",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.detect_liquidity_sweeps",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        "research.context_engine.engine.latest_prior_atr",
        lambda *args, **kwargs: 100.0,
    )
    monkeypatch.setattr(
        "research.context_engine.engine.trapped_between_opposing_arrays",
        lambda **kwargs: False,
    )

    config = ContextEngineConfig(
        primary_mapping="1h_5m_1m",
        mss=MSSVariant(pivot_width=1),
        balance=replace(ContextEngineConfig().balance, lookback_bars=10),
    )
    result = ContextEngine(config).evaluate(
        _minimum_timeframes(
            parent_bullish=True,
            child_bullish=True,
            evaluation=evaluation,
        ),
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    )
    assert result.snapshot.state == ContextState.REACTION_CONFIRMED
    assert result.snapshot.direction == Direction.BULLISH
    assert result.snapshot.outcome == OutcomeLabel.CONTINUATION
    assert not result.snapshot.entry_authorized
    assert result.snapshot.evidence_ids == (
        "parent-poi",
        "mss",
        "displacement",
        "entry-array",
    )
    assert result.snapshot.transitions[-1].to_state == ContextState.REACTION_CONFIRMED


def test_future_mutation_does_not_change_earlier_snapshot() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    config = ContextEngineConfig(
        primary_mapping="1h_5m_1m",
        mss=MSSVariant(pivot_width=1),
        balance=replace(ContextEngineConfig().balance, lookback_bars=10),
    )
    original = _minimum_timeframes(
        parent_bullish=True,
        child_bullish=False,
        evaluation=evaluation,
    )
    before = ContextEngine(config).evaluate(
        original,
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    ).snapshot.to_record()
    changed = {name: frame.copy() for name, frame in original.items()}
    for name, frame in tuple(changed.items()):
        future_index = pd.date_range(
            evaluation + pd.Timedelta(minutes=1),
            periods=5,
            freq="1min",
            tz="UTC",
        )
        future = pd.DataFrame(
            {
                "open": 10000.0,
                "high": 11000.0,
                "low": 9000.0,
                "close": 10500.0,
                "available_at": future_index + pd.Timedelta(minutes=1),
                "observed_minutes": 1,
                "timeframe": name,
            },
            index=future_index,
        )
        changed[name] = pd.concat([frame, future]).sort_index()
    after = ContextEngine(config).evaluate(
        changed,
        evaluation_at=evaluation,
        mapping_name="1h_5m_1m",
    ).snapshot.to_record()
    assert before == after


def test_evaluation_result_rejects_future_event_evidence() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    snapshot = ContextSnapshot(
        evaluation_at=evaluation,
        mapping_name="test",
        parent_timeframe="4H",
        reaction_timeframe="15min",
        refinement_timeframe="5min",
        state=ContextState.NEUTRAL,
        direction=Direction.NEUTRAL,
        outcome=OutcomeLabel.NEUTRAL,
        parent_direction=Direction.NEUTRAL,
        child_direction=Direction.NEUTRAL,
        entry_authorized=False,
        no_trade_reasons=("test",),
        evidence_ids=(),
        source_rule_ids=("A31",),
        variant_ids=(),
        config_fingerprint="test",
        transitions=(),
    )
    future = EvidenceEvent(
        event_id="future",
        event_type="raw_fvg",
        direction=Direction.BULLISH,
        timeframe="5min",
        variant="test",
        taxonomy="test",
        created_at=evaluation,
        available_at=evaluation + pd.Timedelta(minutes=5),
        source_rule_ids=("A04",),
    )
    with pytest.raises(ValueError, match="future evidence"):
        EvaluationResult(snapshot, (future,), (), (), (), ())


def test_invalid_state_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid D005 state transition"):
        validate_transition(
            ContextState.NEUTRAL, ContextState.REACTION_CONFIRMED
        )


def test_snapshot_can_never_authorize_entry() -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    with pytest.raises(ValueError, match="cannot authorize"):
        ContextSnapshot(
            evaluation_at=evaluation,
            mapping_name="test",
            parent_timeframe="4H",
            reaction_timeframe="15min",
            refinement_timeframe="5min",
            state=ContextState.REACTION_CONFIRMED,
            direction=Direction.BULLISH,
            outcome=OutcomeLabel.CONTINUATION,
            parent_direction=Direction.BULLISH,
            child_direction=Direction.BULLISH,
            entry_authorized=True,
            no_trade_reasons=(),
            evidence_ids=(),
            source_rule_ids=("B08",),
            variant_ids=(),
            config_fingerprint="x",
            transitions=(),
        )


def test_build_timeframes_does_not_mutate_source_and_marks_availability() -> None:
    index = pd.date_range(
        "2025-01-05 18:00",
        periods=24 * 60,
        freq="1min",
        tz="America/New_York",
    ).tz_convert("UTC")
    source = pd.DataFrame(
        {
            "mid_open": 2000.0,
            "mid_high": 2000.1,
            "mid_low": 1999.9,
            "mid_close": 2000.0,
        },
        index=index,
    )
    before = source.copy(deep=True)
    timeframes = build_timeframes(source)
    pd.testing.assert_frame_equal(source, before)
    assert set(timeframes) == {"1min", "5min", "15min", "1H", "4H", "1D", "1W"}
    assert (
        pd.to_datetime(timeframes["4H"]["available_at"], utc=True)
        > timeframes["4H"].index
    ).all()


def test_bar_validation_rejects_unclosed_or_invalid_ohlc_inputs() -> None:
    frame = pd.DataFrame(
        {"open": [1.0], "high": [0.5], "low": [0.0], "close": [1.0]},
        index=pd.DatetimeIndex(["2025-01-01"], tz="UTC"),
    )
    with pytest.raises(BarValidationError, match="OHLC invariant"):
        normalize_bars(frame, "1min")


def test_research_report_writes_independent_ob_variants_and_no_valid_ob(
    tmp_path: Path,
) -> None:
    evaluation = pd.Timestamp("2025-01-06 12:30", tz="UTC")
    snapshot = ContextSnapshot(
        evaluation_at=evaluation,
        mapping_name="4h_15m_5m",
        parent_timeframe="4H",
        reaction_timeframe="15min",
        refinement_timeframe="5min",
        state=ContextState.NEUTRAL,
        direction=Direction.NEUTRAL,
        outcome=OutcomeLabel.NEUTRAL,
        parent_direction=Direction.NEUTRAL,
        child_direction=Direction.NEUTRAL,
        entry_authorized=False,
        no_trade_reasons=("reaction_confirmation_absent",),
        evidence_ids=(),
        source_rule_ids=("A31",),
        variant_ids=(),
        config_fingerprint=ContextEngineConfig().fingerprint(),
        transitions=(),
    )
    result = EvaluationResult(snapshot, (), (), (), (), ())
    persisted = persist_research_results(
        [result],
        output_dir=tmp_path,
        config=ContextEngineConfig(),
        input_provenance={"source": "synthetic", "read_only": True},
    )
    assert (tmp_path / "context_snapshots.parquet").is_file()
    assert (tmp_path / "artifact_manifest.json").is_file()
    report = (tmp_path / "D005_CONTEXT_ENGINE_RESEARCH_REPORT.md").read_text()
    assert "robust standalone directional edge" in report
    assert "No aggregate `valid_ob`" in report
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["entry_authorized_count"] == 0
    assert summary["order_block_variant_statistics"] == {}
    assert summary["production_behavior_changed"] is False
    assert persisted["summary"]["snapshot_count"] == 1


def test_d005_package_has_no_production_strategy_import_or_index_timing_rule() -> None:
    package = REPOSITORY_ROOT / "research/context_engine"
    executable_modules = (
        "bars.py",
        "config.py",
        "engine.py",
        "features.py",
        "models.py",
        "pipeline.py",
    )
    source = "\n".join(
        (package / filename).read_text(encoding="utf-8")
        for filename in executable_modules
    )
    assert "xauusd_signal" not in source
    assert "09:30" not in source
    assert "10:00" not in source
    assert "NAS100" not in source
    assert "SP500" not in source
