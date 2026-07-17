"""Isolated FVG entry-geometry experiments for the RULE_ONLY strategy.

This module deliberately lives outside ``xauusd_signal`` and is excluded by
the package discovery rule in ``pyproject.toml``. It reuses production event,
target, stop, lifecycle, and exit helpers while varying only the deterministic
price selected inside the already-detected FVG.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from statistics import fmean, median
from typing import cast

import pandas as pd

from xauusd_signal.backtest import (
    BacktestConfig,
    BacktestResult,
    OrderRecord,
    Trade,
    _append_state,
    _entry_touched,
    _exit_trade,
    _pre_entry_invalidation,
    _record_rejections,
)
from xauusd_signal.data import load_ohlcv_csv
from xauusd_signal.events import FairValueGap
from xauusd_signal.strategy import (
    StrategyConfig,
    StrategyEventCache,
    _base_no_trade,
    _risk_reward,
    _rule_confidence,
    _target_for_long,
    _target_for_short,
    build_strategy_event_cache,
)
from xauusd_signal.types import (
    Decision,
    EntryLifecycle,
    EntryModel,
    EntryOutcome,
    EntryZone,
    HtfBias,
    MarketRegime,
    ModelPrediction,
    OperatingMode,
    SetupState,
    Signal,
    TakeProfit,
)


class ResearchEntryModel(StrEnum):
    """FVG depth measured from the distal edge toward the proximal edge."""

    DISTAL_EDGE = "FVG_DISTAL_EDGE"
    PERCENT_25 = "FVG_25_PERCENT"
    MIDPOINT = "FVG_MIDPOINT"
    PERCENT_75 = "FVG_75_PERCENT"
    PROXIMAL_EDGE = "FVG_PROXIMAL_EDGE"

    @property
    def label(self) -> str:
        return self.value.removeprefix("FVG_")

    @property
    def distal_fraction(self) -> float:
        return {
            ResearchEntryModel.DISTAL_EDGE: 0.0,
            ResearchEntryModel.PERCENT_25: 0.25,
            ResearchEntryModel.MIDPOINT: 0.50,
            ResearchEntryModel.PERCENT_75: 0.75,
            ResearchEntryModel.PROXIMAL_EDGE: 1.0,
        }[self]


@dataclass(frozen=True)
class GeometryCandidate:
    model: ResearchEntryModel
    direction: Decision
    activation_index: int
    activation_at: str
    entry_price: float
    stop_loss: float
    target_price: float
    stop_distance: float
    target_distance: float
    risk_reward: float
    passes_minimum_rr: bool

    @property
    def year(self) -> int:
        return pd.Timestamp(self.activation_at).year


@dataclass(frozen=True)
class GeometryRun:
    model: ResearchEntryModel
    bias: HtfBias
    candidates: tuple[GeometryCandidate, ...]
    zero_cost: BacktestResult
    research_cost: BacktestResult


@dataclass(frozen=True)
class GeometrySummary:
    model: str
    direction: str
    period: str
    cost_scenario: str
    candidates: int
    rr_passes: int
    average_rr: float
    median_rr: float
    average_stop_distance: float
    average_target_distance: float
    orders: int
    fill_rate: float
    expiration_rate: float
    invalidation_rate: float
    closed_trades: int
    expectancy: float
    profit_factor: float | None
    max_drawdown_r: float


@dataclass(frozen=True)
class CommonCandidateSummary:
    model: str
    direction: str
    common_candidates: int
    rr_passes: int
    average_rr: float
    median_rr: float
    average_stop_distance: float
    average_target_distance: float


def entry_price_for_model(
    fvg: FairValueGap,
    model: ResearchEntryModel,
) -> float:
    """Return a directional FVG price at a distal-to-proximal depth."""

    fraction = model.distal_fraction
    if fvg.direction == "bullish":
        return fvg.low + fraction * (fvg.high - fvg.low)
    if fvg.direction == "bearish":
        return fvg.high - fraction * (fvg.high - fvg.low)
    raise ValueError(f"Unsupported FVG direction: {fvg.direction}")


def _validate_research_config(config: StrategyConfig) -> None:
    if config.operating_mode != OperatingMode.RULE_ONLY:
        raise ValueError("Entry-geometry research is restricted to RULE_ONLY.")
    if config.htf_bias == HtfBias.NEUTRAL:
        raise ValueError("A fixed BULLISH or BEARISH research bias is required.")
    if config.entry_model != EntryModel.FVG_MIDPOINT:
        raise ValueError("The production entry model must remain FVG_MIDPOINT.")


def _research_lifecycle_model(model: ResearchEntryModel) -> EntryModel:
    if model == ResearchEntryModel.MIDPOINT:
        return EntryModel.FVG_MIDPOINT
    # Research enums are intentionally not added to the production EntryModel.
    return cast(EntryModel, model)


def _no_trade(
    df: pd.DataFrame,
    config: StrategyConfig,
    model: ResearchEntryModel,
    reasons: list[str],
    explanation: str,
    activation_index: int,
) -> Signal:
    signal = _base_no_trade(
        df,
        config,
        reasons,
        ModelPrediction.unavailable(),
        explanation,
        activation_index,
    )
    if model == ResearchEntryModel.MIDPOINT or signal.lifecycle is None:
        return signal
    return replace(
        signal,
        lifecycle=replace(
            signal.lifecycle,
            entry_model=_research_lifecycle_model(model),
        ),
    )


def evaluate_entry_geometry_at(
    df: pd.DataFrame,
    activation_index: int,
    config: StrategyConfig,
    cache: StrategyEventCache,
    model: ResearchEntryModel,
) -> tuple[Signal, GeometryCandidate | None]:
    """Evaluate one causal bar while changing only the FVG entry price."""

    _validate_research_config(config)
    if activation_index < 7:
        return (
            _no_trade(
                df,
                config,
                model,
                ["insufficient_data"],
                "Not enough closed candles.",
                activation_index,
            ),
            None,
        )

    if config.htf_bias == HtfBias.BULLISH:
        decision = Decision.BUY
        raid_direction = "sell_side"
        mss_direction = "bullish"
        fvg_direction = "bullish"
        setup_name = "SweepMssFvgRetraceLong"
        invalidation = (
            "Close below swept sell-side liquidity or stop-loss invalidates "
            "the long setup."
        )
    else:
        decision = Decision.SELL
        raid_direction = "buy_side"
        mss_direction = "bearish"
        fvg_direction = "bearish"
        setup_name = "SweepMssFvgRetraceShort"
        invalidation = (
            "Close above swept buy-side liquidity or stop-loss invalidates "
            "the short setup."
        )

    raid = cache.latest_confirmed_raids[raid_direction][activation_index]
    if raid is None:
        return (
            _no_trade(
                df,
                config,
                model,
                ["no_liquidity_raid", "sweep_not_confirmed"],
                "No confirmed liquidity sweep.",
                activation_index,
            ),
            None,
        )

    mss = cache.latest_directional_mss[mss_direction][activation_index]
    if mss is None:
        return (
            _no_trade(
                df,
                config,
                model,
                ["no_mss_body_close"],
                "No body-close MSS after sweep.",
                activation_index,
            ),
            None,
        )

    fvg = cache.fvg_by_end.get((fvg_direction, activation_index))
    if fvg is not None and fvg.end_index <= mss.break_index:
        fvg = None
    if fvg is None:
        return (
            _no_trade(
                df,
                config,
                model,
                ["no_valid_fvg"],
                "No valid FVG after MSS.",
                activation_index,
            ),
            None,
        )

    entry = entry_price_for_model(fvg, model)
    if decision == Decision.BUY:
        stop = raid.level_price - config.spread_buffer
        target = _target_for_long(
            cache.swings,
            entry,
            mss.swing_index,
            fvg.created_at,
        )
    else:
        stop = raid.level_price + config.spread_buffer
        target = _target_for_short(
            cache.swings,
            entry,
            mss.swing_index,
            fvg.created_at,
        )

    if target is None:
        return (
            _no_trade(
                df,
                config,
                model,
                ["target_unavailable"],
                "No opposing liquidity target is available.",
                activation_index,
            ),
            None,
        )

    stop_distance = abs(entry - stop)
    if stop_distance < config.min_stop_distance:
        return (
            _no_trade(
                df,
                config,
                model,
                ["stop_unavailable"],
                "Structural stop distance is too small for stable testing.",
                activation_index,
            ),
            None,
        )

    target_distance = (
        target - entry if decision == Decision.BUY else entry - target
    )
    risk_reward = _risk_reward(decision, entry, stop, target)
    candidate = GeometryCandidate(
        model=model,
        direction=decision,
        activation_index=activation_index,
        activation_at=str(df.iloc[activation_index]["closed_at"]),
        entry_price=entry,
        stop_loss=stop,
        target_price=target,
        stop_distance=stop_distance,
        target_distance=target_distance,
        risk_reward=risk_reward,
        passes_minimum_rr=risk_reward >= config.min_risk_reward,
    )
    if not candidate.passes_minimum_rr:
        return (
            _no_trade(
                df,
                config,
                model,
                ["risk_reward_below_minimum"],
                "Risk-to-reward is below the configured minimum.",
                activation_index,
            ),
            candidate,
        )

    valid_reasons = [
        "htf_bias_aligned",
        "confirmed_sweep",
        "mss_body_close",
        "valid_post_mss_fvg",
        "risk_reward_accepted",
    ]
    confidence = _rule_confidence(valid_reasons)
    if confidence < config.min_confidence:
        return (
            _no_trade(
                df,
                config,
                model,
                ["confidence_below_threshold"],
                "Confidence is below threshold.",
                activation_index,
            ),
            candidate,
        )

    tp1 = (
        entry + (entry - stop)
        if decision == Decision.BUY
        else entry - (stop - entry)
    )
    activation_at = str(fvg.created_at)
    lifecycle = EntryLifecycle(
        state=SetupState.ENTRY_PENDING,
        state_history=(SetupState.SETUP_FORMING, SetupState.ENTRY_PENDING),
        execution_model=config.execution_model,
        entry_model=_research_lifecycle_model(model),
        sweep_index=raid.raid_index,
        sweep_confirmed_at=str(raid.detected_at),
        mss_index=mss.break_index,
        mss_confirmed_at=str(mss.detected_at),
        fvg_start_index=fvg.start_index,
        fvg_end_index=fvg.end_index,
        fvg_created_at=activation_at,
        structural_level_price=raid.level_price,
        order_activation_index=activation_index,
        order_activation_at=activation_at,
        first_eligible_fill_index=activation_index + 1,
        entry_expiration_index=activation_index + config.max_entry_wait_bars,
    )
    entry_type = (
        "FVG_MIDPOINT_LIMIT"
        if model == ResearchEntryModel.MIDPOINT
        else f"{model.value}_LIMIT"
    )
    signal = Signal(
        decision=decision,
        operating_mode=config.operating_mode,
        timestamp=str(df.iloc[activation_index]["closed_at"]),
        setup_name=setup_name,
        entry_type=entry_type,
        entry_price=entry,
        entry_zone=EntryZone(low=fvg.low, high=fvg.high),
        stop_loss=stop,
        take_profit=[
            TakeProfit("TP1_1R", tp1),
            TakeProfit("TP2_LIQUIDITY", target),
        ],
        risk_reward=risk_reward,
        confidence=confidence,
        ml=ModelPrediction.unavailable(),
        htf_bias=config.htf_bias,
        market_regime=MarketRegime.REVERSAL_CANDIDATE,
        confluences=[
            "confirmed_sweep",
            "mss_body_close",
            "post_mss_fvg",
            "opposing_liquidity_target",
        ],
        structural_invalidation=invalidation,
        explanation=f"{setup_name} is valid under {config.operating_mode.value}.",
        valid_reasons=valid_reasons,
        rejection_reasons=[],
        research_only=False,
        lifecycle=lifecycle,
    )
    return signal, candidate


def scan_geometry_candidates(
    df: pd.DataFrame,
    config: StrategyConfig,
    cache: StrategyEventCache,
    model: ResearchEntryModel,
    warmup_bars: int = 8,
) -> tuple[GeometryCandidate, ...]:
    """Scan a common all-bar opportunity universe without execution skipping."""

    candidates: list[GeometryCandidate] = []
    for index in range(warmup_bars, len(df) - 1):
        _, candidate = evaluate_entry_geometry_at(
            df,
            index,
            config,
            cache,
            model,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def run_entry_geometry_backtest(
    df: pd.DataFrame,
    config: BacktestConfig,
    model: ResearchEntryModel,
    warmup_bars: int = 8,
    event_cache: StrategyEventCache | None = None,
) -> BacktestResult:
    """Replay one geometry using the production no-overlap lifecycle."""

    _validate_research_config(config.strategy)
    trades: list[Trade] = []
    signals: list[Signal] = []
    signal_indices: list[int] = []
    orders: list[OrderRecord] = []
    rejection_counts: dict[str, int] = {}
    outcome_counts: dict[str, int] = {}
    cache = event_cache or build_strategy_event_cache(df)
    i = warmup_bars

    while i < len(df) - 1:
        signal, _ = evaluate_entry_geometry_at(
            df,
            i,
            config.strategy,
            cache,
            model,
        )
        signals.append(signal)
        signal_indices.append(i)
        if signal.decision == Decision.NO_TRADE:
            _record_rejections(rejection_counts, signal)
            i += 1
            continue

        lifecycle = signal.lifecycle
        activation_index = (
            lifecycle.order_activation_index
            if lifecycle is not None
            and lifecycle.order_activation_index is not None
            else i
        )
        first_eligible = max(
            i + 1,
            lifecycle.first_eligible_fill_index
            if lifecycle is not None
            and lifecycle.first_eligible_fill_index is not None
            else i + 1,
        )
        expiration_index = (
            lifecycle.entry_expiration_index
            if lifecycle is not None
            and lifecycle.entry_expiration_index is not None
            else activation_index + config.strategy.max_entry_wait_bars
        )
        last_available = min(expiration_index, len(df) - 1)
        terminal_index = last_available
        entry_index: int | None = None
        invalidation_index: int | None = None
        invalidation_reason: str | None = None

        for index in range(first_eligible, last_available + 1):
            invalidation_reason = _pre_entry_invalidation(
                df.iloc[index],
                signal,
                config,
            )
            if invalidation_reason is not None:
                invalidation_index = index
                terminal_index = index
                break
            if _entry_touched(df.iloc[index], signal):
                entry_index = index
                terminal_index = index
                break

        if invalidation_index is not None and lifecycle is not None:
            reason = invalidation_reason or EntryOutcome.SETUP_INVALIDATED.value
            lifecycle = _append_state(
                lifecycle,
                SetupState.SETUP_INVALIDATED,
                structural_invalidation_index=invalidation_index,
                structural_invalidation_at=str(
                    df.iloc[invalidation_index]["closed_at"]
                ),
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
            outcome_counts[outcome.value] = (
                outcome_counts.get(outcome.value, 0) + 1
            )
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
            outcome_counts[outcome.value] = (
                outcome_counts.get(outcome.value, 0) + 1
            )
            i = max(trade.exit_index + 1, i + 1)
            continue

        if expiration_index <= len(df) - 1:
            outcome = EntryOutcome.ENTRY_EXPIRED
            if lifecycle is not None:
                lifecycle = _append_state(
                    lifecycle,
                    SetupState.ENTRY_EXPIRED,
                    entry_expiration_at=str(
                        df.iloc[expiration_index]["closed_at"]
                    ),
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


def apply_research_costs(
    result: BacktestResult,
    spread_cost: float = 0.20,
    slippage: float = 0.10,
    commission_r: float = 0.01,
) -> BacktestResult:
    """Reprice a zero-cost replay; costs do not alter lifecycle timing."""

    trades = []
    for trade in result.trades:
        risk = abs(trade.entry_price - trade.stop_loss)
        cost_r = (spread_cost + 2 * slippage) / risk + commission_r
        trades.append(replace(trade, r_multiple=trade.r_multiple - cost_r))
    return replace(result, trades=trades)


def run_entry_geometry_research(
    df: pd.DataFrame,
    strategy: StrategyConfig,
    model: ResearchEntryModel,
    max_holding_bars: int = 48,
    event_cache: StrategyEventCache | None = None,
) -> GeometryRun:
    """Run common-universe geometry and production-equivalent execution views."""

    _validate_research_config(strategy)
    cache = event_cache or build_strategy_event_cache(df)
    candidates = scan_geometry_candidates(df, strategy, cache, model)
    zero_cost = run_entry_geometry_backtest(
        df,
        BacktestConfig(
            strategy=strategy,
            spread_cost=0.0,
            slippage=0.0,
            commission_r=0.0,
            max_holding_bars=max_holding_bars,
        ),
        model,
        event_cache=cache,
    )
    return GeometryRun(
        model=model,
        bias=strategy.htf_bias,
        candidates=candidates,
        zero_cost=zero_cost,
        research_cost=apply_research_costs(zero_cost),
    )


def summarize_geometry_run(
    run: GeometryRun,
    cost_scenario: str = "research",
    year: int | None = None,
) -> GeometrySummary:
    """Summarize candidates and activation-cohort execution outcomes."""

    if cost_scenario not in {"zero", "research"}:
        raise ValueError("cost_scenario must be 'zero' or 'research'.")
    result = run.research_cost if cost_scenario == "research" else run.zero_cost
    signal_years = {
        index: pd.Timestamp(signal.timestamp).year
        for index, signal in zip(
            result.signal_indices,
            result.signals,
            strict=True,
        )
    }
    candidates = [
        candidate
        for candidate in run.candidates
        if year is None or candidate.year == year
    ]
    orders = [
        order
        for order in result.orders
        if year is None or signal_years[order.signal_index] == year
    ]
    trades = [
        trade
        for trade in result.trades
        if year is None or signal_years[trade.signal_index] == year
    ]
    performance = BacktestResult(trades=trades)

    def rate(outcome: EntryOutcome) -> float:
        if not orders:
            return 0.0
        return sum(order.outcome == outcome for order in orders) / len(orders)

    rr_values = [candidate.risk_reward for candidate in candidates]
    stops = [candidate.stop_distance for candidate in candidates]
    targets = [candidate.target_distance for candidate in candidates]
    return GeometrySummary(
        model=run.model.label,
        direction="LONG" if run.bias == HtfBias.BULLISH else "SHORT",
        period="ALL" if year is None else str(year),
        cost_scenario=cost_scenario,
        candidates=len(candidates),
        rr_passes=sum(candidate.passes_minimum_rr for candidate in candidates),
        average_rr=fmean(rr_values) if rr_values else 0.0,
        median_rr=median(rr_values) if rr_values else 0.0,
        average_stop_distance=fmean(stops) if stops else 0.0,
        average_target_distance=fmean(targets) if targets else 0.0,
        orders=len(orders),
        fill_rate=rate(EntryOutcome.ENTRY_FILLED),
        expiration_rate=rate(EntryOutcome.ENTRY_EXPIRED),
        invalidation_rate=rate(EntryOutcome.SETUP_INVALIDATED),
        closed_trades=len(trades),
        expectancy=performance.expectancy,
        profit_factor=performance.profit_factor,
        max_drawdown_r=performance.max_drawdown_r,
    )


def summarize_common_candidate_cohort(
    runs: list[GeometryRun],
) -> list[CommonCandidateSummary]:
    """Compare geometry on activation bars eligible under every model."""

    if not runs:
        return []
    biases = {run.bias for run in runs}
    if len(biases) != 1:
        raise ValueError("Common candidate cohorts must use one fixed bias.")
    candidate_maps = {
        run.model: {
            candidate.activation_index: candidate
            for candidate in run.candidates
        }
        for run in runs
    }
    common_indices = set.intersection(
        *(set(candidates) for candidates in candidate_maps.values())
    )
    direction = "LONG" if runs[0].bias == HtfBias.BULLISH else "SHORT"
    summaries = []
    for run in runs:
        candidates = [
            candidate_maps[run.model][index]
            for index in sorted(common_indices)
        ]
        rr_values = [candidate.risk_reward for candidate in candidates]
        stops = [candidate.stop_distance for candidate in candidates]
        targets = [candidate.target_distance for candidate in candidates]
        summaries.append(
            CommonCandidateSummary(
                model=run.model.label,
                direction=direction,
                common_candidates=len(candidates),
                rr_passes=sum(
                    candidate.passes_minimum_rr for candidate in candidates
                ),
                average_rr=fmean(rr_values) if rr_values else 0.0,
                median_rr=median(rr_values) if rr_values else 0.0,
                average_stop_distance=fmean(stops) if stops else 0.0,
                average_target_distance=fmean(targets) if targets else 0.0,
            )
        )
    return summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated AurumFlow FVG entry-geometry research."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument(
        "--htf-bias",
        choices=[HtfBias.BULLISH.value, HtfBias.BEARISH.value, "BOTH"],
        default="BOTH",
    )
    parser.add_argument("--source-timezone")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    df = load_ohlcv_csv(args.csv, source_timezone=args.source_timezone)
    cache = build_strategy_event_cache(df)
    biases = (
        [HtfBias.BULLISH, HtfBias.BEARISH]
        if args.htf_bias == "BOTH"
        else [HtfBias(args.htf_bias)]
    )
    summaries = []
    common_candidate_cohorts = []
    for bias in biases:
        strategy = StrategyConfig(
            operating_mode=OperatingMode.RULE_ONLY,
            htf_bias=bias,
        )
        runs = []
        for model in ResearchEntryModel:
            run = run_entry_geometry_research(
                df,
                strategy,
                model,
                event_cache=cache,
            )
            runs.append(run)
            for cost_scenario in ("zero", "research"):
                summaries.append(
                    asdict(
                        summarize_geometry_run(
                            run,
                            cost_scenario=cost_scenario,
                        )
                    )
                )
                for year in range(2023, 2027):
                    summaries.append(
                        asdict(
                            summarize_geometry_run(
                                run,
                                cost_scenario=cost_scenario,
                                year=year,
                            )
                        )
                    )
        common_candidate_cohorts.extend(
            asdict(summary)
            for summary in summarize_common_candidate_cohort(runs)
        )
    print(
        json.dumps(
            {
                "configuration": {
                    "entry_depth": "distal_to_proximal",
                    "minimum_risk_reward": 2.0,
                    "maximum_entry_wait_bars": 8,
                    "maximum_holding_bars": 48,
                    "research_costs": {
                        "spread": 0.20,
                        "slippage_per_side": 0.10,
                        "commission_r": 0.01,
                    },
                },
                "summaries": summaries,
                "common_candidate_cohorts": common_candidate_cohorts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
