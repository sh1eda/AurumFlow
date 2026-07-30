"""Statistical tables, baselines, and isolated hypothetical strategy replays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
import random
from typing import Callable, Iterable, Mapping

import numpy as np
import pandas as pd

from .config import (
    CONTROL_WINDOWS,
    COST_SCENARIOS,
    HORIZON_WINDOWS,
    REFERENCE_WINDOWS,
    SUBWINDOWS,
    CostScenario,
    ResearchConfig,
    local_timestamp,
)
from .features import (
    classify_sweep,
    threshold_to_price,
    utc_slice,
    window_slice,
)


@dataclass(frozen=True)
class AnalysisArtifacts:
    daily_events: pd.DataFrame
    fvg_events: pd.DataFrame
    strategy_events: pd.DataFrame
    tables: Mapping[str, pd.DataFrame]
    partition_specification: Mapping[str, object]


def chronological_partitions(daily: pd.DataFrame) -> tuple[pd.Series, dict[str, object]]:
    """Assign chronological 60/20/20 partitions without shuffling."""

    eligible = daily[daily["core_eligible"].astype(bool)].sort_values("trading_date")
    dates = eligible["trading_date"].tolist()
    n = len(dates)
    development_end = max(1, int(math.floor(0.60 * n))) if n else 0
    validation_end = max(development_end + 1, int(math.floor(0.80 * n))) if n > 1 else n
    validation_end = min(validation_end, n)
    mapping: dict[date, str] = {}
    for position, value in enumerate(dates):
        mapping[value] = (
            "development"
            if position < development_end
            else "validation"
            if position < validation_end
            else "holdout"
        )
    labels = daily["trading_date"].map(mapping).fillna("excluded")

    def part(name: str) -> dict[str, object]:
        values = [value for value in dates if mapping[value] == name]
        return {
            "start": values[0].isoformat() if values else None,
            "end": values[-1].isoformat() if values else None,
            "sessions": len(values),
        }

    specification = {
        "method": "chronological eligible-session split by position",
        "random_shuffle": False,
        "development_fraction": 0.60,
        "validation_fraction": 0.20,
        "holdout_fraction": 0.20,
        "development": part("development"),
        "validation": part("validation"),
        "holdout": part("holdout"),
        "threshold_rule": (
            "displacement percentiles use strictly prior eligible observations "
            "even inside each chronological partition"
        ),
        "holdout_rule": "no variant selection or threshold fitting on holdout",
    }
    return labels.astype("string"), specification


def _normal_ci(values: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(clean) < 2:
        return math.nan, math.nan
    mean = float(clean.mean())
    se = float(clean.std(ddof=1) / math.sqrt(len(clean)))
    return mean - 1.96 * se, mean + 1.96 * se


def bootstrap_mean_ci(
    values: pd.Series,
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    """Deterministic session-level percentile bootstrap."""

    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(clean) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=float)
    # Chunking avoids a potentially large resamples x sessions allocation.
    for start in range(0, resamples, 200):
        count = min(200, resamples - start)
        indexes = rng.integers(0, len(clean), size=(count, len(clean)))
        estimates[start : start + count] = clean[indexes].mean(axis=1)
    return (
        float(np.quantile(estimates, 0.025)),
        float(np.quantile(estimates, 0.975)),
    )


def _approx_p_value(values: pd.Series, null: float = 0.0) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if len(clean) < 2:
        return math.nan
    standard_deviation = float(clean.std(ddof=1))
    if standard_deviation == 0:
        return 0.0 if float(clean.mean()) != null else 1.0
    z = abs((float(clean.mean()) - null) / (standard_deviation / math.sqrt(len(clean))))
    return math.erfc(z / math.sqrt(2.0))


def numeric_summary(
    values: pd.Series,
    *,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    lower, upper = _normal_ci(clean)
    bootstrap_lower, bootstrap_upper = bootstrap_mean_ci(
        clean, resamples=resamples, seed=seed
    )
    return {
        "sample_count": int(len(clean)),
        "mean": float(clean.mean()) if len(clean) else math.nan,
        "median": float(clean.median()) if len(clean) else math.nan,
        "standard_deviation": float(clean.std(ddof=1)) if len(clean) > 1 else math.nan,
        "p05": float(clean.quantile(0.05)) if len(clean) else math.nan,
        "p25": float(clean.quantile(0.25)) if len(clean) else math.nan,
        "p75": float(clean.quantile(0.75)) if len(clean) else math.nan,
        "p95": float(clean.quantile(0.95)) if len(clean) else math.nan,
        "win_rate": float(clean.gt(0).mean()) if len(clean) else math.nan,
        "mean_ci_lower": lower,
        "mean_ci_upper": upper,
        "bootstrap_ci_lower": bootstrap_lower,
        "bootstrap_ci_upper": bootstrap_upper,
        "approx_two_sided_p_value": _approx_p_value(clean),
    }


def _bh_q_values(p_values: Iterable[float]) -> list[float]:
    values = list(p_values)
    valid = [(index, value) for index, value in enumerate(values) if np.isfinite(value)]
    output = [math.nan] * len(values)
    if not valid:
        return output
    ordered = sorted(valid, key=lambda item: item[1])
    count = len(ordered)
    adjusted = [0.0] * count
    running = 1.0
    for position in range(count - 1, -1, -1):
        _, value = ordered[position]
        candidate = min(1.0, value * count / (position + 1))
        running = min(running, candidate)
        adjusted[position] = running
    for (original, _), q_value in zip(ordered, adjusted):
        output[original] = q_value
    return output


def _directional_accuracy(signal: pd.Series, outcome: pd.Series) -> float:
    left = pd.to_numeric(signal, errors="coerce")
    right = pd.to_numeric(outcome, errors="coerce")
    valid = left.ne(0) & right.ne(0) & left.notna() & right.notna()
    return float(np.sign(left[valid]).eq(np.sign(right[valid])).mean()) if valid.any() else math.nan


def aggregate_condition_tables(
    daily: pd.DataFrame,
    config: ResearchConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Aggregate patterns overall, by year, and by direction."""

    eligible = daily[daily["core_eligible"].astype(bool)].copy()
    eligible["year"] = pd.to_datetime(eligible["trading_date"]).dt.year
    conditions: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
        "all_eligible_days": lambda frame: pd.Series(True, index=frame.index),
        "high_sweep_only": lambda frame: frame["sweep_type"].eq("high_only"),
        "low_sweep_only": lambda frame: frame["sweep_type"].eq("low_only"),
        "both_side_sweep": lambda frame: frame["sweep_type"].eq("both"),
        "no_sweep": lambda frame: frame["sweep_type"].eq("neither"),
        "high_sweep_rejection": lambda frame: frame["high_sweep"] & frame["high_reentry"],
        "low_sweep_rejection": lambda frame: frame["low_sweep"] & frame["low_reentry"],
        "high_or_extreme_displacement": lambda frame: frame["displacement_high_or_extreme"],
        "sweep_plus_displacement": lambda frame: ~frame["sweep_type"].eq("neither")
        & frame["displacement_high_or_extreme"],
        "sweep_plus_mss": lambda frame: (
            (frame["high_sweep"] & frame["bearish_mss_before_0900"])
            | (frame["low_sweep"] & frame["bullish_mss_before_0900"])
        ),
        "sweep_plus_fvg": lambda frame: (
            (frame["high_sweep"] & frame["bearish_fvg_1m"])
            | (frame["low_sweep"] & frame["bullish_fvg_1m"])
        ),
    }
    records: list[dict[str, object]] = []
    yearly: list[dict[str, object]] = []
    directional: list[dict[str, object]] = []
    counter = 0
    for condition, selector in conditions.items():
        selected = eligible[selector(eligible)]
        for horizon in HORIZON_WINDOWS:
            column = f"horizon_{horizon.name}_return_bps"
            summary = numeric_summary(
                selected[column],
                resamples=config.bootstrap_resamples,
                seed=config.random_seed + counter,
            )
            records.append(
                {
                    "condition": condition,
                    "horizon": horizon.name,
                    "eligible_days": int(len(eligible)),
                    "event_frequency": len(selected) / len(eligible) if len(eligible) else math.nan,
                    **summary,
                }
            )
            counter += 1
            for year, group in selected.groupby("year", sort=True):
                yearly.append(
                    {
                        "condition": condition,
                        "year": int(year),
                        "horizon": horizon.name,
                        **numeric_summary(
                            group[column],
                            resamples=min(config.bootstrap_resamples, 500),
                            seed=config.random_seed + counter,
                        ),
                    }
                )
                counter += 1
            for direction, group in selected.groupby("window_direction", dropna=False):
                directional.append(
                    {
                        "condition": condition,
                        "window_direction": int(direction) if pd.notna(direction) else 0,
                        "horizon": horizon.name,
                        **numeric_summary(
                            group[column],
                            resamples=min(config.bootstrap_resamples, 500),
                            seed=config.random_seed + counter,
                        ),
                    }
                )
                counter += 1
    aggregate = pd.DataFrame.from_records(records)
    if not aggregate.empty:
        aggregate["bh_q_value"] = _bh_q_values(aggregate["approx_two_sided_p_value"])
        aggregate["multiple_testing_note"] = (
            "Benjamini-Hochberg across this descriptive comparison family"
        )
    return (
        aggregate,
        pd.DataFrame.from_records(yearly),
        pd.DataFrame.from_records(directional),
    )


