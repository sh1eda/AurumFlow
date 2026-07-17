# AurumFlow Implementation Plan

## Summary
Build a conservative offline-first research, backtest, walk-forward, and paper-trading system around the existing XGBoost work, but treat all current model/backtest claims as unverified. The first implementation will not enable real-money order execution.

Implementation starts with `RULE_ONLY`. Missing or unverified ML artifacts must not block rule-system development.

Important repo findings to document first in `docs/implementation/REPOSITORY_ANALYSIS.md`:
- Current working tree lacks physical Python/model files; legacy scripts and model pointers exist in `HEAD`.
- Existing models are Git LFS pointers in `HEAD`, not loadable `.pkl` files in the visible checkout.
- Legacy training uses XGBoost binary classification with target `1 = Close[t+5] > Close[t]`, `0 = not higher`.
- Intraday scripts use random stratified splits, uncalibrated probabilities, placeholder SMC backtest features, no SL/TP, and a look-ahead-prone FVG detector.
- Compact knowledge docs are sufficient for v1; do not read raw PDFs unless a later ambiguity requires it.

## Public Interfaces
Add a Python package plus CLI-style entrypoints, using standard dataclasses and JSON output.

Core output schema:
```json
{
  "decision": "BUY | SELL | NO_TRADE",
  "setup_name": "SweepMssFvgRetraceLong | SweepMssFvgRetraceShort | null",
  "entry_type": "FVG_MIDPOINT_LIMIT",
  "entry_price": 0.0,
  "entry_zone": {"low": 0.0, "high": 0.0},
  "stop_loss": 0.0,
  "take_profit": [{"name": "TP1_1R", "price": 0.0}, {"name": "TP2_LIQUIDITY", "price": 0.0}],
  "risk_reward": 0.0,
  "confidence": 0.0,
  "ml": {
    "direction": "UP_HORIZON | NOT_UP_HORIZON | UNAVAILABLE",
    "confidence": 0.0,
    "raw_prediction": null,
    "probabilities": {},
    "model_version": "",
    "feature_timestamp": "",
    "feature_hash": ""
  },
  "htf_bias": "BULLISH | BEARISH | NEUTRAL",
  "market_regime": "COMPRESSION | EXPANSION | RETRACEMENT | REVERSAL_CANDIDATE | UNKNOWN",
  "confluences": [],
  "structural_invalidation": "",
  "explanation": "",
  "valid_reasons": [],
  "rejection_reasons": []
}
```

Accepted signals also include a lifecycle payload with setup state history and causal
indices/timestamps for the sweep, MSS, FVG, activation, first eligible fill,
expiration, invalidation, fill, and exit.

Model adapter contract:
`ModelPrediction(direction, confidence, raw_prediction, probabilities, model_version, feature_timestamp, feature_hash)`.
The adapter must load only through a manifest that declares feature names/order, target horizon, class semantics, calibration status, training window, and data hash.

## Implementation Changes
- Create a source-grounded research package without restoring or overwriting the dirty legacy worktree. Legacy scripts from `HEAD` are reference material only.
- Implement causal data loaders for Yahoo-style OHLCV CSVs, timezone-aware timestamps, closed-candle-only HTF resampling, and `merge_asof` joins that never use incomplete HTF candles.
- Reject naive source timestamps without an explicit timezone, report source-data defects without silent repair, and normalize validated output to UTC only through an explicit command.
- Implement deterministic event primitives first: swing highs/lows, time-based liquidity levels grouped by bar timestamp and detected at period close, raw liquidity raids, confirmed sweeps, body-close BOS/MSS, raw FVGs known only after candle 3 closes, IFVG close-through flags, and basic FVG fill/CE tracking.
- Keep PO3, SMT, MMXM, market-cycle labels, session killzones, displacement strength, equal-high tolerance, confidence weights, RR threshold, and CE midpoint entries explicitly marked as `IMPLEMENTATION_HYPOTHESIS`, not source rules.
- Implement only two v1 setup templates: `SweepMssFvgRetraceLong` and `SweepMssFvgRetraceShort`.
- Valid BUY/SELL requires all hard gates: closed candle data, non-neutral HTF draw, confirmed sweep, body-close MSS in signal direction, a newly known post-MSS FVG, structural stop, causally known opposing-liquidity target, minimum RR `2.0`, operating-mode allowance, and confidence `>= 0.70`.
- `RULE_ONLY` and `HYBRID_RESEARCH` must not return `NO_TRADE` solely because ML is missing or unverified. `HYBRID_VALIDATED` must reject with `model_not_verified`, `model_unavailable`, or another stable ML rejection code when an approved ML behavior cannot be applied.
- Implement stop default as beyond the swept structural swing plus spread buffer, entry default as FVG consequent encroachment midpoint, TP1 as `1R`, and TP2 as the nearest post-MSS opposing external liquidity, excluding the already-broken MSS swing. These defaults are hypotheses and must be reported as such.
- Reject setups whose structural stop distance is below the configured minimum stop-distance guard so costs cannot create impossible R-multiple artifacts.
- Implement backtesting as a closed-bar event simulator with `PENDING_LIMIT_AFTER_FVG_CREATION`, next-bar-first midpoint fills, an eight-bar default pending lifetime, conservative pre-entry invalidation, spread/slippage/commission costs applied to all exits, no same-bar hindsight, explicit order outcomes, and full signal/rejection logs.
- Keep the FVG midpoint as the only implemented entry model until another model is explicitly researched and validated.
- Require swing targets to satisfy `detected_at <= order_activation_at`; index position alone is not causal evidence.
- Implement paper trading as a file-backed replay ledger only. Any broker/live order function must raise a hard error unless a future controlled-execution module is explicitly added.

