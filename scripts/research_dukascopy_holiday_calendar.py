#!/usr/bin/env python3
"""Build the D002 XAUUSD holiday/special-hours audit without downloading data."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from zoneinfo import ZoneInfo

try:
    from scripts.dukascopy_common import (
        Manifest,
        PipelineConfig,
        atomic_write_bytes,
        atomic_write_json,
        format_utc,
        load_config,
        manifest_file_hash,
        parse_utc_boundary,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_file,
        utc_now,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution fallback
    from dukascopy_common import (  # type: ignore
        Manifest,
        PipelineConfig,
        atomic_write_bytes,
        atomic_write_json,
        format_utc,
        load_config,
        manifest_file_hash,
        parse_utc_boundary,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_file,
        utc_now,
    )


UTC = timezone.utc
BASELINE_SCHEMA_VERSION = 1
AUDIT_SCHEMA_VERSION = 1
ALLOWED_CLOSURE_TYPES = {
    "expected_holiday_closure",
    "expected_special_hours_closure",
}
NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _range_from_report(report: Mapping[str, Any]) -> tuple[datetime, datetime]:
    coverage = _require_mapping(report.get("range"), name="report.range")
    return (
        parse_utc_boundary(str(coverage["start_inclusive"])),
        parse_utc_boundary(str(coverage["end_exclusive"])),
    )


def build_baseline_snapshot(
    *,
    config: PipelineConfig,
    symbol: str,
    manifest_path: Path,
    verification_report_path: Path,
    holiday_candidates_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Snapshot and validate the pre-classification full-range state."""

    report = _require_mapping(
        _read_json(verification_report_path), name="verification report"
    )
    candidates_report = _require_mapping(
        _read_json(holiday_candidates_path), name="holiday candidates report"
    )
    symbol = symbol.upper()
    if report.get("symbol") != symbol or candidates_report.get("symbol") != symbol:
        raise ValueError("baseline inputs do not describe the requested symbol")
    start, end = _range_from_report(report)
    candidate_start, candidate_end = _range_from_report(candidates_report)
    if (candidate_start, candidate_end) != (start, end):
        raise ValueError("verification and holiday-candidate ranges differ")

    reconciliation = _require_mapping(
        report.get("reconciliation"), name="report.reconciliation"
    )
    if not reconciliation.get("balanced"):
        raise ValueError("baseline verification report is not balanced")

    manifest = Manifest(manifest_path, config=config, symbol=symbol)
    verified_files: list[dict[str, Any]] = []
    unresolved_records: list[dict[str, Any]] = []
    partitions = report.get("partitions")
    if not isinstance(partitions, list):
        raise ValueError("verification report.partitions must be a list")

    for item_value in partitions:
        item = _require_mapping(item_value, name="verification partition")
        timestamp = str(item["partition_timestamp"])
        entry = manifest.entries.get(timestamp)
        classification = item.get("classification")
        if classification == "verified_data":
            if entry is None or entry.get("status") != "verified":
                raise ValueError(
                    f"verified partition lacks a verified manifest record: {timestamp}"
                )
            file_path = resolve_manifest_file_path(
                entry.get("file_path"), repository_root=config.repository_root
            )
            if file_path is None or not file_path.is_file():
                raise ValueError(f"verified BI5 file is missing: {timestamp}")
            stored_sha256 = entry.get("sha256")
            if not isinstance(stored_sha256, str) or not stored_sha256:
                raise ValueError(f"verified partition has no stored SHA256: {timestamp}")
            actual_sha256 = sha256_file(file_path)
            if actual_sha256 != stored_sha256:
                raise ValueError(
                    f"verified-file integrity failure before D002: {timestamp}"
                )
            actual_size = file_path.stat().st_size
            if entry.get("byte_size") != actual_size:
                raise ValueError(
                    f"verified-file size differs from manifest before D002: {timestamp}"
                )
            verified_files.append(
                {
                    "partition_timestamp": timestamp,
                    "file_path": relative_repository_path(
                        file_path, config.repository_root
                    ),
                    "file_size": actual_size,
                    "stored_sha256": stored_sha256,
                    "actual_sha256": actual_sha256,
                    "manifest_status": entry.get("status"),
                    "evidence_kind": entry.get("evidence_kind"),
                }
            )
        elif classification == "unresolved_status":
            unresolved_records.append(
                {
                    "partition_timestamp": timestamp,
                    "manifest_status": (entry or {}).get("status"),
                    "evidence_kind": (entry or {}).get("evidence_kind"),
                    "http_status": (entry or {}).get("http_status"),
                    "response_byte_length": (entry or {}).get(
                        "response_byte_length"
                    ),
                }
            )

    candidate_values = candidates_report.get("candidates")
    if not isinstance(candidate_values, list):
        raise ValueError("holiday candidates report.candidates must be a list")
    candidate_timestamps = sorted(
        str(_require_mapping(item, name="holiday candidate")["partition_timestamp"])
        for item in candidate_values
    )
    unresolved_timestamps = sorted(
        item["partition_timestamp"] for item in unresolved_records
    )
    if candidate_timestamps != unresolved_timestamps:
        raise ValueError(
            "holiday-candidate timestamps do not exactly match unresolved baseline"
        )

    expected_verified = int(reconciliation["verified"])
    expected_unresolved = int(reconciliation["unresolved"])
    if len(verified_files) != expected_verified:
        raise ValueError(
            f"verified snapshot count {len(verified_files)} != {expected_verified}"
        )
    if len(unresolved_records) != expected_unresolved:
        raise ValueError(
            f"unresolved snapshot count {len(unresolved_records)} != "
            f"{expected_unresolved}"
        )

    return {
        "snapshot_schema_version": BASELINE_SCHEMA_VERSION,
        "task": "D002",
        "mode": "read_only_pre_classification_baseline",
        "generated_at": format_utc(generated_at or utc_now()),
        "symbol": symbol,
        "range": {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(end),
        },
        "verification_report_path": relative_repository_path(
            verification_report_path, config.repository_root
        ),
        "holiday_candidates_path": relative_repository_path(
            holiday_candidates_path, config.repository_root
        ),
        "manifest_path": relative_repository_path(
            manifest_path, config.repository_root
        ),
        "manifest_sha256": manifest_file_hash(manifest_path),
        "reconciliation": dict(reconciliation),
        "expected_partition_count": int(reconciliation["expected_partitions"]),
        "verified_partition_count": len(verified_files),
        "unresolved_partition_count": len(unresolved_records),
        "verified_files": verified_files,
        "unresolved_records": unresolved_records,
    }


