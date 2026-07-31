from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .backtest import BacktestConfig, BacktestResult, run_backtest
from .strategy import (
    StrategyEventCache,
    _risk_reward,
    _target_for_long,
    _target_for_short,
    build_strategy_event_cache,
)
from .types import Decision, EntryOutcome, HtfBias


FUNNEL_STAGES = (
    "bars_evaluated",
    "accepted_htf_bias",
    "confirmed_liquidity_raids",
    "confirmed_sweeps",
    "directional_mss",
    "valid_post_mss_fvg",
    "pending_entry_order_created",
    "target_available",
    "structural_stop_available",
    "minimum_rr_passed",
    "pending_order_activated",
    "entry_filled",
    "entry_expired",
    "setup_invalidated",
    "trade_closed",
)

STAGE_PARENT = {
    "bars_evaluated": None,
    "accepted_htf_bias": "bars_evaluated",
    "confirmed_liquidity_raids": "accepted_htf_bias",
    "confirmed_sweeps": "confirmed_liquidity_raids",
    "directional_mss": "confirmed_sweeps",
    "valid_post_mss_fvg": "directional_mss",
    "pending_entry_order_created": "valid_post_mss_fvg",
    "target_available": "pending_entry_order_created",
    "structural_stop_available": "target_available",
    "minimum_rr_passed": "structural_stop_available",
    "pending_order_activated": "minimum_rr_passed",
    "entry_filled": "pending_order_activated",
    "entry_expired": "pending_order_activated",
    "setup_invalidated": "pending_order_activated",
    "trade_closed": "entry_filled",
}


@dataclass(frozen=True)
class FunnelStage:
    name: str
    count: int
    previous_stage: str | None
    percent_from_previous: float
    percent_from_initial: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "count": self.count,
            "previous_stage": self.previous_stage,
            "percent_from_previous": self.percent_from_previous,
            "percent_from_initial": self.percent_from_initial,
        }


@dataclass(frozen=True)
class DirectionFunnel:
    direction: str
    stages: tuple[FunnelStage, ...]

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def count(self, stage_name: str) -> int:
        return next(stage.count for stage in self.stages if stage.name == stage_name)


@dataclass(frozen=True)
class RuleFunnelReport:
    dataset: dict
    configuration: dict
    directions: dict[str, DirectionFunnel]
    ranked_codes: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "configuration": self.configuration,
            "directions": {
                name: funnel.to_dict() for name, funnel in self.directions.items()
            },
            "ranked_rejection_outcome_codes": list(self.ranked_codes),
        }

    def to_text(self) -> str:
        lines = [
            "AurumFlow rule funnel",
            (
                f"Dataset: {self.dataset['bars']} bars | "
                f"{self.dataset['start']} to {self.dataset['end']} | "
                f"duration {self.dataset['duration']}"
            ),
            (
                f"Mode: {self.configuration['mode']} | "
                f"HTF bias: {self.configuration['htf_bias']} | "
                f"max wait: {self.configuration['max_entry_wait_bars']} bars | "
                f"max hold: {self.configuration['max_holding_bars']} bars"
            ),
            (
                f"Costs: spread={self.configuration['spread_cost']}, "
                f"slippage={self.configuration['slippage']}, "
                f"commission_r={self.configuration['commission_r']}"
            ),
        ]
        for direction in ("LONG", "SHORT", "COMBINED"):
            lines.extend(["", direction, "stage                              count   previous%   initial%"])
            for stage in self.directions[direction].stages:
                lines.append(
                    f"{stage.name:<34} {stage.count:>5}   "
                    f"{stage.percent_from_previous:>8.2f}%   "
                    f"{stage.percent_from_initial:>7.2f}%"
                )
        lines.extend(["", "Ranked rejection/outcome codes"])
        if not self.ranked_codes:
            lines.append("none")
        else:
            for item in self.ranked_codes:
                lines.append(f"{item['count']:>5}  {item['code']}")
        return "\n".join(lines)


def _empty_counts() -> dict[str, int]:
    return {stage: 0 for stage in FUNNEL_STAGES}


def _accepted_bias(decision: Decision, htf_bias: HtfBias) -> bool:
    return (decision == Decision.BUY and htf_bias == HtfBias.BULLISH) or (
        decision == Decision.SELL and htf_bias == HtfBias.BEARISH
    )


