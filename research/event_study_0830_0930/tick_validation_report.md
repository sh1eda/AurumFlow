# XAUUSD Tick Validation Report

Generated: 2026-07-17T14:06:18+00:00  
Input: `data/local/XAUUSD_202507171300_202607171409.csv`  
Overall verdict: **WARNING**  
Quality score: **89/100**  
Normalization gate: **PASS**

This report qualifies data only. Stage 1 and all strategy tests were not run.

## Whole-file streaming results

| Measure | Result |
|---|---:|
| Physical data rows | 114,681,897 |
| Parsed rows | 114,681,897 |
| First source timestamp | 2025-07-17T13:00:00.428 |
| Last source timestamp | 2026-07-17T14:09:53.920 |
| First UTC timestamp (assumed mapping) | 2025-07-17T10:00:00.428+00:00 |
| Last UTC timestamp (assumed mapping) | 2026-07-17T11:09:53.920+00:00 |
| Duplicate timestamp rows | 1,091,679 |
| Timestamp reversals | 0 |
| Malformed rows | 0 |
| Invalid required rows | 0 |
| Zero-spread rows | 627,190 |
| Negative-spread rows | 0 |
| Bid-side values reconstructed from prior quote | 26,239,500 |
| Ask-side values reconstructed from prior quote | 26,124,875 |
| Flag/state consistency violations | 0 |
| LAST values present | 0 |
| VOLUME values present | 0 |

## Spread diagnostics (price units)

| Measure | Result |
|---|---:|
| Median | 0.16 |
| Average | 0.1592 |
| 95th percentile | 0.25 |
| 99th percentile | 0.44 |
| Maximum | 65.93 |

| Spread range | Rows | Percentage |
|---|---:|---:|
| 0.00 | 627,190 | 0.5469% |
| 0.01-0.05 | 11,591,401 | 10.1074% |
| 0.06-0.10 | 11,145,712 | 9.7188% |
| 0.11-0.20 | 73,583,373 | 64.1630% |
| 0.21-0.30 | 14,381,891 | 12.5407% |
| 0.31-0.50 | 2,672,164 | 2.3301% |
| 0.51-1.00 | 451,918 | 0.3941% |
| 1.01-2.00 | 196,535 | 0.1714% |
| 2.01-5.00 | 11,227 | 0.0098% |
| >5.00 | 20,486 | 0.0179% |

## Tick frequency

| Measure | Result |
|---|---:|
| Populated minutes | 348,720 |
| Mean ticks per populated minute | 328.87 |
| Median ticks per populated minute | 254.00 |
| 95th percentile ticks/minute | 939.00 |
| 99th percentile ticks/minute | 1,260.00 |
| Maximum ticks/minute | 2,956 |
| Median interarrival | 71 ms |
| 95th percentile interarrival | 705 ms |
| 99th percentile interarrival | 1,466 ms |
| Maximum interarrival | 266,421,329 ms |

`Missing timestamps` are not defined as absent milliseconds because ticks are event-driven. The coverage section instead reports empty minute buckets and incomplete registered windows.

## New York event-window coverage

Candidate weekdays: **262**  
Weekday dates with no ticks: **1**

| Window | Complete days | Complete coverage | Missing windows |
|---|---:|---:|---:|
| delivery_0930_1000 | 257 | 98.09% | 5 |
| equity_open_reaction_0930_0950 | 257 | 98.09% | 5 |
| extended_impulse_0830_0845 | 258 | 98.47% | 4 |
| full_study_0730_1030 | 255 | 97.33% | 7 |
| initial_impulse_0830_0835 | 258 | 98.47% | 4 |
| pre_news_0730_0830 | 257 | 98.09% | 5 |
| pre_news_0800_0830 | 257 | 98.09% | 5 |
| retracement_0835_0930 | 256 | 97.71% | 6 |
| secondary_1000_1030 | 258 | 98.47% | 4 |

Missing anchor-window dates:

- initial_impulse_0830_0835: 2025-12-25, 2026-01-01, 2026-04-03, 2026-07-17
- equity_open_reaction_0930_0950: 2025-09-22, 2025-12-25, 2026-01-01, 2026-04-03, 2026-07-17
- secondary_1000_1030: 2025-12-25, 2026-01-01, 2026-04-03, 2026-07-17

Missing weekday dates: 2026-04-03

Holiday and scheduled-closure status is not inferred without an exchange calendar; a weekday with no ticks is reported as a missing date, not automatically called corruption.

## Weekend observations

- new york saturday ticks: 0
- new york sunday ticks: 6,057,384
- source clock saturday ticks: 0
- source clock sunday ticks: 0
- Note: Sunday New York ticks can be legitimate electronic-session reopening data; weekend counts are reported, not automatically classified as corrupt.

## Quality assessment

Warnings:

- Source timezone is inferred rather than confirmed by broker/feed documentation
- 20,486 valid quote states have spreads above 5.00 price units; their timing must be isolated before execution-cost inference
- 627,190 reconstructed quote states have zero spread; execution-cost research must report a nonzero-cost sensitivity rather than treating them as a general zero-cost assumption

## Normalized outputs

- Canonical tick dataset: research/event_study_0830_0930/external_data/normalized/XAUUSD_202507171300_202607171409.canonical_ticks.csv
- One-minute bid/ask bars: research/event_study_0830_0930/external_data/normalized/XAUUSD_202507171300_202607171409.1m_bidask.csv
- Canonical tick rows: 114,681,897
- One-minute bars: 348,720

The source export was opened read-only and was not overwritten.

## Research readiness

- Additional Data Required: Point-in-time U.S. economic releases with actual/consensus/vintage fields; broker server-timezone confirmation; broker commission and realized slippage/latency; trade/last/volume data for trade-price studies; and additional full years for the registered year-by-year stability requirement.
- Entry Geometry: Tick and one-minute bid/ask geometry can be studied later; not authorized in this qualification phase.
- Execution Cost Modeling: Observed bid/ask spreads are available. Broker commission, latency and realized slippage observations are still required for a complete execution model.
- Lifecycle Classification: Market path data are sufficient after normalization, but lifecycle research must wait until Stage 1 and the economic-calendar gate are complete.
- Stage 1: Technically runnable after a point-in-time economic calendar is supplied; definitive event attribution remains conditional on timezone confirmation.

## Derivative verification

- Status: PASS
- One-minute rows checked: 348,720
- Tick-count sum: 114,681,897
- Minute timestamp duplicates: 0
- Minute timestamp reversals: 0
- OHLC invariant violations: 0
- Open/close negative-spread violations: 0
- Minutes with maximum spread above 5.00: 143
- Extreme-spread minutes inside 08:00–10:30 ET: 4

No empirical event study, lifecycle classification, entry-geometry test, or backtest was run.
