"""Bid/ask-aware execution primitives for later empirical strategy stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class ExecutionCostError(ValueError):
    """Raised when an order cannot be modeled under the declared assumptions."""


@dataclass(frozen=True)
class CostScenario:
    name: str
    additional_slippage_points: float
    news_window_slippage_points: float
    stop_order_slippage_points: float
    maximum_acceptable_spread: float
    limit_fill_assumption: Literal["touch", "trade_through", "next_tick"]
    trade_through_points: float = 0.01


DEFAULT_COST_SCENARIOS: dict[str, CostScenario] = {
    "optimistic": CostScenario(
        name="optimistic",
        additional_slippage_points=0.00,
        news_window_slippage_points=0.02,
        stop_order_slippage_points=0.02,
        maximum_acceptable_spread=0.30,
        limit_fill_assumption="touch",
    ),
    "base": CostScenario(
        name="base",
        additional_slippage_points=0.03,
        news_window_slippage_points=0.08,
        stop_order_slippage_points=0.05,
        maximum_acceptable_spread=0.50,
        limit_fill_assumption="trade_through",
        trade_through_points=0.01,
    ),
    "stress": CostScenario(
        name="stress",
        additional_slippage_points=0.10,
        news_window_slippage_points=0.25,
        stop_order_slippage_points=0.15,
        maximum_acceptable_spread=1.00,
        limit_fill_assumption="next_tick",
    ),
}


@dataclass(frozen=True)
class ExecutionQuote:
    bid: float
    ask: float
    in_news_window: bool = False

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class ExecutionDecision:
    executable: bool
    price: float | None
    spread: float
    reason: str
    scenario: str


class ExecutionCostModel:
    def __init__(self, scenario: CostScenario) -> None:
        self.scenario = scenario

    def _validate_quote(self, quote: ExecutionQuote) -> str | None:
        if quote.bid <= 0 or quote.ask <= 0 or quote.ask <= quote.bid:
            return "invalid_bid_ask_quote"
        if quote.spread > self.scenario.maximum_acceptable_spread:
            return "spread_exceeds_maximum"
        return None

    def _slippage(self, quote: ExecutionQuote, *, stop_order: bool) -> float:
        slippage = self.scenario.additional_slippage_points
        if quote.in_news_window:
            slippage += self.scenario.news_window_slippage_points
        if stop_order:
            slippage += self.scenario.stop_order_slippage_points
        return slippage

    def market_price(
        self,
        *,
        side: Literal["long", "short"],
        action: Literal["entry", "exit"],
        quote: ExecutionQuote,
        stop_order: bool = False,
    ) -> ExecutionDecision:
        problem = self._validate_quote(quote)
        if problem:
            return ExecutionDecision(False, None, quote.spread, problem, self.scenario.name)
        slippage = self._slippage(quote, stop_order=stop_order)
        if side == "long" and action == "entry":
            price = quote.ask + slippage
        elif side == "long" and action == "exit":
            price = quote.bid - slippage
        elif side == "short" and action == "entry":
            price = quote.bid - slippage
        elif side == "short" and action == "exit":
            price = quote.ask + slippage
        else:  # pragma: no cover - Literal callers and tests cover valid combinations
            raise ExecutionCostError(f"Unsupported execution side/action: {side}/{action}")
        return ExecutionDecision(True, price, quote.spread, "executable", self.scenario.name)

    def limit_fill(
        self,
        *,
        side: Literal["long", "short"],
        limit_price: float,
        bid_low: float,
        bid_high: float,
        ask_low: float,
        ask_high: float,
        next_tick_available: bool = False,
    ) -> bool:
        assumption = self.scenario.limit_fill_assumption
        if assumption == "next_tick":
            return next_tick_available
        if side == "long":
            threshold = limit_price
            if assumption == "trade_through":
                threshold -= self.scenario.trade_through_points
            return ask_low <= threshold
        threshold = limit_price
        if assumption == "trade_through":
            threshold += self.scenario.trade_through_points
        return bid_high >= threshold
