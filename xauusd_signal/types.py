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


class SetupState(StrEnum):
    SETUP_FORMING = "SETUP_FORMING"
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTRY_FILLED = "ENTRY_FILLED"
    ENTRY_EXPIRED = "ENTRY_EXPIRED"
    SETUP_INVALIDATED = "SETUP_INVALIDATED"
    TRADE_OPEN = "TRADE_OPEN"
    TRADE_CLOSED = "TRADE_CLOSED"


class EntryOutcome(StrEnum):
    ENTRY_FILLED = "entry_filled"
    ENTRY_EXPIRED = "entry_expired"
    SETUP_INVALIDATED = "setup_invalidated"
    ENTRY_NOT_REACHED = "entry_not_reached"


class EntryModel(StrEnum):
    FVG_MIDPOINT = "FVG_MIDPOINT"


class ExecutionModel(StrEnum):
    PENDING_LIMIT_AFTER_FVG_CREATION = "PENDING_LIMIT_AFTER_FVG_CREATION"


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
class EntryLifecycle:
    state: SetupState
    state_history: tuple[SetupState, ...]
    execution_model: ExecutionModel
    entry_model: EntryModel
    sweep_index: int | None = None
    sweep_confirmed_at: str = ""
    mss_index: int | None = None
    mss_confirmed_at: str = ""
    fvg_start_index: int | None = None
    fvg_end_index: int | None = None
    fvg_created_at: str = ""
    structural_level_price: float | None = None
    order_activation_index: int | None = None
    order_activation_at: str = ""
    first_eligible_fill_index: int | None = None
    entry_expiration_index: int | None = None
    entry_expiration_at: str = ""
    structural_invalidation_index: int | None = None
    structural_invalidation_at: str = ""
    entry_fill_index: int | None = None
    entry_fill_at: str = ""
    trade_exit_index: int | None = None
    trade_exit_at: str = ""
    outcome: EntryOutcome | None = None


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
    lifecycle: EntryLifecycle | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        data["operating_mode"] = self.operating_mode.value
        data["htf_bias"] = self.htf_bias.value
        data["market_regime"] = self.market_regime.value
        data["ml"]["direction"] = self.ml.direction.value
        if self.lifecycle is not None:
            lifecycle = data["lifecycle"]
            lifecycle["state"] = self.lifecycle.state.value
            lifecycle["state_history"] = [state.value for state in self.lifecycle.state_history]
            lifecycle["execution_model"] = self.lifecycle.execution_model.value
            lifecycle["entry_model"] = self.lifecycle.entry_model.value
            if self.lifecycle.outcome is not None:
                lifecycle["outcome"] = self.lifecycle.outcome.value
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
    "entry_filled",
    "entry_expired",
    "entry_not_reached",
    "setup_invalidated",
    "structural_break_before_entry",
    "stop_level_breached_before_entry",
    "fvg_close_through_before_entry",
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
