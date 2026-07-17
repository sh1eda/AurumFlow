from __future__ import annotations

import math
import random

import pandas as pd


def _maximum_drawdown(values: pd.Series) -> float:
    if values.empty:
        return math.nan
    equity = values.cumsum()
    drawdown = equity - equity.cummax().clip(lower=0)
    return float(drawdown.min())


def performance_summary(trades: pd.DataFrame, *, minimum_sample: int = 30) -> dict:
    """Summarize setup, execution and R outcomes without hiding small samples."""

    if trades.empty:
        return {
            "sample_sessions": 0,
            "setup_count": 0,
            "filled_count": 0,
            "warning": "INSUFFICIENT SAMPLE: no setups",
        }
    filled = trades[trades["order_status"].eq("filled")].sort_values("fill_time")
    net = pd.to_numeric(filled.get("net_r", pd.Series(dtype=float)), errors="coerce").dropna()
    gains = float(net[net > 0].sum())
    losses = float(-net[net < 0].sum())
    filled_count = int(len(filled))
    sample_sessions = int(trades["session_date"].nunique())
    setup_count = int(trades["setup_id"].nunique()) if "setup_id" in trades else int(len(trades))
    eligible_sessions = (
        int(pd.to_numeric(trades["eligible_session_count"], errors="coerce").max())
        if "eligible_session_count" in trades and trades["eligible_session_count"].notna().any()
        else sample_sessions
    )
    summary = {
        "sample_sessions": sample_sessions,
        "eligible_sessions": eligible_sessions,
        "setup_count": setup_count,
        "candidate_order_count": int(len(trades)),
        "setup_frequency_per_session": setup_count / eligible_sessions if eligible_sessions else math.nan,
        "filled_count": filled_count,
        "fill_rate": filled_count / len(trades),
        "win_rate": float((net > 0).mean()) if not net.empty else math.nan,
        "average_r": float(net.mean()) if not net.empty else math.nan,
        "median_r": float(net.median()) if not net.empty else math.nan,
        "profit_factor": gains / losses if losses > 0 else (math.inf if gains > 0 else math.nan),
        "expectancy_after_costs_r": float(net.mean()) if not net.empty else math.nan,
        "maximum_drawdown_r": _maximum_drawdown(net),
        "mae_r_p10": float(filled["mae_r"].quantile(0.10)) if filled_count else math.nan,
        "mae_r_median": float(filled["mae_r"].median()) if filled_count else math.nan,
        "mfe_r_median": float(filled["mfe_r"].median()) if filled_count else math.nan,
        "mfe_r_p90": float(filled["mfe_r"].quantile(0.90)) if filled_count else math.nan,
        "expiration_rate": float(trades["order_status"].eq("expired_unfilled").mean()),
        "median_minutes_to_1r": float(filled["time_to_1r_minutes"].median()) if filled_count else math.nan,
        "median_minutes_to_1_5r": float(filled["time_to_1_5r_minutes"].median()) if filled_count else math.nan,
        "median_minutes_to_2r": float(filled["time_to_2r_minutes"].median()) if filled_count else math.nan,
        "median_minutes_to_opposing_liquidity": (
            float(filled["time_to_opposing_liquidity_minutes"].median()) if filled_count else math.nan
        ),
        "warning": (
            f"INSUFFICIENT SAMPLE: {filled_count} filled trades < {minimum_sample}"
            if filled_count < minimum_sample
            else ""
        ),
    }
    return summary


def grouped_performance(
    trades: pd.DataFrame,
    *,
    minimum_sample: int = 30,
) -> pd.DataFrame:
    """Report standalone and registered stability slices separately."""

    if trades.empty:
        return pd.DataFrame()
    enriched = trades.copy()
    enriched["calendar_year"] = pd.to_datetime(enriched["session_date"]).dt.year
    enriched["side"] = enriched["direction"].map({1: "long", -1: "short"})
    # Entry geometries and structure scales are mutually exclusive model
    # variants. Never pool them into one equity curve, PF or drawdown.
    base = [
        "cost_scenario_spread_price",
        "cost_scenario_slippage_per_side",
        "exit_policy",
        "family",
        "geometry",
        "structure_scale",
    ]
    dimensions = [
        base,
        base + ["calendar_year"],
        base + ["side"],
        base + ["event_class"],
        base + ["news_category"],
        base + ["impulse_size_bucket"],
        base + ["higher_timeframe_bias_alignment"],
        base + ["directional_relationship_0830_0930"],
        base + ["important_1000_release"],
    ]
    records: list[dict] = []
    for keys in dimensions:
        for values, group in enriched.groupby(keys, dropna=False):
            values = values if isinstance(values, tuple) else (values,)
            labels = {key: value for key, value in zip(keys, values)}
            records.append(
                {
                    "breakdown": "+".join(keys),
                    **labels,
                    **performance_summary(group, minimum_sample=minimum_sample),
                }
            )
    return pd.DataFrame.from_records(records)


def session_bootstrap_expectancy(
    trades: pd.DataFrame,
    *,
    iterations: int = 2000,
    seed: int = 830930,
) -> dict:
    """Bootstrap mean net R by session so correlated geometries stay clustered."""

    filled = trades[trades["order_status"].eq("filled")].copy()
    if filled.empty:
        return {"bootstrap_iterations": iterations, "sessions": 0, "mean_r": math.nan, "ci_2_5": math.nan, "ci_97_5": math.nan}
    session_means = filled.groupby("session_date")["net_r"].mean()
    sessions = session_means.tolist()
    rng = random.Random(seed)
    estimates = []
    for _ in range(iterations):
        sample = [sessions[rng.randrange(len(sessions))] for _ in range(len(sessions))]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    lower = estimates[int(0.025 * (iterations - 1))]
    upper = estimates[int(0.975 * (iterations - 1))]
    return {
        "bootstrap_iterations": iterations,
        "sessions": len(sessions),
        "mean_r": float(session_means.mean()),
        "ci_2_5": lower,
        "ci_97_5": upper,
    }
