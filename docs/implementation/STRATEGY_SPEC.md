# Strategy Specification

## Purpose

This specification defines the v1 explainable XAUUSD signal system. It is implementation authority for signal generation, backtesting, walk-forward validation, and paper-trading infrastructure.

The system must prioritize rare, reproducible, structurally valid, explainable setups. When the setup is not complete, the correct decision is `NO_TRADE`.

## Authority And Boundaries

Use this source order:

1. `docs/implementation/IMPLEMENTATION_PLAN.md`
2. this file
3. `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`
4. `docs/source_analysis/CODEX_CONTEXT_GUIDE.md`
5. compact files under `docs/knowledge/`
6. legacy repository code and model artifacts

Do not read raw PDFs during v1 implementation unless compact docs contain an unresolved ambiguity that blocks implementation.

Do not silently merge conflicting concepts. If a conflict affects code, follow the higher-authority source and preserve the conflict in documentation or rejection metadata.

## Signal Decisions

The only valid top-level decisions are:

- `BUY`
- `SELL`
- `NO_TRADE`

`BUY` and `SELL` are allowed only when all hard gates for a v1 setup pass.

`NO_TRADE` must include explicit `rejection_reasons`.

## Output Schema

Every signal evaluation must return this logical schema:

- `decision`: `BUY`, `SELL`, or `NO_TRADE`.
- `setup_name`: `SweepMssFvgRetraceLong`, `SweepMssFvgRetraceShort`, or `null`.
- `entry_type`: `FVG_MIDPOINT_LIMIT` or `null`.
- `entry_price`: numeric price or `null`.
- `entry_zone`: object with `low` and `high`, or `null`.
- `stop_loss`: numeric price or `null`.
- `take_profit`: ordered list of target objects.
- `risk_reward`: numeric ratio or `null`.
- `confidence`: numeric score from `0.0` to `1.0`.
- `ml`: `ModelPrediction` payload.
- `htf_bias`: `BULLISH`, `BEARISH`, or `NEUTRAL`.
- `market_regime`: `COMPRESSION`, `EXPANSION`, `RETRACEMENT`, `REVERSAL_CANDIDATE`, or `UNKNOWN`.
- `confluences`: list of detected source-grounded confluences and research labels.
- `structural_invalidation`: human-readable condition.
- `explanation`: concise human-readable explanation.
- `valid_reasons`: list of reasons the setup is valid.
- `rejection_reasons`: list of reasons no valid setup exists.
- `lifecycle`: setup/order state, state history, causal event indices and timestamps,
  activation, first-fill, expiration, invalidation, entry, exit, and terminal outcome metadata.

The implemented pending-order entry type is `FVG_MIDPOINT_LIMIT`. The midpoint is an
implementation hypothesis, not a claim that it is the optimal FVG entry level.

The JSON names from `IMPLEMENTATION_PLAN.md` are the canonical serialized field names.

## ModelPrediction Contract

Model output must be represented as:

- `direction`: `UP_HORIZON`, `NOT_UP_HORIZON`, or `UNAVAILABLE`.
- `confidence`: numeric score from `0.0` to `1.0`.
- `raw_prediction`: original model class, score, or `null`.
- `probabilities`: class probability map.
- `model_version`: manifest-defined version string.
- `feature_timestamp`: timestamp for the feature row.
- `feature_hash`: deterministic hash of model input features.

The strategy layer must not call model binaries directly. It may only consume this adapter output.

Class semantics:
- `UP_HORIZON` means the model predicts `Close[t + horizon] > Close[t]`.
- `NOT_UP_HORIZON` means the model predicts price is not higher after the horizon.
- These are not direct BUY/SELL classes.

ML behavior is mode-dependent. `RULE_ONLY` and `HYBRID_RESEARCH` must not block rule-derived signals because ML is unavailable or unverified. `HYBRID_VALIDATED` may use ML only after the validation gate in `docs/implementation/MODEL_INTEGRATION.md` is satisfied.

## Operating Modes

- `RULE_ONLY`: rules may generate `BUY`, `SELL`, or `NO_TRADE`; ML is optional metadata only and cannot block or create trades.
- `HYBRID_RESEARCH`: rule behavior is identical to `RULE_ONLY`; ML is logged when available, signals are marked research-only, and ML does not alter eligibility.
- `HYBRID_VALIDATED`: ML may filter, rank, or modify confidence only after approval; structural rules remain mandatory.

## Source Rules

These are implementation-safe source rules from the compact knowledge base.

- A short-term swing high has a higher high than the candle on both sides.
- A short-term swing low has a lower low than the candle on both sides.
- Wick-only breaks on 15m+ are not structure confirmation. They are liquidity events.
- Structure breaks on 15m+ require body close confirmation.
- A raw FVG is a three-candle wick-range inefficiency between candle 1 and candle 3.
- A raw FVG is known only after candle 3 closes.
- Time-based liquidity levels include prior day, week, month, and session highs/lows once session calendar rules are fixed. Implemented v1 levels are grouped by bar timestamp in a configured timezone and become knowable only at period close.
- A raw liquidity raid is price crossing a known liquidity level.
- A confirmed sweep requires a reaction such as return inside the range, body-close rejection, MSS, or displacement.
- HTF bias is context, not a direct entry trigger.
- FVG entries must be filtered by liquidity and structure, not taken from every raw FVG touch.

