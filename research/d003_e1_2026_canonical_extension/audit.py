"""Deterministic source, schema, gap, and feed-compatibility audits."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from scripts.build_dukascopy_canonical import canonical_schema

from .config import ExtensionAuditConfig


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def directory_fingerprint(path: Path) -> str:
    records: list[dict[str, object]] = []
    if not path.exists():
        return canonical_json_hash(records)
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        records.append(
            {
                "path": file_path.relative_to(path).as_posix(),
                "bytes": file_path.stat().st_size,
                "sha256": sha256_file(file_path),
            }
        )
    return canonical_json_hash(records)


def _load_tick_metadata(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tick metadata must be an object")
    return value


def _m15_inventory(path: Path, *, utc_normalized: bool) -> dict[str, object]:
    if utc_normalized:
        frame = pd.read_csv(path, usecols=["timestamp", "volume"])
        timestamp = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        start = timestamp.min()
        end = timestamp.max()
        row_count = len(frame)
        timestamp_format = "ISO-8601 UTC"
        timezone_name = "UTC"
    else:
        frame = pd.read_csv(
            path,
            encoding="utf-16",
            header=None,
            names=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "spread",
            ],
        )
        timestamp = pd.to_datetime(
            frame["timestamp"], format="%Y.%m.%d %H:%M", errors="coerce"
        )
        start = timestamp.min()
        end = timestamp.max()
        row_count = len(frame)
        timestamp_format = "%Y.%m.%d %H:%M, UTF-16"
        timezone_name = "naive broker/server wall time"
    return {
        "row_count": int(row_count),
        "start_timestamp": start.isoformat() if pd.notna(start) else None,
        "end_timestamp": end.isoformat() if pd.notna(end) else None,
        "timestamp_format": timestamp_format,
        "timezone": timezone_name,
    }


def build_source_inventory(
    root: Path, config: ExtensionAuditConfig
) -> pd.DataFrame:
    metadata_path = root / config.tick_metadata
    metadata = _load_tick_metadata(metadata_path)
    quality = metadata["quality"]
    derivative = metadata["derivative_verification"]
    input_meta = metadata["input"]
    output_meta = metadata["outputs"]
    timezone_meta = metadata["timezone"]

    raw_start = "2025-07-17T13:00:00.428"
    raw_end = "2026-07-17T14:09:53.920"
    utc_start = derivative["first_minute_utc"]
    utc_end = "2026-07-17T11:09:53.920+00:00"
    warnings = " | ".join(quality.get("warnings", []))
    raw_duplicate_timestamps = 1_091_679

    records: list[dict[str, object]] = []

    def add(
        relative_path: str,
        *,
        role: str,
        source_type: str,
        provenance: str,
        timezone_name: str,
        timestamp_format: str,
        price_fields: str,
        bid_ask_mid: str,
        volume_fields: str,
        granularity: str,
        start_timestamp: str | None,
        end_timestamp: str | None,
        row_count: int | None,
        duplicate_periods: int | None,
        missing_periods: str,
        dst_behavior: str,
        weekend_behavior: str,
        derived_from: str | None,
        post_2025_candidate: bool,
        notes: str,
    ) -> None:
        path = root / relative_path
        records.append(
            {
                "source_filename": path.name,
                "path": relative_path,
                "role": role,
                "source_type": source_type,
                "broker_or_feed_provenance": provenance,
                "symbol": config.symbol,
                "timezone": timezone_name,
                "timestamp_format": timestamp_format,
                "price_fields": price_fields,
                "bid_ask_mid_availability": bid_ask_mid,
                "volume_fields": volume_fields,
                "source_granularity": granularity,
                "start_timestamp": start_timestamp,
                "end_timestamp": end_timestamp,
                "row_count": row_count,
                "file_size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "missing_periods": missing_periods,
                "duplicated_periods": duplicate_periods,
                "suspected_broker_session_gaps": (
                    "reported separately from minute-gap audit"
                ),
                "dst_behavior": dst_behavior,
                "weekend_behavior": weekend_behavior,
                "derived_from": derived_from,
                "post_2025_candidate": post_2025_candidate,
                "notes": notes,
            }
        )

    add(
        config.raw_tick_source,
        role="primary_raw_candidate",
        source_type="MT5 tab-delimited tick export",
        provenance=(
            "mt5_local_export; broker/feed identity absent from file"
        ),
        timezone_name=(
            "naive server time; Europe/Helsinki strongly supported, "
            "not broker-authenticated"
        ),
        timestamp_format="%Y.%m.%d %H:%M:%S.%f",
        price_fields="<BID>, <ASK>; <LAST> empty",
        bid_ask_mid="bid/ask observed or incremental side update; mid derivable",
        volume_fields="<VOLUME> exists but empty on every validated row",
        granularity="event-driven tick/quote update",
        start_timestamp=raw_start,
        end_timestamp=raw_end,
        row_count=int(output_meta["normalized_tick_rows"]),
        duplicate_periods=raw_duplicate_timestamps,
        missing_periods="event-driven; minute gaps reported separately",
        dst_behavior=(
            "empirically follows Europe/Helsinki UTC+2/UTC+3"
        ),
        weekend_behavior=(
            "source-clock Saturday 0 and Sunday 0; UTC/NY reopening differs"
        ),
        derived_from=None,
        post_2025_candidate=True,
        notes=warnings,
    )
    add(
        config.normalized_tick_source,
        role="existing_read_only_derivative",
        source_type="normalized CSV quote-state ticks",
        provenance="derived from local MT5 export, not D003",
        timezone_name="UTC after Europe/Helsinki conversion",
        timestamp_format="ISO-8601 millisecond UTC",
        price_fields="bid, ask; mid/spread not stored",
        bid_ask_mid="bid/ask; unchanged side reconstructed from prior quote state",
        volume_fields="none",
        granularity="normalized event-driven quote state",
        start_timestamp="2025-07-17T10:00:00.428+00:00",
        end_timestamp=utc_end,
        row_count=int(output_meta["normalized_tick_rows"]),
        duplicate_periods=raw_duplicate_timestamps,
        missing_periods="event-driven; minute derivative audited separately",
        dst_behavior="converted using Europe/Helsinki rules",
        weekend_behavior="UTC/NY Sunday electronic reopening observations",
        derived_from=config.raw_tick_source,
        post_2025_candidate=True,
        notes="existing event-study derivative; not a D003 canonical file",
    )
    add(
        config.normalized_minute_source,
        role="overlap_comparison_derivative",
        source_type="one-minute bid/ask OHLC CSV",
        provenance="derived from local MT5 export, not D003",
        timezone_name="UTC",
        timestamp_format="ISO-8601 minute UTC",
        price_fields=(
            "bid/ask/mid OHLC, tick_count, median/maximum/last spread"
        ),
        bid_ask_mid="bid, ask, and mid OHLC available",
        volume_fields="none",
        granularity="one minute; populated buckets only",
        start_timestamp=utc_start,
        end_timestamp=derivative["last_minute_utc"],
        row_count=int(output_meta["minute_bar_rows"]),
        duplicate_periods=int(
            derivative["derivative_verification"][
                "duplicate_minute_timestamps"
            ]
        ) if "derivative_verification" in derivative else int(
            derivative["duplicate_minute_timestamps"]
        ),
        missing_periods="reported by deterministic minute-gap audit",
        dst_behavior="UTC derived using Europe/Helsinki rules",
        weekend_behavior=(
            "New York Saturday 0; New York Sunday reopening observations"
        ),
        derived_from=config.raw_tick_source,
        post_2025_candidate=True,
        notes="read-only comparison aid; not tick-level D003 input",
    )

    m15 = _m15_inventory(root / config.m15_source, utc_normalized=False)
    add(
        config.m15_source,
        role="supporting_bar_source",
        source_type="MT5 M15 single-price OHLC export",
        provenance="MetaTrader 5 export; broker identity absent",
        timezone_name=str(m15["timezone"]),
        timestamp_format=str(m15["timestamp_format"]),
        price_fields="open, high, low, close, zero spread",
        bid_ask_mid="single price only",
        volume_fields="M15 tick-volume count; not native bid/ask volume",
        granularity="15 minute",
        start_timestamp=str(m15["start_timestamp"]),
        end_timestamp=str(m15["end_timestamp"]),
        row_count=int(m15["row_count"]),
        duplicate_periods=None,
        missing_periods="not controlling; structurally insufficient",
        dst_behavior="requires Europe/Helsinki interpretation",
        weekend_behavior="bar-level only",
        derived_from=None,
        post_2025_candidate=True,
        notes="cannot reconstruct tick order, bid/ask, spread, or side volumes",
    )
    m15_utc = _m15_inventory(
        root / config.m15_utc_source, utc_normalized=True
    )
    add(
        config.m15_utc_source,
        role="supporting_bar_derivative",
        source_type="UTC-normalized M15 single-price CSV",
        provenance="derived from local MT5 M15 export",
        timezone_name=str(m15_utc["timezone"]),
        timestamp_format=str(m15_utc["timestamp_format"]),
        price_fields="open, high, low, close",
        bid_ask_mid="single price only",
        volume_fields="M15 tick-volume count; not native bid/ask volume",
        granularity="15 minute",
        start_timestamp=str(m15_utc["start_timestamp"]),
        end_timestamp=str(m15_utc["end_timestamp"]),
        row_count=int(m15_utc["row_count"]),
        duplicate_periods=None,
        missing_periods="not controlling; structurally insufficient",
        dst_behavior="UTC derivative of inferred broker timezone",
        weekend_behavior="bar-level only",
        derived_from=config.m15_source,
        post_2025_candidate=True,
        notes="cannot satisfy the D003 tick schema",
    )

    prior_path = root / config.prior_tick_source
    add(
        config.prior_tick_source,
        role="pre_2026_supporting_source",
        source_type="MT5 tab-delimited tick export",
        provenance="local MT5 export; broker identity absent",
        timezone_name="naive broker/server wall time",
        timestamp_format="%Y.%m.%d %H:%M:%S.%f",
        price_fields="<BID>, <ASK>",
        bid_ask_mid="bid/ask; mid derivable",
        volume_fields="<VOLUME> empty in observed format",
        granularity="event-driven tick/quote update",
        start_timestamp="2025-05-27T10:36:28.082",
        end_timestamp="2025-07-17T04:10:31.928",
        row_count=3_082_351,
        duplicate_periods=None,
        missing_periods="not audited; contains no post-2025 rows",
        dst_behavior="not controlling",
        weekend_behavior="not controlling",
        derived_from=None,
        post_2025_candidate=False,
        notes=(
            f"size/hash recorded for completeness; {prior_path.name} ends in 2025"
        ),
    )
    return pd.DataFrame.from_records(records)


def build_schema_audit(
    config: ExtensionAuditConfig,
) -> tuple[pd.DataFrame, dict[str, object]]:
    expected = canonical_schema()
    observed = {
        "timestamp_utc": (
            "derivable only after Europe/Helsinki timezone interpretation"
        ),
        "bid": "available after flag-consistent quote-state reconstruction",
        "ask": "available after flag-consistent quote-state reconstruction",
        "bid_volume": "absent; raw <VOLUME> empty on every row",
        "ask_volume": "absent; raw <VOLUME> empty on every row",
        "mid": "deterministically derivable as (bid + ask) / 2",
        "spread": "deterministically derivable as ask - bid",
        "symbol": "available as XAUUSD from export identity",
        "source_partition": (
            "UTC hour derivable, but not D001-verified Dukascopy partition"
        ),
    }
    reconstructable = {
        "timestamp_utc": False,
        "bid": True,
        "ask": True,
        "bid_volume": False,
        "ask_volume": False,
        "mid": True,
        "spread": True,
        "symbol": True,
        "source_partition": False,
    }
    records: list[dict[str, object]] = []
    for field in expected:
        records.append(
            {
                "column": field.name,
                "required_type": str(field.type),
                "required_nullable": field.nullable,
                "candidate_evidence": observed[field.name],
                "reconstructable_without_inference": reconstructable[field.name],
                "contract_satisfied": bool(
                    reconstructable[field.name]
                    and field.name not in {"timestamp_utc", "source_partition"}
                ),
            }
        )
    metadata_checks = {
        "d003_source_metadata": "dukascopy-public-bi5",
        "candidate_source_metadata": "mt5_local_export",
        "same_feed_authenticated": False,
        "broker_identity_present": False,
        "source_timezone_explicit": False,
        "timezone_empirically_supported": True,
        "timezone_broker_authenticated": False,
        "d001_verified_partition_manifest": False,
        "d002_closure_overlay_compatible": False,
        "frozen_d003_builder_accepts_source": False,
        "native_bid_volume_available": False,
        "native_ask_volume_available": False,
        "exact_nonnullable_schema_possible_without_fabrication": False,
    }
    return pd.DataFrame.from_records(records), metadata_checks


def load_historical_overlap(
    root: Path, config: ExtensionAuditConfig
) -> pd.DataFrame:
    start = pd.Timestamp(config.overlap_start)
    end = pd.Timestamp(config.overlap_end)
    files = sorted(
        (root / config.historical_minute_source / "year=2025").rglob(
            "bars_1m_*.parquet"
        )
    )
    frames: list[pd.DataFrame] = []
    columns = [
        "timestamp_utc",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "mid_open",
        "mid_high",
        "mid_low",
        "mid_close",
        "tick_count",
        "median_spread",
        "maximum_spread",
        "last_spread",
    ]
    for path in files:
        table = pq.read_table(path, columns=columns)
        frame = table.to_pandas()
        frame = frame[
            frame["timestamp_utc"].ge(start)
            & frame["timestamp_utc"].lt(end)
        ]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError("D003-derived overlap is empty")
    result = pd.concat(frames, ignore_index=True)
    return result.sort_values("timestamp_utc", kind="mergesort")


def load_mt5_minutes(root: Path, config: ExtensionAuditConfig) -> pd.DataFrame:
    frame = pd.read_csv(root / config.normalized_minute_source)
    frame["timestamp_utc"] = pd.to_datetime(
        frame.pop("timestamp"), utc=True, errors="raise"
    )
    return frame.sort_values("timestamp_utc", kind="mergesort")


def _quantiles(values: pd.Series, prefix: str) -> dict[str, float | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {
            f"{prefix}_mean": None,
            f"{prefix}_median": None,
            f"{prefix}_p95": None,
            f"{prefix}_p99": None,
            f"{prefix}_p999": None,
            f"{prefix}_max": None,
        }
    return {
        f"{prefix}_mean": float(clean.mean()),
        f"{prefix}_median": float(clean.median()),
        f"{prefix}_p95": float(clean.quantile(0.95)),
        f"{prefix}_p99": float(clean.quantile(0.99)),
        f"{prefix}_p999": float(clean.quantile(0.999)),
        f"{prefix}_max": float(clean.max()),
    }


def _feed_distribution(
    frame: pd.DataFrame, feed: str
) -> dict[str, object]:
    ordered = frame.sort_values("timestamp_utc", kind="mergesort").copy()
    delta = ordered["timestamp_utc"].diff().dt.total_seconds()
    consecutive = delta.eq(60)
    close_return = ordered["mid_close"].diff().where(consecutive)
    bar_range = ordered["mid_high"] - ordered["mid_low"]
    result: dict[str, object] = {
        "feed": feed,
        "minute_rows": int(len(ordered)),
        "duplicate_minutes": int(
            ordered["timestamp_utc"].duplicated(keep=False).sum()
        ),
        "timestamp_reversals": int(
            ordered["timestamp_utc"].diff().lt(pd.Timedelta(0)).sum()
        ),
        "gaps_over_one_minute": int(delta.gt(60).sum()),
        "median_spread": float(ordered["median_spread"].median()),
        "maximum_spread": float(ordered["maximum_spread"].max()),
        "median_tick_count": float(ordered["tick_count"].median()),
    }
    result.update(_quantiles(close_return.abs(), "absolute_1m_return"))
    result.update(_quantiles(bar_range, "mid_bar_range"))
    result.update(_quantiles(ordered["median_spread"], "median_spread"))
    result.update(_quantiles(ordered["maximum_spread"], "maximum_spread"))
    result.update(_quantiles(ordered["tick_count"], "tick_count"))
    for metric, values in {
        "absolute_1m_return": close_return.abs(),
        "mid_bar_range": bar_range,
        "maximum_spread": ordered["maximum_spread"],
        "tick_count": ordered["tick_count"],
    }.items():
        clean = values.dropna()
        for quantile, label in ((0.99, "p99"), (0.999, "p999")):
            threshold = clean.quantile(quantile)
            result[f"{metric}_{label}_threshold"] = float(threshold)
            result[f"{metric}_{label}_exceedances"] = int(
                clean.gt(threshold).sum()
            )
            result[f"{metric}_{label}_exceedance_share"] = float(
                clean.gt(threshold).mean()
            )
    return result


def _dst_regime(timestamp: pd.Series) -> pd.Series:
    date = timestamp.dt.date
    return pd.Series(
        np.select(
            [
                (date <= datetime(2025, 10, 25).date()),
                (
                    (date >= datetime(2025, 10, 26).date())
                    & (date <= datetime(2025, 11, 1).date())
                ),
                (date >= datetime(2025, 11, 2).date()),
            ],
            ["summer_both_dst", "fall_dst_mismatch", "winter_standard"],
            default="other",
        ),
        index=timestamp.index,
    )


def compare_feeds(
    historical: pd.DataFrame,
    mt5: pd.DataFrame,
    config: ExtensionAuditConfig,
) -> dict[str, pd.DataFrame]:
    start = pd.Timestamp(config.overlap_start)
    end = pd.Timestamp(config.overlap_end)
    d003 = historical[
        historical["timestamp_utc"].ge(start)
        & historical["timestamp_utc"].lt(end)
    ].copy()
    candidate = mt5[
        mt5["timestamp_utc"].ge(start)
        & mt5["timestamp_utc"].lt(end)
    ].copy()
    common = d003.merge(
        candidate,
        on="timestamp_utc",
        how="inner",
        suffixes=("_d003", "_mt5"),
        validate="one_to_one",
    ).sort_values("timestamp_utc", kind="mergesort")
    if common.empty:
        raise RuntimeError("no true D003/MT5 timestamp overlap")

    union_count = len(
        set(d003["timestamp_utc"]).union(set(candidate["timestamp_utc"]))
    )
    diff_metrics: dict[str, object] = {
        "d003_overlap_minutes": int(len(d003)),
        "mt5_overlap_minutes": int(len(candidate)),
        "common_minutes": int(len(common)),
        "union_minutes": int(union_count),
        "coverage_jaccard": float(len(common) / union_count),
        "d003_only_minutes": int(len(d003) - len(common)),
        "mt5_only_minutes": int(len(candidate) - len(common)),
        "overlap_start": common["timestamp_utc"].min().isoformat(),
        "overlap_end": common["timestamp_utc"].max().isoformat(),
    }
    for field in (
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "mid_open",
        "mid_high",
        "mid_low",
        "mid_close",
    ):
        difference = common[f"{field}_mt5"] - common[f"{field}_d003"]
        diff_metrics.update(_quantiles(difference.abs(), f"abs_{field}_diff"))
        if field == "mid_close":
            diff_metrics.update(_quantiles(difference, "signed_mid_close_diff"))

    consecutive = common["timestamp_utc"].diff().eq(pd.Timedelta(minutes=1))
    d003_return = common["mid_close_d003"].diff().where(consecutive)
    mt5_return = common["mid_close_mt5"].diff().where(consecutive)
    return_diff = mt5_return - d003_return
    diff_metrics.update(_quantiles(return_diff.abs(), "abs_1m_return_diff"))
    valid_returns = pd.concat(
        [d003_return, mt5_return], axis=1
    ).dropna()
    diff_metrics["one_minute_return_correlation"] = float(
        valid_returns.corr().iloc[0, 1]
    )
    diff_metrics["median_spread_ratio_mt5_to_d003"] = float(
        common["median_spread_mt5"].median()
        / common["median_spread_d003"].median()
    )
    diff_metrics["median_tick_count_ratio_mt5_to_d003"] = float(
        common["tick_count_mt5"].median()
        / common["tick_count_d003"].median()
    )

    distributions = pd.DataFrame.from_records(
        [
            _feed_distribution(d003, "d003_dukascopy"),
            _feed_distribution(candidate, "mt5_unknown_broker"),
        ]
    )

    dst_frame = common[
        [
            "timestamp_utc",
            "mid_close_d003",
            "mid_close_mt5",
            "median_spread_d003",
            "median_spread_mt5",
            "tick_count_d003",
            "tick_count_mt5",
        ]
    ].copy()
    dst_frame["dst_regime"] = _dst_regime(dst_frame["timestamp_utc"])
    dst_frame["absolute_mid_close_difference"] = (
        dst_frame["mid_close_mt5"] - dst_frame["mid_close_d003"]
    ).abs()
    dst = (
        dst_frame.groupby("dst_regime", dropna=False, observed=True)
        .agg(
            common_minutes=("timestamp_utc", "size"),
            median_absolute_mid_close_difference=(
                "absolute_mid_close_difference",
                "median",
            ),
            p95_absolute_mid_close_difference=(
                "absolute_mid_close_difference",
                lambda values: values.quantile(0.95),
            ),
            median_d003_spread=("median_spread_d003", "median"),
            median_mt5_spread=("median_spread_mt5", "median"),
            median_d003_tick_count=("tick_count_d003", "median"),
            median_mt5_tick_count=("tick_count_mt5", "median"),
        )
        .reset_index()
    )

    hour_records: list[dict[str, object]] = []
    for feed, frame in (
        ("d003_dukascopy", d003),
        ("mt5_unknown_broker", candidate),
    ):
        counts = frame.groupby(frame["timestamp_utc"].dt.hour).size()
        total = int(counts.sum())
        for hour in range(24):
            count = int(counts.get(hour, 0))
            hour_records.append(
                {
                    "feed": feed,
                    "utc_hour": hour,
                    "populated_minutes": count,
                    "share": float(count / total) if total else math.nan,
                }
            )
    session = pd.DataFrame.from_records(hour_records)
    return {
        "overlap_summary": pd.DataFrame.from_records([diff_metrics]),
        "feed_distributions": distributions,
        "dst_comparison": dst,
        "session_comparison": session,
    }


def build_gap_report(mt5: pd.DataFrame) -> pd.DataFrame:
    ordered = mt5.sort_values("timestamp_utc", kind="mergesort").copy()
    previous = ordered["timestamp_utc"].shift()
    delta_minutes = (
        ordered["timestamp_utc"] - previous
    ).dt.total_seconds() / 60.0
    mask = delta_minutes.gt(1)
    gaps = (
        ordered.loc[mask, ["timestamp_utc"]]
        .copy()
        .reset_index(drop=True)
    )
    gaps["previous_timestamp_utc"] = (
        previous.loc[mask].reset_index(drop=True)
    )
    gaps["gap_minutes_between_observations"] = (
        delta_minutes.loc[mask].reset_index(drop=True)
    )
    gaps["missing_minute_buckets"] = (
        gaps["gap_minutes_between_observations"].round().astype(int) - 1
    )
    local_before = pd.to_datetime(
        gaps["previous_timestamp_utc"], utc=True
    ).dt.tz_convert("America/New_York")
    local_after = gaps["timestamp_utc"].dt.tz_convert("America/New_York")
    weekend = (
        local_before.dt.dayofweek.eq(4)
        & local_after.dt.dayofweek.eq(6)
        & gaps["gap_minutes_between_observations"].ge(24 * 60)
    )
    daily_session = (
        local_before.dt.hour.isin([16, 17])
        & local_after.dt.hour.isin([17, 18])
        & gaps["gap_minutes_between_observations"].between(30, 180)
    )
    gaps["gap_classification"] = np.select(
        [weekend, daily_session],
        [
            "suspected_weekend_market_closure",
            "suspected_broker_daily_session_gap",
        ],
        default="suspected_missing_or_special_closure",
    )
    gaps["previous_timestamp_new_york"] = local_before.astype(str)
    gaps["next_timestamp_new_york"] = local_after.astype(str)
    return gaps[
        [
            "previous_timestamp_utc",
            "timestamp_utc",
            "previous_timestamp_new_york",
            "next_timestamp_new_york",
            "gap_minutes_between_observations",
            "missing_minute_buckets",
            "gap_classification",
        ]
    ].rename(columns={"timestamp_utc": "next_timestamp_utc"})


def build_duplicate_report(
    mt5: pd.DataFrame, metadata: dict[str, Any]
) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        [
            {
                "level": "raw_tick_timestamp",
                "duplicate_count": 1_091_679,
                "interpretation": (
                    "same-millisecond timestamps; not necessarily exact "
                    "duplicate quote states"
                ),
                "d003_identity_comparable": False,
                "reason": (
                    "D003 identity includes bid_volume and ask_volume, which "
                    "are absent from the MT5 source"
                ),
            },
            {
                "level": "normalized_minute_timestamp",
                "duplicate_count": int(
                    mt5["timestamp_utc"].duplicated(keep=False).sum()
                ),
                "interpretation": "duplicate populated one-minute buckets",
                "d003_identity_comparable": True,
                "reason": "minute timestamp identity is directly comparable",
            },
            {
                "level": "normalized_tick_exact_identity",
                "duplicate_count": None,
                "interpretation": "not asserted by prior qualification",
                "d003_identity_comparable": False,
                "reason": (
                    "native side volumes are absent and the D003 duplicate "
                    "key cannot be reproduced"
                ),
            },
        ]
    )


def verify_historical_release(
    root: Path, config: ExtensionAuditConfig
) -> dict[str, object]:
    release_root = root / config.historical_release_root
    manifest_path = release_root / "canonical_manifest.json"
    checksum_path = release_root / "parquet_sha256.txt"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    missing: list[str] = []
    for record in manifest["files"]:
        path = root / str(record["path"])
        if not path.is_file():
            missing.append(str(record["path"]))
            continue
        if path.stat().st_size != int(record["byte_size"]):
            mismatches.append(str(record["path"]) + ":bytes")
            continue
        if sha256_file(path) != str(record["sha256"]):
            mismatches.append(str(record["path"]) + ":sha256")
    checksum_lines = [
        line for line in checksum_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "release_id": config.historical_release_id,
        "manifest_sha256": sha256_file(manifest_path),
        "parquet_checksum_manifest_sha256": sha256_file(checksum_path),
        "declared_files": int(len(manifest["files"])),
        "checksum_entries": int(len(checksum_lines)),
        "declared_rows": int(manifest["row_count"]),
        "missing_files": missing,
        "mismatches": mismatches,
        "verified": not missing
        and not mismatches
        and len(checksum_lines) == len(manifest["files"]),
    }


def classify_compatibility(
    schema_checks: pd.DataFrame,
    metadata_checks: dict[str, object],
    feed_comparison: pd.DataFrame,
) -> dict[str, object]:
    critical = {
        "same_feed_authenticated": bool(
            metadata_checks["same_feed_authenticated"]
        ),
        "broker_identity_present": bool(
            metadata_checks["broker_identity_present"]
        ),
        "source_timezone_explicit": bool(
            metadata_checks["source_timezone_explicit"]
        ),
        "timezone_broker_authenticated": bool(
            metadata_checks["timezone_broker_authenticated"]
        ),
        "native_bid_volume_available": bool(
            metadata_checks["native_bid_volume_available"]
        ),
        "native_ask_volume_available": bool(
            metadata_checks["native_ask_volume_available"]
        ),
        "frozen_d003_builder_accepts_source": bool(
            metadata_checks["frozen_d003_builder_accepts_source"]
        ),
        "exact_nonnullable_schema_possible_without_fabrication": bool(
            metadata_checks[
                "exact_nonnullable_schema_possible_without_fabrication"
            ]
        ),
    }
    gate_passed = all(critical.values()) and bool(
        schema_checks["contract_satisfied"].all()
    )
    overlap = feed_comparison.iloc[0]
    return {
        "classification_id": 2 if gate_passed else 3,
        "classification_label": (
            "compatible after deterministic normalization"
            if gate_passed
            else "usable only as a separately labeled feed"
        ),
        "stage_a_passed": gate_passed,
        "stage_b_permitted": gate_passed,
        "critical_gate_checks": critical,
        "blocking_reasons": [] if gate_passed else [
            "candidate is MT5/unknown-broker, not authenticated Dukascopy BI5",
            "native bid_volume is absent and cannot be reconstructed",
            "native ask_volume is absent and cannot be reconstructed",
            "source timezone is empirically supported but not explicit or broker-authenticated",
            "candidate cannot enter the frozen D001/D002/D003 BI5 build path",
            "D003 exact non-nullable schema cannot be produced without fabrication",
        ],
        "supporting_feed_differences": {
            "median_absolute_mid_close_difference": float(
                overlap["abs_mid_close_diff_median"]
            ),
            "p95_absolute_mid_close_difference": float(
                overlap["abs_mid_close_diff_p95"]
            ),
            "one_minute_return_correlation": float(
                overlap["one_minute_return_correlation"]
            ),
            "median_spread_ratio_mt5_to_d003": float(
                overlap["median_spread_ratio_mt5_to_d003"]
            ),
            "median_tick_count_ratio_mt5_to_d003": float(
                overlap["median_tick_count_ratio_mt5_to_d003"]
            ),
        },
        "decision_rule": (
            "numeric similarity cannot override different provenance or "
            "missing required native fields"
        ),
    }