def _load_calendar(
    path: Path, *, symbol: str, expected_start: datetime, expected_end: datetime
) -> dict[str, Any]:
    calendar = dict(_require_mapping(_read_json(path), name="holiday calendar"))
    if calendar.get("calendar_schema_version") != 1:
        raise ValueError("unsupported holiday calendar schema")
    if calendar.get("symbol") != symbol.upper():
        raise ValueError("holiday calendar symbol does not match")
    calendar_range = _require_mapping(calendar.get("range"), name="calendar.range")
    if (
        parse_utc_boundary(str(calendar_range["start_inclusive"])),
        parse_utc_boundary(str(calendar_range["end_exclusive"])),
    ) != (expected_start, expected_end):
        raise ValueError("holiday calendar range does not match the baseline")
    sources = _require_mapping(calendar.get("sources"), name="calendar.sources")
    for source_id, value in sources.items():
        source = _require_mapping(value, name=f"calendar.sources.{source_id}")
        for field in (
            "publisher",
            "title",
            "publication_date",
            "url",
            "applicable_timezone",
            "support",
        ):
            if not source.get(field):
                raise ValueError(f"calendar source {source_id!r} lacks {field}")
        if not str(source["url"]).startswith("https://"):
            raise ValueError(f"calendar source {source_id!r} must use HTTPS")
    _validate_calendar_rules(calendar)
    return calendar


def _validate_source_ids(
    source_ids: Any, *, sources: Mapping[str, Any], context: str
) -> list[str]:
    if not isinstance(source_ids, list) or not source_ids:
        raise ValueError(f"{context} must cite at least one source")
    normalized = [str(source_id) for source_id in source_ids]
    missing = [source_id for source_id in normalized if source_id not in sources]
    if missing:
        raise ValueError(f"{context} cites unknown sources: {missing}")
    return normalized


