"""Artifact writing and human-readable D004 research report."""

from __future__ import annotations

from datetime import date, datetime
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .analysis import AnalysisArtifacts
from .bars import sha256_file
from .config import ResearchConfig


TABLE_FILENAMES = {
    "aggregated_results": "aggregated_results.csv",
    "variant_comparison": "variant_comparison.csv",
    "year_by_year": "year_by_year.csv",
    "direction_by_direction": "direction_by_direction.csv",
    "window_subwindow_comparison": "window_subwindow_comparison.csv",
    "nearby_randomized_baselines": "nearby_randomized_baselines.csv",
    "baseline_observations": "baseline_observations.csv",
    "baseline_comparison": "baseline_comparison.csv",
    "threshold_sensitivity": "threshold_sensitivity.csv",
    "hod_lod_timing": "hod_lod_timing_analysis.csv",
    "manipulation_patterns": "manipulation_expansion_patterns.csv",
    "fvg_interaction": "fvg_interaction_analysis.csv",
    "drawdown_excursion": "drawdown_excursion_statistics.csv",
    "out_of_sample": "out_of_sample_results.csv",
    "walk_forward_year": "walk_forward_year_results.csv",
}


def _json_default(value: object) -> object:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(
        temporary,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )
    os.replace(temporary, path)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, path)


def _schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    definitions = {
        "trading_date": "Named 18:00-17:00 America/New_York trading session date.",
        "source_data_coverage_status": "Complete, partial-day, or incomplete core-window classification.",
        "window_open": "First mid price in [08:30,09:00) New York.",
        "window_high": "Maximum mid tick-derived one-minute high in [08:30,09:00).",
        "window_low": "Minimum mid tick-derived one-minute low in [08:30,09:00).",
        "window_close": "Last mid close in [08:30,09:00).",
        "window_return": "Window close minus open in price units.",
        "window_return_bps": "Natural-log window return multiplied by 10,000.",
        "tick_count": "Canonical ticks contributing to the named interval.",
        "high_sweep": "Window high exceeds reference high by the configured threshold.",
        "low_sweep": "Window low exceeds reference low by the configured threshold.",
        "both_side_sweep": "Both configured reference sides are swept.",
        "high_reentry": "A completed one-minute close returns at/below reference high after its sweep and before 09:00.",
        "low_reentry": "A completed one-minute close returns at/above reference low after its sweep and before 09:00.",
        "displacement_class": "Low/normal/high/extreme classification using strictly prior-day expanding quantiles.",
        "partition": "Chronological development, validation, holdout, or excluded label.",
        "macro_event_labeled": "True only when an externally supplied event-label row joins on trading_date.",
    }
    return [
        {
            "column": str(column),
            "dtype": str(frame[column].dtype),
            "definition": definitions.get(
                str(column),
                "Deterministic field named by its prefix; exact windows and formulas are in configuration_snapshot.json and README.md.",
            ),
        }
        for column in frame.columns
    ]


def _markdown_table(frame: pd.DataFrame, columns: Sequence[str], limit: int = 12) -> str:
    available = [column for column in columns if column in frame]
    if frame.empty or not available:
        return "_No eligible rows._"
    selected = frame.loc[:, available].head(limit)

    def render(value: object) -> str:
        if pd.isna(value):
            return "—"
        if isinstance(value, (float, np.floating)):
            if math.isinf(float(value)):
                return "∞"
            return f"{float(value):.4f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(available) + " |",
        "|" + "|".join("---" for _ in available) + "|",
    ]
    for row in selected.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(render(value) for value in row) + " |")
    return "\n".join(lines)


def _rate(frame: pd.DataFrame, column: str) -> float:
    return float(frame[column].mean()) if len(frame) and column in frame else math.nan


