from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.event_study_0830_0930.tick_qualification import (
    normalize_ticks,
    validate_ticks,
    verify_normalized_outputs,
)


def _write_ticks(path: Path) -> None:
    path.write_text(
        "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\r\n"
        "2025.07.17\t13:00:00.000\t3325.56\t3325.71\t\t\t6\r\n"
        "2025.07.17\t13:00:00.000\t3325.57\t\t\t\t2\r\n"
        "2025.07.17\t13:00:30.000\t\t3325.73\t\t\t4\r\n"
        "2025.07.17\t13:01:00.000\t3325.59\t3325.74\t\t\t4\r\n",
        encoding="ascii",
        newline="",
    )


def test_streaming_validation_and_normalization_are_isolated(tmp_path: Path) -> None:
    source = tmp_path / "ticks.csv"
    reports = tmp_path / "reports"
    normalized = tmp_path / "normalized"
    _write_ticks(source)
    original = source.read_bytes()

    metadata = validate_ticks(
        source,
        reports,
        source_timezone="UTC",
        timezone_status="confirmed",
        chunk_rows=2,
        progress_rows=2,
    )

    assert metadata["validation"]["physical_data_rows"] == 4
    assert metadata["validation"]["duplicate_timestamp_rows"] == 1
    assert metadata["validation"]["monotonicity_violations"] == 0
    assert metadata["validation"]["spread"]["median"] == 0.15
    assert metadata["validation"]["reconstructed_bid_rows"] == 1
    assert metadata["validation"]["reconstructed_ask_rows"] == 1
    assert metadata["quality"]["normalization_gate_passed"] is True
    assert source.read_bytes() == original

    completed = normalize_ticks(
        source,
        reports,
        normalized,
        source_timezone="UTC",
        chunk_rows=2,
        progress_rows=2,
    )

    assert completed["outputs"]["normalized_tick_rows"] == 4
    assert completed["outputs"]["minute_bar_rows"] == 2
    ticks = pd.read_csv(normalized / "ticks.canonical_ticks.csv")
    bars = pd.read_csv(normalized / "ticks.1m_bidask.csv")
    assert list(ticks.columns) == ["timestamp", "bid", "ask", "flags", "source", "symbol"]
    assert bars.loc[0, "bid_open"] == 3325.56
    assert bars.loc[0, "bid_close"] == 3325.57
    assert bars.loc[0, "ask_high"] == 3325.73
    assert bars.loc[0, "tick_count"] == 3
    assert source.read_bytes() == original
    verified = verify_normalized_outputs(reports)
    assert verified["derivative_verification"]["status"] == "PASS"
