from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import lzma
from pathlib import Path
import struct

import pytest

from scripts import download_dukascopy_ticks as downloader
from scripts import verify_dukascopy_downloads as verifier
from scripts.build_dukascopy_canonical import build_canonical
from scripts.dukascopy_common import (
    EmptyPayloadError,
    MalformedPayloadError,
    Manifest,
    Partition,
    PlaceholderPayloadError,
    StructuredLogger,
    atomic_write_bytes,
    decode_ticks,
    generate_partitions,
    inspect_bi5_payload,
    is_expected_closure,
    load_config,
    parse_utc_boundary,
    partition_file_path,
    partition_url,
    sha256_file,
)
from scripts.download_dukascopy_ticks import (
    HttpResult,
    HttpxTransport,
    ProxyPoolTransport,
    SourceRequestError,
    download_range,
    fetch_with_retry,
    load_targeted_recovery_allowlist,
    load_targeted_recovery_partitions,
    load_proxy_file,
    mask_proxy_url,
)
from scripts.verify_dukascopy_downloads import (
    build_holiday_candidates_report,
    classify_partition,
    verify_range,
)


UTC = timezone.utc
REPOSITORY = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY / "config" / "dukascopy_data.toml"
PROXY_URLS = (
    "http://user-one:password-one@proxy-one.test:8001",
    "http://user-two:password-two@proxy-two.test:8002",
    "http://user-three:password-three@proxy-three.test:8003",
)


def tick_bytes(
    *records: tuple[int, int, int, float, float],
) -> bytes:
    raw = b"".join(struct.pack(">IIIff", *record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def sample_payload() -> bytes:
    return tick_bytes(
        (100, 2_650_250, 2_650_100, 1.25, 2.5),
        (900, 2_650_300, 2_650_150, 1.5, 3.0),
    )


@pytest.fixture
def config():
    loaded = load_config(CONFIG_PATH)
    loaded.download["request_delay_seconds"] = 0.0
    loaded.download["throttle_seconds"] = 0.0
    loaded.download["backoff_initial_seconds"] = 0.0
    loaded.download["backoff_max_seconds"] = 0.0
    return loaded


class SequenceTransport:
    def __init__(self, events):
        self.events = list(events)
        self.calls = 0

    def fetch(self, _url, *, timeout, headers):
        assert timeout > 0
        assert "User-Agent" in headers
        self.calls += 1
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class CapturingLogger:
    def __init__(self):
        self.records: list[dict[str, object]] = []

    def emit(self, level, event, **fields):
        self.records.append({"level": level, "event": event, **fields})


class AdvancingClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class StubProxyClient:
    def __init__(self, proxy_url, events):
        self.proxy_url = proxy_url
        self.events = events
        self.calls = 0
        self.closed = False

    def fetch(self, _url, *, timeout, headers):
        assert timeout > 0
        assert "User-Agent" in headers
        self.calls += 1
        event = self.events[self.proxy_url].pop(0)
        if isinstance(event, BaseException):
            raise event
        return event

    def close(self):
        self.closed = True


class StubProxyFactory:
    def __init__(self, events=None):
        self.events = events or {}
        self.clients: list[StubProxyClient] = []

    def __call__(self, proxy_url):
        client = StubProxyClient(proxy_url, self.events)
        self.clients.append(client)
        return client


def test_httpx_transport_passes_proxy_and_disables_http2(monkeypatch):
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(downloader.httpx, "Client", FakeClient)
    proxy_url = "http://username:password@proxy-host:8080"
    transport = HttpxTransport(proxy_url=proxy_url)
    transport.close()
    assert captured["proxy"] == proxy_url
    assert captured["http2"] is False
    assert captured["follow_redirects"] is True
    assert captured["closed"] is True


def test_httpx_transport_operates_without_proxy(monkeypatch):
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def close(self):
            pass

    monkeypatch.setattr(downloader.httpx, "Client", FakeClient)
    HttpxTransport().close()
    assert captured["proxy"] is None
    assert captured["http2"] is False


def test_proxy_credentials_are_completely_masked_in_diagnostics(monkeypatch):
    proxy_url = "http://sensitive-user:sensitive-password@proxy-host:8080"
    masked = mask_proxy_url(proxy_url)
    assert masked == "http://***:***@proxy-host:8080"
    assert "sensitive-user" not in masked
    assert "sensitive-password" not in masked

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        def get(self, *_args, **_kwargs):
            raise downloader.httpx.ProxyError(f"proxy connection failed: {proxy_url}")

        def close(self):
            pass

    monkeypatch.setattr(downloader.httpx, "Client", FailingClient)
    transport = HttpxTransport(proxy_url=proxy_url)
    with pytest.raises(SourceRequestError) as raised:
        transport.fetch("https://example.invalid", timeout=1, headers={})
    diagnostic = str(raised.value)
    assert "sensitive-user" not in diagnostic
    assert "sensitive-password" not in diagnostic
    assert "http://***:***@proxy-host:8080" in diagnostic


def test_proxy_url_defaults_from_environment(monkeypatch, tmp_path):
    proxy_url = "http://username:password@proxy-host:8080"
    captured: dict[str, object] = {}

    def fake_download_range(**kwargs):
        captured.update(kwargs)
        return {"unresolved": 0}

    monkeypatch.setenv("DUKASCOPY_PROXY_URL", proxy_url)
    monkeypatch.setattr(downloader, "download_range", fake_download_range)
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07",
            "--end",
            "2025-01-08",
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--no-log-file",
            "--quiet",
        ]
    )
    assert code == 0
    assert captured["proxy_url"] == proxy_url
    assert captured["request_delay_seconds"] == 2.0


def test_proxy_url_and_proxy_file_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit):
        downloader.build_parser().parse_args(
            [
                "--symbol",
                "XAUUSD",
                "--start",
                "2025-01-07",
                "--end",
                "2025-01-08",
                "--proxy-url",
                PROXY_URLS[0],
                "--proxy-file",
                "proxies.txt",
            ]
        )
    diagnostics = capsys.readouterr().err
    assert "not allowed with argument" in diagnostics
    assert "user-one" not in diagnostics
    assert "password-one" not in diagnostics


def test_proxy_file_ignores_comments_blanks_and_stably_deduplicates(tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "\n"
        "  # primary pool\n"
        f"  {PROXY_URLS[0]}  \n"
        f"{PROXY_URLS[1]}\n"
        f"{PROXY_URLS[0]}\n"
        "\t\n",
        encoding="utf-8",
    )
    assert load_proxy_file(proxy_file) == [PROXY_URLS[0], PROXY_URLS[1]]


def test_invalid_proxy_file_entry_fails_without_exposing_credentials(tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "not-a-url-with-private-user:private-password@proxy.test\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as raised:
        load_proxy_file(proxy_file)
    diagnostic = str(raised.value)
    assert "line 1" in diagnostic
    assert "private-user" not in diagnostic
    assert "private-password" not in diagnostic


def test_proxy_file_with_no_usable_entries_fails_fast(tmp_path):
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("\n# only a comment\n  # another comment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable proxy URLs"):
        load_proxy_file(proxy_file)


def test_proxy_credentials_do_not_enter_manifest_or_structured_log(tmp_path, config):
    config.download["max_attempts"] = 1
    proxy_url = "http://private-user:private-password@proxy-host:8080"
    log_path = tmp_path / "download.jsonl"
    with StructuredLogger(log_path=log_path, quiet=True) as logger:
        download_range(
            config=config,
            symbol="XAUUSD",
            start=parse_utc_boundary("2025-01-07T00:00:00Z"),
            end=parse_utc_boundary("2025-01-07T01:00:00Z"),
            raw_root=tmp_path / "raw",
            manifest_path=manifest_path(tmp_path),
            transport=SequenceTransport(
                [
                    SourceRequestError(
                        f"proxy connection failed: {proxy_url}", retryable=False
                    )
                ]
            ),
            request_delay_seconds=0,
            sleep=lambda _seconds: None,
            logger=logger,
        )
    diagnostics = manifest_path(tmp_path).read_text() + log_path.read_text()
    assert "private-user" not in diagnostics
    assert "private-password" not in diagnostics
    assert "http://***:***@proxy-host:8080" in diagnostics


def test_proxy_pool_rotates_round_robin_and_closes_replaced_clients():
    logger = CapturingLogger()
    factory = StubProxyFactory()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=0,
        sleep=lambda _seconds: None,
        logger=logger,
        transport_factory=factory,
    )
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    failure = SourceRequestError(
        "HTTP 503", retryable=True, status=503, counts_for_proxy_rotation=True
    )
    assert pool.current_proxy == PROXY_URLS[0]
    pool.record_transient_failure(failure, partition=partition)
    assert pool.current_proxy == PROXY_URLS[1]
    assert factory.clients[0].closed is True
    pool.record_transient_failure(failure, partition=partition)
    assert pool.current_proxy == PROXY_URLS[2]
    assert factory.clients[1].closed is True
    pool.record_transient_failure(failure, partition=partition)
    assert pool.current_proxy == PROXY_URLS[0]
    assert factory.clients[2].closed is True
    assert [record["event"] for record in logger.records] == [
        "proxy_rotation",
        "proxy_rotation",
        "proxy_rotation",
    ]
    pool.close()
    assert factory.clients[-1].closed is True