def _validate_calendar_rules(calendar: Mapping[str, Any]) -> None:
    sources = _require_mapping(calendar.get("sources"), name="calendar.sources")
    intervals = calendar.get("event_intervals")
    if not isinstance(intervals, list):
        raise ValueError("calendar.event_intervals must be a list")
    seen_ids: set[str] = set()
    parsed: list[tuple[datetime, datetime, str]] = []
    for value in intervals:
        if not isinstance(value, list) or len(value) != 7:
            raise ValueError("each event interval must contain seven fields")
        rule_id, _event, closure_type, start_text, end_text, confidence, source_ids = (
            value
        )
        rule_id = str(rule_id)
        if rule_id in seen_ids:
            raise ValueError(f"duplicate holiday interval id: {rule_id}")
        seen_ids.add(rule_id)
        if closure_type not in ALLOWED_CLOSURE_TYPES:
            raise ValueError(f"unsupported closure type for {rule_id}: {closure_type}")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError(f"unsupported confidence for {rule_id}: {confidence}")
        start = parse_utc_boundary(str(start_text))
        end = parse_utc_boundary(str(end_text))
        if start >= end:
            raise ValueError(f"invalid event interval for {rule_id}")
        if (end - start).total_seconds() % 3600:
            raise ValueError(f"event interval is not hourly for {rule_id}")
        _validate_source_ids(
            source_ids, sources=sources, context=f"event interval {rule_id}"
        )
        parsed.append((start, end, rule_id))
    parsed.sort()
    for (_, left_end, left_id), (right_start, _, right_id) in zip(
        parsed, parsed[1:]
    ):
        if right_start < left_end:
            raise ValueError(
                f"overlapping event intervals are ambiguous: {left_id}, {right_id}"
            )

    recurring = calendar.get("recurring_special_hours_rules")
    if not isinstance(recurring, list) or not recurring:
        raise ValueError("calendar must define recurring special-hours rules")
    for value in recurring:
        rule = _require_mapping(value, name="recurring special-hours rule")
        rule_id = str(rule.get("rule_id"))
        if rule_id in seen_ids:
            raise ValueError(f"duplicate calendar rule id: {rule_id}")
        seen_ids.add(rule_id)
        if rule.get("closure_type") != "expected_special_hours_closure":
            raise ValueError(f"recurring rule {rule_id} has invalid closure type")
        if rule.get("timezone") != "America/New_York":
            raise ValueError(f"recurring rule {rule_id} must use America/New_York")
        if rule.get("local_start") != "17:00" or rule.get("local_end") != "18:00":
            raise ValueError(f"recurring rule {rule_id} must span 17:00-18:00 NY")
        weekdays = rule.get("local_weekdays")
        if not isinstance(weekdays, list) or any(
            not isinstance(day, int) or day not in range(7) for day in weekdays
        ):
            raise ValueError(f"recurring rule {rule_id} has invalid weekdays")
        _validate_source_ids(
            rule.get("source_ids"),
            sources=sources,
            context=f"recurring rule {rule_id}",
        )


def group_contiguous_timestamps(timestamps: list[str]) -> list[dict[str, Any]]:
    """Group unique hourly UTC timestamps into exact half-open intervals."""

    parsed = sorted(parse_utc_boundary(value) for value in timestamps)
    if len(parsed) != len(set(parsed)):
        raise ValueError("candidate timestamps contain duplicates")
    if not parsed:
        return []
    grouped: list[dict[str, Any]] = []
    start = previous = parsed[0]
    for current in parsed[1:]:
        if current != previous + timedelta(hours=1):
            grouped.append(
                {
                    "start_inclusive": format_utc(start),
                    "end_exclusive": format_utc(previous + timedelta(hours=1)),
                    "partition_count": int(
                        (previous + timedelta(hours=1) - start).total_seconds()
                        // 3600
                    ),
                }
            )
            start = current
        previous = current
    grouped.append(
        {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(previous + timedelta(hours=1)),
            "partition_count": int(
                (previous + timedelta(hours=1) - start).total_seconds() // 3600
            ),
        }
    )
    return grouped


def _source_records(
    calendar: Mapping[str, Any], source_ids: list[str]
) -> list[dict[str, Any]]:
    sources = _require_mapping(calendar["sources"], name="calendar.sources")
    return [
        {"source_id": source_id, **dict(_require_mapping(sources[source_id], name=source_id))}
        for source_id in source_ids
    ]


def _event_match(
    calendar: Mapping[str, Any], timestamp: datetime
) -> dict[str, Any] | None:
    for value in calendar["event_intervals"]:
        rule_id, event, closure_type, start_text, end_text, confidence, source_ids = (
            value
        )
        start = parse_utc_boundary(str(start_text))
        end = parse_utc_boundary(str(end_text))
        if start <= timestamp < end:
            return {
                "rule_id": str(rule_id),
                "closure_type": str(closure_type),
                "event": str(event),
                "applicable_timezone": "UTC",
                "closed_interval": {
                    "start_inclusive": format_utc(start),
                    "end_exclusive": format_utc(end),
                },
                "confidence": str(confidence),
                "sources": _source_records(calendar, [str(x) for x in source_ids]),
            }
    return None


