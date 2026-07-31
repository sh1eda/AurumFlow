# FVG Entry Geometry Research

## Scope And Production Safety

This report measures deterministic FVG entry placement without changing the
production strategy. The official AurumFlow entry remains `FVG_MIDPOINT`.
No production module, strategy rule, stop rule, target rule, minimum R:R,
invalidation rule, or execution default was changed for this experiment.

The alternatives live in `research/fvg_entry_geometry.py`. The `research/`
package is excluded from production package discovery by `pyproject.toml`.
An equivalence test confirms that the research `MIDPOINT` replay exactly matches
the production backtest for both LONG and SHORT lifecycle fixtures.

This is research and educational software. Backtests are not evidence of future
profitability.

## Research Question

Only the entry price inside an already-detected FVG changes. Every model uses the
same:

- confirmed liquidity sweep;
- body-close MSS;
- post-MSS FVG;
- structural stop and `0.10` stop buffer;
- causal opposing-liquidity target function;
- `2.0` minimum R:R;
- eight-bar pending-order lifetime;
- pre-entry invalidation ordering;
- 48-bar maximum holding period;
- stop-first same-bar exit assumption;
- no-overlap replay behavior.

Target *logic* is fixed, but the selected causal target may change when an entry
crosses a previously detected swing. That is a direct consequence of applying
the unchanged target function to a different entry, not a target-rule change.

## Entry Definitions

Depth is measured from the distal edge toward the proximal edge.

| Model | Distal fraction | Bullish FVG | Bearish FVG |
| --- | ---: | --- | --- |
| `DISTAL_EDGE` | 0% | FVG low | FVG high |
| `25_PERCENT` | 25% | low + 25% of width | high - 25% of width |
| `MIDPOINT` | 50% | consequent encroachment | consequent encroachment |
| `75_PERCENT` | 75% | low + 75% of width | high - 75% of width |
| `PROXIMAL_EDGE` | 100% | FVG high | FVG low |

## Dataset And Assumptions

- Input: `data/local/XAUUSDM15.utc.csv`, normalized from the local MT5 export.
- Bars: `69,768` M15 candles.
- UTC bar-open range: `2023-07-25 22:00` through `2026-07-14 16:45`.
- Timestamp interpretation: UTC, with `closed_at = timestamp + 15 minutes`.
- Data quality details: [DATA_QUALITY_REPORT.md](DATA_QUALITY_REPORT.md).
- Prior geometric diagnosis: [RR_BOTTLENECK_ANALYSIS.md](RR_BOTTLENECK_ANALYSIS.md).

BULLISH and BEARISH fixed-bias runs are independent detector diagnostics. There
is no implemented causal HTF-bias selector, so summing the directions does not
create a deployable combined strategy.

Performance is shown before costs and under the existing research-cost
sensitivity:

| Scenario | Spread | Slippage | Commission |
| --- | ---: | ---: | ---: |
| Zero cost | `0.00` | `0.00` per side | `0.00R` |
| Research cost | `0.20` | `0.10` per side | `0.01R` |

The research costs are not broker-calibrated. They are a sensitivity assumption.

## Measurement Views

Two complementary views prevent selection effects from being mistaken for
geometry:

1. **Common candidate cohort:** all activation bars that have a valid stop and
   target under every model. This isolates entry geometry on the same events.
2. **Production-equivalent execution replay:** each model runs independently
   with the current no-overlap order lifecycle. This measures actual orders,
   fills, expirations, invalidations, closed trades, expectancy, profit factor,
   and drawdown.

The all-bar candidate scan can contain more candidates than the execution replay
because production skips bars while an order or trade is active. For example,
the all-bar midpoint view has `4,927` candidates and `267` R:R passes, while the
production-equivalent replay creates `249` midpoint orders.

## Main Finding

Entry depth creates a clear structural-execution tradeoff:

- Moving **distal** improves achievable R:R and creates more R:R-qualified
  orders, but reduces fills and causes more expirations.
