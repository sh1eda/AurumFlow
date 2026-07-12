import json

import pandas as pd

from xauusd_signal.cli import main


def test_cli_signal_outputs_json(tmp_path, capsys):
    path = tmp_path / "bars.csv"
    pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=2, freq="15min", tz="UTC"),
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
            "volume": [1, 1],
        }
    ).to_csv(path, index=False)
    code = main(["signal", "--csv", str(path), "--htf-bias", "BULLISH"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "NO_TRADE"
    assert "insufficient_data" in payload["rejection_reasons"]
