# R:R Bottleneck Analysis

## Scope

This report analyzes why the unchanged `RULE_ONLY` funnel rejects most candidates at the `2.0` minimum risk/reward gate. It does not change the minimum R:R, stop placement, target selection, entry model, setup rules, or lifecycle behavior.

The analysis uses the validated local XAUUSD M15 dataset:

- UTC range: `2023-07-25 22:00` through `2026-07-14 16:45`.
- Bars: `69,768`.
- Fixed-bias views: BULLISH/LONG and BEARISH/SHORT, replayed separately.
- Pre-R:R candidates with target and minimum stop distance available: `4,800`.
- R:R rejected: `4,551`.
- Nominal R:R passed: `249`.

All `4,551` rejects were measured row by row. Tables below aggregate those candidate-level records.

## Measurement Definitions

| Field | Diagnostic definition |
| --- | --- |
| Stop distance | Absolute FVG-midpoint entry to configured structural stop distance. |
| Target distance | Directional FVG-midpoint entry to selected TP2 distance. |
| Achieved R:R | Target distance divided by stop distance, exactly as used by the strategy gate. |
| Sweep size | Raid-wick penetration beyond the selected swept swing level. |
| FVG size | FVG high minus FVG low. |
| MSS size | Confirming close displacement beyond the broken MSS swing. |
| Stop buffer | Configured `0.10` price units for every candidate. |
| Target type | Causal opposing swing high for LONG or causal opposing swing low for SHORT. |
| Diagnostic equilibrium | Midpoint between the swept structural level and selected TP2. This is analysis metadata, not a strategy rule. |
| Midpoint distance | Signed entry distance from diagnostic equilibrium. Positive means LONG discount or SHORT premium relative to that range; negative means the entry is on the target-side half. |
| Entry range fraction | Directional distance from swept level to entry divided by swept-level-to-target distance. Lower is nearer the swept level. |
| Order wait/fill | Rejects create no actual order. Reported wait/fill values are counterfactual probes using the unchanged eight-bar, invalidation-first lifecycle. No trade result is generated. |
| ATR normalization | Causal 14-bar average true range at activation, used only to compare different price/volatility regimes. |

## Headline Results

Rejected candidates have a large stop and a close target relative to their activation-time volatility:

| Population | Count | Avg stop | Median stop | Avg target | Median target | Avg R:R | Median R:R | Median stop ATR | Median target ATR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rejected | 4,551 | 18.31 | 10.25 | 4.13 | 1.66 | 0.328 | 0.164 | 2.474 | 0.427 |
| Nominal pass | 249 | 3.12 | 1.82 | 10.35 | 7.48 | 4.416 | 3.168 | 0.437 | 1.649 |
| Rejected, protective stop side only | 4,154 | 18.32 | 10.51 | 3.69 | 1.57 | 0.302 | 0.153 | 2.530 | 0.406 |
| Passed, protective stop side only | 153 | 3.21 | 1.70 | 10.33 | 7.20 | 4.416 | 2.972 | 0.437 | 1.594 |

The median reject therefore has a stop `5.67` times the ATR-normalized median of nominal passes and a target only `25.9%` as large. Both components differ materially.

## Exact Geometric Decomposition

For protective-side stops and a positive swept-level-to-target range, let:

- `D` be swept-level-to-target distance,
- `x` be swept-level-to-entry distance in the target direction,
- `b` be the `0.10` stop buffer.

The implemented geometry is:

```text
risk   = x + b
reward = D - x
R:R    = (D - x) / (x + b)
```

Before the buffer, `2R` requires `x / D <= 1/3`. The buffer makes the allowed fraction slightly smaller. The rejects decompose exhaustively as follows:

| Geometric condition | Rejects | Share |
| --- | ---: | ---: |
| Positive structural range, protective stop, entry beyond first third | 4,138 | 90.93% |
| Target not beyond swept level in the intended direction; stop also non-protective | 302 | 6.64% |
| Positive range but stop remains on the non-protective side of entry | 95 | 2.09% |
| Protective geometry inside the first third, rejected only after the `0.10` buffer | 16 | 0.35% |
| Total | 4,551 | 100.00% |

