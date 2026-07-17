import pandas as pd
import pytest

from research.fvg_entry_geometry import (
    ResearchEntryModel,
    apply_research_costs,
    entry_price_for_model,
    evaluate_entry_geometry_at,
    run_entry_geometry_research,
    run_entry_geometry_backtest,
    summarize_common_candidate_cohort,
)
from xauusd_signal.backtest import BacktestConfig, run_backtest
from xauusd_signal.data import add_closed_at
from xauusd_signal.events import FairValueGap
from xauusd_signal.strategy import StrategyConfig, build_strategy_event_cache
from xauusd_signal.types import EntryModel, HtfBias, OperatingMode


def pending_long_df() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2025-01-01 00:00",
                periods=13,
                freq="15min",
                tz="UTC",
            ),
            "open": [100, 103, 103, 102, 100, 99, 101, 104, 103, 103, 106, 106, 110],
            "high": [101, 105, 104, 103, 102, 101, 107, 125, 104, 105, 108, 108, 126],
            "low": [99, 100, 101, 98, 99, 97, 100, 103, 102, 102, 106, 104.5, 104],
            "close": [100, 104, 102, 99, 101, 100, 106, 104, 103, 104, 107, 106, 125],
            "volume": [1] * 13,
        }
    )
    frame[["open", "high", "low", "close"]] = frame[
        ["open", "high", "low", "close"]
    ].astype(float)
    return add_closed_at(frame, pd.Timedelta(minutes=15))


def strategy() -> StrategyConfig:
    return StrategyConfig(
        operating_mode=OperatingMode.RULE_ONLY,
        htf_bias=HtfBias.BULLISH,
    )


def test_entry_depth_runs_distal_to_proximal_in_both_directions():
    created_at = pd.Timestamp("2025-01-01", tz="UTC")
    bullish = FairValueGap("bullish", 1, 3, 100.0, 110.0, 105.0, created_at)
    bearish = FairValueGap("bearish", 1, 3, 100.0, 110.0, 105.0, created_at)
    models = list(ResearchEntryModel)

    assert [entry_price_for_model(bullish, model) for model in models] == [
        100.0,
        102.5,
        105.0,
        107.5,
        110.0,
    ]
    assert [entry_price_for_model(bearish, model) for model in models] == [
        110.0,
        107.5,
        105.0,
        102.5,
        100.0,
    ]


@pytest.mark.parametrize("bias", [HtfBias.BULLISH, HtfBias.BEARISH])
def test_research_midpoint_replay_is_exactly_production_equivalent(
    bias: HtfBias,
):
    df = pending_long_df()
    if bias == HtfBias.BEARISH:
        mirrored = df.copy()
        mirrored["open"] = 200.0 - df["open"]
        mirrored["close"] = 200.0 - df["close"]
        mirrored["high"] = 200.0 - df["low"]
        mirrored["low"] = 200.0 - df["high"]
        df = mirrored
    config = BacktestConfig(
        StrategyConfig(
            operating_mode=OperatingMode.RULE_ONLY,
            htf_bias=bias,
        )
    )
    cache = build_strategy_event_cache(df)

    production = run_backtest(df, config, event_cache=cache)
    research = run_entry_geometry_backtest(
        df,
        config,
        ResearchEntryModel.MIDPOINT,
        event_cache=cache,
    )

    assert research == production


def test_alternative_models_change_only_entry_dependent_geometry():
    df = pending_long_df()
    config = strategy()
    cache = build_strategy_event_cache(df)
    signals = []
    candidates = []
    for model in ResearchEntryModel:
        signal, candidate = evaluate_entry_geometry_at(
            df,
            10,
            config,
            cache,
            model,
        )
        signals.append(signal)
        candidates.append(candidate)

    assert all(candidate is not None for candidate in candidates)
    assert len({signal.entry_price for signal in signals}) == 5
    assert len({signal.stop_loss for signal in signals}) == 1
    assert len({signal.take_profit[-1].price for signal in signals}) == 1
    assert len({signal.lifecycle.sweep_index for signal in signals}) == 1
    assert len({signal.lifecycle.mss_index for signal in signals}) == 1
    assert len({signal.lifecycle.fvg_end_index for signal in signals}) == 1


def test_production_entry_model_remains_midpoint_only():
    assert list(EntryModel) == [EntryModel.FVG_MIDPOINT]
    assert StrategyConfig().entry_model == EntryModel.FVG_MIDPOINT


def test_common_candidate_summary_uses_the_same_activation_cohort():
    df = pending_long_df()
    cache = build_strategy_event_cache(df)
    runs = [
        run_entry_geometry_research(
            df,
            strategy(),
            model,
            event_cache=cache,
        )
        for model in ResearchEntryModel
    ]

    summaries = summarize_common_candidate_cohort(runs)

    assert len(summaries) == 5
    assert {summary.common_candidates for summary in summaries} == {1}
    assert [summary.model for summary in summaries] == [
        model.label for model in ResearchEntryModel
    ]


def test_cost_repricing_matches_a_direct_costed_replay():
    df = pending_long_df()
    cache = build_strategy_event_cache(df)
    zero = run_entry_geometry_backtest(
        df,
        BacktestConfig(strategy()),
        ResearchEntryModel.MIDPOINT,
        event_cache=cache,
    )
    direct = run_entry_geometry_backtest(
        df,
        BacktestConfig(
            strategy(),
            spread_cost=0.20,
            slippage=0.10,
            commission_r=0.01,
        ),
        ResearchEntryModel.MIDPOINT,
        event_cache=cache,
    )
    repriced = apply_research_costs(zero)

    assert repriced.orders == direct.orders
    assert repriced.trades[0].r_multiple == pytest.approx(
        direct.trades[0].r_multiple
    )
