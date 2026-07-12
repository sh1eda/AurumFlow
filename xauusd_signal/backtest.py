from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .strategy import StrategyConfig, evaluate_signal
from .types import Decision, Signal


@dataclass(frozen=True)
class BacktestConfig:
    strategy: StrategyConfig
    spread_cost: float = 0.0
    slippage: float = 0.0
    commission_r: float = 0.0
    max_holding_bars: int = 48


@dataclass(frozen=True)
class Trade:
    decision: Decision
    signal_index: int
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    stop_loss: float
    target_price: float
    r_multiple: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)

    @property
    def closed_trades(self) -> int:
        return len(self.trades)

    @property
    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        return sum(trade.r_multiple for trade in self.trades) / len(self.trades)

    @property
    def profit_factor(self) -> float | None:
        wins = sum(trade.r_multiple for trade in self.trades if trade.r_multiple > 0)
        losses = abs(sum(trade.r_multiple for trade in self.trades if trade.r_multiple < 0))
        if losses == 0:
            return None if wins > 0 else 0.0
        return wins / losses

    @property
    def max_drawdown_r(self) -> float:
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for trade in self.trades:
            equity += trade.r_multiple
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)
        return abs(drawdown)


def _record_rejections(counts: dict[str, int], signal: Signal) -> None:
    for reason in signal.rejection_reasons:
        counts[reason] = counts.get(reason, 0) + 1


def _entry_touched(row: pd.Series, signal: Signal) -> bool:
    if signal.entry_price is None:
        return False
    return bool(row["low"] <= signal.entry_price <= row["high"])


def _exit_trade(df: pd.DataFrame, entry_index: int, signal: Signal, config: BacktestConfig) -> Trade:
    assert signal.entry_price is not None
    assert signal.stop_loss is not None
    assert signal.take_profit
    target = signal.take_profit[-1].price
    risk = abs(signal.entry_price - signal.stop_loss)
    max_exit = min(len(df), entry_index + config.max_holding_bars + 1)
    exit_price = float(df.iloc[max_exit - 1]["close"])
    exit_index = max_exit - 1
    exit_reason = "time_exit"

    for i in range(entry_index, max_exit):
        row = df.iloc[i]
        if signal.decision == Decision.BUY:
            stop_hit = row["low"] <= signal.stop_loss
            target_hit = row["high"] >= target
        else:
            stop_hit = row["high"] >= signal.stop_loss
            target_hit = row["low"] <= target
        if stop_hit:
            exit_price = signal.stop_loss
            exit_index = i
            exit_reason = "stop_loss"
            break
        if target_hit:
            exit_price = target
            exit_index = i
            exit_reason = "target"
            break

    if signal.decision == Decision.BUY:
        gross_r = (exit_price - signal.entry_price) / risk
        adjusted_entry = signal.entry_price + config.slippage + config.spread_cost
        adjusted_exit = exit_price - config.slippage
        net_r = (adjusted_exit - adjusted_entry) / risk - config.commission_r
    else:
        gross_r = (signal.entry_price - exit_price) / risk
        adjusted_entry = signal.entry_price - config.slippage - config.spread_cost
        adjusted_exit = exit_price + config.slippage
        net_r = (adjusted_entry - adjusted_exit) / risk - config.commission_r
    r_multiple = net_r

    return Trade(
        decision=signal.decision,
        signal_index=-1,
        entry_index=entry_index,
        exit_index=exit_index,
        entry_price=signal.entry_price,
        exit_price=exit_price,
        stop_loss=signal.stop_loss,
        target_price=target,
        r_multiple=r_multiple,
        exit_reason=exit_reason,
    )


def run_backtest(df: pd.DataFrame, config: BacktestConfig, warmup_bars: int = 8) -> BacktestResult:
    trades: list[Trade] = []
    signals: list[Signal] = []
    rejection_counts: dict[str, int] = {}
    i = warmup_bars
    while i < len(df) - 1:
        window = df.iloc[: i + 1].reset_index(drop=True)
        signal = evaluate_signal(window, config.strategy)
        signals.append(signal)
        if signal.decision == Decision.NO_TRADE:
            _record_rejections(rejection_counts, signal)
            i += 1
            continue

        entry_index = None
        for j in range(i + 1, len(df)):
            if _entry_touched(df.iloc[j], signal):
                entry_index = j
                break
        if entry_index is None:
            rejection_counts["entry_not_filled"] = rejection_counts.get("entry_not_filled", 0) + 1
            i += 1
            continue
        trade = _exit_trade(df, entry_index, signal, config)
        trade = Trade(
            decision=trade.decision,
            signal_index=i,
            entry_index=trade.entry_index,
            exit_index=trade.exit_index,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            stop_loss=trade.stop_loss,
            target_price=trade.target_price,
            r_multiple=trade.r_multiple,
            exit_reason=trade.exit_reason,
        )
        trades.append(trade)
        i = max(trade.exit_index + 1, i + 1)

    return BacktestResult(trades=trades, signals=signals, rejection_counts=rejection_counts)
