# Changelog

All notable changes to AurumFlow will be documented in this file.

The format is based on human-readable release notes. This project does not promise delivery dates or future performance.

## [0.1.0] - 2026-07-13

### Added

- Initial research release.
- Explainable XAUUSD signal package.
- Deterministic `RULE_ONLY` signal evaluation.
- `HYBRID_RESEARCH` and `HYBRID_VALIDATED` mode interfaces.
- Causal OHLCV loading, resampling, and higher-timeframe join helpers.
- Market-event detection for swings, fair value gaps, liquidity raids, structure breaks, and time liquidity levels.
- CLI commands for signals, backtests, walk-forward validation, and paper-signal logging.
- Pending midpoint-limit lifecycle with bounded expiration and conservative pre-entry invalidation.
- Causal swing-target filtering at order activation.
- LONG, SHORT, and combined rule-funnel diagnostics with text and JSON output.
- Strict `data-check` workflow with explicit timezone normalization, OHLC validation, gap reporting, and guarded normalized output.
- UTC period slicing and explicit backtest holding-period configuration for reproducible real-data reports.
- Headerless UTF-16 MetaTrader 5 CSV import support.
- Real-data quality, yearly/monthly fixed-bias funnel, and zero/research-cost baseline reports.
- Baseline backtesting and validation reports.
- Model-adapter safeguards for optional ML research.
- Test suite covering core data, event, strategy, backtest, validation, model, paper, and CLI behavior.

### Changed

- Reused causally available event primitives during replay to make multi-year
  diagnostics practical without changing strategy or lifecycle behavior.
