from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StudyConfig:
    """Frozen primary specification; variants belong in explicit sensitivity runs."""

    timezone: str = "America/New_York"
    london_timezone: str = "Europe/London"
    required_bar_seconds: int = 60
    pre_news_start: str = "07:30"
    pre_news_secondary_start: str = "08:00"
    impulse_start: str = "08:30"
    impulse_end: str = "08:35"
    extended_impulse_end: str = "08:45"
    retracement_end: str = "09:30"
    equity_open: str = "09:30"
    equity_reaction_end: str = "09:50"
    delivery_end: str = "10:00"
    secondary_end: str = "10:30"
    swing_width: int = 2
    acceptance_closes: int = 2
    sweep_reentry_minutes: int = 5
    minimum_history_sessions: int = 20
    same_time_lookback: int = 60
    adr_lookback: int = 20
    displacement_body_multiple: float = 1.5
    displacement_atr_multiple: float = 1.25
    displacement_body_fraction: float = 0.60
    displacement_close_fraction: float = 0.20
    exhaustion_adr_share: float = 0.35
    continuation_extension: float = 0.50
    continuation_retracement_cap: float = 0.25
    partial_retracement_floor: float = 0.25
    partial_retracement_cap: float = 0.75
    minimum_tick_price: float = 0.01
    normal_spread_price: float = 0.15
    normal_slippage_price_per_side: float = 0.05
    stressed_spread_price: float = 0.30
    stressed_slippage_price_per_side: float = 0.10
    minimum_report_sample: int = 30

    def validate(self) -> None:
        if self.timezone != "America/New_York":
            raise ValueError("Primary study timezone must remain America/New_York")
        if self.required_bar_seconds != 60:
            raise ValueError("Primary study resolution must remain one minute")
        if self.acceptance_closes < 1 or self.swing_width < 1:
            raise ValueError("acceptance_closes and swing_width must be positive")
