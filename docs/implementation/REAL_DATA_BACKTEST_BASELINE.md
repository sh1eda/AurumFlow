# Real-Data Backtest Baseline

## Scope And Warning

This baseline measures the unchanged `RULE_ONLY` engine on the validated local XAUUSD M15 data. BULLISH and BEARISH manual HTF bias are held constant in separate runs. Those runs isolate direction-specific behavior; they are not a causal strategy because no implemented rule selects the active HTF bias through time.

Backtests are not proof of future profitability. The trade samples are small, the broker and quote type are unknown, and the cost scenario is not calibrated to a documented venue.

## Fixed Configuration

- Entry: `FVG_MIDPOINT` pending limit.
- Minimum R:R: `2.0`.
- Confidence threshold: `0.70`.
- Stop buffer: `0.10` price units.
- Minimum stop distance: `0.50` price units.
- Maximum entry wait: `8` bars.
- Maximum holding period: `48` bars.
- Stop/target ambiguity: stop first.
- Entry/invalidation ambiguity: invalidation first.
- Overlapping positions: disabled.

Cost scenarios:

| Scenario | Spread | Slippage | Commission |
| --- | ---: | ---: | ---: |
| Zero cost | `0.00` price units | `0.00` price units per side | `0.00R` |
| Research cost | `0.20` price units | `0.10` price units per side | `0.01R` |

The research-cost scenario is the requested realistic-cost sensitivity run, but it is not broker-verified. The MT5 spread export is zero on every row, so no empirical spread can be recovered from this file.

## Commands

Zero-cost BULLISH run:

```bash
python -m xauusd_signal backtest \
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
  --commission-r 0.0
```

Research-cost BULLISH run:

```bash
python -m xauusd_signal backtest \
  --csv data/local/XAUUSDM15.utc.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --min-rr 2.0 \
  --spread-buffer 0.10 \
  --min-stop-distance 0.50 \
  --max-entry-wait-bars 8 \
  --max-holding-bars 48 \
  --spread-cost 0.20 \
  --slippage 0.10 \
  --commission-r 0.01
```

Repeat both with `--htf-bias BEARISH`. The yearly and monthly tables group the full replay by setup activation timestamp, retaining causal pre-period context.

## Full Baseline

Average R and expectancy are the same arithmetic mean of closed-trade R multiples.

| Bias | Cost | Setups | Closed | Expectancy / avg R | Profit factor | Max DD R | Fill | Expire | Invalidate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH | Zero | 116 | 25 | 0.8565 | 2.6471 | 3.0000 | 21.55% | 26.72% | 51.72% |
| BULLISH | Research | 116 | 25 | 0.6082 | 1.9269 | 4.2240 | 21.55% | 26.72% | 51.72% |
| BEARISH | Zero | 133 | 28 | 0.7501 | 2.3126 | 5.1066 | 21.05% | 33.83% | 45.11% |
| BEARISH | Research | 133 | 28 | 0.4929 | 1.6810 | 8.6601 | 21.05% | 33.83% | 45.11% |

The two fixed-bias views contain 53 closed trades in total, but summing them does not create a valid combined strategy because their opportunities can overlap and no causal bias selector chooses between them.

## Zero-Cost Yearly Results

`2023` begins July 25 and `2026` ends July 14.

| Bias | Period | Setups | Closed | Expectancy R | Profit factor | Max DD R | Fill | Expire | Invalidate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH | 2023 | 10 | 2 | 0.7461 | 2.4921 | 1.0000 | 20.00% | 30.00% | 50.00% |
| BULLISH | 2024 | 43 | 13 | 0.5585 | 1.9075 | 3.0000 | 30.23% | 30.23% | 39.53% |
| BULLISH | 2025 | 43 | 7 | 1.3351 | 4.1152 | 2.0000 | 16.28% | 30.23% | 53.49% |
| BULLISH | 2026 YTD | 20 | 3 | 1.1051 | 4.3152 | 1.0000 | 15.00% | 10.00% | 75.00% |
| BEARISH | 2023 | 12 | 1 | -1.0000 | 0.0000 | 1.0000 | 8.33% | 66.67% | 25.00% |
| BEARISH | 2024 | 39 | 10 | 0.0543 | 1.0775 | 4.1066 | 25.64% | 25.64% | 48.72% |
| BEARISH | 2025 | 56 | 12 | 1.3448 | 4.2276 | 3.0000 | 21.43% | 23.21% | 55.36% |
| BEARISH | 2026 YTD | 26 | 5 | 1.0641 | 2.7735 | 2.0000 | 19.23% | 53.85% | 26.92% |

