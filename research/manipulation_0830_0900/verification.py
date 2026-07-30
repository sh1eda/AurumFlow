"""Independent artifact-level verifier for D004.

This module intentionally does not import the feature or analysis pipeline.
It recomputes artifact hashes and key aggregates directly from persisted rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .bars import sha256_file
from .reporting import write_json


REQUIRED_FILES = {
    "daily_events.parquet",
    "daily_event_schema.json",
    "strategy_events.parquet",
    "fvg_events.parquet",
    "aggregated_results.csv",
    "variant_comparison.csv",
    "year_by_year.csv",
    "direction_by_direction.csv",
    "window_subwindow_comparison.csv",
    "nearby_randomized_baselines.csv",
    "baseline_comparison.csv",
    "threshold_sensitivity.csv",
    "hod_lod_timing_analysis.csv",
    "manipulation_expansion_patterns.csv",
    "fvg_interaction_analysis.csv",
    "drawdown_excursion_statistics.csv",
    "out_of_sample_results.csv",
    "walk_forward_year_results.csv",
    "configuration_snapshot.json",
    "chronological_partition_specification.json",
    "reproducibility_metadata.json",
    "D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md",
    "artifact_manifest.json",
    "run.log.jsonl",
}


def _profit_factor(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(clean[clean > 0].sum())
    losses = float(-clean[clean < 0].sum())
    if losses > 0:
        return gains / losses
    return math.inf if gains > 0 else math.nan


def _drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return math.nan
    equity = clean.cumsum()
    return float((equity.cummax().clip(lower=0.0) - equity).max())


def _same(left: float, right: float, tolerance: float = 1e-9) -> bool:
    if math.isnan(left) and math.isnan(right):
        return True
    if math.isinf(left) or math.isinf(right):
        return left == right
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def verify_output(output_dir: Path, *, write: bool = False) -> dict[str, Any]:
    checks: list[dict[str, object]] = []
    errors: list[str] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            errors.append(f"{name}: {detail}")

    present = {path.name for path in output_dir.iterdir() if path.is_file()}
    missing = sorted(REQUIRED_FILES - present)
    check("required_files", not missing, f"missing={missing}")

    manifest_path = output_dir / "artifact_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hash_errors = []
        for record in manifest.get("files", []):
            path = output_dir / record["path"]
            if not path.is_file():
                hash_errors.append(f"{path.name}:missing")
            elif path.stat().st_size != int(record["byte_size"]):
                hash_errors.append(f"{path.name}:size")
            elif sha256_file(path) != record["sha256"]:
                hash_errors.append(f"{path.name}:sha256")
        check("artifact_hashes", not hash_errors, f"errors={hash_errors}")
    else:
        check("artifact_hashes", False, "artifact manifest missing")

    if missing:
        result = {
            "schema_version": 1,
            "status": "FAIL",
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "errors": errors,
        }
        if write:
            write_json(output_dir / "independent_verification.json", result)
        return result

    daily = pd.read_parquet(output_dir / "daily_events.parquet")
    strategy = pd.read_parquet(output_dir / "strategy_events.parquet")
    fvg = pd.read_parquet(output_dir / "fvg_events.parquet")
    variants = pd.read_csv(output_dir / "variant_comparison.csv")
    metadata = json.loads(
        (output_dir / "reproducibility_metadata.json").read_text(encoding="utf-8")
    )
    trading_dates = pd.to_datetime(daily["trading_date"], errors="coerce")
    check(
        "daily_dates_unique_ordered",
        bool(
            trading_dates.notna().all()
            and not trading_dates.duplicated().any()
            and trading_dates.is_monotonic_increasing
        ),
        f"rows={len(daily)} duplicates={int(trading_dates.duplicated().sum())}",
    )
    coverage_valid = daily["source_data_coverage_status"].isin(
        ["complete", "core_complete_day_partial", "core_incomplete"]
    ).all()
    check("coverage_status_domain", bool(coverage_valid), "explicit status on every weekday")
    complete = daily["window_complete"].astype(bool)
    ohlc_valid = (
        daily.loc[complete, "window_high"]
        .ge(daily.loc[complete, ["window_open", "window_close"]].max(axis=1))
        .all()
        and daily.loc[complete, "window_low"]
        .le(daily.loc[complete, ["window_open", "window_close"]].min(axis=1))
        .all()
        and daily.loc[complete, "window_high"].ge(daily.loc[complete, "window_low"]).all()
        and daily.loc[complete, "window_minute_count"].eq(30).all()
    )
    check("daily_window_ohlc_and_boundaries", bool(ohlc_valid), f"complete={int(complete.sum())}")
    prior_counts_ok = True
    finite_seen = 0
    for row in daily.itertuples(index=False):
        if int(row.displacement_history_count) != finite_seen:
            prior_counts_ok = False
            break
        if np.isfinite(float(row.window_range_atr)) and bool(row.core_eligible):
            finite_seen += 1
    check(
        "strictly_prior_displacement_history",
        prior_counts_ok,
        f"final_prior_observations={finite_seen}",
    )
    threshold_labels_ok = True
    for row in daily.itertuples(index=False):
        label = str(row.displacement_class)
        value = float(row.window_range_atr)
        if label == "insufficient_history":
            continue
        if not np.isfinite(value):
            threshold_labels_ok = False
            break
        expected = (
            "low"
            if value <= float(row.displacement_p25_prior)
            else "normal"
            if value <= float(row.displacement_p75_prior)
            else "high"
            if value <= float(row.displacement_p90_prior)
            else "extreme"
        )
        if label != expected:
            threshold_labels_ok = False
            break
    check("displacement_label_recalculation", threshold_labels_ok, "labels match saved prior thresholds")
    partitions = daily[daily["partition"].isin(["development", "validation", "holdout"])]
    order = {"development": 0, "validation": 1, "holdout": 2}
    partition_codes = partitions["partition"].map(order)
    check(
        "chronological_partitions",
        bool(partition_codes.is_monotonic_increasing),
        str(partitions.groupby("partition")["trading_date"].agg(["min", "max", "count"]).to_dict()),
    )
    if not strategy.empty:
        entry = pd.to_datetime(strategy["entry_time"], utc=True)
        local = entry.dt.tz_convert("America/New_York")
        causal_entries = local.dt.hour.eq(9) & local.dt.minute.eq(0)
        check(
            "strategy_entry_causality",
            bool(causal_entries.all()),
            f"rows={len(strategy)} non_0900={int((~causal_entries).sum())}",
        )
    else:
        check("strategy_entry_causality", False, "strategy dataset is empty")
    if not fvg.empty:
        creation = pd.to_datetime(fvg["creation_time"], utc=True).dt.tz_convert(
            "America/New_York"
        )
        causal_fvg = (
            creation.dt.hour.gt(8)
            | (creation.dt.hour.eq(8) & creation.dt.minute.gt(30))
        ) & (
            creation.dt.hour.lt(9)
            | (creation.dt.hour.eq(9) & creation.dt.minute.eq(0))
        )
        check(
            "fvg_window_availability",
            bool(causal_fvg.all()),
            f"rows={len(fvg)} invalid={int((~causal_fvg).sum())}",
        )
    else:
        check("fvg_window_availability", True, "no FVG rows")

    aggregate_errors: list[str] = []
    keys = ["variant", "direction", "horizon", "cost_scenario"]
    all_rows = variants[variants["partition"].eq("all")]
    for _, expected in all_rows.iterrows():
        selected = strategy.copy()
        for key in keys:
            selected = selected[selected[key].astype(str).eq(str(expected[key]))]
        net = selected["net_r"]
        actual = {
            "trade_count": int(net.notna().sum()),
            "expectancy_r": float(net.mean()),
            "profit_factor": _profit_factor(net),
            "maximum_drawdown_r": _drawdown(net),
        }
        for field, value in actual.items():
            expected_value = float(expected[field])
            if field == "trade_count":
                matches = int(expected_value) == int(value)
            else:
                matches = _same(expected_value, value)
            if not matches:
                aggregate_errors.append(
                    f"{expected['variant']}:{expected['direction']}:{expected['horizon']}:"
                    f"{expected['cost_scenario']}:{field}"
                )
    check(
        "variant_aggregate_recalculation",
        not aggregate_errors,
        f"errors={aggregate_errors[:20]} checked={len(all_rows)}",
    )
    metadata_counts = (
        int(metadata["candidate_dates"]) == len(daily)
        and int(metadata["core_eligible_dates"]) == int(daily["core_eligible"].sum())
        and int(metadata["strategy_event_rows"]) == len(strategy)
        and int(metadata["fvg_event_count"]) == len(fvg)
    )
    check("metadata_reconciliation", bool(metadata_counts), "persisted row counts agree")
    processing = metadata.get("processing_reconciliation", {})
    reconciliation_ok = (
        int(processing.get("source_files_processed", -1))
        == int(metadata["processed_source_files"])
        and int(processing.get("source_files_skipped", -1)) == 0
        and int(processing.get("source_files_failed", -1)) == 0
        and int(processing.get("candidate_trading_dates_processed", -1))
        == len(daily)
        and int(processing.get("candidate_trading_dates_failed", -1)) == 0
        and len(processing.get("inference_excluded_dates", []))
        == int((~daily["core_eligible"].astype(bool)).sum())
    )
    check(
        "processing_reconciliation",
        bool(reconciliation_ok),
        "processed/skipped/failed/incomplete counts reconcile",
    )
    canonical_root = Path(
        json.loads(
            (output_dir / "configuration_snapshot.json").read_text(encoding="utf-8")
        )["dataset_root"]
    )
    canonical_manifest = canonical_root / "canonical_manifest.json"
    canonical_hash_ok = (
        canonical_manifest.is_file()
        and sha256_file(canonical_manifest)
        == metadata["canonical_dataset"]["manifest_sha256"]
    )
    check("canonical_manifest_identity", canonical_hash_ok, str(canonical_manifest))

    result = {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "errors": errors,
        "independence": (
            "Artifact verifier reads persisted rows and recomputes hashes and "
            "aggregates without importing feature or analysis modules."
        ),
    }
    if write:
        write_json(output_dir / "independent_verification.json", result)
    return result
