"""Canonical point-in-time economic-calendar adapters and surprise features."""

from __future__ import annotations

import hashlib
import json
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .market_data_adapter import MarketDataError, _normal_name, _parse_utc, _read_table


CANONICAL_RELEASE_COLUMNS = (
    "event_id",
    "release_timestamp_utc",
    "release_timestamp_new_york",
    "event_name",
    "institution",
    "country",
    "category",
    "importance",
    "actual",
    "consensus",
    "previous",
    "revised_previous",
    "unit",
    "release_version",
    "source",
    "source_url",
    "retrieval_timestamp",
    "point_in_time_verified",
    "notes",
)

# These fields belong to the official-source research schema.  They are kept
# alongside the original empirical adapter contract so an import/export cycle
# cannot silently discard provenance, schedule-change, or vintage information.
OFFICIAL_SOURCE_COLUMNS = (
    "release_timestamp_local",
    "timezone",
    "currency",
    "agency",
    "event_name_raw",
    "event_name_canonical",
    "event_category",
    "event_subcategory",
    "release_type",
    "scheduled_or_unscheduled",
    "source_type",
    "retrieved_at_utc",
    "actual_unit",
    "consensus_source",
    "previous_as_published",
    "revision_value",
    "revision_direction",
    "reference_period",
    "release_vintage",
    "value_status",
    "consensus_status",
    "latest_revised_value",
    "original_scheduled_timestamp_local",
    "original_scheduled_timestamp_utc",
    "schedule_change_status",
    "schedule_change_reason",
    "schedule_source_url",
    "timing_verified",
    "calendar_reliability_grade",
    "release_bundle_key",
)


class EconomicCalendarError(ValueError):
    """Raised when release data cannot satisfy the canonical integrity contract."""


@dataclass(frozen=True)
class CalendarAdapterResult:
    frame: pd.DataFrame
    metadata: dict[str, Any]


CALENDAR_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("event_id", "id", "eventid"),
    "release_timestamp_utc": (
        "release_timestamp_utc",
        "release_timestamp",
        "timestamp",
        "datetime",
        "date_time",
        "time",
    ),
    "release_timestamp_new_york": (
        "release_timestamp_new_york",
        "timestamp_new_york",
        "new_york_time",
    ),
    "event_name": ("event_name", "event", "name", "indicator", "title"),
    "institution": ("institution", "agency", "publisher"),
    "country": ("country", "currency", "region"),
    "category": ("category", "event_category", "group"),
    "importance": ("importance", "impact", "priority"),
    "actual": ("actual", "actual_value"),
    "consensus": ("consensus", "forecast", "expected"),
    "previous": ("previous", "prior"),
    "revised_previous": ("revised_previous", "revision", "revised", "prior_revised"),
    "unit": ("unit", "units"),
    "release_version": ("release_version", "version", "vintage"),
    "source": ("source", "vendor", "provider"),
    "source_url": ("source_url", "url", "release_url"),
    "retrieval_timestamp": (
        "retrieval_timestamp",
        "retrieved_at",
        "vintage_retrieved_at",
    ),
    "point_in_time_verified": (
        "point_in_time_verified",
        "point_in_time",
        "pit_verified",
    ),
    "notes": ("notes", "note", "comments"),
}


EVENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcore\s+(consumer price|cpi)\b", "Core CPI"),
    (r"\b(consumer price index|cpi)\b", "CPI"),
    (r"\b(nonfarm payrolls?|non-farm payrolls?|employment situation)\b", "Nonfarm Payrolls"),
    (r"\bunemployment rate\b", "Unemployment Rate"),
    (r"\baverage hourly earnings?\b", "Average Hourly Earnings"),
    (r"\bcore\s+(producer price|ppi)\b", "Core PPI"),
    (r"\b(producer price index|ppi)\b", "PPI"),
    (r"\bcore\s+retail sales\b|\bretail sales.*ex", "Core Retail Sales"),
    (r"\bretail sales\b", "Retail Sales"),
    (r"\b(gross domestic product|gdp)\b", "GDP"),
    (r"\b(initial jobless claims?|initial unemployment claims?)\b", "Initial Jobless Claims"),
    (r"\bcontinuing claims?\b", "Continuing Claims"),
    (r"\bcore\s+durable goods\b|\bdurable goods.*ex", "Core Durable Goods"),
    (r"\bdurable goods\b", "Durable Goods"),
    (r"\bpersonal income\b", "Personal Income"),
    (r"\bcore\s+(pce|personal consumption expenditures?)\b", "Core PCE"),
    (r"\b(pce|personal consumption expenditures?)\b", "PCE"),
    (r"\bpersonal spending\b", "Personal Spending"),
    (r"\bism\b.*\bmanufacturing\b|\bmanufacturing pmi\b", "ISM Manufacturing"),
    (r"\bism\b.*\b(services|non-manufacturing)\b|\bservices pmi\b", "ISM Services"),
    (r"\bconsumer confidence\b", "Consumer Confidence"),
    (r"\b(jolts|job openings)\b", "JOLTS"),
    (r"\b(university of michigan|u\.?\s*of\s*michigan|michigan sentiment)\b", "University of Michigan"),
    (
        r"\b(fomc|federal reserve|fed funds|monetary policy|summary of economic projections)\b",
        "Federal Reserve",
    ),
    (r"\bindustrial production\b", "Industrial Production"),
    (r"\bcapacity utilization\b", "Capacity Utilization"),
    (r"\bhousing starts?\b", "Housing Starts"),
    (r"\bbuilding permits?\b", "Building Permits"),
    (r"\b(import prices?|import price index)\b", "Import Prices"),
    (r"\b(export prices?|export price index)\b", "Export Prices"),
    (r"\bemployment cost index\b", "Employment Cost Index"),
    (r"\bproductivity\b", "Productivity"),
    (r"\bunit labor costs?\b", "Unit Labor Costs"),
    (r"\bphiladelphia fed\b", "Philadelphia Fed"),
    (r"\bempire state\b", "Empire State Manufacturing"),
    (r"\bnew home sales\b", "New Home Sales"),
    (r"\bexisting home sales\b", "Existing Home Sales"),
    (r"\bfactory orders\b", "Factory Orders"),
    (r"\bconstruction spending\b", "Construction Spending"),
    (r"\bbusiness inventories\b", "Business Inventories"),
    (r"\bwholesale inventories\b", "Wholesale Inventories"),
    (r"\btrade balance\b|\bgoods trade balance\b", "Trade Balance"),
)


def classify_event_name(event_name: str) -> str:
    normalized = re.sub(r"\s+", " ", event_name.strip().lower())
    for pattern, canonical in EVENT_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return canonical
    return "Other"


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "verified"}:
        return True
    if normalized in {"false", "0", "no", "n", "unverified", ""}:
        return False
    raise EconomicCalendarError(f"Unrecognized point-in-time flag: {value!r}")


def _parse_number(value: object) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"na", "n/a", "none", "null", "-"}:
        return math.nan
    multiplier = 1.0
    match = re.fullmatch(r"([+-]?[0-9]*\.?[0-9]+)\s*([kmb%]?)", text, flags=re.IGNORECASE)
    if not match:
        return math.nan
    number, suffix = match.groups()
    if suffix.lower() == "k":
        multiplier = 1_000.0
    elif suffix.lower() == "m":
        multiplier = 1_000_000.0
    elif suffix.lower() == "b":
        multiplier = 1_000_000_000.0
    return float(number) * multiplier


def _resolve(raw: pd.DataFrame, mapping: Mapping[str, str] | None) -> dict[str, object]:
    normalized = {_normal_name(column): column for column in raw.columns}
    result: dict[str, object] = {}
    for canonical, aliases in CALENDAR_ALIASES.items():
        requested = mapping.get(canonical) if mapping else None
        candidates = (requested,) if requested else aliases
        for candidate in candidates:
            if candidate is None:
                continue
            key = _normal_name(candidate)
            if key in normalized:
                result[canonical] = normalized[key]
                break
        if requested and canonical not in result:
            raise EconomicCalendarError(
                f"Configured calendar column {requested!r} for {canonical!r} was not found"
            )
    return result


def _text_column(
    raw: pd.DataFrame,
    resolved: Mapping[str, object],
    name: str,
    default: str,
) -> pd.Series:
    if name not in resolved:
        return pd.Series(default, index=raw.index, dtype="object")
    return raw[resolved[name]].fillna(default).astype(str).str.strip()


