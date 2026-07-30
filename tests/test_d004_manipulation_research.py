from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.manipulation_0830_0900.bars import (
    aggregate_bars,
    sha256_file,
    ticks_to_one_minute,
)
from research.manipulation_0830_0900.config import (
    ResearchConfig,
    trading_session_date,
    utc_bounds,
)
from research.manipulation_0830_0900.features import (
    _load_event_labels,
    build_daily_events,
    classify_displacement_expanding,
    classify_sweep,
    detect_fvgs,
    displacement_metrics,
    label_hod_lod,
    summarize_window,
    window_slice,
)
from research.manipulation_0830_0900.pipeline import run_research
from research.manipulation_0830_0900.verification import verify_output
from xauusd_signal.strategy import StrategyConfig
from xauusd_signal.types import EntryModel


def _bar_frame(index: pd.DatetimeIndex, prices: np.ndarray | list[float]) -> pd.DataFrame:
    mid = np.asarray(prices, dtype=float)
    spread = np.full(len(index), 0.20)
    frame = pd.DataFrame(index=index)
    for name, offset in (("mid", 0.0), ("bid", -0.10), ("ask", 0.10)):
        base = mid + offset
        frame[f"{name}_open"] = base
        frame[f"{name}_high"] = base + 0.04
        frame[f"{name}_low"] = base - 0.04
        frame[f"{name}_close"] = base + 0.01
    frame["tick_count"] = 2
    frame["median_spread"] = spread
    frame["maximum_spread"] = spread
    frame["last_spread"] = spread
    frame.index.name = "timestamp_utc"
    return frame


def _continuous_bars(start: str, end: str) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="1min", inclusive="left", tz="UTC")
    position = np.arange(len(index), dtype=float)
    prices = 2000.0 + 0.001 * position + 0.30 * np.sin(position / 31.0)
    return _bar_frame(index, prices)


def test_new_york_conversion_uses_dst_not_a_fixed_offset() -> None:
    winter, _ = utc_bounds(date(2025, 3, 7), "08:30", "09:00")
    summer, summer_end = utc_bounds(date(2025, 3, 10), "08:30", "09:00")

    assert winter == pd.Timestamp("2025-03-07 13:30", tz="UTC")
    assert summer == pd.Timestamp("2025-03-10 12:30", tz="UTC")
    assert summer_end - summer == pd.Timedelta(minutes=30)


def test_dst_autumn_transition_changes_utc_mapping_without_changing_duration() -> None:
    before, _ = utc_bounds(date(2025, 10, 31), "08:30", "09:00")
    after, after_end = utc_bounds(date(2025, 11, 3), "08:30", "09:00")

    assert before == pd.Timestamp("2025-10-31 12:30", tz="UTC")
    assert after == pd.Timestamp("2025-11-03 13:30", tz="UTC")
    assert after_end - after == pd.Timedelta(minutes=30)


def test_trading_session_mapping_reuses_1800_new_york_boundary() -> None:
    evening = pd.Timestamp("2025-01-05 18:00", tz="America/New_York")
    daytime = pd.Timestamp("2025-01-06 16:59", tz="America/New_York")

    assert trading_session_date(evening) == date(2025, 1, 6)
    assert trading_session_date(daytime) == date(2025, 1, 6)


def test_half_open_window_includes_0830_and_excludes_0900() -> None:
    local = pd.DatetimeIndex(
        [
            "2025-01-06 08:29",
            "2025-01-06 08:30",
            "2025-01-06 08:59",
            "2025-01-06 09:00",
        ],
        tz="America/New_York",
    )
    bars = _bar_frame(local.tz_convert("UTC"), [1.0, 2.0, 3.0, 4.0])

    selected = window_slice(bars, date(2025, 1, 6), "08:30", "09:00")

    assert list(selected["mid_open"]) == [2.0, 3.0]


def test_tick_candles_are_left_aligned_and_ohlc_consistent() -> None:
    ticks = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(
                [
                    "2025-01-06T13:30:00.000Z",
                    "2025-01-06T13:30:59.999Z",
                    "2025-01-06T13:31:00.000Z",
                ],
                utc=True,
            ),
            "bid": [1999.9, 2000.9, 2001.9],
            "ask": [2000.1, 2001.1, 2002.1],
            "mid": [2000.0, 2001.0, 2002.0],
            "spread": [0.2, 0.2, 0.2],
        }
    )

    bars = ticks_to_one_minute(ticks)

    assert list(bars.index) == [
        pd.Timestamp("2025-01-06 13:30", tz="UTC"),
        pd.Timestamp("2025-01-06 13:31", tz="UTC"),
    ]
    assert bars.iloc[0]["mid_open"] == 2000.0
    assert bars.iloc[0]["mid_high"] == 2001.0
    assert bars.iloc[0]["mid_close"] == 2001.0
    assert bars.iloc[0]["tick_count"] == 2


