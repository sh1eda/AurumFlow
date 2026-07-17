# Real-Data Funnel Report

## Scope

This report measures the current `RULE_ONLY` implementation on the validated local XAUUSD M15 dataset. The strategy rules were not changed or tuned. BULLISH and BEARISH manual HTF bias were run separately over the full history.

These are directional detector diagnostics, not a deployable strategy simulation. Holding one bias constant for years is not a causal HTF selection process.

## Dataset And Configuration

- Bars: `69,768`.
- UTC bar-open range: `2023-07-25 22:00` to `2026-07-14 16:45`.
- Mode: `RULE_ONLY`.
- Entry: `FVG_MIDPOINT` pending limit.
- Minimum R:R: `2.0`.
- Confidence threshold: `0.70`.
- Stop buffer: `0.10` price units.
- Minimum stop distance: `0.50` price units.
- Maximum entry wait: `8` bars.
- Maximum holding period: `48` bars.
- Pre-entry structural, stop-level, and FVG close-through invalidation: enabled.
- Overlapping pending orders/positions: disabled.

Yearly and half-period rows were grouped from each full-history replay by the setup's UTC evaluation/activation timestamp. This retains causal history across period boundaries. Because the simulator skips bars while an order or trade is active, BULLISH and BEARISH runs have different evaluated-bar counts.

## Commands

Zero-cost diagnostic:

```bash
python -m xauusd_signal diagnose \
  --csv data/local/XAUUSDM15.utc.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --min-rr 2.0 \
  --spread-buffer 0.10 \
  --min-stop-distance 0.50 \
  --max-entry-wait-bars 8 \
  --max-holding-bars 48 \
  --spread-cost 0.0 \
  --slippage 0.0 \
  --commission-r 0.0 \
  --format json
```

Repeat with `--htf-bias BEARISH`. The requested research-cost diagnostic used the same command with `--spread-cost 0.20 --slippage 0.10 --commission-r 0.01`. Funnel and order-outcome counts were identical in both cost runs because costs affect R results, not eligibility or exit timing.

For an independent calendar slice, use inclusive UTC `--start` and exclusive UTC `--end`, for example `--start 2025-01-01 --end 2026-01-01`. Such a run starts with no pre-period event history and therefore is not the source of the full-context yearly tables below.

## Full Funnel

Funnel sweep/MSS/FVG counts are evaluated-bar state counts: a bar survives a stage when the current causal prefix contains the required state. They are not counts of distinct market events.

| View | Bars | Sweeps | MSS | Post-MSS FVG | Target | Stop | R:R pass | Orders | Filled | Expired | Invalidated | Closed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH / LONG | 69,229 | 69,211 | 32,997 | 4,656 | 2,537 | 2,485 | 116 | 116 | 25 | 31 | 60 | 25 |
| BEARISH / SHORT | 69,024 | 69,024 | 31,013 | 3,865 | 2,359 | 2,315 | 133 | 133 | 28 | 45 | 60 | 28 |
| Directional aggregate | 138,253 | 138,235 | 64,010 | 8,521 | 4,896 | 4,800 | 249 | 249 | 53 | 76 | 120 | 53 |

The aggregate is the sum of two independent fixed-bias runs. It is not a single backtest and may contain overlapping opportunities.

Distinct detector events over the raw history provide additional context:

| Fixed-bias view | Confirmed directional sweeps | Directional MSS events | Raw directional FVGs |
| --- | ---: | ---: | ---: |
| BULLISH / LONG | 5,301 | 5,220 | 7,723 |
| BEARISH / SHORT | 5,400 | 5,092 | 6,645 |

## Yearly Funnel

`2023` is partial from July 25 UTC. `2026` is year-to-date through July 14.