## Implementation Hypotheses

The following are not source rules. They are explicit v1 research hypotheses that must be backtested:

- Initial execution timeframe is 15m.
- HTF context uses closed 4H and Daily candles where enough data exists.
- Consequent encroachment, the FVG midpoint, is the default entry price.
- `PENDING_LIMIT_AFTER_FVG_CREATION` is the default execution model.
- Pending orders remain eligible for `8` closed bars by default.
- Structural close, stop-level breach, and full FVG close-through invalidation are enabled by default.
- Minimum acceptable risk-to-reward is `2.0`.
- Signal confidence threshold is `0.70`.
- Stop default is beyond the swept structural swing plus configured spread buffer.
- A structural stop distance below the configured minimum stop distance is rejected as `stop_unavailable`; this is a backtest-stability guard, not a source rule.
- TP1 is `1R`.
- TP2 is the nearest post-MSS opposing external liquidity already detected at activation, excluding the already-broken MSS swing.
- Market regime labels are annotations, not trade triggers.
- PO3, SMT, MMXM, Judas, session killzones, equal-high/equal-low tolerance, displacement strength, and CE entry refinement are research labels or filters until validated.

Every backtest report must identify which hypotheses were active.

## Deterministic Event Primitives

Implement these before setup logic:

- `swing_high`
- `swing_low`
- `time_liquidity_level`
- `liquidity_raid`
- `confirmed_sweep`
- `bos_body_close`
- `mss_body_close`
- `fvg_created`
- `fvg_midpoint`
- `fvg_fill_status`
- `ifvg_close_through`
- `htf_draw_selected`
- `market_regime_label`

Setup/order state values are:

- `SETUP_FORMING`
- `ENTRY_PENDING`
- `ENTRY_FILLED`
- `ENTRY_EXPIRED`
- `SETUP_INVALIDATED`
- `TRADE_OPEN`
- `TRADE_CLOSED`

Event timestamps must reflect when the event becomes knowable. For example, an FVG detected from candles 1, 2, and 3 is timestamped no earlier than candle 3 close.

## V1 Setup Templates

Only two setup templates are in scope for v1.

### SweepMssFvgRetraceLong

Required hard gates:

1. Data row is based on closed candles only.
2. HTF bias is `BULLISH`.
3. Sell-side liquidity was raided.
4. Sweep is confirmed.
5. Body-close MSS confirms bullish structure shift.
6. A new bullish FVG closes after the MSS and becomes causally known.
7. Entry price defaults to the FVG midpoint.
8. The activation bar is not required to retrace to the midpoint.
9. Stop-loss is below the swept structural swing plus spread buffer.
10. TP2 target is opposing buy-side external liquidity already detected at activation.
11. Risk-to-reward to TP2 is at least `2.0`.
12. Operating mode allows the signal: no ML gate in `RULE_ONLY` or `HYBRID_RESEARCH`; approved ML behavior only in `HYBRID_VALIDATED`.
13. Confidence is at least `0.70`.

Structural invalidation:
- Bullish setup is invalid if price closes below the swept low or the stop level before entry or before target according to the simulator rules.

### SweepMssFvgRetraceShort

Required hard gates:

1. Data row is based on closed candles only.
2. HTF bias is `BEARISH`.
3. Buy-side liquidity was raided.
4. Sweep is confirmed.
5. Body-close MSS confirms bearish structure shift.
6. A new bearish FVG closes after the MSS and becomes causally known.
7. Entry price defaults to the FVG midpoint.
8. The activation bar is not required to retrace to the midpoint.
9. Stop-loss is above the swept structural swing plus spread buffer.
10. TP2 target is opposing sell-side external liquidity already detected at activation.
11. Risk-to-reward to TP2 is at least `2.0`.
12. Operating mode allows the signal: no ML gate in `RULE_ONLY` or `HYBRID_RESEARCH`; approved ML behavior only in `HYBRID_VALIDATED`.
13. Confidence is at least `0.70`.

Structural invalidation:
- Bearish setup is invalid if price closes above the swept high or the stop level before entry or before target according to the simulator rules.

## Entry Lifecycle

The default lifecycle is `PENDING_LIMIT_AFTER_FVG_CREATION`:

1. The sweep confirmation timestamp is the raid candle close.
2. The MSS confirmation timestamp is the body-close break candle close.
3. The FVG creation timestamp is candle 3 close.
4. The pending order activates only when the FVG and every hard setup gate are known.
5. The activation bar cannot fill the order; the next closed bar is first eligible.
6. The order is eligible through `activation_index + max_entry_wait_bars`, inclusive.
7. If it remains untouched through that bar, it becomes `ENTRY_EXPIRED`.
8. If the dataset ends first, the outcome is `entry_not_reached`, preserving the distinction between expiration and right-censoring.
9. A filled order transitions through `ENTRY_FILLED`, `TRADE_OPEN`, and `TRADE_CLOSED`.