- Moving **proximal** increases fill probability and reduces expiration, but
  widens stop distance relative to entry, removes R:R-qualified opportunities,
  and shifts a larger share of orders into pre-entry invalidation.
- `75_PERCENT` has the highest descriptive after-cost expectancy, but only by
  `0.012R` over `MIDPOINT`; the direction and yearly tables do not support
  treating that difference as robust.

## Same-Event Geometry

This is the cleanest structural comparison. Every row within a direction uses
the same activation cohort.

| Model | Direction | Common N | R:R passes | Average R:R | Median R:R | Avg stop | Avg target |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `DISTAL_EDGE` | LONG | 2,193 | 129 | 0.570 | 0.221 | 15.986 | 4.388 |
| `25_PERCENT` | LONG | 2,193 | 106 | 0.512 | 0.217 | 16.293 | 4.414 |
| `MIDPOINT` | LONG | 2,193 | 82 | 0.464 | 0.205 | 16.607 | 4.448 |
| `75_PERCENT` | LONG | 2,193 | 70 | 0.426 | 0.185 | 16.924 | 4.196 |
| `PROXIMAL_EDGE` | LONG | 2,193 | 67 | 0.404 | 0.169 | 17.242 | 3.937 |
| `DISTAL_EDGE` | SHORT | 2,140 | 144 | 0.657 | 0.226 | 18.166 | 5.290 |
| `25_PERCENT` | SHORT | 2,140 | 122 | 0.605 | 0.219 | 18.608 | 5.298 |
| `MIDPOINT` | SHORT | 2,140 | 101 | 0.532 | 0.214 | 19.077 | 5.231 |
| `75_PERCENT` | SHORT | 2,140 | 85 | 0.508 | 0.205 | 19.553 | 4.979 |
| `PROXIMAL_EDGE` | SHORT | 2,140 | 82 | 0.514 | 0.190 | 20.032 | 4.706 |

Across the `4,333` common directional candidates, average R:R falls from
`0.613` at `DISTAL_EDGE` to `0.458` at `PROXIMAL_EDGE`. Average stop distance
rises from `17.063` to `18.620`, while average target distance falls from
`4.833` to `4.317`. R:R passes fall from `273` to `149`.

### Structural Chart

```text
Same-event average achievable R:R (higher is healthier)
DISTAL_EDGE    0.613 | ########################
25_PERCENT     0.558 | ######################
MIDPOINT       0.498 | ####################
75_PERCENT     0.467 | ###################
PROXIMAL_EDGE  0.458 | ##################

Same-event R:R passes out of 4,333 directional candidates
DISTAL_EDGE      273 | ########################
25_PERCENT       228 | ####################
MIDPOINT         183 | ################
75_PERCENT       155 | ##############
PROXIMAL_EDGE    149 | #############
```

`PROXIMAL_EDGE` is the geometry that most damages R:R. `DISTAL_EDGE` is the
structurally healthiest R:R geometry, but that result alone says nothing about
whether orders can be filled efficiently.

## Execution And Performance

The following table uses model-specific all-bar candidate metrics and the
production-equivalent no-overlap replay. Expectancy, profit factor, and drawdown
use the research-cost scenario.