def test_proxy_pool_stays_on_healthy_proxy_and_success_resets_failures():
    factory = StubProxyFactory()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=300,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    failure = SourceRequestError(
        "read timeout", retryable=True, counts_for_proxy_rotation=True
    )
    assert pool.record_transient_failure(failure, partition=partition) is False
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts[0] == 1
    pool.record_success()
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts[0] == 0
    assert pool.failed_since_success == set()
    assert len(factory.clients) == 1
    pool.close()


def test_proxy_pool_rotates_for_503_and_timeout_failures():
    logger = CapturingLogger()
    factory = StubProxyFactory()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=0,
        logger=logger,
        transport_factory=factory,
    )
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    pool.record_transient_failure(
        SourceRequestError(
            "HTTP 503",
            retryable=True,
            status=503,
            counts_for_proxy_rotation=True,
        ),
        partition=partition,
    )
    assert pool.current_proxy == PROXY_URLS[1]
    pool.record_transient_failure(
        SourceRequestError(
            "network request timed out",
            retryable=True,
            counts_for_proxy_rotation=True,
        ),
        partition=partition,
    )
    assert pool.current_proxy == PROXY_URLS[2]
    pool.close()


def test_proxy_pool_does_not_rotate_for_deterministic_http_4xx():
    factory = StubProxyFactory(
        {
            PROXY_URLS[0]: [HttpResult(404, b"not found", {})],
            PROXY_URLS[1]: [],
            PROXY_URLS[2]: [],
        }
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=0,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    with pytest.raises(SourceRequestError, match="HTTP 404"):
        fetch_with_retry(
            "https://example.invalid/partition",
            transport=pool,
            timeout=1,
            user_agent="test",
            max_attempts=1,
            request_delay=0,
            sleep=lambda _seconds: None,
            logger=StructuredLogger(quiet=True),
            partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
        )
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts == [0, 0, 0]
    pool.close()


def test_proxy_pool_skips_cooling_proxy():
    clock = AdvancingClock()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=300,
        sleep=clock.sleep,
        clock=clock,
        logger=CapturingLogger(),
        transport_factory=StubProxyFactory(),
    )
    pool.cooldown_until[1] = 100.0
    pool.record_transient_failure(
        SourceRequestError(
            "HTTP 503",
            retryable=True,
            status=503,
            counts_for_proxy_rotation=True,
        ),
        partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    assert pool.current_proxy == PROXY_URLS[2]
    assert clock.sleeps == []
    pool.close()


def test_proxy_pool_waits_until_earliest_cooldown_when_all_unavailable():
    clock = AdvancingClock()
    logger = CapturingLogger()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=10,
        sleep=clock.sleep,
        clock=clock,
        logger=logger,
        transport_factory=StubProxyFactory(),
    )
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    failure = SourceRequestError(
        "HTTP 503", retryable=True, status=503, counts_for_proxy_rotation=True
    )
    pool.record_transient_failure(failure, partition=partition)
    pool.record_transient_failure(failure, partition=partition)
    clock.value = 5.0
    pool.record_transient_failure(failure, partition=partition)
    waits = [record for record in logger.records if record["event"] == "proxy_pool_wait"]
    assert clock.sleeps == [5.0]
    assert len(waits) == 1
    assert waits[0]["wait_seconds"] == 5.0
    assert waits[0]["unavailable_proxy_count"] == 3
    assert pool.current_proxy == PROXY_URLS[0]
    pool.close()


def test_proxy_rotation_logs_only_masked_credentials():
    logger = CapturingLogger()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=1,
        cooldown_seconds=0,
        logger=logger,
        transport_factory=StubProxyFactory(),
    )
    pool.record_transient_failure(
        SourceRequestError(
            f"proxy failed: {PROXY_URLS[0]}",
            retryable=True,
            counts_for_proxy_rotation=True,
        ),
        partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    diagnostics = json.dumps(logger.records)
    for secret in (
        "user-one",
        "password-one",
        "user-two",
        "password-two",
    ):
        assert secret not in diagnostics
    assert "http://***:***@proxy-one.test:8001" in diagnostics
    assert "http://***:***@proxy-two.test:8002" in diagnostics
    pool.close()


def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "manifests" / "XAUUSD_ticks_manifest.json"


def write_recovery_report(
    path: Path,
    *,
    start: str,
    end: str,
    groups: dict[str, list[str]],
) -> Path:
    start_dt = parse_utc_boundary(start)
    end_dt = parse_utc_boundary(end)
    unresolved = {
        timestamp for timestamps in groups.values() for timestamp in timestamps
    }
    partitions = [
        {
            "partition_timestamp": partition.key,
            "classification": (
                "unresolved_status"
                if partition.key in unresolved
                else "verified_data"
            ),
        }
        for partition in generate_partitions(start_dt, end_dt)
    ]
    path.write_text(
        json.dumps(
            {
                "symbol": "XAUUSD",
                "range": {
                    "start_inclusive": start,
                    "end_exclusive": end,
                },
                "reconciliation": {
                    "expected_partitions": len(partitions),
                    "verified": len(partitions) - len(unresolved),
                    "expected_market_closures": 0,
                    "missing": 0,
                    "corrupt": 0,
                    "unresolved": len(unresolved),
                    "accounted_partitions": len(partitions),
                    "balanced": True,
                },
                "partitions": partitions,
                "reclassification_audit": {
                    "remaining_unresolved_by_error_kind": groups
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def record_verified_partition(
    *,
    config,
    manifest: Manifest,
    raw_root: Path,
    partition: Partition,
    payload: bytes | None = None,
) -> Path:
    body = payload or sample_payload()
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(raw_file, body)
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source=config.source["id"],
        source_url=partition_url(config, "XAUUSD", partition),
        download_timestamp="2025-01-08T00:00:00Z",
        file_path=str(raw_file),
        byte_size=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        status="verified",
        retry_count=0,
        error_details=None,
        record_count=2,
    )
    return raw_file


def test_url_generation_uses_native_zero_based_month(config):
    partition = Partition(datetime(2024, 2, 29, 7, tzinfo=UTC))
    assert partition_url(config, "XAUUSD", partition) == (
        "https://datafeed.dukascopy.com/datafeed/XAUUSD/2024/01/29/07h_ticks.bi5"
    )
    assert partition_file_path(Path("raw"), "XAUUSD", partition) == Path(
        "raw/XAUUSD/2024/02/29/07h_ticks.bi5"
    )


def test_utc_boundaries_are_inclusive_start_exclusive_end_and_cover_leap_day():
    start = parse_utc_boundary("2024-02-28")
    end = parse_utc_boundary("2024-03-01")
    partitions = generate_partitions(start, end)
    assert len(partitions) == 48
    assert partitions[0].key == "2024-02-28T00:00:00Z"
    assert partitions[-1].key == "2024-02-29T23:00:00Z"
    with pytest.raises(ValueError, match="explicit UTC offset"):
        parse_utc_boundary("2024-02-29T01:00:00")


def test_targeted_recovery_report_loads_every_unresolved_evidence_group(tmp_path):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T03:00:00Z")
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T03:00:00Z",
        groups={
            "ambiguous_closure_evidence": ["2025-01-07T00:00:00Z"],
            "empty_payload_open_market": ["2025-01-07T01:00:00Z"],
            "http_5xx": ["2025-01-07T02:00:00Z"],
        },
    )

    selected, audit = load_targeted_recovery_allowlist(
        path,
        symbol="XAUUSD",
        start=start,
        end=end,
        expected_count=3,
    )

    assert selected == {
        "2025-01-07T00:00:00Z",
        "2025-01-07T01:00:00Z",
        "2025-01-07T02:00:00Z",
    }
    assert audit == {
        "allowlist_count": 3,
        "duplicate_timestamps": 0,
        "timestamps_outside_range": 0,
        "verified_or_confirmed_closure_timestamps_in_allowlist": 0,
        "report_unresolved": 3,
        "expected_allowlist_count": 3,
        "unresolved_groups": {
            "ambiguous_closure_evidence": 1,
            "empty_payload_open_market": 1,
            "http_5xx": 1,
        },
        "ungrouped_unresolved_timestamps": 0,
        "grouped_non_unresolved_timestamps": 0,
    }


def test_targeted_recovery_report_rejects_duplicate_group_timestamps(tmp_path):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T02:00:00Z")
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={
            "timeout": [
                "2025-01-07T00:00:00Z",
                "2025-01-07T00:00:00Z",
            ],
        },
    )

    with pytest.raises(ValueError, match="duplicate_timestamps=1"):
        load_targeted_recovery_allowlist(
            path,
            symbol="XAUUSD",
            start=start,
            end=end,
        )


def test_targeted_recovery_report_rejects_out_of_range_timestamp(tmp_path):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T02:00:00Z")
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={"timeout": ["2025-01-07T02:00:00Z"]},
    )

    with pytest.raises(ValueError, match="timestamps_outside_range=1"):
        load_targeted_recovery_allowlist(
            path,
            symbol="XAUUSD",
            start=start,
            end=end,
        )


def test_targeted_recovery_report_rejects_verified_or_closure_overlap(tmp_path):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T02:00:00Z")
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={"manifest_status_failed": ["2025-01-07T00:00:00Z"]},
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    report["partitions"][0]["classification"] = "expected_market_closure"
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="verified_or_confirmed_closure_timestamps_in_allowlist=1",
    ):
        load_targeted_recovery_allowlist(
            path,
            symbol="XAUUSD",
            start=start,
            end=end,
        )


