"""Shared primitives for the Dukascopy historical tick-data pipeline.

The source archive is partitioned by UTC hour.  Each accepted object is retained
verbatim; decompression is used only to validate or decode it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import lzma
import math
import os
from pathlib import Path
import struct
import tempfile
import tomllib
from typing import Any, Iterable, Iterator, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC = timezone.utc
CODE_VERSION = "D001-2"
MANIFEST_SCHEMA_VERSION = 1
TICK_STRUCT = struct.Struct(">IIIff")


class DukascopyError(RuntimeError):
    """Base class for data-pipeline failures."""


class ConfigurationError(DukascopyError):
    """The versioned data-source configuration is invalid."""


class DuplicateManifestKeyError(ConfigurationError):
    """A JSON manifest contains a duplicate key and is therefore ambiguous."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"duplicate JSON key in manifest: {key!r}")


class PayloadValidationError(DukascopyError):
    """A downloaded archive object cannot be accepted as a tick partition."""


class EmptyPayloadError(PayloadValidationError):
    """The source returned no compressed ticks."""


class MalformedPayloadError(PayloadValidationError):
    """The compressed object or decoded record stream is malformed."""


class PlaceholderPayloadError(PayloadValidationError):
    """The response resembles an HTML/text placeholder rather than BI5 data."""


@dataclass(frozen=True, order=True)
class Partition:
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("partition timestamp must be timezone-aware")
        normalized = self.timestamp.astimezone(UTC)
        if normalized.minute or normalized.second or normalized.microsecond:
            raise ValueError("partition timestamp must be aligned to a UTC hour")
        object.__setattr__(self, "timestamp", normalized)

    @property
    def key(self) -> str:
        return self.timestamp.strftime("%Y-%m-%dT%H:00:00Z")


@dataclass(frozen=True)
class SymbolConfig:
    archive_symbol: str
    price_scale: int


@dataclass(frozen=True)
class HolidayClosureInterval:
    rule_id: str
    rule_type: str
    event: str
    start_inclusive: datetime
    end_exclusive: datetime
    confidence: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class RecurringHolidayClosureRule:
    rule_id: str
    rule_type: str
    event: str
    timezone_name: str
    local_weekdays: tuple[int, ...]
    local_start_minutes: int
    local_end_minutes: int
    confidence: str
    source_ids: tuple[str, ...]
    only_when_market_calendar_offset_differs: bool


@dataclass(frozen=True)
class HolidayCalendarConfig:
    path: Path
    calendar_id: str
    schema_version: int
    symbol: str
    start_inclusive: datetime
    end_exclusive: datetime
    accepted_confidence_levels: frozenset[str]
    sources: Mapping[str, Mapping[str, Any]]
    event_intervals: tuple[HolidayClosureInterval, ...]
    recurring_rules: tuple[RecurringHolidayClosureRule, ...]


@dataclass(frozen=True)
class PipelineConfig:
    path: Path
    repository_root: Path
    version: int
    source: Mapping[str, Any]
    symbols: Mapping[str, SymbolConfig]
    paths: Mapping[str, Path]
    download: Mapping[str, Any]
    partition_rules: Mapping[str, Any]
    validation: Mapping[str, Any]
    canonical: Mapping[str, Any]
    holiday_calendars: Mapping[str, HolidayCalendarConfig]

    def symbol(self, name: str) -> SymbolConfig:
        try:
            return self.symbols[name.upper()]
        except KeyError as exc:
            supported = ", ".join(sorted(self.symbols))
            raise ConfigurationError(
                f"unsupported symbol {name!r}; configured symbols: {supported}"
            ) from exc

    def path_for(self, name: str) -> Path:
        try:
            configured = self.paths[name]
        except KeyError as exc:
            raise ConfigurationError(f"missing [paths].{name}") from exc
        return configured if configured.is_absolute() else self.repository_root / configured

    def holiday_calendar(self, name: str) -> HolidayCalendarConfig | None:
        return self.holiday_calendars.get(name.upper())