This is the direct root cause. In most rejected setups the post-MSS FVG midpoint appears after more than the first third of the current swept-level-to-target range has already been consumed. The same spatial condition simultaneously makes the stop far from entry and the remaining target close.

The rejected median entry range fraction is `0.861`; the nominal-pass median is `0.140`. Lower entry range fraction distinguishes pass from rejection with AUC `0.978`, where `0.5` means no separation and `1.0` means perfect separation.

## Direction Comparison

| Direction | Rejects | Avg stop | Median stop | Avg target | Median target | Avg R:R | Median R:R | Wrong-side stop | Favorable midpoint |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LONG | 2,369 | 17.07 | 10.32 | 3.77 | 1.50 | 0.313 | 0.159 | 193 | 325 |
| SHORT | 2,182 | 19.66 | 10.19 | 4.52 | 1.84 | 0.345 | 0.173 | 204 | 362 |

LONG and SHORT are similar. SHORT rejects have slightly higher average target distance and R:R, but their medians remain far below `2.0`. Directional pass rates are `4.67%` LONG and `5.75%` SHORT, a difference of only `1.08` percentage points.

## Yearly Breakdown

Absolute distances rise with the XAUUSD price/volatility regime, especially in 2026, but rejected R:R remains stable and low.

| Period | Rejects | Avg stop | Median stop | Avg target | Median target | Avg R:R | Median R:R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 partial | 651 | 6.81 | 4.69 | 1.34 | 0.78 | 0.323 | 0.156 |
| 2024 | 1,511 | 10.34 | 6.74 | 2.11 | 1.20 | 0.329 | 0.171 |
| 2025 | 1,566 | 18.93 | 13.15 | 3.94 | 1.92 | 0.311 | 0.151 |
| 2026 YTD | 823 | 40.84 | 27.42 | 10.42 | 5.29 | 0.364 | 0.191 |

Median stop distance normalized by ATR is `2.70`, `2.36`, `2.56`, and `2.34` for 2023 through 2026. Median target distance is `0.45`, `0.42`, `0.41`, and `0.46 ATR`. The stable normalized relationship shows that nominal price inflation is not the explanation.

## Monthly Breakdown

| Month | Rejects | Avg stop | Avg target | Avg R:R | Median R:R |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2023-07 | 25 | 5.98 | 1.03 | 0.222 | 0.161 |
| 2023-08 | 120 | 4.94 | 0.99 | 0.284 | 0.154 |
| 2023-09 | 135 | 5.69 | 1.00 | 0.321 | 0.136 |
| 2023-10 | 130 | 7.67 | 1.55 | 0.330 | 0.151 |
| 2023-11 | 121 | 7.62 | 1.53 | 0.337 | 0.166 |
| 2023-12 | 120 | 8.39 | 1.70 | 0.364 | 0.158 |
| 2024-01 | 127 | 6.92 | 1.62 | 0.343 | 0.175 |
| 2024-02 | 72 | 4.99 | 0.85 | 0.284 | 0.161 |
| 2024-03 | 121 | 9.54 | 2.37 | 0.340 | 0.194 |
| 2024-04 | 145 | 13.64 | 2.72 | 0.344 | 0.138 |
| 2024-05 | 132 | 10.54 | 2.01 | 0.325 | 0.141 |
| 2024-06 | 144 | 15.53 | 2.04 | 0.305 | 0.116 |
| 2024-07 | 128 | 7.62 | 2.16 | 0.383 | 0.196 |
| 2024-08 | 136 | 11.02 | 2.64 | 0.330 | 0.191 |
| 2024-09 | 120 | 8.49 | 1.84 | 0.327 | 0.192 |
| 2024-10 | 138 | 7.56 | 1.82 | 0.341 | 0.217 |
| 2024-11 | 136 | 15.40 | 2.62 | 0.317 | 0.156 |
| 2024-12 | 112 | 8.97 | 1.86 | 0.284 | 0.160 |
| 2025-01 | 105 | 8.58 | 1.36 | 0.268 | 0.128 |
| 2025-02 | 146 | 13.01 | 3.44 | 0.365 | 0.194 |
| 2025-03 | 120 | 11.51 | 2.47 | 0.337 | 0.196 |
| 2025-04 | 122 | 24.86 | 5.38 | 0.250 | 0.142 |
| 2025-05 | 140 | 27.70 | 4.44 | 0.254 | 0.111 |
| 2025-06 | 114 | 12.22 | 3.43 | 0.372 | 0.259 |
| 2025-07 | 146 | 13.88 | 2.29 | 0.300 | 0.136 |
| 2025-08 | 144 | 13.15 | 2.52 | 0.317 | 0.168 |
| 2025-09 | 122 | 19.09 | 3.19 | 0.273 | 0.126 |
| 2025-10 | 150 | 34.68 | 7.24 | 0.300 | 0.148 |
| 2025-11 | 142 | 22.87 | 5.23 | 0.345 | 0.143 |
| 2025-12 | 115 | 21.44 | 5.64 | 0.345 | 0.173 |
| 2026-01 | 133 | 46.21 | 13.78 | 0.341 | 0.132 |
| 2026-02 | 93 | 49.44 | 11.72 | 0.364 | 0.211 |
| 2026-03 | 138 | 51.92 | 15.02 | 0.403 | 0.265 |
| 2026-04 | 142 | 34.17 | 8.91 | 0.367 | 0.199 |
| 2026-05 | 143 | 32.28 | 6.01 | 0.372 | 0.188 |
| 2026-06 | 111 | 34.60 | 8.26 | 0.374 | 0.185 |
| 2026-07 | 63 | 38.01 | 8.59 | 0.290 | 0.151 |