| Model | Dir | Candidates | R:R pass | Avg / med R:R | Avg stop / target | Orders | Fill / expire / invalidate | Closed | Exp R | PF | DD R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `DISTAL_EDGE` | LONG | 2,951 | 169 | 0.521 / 0.167 | 15.825 / 3.640 | 162 | 18.5 / 38.3 / 43.2% | 30 | 0.868 | 2.409 | 10.244 |
| `25_PERCENT` | LONG | 2,716 | 152 | 0.536 / 0.171 | 15.979 / 3.824 | 144 | 19.4 / 35.4 / 45.1% | 28 | 0.718 | 2.134 | 5.617 |
| `MIDPOINT` | LONG | 2,542 | 125 | 0.523 / 0.176 | 16.171 / 4.019 | 116 | 21.6 / 26.7 / 51.7% | 25 | 0.608 | 1.927 | 4.224 |
| `75_PERCENT` | LONG | 2,387 | 105 | 0.494 / 0.175 | 16.509 / 3.984 | 100 | 22.0 / 21.0 / 57.0% | 22 | 0.591 | 1.934 | 4.117 |
| `PROXIMAL_EDGE` | LONG | 2,270 | 97 | 0.490 / 0.179 | 16.724 / 3.920 | 90 | 23.3 / 21.1 / 55.6% | 21 | 0.379 | 1.525 | 4.158 |
| `DISTAL_EDGE` | SHORT | 2,647 | 181 | 0.660 / 0.198 | 17.774 / 4.630 | 170 | 18.8 / 37.6 / 43.5% | 32 | -0.033 | 0.962 | 11.412 |
| `25_PERCENT` | SHORT | 2,515 | 159 | 0.640 / 0.194 | 17.984 / 4.774 | 148 | 22.3 / 36.5 / 41.2% | 33 | 0.130 | 1.162 | 13.235 |
| `MIDPOINT` | SHORT | 2,385 | 142 | 0.592 / 0.200 | 18.446 / 4.877 | 133 | 21.1 / 33.8 / 45.1% | 28 | 0.493 | 1.681 | 8.660 |
| `75_PERCENT` | SHORT | 2,299 | 115 | 0.560 / 0.202 | 18.727 / 4.759 | 106 | 26.4 / 25.5 / 48.1% | 28 | 0.535 | 1.808 | 4.610 |
| `PROXIMAL_EDGE` | SHORT | 2,218 | 104 | 0.579 / 0.204 | 19.402 / 4.653 | 98 | 25.5 / 20.4 / 54.1% | 25 | 0.377 | 1.517 | 4.453 |

### Directional Aggregate

The aggregate below pools the two independent fixed-bias views for descriptive
comparison only. It is not a combined strategy. `Worst DD` is the larger of the
LONG and SHORT drawdowns, avoiding a fictitious overlapping equity curve.

| Model | Orders | Fill | Expire | Invalidate | Closed | After-cost expectancy | PF | Worst DD R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `DISTAL_EDGE` | 332 | 18.7% | 38.0% | 43.4% | 62 | 0.403 | 1.536 | 11.412 |
| `25_PERCENT` | 292 | 20.9% | 36.0% | 43.2% | 61 | 0.400 | 1.551 | 13.235 |
| `MIDPOINT` | 249 | 21.3% | 30.5% | 48.2% | 53 | 0.547 | 1.791 | 8.660 |
| `75_PERCENT` | 206 | 24.3% | 23.3% | 52.4% | 50 | 0.560 | 1.862 | 4.610 |
| `PROXIMAL_EDGE` | 188 | 24.5% | 20.7% | 54.8% | 46 | 0.378 | 1.521 | 4.453 |

```text
Fill rate (higher means more activated orders fill)
DISTAL_EDGE    18.7% | ###################
25_PERCENT     20.9% | #####################
MIDPOINT       21.3% | #####################
75_PERCENT     24.3% | ########################
PROXIMAL_EDGE  24.5% | #########################

Expiration rate (lower is better for retracement reach)
DISTAL_EDGE    38.0% | ######################################
25_PERCENT     36.0% | ####################################
MIDPOINT       30.5% | ###############################
75_PERCENT     23.3% | #######################
PROXIMAL_EDGE  20.7% | #####################

After-cost expectancy (descriptive fixed-bias pool)
DISTAL_EDGE    0.403R | ################
25_PERCENT     0.400R | ################
MIDPOINT       0.547R | ######################
75_PERCENT     0.560R | ######################
PROXIMAL_EDGE  0.378R | ###############
```

