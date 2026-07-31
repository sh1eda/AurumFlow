#!/usr/bin/env python3
"""Resumable downloader for native hourly Dukascopy BI5 tick partitions."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime
import email.utils
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Protocol, Sequence
from urllib.parse import urlsplit

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
    proxy_identity_masked: str | None = None


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
        counts_for_proxy_rotation: bool = False,
        response_byte_length: int | None = None,
        proxy_identity_masked: str | None = None,
        evidence_kind: str = "network_failure",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after
        self.counts_for_proxy_rotation = counts_for_proxy_rotation
        self.response_byte_length = response_byte_length
        self.proxy_identity_masked = proxy_identity_masked
        self.evidence_kind = evidence_kind


_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@"
)


def mask_proxy_url(value: str) -> str:
    """Remove all URL userinfo so proxy credentials cannot enter diagnostics."""

    return _URL_CREDENTIALS.sub(r"\g<scheme>***:***@", value)


def validate_proxy_url(proxy_url: str) -> str:
    """Validate an HTTP(S) proxy without ever returning credentials in errors."""

    candidate = proxy_url.strip()
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError
        if not parsed.hostname or any(character.isspace() for character in candidate):
            raise ValueError
        _port = parsed.port
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError
        httpx.URL(candidate)
    except (TypeError, ValueError):
        raise ValueError("invalid proxy URL") from None
    return candidate


def load_proxy_file(path: str | Path) -> list[str]:
    """Load, validate, and stably deduplicate a one-proxy-per-line file."""

    proxy_path = Path(path)
    try:
        lines = proxy_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise OSError(f"could not read proxy file {proxy_path}: {detail}") from None
    proxies: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        try:
            validated = validate_proxy_url(candidate)
        except ValueError:
            raise ValueError(f"invalid proxy URL on line {line_number}") from None
        if validated not in seen:
            seen.add(validated)
            proxies.append(validated)
    if not proxies:
        raise ValueError(f"proxy file {proxy_path} contains no usable proxy URLs")
    return proxies


class HttpxTransport:
    """Persistent HTTP/1.1 transport for sequential archive requests."""

    def __init__(self, proxy_url: str | None = None) -> None:
        self._proxy_url = validate_proxy_url(proxy_url) if proxy_url else None
        try:
            self._client = httpx.Client(
                http2=False,
                follow_redirects=True,
                proxy=self._proxy_url,
            )
        except (httpx.HTTPError, TypeError, ValueError):
            proxy_diagnostic = (
                mask_proxy_url(self._proxy_url) if self._proxy_url else "disabled"
            )
            raise ValueError(
                f"could not initialize HTTP client; proxy={proxy_diagnostic}"
            ) from None

    @property
    def proxy_identity_masked(self) -> str:
        return mask_proxy_url(self._proxy_url) if self._proxy_url else "direct"

    def fetch(self, url: str, *, timeout: float, headers: dict[str, str]) -> HttpResult:
        try:
            response = self._client.get(url, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            detail = mask_proxy_url(str(exc))
            raise SourceRequestError(
                f"network request timed out: {detail}",
                retryable=True,
                counts_for_proxy_rotation=True,
                proxy_identity_masked=self.proxy_identity_masked,
                evidence_kind="timeout",
            ) from None
        except httpx.ProxyError as exc:
            detail = mask_proxy_url(str(exc))
            raise SourceRequestError(
                f"proxy request failed: {detail}",
                retryable=True,
                counts_for_proxy_rotation=True,
                proxy_identity_masked=self.proxy_identity_masked,
                evidence_kind="proxy_failure",
            ) from None
        except httpx.TransportError as exc:
            detail = mask_proxy_url(str(exc))
            lowered = detail.lower()
            evidence_kind = (
                "tls_ssl_failure"
                if "tls" in lowered or "ssl" in lowered or "certificate" in lowered
                else (
                    "connection_reset"
                    if "reset" in lowered or "unexpected_eof" in lowered
                    else "network_failure"
                )
            )
            raise SourceRequestError(
                f"network request failed: {detail}",
                retryable=True,
                counts_for_proxy_rotation=True,
                proxy_identity_masked=self.proxy_identity_masked,
                evidence_kind=evidence_kind,
            ) from None
        return HttpResult(
            status=response.status_code,
            body=response.content,
            headers={key.lower(): value for key, value in response.headers.items()},
            proxy_identity_masked=self.proxy_identity_masked,
        )

    def close(self) -> None:
        self._client.close()


class ProxyPoolTransport:
    """Health-aware deterministic proxy rotation over replaceable HTTPX clients."""

    def __init__(
        self,
        proxy_urls: Sequence[str],
        *,
        rotate_after_failures: int = 2,
        cooldown_seconds: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        logger: StructuredLogger,
        transport_factory: Callable[[str], Transport] | None = None,
    ) -> None:
        self.proxy_urls = tuple(validate_proxy_url(value) for value in proxy_urls)
        if not self.proxy_urls:
            raise ValueError("proxy pool requires at least one proxy URL")
        if rotate_after_failures < 1:
            raise ValueError("proxy_rotate_after_failures must be at least 1")
        if cooldown_seconds < 0:
            raise ValueError("proxy_cooldown_seconds must be non-negative")
        self.rotate_after_failures = int(rotate_after_failures)
        self.cooldown_seconds = float(cooldown_seconds)
        self.sleep = sleep
        self.clock = clock
        self.logger = logger
        self.transport_factory = transport_factory or (
            lambda proxy_url: HttpxTransport(proxy_url=proxy_url)
        )
        self.current_index = 0
        self.failure_counts = [0 for _proxy in self.proxy_urls]
        self.cooldown_until = [0.0 for _proxy in self.proxy_urls]
        self.failed_since_success: set[int] = set()
        self.total_failure_counts = [0 for _proxy in self.proxy_urls]
        self.transient_failure_events = 0
        self.rotation_count = 0
        self.wait_count = 0
        self._transport = self.transport_factory(self.proxy_urls[self.current_index])
        self._closed = False

    @property
    def current_proxy(self) -> str:
        return self.proxy_urls[self.current_index]

    @property
    def failures_span_pool(self) -> bool:
        return len(self.failed_since_success) == len(self.proxy_urls)

    def fetch(self, url: str, *, timeout: float, headers: dict[str, str]) -> HttpResult:
        proxy_identity = mask_proxy_url(self.current_proxy)
        try:
            result = self._transport.fetch(url, timeout=timeout, headers=headers)
        except SourceRequestError as exc:
            if exc.proxy_identity_masked is None:
                exc.proxy_identity_masked = proxy_identity
            raise
        if result.proxy_identity_masked is None:
            return replace(result, proxy_identity_masked=proxy_identity)
        return result

    def record_success(self) -> None:
        self.failure_counts[self.current_index] = 0
        self.failed_since_success.clear()

    def record_transient_failure(
        self,
        error: SourceRequestError,
        *,
        partition: Partition,
    ) -> bool:
        if not error.counts_for_proxy_rotation:
            return False
        failed_index = self.current_index
        self.failure_counts[failed_index] += 1
        self.total_failure_counts[failed_index] += 1
        self.transient_failure_events += 1
        self.failed_since_success.add(failed_index)
        consecutive_failures = self.failure_counts[failed_index]
        if consecutive_failures < self.rotate_after_failures:
            return False
        now = self.clock()
        self.cooldown_until[failed_index] = now + self.cooldown_seconds
        next_index = self._select_next_proxy(now=now, partition=partition)
        self._switch_proxy(
            next_index,
            reason=mask_proxy_url(str(error)),
            consecutive_failures=consecutive_failures,
            partition=partition,
        )
        return True

    def _select_next_proxy(self, *, now: float, partition: Partition) -> int:
        available = self._available_indices(now)
        if not available:
            self.wait_count += 1
            earliest = min(self.cooldown_until)
            wait_seconds = max(0.0, earliest - now)
            self.logger.emit(
                "warning",
                "proxy_pool_wait",
                wait_seconds=wait_seconds,
                unavailable_proxy_count=len(self.proxy_urls),
                partition=partition.key,
            )
            if wait_seconds > 0:
                self.sleep(wait_seconds)
            now += wait_seconds
            available = self._available_indices(now)
        for offset in range(1, len(self.proxy_urls) + 1):
            candidate = (self.current_index + offset) % len(self.proxy_urls)
            if candidate in available:
                return candidate
        raise RuntimeError("proxy pool could not select an available proxy")

    def _available_indices(self, now: float) -> set[int]:
        return {
            index
            for index, cooldown_until in enumerate(self.cooldown_until)
            if cooldown_until <= now
        }

    def _switch_proxy(
        self,
        next_index: int,
        *,
        reason: str,
        consecutive_failures: int,
        partition: Partition,
    ) -> None:
        previous_index = self.current_index
        replacement = self.transport_factory(self.proxy_urls[next_index])
        previous_transport = self._transport
        self._transport = replacement
        self.current_index = next_index
        self.rotation_count += 1
        self.failure_counts[next_index] = 0
        close = getattr(previous_transport, "close", None)
        if callable(close):
            close()
        self.logger.emit(
            "warning",
            "proxy_rotation",
            previous_proxy_masked=mask_proxy_url(self.proxy_urls[previous_index]),
            next_proxy_masked=mask_proxy_url(self.proxy_urls[next_index]),
            reason=reason,
            consecutive_failures=consecutive_failures,
            partition=partition.key,
        )

    def recovery_statistics(self) -> dict[str, Any]:
        return {
            "proxy_failure_events": self.transient_failure_events,
            "proxy_rotations": self.rotation_count,
            "proxy_pool_waits": self.wait_count,
            "proxy_failures_by_masked_identity": {
                mask_proxy_url(proxy): self.total_failure_counts[index]
                for index, proxy in enumerate(self.proxy_urls)
            },
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()


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


def _transport_proxy_identity(transport: Transport) -> str:
    current_proxy = getattr(transport, "current_proxy", None)
    if isinstance(current_proxy, str):
        return mask_proxy_url(current_proxy)
    identity = getattr(transport, "proxy_identity_masked", None)
    return str(identity) if identity else "direct"


def fetch_with_retry(
    url: str,
    *,
    transport: Transport,
    timeout: float,
    user_agent: str,
    max_attempts: int,
    sleep: Callable[[float], None],
    logger: StructuredLogger,
    partition: Partition,
    backoff_schedule: Sequence[float] | None = None,
    request_delay: float | None = None,
    # Backward-compatible test/API aliases. New downloader calls use the explicit
    # schedule and request-delay names above.
    backoff_initial: float | None = None,
    backoff_max: float | None = None,
    throttle: float | None = None,
) -> tuple[HttpResult, int]:
    """Fetch a partition, retrying only failures classified as transient."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if request_delay is None:
        request_delay = throttle if throttle is not None else 2.0
    request_delay = float(request_delay)
    if request_delay < 0:
        raise ValueError("request_delay must be non-negative")
    if backoff_schedule is None:
        if backoff_initial is None:
            backoff_schedule = (15.0, 60.0, 300.0)
        else:
            cap = float(backoff_max) if backoff_max is not None else float("inf")
            backoff_schedule = tuple(
                min(cap, float(backoff_initial) * (2**index))
                for index in range(max(1, max_attempts - 1))
            )
    retry_delays = tuple(float(delay) for delay in backoff_schedule)
    if not retry_delays or any(delay < 0 for delay in retry_delays):
        raise ValueError("backoff_schedule must contain non-negative delays")

    last_error: SourceRequestError | None = None
    for attempt in range(1, max_attempts + 1):
        proxy_identity = _transport_proxy_identity(transport)
        try:
            result = transport.fetch(
                url,
                timeout=timeout,
                headers={"User-Agent": user_agent, "Accept": "application/octet-stream"},
            )
            if result.status != 200:
                retry_after = _parse_retry_after(result.headers.get("retry-after"))
                detail = mask_proxy_url(
                    result.body[:256].decode("utf-8", errors="replace").strip()
                )
                suffix = f": {detail}" if detail else ""
                raise SourceRequestError(
                    f"HTTP {result.status}{suffix}",
                    retryable=result.status in {408, 425, 429} or result.status >= 500,
                    status=result.status,
                    retry_after=retry_after,
                    counts_for_proxy_rotation=result.status in {429, 502, 503, 504},
                    response_byte_length=len(result.body),
                    proxy_identity_masked=(
                        result.proxy_identity_masked or proxy_identity
                    ),
                    evidence_kind="http_error",
                )
            content_length = result.headers.get("content-length")
            if content_length is not None and int(content_length) != len(result.body):
                raise SourceRequestError(
                    f"Content-Length {content_length} does not match {len(result.body)} bytes",
                    retryable=True,
                    status=result.status,
                    response_byte_length=len(result.body),
                    proxy_identity_masked=(
                        result.proxy_identity_masked or proxy_identity
                    ),
                    evidence_kind="content_length_mismatch",
                )
            if request_delay > 0:
                sleep(request_delay)
            return result, attempt - 1
        except SourceRequestError as exc:
            if exc.proxy_identity_masked is None:
                exc.proxy_identity_masked = proxy_identity
            last_error = exc
            record_failure = getattr(transport, "record_transient_failure", None)
            if callable(record_failure):
                record_failure(exc, partition=partition)
            if not exc.retryable or attempt == max_attempts:
                if request_delay > 0:
                    sleep(request_delay)
                raise
            delay = retry_delays[min(attempt - 1, len(retry_delays) - 1)]
            if exc.retry_after is not None:
                delay = max(delay, exc.retry_after)
            logger.emit(
                "warning",
                "download_retry",
                partition=partition.key,
                attempt=attempt,
                delay_seconds=delay,
                error=mask_proxy_url(str(exc)),
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
    evidence_kind: str | None = None,
    http_status: int | None = None,
    response_byte_length: int | None = None,
    proxy_identity_masked: str | None = None,
    final_attempt_timestamp: str | None = None,
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
        "evidence_kind": evidence_kind,
        "http_status": http_status,
        "response_byte_length": response_byte_length,
        "proxy_identity_masked": proxy_identity_masked,
        "final_attempt_timestamp": final_attempt_timestamp,
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


def load_targeted_recovery_allowlist(
    report_path: str | Path,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    expected_count: int | None = None,
) -> tuple[set[str], dict[str, Any]]:
    """Load and fail-closed audit the verifier's complete unresolved allowlist."""

    path = Path(report_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load targeted recovery report {path}: {exc}") from None
    normalized_symbol = symbol.upper()
    if report.get("symbol") != normalized_symbol:
        raise ValueError(
            f"recovery report symbol {report.get('symbol')!r} does not match "
            f"{normalized_symbol}"
        )
    expected_range = {
        "start_inclusive": format_utc(start),
        "end_exclusive": format_utc(end),
    }
    if report.get("range") != expected_range:
        raise ValueError(
            "recovery report range must exactly match the requested [start, end)"
        )
    allowed_range = {partition.key for partition in generate_partitions(start, end)}
    reconciliation = report.get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise ValueError("recovery report does not contain reconciliation totals")
    if reconciliation.get("balanced") is not True:
        raise ValueError("recovery report reconciliation must be balanced")
    if reconciliation.get("expected_partitions") != len(allowed_range):
        raise ValueError(
            "recovery report expected_partitions does not match requested range"
        )
    report_unresolved = reconciliation.get("unresolved")
    if not isinstance(report_unresolved, int) or isinstance(report_unresolved, bool):
        raise ValueError("recovery report unresolved total must be an integer")
    if report_unresolved < 0:
        raise ValueError("recovery report unresolved total must be non-negative")

    partition_details = report.get("partitions")
    if not isinstance(partition_details, list):
        raise ValueError("recovery report does not contain partition classifications")
    report_classifications: dict[str, str] = {}
    duplicate_report_timestamps: set[str] = set()
    report_timestamps_outside_range: set[str] = set()
    for item in partition_details:
        if not isinstance(item, dict):
            raise ValueError("recovery report partition detail must be an object")
        timestamp = item.get("partition_timestamp")
        classification = item.get("classification")
        if not isinstance(timestamp, str) or not isinstance(classification, str):
            raise ValueError(
                "recovery report partition detail requires timestamp and classification"
            )
        if timestamp in report_classifications:
            duplicate_report_timestamps.add(timestamp)
        report_classifications[timestamp] = classification
        if timestamp not in allowed_range:
            report_timestamps_outside_range.add(timestamp)
    if duplicate_report_timestamps:
        raise ValueError(
            "recovery report contains duplicate partition timestamps: "
            f"{sorted(duplicate_report_timestamps)[0]}"
        )
    if report_timestamps_outside_range:
        raise ValueError(
            "recovery report contains partition outside requested range: "
            f"{sorted(report_timestamps_outside_range)[0]}"
        )
    missing_report_timestamps = allowed_range - set(report_classifications)
    if missing_report_timestamps:
        raise ValueError(
            "recovery report omits expected partition: "
            f"{sorted(missing_report_timestamps)[0]}"
        )

    groups = (
        report.get("reclassification_audit", {})
        .get("remaining_unresolved_by_error_kind", {})
    )
    if not isinstance(groups, dict):
        raise ValueError("recovery report does not contain unresolved evidence groups")
    selected: set[str] = set()
    duplicate_timestamps: set[str] = set()
    timestamps_outside_range: set[str] = set()
    group_counts: dict[str, int] = {}
    for group in sorted(groups):
        timestamps = groups[group]
        if not isinstance(timestamps, list) or not all(
            isinstance(value, str) for value in timestamps
        ):
            raise ValueError(f"recovery evidence group {group!r} must be a timestamp list")
        group_counts[group] = len(timestamps)
        for timestamp in timestamps:
            if timestamp not in allowed_range:
                timestamps_outside_range.add(timestamp)
            if timestamp in selected:
                duplicate_timestamps.add(timestamp)
            selected.add(timestamp)
    overlap = {
        timestamp
        for timestamp in selected
        if report_classifications.get(timestamp)
        in {"verified_data", "expected_market_closure"}
    }
    reported_unresolved = {
        timestamp
        for timestamp, classification in report_classifications.items()
        if classification == "unresolved_status"
    }
    ungrouped_unresolved = reported_unresolved - selected
    grouped_non_unresolved = selected - reported_unresolved

    audit = {
        "allowlist_count": len(selected),
        "duplicate_timestamps": len(duplicate_timestamps),
        "timestamps_outside_range": len(timestamps_outside_range),
        "verified_or_confirmed_closure_timestamps_in_allowlist": len(overlap),
        "report_unresolved": report_unresolved,
        "expected_allowlist_count": (
            report_unresolved if expected_count is None else expected_count
        ),
        "unresolved_groups": group_counts,
        "ungrouped_unresolved_timestamps": len(ungrouped_unresolved),
        "grouped_non_unresolved_timestamps": len(grouped_non_unresolved),
    }
    if duplicate_timestamps:
        raise ValueError(
            "targeted recovery preflight failed: duplicate_timestamps="
            f"{len(duplicate_timestamps)}"
        )
    if timestamps_outside_range:
        raise ValueError(
            "targeted recovery preflight failed: timestamps_outside_range="
            f"{len(timestamps_outside_range)}"
        )
    if overlap:
        raise ValueError(
            "targeted recovery preflight failed: "
            "verified_or_confirmed_closure_timestamps_in_allowlist="
            f"{len(overlap)}"
        )
    if ungrouped_unresolved or grouped_non_unresolved:
        raise ValueError(
            "targeted recovery groups do not exactly cover every unresolved partition"
        )
    if len(selected) != report_unresolved:
        raise ValueError(
            "targeted recovery allowlist count does not match report unresolved total: "
            f"{len(selected)} != {report_unresolved}"
        )
    if expected_count is not None and len(selected) != expected_count:
        raise ValueError(
            "targeted recovery allowlist count does not match required count: "
            f"{len(selected)} != {expected_count}"
        )
    return selected, audit


def load_targeted_recovery_partitions(
    report_path: str | Path,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    expected_count: int | None = None,
) -> set[str]:
    """Backward-compatible set-only targeted recovery loader."""

    selected, _audit = load_targeted_recovery_allowlist(
        report_path,
        symbol=symbol,
        start=start,
        end=end,
        expected_count=expected_count,
    )
    return selected


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
    proxy_url: str | None = None,
    proxy_urls: Sequence[str] | None = None,
    proxy_rotate_after_failures: int | None = None,
    proxy_cooldown_seconds: float | None = None,
    request_delay_seconds: float | None = None,
    retry_backoff_seconds: Sequence[float] | None = None,
    circuit_breaker_threshold: int | None = None,
    circuit_breaker_pause_seconds: float | None = None,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    logger: StructuredLogger | None = None,
    now: Callable[[], datetime] = utc_now,
    selected_partition_keys: set[str] | None = None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    config.symbol(symbol)
    if proxy_url is not None and proxy_urls is not None:
        raise ValueError("proxy_url and proxy_urls are mutually exclusive")
    partitions = generate_partitions(start, end)
    expected_partition_keys = {partition.key for partition in partitions}
    if selected_partition_keys is not None:
        outside_range = set(selected_partition_keys) - expected_partition_keys
        if outside_range:
            first = sorted(outside_range)[0]
            raise ValueError(f"targeted recovery partition outside range: {first}")
    manifest = Manifest(manifest_path, config=config, symbol=symbol)
    if request_delay_seconds is None:
        request_delay_seconds = float(
            config.download.get(
                "request_delay_seconds",
                config.download.get("throttle_seconds", 2.0),
            )
        )
    if request_delay_seconds < 0:
        raise ValueError("request_delay_seconds must be non-negative")
    if retry_backoff_seconds is None:
        configured_schedule = config.download.get("retry_backoff_seconds")
        if configured_schedule is not None:
            retry_backoff_seconds = tuple(float(value) for value in configured_schedule)
        else:
            initial = float(config.download.get("backoff_initial_seconds", 15.0))
            maximum = float(config.download.get("backoff_max_seconds", 300.0))
            retry_backoff_seconds = tuple(
                min(maximum, initial * (2**index)) for index in range(3)
            )
    retry_backoff_seconds = tuple(float(value) for value in retry_backoff_seconds)
    if not retry_backoff_seconds or any(value < 0 for value in retry_backoff_seconds):
        raise ValueError("retry_backoff_seconds must contain non-negative delays")
    if circuit_breaker_threshold is None:
        circuit_breaker_threshold = int(
            config.download.get("circuit_breaker_threshold", 5)
        )
    if circuit_breaker_pause_seconds is None:
        circuit_breaker_pause_seconds = float(
            config.download.get("circuit_breaker_pause_seconds", 900.0)
        )
    if circuit_breaker_threshold < 1:
        raise ValueError("circuit_breaker_threshold must be at least 1")
    if circuit_breaker_pause_seconds < 0:
        raise ValueError("circuit_breaker_pause_seconds must be non-negative")
    if proxy_rotate_after_failures is None:
        proxy_rotate_after_failures = int(
            config.download.get("proxy_rotate_after_failures", 2)
        )
    if proxy_cooldown_seconds is None:
        proxy_cooldown_seconds = float(
            config.download.get("proxy_cooldown_seconds", 300.0)
        )
    if proxy_rotate_after_failures < 1:
        raise ValueError("proxy_rotate_after_failures must be at least 1")
    if proxy_cooldown_seconds < 0:
        raise ValueError("proxy_cooldown_seconds must be non-negative")
    owned_logger = logger is None
    logger = logger or StructuredLogger()
    owned_transport = transport is None
    if transport is None:
        if proxy_urls is not None:
            transport = ProxyPoolTransport(
                proxy_urls,
                rotate_after_failures=proxy_rotate_after_failures,
                cooldown_seconds=proxy_cooldown_seconds,
                sleep=sleep,
                logger=logger,
            )
        else:
            transport = HttpxTransport(proxy_url=proxy_url)
    consecutive_transient_failures = 0
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
        "targeted_partitions": (
            len(selected_partition_keys)
            if selected_partition_keys is not None
            else len(partitions)
        ),
        "attempted_partitions": 0,
        "total_retries": 0,
    }
    try:
        for index, partition in enumerate(partitions, start=1):
            if (
                selected_partition_keys is not None
                and partition.key not in selected_partition_keys
            ):
                summary["not_selected"] += 1
                continue
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

            closure_evidence = manifest_no_data_evidence(entry)
            if (
                is_expected_closure(config, partition, symbol=symbol)
                and closure_evidence is not None
                and not path.is_file()
            ):
                consecutive_transient_failures = 0
                summary["expected_market_closures"] += 1
                if not dry_run:
                    preserved_details = str(
                        (entry or {}).get("error_details") or ""
                    ).strip()
                    if not preserved_details:
                        preserved_details = (
                            f"{closure_evidence}: source returned explicit no data"
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
                            status="expected_market_closure",
                            retry_count=int(
                                (entry or {}).get("retry_count") or 0
                            ),
                            error_details=preserved_details,
                            download_timestamp=(entry or {}).get(
                                "download_timestamp"
                            ),
                            evidence_kind=(entry or {}).get("evidence_kind"),
                            http_status=(entry or {}).get("http_status"),
                            response_byte_length=(entry or {}).get(
                                "response_byte_length"
                            ),
                            proxy_identity_masked=(entry or {}).get(
                                "proxy_identity_masked"
                            ),
                            final_attempt_timestamp=(entry or {}).get(
                                "final_attempt_timestamp"
                            ),
                        ),
                    )
                    manifest.save()
                logger.emit(
                    "info",
                    "partition_expected_closure",
                    partition=partition.key,
                    evidence=closure_evidence,
                )
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
            result: HttpResult | None = None
            try:
                summary["attempted_partitions"] += 1
                result, retry_count = fetch_with_retry(
                    url,
                    transport=transport,
                    timeout=float(config.download["timeout_seconds"]),
                    user_agent=str(config.download["user_agent"]),
                    max_attempts=int(config.download["max_attempts"]),
                    backoff_schedule=retry_backoff_seconds,
                    request_delay=request_delay_seconds,
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
                final_attempt_timestamp = format_utc(now())
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
                        download_timestamp=final_attempt_timestamp,
                        record_count=rows,
                        evidence_kind="valid_bi5_payload",
                        http_status=result.status,
                        response_byte_length=len(result.body),
                        proxy_identity_masked=(
                            result.proxy_identity_masked
                            or _transport_proxy_identity(transport)
                        ),
                        final_attempt_timestamp=final_attempt_timestamp,
                    ),
                )
                manifest.save()
                record_success = getattr(transport, "record_success", None)
                if callable(record_success):
                    record_success()
                consecutive_transient_failures = 0
                summary["downloaded"] += 1
                summary["total_retries"] += retry_count
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
                safe_error = mask_proxy_url(str(exc))
                error_kind = (
                    "empty_payload" if isinstance(exc, EmptyPayloadError) else type(exc).__name__
                )
                confirmed_closure = isinstance(
                    exc, EmptyPayloadError
                ) and is_expected_closure(config, partition, symbol=symbol)
                if isinstance(exc, SourceRequestError):
                    retry_count = max(
                        retry_count,
                        int(config.download["max_attempts"]) - 1 if exc.retryable else 0,
                    )
                    http_status = exc.status
                    response_byte_length = exc.response_byte_length
                    proxy_identity = (
                        exc.proxy_identity_masked
                        or _transport_proxy_identity(transport)
                    )
                    evidence_kind = exc.evidence_kind
                else:
                    http_status = result.status if result is not None else None
                    response_byte_length = (
                        len(result.body) if result is not None else None
                    )
                    proxy_identity = (
                        result.proxy_identity_masked
                        if result is not None
                        and result.proxy_identity_masked is not None
                        else _transport_proxy_identity(transport)
                    )
                    if isinstance(exc, EmptyPayloadError):
                        evidence_kind = "confirmed_empty_payload"
                    elif isinstance(exc, PayloadValidationError):
                        evidence_kind = "malformed_non_empty_payload"
                    elif isinstance(exc, OSError):
                        evidence_kind = "local_io_failure"
                    else:
                        evidence_kind = "decode_or_value_failure"
                final_attempt_timestamp = format_utc(now())
                manifest_status = (
                    "expected_market_closure" if confirmed_closure else "failed"
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
                        status=manifest_status,
                        retry_count=retry_count,
                        error_details=f"{error_kind}: {safe_error}",
                        download_timestamp=final_attempt_timestamp,
                        evidence_kind=evidence_kind,
                        http_status=http_status,
                        response_byte_length=response_byte_length,
                        proxy_identity_masked=proxy_identity,
                        final_attempt_timestamp=final_attempt_timestamp,
                    ),
                )
                manifest.save()
                summary["total_retries"] += retry_count
                if confirmed_closure:
                    summary["expected_market_closures"] += 1
                    consecutive_transient_failures = 0
                    logger.emit(
                        "info",
                        "partition_expected_closure",
                        partition=partition.key,
                        evidence="empty_payload",
                    )
                    continue
                summary["failed"] += 1
                logger.emit(
                    "error",
                    "partition_failed",
                    partition=partition.key,
                    error_kind=error_kind,
                    error=safe_error,
                    retry_count=retry_count,
                )
                if isinstance(exc, SourceRequestError) and exc.retryable:
                    consecutive_transient_failures += 1
                    if consecutive_transient_failures >= circuit_breaker_threshold:
                        pool_failures_span = getattr(
                            transport, "failures_span_pool", True
                        )
                        if (
                            not exc.counts_for_proxy_rotation
                            or bool(pool_failures_span)
                        ):
                            logger.emit(
                                "warning",
                                "circuit_breaker_pause",
                                consecutive_transient_failures=(
                                    consecutive_transient_failures
                                ),
                                pause_seconds=circuit_breaker_pause_seconds,
                            )
                            if circuit_breaker_pause_seconds > 0:
                                sleep(circuit_breaker_pause_seconds)
        if not dry_run:
            summary["unresolved"] = _count_unresolved(
                config=config, manifest=manifest, partitions=partitions
            )
        recovery_statistics = getattr(transport, "recovery_statistics", None)
        if callable(recovery_statistics):
            summary.update(recovery_statistics())
        logger.emit("info", "download_complete", **summary)
        return summary
    finally:
        if owned_transport:
            close = getattr(transport, "close", None)
            if callable(close):
                close()
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
        "--targeted-recovery-report",
        help=(
            "verifier JSON report whose complete unresolved evidence groups form "
            "the only request allowlist"
        ),
    )
    parser.add_argument(
        "--targeted-recovery-expected-count",
        type=int,
        help=(
            "fail closed unless the audited targeted recovery allowlist has "
            "exactly this many unique timestamps"
        ),
    )
    proxy_options = parser.add_mutually_exclusive_group()
    proxy_options.add_argument(
        "--proxy-url",
        help=(
            "optional HTTPX proxy URL; defaults to DUKASCOPY_PROXY_URL when set "
            "and credentials are always masked in diagnostics"
        ),
    )
    proxy_options.add_argument(
        "--proxy-file",
        help="one HTTP(S) proxy URL per line; blank and # comment lines are ignored",
    )
    parser.add_argument(
        "--proxy-rotate-after-failures",
        type=int,
        default=2,
        help="consecutive proxy failures before rotation (default: 2)",
    )
    parser.add_argument(
        "--proxy-cooldown-seconds",
        type=float,
        default=300.0,
        help="cooldown for a rotated-out proxy (default: 300)",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=2.0,
        help="delay after each partition request (default: 2.0)",
    )
    parser.add_argument(
        "--circuit-breaker-threshold",
        type=int,
        help="override configured consecutive transient-failure threshold",
    )
    parser.add_argument(
        "--circuit-breaker-pause-seconds",
        type=float,
        help="override configured circuit-breaker pause duration",
    )
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
        proxy_url = args.proxy_url
        proxy_urls = None
        if args.proxy_file:
            proxy_urls = load_proxy_file(args.proxy_file)
        elif proxy_url is None:
            proxy_url = os.environ.get("DUKASCOPY_PROXY_URL")
        if proxy_url is not None:
            proxy_url = validate_proxy_url(proxy_url)
        start = parse_utc_boundary(args.start)
        end = parse_utc_boundary(args.end)
        targeted_allowlist_audit = None
        if args.targeted_recovery_report:
            selected_partition_keys, targeted_allowlist_audit = (
                load_targeted_recovery_allowlist(
                    args.targeted_recovery_report,
                    symbol=symbol,
                    start=start,
                    end=end,
                    expected_count=args.targeted_recovery_expected_count,
                )
            )
        else:
            if args.targeted_recovery_expected_count is not None:
                raise ValueError(
                    "--targeted-recovery-expected-count requires "
                    "--targeted-recovery-report"
                )
            selected_partition_keys = None
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
            if targeted_allowlist_audit is not None:
                logger.emit(
                    "info",
                    "targeted_recovery_preflight",
                    **targeted_allowlist_audit,
                )
            summary = download_range(
                config=config,
                symbol=symbol,
                start=start,
                end=end,
                raw_root=raw_root,
                manifest_path=manifest_path,
                mode=args.only,
                dry_run=args.dry_run,
                proxy_url=proxy_url,
                proxy_urls=proxy_urls,
                proxy_rotate_after_failures=args.proxy_rotate_after_failures,
                proxy_cooldown_seconds=args.proxy_cooldown_seconds,
                request_delay_seconds=args.request_delay_seconds,
                circuit_breaker_threshold=args.circuit_breaker_threshold,
                circuit_breaker_pause_seconds=args.circuit_breaker_pause_seconds,
                selected_partition_keys=selected_partition_keys,
                logger=logger,
            )
        return 0 if args.dry_run or summary["unresolved"] == 0 else 2
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print(f"error: {mask_proxy_url(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
