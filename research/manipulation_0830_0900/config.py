"""Frozen configuration and deterministic time definitions for D004."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from research.LIQUIDITY.levels import (
    trading_session_date as validated_trading_session_date,
)


NEW_YORK = "America/New_York"
LONDON = "Europe/London"


@dataclass(frozen=True)
class ClockWindow:
    """A half-open local-clock window."""

    name: str
    start: str
    end: str

    @property
    def minutes(self) -> int:
        start = parse_clock(self.start)
        end = parse_clock(self.end)
        anchor = date(2000, 1, 1)
        left = pd.Timestamp.combine(anchor, start)
        right = pd.Timestamp.combine(anchor, end)
        if right <= left:
            right += pd.Timedelta(days=1)
        return int((right - left).total_seconds() // 60)


SUBWINDOWS: tuple[ClockWindow, ...] = (
    ClockWindow("0830_0835", "08:30", "08:35"),
    ClockWindow("0830_0845", "08:30", "08:45"),
    ClockWindow("0830_0900", "08:30", "09:00"),
    ClockWindow("0845_0900", "08:45", "09:00"),
)

CONTROL_WINDOWS: tuple[ClockWindow, ...] = (
    ClockWindow("0730_0800", "07:30", "08:00"),
    ClockWindow("0800_0830", "08:00", "08:30"),
    ClockWindow("0830_0900", "08:30", "09:00"),
    ClockWindow("0900_0930", "09:00", "09:30"),
    ClockWindow("0930_1000", "09:30", "10:00"),
)

REFERENCE_WINDOWS: tuple[ClockWindow, ...] = (
    ClockWindow("0000_0830", "00:00", "08:30"),
    ClockWindow("0700_0830", "07:00", "08:30"),
    ClockWindow("0800_0830", "08:00", "08:30"),
    ClockWindow("0800_0830_exact", "08:00", "08:30"),
)

HORIZON_WINDOWS: tuple[ClockWindow, ...] = (
    ClockWindow("0900_0930", "09:00", "09:30"),
    ClockWindow("0900_1000", "09:00", "10:00"),
    ClockWindow("0900_1200", "09:00", "12:00"),
    ClockWindow("0900_1600", "09:00", "16:00"),
    ClockWindow("0900_1700", "09:00", "17:00"),
)


@dataclass(frozen=True)
class CostScenario:
    name: str
    spread_price: float
    slippage_price_per_side: float
    commission_r: float
    provenance: str


COST_SCENARIOS: tuple[CostScenario, ...] = (
    CostScenario(
        "zero_cost",
        0.0,
        0.0,
        0.0,
        "raw research movement",
    ),
    CostScenario(
        "repository_default",
        0.0,
        0.0,
        0.0,
        "xauusd_signal.backtest.BacktestConfig defaults",
    ),
    CostScenario(
        "conservative",
        0.20,
        0.10,
        0.01,
        "existing isolated FVG research sensitivity",
    ),
)


@dataclass(frozen=True)
class ResearchConfig:
    """Complete D004 run configuration.

    All defaults are research-only.  They are not connected to production
    strategy configuration.
    """

    dataset_root: Path
    output_dir: Path
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = NEW_YORK
    window_start: str = "08:30"
    window_end: str = "09:00"
    bar_resolutions: tuple[int, ...] = (1, 5, 15)
    reference_range: str = "0800_0830"
    primary_sweep_threshold_mode: str = "absolute"
    primary_sweep_threshold: float = 0.05
    absolute_sweep_thresholds: tuple[float, ...] = (0.01, 0.05, 0.10, 0.20)
    bps_sweep_thresholds: tuple[float, ...] = (0.25, 0.50, 1.00, 2.00)
    atr_sweep_thresholds: tuple[float, ...] = (0.01, 0.025, 0.05, 0.10)
    range_sweep_thresholds: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05)
    tick_size: float = 0.01
    atr_lookback_bars: int = 20
    displacement_history_days: int = 20
    displacement_quantiles: tuple[float, float, float] = (0.25, 0.75, 0.90)
    expansion_atr_fraction: float = 0.25
    swing_width: int = 2
    mss_max_confirmation_minutes: int = 60
    fvg_expiration_minutes: int = 480
    bootstrap_resamples: int = 1000
    random_seed: int = 4004
    worker_count: int = 1
    resume: bool = True
    event_labels: Path | None = None
    report_path: Path | None = None

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError(
                "D004 is preregistered in America/New_York; another timezone "
                "would define a different experiment"
            )
        parse_clock(self.window_start)
        parse_clock(self.window_end)
        if self.window_start >= self.window_end:
            raise ValueError("window start must precede window end on the same local date")
        if set(self.bar_resolutions) - {1, 5, 15}:
            raise ValueError("bar resolutions must be selected from 1, 5 and 15 minutes")
        reference_names = {item.name for item in REFERENCE_WINDOWS}
        if self.reference_range not in reference_names:
            raise ValueError(f"unknown reference range: {self.reference_range}")
        if self.primary_sweep_threshold_mode not in {
            "absolute",
            "bps",
            "atr_fraction",
            "recent_range_fraction",
        }:
            raise ValueError("unsupported primary sweep threshold mode")
        if self.primary_sweep_threshold < 0:
            raise ValueError("sweep threshold cannot be negative")
        if self.tick_size <= 0:
            raise ValueError("tick size must be positive")
        if self.displacement_history_days < 2:
            raise ValueError("displacement history must be at least two days")
        if tuple(sorted(self.displacement_quantiles)) != self.displacement_quantiles:
            raise ValueError("displacement quantiles must be increasing")
        if not all(0 < value < 1 for value in self.displacement_quantiles):
            raise ValueError("displacement quantiles must be between zero and one")
        if self.bootstrap_resamples < 100:
            raise ValueError("bootstrap resamples must be at least 100")
        if self.worker_count < 1:
            raise ValueError("worker count must be positive")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start date must not be after end date")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("dataset_root", "output_dir", "event_labels", "report_path"):
            value = payload[key]
            payload[key] = str(value) if value is not None else None
        payload["subwindows"] = [asdict(item) for item in SUBWINDOWS]
        payload["control_windows"] = [asdict(item) for item in CONTROL_WINDOWS]
        payload["reference_windows"] = [asdict(item) for item in REFERENCE_WINDOWS]
        payload["horizon_windows"] = [asdict(item) for item in HORIZON_WINDOWS]
        payload["cost_scenarios"] = [asdict(item) for item in COST_SCENARIOS]
        payload["trading_day_definition"] = (
            "18:00 previous New York calendar date through 17:00 named date; "
            "evening observations map to the following named session"
        )
        payload["window_interval_semantics"] = "[start, end)"
        return payload


def parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid local clock {value!r}; expected HH:MM[:SS]") from exc


def local_timestamp(session_date: date, clock: str, timezone: str = NEW_YORK) -> pd.Timestamp:
    """Return an IANA-zone-aware timestamp for a local session clock."""

    return pd.Timestamp.combine(session_date, parse_clock(clock)).tz_localize(
        ZoneInfo(timezone),
        ambiguous="raise",
        nonexistent="raise",
    )


def utc_bounds(
    session_date: date,
    start: str,
    end: str,
    timezone: str = NEW_YORK,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Convert one half-open local window to UTC with DST-aware IANA rules."""

    left = local_timestamp(session_date, start, timezone)
    right_date = session_date
    if parse_clock(end) <= parse_clock(start):
        right_date += timedelta(days=1)
    right = local_timestamp(right_date, end, timezone)
    return left.tz_convert("UTC"), right.tz_convert("UTC")


def trading_day_bounds(
    session_date: date, timezone: str = NEW_YORK
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Validated repository convention: prior 18:00 through named-date 17:00."""

    previous = session_date - timedelta(days=1)
    left = local_timestamp(previous, "18:00", timezone)
    right = local_timestamp(session_date, "17:00", timezone)
    return left.tz_convert("UTC"), right.tz_convert("UTC")


def trading_session_date(timestamp: pd.Timestamp, timezone: str = NEW_YORK) -> date:
    """Map an instant to the repository's 18:00-17:00 named session."""

    if timezone != NEW_YORK:
        raise ValueError("the validated repository trading session is America/New_York")
    return validated_trading_session_date(pd.Timestamp(timestamp))


def selected_windows(
    names: Iterable[str], available: tuple[ClockWindow, ...]
) -> tuple[ClockWindow, ...]:
    lookup = {item.name: item for item in available}
    result = []
    for name in names:
        if name not in lookup:
            raise ValueError(f"unknown window {name!r}")
        result.append(lookup[name])
    return tuple(result)
