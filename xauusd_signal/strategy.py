from __future__ import annotations

import heapq
from dataclasses import dataclass

import pandas as pd

from .events import (
    FairValueGap,
    LiquidityRaid,
    StructureBreak,
    Swing,
    detect_fvgs,
    detect_liquidity_raids,
    detect_mss,
    detect_swings,
)
from .types import (
    Decision,
    EntryLifecycle,
    EntryModel,
    EntryZone,
    ExecutionModel,
    HtfBias,
    MLDirection,
    MarketRegime,
    ModelPrediction,
    OperatingMode,
    SetupState,
    Signal,
    TakeProfit,
)


RULE_CONFIDENCE_WEIGHTS = {
    "htf_bias_aligned": 0.20,
    "confirmed_sweep": 0.20,
    "mss_body_close": 0.20,
    "valid_post_mss_fvg": 0.20,
    "risk_reward_accepted": 0.20,
}


@dataclass(frozen=True)
class StrategyConfig:
    operating_mode: OperatingMode = OperatingMode.RULE_ONLY
    htf_bias: HtfBias = HtfBias.NEUTRAL
    min_risk_reward: float = 2.0
    min_confidence: float = 0.70
    spread_buffer: float = 0.10
    min_stop_distance: float = 0.50
    hybrid_validated_enabled: bool = False
    hybrid_validated_behavior: str | None = None
    execution_model: ExecutionModel = ExecutionModel.PENDING_LIMIT_AFTER_FVG_CREATION
    entry_model: EntryModel = EntryModel.FVG_MIDPOINT
    max_entry_wait_bars: int = 8
    invalidate_on_structural_break: bool = True
    invalidate_on_stop_level_breach: bool = True
    invalidate_on_fvg_close_through: bool = True

    def __post_init__(self) -> None:
        if self.max_entry_wait_bars < 1:
            raise ValueError("max_entry_wait_bars must be at least 1")


@dataclass(frozen=True)
class StrategyEventCache:
    swings: tuple[Swing, ...]
    raids: tuple[LiquidityRaid, ...]
    breaks: tuple[StructureBreak, ...]
    fvgs: tuple[FairValueGap, ...]
    latest_confirmed_raids: dict[str, tuple[LiquidityRaid | None, ...]]
    latest_directional_mss: dict[str, tuple[StructureBreak | None, ...]]
    fvg_by_end: dict[tuple[str, int], FairValueGap]


def build_strategy_event_cache(df: pd.DataFrame) -> StrategyEventCache:
    swings = detect_swings(df)
    raids = detect_liquidity_raids(df, swings)
    breaks = detect_mss(df, swings, raids)
    fvgs = detect_fvgs(df)

    raids_by_index: dict[int, list[LiquidityRaid]] = {}
    for raid in raids:
        if raid.confirmed:
            raids_by_index.setdefault(raid.raid_index, []).append(raid)

    breaks_by_index: dict[int, list[tuple[int, StructureBreak]]] = {}
    for sequence, event in enumerate(breaks):
        breaks_by_index.setdefault(event.break_index, []).append((sequence, event))

    latest_raids: dict[str, list[LiquidityRaid | None]] = {
        "buy_side": [],
        "sell_side": [],
    }
    latest_mss: dict[str, list[StructureBreak | None]] = {
        "bullish": [],
        "bearish": [],
    }
    current_raids: dict[str, LiquidityRaid | None] = {
        "buy_side": None,
        "sell_side": None,
    }
    active_breaks: dict[str, list[tuple[int, int, StructureBreak]]] = {
        "bullish": [],
        "bearish": [],
    }

    for index in range(len(df)):
        for raid in raids_by_index.get(index, []):
            current_raids[raid.direction] = raid
        for sequence, event in breaks_by_index.get(index, []):
            origin = event.origin_raid_index
            if origin is None:
                continue
            heapq.heappush(
                active_breaks[event.direction],
                (-origin, -sequence, event),
            )

        for raid_direction, mss_direction in (
            ("sell_side", "bullish"),
            ("buy_side", "bearish"),
        ):
            raid = current_raids[raid_direction]
            heap = active_breaks[mss_direction]
            if raid is not None:
                while heap and heap[0][2].break_index <= raid.raid_index:
                    heapq.heappop(heap)
            selected = heap[0][2] if raid is not None and heap else None
            latest_mss[mss_direction].append(selected)

        latest_raids["buy_side"].append(current_raids["buy_side"])
        latest_raids["sell_side"].append(current_raids["sell_side"])

    return StrategyEventCache(
        swings=tuple(swings),
        raids=tuple(raids),
        breaks=tuple(breaks),
        fvgs=tuple(fvgs),
        latest_confirmed_raids={
            direction: tuple(values) for direction, values in latest_raids.items()
        },
        latest_directional_mss={
            direction: tuple(values) for direction, values in latest_mss.items()
        },
        fvg_by_end={(fvg.direction, fvg.end_index): fvg for fvg in fvgs},
    )