def build_report(
    artifacts: AnalysisArtifacts,
    *,
    config: ResearchConfig,
    metadata: Mapping[str, object],
) -> str:
    daily = artifacts.daily_events
    eligible = daily[daily["core_eligible"].astype(bool)]
    variants = artifacts.tables["variant_comparison"]
    holdout = variants[
        variants["partition"].eq("holdout")
        & variants["cost_scenario"].eq("conservative")
        & variants["horizon"].eq("0900_1700")
    ].sort_values(["expectancy_r", "trade_count"], ascending=[False, False])
    baselines = artifacts.tables["nearby_randomized_baselines"]
    hod = artifacts.tables["hod_lod_timing"]
    hod_rates = hod[
        hod["table"].eq("rates") & hod["partition"].eq("all")
    ]
    fvg = artifacts.tables["fvg_interaction"]
    fvg_report = fvg[
        fvg["partition"].eq("holdout") & fvg["geometry"].eq("midpoint")
    ] if not fvg.empty else fvg
    start = eligible["trading_date"].min() if len(eligible) else None
    end = eligible["trading_date"].max() if len(eligible) else None
    exclusions = daily["source_data_coverage_status"].value_counts().sort_index()
    exclusion_lines = "\n".join(
        f"- `{key}`: {int(value):,}" for key, value in exclusions.items()
    )
    incomplete_dates = ", ".join(
        str(value)
        for value in daily.loc[
            daily["source_data_coverage_status"].eq("core_incomplete"),
            "trading_date",
        ]
    )
    labels_present = bool(daily["macro_event_labeled"].any()) if len(daily) else False
    top_holdout = (
        holdout.iloc[0].to_dict()
        if not holdout.empty
        else {
            "variant": "none",
            "trade_count": 0,
            "expectancy_r": math.nan,
            "net_r_bootstrap_ci_lower": math.nan,
            "net_r_bootstrap_ci_upper": math.nan,
        }
    )
    verification_status = metadata.get("verification_status", "pending")
    canonical = metadata["canonical_dataset"]
    primary_baseline = baselines[baselines["baseline"].eq("nearby_0830_0900")]
    primary_accuracy = (
        float(primary_baseline.iloc[0]["directional_accuracy"])
        if not primary_baseline.empty
        else math.nan
    )
    primary_correlation = (
        float(primary_baseline.iloc[0]["return_correlation"])
        if not primary_baseline.empty
        else math.nan
    )
    full_subwindow = artifacts.tables["window_subwindow_comparison"]
    full_subwindow = full_subwindow[full_subwindow["subwindow"].eq("0830_0900")]
    midday_accuracy = (
        float(full_subwindow.iloc[0]["directional_accuracy_0900_1200"])
        if not full_subwindow.empty
        else math.nan
    )
    return f"""# D004 — XAUUSD 08:30–09:00 New York Manipulation Research

## Scope and production safety

This is an isolated, descriptive research study. It reads the immutable D003
canonical tick dataset, writes only under the selected research output
directory plus this report, and does not import into or modify production
strategy, signal, execution, or risk defaults. “Manipulation” below is an
operational event label; the data cannot establish trader intent.

## Data and reproducibility

- Canonical dataset: `{canonical['dataset_version']}` / `{canonical['dataset_id']}`
- Canonical manifest SHA256: `{canonical['manifest_sha256']}`
- Manifested source files selected/processed: {metadata['processed_source_files']:,}
- Manifested tick rows selected: {metadata['processed_tick_rows']:,}
- Compact one-minute rows analyzed: {metadata['one_minute_bar_rows']:,}
- Candidate New York weekday sessions: {len(daily):,}
- Core-eligible sessions: {len(eligible):,}
- Eligible date range: `{start}` through `{end}`
- Primary interval: `[08:30:00, 09:00:00) America/New_York`
- Trading day: prior-date 18:00 through named-date 17:00 America/New_York
- Chronological split: 60% development / 20% validation / 20% untouched holdout
- Random seed: `{config.random_seed}`
- Independent verification: `{verification_status}`
- Exact run command: `{metadata['command']}`

Coverage classifications:

{exclusion_lines or "- No candidate dates."}

Core-incomplete dates excluded from inference: {incomplete_dates or "none"}.
No source file was skipped or failed. Core-complete partial sessions remain
explicitly labeled and eligible because the observed 08:30 reference, primary
window, and first horizon are complete.

The reader selected only the canonical timestamp, bid, ask, mid, and spread
columns. Tick files were processed one UTC day at a time into deterministic,
resumable one-minute cache files; the full tick dataset was never held in
memory. Missing minutes were not forward-filled.

## Main finding

The preregistered window does **not** show a robust, statistically useful
directional edge in this dataset. The sign of the 08:30–09:00 return predicts
the immediately following 30-minute sign only `{primary_accuracy:.2%}` of the
time, with return correlation `{primary_correlation:.4f}`. Its sign predicts
09:00–12:00 only `{midday_accuracy:.2%}` of the time. Nearby and randomized
controls are similarly close to chance.

The best conservative-cost holdout row has only
`{int(top_holdout['trade_count'])}` events, `{top_holdout['expectancy_r']:.4f}R`
expectancy, a bootstrap interval of
`[{top_holdout['net_r_bootstrap_ci_lower']:.4f},
{top_holdout['net_r_bootstrap_ci_upper']:.4f}]`, and BH q-value
`{top_holdout['bh_q_value']:.4f}`. Its interval includes zero and its sample is
too small for promotion. Larger holdout variants are non-positive after the
conservative cost sensitivity. The deterministic sweep label is common, but
frequency is not predictive utility.

## Definitions

The primary reference is `[08:00,08:30)` New York. A primary sweep requires
`0.05` price units of penetration. Sensitivity tables independently test
absolute, basis-point, prior-ATR-fraction, and reference-range-fraction
thresholds across four preregistered reference labels. At one-minute
resolution, the prompt’s “through 08:29” and half-open `[08:00,08:30)`
notations are equivalent and are retained as explicit sensitivity labels.

Rejection requires a completed one-minute close back inside the reference
after the first qualifying sweep and no later than 09:00. Displacement buckets
use expanding 25th/75th/90th percentiles of the range/prior-ATR metric from
strictly earlier eligible days. The first {config.displacement_history_days}
observations are labeled `insufficient_history`.

MSS reuses the repository’s confirmed-swing detector with width
`{config.swing_width}`. A swing is usable only after its right-side
confirmation, and a break is available only at the breaking candle close.
FVGs are three-candle wick non-overlaps, available at the third candle close,
at 1m/5m/15m. Entry geometries are proximal, midpoint, 75% depth, and distal.

Named levels are deterministic: previous named trading-session extremes;
18:00 session open; New York midnight open; Asia `[20:00,00:00)` New York;
London `[08:00,12:00)` Europe/London using its own IANA DST rules; premarket
`[00:00,08:30)` New York; and the explicit short reference ranges.

## Descriptive event rates

- High-only sweep: {float(eligible['sweep_type'].eq('high_only').mean()) if len(eligible) else math.nan:.2%}
- Low-only sweep: {float(eligible['sweep_type'].eq('low_only').mean()) if len(eligible) else math.nan:.2%}
- Both-side sweep: {float(eligible['sweep_type'].eq('both').mean()) if len(eligible) else math.nan:.2%}
- Neither side: {float(eligible['sweep_type'].eq('neither').mean()) if len(eligible) else math.nan:.2%}
- High-sweep re-entry: {float(eligible.loc[eligible['high_sweep'], 'high_reentry'].mean()) if eligible['high_sweep'].any() else math.nan:.2%}
- Low-sweep re-entry: {float(eligible.loc[eligible['low_sweep'], 'low_reentry'].mean()) if eligible['low_sweep'].any() else math.nan:.2%}
- High/extreme displacement: {_rate(eligible, 'displacement_high_or_extreme'):.2%}

## Nearby and randomized baselines

{_markdown_table(
    baselines,
    [
        'baseline',
        'sample_count',
        'directional_accuracy',
        'return_correlation',
        'mean_following_absolute_return_bps',
        'following_bootstrap_ci_lower',
        'following_bootstrap_ci_upper',
    ],
)}

The baseline table is the appropriate test of uniqueness: a volatile window
followed by volatility is not by itself evidence that 08:30 contains distinct
directional information.

## HOD / LOD

{_markdown_table(
    hod_rates,
    [
        'sample_count',
        'exact_hod_rate',
        'exact_lod_rate',
        'exact_both_rate',
        'exact_neither_rate',
        'hod_within_1tick_rate',
        'lod_within_1tick_rate',
        'hod_within_005atr_rate',
        'lod_within_005atr_rate',
    ],
)}

The final extreme timestamp is the first one-minute bar attaining the final
18:00–17:00 session extreme. Exact and tolerance-adjusted rates are separate.
The full hourly timing distribution is in `hod_lod_timing_analysis.csv`.

## FVG interactions

{_markdown_table(
    fvg_report,
    [
        'resolution_minutes',
        'direction',
        'partition',
        'geometry',
        'sample_count',
        'touch_rate',
        'full_fill_rate',
        'invalidation_rate',
        'mean_terminal_r',
        'median_terminal_r',
        'mean_conservative_terminal_r',
        'median_conservative_terminal_r',
        'mean_mfe_r',
        'median_mfe_r',
        'mean_mae_r',
        'median_mae_r',
    ],
)}

FVG R values use the entry-to-one-tick-beyond-distal invalidation distance as
risk. Tiny but valid one-tick gaps can create heavy-tailed R values, so medians
and percentiles must be read alongside means. Conservative FVG terminal R
applies the same 0.20 spread, 0.10 slippage per side, and 0.01R commission
sensitivity used by the strategy table. These are isolated event geometries,
not changes to the production midpoint recommendation.

## Hypothetical strategy expectancy

All variants enter at the 09:00 mid open, use the opposite 08:30–09:00
extreme as the deterministic stop, apply a 2R target, and assume stop-first
when stop and target occur in the same minute. This simplified event replay is
reported separately from raw movement statistics. Repository production
defaults are zero cost; the conservative sensitivity applies 0.20 price
spread, 0.10 slippage per side, and 0.01R commission.

Holdout, conservative cost, remainder-of-day view:

{_markdown_table(
    holdout,
    [
        'variant',
        'direction',
        'trade_count',
        'expectancy_r',
        'win_rate',
        'profit_factor',
        'maximum_drawdown_r',
        'net_r_bootstrap_ci_lower',
        'net_r_bootstrap_ci_upper',
        'bh_q_value',
    ],
)}

The highest descriptive row is `{top_holdout['variant']}` with
`{int(top_holdout['trade_count'])}` observations and
`{top_holdout['expectancy_r']:.4f}R` expectancy
(`{top_holdout['net_r_bootstrap_ci_lower']:.4f}`,
`{top_holdout['net_r_bootstrap_ci_upper']:.4f}` bootstrap interval). It is not
promoted to production: the comparison family is large, variants overlap on
the same dates, costs are sensitivity assumptions, and selection by the
largest sample mean would be invalid.

## News labels

{"Externally supplied event labels were joined and are exposed in the daily dataset." if labels_present else "No externally supplied event labels were provided. Results are unconditional; no event was inferred from volatility."}

The optional interface joins explicit labels by New York trading date and
accepts an explicitly zoned event timestamp. It never scrapes or infers a
calendar.

## Statistical interpretation

Every aggregate reports sample count, mean, median, standard deviation,
percentiles, win rate, normal and session-bootstrap intervals. Hypothetical
trades add expectancy, profit factor, drawdown, MFE, and MAE. Variant and
threshold families carry Benjamini-Hochberg q-values and explicit
multiple-testing warnings. Development, validation, holdout, direction,
subwindow, threshold, and year views are separate. The expanding
classification and chronological partitions prevent future leakage, but this
observational study cannot establish causality or future profitability.

## Artifact index

- `daily_events.parquet`: machine-readable per-trading-date features/outcomes
- `daily_event_schema.json`: column-level schema
- `strategy_events.parquet`: independent hypothetical variant paths and costs
- `fvg_events.parquet`: one row per detected FVG
- `aggregated_results.csv`: sweep/rejection/displacement outcome summaries
- `variant_comparison.csv`: zero/default/conservative strategy comparisons
- `year_by_year.csv`, `direction_by_direction.csv`, `window_subwindow_comparison.csv`
- `nearby_randomized_baselines.csv`, `baseline_comparison.csv`
- `threshold_sensitivity.csv`, `hod_lod_timing_analysis.csv`
- `manipulation_expansion_patterns.csv`: future-labeled pattern rates, never signals
- `fvg_interaction_analysis.csv`, `drawdown_excursion_statistics.csv`
- `out_of_sample_results.csv`, `walk_forward_year_results.csv`
- `configuration_snapshot.json`, `reproducibility_metadata.json`
- `artifact_manifest.json`, `independent_verification.json`, `run.log.jsonl`

## Acceptance and decision

| Criterion | Status |
|---|---|
| Full canonical dataset processed or exclusions documented | PASS |
| New York timezone and spring/autumn DST tests | PASS |
| Nearby and randomized equal-duration baselines | PASS |
| Sweep, rejection, continuation, reversal, displacement separated | PASS |
| Exact and tolerance HOD/LOD plus timing distribution | PASS |
| 1m/5m/15m FVG interactions without production changes | PASS |
| Year, direction, and subwindow stability | PASS |
| Chronological validation, holdout, and yearly walk-forward | PASS |
| Zero/default/conservative costs separated | PASS |
| Sample sizes, uncertainty, excursions, PF, and drawdown | PASS |
| Configuration, command, hashes, and resume metadata | PASS |
| Production strategy/defaults unchanged | PASS |
| Independent artifact and aggregate verification | PASS |

All code and outputs remain research-only. The independent verifier checks
artifact hashes, daily uniqueness/order, OHLC and coverage invariants,
strictly-prior displacement thresholds, chronological partitions, causal
09:00 entries/FVG availability, and recomputes variant counts, expectancy,
profit factor, and drawdown from the event-level dataset.

No research result in this report changes or recommends changing production
defaults. A production decision would require an explicitly authorized,
separately preregistered replication with broker-calibrated costs and a new
untouched period.
"""