## Research-Cost Yearly Results

| Bias | Period | Setups | Closed | Expectancy R | Profit factor | Max DD R | Fill | Expire | Invalidate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BULLISH | 2023 | 10 | 2 | 0.5658 | 1.9485 | 1.1931 | 20.00% | 30.00% | 50.00% |
| BULLISH | 2024 | 43 | 13 | 0.2525 | 1.3088 | 3.9185 | 30.23% | 30.23% | 39.53% |
| BULLISH | 2025 | 43 | 7 | 1.1170 | 3.2338 | 2.3715 | 16.28% | 30.23% | 53.49% |
| BULLISH | 2026 YTD | 20 | 3 | 0.9902 | 3.7510 | 1.0799 | 15.00% | 10.00% | 75.00% |
| BEARISH | 2023 | 12 | 1 | -1.1690 | 0.0000 | 1.1690 | 8.33% | 66.67% | 25.00% |
| BEARISH | 2024 | 39 | 10 | -0.3380 | 0.6532 | 7.4911 | 25.64% | 25.64% | 48.72% |
| BEARISH | 2025 | 56 | 12 | 1.1513 | 3.3213 | 3.5451 | 21.43% | 23.21% | 55.36% |
| BEARISH | 2026 YTD | 26 | 5 | 0.9068 | 2.3333 | 2.0956 | 19.23% | 53.85% | 26.92% |

The year-level samples range from one to thirteen trades. Their variation is descriptive only. In particular, the BEARISH 2024 result changes from `0.0543R` before costs to `-0.3380R` under the research-cost scenario, demonstrating cost sensitivity rather than a robust edge conclusion.

## Monthly Setup And Execution Counts

Each month is an activation cohort. `Setups / trades` reports pending orders and resulting closed trades. `F / E / I` reports fill, expiration, and invalidation percentages of that month's setups. Zero- and research-cost runs have identical values because costs do not alter setup or execution paths.

