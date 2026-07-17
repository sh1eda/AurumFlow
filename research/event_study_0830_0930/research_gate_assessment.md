# Research-Gate Assessment

Gate date: 2026-07-17. The mandatory source-research phase is complete. This gate authorizes only an **isolated research framework** and a future event study when suitable data are supplied. It does not authorize modification of production strategy code, defaults, entries or risk settings, and it does not conclude that any model works.

## Gate decision

**Pass for isolated implementation; blocked for real-data backtest.** The literature, source register, objective definitions, transfer analysis and falsifiable hypotheses are sufficient to implement the measurement framework. The repository's M15, zero-spread, unknown-feed data are insufficient for the requested one-/three-/five-minute analysis, so the real event study and all performance conclusions remain gated.

## Accepted for testing

- Official 08:30 and 10:00 ET scheduled-event windows and a formal 09:30 U.S. cash-equity open.
- Pre-news, London and previous-day ranges; opens, highs, lows and midpoints.
- Event-window return, high-low range, realized movement, ADR share and causal rolling same-time normalization.
- Release class, event category and surprise magnitude when point-in-time data are available.
- Observable breach, acceptance, re-entry, failed-breakout, continuation and reversal paths.
- Causally confirmed one-/three-minute swing breaks, with displacement as normalized price geometry.
- MFE, MAE, time-to-R/opposing-level and conservative cost/fill sensitivity.
- Three standalone families: 08:30 continuation, 08:30 false-move reversal and 09:30 non-news sweep/reversal.

## Modified for XAUUSD

- **09:30:** treated as a possible incremental equity-open/cross-asset repricing window, never as the gold open.
- **Liquidity sweep:** renamed operationally as a predeclared-level breach plus prompt close re-entry; no stop inventory or intent is inferred.
- **Displacement/MSS/FVG:** retained as deterministic, volatility-normalized geometry with causal confirmation times; institutional-order and “fair value” stories are removed.
- **Rejection block/OTE:** retained only as exploratory entry geometry and compared against simpler retracements on identical triggers.
- **Judas swing/manipulation:** represented only by a false-breakout/re-entry/MSS path. The intent claim is excluded.
- **10:00:** split into important release, minor release and no-release cohorts; the candle open has no assumed formal status.
- **London range:** calculated using Europe/London local time, with an ET-clock sensitivity view because DST transitions differ.

## Rejected

- Deliberate manipulation, stop hunting or institutional intent inferred from OHLC.
- The claim that FVGs are economic fair value, contain unfilled institutional orders or must fill.
- A universal accumulation–manipulation–distribution sequence.
- A formal XAUUSD/Nasdaq “10:00 key open.”
- Hindsight daily bias, hindsight swing selection and lifecycle outcome labels used as entry signals.
- Any event-study/backtest result derived from the repository's M15 bars for one-/three-/five-minute questions.

## Lacking reliable evidence

- An independent 09:30 XAUUSD edge after controlling for 08:30 news and impulse persistence.
- A generic non-release 10:00 clock effect.
- Superiority of rejection blocks, FVG edges or OTE ratios over simple market/fixed retracement entries.
- A stable impulse-exhaustion threshold.
- A universal rule that liquidity sweeps reverse rather than continue.
- A higher-timeframe-bias definition that improves gold outcomes without hindsight.

These remain hypotheses, not assumptions.

## Remaining data requirements

1. One-minute or tick XAUUSD with valid bid/ask or historical spread, documented source timezone, DST behavior and feed provenance.
2. Historical point-in-time 08:30/10:00 release calendar with importance, actual, consensus, prior/revision and units.
3. Preferably one-minute/tick COMEX GC for replication and feed-quality comparison.
4. DXY, Treasury/real-yield and NQ/ES event-window data for the controlled 09:30 mechanism test.
5. Enough history for chronological train/validation/holdout splits and category-level power; five or more years is preferable, subject to regime analysis.

The exact input contract will be enforced by the isolated loader. Missing spread data may be handled only with labeled assumption scenarios, never as zero cost.

## Principal data-mining risks

- optimizing among many windows, pivot widths, buffers, entry ratios, expiries and cost settings;
- selecting an exhaustion cutoff after viewing the full response curve;
- reporting only the best news category, direction or year;
- treating correlated entry variants as independent evidence;
- using final lifecycle class to filter an earlier signal;
- reconstructing “major” events or higher-timeframe bias from the observed price response;
- tuning on the final chronological holdout;
- mistaking event-time volatility for tradable directional predictability.

Controls: freeze a primary specification, show all registered variants, cluster/resample by session, use chronological validation, preserve a final holdout, adjust within hypothesis families and require cost/year/direction/category stability.

## Proposed objective definitions

The frozen primary definitions are in `concept_definitions.md`. The minimum implementation set is:

- half-open ET windows using `America/New_York`;
- 08:30 impulse `[08:30,08:35)` and extended impulse `[08:30,08:45)`;
- acceptance = two consecutive one-minute closes outside a predeclared boundary plus buffer;
- re-entry = first close inside the buffered range before acceptance;
- sweep = breach plus close re-entry within the predeclared bar limit;
- displacement = normalized body, range, body-fraction and close-location thresholds using only prior baselines;
- MSS = first displacement close through the latest already-confirmed swing;
- FVG = three-closed-candle wick non-overlap, actionable only after candle three closes;
- exhaustion = preregistered ADR-share/same-time-percentile outcome, analyzed continuously before thresholds;
- full reversal/continuation/partial retracement = retrospective path labels with fixed targets and horizons.

## Proposed experiment sequence

1. **Data audit:** validate timestamp uniqueness, IANA conversion, DST sessions, resolution, gaps, OHLC invariants, bid/ask/spread, calendar provenance and event coverage. Fail closed when required fields are absent.
2. **Unconditional event study:** generate five-minute absolute and directional movement heatmaps from 08:00–10:30 by A/B/C class and D overlay. No entries.
3. **08:30 information test:** compare major/minor/no-release movement, category and standardized surprise effects, with causal same-time normalization.
4. **Incremental 09:30 test:** regress/match 09:30 movement on 08:30 impulse, event/surprise, prior volatility and available dollar/yield/equity controls. Separate mean return from volatility.
5. **10:00 decomposition:** compare important, minor and no-10:00 cohorts; test whether a residual clock effect remains.
6. **Lifecycle study:** calculate causal path features and retrospective mutually exclusive states. Estimate competing continuation/reversal probabilities without using states as signals.
7. **Standalone strategies:** evaluate families A, B and C separately. Do not combine them.
8. **Entry-geometry comparison:** on identical trigger cohorts compare market MSS, FVG edges/midpoint, rejection block, 50/62/75% and OTE variants under identical stops/targets/expiry.
9. **Execution/risk analysis:** normal/event/stressed spread and slippage, conservative same-bar ordering, MFE/MAE/time-to-R, forced exit before important 10:00 releases.
10. **Robustness:** calendar year, direction, news category, impulse bucket, higher-timeframe alignment, 08:30/09:30 agreement and 10:00 flag; session bootstrap confidence intervals and explicit small-N warnings.
11. **Chronological validation:** expanding/rolling training, untouched final holdout, alternative XAUUSD feed and COMEX replication if available.

Only after steps 1–11 can the research answer whether any effect is stable enough for a separate future production-research proposal. Aggregate profitability alone is an automatic failure of the stability gate.