Before entry, default invalidation checks are conservative and evaluated before a possible fill on the same bar:

- stop-level wick breach,
- body close through the swept structural level,
- full FVG close-through: below the bullish FVG low or above the bearish FVG high.

When entry and invalidation are both possible in one bar and lower-timeframe ordering is unknown, invalidation wins. Overlapping pending orders and positions are not allowed by the current simulator.

Target selection is causal. `_target_for_long` and `_target_for_short` may only use a swing whose `detected_at` timestamp is at or before order activation. A geometrically earlier swing that had not yet received its right-candle confirmation is unavailable.

## ML Alignment

For long setups:
- Aligned ML direction is `UP_HORIZON`.

For short setups:
- Aligned ML direction is `NOT_UP_HORIZON`.

Because the legacy model does not predict trade direction directly, this mapping is a hypothesis and must be reported in validation output.

If the model is unavailable, unverified, missing `predict_proba()`, has ambiguous class order, has feature mismatch, or lacks a manifest, `RULE_ONLY` and `HYBRID_RESEARCH` must continue with ML marked unavailable or invalid. `HYBRID_VALIDATED` must reject with a specific ML rejection reason when its approved ML behavior cannot be applied.

## Rejection And Outcome Codes

Use stable rejection and order-outcome codes. Initial required codes:

- `insufficient_data`
- `open_candle`
- `htf_bias_neutral`
- `htf_bias_conflict`
- `no_liquidity_raid`
- `sweep_not_confirmed`
- `no_mss_body_close`
- `no_valid_fvg`
- `entry_filled`
- `entry_expired`
- `entry_not_reached`
- `setup_invalidated`
- `structural_break_before_entry`
- `stop_level_breached_before_entry`
- `fvg_close_through_before_entry`
- `stop_unavailable`
- `target_unavailable`
- `risk_reward_below_minimum`
- `confidence_below_threshold`
- `model_unavailable`
- `model_not_verified`
- `model_feature_mismatch`
- `model_class_mapping_ambiguous`
- `model_probability_unavailable`
- `model_direction_conflict`
- `outside_research_session`
- `news_filter_active`
- `paper_execution_only`

Do not invent free-text-only rejection reasons when a stable code applies.

## Confidence Model

Confidence is an implementation score, not a source claim.

Default v1 scoring:
- Start at `0.0`.
- Add `0.20` for HTF bias alignment.
- Add `0.20` for confirmed sweep.
- Add `0.20` for body-close MSS.
- Add `0.20` for a valid post-MSS FVG.
- Add `0.20` for acceptable risk-to-reward.
- Add weight for verified aligned ML only in `HYBRID_VALIDATED` when the approved ML behavior permits confidence modification.
- Cap at `1.0`.

The current fixed rule weights produce confidence `1.0` only after all hard rule gates pass. `NO_TRADE` confidence remains `0.0` unless a future documented research report changes this behavior.

## Backtest Rules

Backtests must be closed-bar and causal:

- Source CSVs must pass explicit timezone and structural data-quality validation before backtesting; corrupted rows must not be silently dropped, sorted, deduplicated, or repaired.
- No signal may use data from an unclosed current candle.
- HTF values must be joined only after the HTF candle has closed.
- FVGs must become available only after the third candle closes.
- A valid setup activates one pending midpoint limit after FVG creation; no pre-entry retracement is required.
- Entry evaluation begins on the next closed bar and ends after the configured maximum wait.
- Log `entry_filled`, `entry_expired`, `setup_invalidated`, and `entry_not_reached` separately.
- Pre-entry invalidation is checked before entry when both are possible in the same bar.
- If stop and target are both touched in the same bar, use the conservative stop-first assumption unless the simulator has lower-timeframe data proving order.
- Apply spread, slippage, and commission assumptions to all exits, including time exits, and include those assumptions in every report.
- Log all accepted signals and all `NO_TRADE` rejection reasons.
- Do not report fabricated Sharpe, win rate, or profitability values.

## Walk-Forward Validation Rules

Validation must be chronological:

- Training windows must precede validation windows.
- Hyperparameter choices must be made only within the training window.
- Feature preprocessing must be fitted only on training data.
- The final report must compare at least:
  - rule-only setup behavior,
  - ML-gated behavior,
  - basic baseline behavior where available.
- ML may gate production or paper signals only after after-cost out-of-sample lift is documented.
- `HYBRID_VALIDATED` requires positive after-cost out-of-sample expectancy, better expectancy than the paired `RULE_ONLY` baseline, at least 5 chronological OOS folds, and at least 100 closed OOS trades. Otherwise status remains `INSUFFICIENT_EVIDENCE`.

## Paper Trading Rules

Paper trading is file-backed simulation only:

- It may record candidate signals, simulated orders, fills, stops, targets, and ledger state.
- It must not call broker APIs.
- It must not place real orders.
- Any real-money order execution function must raise a hard error unless a future controlled-execution module is explicitly authorized.

## Documentation Synchronization

When implementation behavior differs from this file:

- update this specification,
- identify whether the change is a source rule or implementation hypothesis,
- update validation/backtest documentation,
- do not silently change strategy definitions in code.
