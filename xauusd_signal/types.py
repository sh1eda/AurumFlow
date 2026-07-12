from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class OperatingMode(StrEnum):
    RULE_ONLY = "RULE_ONLY"
    HYBRID_RESEARCH = "HYBRID_RESEARCH"
    HYBRID_VALIDATED = "HYBRID_VALIDATED"


class MLDirection(StrEnum):
    UP_HORIZON = "UP_HORIZON"
    NOT_UP_HORIZON = "NOT_UP_HORIZON"
    UNAVAILABLE = "UNAVAILABLE"


class HtfBias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class MarketRegime(StrEnum):
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    RETRACEMENT = "RETRACEMENT"
    REVERSAL_CANDIDATE = "REVERSAL_CANDIDATE"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


@dataclass(frozen=True)
class EntryZone:
    low: float
    high: float

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class TakeProfit:
    name: str
    price: float


@dataclass(frozen=True)
class ModelPrediction:
    direction: MLDirection
    confidence: float
    raw_prediction: Any = None
    probabilities: dict[str, float] = field(default_factory=dict)
    model_version: str = ""
    feature_timestamp: str = ""
    feature_hash: str = ""

    @classmethod
    def unavailable(cls, reason: str = "model_unavailable") -> "ModelPrediction":
        return cls(
            direction=MLDirection.UNAVAILABLE,
            confidence=0.0,
            raw_prediction=reason,
            probabilities={},
            model_version="",
            feature_timestamp="",
            feature_hash="",
        )


@dataclass(frozen=True)
class Signal:
    decision: Decision
    operating_mode: OperatingMode
    timestamp: str
    setup_name: str | None = None
    entry_type: str | None = None
    entry_price: float | None = None
    entry_zone: EntryZone | None = None
    stop_loss: float | None = None
    take_profit: list[TakeProfit] = field(default_factory=list)
    risk_reward: float | None = None
    confidence: float = 0.0
    ml: ModelPrediction = field(default_factory=ModelPrediction.unavailable)
    htf_bias: HtfBias = HtfBias.NEUTRAL
    market_regime: MarketRegime = MarketRegime.UNKNOWN
    confluences: list[str] = field(default_factory=list)
    structural_invalidation: str = ""
    explanation: str = ""
    valid_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    research_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        data["operating_mode"] = self.operating_mode.value
        data["htf_bias"] = self.htf_bias.value
        data["market_regime"] = self.market_regime.value
        data["ml"]["direction"] = self.ml.direction.value
        return data


REJECTION_REASONS = {
    "insufficient_data",
    "open_candle",
    "htf_bias_neutral",
    "htf_bias_conflict",
    "no_liquidity_raid",
    "sweep_not_confirmed",
    "no_mss_body_close",
    "no_valid_fvg",
    "entry_zone_unavailable",
    "entry_not_filled",
    "stop_unavailable",
    "target_unavailable",
    "risk_reward_below_minimum",
    "confidence_below_threshold",
    "model_unavailable",
    "model_not_verified",
    "model_feature_mismatch",
    "model_class_mapping_ambiguous",
    "model_probability_unavailable",
    "model_direction_conflict",
    "outside_research_session",
    "news_filter_active",
    "paper_execution_only",
}
