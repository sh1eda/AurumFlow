import pandas as pd

from xauusd_signal.data import add_closed_at, causal_join_htf, resample_ohlcv
from xauusd_signal.events import (
    detect_fvgs,
    detect_ifvg_close_through,
    detect_swings,
    detect_time_liquidity_levels,
    evaluate_fvg_status,
)


def sample_df():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00", periods=6, freq="15min", tz="UTC"),
            "open": [10, 11, 12, 11, 10, 13],
            "high": [11, 13, 12, 12, 11, 15],
            "low": [9, 10, 11, 8, 9, 12.5],
            "close": [10.5, 12, 11.5, 9, 10.5, 14],
            "volume": [1, 1, 1, 1, 1, 1],
        }
    )
    return add_closed_at(df, pd.Timedelta(minutes=15))


def test_swing_detection_is_known_after_right_candle_close():
    df = sample_df()
    swings = detect_swings(df)
    high = next(s for s in swings if s.kind == "swing_high")
    assert high.swing_index == 1
    assert high.detected_at == df.iloc[2]["closed_at"]


def test_fvg_is_known_only_after_third_candle_close():
    df = sample_df()
    fvgs = detect_fvgs(df)
    bullish = next(f for f in fvgs if f.direction == "bullish")
    assert bullish.start_index == 3
    assert bullish.end_index == 5
    assert bullish.created_at == df.iloc[5]["closed_at"]
    assert bullish.low == df.iloc[3]["high"]
    assert bullish.high == df.iloc[5]["low"]


def test_causal_htf_join_uses_closed_htf_candles_only():
    base = sample_df()
    htf = resample_ohlcv(base, "30min")
    joined = causal_join_htf(base, htf, "m30")
    known = joined.dropna(subset=["m30_closed_at"])
    assert (known["m30_closed_at"] <= known["closed_at"]).all()


def test_fvg_fill_and_ifvg_close_through_are_after_fvg_creation():
    df = sample_df()
    extra = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2025-01-01 01:30", tz="UTC")],
            "open": [12.0],
            "high": [13.0],
            "low": [9.0],
            "close": [10.0],
            "volume": [1],
        }
    )
    df = add_closed_at(pd.concat([df.drop(columns=["closed_at"]), extra], ignore_index=True), pd.Timedelta(minutes=15))
    bullish = next(f for f in detect_fvgs(df) if f.direction == "bullish" and f.end_index == 5)
    status = evaluate_fvg_status(df, bullish)
    ifvgs = detect_ifvg_close_through(df, [bullish])

    assert status.first_midpoint_index == 6
    assert status.first_fill_index == 6
    assert status.close_through_index == 6
    assert ifvgs[0].detected_at == df.iloc[6]["closed_at"]
    assert ifvgs[0].detected_at > bullish.created_at


def test_time_liquidity_levels_are_detected_at_period_close():
    df = add_closed_at(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2025-01-01", periods=4, freq="6h", tz="UTC"),
                "open": [10, 11, 12, 13],
                "high": [12, 14, 13, 15],
                "low": [9, 10, 11, 8],
                "close": [11, 12, 12, 14],
                "volume": [1, 1, 1, 1],
            }
        ),
        pd.Timedelta(hours=6),
    )
    levels = detect_time_liquidity_levels(df, periods=("D",), timezone="UTC")
    high = next(level for level in levels if level.side == "high")
    low = next(level for level in levels if level.side == "low")

    assert high.price == 15
    assert low.price == 8
    assert high.detected_at == df.iloc[-1]["closed_at"]
    assert low.detected_at == df.iloc[-1]["closed_at"]
