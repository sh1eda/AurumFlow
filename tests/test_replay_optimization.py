import numpy as np
import pandas as pd
import pytest

from xauusd_signal.data import add_closed_at
from xauusd_signal.events import (
    FairValueGap,
    LiquidityRaid,
    StructureBreak,
    Swing,
    detect_fvgs,
    detect_liquidity_raids,
    detect_mss,
    detect_swings,
    latest_swing_before,
)
from xauusd_signal.strategy import (
    StrategyConfig,
    build_strategy_event_cache,
    evaluate_signal,
    evaluate_signal_at,
)
from xauusd_signal.types import HtfBias, OperatingMode


def random_bars(rows: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(20260714)
    close = 2000.0 + np.cumsum(rng.normal(0.0, 2.0, rows))
    open_ = np.concatenate(([close[0]], close[:-1]))
    high = np.maximum(open_, close) + rng.uniform(0.1, 2.5, rows)
    low = np.minimum(open_, close) - rng.uniform(0.1, 2.5, rows)
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2025-01-01", periods=rows, freq="15min", tz="UTC"
            ),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.ones(rows),
        }
    )
    return add_closed_at(df, pd.Timedelta(minutes=15))


def naive_swings(df: pd.DataFrame) -> list[Swing]:
    swings = []
    for index in range(1, len(df) - 1):
        previous = df.iloc[index - 1]
        row = df.iloc[index]
        following = df.iloc[index + 1]
        if row["high"] > previous["high"] and row["high"] > following["high"]:
            swings.append(
                Swing("swing_high", index, float(row["high"]), following["closed_at"])
            )
        if row["low"] < previous["low"] and row["low"] < following["low"]:
            swings.append(
                Swing("swing_low", index, float(row["low"]), following["closed_at"])
            )
    return swings


def naive_raids(df: pd.DataFrame, swings: list[Swing]) -> list[LiquidityRaid]:
    raids = []
    for index in range(1, len(df)):
        row = df.iloc[index]
        prior_high = latest_swing_before(swings, "swing_high", index)
        prior_low = latest_swing_before(swings, "swing_low", index)
        if prior_high and row["high"] > prior_high.price:
            raids.append(
                LiquidityRaid(
                    "buy_side",
                    prior_high.price,
                    prior_high.swing_index,
                    index,
                    row["closed_at"],
                    bool(row["close"] < prior_high.price),
                )
            )
        if prior_low and row["low"] < prior_low.price:
            raids.append(
                LiquidityRaid(
                    "sell_side",
                    prior_low.price,
                    prior_low.swing_index,
                    index,
                    row["closed_at"],
                    bool(row["close"] > prior_low.price),
                )
            )
    return raids


def naive_fvgs(df: pd.DataFrame) -> list[FairValueGap]:
    fvgs = []
    for index in range(2, len(df)):
        candle_1 = df.iloc[index - 2]
        candle_3 = df.iloc[index]
        if candle_1["high"] < candle_3["low"]:
            low = float(candle_1["high"])
            high = float(candle_3["low"])
            fvgs.append(
                FairValueGap(
                    "bullish",
                    index - 2,
                    index,
                    low,
                    high,
                    (low + high) / 2,
                    candle_3["closed_at"],
                )
            )
        elif candle_1["low"] > candle_3["high"]:
            low = float(candle_3["high"])
            high = float(candle_1["low"])
            fvgs.append(
                FairValueGap(
                    "bearish",
                    index - 2,
                    index,
                    low,
                    high,
                    (low + high) / 2,
                    candle_3["closed_at"],
                )
            )
    return fvgs


def naive_mss(
    df: pd.DataFrame,
    swings: list[Swing],
    raids: list[LiquidityRaid],
) -> list[StructureBreak]:
    breaks = []
    for raid in raids:
        if not raid.confirmed:
            continue
        if raid.direction == "sell_side":
            target = latest_swing_before(swings, "swing_high", raid.raid_index)
            direction = "bullish"
            comparison = lambda close: close > target.price
        else:
            target = latest_swing_before(swings, "swing_low", raid.raid_index)
            direction = "bearish"
            comparison = lambda close: close < target.price
        if target is None:
            continue
        for index in range(raid.raid_index + 1, len(df)):
            if comparison(df.iloc[index]["close"]):
                breaks.append(
                    StructureBreak(
                        direction,
                        index,
                        target.swing_index,
                        target.price,
                        df.iloc[index]["closed_at"],
                        origin_raid_index=raid.raid_index,
                    )
                )
                break
    return breaks


def test_optimized_event_primitives_match_reference_algorithms():
    df = random_bars()
    expected_swings = naive_swings(df)
    expected_raids = naive_raids(df, expected_swings)

    assert detect_swings(df) == expected_swings
    assert detect_fvgs(df) == naive_fvgs(df)
    assert detect_liquidity_raids(df, expected_swings) == expected_raids
    assert detect_mss(df, expected_swings, expected_raids) == naive_mss(
        df, expected_swings, expected_raids
    )


@pytest.mark.parametrize("bias", [HtfBias.BULLISH, HtfBias.BEARISH])
def test_cached_signal_replay_matches_causal_prefix_replay(bias: HtfBias):
    df = random_bars(120)
    config = StrategyConfig(
        operating_mode=OperatingMode.RULE_ONLY,
        htf_bias=bias,
    )
    cache = build_strategy_event_cache(df)

    for index in range(7, len(df)):
        prefix = df.iloc[: index + 1].reset_index(drop=True)
        expected = evaluate_signal(prefix, config)
        actual = evaluate_signal_at(df, index, config, cache)
        assert actual == expected