def _scan_rule_stages(
    config: BacktestConfig,
    evaluated_indices: Iterable[int],
    decision: Decision,
    event_cache: StrategyEventCache,
) -> dict[str, int]:
    counts = _empty_counts()
    if decision == Decision.BUY:
        raid_direction = "sell_side"
        mss_direction = "bullish"
        fvg_direction = "bullish"
    else:
        raid_direction = "buy_side"
        mss_direction = "bearish"
        fvg_direction = "bearish"

    for index in evaluated_indices:
        counts["bars_evaluated"] += 1
        if not _accepted_bias(decision, config.strategy.htf_bias):
            continue
        counts["accepted_htf_bias"] += 1

        raid = event_cache.latest_confirmed_raids[raid_direction][index]
        if raid is None:
            continue
        # In v1 a confirmed directional raid is the confirmed-sweep primitive.
        counts["confirmed_liquidity_raids"] += 1
        counts["confirmed_sweeps"] += 1
        mss = event_cache.latest_directional_mss[mss_direction][index]
        if mss is None:
            continue
        counts["directional_mss"] += 1

        fvg = event_cache.fvg_by_end.get((fvg_direction, index))
        if fvg is None or fvg.end_index <= mss.break_index:
            continue
        counts["valid_post_mss_fvg"] += 1
        counts["pending_entry_order_created"] += 1
        entry = fvg.midpoint

        if decision == Decision.BUY:
            target = _target_for_long(
                event_cache.swings, entry, mss.swing_index, fvg.created_at
            )
            stop = raid.level_price - config.strategy.spread_buffer
        else:
            target = _target_for_short(
                event_cache.swings, entry, mss.swing_index, fvg.created_at
            )
            stop = raid.level_price + config.strategy.spread_buffer
        if target is None:
            continue
        counts["target_available"] += 1

        if abs(entry - stop) < config.strategy.min_stop_distance:
            continue
        counts["structural_stop_available"] += 1

        if _risk_reward(decision, entry, stop, target) < config.strategy.min_risk_reward:
            continue
        counts["minimum_rr_passed"] += 1

    return counts


def _apply_execution_counts(
    counts: dict[str, int],
    result: BacktestResult,
    decision: Decision,
) -> None:
    orders = [order for order in result.orders if order.decision == decision]
    counts["pending_order_activated"] = len(orders)
    counts["entry_filled"] = sum(
        order.outcome == EntryOutcome.ENTRY_FILLED for order in orders
    )
    counts["entry_expired"] = sum(
        order.outcome == EntryOutcome.ENTRY_EXPIRED for order in orders
    )
    counts["setup_invalidated"] = sum(
        order.outcome == EntryOutcome.SETUP_INVALIDATED for order in orders
    )
    counts["trade_closed"] = sum(trade.decision == decision for trade in result.trades)


def _percentage(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 2) if denominator else 0.0


def _build_funnel(direction: str, counts: dict[str, int]) -> DirectionFunnel:
    initial = counts["bars_evaluated"]
    stages = []
    for name in FUNNEL_STAGES:
        parent = STAGE_PARENT[name]
        parent_count = counts[parent] if parent is not None else counts[name]
        stages.append(
            FunnelStage(
                name=name,
                count=counts[name],
                previous_stage=parent,
                percent_from_previous=_percentage(counts[name], parent_count),
                percent_from_initial=_percentage(counts[name], initial),
            )
        )
    return DirectionFunnel(direction=direction, stages=tuple(stages))


def _dataset_summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "bars": 0,
            "start": "",
            "end": "",
            "duration": "0 days 00:00:00",
            "duration_seconds": 0.0,
        }
    start = pd.Timestamp(df.iloc[0]["timestamp"])
    end = pd.Timestamp(df.iloc[-1]["closed_at"])
    duration = end - start
    return {
        "bars": len(df),
        "start": str(start),
        "end": str(end),
        "duration": str(duration),
        "duration_seconds": duration.total_seconds(),
    }


def run_rule_funnel(
    df: pd.DataFrame,
    config: BacktestConfig,
    warmup_bars: int = 8,
) -> RuleFunnelReport:
    event_cache = build_strategy_event_cache(df)
    result = run_backtest(
        df, config, warmup_bars=warmup_bars, event_cache=event_cache
    )
    long_counts = _scan_rule_stages(
        config, result.signal_indices, Decision.BUY, event_cache
    )
    short_counts = _scan_rule_stages(
        config, result.signal_indices, Decision.SELL, event_cache
    )
    _apply_execution_counts(long_counts, result, Decision.BUY)
    _apply_execution_counts(short_counts, result, Decision.SELL)
    combined_counts = {
        stage: long_counts[stage] + short_counts[stage] for stage in FUNNEL_STAGES
    }

    ranked = Counter(result.rejection_counts)
    ranked.update(result.outcome_counts)
    ranked_codes = tuple(
        {"code": code, "count": count}
        for code, count in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))
    )
    return RuleFunnelReport(
        dataset=_dataset_summary(df),
        configuration={
            "mode": config.strategy.operating_mode.value,
            "htf_bias": config.strategy.htf_bias.value,
            "entry_model": config.strategy.entry_model.value,
            "execution_model": config.strategy.execution_model.value,
            "max_entry_wait_bars": config.strategy.max_entry_wait_bars,
            "max_holding_bars": config.max_holding_bars,
            "min_risk_reward": config.strategy.min_risk_reward,
            "stop_buffer": config.strategy.spread_buffer,
            "spread_cost": config.spread_cost,
            "slippage": config.slippage,
            "commission_r": config.commission_r,
        },
        directions={
            "LONG": _build_funnel("LONG", long_counts),
            "SHORT": _build_funnel("SHORT", short_counts),
            "COMBINED": _build_funnel("COMBINED", combined_counts),
        },
        ranked_codes=ranked_codes,
    )
