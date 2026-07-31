import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from xauusd_signal.cli import _load_tail, main
from xauusd_signal.data import DataValidationError, load_ohlcv_csv
from xauusd_signal.data_quality import inspect_ohlcv_csv


def valid_frame(timestamps=None, include_volume=True) -> pd.DataFrame:
    if timestamps is None:
        timestamps = pd.date_range(
            "2025-01-06 00:00", periods=4, freq="15min", tz="UTC"
        )
    data = {
        "timestamp": timestamps,
        "open": [2640.0, 2641.0, 2642.0, 2643.0],
        "high": [2642.0, 2643.0, 2644.0, 2645.0],
        "low": [2639.0, 2640.0, 2641.0, 2642.0],
        "close": [2641.0, 2642.0, 2643.0, 2644.0],
    }
    if include_volume:
        data["volume"] = [100, 110, 120, 130]
    return pd.DataFrame(data)


def write_csv(tmp_path: Path, frame: pd.DataFrame, name: str = "bars.csv") -> Path:
    path = tmp_path / name
    frame.to_csv(path, index=False)
    return path


def test_data_check_accepts_valid_utc_data_and_nullable_volume(tmp_path):
    path = write_csv(tmp_path, valid_frame(include_volume=False))
    result = inspect_ohlcv_csv(path)

    assert result.report.total_rows == 4
    assert result.report.valid_for_research is True
    assert result.report.source_timestamp_mode == "aware"
    assert result.report.internal_timezone == "UTC"
    assert result.report.volume_available is False
    assert result.report.volume_missing == 4
    assert result.report.frequency_inconsistencies == 0


def test_naive_timestamps_are_rejected_without_source_timezone(tmp_path):
    naive = valid_frame().copy()
    naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
    path = write_csv(tmp_path, naive)

    with pytest.raises(DataValidationError, match="Naive timestamps require"):
        inspect_ohlcv_csv(path)
    assert main(["data-check", "--csv", str(path)]) == 2


def test_naive_source_timezone_is_normalized_to_utc(tmp_path):
    naive_times = pd.date_range("2025-01-06 09:30", periods=4, freq="15min")
    path = write_csv(tmp_path, valid_frame(naive_times))
    result = inspect_ohlcv_csv(path, source_timezone="America/New_York")

    assert result.normalized.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-01-06 14:30", tz="UTC"
    )
    assert result.report.source_timezone == "America/New_York"


def test_headerless_utf16_mt5_export_is_supported(tmp_path):
    path = tmp_path / "XAUUSDM15.csv"
    pd.DataFrame(
        [
            ["2025.01.06 02:00", 2640.0, 2642.0, 2639.0, 2641.0, 100, 0],
            ["2025.01.06 02:15", 2641.0, 2643.0, 2640.0, 2642.0, 110, 0],
        ]
    ).to_csv(path, index=False, header=False, encoding="utf-16")

    result = inspect_ohlcv_csv(path, source_timezone="Europe/Helsinki")
    assert result.report.total_rows == 2
    assert result.report.volume_available is True
    assert result.normalized.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-01-06 00:00", tz="UTC"
    )


def test_duplicate_timestamps_are_reported_and_block_normalized_output(tmp_path):
    frame = valid_frame()
    frame.loc[3, "timestamp"] = frame.loc[2, "timestamp"]
    path = write_csv(tmp_path, frame)
    result = inspect_ohlcv_csv(path)

    assert result.report.duplicate_timestamps == 1
    assert result.report.valid_for_research is False
    with pytest.raises(DataValidationError, match="was not written"):
        result.write_normalized_csv(tmp_path / "normalized.csv")


def test_invalid_ohlc_relationships_and_non_positive_prices_are_reported(tmp_path):
    frame = valid_frame()
    frame.loc[1, ["open", "high", "low", "close"]] = [2643.0, 2642.0, 2640.0, 2644.0]
    frame.loc[2, "low"] = 0.0
    path = write_csv(tmp_path, frame)
    report = inspect_ohlcv_csv(path).report

    assert report.invalid_ohlc_relationships == 1
    assert report.invalid_ohlc_breakdown["high_below_open"] == 1
    assert report.invalid_ohlc_breakdown["high_below_close"] == 1
    assert report.non_positive_prices == 1
    assert report.valid_for_research is False


def test_frequency_gaps_and_unsorted_pairs_are_reported(tmp_path):
    gap_times = pd.to_datetime(
        [
            "2025-01-06T00:00:00Z",
            "2025-01-06T00:15:00Z",
            "2025-01-06T01:30:00Z",
            "2025-01-06T01:45:00Z",
        ],
        utc=True,
    )
    gap_path = write_csv(tmp_path, valid_frame(gap_times), "gaps.csv")
    gap_report = inspect_ohlcv_csv(gap_path).report

    assert gap_report.frequency_inconsistencies == 1
    assert gap_report.estimated_missing_bars == 4
    assert gap_report.large_timestamp_gaps == 1

    unsorted = valid_frame()
    unsorted.loc[[1, 2], "timestamp"] = unsorted.loc[[2, 1], "timestamp"].to_numpy()
    unsorted_path = write_csv(tmp_path, unsorted, "unsorted.csv")
    unsorted_report = inspect_ohlcv_csv(unsorted_path).report
    assert unsorted_report.unsorted_timestamp_pairs == 1
    assert unsorted_report.valid_for_research is False


def test_explicit_normalized_output_is_loadable_by_strict_loader(tmp_path):
    source = write_csv(tmp_path, valid_frame())
    result = inspect_ohlcv_csv(source)
    destination = result.write_normalized_csv(tmp_path / "normalized" / "xauusd_15m.csv")

    loaded = load_ohlcv_csv(destination)
    assert len(loaded) == 4
    assert str(loaded.iloc[0]["timestamp"].tzinfo) == "UTC"


def test_utc_period_boundaries_are_inclusive_then_exclusive(tmp_path):
    path = write_csv(tmp_path, valid_frame())
    filtered = _load_tail(
        str(path),
        bars=None,
        source_timezone=None,
        start="2025-01-06T00:15:00Z",
        end="2025-01-06T00:45:00Z",
    )

    assert filtered["timestamp"].tolist() == [
        pd.Timestamp("2025-01-06T00:15:00Z"),
        pd.Timestamp("2025-01-06T00:30:00Z"),
    ]


def test_data_check_cli_json_and_local_data_path_is_gitignored(tmp_path, capsys):
    path = write_csv(tmp_path, valid_frame())
    code = main(["data-check", "--csv", str(path), "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid_for_research"] is True
    assert payload["total_rows"] == 4

    repository = Path(__file__).resolve().parents[1]
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/local/xauusd_15m.csv"],
        cwd=repository,
        check=False,
    )
    assert ignored.returncode == 0