No month reaches an average rejected R:R of `0.5`. The bottleneck is persistent rather than isolated to one month or volatility regime.

## Stop-Distance Histogram

Percentages are within each rejected group.

| Stop distance | All | LONG | SHORT | 2023 | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `<1` | 1.3% | 1.3% | 1.3% | 4.1% | 1.5% | 0.5% | 0.0% |
| `1-<2` | 4.3% | 4.4% | 4.1% | 9.2% | 6.6% | 2.1% | 0.2% |
| `2-<4` | 14.0% | 14.3% | 13.7% | 26.4% | 21.0% | 8.7% | 1.5% |
| `4-<8` | 22.0% | 22.0% | 21.9% | 32.9% | 28.2% | 19.5% | 6.7% |
| `8-<16` | 23.8% | 24.6% | 22.9% | 20.1% | 24.8% | 26.4% | 19.8% |
| `16-<32` | 19.0% | 20.0% | 18.0% | 6.3% | 12.8% | 25.5% | 28.1% |
| `32-<64` | 11.0% | 9.8% | 12.3% | 0.9% | 4.5% | 14.0% | 25.3% |
| `64-<128` | 3.8% | 3.0% | 4.6% | 0.0% | 0.6% | 3.1% | 13.9% |
| `128+` | 0.9% | 0.7% | 1.1% | 0.0% | 0.0% | 0.2% | 4.6% |

## Target-Distance Histogram

| Target distance | All | LONG | SHORT | 2023 | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `<0.25` | 11.9% | 12.1% | 11.7% | 20.4% | 15.9% | 9.1% | 3.3% |
| `0.25-<0.5` | 10.3% | 10.8% | 9.8% | 18.4% | 11.8% | 8.3% | 5.2% |
| `0.5-<1` | 14.3% | 15.7% | 12.7% | 18.4% | 16.2% | 14.9% | 6.3% |
| `1-<2` | 19.2% | 20.3% | 18.0% | 21.8% | 22.5% | 19.3% | 10.8% |
| `2-<4` | 18.1% | 17.5% | 18.8% | 14.0% | 19.2% | 19.7% | 16.4% |
| `4-<8` | 14.3% | 13.5% | 15.2% | 6.0% | 11.3% | 17.6% | 20.2% |
| `8-<16` | 7.0% | 6.2% | 7.9% | 0.6% | 2.6% | 7.0% | 20.3% |
| `16-<32` | 3.2% | 2.5% | 4.0% | 0.3% | 0.5% | 3.0% | 11.1% |
| `32-<64` | 1.3% | 1.1% | 1.6% | 0.0% | 0.1% | 1.1% | 5.2% |
| `64+` | 0.2% | 0.3% | 0.2% | 0.0% | 0.0% | 0.1% | 1.2% |