def test_five_and_fifteen_minute_candles_reconcile_one_minute_inputs() -> None:
    index = pd.date_range("2025-01-06 13:30", periods=15, freq="1min", tz="UTC")
    one = _bar_frame(index, np.arange(15, dtype=float) + 2000.0)

    five = aggregate_bars(one, 5)
    fifteen = aggregate_bars(one, 15)

    assert list(five.index.minute) == [30, 35, 40]
    assert five.iloc[0]["mid_open"] == one.iloc[0]["mid_open"]
    assert five.iloc[0]["mid_close"] == one.iloc[4]["mid_close"]
    assert fifteen.iloc[0]["mid_high"] == one["mid_high"].max()
    assert fifteen.iloc[0]["tick_count"] == 30


def test_sweep_and_reentry_classification_is_directionally_explicit() -> None:
    index = pd.date_range("2025-01-06 13:30", periods=4, freq="1min", tz="UTC")
    window = _bar_frame(index, [100.0, 101.2, 100.7, 100.4])
    window.loc[index[1], "mid_high"] = 101.6
    window.loc[index[2], "mid_close"] = 100.8

    result = classify_sweep(
        window,
        reference_high=101.0,
        reference_low=99.0,
        threshold_price=0.5,
    )

    assert result["sweep_type"] == "high_only"
    assert result["high_sweep"] is True
    assert result["low_sweep"] is False
    assert result["high_reentry"] is True
    assert result["high_reentry_time"] == index[2]
    assert result["high_reentry_minutes"] == 1.0


def test_both_side_sweep_is_not_collapsed_into_one_direction() -> None:
    index = pd.date_range("2025-01-06 13:30", periods=3, freq="1min", tz="UTC")
    window = _bar_frame(index, [100.0, 100.0, 100.0])
    window.loc[index[0], "mid_high"] = 102.0
    window.loc[index[1], "mid_low"] = 98.0

    result = classify_sweep(
        window,
        reference_high=101.0,
        reference_low=99.0,
        threshold_price=0.5,
    )

    assert result["both_side_sweep"] is True
    assert result["sweep_type"] == "both"
    assert result["neither_sweep"] is False


def test_displacement_metrics_and_prior_only_classification() -> None:
    index = pd.date_range("2025-01-06 13:30", periods=3, freq="1min", tz="UTC")
    window = _bar_frame(index, [100.0, 101.0, 102.0])
    metrics = displacement_metrics(window, prior_atr=2.0)
    source = pd.DataFrame(
        {
            "trading_date": pd.date_range("2025-01-01", periods=5).date,
            "window_range_atr": [1.0, 2.0, 3.0, 4.0, 100.0],
        }
    )
    classified = classify_displacement_expanding(source, minimum_history=2)
    changed_future = source.copy()
    changed_future.loc[4, "window_range_atr"] = 10000.0
    changed = classify_displacement_expanding(changed_future, minimum_history=2)

    assert metrics["window_range_atr"] > 1.0
    assert classified.loc[2, "displacement_history_count"] == 2
    assert classified.loc[2, "displacement_class"] == "extreme"
    pd.testing.assert_series_equal(
        classified.loc[:3, "displacement_class"],
        changed.loc[:3, "displacement_class"],
    )


def test_hod_lod_labels_exact_and_tolerance_adjusted_rates() -> None:
    index = pd.date_range("2025-01-06 13:00", periods=5, freq="1min", tz="UTC")
    day = _bar_frame(index, [100.0, 103.0, 101.0, 98.0, 100.0])
    window = day.iloc[1:3]

    labels = label_hod_lod(day, window, tick_size=0.01, prior_atr=2.0)

    assert labels["window_creates_hod"] is True
    assert labels["window_creates_lod"] is False
    assert labels["window_within_hod_1tick"] is True
    assert labels["hod_time"] == index[1]

    near_window = window.copy()
    near_window.loc[:, "mid_high"] = near_window["mid_high"].clip(
        upper=day["mid_high"].max() - 0.005
    )
    near_labels = label_hod_lod(
        day, near_window, tick_size=0.01, prior_atr=2.0
    )
    assert near_labels["window_creates_hod"] is False
    assert near_labels["window_within_hod_1tick"] is True


def test_missing_window_is_explicitly_incomplete_and_not_filled() -> None:
    frame = _bar_frame(
        pd.date_range("2025-01-06 13:30", periods=29, freq="1min", tz="UTC"),
        np.arange(29, dtype=float) + 2000.0,
    )

    summary = summarize_window(frame, "window", 30)

    assert summary["window_minute_count"] == 29
    assert summary["window_complete"] is False


def test_fvg_availability_is_third_bar_close_not_open() -> None:
    index = pd.date_range("2025-01-06 13:30", periods=3, freq="1min", tz="UTC")
    bars = _bar_frame(index, [100.0, 101.0, 103.0])
    bars.loc[index[0], "mid_high"] = 100.5
    bars.loc[index[2], "mid_low"] = 102.0

    fvgs = detect_fvgs(bars, resolution_minutes=1)

    assert len(fvgs) == 1
    assert fvgs.iloc[0]["direction"] == "bullish"
    assert fvgs.iloc[0]["creation_time"] == index[2] + pd.Timedelta(minutes=1)

    sub_tick = bars.copy()
    sub_tick.loc[index[2], "mid_low"] = 100.505
    assert detect_fvgs(
        sub_tick, resolution_minutes=1, minimum_width=0.01
    ).empty


