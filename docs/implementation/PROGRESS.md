# Implementation Progress

## Current Status

The approved RULE_ONLY-first implementation is in place. The system now has an offline Python package, CLI entrypoint, causal data layer, deterministic SMC/ICT event primitives, rule-only signal generation, closed-bar backtesting, chronological walk-forward reporting, file-backed paper ledger, and manifest-backed model adapter readiness.

No real-money execution has been implemented. The only real-order function intentionally raises a hard error.

## Implemented Modules

- `xauusd_signal/types.py`: canonical enums, signal schema, model prediction schema, rejection codes, and validation statuses.
- `xauusd_signal/data.py`: OHLCV CSV loader, timezone-aware timestamps, `closed_at` handling, resampling, and causal higher-timeframe joins.
- `xauusd_signal/events.py`: swing highs/lows, FVG creation, FVG fill status, IFVG close-through events, time-liquidity levels, liquidity raids, and MSS body-close events.
- `xauusd_signal/strategy.py`: RULE_ONLY, HYBRID_RESEARCH, and HYBRID_VALIDATED mode handling; `SweepMssFvgRetraceLong`; `SweepMssFvgRetraceShort`; stop, target, confidence, and rejection logic.
- `xauusd_signal/backtest.py`: closed-bar replay simulator with next-bar entry search, conservative stop-before-target handling, spread/slippage/commission costs, missed-entry logging, and rejection aggregation.
- `xauusd_signal/validation.py`: chronological split generation, RULE_ONLY walk-forward baseline reporting, and HYBRID_VALIDATED approval gate.
- `xauusd_signal/paper.py`: JSONL file-backed paper ledger and hard-blocked real-order function.
- `xauusd_signal/models.py`: manifest-backed model adapter, feature hashing, feature-order enforcement, class-semantics checks, and `UNAVAILABLE` behavior for missing or invalid artifacts.
- `xauusd_signal/cli.py`: command-line commands for signal generation, backtests, validation, and paper-ledger recording.

## Operating Modes

- `RULE_ONLY`: implemented. SMC/ICT rules may produce `BUY`, `SELL`, or `NO_TRADE`. ML is not required and cannot block or create trades.
- `HYBRID_RESEARCH`: interface implemented. Rule behavior remains identical to `RULE_ONLY`; signals are marked research-only. ML may be logged only when adapter inputs are actually available.
- `HYBRID_VALIDATED`: gate implemented but not enabled. ML may not affect trades until the explicit validation requirements are met.

## HYBRID_VALIDATED Approval Gate

HYBRID_VALIDATED remains disabled unless all of the following are true:

- physical model artifact exists,
- complete manifest exists,
- adapter verifies object type, feature order, class order, class semantics, `predict_proba()` availability, missing-value behavior, and feature hash stability,
- feature generation is causal and closed-candle-only,
- chronological walk-forward validation is complete,
- validation includes spread, slippage, and commission,
- primary metric, after-cost out-of-sample expectancy, is positive,
- primary expectancy improves versus paired RULE_ONLY baseline,
- at least 5 chronological OOS folds are evaluated,
- at least 100 closed OOS trades are evaluated for the ML behavior.

If trade count or fold count is insufficient, status remains `INSUFFICIENT_EVIDENCE`. ML must not be approved based only on secondary metrics when primary expectancy worsens.

## Verification Completed

Last implementation verification:

- `python3 -m pytest`: 21 tests passed.
- `python3 -m compileall xauusd_signal tests`: passed.
- Configured lint/type checks: none found beyond `pyproject.toml` pytest configuration.

Covered test areas:

- FVG timing and third-candle availability.
- Swing detection timing.
- Causal higher-timeframe joins.
- FVG fill and IFVG close-through timing.
- Time-liquidity level timing.
- RULE_ONLY signal behavior.
- HYBRID_RESEARCH does not block rule signals.
- HYBRID_VALIDATED rejects unverified ML.
- Backtest next-bar entry handling.
- Conservative stop-before-target same-bar behavior.
- After-cost time-exit R calculation.
- Walk-forward evidence gate.
- Model feature-order hashing.
- Missing artifact, feature mismatch, missing `predict_proba()`, ambiguous class mapping, and valid injected model predictions.
- Paper ledger recording and real-order blocking.

## Smoke Outputs

The sample RULE_ONLY smoke run is infrastructure validation only, not a performance claim.

Backtest smoke command:

```bash
python3 -m xauusd_signal backtest --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 500 --spread-cost 0.2 --slippage 0.1 --commission-r 0.0
```

Observed result:

- closed trades: `0`
- expectancy: `0.0`
- max drawdown R: `0.0`
- profit factor: `0.0`

The zero-trade result reflects the strict v1 gates, especially post-MSS opposing-liquidity TP2 requirements and risk/reward filtering, on the sampled data slice.

## Current Commands

RULE_ONLY signal generation:

```bash
python3 -m xauusd_signal signal --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 200
```

Backtest:

```bash
python3 -m xauusd_signal backtest --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 500 --spread-cost 0.2 --slippage 0.1 --commission-r 0.0
```

Walk-forward validation:

```bash
python3 -m xauusd_signal validate --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 800 --folds 5 --spread-cost 0.2 --slippage 0.1
```

Paper ledger:

```bash
python3 -m xauusd_signal paper --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 200 --ledger /private/tmp/xauusd-paper-ledger.jsonl
```

## Look-Ahead And Fill Review

- Signal evaluation uses data through the current closed candle only.
- FVGs become available only after the third candle closes.
- Swing points are detected only after the right candle closes.
- Higher-timeframe joins use `closed_at` with backward `merge_asof`.
- Backtest entry search begins after the signal bar.
- Stop and target touched in the same bar are resolved stop-first unless lower-timeframe sequencing is later added.
- Spread, slippage, and commission are applied to all exits, including time exits.

## Remaining Limitations

- Physical ML model binaries are still unavailable in the visible checkout; model predictions remain `UNAVAILABLE`.
- HYBRID_VALIDATED is not enabled and must remain disabled until the approval gate is satisfied.
- HTF bias is passed explicitly through CLI/config; automated HTF draw selection is not implemented yet.
- Session calendar handling is basic; time-liquidity levels support configurable timezone grouping but not full venue/session rules.
- The v1 setup templates are intentionally narrow and may produce very few or zero trades on short samples.
- TP2 uses nearest post-MSS opposing swing liquidity; richer liquidity taxonomies, equal-high/equal-low clustering, and session liquidity are not yet validated.
- No broker integration exists.
- No live/paper fill lifecycle beyond file-backed signal recording is implemented.
- Existing repository Git state contains pre-existing staged deletions and same-path untracked files; that state was not modified or repaired during implementation.

## Documentation Synchronization

The following planning documents were synchronized with actual behavior:

- `docs/implementation/IMPLEMENTATION_PLAN.md`
- `docs/implementation/STRATEGY_SPEC.md`
- `docs/implementation/REPOSITORY_ANALYSIS.md`
- `docs/implementation/MODEL_INTEGRATION.md`

This file records implementation progress and should be updated whenever behavior, verification results, operating-mode status, or limitations change.