## R:R Histogram

| Achieved R:R | All | LONG | SHORT | 2023 | 2024 | 2025 | 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `<0.05` | 22.9% | 23.7% | 22.0% | 23.8% | 22.9% | 24.4% | 19.4% |
| `0.05-<0.10` | 14.8% | 15.0% | 14.6% | 14.1% | 14.8% | 15.1% | 14.7% |
| `0.10-<0.25` | 22.8% | 23.4% | 22.1% | 24.1% | 22.6% | 22.0% | 23.7% |
| `0.25-<0.50` | 17.4% | 17.5% | 17.4% | 16.6% | 16.8% | 18.1% | 18.1% |
| `0.50-<0.75` | 8.5% | 8.0% | 9.0% | 7.2% | 9.7% | 8.2% | 7.9% |
| `0.75-<1.00` | 5.3% | 5.1% | 5.5% | 6.3% | 5.4% | 4.9% | 5.2% |
| `1.00-<1.25` | 3.2% | 2.8% | 3.7% | 3.1% | 2.6% | 3.4% | 4.1% |
| `1.25-<1.50` | 2.1% | 1.7% | 2.5% | 1.2% | 2.4% | 1.5% | 3.4% |
| `1.50-<1.75` | 2.0% | 2.0% | 2.0% | 2.0% | 2.0% | 1.6% | 2.7% |
| `1.75-<2.00` | 0.9% | 0.7% | 1.2% | 1.5% | 0.9% | 0.9% | 0.7% |

`60.5%` of rejects are below `0.25R`; only `43` rejects (`0.94%`) are between `1.75R` and `2.0R`. This is not a near-threshold crowding problem.

## Variable Attribution

Univariate AUC measures how well one variable separates nominal passes from rejects. Direction is chosen so higher AUC means more pass-like. Separation is `2 * |AUC - 0.5|`.

| Rank | Variable | AUC | Separation | Finding |
| ---: | --- | ---: | ---: | --- |
| 1 | Lower entry range fraction | 0.978 | 95.5% | Direct geometric location is strongest. |
| 2 | Lower stop distance / ATR | 0.951 | 90.2% | Stop excess strongly separates rejects. |
| 3 | More favorable equilibrium distance / ATR | 0.927 | 85.4% | All nominal passes are on the favorable side; 84.9% of rejects are not. |
| 4 | Larger target distance / ATR | 0.862 | 72.5% | Close targets are also material. |
| 5 | Shorter sweep-to-activation delay | 0.596 | 19.1% | Weak secondary association. |
| 6 | Shorter MSS-to-activation delay | 0.573 | 14.5% | Weak secondary association. |
| 7 | Larger FVG size / ATR | 0.562 | 12.4% | Tiny FVG size is weak, not dominant. |
| 8 | Smaller sweep size / ATR | 0.552 | 10.4% | Weak inverse association. |
| 9 | MSS size / ATR | 0.517 | 3.5% | Essentially no separation. |
| 10 | Counterfactual order wait | 0.500 | 0.0% | No explanatory value and occurs after the R:R decision. |

For the exact additive identity `log(R:R) = log(target distance) - log(stop distance)`, target distance accounts for approximately `72%` of observed log-R:R variance and inverse stop distance for `28%`. This variance decomposition does not contradict stop distance being the better threshold classifier: target distance varies more continuously, while a small-stop region sharply distinguishes passes.

The configured buffer is not material:

- median buffer share of rejected stop distance: `0.98%`;
- mean buffer share: `1.65%`;
- rejects that would reach `2R` with the buffer removed: `16 / 4,551` (`0.35%`).

## Nearest Filled-Trade Comparison

Each rejected setup was paired with the nearest actual filled, R:R-passing trade in activation time, restricted to the same direction and calendar year. There are 53 unique filled comparators. Because passing trades are rare, comparators are reused; the median temporal separation is `957` M15 bars and the 90th percentile is `3,686` bars.

