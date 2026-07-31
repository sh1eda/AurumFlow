"""Frozen research configuration for D005.

None of these values are production strategy defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, time, timedelta
import hashlib
import json
from zoneinfo import ZoneInfo

import pandas as pd


NEW_YORK = "America/New_York"
OBSERVATION_WINDOW = ("08:30", "09:00")
ORDER_BLOCK_VARIANTS = (
    "consecutive_block",
    "last_opposing_candle",
    "inefficiency_break_origin",
)


@dataclass(frozen=True)
class TimeframeMapping:
    name: str
    parent: str
    reaction: str
    refinement: str
    optional_refinement: str | None = None


DEFAULT_MAPPINGS: tuple[TimeframeMapping, ...] = (
    TimeframeMapping("weekly_4h_1h", "1W", "4H", "1H"),
    TimeframeMapping("daily_1h_15m", "1D", "1H", "15min"),
    TimeframeMapping("4h_15m_5m", "4H", "15min", "5min"),
    TimeframeMapping("1h_5m_1m", "1H", "5min", "5min", "1min"),
)


@dataclass(frozen=True)
class MSSVariant:
    name: str = "body_close_pivot_w2"
    pivot_width: int = 2
    body_close_required: bool = True
    confirmation_timeout_bars: int = 12

    def validate(self) -> None:
        if self.pivot_width < 1:
            raise ValueError("MSS pivot width must be positive")
        if self.confirmation_timeout_bars < 1:
            raise ValueError("MSS confirmation timeout must be positive")


@dataclass(frozen=True)
class DisplacementVariant:
    name: str = "atr_body_baseline"
    body_range_minimum: float = 0.60
    true_range_atr_minimum: float = 1.25
    atr_lookback: int = 14
    atr_min_periods: int = 10
    immediate_retracement_bars: int = 2
    maximum_immediate_retracement: float = 0.50

    def validate(self) -> None:
        if not 0 < self.body_range_minimum <= 1:
            raise ValueError("body/range threshold must be in (0, 1]")
        if self.true_range_atr_minimum <= 0:
            raise ValueError("ATR-normalized displacement threshold must be positive")
        if self.atr_lookback < 2:
            raise ValueError("ATR lookback must be at least two bars")
        if not 1 <= self.atr_min_periods <= self.atr_lookback:
            raise ValueError("ATR minimum periods must be within the lookback")
        if self.immediate_retracement_bars < 0:
            raise ValueError("immediate retracement bars cannot be negative")
        if not 0 <= self.maximum_immediate_retracement <= 1:
            raise ValueError("maximum immediate retracement must be in [0, 1]")


@dataclass(frozen=True)
class PremarketConfig:
    timezone: str = NEW_YORK
    start: str = "00:00"
    end: str = "08:30"
    minimum_coverage: float = 0.95
    sweep_penetration: float = 0.01
    require_body_close_reclaim: bool = True

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        parse_clock(self.start)
        parse_clock(self.end)
        if parse_clock(self.end) <= parse_clock(self.start):
            raise ValueError("premarket interval must not cross midnight")
        if not 0 < self.minimum_coverage <= 1:
            raise ValueError("premarket minimum coverage must be in (0, 1]")
        if self.sweep_penetration < 0:
            raise ValueError("premarket sweep penetration cannot be negative")


@dataclass(frozen=True)
class BalanceVariant:
    name: str = "efficiency_atr_range"
    lookback_bars: int = 20
    maximum_efficiency_ratio: float = 0.35
    maximum_range_atr: float = 4.0
    minimum_boundary_touches: int = 2

    def validate(self) -> None:
        if self.lookback_bars < 5:
            raise ValueError("balance lookback must be at least five bars")
        if not 0 <= self.maximum_efficiency_ratio <= 1:
            raise ValueError("balance efficiency ratio must be in [0, 1]")
        if self.maximum_range_atr <= 0:
            raise ValueError("balance range/ATR threshold must be positive")
        if self.minimum_boundary_touches < 1:
            raise ValueError("minimum boundary touches must be positive")


@dataclass(frozen=True)
class ContextEngineConfig:
    """Complete D005 research configuration."""

    timezone: str = NEW_YORK
    mappings: tuple[TimeframeMapping, ...] = DEFAULT_MAPPINGS
    primary_mapping: str = "4h_15m_5m"
    optional_1m_refinement: bool = False
    mss: MSSVariant = field(default_factory=MSSVariant)
    displacement: DisplacementVariant = field(default_factory=DisplacementVariant)
    premarket: PremarketConfig = field(default_factory=PremarketConfig)
    balance: BalanceVariant = field(default_factory=BalanceVariant)
    equal_level_tolerance_atr: float = 0.10
    liquidity_sweep_penetration: float = 0.01
    require_liquidity_reclaim: bool = True
    fvg_minimum_width: float = 0.0
    ob_lookback_bars: int = 6
    maximum_overextension_atr: float = 3.0
    maximum_zone_risk_atr: float = 2.0
    minimum_zone_width: float = 0.0
    trapped_array_max_distance_atr: float = 1.0
    source_rule_catalog: str = "research/context_engine/source_rule_catalog.json"
    d005_version: str = "D005-v1"

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError("D005 defaults are defined in America/New_York")
        self.mss.validate()
        self.displacement.validate()
        self.premarket.validate()
        self.balance.validate()
        names = [mapping.name for mapping in self.mappings]
        if len(names) != len(set(names)):
            raise ValueError("timeframe mapping names must be unique")
        if self.primary_mapping not in names:
            raise ValueError(f"unknown primary mapping: {self.primary_mapping}")
        if self.equal_level_tolerance_atr < 0:
            raise ValueError("equal-level ATR tolerance cannot be negative")
        if self.liquidity_sweep_penetration < 0:
            raise ValueError("liquidity sweep penetration cannot be negative")
        if self.fvg_minimum_width < 0:
            raise ValueError("FVG minimum width cannot be negative")
        if self.ob_lookback_bars < 1:
            raise ValueError("OB lookback must be positive")
        if self.maximum_overextension_atr <= 0:
            raise ValueError("overextension threshold must be positive")
        if self.maximum_zone_risk_atr <= 0:
            raise ValueError("zone risk threshold must be positive")
        if self.minimum_zone_width < 0:
            raise ValueError("minimum zone width cannot be negative")

    def mapping(self, name: str | None = None) -> TimeframeMapping:
        selected = name or self.primary_mapping
        for mapping in self.mappings:
            if mapping.name == selected:
                if mapping.optional_refinement and not self.optional_1m_refinement:
                    return TimeframeMapping(
                        mapping.name,
                        mapping.parent,
                        mapping.reaction,
                        mapping.refinement,
                        None,
                    )
                return mapping
        raise KeyError(selected)

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["order_block_variants"] = list(ORDER_BLOCK_VARIANTS)
        payload["ob_taxonomies"] = {
            "consecutive_block": "ict_order_block",
            "last_opposing_candle": "ict_order_block",
            "inefficiency_break_origin": "smc_supply_demand_zone",
        }
        payload["observation_window"] = {
            "timezone": NEW_YORK,
            "start": OBSERVATION_WINDOW[0],
            "end": OBSERVATION_WINDOW[1],
            "semantics": "[start, end)",
            "research_only": True,
        }
        payload["production_entry_authorization"] = False
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid local clock {value!r}") from exc


def local_bounds(
    session_date: date,
    start: str,
    end: str,
    timezone: str = NEW_YORK,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return DST-safe UTC bounds for a half-open local interval."""

    zone = ZoneInfo(timezone)
    left = pd.Timestamp.combine(session_date, parse_clock(start)).tz_localize(
        zone, ambiguous="raise", nonexistent="raise"
    )
    right_date = session_date
    if parse_clock(end) <= parse_clock(start):
        right_date += timedelta(days=1)
    right = pd.Timestamp.combine(right_date, parse_clock(end)).tz_localize(
        zone, ambiguous="raise", nonexistent="raise"
    )
    return left.tz_convert("UTC"), right.tz_convert("UTC")
