from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
OHLC_COLUMNS = ["open", "high", "low", "close"]


class DataValidationError(ValueError):
    pass


def _canonical_column_name(column: object) -> str:
    return str(column).strip().lower().strip("<>")


def read_ohlcv_csv_raw(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise DataValidationError(f"CSV file does not exist: {path}")
    with path.open("rb") as binary:
        prefix = binary.read(4)
    encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    with path.open(encoding=encoding, errors="ignore") as source:
        first_line = next((line.strip() for line in source if line.strip()), "")
    if not first_line:
        raise DataValidationError(f"CSV file is empty: {path}")

    delimiter = "\t" if first_line.count("\t") > first_line.count(",") else ","
    first_field = first_line.split(delimiter, 1)[0].strip()
    headerless_mt5 = bool(
        re.fullmatch(r"\d{4}[./-]\d{2}[./-]\d{2}\s+\d{2}:\d{2}(?::\d{2})?", first_field)
    )

    if first_line.startswith("Price,"):
        frame = pd.read_csv(
            path,
            skiprows=3,
            header=None,
            names=["timestamp", "close", "high", "low", "open", "volume"],
            encoding=encoding,
        )
        volume_present = True
    elif headerless_mt5:
        raw = pd.read_csv(path, sep=delimiter, encoding=encoding, header=None)
        if raw.shape[1] < 6:
            raise DataValidationError(
                "Headerless MT5 export requires timestamp, OHLC, and tick-volume fields."
            )
        frame = pd.DataFrame(
            {
                "timestamp": raw.iloc[:, 0],
                "open": raw.iloc[:, 1],
                "high": raw.iloc[:, 2],
                "low": raw.iloc[:, 3],
                "close": raw.iloc[:, 4],
                "volume": raw.iloc[:, 5],
            }
        )
        volume_present = True
    else:
        raw = pd.read_csv(path, sep=delimiter, encoding=encoding)
        raw = raw.rename(columns={column: _canonical_column_name(column) for column in raw.columns})
        if "timestamp" in raw.columns:
            timestamp = raw["timestamp"]
        elif "datetime" in raw.columns:
            timestamp = raw["datetime"]
        elif "date" in raw.columns and "time" in raw.columns:
            timestamp = raw["date"].astype(str).str.strip() + " " + raw["time"].astype(str).str.strip()
        elif "date" in raw.columns:
            timestamp = raw["date"]
        else:
            raise DataValidationError(
                "CSV requires timestamp, datetime, date, or date/time columns."
            )

        missing = [column for column in OHLC_COLUMNS if column not in raw.columns]
        if missing:
            raise DataValidationError(
                f"CSV is missing required OHLC columns: {', '.join(missing)}"
            )
        volume_column = next(
            (
                column
                for column in ("volume", "tick_volume", "tickvol", "vol")
                if column in raw.columns
            ),
            None,
        )
        volume_present = volume_column is not None
        frame = pd.DataFrame(
            {
                "timestamp": timestamp,
                "open": raw["open"],
                "high": raw["high"],
                "low": raw["low"],
                "close": raw["close"],
                "volume": raw[volume_column] if volume_column else pd.NA,
            }
        )

    frame.attrs["volume_column_present"] = volume_present
    return frame[CANONICAL_COLUMNS]


def _timestamp_mode(series: pd.Series) -> str:
    modes: set[str] = set()
    for value in series.dropna():
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if pd.isna(timestamp):
            continue
        modes.add("aware" if timestamp.tzinfo is not None else "naive")
        if len(modes) > 1:
            raise DataValidationError(
                "Timestamp column mixes timezone-aware and naive values."
            )
    return next(iter(modes), "unknown")


def normalize_timestamp_series(
    series: pd.Series,
    source_timezone: str | None = None,
) -> tuple[pd.Series, str]:
    mode = _timestamp_mode(series)
    if mode == "naive":
        if not source_timezone:
            raise DataValidationError(
                "Naive timestamps require --source-timezone, for example UTC or America/New_York."
            )
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
        try:
            normalized = parsed.dt.tz_localize(
                source_timezone,
                ambiguous="raise",
                nonexistent="raise",
            ).dt.tz_convert("UTC")
        except Exception as exc:
            raise DataValidationError(
                f"Could not localize timestamps with source timezone {source_timezone!r}; "
                "DST-ambiguous and nonexistent local times must be resolved in the source export."
            ) from exc
        return normalized, mode

    normalized = pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    return normalized, mode


def normalize_ohlcv_frame(
    frame: pd.DataFrame,
    source_timezone: str | None = None,
) -> tuple[pd.DataFrame, str]:
    result = frame.copy()
    volume_present = bool(frame.attrs.get("volume_column_present", "volume" in frame.columns))
    result["timestamp"], timestamp_mode = normalize_timestamp_series(
        result["timestamp"], source_timezone
    )
    for column in [*OHLC_COLUMNS, "volume"]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result.attrs["volume_column_present"] = volume_present
    result.attrs["source_timestamp_mode"] = timestamp_mode
    return result[CANONICAL_COLUMNS], timestamp_mode


def _strict_frame_errors(frame: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    if frame.empty:
        errors.append("no data rows")
        return errors
    if frame["timestamp"].isna().any():
        errors.append("unparseable timestamps")
    if frame[OHLC_COLUMNS].isna().any(axis=None):
        errors.append("missing or non-numeric OHLC values")
    valid_timestamps = frame["timestamp"].dropna()
    if valid_timestamps.duplicated().any():
        errors.append("duplicate timestamps")
    if not valid_timestamps.is_monotonic_increasing:
        errors.append("unsorted timestamps")

    complete = frame.dropna(subset=OHLC_COLUMNS)
    invalid_ohlc = (
        (complete["high"] < complete["open"])
        | (complete["high"] < complete["close"])
        | (complete["high"] < complete["low"])
        | (complete["low"] > complete["open"])
        | (complete["low"] > complete["close"])
    )
    if invalid_ohlc.any():
        errors.append("invalid OHLC relationships")
    if (complete[OHLC_COLUMNS] <= 0).any(axis=None):
        errors.append("non-positive prices")
    return errors


def infer_bar_delta(df: pd.DataFrame) -> pd.Timedelta:
    if len(df) < 2:
        return pd.Timedelta(minutes=15)
    deltas = df["timestamp"].sort_values().diff().dropna()
    if deltas.empty:
        return pd.Timedelta(minutes=15)
    return deltas.median()


def add_closed_at(df: pd.DataFrame, bar_delta: pd.Timedelta | None = None) -> pd.DataFrame:
    result = df.copy()
    delta = bar_delta or infer_bar_delta(result)
    result["closed_at"] = result["timestamp"] + delta
    return result


def load_ohlcv_csv(
    path: str | Path,
    source_timezone: str | None = None,
) -> pd.DataFrame:
    raw = read_ohlcv_csv_raw(path)
    frame, _ = normalize_ohlcv_frame(raw, source_timezone)
    errors = _strict_frame_errors(frame)
    if errors:
        joined = ", ".join(errors)
        raise DataValidationError(
            f"CSV failed strict validation: {joined}. Run 'aurumflow data-check' for details."
        )
    return add_closed_at(frame.reset_index(drop=True))


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    frame = df.sort_values("timestamp").set_index("timestamp")
    resampled = frame.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return add_closed_at(resampled[CANONICAL_COLUMNS], pd.to_timedelta(rule))


def causal_join_htf(base: pd.DataFrame, htf: pd.DataFrame, prefix: str) -> pd.DataFrame:
    base_sorted = base.sort_values("closed_at").reset_index(drop=True)
    htf_sorted = htf.sort_values("closed_at").reset_index(drop=True)
    htf_cols = ["closed_at", "open", "high", "low", "close", "volume"]
    renamed = htf_sorted[htf_cols].rename(
        columns={
            "closed_at": f"{prefix}_closed_at",
            "open": f"{prefix}_open",
            "high": f"{prefix}_high",
            "low": f"{prefix}_low",
            "close": f"{prefix}_close",
            "volume": f"{prefix}_volume",
        }
    )
    joined = pd.merge_asof(
        base_sorted,
        renamed,
        left_on="closed_at",
        right_on=f"{prefix}_closed_at",
        direction="backward",
        allow_exact_matches=True,
    )
    return joined
