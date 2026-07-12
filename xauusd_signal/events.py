from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Swing:
    kind: str
    swing_index: int
    price: float
    detected_at: pd.Timestamp


@dataclass(frozen=True)
class FairValueGap:
    direction: str
    start_index: int
    end_index: int
    low: float
    high: float
    midpoint: float
    created_at: pd.Timestamp


@dataclass(frozen=True)
class FvgStatus:
    fvg: FairValueGap
    midpoint_touched: bool
    filled: bool
    close_through_index: int | None
    first_midpoint_index: int | None
    first_fill_index: int | None
    detected_at: pd.Timestamp | None


@dataclass(frozen=True)
class TimeLiquidityLevel:
    period: str
    side: str
    price: float
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    detected_at: pd.Timestamp


@dataclass(frozen=True)
class IfvgCloseThrough:
    direction: str
    fvg: FairValueGap
    close_through_index: int
    detected_at: pd.Timestamp


@dataclass(frozen=True)
class LiquidityRaid:
    direction: str
    level_price: float
    level_index: int
    raid_index: int
    detected_at: pd.Timestamp
    confirmed: bool


@dataclass(frozen=True)
class StructureBreak:
    direction: str
    break_index: int
    swing_index: int
    swing_price: float
    detected_at: pd.Timestamp
    kind: str = "mss_body_close"


def detect_swings(df: pd.DataFrame) -> list[Swing]:
    swings: list[Swing] = []
    for i in range(1, len(df) - 1):
        prev_row = df.iloc[i - 1]
        row = df.iloc[i]
        next_row = df.iloc[i + 1]
        detected_at = next_row["closed_at"]
        if row["high"] > prev_row["high"] and row["high"] > next_row["high"]:
            swings.append(Swing("swing_high", i, float(row["high"]), detected_at))
        if row["low"] < prev_row["low"] and row["low"] < next_row["low"]:
            swings.append(Swing("swing_low", i, float(row["low"]), detected_at))
    return swings


def detect_fvgs(df: pd.DataFrame) -> list[FairValueGap]:
    fvgs: list[FairValueGap] = []
    for i in range(2, len(df)):
        candle_1 = df.iloc[i - 2]
        candle_3 = df.iloc[i]
        created_at = candle_3["closed_at"]
        if candle_1["high"] < candle_3["low"]:
            low = float(candle_1["high"])
            high = float(candle_3["low"])
            fvgs.append(
                FairValueGap("bullish", i - 2, i, low, high, (low + high) / 2, created_at)
            )
        elif candle_1["low"] > candle_3["high"]:
            low = float(candle_3["high"])
            high = float(candle_1["low"])
            fvgs.append(
                FairValueGap("bearish", i - 2, i, low, high, (low + high) / 2, created_at)
            )
    return fvgs


def evaluate_fvg_status(df: pd.DataFrame, fvg: FairValueGap) -> FvgStatus:
    midpoint_index: int | None = None
    fill_index: int | None = None
    close_through_index: int | None = None
    detected_at: pd.Timestamp | None = None

    for i in range(fvg.end_index + 1, len(df)):
        row = df.iloc[i]
        if midpoint_index is None and row["low"] <= fvg.midpoint <= row["high"]:
            midpoint_index = i
        if fvg.direction == "bullish":
            if fill_index is None and row["low"] <= fvg.low:
                fill_index = i
            if close_through_index is None and row["close"] < fvg.low:
                close_through_index = i
        else:
            if fill_index is None and row["high"] >= fvg.high:
                fill_index = i
            if close_through_index is None and row["close"] > fvg.high:
                close_through_index = i
        if detected_at is None and any(index == i for index in [midpoint_index, fill_index, close_through_index]):
            detected_at = row["closed_at"]

    return FvgStatus(
        fvg=fvg,
        midpoint_touched=midpoint_index is not None,
        filled=fill_index is not None,
        close_through_index=close_through_index,
        first_midpoint_index=midpoint_index,
        first_fill_index=fill_index,
        detected_at=detected_at,
    )