def test_targeted_recovery_report_rejects_required_count_mismatch(tmp_path):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T02:00:00Z")
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={"connection_error": ["2025-01-07T00:00:00Z"]},
    )

    with pytest.raises(ValueError, match="required count"):
        load_targeted_recovery_allowlist(
            path,
            symbol="XAUUSD",
            start=start,
            end=end,
            expected_count=2,
        )


def test_targeted_recovery_report_rejects_range_mismatch(tmp_path):
    path = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={
            "ambiguous_closure_evidence": ["2025-01-07T00:00:00Z"],
            "empty_payload_open_market": [],
        },
    )

    with pytest.raises(ValueError, match="range must exactly match"):
        load_targeted_recovery_partitions(
            path,
            symbol="XAUUSD",
            start=parse_utc_boundary("2025-01-07T00:00:00Z"),
            end=parse_utc_boundary("2025-01-07T03:00:00Z"),
        )


def test_xauusd_weekend_calendar_is_symbol_specific(config):
    saturday = Partition(datetime(2025, 1, 11, 12, tzinfo=UTC))
    sunday = Partition(datetime(2025, 1, 12, 12, tzinfo=UTC))
    assert is_expected_closure(config, saturday, symbol="XAUUSD") is True
    assert is_expected_closure(config, sunday, symbol="XAUUSD") is True
    assert is_expected_closure(config, saturday, symbol="EURUSD") is False


def test_xauusd_daily_break_matches_only_winter_hour(config):
    winter_break = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    winter_hour_before = Partition(datetime(2025, 1, 7, 21, tzinfo=UTC))
    assert is_expected_closure(config, winter_break, symbol="XAUUSD") is True
    assert is_expected_closure(config, winter_hour_before, symbol="XAUUSD") is False


def test_xauusd_daily_break_matches_only_summer_hour(config):
    summer_break = Partition(datetime(2025, 7, 8, 21, tzinfo=UTC))
    summer_hour_after = Partition(datetime(2025, 7, 8, 22, tzinfo=UTC))
    assert is_expected_closure(config, summer_break, symbol="XAUUSD") is True
    assert is_expected_closure(config, summer_hour_after, symbol="XAUUSD") is False


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (datetime(2025, 3, 28, 22, tzinfo=UTC), True),  # Friday before BST
        (datetime(2025, 3, 31, 21, tzinfo=UTC), True),  # Monday after BST
        (datetime(2025, 3, 31, 22, tzinfo=UTC), False),
        (datetime(2025, 10, 24, 21, tzinfo=UTC), True),  # Friday before GMT
        (datetime(2025, 10, 27, 22, tzinfo=UTC), True),  # Monday after GMT
        (datetime(2025, 10, 27, 21, tzinfo=UTC), False),
    ],
)
def test_xauusd_daily_break_follows_london_dst_boundaries(config, timestamp, expected):
    assert is_expected_closure(
        config, Partition(timestamp), symbol="XAUUSD"
    ) is expected


def test_xauusd_daily_break_rule_does_not_apply_to_other_symbols(config):
    winter_break = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    assert is_expected_closure(config, winter_break, symbol="EURUSD") is False


@pytest.mark.parametrize(
    ("timestamp", "closed"),
    [
        ("2025-01-10T21:00:00Z", False),  # winter Friday pre-close
        ("2025-01-10T22:00:00Z", True),  # winter Friday at/after close
        ("2025-01-11T12:00:00Z", True),  # winter Saturday
        ("2025-01-12T21:00:00Z", True),  # winter Sunday pre-open
        ("2025-01-12T22:00:00Z", False),  # winter Sunday at/after open
        ("2025-07-11T20:00:00Z", False),  # summer Friday pre-close
        ("2025-07-11T21:00:00Z", True),  # summer Friday at/after close
        ("2025-07-12T12:00:00Z", True),  # summer Saturday
        ("2025-07-13T20:00:00Z", True),  # summer Sunday pre-open
        ("2025-07-13T21:00:00Z", False),  # summer Sunday at/after open
        ("2025-02-02T02:00:00Z", True),  # confirmed failed Sunday payload
    ],
)
def test_xauusd_weekly_market_boundaries(config, timestamp, closed):
    assert is_expected_closure(
        config,
        Partition(parse_utc_boundary(timestamp)),
        symbol="XAUUSD",
    ) is closed


@pytest.mark.parametrize(
    ("timestamp", "closed"),
    [
        ("2025-03-28T21:00:00Z", False),  # Friday 21:00 GMT
        ("2025-03-28T22:00:00Z", True),  # Friday close before BST change
        ("2025-03-30T20:00:00Z", True),  # Sunday 21:00 BST
        ("2025-03-30T21:00:00Z", False),  # Sunday reopen after BST change
        ("2025-10-24T20:00:00Z", False),  # Friday 21:00 BST
        ("2025-10-24T21:00:00Z", True),  # Friday close before GMT change
        ("2025-10-26T21:00:00Z", True),  # Sunday 21:00 GMT
        ("2025-10-26T22:00:00Z", False),  # Sunday reopen after GMT change
    ],
)
def test_xauusd_weekly_calendar_follows_dst_transition_weekends(
    config, timestamp, closed
):
    assert is_expected_closure(
        config,
        Partition(parse_utc_boundary(timestamp)),
        symbol="XAUUSD",
    ) is closed


