from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd

from .config import StudyConfig
from .features import _window


def _movement(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"directional_bp": math.nan, "absolute_bp": math.nan, "range_bp": math.nan}
    opening = float(frame["open"].iloc[0])
    closing = float(frame["close"].iloc[-1])
    directional = 10000 * math.log(closing / opening)
    return {
        "directional_bp": directional,
        "absolute_bp": abs(directional),
        "range_bp": 10000 * (float(frame["high"].max()) - float(frame["low"].min())) / opening,
    }


def build_test_panel(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    config: StudyConfig | None = None,
) -> pd.DataFrame:
    """Build non-overlapping matched windows for preregistered event-time tests."""

    cfg = config or StudyConfig()
    records: list[dict] = []
    for session_date, row in features.iterrows():
        windows = {
            "impulse": _window(prices, session_date, "08:30", "08:35", cfg.timezone),
            "pre_equity_control": _window(prices, session_date, "09:10", "09:30", cfg.timezone),
            "equity_reaction": _window(prices, session_date, "09:30", "09:50", cfg.timezone),
            "delivery": _window(prices, session_date, "09:30", "10:00", cfg.timezone),
            "secondary": _window(prices, session_date, "10:00", "10:30", cfg.timezone),
        }
        record = {
            "session_date": session_date,
            "event_class": row["event_class"],
            "important_1000_release": bool(row["important_1000_release"]),
            "minor_1000_release": bool(row["minor_1000_release"]),
            "day_of_week": pd.Timestamp(session_date).dayofweek,
            "reentry_before_acceptance": bool(row.get("reentry_before_acceptance", False)),
            "acceptance_observed": pd.notna(row.get("directional_boundary_acceptance_time")),
            "holds_impulse_midpoint_to_0930": bool(row.get("holds_impulse_midpoint_to_0930", False)),
            "lifecycle_state_1m": row.get("lifecycle_state_1m", ""),
        }
        for name, frame in windows.items():
            for metric, value in _movement(frame).items():
                record[f"{name}_{metric}"] = value
        record["delta_0930_vs_precontrol_absolute_bp"] = (
            record["equity_reaction_absolute_bp"] - record["pre_equity_control_absolute_bp"]
        )
        record["delta_1000_vs_delivery_absolute_bp"] = (
            record["secondary_absolute_bp"] - record["delivery_absolute_bp"]
        )
        records.append(record)
    return pd.DataFrame.from_records(records)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    return float(ordered[round((len(ordered) - 1) * probability)])


def _group_contrast(
    panel: pd.DataFrame,
    *,
    value: str,
    group: str,
    first,
    second,
    statistic: str,
    iterations: int,
    seed: int,
) -> dict:
    first_values = panel.loc[panel[group].eq(first), value].dropna().astype(float).tolist()
    second_values = panel.loc[panel[group].eq(second), value].dropna().astype(float).tolist()
    if not first_values or not second_values:
        return {"estimate": math.nan, "ci_2_5": math.nan, "ci_97_5": math.nan, "sample_a": len(first_values), "sample_b": len(second_values)}
    reducer = (lambda values: float(pd.Series(values).median())) if statistic == "median" else (lambda values: sum(values) / len(values))
    estimate = reducer(first_values) - reducer(second_values)
    rng = random.Random(seed)
    bootstrap: list[float] = []
    for _ in range(iterations):
        resample_first = [first_values[rng.randrange(len(first_values))] for _ in first_values]
        resample_second = [second_values[rng.randrange(len(second_values))] for _ in second_values]
        bootstrap.append(reducer(resample_first) - reducer(resample_second))
    return {
        "estimate": estimate,
        "ci_2_5": _percentile(bootstrap, 0.025),
        "ci_97_5": _percentile(bootstrap, 0.975),
        "sample_a": len(first_values),
        "sample_b": len(second_values),
    }


