#!/usr/bin/env python3
"""Verify Dukascopy raw archives and produce JSON/Markdown quality reports."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.dukascopy_common import (
        EmptyPayloadError,
        MalformedPayloadError,
        Manifest,
        Partition,
        PipelineConfig,
        PlaceholderPayloadError,
        atomic_write_bytes,
        atomic_write_json,
        format_utc,
        generate_partitions,
        is_expected_closure,
        load_config,
        manifest_file_hash,
        parse_utc_boundary,
        partition_file_path,
        resolve_manifest_file_path,
        sha256_file,
        utc_now,
        validate_bi5_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from dukascopy_common import (  # type: ignore
        EmptyPayloadError,
        MalformedPayloadError,
        Manifest,
        Partition,
        PipelineConfig,
        PlaceholderPayloadError,
        atomic_write_bytes,
        atomic_write_json,
        format_utc,
        generate_partitions,
        is_expected_closure,
        load_config,
        manifest_file_hash,
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
    candidate = manifest_path or expected_path
    closure = is_expected_closure(config, partition)

    result: dict[str, Any] = {
        "partition_timestamp": partition.key,
        "classification": None,
        "file_path": (entry or {}).get("file_path"),
        "manifest_status": (entry or {}).get("status"),
        "manifest_sha256": (entry or {}).get("sha256"),
        "computed_sha256": None,
        "byte_size": None,
        "record_count": None,
        "closure_rule_matched": closure,
        "details": None,
    }

    # Available verified data wins over a closure rule, exposing rule conflicts.
    if entry and entry.get("status") == "verified":
        if not candidate.is_file():
            result.update(
                classification="missing_partition",
                details="manifest says verified but the raw file is unavailable",
            )
            return result
        result["byte_size"] = candidate.stat().st_size
        checksum = sha256_file(candidate)
        result["computed_sha256"] = checksum
        if checksum != entry.get("sha256"):
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
        except (EmptyPayloadError, MalformedPayloadError, PlaceholderPayloadError) as exc:
            result.update(
                classification="malformed_payload",
                details=f"{type(exc).__name__}: {exc}",
            )
            return result
        result.update(
            classification="verified_data",
            record_count=rows,
            details=(
                "verified data conflicts with a configured closure rule"
                if closure
                else "checksum and BI5 payload verified"
            ),
        )
        return result

    if closure:
        if candidate.is_file():
            result.update(
                classification="unresolved_status",
                byte_size=candidate.stat().st_size,
                details="configured closure has an unverified raw file",
            )
        else:
            result.update(
                classification="expected_market_closure",
                details="matched explicit configured UTC closure rule",
            )
        return result

    if entry is None:
        if expected_path.is_file():
            result.update(
                classification="unresolved_status",
                byte_size=expected_path.stat().st_size,
                details="raw file exists without a manifest record",
            )
        else:
            result.update(
                classification="missing_partition",
                details="no manifest record or raw file",
            )
        return result

    if not candidate.is_file():
        if entry.get("status") in {"failed", "unresolved", "malformed_payload", "corrupt"}:
            result.update(
                classification="unresolved_status",
                details=entry.get("error_details") or f"manifest status is {entry.get('status')}",
            )
        else:
            result.update(
                classification="missing_partition",
                details=f"manifest status {entry.get('status')!r} has no raw file",
            )
        return result

    result.update(
        classification="unresolved_status",
        byte_size=candidate.stat().st_size,
        details=f"raw file is not accepted; manifest status is {entry.get('status')!r}",
    )
    return result


def verify_range(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    manifest_path: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    partitions = generate_partitions(start, end)
    manifest = Manifest(manifest_path, config=config, symbol=symbol)
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
    counts = {
        classification: sum(
            item["classification"] == classification for item in details
        )
        for classification in CLASSIFICATIONS
    }
    unresolved = sum(
        counts[name]
        for name in (
            "missing_partition",
            "corrupt_partition",
            "malformed_payload",
            "unresolved_status",
        )
    )
    return {
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
        "manifest_sha256": manifest_file_hash(manifest_path) if manifest_path.exists() else None,
        "closure_rules": {
            "closure_timezone": config.partition_rules.get("closure_timezone", "UTC"),
            "full_day_closed_weekdays": config.partition_rules.get(
                "full_day_closed_weekdays", []
            ),
            "explicit_closed_dates": config.partition_rules.get(
                "explicit_closed_dates", []
            ),
            "closed_utc_hours_by_weekday": config.partition_rules.get(
                "closed_utc_hours_by_weekday", {}
            ),
        },
        "counts": {**counts, "expected_partitions": len(partitions), "unresolved": unresolved},
        "partitions": details,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
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
            "A market closure is reported only when an explicit UTC calendar rule in the "
            "versioned configuration matches. HTTP failures never establish a closure.",
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
        )
        atomic_write_json(json_path, report)
        atomic_write_bytes(markdown_path, render_markdown(report).encode("utf-8"))
        print(
            f"verified={report['counts']['verified_data']} "
            f"closures={report['counts']['expected_market_closure']} "
            f"unresolved={report['counts']['unresolved']}"
        )
        print(f"json_report={json_path}")
        print(f"markdown_report={markdown_path}")
        return 0 if report["counts"]["unresolved"] == 0 else 2
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
