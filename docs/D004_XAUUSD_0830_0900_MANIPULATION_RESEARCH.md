# D004 — XAUUSD 08:30–09:00 New York Manipulation Research

## Scope and production safety

This is an isolated, descriptive research study. It reads the immutable D003
canonical tick dataset, writes only under the selected research output
directory plus this report, and does not import into or modify production
strategy, signal, execution, or risk defaults. “Manipulation” below is an
operational event label; the data cannot establish trader intent.

## Data and reproducibility

- Canonical dataset: `d003-v1` / `3ef1612c3ac73469e0b0`
- Canonical manifest SHA256: `16a560443f6429e4250d68af7b5a02d7da255d7dfcf7b2945d34a2c29a9d62ab`
- Manifested source files selected/processed: 1,554
- Manifested tick rows selected: 270,997,638
- Compact one-minute rows analyzed: 1,772,168
- Candidate New York weekday sessions: 1,303
- Core-eligible sessions: 1,289
- Eligible date range: `2021-01-04` through `2025-12-31`
- Primary interval: `[08:30:00, 09:00:00) America/New_York`
- Trading day: prior-date 18:00 through named-date 17:00 America/New_York
- Chronological split: 60% development / 20% validation / 20% untouched holdout
- Random seed: `4004`
- Independent verification: `PASS`
- Exact run command: `/Users/serhanceylan/miniconda3/bin/python -m research.manipulation_0830_0900 run --dataset-root data/canonical/xauusd_ticks --output-dir research_outputs/D004_XAUUSD_0830_0900 --timezone America/New_York --window-start 08:30 --window-end 09:00 --bar-resolutions 1,5,15 --reference-range 0800_0830 --sweep-threshold-mode absolute --sweep-threshold 0.05 --worker-count 4 --random-seed 4004 --bootstrap-resamples 1000 --resume --report-path docs/D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md`

Coverage classifications:

- `complete`: 1,248
- `core_complete_day_partial`: 41
- `core_incomplete`: 14

Core-incomplete dates excluded from inference: 2021-04-02, 2021-12-24, 2022-04-15, 2022-12-26, 2023-01-02, 2023-03-09, 2023-04-07, 2023-12-25, 2024-01-01, 2024-03-29, 2024-12-25, 2025-01-01, 2025-04-18, 2025-12-25.
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
the immediately following 30-minute sign only `48.25%` of the
time, with return correlation `-0.0139`. Its sign predicts
09:00–12:00 only `50.16%` of the time. Nearby and randomized
controls are similarly close to chance.

The best conservative-cost holdout row has only
`19` events, `0.1923R`
expectancy, a bootstrap interval of
`[-0.3589,
0.7571]`, and BH q-value
`0.7803`. Its interval includes zero and its sample is
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
strictly earlier eligible days. The first 20
observations are labeled `insufficient_history`.

MSS reuses the repository’s confirmed-swing detector with width
`2`. A swing is usable only after its right-side
confirmation, and a break is available only at the breaking candle close.
FVGs are three-candle wick non-overlaps, available at the third candle close,
at 1m/5m/15m. Entry geometries are proximal, midpoint, 75% depth, and distal.

Named levels are deterministic: previous named trading-session extremes;
18:00 session open; New York midnight open; Asia `[20:00,00:00)` New York;
London `[08:00,12:00)` Europe/London using its own IANA DST rules; premarket
`[00:00,08:30)` New York; and the explicit short reference ranges.

## Descriptive event rates

- High-only sweep: 36.54%
- Low-only sweep: 36.54%
- Both-side sweep: 18.46%
- Neither side: 8.46%
- High-sweep re-entry: 80.54%
- Low-sweep re-entry: 85.19%
- High/extreme displacement: 24.59%

## Nearby and randomized baselines

| baseline | sample_count | directional_accuracy | return_correlation | mean_following_absolute_return_bps | following_bootstrap_ci_lower | following_bootstrap_ci_upper |
|---|---|---|---|---|---|---|
| nearby_0730_0800 | 1289 | 0.4938 | 0.0064 | 12.5465 | -1.1004 | 0.8582 |
| nearby_0800_0830 | 1289 | 0.5019 | 0.0363 | 18.8281 | -1.1487 | 1.8494 |
| nearby_0830_0900 | 1288 | 0.4825 | -0.0139 | 14.3704 | -1.3355 | 0.7958 |
| nearby_0900_0930 | 1287 | 0.4957 | 0.0165 | 18.5237 | -2.3248 | 0.2316 |
| nearby_0930_1000 | 1285 | 0.5128 | 0.0383 | 17.7882 | -0.9282 | 1.7428 |
| randomized_equal_duration | 1280 | 0.5051 | 0.0294 | 10.2872 | -0.2096 | 1.4645 |

The baseline table is the appropriate test of uniqueness: a volatile window
followed by volatility is not by itself evidence that 08:30 contains distinct
directional information.

## HOD / LOD

