import pandas as pd

from xauusd_signal.backtest import BacktestConfig, run_backtest
from xauusd_signal.data import add_closed_at
from xauusd_signal.events import Swing
from xauusd_signal.strategy import (
    StrategyConfig,
    _target_for_long,
    _target_for_short,
    evaluate_signal,
)
from xauusd_signal.types import Decision, EntryOutcome, HtfBias, OperatingMode, SetupState


def legacy_double_retracement_df() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00", periods=11, freq="15min", tz="UTC"),
            "open": [100, 103, 103, 102, 100, 99, 101, 104, 104, 103, 105],
            "high": [101, 105, 104, 103, 102, 101, 106, 115, 104, 103, 116],
            "low": [99, 100, 101, 98, 99, 97, 100, 103, 101.5, 101, 103],
            "close": [100, 104, 102, 99, 101, 100, 106, 104, 103, 102, 115],
            "volume": [1] * 11,
        }
    )
    return add_closed_at(df, pd.Timedelta(minutes=15))


def pending_long_df() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00", periods=13, freq="15min", tz="UTC"),
            "open": [100, 103, 103, 102, 100, 99, 101, 104, 103, 103, 106, 106, 110],
            "high": [101, 105, 104, 103, 102, 101, 107, 125, 104, 105, 108, 108, 126],
            "low": [99, 100, 101, 98, 99, 97, 100, 103, 102, 102, 106, 104.5, 104],
            "close": [100, 104, 102, 99, 101, 100, 106, 104, 103, 104, 107, 106, 125],
            "volume": [1] * 13,
        }
    )
    df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
    return add_closed_at(df, pd.Timedelta(minutes=15))


def strategy_config(**changes) -> StrategyConfig:
    values = {
        "operating_mode": OperatingMode.RULE_ONLY,
        "htf_bias": HtfBias.BULLISH,
    }
    values.update(changes)
    return StrategyConfig(**values)


def test_legacy_double_retracement_fixture_is_rejected_by_causal_activation():
    df = legacy_double_retracement_df()
    strategy = strategy_config()

    at_fvg_creation = evaluate_signal(df.iloc[:8].reset_index(drop=True), strategy)
    on_retracement = evaluate_signal(df.iloc[:9].reset_index(drop=True), strategy)
    result = run_backtest(df, BacktestConfig(strategy))

    assert at_fvg_creation.decision == Decision.NO_TRADE
    assert at_fvg_creation.rejection_reasons == ["target_unavailable"]
    assert on_retracement.decision == Decision.NO_TRADE
    assert on_retracement.rejection_reasons == ["no_valid_fvg"]
    assert result.orders == []


def test_pending_order_is_created_when_causal_fvg_becomes_known():
    df = pending_long_df().iloc[:11].reset_index(drop=True)
    signal = evaluate_signal(df, strategy_config())

    assert signal.decision == Decision.BUY
    assert signal.entry_price == 105.0
    assert signal.lifecycle.state == SetupState.ENTRY_PENDING
    assert signal.lifecycle.fvg_created_at == str(df.iloc[10]["closed_at"])
    assert signal.lifecycle.order_activation_index == 10
    assert signal.lifecycle.first_eligible_fill_index == 11
    assert signal.lifecycle.entry_expiration_index == 18


def test_signal_does_not_require_activation_bar_to_touch_entry_level():
    df = pending_long_df().iloc[:11].reset_index(drop=True)
    signal = evaluate_signal(df, strategy_config())

    assert df.iloc[10]["low"] > signal.entry_price
    assert signal.decision == Decision.BUY


def test_first_eligible_bar_fills_without_same_bar_hindsight():
    result = run_backtest(pending_long_df(), BacktestConfig(strategy_config()))

    order = result.orders[0]
    assert order.order_activation_index == 10
    assert order.first_eligible_fill_index == 11
    assert order.entry_index == 11
    assert order.exit_index == 12
    assert order.outcome == EntryOutcome.ENTRY_FILLED
    assert result.trades[0].expiration_index == 18
    assert order.lifecycle.state_history == (
        SetupState.SETUP_FORMING,
        SetupState.ENTRY_PENDING,
        SetupState.ENTRY_FILLED,
        SetupState.TRADE_OPEN,
        SetupState.TRADE_CLOSED,
    )