`PROXIMAL_EDGE` has the highest fill rate, but it exceeds `75_PERCENT` by only
`0.2` percentage points and has materially lower expectancy and profit factor.
Moving proximal does not simply convert expirations into fills: invalidation
rises from `43.4%` at DISTAL to `54.8%` at PROXIMAL.

## Zero-Cost Sensitivity

| Model | Direction | Closed | Expectancy R | Profit factor | Max DD R |
| --- | --- | ---: | ---: | ---: | ---: |
| `DISTAL_EDGE` | LONG | 30 | 1.146 | 3.456 | 5.769 |
| `25_PERCENT` | LONG | 28 | 0.989 | 2.979 | 4.000 |
| `MIDPOINT` | LONG | 25 | 0.857 | 2.647 | 3.000 |
| `75_PERCENT` | LONG | 22 | 0.865 | 2.730 | 3.000 |
| `PROXIMAL_EDGE` | LONG | 21 | 0.692 | 2.211 | 3.000 |
| `DISTAL_EDGE` | SHORT | 32 | 0.173 | 1.240 | 7.000 |
| `25_PERCENT` | SHORT | 33 | 0.323 | 1.484 | 10.036 |
| `MIDPOINT` | SHORT | 28 | 0.750 | 2.313 | 5.107 |
| `75_PERCENT` | SHORT | 28 | 0.750 | 2.399 | 3.000 |
| `PROXIMAL_EDGE` | SHORT | 25 | 0.622 | 2.037 | 3.358 |

Costs materially weaken the distal SHORT result from `0.173R` to `-0.033R`.
That sensitivity is another reason not to promote the structurally highest-R:R
geometry based on trade count alone.

## Yearly Breakdown

`2023` is partial from July 25 and `2026` is year-to-date through July 14.
`Candidates/pass` is the all-bar geometry view. Orders and execution metrics are
from the production-equivalent replay. Performance uses research costs.

