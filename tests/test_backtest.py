import pandas as pd
import pytest

from xauusd_signal.backtest import BacktestConfig, _exit_trade, run_backtest
from xauusd_signal.data import add_closed_at
from xauusd_signal.strategy import StrategyConfig
from xauusd_signal.types import Decision, HtfBias, OperatingMode, Signal, TakeProfit


def backtest_df():
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
    return add_closed_at(df, pd.Timedelta(minutes=15))


def test_backtest_uses_next_bar_entry_and_records_target_win():
    result = run_backtest(
        backtest_df(),
        BacktestConfig(
            StrategyConfig(operating_mode=OperatingMode.RULE_ONLY, htf_bias=HtfBias.BULLISH),
            spread_cost=0.0,
            slippage=0.0,
        ),
    )
    assert result.closed_trades == 1
    trade = result.trades[0]
    assert trade.decision == Decision.BUY
    assert trade.entry_index > trade.signal_index
    assert trade.order_activation_index == trade.signal_index
    assert trade.exit_reason == "target"
    assert trade.r_multiple > 2.0


def test_backtest_stop_first_when_stop_and_target_same_bar():
    df = backtest_df()
    df.loc[12, "high"] = 126
    df.loc[12, "low"] = 96
    result = run_backtest(
        df,
        BacktestConfig(StrategyConfig(operating_mode=OperatingMode.RULE_ONLY, htf_bias=HtfBias.BULLISH)),
    )
    assert result.trades[0].exit_reason == "stop_loss"
    assert result.trades[0].r_multiple < 0


def test_time_exit_uses_after_cost_r_multiple():
    df = add_closed_at(
        pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2025-01-01 00:00", tz="UTC")],
                "open": [100.0],
                "high": [101.0],
                "low": [99.5],
                "close": [100.5],
                "volume": [1],
            }
        ),
        pd.Timedelta(minutes=15),
    )
    signal = Signal(
        decision=Decision.BUY,
        operating_mode=OperatingMode.RULE_ONLY,
        timestamp=str(df.iloc[0]["closed_at"]),
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=[TakeProfit("TP2_LIQUIDITY", 110.0)],
    )
    trade = _exit_trade(
        df,
        0,
        signal,
        BacktestConfig(
            StrategyConfig(operating_mode=OperatingMode.RULE_ONLY, htf_bias=HtfBias.BULLISH),
            spread_cost=0.2,
            slippage=0.1,
            max_holding_bars=0,
        ),
    )
    assert trade.exit_reason == "time_exit"
    assert trade.r_multiple == pytest.approx(0.1)