| Variable | Rejected median | Nearest filled median | Median paired difference |
| --- | ---: | ---: | ---: |
| Stop distance / ATR | 2.474 | 0.593 | +1.882 |
| Target distance / ATR | 0.427 | 1.746 | -1.272 |
| Achieved R:R | 0.164 | 2.942 | -2.664 |
| Sweep size / ATR | 0.248 | 0.140 | +0.062 |
| FVG size / ATR | 0.252 | 0.299 | -0.049 |
| MSS size / ATR | 0.350 | 0.441 | -0.045 |
| Signed midpoint distance / ATR | -0.866 | 0.602 | -1.555 |
| Lifecycle wait bars | 2 counterfactual | 1 actual | +1 |

Normalized component replacement against the paired filled trade gives:

| Pair result | Rejects | Share | Interpretation |
| --- | ---: | ---: | --- |
| Both pass-like stop and target are required | 3,032 | 66.62% | Joint geometry dominates. |
| Pass-like stop alone is sufficient | 958 | 21.05% | Stop excess is the larger single-component contribution. |
| Pass-like target alone is sufficient | 536 | 11.78% | Target shortfall is material but smaller. |
| Either component alone is sufficient | 25 | 0.55% | Both differ enough to independently cross the gate. |

This pairing supports the direct geometric result: most failures cannot be attributed exclusively to stop placement or target selection. The combination is mismatched to the FVG midpoint location. When one component alone explains the difference, stop excess occurs about `1.8` times as often as target shortfall.

## Lifecycle Probe

Every rejected candidate has actual status `rr_rejected_not_activated`; no order exists under the strategy. The counterfactual probe used existing lifecycle ordering solely to describe retracement behavior:

| Counterfactual status | Count | Share | Median wait |
| --- | ---: | ---: | ---: |
| Filled | 1,895 | 41.64% | 2 bars |
| Expired | 1,277 | 28.06% | 8 bars |
| FVG invalidated | 889 | 19.53% | 1 bar |
| Stop invalidated | 489 | 10.74% | 1 bar |
| Structure invalidated | 1 | 0.02% | 1 bar |

Wait time cannot cause an R:R rejection because the R:R gate executes before order activation. Its AUC is effectively `0.500`.

## Geometry Audit Finding

The current `structural_stop_available` funnel stage checks absolute stop distance but does not classify stop side relative to entry. The analysis found:

- `493 / 4,800` candidates with a non-protective stop side;
- `397` of those are R:R rejects;
- `96` are nominal R:R passes;
- of those 96 nominal passes, 80 invalidate and 16 expire; none fill.

This does not explain the majority of R:R rejects. It does mean that nominal passes are not all clean structural comparators, so the report separately shows protective-side populations and uses actual filled trades for nearest-neighbor comparison. This is an observation only; no implementation change is made here.

## Target-Type Boundary

All candidates use one target hierarchy:

- LONG: causal opposing swing high;
- SHORT: causal opposing swing low.

There is no alternative target type in the current implementation, so this dataset cannot determine whether the hierarchy is wrong. It can determine only that the selected target is usually close relative to entry. Claiming a hierarchy defect would require testing a different strategy rule, which is outside this analysis.

## Ranked Rejection Explanations

There are not ten independent causal rejection codes; every row has the same `risk_reward_below_minimum` code. The following ranks measured explanations and explicitly marks weak or ruled-out alternatives. Categories overlap where noted.

| Rank | Explanation | Quantification | Assessment |
| ---: | --- | --- | --- |
| 1 | Entry is beyond the first third of positive structural range | 4,138 rejects; 90.93% | Dominant direct cause. |
| 2 | Joint stop excess and target shortfall | 3,032 nearest-filled pairs; 66.62% | Dominant component attribution. |
| 3 | Oversized stop relative to volatility | Median 2.474 ATR vs 0.593 nearest filled; AUC 0.951 | Strong. |
| 4 | Target too close relative to volatility | Median 0.427 ATR vs 1.746 nearest filled; AUC 0.862 | Strong but secondary to stop as classifier. |
| 5 | Non-protective stop-side geometry | 397 rejects; 8.72% | Material data-quality finding, not majority cause. |
| 6 | Target not beyond swept level in target direction | 302 rejects; 6.64%; subset of rank 5 | Structural-range inversion. |
| 7 | Activation delay after sweep/MSS | Median 17/12 bars in rejects vs 13/9 in passes; AUC 0.596/0.573 | Weak association, not sufficient explanation. |
| 8 | Small FVG | Median 0.252 ATR vs 0.361 nominal pass; AUC 0.562 | Weak. |
| 9 | Sweep or MSS size | Separation 10.4% and 3.5% | Weak to negligible. |
| 10 | Stop buffer, order wait, direction, year, or target type | Buffer explains 0.35%; wait AUC 0.500; direction/year pass-rate ranges are small; target type has no variation | Ruled out or not identifiable. |