| Model | Dir | Year | Candidates/pass | Avg / med R:R | Avg stop / target | Orders | Fill / expire / invalidate | Closed | Exp R | PF | DD R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `DISTAL_EDGE` | LONG | 2023 | 376/16 | 0.514 / 0.180 | 6.226 / 1.475 | 16 | 12.5 / 56.2 / 31.2% | 2 | -1.278 | 0.000 | 2.556 |
| `DISTAL_EDGE` | LONG | 2024 | 1,021/59 | 0.530 / 0.187 | 8.727 / 2.193 | 56 | 28.6 / 33.9 / 37.5% | 16 | 0.147 | 1.174 | 7.688 |
| `DISTAL_EDGE` | LONG | 2025 | 1,066/60 | 0.503 / 0.137 | 16.502 / 3.420 | 57 | 12.3 / 36.8 / 50.9% | 7 | 1.448 | 5.262 | 1.215 |
| `DISTAL_EDGE` | LONG | 2026 YTD | 488/34 | 0.546 / 0.186 | 36.590 / 8.820 | 33 | 15.2 / 39.4 / 45.5% | 5 | 3.222 | n/a | 0.000 |
| `25_PERCENT` | LONG | 2023 | 350/20 | 0.518 / 0.189 | 6.319 / 1.601 | 19 | 15.8 / 52.6 / 31.6% | 3 | 0.936 | 3.318 | 1.211 |
| `25_PERCENT` | LONG | 2024 | 943/51 | 0.536 / 0.193 | 9.011 / 2.319 | 48 | 31.2 / 33.3 / 35.4% | 15 | 0.723 | 2.019 | 4.406 |
| `25_PERCENT` | LONG | 2025 | 975/51 | 0.491 / 0.137 | 16.764 / 3.599 | 48 | 12.5 / 35.4 / 52.1% | 6 | 0.540 | 1.871 | 2.575 |
| `25_PERCENT` | LONG | 2026 YTD | 448/30 | 0.649 / 0.174 | 36.485 / 9.219 | 29 | 13.8 / 27.6 / 58.6% | 4 | 0.801 | 2.487 | 2.154 |
| `MIDPOINT` | LONG | 2023 | 332/11 | 0.460 / 0.178 | 6.510 / 1.546 | 10 | 20.0 / 30.0 / 50.0% | 2 | 0.566 | 1.948 | 1.193 |
| `MIDPOINT` | LONG | 2024 | 895/47 | 0.534 / 0.192 | 9.184 / 2.340 | 43 | 30.2 / 30.2 / 39.5% | 13 | 0.253 | 1.309 | 3.918 |
| `MIDPOINT` | LONG | 2025 | 897/46 | 0.480 / 0.155 | 16.979 / 3.697 | 43 | 16.3 / 30.2 / 53.5% | 7 | 1.117 | 3.234 | 2.372 |
| `MIDPOINT` | LONG | 2026 YTD | 418/21 | 0.643 / 0.197 | 37.068 / 10.268 | 20 | 15.0 / 10.0 / 75.0% | 3 | 0.990 | 3.751 | 1.080 |
| `75_PERCENT` | LONG | 2023 | 315/10 | 0.441 / 0.188 | 6.285 / 1.519 | 10 | 20.0 / 20.0 / 60.0% | 2 | 0.498 | 1.846 | 1.178 |
| `75_PERCENT` | LONG | 2024 | 846/41 | 0.511 / 0.187 | 9.437 / 2.343 | 40 | 27.5 / 27.5 / 45.0% | 11 | 0.483 | 1.672 | 2.939 |
| `75_PERCENT` | LONG | 2025 | 835/37 | 0.449 / 0.158 | 17.205 / 3.741 | 33 | 21.2 / 21.2 / 57.6% | 7 | 1.299 | 4.706 | 1.393 |
| `75_PERCENT` | LONG | 2026 YTD | 391/17 | 0.599 / 0.188 | 38.560 / 10.042 | 17 | 11.8 / 5.9 / 82.4% | 2 | -1.195 | 0.000 | 2.390 |
| `PROXIMAL_EDGE` | LONG | 2023 | 299/12 | 0.545 / 0.191 | 6.536 / 1.591 | 10 | 10.0 / 50.0 / 40.0% | 1 | -1.165 | 0.000 | 1.165 |
| `PROXIMAL_EDGE` | LONG | 2024 | 814/39 | 0.507 / 0.186 | 9.527 / 2.346 | 38 | 34.2 / 18.4 / 47.4% | 13 | 0.844 | 2.401 | 2.647 |
| `PROXIMAL_EDGE` | LONG | 2025 | 786/30 | 0.437 / 0.161 | 17.593 / 3.673 | 26 | 19.2 / 19.2 / 61.5% | 5 | 0.081 | 1.104 | 3.905 |
| `PROXIMAL_EDGE` | LONG | 2026 YTD | 371/16 | 0.522 / 0.176 | 38.884 / 9.774 | 16 | 12.5 / 12.5 / 75.0% | 2 | -1.127 | 0.000 | 2.254 |
| `DISTAL_EDGE` | SHORT | 2023 | 392/13 | 0.392 / 0.146 | 6.349 / 1.377 | 11 | 18.2 / 45.5 / 36.4% | 2 | -1.341 | 0.000 | 2.682 |
| `DISTAL_EDGE` | SHORT | 2024 | 825/54 | 0.637 / 0.219 | 10.143 / 2.435 | 52 | 15.4 / 28.8 / 55.8% | 8 | -0.523 | 0.461 | 5.311 |
| `DISTAL_EDGE` | SHORT | 2025 | 899/67 | 0.708 / 0.208 | 17.805 / 4.545 | 62 | 16.1 / 38.7 / 45.2% | 10 | -0.030 | 0.965 | 5.193 |
| `DISTAL_EDGE` | SHORT | 2026 YTD | 531/47 | 0.815 / 0.197 | 38.010 / 10.587 | 45 | 26.7 / 44.4 / 28.9% | 12 | 0.509 | 1.669 | 4.247 |
| `25_PERCENT` | SHORT | 2023 | 379/16 | 0.419 / 0.158 | 6.498 / 1.398 | 13 | 23.1 / 61.5 / 15.4% | 3 | -1.268 | 0.000 | 3.803 |
| `25_PERCENT` | SHORT | 2024 | 794/51 | 0.603 / 0.196 | 10.388 / 2.438 | 49 | 18.4 / 30.6 / 51.0% | 9 | -1.041 | 0.069 | 9.366 |
| `25_PERCENT` | SHORT | 2025 | 849/56 | 0.663 / 0.203 | 18.221 / 4.761 | 51 | 21.6 / 29.4 / 49.0% | 11 | 0.743 | 2.142 | 4.665 |
| `25_PERCENT` | SHORT | 2026 YTD | 493/36 | 0.831 / 0.229 | 38.638 / 11.153 | 35 | 28.6 / 45.7 / 25.7% | 10 | 0.930 | 2.678 | 3.143 |
| `MIDPOINT` | SHORT | 2023 | 365/15 | 0.427 / 0.161 | 6.575 / 1.463 | 12 | 8.3 / 66.7 / 25.0% | 1 | -1.169 | 0.000 | 1.169 |
| `MIDPOINT` | SHORT | 2024 | 736/39 | 0.536 / 0.194 | 10.613 / 2.461 | 39 | 25.6 / 25.6 / 48.7% | 10 | -0.338 | 0.653 | 7.491 |
| `MIDPOINT` | SHORT | 2025 | 813/61 | 0.649 / 0.221 | 18.537 / 4.925 | 56 | 21.4 / 23.2 / 55.4% | 12 | 1.151 | 3.321 | 3.545 |
| `MIDPOINT` | SHORT | 2026 YTD | 471/27 | 0.709 / 0.218 | 39.729 / 11.217 | 26 | 19.2 / 53.8 / 26.9% | 5 | 0.907 | 2.333 | 2.096 |
| `75_PERCENT` | SHORT | 2023 | 355/11 | 0.410 / 0.164 | 6.690 / 1.460 | 10 | 10.0 / 50.0 / 40.0% | 1 | -1.163 | 0.000 | 1.163 |
| `75_PERCENT` | SHORT | 2024 | 705/34 | 0.523 / 0.210 | 10.539 / 2.479 | 32 | 28.1 / 25.0 / 46.9% | 9 | 0.182 | 1.235 | 4.610 |
| `75_PERCENT` | SHORT | 2025 | 782/46 | 0.604 / 0.204 | 18.913 / 4.782 | 41 | 31.7 / 14.6 / 53.7% | 13 | 0.550 | 1.886 | 3.272 |
| `75_PERCENT` | SHORT | 2026 YTD | 457/24 | 0.658 / 0.224 | 40.392 / 10.801 | 23 | 21.7 / 34.8 / 43.5% | 5 | 1.469 | 4.147 | 1.279 |
| `PROXIMAL_EDGE` | SHORT | 2023 | 338/7 | 0.364 / 0.173 | 6.711 / 1.470 | 6 | 16.7 / 33.3 / 50.0% | 1 | -1.157 | 0.000 | 1.157 |
| `PROXIMAL_EDGE` | SHORT | 2024 | 677/37 | 0.554 / 0.230 | 10.788 / 2.499 | 36 | 27.8 / 16.7 / 55.6% | 10 | 0.626 | 1.925 | 4.453 |
| `PROXIMAL_EDGE` | SHORT | 2025 | 756/37 | 0.614 / 0.207 | 19.582 / 4.699 | 34 | 23.5 / 14.7 / 61.8% | 8 | -0.214 | 0.751 | 3.435 |
| `PROXIMAL_EDGE` | SHORT | 2026 YTD | 447/23 | 0.721 / 0.209 | 41.740 / 10.243 | 22 | 27.3 / 31.8 / 40.9% | 6 | 1.007 | 2.760 | 2.175 |

