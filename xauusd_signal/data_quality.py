from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .data import (
    CANONICAL_COLUMNS,
    OHLC_COLUMNS,
    DataValidationError,
    normalize_ohlcv_frame,
    read_ohlcv_csv_raw,
)


@dataclass(frozen=True)
class DataQualityReport:
    source_path: str
    source: str
    symbol: str
    broker: str
    price_type: str
    expected_frequency: str
    large_gap_threshold: str
    total_rows: int
    first_timestamp: str
    last_timestamp: str
    duration_days: float
    minimum_history_days: int
    meets_minimum_history: bool
    source_timestamp_mode: str
    source_timezone: str
    internal_timezone: str
    timestamp_parse_errors: int
    duplicate_timestamps: int
    unsorted_timestamp_pairs: int
    missing_ohlc_values: dict[str, int]
    missing_ohlc_rows: int
    invalid_ohlc_relationships: int
    invalid_ohlc_breakdown: dict[str, int]
    non_positive_prices: int
    zero_range_candles: int
    frequency_inconsistencies: int
    estimated_missing_bars: int
    large_timestamp_gaps: int
    gap_examples: tuple[dict, ...]
    weekend_rows: int
    duplicate_candles: int
    volume_available: bool
    volume_non_null: int
    volume_missing: int
    volume_zero: int
    valid_for_research: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        lines = [
            "AurumFlow data quality report",
            f"Path: {self.source_path}",
            (
                f"Source: {self.source} | symbol: {self.symbol} | "
                f"broker/feed: {self.broker} | price type: {self.price_type}"
            ),
            (
                f"Rows: {self.total_rows} | {self.first_timestamp} to "
                f"{self.last_timestamp} | {self.duration_days:.2f} days"
            ),
            (
                f"Timestamps: {self.source_timestamp_mode} source "
                f"({self.source_timezone}) -> {self.internal_timezone}"
            ),
            f"Expected frequency: {self.expected_frequency}",
            "",
            f"valid_for_research: {self.valid_for_research}",
            f"meets_minimum_history: {self.meets_minimum_history}",
            f"timestamp_parse_errors: {self.timestamp_parse_errors}",
            f"duplicate_timestamps: {self.duplicate_timestamps}",
            f"unsorted_timestamp_pairs: {self.unsorted_timestamp_pairs}",
            f"missing_ohlc_rows: {self.missing_ohlc_rows}",
            f"invalid_ohlc_relationships: {self.invalid_ohlc_relationships}",
            f"non_positive_prices: {self.non_positive_prices}",
            f"zero_range_candles: {self.zero_range_candles}",
            f"frequency_inconsistencies: {self.frequency_inconsistencies}",
            f"estimated_missing_bars: {self.estimated_missing_bars}",
            f"large_timestamp_gaps: {self.large_timestamp_gaps}",
            f"weekend_rows: {self.weekend_rows}",
            f"duplicate_candles: {self.duplicate_candles}",
            (
                f"volume: available={self.volume_available}, "
                f"non_null={self.volume_non_null}, missing={self.volume_missing}, "
                f"zero={self.volume_zero}"
            ),
        ]
        if self.warnings:
            lines.extend(["", "Warnings"])
            lines.extend(f"- {warning}" for warning in self.warnings)
        if self.gap_examples:
            lines.extend(["", "Large gap examples"])
            lines.extend(
                (
                    f"- {gap['start']} -> {gap['end']} "
                    f"({gap['duration']}, estimated missing bars: {gap['estimated_missing_bars']})"
                )
                for gap in self.gap_examples
            )
        return "\n".join(lines)


@dataclass
class DataQualityResult:
    report: DataQualityReport
    normalized: pd.DataFrame

    def write_normalized_csv(self, path: str | Path) -> Path:
        if not self.report.valid_for_research:
            raise DataValidationError(
                "Normalized output was not written because structural data-quality checks failed."
            )
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.normalized[CANONICAL_COLUMNS].to_csv(destination, index=False)
        return destination


def _invalid_ohlc_breakdown(frame: pd.DataFrame) -> tuple[dict[str, int], pd.Series]:
    complete = frame.dropna(subset=OHLC_COLUMNS)
    conditions = {
        "high_below_open": complete["high"] < complete["open"],
        "high_below_close": complete["high"] < complete["close"],
        "high_below_low": complete["high"] < complete["low"],
        "low_above_open": complete["low"] > complete["open"],
        "low_above_close": complete["low"] > complete["close"],
    }
    invalid_rows = pd.Series(False, index=complete.index)
    for condition in conditions.values():
        invalid_rows |= condition
    return ({name: int(condition.sum()) for name, condition in conditions.items()}, invalid_rows)