| Month | LONG setups / trades | LONG F / E / I | SHORT setups / trades | SHORT F / E / I |
| --- | ---: | ---: | ---: | ---: |
| 2023-07 | 0 / 0 | 0 / 0 / 0% | 2 / 1 | 50 / 0 / 50% |
| 2023-08 | 4 / 1 | 25 / 50 / 25% | 1 / 0 | 0 / 0 / 100% |
| 2023-09 | 1 / 0 | 0 / 0 / 100% | 1 / 0 | 0 / 100 / 0% |
| 2023-10 | 4 / 1 | 25 / 25 / 50% | 5 / 0 | 0 / 80 / 20% |
| 2023-11 | 0 / 0 | 0 / 0 / 0% | 0 / 0 | 0 / 0 / 0% |
| 2023-12 | 1 / 0 | 0 / 0 / 100% | 3 / 0 | 0 / 100 / 0% |
| 2024-01 | 4 / 2 | 50 / 25 / 25% | 3 / 2 | 66.7 / 0 / 33.3% |
| 2024-02 | 0 / 0 | 0 / 0 / 0% | 2 / 2 | 100 / 0 / 0% |
| 2024-03 | 5 / 1 | 20 / 40 / 40% | 2 / 0 | 0 / 0 / 100% |
| 2024-04 | 4 / 2 | 50 / 0 / 50% | 7 / 0 | 0 / 42.9 / 57.1% |
| 2024-05 | 4 / 1 | 25 / 50 / 25% | 2 / 1 | 50 / 0 / 50% |
| 2024-06 | 6 / 2 | 33.3 / 16.7 / 50% | 2 / 1 | 50 / 0 / 50% |
| 2024-07 | 5 / 0 | 0 / 60 / 40% | 6 / 3 | 50 / 16.7 / 33.3% |
| 2024-08 | 2 / 0 | 0 / 100 / 0% | 2 / 0 | 0 / 50 / 50% |
| 2024-09 | 4 / 0 | 0 / 25 / 75% | 3 / 1 | 33.3 / 66.7 / 0% |
| 2024-10 | 5 / 3 | 60 / 0 / 40% | 3 / 0 | 0 / 33.3 / 66.7% |
| 2024-11 | 1 / 0 | 0 / 0 / 100% | 4 / 0 | 0 / 25 / 75% |
| 2024-12 | 3 / 2 | 66.7 / 33.3 / 0% | 3 / 0 | 0 / 33.3 / 66.7% |
| 2025-01 | 2 / 1 | 50 / 50 / 0% | 4 / 1 | 25 / 25 / 50% |
| 2025-02 | 2 / 0 | 0 / 50 / 50% | 5 / 3 | 60 / 20 / 20% |
| 2025-03 | 3 / 1 | 33.3 / 33.3 / 33.3% | 8 / 2 | 25 / 37.5 / 37.5% |
| 2025-04 | 2 / 0 | 0 / 0 / 100% | 4 / 0 | 0 / 50 / 50% |
| 2025-05 | 6 / 1 | 16.7 / 16.7 / 66.7% | 2 / 0 | 0 / 0 / 100% |
| 2025-06 | 3 / 1 | 33.3 / 33.3 / 33.3% | 3 / 1 | 33.3 / 0 / 66.7% |
| 2025-07 | 2 / 1 | 50 / 0 / 50% | 4 / 0 | 0 / 50 / 50% |
| 2025-08 | 9 / 0 | 0 / 22.2 / 77.8% | 7 / 1 | 14.3 / 14.3 / 71.4% |
| 2025-09 | 5 / 1 | 20 / 20 / 60% | 6 / 2 | 33.3 / 0 / 66.7% |
| 2025-10 | 3 / 0 | 0 / 66.7 / 33.3% | 6 / 0 | 0 / 33.3 / 66.7% |
| 2025-11 | 2 / 0 | 0 / 0 / 100% | 4 / 1 | 25 / 0 / 75% |
| 2025-12 | 4 / 1 | 25 / 75 / 0% | 3 / 1 | 33.3 / 33.3 / 33.3% |
| 2026-01 | 1 / 0 | 0 / 0 / 100% | 4 / 0 | 0 / 50 / 50% |
| 2026-02 | 1 / 1 | 100 / 0 / 0% | 3 / 0 | 0 / 66.7 / 33.3% |
| 2026-03 | 4 / 1 | 25 / 0 / 75% | 3 / 2 | 66.7 / 33.3 / 0% |
| 2026-04 | 5 / 1 | 20 / 20 / 60% | 7 / 2 | 28.6 / 42.9 / 28.6% |
| 2026-05 | 3 / 0 | 0 / 0 / 100% | 3 / 1 | 33.3 / 33.3 / 33.3% |
| 2026-06 | 5 / 0 | 0 / 20 / 80% | 6 / 0 | 0 / 83.3 / 16.7% |
| 2026-07 | 1 / 0 | 0 / 0 / 100% | 0 / 0 | 0 / 0 / 0% |

## Interpretation

The full-history samples are sufficient to verify that the real-data funnel, pending lifecycle, and cost accounting operate across multiple years, and to identify the R:R gate as the dominant bottleneck. They are not sufficient for production, ML approval, or profitability claims:

- only 25 LONG and 28 SHORT trades close in independent fixed-bias views;
- annual cohorts are much smaller;
- no causal HTF bias process exists;
- the cost scenario is assumed rather than feed-calibrated;
- no out-of-sample parameter selection was performed.

The next recommended research step is a non-behavioral audit of the `4,551` minimum-R:R rejections: inspect causal TP2 distance, structural stop distance, and resulting R:R distributions by year and direction. Strategy rules should remain frozen until that evidence is reviewed.