| sample_count | exact_hod_rate | exact_lod_rate | exact_both_rate | exact_neither_rate | hod_within_1tick_rate | lod_within_1tick_rate | hod_within_005atr_rate | lod_within_005atr_rate |
|---|---|---|---|---|---|---|---|---|
| 1289 | 0.0590 | 0.0613 | 0.0031 | 0.8829 | 0.0590 | 0.0636 | 0.0652 | 0.0690 |

The final extreme timestamp is the first one-minute bar attaining the final
18:00–17:00 session extreme. Exact and tolerance-adjusted rates are separate.
The full hourly timing distribution is in `hod_lod_timing_analysis.csv`.

## FVG interactions

| resolution_minutes | direction | partition | geometry | sample_count | touch_rate | full_fill_rate | invalidation_rate | mean_terminal_r | median_terminal_r | mean_conservative_terminal_r | median_conservative_terminal_r | mean_mfe_r | median_mfe_r | mean_mae_r | median_mae_r |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | bearish | holdout | midpoint | 857 | 0.9428 | 0.9172 | 0.8950 | -9.2129 | -7.9208 | -11.9182 | -9.1451 | 122.0426 | 39.7490 | 110.2440 | 45.9573 |
| 1 | bullish | holdout | midpoint | 918 | 0.9542 | 0.9150 | 0.8834 | 3.6233 | 7.3775 | 0.8368 | 5.9288 | 118.4433 | 45.5879 | 133.5973 | 44.8985 |
| 5 | bearish | holdout | midpoint | 151 | 0.9205 | 0.8013 | 0.7947 | -24.3412 | -3.0765 | -26.1043 | -3.8238 | 71.9824 | 21.1151 | 81.1781 | 21.0994 |
| 5 | bullish | holdout | midpoint | 179 | 0.9218 | 0.8268 | 0.7821 | -8.5044 | 7.9040 | -10.3420 | 7.0699 | 70.2138 | 27.4970 | 76.2441 | 20.9707 |
| 15 | bearish | holdout | midpoint | 54 | 0.7963 | 0.6852 | 0.6852 | 0.7788 | -1.7762 | 0.1947 | -1.9306 | 20.7645 | 6.6629 | 22.1549 | 10.1050 |
| 15 | bullish | holdout | midpoint | 68 | 0.7794 | 0.6471 | 0.6176 | 27.1771 | 4.2152 | 26.2429 | 3.8855 | 51.4696 | 13.6471 | 28.3265 | 9.2335 |

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

| variant | direction | trade_count | expectancy_r | win_rate | profit_factor | maximum_drawdown_r | net_r_bootstrap_ci_lower | net_r_bootstrap_ci_upper | bh_q_value |
|---|---|---|---|---|---|---|---|---|---|
| displacement_only_continuation | short | 19 | 0.1923 | 0.4211 | 1.4256 | 2.7951 | -0.3589 | 0.7571 | 0.7803 |
| displacement_only_continuation | long | 12 | -0.0115 | 0.5833 | 0.9744 | 2.0650 | -0.5560 | 0.5659 | 0.9992 |
| directional_baseline_continuation | short | 122 | -0.1285 | 0.3361 | 0.8172 | 24.1936 | -0.3660 | 0.1105 | 0.6249 |
| directional_baseline_continuation | long | 136 | -0.1495 | 0.3603 | 0.7807 | 28.5604 | -0.3553 | 0.0777 | 0.4868 |
| low_sweep_bearish_continuation | short | 128 | -0.1798 | 0.3359 | 0.7619 | 34.3218 | -0.4217 | 0.0546 | 0.4452 |
| high_sweep_bullish_continuation | long | 142 | -0.2807 | 0.3592 | 0.6658 | 48.9053 | -0.5219 | -0.0291 | 0.2031 |
| sweep_plus_displacement_plus_fvg | long | 18 | -0.3267 | 0.5000 | 0.7049 | 12.1525 | -2.0001 | 0.7974 | 0.8731 |
| sweep_plus_displacement | long | 19 | -0.4232 | 0.4737 | 0.6360 | 13.9552 | -1.9744 | 0.7139 | 0.7921 |
| sweep_plus_displacement | short | 12 | -0.4865 | 0.2500 | 0.4964 | 8.8351 | -1.2794 | 0.4316 | 0.6012 |
| low_sweep_bullish_expansion | long | 128 | -0.5063 | 0.3281 | 0.5131 | 70.4756 | -0.8547 | -0.1936 | 0.0183 |
| large_impulse_full_reversal | long | 19 | -0.5296 | 0.4211 | 0.5661 | 15.0584 | -2.0656 | 0.5098 | 0.7096 |
| large_impulse_full_reversal | short | 12 | -0.5461 | 0.2500 | 0.4675 | 9.5513 | -1.3070 | 0.4044 | 0.5645 |

The highest descriptive row is `displacement_only_continuation` with
`19` observations and
`0.1923R` expectancy
(`-0.3589`,
`0.7571` bootstrap interval). It is not
promoted to production: the comparison family is large, variants overlap on
the same dates, costs are sensitivity assumptions, and selection by the
largest sample mean would be invalid.

## News labels

No externally supplied event labels were provided. Results are unconditional; no event was inferred from volatility.

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
