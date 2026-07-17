from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from .strategy import (
    StrategyConfig,
    StrategyEventCache,
    build_strategy_event_cache,
    evaluate_signal_at,
)
from .types import Decision, EntryLifecycle, EntryOutcome, SetupState, Signal


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
    order_activation_index: int = -1
    expiration_index: int | None = None
    invalidation_index: int | None = None
    lifecycle: EntryLifecycle | None = None


@dataclass(frozen=True)
class OrderRecord:
    decision: Decision
    signal_index: int
    order_activation_index: int
    first_eligible_fill_index: int
    expiration_index: int
    outcome_index: int
    outcome: EntryOutcome
    reason: str
    entry_index: int | None = None
    exit_index: int | None = None
    invalidation_index: int | None = None
    lifecycle: EntryLifecycle | None = None


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    signal_indices: list[int] = field(default_factory=list)
    orders: list[OrderRecord] = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    outcome_counts: dict[str, int] = field(default_factory=dict)

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


def _append_state(lifecycle: EntryLifecycle, state: SetupState, **changes) -> EntryLifecycle:
    return replace(
        lifecycle,
        state=state,
        state_history=lifecycle.state_history + (state,),
        **changes,
    )


def _pre_entry_invalidation(row: pd.Series, signal: Signal, config: BacktestConfig) -> str | None:
    strategy = config.strategy
    if signal.stop_loss is None or signal.entry_zone is None or signal.lifecycle is None:
        return None

    if strategy.invalidate_on_stop_level_breach:
        stop_breached = (
            row["low"] <= signal.stop_loss
            if signal.decision == Decision.BUY
            else row["high"] >= signal.stop_loss
        )
        if stop_breached:
            return "stop_level_breached_before_entry"

    structural_level = signal.lifecycle.structural_level_price
    if strategy.invalidate_on_structural_break and structural_level is not None:
        structure_broken = (
            row["close"] < structural_level
            if signal.decision == Decision.BUY
            else row["close"] > structural_level
        )
        if structure_broken:
            return "structural_break_before_entry"

    if strategy.invalidate_on_fvg_close_through:
        fvg_closed_through = (
            row["close"] < signal.entry_zone.low
            if signal.decision == Decision.BUY
            else row["close"] > signal.entry_zone.high
        )
        if fvg_closed_through:
            return "fvg_close_through_before_entry"
    return None


def _exit_trade(
    df: pd.DataFrame,
    entry_index: int,
    signal: Signal,
    config: BacktestConfig,
    signal_index: int = -1,
) -> Trade:
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
        adjusted_entry = signal.entry_price + config.slippage + config.spread_cost
        adjusted_exit = exit_price - config.slippage
        net_r = (adjusted_exit - adjusted_entry) / risk - config.commission_r
    else:
        adjusted_entry = signal.entry_price - config.slippage - config.spread_cost
        adjusted_exit = exit_price + config.slippage
        net_r = (adjusted_entry - adjusted_exit) / risk - config.commission_r
    r_multiple = net_r

    lifecycle = signal.lifecycle
    if lifecycle is not None:
        lifecycle = _append_state(
            lifecycle,
            SetupState.ENTRY_FILLED,
            entry_fill_index=entry_index,
            entry_fill_at=str(df.iloc[entry_index]["closed_at"]),
            outcome=EntryOutcome.ENTRY_FILLED,
        )
        lifecycle = _append_state(lifecycle, SetupState.TRADE_OPEN)
        lifecycle = _append_state(
            lifecycle,
            SetupState.TRADE_CLOSED,
            trade_exit_index=exit_index,
            trade_exit_at=str(df.iloc[exit_index]["closed_at"]),
        )

    return Trade(
        decision=signal.decision,
        signal_index=signal_index,
        entry_index=entry_index,
        exit_index=exit_index,
        entry_price=signal.entry_price,
        exit_price=exit_price,
        stop_loss=signal.stop_loss,
        target_price=target,
        r_multiple=r_multiple,
        exit_reason=exit_reason,
        order_activation_index=(
            signal.lifecycle.order_activation_index
            if signal.lifecycle is not None and signal.lifecycle.order_activation_index is not None
            else signal_index
        ),
        expiration_index=(
            signal.lifecycle.entry_expiration_index
            if signal.lifecycle is not None
            else None
        ),
        lifecycle=lifecycle,
    )