def _recurring_match(
    calendar: Mapping[str, Any], timestamp: datetime
) -> dict[str, Any] | None:
    local = timestamp.astimezone(NEW_YORK)
    if local.hour != 17 or local.minute or local.second or local.microsecond:
        return None
    for value in calendar["recurring_special_hours_rules"]:
        rule = _require_mapping(value, name="recurring special-hours rule")
        if local.weekday() not in rule["local_weekdays"]:
            continue
        if rule.get("only_when_europe_london_offset_differs"):
            # D001 expresses the break at 22:00 Europe/London.  During the
            # US/EU transition gap, 17:00 New York maps to 21:00 London and is
            # therefore outside the D001 hour.
            if timestamp.astimezone(LONDON).hour == 22:
                continue
        return {
            "rule_id": str(rule["rule_id"]),
            "closure_type": str(rule["closure_type"]),
            "event": str(rule["event"]),
            "applicable_timezone": str(rule["timezone"]),
            "closed_interval": {
                "start_inclusive": format_utc(timestamp),
                "end_exclusive": format_utc(timestamp + timedelta(hours=1)),
            },
            "confidence": str(rule["confidence"]),
            "sources": _source_records(
                calendar, [str(x) for x in rule["source_ids"]]
            ),
        }
    return None


def classify_candidate(
    candidate_value: Mapping[str, Any], calendar: Mapping[str, Any]
) -> dict[str, Any]:
    """Classify one confirmed-empty candidate, failing closed on evidence."""

    candidate = dict(candidate_value)
    timestamp_text = str(candidate["partition_timestamp"])
    timestamp = parse_utc_boundary(timestamp_text)
    evidence_ok = (
        candidate.get("evidence_kind") == "confirmed_empty_payload"
        and candidate.get("http_status") == 200
        and candidate.get("response_byte_length") == 0
    )
    base = {
        **candidate,
        "classification": "unexplained_empty_payload",
        "closure_type": None,
        "rule_id": None,
        "event": None,
        "applicable_timezone": None,
        "closed_interval": None,
        "confidence": None,
        "sources": [],
        "classification_reason": None,
    }
    if not evidence_ok:
        base["classification_reason"] = (
            "required HTTP 200 confirmed-zero-byte evidence is absent"
        )
        return base

    match = _event_match(calendar, timestamp) or _recurring_match(
        calendar, timestamp
    )
    if match is None:
        base["classification_reason"] = (
            "no authoritative D002 holiday or special-hours rule matched"
        )
        return base
    accepted = set(
        _require_mapping(
            calendar["classification_policy"], name="classification_policy"
        )["accepted_confidence_levels"]
    )
    if match["confidence"] not in accepted:
        base["classification_reason"] = (
            f"matched confidence {match['confidence']!r} is not accepted"
        )
        return base
    base.update(
        classification=match["closure_type"],
        closure_type=match["closure_type"],
        rule_id=match["rule_id"],
        event=match["event"],
        applicable_timezone=match["applicable_timezone"],
        closed_interval=match["closed_interval"],
        confidence=match["confidence"],
        sources=match["sources"],
        classification_reason=(
            "authoritative schedule matched exact hour and source evidence "
            "confirms HTTP 200 zero-byte response"
        ),
    )
    return base