Annual closed-trade counts range from one to sixteen. Sign changes across years
and directions are material. They prevent a defensible claim that the small
full-history expectancy advantage of `75_PERCENT` is stable.

## Interpretation By Objective

### Structurally Healthier Trades

`DISTAL_EDGE` produces the strongest same-event R:R geometry. Compared with
`MIDPOINT`, it reduces common-cohort average stop distance by `0.764`, raises
average R:R by `0.115`, and produces `90` more R:R passes. This is a geometric
result, not proof that DISTAL entries are preferable in execution.

### Geometry That Increases Fills

Fill rate rises toward the proximal edge. `PROXIMAL_EDGE` is highest at `24.5%`,
closely followed by `75_PERCENT` at `24.3%`. The midpoint rate is `21.3%`.

### Geometry That Destroys R:R

`PROXIMAL_EDGE` is worst on same-event R:R: `0.458` average and `149` passes,
versus `0.613` and `273` at DISTAL. The effect comes from both a wider stop
distance from entry and a shorter target distance.

### Geometry With Excessive Expiration

`DISTAL_EDGE` has the highest expiration rate at `38.0%`; `25_PERCENT` is next at
`36.0%`. Their deeper retracement requirement is not reached within eight bars
often enough to offset their larger R:R-qualified order count cleanly.

