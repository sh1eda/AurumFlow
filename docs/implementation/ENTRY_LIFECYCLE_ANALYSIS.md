# Entry Lifecycle Analysis

## Scope

This review covers the boundary between rule setup detection and simulated order execution. It does not add setup concepts, alter ML behavior, add live execution, or introduce account-level risk controls.

## Legacy Behavior Confirmed

The pre-correction implementation had no explicit pending-order lifecycle:

1. `evaluate_signal()` selected the latest directional FVG after the MSS.
2. It returned `NO_TRADE` unless the latest closed bar overlapped that FVG zone.
3. A valid signal used the FVG midpoint as its entry price.
4. `run_backtest()` began entry evaluation at the next bar.
5. It searched every remaining bar until the midpoint was touched.

This created a semantic contradiction. A setup could become a signal only after a retracement bar had already reached the FVG, but that bar could not fill the order. The simulator therefore required a later touch. The search also had no expiration or pre-entry invalidation boundary.

The pre-correction baseline run of the deterministic fixture in `tests/test_entry_lifecycle.py` confirmed the sequence:

- FVG created at index `7`.
- The opposing target swing was detected only at index `8`.
- The index `8` bar overlapped the FVG and created the legacy signal.
- Entry evaluation started at index `9`.
- The trade filled only because index `9` touched the midpoint again.

The same fixture also exposed a target-causality defect: the selected target did not exist as a confirmed swing when the FVG became known.

## Corrected Semantic Model

The implementation target is `PENDING_LIMIT_AFTER_FVG_CREATION`:

1. A confirmed directional sweep is known.
2. A directional body-close MSS is known.
3. A valid post-MSS FVG closes and becomes known.
4. All structural stop, causal target, R:R, operating-mode, and confidence gates pass.
5. A pending limit order is activated at the configured FVG entry level.
6. The first eligible fill is the next closed bar.
7. The order fills, expires after a bounded wait, or is invalidated before entry.
8. A filled trade closes by stop, target, or the existing time-exit rule.

The FVG midpoint remains the initial entry-level implementation hypothesis. The correction changes when an order exists and how long it remains eligible; it does not introduce a new setup or relax the structural rule gates.

## Causality Requirements

- No order exists before every setup input is known.
- The FVG is usable only after candle 3 closes.
- A swing target is usable only when `swing.detected_at` is at or before order activation.
- The activation bar cannot fill its own order.
- If entry and invalidation occur in the same later bar without lower-timeframe sequencing, invalidation wins.
- A pending order has a finite configured lifetime.

Detailed defaults and final state transitions are maintained in `STRATEGY_SPEC.md` after implementation.

## Implemented State Transitions

| Terminal path | State history |
| --- | --- |
| Filled trade | `SETUP_FORMING -> ENTRY_PENDING -> ENTRY_FILLED -> TRADE_OPEN -> TRADE_CLOSED` |
| Expired order | `SETUP_FORMING -> ENTRY_PENDING -> ENTRY_EXPIRED` |
| Invalidated setup | `SETUP_FORMING -> ENTRY_PENDING -> SETUP_INVALIDATED` |
| Dataset ends before expiry | Remains `ENTRY_PENDING` with outcome `entry_not_reached` |

The signal lifecycle records sweep, MSS, FVG, activation, first eligible fill, and planned expiration indices/timestamps. Final order records add invalidation or entry indices; filled trades add exit indices and timestamps.

## Implemented Defaults

- Execution model: `PENDING_LIMIT_AFTER_FVG_CREATION`.
- Entry model: `FVG_MIDPOINT`.
- Maximum wait: `8` closed bars after activation.
- Structural close invalidation: enabled.
- Stop-level wick breach invalidation: enabled.
- Full FVG close-through invalidation: enabled.
- Expiration bar: remains eligible; it expires after that bar closes without a fill or invalidation.
- Overlap: one pending order or open position at a time.

The legacy fixture now verifies that a late-confirmed target cannot retroactively activate its older FVG. The causal fixture verifies activation at FVG confirmation, first fill on the next bar, all terminal order outcomes, conservative same-bar handling, and repeated-run determinism.