def _verify_post_classification_integrity(
    *,
    baseline: Mapping[str, Any],
    config: PipelineConfig,
    manifest_path: Path,
    verification_report_path: Path,
    symbol: str,
) -> dict[str, Any]:
    manifest = Manifest(manifest_path, config=config, symbol=symbol)
    current_report = _require_mapping(
        _read_json(verification_report_path), name="current verification report"
    )
    current_verified = {
        str(item["partition_timestamp"])
        for item in current_report["partitions"]
        if item["classification"] == "verified_data"
    }
    baseline_verified_values = baseline.get("verified_files")
    if not isinstance(baseline_verified_values, list):
        raise ValueError("baseline verified_files must be a list")
    baseline_verified = {
        str(_require_mapping(value, name="baseline verified file")["partition_timestamp"]):
        _require_mapping(value, name="baseline verified file")
        for value in baseline_verified_values
    }
    added = sorted(current_verified - set(baseline_verified))
    removed = sorted(set(baseline_verified) - current_verified)
    renamed: list[str] = []
    size_changed: list[str] = []
    stored_hash_changed: list[str] = []
    actual_hash_mismatch: list[str] = []
    downgraded: list[str] = []
    for timestamp, old in baseline_verified.items():
        entry = manifest.entries.get(timestamp)
        if entry is None or entry.get("status") != "verified":
            downgraded.append(timestamp)
            continue
        path = resolve_manifest_file_path(
            entry.get("file_path"), repository_root=config.repository_root
        )
        current_relative = (
            relative_repository_path(path, config.repository_root)
            if path is not None
            else None
        )
        if current_relative != old["file_path"]:
            renamed.append(timestamp)
            continue
        if path is None or not path.is_file():
            removed.append(timestamp)
            continue
        if path.stat().st_size != old["file_size"]:
            size_changed.append(timestamp)
        if entry.get("sha256") != old["stored_sha256"]:
            stored_hash_changed.append(timestamp)
        if sha256_file(path) != entry.get("sha256"):
            actual_hash_mismatch.append(timestamp)

    failures = {
        "verified_partitions_added": sorted(set(added)),
        "verified_partitions_removed": sorted(set(removed)),
        "verified_files_renamed": renamed,
        "verified_file_sizes_changed": size_changed,
        "stored_sha256_changed": stored_hash_changed,
        "stored_sha256_mismatches": actual_hash_mismatch,
        "previously_verified_downgraded": downgraded,
    }
    passed = all(not values for values in failures.values())
    return {
        "passed": passed,
        "manifest_sha256_before": baseline["manifest_sha256"],
        "manifest_sha256_after": manifest_file_hash(manifest_path),
        "manifest_unchanged": (
            baseline["manifest_sha256"] == manifest_file_hash(manifest_path)
        ),
        "verified_file_count_before": len(baseline_verified),
        "verified_file_count_after": len(current_verified),
        "all_stored_sha256_match_files": not actual_hash_mismatch,
        **failures,
    }


