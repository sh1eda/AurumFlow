import json

import pandas as pd

from xauusd_signal.backtest import BacktestConfig
from xauusd_signal.cli import main
from xauusd_signal.data import add_closed_at
from xauusd_signal.diagnostics import run_rule_funnel
from xauusd_signal.strategy import StrategyConfig
from xauusd_signal.types import HtfBias, OperatingMode


def long_funnel_df() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00", periods=13, freq="15min", tz="UTC"),
            "open": [100, 103, 103, 102, 100, 99, 101, 104, 103, 103, 106, 106, 110],
            "high": [101, 105, 104, 103, 102, 101, 107, 125, 104, 105, 108, 108, 126],
            "low": [99, 100, 101, 98, 99, 97, 100, 103, 102, 102, 106, 104.5, 104],
            "close": [100, 104, 102, 99, 101, 100, 106, 104, 103, 104, 107, 106, 125],
            "volume": [1] * 13,
        }
    )
    return add_closed_at(df, pd.Timedelta(minutes=15))


def mirrored_short_df() -> pd.DataFrame:
    long = long_funnel_df()
    short = long.copy()
    short["open"] = 200.0 - long["open"]
    short["close"] = 200.0 - long["close"]
    short["high"] = 200.0 - long["low"]
    short["low"] = 200.0 - long["high"]
    return short


def config(bias: HtfBias) -> BacktestConfig:
    return BacktestConfig(
        StrategyConfig(
            operating_mode=OperatingMode.RULE_ONLY,
            htf_bias=bias,
        )
    )


def stage_counts(report, direction: str) -> dict[str, int]:
    return {stage.name: stage.count for stage in report.directions[direction].stages}


def test_long_funnel_counts_and_percentages_match_execution():
    report = run_rule_funnel(long_funnel_df(), config(HtfBias.BULLISH))
    long = stage_counts(report, "LONG")

    assert long["bars_evaluated"] == 3
    assert long["confirmed_sweeps"] == 3
    assert long["directional_mss"] == 3
    assert long["valid_post_mss_fvg"] == 1
    assert long["pending_entry_order_created"] == 1
    assert long["pending_order_activated"] == 1
    assert long["entry_filled"] == 1
    assert long["trade_closed"] == 1

    fvg_stage = next(
        stage
        for stage in report.directions["LONG"].stages
        if stage.name == "valid_post_mss_fvg"
    )
    assert fvg_stage.percent_from_previous == 33.33
    assert fvg_stage.percent_from_initial == 33.33


def test_funnel_keeps_long_short_and_combined_counts_separate():
    bullish = run_rule_funnel(long_funnel_df(), config(HtfBias.BULLISH))
    bearish = run_rule_funnel(mirrored_short_df(), config(HtfBias.BEARISH))

    bullish_long = stage_counts(bullish, "LONG")
    bullish_short = stage_counts(bullish, "SHORT")
    bullish_combined = stage_counts(bullish, "COMBINED")
    assert bullish_long["pending_order_activated"] == 1
    assert bullish_short["accepted_htf_bias"] == 0
    assert bullish_combined["bars_evaluated"] == 6
    assert bullish_combined["entry_filled"] == 1

    bearish_long = stage_counts(bearish, "LONG")
    bearish_short = stage_counts(bearish, "SHORT")
    assert bearish_long["accepted_htf_bias"] == 0
    assert bearish_short["pending_order_activated"] == 1
    assert bearish_short["entry_filled"] == 1


def test_funnel_replay_is_deterministic():
    first = run_rule_funnel(long_funnel_df(), config(HtfBias.BULLISH))
    second = run_rule_funnel(long_funnel_df(), config(HtfBias.BULLISH))

    assert first == second


def test_diagnose_cli_supports_json_and_text(tmp_path, capsys):
    path = tmp_path / "bars.csv"
    long_funnel_df().drop(columns=["closed_at"]).to_csv(path, index=False)
    base_args = [
        "diagnose",
        "--csv",
        str(path),
        "--mode",
        "RULE_ONLY",
        "--htf-bias",
        "BULLISH",
    ]

    assert main(base_args + ["--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directions"]["LONG"]["direction"] == "LONG"
    assert payload["dataset"]["bars"] == 13

    assert main(base_args) == 0
    text = capsys.readouterr().out
    assert "AurumFlow rule funnel" in text
    assert "pending_order_activated" in text