def test_optional_event_labels_reject_timezone_naive_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_text(
        "trading_date,event_timestamp,event_label\n"
        "2025-01-06,2025-01-06 08:30:00,CPI\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="explicit timezone"):
        _load_event_labels(path, "America/New_York")


def test_daily_feature_rerun_is_deterministic_and_preserves_production_defaults(
    tmp_path: Path,
) -> None:
    bars = _continuous_bars("2025-01-05 22:00", "2025-01-10 22:00")
    config = ResearchConfig(
        dataset_root=tmp_path,
        output_dir=tmp_path / "output",
        start_date=date(2025, 1, 6),
        end_date=date(2025, 1, 8),
        displacement_history_days=2,
        bootstrap_resamples=100,
    )

    first_daily, first_fvg = build_daily_events(bars, config)
    second_daily, second_fvg = build_daily_events(bars, config)

    pd.testing.assert_frame_equal(first_daily, second_daily)
    pd.testing.assert_frame_equal(first_fvg, second_fvg)
    assert list(EntryModel) == [EntryModel.FVG_MIDPOINT]
    assert StrategyConfig().entry_model == EntryModel.FVG_MIDPOINT


def _write_canonical_fixture(root: Path) -> tuple[Path, dict[str, str]]:
    dataset_root = root / "data" / "canonical" / "xauusd_ticks"
    dataset_root.mkdir(parents=True)
    records = []
    source_hashes: dict[str, str] = {}
    total_rows = 0
    for utc_date in pd.date_range("2025-01-05", "2025-01-09", freq="D"):
        index = pd.date_range(
            utc_date,
            utc_date + pd.Timedelta(days=1),
            freq="1min",
            inclusive="left",
            tz="UTC",
        )
        position = np.arange(len(index), dtype=float)
        day_offset = (utc_date.date() - date(2025, 1, 5)).days
        mid = 2000.0 + day_offset + 0.20 * np.sin(position / 17.0) + position * 0.0005
        spread = np.full(len(index), 0.20)
        frame = pd.DataFrame(
            {
                "timestamp_utc": index,
                "bid": mid - spread / 2,
                "ask": mid + spread / 2,
                "bid_volume": np.ones(len(index), dtype="float32"),
                "ask_volume": np.ones(len(index), dtype="float32"),
                "mid": mid,
                "spread": spread,
                "symbol": "XAUUSD",
                "source_partition": index.strftime("%Y-%m-%dT%H:00:00Z"),
            }
        )
        target = (
            dataset_root
            / f"year={utc_date.year:04d}"
            / f"month={utc_date.month:02d}"
            / f"xauusd_ticks_{utc_date.date().isoformat()}.parquet"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False, engine="pyarrow", compression="zstd")
        relative = target.relative_to(root)
        digest = sha256_file(target)
        source_hashes[str(relative)] = digest
        records.append(
            {
                "date": utc_date.date().isoformat(),
                "path": str(relative),
                "sha256": digest,
                "row_count": len(frame),
            }
        )
        total_rows += len(frame)
    manifest = {
        "dataset_version": "d003-v1",
        "dataset_id": "synthetic-d004",
        "canonical_file_count": len(records),
        "row_count": total_rows,
        "date_range": {
            "start_inclusive": "2025-01-05T00:00:00Z",
            "end_exclusive": "2025-01-10T00:00:00Z",
        },
        "files": records,
    }
    (dataset_root / "canonical_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return dataset_root, source_hashes


def test_small_synthetic_end_to_end_fixture_is_resumable_and_independently_verified(
    tmp_path: Path,
) -> None:
    dataset_root, source_hashes = _write_canonical_fixture(tmp_path)
    output = tmp_path / "research_output"
    report = tmp_path / "D004.md"
    config = ResearchConfig(
        dataset_root=dataset_root,
        output_dir=output,
        start_date=date(2025, 1, 6),
        end_date=date(2025, 1, 8),
        displacement_history_days=2,
        bootstrap_resamples=100,
        random_seed=44,
        report_path=report,
    )

    first = run_research(config, argv=["synthetic-d004"])
    daily_hash = sha256_file(output / "daily_events.parquet")
    strategy_hash = sha256_file(output / "strategy_events.parquet")
    second = run_research(config, argv=["synthetic-d004"])
    verification = verify_output(output)

    assert first["verification"]["status"] == "PASS"
    assert second["verification"]["status"] == "PASS"
    assert verification["status"] == "PASS"
    assert sha256_file(output / "daily_events.parquet") == daily_hash
    assert sha256_file(output / "strategy_events.parquet") == strategy_hash
    assert report.is_file()
    assert second["metadata"]["bar_cache_reused_files"] == 5
    for relative, digest in source_hashes.items():
        assert sha256_file(tmp_path / relative) == digest
