# Rule Funnel Report

## Purpose

The rule funnel identifies where deterministic setup candidates stop progressing. It is a diagnostic report, not a performance report, and it does not change strategy eligibility.

Run it with:

```bash
aurumflow diagnose \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --bars 5000
```

Human-readable output is the default. Add `--format json` for structured output.

## Stage Semantics

The report tracks LONG, SHORT, and combined counts for evaluated bars, accepted HTF bias, confirmed liquidity raids, confirmed sweeps, directional MSS, a newly known post-MSS FVG, pending-order creation, causal target availability, structural stop availability, minimum R:R, activation, fills, expirations, invalidations, and closed trades.

In the current v1 event model, a confirmed directional `LiquidityRaid` is also the confirmed-sweep primitive. Those two stages therefore have equal counts. `pending_entry_order_created` means the new FVG defines a midpoint order candidate; `pending_order_activated` means all later target, stop, R:R, mode, and confidence gates passed and the backtester recorded the order.

Fill, expiry, and invalidation are sibling outcomes. Their previous-stage percentage uses `pending_order_activated` as the denominator. Closed-trade survival uses `entry_filled`.

## Deterministic Verification Dataset

No market-data CSV is committed to the repository. This report retains the
deterministic 15-minute lifecycle fixture from `tests/test_diagnostics.py`
solely to verify semantics. Measured local-market results are documented in
[`REAL_DATA_FUNNEL_REPORT.md`](REAL_DATA_FUNNEL_REPORT.md).

- Bars: `13`
- Start: `2025-01-01 00:00:00+00:00`
- End: `2025-01-01 03:15:00+00:00`
- Duration: `3 hours 15 minutes`
- Mode: `RULE_ONLY`
- HTF bias: `BULLISH`
- Entry model: `FVG_MIDPOINT`
- Maximum wait: `8` bars

## Verification Counts

| Stage | LONG | SHORT | Combined |
| --- | ---: | ---: | ---: |
| Bars evaluated | 3 | 3 | 6 |
| Accepted HTF bias | 3 | 0 | 3 |
| Confirmed liquidity raids | 3 | 0 | 3 |
| Confirmed sweeps | 3 | 0 | 3 |
| Directional MSS | 3 | 0 | 3 |
| Valid post-MSS FVG | 1 | 0 | 1 |
| Pending entry order created | 1 | 0 | 1 |
| Target available | 1 | 0 | 1 |
| Structural stop available | 1 | 0 | 1 |
| Minimum R:R passed | 1 | 0 | 1 |
| Pending order activated | 1 | 0 | 1 |
| Entry filled | 1 | 0 | 1 |
| Entry expired | 0 | 0 | 0 |
| Setup invalidated | 0 | 0 | 0 |
| Trade closed | 1 | 0 | 1 |

The LONG FVG stage retained `33.33%` from the preceding MSS stage and `33.33%` from the initial LONG evaluated set. Every later hard gate retained the single candidate. Ranked codes were `no_valid_fvg: 2` and `entry_filled: 1`.

The mirrored bearish fixture produces the symmetric SHORT result and is covered by the test suite. Repeated runs produce identical reports.

## Interpretation And Next Step

For this semantic fixture, the largest reduction is the requirement for a newly known post-MSS FVG. That result is intentionally constructed and cannot identify a real-market bottleneck.

The real-data run is complete and identifies minimum R:R as the dominant
funnel reduction. See `REAL_DATA_FUNNEL_REPORT.md` for the measured counts and
limitations. Do not tune thresholds from the synthetic fixture.