def _gap_summary(
    timestamps: pd.Series,
    expected_delta: pd.Timedelta,
    large_gap_multiple: int,
) -> tuple[int, int, int, tuple[dict, ...]]:
    ordered = timestamps.dropna().drop_duplicates().sort_values().reset_index(drop=True)
    deltas = ordered.diff()
    inconsistencies = int((deltas.dropna() != expected_delta).sum())
    missing_bars = 0
    examples: list[dict] = []
    threshold = expected_delta * large_gap_multiple
    for index in range(1, len(ordered)):
        delta = ordered.iloc[index] - ordered.iloc[index - 1]
        estimated = max(int(delta // expected_delta) - 1, 0)
        missing_bars += estimated
        if delta > threshold:
            examples.append(
                {
                    "start": str(ordered.iloc[index - 1]),
                    "end": str(ordered.iloc[index]),
                    "duration": str(delta),
                    "estimated_missing_bars": estimated,
                }
            )
    return inconsistencies, missing_bars, len(examples), tuple(examples[:10])


def inspect_ohlcv_csv(
    path: str | Path,
    source_timezone: str | None = None,
    expected_frequency: str = "15min",
    large_gap_multiple: int = 4,
    minimum_history_days: int = 365,
    source: str = "unknown",
    symbol: str = "XAUUSD",
    broker: str = "unknown",
    price_type: str = "unknown",
) -> DataQualityResult:
    if large_gap_multiple < 2:
        raise DataValidationError("large_gap_multiple must be at least 2")
    if minimum_history_days < 1:
        raise DataValidationError("minimum_history_days must be at least 1")
    try:
        expected_delta = pd.to_timedelta(expected_frequency)
    except (TypeError, ValueError) as exc:
        raise DataValidationError(
            f"Invalid expected_frequency: {expected_frequency}"
        ) from exc
    if expected_delta <= pd.Timedelta(0):
        raise DataValidationError("expected_frequency must be positive")

    raw = read_ohlcv_csv_raw(path)
    volume_available = bool(raw.attrs.get("volume_column_present", False))
    frame, timestamp_mode = normalize_ohlcv_frame(raw, source_timezone)
    timestamps = frame["timestamp"]
    valid_timestamps = timestamps.dropna()
    timestamp_parse_errors = int(timestamps.isna().sum())
    duplicate_timestamps = int(valid_timestamps.duplicated(keep="first").sum())
    unsorted_timestamp_pairs = int((valid_timestamps.diff() < pd.Timedelta(0)).sum())

    missing_ohlc_values = {
        column: int(frame[column].isna().sum()) for column in OHLC_COLUMNS
    }
    missing_ohlc_rows = int(frame[OHLC_COLUMNS].isna().any(axis=1).sum())
    invalid_breakdown, invalid_mask = _invalid_ohlc_breakdown(frame)
    invalid_ohlc_relationships = int(invalid_mask.sum())
    complete = frame.dropna(subset=OHLC_COLUMNS)
    non_positive_prices = int((complete[OHLC_COLUMNS] <= 0).any(axis=1).sum())
    zero_range_candles = int((complete["high"] == complete["low"]).sum())
    duplicate_candles = int(
        frame.duplicated(subset=CANONICAL_COLUMNS, keep="first").sum()
    )

    frequency_inconsistencies, estimated_missing_bars, large_gaps, gap_examples = (
        _gap_summary(timestamps, expected_delta, large_gap_multiple)
    )
    weekend_rows = int((valid_timestamps.dt.dayofweek >= 5).sum())

    if valid_timestamps.empty:
        first_timestamp = ""
        last_timestamp = ""
        duration_days = 0.0
    else:
        first = valid_timestamps.min()
        last = valid_timestamps.max()
        first_timestamp = str(first)
        last_timestamp = str(last)
        duration_days = (last - first).total_seconds() / 86_400
    meets_minimum_history = duration_days >= minimum_history_days

    volume_non_null = int(frame["volume"].notna().sum())
    volume_missing = int(frame["volume"].isna().sum())
    volume_zero = int((frame["volume"] == 0).sum())

    fatal_counts = (
        timestamp_parse_errors,
        duplicate_timestamps,
        unsorted_timestamp_pairs,
        missing_ohlc_rows,
        invalid_ohlc_relationships,
        non_positive_prices,
    )
    valid_for_research = bool(len(frame) > 0 and not any(fatal_counts))
    warnings: list[str] = []
    if frequency_inconsistencies:
        warnings.append(
            "Timestamp gaps differ from the expected frequency; market closures and missing data are not distinguished automatically."
        )
    if weekend_rows:
        warnings.append("Weekend rows are present after UTC normalization.")
    if not volume_available or volume_missing:
        warnings.append("Volume is unavailable or incomplete; current RULE_ONLY logic does not depend on it.")
    if not meets_minimum_history:
        warnings.append(
            f"History is shorter than the {minimum_history_days}-day diagnostic target."
        )
    if zero_range_candles:
        warnings.append("Zero-range candles are present and should be checked against the source feed.")

    report = DataQualityReport(
        source_path=str(Path(path)),
        source=source,
        symbol=symbol,
        broker=broker,
        price_type=price_type,
        expected_frequency=str(expected_delta),
        large_gap_threshold=str(expected_delta * large_gap_multiple),
        total_rows=len(frame),
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        duration_days=duration_days,
        minimum_history_days=minimum_history_days,
        meets_minimum_history=meets_minimum_history,
        source_timestamp_mode=timestamp_mode,
        source_timezone=source_timezone or ("embedded offset" if timestamp_mode == "aware" else "unknown"),
        internal_timezone="UTC",
        timestamp_parse_errors=timestamp_parse_errors,
        duplicate_timestamps=duplicate_timestamps,
        unsorted_timestamp_pairs=unsorted_timestamp_pairs,
        missing_ohlc_values=missing_ohlc_values,
        missing_ohlc_rows=missing_ohlc_rows,
        invalid_ohlc_relationships=invalid_ohlc_relationships,
        invalid_ohlc_breakdown=invalid_breakdown,
        non_positive_prices=non_positive_prices,
        zero_range_candles=zero_range_candles,
        frequency_inconsistencies=frequency_inconsistencies,
        estimated_missing_bars=estimated_missing_bars,
        large_timestamp_gaps=large_gaps,
        gap_examples=gap_examples,
        weekend_rows=weekend_rows,
        duplicate_candles=duplicate_candles,
        volume_available=volume_available,
        volume_non_null=volume_non_null,
        volume_missing=volume_missing,
        volume_zero=volume_zero,
        valid_for_research=valid_for_research,
        warnings=tuple(warnings),
    )
    return DataQualityResult(report=report, normalized=frame.reset_index(drop=True))
