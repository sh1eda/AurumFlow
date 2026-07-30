"""Closed-bar validation and deterministic timeframe construction for D005."""

from __future__ import annotations

from datetime import date, timedelta
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import NEW_YORK


TIMEFRAME_MINUTES: Mapping[str, int] = MappingProxyType(
    {
        "1min": 1,
        "5min": 5,
        "15min": 15,
        "1H": 60,
        "4H": 240,
        "1D": 24 * 60,
        "1W": 7 * 24 * 60,
    }
)

OHLC = ("open", "high", "low", "close")


class BarValidationError(ValueError):
    """Raised when D005 bars cannot satisfy their closed-bar contract."""


def _utc_index(values: object) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    index.name = "timestamp_utc"
    return index


def normalize_bars(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Return a detached generic OHLC view with explicit close availability."""

    if timeframe not in TIMEFRAME_MINUTES:
        raise BarValidationError(f"unsupported timeframe: {timeframe}")
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "timestamp_utc" not in frame:
            raise BarValidationError("bars require a DatetimeIndex or timestamp_utc")
        source = frame.copy()
        index = _utc_index(source.pop("timestamp_utc"))
        source.index = index
    else:
        source = frame.copy()
        source.index = _utc_index(source.index)
    if source.index.has_duplicates or not source.index.is_monotonic_increasing:
        raise BarValidationError("bar timestamps must be unique and ordered")

    if set(OHLC).issubset(source.columns):
        out = source.loc[:, list(OHLC)].copy()
    elif {f"mid_{name}" for name in OHLC}.issubset(source.columns):
        out = source.loc[:, [f"mid_{name}" for name in OHLC]].rename(
            columns={f"mid_{name}": name for name in OHLC}
        )
    else:
        raise BarValidationError("bars require open/high/low/close or mid OHLC columns")

    for column in OHLC:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if out.isna().any().any() or not np.isfinite(out.to_numpy()).all():
        raise BarValidationError("bar OHLC contains missing or non-finite values")
    invalid = (
        out["high"].lt(out["low"])
        | out["high"].lt(out[["open", "close"]].max(axis=1))
        | out["low"].gt(out[["open", "close"]].min(axis=1))
    )
    if invalid.any():
        raise BarValidationError(f"{int(invalid.sum())} OHLC invariant violations")

    if "available_at" in source:
        available = _utc_index(source["available_at"])
    else:
        available = out.index + pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    if (available < out.index).any():
        raise BarValidationError("available_at cannot precede bar open")
    out["available_at"] = available
    if "observed_minutes" in source:
        out["observed_minutes"] = pd.to_numeric(
            source["observed_minutes"], errors="coerce"
        ).to_numpy()
    else:
        out["observed_minutes"] = TIMEFRAME_MINUTES[timeframe]
    out["timeframe"] = timeframe
    out.attrs["d005_closed_bar_contract"] = True
    return out


def closed_bars_asof(
    bars: pd.DataFrame, evaluation_at: pd.Timestamp
) -> pd.DataFrame:
    """Return only bars whose close/availability is no later than evaluation."""

    evaluation = pd.Timestamp(evaluation_at)
    if evaluation.tz is None:
        raise BarValidationError("evaluation timestamp must be timezone-aware")
    evaluation = evaluation.tz_convert("UTC")
    available = pd.to_datetime(bars["available_at"], utc=True)
    result = bars.loc[available.le(evaluation)].copy()
    if not result.empty and pd.to_datetime(
        result["available_at"], utc=True
    ).gt(evaluation).any():
        raise AssertionError("future bar escaped causal filter")
    return result


def _intraday_aggregate(one_minute: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    minutes = TIMEFRAME_MINUTES[timeframe]
    aggregated = one_minute[list(OHLC)].resample(
        f"{minutes}min", label="left", closed="left", origin="epoch"
    ).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    counts = one_minute["close"].resample(
        f"{minutes}min", label="left", closed="left", origin="epoch"
    ).size()
    aggregated["observed_minutes"] = counts
    aggregated = aggregated.dropna(subset=list(OHLC))
    aggregated["available_at"] = aggregated.index + pd.Timedelta(minutes=minutes)
    return normalize_bars(aggregated, timeframe)


def _named_session_dates(index: pd.DatetimeIndex) -> list[date]:
    local = index.tz_convert(NEW_YORK)
    result: list[date] = []
    for stamp in local:
        named = stamp.date()
        if stamp.hour >= 18:
            named += timedelta(days=1)
        result.append(named)
    return result


def _local_timestamp(day: date, clock: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day.isoformat()} {clock}", tz=ZoneInfo(NEW_YORK)).tz_convert(
        "UTC"
    )


def _daily_aggregate(one_minute: pd.DataFrame) -> pd.DataFrame:
    work = one_minute.copy()
    work["session_date"] = _named_session_dates(work.index)
    records: list[dict[str, object]] = []
    index: list[pd.Timestamp] = []
    for session_date, group in work.groupby("session_date", sort=True):
        start_day = session_date - timedelta(days=1)
        index.append(_local_timestamp(start_day, "18:00"))
        records.append(
            {
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "observed_minutes": int(len(group)),
                "available_at": _local_timestamp(session_date, "17:00"),
            }
        )
    result = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="timestamp_utc"))
    return normalize_bars(result, "1D")


def _weekly_aggregate(daily: pd.DataFrame) -> pd.DataFrame:
    work = daily.copy()
    available_local = pd.to_datetime(work["available_at"], utc=True).dt.tz_convert(
        NEW_YORK
    )
    session_dates = available_local.dt.date
    work["week_start"] = [
        value - timedelta(days=value.weekday()) for value in session_dates
    ]
    records: list[dict[str, object]] = []
    index: list[pd.Timestamp] = []
    for week_start, group in work.groupby("week_start", sort=True):
        index.append(_local_timestamp(week_start - timedelta(days=1), "18:00"))
        friday = week_start + timedelta(days=4)
        records.append(
            {
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "observed_minutes": int(group["observed_minutes"].sum()),
                "available_at": _local_timestamp(friday, "17:00"),
            }
        )
    result = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="timestamp_utc"))
    return normalize_bars(result, "1W")


def build_timeframes(one_minute: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build all D005 timeframes without modifying the source frame."""

    base = normalize_bars(one_minute, "1min")
    result = {"1min": base}
    for timeframe in ("5min", "15min", "1H", "4H"):
        result[timeframe] = _intraday_aggregate(base, timeframe)
    result["1D"] = _daily_aggregate(base)
    result["1W"] = _weekly_aggregate(result["1D"])
    return result