## Representative Examples

`Probe` and `wait` remain counterfactual for rejects. Distances are XAUUSD price units.

| Example | UTC activation | Dir | Stop | Target | R:R | Stop ATR | Target ATR | Sweep | FVG | MSS | Midpoint dist | Probe | Wait | Nearest filled R:R |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Median reject | 2025-03-03 15:15 | LONG | 19.72 | 3.24 | 0.164 | 4.10 | 0.67 | 1.28 | 0.82 | 3.56 | -8.19 | Expired | 8 | 2.141 |
| Largest stop / ATR | 2024-06-10 02:45 | SHORT | 90.01 | 3.35 | 0.037 | 36.61 | 1.36 | 0.20 | 0.68 | 3.28 | -43.28 | Filled | 1 | 2.753 |
| Smallest target / ATR | 2025-04-08 12:00 | LONG | 20.53 | approximately 0.00 | approximately 0.000 | 3.76 | approximately 0.00 | 2.37 | 0.82 | 2.42 | -10.21 | FVG invalidated | 1 | 2.141 |
| Nearest threshold | 2025-08-22 13:45 | LONG | 2.82 | 5.62 | 1.998 | 0.80 | 1.61 | 0.15 | 2.61 | 2.72 | 1.45 | Expired | 8 | 2.942 |
| Non-protective stop side | 2025-11-04 06:45 | LONG | 22.65 | 10.04 | 0.443 | 3.21 | 1.42 | 4.96 | 1.61 | 0.47 | 16.40 | Stop invalidated | 1 | 2.584 |
| Joint mismatch | 2025-11-03 21:30 | SHORT | 17.18 | 1.74 | 0.102 | 2.90 | 0.29 | 0.06 | 1.59 | 0.47 | -7.67 | Filled | 2 | 3.172 |
| Stop-excess pair | 2026-03-30 12:30 | LONG | 35.19 | 17.73 | 0.504 | 2.58 | 1.30 | 2.34 | 3.04 | 3.38 | -8.68 | Filled | 2 | 2.178 |
| Target-shortfall pair | 2024-05-30 07:15 | LONG | 2.70 | 1.16 | 0.432 | 0.83 | 0.36 | 0.55 | 1.57 | 0.33 | 1.98 | Stop invalidated | 1 | 2.870 |

## Causal Explanation

The R:R gate itself is behaving deterministically. The dominant failure occurs before order execution:

1. A sweep and MSS establish a distant structural stop anchor.
2. The selected post-MSS FVG midpoint frequently appears far along the move from that anchor toward the already-known opposing swing target.
3. Entry at that midpoint leaves a long distance back to the structural stop and a short remaining distance to TP2.
4. In `90.93%` of rejects, the entry is already beyond the first-third region required for `2R` before buffer effects.
5. Fill timing, expiration, and invalidation occur later and cannot cause the gate failure.

The evidence does not support blaming the `0.10` buffer, FVG size, MSS size, direction, year, or order timing. It also cannot establish that the target hierarchy is wrong because no alternative hierarchy exists in the measured implementation.

## Conclusion

The dominant cause is **joint stop/target geometry relative to the FVG midpoint**, with stop excess the stronger binary separator and target compression the larger source of continuous R:R variance. The current stop anchor and target may each be structurally reasonable in isolation; the measured incompatibility is that the activation entry usually lies too far toward the target for their combination to offer `2R`.

This supports the interpretation that the current strategy is highly selective under its existing geometry. It does not, by itself, justify changing the stop, target, entry, or minimum R:R.

Confidence is **high** that the geometric location is the direct cause because the decomposition is algebraic and covers all 4,551 rejects. Confidence is **moderate** when assigning structural responsibility between stop placement and target selection because 66.62% of nearest-filled comparisons require both components and no alternative target or stop rule was tested.