def _build_classified_intervals(
    classified: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not classified:
        return []
    ordered = sorted(
        classified, key=lambda item: parse_utc_boundary(item["partition_timestamp"])
    )
    intervals: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = [ordered[0]]
    for item in ordered[1:]:
        previous_time = parse_utc_boundary(current[-1]["partition_timestamp"])
        current_time = parse_utc_boundary(item["partition_timestamp"])
        same_label = all(
            item.get(field) == current[-1].get(field)
            for field in ("classification", "rule_id", "event", "confidence")
        )
        if current_time != previous_time + timedelta(hours=1) or not same_label:
            intervals.append(_summarize_classified_interval(current))
            current = [item]
        else:
            current.append(item)
    intervals.append(_summarize_classified_interval(current))
    return intervals


def _summarize_classified_interval(items: list[dict[str, Any]]) -> dict[str, Any]:
    start = parse_utc_boundary(items[0]["partition_timestamp"])
    end = parse_utc_boundary(items[-1]["partition_timestamp"]) + timedelta(hours=1)
    first = items[0]
    return {
        "start_inclusive": format_utc(start),
        "end_exclusive": format_utc(end),
        "partition_count": len(items),
        "classification": first["classification"],
        "closure_type": first["closure_type"],
        "rule_id": first["rule_id"],
        "event": first["event"],
        "applicable_timezone": first["applicable_timezone"],
        "confidence": first["confidence"],
        "sources": first["sources"],
    }


def build_d002_audit(
    *,
    config: PipelineConfig,
    symbol: str,
    baseline_path: Path,
    manifest_path: Path,
    verification_report_path: Path,
    holiday_candidates_path: Path,
    calendar_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    baseline = _require_mapping(_read_json(baseline_path), name="D002 baseline")
    if baseline.get("mode") != "read_only_pre_classification_baseline":
        raise ValueError("D002 baseline has an invalid mode")
    symbol = symbol.upper()
    if baseline.get("symbol") != symbol:
        raise ValueError("D002 baseline symbol does not match")
    start, end = _range_from_report(baseline)
    calendar = _load_calendar(
        calendar_path, symbol=symbol, expected_start=start, expected_end=end
    )
    candidates_report = _require_mapping(
        _read_json(holiday_candidates_path), name="holiday candidates report"
    )
    candidate_values = candidates_report.get("candidates")
    if not isinstance(candidate_values, list):
        raise ValueError("holiday candidates must be a list")
    candidate_mappings = [
        _require_mapping(value, name="holiday candidate") for value in candidate_values
    ]
    candidate_intervals = group_contiguous_timestamps(
        [str(value["partition_timestamp"]) for value in candidate_mappings]
    )
    classified = [
        classify_candidate(candidate, calendar) for candidate in candidate_mappings
    ]
    counts = Counter(item["classification"] for item in classified)
    evidence_violations = [
        item["partition_timestamp"]
        for item in classified
        if item["classification"] in ALLOWED_CLOSURE_TYPES
        and not (
            item.get("evidence_kind") == "confirmed_empty_payload"
            and item.get("http_status") == 200
            and item.get("response_byte_length") == 0
        )
    ]
    before = dict(
        _require_mapping(baseline["reconciliation"], name="baseline.reconciliation")
    )
    after = {
        "expected_partitions": int(before["expected_partitions"]),
        "verified": int(before["verified"]),
        "expected_market_closures": int(before["expected_market_closures"]),
        "expected_holiday_closures": counts["expected_holiday_closure"],
        "expected_special_hours_closures": counts[
            "expected_special_hours_closure"
        ],
        "missing": int(before["missing"]),
        "corrupt": int(before["corrupt"]),
        "unresolved": counts["unexplained_empty_payload"],
    }
    after["accounted_partitions"] = sum(
        after[field]
        for field in (
            "verified",
            "expected_market_closures",
            "expected_holiday_closures",
            "expected_special_hours_closures",
            "missing",
            "corrupt",
            "unresolved",
        )
    )
    after["balanced"] = after["accounted_partitions"] == after["expected_partitions"]
    integrity = _verify_post_classification_integrity(
        baseline=baseline,
        config=config,
        manifest_path=manifest_path,
        verification_report_path=verification_report_path,
        symbol=symbol,
    )
    if not integrity["passed"]:
        raise ValueError("verified-file integrity check failed after D002 classification")
    if evidence_violations:
        raise ValueError("a closure classification lacks confirmed empty evidence")
    if not after["balanced"]:
        raise ValueError("D002 reconciliation is not balanced")
    unexplained = [
        item["partition_timestamp"]
        for item in classified
        if item["classification"] == "unexplained_empty_payload"
    ]
    return {
        "audit_schema_version": AUDIT_SCHEMA_VERSION,
        "task": "D002",
        "mode": "offline_report_only",
        "manifest_mutated": False,
        "verified_bi5_files_mutated": False,
        "generated_at": format_utc(generated_at or utc_now()),
        "symbol": symbol,
        "range": {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(end),
        },
        "inputs": {
            "baseline": relative_repository_path(
                baseline_path, config.repository_root
            ),
            "verification_report": relative_repository_path(
                verification_report_path, config.repository_root
            ),
            "holiday_candidates": relative_repository_path(
                holiday_candidates_path, config.repository_root
            ),
            "calendar": relative_repository_path(
                calendar_path, config.repository_root
            ),
        },
        "candidate_count": len(classified),
        "candidate_contiguous_interval_count": len(candidate_intervals),
        "candidate_contiguous_intervals": candidate_intervals,
        "classification_counts": {
            "expected_holiday_closure": counts["expected_holiday_closure"],
            "expected_special_hours_closure": counts[
                "expected_special_hours_closure"
            ],
            "unexplained_empty_payload": counts["unexplained_empty_payload"],
        },
        "before_reconciliation": before,
        "after_reconciliation": after,
        "integrity_proof": integrity,
        "closure_without_confirmed_empty_evidence_count": len(evidence_violations),
        "closure_without_confirmed_empty_evidence": evidence_violations,
        "unexplained_timestamps": unexplained,
        "classified_intervals": _build_classified_intervals(classified),
        "partitions": classified,
    }


def render_audit_markdown(
    audit: Mapping[str, Any], calendar: Mapping[str, Any]
) -> str:
    before = _require_mapping(
        audit["before_reconciliation"], name="before reconciliation"
    )
    after = _require_mapping(
        audit["after_reconciliation"], name="after reconciliation"
    )
    counts = _require_mapping(
        audit["classification_counts"], name="classification counts"
    )
    integrity = _require_mapping(audit["integrity_proof"], name="integrity proof")
    lines = [
        "# D002 — XAUUSD Holiday and Special-Hours Calendar Research",
        "",
        f"- Generated: `{audit['generated_at']}`",
        f"- Range: `{audit['range']['start_inclusive']}` to "
        f"`{audit['range']['end_exclusive']}` (end exclusive)",
        "- Method: offline, report-only classification; no historical download",
        f"- Candidate hours: `{audit['candidate_count']}` in "
        f"`{audit['candidate_contiguous_interval_count']}` contiguous intervals",
        "",
        "## Decision",
        "",
        (
            f"`{counts['expected_holiday_closure']}` hours are supported as "
            "expected holiday closures; "
            f"`{counts['expected_special_hours_closure']}` hours are supported as "
            "expected special-hours closures; "
            f"`{counts['unexplained_empty_payload']}` remain unexplained."
        ),
        "",
        "Classification requires both an authoritative calendar match and the "
        "preserved HTTP 200, zero-byte, confirmed-empty source response. Empty data "
        "alone is never sufficient.",
        "",
        "## Before / after reconciliation",
        "",
        "| Category | Before | After |",
        "|---|---:|---:|",
        f"| expected partitions | {before['expected_partitions']} | {after['expected_partitions']} |",
        f"| verified | {before['verified']} | {after['verified']} |",
        f"| regular market closures | {before['expected_market_closures']} | {after['expected_market_closures']} |",
        f"| holiday closures | 0 | {after['expected_holiday_closures']} |",
        f"| special-hours closures | 0 | {after['expected_special_hours_closures']} |",
        f"| missing | {before['missing']} | {after['missing']} |",
        f"| corrupt | {before['corrupt']} | {after['corrupt']} |",
        f"| unresolved | {before['unresolved']} | {after['unresolved']} |",
        "",
        (
            f"`{after['expected_partitions']} = {after['verified']} verified + "
            f"{after['expected_market_closures']} regular closures + "
            f"{after['expected_holiday_closures']} holiday closures + "
            f"{after['expected_special_hours_closures']} special-hours closures + "
            f"{after['missing']} missing + {after['corrupt']} corrupt + "
            f"{after['unresolved']} unresolved`"
        ),
        "",
        f"- Balanced: `{str(after['balanced']).lower()}`",
        "",
        "## Verified-file integrity proof",
        "",
        f"- Baseline verified files: `{integrity['verified_file_count_before']}`",
        f"- Post-classification verified files: `{integrity['verified_file_count_after']}`",
        f"- Manifest unchanged: `{str(integrity['manifest_unchanged']).lower()}`",
        f"- No added verified partition: `{not integrity['verified_partitions_added']}`",
        f"- No removed verified partition/file: `{not integrity['verified_partitions_removed']}`",
        f"- No renamed verified file: `{not integrity['verified_files_renamed']}`",
        f"- No verified file-size change: `{not integrity['verified_file_sizes_changed']}`",
        f"- Every stored SHA256 matches its BI5 file: `{integrity['all_stored_sha256_match_files']}`",
        f"- No verified partition downgraded: `{not integrity['previously_verified_downgraded']}`",
        f"- Overall integrity check: `{str(integrity['passed']).lower()}`",
        "",
        "## Classification families",
        "",
        "- Holiday closures: Good Friday, Christmas/New Year, and supported U.S. "
        "national-holiday Bullion breaks.",
        "- Special-hours closures: the XAU Sunday opening/settlement hour, temporary "
        "U.S.-versus-Europe DST settlement shifts, Thanksgiving Friday, and "
        "Christmas Eve early closes.",
        "",
        "The U.S. DST notices are material: Dukascopy states that market opening and "
        "settlement follow 17:00 New York, so the temporary March and "
        "October/November hours cannot be modeled by Europe/London alone.",
        "",
        "## Classified contiguous intervals",
        "",
        "| UTC interval | Hours | Classification | Event | Confidence |",
        "|---|---:|---|---|---|",
    ]
    for interval in audit["classified_intervals"]:
        lines.append(
            f"| `{interval['start_inclusive']}` – `{interval['end_exclusive']}` "
            f"| {interval['partition_count']} | `{interval['classification']}` "
            f"| {interval['event']} | {interval['confidence']} |"
        )
    lines.extend(["", "## Authoritative sources", ""])
    for source_id, source_value in calendar["sources"].items():
        source = _require_mapping(source_value, name=source_id)
        lines.extend(
            [
                f"### `{source_id}`",
                "",
                f"- Publisher: {source['publisher']}",
                f"- Publication/date: {source['publication_date']}",
                f"- Timezone: {source['applicable_timezone']}",
                f"- Source: [{source['title']}]({source['url']})",
                f"- Support: {source['support']}",
                "",
            ]
        )
    lines.extend(["## Still unexplained", ""])
    if audit["unexplained_timestamps"]:
        lines.extend(f"- `{value}`" for value in audit["unexplained_timestamps"])
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument(
        "--manifest", default="data/manifests/XAUUSD_ticks_manifest.json"
    )
    parser.add_argument(
        "--verification-report",
        default="data/reports/dukascopy_XAUUSD_download_quality.json",
    )
    parser.add_argument(
        "--holiday-candidates",
        default=(
            "data/reports/"
            "dukascopy_XAUUSD_holiday_candidates_2021_2026.json"
        ),
    )
    parser.add_argument(
        "--baseline-output",
        default="data/reports/D002_XAUUSD_baseline_2021_2026.json",
    )
    parser.add_argument(
        "--calendar",
        default="config/dukascopy_XAUUSD_holiday_calendar.json",
    )
    parser.add_argument(
        "--audit-json",
        default="data/reports/D002_XAUUSD_holiday_special_hours_audit.json",
    )
    parser.add_argument(
        "--audit-markdown",
        default="data/reports/D002_XAUUSD_holiday_special_hours_audit.md",
    )
    parser.add_argument(
        "--unexplained-output",
        default="data/reports/D002_XAUUSD_unexplained_timestamps.json",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="create the read-only pre-classification integrity snapshot",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        baseline_path = Path(args.baseline_output)
        if args.baseline_only:
            baseline = build_baseline_snapshot(
                config=config,
                symbol=args.symbol,
                manifest_path=Path(args.manifest),
                verification_report_path=Path(args.verification_report),
                holiday_candidates_path=Path(args.holiday_candidates),
            )
            atomic_write_json(baseline_path, baseline)
            print(
                "baseline: "
                f"expected={baseline['expected_partition_count']} "
                f"verified={baseline['verified_partition_count']} "
                f"unresolved={baseline['unresolved_partition_count']} "
                "verified_hashes_match=true"
            )
            print(f"baseline_output={baseline_path}")
            return 0
        if not baseline_path.is_file():
            raise ValueError(
                "D002 baseline snapshot is required; run with --baseline-only first"
            )
        calendar_path = Path(args.calendar)
        audit = build_d002_audit(
            config=config,
            symbol=args.symbol,
            baseline_path=baseline_path,
            manifest_path=Path(args.manifest),
            verification_report_path=Path(args.verification_report),
            holiday_candidates_path=Path(args.holiday_candidates),
            calendar_path=calendar_path,
        )
        audit_json_path = Path(args.audit_json)
        audit_markdown_path = Path(args.audit_markdown)
        unexplained_path = Path(args.unexplained_output)
        calendar = _require_mapping(
            _read_json(calendar_path), name="holiday calendar"
        )
        atomic_write_json(audit_json_path, audit)
        atomic_write_bytes(
            audit_markdown_path, render_audit_markdown(audit, calendar).encode("utf-8")
        )
        atomic_write_json(
            unexplained_path,
            {
                "report_schema_version": 1,
                "task": "D002",
                "generated_at": audit["generated_at"],
                "symbol": audit["symbol"],
                "range": audit["range"],
                "classification": "unexplained_empty_payload",
                "count": len(audit["unexplained_timestamps"]),
                "timestamps": audit["unexplained_timestamps"],
            },
        )
        counts = audit["classification_counts"]
        after = audit["after_reconciliation"]
        print(
            "classification: "
            f"holiday={counts['expected_holiday_closure']} "
            f"special_hours={counts['expected_special_hours_closure']} "
            f"unexplained={counts['unexplained_empty_payload']}"
        )
        print(
            "reconciliation: "
            f"expected={after['expected_partitions']} "
            f"verified={after['verified']} "
            f"regular_closures={after['expected_market_closures']} "
            f"holiday_closures={after['expected_holiday_closures']} "
            f"special_hours_closures={after['expected_special_hours_closures']} "
            f"missing={after['missing']} corrupt={after['corrupt']} "
            f"unresolved={after['unresolved']} "
            f"balanced={str(after['balanced']).lower()}"
        )
        print(
            "integrity: "
            f"passed={str(audit['integrity_proof']['passed']).lower()} "
            f"manifest_unchanged="
            f"{str(audit['integrity_proof']['manifest_unchanged']).lower()} "
            "verified_hashes_match="
            f"{str(audit['integrity_proof']['all_stored_sha256_match_files']).lower()}"
        )
        print(f"audit_json={audit_json_path}")
        print(f"audit_markdown={audit_markdown_path}")
        print(f"unexplained_output={unexplained_path}")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