def test_payload_validation_rejects_empty_malformed_and_placeholder(config):
    limit = config.download["max_compressed_bytes"]
    with pytest.raises(EmptyPayloadError):
        inspect_bi5_payload(b"", max_compressed_bytes=limit)
    with pytest.raises(MalformedPayloadError, match="decompression"):
        inspect_bi5_payload(b"not-lzma", max_compressed_bytes=limit)
    with pytest.raises(PlaceholderPayloadError):
        inspect_bi5_payload(b"<!DOCTYPE html><title>404</title>", max_compressed_bytes=limit)
    malformed = lzma.compress(b"123", format=lzma.FORMAT_ALONE)
    with pytest.raises(MalformedPayloadError, match="not divisible"):
        inspect_bi5_payload(malformed, max_compressed_bytes=limit)


def test_binary_decoding_preserves_bid_ask_precision_and_scaling(config):
    partition = Partition(datetime(2025, 1, 7, 1, tzinfo=UTC))
    decoded, count = inspect_bi5_payload(
        sample_payload(), max_compressed_bytes=config.download["max_compressed_bytes"]
    )
    rows = list(decode_ticks(decoded, partition=partition, price_scale=1000))
    assert count == 2
    assert rows[0]["timestamp_ms"] == int(partition.timestamp.timestamp() * 1000) + 100
    assert rows[0]["bid"] == 2650.1
    assert rows[0]["ask"] == 2650.25
    assert rows[0]["bid_volume"] == 2.5
    assert rows[0]["ask_volume"] == 1.25