def _paired_mean(
    values: pd.Series,
    *,
    iterations: int,
    seed: int,
) -> dict:
    clean = values.dropna().astype(float).tolist()
    if not clean:
        return {"estimate": math.nan, "ci_2_5": math.nan, "ci_97_5": math.nan, "sample_a": 0, "sample_b": 0}
    estimate = sum(clean) / len(clean)
    rng = random.Random(seed)
    bootstrap = [
        sum(clean[rng.randrange(len(clean))] for _ in clean) / len(clean)
        for _ in range(iterations)
    ]
    return {
        "estimate": estimate,
        "ci_2_5": _percentile(bootstrap, 0.025),
        "ci_97_5": _percentile(bootstrap, 0.975),
        "sample_a": len(clean),
        "sample_b": len(clean),
    }


def _fit_0930_clock_coefficient(panel: pd.DataFrame, outcome_suffix: str) -> float:
    stacked: list[dict] = []
    for _, row in panel.iterrows():
        for prefix, is_0930 in (("pre_equity_control", 0.0), ("equity_reaction", 1.0)):
            stacked.append(
                {
                    "y": row[f"{prefix}_{outcome_suffix}"],
                    "is_0930": is_0930,
                    "impulse_absolute": row["impulse_absolute_bp"],
                    "impulse_directional": row["impulse_directional_bp"],
                    "major": float(row["event_class"] == "A_major_0830"),
                    "minor": float(row["event_class"] == "B_minor_0830"),
                    "dow": int(row["day_of_week"]),
                }
            )
    data = pd.DataFrame.from_records(stacked).dropna()
    if data.empty:
        return math.nan
    columns = [np.ones(len(data)), data["is_0930"].to_numpy(float)]
    impulse_control = "impulse_directional" if outcome_suffix == "directional_bp" else "impulse_absolute"
    columns.append(data[impulse_control].to_numpy(float))
    columns.extend([data["major"].to_numpy(float), data["minor"].to_numpy(float)])
    for day in (1, 2, 3, 4):
        columns.append(data["dow"].eq(day).to_numpy(float))
    design = np.column_stack(columns)
    coefficients, _, rank, _ = np.linalg.lstsq(design, data["y"].to_numpy(float), rcond=None)
    if rank < 2:
        return math.nan
    return float(coefficients[1])


def _cluster_bootstrap_0930(
    panel: pd.DataFrame,
    *,
    outcome_suffix: str,
    iterations: int,
    seed: int,
) -> dict:
    clean = panel.dropna(
        subset=[
            f"pre_equity_control_{outcome_suffix}",
            f"equity_reaction_{outcome_suffix}",
            "impulse_absolute_bp",
            "impulse_directional_bp",
        ]
    ).copy()
    estimate = _fit_0930_clock_coefficient(clean, outcome_suffix)
    if clean.empty:
        return {"estimate": estimate, "ci_2_5": math.nan, "ci_97_5": math.nan, "sample_a": 0, "sample_b": 0}
    rng = random.Random(seed)
    bootstrap: list[float] = []
    for _ in range(iterations):
        positions = [rng.randrange(len(clean)) for _ in range(len(clean))]
        sample = clean.iloc[positions].reset_index(drop=True)
        coefficient = _fit_0930_clock_coefficient(sample, outcome_suffix)
        if pd.notna(coefficient):
            bootstrap.append(coefficient)
    return {
        "estimate": estimate,
        "ci_2_5": _percentile(bootstrap, 0.025),
        "ci_97_5": _percentile(bootstrap, 0.975),
        "sample_a": len(clean),
        "sample_b": len(clean),
    }