def test_pending_order_expires_after_configured_wait():
    df = pending_long_df()
    df.loc[11:12, "low"] = 106.0
    config = strategy_config(max_entry_wait_bars=2)
    result = run_backtest(df, BacktestConfig(config))

    order = result.orders[0]
    assert order.outcome == EntryOutcome.ENTRY_EXPIRED
    assert order.expiration_index == 12
    assert order.outcome_index == 12
    assert order.lifecycle.state == SetupState.ENTRY_EXPIRED
    assert result.outcome_counts == {"entry_expired": 1}


def test_structural_invalidation_wins_when_entry_is_possible_on_same_bar():
    df = pending_long_df()
    df.loc[11, ["high", "low", "close"]] = [108.0, 97.95, 97.95]
    result = run_backtest(df, BacktestConfig(strategy_config()))

    order = result.orders[0]
    assert order.entry_index is None
    assert order.invalidation_index == 11
    assert order.outcome == EntryOutcome.SETUP_INVALIDATED
    assert order.reason == "structural_break_before_entry"


def test_fvg_close_through_invalidates_before_entry():
    df = pending_long_df()
    df.loc[11, ["high", "low", "close"]] = [104.9, 103.0, 103.5]
    result = run_backtest(df, BacktestConfig(strategy_config()))

    order = result.orders[0]
    assert order.outcome == EntryOutcome.SETUP_INVALIDATED
    assert order.reason == "fvg_close_through_before_entry"
    assert order.invalidation_index == 11


def test_stop_breach_invalidation_is_configurable():
    df = pending_long_df()
    df.loc[11, ["high", "low", "close"]] = [104.9, 97.0, 103.5]

    enabled = run_backtest(df, BacktestConfig(strategy_config(max_entry_wait_bars=1)))
    assert enabled.orders[0].reason == "stop_level_breached_before_entry"

    disabled_config = strategy_config(
        max_entry_wait_bars=1,
        invalidate_on_stop_level_breach=False,
        invalidate_on_structural_break=False,
        invalidate_on_fvg_close_through=False,
    )
    disabled = run_backtest(df, BacktestConfig(disabled_config))
    assert disabled.orders[0].outcome == EntryOutcome.ENTRY_EXPIRED


def test_valid_order_is_not_reached_when_dataset_ends_before_expiration():
    df = pending_long_df().iloc[:12].copy()
    df.loc[11, "low"] = 106.0
    result = run_backtest(df, BacktestConfig(strategy_config(max_entry_wait_bars=8)))

    order = result.orders[0]
    assert order.outcome == EntryOutcome.ENTRY_NOT_REACHED
    assert order.expiration_index == 18
    assert order.outcome_index == 11
    assert result.closed_trades == 0


def test_target_swings_must_be_detected_by_activation_time():
    activation = pd.Timestamp("2025-01-01 02:00", tz="UTC")
    late = activation + pd.Timedelta(minutes=15)
    long_swings = [Swing("swing_high", 7, 125.0, late)]
    short_swings = [Swing("swing_low", 7, 75.0, late)]

    assert _target_for_long(long_swings, 105.0, 1, activation) is None
    assert _target_for_short(short_swings, 95.0, 1, activation) is None

    known_long = [Swing("swing_high", 7, 125.0, activation)]
    known_short = [Swing("swing_low", 7, 75.0, activation)]
    assert _target_for_long(known_long, 105.0, 1, activation) == 125.0
    assert _target_for_short(known_short, 95.0, 1, activation) == 75.0


def test_repeated_backtests_are_deterministic():
    config = BacktestConfig(strategy_config())
    first = run_backtest(pending_long_df(), config)
    second = run_backtest(pending_long_df(), config)

    assert first == second
