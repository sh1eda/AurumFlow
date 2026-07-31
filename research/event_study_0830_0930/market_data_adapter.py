"""Source-agnostic adapters for canonical XAUUSD bid/ask data."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pandas as pd


BAR_REQUIRED_COLUMNS = (
    "timestamp",
    "bid_open",
    "bid_high",
    "bid_low",
    "bid_close",
    "ask_open",
    "ask_high",
    "ask_low",
    "ask_close",
    "source",
    "symbol",
)
BAR_OPTIONAL_COLUMNS = (
    "tick_volume",
    "real_volume",
    "mid_open",
    "mid_high",
    "mid_low",
    "mid_close",
    "tick_count",
    "median_spread",
    "maximum_spread",
    "last_spread",
)
TICK_REQUIRED_COLUMNS = ("timestamp", "bid", "ask", "source", "symbol")
TICK_OPTIONAL_COLUMNS = ("bid_size", "ask_size")


class MarketDataError(ValueError):
    """Raised when market data cannot be mapped without inventing information."""


@dataclass(frozen=True)
class AdapterResult:
    frame: pd.DataFrame
    metadata: dict[str, Any]


def _normal_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _read_csv(path: Path) -> pd.DataFrame:
    attempts = (
        {"encoding": "utf-8-sig", "sep": None, "engine": "python"},
        {"encoding": "utf-16", "sep": "\t"},
        {"encoding": "utf-16", "sep": None, "engine": "python"},
    )
    errors: list[str] = []
    for options in attempts:
        try:
            frame = pd.read_csv(path, **options)
            if len(frame.columns) > 1:
                return frame
        except Exception as exc:  # pragma: no cover - only final error is relevant
            errors.append(str(exc))
    raise MarketDataError(f"Could not parse CSV {path.name}: {errors[-1] if errors else 'unknown error'}")


def _read_table(path: str | Path, *, input_format: str) -> pd.DataFrame:
    source_path = Path(path)
    if not source_path.exists():
        raise MarketDataError(f"Market-data input does not exist: {source_path}")
    if input_format == "parquet":
        try:
            return pd.read_parquet(source_path)
        except ImportError as exc:
            raise MarketDataError(
                "Parquet support requires the isolated empirical dependency listed in "
                "requirements-empirical.txt (pyarrow)."
            ) from exc
    return _read_csv(source_path)


def _parse_utc(values: pd.Series, *, source_timezone: str | None, label: str) -> pd.Series:
    try:
        parsed = pd.to_datetime(values, errors="coerce")
    except Exception as exc:
        raise MarketDataError(f"{label} timestamps could not be parsed") from exc
    if parsed.isna().any():
        raise MarketDataError(f"{label} contains {int(parsed.isna().sum())} invalid timestamp(s)")

    try:
        index = pd.DatetimeIndex(parsed)
    except Exception:
        try:
            index = pd.DatetimeIndex(pd.to_datetime(values, errors="raise", utc=True))
        except Exception as exc:
            raise MarketDataError(
                f"{label} contains incompatible mixed timestamp offsets; normalize them explicitly"
            ) from exc

    if index.tz is None:
        if not source_timezone:
            raise MarketDataError(
                f"{label} timestamps are timezone-naive; provide an IANA source timezone"
            )
        try:
            ZoneInfo(source_timezone)
            index = index.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
        except Exception as exc:
            raise MarketDataError(
                f"{label} contains an unknown zone or ambiguous/nonexistent DST timestamp"
            ) from exc
    return pd.Series(index.tz_convert("UTC"), index=values.index, name="timestamp")


def _resolve_columns(
    raw: pd.DataFrame,
    aliases: Mapping[str, tuple[str, ...]],
    explicit_mapping: Mapping[str, str] | None,
) -> dict[str, object]:
    normalized = {_normal_name(column): column for column in raw.columns}
    resolved: dict[str, object] = {}
    for canonical, candidates in aliases.items():
        requested = explicit_mapping.get(canonical) if explicit_mapping else None
        if requested is not None:
            key = _normal_name(requested)
            if key not in normalized:
                raise MarketDataError(
                    f"Configured source column {requested!r} for {canonical!r} was not found"
                )
            resolved[canonical] = normalized[key]
            continue
        for candidate in candidates:
            key = _normal_name(candidate)
            if key in normalized:
                resolved[canonical] = normalized[key]
                break
    return resolved


def _coerce_numeric(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    bad = frame[[column for column in columns if column in frame]].isna().any(axis=1)
    if bad.any():
        raise MarketDataError(f"Market data contains {int(bad.sum())} non-numeric required value row(s)")


def _constant_text(
    raw: pd.DataFrame,
    resolved: Mapping[str, object],
    canonical: str,
    supplied: str | None,
) -> pd.Series:
    if canonical in resolved:
        values = raw[resolved[canonical]].fillna("").astype(str).str.strip()
        if supplied is not None:
            nonempty = values[values.ne("")]
            if not nonempty.empty and not nonempty.eq(supplied).all():
                raise MarketDataError(
                    f"Supplied {canonical}={supplied!r} conflicts with values in the input"
                )
            return pd.Series(supplied, index=raw.index)
        return values
    if not supplied:
        raise MarketDataError(f"Input has no {canonical!r} column; provide --{canonical}")
    return pd.Series(supplied, index=raw.index)


def _positive_interval_seconds(timestamps: pd.Series) -> float | None:
    deltas = timestamps.diff().dt.total_seconds()
    positive = deltas[deltas.gt(0)]
    if positive.empty:
        return None
    modes = positive.mode()
    return float(modes.iloc[0] if not modes.empty else positive.median())


GENERIC_BAR_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "datetime", "date_time", "time", "utc"),
    "bid_open": ("bid_open", "bidopen", "open_bid"),
    "bid_high": ("bid_high", "bidhigh", "high_bid"),
    "bid_low": ("bid_low", "bidlow", "low_bid"),
    "bid_close": ("bid_close", "bidclose", "close_bid"),
    "ask_open": ("ask_open", "askopen", "open_ask"),
    "ask_high": ("ask_high", "askhigh", "high_ask"),
    "ask_low": ("ask_low", "asklow", "low_ask"),
    "ask_close": ("ask_close", "askclose", "close_ask"),
    "tick_volume": ("tick_volume", "tickvol", "ticks", "volume_ticks"),
    "real_volume": ("real_volume", "realvol", "volume_real"),
    "source": ("source", "vendor", "broker", "feed"),
    "symbol": ("symbol", "instrument", "ticker"),
}
GENERIC_TICK_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "datetime", "date_time", "time", "utc"),
    "bid": ("bid", "bid_price", "bidprice"),
    "ask": ("ask", "ask_price", "askprice"),
    "bid_size": ("bid_size", "bidsize", "bid_volume", "bidvolume"),
    "ask_size": ("ask_size", "asksize", "ask_volume", "askvolume"),
    "source": ("source", "vendor", "broker", "feed"),
    "symbol": ("symbol", "instrument", "ticker"),
}


class MarketDataAdapter(ABC):
    """Adapter interface returning canonical, UTC market observations."""

    @abstractmethod
    def load(self, path: str | Path) -> AdapterResult:
        raise NotImplementedError


class GenericMarketDataAdapter(MarketDataAdapter):
    def __init__(
        self,
        *,
        mode: str,
        input_format: str = "generic-csv",
        source_timezone: str | None = None,
        source: str | None = None,
        symbol: str | None = None,
        column_mapping: Mapping[str, str] | None = None,
        aliases: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        if mode not in {"bars", "ticks"}:
            raise MarketDataError("Market mode must be 'bars' or 'ticks'")
        self.mode = mode
        self.input_format = input_format
        self.source_timezone = source_timezone
        self.source = source
        self.symbol = symbol
        self.column_mapping = dict(column_mapping or {})
        self.aliases = dict(
            aliases or (GENERIC_BAR_ALIASES if mode == "bars" else GENERIC_TICK_ALIASES)
        )

    def _prepare_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        return raw

    def load(self, path: str | Path) -> AdapterResult:
        raw = self._prepare_raw(_read_table(path, input_format=self.input_format))
        resolved = _resolve_columns(raw, self.aliases, self.column_mapping)
        required = BAR_REQUIRED_COLUMNS if self.mode == "bars" else TICK_REQUIRED_COLUMNS
        missing = [column for column in required if column not in resolved and column not in {"source", "symbol"}]
        if missing:
            single_price = {"open", "high", "low", "close"}.issubset(
                {_normal_name(column) for column in raw.columns}
            )
            detail = (
                " A single-price OHLC export is not a bid/ask dataset and will not be expanded."
                if self.mode == "bars" and single_price
                else ""
            )
            raise MarketDataError(f"Missing canonical {self.mode} columns: {missing}.{detail}")

        output = pd.DataFrame(index=raw.index)
        output["timestamp"] = _parse_utc(
            raw[resolved["timestamp"]],
            source_timezone=self.source_timezone,
            label="market input",
        )
        numeric_required = (
            list(BAR_REQUIRED_COLUMNS[1:9]) if self.mode == "bars" else ["bid", "ask"]
        )
        numeric_optional = (
            ["tick_volume", "real_volume"] if self.mode == "bars" else ["bid_size", "ask_size"]
        )
        for column in numeric_required + numeric_optional:
            if column in resolved:
                output[column] = raw[resolved[column]]
        _coerce_numeric(output, numeric_required)
        for column in numeric_optional:
            if column in output:
                output[column] = pd.to_numeric(output[column], errors="coerce")

        output["source"] = _constant_text(raw, resolved, "source", self.source)
        output["symbol"] = _constant_text(raw, resolved, "symbol", self.symbol)

        interval = _positive_interval_seconds(output["timestamp"])
        if self.mode == "bars" and interval is not None and interval != 60:
            raise MarketDataError(
                f"Input resolution is approximately {interval:g} seconds; Mode A requires "
                "one-minute bid/ask bars. Coarser data, including M15, is never upsampled; "
                "sub-minute observations must use Mode B tick aggregation."
            )

        if self.mode == "bars":
            for field in ("open", "high", "low", "close"):
                output[f"mid_{field}"] = (
                    output[f"bid_{field}"] + output[f"ask_{field}"]
                ) / 2.0
            output["last_spread"] = output["ask_close"] - output["bid_close"]

        ordered = list(required) + [
            column
            for column in (BAR_OPTIONAL_COLUMNS if self.mode == "bars" else TICK_OPTIONAL_COLUMNS)
            if column in output and column not in required
        ]
        output = output[ordered]
        metadata = {
            "adapter": type(self).__name__,
            "input_format": self.input_format,
            "mode": self.mode,
            "input_path_name": Path(path).name,
            "row_count": int(len(output)),
            "source_timezone": self.source_timezone,
            "internal_timezone": "UTC",
            "input_monotonic": bool(output["timestamp"].is_monotonic_increasing),
            "duplicate_timestamp_count": int(output["timestamp"].duplicated().sum()),
            "inferred_interval_seconds": interval,
            "column_mapping": {key: str(value) for key, value in resolved.items()},
        }
        return AdapterResult(output, metadata)


class MT5MarketDataAdapter(GenericMarketDataAdapter):
    """MetaTrader 5 tick or explicit bid/ask-bar export adapter."""

    def __init__(self, **kwargs: Any) -> None:
        mode = kwargs.get("mode")
        aliases = dict(GENERIC_BAR_ALIASES if mode == "bars" else GENERIC_TICK_ALIASES)
        if mode == "ticks":
            aliases.update(
                {
                    "timestamp": ("timestamp", "date_time", "datetime"),
                    "bid": ("bid",),
                    "ask": ("ask",),
                }
            )
        super().__init__(input_format="generic-csv", aliases=aliases, **kwargs)

    def _prepare_raw(self, raw: pd.DataFrame) -> pd.DataFrame:
        normalized = {_normal_name(column): column for column in raw.columns}
        if not any(key in normalized for key in ("timestamp", "datetime", "date_time")):
            date_column = normalized.get("date")
            time_column = normalized.get("time")
            if date_column is not None and time_column is not None:
                raw = raw.copy()
                raw["timestamp"] = (
                    raw[date_column].astype(str).str.strip()
                    + " "
                    + raw[time_column].astype(str).str.strip()
                )
        return raw


class DukascopyMarketDataAdapter(GenericMarketDataAdapter):
    """Dukascopy tick/CSV adapter with common exported column aliases."""

    def __init__(self, **kwargs: Any) -> None:
        mode = kwargs.get("mode")
        aliases = dict(GENERIC_BAR_ALIASES if mode == "bars" else GENERIC_TICK_ALIASES)
        if mode == "ticks":
            aliases.update(
                {
                    "timestamp": ("timestamp", "utc", "gmt_time", "local_time"),
                    "bid": ("bid", "bidprice", "bid_price"),
                    "ask": ("ask", "askprice", "ask_price"),
                    "bid_size": ("bidvolume", "bid_volume", "bidsize"),
                    "ask_size": ("askvolume", "ask_volume", "asksize"),
                }
            )
        super().__init__(input_format="generic-csv", aliases=aliases, **kwargs)


class BrokerCSVMarketDataAdapter(GenericMarketDataAdapter):
    """Broker-specific CSV adapter driven by an explicit canonical-to-source map."""


class ParquetMarketDataAdapter(GenericMarketDataAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(input_format="parquet", **kwargs)


def get_market_adapter(
    adapter_name: str,
    *,
    mode: str,
    source_timezone: str | None,
    source: str | None,
    symbol: str | None,
    column_mapping: Mapping[str, str] | None = None,
) -> MarketDataAdapter:
    kwargs = {
        "mode": mode,
        "source_timezone": source_timezone,
        "source": source,
        "symbol": symbol,
        "column_mapping": column_mapping,
    }
    adapters: dict[str, type[GenericMarketDataAdapter]] = {
        "generic-csv": GenericMarketDataAdapter,
        "broker-csv": BrokerCSVMarketDataAdapter,
        "mt5": MT5MarketDataAdapter,
        "dukascopy": DukascopyMarketDataAdapter,
        "parquet": ParquetMarketDataAdapter,
    }
    try:
        return adapters[adapter_name](**kwargs)
    except KeyError as exc:
        raise MarketDataError(f"Unknown market adapter: {adapter_name}") from exc


def tick_to_minute_bars(ticks: pd.DataFrame) -> AdapterResult:
    """Aggregate bid and ask independently; no midpoint fill or forward fill occurs."""

    missing = [column for column in TICK_REQUIRED_COLUMNS if column not in ticks]
    if missing:
        raise MarketDataError(f"Canonical tick data is missing columns: {missing}")
    if ticks.empty:
        raise MarketDataError("Cannot aggregate an empty tick dataset")
    if not ticks["timestamp"].is_monotonic_increasing:
        raise MarketDataError("Tick timestamps are not monotonic; validate source ordering first")
    if ticks["source"].nunique(dropna=False) != 1 or ticks["symbol"].nunique(dropna=False) != 1:
        raise MarketDataError("Tick aggregation requires one source and one symbol")
    invalid_quote = ticks["bid"].le(0) | ticks["ask"].le(0) | ticks["ask"].le(ticks["bid"])
    if invalid_quote.any():
        raise MarketDataError(
            f"Tick aggregation refused {int(invalid_quote.sum())} non-positive or crossed quote(s)"
        )
    for size_column in ("bid_size", "ask_size"):
        if size_column in ticks and ticks[size_column].dropna().lt(0).any():
            raise MarketDataError(f"Tick aggregation refused negative {size_column} values")

    work = ticks.copy()
    work["mid"] = (work["bid"] + work["ask"]) / 2.0
    work["spread"] = work["ask"] - work["bid"]
    work = work.set_index("timestamp", drop=False)
    grouper = pd.Grouper(freq="1min", label="left", closed="left")
    grouped = work.groupby(grouper, sort=True)
    bars = grouped.agg(
        bid_open=("bid", "first"),
        bid_high=("bid", "max"),
        bid_low=("bid", "min"),
        bid_close=("bid", "last"),
        ask_open=("ask", "first"),
        ask_high=("ask", "max"),
        ask_low=("ask", "min"),
        ask_close=("ask", "last"),
        mid_open=("mid", "first"),
        mid_high=("mid", "max"),
        mid_low=("mid", "min"),
        mid_close=("mid", "last"),
        tick_count=("bid", "size"),
        median_spread=("spread", "median"),
        maximum_spread=("spread", "max"),
        last_spread=("spread", "last"),
    )
    bars = bars.dropna(subset=["bid_open", "ask_open"]).reset_index()
    bars["source"] = str(ticks["source"].iloc[0])
    bars["symbol"] = str(ticks["symbol"].iloc[0])
    ordered = list(BAR_REQUIRED_COLUMNS) + [
        column for column in BAR_OPTIONAL_COLUMNS if column in bars
    ]
    bars = bars[ordered]
    metadata = {
        "aggregation": "independent_bid_ask_tick_to_one_minute",
        "minute_label": "left",
        "minute_closed": "left",
        "forward_fill": False,
        "midpoint_role": "analytical_only",
        "tick_rows": int(len(ticks)),
        "duplicate_tick_timestamp_count": int(ticks["timestamp"].duplicated().sum()),
        "minute_rows": int(len(bars)),
        "spread_statistics": ["median", "maximum", "last"],
        "internal_timezone": "UTC",
    }
    bars.attrs["aggregation_metadata"] = metadata
    return AdapterResult(bars, metadata)


def read_mapping_json(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    mapping = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
    ):
        raise MarketDataError("Column mapping JSON must be an object of canonical: source names")
    return mapping


def write_canonical_market(frame: pd.DataFrame, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        try:
            frame.to_parquet(output, index=False)
        except ImportError as exc:
            raise MarketDataError(
                "Writing Parquet requires pyarrow from requirements-empirical.txt"
            ) from exc
    else:
        frame.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z")