def _base_no_trade(
    df: pd.DataFrame,
    config: StrategyConfig,
    reasons: list[str],
    ml: ModelPrediction,
    explanation: str,
    evaluation_index: int | None = None,
) -> Signal:
    if df.empty:
        timestamp = ""
    else:
        index = len(df) - 1 if evaluation_index is None else evaluation_index
        timestamp = str(df.iloc[index]["closed_at"])
    return Signal(
        decision=Decision.NO_TRADE,
        operating_mode=config.operating_mode,
        timestamp=timestamp,
        ml=ml,
        htf_bias=config.htf_bias,
        market_regime=MarketRegime.UNKNOWN,
        explanation=explanation,
        rejection_reasons=reasons,
        research_only=config.operating_mode == OperatingMode.HYBRID_RESEARCH,
        lifecycle=EntryLifecycle(
            state=SetupState.SETUP_FORMING,
            state_history=(SetupState.SETUP_FORMING,),
            execution_model=config.execution_model,
            entry_model=config.entry_model,
        ),
    )


def _target_for_long(
    swings,
    entry: float,
    after_index: int,
    known_at: pd.Timestamp,
) -> float | None:
    candidates = [
        swing.price
        for swing in swings
        if swing.kind == "swing_high"
        and swing.swing_index > after_index
        and swing.price > entry
        and swing.detected_at <= known_at
    ]
    return min(candidates) if candidates else None


def _target_for_short(
    swings,
    entry: float,
    after_index: int,
    known_at: pd.Timestamp,
) -> float | None:
    candidates = [
        swing.price
        for swing in swings
        if swing.kind == "swing_low"
        and swing.swing_index > after_index
        and swing.price < entry
        and swing.detected_at <= known_at
    ]
    return max(candidates) if candidates else None


def _entry_price(fvg: FairValueGap, entry_model: EntryModel) -> float:
    if entry_model == EntryModel.FVG_MIDPOINT:
        return fvg.midpoint
    raise ValueError(f"Unsupported entry model: {entry_model}")


