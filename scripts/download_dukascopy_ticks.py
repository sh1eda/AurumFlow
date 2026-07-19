#!/usr/bin/env python3
"""Resumable downloader for native hourly Dukascopy BI5 tick partitions."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import email.utils
from pathlib import Path
import sys
import time
from typing import Any, Callable, Protocol

import httpx

try:
    from scripts.dukascopy_common import (
        EmptyPayloadError,
        Manifest,
        Partition,
        PayloadValidationError,
        PipelineConfig,
        StructuredLogger,
        atomic_write_bytes,
        format_utc,
        generate_partitions,
        inspect_bi5_payload,
        is_expected_closure,
        load_config,
        manifest_no_data_evidence,
        parse_utc_boundary,
        partition_file_path,
        partition_url,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_bytes,
        sha256_file,
        utc_now,
        validate_bi5_file,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    from dukascopy_common import (  # type: ignore
        EmptyPayloadError,
        Manifest,
        Partition,
        PayloadValidationError,
        PipelineConfig,
        StructuredLogger,
        atomic_write_bytes,
        format_utc,
        generate_partitions,
        inspect_bi5_payload,
        is_expected_closure,
        load_config,
        manifest_no_data_evidence,
        parse_utc_boundary,
        partition_file_path,
        partition_url,
        relative_repository_path,
        resolve_manifest_file_path,
        sha256_bytes,
        sha256_file,
        utc_now,
        validate_bi5_file,
    )


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    headers: dict[str, str]


class Transport(Protocol):
    def fetch(self, url: str, *, timeout: float, headers: dict[str, str]) -> HttpResult:
        ...


class SourceRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


class HttpxTransport:
    """Persistent HTTP/2 transport for efficient sequential archive requests."""

    def __init__(self) -> None:
        self._client = httpx.Client(http2=True, follow_redirects=True)

    def fetch(self, url: str, *, timeout: float, headers: dict[str, str]) -> HttpResult:
        try:
            response = self._client.get(url, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise SourceRequestError(f"network request timed out: {exc}", retryable=True) from exc
        except httpx.TransportError as exc:
            raise SourceRequestError(
                f"network request failed: {exc}", retryable=True
            ) from exc
        return HttpResult(
            status=response.status_code,
            body=response.content,
            headers={key.lower(): value for key, value in response.headers.items()},
        )

    def close(self) -> None:
        self._client.close()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, parsed.timestamp() - time.time())


def fetch_with_retry(
    url: str,
    *,
    transport: Transport,
    timeout: float,
    user_agent: str,
    max_attempts: int,
    backoff_initial: float,
    backoff_max: float,
    throttle: float,
    sleep: Callable[[float], None],
    logger: StructuredLogger,
    partition: Partition,
) -> tuple[HttpResult, int]:
    """Fetch a partition, retrying only failures classified as transient."""

    last_error: SourceRequestError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = transport.fetch(
                url,
                timeout=timeout,
                headers={"User-Agent": user_agent, "Accept": "application/octet-stream"},
            )
            if result.status != 200:
                retry_after = _parse_retry_after(result.headers.get("retry-after"))
                detail = result.body[:256].decode("utf-8", errors="replace").strip()
                suffix = f": {detail}" if detail else ""
                raise SourceRequestError(
                    f"HTTP {result.status}{suffix}",
                    retryable=result.status in {408, 425, 429} or result.status >= 500,
                    status=result.status,
                    retry_after=retry_after,
                )
            content_length = result.headers.get("content-length")
            if content_length is not None and int(content_length) != len(result.body):
                raise SourceRequestError(
                    f"Content-Length {content_length} does not match {len(result.body)} bytes",
                    retryable=True,
                    status=result.status,
                )
            if throttle > 0:
                sleep(throttle)
            return result, attempt - 1
        except SourceRequestError as exc:
            last_error = exc
            if not exc.retryable or attempt == max_attempts:
                raise
            delay = min(backoff_max, backoff_initial * (2 ** (attempt - 1)))
            if exc.retry_after is not None:
                delay = max(delay, exc.retry_after)
            logger.emit(
                "warning",
                "download_retry",
                partition=partition.key,
                attempt=attempt,
                delay_seconds=delay,
                error=str(exc),
            )
            sleep(delay)
    assert last_error is not None  # defensive: max_attempts is validated by caller
    raise last_error


def _manifest_entry(
    *,
    config: PipelineConfig,
    symbol: str,
    partition: Partition,
    url: str,
    file_path: Path | None,
    byte_size: int | None,
    checksum: str | None,
    status: str,
    retry_count: int,
    error_details: str | None,
    download_timestamp: str | None,
    record_count: int | None = None,
) -> dict[str, Any]:
    return {
        "archive_symbol": config.symbol(symbol).archive_symbol,
        "source": config.source["id"],
        "source_url": url,
        "download_timestamp": download_timestamp,
        "file_path": (
            relative_repository_path(file_path, config.repository_root)
            if file_path is not None
            else None
        ),
        "byte_size": byte_size,
        "sha256": checksum,
        "status": status,
        "retry_count": retry_count,
        "error_details": error_details,
        "record_count": record_count,
    }


def _entry_is_verified(
    entry: dict[str, Any] | None,
    *,
    config: PipelineConfig,
) -> tuple[bool, str | None]:
    if not entry or entry.get("status") != "verified":
        return False, None
    path = resolve_manifest_file_path(
        entry.get("file_path"), repository_root=config.repository_root
    )
    if path is None or not path.is_file():
        return False, "verified manifest entry has no available file"
    checksum = sha256_file(path)
    if checksum != entry.get("sha256"):
        return False, "verified file checksum no longer matches manifest"
    try:
        validate_bi5_file(
            path,
            max_compressed_bytes=int(config.download["max_compressed_bytes"]),
        )
    except PayloadValidationError as exc:
        return False, f"verified file no longer validates: {exc}"
    return True, None


def _selected_for_mode(
    mode: str, entry: dict[str, Any] | None, file_path: Path
) -> bool:
    if mode == "all":
        return True
    status = entry.get("status") if entry else None
    if mode == "failed":
        return status in {"failed", "corrupt", "malformed_payload", "unresolved"}
    if mode == "missing":
        return entry is None or status == "missing" or not file_path.exists()
    if mode == "failed-or-missing":
        return _selected_for_mode("failed", entry, file_path) or _selected_for_mode(
            "missing", entry, file_path
        )
    raise ValueError(f"unsupported selection mode {mode}")


def _count_unresolved(
    *,
    config: PipelineConfig,
    manifest: Manifest,
    partitions: list[Partition],
) -> int:
    unresolved = 0
    for partition in partitions:
        entry = manifest.get(partition)
        if is_expected_closure(
            config, partition, symbol=manifest.symbol
        ) and manifest_no_data_evidence(entry) is not None:
            continue
        valid, _error = _entry_is_verified(entry, config=config)
        if not valid:
            unresolved += 1
    return unresolved


def download_range(
    *,
    config: PipelineConfig,
    symbol: str,
    start: datetime,
    end: datetime,
    raw_root: Path,
    manifest_path: Path,
    mode: str = "all",
    dry_run: bool = False,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    logger: StructuredLogger | None = None,
    now: Callable[[], datetime] = utc_now,
) -> dict[str, int]:
    symbol = symbol.upper()
    config.symbol(symbol)
    partitions = generate_partitions(start, end)
    manifest = Manifest(manifest_path, config=config, symbol=symbol)
    owned_logger = logger is None
    logger = logger or StructuredLogger()
    owned_transport = transport is None
    transport = transport or HttpxTransport()
    summary = {
        "expected_partitions": len(partitions),
        "downloaded": 0,
        "resumed_verified": 0,
        "recovered_existing": 0,
        "expected_market_closures": 0,
        "failed": 0,
        "not_selected": 0,
        "dry_run_planned": 0,
        "unresolved": 0,
    }
    try:
        for index, partition in enumerate(partitions, start=1):
            url = partition_url(config, symbol, partition)
            path = partition_file_path(raw_root, symbol, partition)
            entry = manifest.get(partition)
            logger.emit(
                "info",
                "partition_progress",
                current=index,
                total=len(partitions),
                partition=partition.key,
            )
            verified, verification_error = _entry_is_verified(entry, config=config)
            if verified:
                summary["resumed_verified"] += 1
                logger.emit("info", "partition_skipped_verified", partition=partition.key)
                continue
            if verification_error and not dry_run:
                manifest.record(
                    partition,
                    **_manifest_entry(
                        config=config,
                        symbol=symbol,
                        partition=partition,
                        url=url,
                        file_path=path if path.exists() else None,
                        byte_size=path.stat().st_size if path.exists() else None,
                        checksum=(entry or {}).get("sha256"),
                        status="corrupt",
                        retry_count=int(entry.get("retry_count", 0)) if entry else 0,
                        error_details=verification_error,
                        download_timestamp=(entry or {}).get("download_timestamp"),
                    ),
                )
                manifest.save()
                entry = manifest.get(partition)

            # Recover a fully written object if a process stopped before its manifest update.
            recoverable_unmanifested_file = entry is None or (
                entry.get("status") in {"missing", "failed", "unresolved"}
                and entry.get("sha256") is None
            )
            if path.is_file() and not dry_run and recoverable_unmanifested_file:
                try:
                    rows = validate_bi5_file(
                        path,
                        max_compressed_bytes=int(config.download["max_compressed_bytes"]),
                    )
                except PayloadValidationError:
                    pass
                else:
                    checksum = sha256_file(path)
                    manifest.record(
                        partition,
                        **_manifest_entry(
                            config=config,
                            symbol=symbol,
                            partition=partition,
                            url=url,
                            file_path=path,
                            byte_size=path.stat().st_size,
                            checksum=checksum,
                            status="verified",
                            retry_count=0,
                            error_details=None,
                            download_timestamp=format_utc(now()),
                            record_count=rows,
                        ),
                    )
                    manifest.save()
                    summary["recovered_existing"] += 1
                    logger.emit(
                        "info",
                        "partition_recovered_existing",
                        partition=partition.key,
                        sha256=checksum,
                        records=rows,
                    )
                    continue

            if (
                is_expected_closure(config, partition, symbol=symbol)
                and manifest_no_data_evidence(entry) is not None
                and not path.is_file()
            ):
                summary["expected_market_closures"] += 1
                if not dry_run:
                    manifest.record(
                        partition,
                        **_manifest_entry(
                            config=config,
                            symbol=symbol,
                            partition=partition,
                            url=url,
                            file_path=None,
                            byte_size=None,
                            checksum=None,
                            status="expected_market_closure",
                            retry_count=0,
                            error_details=(
                                "matched configured closure rule with missing or explicit "
                                "no-data evidence"
                            ),
                            download_timestamp=None,
                        ),
                    )
                    manifest.save()
                logger.emit("info", "partition_expected_closure", partition=partition.key)
                continue

            if not _selected_for_mode(mode, entry, path):
                summary["not_selected"] += 1
                logger.emit("info", "partition_not_selected", partition=partition.key, mode=mode)
                continue
            if dry_run:
                summary["dry_run_planned"] += 1
                logger.emit(
                    "info", "partition_dry_run", partition=partition.key, url=url, path=str(path)
                )
                continue

            retry_count = 0
            try:
                result, retry_count = fetch_with_retry(
                    url,
                    transport=transport,
                    timeout=float(config.download["timeout_seconds"]),
                    user_agent=str(config.download["user_agent"]),
                    max_attempts=int(config.download["max_attempts"]),
                    backoff_initial=float(config.download["backoff_initial_seconds"]),
                    backoff_max=float(config.download["backoff_max_seconds"]),
                    throttle=float(config.download["throttle_seconds"]),
                    sleep=sleep,
                    logger=logger,
                    partition=partition,
                )
                _decoded, rows = inspect_bi5_payload(
                    result.body,
                    max_compressed_bytes=int(config.download["max_compressed_bytes"]),
                )
                atomic_write_bytes(path, result.body)
                checksum = sha256_bytes(result.body)
                manifest.record(
                    partition,
                    **_manifest_entry(
                        config=config,
                        symbol=symbol,
                        partition=partition,
                        url=url,
                        file_path=path,
                        byte_size=len(result.body),
                        checksum=checksum,
                        status="verified",
                        retry_count=retry_count,
                        error_details=None,
                        download_timestamp=format_utc(now()),
                        record_count=rows,
                    ),
                )
                manifest.save()
                summary["downloaded"] += 1
                logger.emit(
                    "info",
                    "partition_downloaded",
                    partition=partition.key,
                    bytes=len(result.body),
                    records=rows,
                    sha256=checksum,
                    retry_count=retry_count,
                )
            except (SourceRequestError, PayloadValidationError, OSError, ValueError) as exc:
                summary["failed"] += 1
                error_kind = (
                    "empty_payload" if isinstance(exc, EmptyPayloadError) else type(exc).__name__
                )
                if isinstance(exc, SourceRequestError):
                    retry_count = max(
                        retry_count,
                        int(config.download["max_attempts"]) - 1 if exc.retryable else 0,
                    )
                manifest.record(
                    partition,
                    **_manifest_entry(
                        config=config,
                        symbol=symbol,
                        partition=partition,
                        url=url,
                        file_path=None,
                        byte_size=None,
                        checksum=None,
                        status="failed",
                        retry_count=retry_count,
                        error_details=f"{error_kind}: {exc}",
                        download_timestamp=format_utc(now()),
                    ),
                )
                manifest.save()
                logger.emit(
                    "error",
                    "partition_failed",
                    partition=partition.key,
                    error_kind=error_kind,
                    error=str(exc),
                    retry_count=retry_count,
                )
        if not dry_run:
            summary["unresolved"] = _count_unresolved(
                config=config, manifest=manifest, partitions=partitions
            )
        logger.emit("info", "download_complete", **summary)
        return summary
    finally:
        if owned_transport and isinstance(transport, HttpxTransport):
            transport.close()
        if owned_logger:
            logger.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="inclusive UTC date/hour")
    parser.add_argument("--end", required=True, help="exclusive UTC date/hour")
    parser.add_argument("--config", default="config/dukascopy_data.toml")
    parser.add_argument("--output-root", help="override configured raw data root")
    parser.add_argument("--manifest", help="override manifest JSON path")
    parser.add_argument(
        "--only",
        choices=("all", "failed", "missing", "failed-or-missing"),
        default="all",
        help="restrict network work while retaining unresolved-failure exit semantics",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-path", help="override structured JSONL log path")
    parser.add_argument("--no-log-file", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        symbol = args.symbol.upper()
        config.symbol(symbol)
        start = parse_utc_boundary(args.start)
        end = parse_utc_boundary(args.end)
        raw_root = Path(args.output_root) if args.output_root else config.path_for("raw_root")
        manifest_path = (
            Path(args.manifest)
            if args.manifest
            else config.path_for("manifests_root") / f"{symbol}_ticks_manifest.json"
        )
        if args.no_log_file:
            log_path = None
        elif args.log_path:
            log_path = Path(args.log_path)
        else:
            stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
            log_path = config.path_for("logs_root") / f"download_{symbol}_{stamp}.jsonl"
        with StructuredLogger(log_path=log_path, quiet=args.quiet) as logger:
            summary = download_range(
                config=config,
                symbol=symbol,
                start=start,
                end=end,
                raw_root=raw_root,
                manifest_path=manifest_path,
                mode=args.only,
                dry_run=args.dry_run,
                logger=logger,
            )
        return 0 if args.dry_run or summary["unresolved"] == 0 else 2
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