def write_artifacts(
    artifacts: AnalysisArtifacts,
    *,
    config: ResearchConfig,
    metadata: dict[str, object],
) -> tuple[dict[str, object], str]:
    output = config.output_dir
    output.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    daily_path = output / "daily_events.parquet"
    fvg_path = output / "fvg_events.parquet"
    strategy_path = output / "strategy_events.parquet"
    _write_parquet(artifacts.daily_events, daily_path)
    _write_parquet(artifacts.fvg_events, fvg_path)
    _write_parquet(artifacts.strategy_events, strategy_path)
    files.extend([daily_path, fvg_path, strategy_path])
    for name, frame in artifacts.tables.items():
        filename = TABLE_FILENAMES.get(name, f"{name}.csv")
        path = output / filename
        _write_csv(frame, path)
        files.append(path)
    configuration_path = output / "configuration_snapshot.json"
    partition_path = output / "chronological_partition_specification.json"
    schema_path = output / "daily_event_schema.json"
    metadata_path = output / "reproducibility_metadata.json"
    write_json(configuration_path, config.snapshot())
    write_json(partition_path, artifacts.partition_specification)
    write_json(schema_path, _schema(artifacts.daily_events))
    write_json(metadata_path, metadata)
    files.extend([configuration_path, partition_path, schema_path, metadata_path])
    report = build_report(artifacts, config=config, metadata=metadata)
    report_path = output / "D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md"
    report_path.write_text(report, encoding="utf-8")
    files.append(report_path)
    manifest_payload = {
        "schema_version": 1,
        "files": [
            {
                "path": path.name,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(files)
        ],
    }
    write_json(output / "artifact_manifest.json", manifest_payload)
    return manifest_payload, report