def subwindow_comparison(daily: pd.DataFrame, config: ResearchConfig) -> pd.DataFrame:
    eligible = daily[daily["core_eligible"].astype(bool)].copy()
    outcome = eligible["horizon_0900_1200_return_bps"]
    records: list[dict[str, object]] = []
    for position, window in enumerate(SUBWINDOWS):
        signal = eligible[f"subwindow_{window.name}_return_bps"]
        valid = signal.notna() & outcome.notna()
        records.append(
            {
                "subwindow": window.name,
                "start": window.start,
                "end": window.end,
                "sample_count": int(valid.sum()),
                "directional_accuracy_0900_1200": _directional_accuracy(
                    signal[valid], outcome[valid]
                ),
                "pearson_correlation_0900_1200": (
                    float(signal[valid].corr(outcome[valid])) if valid.sum() > 2 else math.nan
                ),
                **{
                    f"subwindow_return_{key}": value
                    for key, value in numeric_summary(
                        signal[valid],
                        resamples=config.bootstrap_resamples,
                        seed=config.random_seed + 20_000 + position,
                    ).items()
                },
            }
        )
    return pd.DataFrame.from_records(records)


def control_window_comparison(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    config: ResearchConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare equal-duration nearby and deterministic randomized windows."""

    eligible_dates = daily.loc[daily["core_eligible"].astype(bool), "trading_date"].tolist()
    observations: list[dict[str, object]] = []
    for session_date in eligible_dates:
        for window in CONTROL_WINDOWS:
            source = window_slice(bars, session_date, window.start, window.end)
            end = local_timestamp(session_date, window.end)
            following_end = end + pd.Timedelta(minutes=30)
            future = utc_slice(
                bars, end.tz_convert("UTC"), following_end.tz_convert("UTC")
            )
            if len(source) != 30 or len(future) != 30:
                continue
            observations.append(
                {
                    "trading_date": session_date,
                    "baseline": f"nearby_{window.name}",
                    "window_return_bps": 10000.0
                    * math.log(
                        float(source["mid_close"].iloc[-1])
                        / float(source["mid_open"].iloc[0])
                    ),
                    "following_return_bps": 10000.0
                    * math.log(
                        float(future["mid_close"].iloc[-1])
                        / float(future["mid_open"].iloc[0])
                    ),
                    "following_absolute_return_bps": abs(
                        10000.0
                        * math.log(
                            float(future["mid_close"].iloc[-1])
                            / float(future["mid_open"].iloc[0])
                        )
                    ),
                }
            )
        rng = random.Random(f"{config.random_seed}:{session_date.isoformat()}")
        random_start_minute = rng.randrange(0, 15 * 60 + 31)
        random_left = local_timestamp(session_date, "00:00") + pd.Timedelta(
            minutes=random_start_minute
        )
        random_right = random_left + pd.Timedelta(minutes=30)
        future_right = random_right + pd.Timedelta(minutes=30)
        source = utc_slice(
            bars, random_left.tz_convert("UTC"), random_right.tz_convert("UTC")
        )
        future = utc_slice(
            bars, random_right.tz_convert("UTC"), future_right.tz_convert("UTC")
        )
        if len(source) == 30 and len(future) == 30:
            source_return = 10000.0 * math.log(
                float(source["mid_close"].iloc[-1]) / float(source["mid_open"].iloc[0])
            )
            future_return = 10000.0 * math.log(
                float(future["mid_close"].iloc[-1]) / float(future["mid_open"].iloc[0])
            )
            observations.append(
                {
                    "trading_date": session_date,
                    "baseline": "randomized_equal_duration",
                    "window_return_bps": source_return,
                    "following_return_bps": future_return,
                    "following_absolute_return_bps": abs(future_return),
                    "random_start_new_york": random_left,
                }
            )
    raw = pd.DataFrame.from_records(observations)
    records: list[dict[str, object]] = []
    if not raw.empty:
        for position, (name, group) in enumerate(raw.groupby("baseline", sort=True)):
            records.append(
                {
                    "baseline": name,
                    "sample_count": int(len(group)),
                    "directional_accuracy": _directional_accuracy(
                        group["window_return_bps"], group["following_return_bps"]
                    ),
                    "return_correlation": float(
                        group["window_return_bps"].corr(group["following_return_bps"])
                    ),
                    **{
                        f"following_{key}": value
                        for key, value in numeric_summary(
                            group["following_return_bps"],
                            resamples=config.bootstrap_resamples,
                            seed=config.random_seed + 30_000 + position,
                        ).items()
                    },
                    "mean_following_absolute_return_bps": float(
                        group["following_absolute_return_bps"].mean()
                    ),
                }
            )
    return pd.DataFrame.from_records(records), raw


def threshold_sensitivity(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    eligible = daily[daily["core_eligible"].astype(bool)].copy()
    modes = {
        "absolute": config.absolute_sweep_thresholds,
        "bps": config.bps_sweep_thresholds,
        "atr_fraction": config.atr_sweep_thresholds,
        "recent_range_fraction": config.range_sweep_thresholds,
    }
    records: list[dict[str, object]] = []
    counter = 0
    for reference in REFERENCE_WINDOWS:
        high_column = f"reference_{reference.name}_high"
        low_column = f"reference_{reference.name}_low"
        for mode, values in modes.items():
            for threshold_value in values:
                events: list[dict[str, object]] = []
                for row in eligible.itertuples(index=False):
                    reference_high = float(getattr(row, high_column))
                    reference_low = float(getattr(row, low_column))
                    threshold = threshold_to_price(
                        mode,
                        float(threshold_value),
                        reference_high=reference_high,
                        reference_low=reference_low,
                        prior_atr=float(row.prior_atr_15m_20),
                    )
                    window = window_slice(
                        bars,
                        row.trading_date,
                        config.window_start,
                        config.window_end,
                    )
                    classified = classify_sweep(
                        window,
                        reference_high=reference_high,
                        reference_low=reference_low,
                        threshold_price=threshold,
                    )
                    events.append(
                        {
                            **classified,
                            "outcome": float(row.horizon_0900_1200_return_bps),
                        }
                    )
                event_frame = pd.DataFrame.from_records(events)
                for sweep_type in ("high_only", "low_only", "both", "neither"):
                    selected = event_frame[event_frame["sweep_type"].eq(sweep_type)]
                    summary = numeric_summary(
                        selected["outcome"],
                        resamples=min(config.bootstrap_resamples, 500),
                        seed=config.random_seed + 40_000 + counter,
                    )
                    records.append(
                        {
                            "reference_range": reference.name,
                            "threshold_mode": mode,
                            "threshold_value": threshold_value,
                            "sweep_type": sweep_type,
                            "eligible_days": int(len(eligible)),
                            "event_frequency": (
                                len(selected) / len(eligible) if len(eligible) else math.nan
                            ),
                            **summary,
                        }
                    )
                    counter += 1
    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result["bh_q_value"] = _bh_q_values(result["approx_two_sided_p_value"])
        result["multiple_testing_note"] = (
            "sensitivity family is descriptive; BH q-values do not authorize selection"
        )
    return result


def _signal_variants(row: pd.Series) -> list[tuple[str, int]]:
    window_direction = int(row["window_direction"]) if pd.notna(row["window_direction"]) else 0
    high_sweep = bool(row["high_sweep"])
    low_sweep = bool(row["low_sweep"])
    displaced = bool(row["displacement_high_or_extreme"])
    bullish_mss = bool(row["bullish_mss_before_0900"])
    bearish_mss = bool(row["bearish_mss_before_0900"])
    bullish_fvg = bool(row["bullish_fvg_1m"])
    bearish_fvg = bool(row["bearish_fvg_1m"])
    variants: list[tuple[str, int]] = []
    if window_direction:
        variants.extend(
            [
                ("directional_baseline_continuation", window_direction),
                ("directional_baseline_reversal", -window_direction),
            ]
        )
    if high_sweep:
        variants.extend(
            [
                ("high_sweep_bearish_expansion", -1),
                ("high_sweep_bullish_continuation", 1),
            ]
        )
    if low_sweep:
        variants.extend(
            [
                ("low_sweep_bullish_expansion", 1),
                ("low_sweep_bearish_continuation", -1),
            ]
        )
    if high_sweep and low_sweep and window_direction:
        variants.append(("both_side_sweep_reversal", -window_direction))
    reversal_direction = -1 if high_sweep and not low_sweep else 1 if low_sweep and not high_sweep else -window_direction
    any_sweep = high_sweep or low_sweep
    matching_mss = (
        reversal_direction == 1 and bullish_mss
    ) or (reversal_direction == -1 and bearish_mss)
    matching_fvg = (
        reversal_direction == 1 and bullish_fvg
    ) or (reversal_direction == -1 and bearish_fvg)
    if any_sweep and reversal_direction:
        variants.append(("sweep_only_reversal", reversal_direction))
    if displaced and window_direction:
        variants.extend(
            [
                ("displacement_only_continuation", window_direction),
                ("large_impulse_full_reversal", -window_direction),
            ]
        )
    if any_sweep and displaced and reversal_direction:
        variants.append(("sweep_plus_displacement", reversal_direction))
    if any_sweep and matching_mss and reversal_direction:
        variants.append(("sweep_plus_mss", reversal_direction))
    if any_sweep and displaced and matching_mss and reversal_direction:
        variants.append(("sweep_plus_displacement_plus_mss", reversal_direction))
    if any_sweep and displaced and matching_fvg and reversal_direction:
        variants.append(("sweep_plus_displacement_plus_fvg", reversal_direction))
    if (
        any_sweep
        and displaced
        and matching_mss
        and matching_fvg
        and reversal_direction
    ):
        variants.append(("full_sweep_displacement_mss_fvg", reversal_direction))
    # A given day can reach a named variant through more than one sweep side.
    return list(dict.fromkeys(variants))


def _replay_path(
    path: pd.DataFrame,
    *,
    direction: int,
    entry: float,
    stop: float,
    target_r: float = 2.0,
) -> dict[str, object]:
    risk = abs(entry - stop)
    if path.empty or direction not in {-1, 1} or risk <= 0:
        return {
            "risk_price": risk,
            "gross_r": math.nan,
            "mfe_r": math.nan,
            "mae_r": math.nan,
            "exit_reason": "invalid_or_missing_path",
            "exit_time": pd.NaT,
        }
    target = entry + direction * target_r * risk
    exit_price = float(path["mid_close"].iloc[-1])
    exit_time = path.index[-1] + pd.Timedelta(minutes=1)
    exit_reason = "time_exit"
    for timestamp, bar in path.iterrows():
        stop_hit = (
            float(bar["mid_low"]) <= stop
            if direction > 0
            else float(bar["mid_high"]) >= stop
        )
        target_hit = (
            float(bar["mid_high"]) >= target
            if direction > 0
            else float(bar["mid_low"]) <= target
        )
        if stop_hit:
            exit_price = stop
            exit_time = timestamp + pd.Timedelta(minutes=1)
            exit_reason = "stop"
            break
        if target_hit:
            exit_price = target
            exit_time = timestamp + pd.Timedelta(minutes=1)
            exit_reason = "target"
            break
    gross_r = direction * (exit_price - entry) / risk
    if direction > 0:
        mfe = (float(path["mid_high"].max()) - entry) / risk
        mae = (entry - float(path["mid_low"].min())) / risk
    else:
        mfe = (entry - float(path["mid_low"].min())) / risk
        mae = (float(path["mid_high"].max()) - entry) / risk
    return {
        "risk_price": risk,
        "target_price": target,
        "gross_r": gross_r,
        "mfe_r": mfe,
        "mae_r": mae,
        "exit_reason": exit_reason,
        "exit_time": exit_time,
    }


def _net_r(gross_r: float, risk: float, scenario: CostScenario) -> float:
    if not np.isfinite(gross_r) or risk <= 0:
        return math.nan
    price_cost = scenario.spread_price + 2.0 * scenario.slippage_price_per_side
    return gross_r - price_cost / risk - scenario.commission_r


def strategy_event_dataset(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    eligible = daily[daily["core_eligible"].astype(bool)].sort_values("trading_date")
    for _, row in eligible.iterrows():
        entry = float(row["horizon_0900_0930_open"])
        for variant, direction in _signal_variants(row):
            stop = float(row["window_low"] if direction > 0 else row["window_high"])
            for horizon in HORIZON_WINDOWS:
                path = window_slice(
                    bars,
                    row["trading_date"],
                    horizon.start,
                    horizon.end,
                )
                replay = _replay_path(
                    path,
                    direction=direction,
                    entry=entry,
                    stop=stop,
                )
                for scenario in COST_SCENARIOS:
                    records.append(
                        {
                            "trading_date": row["trading_date"],
                            "partition": row["partition"],
                            "variant": variant,
                            "direction": "long" if direction > 0 else "short",
                            "direction_sign": direction,
                            "horizon": horizon.name,
                            "cost_scenario": scenario.name,
                            "entry_time": local_timestamp(
                                row["trading_date"], "09:00"
                            ).tz_convert("UTC"),
                            "entry_price": entry,
                            "stop_price": stop,
                            **replay,
                            "net_r": _net_r(
                                float(replay["gross_r"]),
                                float(replay["risk_price"]),
                                scenario,
                            ),
                        }
                    )
    result = pd.DataFrame.from_records(records)
    return (
        result.sort_values(
            ["trading_date", "variant", "horizon", "cost_scenario"]
        ).reset_index(drop=True)
        if not result.empty
        else result
    )


def _maximum_drawdown(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if clean.empty:
        return math.nan
    equity = clean.cumsum()
    running_peak = equity.cummax().clip(lower=0.0)
    return float((running_peak - equity).max())


def strategy_summary(
    events: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    if events.empty:
        return pd.DataFrame()
    counter = 0
    group_columns = ["variant", "direction", "horizon", "cost_scenario"]
    for partition in ("all", "development", "validation", "holdout"):
        source = events if partition == "all" else events[events["partition"].eq(partition)]
        for keys, group in source.groupby(group_columns, sort=True):
            net = pd.to_numeric(group["net_r"], errors="coerce").dropna()
            gains = float(net[net > 0].sum())
            losses = float(-net[net < 0].sum())
            summary = numeric_summary(
                net,
                resamples=config.bootstrap_resamples,
                seed=config.random_seed + 50_000 + counter,
            )
            records.append(
                {
                    "partition": partition,
                    **dict(zip(group_columns, keys)),
                    "trade_count": int(len(net)),
                    "expectancy_r": float(net.mean()) if len(net) else math.nan,
                    "profit_factor": (
                        gains / losses
                        if losses > 0
                        else math.inf
                        if gains > 0
                        else math.nan
                    ),
                    "maximum_drawdown_r": _maximum_drawdown(net),
                    "mean_mae_r": float(group["mae_r"].mean()),
                    "mean_mfe_r": float(group["mfe_r"].mean()),
                    "stop_rate": float(group["exit_reason"].eq("stop").mean()),
                    "target_rate": float(group["exit_reason"].eq("target").mean()),
                    **{
                        f"net_r_{key}": value
                        for key, value in summary.items()
                        if key
                        not in {
                            "sample_count",
                            "mean",
                            "median",
                            "win_rate",
                        }
                    },
                    "win_rate": float(net.gt(0).mean()) if len(net) else math.nan,
                    "median_r": float(net.median()) if len(net) else math.nan,
                }
            )
            counter += 1
    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result["bh_q_value"] = _bh_q_values(
            result["net_r_approx_two_sided_p_value"]
        )
        result["selection_warning"] = (
            "Do not select the maximum in-sample expectancy; validation and "
            "holdout stability plus BH-aware uncertainty are required"
        )
    return result


def baseline_comparison(
    daily: pd.DataFrame,
    strategy: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    eligible = daily[daily["core_eligible"].astype(bool)]
    for horizon in HORIZON_WINDOWS:
        outcome = eligible[f"horizon_{horizon.name}_return_bps"]
        signal = eligible["window_return_bps"]
        no_event = eligible[eligible["sweep_type"].eq("neither")][
            f"horizon_{horizon.name}_return_bps"
        ]
        event = eligible[~eligible["sweep_type"].eq("neither")][
            f"horizon_{horizon.name}_return_bps"
        ]
        records.extend(
            [
                {
                    "baseline": "all_eligible_days",
                    "horizon": horizon.name,
                    **numeric_summary(
                        outcome,
                        resamples=config.bootstrap_resamples,
                        seed=config.random_seed + 60_000 + len(records),
                    ),
                },
                {
                    "baseline": "days_without_qualifying_sweep",
                    "horizon": horizon.name,
                    **numeric_summary(
                        no_event,
                        resamples=config.bootstrap_resamples,
                        seed=config.random_seed + 60_000 + len(records),
                    ),
                },
                {
                    "baseline": "days_with_qualifying_sweep",
                    "horizon": horizon.name,
                    **numeric_summary(
                        event,
                        resamples=config.bootstrap_resamples,
                        seed=config.random_seed + 60_000 + len(records),
                    ),
                },
                {
                    "baseline": "directional_sign_of_0830_0900_return",
                    "horizon": horizon.name,
                    "sample_count": int((signal.notna() & outcome.notna()).sum()),
                    "directional_accuracy": _directional_accuracy(signal, outcome),
                    "mean": math.nan,
                    "median": math.nan,
                    "standard_deviation": math.nan,
                    "p05": math.nan,
                    "p25": math.nan,
                    "p75": math.nan,
                    "p95": math.nan,
                    "win_rate": math.nan,
                    "mean_ci_lower": math.nan,
                    "mean_ci_upper": math.nan,
                    "bootstrap_ci_lower": math.nan,
                    "bootstrap_ci_upper": math.nan,
                    "approx_two_sided_p_value": math.nan,
                },
            ]
        )
    result = pd.DataFrame.from_records(records)
    if not result.empty:
        result["effect_size_vs_all_days"] = math.nan
        for horizon, group in result.groupby("horizon"):
            baseline = group[group["baseline"].eq("all_eligible_days")]
            if baseline.empty:
                continue
            mean = float(baseline.iloc[0]["mean"])
            standard_deviation = float(baseline.iloc[0]["standard_deviation"])
            indexes = group.index
            result.loc[indexes, "effect_size_vs_all_days"] = (
                (group["mean"] - mean) / standard_deviation
                if np.isfinite(standard_deviation) and standard_deviation > 0
                else math.nan
            )
    return result


def hod_lod_analysis(daily: pd.DataFrame) -> pd.DataFrame:
    eligible = daily[daily["core_eligible"].astype(bool)].copy()
    records: list[dict[str, object]] = []
    for label in ("all", "development", "validation", "holdout"):
        group = eligible if label == "all" else eligible[eligible["partition"].eq(label)]
        record: dict[str, object] = {
                "table": "rates",
                "partition": label,
                "bucket": "all",
                "sample_count": int(len(group)),
                "exact_hod_rate": float(group["window_creates_hod"].mean()) if len(group) else math.nan,
                "exact_lod_rate": float(group["window_creates_lod"].mean()) if len(group) else math.nan,
                "exact_both_rate": float(group["window_creates_both"].mean()) if len(group) else math.nan,
                "exact_neither_rate": float(group["window_creates_neither"].mean()) if len(group) else math.nan,
                "hod_within_1tick_rate": float(group["window_within_hod_1tick"].mean()) if len(group) else math.nan,
                "lod_within_1tick_rate": float(group["window_within_lod_1tick"].mean()) if len(group) else math.nan,
                "hod_within_5tick_rate": float(group["window_within_hod_5tick"].mean()) if len(group) else math.nan,
                "lod_within_5tick_rate": float(group["window_within_lod_5tick"].mean()) if len(group) else math.nan,
                "hod_within_005atr_rate": float(group["window_within_hod_005atr"].mean()) if len(group) else math.nan,
                "lod_within_005atr_rate": float(group["window_within_lod_005atr"].mean()) if len(group) else math.nan,
        }
        for label_column, prefix in (
            ("window_creates_hod", "exact_hod"),
            ("window_creates_lod", "exact_lod"),
            ("window_within_hod_1tick", "hod_within_1tick"),
            ("window_within_lod_1tick", "lod_within_1tick"),
        ):
            rate = float(group[label_column].mean()) if len(group) else math.nan
            standard_error = (
                math.sqrt(rate * (1.0 - rate) / len(group))
                if len(group) and np.isfinite(rate)
                else math.nan
            )
            record[f"{prefix}_ci_lower"] = (
                max(0.0, rate - 1.96 * standard_error)
                if np.isfinite(standard_error)
                else math.nan
            )
            record[f"{prefix}_ci_upper"] = (
                min(1.0, rate + 1.96 * standard_error)
                if np.isfinite(standard_error)
                else math.nan
            )
        records.append(record)
    for extreme, timestamp_column in (("hod", "hod_time"), ("lod", "lod_time")):
        timestamps = pd.to_datetime(eligible[timestamp_column], utc=True, errors="coerce")
        local_hours = timestamps.dt.tz_convert("America/New_York").dt.hour
        for hour, count in local_hours.value_counts().sort_index().items():
            records.append(
                {
                    "table": "timing_distribution",
                    "partition": "all",
                    "bucket": f"{extreme}_{int(hour):02d}:00",
                    "sample_count": int(count),
                    "timing_rate": count / len(eligible) if len(eligible) else math.nan,
                }
            )
    return pd.DataFrame.from_records(records)


def manipulation_pattern_table(daily: pd.DataFrame) -> pd.DataFrame:
    """Report future-labeled pattern outcomes without treating them as signals."""

    eligible = daily[daily["core_eligible"].astype(bool)].copy()
    patterns = (
        "high_sweep_bearish_expansion_outcome",
        "high_sweep_bullish_continuation_outcome",
        "low_sweep_bullish_expansion_outcome",
        "low_sweep_bearish_continuation_outcome",
        "both_sweep_directional_expansion_outcome",
        "large_impulse_retraces_half_window",
        "large_impulse_retracement_then_continuation_outcome",
        "large_impulse_full_reversal_outcome",
    )
    records: list[dict[str, object]] = []
    for partition in ("all", "development", "validation", "holdout"):
        source = eligible if partition == "all" else eligible[
            eligible["partition"].eq(partition)
        ]
        for pattern in patterns:
            values = source[pattern].astype(bool)
            count = int(values.sum())
            records.append(
                {
                    "partition": partition,
                    "pattern": pattern,
                    "eligible_days": int(len(source)),
                    "event_count": count,
                    "event_rate": count / len(source) if len(source) else math.nan,
                    "classification": (
                        "future outcome label; never used to qualify a 09:00 signal"
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def fvg_summary(fvgs: pd.DataFrame, config: ResearchConfig) -> pd.DataFrame:
    if fvgs.empty:
        return pd.DataFrame(
            columns=[
                "resolution_minutes",
                "direction",
                "partition",
                "sample_count",
                "full_fill_rate",
            ]
        )
    frame = fvgs[fvgs["partition"].ne("excluded")].copy()
    records: list[dict[str, object]] = []
    geometries = ("proximal", "midpoint", "depth_75", "distal")
    for (resolution, direction, partition), group in frame.groupby(
        ["resolution_minutes", "direction", "partition"], sort=True
    ):
        base = {
            "resolution_minutes": int(resolution),
            "direction": direction,
            "partition": partition,
            "sample_count": int(len(group)),
            "mean_width": float(group["width"].mean()),
            "mean_width_atr": float(group["width_atr"].mean()),
            "touch_rate": float(group["first_touch_time"].notna().mean()),
            "mean_fill_percentage": float(group["fill_percentage"].mean()),
            "full_fill_rate": float(group["full_fill"].mean()),
            "invalidation_rate": float(group["invalidation"].mean()),
        }
        for geometry in geometries:
            values = pd.to_numeric(group[f"{geometry}_terminal_r"], errors="coerce")
            conservative = pd.to_numeric(
                group[f"{geometry}_conservative_terminal_r"], errors="coerce"
            )
            interval = bootstrap_mean_ci(
                values,
                resamples=config.bootstrap_resamples,
                seed=config.random_seed + 70_000 + len(records),
            )
            records.append(
                {
                    **base,
                    "geometry": geometry,
                    "geometry_touch_rate": float(
                        group[f"{geometry}_touch_time"].notna().mean()
                    ),
                    "mean_terminal_r": float(values.mean()),
                    "median_terminal_r": float(values.median()),
                    "terminal_r_p05": float(values.quantile(0.05)),
                    "terminal_r_p95": float(values.quantile(0.95)),
                    "mean_conservative_terminal_r": float(conservative.mean()),
                    "median_conservative_terminal_r": float(conservative.median()),
                    "mean_mfe_r": float(group[f"{geometry}_mfe_r"].mean()),
                    "median_mfe_r": float(group[f"{geometry}_mfe_r"].median()),
                    "mean_mae_r": float(group[f"{geometry}_mae_r"].mean()),
                    "median_mae_r": float(group[f"{geometry}_mae_r"].median()),
                    "bootstrap_ci_lower": interval[0],
                    "bootstrap_ci_upper": interval[1],
                }
            )
    return pd.DataFrame.from_records(records)


def walk_forward_table(strategy_summary_frame: pd.DataFrame) -> pd.DataFrame:
    """Expose validation/holdout rows as the strict out-of-sample comparison."""

    if strategy_summary_frame.empty:
        return pd.DataFrame()
    return strategy_summary_frame[
        strategy_summary_frame["partition"].isin(["validation", "holdout"])
    ].copy()


def walk_forward_year_table(
    events: pd.DataFrame,
    config: ResearchConfig,
) -> pd.DataFrame:
    """Evaluate each calendar year after the first using only causal features.

    D004 variants contain no fitted coefficients.  The displacement bucket in
    each event was already computed from strictly earlier days, so this yearly
    table is a genuine expanding-history walk-forward view rather than a
    shuffled cross-validation score.
    """

    if events.empty:
        return pd.DataFrame()
    frame = events.copy()
    frame["test_year"] = pd.to_datetime(frame["trading_date"]).dt.year
    years = sorted(frame["test_year"].unique())
    first_year = years[0]
    records: list[dict[str, object]] = []
    counter = 0
    keys = ["variant", "direction", "horizon", "cost_scenario"]
    for year in years[1:]:
        source = frame[frame["test_year"].eq(year)]
        for values, group in source.groupby(keys, sort=True):
            net = pd.to_numeric(group["net_r"], errors="coerce").dropna()
            summary = numeric_summary(
                net,
                resamples=min(config.bootstrap_resamples, 500),
                seed=config.random_seed + 80_000 + counter,
            )
            gains = float(net[net > 0].sum())
            losses = float(-net[net < 0].sum())
            records.append(
                {
                    "training_history_start_year": int(first_year),
                    "training_history_end_year": int(year - 1),
                    "test_year": int(year),
                    **dict(zip(keys, values)),
                    "trade_count": int(len(net)),
                    "expectancy_r": float(net.mean()) if len(net) else math.nan,
                    "profit_factor": (
                        gains / losses
                        if losses > 0
                        else math.inf
                        if gains > 0
                        else math.nan
                    ),
                    "maximum_drawdown_r": _maximum_drawdown(net),
                    "win_rate": float(net.gt(0).mean()) if len(net) else math.nan,
                    "bootstrap_ci_lower": summary["bootstrap_ci_lower"],
                    "bootstrap_ci_upper": summary["bootstrap_ci_upper"],
                    "causal_threshold_rule": (
                        "event displacement class uses strictly prior sessions"
                    ),
                }
            )
            counter += 1
    return pd.DataFrame.from_records(records)


def run_analysis(
    daily: pd.DataFrame,
    fvg_events: pd.DataFrame,
    bars: pd.DataFrame,
    config: ResearchConfig,
) -> AnalysisArtifacts:
    daily = daily.copy()
    daily["partition"], specification = chronological_partitions(daily)
    if not fvg_events.empty:
        partition_map = daily.set_index("trading_date")["partition"]
        fvg_events = fvg_events.copy()
        fvg_events["partition"] = fvg_events["trading_date"].map(partition_map).fillna(
            "excluded"
        )
    aggregate, yearly, directional = aggregate_condition_tables(daily, config)
    subwindows = subwindow_comparison(daily, config)
    controls, control_observations = control_window_comparison(daily, bars, config)
    sensitivity = threshold_sensitivity(daily, bars, config)
    strategy = strategy_event_dataset(daily, bars)
    variants = strategy_summary(strategy, config)
    tables = {
        "aggregated_results": aggregate,
        "variant_comparison": variants,
        "year_by_year": yearly,
        "direction_by_direction": directional,
        "window_subwindow_comparison": subwindows,
        "nearby_randomized_baselines": controls,
        "baseline_observations": control_observations,
        "baseline_comparison": baseline_comparison(daily, strategy, config),
        "threshold_sensitivity": sensitivity,
        "hod_lod_timing": hod_lod_analysis(daily),
        "manipulation_patterns": manipulation_pattern_table(daily),
        "fvg_interaction": fvg_summary(fvg_events, config),
        "drawdown_excursion": variants[
            [
                "partition",
                "variant",
                "direction",
                "horizon",
                "cost_scenario",
                "trade_count",
                "maximum_drawdown_r",
                "mean_mae_r",
                "mean_mfe_r",
            ]
        ].copy()
        if not variants.empty
        else pd.DataFrame(),
        "out_of_sample": walk_forward_table(variants),
        "walk_forward_year": walk_forward_year_table(strategy, config),
    }
    return AnalysisArtifacts(
        daily_events=daily,
        fvg_events=fvg_events,
        strategy_events=strategy,
        tables=tables,
        partition_specification=specification,
    )