def run_backtest(
    df: pd.DataFrame,
    config: BacktestConfig,
    warmup_bars: int = 8,
    event_cache: StrategyEventCache | None = None,
) -> BacktestResult:
    trades: list[Trade] = []
    signals: list[Signal] = []
    signal_indices: list[int] = []
    orders: list[OrderRecord] = []
    rejection_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    event_cache = event_cache or build_strategy_event_cache(df)
    i = warmup_bars
    while i < len(df) - 1:
        signal = evaluate_signal_at(df, i, config.strategy, event_cache)
        signals.append(signal)
        signal_indices.append(i)
        if signal.decision == Decision.NO_TRADE:
            _record_rejections(rejection_counts, signal)
            i += 1
            continue

        lifecycle = signal.lifecycle
        activation_index = (
            lifecycle.order_activation_index
            if lifecycle is not None and lifecycle.order_activation_index is not None
            else i
        )
        first_eligible = max(
            i + 1,
            lifecycle.first_eligible_fill_index
            if lifecycle is not None and lifecycle.first_eligible_fill_index is not None
            else i + 1,
        )
        expiration_index = (
            lifecycle.entry_expiration_index
            if lifecycle is not None and lifecycle.entry_expiration_index is not None
            else activation_index + config.strategy.max_entry_wait_bars
        )
        last_available = min(expiration_index, len(df) - 1)
        terminal_index = last_available
        entry_index: int | None = None
        invalidation_index: int | None = None
        invalidation_reason: str | None = None

        for j in range(first_eligible, last_available + 1):
            invalidation_reason = _pre_entry_invalidation(df.iloc[j], signal, config)
            if invalidation_reason is not None:
                invalidation_index = j
                terminal_index = j
                break
            if _entry_touched(df.iloc[j], signal):
                entry_index = j
                terminal_index = j
                break

        if invalidation_index is not None and lifecycle is not None:
            reason = invalidation_reason or EntryOutcome.SETUP_INVALIDATED.value
            lifecycle = _append_state(
                lifecycle,
                SetupState.SETUP_INVALIDATED,
                structural_invalidation_index=invalidation_index,
                structural_invalidation_at=str(df.iloc[invalidation_index]["closed_at"]),
                outcome=EntryOutcome.SETUP_INVALIDATED,
            )
            outcome = EntryOutcome.SETUP_INVALIDATED
            orders.append(
                OrderRecord(
                    decision=signal.decision,
                    signal_index=i,
                    order_activation_index=activation_index,
                    first_eligible_fill_index=first_eligible,
                    expiration_index=expiration_index,
                    outcome_index=terminal_index,
                    outcome=outcome,
                    reason=reason,
                    invalidation_index=invalidation_index,
                    lifecycle=lifecycle,
                )
            )
            outcome_counts[outcome.value] = outcome_counts.get(outcome.value, 0) + 1
            outcome_counts[reason] = outcome_counts.get(reason, 0) + 1
            i = terminal_index + 1
            continue

        if entry_index is not None:
            trade = _exit_trade(df, entry_index, signal, config, signal_index=i)
            trades.append(trade)
            outcome = EntryOutcome.ENTRY_FILLED
            orders.append(
                OrderRecord(
                    decision=signal.decision,
                    signal_index=i,
                    order_activation_index=activation_index,
                    first_eligible_fill_index=first_eligible,
                    expiration_index=expiration_index,
                    outcome_index=entry_index,
                    outcome=outcome,
                    reason=outcome.value,
                    entry_index=entry_index,
                    exit_index=trade.exit_index,
                    lifecycle=trade.lifecycle,
                )
            )
            outcome_counts[outcome.value] = outcome_counts.get(outcome.value, 0) + 1
            i = max(trade.exit_index + 1, i + 1)
            continue

        if expiration_index <= len(df) - 1:
            outcome = EntryOutcome.ENTRY_EXPIRED
            if lifecycle is not None:
                lifecycle = _append_state(
                    lifecycle,
                    SetupState.ENTRY_EXPIRED,
                    entry_expiration_at=str(df.iloc[expiration_index]["closed_at"]),
                    outcome=outcome,
                )
        else:
            outcome = EntryOutcome.ENTRY_NOT_REACHED
            if lifecycle is not None:
                lifecycle = replace(lifecycle, outcome=outcome)
        orders.append(
            OrderRecord(
                decision=signal.decision,
                signal_index=i,
                order_activation_index=activation_index,
                first_eligible_fill_index=first_eligible,
                expiration_index=expiration_index,
                outcome_index=terminal_index,
                outcome=outcome,
                reason=outcome.value,
                lifecycle=lifecycle,
            )
        )
        outcome_counts[outcome.value] = outcome_counts.get(outcome.value, 0) + 1
        i = terminal_index + 1

    return BacktestResult(
        trades=trades,
        signals=signals,
        signal_indices=signal_indices,
        orders=orders,
        rejection_counts=rejection_counts,
        outcome_counts=outcome_counts,
    )
