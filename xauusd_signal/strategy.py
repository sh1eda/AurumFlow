from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .events import (
    FairValueGap,
    LiquidityRaid,
    StructureBreak,
    detect_fvgs,
    detect_liquidity_raids,
    detect_mss,
    detect_swings,
)
from .types import (
    Decision,
    EntryZone,
    HtfBias,
    MLDirection,
    MarketRegime,
    ModelPrediction,
    OperatingMode,
    Signal,
    TakeProfit,
)


RULE_CONFIDENCE_WEIGHTS = {
    "htf_bias_aligned": 0.20,
    "confirmed_sweep": 0.20,
    "mss_body_close": 0.20,
    "valid_fvg_entry_zone": 0.20,
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


def _base_no_trade(
    df: pd.DataFrame,
    config: StrategyConfig,
    reasons: list[str],
    ml: ModelPrediction,
    explanation: str,
) -> Signal:
    timestamp = "" if df.empty else str(df.iloc[-1]["closed_at"])
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
    )


def _latest_after(items, index_attr: str, after_index: int):
    candidates = [item for item in items if getattr(item, index_attr) > after_index]
    return candidates[-1] if candidates else None


def _latest_fvg_after(fvgs: list[FairValueGap], direction: str, after_index: int) -> FairValueGap | None:
    candidates = [fvg for fvg in fvgs if fvg.direction == direction and fvg.end_index > after_index]
    return candidates[-1] if candidates else None


def _zone_overlaps_last_bar(df: pd.DataFrame, zone: EntryZone) -> bool:
    last = df.iloc[-1]
    return bool(last["low"] <= zone.high and last["high"] >= zone.low)


def _target_for_long(swings, entry: float, after_index: int) -> float | None:
    candidates = [
        swing.price
        for swing in swings
        if swing.kind == "swing_high" and swing.swing_index > after_index and swing.price > entry
    ]
    return min(candidates) if candidates else None


def _target_for_short(swings, entry: float, after_index: int) -> float | None:
    candidates = [
        swing.price
        for swing in swings
        if swing.kind == "swing_low" and swing.swing_index > after_index and swing.price < entry
    ]
    return max(candidates) if candidates else None


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
    if len(df) < 8:
        return _base_no_trade(df, config, ["insufficient_data"], ml, "Not enough closed candles.")
    if config.htf_bias == HtfBias.NEUTRAL:
        return _base_no_trade(df, config, ["htf_bias_neutral"], ml, "HTF bias is neutral.")

    swings = detect_swings(df)
    raids = detect_liquidity_raids(df, swings)
    breaks = detect_mss(df, swings, raids)
    fvgs = detect_fvgs(df)

    if config.htf_bias == HtfBias.BULLISH:
        return _evaluate_direction(df, config, ml, swings, raids, breaks, fvgs, Decision.BUY)
    return _evaluate_direction(df, config, ml, swings, raids, breaks, fvgs, Decision.SELL)


def _evaluate_direction(
    df: pd.DataFrame,
    config: StrategyConfig,
    ml: ModelPrediction,
    swings,
    raids: list[LiquidityRaid],
    breaks: list[StructureBreak],
    fvgs: list[FairValueGap],
    decision: Decision,
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

    raid_candidates = [r for r in raids if r.direction == raid_direction and r.confirmed]
    if not raid_candidates:
        return _base_no_trade(df, config, ["no_liquidity_raid", "sweep_not_confirmed"], ml, "No confirmed liquidity sweep.")
    raid = raid_candidates[-1]

    mss_candidates = [b for b in breaks if b.direction == mss_direction and b.break_index > raid.raid_index]
    if not mss_candidates:
        return _base_no_trade(df, config, ["no_mss_body_close"], ml, "No body-close MSS after sweep.")
    mss = mss_candidates[-1]

    fvg = _latest_fvg_after(fvgs, fvg_direction, mss.break_index - 1)
    if not fvg:
        return _base_no_trade(df, config, ["no_valid_fvg"], ml, "No valid FVG after MSS.")
    zone = EntryZone(low=fvg.low, high=fvg.high)
    if not _zone_overlaps_last_bar(df, zone):
        return _base_no_trade(df, config, ["entry_zone_unavailable"], ml, "Latest candle has not retraced into the FVG zone.")

    entry = fvg.midpoint
    if decision == Decision.BUY:
        stop = raid.level_price - config.spread_buffer
        target = _target_for_long(swings, entry, mss.swing_index)
        invalidation = "Close below swept sell-side liquidity or stop-loss invalidates the long setup."
    else:
        stop = raid.level_price + config.spread_buffer
        target = _target_for_short(swings, entry, mss.swing_index)
        invalidation = "Close above swept buy-side liquidity or stop-loss invalidates the short setup."
    if target is None:
        return _base_no_trade(df, config, ["target_unavailable"], ml, "No opposing liquidity target is available.")
    if abs(entry - stop) < config.min_stop_distance:
        return _base_no_trade(df, config, ["stop_unavailable"], ml, "Structural stop distance is too small for stable testing.")

    rr = _risk_reward(decision, entry, stop, target)
    if rr < config.min_risk_reward:
        return _base_no_trade(df, config, ["risk_reward_below_minimum"], ml, "Risk-to-reward is below the configured minimum.")

    ml_allowed, ml_rejection = _ml_allows_signal(decision, config, ml)
    if not ml_allowed and ml_rejection:
        return _base_no_trade(df, config, [ml_rejection], ml, "ML gate is not available for HYBRID_VALIDATED.")

    valid_reasons = [
        "htf_bias_aligned",
        "confirmed_sweep",
        "mss_body_close",
        "valid_fvg_entry_zone",
        "risk_reward_accepted",
    ]
    confidence = _rule_confidence(valid_reasons)
    if config.operating_mode == OperatingMode.HYBRID_VALIDATED and config.hybrid_validated_behavior == "confidence_modifier":
        confidence = min(1.0, 0.8 + 0.2 * ml.confidence)
    if confidence < config.min_confidence:
        return _base_no_trade(df, config, ["confidence_below_threshold"], ml, "Confidence is below threshold.")

    tp1 = entry + (entry - stop) if decision == Decision.BUY else entry - (stop - entry)
    signal = Signal(
        decision=decision,
        operating_mode=config.operating_mode,
        timestamp=str(df.iloc[-1]["closed_at"]),
        setup_name=setup_name,
        entry_type="FVG_RETRACE_ZONE",
        entry_price=entry,
        entry_zone=zone,
        stop_loss=stop,
        take_profit=[TakeProfit("TP1_1R", tp1), TakeProfit("TP2_LIQUIDITY", target)],
        risk_reward=rr,
        confidence=confidence,
        ml=ml,
        htf_bias=config.htf_bias,
        market_regime=MarketRegime.REVERSAL_CANDIDATE,
        confluences=["confirmed_sweep", "mss_body_close", "fvg_retrace", "opposing_liquidity_target"],
        structural_invalidation=invalidation,
        explanation=f"{setup_name} is valid under {config.operating_mode.value}.",
        valid_reasons=valid_reasons,
        rejection_reasons=[],
        research_only=config.operating_mode == OperatingMode.HYBRID_RESEARCH,
    )
    return signal