def _risk_reward(decision: Decision, entry: float, stop: float, target: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    reward = target - entry if decision == Decision.BUY else entry - target
    return reward / risk


def _rule_confidence(valid_reasons: list[str]) -> float:
    return min(1.0, sum(RULE_CONFIDENCE_WEIGHTS.get(reason, 0.0) for reason in valid_reasons))


def _ml_allows_signal(decision: Decision, config: StrategyConfig, ml: ModelPrediction) -> tuple[bool, str | None]:
    if config.operating_mode == OperatingMode.RULE_ONLY:
        return True, None
    if config.operating_mode == OperatingMode.HYBRID_RESEARCH:
        return True, None
    if not config.hybrid_validated_enabled:
        return False, "model_not_verified"
    if ml.direction == MLDirection.UNAVAILABLE:
        return False, "model_unavailable"
    aligned = (
        (decision == Decision.BUY and ml.direction == MLDirection.UP_HORIZON)
        or (decision == Decision.SELL and ml.direction == MLDirection.NOT_UP_HORIZON)
    )
    return (True, None) if aligned else (False, "model_direction_conflict")


def evaluate_signal(
    df: pd.DataFrame,
    config: StrategyConfig | None = None,
    ml_prediction: ModelPrediction | None = None,
) -> Signal:
    config = config or StrategyConfig()
    ml = ml_prediction or ModelPrediction.unavailable()
    if df.empty:
        return _base_no_trade(
            df, config, ["insufficient_data"], ml, "Not enough closed candles."
        )
    cache = build_strategy_event_cache(df)
    return evaluate_signal_at(df, len(df) - 1, config, cache, ml)


def evaluate_signal_at(
    df: pd.DataFrame,
    evaluation_index: int,
    config: StrategyConfig,
    cache: StrategyEventCache,
    ml_prediction: ModelPrediction | None = None,
) -> Signal:
    ml = ml_prediction or ModelPrediction.unavailable()
    if evaluation_index < 7:
        return _base_no_trade(
            df,
            config,
            ["insufficient_data"],
            ml,
            "Not enough closed candles.",
            evaluation_index,
        )
    if config.htf_bias == HtfBias.NEUTRAL:
        return _base_no_trade(
            df,
            config,
            ["htf_bias_neutral"],
            ml,
            "HTF bias is neutral.",
            evaluation_index,
        )

    if config.htf_bias == HtfBias.BULLISH:
        return _evaluate_direction(
            df, config, ml, cache, Decision.BUY, evaluation_index
        )
    return _evaluate_direction(
        df, config, ml, cache, Decision.SELL, evaluation_index
    )


def _evaluate_direction(
    df: pd.DataFrame,
    config: StrategyConfig,
    ml: ModelPrediction,
    cache: StrategyEventCache,
    decision: Decision,
    activation_index: int,
) -> Signal:
    if decision == Decision.BUY:
        raid_direction = "sell_side"
        mss_direction = "bullish"
        fvg_direction = "bullish"
        setup_name = "SweepMssFvgRetraceLong"
    else:
        raid_direction = "buy_side"
        mss_direction = "bearish"
        fvg_direction = "bearish"
        setup_name = "SweepMssFvgRetraceShort"

    raid = cache.latest_confirmed_raids[raid_direction][activation_index]
    if raid is None:
        return _base_no_trade(
            df,
            config,
            ["no_liquidity_raid", "sweep_not_confirmed"],
            ml,
            "No confirmed liquidity sweep.",
            activation_index,
        )

    mss = cache.latest_directional_mss[mss_direction][activation_index]
    if mss is None:
        return _base_no_trade(
            df,
            config,
            ["no_mss_body_close"],
            ml,
            "No body-close MSS after sweep.",
            activation_index,
        )

    fvg = cache.fvg_by_end.get((fvg_direction, activation_index))
    if fvg is not None and fvg.end_index <= mss.break_index:
        fvg = None
    if not fvg:
        return _base_no_trade(
            df,
            config,
            ["no_valid_fvg"],
            ml,
            "No valid FVG after MSS.",
            activation_index,
        )
    zone = EntryZone(low=fvg.low, high=fvg.high)
    entry = _entry_price(fvg, config.entry_model)
    if decision == Decision.BUY:
        stop = raid.level_price - config.spread_buffer
        target = _target_for_long(cache.swings, entry, mss.swing_index, fvg.created_at)
        invalidation = "Close below swept sell-side liquidity or stop-loss invalidates the long setup."
    else:
        stop = raid.level_price + config.spread_buffer
        target = _target_for_short(cache.swings, entry, mss.swing_index, fvg.created_at)
        invalidation = "Close above swept buy-side liquidity or stop-loss invalidates the short setup."
    if target is None:
        return _base_no_trade(
            df,
            config,
            ["target_unavailable"],
            ml,
            "No opposing liquidity target is available.",
            activation_index,
        )
    if abs(entry - stop) < config.min_stop_distance:
        return _base_no_trade(
            df,
            config,
            ["stop_unavailable"],
            ml,
            "Structural stop distance is too small for stable testing.",
            activation_index,
        )

    rr = _risk_reward(decision, entry, stop, target)
    if rr < config.min_risk_reward:
        return _base_no_trade(
            df,
            config,
            ["risk_reward_below_minimum"],
            ml,
            "Risk-to-reward is below the configured minimum.",
            activation_index,
        )

    ml_allowed, ml_rejection = _ml_allows_signal(decision, config, ml)
    if not ml_allowed and ml_rejection:
        return _base_no_trade(
            df,
            config,
            [ml_rejection],
            ml,
            "ML gate is not available for HYBRID_VALIDATED.",
            activation_index,
        )

    valid_reasons = [
        "htf_bias_aligned",
        "confirmed_sweep",
        "mss_body_close",
        "valid_post_mss_fvg",
        "risk_reward_accepted",
    ]
    confidence = _rule_confidence(valid_reasons)
    if config.operating_mode == OperatingMode.HYBRID_VALIDATED and config.hybrid_validated_behavior == "confidence_modifier":
        confidence = min(1.0, 0.8 + 0.2 * ml.confidence)
    if confidence < config.min_confidence:
        return _base_no_trade(
            df,
            config,
            ["confidence_below_threshold"],
            ml,
            "Confidence is below threshold.",
            activation_index,
        )

    tp1 = entry + (entry - stop) if decision == Decision.BUY else entry - (stop - entry)
    activation_at = str(fvg.created_at)
    lifecycle = EntryLifecycle(
        state=SetupState.ENTRY_PENDING,
        state_history=(SetupState.SETUP_FORMING, SetupState.ENTRY_PENDING),
        execution_model=config.execution_model,
        entry_model=config.entry_model,
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
    signal = Signal(
        decision=decision,
        operating_mode=config.operating_mode,
        timestamp=str(df.iloc[activation_index]["closed_at"]),
        setup_name=setup_name,
        entry_type="FVG_MIDPOINT_LIMIT",
        entry_price=entry,
        entry_zone=zone,
        stop_loss=stop,
        take_profit=[TakeProfit("TP1_1R", tp1), TakeProfit("TP2_LIQUIDITY", target)],
        risk_reward=rr,
        confidence=confidence,
        ml=ml,
        htf_bias=config.htf_bias,
        market_regime=MarketRegime.REVERSAL_CANDIDATE,
        confluences=["confirmed_sweep", "mss_body_close", "post_mss_fvg", "opposing_liquidity_target"],
        structural_invalidation=invalidation,
        explanation=f"{setup_name} is valid under {config.operating_mode.value}.",
        valid_reasons=valid_reasons,
        rejection_reasons=[],
        research_only=config.operating_mode == OperatingMode.HYBRID_RESEARCH,
        lifecycle=lifecycle,
    )
    return signal