def test_retry_logic_uses_server_friendly_default_backoff(config):
    transport = SequenceTransport(
        [
            SourceRequestError("temporary", retryable=True),
            SourceRequestError("still temporary", retryable=True),
            SourceRequestError("server still unavailable", retryable=True),
            HttpResult(200, sample_payload(), {}),
        ]
    )
    sleeps: list[float] = []
    result, retries = fetch_with_retry(
        "https://example.invalid/partition",
        transport=transport,
        timeout=1,
        user_agent="test",
        max_attempts=4,
        request_delay=0,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
        partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    assert result.status == 200
    assert retries == 3
    assert sleeps == [15, 60, 300]


def test_request_delay_applies_after_successful_request():
    sleeps: list[float] = []
    result, retries = fetch_with_retry(
        "https://example.invalid/partition",
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        timeout=1,
        user_agent="test",
        max_attempts=4,
        request_delay=2.0,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
        partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    assert result.status == 200
    assert retries == 0
    assert sleeps == [2.0]


def test_non_retryable_http_failure_stops_immediately():
    transport = SequenceTransport([SourceRequestError("HTTP 404", retryable=False)])
    with pytest.raises(SourceRequestError, match="404"):
        fetch_with_retry(
            "https://example.invalid/missing",
            transport=transport,
            timeout=1,
            user_agent="test",
            max_attempts=4,
            backoff_initial=1,
            backoff_max=8,
            throttle=0,
            sleep=lambda _seconds: None,
            logger=StructuredLogger(quiet=True),
            partition=Partition(datetime(2025, 1, 7, tzinfo=UTC)),
        )
    assert transport.calls == 1


def test_download_manifest_atomic_write_and_safe_resume(tmp_path, config):
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    transport = SequenceTransport([HttpResult(200, sample_payload(), {})])
    kwargs = dict(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=raw_root,
        manifest_path=path,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    first = download_range(transport=transport, **kwargs)
    second_transport = SequenceTransport([])
    second = download_range(transport=second_transport, **kwargs)
    payload = json.loads(path.read_text())
    entry = payload["partitions"]["2025-01-07T00:00:00Z"]
    raw_file = partition_file_path(
        raw_root, "XAUUSD", Partition(datetime(2025, 1, 7, tzinfo=UTC))
    )
    assert first["downloaded"] == 1
    assert second["resumed_verified"] == 1
    assert second_transport.calls == 0
    assert entry["status"] == "verified"
    assert entry["byte_size"] == raw_file.stat().st_size
    assert entry["sha256"] == sha256_file(raw_file)
    assert entry["record_count"] == 2
    assert not list(raw_file.parent.glob("*.tmp"))


def test_existing_valid_file_is_recovered_without_network(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(raw_file, sample_payload())
    transport = SequenceTransport([])
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=datetime(2025, 1, 7, 1, tzinfo=UTC),
        raw_root=raw_root,
        manifest_path=manifest_path(tmp_path),
        transport=transport,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["recovered_existing"] == 1
    assert summary["unresolved"] == 0
    assert transport.calls == 0


def test_checksum_drift_requires_source_redownload_not_local_adoption(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=datetime(2025, 1, 7, 1, tzinfo=UTC),
        raw_root=raw_root,
        manifest_path=path,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    download_range(
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]), **common
    )
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    different_valid_payload = tick_bytes((50, 2_640_100, 2_640_000, 1.0, 2.0))
    atomic_write_bytes(raw_file, different_valid_payload)
    source_transport = SequenceTransport([HttpResult(200, sample_payload(), {})])
    summary = download_range(transport=source_transport, **common)
    assert source_transport.calls == 1
    assert summary["downloaded"] == 1
    assert raw_file.read_bytes() == sample_payload()


def test_empty_response_is_failed_not_market_closure(tmp_path, config):
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=SequenceTransport([HttpResult(200, b"", {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    entry = json.loads(manifest_path(tmp_path).read_text())["partitions"][
        "2025-01-07T00:00:00Z"
    ]
    assert summary["failed"] == 1
    assert summary["unresolved"] == 1
    assert entry["status"] == "failed"
    assert "empty_payload" in entry["error_details"]
    assert entry["evidence_kind"] == "confirmed_empty_payload"
    assert entry["http_status"] == 200
    assert entry["response_byte_length"] == 0
    assert entry["retry_count"] == 0
    assert entry["proxy_identity_masked"] == "direct"
    assert entry["final_attempt_timestamp"]


def test_expected_closure_does_not_change_proxy_health(tmp_path, config):
    factory = StubProxyFactory(
        {
            PROXY_URLS[0]: [HttpResult(200, b"", {})],
            PROXY_URLS[1]: [],
            PROXY_URLS[2]: [],
        }
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=300,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    pool.failure_counts[0] = 1
    pool.failed_since_success.add(0)
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T22:00:00Z"),
        end=parse_utc_boundary("2025-01-07T23:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=pool,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["expected_market_closures"] == 1
    assert summary["failed"] == 0
    assert factory.clients[0].calls == 1
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts[0] == 1
    assert pool.failed_since_success == {0}
    entry = json.loads(manifest_path(tmp_path).read_text())["partitions"][
        "2025-01-07T22:00:00Z"
    ]
    assert entry["evidence_kind"] == "confirmed_empty_payload"
    assert entry["http_status"] == 200
    assert entry["response_byte_length"] == 0
    assert entry["proxy_identity_masked"] == (
        "http://***:***@proxy-one.test:8001"
    )
    pool.close()


def test_decode_error_does_not_change_proxy_health(tmp_path, config):
    malformed = lzma.compress(b"not-a-20-byte-record", format=lzma.FORMAT_ALONE)
    factory = StubProxyFactory(
        {
            PROXY_URLS[0]: [HttpResult(200, malformed, {})],
            PROXY_URLS[1]: [],
            PROXY_URLS[2]: [],
        }
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=300,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    pool.failure_counts[0] = 1
    pool.failed_since_success.add(0)
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=pool,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["failed"] == 1
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts[0] == 1
    assert pool.failed_since_success == {0}
    entry = json.loads(manifest_path(tmp_path).read_text())["partitions"][
        "2025-01-07T00:00:00Z"
    ]
    assert entry["evidence_kind"] == "malformed_non_empty_payload"
    assert entry["http_status"] == 200
    assert entry["response_byte_length"] == len(malformed)
    assert entry["proxy_identity_masked"] == (
        "http://***:***@proxy-one.test:8001"
    )
    pool.close()


def test_filesystem_error_does_not_change_proxy_health(
    monkeypatch, tmp_path, config
):
    factory = StubProxyFactory(
        {
            PROXY_URLS[0]: [HttpResult(200, sample_payload(), {})],
            PROXY_URLS[1]: [],
            PROXY_URLS[2]: [],
        }
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=300,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    pool.failure_counts[0] = 1
    pool.failed_since_success.add(0)
    monkeypatch.setattr(
        downloader,
        "atomic_write_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=pool,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["failed"] == 1
    assert pool.current_proxy == PROXY_URLS[0]
    assert pool.failure_counts[0] == 1
    assert pool.failed_since_success == {0}
    pool.close()


def test_failed_or_missing_selection_redrives_failed_partition(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    download_range(
        transport=SequenceTransport([SourceRequestError("HTTP 404", retryable=False)]),
        **common,
    )
    summary = download_range(
        mode="failed-or-missing",
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        **common,
    )
    assert summary["downloaded"] == 1
    assert summary["unresolved"] == 0


def test_circuit_breaker_pauses_after_five_transient_partition_failures(
    tmp_path, config
):
    config.download["max_attempts"] = 1
    sleeps: list[float] = []
    transport = SequenceTransport(
        [SourceRequestError("stream reset", retryable=True) for _ in range(5)]
    )
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T05:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=transport,
        request_delay_seconds=0,
        circuit_breaker_threshold=5,
        circuit_breaker_pause_seconds=900,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["failed"] == 5
    assert summary["unresolved"] == 5
    assert transport.calls == 5
    assert sleeps == [900]


def test_circuit_breaker_counter_resets_after_successful_download(tmp_path, config):
    config.download["max_attempts"] = 1
    sleeps: list[float] = []
    events = [
        SourceRequestError("timeout", retryable=True),
        HttpResult(200, sample_payload(), {}),
        *[SourceRequestError("stream reset", retryable=True) for _ in range(4)],
    ]
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T06:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=SequenceTransport(events),
        request_delay_seconds=0,
        circuit_breaker_threshold=5,
        circuit_breaker_pause_seconds=900,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["downloaded"] == 1
    assert summary["failed"] == 5
    assert sleeps == []


def test_circuit_breaker_counter_resets_after_expected_closure(tmp_path, config):
    config.download["max_attempts"] = 1
    sleeps: list[float] = []
    transport = SequenceTransport(
        [SourceRequestError("timeout", retryable=True) for _ in range(4)]
        + [HttpResult(200, b"", {})]
        + [SourceRequestError("timeout", retryable=True) for _ in range(4)]
    )
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T18:00:00Z"),
        end=parse_utc_boundary("2025-01-08T03:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=transport,
        request_delay_seconds=0,
        circuit_breaker_threshold=5,
        circuit_breaker_pause_seconds=900,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["expected_market_closures"] == 1
    assert summary["failed"] == 8
    assert transport.calls == 9
    assert sleeps == []


def test_pool_circuit_breaker_waits_for_failures_across_available_pool(
    tmp_path, config
):
    config.download["max_attempts"] = 1
    transient = lambda label: SourceRequestError(
        label, retryable=True, counts_for_proxy_rotation=True
    )
    factory = StubProxyFactory(
        {
            PROXY_URLS[0]: [transient("p1 timeout"), transient("p1 reset")],
            PROXY_URLS[1]: [transient("p2 timeout"), transient("p2 reset")],
            PROXY_URLS[2]: [transient("p3 timeout")],
        }
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=0,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    sleeps: list[float] = []
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T05:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=pool,
        request_delay_seconds=0,
        circuit_breaker_threshold=5,
        circuit_breaker_pause_seconds=900,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
    )
    assert summary["failed"] == 5
    assert pool.failures_span_pool is True
    assert sleeps == [900]
    pool.close()


def test_pool_defers_global_circuit_breaker_while_healthy_candidates_remain(
    tmp_path, config
):
    config.download["max_attempts"] = 1
    events = [
        SourceRequestError(
            "p1 timeout", retryable=True, counts_for_proxy_rotation=True
        )
        for _ in range(5)
    ]
    factory = StubProxyFactory(
        {PROXY_URLS[0]: events, PROXY_URLS[1]: [], PROXY_URLS[2]: []}
    )
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=10,
        cooldown_seconds=0,
        logger=CapturingLogger(),
        transport_factory=factory,
    )
    sleeps: list[float] = []
    download_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T05:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        transport=pool,
        request_delay_seconds=0,
        circuit_breaker_threshold=5,
        circuit_breaker_pause_seconds=900,
        sleep=sleeps.append,
        logger=StructuredLogger(quiet=True),
    )
    assert pool.failures_span_pool is False
    assert pool.current_proxy == PROXY_URLS[0]
    assert sleeps == []
    pool.close()


def test_three_proxy_mocked_integration_rotates_then_downloads_once(
    tmp_path, config
):
    config.download["max_attempts"] = 5
    events = {
        PROXY_URLS[0]: [
            HttpResult(503, b"service unavailable", {}),
            HttpResult(503, b"service unavailable", {}),
        ],
        PROXY_URLS[1]: [
            SourceRequestError(
                "connect timeout", retryable=True, counts_for_proxy_rotation=True
            ),
            SourceRequestError(
                "read timeout", retryable=True, counts_for_proxy_rotation=True
            ),
        ],
        PROXY_URLS[2]: [HttpResult(200, sample_payload(), {})],
    }
    factory = StubProxyFactory(events)
    logger = CapturingLogger()
    pool = ProxyPoolTransport(
        PROXY_URLS,
        rotate_after_failures=2,
        cooldown_seconds=0,
        logger=logger,
        transport_factory=factory,
    )
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        request_delay_seconds=0,
        retry_backoff_seconds=(0,),
        sleep=lambda _seconds: None,
    )
    first = download_range(transport=pool, logger=logger, **common)
    raw_file = partition_file_path(
        tmp_path / "raw",
        "XAUUSD",
        Partition(datetime(2025, 1, 7, tzinfo=UTC)),
    )
    manifest_payload = json.loads(manifest_path(tmp_path).read_text())
    assert first["downloaded"] == 1
    assert first["failed"] == 0
    assert first["unresolved"] == 0
    assert first["total_retries"] == 4
    assert first["proxy_failure_events"] == 4
    assert first["proxy_rotations"] == 2
    assert raw_file.read_bytes() == sample_payload()
    assert len(manifest_payload["partitions"]) == 1
    recovered_entry = manifest_payload["partitions"]["2025-01-07T00:00:00Z"]
    assert recovered_entry["status"] == "verified"
    assert recovered_entry["proxy_identity_masked"] == (
        "http://***:***@proxy-three.test:8003"
    )
    rotations = [record for record in logger.records if record["event"] == "proxy_rotation"]
    assert len(rotations) == 2
    diagnostics = json.dumps(logger.records)
    for secret in (
        "user-one",
        "password-one",
        "user-two",
        "password-two",
        "user-three",
        "password-three",
    ):
        assert secret not in diagnostics
    pool.close()

    resume_transport = SequenceTransport([])
    resumed = download_range(
        mode="failed-or-missing",
        transport=resume_transport,
        logger=StructuredLogger(quiet=True),
        **common,
    )
    assert resumed["resumed_verified"] == 1
    assert resumed["downloaded"] == 0
    assert resume_transport.calls == 0


def test_http_503_during_break_remains_failed_and_unresolved(tmp_path, config):
    config.download["max_attempts"] = 1
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        retry_count=0,
        error_details="SourceRequestError: HTTP 503",
    )
    manifest.save()
    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=parse_utc_boundary("2025-01-07T23:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
        transport=SequenceTransport(
            [HttpResult(503, b"service unavailable", {})]
        ),
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    entry = json.loads(path.read_text())["partitions"][partition.key]
    verified = classify_partition(
        config=config,
        manifest=Manifest(path, config=config, symbol="XAUUSD"),
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )
    assert summary["failed"] == 1
    assert summary["expected_market_closures"] == 0
    assert summary["unresolved"] == 1
    assert entry["status"] == "failed"
    assert "HTTP 503" in entry["error_details"]
    assert entry["evidence_kind"] == "http_error"
    assert entry["http_status"] == 503
    assert entry["response_byte_length"] == len(b"service unavailable")
    assert entry["proxy_identity_masked"] == "direct"
    assert verified["classification"] == "unresolved_status"


def test_successful_resume_after_transient_partition_failure(tmp_path, config):
    config.download["max_attempts"] = 1
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    common = dict(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=tmp_path / "raw",
        manifest_path=manifest_path(tmp_path),
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    first = download_range(
        transport=SequenceTransport(
            [SourceRequestError("network timeout", retryable=True)]
        ),
        **common,
    )
    second = download_range(
        mode="failed-or-missing",
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        **common,
    )
    entry = json.loads(manifest_path(tmp_path).read_text())["partitions"][
        "2025-01-07T00:00:00Z"
    ]
    assert first["failed"] == 1
    assert first["unresolved"] == 1
    assert second["downloaded"] == 1
    assert second["unresolved"] == 0
    assert entry["status"] == "verified"


def test_targeted_recovery_requests_only_allowlisted_unresolved_partition(
    tmp_path, config
):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T03:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    verified_partition = Partition(start)
    verified_file = record_verified_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        partition=verified_partition,
    )
    ambiguous = Partition(parse_utc_boundary("2025-01-07T01:00:00Z"))
    manifest.record(
        ambiguous,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="expected_market_closure",
        error_details=(
            "matched configured closure rule with missing or explicit no-data evidence"
        ),
    )
    excluded = Partition(parse_utc_boundary("2025-01-07T02:00:00Z"))
    manifest.record(
        excluded,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()
    original_verified = verified_file.read_bytes()
    transport = SequenceTransport(
        [
            HttpResult(
                200,
                sample_payload(),
                {},
                proxy_identity_masked="http://***:***@proxy.test:8000",
            )
        ]
    )

    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        selected_partition_keys={ambiguous.key},
        transport=transport,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        now=lambda: datetime(2025, 1, 8, tzinfo=UTC),
        logger=StructuredLogger(quiet=True),
    )
    payload = json.loads(path.read_text())["partitions"]

    assert transport.calls == 1
    assert verified_file.read_bytes() == original_verified
    assert payload[verified_partition.key]["status"] == "verified"
    assert payload[ambiguous.key]["status"] == "verified"
    assert payload[ambiguous.key]["evidence_kind"] == "valid_bi5_payload"
    assert payload[ambiguous.key]["http_status"] == 200
    assert payload[ambiguous.key]["response_byte_length"] == len(sample_payload())
    assert payload[ambiguous.key]["proxy_identity_masked"] == (
        "http://***:***@proxy.test:8000"
    )
    assert payload[ambiguous.key]["final_attempt_timestamp"] == (
        "2025-01-08T00:00:00Z"
    )
    assert payload[excluded.key]["status"] == "failed"
    assert summary["targeted_partitions"] == 1
    assert summary["attempted_partitions"] == 1
    assert summary["not_selected"] == 2
    assert summary["downloaded"] == 1


def test_targeted_recovery_resumes_without_requesting_newly_verified_file(
    tmp_path, config
):
    config.download["max_attempts"] = 1
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T02:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    selected = {
        "2025-01-07T00:00:00Z",
        "2025-01-07T01:00:00Z",
    }
    first_transport = SequenceTransport(
        [
            HttpResult(200, sample_payload(), {}),
            SourceRequestError(
                "network request timed out",
                retryable=True,
                proxy_identity_masked="http://***:***@proxy.test:8000",
                evidence_kind="timeout",
            ),
        ]
    )
    first = download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        selected_partition_keys=selected,
        transport=first_transport,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    first_file = partition_file_path(
        raw_root, "XAUUSD", Partition(start)
    )
    first_hash = sha256_file(first_file)
    failed_entry = json.loads(path.read_text())["partitions"][
        "2025-01-07T01:00:00Z"
    ]
    assert failed_entry["evidence_kind"] == "timeout"
    assert failed_entry["http_status"] is None
    assert failed_entry["response_byte_length"] is None
    assert failed_entry["retry_count"] == 0
    assert failed_entry["proxy_identity_masked"] == (
        "http://***:***@proxy.test:8000"
    )
    assert failed_entry["final_attempt_timestamp"]
    second_transport = SequenceTransport(
        [HttpResult(200, sample_payload(), {})]
    )

    second = download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        selected_partition_keys=selected,
        transport=second_transport,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )

    assert first["downloaded"] == 1
    assert first["failed"] == 1
    assert second_transport.calls == 1
    assert second["resumed_verified"] == 1
    assert second["downloaded"] == 1
    assert second["unresolved"] == 0
    assert sha256_file(first_file) == first_hash


def test_checksum_verification_detects_corruption(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        transport=SequenceTransport([HttpResult(200, sample_payload(), {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    raw_file = next(raw_root.rglob("*.bi5"))
    atomic_write_bytes(raw_file, sample_payload() + b"tampered")
    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
    )
    assert report["counts"]["corrupt_partition"] == 1
    assert report["counts"]["unresolved"] == 1


def test_verifier_detects_checksum_valid_but_malformed_payload(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    malformed = lzma.compress(b"not-a-20-byte-record", format=lzma.FORMAT_ALONE)
    atomic_write_bytes(raw_file, malformed)
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        archive_symbol="XAUUSD",
        source=config.source["id"],
        source_url=partition_url(config, "XAUUSD", partition),
        download_timestamp="2025-01-08T00:00:00Z",
        file_path=str(raw_file),
        byte_size=len(malformed),
        sha256=hashlib.sha256(malformed).hexdigest(),
        status="verified",
        retry_count=0,
        error_details=None,
        record_count=None,
    )
    manifest.save()
    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )
    assert result["classification"] == "malformed_payload"


def test_malformed_non_empty_payload_during_daily_break_remains_malformed(
    tmp_path, config
):
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    malformed = lzma.compress(b"not-a-20-byte-record", format=lzma.FORMAT_ALONE)
    atomic_write_bytes(raw_file, malformed)
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=str(raw_file),
        byte_size=len(malformed),
        sha256=hashlib.sha256(malformed).hexdigest(),
        status="verified",
        error_details=None,
    )
    manifest.save()
    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )
    assert result["closure_rule_matched"] is True
    assert result["classification"] == "malformed_payload"


def test_daily_break_requires_no_data_evidence_not_http_failure(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="SourceRequestError: HTTP 500",
    )
    manifest.save()
    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )
    assert result["closure_rule_matched"] is True
    assert result["classification"] == "unresolved_status"


def test_daily_break_accepts_recorded_empty_payload(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()
    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )
    assert result["classification"] == "expected_market_closure"
    assert result["closure_evidence"] == "empty_payload"


def test_confirmed_sunday_empty_payload_is_expected_closure(tmp_path, config):
    partition = Partition(datetime(2025, 2, 2, 2, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["closure_rule_matched"] is True
    assert result["closure_rule"]["rule_type"] == "symbol_weekly_market_close"
    assert result["classification"] == "expected_market_closure"
    assert result["closure_evidence"] == "empty_payload"


def test_downloader_reclassifies_preserved_sunday_empty_without_request(
    tmp_path, config
):
    partition = Partition(datetime(2025, 2, 2, 2, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
        retry_count=0,
        download_timestamp="2025-02-03T00:00:00Z",
    )
    manifest.save()
    transport = SequenceTransport([])

    summary = download_range(
        config=config,
        symbol="XAUUSD",
        start=partition.timestamp,
        end=parse_utc_boundary("2025-02-02T03:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
        mode="failed-or-missing",
        transport=transport,
        request_delay_seconds=0,
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    updated = json.loads(path.read_text())["partitions"][partition.key]

    assert transport.calls == 0
    assert summary["expected_market_closures"] == 1
    assert summary["unresolved"] == 0
    assert updated["status"] == "expected_market_closure"
    assert updated["error_details"] == "empty_payload: compressed response is empty"


@pytest.mark.parametrize(
    "error_details",
    [
        "SourceRequestError: HTTP 503: Service Unavailable",
        "SourceRequestError: network request timed out",
    ],
)
def test_sunday_source_failures_remain_unresolved(
    tmp_path, config, error_details
):
    partition = Partition(datetime(2025, 2, 2, 2, tzinfo=UTC))
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details=error_details,
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["closure_rule_matched"] is True
    assert result["classification"] == "unresolved_status"
    assert result["closure_evidence"] is None


def test_open_hour_empty_payload_remains_unresolved(tmp_path, config):
    partition = Partition(datetime(2025, 2, 2, 22, tzinfo=UTC))
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["closure_rule_matched"] is False
    assert result["classification"] == "unresolved_status"


def test_offline_reclassification_audit_groups_remaining_errors(tmp_path, config):
    start = parse_utc_boundary("2025-02-02T20:00:00Z")
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    records = {
        "2025-02-02T20:00:00Z": "empty_payload: compressed response is empty",
        "2025-02-02T21:00:00Z": "SourceRequestError: HTTP 503",
        "2025-02-02T22:00:00Z": "empty_payload: compressed response is empty",
    }
    for timestamp, error_details in records.items():
        manifest.record(
            Partition(parse_utc_boundary(timestamp)),
            file_path=None,
            byte_size=None,
            sha256=None,
            status="failed",
            error_details=error_details,
        )
    manifest.save()

    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=parse_utc_boundary("2025-02-02T23:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
        reclassification_audit=True,
    )
    audit = report["reclassification_audit"]

    assert report["reconciliation"] == {
        "expected_partitions": 3,
        "verified": 0,
        "expected_market_closures": 1,
        "missing": 0,
        "corrupt": 0,
        "unresolved": 2,
        "accounted_partitions": 3,
        "balanced": True,
    }
    assert audit["manifest_mutated"] is False
    assert audit["empty_payload_entries_evaluated"] == 2
    assert audit["reclassified_from_unresolved_to_expected_market_closure"] == 1
    assert audit["remaining_unresolved_by_error_kind"] == {
        "empty_payload_open_market": ["2025-02-02T22:00:00Z"],
        "http_5xx": ["2025-02-02T21:00:00Z"],
    }
    holiday_candidates = build_holiday_candidates_report(report)
    assert holiday_candidates["count"] == 1
    assert holiday_candidates["candidates"][0]["partition_timestamp"] == (
        "2025-02-02T22:00:00Z"
    )


def test_verifier_does_not_treat_a_silent_calendar_gap_as_closure(tmp_path, config):
    empty_manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    empty_manifest.save()
    saturday = Partition(datetime(2025, 1, 11, 12, tzinfo=UTC))
    monday = Partition(datetime(2025, 1, 13, 12, tzinfo=UTC))
    closure = classify_partition(
        config=config,
        manifest=empty_manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=saturday,
    )
    missing = classify_partition(
        config=config,
        manifest=empty_manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=monday,
    )
    assert closure["closure_rule_matched"] is True
    assert closure["classification"] == "missing_partition"
    assert missing["classification"] == "missing_partition"


def test_verifier_reconciles_every_hour_without_silent_gaps(tmp_path, config):
    start = parse_utc_boundary("2025-01-07T21:00:00Z")
    end = parse_utc_boundary("2025-01-08T00:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    record_verified_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        partition=Partition(start),
    )
    closure = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    manifest.record(
        closure,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()

    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        generated_at=datetime(2025, 1, 8, tzinfo=UTC),
    )

    assert [item["partition_timestamp"] for item in report["partitions"]] == [
        "2025-01-07T21:00:00Z",
        "2025-01-07T22:00:00Z",
        "2025-01-07T23:00:00Z",
    ]
    assert report["reconciliation"] == {
        "expected_partitions": 3,
        "verified": 1,
        "expected_market_closures": 1,
        "missing": 1,
        "corrupt": 0,
        "unresolved": 0,
        "accounted_partitions": 3,
        "balanced": True,
    }
    assert report["counts"]["unresolved"] == 1


@pytest.mark.parametrize("record_count", [None, -1, 1, True])
def test_verified_partition_requires_plausible_matching_record_count(
    tmp_path, config, record_count
):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    record_verified_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        partition=partition,
    )
    manifest.get(partition)["record_count"] = record_count
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["classification"] == "unresolved_status"
    assert "record_count" in result["details"]


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("byte_size", -1, "byte_size"),
        ("byte_size", 999, "file size"),
        ("sha256", None, "SHA-256"),
        ("file_path", "elsewhere/00h_ticks.bi5", "file_path"),
        (
            "partition_timestamp",
            "2025-01-07T01:00:00Z",
            "partition_timestamp",
        ),
    ],
)
def test_verifier_detects_manifest_file_metadata_inconsistencies(
    tmp_path, config, field, value, detail
):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    record_verified_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        partition=partition,
    )
    manifest.get(partition)[field] = value
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["classification"] == "unresolved_status"
    assert detail in result["details"]


def test_verified_manifest_entry_with_missing_bi5_is_missing(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    raw_file = partition_file_path(tmp_path / "raw", "XAUUSD", partition)
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=str(raw_file),
        byte_size=100,
        sha256="0" * 64,
        status="verified",
        error_details=None,
        record_count=2,
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["classification"] == "missing_partition"
    assert "unavailable" in result["details"]


def test_duplicate_json_partition_key_is_reported_and_reconciled(tmp_path, config):
    path = manifest_path(tmp_path)
    path.parent.mkdir(parents=True)
    duplicate_key = "2025-01-07T00:00:00Z"
    path.write_text(
        "{"
        '"symbol":"XAUUSD",'
        '"partitions":{'
        f'"{duplicate_key}":{{"partition_timestamp":"{duplicate_key}"}},'
        f'"{duplicate_key}":{{"partition_timestamp":"{duplicate_key}"}}'
        "}"
        "}",
        encoding="utf-8",
    )

    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
    )

    assert report["manifest_errors"][0]["type"] == "duplicate_json_key"
    assert report["manifest_errors"][0]["key"] == duplicate_key
    assert report["reconciliation"]["unresolved"] == 1
    assert report["reconciliation"]["balanced"] is True


def test_duplicate_declared_partition_timestamp_is_reported(tmp_path, config):
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    first = Partition(datetime(2025, 1, 7, tzinfo=UTC))
    second = Partition(datetime(2025, 1, 7, 1, tzinfo=UTC))
    manifest.record(first, status="missing", file_path=None)
    manifest.record(
        second,
        partition_timestamp=first.key,
        status="missing",
        file_path=None,
    )
    manifest.save()

    report = verify_range(
        config=config,
        symbol="XAUUSD",
        start=first.timestamp,
        end=parse_utc_boundary("2025-01-07T02:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
    )

    assert report["manifest_errors"][0]["type"] == "duplicate_partition_timestamp"
    assert report["reconciliation"]["unresolved"] == 2
    assert report["reconciliation"]["accounted_partitions"] == 2


@pytest.mark.parametrize(
    "failure",
    [
        "SourceRequestError: HTTP 429",
        "SourceRequestError: HTTP 503",
        "network request timed out",
        "proxy failed: connection refused",
        "TLS/SSL handshake failed",
        "connection reset by peer",
        "decode failed: LZMA stream corrupt",
        "missing file",
    ],
)
def test_failures_during_a_calendar_break_never_become_closures(
    tmp_path, config, failure
):
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details=failure,
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=tmp_path / "raw",
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["closure_rule_matched"] is True
    assert result["classification"] == "unresolved_status"


def test_empty_payload_outside_calendar_is_malformed(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, 21, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(raw_file, b"")
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=str(raw_file),
        byte_size=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["closure_rule_matched"] is False
    assert result["classification"] == "malformed_payload"


def test_http_failure_with_empty_file_during_break_is_not_closure(tmp_path, config):
    partition = Partition(datetime(2025, 1, 7, 22, tzinfo=UTC))
    raw_root = tmp_path / "raw"
    raw_file = partition_file_path(raw_root, "XAUUSD", partition)
    atomic_write_bytes(raw_file, b"")
    manifest = Manifest(manifest_path(tmp_path), config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=str(raw_file),
        byte_size=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        status="failed",
        error_details="SourceRequestError: HTTP 503",
    )
    manifest.save()

    result = classify_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        symbol="XAUUSD",
        partition=partition,
    )

    assert result["classification"] == "malformed_payload"


def test_verifier_cli_prints_reconciliation_and_exits_nonzero_for_gap(
    tmp_path, capsys
):
    code = verifier.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--raw-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--json-report",
            str(tmp_path / "report.json"),
            "--markdown-report",
            str(tmp_path / "report.md"),
        ]
    )
    output = capsys.readouterr().out

    assert code == 2
    assert (
        "expected_partitions=1 = verified=0 + expected_market_closures=0 + "
        "missing=1 + corrupt=0 + unresolved=0"
    ) in output
    assert "accounted=1 balanced=true" in output


def test_verifier_cli_exits_zero_for_fully_verified_range(tmp_path, config, capsys):
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    record_verified_partition(
        config=config,
        manifest=manifest,
        raw_root=raw_root,
        partition=Partition(start),
    )
    manifest.save()

    code = verifier.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--raw-root",
            str(raw_root),
            "--manifest",
            str(path),
            "--json-report",
            str(tmp_path / "report.json"),
            "--markdown-report",
            str(tmp_path / "report.md"),
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "expected_partitions=1 = verified=1" in output
    assert "missing=0 + corrupt=0 + unresolved=0" in output


def test_verifier_cli_reclassification_is_offline_and_report_only(
    tmp_path, config, capsys
):
    partition = Partition(datetime(2025, 2, 2, 2, tzinfo=UTC))
    path = manifest_path(tmp_path)
    manifest = Manifest(path, config=config, symbol="XAUUSD")
    manifest.record(
        partition,
        file_path=None,
        byte_size=None,
        sha256=None,
        status="failed",
        error_details="empty_payload: compressed response is empty",
    )
    manifest.save()
    original_manifest = path.read_bytes()
    json_report = tmp_path / "audit.json"

    code = verifier.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            partition.key,
            "--end",
            "2025-02-02T03:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--raw-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(path),
            "--json-report",
            str(json_report),
            "--markdown-report",
            str(tmp_path / "audit.md"),
            "--reclassify-empty-closures",
        ]
    )
    output = capsys.readouterr().out
    report = json.loads(json_report.read_text())

    assert code == 0
    assert path.read_bytes() == original_manifest
    assert "mode=offline_report_only manifest_mutated=false" in output
    assert (
        report["reclassification_audit"][
            "reclassified_from_unresolved_to_expected_market_closure"
        ]
        == 1
    )


def test_atomic_write_leaves_complete_target_and_no_temporary_file(tmp_path):
    destination = tmp_path / "nested" / "result.bin"
    atomic_write_bytes(destination, b"first")
    atomic_write_bytes(destination, b"second")
    assert destination.read_bytes() == b"second"
    assert list(destination.parent.glob("*.tmp")) == []


def test_cli_returns_nonzero_when_unresolved_failures_remain(monkeypatch, tmp_path):
    monkeypatch.setattr(
        downloader,
        "download_range",
        lambda **_kwargs: {"unresolved": 1},
    )
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--no-log-file",
            "--quiet",
        ]
    )
    assert code == 2


def test_cli_passes_explicit_proxy_and_request_delay(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_download_range(**kwargs):
        captured.update(kwargs)
        return {"unresolved": 0}

    monkeypatch.setattr(downloader, "download_range", fake_download_range)
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--proxy-url",
            "http://username:password@proxy-host:8080",
            "--request-delay-seconds",
            "4.5",
            "--no-log-file",
            "--quiet",
        ]
    )
    assert code == 0
    assert captured["proxy_url"] == "http://username:password@proxy-host:8080"
    assert captured["request_delay_seconds"] == 4.5


def test_cli_passes_exact_targeted_recovery_allowlist(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    report = write_recovery_report(
        tmp_path / "audit.json",
        start="2025-01-07T00:00:00Z",
        end="2025-01-07T02:00:00Z",
        groups={
            "ambiguous_closure_evidence": ["2025-01-07T00:00:00Z"],
            "empty_payload_open_market": ["2025-01-07T01:00:00Z"],
        },
    )

    def fake_download_range(**kwargs):
        captured.update(kwargs)
        return {"unresolved": 0}

    monkeypatch.setattr(downloader, "download_range", fake_download_range)
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T02:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--targeted-recovery-report",
            str(report),
            "--no-log-file",
            "--quiet",
        ]
    )

    assert code == 0
    assert captured["selected_partition_keys"] == {
        "2025-01-07T00:00:00Z",
        "2025-01-07T01:00:00Z",
    }


def test_cli_loads_proxy_file_and_passes_pool_settings(monkeypatch, tmp_path):
    captured: dict[str, object] = {}
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("\n".join(PROXY_URLS) + "\n", encoding="utf-8")

    def fake_download_range(**kwargs):
        captured.update(kwargs)
        return {"unresolved": 0}

    monkeypatch.setattr(downloader, "download_range", fake_download_range)
    code = downloader.main(
        [
            "--symbol",
            "XAUUSD",
            "--start",
            "2025-01-07T00:00:00Z",
            "--end",
            "2025-01-07T01:00:00Z",
            "--config",
            str(CONFIG_PATH),
            "--output-root",
            str(tmp_path / "raw"),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--proxy-file",
            str(proxy_file),
            "--proxy-rotate-after-failures",
            "3",
            "--proxy-cooldown-seconds",
            "45",
            "--no-log-file",
            "--quiet",
        ]
    )
    assert code == 0
    assert captured["proxy_url"] is None
    assert captured["proxy_urls"] == list(PROXY_URLS)
    assert captured["proxy_rotate_after_failures"] == 3
    assert captured["proxy_cooldown_seconds"] == 45.0


def test_canonical_quality_checks_and_deterministic_output(tmp_path, config):
    pytest.importorskip("pyarrow")
    start = parse_utc_boundary("2025-01-07T00:00:00Z")
    end = parse_utc_boundary("2025-01-07T01:00:00Z")
    payload = tick_bytes(
        (1000, 2_650_100, 2_650_000, 1.0, 2.0),
        (500, 2_649_000, 2_650_000, 1.5, 2.5),  # non-monotonic and crossed
        (500, 2_649_000, 2_650_000, 1.5, 2.5),  # exact duplicate
        (2_000, 2_660_000, 2_650_000, 2.0, 3.0),  # implausible spread
    )
    raw_root = tmp_path / "raw"
    path = manifest_path(tmp_path)
    download_range(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        transport=SequenceTransport([HttpResult(200, payload, {})]),
        sleep=lambda _seconds: None,
        logger=StructuredLogger(quiet=True),
    )
    kwargs = dict(
        config=config,
        symbol="XAUUSD",
        start=start,
        end=end,
        raw_root=raw_root,
        manifest_path=path,
        processed_root=tmp_path / "processed",
    )
    first = build_canonical(**kwargs)
    first_metadata_bytes = Path(first["metadata_path"]).read_bytes()
    first_parquet = Path(first["dataset_root"]) / "date=2025-01-07" / "ticks.parquet"
    first_checksum = hashlib.sha256(first_parquet.read_bytes()).hexdigest()
    second = build_canonical(**kwargs)
    second_checksum = hashlib.sha256(first_parquet.read_bytes()).hexdigest()
    quality = first["quality_statistics"]
    assert first["row_count"] == 4
    assert quality["non_monotonic_timestamps"] == 1
    assert quality["duplicate_records"] == 1
    assert quality["duplicate_timestamps"] == 1
    assert quality["crossed_spreads"] == 2
    assert quality["implausible_spreads"] == 1
    assert first["bid_ask_examples"][0]["timestamp"].endswith("00.500Z")
    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert first_metadata_bytes == Path(second["metadata_path"]).read_bytes()
    assert first_checksum == second_checksum


def test_builder_reports_missing_partition_without_imputation(tmp_path, config):
    pytest.importorskip("pyarrow")
    path = manifest_path(tmp_path)
    Manifest(path, config=config, symbol="XAUUSD").save()
    metadata = build_canonical(
        config=config,
        symbol="XAUUSD",
        start=parse_utc_boundary("2025-01-07T00:00:00Z"),
        end=parse_utc_boundary("2025-01-07T01:00:00Z"),
        raw_root=tmp_path / "raw",
        manifest_path=path,
        processed_root=tmp_path / "processed",
    )
    assert metadata["row_count"] == 0
    assert metadata["coverage"]["unresolved_partitions"] == 1
    assert metadata["exclusions"][0]["classification"] == "missing_partition"