def detect_ifvg_close_through(df: pd.DataFrame, fvgs: list[FairValueGap]) -> list[IfvgCloseThrough]:
    events: list[IfvgCloseThrough] = []
    for fvg in fvgs:
        status = evaluate_fvg_status(df, fvg)
        if status.close_through_index is None:
            continue
        direction = "bearish" if fvg.direction == "bullish" else "bullish"
        row = df.iloc[status.close_through_index]
        events.append(IfvgCloseThrough(direction, fvg, status.close_through_index, row["closed_at"]))
    return events


def detect_time_liquidity_levels(
    df: pd.DataFrame,
    periods: tuple[str, ...] = ("D", "W", "M"),
    timezone: str = "America/New_York",
) -> list[TimeLiquidityLevel]:
    if df.empty:
        return []

    working = df.copy()
    closed_at = pd.to_datetime(working["closed_at"], utc=True)
    timestamp = pd.to_datetime(working["timestamp"], utc=True)
    local_timestamp = timestamp.dt.tz_convert(timezone).dt.tz_localize(None)
    levels: list[TimeLiquidityLevel] = []

    for period in periods:
        working["_period"] = local_timestamp.dt.to_period(period)
        for _, group in working.groupby("_period", sort=True):
            if group.empty:
                continue
            detected_at = group["closed_at"].max()
            period_start = group["timestamp"].min()
            period_end = group["closed_at"].max()
            levels.append(
                TimeLiquidityLevel(
                    period=period,
                    side="high",
                    price=float(group["high"].max()),
                    period_start=period_start,
                    period_end=period_end,
                    detected_at=detected_at,
                )
            )
            levels.append(
                TimeLiquidityLevel(
                    period=period,
                    side="low",
                    price=float(group["low"].min()),
                    period_start=period_start,
                    period_end=period_end,
                    detected_at=detected_at,
                )
            )
    return levels


def latest_swing_before(swings: list[Swing], kind: str, before_index: int) -> Swing | None:
    candidates = [s for s in swings if s.kind == kind and s.swing_index < before_index]
    return candidates[-1] if candidates else None


def detect_liquidity_raids(df: pd.DataFrame, swings: list[Swing]) -> list[LiquidityRaid]:
    raids: list[LiquidityRaid] = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prior_high = latest_swing_before(swings, "swing_high", i)
        prior_low = latest_swing_before(swings, "swing_low", i)
        if prior_high and row["high"] > prior_high.price:
            confirmed = bool(row["close"] < prior_high.price)
            raids.append(
                LiquidityRaid("buy_side", prior_high.price, prior_high.swing_index, i, row["closed_at"], confirmed)
            )
        if prior_low and row["low"] < prior_low.price:
            confirmed = bool(row["close"] > prior_low.price)
            raids.append(
                LiquidityRaid("sell_side", prior_low.price, prior_low.swing_index, i, row["closed_at"], confirmed)
            )
    return raids


def detect_mss(df: pd.DataFrame, swings: list[Swing], raids: list[LiquidityRaid]) -> list[StructureBreak]:
    breaks: list[StructureBreak] = []
    for raid in raids:
        if not raid.confirmed:
            continue
        if raid.direction == "sell_side":
            target = latest_swing_before(swings, "swing_high", raid.raid_index)
            direction = "bullish"
            if not target:
                continue
            for i in range(raid.raid_index + 1, len(df)):
                if df.iloc[i]["close"] > target.price:
                    breaks.append(
                        StructureBreak(direction, i, target.swing_index, target.price, df.iloc[i]["closed_at"])
                    )
                    break
        else:
            target = latest_swing_before(swings, "swing_low", raid.raid_index)
            direction = "bearish"
            if not target:
                continue
            for i in range(raid.raid_index + 1, len(df)):
                if df.iloc[i]["close"] < target.price:
                    breaks.append(
                        StructureBreak(direction, i, target.swing_index, target.price, df.iloc[i]["closed_at"])
                    )
                    break
    return breaks