### Performance Ranking

After assumed costs, `75_PERCENT` has the highest pooled descriptive expectancy
at `0.560R`, followed by `MIDPOINT` at `0.547R`. The difference is only `0.012R`
over 50 versus 53 closed trades. LONG favors DISTAL (`0.868R`), while SHORT
favors `75_PERCENT` (`0.535R`). This disagreement and the annual instability
make the performance ranking low confidence.

## Recommendation

**Keep `MIDPOINT` as the production default.** It remains a reasonable balance:

- materially better R:R geometry than the two more proximal models;
- fewer expirations and lower drawdown than the two more distal models;
- more closed trades than `75_PERCENT` and `PROXIMAL_EDGE`;
- after-cost performance within `0.012R` of the descriptive leader;
- already specified, implemented, and equivalence-tested as the official rule.

`75_PERCENT` is the strongest **future validation candidate**, not a production
replacement. It improves fills and descriptive drawdown while preserving more
R:R than `PROXIMAL_EDGE`, but it creates fewer R:R-qualified orders, increases
invalidation share, and lacks stable direction/year evidence.

No entry model should be promoted without a causal HTF-bias process,
broker-calibrated costs, chronological out-of-sample validation, and a larger
closed-trade sample. This report does not authorize a strategy change.

## Final Research Answers

| Question | Result |
| --- | --- |
| Best R:R geometry | `DISTAL_EDGE` (`0.613` same-event average R:R) |
| Best expectancy geometry | `75_PERCENT` (`0.560R` pooled descriptive after-cost expectancy) |
| Highest fill geometry | `PROXIMAL_EDGE` (`24.5%`) |
| Lowest drawdown geometry | `PROXIMAL_EDGE` on worst fixed-bias after-cost DD (`4.453R`); LONG alone favors `75_PERCENT` (`4.117R`) |
| Recommended production candidate | `MIDPOINT` retained; `75_PERCENT` is research-only for future validation |
| Confidence | High for geometry and lifecycle effects; low-to-moderate for performance ranking |
| Should midpoint remain default? | Yes |

## Reproduction

```bash
python -m research.fvg_entry_geometry \
  --csv data/local/XAUUSDM15.utc.csv \
  --htf-bias BOTH \
  > /tmp/aurumflow_fvg_entry_research.json
```

The command emits full-history and yearly zero/research-cost summaries plus the
same-event common candidate cohorts. The generated JSON is intentionally not a
tracked repository artifact.
