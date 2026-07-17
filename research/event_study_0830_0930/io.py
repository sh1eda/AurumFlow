from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .config import StudyConfig


class DataRequirementError(ValueError):
    """Raised when an input cannot support the registered study design."""


PRICE_ALIASES = {
    "timestamp": ("timestamp", "datetime", "time", "date_time"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "spread": ("spread", "spread_price"),
}


def _find_column(columns: list[str], aliases: tuple[str, ...], required: bool = True) -> str | None:
    normalized = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    if required:
        raise DataRequirementError(f"Missing required column; expected one of {aliases}")
    return None


def _parse_timestamp(
    values: pd.Series,
    *,
    source_timezone: str | None,
    target_timezone: str,
    label: str,
) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any():
        bad = int(parsed.isna().sum())
        raise DataRequirementError(f"{label} contains {bad} unparseable timestamp(s)")
    index = pd.DatetimeIndex(parsed)
    if index.tz is None:
        if not source_timezone:
            raise DataRequirementError(
                f"{label} timestamps are timezone-naive; provide --source-timezone with an IANA zone"
            )
        try:
            ZoneInfo(source_timezone)
        except Exception as exc:  # pragma: no cover - platform zone database failure
            raise DataRequirementError(f"Unknown IANA timezone: {source_timezone}") from exc
        try:
            index = index.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
        except Exception as exc:
            raise DataRequirementError(
                f"{label} contains ambiguous/nonexistent local timestamps; supply unambiguous UTC data"
            ) from exc
    return index.tz_convert(target_timezone)


def _aggregate_to_one_minute(frame: pd.DataFrame) -> pd.DataFrame:
    aggregations: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "spread" in frame:
        aggregations["spread"] = "max"
    return frame.resample("1min", label="left", closed="left").agg(aggregations).dropna(subset=["open"])


def load_prices(
    path: str | Path,
    *,
    source_timezone: str | None = None,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Load one-minute-or-finer OHLC and convert it to America/New_York.

    Coarser bars fail closed because they cannot resolve the registered event
    windows or causal structures.  Sub-minute inputs are conservatively aggregated
    to one-minute OHLC.
    """

    cfg = config or StudyConfig()
    cfg.validate()
    raw = pd.read_csv(path)
    columns = list(raw.columns)
    selected: dict[str, pd.Series] = {}
    for canonical in ("open", "high", "low", "close"):
        source = _find_column(columns, PRICE_ALIASES[canonical])
        selected[canonical] = pd.to_numeric(raw[source], errors="coerce")
    spread_source = _find_column(columns, PRICE_ALIASES["spread"], required=False)
    if spread_source:
        selected["spread"] = pd.to_numeric(raw[spread_source], errors="coerce")
    timestamp_source = _find_column(columns, PRICE_ALIASES["timestamp"])
    frame = pd.DataFrame(selected)
    frame.index = _parse_timestamp(
        raw[timestamp_source],
        source_timezone=source_timezone,
        target_timezone=cfg.timezone,
        label="price input",
    )
    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise DataRequirementError("Price input contains non-numeric or missing OHLC values")
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        duplicates = int(frame.index.duplicated().sum())
        raise DataRequirementError(f"Price input contains {duplicates} duplicate timestamp(s)")
    if len(frame) < 2:
        raise DataRequirementError("Price input must contain at least two rows")

    deltas = frame.index.to_series().diff().dropna().dt.total_seconds()
    positive = deltas[deltas > 0]
    if positive.empty:
        raise DataRequirementError("Cannot infer a positive input interval")
    modal_seconds = float(positive.mode().iloc[0])
    if modal_seconds > cfg.required_bar_seconds:
        raise DataRequirementError(
            f"Input resolution is approximately {modal_seconds:g} seconds; the registered study requires "
            "one-minute or finer data. Do not upsample coarser OHLC."
        )
    if modal_seconds < cfg.required_bar_seconds:
        frame = _aggregate_to_one_minute(frame)

    invalid = (
        (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame["low"])
    )
    if invalid.any():
        raise DataRequirementError(f"OHLC invariants fail on {int(invalid.sum())} row(s)")
    if "spread" in frame and (frame["spread"] < 0).any():
        raise DataRequirementError("Spread values cannot be negative")

    frame.index.name = "timestamp_et"
    frame["session_date"] = frame.index.date
    return frame


def load_calendar(
    path: str | Path,
    *,
    source_timezone: str | None = "America/New_York",
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Load a point-in-time economic calendar using the documented schema."""

    cfg = config or StudyConfig()
    raw = pd.read_csv(path)
    normalized = {str(c).strip().lower(): c for c in raw.columns}
    required = ("release_timestamp", "event_name", "importance")
    missing = [c for c in required if c not in normalized]
    if missing:
        raise DataRequirementError(f"Calendar is missing required columns: {', '.join(missing)}")

    out = raw.rename(columns={source: str(source).strip().lower() for source in raw.columns}).copy()
    out.index = _parse_timestamp(
        out["release_timestamp"],
        source_timezone=source_timezone,
        target_timezone=cfg.timezone,
        label="calendar",
    )
    out.index.name = "release_timestamp_et"
    out["event_name"] = out["event_name"].astype(str).str.strip()
    out["importance"] = out["importance"].astype(str).str.strip().str.lower()
    allowed = {"major", "minor", "none"}
    unknown = sorted(set(out["importance"]) - allowed)
    if unknown:
        raise DataRequirementError(f"Unknown calendar importance value(s): {unknown}; use major/minor/none")
    for numeric in ("actual", "consensus", "previous", "revision", "surprise"):
        if numeric in out:
            out[numeric] = pd.to_numeric(out[numeric], errors="coerce")
    out["session_date"] = out.index.date
    out["clock"] = out.index.strftime("%H:%M")
    out["is_0830"] = out["clock"].eq("08:30")
    out["is_1000"] = out["clock"].eq("10:00")
    return out.sort_index()


def classify_event_days(price_dates: pd.Series | list, calendar: pd.DataFrame) -> pd.DataFrame:
    """Assign mutually exclusive A/B/C 08:30 classes plus the D 10:00 overlay."""

    dates = pd.Index(pd.unique(pd.Series(price_dates)), name="session_date")
    records: list[dict] = []
    for session_date in dates:
        events = calendar[calendar["session_date"].eq(session_date)]
        at_0830 = events[events["is_0830"]]
        at_1000 = events[events["is_1000"]]
        if at_0830["importance"].eq("major").any():
            event_class = "A_major_0830"
        elif at_0830["importance"].eq("minor").any():
            event_class = "B_minor_0830"
        else:
            event_class = "C_no_meaningful_0830"
        records.append(
            {
                "session_date": session_date,
                "event_class": event_class,
                "important_1000_release": bool(at_1000["importance"].eq("major").any()),
                "minor_1000_release": bool(at_1000["importance"].eq("minor").any()),
                "events_0830": " | ".join(at_0830["event_name"].tolist()),
                "events_1000": " | ".join(at_1000["event_name"].tolist()),
                "news_category_0830": " | ".join(
                    at_0830.get("category", pd.Series(dtype=str)).dropna().astype(str).tolist()
                ),
            }
        )
    return pd.DataFrame.from_records(records).set_index("session_date").sort_index()