def _optional_utc(
    values: pd.Series,
    *,
    source_timezone: str | None,
    label: str,
) -> pd.Series:
    present = values.notna() & values.astype(str).str.strip().ne("")
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns, UTC]")
    if present.any():
        result.loc[present] = _parse_utc(
            values.loc[present], source_timezone=source_timezone, label=label
        )
    return result


def _event_id(row: pd.Series) -> str:
    existing = str(row.get("event_id", "")).strip()
    if existing:
        return existing
    payload = "|".join(
        [
            str(row["source"]),
            pd.Timestamp(row["release_timestamp_utc"]).isoformat(),
            str(row["event_name"]),
            str(row["release_version"]),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


class EconomicCalendarAdapter(ABC):
    @abstractmethod
    def load(self, path: str | Path) -> CalendarAdapterResult:
        raise NotImplementedError


class GenericEconomicCalendarAdapter(EconomicCalendarAdapter):
    def __init__(
        self,
        *,
        input_format: str = "generic-csv",
        source_timezone: str | None = None,
        source: str | None = None,
        column_mapping: Mapping[str, str] | None = None,
    ) -> None:
        self.input_format = input_format
        self.source_timezone = source_timezone
        self.source = source
        self.column_mapping = dict(column_mapping or {})

    def load(self, path: str | Path) -> CalendarAdapterResult:
        try:
            raw = _read_table(path, input_format=self.input_format)
        except MarketDataError as exc:
            raise EconomicCalendarError(str(exc)) from exc
        resolved = _resolve(raw, self.column_mapping)
        if "event_name" not in resolved:
            raise EconomicCalendarError("Calendar input requires an event-name column")
        timestamp_field = (
            "release_timestamp_utc"
            if "release_timestamp_utc" in resolved
            else "release_timestamp_new_york"
        )
        if timestamp_field not in resolved:
            raise EconomicCalendarError("Calendar input requires a release timestamp")
        timezone = self.source_timezone
        if timestamp_field == "release_timestamp_new_york" and timezone is None:
            timezone = "America/New_York"
        timestamp = _parse_utc(
            raw[resolved[timestamp_field]],
            source_timezone=timezone,
            label="economic calendar",
        )

        out = pd.DataFrame(index=raw.index)
        out["release_timestamp_utc"] = timestamp
        out["release_timestamp_new_york"] = timestamp.dt.tz_convert("America/New_York")
        for field, default in (
            ("event_name", ""),
            ("institution", ""),
            ("country", "US"),
            ("category", ""),
            ("importance", "none"),
            ("unit", ""),
            ("release_version", "original"),
            ("source_url", ""),
            ("notes", ""),
        ):
            out[field] = _text_column(raw, resolved, field, default)
        out["source"] = _text_column(raw, resolved, "source", self.source or "")
        if self.source:
            present = out["source"].replace("", self.source)
            conflict = present.ne(self.source)
            if conflict.any():
                raise EconomicCalendarError("Supplied calendar source conflicts with input values")
            out["source"] = self.source
        if out["source"].eq("").any():
            raise EconomicCalendarError("Calendar source must be supplied or present in the input")

        out["importance"] = out["importance"].str.lower().replace(
            {"high": "major", "medium": "minor", "low": "none"}
        )
        invalid_importance = sorted(set(out["importance"]) - {"major", "minor", "none"})
        if invalid_importance:
            raise EconomicCalendarError(f"Unknown importance values: {invalid_importance}")
        for field in ("actual", "consensus", "previous", "revised_previous"):
            if field in resolved:
                out[field] = raw[resolved[field]].map(_parse_number)
            else:
                out[field] = math.nan
        if "point_in_time_verified" in resolved:
            out["point_in_time_verified"] = raw[resolved["point_in_time_verified"]].map(
                _parse_bool
            )
        else:
            out["point_in_time_verified"] = False
        if "retrieval_timestamp" in resolved:
            out["retrieval_timestamp"] = _optional_utc(
                raw[resolved["retrieval_timestamp"]],
                source_timezone=self.source_timezone or "UTC",
                label="calendar retrieval",
            )
        else:
            out["retrieval_timestamp"] = pd.NaT
        out["event_id"] = _text_column(raw, resolved, "event_id", "")
        out["event_type"] = out["event_name"].map(classify_event_name)
        blank_category = out["category"].eq("")
        out.loc[blank_category, "category"] = out.loc[blank_category, "event_type"]
        out["event_id"] = out.apply(_event_id, axis=1)
        if out["event_id"].duplicated().any():
            raise EconomicCalendarError("Calendar contains duplicate event_id values")

        # Preserve the richer official-source schema when present.  Required
        # aliases are derived from the normalized core fields if the input is a
        # legacy calendar, keeping old fixtures and downstream readers working.
        raw_normalized = {_normal_name(column): column for column in raw.columns}
        for field in OFFICIAL_SOURCE_COLUMNS:
            raw_column = raw_normalized.get(_normal_name(field))
            if raw_column is not None:
                out[field] = raw[raw_column]
            else:
                out[field] = ""
        out["release_timestamp_local"] = out["release_timestamp_new_york"]
        out["timezone"] = out["timezone"].replace("", "America/New_York")
        out["currency"] = out["currency"].replace("", "USD")
        out["agency"] = out["agency"].where(out["agency"].ne(""), out["institution"])
        out["event_name_raw"] = out["event_name_raw"].where(
            out["event_name_raw"].ne(""), out["event_name"]
        )
        out["event_name_canonical"] = out["event_name_canonical"].where(
            out["event_name_canonical"].ne(""), out["event_name"]
        )
        out["event_category"] = out["event_category"].where(
            out["event_category"].ne(""), out["category"]
        )
        out["release_type"] = out["release_type"].where(
            out["release_type"].ne(""), out["release_version"]
        )
        out["scheduled_or_unscheduled"] = out["scheduled_or_unscheduled"].replace(
            "", "scheduled"
        )
        out["retrieved_at_utc"] = out["retrieved_at_utc"].where(
            out["retrieved_at_utc"].astype(str).str.strip().ne(""),
            out["retrieval_timestamp"],
        )
        out["actual_unit"] = out["actual_unit"].where(
            out["actual_unit"].ne(""), out["unit"]
        )
        out["previous_as_published"] = out["previous_as_published"].where(
            out["previous_as_published"].astype(str).str.strip().ne(""), out["previous"]
        )
        out["release_vintage"] = out["release_vintage"].where(
            out["release_vintage"].ne(""), out["release_version"]
        )
        out["timing_verified"] = out["timing_verified"].replace("", False)

        ordered = list(CANONICAL_RELEASE_COLUMNS) + ["event_type"] + list(
            OFFICIAL_SOURCE_COLUMNS
        )
        out = out[ordered]
        metadata = {
            "adapter": type(self).__name__,
            "input_format": self.input_format,
            "input_path_name": Path(path).name,
            "row_count": int(len(out)),
            "internal_timezone": "UTC",
            "analysis_timezone": "America/New_York",
            "point_in_time_verified_count": int(out["point_in_time_verified"].sum()),
            "timing_only_count": int((~out["point_in_time_verified"]).sum()),
            "unclassified_event_count": int(out["event_type"].eq("Other").sum()),
            "column_mapping": {key: str(value) for key, value in resolved.items()},
        }
        return CalendarAdapterResult(out.sort_values("release_timestamp_utc"), metadata)


class MT5EconomicCalendarAdapter(GenericEconomicCalendarAdapter):
    """Adapter for common MT5 economic-calendar export labels."""


class BrokerEconomicCalendarAdapter(GenericEconomicCalendarAdapter):
    """Explicitly mapped broker/vendor calendar CSV adapter."""


class ParquetEconomicCalendarAdapter(GenericEconomicCalendarAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(input_format="parquet", **kwargs)


def get_calendar_adapter(
    adapter_name: str,
    *,
    source_timezone: str | None,
    source: str | None,
    column_mapping: Mapping[str, str] | None = None,
) -> EconomicCalendarAdapter:
    kwargs = {
        "source_timezone": source_timezone,
        "source": source,
        "column_mapping": column_mapping,
    }
    adapters: dict[str, type[GenericEconomicCalendarAdapter]] = {
        "generic-csv": GenericEconomicCalendarAdapter,
        "broker-csv": BrokerEconomicCalendarAdapter,
        "mt5": MT5EconomicCalendarAdapter,
        "parquet": ParquetEconomicCalendarAdapter,
    }
    try:
        return adapters[adapter_name](**kwargs)
    except KeyError as exc:
        raise EconomicCalendarError(f"Unknown calendar adapter: {adapter_name}") from exc


def add_surprise_features(events: pd.DataFrame, *, minimum_history: int = 5) -> pd.DataFrame:
    """Calculate surprise features only where point-in-time integrity is verified."""

    out = events.sort_values("release_timestamp_utc").copy()
    valid = (
        out["point_in_time_verified"].astype(bool)
        & out["actual"].notna()
        & out["consensus"].notna()
    )
    out["raw_surprise"] = math.nan
    out.loc[valid, "raw_surprise"] = out.loc[valid, "actual"] - out.loc[valid, "consensus"]
    meaningful_percentage = valid & out["consensus"].ne(0)
    out["percentage_surprise"] = math.nan
    out.loc[meaningful_percentage, "percentage_surprise"] = (
        out.loc[meaningful_percentage, "raw_surprise"]
        / out.loc[meaningful_percentage, "consensus"].abs()
    )
    out["surprise_sign"] = "unavailable"
    out.loc[valid & out["raw_surprise"].gt(0), "surprise_sign"] = "positive"
    out.loc[valid & out["raw_surprise"].lt(0), "surprise_sign"] = "negative"
    out.loc[valid & out["raw_surprise"].eq(0), "surprise_sign"] = "zero"
    out["revision_surprise"] = math.nan
    revision_valid = (
        out["point_in_time_verified"].astype(bool)
        & out["previous"].notna()
        & out["revised_previous"].notna()
    )
    out.loc[revision_valid, "revision_surprise"] = (
        out.loc[revision_valid, "revised_previous"] - out.loc[revision_valid, "previous"]
    )
    out["standardized_surprise"] = math.nan
    out["surprise_standardization_group"] = (
        out["event_type"].astype(str) + "|" + out["unit"].fillna("").astype(str)
    )
    for _, indexes in out.groupby("surprise_standardization_group", sort=False).groups.items():
        raw = out.loc[indexes, "raw_surprise"]
        prior_mean = raw.expanding(min_periods=minimum_history).mean().shift(1)
        prior_std = raw.expanding(min_periods=minimum_history).std(ddof=1).shift(1)
        usable = raw.notna() & prior_std.gt(0)
        out.loc[raw.index[usable], "standardized_surprise"] = (
            raw[usable] - prior_mean[usable]
        ) / prior_std[usable]
    out["surprise_eligible"] = valid
    out["surprise_exclusion_reason"] = ""
    out.loc[~out["point_in_time_verified"].astype(bool), "surprise_exclusion_reason"] = (
        "point_in_time_not_verified"
    )
    out.loc[
        out["point_in_time_verified"].astype(bool)
        & (out["actual"].isna() | out["consensus"].isna()),
        "surprise_exclusion_reason",
    ] = "actual_or_consensus_missing"
    return out


CHANNEL_COLUMNS = (
    "usd_implication",
    "nominal_yield_implication",
    "real_yield_implication",
    "risk_sentiment_implication",
    "expected_gold_direction",
)


def apply_directional_mapping(
    events: pd.DataFrame,
    mapping: Mapping[str, Mapping[str, Mapping[str, float]]] | None,
) -> pd.DataFrame:
    """Apply an explicit channel map; the default is intentionally unmapped."""

    out = events.copy()
    for column in CHANNEL_COLUMNS:
        out[column] = math.nan
    out["direction_mapping_status"] = "unmapped"
    if not mapping:
        return out
    for index, row in out.iterrows():
        sign = row.get("surprise_sign")
        rule = mapping.get(str(row.get("event_type", "")), {}).get(str(sign), {})
        if not rule:
            continue
        for column in CHANNEL_COLUMNS:
            if column in rule:
                out.at[index, column] = float(rule[column])
        out.at[index, "direction_mapping_status"] = "configured"
    return out


def read_direction_mapping_json(
    path: str | Path | None,
) -> dict[str, dict[str, dict[str, float]]]:
    if path is None:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EconomicCalendarError("Directional mapping JSON must contain an object")
    return value


def write_canonical_calendar(frame: pd.DataFrame, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        try:
            frame.to_parquet(output, index=False)
        except ImportError as exc:
            raise EconomicCalendarError(
                "Writing Parquet requires pyarrow from requirements-empirical.txt"
            ) from exc
    else:
        frame.to_csv(output, index=False, date_format="%Y-%m-%dT%H:%M:%S.%f%z")
