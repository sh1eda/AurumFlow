from __future__ import annotations

from bisect import bisect_left
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
    origin_raid_index: int | None = None


def detect_swings(df: pd.DataFrame) -> list[Swing]:
    swings: list[Swing] = []
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closed_at = df["closed_at"].tolist()
    for i in range(1, len(df) - 1):
        detected_at = closed_at[i + 1]
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swings.append(Swing("swing_high", i, float(highs[i]), detected_at))
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swings.append(Swing("swing_low", i, float(lows[i]), detected_at))
    return swings


def detect_fvgs(df: pd.DataFrame) -> list[FairValueGap]:
    fvgs: list[FairValueGap] = []
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closed_at = df["closed_at"].tolist()
    for i in range(2, len(df)):
        created_at = closed_at[i]
        if highs[i - 2] < lows[i]:
            low = float(highs[i - 2])
            high = float(lows[i])
            fvgs.append(
                FairValueGap("bullish", i - 2, i, low, high, (low + high) / 2, created_at)
            )
        elif lows[i - 2] > highs[i]:
            low = float(highs[i])
            high = float(lows[i - 2])
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
    swing_highs = [swing for swing in swings if swing.kind == "swing_high"]
    swing_lows = [swing for swing in swings if swing.kind == "swing_low"]
    high_pointer = 0
    low_pointer = 0
    prior_high: Swing | None = None
    prior_low: Swing | None = None
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    closed_at = df["closed_at"].tolist()

    for i in range(1, len(df)):
        while high_pointer < len(swing_highs) and swing_highs[high_pointer].swing_index < i:
            prior_high = swing_highs[high_pointer]
            high_pointer += 1
        while low_pointer < len(swing_lows) and swing_lows[low_pointer].swing_index < i:
            prior_low = swing_lows[low_pointer]
            low_pointer += 1

        if prior_high and highs[i] > prior_high.price:
            confirmed = bool(closes[i] < prior_high.price)
            raids.append(
                LiquidityRaid(
                    "buy_side",
                    prior_high.price,
                    prior_high.swing_index,
                    i,
                    closed_at[i],
                    confirmed,
                )
            )
        if prior_low and lows[i] < prior_low.price:
            confirmed = bool(closes[i] > prior_low.price)
            raids.append(
                LiquidityRaid(
                    "sell_side",
                    prior_low.price,
                    prior_low.swing_index,
                    i,
                    closed_at[i],
                    confirmed,
                )
            )
    return raids


class _CloseExtremaIndex:
    def __init__(self, closes: list[float]) -> None:
        size = 1
        while size < len(closes):
            size *= 2
        self._size = size
        self._length = len(closes)
        self._max = [float("-inf")] * (2 * size)
        self._min = [float("inf")] * (2 * size)
        for index, value in enumerate(closes):
            self._max[size + index] = value
            self._min[size + index] = value
        for index in range(size - 1, 0, -1):
            self._max[index] = max(self._max[index * 2], self._max[index * 2 + 1])
            self._min[index] = min(self._min[index * 2], self._min[index * 2 + 1])

    def first_above(self, start: int, threshold: float) -> int | None:
        return self._find_first(self._max, 1, 0, self._size, start, threshold, True)

    def first_below(self, start: int, threshold: float) -> int | None:
        return self._find_first(self._min, 1, 0, self._size, start, threshold, False)

    def _find_first(
        self,
        tree: list[float],
        node: int,
        left: int,
        right: int,
        start: int,
        threshold: float,
        above: bool,
    ) -> int | None:
        cannot_match = tree[node] <= threshold if above else tree[node] >= threshold
        if right <= start or cannot_match:
            return None
        if right - left == 1:
            return left if left < self._length else None
        midpoint = (left + right) // 2
        match = self._find_first(
            tree, node * 2, left, midpoint, start, threshold, above
        )
        if match is not None:
            return match
        return self._find_first(
            tree, node * 2 + 1, midpoint, right, start, threshold, above
        )


def detect_mss(df: pd.DataFrame, swings: list[Swing], raids: list[LiquidityRaid]) -> list[StructureBreak]:
    breaks: list[StructureBreak] = []
    swing_highs = [swing for swing in swings if swing.kind == "swing_high"]
    swing_lows = [swing for swing in swings if swing.kind == "swing_low"]
    high_indices = [swing.swing_index for swing in swing_highs]
    low_indices = [swing.swing_index for swing in swing_lows]
    closed_at = df["closed_at"].tolist()
    extrema = _CloseExtremaIndex([float(value) for value in df["close"].to_numpy()])

    for raid in raids:
        if not raid.confirmed:
            continue
        if raid.direction == "sell_side":
            position = bisect_left(high_indices, raid.raid_index) - 1
            target = swing_highs[position] if position >= 0 else None
            direction = "bullish"
            if not target:
                continue
            index = extrema.first_above(raid.raid_index + 1, target.price)
        else:
            position = bisect_left(low_indices, raid.raid_index) - 1
            target = swing_lows[position] if position >= 0 else None
            direction = "bearish"
            if not target:
                continue
            index = extrema.first_below(raid.raid_index + 1, target.price)
        if index is not None:
            breaks.append(
                StructureBreak(
                    direction,
                    index,
                    target.swing_index,
                    target.price,
                    closed_at[index],
                    origin_raid_index=raid.raid_index,
                )
            )
    return breaks
