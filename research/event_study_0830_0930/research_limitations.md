# Research Limitations

This phase creates falsifiable definitions and an isolated implementation path. It does not establish that the strategy works.

## Blocking local-data limitations

The only normalized local price file found is `data/local/XAUUSDM15.utc.csv`, containing 15-minute bars from 2023-07-25 through 2026-07-14. The original broker export is also M15. The existing data-quality report records additional constraints: broker/feed and price type are unknown, volume is tick volume, and the spread field is zero.

That dataset is **not suitable for the requested event study**:

- it cannot distinguish 08:30–08:35 from the remainder of the 08:30 bar;
- it cannot construct five-minute heatmaps;
- it cannot confirm one- or three-minute displacement, pivots, MSS, FVGs or rejection blocks;
- it cannot determine the ordering of an entry, stop and target touched inside one bar;
- a zero spread field cannot support after-cost event-time inference;
- M15 extremes can create false sweeps/re-entries because the intrabar path is unknown.

The framework therefore must fail closed on M15 input. Running the requested backtest on these files would create false precision.

## Required data not presently available

1. One-minute or finer XAUUSD bid/ask OHLC (ticks preferred) with timezone/provenance, 07:30–10:30 ET coverage and enough surrounding data for London/prior-day/ADR features.
2. A second market-quality reference—preferably one-minute or tick COMEX GC—for feed validation and a sensitivity analysis between fragmented spot XAUUSD and centralized futures.
3. Historical, point-in-time U.S. release records with scheduled timestamp, event name, importance taxonomy, actual, consensus, previous, revision, units and publication/retrieval vintage. A current calendar page is not a historical surprise database.
4. Historical spread or bid/ask observations by broker. If unavailable, normal/event spread and slippage grids must be assumptions, never observed costs.
5. For the strongest version of the 09:30 incremental test: DXY or a liquid dollar proxy, nominal and real Treasury yields, NQ/ES returns and equity opening-imbalance/volume measures where licensed.

## Market and instrument limitations

- **Spot fragmentation:** XAUUSD has no single consolidated tape. Broker bars can differ in wicks, spreads, rollovers and timestamps, which directly affects sweep/FVG/rejection labels.
- **Futures-versus-spot transfer:** Much of the strongest evidence studies COMEX futures, not retail spot. COMEX price discovery supports relevance, but basis, liquidity, transaction costs and feed construction differ.
- **Changing microstructure:** Electronic participation, release dissemination, algorithmic latency and contract liquidity changed across the samples in S12–S17. Historical effect size need not persist.
- **Price discovery versus predictability:** Fast, high event-time volatility may be efficient incorporation of news. It does not imply a forecastable reversal or continuation after executable costs.
- **Latent mechanisms:** OHLC cannot identify retail stop inventory, institutional intent, hidden orders or an “algorithmic delivery” process.

## Calendar and time limitations

- America/New_York and Europe/London must be handled as IANA zones. The U.S. and U.K. change DST on different dates, so a fixed “London session in ET” silently shifts for several weeks each year.
- Release schedules can change, be delayed, or contain simultaneous events. Historical classification must use the schedule known at the time, not a current reconstructed page alone.
- “Major” and “minor” are not official universal labels. The taxonomy must be documented independently of the price response and sensitivity-tested.
- Surprise standardization is category- and unit-specific. Revisions, seasonal adjustment, benchmark changes and simultaneous releases make a simple actual-minus-consensus value incomplete.
- Federal Reserve decisions usually occur outside the requested window; they should not be forced into an 08:30 taxonomy.

## Statistical limitations

- **Multiple comparisons:** Three families, two bar scales, many entry geometries, several windows, thresholds, news categories, directions and cost scenarios create a large researcher-degrees-of-freedom problem.
- **Small cells:** Important release categories occur monthly or less often. Year × direction × category × geometry tables will frequently be underpowered; warnings must be explicit.
- **Dependence:** Trades from the same event and overlapping entry variants are not independent. Resampling must occur by session/event, not by trade row.
- **Non-stationarity:** Inflation, rate and geopolitical regimes can change gold's response. Random train/test splits are inappropriate; use expanding/rolling chronological validation and a final untouched holdout.
- **Threshold mining:** Selecting an exhaustion, sweep buffer, pivot width or OTE ratio on all data will overfit. Continuous effects and preregistered grids take precedence over best-cell reporting.
- **Matching/model risk:** An apparent 09:30 effect can reflect persistence from 08:30, scheduled 10:00 anticipation, day-of-week, prior volatility or cross-asset moves. Results depend on control specification.
- **Economic versus statistical significance:** Tiny effects may be significant with many bars yet untradeable. Event count, cost-adjusted R and break-even cost matter more than bar-level p-values.
- **Bootstrap limits:** Few years or rare events yield unreliable percentile intervals. Bootstrap output must not conceal insufficient time coverage.

## Definition and execution limitations

- Lifecycle states are known only after 10:30 and are descriptive outcomes. Selecting an earlier entry with the final state is look-ahead bias.
- Pivots are known only after right-hand bars close. FVGs require the third candle to close. Rejection-block selection must choose the first qualifying candle rather than the best later example.
- OHLC cannot reliably order stop and target touches in the same bar. The primary bar-based simulation must assume the adverse outcome; tick data are needed for resolution.
- Limit fills at an OHLC touch can be optimistic during announcements. A touched price is not proof that the order received a fill at the displayed quantity.
- MFE/MAE and R depend on the chosen invalidation, fill and cost model. Comparisons must use identical trigger cohorts and execution rules.
- “Opposing liquidity” is a predeclared price level, not observed depth. Time-to-level results should not be interpreted as evidence that orders were resting there.

## Source-review limitations

- The strongest direct gold studies cover COMEX samples ending before the present and use different frequencies and event sets. Transfer to modern XAUUSD is an inference to be tested.
- Several full papers are paywalled; where full text was unavailable, only claims verifiable from the abstract/metadata were used and this is recorded in `source_register.csv`.
- Tier 3/4 sources define ICT/SMC vocabulary but provide no reliable proof of causation or profitability. Terminology can vary across educators.
- The recent MNQ robustness preprint (S34) is useful opposing evidence but is not peer reviewed and needs replication.
- Failure to locate a study of a specific effect is not proof that no such study exists. The review documents “not verified,” not “impossible.”

## Interpretation boundary

The research can estimate conditional associations and executable historical outcomes under stated assumptions. It cannot prove manipulation, guarantee future performance, or authorize production changes. Any promising result is only a candidate for later independent replication, alternative-feed validation, paper trading and a separate production review.