def run_registered_event_tests(
    prices: pd.DataFrame,
    features: pd.DataFrame,
    *,
    iterations: int = 2000,
    seed: int = 830930,
    minimum_sample: int = 30,
    config: StudyConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run descriptive registered contrasts without declaring strategy success."""

    panel = build_test_panel(prices, features, config=config)
    tests: list[tuple[str, str, str, dict, str]] = []
    tests.append(
        (
            "H01",
            "Literature-supported",
            "Major vs no-meaningful-08:30 mean absolute 08:30–08:35 return",
            _group_contrast(
                panel,
                value="impulse_absolute_bp",
                group="event_class",
                first="A_major_0830",
                second="C_no_meaningful_0830",
                statistic="mean",
                iterations=iterations,
                seed=seed + 1,
            ),
            "bp",
        )
    )
    tests.append(
        (
            "H02",
            "Literature-supported",
            "Major vs minor 08:30 mean high-low range",
            _group_contrast(
                panel,
                value="impulse_range_bp",
                group="event_class",
                first="A_major_0830",
                second="B_minor_0830",
                statistic="mean",
                iterations=iterations,
                seed=seed + 2,
            ),
            "bp",
        )
    )
    tests.append(
        (
            "H05",
            "Inferred",
            "Adjusted 09:30 indicator in matched 20-minute absolute-return panel",
            _cluster_bootstrap_0930(
                panel,
                outcome_suffix="absolute_bp",
                iterations=iterations,
                seed=seed + 5,
            ),
            "bp",
        )
    )
    tests.append(
        (
            "H06",
            "Exploratory",
            "Adjusted 09:30 indicator in matched 20-minute directional-return panel",
            _cluster_bootstrap_0930(
                panel,
                outcome_suffix="directional_bp",
                iterations=iterations,
                seed=seed + 6,
            ),
            "bp",
        )
    )
    no_1000 = panel[~panel["important_1000_release"] & ~panel["minor_1000_release"]]
    tests.append(
        (
            "H11",
            "Inferred",
            "No-10:00-release paired secondary-minus-delivery absolute return",
            _paired_mean(
                no_1000["delta_1000_vs_delivery_absolute_bp"],
                iterations=iterations,
                seed=seed + 11,
            ),
            "bp",
        )
    )
    release_group = panel[panel["important_1000_release"] | ~panel["minor_1000_release"]].copy()
    release_group["release_1000"] = release_group["important_1000_release"].map(
        {True: "important", False: "none"}
    )
    tests.append(
        (
            "H12",
            "Literature-supported",
            "Important vs no-10:00-release mean 10:00–10:30 absolute return",
            _group_contrast(
                release_group,
                value="secondary_absolute_bp",
                group="release_1000",
                first="important",
                second="none",
                statistic="mean",
                iterations=iterations,
                seed=seed + 12,
            ),
            "bp",
        )
    )

    full_reversal = features.get("lifecycle_state_1m", pd.Series(index=features.index, dtype=str)).eq(
        "2_0830_false_breakout_full_reversal"
    )
    path_panel = features.assign(full_reversal=full_reversal.astype(float)).reset_index()
    path_panel["path_group"] = path_panel.apply(
        lambda row: "reentry"
        if bool(row.get("reentry_before_acceptance", False))
        else "acceptance"
        if pd.notna(row.get("directional_boundary_acceptance_time"))
        else "neither",
        axis=1,
    )
    tests.append(
        (
            "H07",
            "Practitioner-derived",
            "Full-reversal probability: re-entry before acceptance minus acceptance",
            _group_contrast(
                path_panel,
                value="full_reversal",
                group="path_group",
                first="reentry",
                second="acceptance",
                statistic="mean",
                iterations=iterations,
                seed=seed + 7,
            ),
            "probability points",
        )
    )

    records: list[dict] = []
    for hypothesis, label, test, result, unit in tests:
        minimum_cell = min(result["sample_a"], result["sample_b"])
        records.append(
            {
                "hypothesis_id": hypothesis,
                "register_label": label,
                "test": test,
                **result,
                "unit": unit,
                "sample_warning": (
                    f"INSUFFICIENT SAMPLE: smallest cell {minimum_cell} < {minimum_sample}"
                    if minimum_cell < minimum_sample
                    else ""
                ),
                "decision_status": "Not automatically adjudicated; apply hypothesis and stability gates",
            }
        )
    return panel, pd.DataFrame.from_records(records)