| Bias | Period | Bars | Sweeps | MSS | FVG | Target | Stop | R:R | Orders | Fill | Expire | Invalidate | Closed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH | 2023 | 10,176 | 10,158 | 4,555 | 598 | 331 | 323 | 10 | 10 | 2 | 3 | 5 | 2 |
| BULLISH | 2024 | 23,535 | 23,535 | 11,630 | 1,572 | 903 | 873 | 43 | 43 | 13 | 13 | 17 | 13 |
| BULLISH | 2025 | 23,371 | 23,371 | 11,284 | 1,727 | 888 | 876 | 43 | 43 | 7 | 13 | 23 | 7 |
| BULLISH | 2026 YTD | 12,147 | 12,147 | 5,528 | 759 | 415 | 413 | 20 | 20 | 3 | 2 | 15 | 3 |
| BEARISH | 2023 | 10,185 | 10,185 | 4,526 | 570 | 355 | 350 | 12 | 12 | 1 | 8 | 3 | 1 |
| BEARISH | 2024 | 23,490 | 23,490 | 9,947 | 1,255 | 746 | 720 | 39 | 39 | 10 | 10 | 19 | 10 |
| BEARISH | 2025 | 23,274 | 23,274 | 10,678 | 1,298 | 799 | 789 | 56 | 56 | 12 | 13 | 31 | 12 |
| BEARISH | 2026 YTD | 12,075 | 12,075 | 5,862 | 742 | 459 | 456 | 26 | 26 | 5 | 14 | 7 | 5 |

## Half-Period Check

The row-count midpoint splits the dataset at `2025-01-15 14:45 UTC`.

| Bias | Half | Bars | Sweeps | MSS | FVG | Target | Stop | R:R | Fill | Expire | Invalidate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH | First | 34,582 | 34,564 | 16,663 | 2,226 | 1,262 | 1,223 | 54 | 16 | 16 | 22 |
| BULLISH | Second | 34,647 | 34,647 | 16,334 | 2,430 | 1,275 | 1,262 | 62 | 9 | 15 | 38 |
| BEARISH | First | 34,548 | 34,548 | 14,862 | 1,860 | 1,121 | 1,090 | 52 | 11 | 18 | 23 |
| BEARISH | Second | 34,476 | 34,476 | 16,151 | 2,005 | 1,238 | 1,225 | 81 | 17 | 27 | 37 |

Both halves reach every lifecycle stage. The strategy is not logically dead or dependent on only one end of the dataset.

## Bottleneck

The primary bottleneck is the fixed minimum R:R gate after a causal target and structural stop are available:

- LONG: `116 / 2,485` pass (`4.67%`); `2,369` fail.
- SHORT: `133 / 2,315` pass (`5.75%`); `2,182` fail.
- Aggregate: `249 / 4,800` pass (`5.19%`); `4,551` fail.

The secondary bottleneck is requiring a newly known directional FVG after the selected MSS:

- LONG: `4,656 / 32,997` survive (`14.11%`).
- SHORT: `3,865 / 31,013` survive (`12.46%`).

Execution is also selective after activation. LONG orders fill at `21.55%`, expire at `26.72%`, and invalidate at `51.72%`. SHORT orders fill at `21.05%`, expire at `33.83%`, and invalidate at `45.11%`. These execution outcomes are downstream of the much larger R:R reduction.

## Ranked Codes

| View | Leading rejection/outcome codes |
| --- | --- |
| LONG | `no_mss_body_close: 36,214`; `no_valid_fvg: 28,341`; `risk_reward_below_minimum: 2,369`; `target_unavailable: 2,119`; `setup_invalidated: 60` |
| SHORT | `no_mss_body_close: 38,011`; `no_valid_fvg: 27,148`; `risk_reward_below_minimum: 2,182`; `target_unavailable: 1,506`; `setup_invalidated: 60` |

## Synthetic Comparison

The deterministic 13-bar lifecycle fixture produces three sweep-state observations, three MSS-state observations, one post-MSS FVG, one order, one fill, and one closed trade on its active side. It proves stage and lifecycle semantics only. Unlike that constructed fixture, the real data identifies the R:R gate as the largest proportional reduction and shows fills, expirations, and invalidations in every multi-month period.

## Conclusion

The current implementation is neither logically broken nor merely unexercised: it creates 249 fixed-bias pending setups and 53 closed trades across the two independent detector views. It is deliberately rare. The real bottleneck is target-to-stop geometry at the unchanged `2.0` minimum R:R gate, followed by post-MSS FVG timing. The next research action should inspect the 4,551 R:R rejections and their causal target/stop distributions before any rule change is proposed.
