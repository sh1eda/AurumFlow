import pandas as pd

from xauusd_signal.data import add_closed_at
from xauusd_signal.strategy import StrategyConfig, evaluate_signal
from xauusd_signal.types import Decision, HtfBias, MLDirection, ModelPrediction, OperatingMode


def long_setup_df():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01 00:00", periods=9, freq="15min", tz="UTC"),
            "open": [100, 103, 103, 102, 100, 99, 101, 104, 104],
            "high": [101, 105, 104, 103, 102, 101, 106, 115, 104],
            "low": [99, 100, 101, 98, 99, 97, 100, 103, 101.5],
            "close": [100, 104, 102, 99, 101, 100, 106, 104, 103],
            "volume": [1] * 9,
        }
    )
    return add_closed_at(df, pd.Timedelta(minutes=15))


def test_rule_only_can_emit_buy_without_ml():
    signal = evaluate_signal(
        long_setup_df(),
        StrategyConfig(operating_mode=OperatingMode.RULE_ONLY, htf_bias=HtfBias.BULLISH),
    )
    assert signal.decision == Decision.BUY
    assert signal.setup_name == "SweepMssFvgRetraceLong"
    assert signal.ml.direction == MLDirection.UNAVAILABLE
    assert "model_not_verified" not in signal.rejection_reasons


def test_hybrid_research_logs_ml_without_blocking_rule_signal():
    ml = ModelPrediction(direction=MLDirection.NOT_UP_HORIZON, confidence=0.99)
    signal = evaluate_signal(
        long_setup_df(),
        StrategyConfig(operating_mode=OperatingMode.HYBRID_RESEARCH, htf_bias=HtfBias.BULLISH),
        ml,
    )
    assert signal.decision == Decision.BUY
    assert signal.research_only is True
    assert signal.ml.direction == MLDirection.NOT_UP_HORIZON


def test_hybrid_validated_rejects_when_not_approved():
    signal = evaluate_signal(
        long_setup_df(),
        StrategyConfig(operating_mode=OperatingMode.HYBRID_VALIDATED, htf_bias=HtfBias.BULLISH),
    )
    assert signal.decision == Decision.NO_TRADE
    assert signal.rejection_reasons == ["model_not_verified"]