def load_config(path: str | Path) -> PipelineConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    version = int(payload.get("version", 0))
    if version != 1:
        raise ConfigurationError(f"unsupported config version {version}; expected 1")
    required = (
        "source",
        "symbols",
        "paths",
        "download",
        "partition_rules",
        "validation",
        "canonical",
    )
    for section in required:
        if section not in payload:
            raise ConfigurationError(f"missing [{section}] configuration section")
    source = payload["source"]
    if source.get("partition") != "hour" or source.get("timezone") != "UTC":
        raise ConfigurationError("D001 requires hourly UTC source partitions")
    if source.get("record_format") != ">IIIff" or int(
        source.get("record_size_bytes", 0)
    ) != TICK_STRUCT.size:
        raise ConfigurationError("source record contract must be >IIIff (20 bytes)")
    symbols = {
        name.upper(): SymbolConfig(
            archive_symbol=str(values["archive_symbol"]),
            price_scale=int(values["price_scale"]),
        )
        for name, values in payload["symbols"].items()
    }
    for name, symbol in symbols.items():
        if symbol.price_scale <= 0:
            raise ConfigurationError(f"{name} price_scale must be positive")
    partition_rules = payload["partition_rules"]
    if partition_rules.get("closure_timezone", "UTC") != "UTC":
        raise ConfigurationError("legacy closure rules must use UTC")
    market_calendars = partition_rules.get("symbol_market_calendars", {})
    if not isinstance(market_calendars, Mapping):
        raise ConfigurationError("symbol_market_calendars must be a table")
    repository_root = config_path.parent.parent
    holiday_calendars: dict[str, HolidayCalendarConfig] = {}
    for configured_name, rule in market_calendars.items():
        name = configured_name.upper()
        if name not in symbols:
            raise ConfigurationError(
                f"market calendar references unsupported symbol {configured_name!r}"
            )
        if not isinstance(rule, Mapping):
            raise ConfigurationError(f"{name} market calendar must be a table")
        calendar_timezone = str(rule.get("calendar_timezone", ""))
        try:
            ZoneInfo(calendar_timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ConfigurationError(
                f"{name} market calendar_timezone is invalid: {calendar_timezone!r}"
            ) from exc
        weekly_close_weekday = int(rule.get("weekly_close_local_weekday", -1))
        weekly_reopen_weekday = int(rule.get("weekly_reopen_local_weekday", -1))
        if (
            weekly_close_weekday not in range(7)
            or weekly_reopen_weekday not in range(7)
            or weekly_close_weekday == weekly_reopen_weekday
        ):
            raise ConfigurationError(
                f"{name} weekly close/reopen weekdays must be distinct integers 0 through 6"
            )
        _parse_local_time(
            rule.get("weekly_close_local_time"),
            field=f"{name}.weekly_close_local_time",
        )
        _parse_local_time(
            rule.get("weekly_reopen_local_time"),
            field=f"{name}.weekly_reopen_local_time",
        )
        maintenance_start = _parse_local_time(
            rule.get("maintenance_local_start"),
            field=f"{name}.maintenance_local_start",
        )
        maintenance_end = _parse_local_time(
            rule.get("maintenance_local_end"),
            field=f"{name}.maintenance_local_end",
        )
        if (maintenance_end - maintenance_start) % (24 * 60) != 60:
            raise ConfigurationError(
                f"{name} maintenance break must span exactly one native hourly partition"
            )
        weekdays = [
            int(day) for day in rule.get("maintenance_local_weekdays", [])
        ]
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ConfigurationError(
                f"{name}.maintenance_local_weekdays must contain ISO weekday "
                "integers 0 through 6"
            )
        if not str(rule.get("source_url", "")).startswith("https://"):
            raise ConfigurationError(
                f"{name} market calendar requires an HTTPS source_url"
            )
        holiday_fields = (
            rule.get("holiday_calendar_path"),
            rule.get("holiday_calendar_range_start_inclusive"),
            rule.get("holiday_calendar_range_end_exclusive"),
        )
        if any(value is not None for value in holiday_fields):
            if any(value is None for value in holiday_fields):
                raise ConfigurationError(
                    f"{name} holiday calendar path and configured range "
                    "must be provided together"
                )
            configured_path = Path(str(holiday_fields[0])).expanduser()
            calendar_path = (
                configured_path
                if configured_path.is_absolute()
                else repository_root / configured_path
            )
            holiday_calendars[name] = _load_holiday_calendar(
                calendar_path.resolve(),
                symbol=name,
                expected_start=_calendar_boundary(
                    holiday_fields[1],
                    field=(
                        f"{name}."
                        "holiday_calendar_range_start_inclusive"
                    ),
                ),
                expected_end=_calendar_boundary(
                    holiday_fields[2],
                    field=(
                        f"{name}."
                        "holiday_calendar_range_end_exclusive"
                    ),
                ),
            )
    return PipelineConfig(
        path=config_path,
        repository_root=repository_root,
        version=version,
        source=source,
        symbols=symbols,
        paths={key: Path(value) for key, value in payload["paths"].items()},
        download=payload["download"],
        partition_rules=partition_rules,
        validation=payload["validation"],
        canonical=payload["canonical"],
        holiday_calendars=holiday_calendars,
    )


def parse_utc_boundary(value: str) -> datetime:
    """Parse a date or timezone-aware ISO timestamp and normalize it to UTC."""

    if len(value) == 10:
        try:
            parsed_date = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"invalid date boundary {value!r}") from exc
        return datetime(
            parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO boundary {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime boundaries must include an explicit UTC offset")
    parsed = parsed.astimezone(UTC)
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError("boundaries must align to a whole UTC hour")
    return parsed


_HOLIDAY_CLOSURE_TYPES = {
    "expected_holiday_closure",
    "expected_special_hours_closure",
}
_HOLIDAY_CONFIDENCE_LEVELS = {"high", "medium", "low"}


def _calendar_boundary(value: Any, *, field: str) -> datetime:
    try:
        return parse_utc_boundary(str(value))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field} is invalid: {exc}") from exc


def _calendar_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{field} must be a JSON object")
    return value


def _calendar_source_ids(
    value: Any,
    *,
    sources: Mapping[str, Mapping[str, Any]],
    field: str,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{field} must cite at least one source")
    source_ids = tuple(str(item) for item in value)
    if len(source_ids) != len(set(source_ids)):
        raise ConfigurationError(f"{field} contains duplicate source IDs")
    missing = sorted(source_id for source_id in source_ids if source_id not in sources)
    if missing:
        raise ConfigurationError(f"{field} cites unknown sources: {missing}")
    return source_ids


def _load_holiday_calendar(
    path: Path,
    *,
    symbol: str,
    expected_start: datetime,
    expected_end: datetime,
) -> HolidayCalendarConfig:
    """Load and fail-closed validate one versioned symbol holiday calendar."""

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except DuplicateManifestKeyError as exc:
        raise ConfigurationError(
            f"holiday calendar {path} contains duplicate JSON key {exc.key!r}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"cannot load holiday calendar {path}: {exc}"
        ) from exc
    calendar = _calendar_mapping(payload, field=f"holiday calendar {path}")
    schema_version = calendar.get("calendar_schema_version")
    if schema_version != 1:
        raise ConfigurationError(
            f"unsupported holiday calendar schema {schema_version!r}"
        )
    normalized_symbol = symbol.upper()
    if calendar.get("symbol") != normalized_symbol:
        raise ConfigurationError(
            f"holiday calendar symbol {calendar.get('symbol')!r} does not "
            f"match {normalized_symbol}"
        )
    calendar_id = str(calendar.get("calendar_id") or "")
    if not calendar_id:
        raise ConfigurationError("holiday calendar_id must be non-empty")
    calendar_range = _calendar_mapping(
        calendar.get("range"), field="holiday calendar.range"
    )
    start = _calendar_boundary(
        calendar_range.get("start_inclusive"),
        field="holiday calendar.range.start_inclusive",
    )
    end = _calendar_boundary(
        calendar_range.get("end_exclusive"),
        field="holiday calendar.range.end_exclusive",
    )
    if start >= end:
        raise ConfigurationError("holiday calendar range must be increasing")
    if (start, end) != (expected_start, expected_end):
        raise ConfigurationError(
            "holiday calendar range is incompatible with the configured range"
        )

    raw_sources = _calendar_mapping(
        calendar.get("sources"), field="holiday calendar.sources"
    )
    if not raw_sources:
        raise ConfigurationError("holiday calendar.sources cannot be empty")
    sources: dict[str, Mapping[str, Any]] = {}
    required_source_fields = (
        "publisher",
        "title",
        "publication_date",
        "url",
        "applicable_timezone",
        "support",
    )
    for raw_source_id, raw_source in raw_sources.items():
        source_id = str(raw_source_id)
        if not source_id:
            raise ConfigurationError("holiday calendar source ID cannot be empty")
        source = dict(
            _calendar_mapping(
                raw_source,
                field=f"holiday calendar.sources.{source_id}",
            )
        )
        for required_field in required_source_fields:
            if not source.get(required_field):
                raise ConfigurationError(
                    f"holiday calendar source {source_id!r} lacks "
                    f"{required_field}"
                )
        if not str(source["url"]).startswith("https://"):
            raise ConfigurationError(
                f"holiday calendar source {source_id!r} must use HTTPS"
            )
        sources[source_id] = source

    policy = _calendar_mapping(
        calendar.get("classification_policy"),
        field="holiday calendar.classification_policy",
    )
    raw_confidences = policy.get("accepted_confidence_levels")
    if not isinstance(raw_confidences, list) or not raw_confidences:
        raise ConfigurationError(
            "holiday calendar accepted_confidence_levels must be a non-empty list"
        )
    accepted_confidences = frozenset(str(value) for value in raw_confidences)
    if (
        len(accepted_confidences) != len(raw_confidences)
        or not accepted_confidences <= _HOLIDAY_CONFIDENCE_LEVELS
    ):
        raise ConfigurationError(
            "holiday calendar accepted confidence levels are invalid"
        )

    raw_intervals = calendar.get("event_intervals")
    if not isinstance(raw_intervals, list):
        raise ConfigurationError(
            "holiday calendar.event_intervals must be a list"
        )
    seen_ids: set[str] = set()
    intervals: list[HolidayClosureInterval] = []
    for index, value in enumerate(raw_intervals):
        if not isinstance(value, list) or len(value) != 7:
            raise ConfigurationError(
                f"holiday event interval {index} must contain seven fields"
            )
        (
            raw_rule_id,
            raw_event,
            raw_rule_type,
            raw_start,
            raw_end,
            raw_confidence,
            raw_source_ids,
        ) = value
        rule_id = str(raw_rule_id)
        if not rule_id:
            raise ConfigurationError("holiday event rule_id cannot be empty")
        if rule_id in seen_ids:
            raise ConfigurationError(
                f"duplicate holiday calendar event ID: {rule_id}"
            )
        seen_ids.add(rule_id)
        rule_type = str(raw_rule_type)
        if rule_type not in _HOLIDAY_CLOSURE_TYPES:
            raise ConfigurationError(
                f"unsupported holiday closure type for {rule_id}: {rule_type}"
            )
        event = str(raw_event)
        if not event:
            raise ConfigurationError(
                f"holiday event label cannot be empty for {rule_id}"
            )
        interval_start = _calendar_boundary(
            raw_start, field=f"holiday event {rule_id}.start_inclusive"
        )
        interval_end = _calendar_boundary(
            raw_end, field=f"holiday event {rule_id}.end_exclusive"
        )
        if interval_start >= interval_end:
            raise ConfigurationError(
                f"holiday event interval is not increasing for {rule_id}"
            )
        if interval_start < start or interval_end > end:
            raise ConfigurationError(
                f"holiday event {rule_id} falls outside the calendar range"
            )
        confidence = str(raw_confidence)
        if confidence not in _HOLIDAY_CONFIDENCE_LEVELS:
            raise ConfigurationError(
                f"holiday event confidence is invalid for {rule_id}"
            )
        source_ids = _calendar_source_ids(
            raw_source_ids,
            sources=sources,
            field=f"holiday event {rule_id}.source_ids",
        )
        intervals.append(
            HolidayClosureInterval(
                rule_id=rule_id,
                rule_type=rule_type,
                event=event,
                start_inclusive=interval_start,
                end_exclusive=interval_end,
                confidence=confidence,
                source_ids=source_ids,
            )
        )
    intervals.sort(key=lambda item: (item.start_inclusive, item.end_exclusive))
    for left, right in zip(intervals, intervals[1:]):
        if right.start_inclusive < left.end_exclusive:
            raise ConfigurationError(
                "overlapping contradictory holiday intervals: "
                f"{left.rule_id}, {right.rule_id}"
            )

    raw_recurring = calendar.get("recurring_special_hours_rules")
    if not isinstance(raw_recurring, list):
        raise ConfigurationError(
            "holiday calendar.recurring_special_hours_rules must be a list"
        )
    recurring_rules: list[RecurringHolidayClosureRule] = []
    for index, value in enumerate(raw_recurring):
        rule = _calendar_mapping(
            value,
            field=f"holiday recurring rule {index}",
        )
        rule_id = str(rule.get("rule_id") or "")
        if not rule_id:
            raise ConfigurationError(
                "holiday recurring rule_id cannot be empty"
            )
        if rule_id in seen_ids:
            raise ConfigurationError(
                f"duplicate holiday calendar event ID: {rule_id}"
            )
        seen_ids.add(rule_id)
        rule_type = str(rule.get("closure_type") or "")
        if rule_type != "expected_special_hours_closure":
            raise ConfigurationError(
                f"unsupported recurring closure type for {rule_id}: "
                f"{rule_type}"
            )
        event = str(rule.get("event") or "")
        if not event:
            raise ConfigurationError(
                f"holiday recurring event label cannot be empty for {rule_id}"
            )
        timezone_name = str(rule.get("timezone") or "")
        try:
            ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ConfigurationError(
                f"holiday recurring rule {rule_id} has invalid timezone "
                f"{timezone_name!r}"
            ) from exc
        raw_weekdays = rule.get("local_weekdays")
        if (
            not isinstance(raw_weekdays, list)
            or not raw_weekdays
            or any(
                not isinstance(day, int)
                or isinstance(day, bool)
                or day not in range(7)
                for day in raw_weekdays
            )
        ):
            raise ConfigurationError(
                f"holiday recurring rule {rule_id} has invalid weekdays"
            )
        local_weekdays = tuple(int(day) for day in raw_weekdays)
        if len(local_weekdays) != len(set(local_weekdays)):
            raise ConfigurationError(
                f"holiday recurring rule {rule_id} has duplicate weekdays"
            )
        local_start = _parse_local_time(
            rule.get("local_start"),
            field=f"holiday recurring rule {rule_id}.local_start",
        )
        local_end = _parse_local_time(
            rule.get("local_end"),
            field=f"holiday recurring rule {rule_id}.local_end",
        )
        if (local_end - local_start) % (24 * 60) != 60:
            raise ConfigurationError(
                f"holiday recurring rule {rule_id} must span one hour"
            )
        confidence = str(rule.get("confidence") or "")
        if confidence not in _HOLIDAY_CONFIDENCE_LEVELS:
            raise ConfigurationError(
                f"holiday recurring confidence is invalid for {rule_id}"
            )
        source_ids = _calendar_source_ids(
            rule.get("source_ids"),
            sources=sources,
            field=f"holiday recurring rule {rule_id}.source_ids",
        )
        offset_condition = rule.get(
            "only_when_europe_london_offset_differs", False
        )
        if not isinstance(offset_condition, bool):
            raise ConfigurationError(
                f"holiday recurring rule {rule_id} offset condition "
                "must be boolean"
            )
        recurring_rules.append(
            RecurringHolidayClosureRule(
                rule_id=rule_id,
                rule_type=rule_type,
                event=event,
                timezone_name=timezone_name,
                local_weekdays=local_weekdays,
                local_start_minutes=local_start,
                local_end_minutes=local_end,
                confidence=confidence,
                source_ids=source_ids,
                only_when_market_calendar_offset_differs=offset_condition,
            )
        )

    return HolidayCalendarConfig(
        path=path,
        calendar_id=calendar_id,
        schema_version=int(schema_version),
        symbol=normalized_symbol,
        start_inclusive=start,
        end_exclusive=end,
        accepted_confidence_levels=accepted_confidences,
        sources=sources,
        event_intervals=tuple(intervals),
        recurring_rules=tuple(recurring_rules),
    )


def generate_partitions(start: datetime, end: datetime) -> list[Partition]:
    """Generate inclusive-start, exclusive-end native hourly partitions."""

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("partition boundaries must be timezone-aware")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if any((start.minute, start.second, start.microsecond)) or any(
        (end.minute, end.second, end.microsecond)
    ):
        raise ValueError("partition boundaries must align to UTC hours")
    if end <= start:
        raise ValueError("end boundary must be later than start boundary")
    count = int((end - start).total_seconds() // 3600)
    return [Partition(start + timedelta(hours=i)) for i in range(count)]


def partition_url(config: PipelineConfig, symbol: str, partition: Partition) -> str:
    mapping = config.symbol(symbol)
    timestamp = partition.timestamp
    values = {
        "base_url": str(config.source["base_url"]).rstrip("/"),
        "archive_symbol": mapping.archive_symbol,
        "year": timestamp.year,
        "month_zero": timestamp.month - 1,
        "day": timestamp.day,
        "hour": timestamp.hour,
    }
    return str(config.source["url_template"]).format(**values)


def partition_file_path(
    raw_root: Path, symbol: str, partition: Partition
) -> Path:
    timestamp = partition.timestamp
    return (
        raw_root
        / symbol.upper()
        / f"{timestamp.year:04d}"
        / f"{timestamp.month:02d}"
        / f"{timestamp.day:02d}"
        / f"{timestamp.hour:02d}h_ticks.bi5"
    )


def _parse_local_time(value: Any, *, field: str) -> int:
    try:
        hour_text, minute_text = str(value).split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field} must use HH:MM") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ConfigurationError(f"{field} must be a valid local wall-clock time")
    return hour * 60 + minute


def _cyclic_interval_contains(
    value: int,
    *,
    start: int,
    end: int,
    cycle: int,
) -> bool:
    value %= cycle
    start %= cycle
    end %= cycle
    if start < end:
        return start <= value < end
    return value >= start or value < end


def _holiday_rule_evidence(
    config: PipelineConfig,
    calendar: HolidayCalendarConfig,
    *,
    rule_id: str,
    rule_type: str,
    event: str,
    start_inclusive: datetime,
    end_exclusive: datetime,
    confidence: str,
    source_ids: tuple[str, ...],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sources = [
        {
            "source_id": source_id,
            **dict(calendar.sources[source_id]),
        }
        for source_id in source_ids
    ]
    result: dict[str, Any] = {
        "rule_id": rule_id,
        "rule_type": rule_type,
        "symbol": calendar.symbol,
        "calendar_id": calendar.calendar_id,
        "calendar_schema_version": calendar.schema_version,
        "calendar_path": relative_repository_path(
            calendar.path, config.repository_root
        ),
        "calendar_timezone": "UTC",
        "utc_interval": {
            "start_inclusive": format_utc(start_inclusive),
            "end_exclusive": format_utc(end_exclusive),
        },
        "event": event,
        "event_label": event,
        "confidence": confidence,
        "source_ids": list(source_ids),
        "evidence_source_ids": list(source_ids),
        "sources": sources,
    }
    if extra:
        result.update(extra)
    return result


def _expected_holiday_closure_rule(
    config: PipelineConfig,
    *,
    symbol: str,
    timestamp: datetime,
    market_rule: Mapping[str, Any],
) -> dict[str, Any] | None:
    calendar = config.holiday_calendar(symbol)
    if calendar is None:
        return None
    if not calendar.start_inclusive <= timestamp < calendar.end_exclusive:
        return None
    for interval in calendar.event_intervals:
        if interval.confidence not in calendar.accepted_confidence_levels:
            continue
        if interval.start_inclusive <= timestamp < interval.end_exclusive:
            return _holiday_rule_evidence(
                config,
                calendar,
                rule_id=interval.rule_id,
                rule_type=interval.rule_type,
                event=interval.event,
                start_inclusive=interval.start_inclusive,
                end_exclusive=interval.end_exclusive,
                confidence=interval.confidence,
                source_ids=interval.source_ids,
            )

    market_timezone_name = str(market_rule["calendar_timezone"])
    market_timezone = ZoneInfo(market_timezone_name)
    market_local_start = timestamp.astimezone(market_timezone)
    market_start_minutes = (
        market_local_start.hour * 60 + market_local_start.minute
    )
    maintenance_start = _parse_local_time(
        market_rule["maintenance_local_start"],
        field=f"{symbol}.maintenance_local_start",
    )
    maintenance_weekdays = {
        int(day) for day in market_rule["maintenance_local_weekdays"]
    }
    for recurring in calendar.recurring_rules:
        if recurring.confidence not in calendar.accepted_confidence_levels:
            continue
        local_timezone = ZoneInfo(recurring.timezone_name)
        local_start = timestamp.astimezone(local_timezone)
        local_end = (timestamp + timedelta(hours=1)).astimezone(
            local_timezone
        )
        actual_start = local_start.hour * 60 + local_start.minute
        actual_end = local_end.hour * 60 + local_end.minute
        if (
            local_start.weekday() not in recurring.local_weekdays
            or actual_start != recurring.local_start_minutes
            or actual_end != recurring.local_end_minutes
        ):
            continue
        if (
            recurring.only_when_market_calendar_offset_differs
            and market_local_start.weekday() in maintenance_weekdays
            and market_start_minutes == maintenance_start
        ):
            continue
        return _holiday_rule_evidence(
            config,
            calendar,
            rule_id=recurring.rule_id,
            rule_type=recurring.rule_type,
            event=recurring.event,
            start_inclusive=timestamp,
            end_exclusive=timestamp + timedelta(hours=1),
            confidence=recurring.confidence,
            source_ids=recurring.source_ids,
            extra={
                "applicable_timezone": recurring.timezone_name,
                "local_interval": (
                    f"{recurring.local_start_minutes // 60:02d}:"
                    f"{recurring.local_start_minutes % 60:02d}-"
                    f"{recurring.local_end_minutes // 60:02d}:"
                    f"{recurring.local_end_minutes % 60:02d}"
                ),
                "local_weekday": local_start.weekday(),
                "local_partition_start": local_start.isoformat(),
                "utc_offset_seconds": int(
                    local_start.utcoffset().total_seconds()
                ),
                "market_calendar_timezone": market_timezone_name,
            },
        )
    return None


def expected_closure_rule(
    config: PipelineConfig,
    partition: Partition,
    *,
    symbol: str | None = None,
) -> dict[str, Any] | None:
    """Return the exact configured calendar rule matching a native UTC hour."""

    rules = config.partition_rules
    if rules.get("closure_timezone", "UTC") != "UTC":
        raise ConfigurationError("legacy closure rules must use UTC")
    timestamp = partition.timestamp
    if timestamp.weekday() in {int(day) for day in rules.get("full_day_closed_weekdays", [])}:
        return {
            "rule_id": f"utc_full_day_weekday_{timestamp.weekday()}",
            "rule_type": "full_day_closed_weekday",
            "calendar_timezone": "UTC",
        }
    if timestamp.date().isoformat() in set(rules.get("explicit_closed_dates", [])):
        return {
            "rule_id": f"utc_closed_date_{timestamp.date().isoformat()}",
            "rule_type": "explicit_closed_date",
            "calendar_timezone": "UTC",
        }
    closed_hours = rules.get("closed_utc_hours_by_weekday", {})
    if timestamp.hour in {
        int(hour) for hour in closed_hours.get(str(timestamp.weekday()), [])
    }:
        return {
            "rule_id": f"utc_weekday_{timestamp.weekday()}_hour_{timestamp.hour:02d}",
            "rule_type": "closed_utc_hour_by_weekday",
            "calendar_timezone": "UTC",
        }

    if symbol is None:
        return None
    normalized_symbol = symbol.upper()
    market_calendars = rules.get("symbol_market_calendars", {})
    rule = market_calendars.get(normalized_symbol)
    if not isinstance(rule, Mapping):
        return None
    calendar_timezone = str(rule["calendar_timezone"])
    calendar = ZoneInfo(calendar_timezone)
    local_start = timestamp.astimezone(calendar)
    local_end = (timestamp + timedelta(hours=1)).astimezone(calendar)
    actual_start = local_start.hour * 60 + local_start.minute
    actual_end = local_end.hour * 60 + local_end.minute

    weekly_close = (
        int(rule["weekly_close_local_weekday"]) * 24 * 60
        + _parse_local_time(
            rule["weekly_close_local_time"],
            field=f"{normalized_symbol}.weekly_close_local_time",
        )
    )
    weekly_reopen = (
        int(rule["weekly_reopen_local_weekday"]) * 24 * 60
        + _parse_local_time(
            rule["weekly_reopen_local_time"],
            field=f"{normalized_symbol}.weekly_reopen_local_time",
        )
    )
    local_minute_of_week = local_start.weekday() * 24 * 60 + actual_start
    if _cyclic_interval_contains(
        local_minute_of_week,
        start=weekly_close,
        end=weekly_reopen,
        cycle=7 * 24 * 60,
    ):
        return {
            "rule_id": f"{normalized_symbol}_weekly_market_close",
            "rule_type": "symbol_weekly_market_close",
            "symbol": normalized_symbol,
            "calendar_timezone": calendar_timezone,
            "local_interval": (
                f"weekday {rule['weekly_close_local_weekday']} "
                f"{rule['weekly_close_local_time']}-weekday "
                f"{rule['weekly_reopen_local_weekday']} "
                f"{rule['weekly_reopen_local_time']}"
            ),
            "local_weekday": local_start.weekday(),
            "local_partition_start": local_start.isoformat(),
            "utc_offset_seconds": int(local_start.utcoffset().total_seconds()),
            "source_url": str(rule["source_url"]),
        }

    configured_start = _parse_local_time(
        rule["maintenance_local_start"],
        field=f"{normalized_symbol}.maintenance_local_start",
    )
    configured_end = _parse_local_time(
        rule["maintenance_local_end"],
        field=f"{normalized_symbol}.maintenance_local_end",
    )
    local_weekdays = {
        int(day) for day in rule["maintenance_local_weekdays"]
    }
    if (
        local_start.weekday() in local_weekdays
        and actual_start == configured_start
        and actual_end == configured_end
    ):
        return {
            "rule_id": f"{normalized_symbol}_daily_maintenance",
            "rule_type": "symbol_daily_maintenance",
            "symbol": normalized_symbol,
            "calendar_timezone": calendar_timezone,
            "local_interval": (
                f"{rule['maintenance_local_start']}-"
                f"{rule['maintenance_local_end']}"
            ),
            "local_weekday": local_start.weekday(),
            "local_partition_start": local_start.isoformat(),
            "utc_offset_seconds": int(local_start.utcoffset().total_seconds()),
            "source_url": str(rule["source_url"]),
        }
    return _expected_holiday_closure_rule(
        config,
        symbol=normalized_symbol,
        timestamp=timestamp,
        market_rule=rule,
    )


def is_expected_closure(
    config: PipelineConfig,
    partition: Partition,
    *,
    symbol: str | None = None,
) -> bool:
    """Return whether an explicit calendar rule matches this exact partition."""

    return expected_closure_rule(config, partition, symbol=symbol) is not None


def manifest_no_data_evidence(entry: Mapping[str, Any] | None) -> str | None:
    """Return affirmative no-data evidence; never infer it from a missing record."""

    if entry is None:
        return None
    status = str(entry.get("status", "")).strip().lower()
    error_details = str(entry.get("error_details") or "").strip().lower()
    failure_markers = (
        "http ",
        "timeout",
        "timed out",
        "proxy",
        "source request error",
        "connection",
        "stream reset",
        "ssl:",
        "tls",
        "decode",
        "lzma",
        "malformed",
        "checksum",
        "missing file",
        "file not found",
        "connection reset",
    )
    if any(marker in error_details for marker in failure_markers):
        return None
    if status == "failed" and error_details.startswith("empty_payload:"):
        return "empty_payload"
    if status in {"no_data", "no-data"}:
        return f"manifest_status:{status}"
    if status == "expected_market_closure":
        if error_details.startswith("empty_payload:"):
            return "empty_payload"
        if error_details.startswith(("no_data:", "no-data:")):
            return "explicit_no_data"
    return None


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_bi5_payload(
    compressed: bytes,
    *,
    max_compressed_bytes: int,
    record_size: int = TICK_STRUCT.size,
) -> tuple[bytes, int]:
    """Validate a compressed BI5 object and return decoded bytes and row count."""

    if not compressed:
        raise EmptyPayloadError("compressed response is empty")
    if len(compressed) > max_compressed_bytes:
        raise MalformedPayloadError(
            f"compressed response exceeds {max_compressed_bytes} bytes"
        )
    prefix = compressed[:256].lstrip().lower()
    placeholder_markers = (b"<!doctype", b"<html", b"<?xml", b"access denied", b"not found")
    if any(prefix.startswith(marker) for marker in placeholder_markers):
        raise PlaceholderPayloadError("response resembles an HTML/text placeholder")
    try:
        decoded = lzma.decompress(compressed)
    except lzma.LZMAError as exc:
        raise MalformedPayloadError(f"LZMA decompression failed: {exc}") from exc
    if not decoded:
        raise EmptyPayloadError("compressed object contains zero tick records")
    if len(decoded) % record_size:
        raise MalformedPayloadError(
            f"decoded size {len(decoded)} is not divisible by record size {record_size}"
        )
    record_count = len(decoded) // record_size
    for index, (offset_ms, _ask, _bid, ask_volume, bid_volume) in enumerate(
        TICK_STRUCT.iter_unpack(decoded)
    ):
        if offset_ms >= 3_600_000:
            raise MalformedPayloadError(
                f"record {index} has out-of-hour millisecond offset {offset_ms}"
            )
        if not math.isfinite(ask_volume) or not math.isfinite(bid_volume):
            raise MalformedPayloadError(f"record {index} has non-finite volume")
    return decoded, record_count


def validate_bi5_file(path: Path, *, max_compressed_bytes: int) -> int:
    compressed = path.read_bytes()
    _, rows = inspect_bi5_payload(
        compressed, max_compressed_bytes=max_compressed_bytes
    )
    return rows


def decode_ticks(
    decoded: bytes, *, partition: Partition, price_scale: int
) -> Iterator[dict[str, Any]]:
    base_ms = int(partition.timestamp.timestamp() * 1000)
    for offset_ms, ask_raw, bid_raw, ask_volume, bid_volume in TICK_STRUCT.iter_unpack(
        decoded
    ):
        yield {
            "timestamp_ms": base_ms + offset_ms,
            "bid": bid_raw / price_scale,
            "ask": ask_raw / price_scale,
            "bid_volume": float(bid_volume),
            "ask_volume": float(ask_volume),
            "partition_timestamp": partition.key,
        }


def relative_repository_path(path: Path, repository_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_manifest_file_path(
    file_path: str | None, *, repository_root: Path
) -> Path | None:
    if not file_path:
        return None
    candidate = Path(file_path)
    return candidate if candidate.is_absolute() else repository_root / candidate


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably write bytes beside their destination, then atomically replace it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, encoded)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting keys that json.loads would overwrite."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateManifestKeyError(key)
        result[key] = value
    return result


class Manifest:
    """Atomic JSON manifest with one current record per native partition."""

    def __init__(
        self,
        path: Path,
        *,
        config: PipelineConfig,
        symbol: str,
    ) -> None:
        self.path = path
        self.config = config
        self.symbol = symbol.upper()
        mapping = config.symbol(self.symbol)
        if path.exists():
            self.payload = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            if self.payload.get("symbol") != self.symbol:
                raise ConfigurationError(
                    f"manifest symbol {self.payload.get('symbol')!r} does not match {self.symbol}"
                )
        else:
            self.payload = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "config_version": config.version,
                "code_version": CODE_VERSION,
                "symbol": self.symbol,
                "archive_symbol": mapping.archive_symbol,
                "source": config.source["id"],
                "source_url_template": config.source["url_template"],
                "partition": "hour",
                "timezone": "UTC",
                "partitions": {},
            }

    @property
    def entries(self) -> dict[str, dict[str, Any]]:
        return self.payload["partitions"]

    def get(self, partition: Partition) -> dict[str, Any] | None:
        return self.entries.get(partition.key)

    def record(self, partition: Partition, **values: Any) -> dict[str, Any]:
        entry = {
            "symbol": self.symbol,
            "partition_timestamp": partition.key,
            **values,
        }
        self.entries[partition.key] = entry
        return entry

    def save(self) -> None:
        self.payload["partitions"] = dict(sorted(self.entries.items()))
        atomic_write_json(self.path, self.payload)


class StructuredLogger:
    """Small JSON-lines logger suitable for both terminal and generated log files."""

    def __init__(self, *, log_path: Path | None = None, quiet: bool = False) -> None:
        self.logger = logging.getLogger(f"dukascopy.{id(self)}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers.clear()
        self.log_path = log_path
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = log_path.open("a", encoding="utf-8")
        else:
            self._file_handle = None
        self.quiet = quiet

    def emit(self, level: str, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            **fields,
        }
        line = json.dumps(record, sort_keys=True, default=str)
        if not self.quiet:
            print(line, flush=True)
        if self._file_handle is not None:
            self._file_handle.write(line + "\n")
            self._file_handle.flush()

    def close(self) -> None:
        if self._file_handle is not None:
            self._file_handle.close()

    def __enter__(self) -> "StructuredLogger":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def manifest_file_hash(path: Path) -> str:
    return sha256_file(path)


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def group_partitions_by_date(
    partitions: Iterable[Partition],
) -> dict[str, list[Partition]]:
    grouped: dict[str, list[Partition]] = {}
    for partition in partitions:
        grouped.setdefault(partition.timestamp.date().isoformat(), []).append(partition)
    return grouped