## Test Plan
- Unit tests for FVG timing, swing detection, liquidity raids, confirmed sweeps, BOS/MSS body-close behavior, HTF closed-candle joins, and no future leakage.
- Adapter tests for feature order mismatch, missing model file, missing `predict_proba`, uncalibrated probability handling, feature hash stability, and class-label mapping.
- Signal tests for valid long, valid short, causal target availability, ML conflict, RR too low, neutral HTF bias, missing sweep, missing MSS, missing FVG, and model unavailable.
- Backtest tests for pending-order activation, first eligible fill, no same-bar hindsight, bounded expiration, structural/FVG invalidation, dataset-censored entries, stop-before-target conservative ordering, costs, no overlapping positions, and deterministic replay.
- Funnel tests for LONG/SHORT separation, combined counts, survival percentages, ranked outcome codes, and repeated-run determinism.
- Validation report tests comparing rule-only versus ML-gated variants over chronological folds, requiring after-cost OOS lift before enabling ML-gated BUY/SELL in paper mode.

## Assumptions
- Because no user selection was returned, use the recommended primary path: offline CSV research plus verified retraining before trusting existing LFS models.
- Initial execution timeframe is 15m, with HTF context from resampled 4H/Daily where data is available.
- Existing model classes are not BUY/SELL labels; class `1` means “higher after horizon,” and class `0` means “not higher after horizon.”
- No raw PDFs are needed for v1 because the compact knowledge files define the implementation boundaries clearly.
- The system prioritizes rare, explainable `NO_TRADE`-heavy behavior over signal frequency.

## Operating Modes

- `RULE_ONLY`: SMC/ICT rules may generate `BUY`, `SELL`, or `NO_TRADE`. ML is not required and cannot block or create trades.
- `HYBRID_RESEARCH`: rule behavior is identical to `RULE_ONLY`. ML predictions are logged and compared when adapter inputs are available, but ML must not create trades, block trades, alter entries, alter stops/targets, or alter eligibility confidence. Signals are marked research-only.
- `HYBRID_VALIDATED`: ML may filter, rank, or modify confidence only after the validation gate in `docs/implementation/MODEL_INTEGRATION.md` is satisfied. ML must never replace structural SMC/ICT gates.

## Revised Implementation Order

1. Keep planning documents synchronized with the approved operating modes.
2. Implement `RULE_ONLY` causal data loading, event primitives, setup evaluation, signal schema, rejection reasons, stop/target logic, and tests.
3. Implement closed-bar backtesting with conservative fills, costs, signal logs, and tests.
4. Implement chronological walk-forward validation with `RULE_ONLY` baseline reports and tests.
5. Implement file-backed paper trading with no broker execution and tests.
6. Implement model adapter readiness and `HYBRID_RESEARCH` logging interfaces without fabricated predictions.
7. Keep `HYBRID_VALIDATED` disabled unless an approved validation report explicitly enables an ML behavior.

The entry-lifecycle correction and rule-funnel diagnostics are implemented before any account-level risk management, automatic HTF-bias selection, new setup concepts, or ML behavior.

## Command Surface

Implemented CLI entrypoint:

- `python3 -m xauusd_signal signal --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 200`
- `python3 -m xauusd_signal backtest --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 500 --spread-cost 0.2 --slippage 0.1`
- `python3 -m xauusd_signal validate --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 800 --folds 5 --spread-cost 0.2 --slippage 0.1`
- `python3 -m xauusd_signal paper --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 200 --ledger /private/tmp/xauusd-paper-ledger.jsonl`
- `python3 -m xauusd_signal diagnose --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 5000`
- `python3 -m xauusd_signal data-check --csv data/local/xauusd_15m.csv --source-timezone UTC --format json`

Installed command equivalent:

- `aurumflow diagnose --csv 15m_data.csv --mode RULE_ONLY --htf-bias BULLISH --bars 5000`
- `aurumflow data-check --csv data/local/xauusd_15m.csv --source-timezone UTC --format json`

## HYBRID_VALIDATED Validation Gate

- Primary metric: after-cost out-of-sample expectancy.
- Secondary metrics: max drawdown, profit factor, average R, and fold-to-fold stability.
- Do not approve ML when primary expectancy worsens, even if secondary metrics improve.
- Minimum evidence: at least 5 chronological out-of-sample folds and at least 100 closed out-of-sample trades for the evaluated ML behavior.
- If evidence is below threshold, status is `INSUFFICIENT_EVIDENCE`.
- Approved ML behavior must be explicit: filter, ranker, confidence modifier, or a named combination.
