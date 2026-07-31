#!/usr/bin/env python3
"""Verify Dukascopy raw archives and produce JSON/Markdown quality reports."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.dukascopy_common import (
        DuplicateManifestKeyError,
        EmptyPayloadError,
        MalformedPayloadError,
        Manifest,
        Partition,
        PipelineConfig,
        PlaceholderPayloadError,
        atomic_write_bytes,
        atomic_write_json,
        expected_closure_rule,
        format_utc,
        generate_partitions,
        load_config,
        manifest_file_hash,
        manifest_no_data_evidence,
        parse_utc_boundary,
        partition_file_path,
        resolve_manifest_file_path,
        sha256_file,
        utc_now,
        validate_bi5_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from dukascopy_common import (  # type: ignore
        DuplicateManifestKeyError,
        EmptyPayloadError,
        MalformedPayloadError,
        Manifest,
        Partition,
        PipelineConfig,
        PlaceholderPayloadError,
        atomic_write_bytes,
        atomic_write_json,
        expected_closure_rule,
        format_utc,
        generate_partitions,
        load_config,
        manifest_file_hash,
        manifest_no_data_evidence,
        parse_utc_boundary,
        partition_file_path,
        resolve_manifest_file_path,
        sha256_file,
        utc_now,
        validate_bi5_file,
    )


CLASSIFICATIONS = (
    "verified_data",
    "expected_market_closure",
    "missing_partition",
    "corrupt_partition",
    "malformed_payload",
    "unresolved_status",
)


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def classify_partition(
    *,
    config: PipelineConfig,
    manifest: Manifest,
    raw_root: Path,
    symbol: str,
    partition: Partition,
) -> dict[str, Any]:
    entry = manifest.get(partition)
    expected_path = partition_file_path(raw_root, symbol, partition)
    manifest_path = resolve_manifest_file_path(
        (entry or {}).get("file_path"), repository_root=config.repository_root
    )
    candidate = expected_path
    closure_rule = expected_closure_rule(config, partition, symbol=symbol)
    closure_evidence = manifest_no_data_evidence(entry)
    manifest_status = (entry or {}).get("status")

    result: dict[str, Any] = {
        "partition_timestamp": partition.key,
        "classification": None,
        "file_path": (entry or {}).get("file_path"),
        "manifest_status": manifest_status,
        "manifest_retry_count": (entry or {}).get("retry_count"),
        "manifest_sha256": (entry or {}).get("sha256"),
        "source_evidence_kind": (entry or {}).get("evidence_kind"),
        "http_status": (entry or {}).get("http_status"),
        "response_byte_length": (entry or {}).get("response_byte_length"),
        "proxy_identity_masked": (entry or {}).get("proxy_identity_masked"),
        "final_attempt_timestamp": (entry or {}).get(
            "final_attempt_timestamp"
        ),
        "computed_sha256": None,
        "byte_size": None,
        "record_count": None,
        "closure_rule_matched": closure_rule is not None,
        "closure_rule": closure_rule,
        "closure_evidence": None,
        "details": None,
    }

    if entry is not None and entry.get("partition_timestamp") != partition.key:
        result.update(
            classification="unresolved_status",
            details=(
                "manifest partition_timestamp does not match its hourly key: "
                f"{entry.get('partition_timestamp')!r}"
            ),
        )
        return result

    if manifest_path is not None and not _same_path(manifest_path, expected_path):
        result.update(
            classification="unresolved_status",
            details=(
                "manifest file_path does not match the expected hourly path: "
                f"{manifest_path}"
            ),
        )
        return result

    if candidate.is_file():
        result["byte_size"] = candidate.stat().st_size
        checksum = sha256_file(candidate)
        result["computed_sha256"] = checksum
        manifest_checksum = (entry or {}).get("sha256")
        if manifest_checksum is not None and checksum != manifest_checksum:
            result.update(
                classification="corrupt_partition",
                details="computed SHA-256 does not match the manifest",
            )
            return result
        try:
            rows = validate_bi5_file(
                candidate,
                max_compressed_bytes=int(config.download["max_compressed_bytes"]),
            )
        except EmptyPayloadError as exc:
            if closure_rule is not None and closure_evidence is not None:
                result.update(
                    classification="expected_market_closure",
                    closure_evidence=closure_evidence,
                    details=(
                        f"{closure_rule['rule_id']} matched and the manifest records "
                        f"source no-data evidence {closure_evidence}"
                    ),
                )
            else:
                result.update(
                    classification="malformed_payload",
                    details=(
                        f"{type(exc).__name__}: {exc}; an empty file alone does not "
                        "establish an expected closure"
                    ),
                )
            return result
        except (MalformedPayloadError, PlaceholderPayloadError) as exc:
            result.update(
                classification="malformed_payload",
                details=f"{type(exc).__name__}: {exc}",
            )
            return result
        if entry and manifest_status == "verified":
            if manifest_path is None:
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details="verified manifest entry has no file_path",
                )
                return result
            if not isinstance(entry.get("sha256"), str) or not entry["sha256"]:
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details="verified manifest entry has no SHA-256",
                )
                return result
            manifest_size = entry.get("byte_size")
            if not _is_nonnegative_int(manifest_size):
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details="verified manifest byte_size is not a non-negative integer",
                )
                return result
            if manifest_size != result["byte_size"]:
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details=(
                        f"manifest byte_size {manifest_size} does not match file size "
                        f"{result['byte_size']}"
                    ),
                )
                return result
            manifest_rows = entry.get("record_count")
            if not _is_nonnegative_int(manifest_rows):
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details=(
                        "verified manifest record_count is not a plausible "
                        "non-negative integer"
                    ),
                )
                return result
            if manifest_rows != rows:
                result.update(
                    classification="unresolved_status",
                    record_count=rows,
                    details=(
                        f"manifest record_count {manifest_rows} does not match "
                        f"decoded count {rows}"
                    ),
                )
                return result
            result.update(
                classification="verified_data",
                record_count=rows,
                details=(
                    "verified data conflicts with a configured closure rule"
                    if closure_rule is not None
                    else "checksum and BI5 payload verified"
                ),
            )
            return result
        result.update(
            classification="unresolved_status",
            record_count=rows,
            details=(
                "valid raw file is not accepted; manifest status is "
                f"{manifest_status!r}"
            ),
        )
        return result

    if entry and manifest_status == "verified":
        result.update(
            classification="missing_partition",
            details="manifest says verified but the raw file is unavailable",
        )
        return result

    if closure_rule is not None and closure_evidence is not None:
        result.update(
            classification="expected_market_closure",
            closure_evidence=closure_evidence,
            details=(
                f"{closure_rule['rule_id']} matched with no-data evidence "
                f"{closure_evidence}"
            ),
        )
        return result

    if entry is None:
        result.update(
            classification="missing_partition",
            details="no manifest record or raw file",
        )
        return result

    if manifest_status in {
        "failed",
        "unresolved",
        "malformed_payload",
        "corrupt",
        "no_data",
        "no-data",
        "expected_market_closure",
    }:
        result.update(
            classification="unresolved_status",
            details=entry.get("error_details") or f"manifest status is {entry.get('status')}",
        )
        return result

    result.update(
        classification="missing_partition",
        details=f"manifest status {manifest_status!r} has no raw file",
    )
    return result


def _manifest_structure_errors(manifest: Manifest) -> list[dict[str, Any]]:
    """Detect duplicate logical entries that JSON object keys cannot express."""

    errors: list[dict[str, Any]] = []
    seen_timestamps: dict[str, str] = {}
    if not isinstance(manifest.entries, dict):
        return [
            {
                "type": "invalid_partitions_container",
                "details": "manifest partitions must be a JSON object",
            }
        ]
    for key, entry in manifest.entries.items():
        if not isinstance(entry, Mapping):
            errors.append(
                {
                    "type": "invalid_partition_entry",
                    "manifest_key": key,
                    "details": "manifest partition entry must be a JSON object",
                }
            )
            continue
        declared = entry.get("partition_timestamp")
        if not isinstance(declared, str):
            continue
        previous = seen_timestamps.get(declared)
        if previous is not None and previous != key:
            errors.append(
                {
                    "type": "duplicate_partition_timestamp",
                    "partition_timestamp": declared,
                    "manifest_keys": [previous, key],
                    "details": (
                        "multiple manifest entries declare the same hourly partition"
                    ),
                }
            )
        else:
            seen_timestamps[declared] = key
    return errors


def _unresolved_manifest_details(
    partitions: list[Partition],
    *,
    reason: str,
) -> list[dict[str, Any]]:
    return [
        {
            "partition_timestamp": partition.key,
            "classification": "unresolved_status",
            "file_path": None,
            "manifest_status": None,
            "manifest_retry_count": None,
            "manifest_sha256": None,
            "source_evidence_kind": None,
            "http_status": None,
            "response_byte_length": None,
            "proxy_identity_masked": None,
            "final_attempt_timestamp": None,
            "computed_sha256": None,
            "byte_size": None,
            "record_count": None,
            "closure_rule_matched": False,
            "closure_rule": None,
            "closure_evidence": None,
            "details": reason,
        }
        for partition in partitions
    ]


def _blocking_error_kind(item: Mapping[str, Any]) -> str:
    classification = str(item["classification"])
    if classification == "missing_partition":
        return "missing_file_or_manifest"
    if classification == "corrupt_partition":
        return "checksum_mismatch"
    if classification == "malformed_payload":
        return "malformed_or_decode_failure"
    details = str(item.get("details") or "").lower()
    status = str(item.get("manifest_status") or "").lower()
    source_evidence_kind = str(item.get("source_evidence_kind") or "")
    if source_evidence_kind == "confirmed_empty_payload":
        return "empty_payload_open_market"
    if source_evidence_kind == "http_error":
        http_status = item.get("http_status")
        return f"http_{http_status}" if http_status is not None else "http_error"
    if source_evidence_kind in {
        "proxy_failure",
        "timeout",
        "tls_ssl_failure",
        "connection_reset",
        "network_failure",
        "content_length_mismatch",
        "malformed_non_empty_payload",
        "local_io_failure",
        "decode_or_value_failure",
    }:
        return source_evidence_kind
    if "duplicate" in details or "manifest rejected" in details:
        return "manifest_integrity_error"
    if status == "expected_market_closure":
        return "ambiguous_closure_evidence"
    if details.startswith("empty_payload:"):
        return "empty_payload_open_market"
    if "http 429" in details:
        return "http_429"
    if "http 5" in details:
        return "http_5xx"
    if "timeout" in details or "timed out" in details:
        return "timeout"
    if "proxy" in details:
        return "proxy_error"
    if "ssl" in details or "tls" in details:
        return "tls_ssl_error"
    if "connection" in details or "streamreset" in details or "stream reset" in details:
        return "connection_error"
    if "decode" in details or "lzma" in details:
        return "decode_error"
    return f"manifest_status_{status or 'unknown'}"


def _build_reclassification_audit(
    details: list[dict[str, Any]],
) -> dict[str, Any]:
    reclassified = [
        item["partition_timestamp"]
        for item in details
        if item["classification"] == "expected_market_closure"
        and item.get("closure_evidence") == "empty_payload"
        and item.get("manifest_status") in {"failed", "unresolved"}
    ]
    empty_payload_entries = [
        item["partition_timestamp"]
        for item in details
        if item.get("closure_evidence") == "empty_payload"
        or str(item.get("details") or "").lower().startswith("empty_payload:")
    ]
    grouped: dict[str, list[str]] = {}
    for item in details:
        if item["classification"] in {
            "verified_data",
            "expected_market_closure",
        }:
            continue
        grouped.setdefault(_blocking_error_kind(item), []).append(
            item["partition_timestamp"]
        )
    return {
        "mode": "offline_report_only",
        "manifest_mutated": False,
        "empty_payload_entries_evaluated": len(empty_payload_entries),
        "reclassified_from_unresolved_to_expected_market_closure": len(
            reclassified
        ),
        "reclassified_partition_timestamps": reclassified,
        "remaining_blocking_partitions": sum(len(items) for items in grouped.values()),
        "remaining_unresolved_by_error_kind": dict(sorted(grouped.items())),
    }


def _build_report(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    manifest_path: Path,
    partitions: list[Partition],
    details: list[dict[str, Any]],
    generated_at: datetime | None,
    manifest_errors: list[dict[str, Any]],
    reclassification_audit: bool,
) -> dict[str, Any]:
    counts = {
        classification: sum(
            item["classification"] == classification for item in details
        )
        for classification in CLASSIFICATIONS
    }
    reconciliation = {
        "expected_partitions": len(partitions),
        "verified": counts["verified_data"],
        "expected_market_closures": counts["expected_market_closure"],
        "missing": counts["missing_partition"],
        "corrupt": counts["corrupt_partition"] + counts["malformed_payload"],
        "unresolved": counts["unresolved_status"],
    }
    reconciliation["accounted_partitions"] = sum(
        reconciliation[name]
        for name in (
            "verified",
            "expected_market_closures",
            "missing",
            "corrupt",
            "unresolved",
        )
    )
    reconciliation["balanced"] = (
        reconciliation["accounted_partitions"]
        == reconciliation["expected_partitions"]
    )
    blocking_total = (
        reconciliation["missing"]
        + reconciliation["corrupt"]
        + reconciliation["unresolved"]
    )
    report = {
        "report_schema_version": 1,
        "generated_at": format_utc(generated_at or utc_now()),
        "symbol": symbol,
        "archive_symbol": config.symbol(symbol).archive_symbol,
        "source": config.source["id"],
        "timezone": "UTC",
        "range": {
            "start_inclusive": format_utc(start),
            "end_exclusive": format_utc(end),
        },
        "manifest_path": str(manifest_path),
        "manifest_sha256": (
            manifest_file_hash(manifest_path) if manifest_path.exists() else None
        ),
        "manifest_errors": manifest_errors,
        "closure_rules": {
            "closure_timezone": config.partition_rules.get(
                "closure_timezone", "UTC"
            ),
            "full_day_closed_weekdays": config.partition_rules.get(
                "full_day_closed_weekdays", []
            ),
            "explicit_closed_dates": config.partition_rules.get(
                "explicit_closed_dates", []
            ),
            "closed_utc_hours_by_weekday": config.partition_rules.get(
                "closed_utc_hours_by_weekday", {}
            ),
            "symbol_market_calendars": config.partition_rules.get(
                "symbol_market_calendars", {}
            ),
        },
        "counts": {
            **counts,
            "expected_partitions": len(partitions),
            "unresolved": blocking_total,
        },
        "reconciliation": reconciliation,
        "partitions": details,
    }
    if reclassification_audit:
        report["reclassification_audit"] = _build_reclassification_audit(
            details
        )
    return report


def verify_range(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    manifest_path: Path,
    generated_at: datetime | None = None,
    reclassification_audit: bool = False,
) -> dict[str, Any]:
    symbol = symbol.upper()
    partitions = generate_partitions(start, end)
    manifest_errors: list[dict[str, Any]] = []
    try:
        manifest = Manifest(manifest_path, config=config, symbol=symbol)
    except DuplicateManifestKeyError as exc:
        manifest_errors.append(
            {
                "type": "duplicate_json_key",
                "key": exc.key,
                "details": str(exc),
            }
        )
        details = _unresolved_manifest_details(
            partitions,
            reason=f"manifest rejected: {exc}",
        )
        return _build_report(
            config=config,
            symbol=symbol,
            start=start,
            end=end,
            manifest_path=manifest_path,
            partitions=partitions,
            details=details,
            generated_at=generated_at,
            manifest_errors=manifest_errors,
            reclassification_audit=reclassification_audit,
        )

    manifest_errors = _manifest_structure_errors(manifest)
    if manifest_errors:
        details = _unresolved_manifest_details(
            partitions,
            reason="manifest rejected because duplicate or invalid entries were detected",
        )
        return _build_report(
            config=config,
            symbol=symbol,
            start=start,
            end=end,
            manifest_path=manifest_path,
            partitions=partitions,
            details=details,
            generated_at=generated_at,
            manifest_errors=manifest_errors,
            reclassification_audit=reclassification_audit,
        )

    details = [
        classify_partition(
            config=config,
            manifest=manifest,
            raw_root=raw_root,
            symbol=symbol,
            partition=partition,
        )
        for partition in partitions
    ]
    return _build_report(
        config=config,
        symbol=symbol,
        start=start,
        end=end,
        manifest_path=manifest_path,
        partitions=partitions,
        details=details,
        generated_at=generated_at,
        manifest_errors=manifest_errors,
        reclassification_audit=reclassification_audit,
    )


def build_holiday_candidates_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Extract confirmed empty open-hour responses for special-hours research."""

    candidates = [
        {
            "partition_timestamp": item["partition_timestamp"],
            "evidence_kind": item.get("source_evidence_kind")
            or "confirmed_empty_payload",
            "http_status": item.get("http_status"),
            "response_byte_length": item.get("response_byte_length"),
            "retry_count": item.get("manifest_retry_count"),
            "proxy_identity_masked": item.get("proxy_identity_masked"),
            "final_attempt_timestamp": item.get("final_attempt_timestamp"),
            "details": item.get("details"),
        }
        for item in report["partitions"]
        if item["classification"] == "unresolved_status"
        and _blocking_error_kind(item) == "empty_payload_open_market"
    ]
    return {
        "report_schema_version": 1,
        "generated_at": report["generated_at"],
        "symbol": report["symbol"],
        "range": report["range"],
        "calendar": report["closure_rules"].get("symbol_market_calendars", {}).get(
            report["symbol"]
        ),
        "evidence_policy": (
            "confirmed empty payload outside the regular weekly/daily calendar; "
            "not classified as a closure"
        ),
        "count": len(candidates),
        "candidates": candidates,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    reconciliation = report["reconciliation"]
    lines = [
        f"# Dukascopy Download Quality — {report['symbol']}",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Source: `{report['source']}`",
        f"- Coverage request: `{report['range']['start_inclusive']}` to "
        f"`{report['range']['end_exclusive']}` (end exclusive)",
        f"- Manifest SHA-256: `{report['manifest_sha256']}`",
        "",
        "## Classification Summary",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    for classification in CLASSIFICATIONS:
        lines.append(f"| {classification.replace('_', ' ')} | {counts[classification]} |")
    lines.extend(
        [
            f"| **unresolved total** | **{counts['unresolved']}** |",
            "",
            "## Coverage Reconciliation",
            "",
            (
                f"`{reconciliation['expected_partitions']} expected = "
                f"{reconciliation['verified']} verified + "
                f"{reconciliation['expected_market_closures']} expected market "
                f"closures + {reconciliation['missing']} missing + "
                f"{reconciliation['corrupt']} corrupt + "
                f"{reconciliation['unresolved']} unresolved`"
            ),
            "",
            f"- Accounted partitions: `{reconciliation['accounted_partitions']}`",
            f"- Balanced: `{str(reconciliation['balanced']).lower()}`",
            "",
            "A market closure is reported only when an explicit versioned calendar rule "
            "matches and the manifest preserves affirmative empty-response or explicit "
            "no-data evidence. A missing file or manifest entry is not closure evidence. "
            "HTTP, timeout, proxy, decode, and other source failures never establish a "
            "closure.",
            "",
            "## Non-verified Partitions",
            "",
            "| Partition (UTC) | Classification | Manifest status | Details |",
            "|---|---|---|---|",
        ]
    )
    non_verified = [
        item for item in report["partitions"] if item["classification"] != "verified_data"
    ]
    if non_verified:
        for item in non_verified:
            details = str(item.get("details") or "").replace("|", "\\|")
            lines.append(
                f"| {item['partition_timestamp']} | {item['classification']} | "
                f"{item.get('manifest_status') or ''} | {details} |"
            )
    else:
        lines.append("| — | — | — | All expected partitions contain verified data. |")
    audit = report.get("reclassification_audit")
    if audit:
        lines.extend(
            [
                "",
                "## Offline Empty-Payload Reclassification Audit",
                "",
                "- Manifest mutated: `false`",
                (
                    "- Empty-payload entries evaluated: "
                    f"`{audit['empty_payload_entries_evaluated']}`"
                ),
                (
                    "- Reclassified from unresolved to expected market closure: "
                    f"`{audit['reclassified_from_unresolved_to_expected_market_closure']}`"
                ),
                (
                    "- Remaining blocking partitions: "
                    f"`{audit['remaining_blocking_partitions']}`"
                ),
            ]
        )
        for error_kind, timestamps in audit[
            "remaining_unresolved_by_error_kind"
        ].items():
            lines.extend(["", f"### `{error_kind}` ({len(timestamps)})", ""])
            lines.extend(f"- `{timestamp}`" for timestamp in timestamps)
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="inclusive UTC date/hour")
    parser.add_argument("--end", required=True, help="exclusive UTC date/hour")
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument("--raw-root")
    parser.add_argument("--manifest")
    parser.add_argument("--json-report")
    parser.add_argument("--markdown-report")
    parser.add_argument(
        "--holiday-candidates-report",
        help=(
            "write a separate JSON list of confirmed empty responses outside "
            "the regular market calendar"
        ),
    )
    parser.add_argument(
        "--reclassify-empty-closures",
        action="store_true",
        help=(
            "produce an offline, report-only audit of existing empty_payload "
            "entries; never writes the manifest or downloads data"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        symbol = args.symbol.upper()
        start = parse_utc_boundary(args.start)
        end = parse_utc_boundary(args.end)
        raw_root = Path(args.raw_root) if args.raw_root else config.path_for("raw_root")
        manifest_path = (
            Path(args.manifest)
            if args.manifest
            else config.path_for("manifests_root") / f"{symbol}_ticks_manifest.json"
        )
        reports_root = config.path_for("reports_root")
        json_path = (
            Path(args.json_report)
            if args.json_report
            else reports_root / f"dukascopy_{symbol}_download_quality.json"
        )
        markdown_path = (
            Path(args.markdown_report)
            if args.markdown_report
            else reports_root / f"dukascopy_{symbol}_download_quality.md"
        )
        report = verify_range(
            config=config,
            symbol=symbol,
            start=start,
            end=end,
            raw_root=raw_root,
            manifest_path=manifest_path,
            reclassification_audit=args.reclassify_empty_closures,
        )
        atomic_write_json(json_path, report)
        atomic_write_bytes(markdown_path, render_markdown(report).encode("utf-8"))
        if args.holiday_candidates_report:
            atomic_write_json(
                Path(args.holiday_candidates_report),
                build_holiday_candidates_report(report),
            )
        print(
            f"verified={report['counts']['verified_data']} "
            f"closures={report['counts']['expected_market_closure']} "
            f"unresolved={report['counts']['unresolved']}"
        )
        reconciliation = report["reconciliation"]
        print(
            "reconciliation: "
            f"expected_partitions={reconciliation['expected_partitions']} = "
            f"verified={reconciliation['verified']} + "
            "expected_market_closures="
            f"{reconciliation['expected_market_closures']} + "
            f"missing={reconciliation['missing']} + "
            f"corrupt={reconciliation['corrupt']} + "
            f"unresolved={reconciliation['unresolved']}; "
            f"accounted={reconciliation['accounted_partitions']} "
            f"balanced={str(reconciliation['balanced']).lower()}"
        )
        print(f"json_report={json_path}")
        print(f"markdown_report={markdown_path}")
        if args.holiday_candidates_report:
            print(f"holiday_candidates_report={args.holiday_candidates_report}")
        if args.reclassify_empty_closures:
            audit = report["reclassification_audit"]
            print(
                "reclassification: "
                "mode=offline_report_only "
                "manifest_mutated=false "
                "from_unresolved_to_expected_market_closure="
                f"{audit['reclassified_from_unresolved_to_expected_market_closure']} "
                f"remaining_blocking={audit['remaining_blocking_partitions']}"
            )
        return (
            0
            if reconciliation["balanced"]
            and reconciliation["missing"] == 0
            and reconciliation["corrupt"] == 0
            and reconciliation["unresolved"] == 0
            else 2
        )
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
