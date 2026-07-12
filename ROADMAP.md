# Roadmap

AurumFlow is research software. This roadmap describes possible development stages without delivery dates or performance promises.

## Stage 1: RULE_ONLY Baseline

- Keep deterministic rule behavior explicit and test-covered.
- Improve examples and documentation for supported CSV inputs.
- Expand diagnostics around accepted and rejected setups.
- Preserve no look-ahead guarantees.

## Stage 2: Diagnostics

- Add richer rejection summaries for research notebooks and reports.
- Improve visual inspection outputs for signals and backtest events.
- Add lightweight fixtures for repeatable examples.
- Document common data-quality problems.

## Stage 3: Automatic HTF Bias Research

- Research higher-timeframe bias rules that can be tested causally.
- Add synthetic tests for time alignment and closed-candle boundaries.
- Compare automatic bias outputs against manually supplied bias.
- Keep manual bias as the default until evidence supports a change.

## Stage 4: Richer SMC Concepts

- Research additional deterministic concepts only when they can be specified clearly.
- Add tests before enabling any new rule in default behavior.
- Keep concept definitions documented with assumptions and invalidation rules.

## Stage 5: ML Validation

- Define manifest requirements for feature ordering, target horizon, class semantics, calibration, and training windows.
- Add reproducible validation reports for any candidate model.
- Require chronological out-of-sample evidence before model output can gate signals.
- Keep ML optional and unavailable by default.

## Stage 6: Hybrid Mode

- Enable `HYBRID_VALIDATED` only after validation criteria are met.
- Compare candidate behavior against the `RULE_ONLY` baseline.
- Track stability, drawdown, expectancy, and trade count across folds.
- Keep failure states explicit and conservative.

## Stage 7: Paper Trading Improvements

- Improve paper-ledger diagnostics and replay tools.
- Add state validation around duplicate signals and simulated fills.
- Keep real-money execution unavailable unless a separate safety design is reviewed.

## Stage 8: Live Execution Research

- Research broker abstraction and operational safety requirements.
- Define hard controls for credentials, dry-run behavior, order sizing, and emergency stops.
- Treat live execution as a separate research track, not a default feature.
