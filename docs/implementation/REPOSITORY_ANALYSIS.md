# Repository Analysis

## Scope And Source Order

This analysis supports the first implementation phase for the XAUUSD explainable signal system. It uses the authority order in `docs/implementation/IMPLEMENTATION_PLAN.md`, `docs/source_analysis/CODEX_CONTEXT_GUIDE.md`, and `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`.

No raw PDFs were read for this document. The compact knowledge files are sufficient for the v1 implementation boundary.

## Current Checkout State

- The visible working tree contains the documentation set, the intraday CSV files, `README.md`, `X_features.csv`, and paper/whitepaper artifacts.
- The Git index is in an unusual state: many files from `HEAD` are shown as deleted while same-named files are present as untracked. Do not run destructive cleanup commands or restore files without an explicit request.
- Re-inspection after the requested LFS check still shows no physical root `*.py`, `*.pkl`, or `*.joblib` files in the visible checkout.
- `git lfs ls-files` lists LFS objects for the model files, but `git lfs status` reports the model paths as deleted and `.git/lfs` is absent. The actual model binaries are therefore still unavailable in this checkout.
- Legacy Python scripts and model files are not present as normal working-tree files, but they exist in `HEAD`:
  - `fetch_data.py`
  - `train_multi_timeframe.py`
  - `backtest_multi_timeframe.py`
  - `multi_timeframe_summary.py`
  - `trading_model_1m.pkl`
  - `trading_model_15m.pkl`
  - `trading_model_30m.pkl`
  - `trading_model_fixed.pkl`
- The `.pkl` files in `HEAD` are Git LFS pointer files, not directly loadable model binaries in the current checkout. For example, `trading_model_15m.pkl` points to a 530946-byte LFS object with SHA-256 `7724dd5a03197f263a1d33391107b25193cfb43497329a452c6840fddf2a5293`.

Implementation implication: new code must not depend on the legacy files being present in the working tree. If existing models are used later, they must be pulled through LFS and loaded only through a manifest-backed adapter.

## Repository Architecture

The repository currently has three main layers:

- Documentation and source triage:
  - `docs/source_analysis/`
  - `docs/knowledge/`
  - `docs/raw_sources/`
- Published model/research artifacts:
  - `README.md`
  - `XAUUSD_Trading_AI_Paper.md`
  - `XAUUSD_Trading_AI_Technical_Whitepaper.md`
  - generated `.html`, `.docx`, and `.tex` variants
- Data and legacy ML artifacts:
  - current visible CSVs: `1m_data.csv`, `15m_data.csv`, `30m_data.csv`, `X_features.csv`
  - legacy `HEAD` CSVs: `daily_data.csv`, `processed_daily_data.csv`, `smc_features_dataset.csv`, `y_target.csv`, feature-importance CSVs, and backtest reports
  - legacy `HEAD` scripts listed above

There is no current package structure, no `pyproject.toml`, and no checked-in test suite.

## Data Sources And Schemas

### Intraday CSVs

Files:
- `1m_data.csv`
- `15m_data.csv`
- `30m_data.csv`

Observed source: Yahoo Finance `GC=F`, used as a gold futures proxy for XAUUSD.

Observed format:
- First row contains field names under a Yahoo Finance multi-index export: `Price,Close,High,Low,Open,Volume`.
- Second row contains ticker labels: `Ticker,GC=F,GC=F,GC=F,GC=F,GC=F`.
- Third row contains `Datetime,,,,,`.
- Data rows are UTC timestamped.

Observed coverage from visible files:
- `1m_data.csv`: 5207 lines, recent snapshot.
- `15m_data.csv`: 3817 lines, from 2025-07-21 to 2025-09-18 in the visible sample.
- `30m_data.csv`: 1913 lines, from 2025-07-21 to 2025-09-18 in the visible sample.

Implementation implication: intraday data is too short for robust conclusions. It can support parser tests and pipeline smoke tests, but not profitability claims.

### Daily Feature Files

Visible file:
- `X_features.csv`

Legacy `HEAD` files:
- `daily_data.csv`
- `processed_daily_data.csv`
- `smc_features_dataset.csv`
- `y_target.csv`

Observed `X_features.csv` columns:
`Date`, `Close`, `High`, `Low`, `Open`, `Volume`, `SMA_20`, `SMA_50`, `EMA_12`, `EMA_26`, `RSI`, `MACD`, `MACD_signal`, `MACD_hist`, `BB_upper`, `BB_middle`, `BB_lower`, `FVG_Size`, `FVG_Type_Encoded`, `OB_Type_Encoded`, `Recovery_Type_Encoded`, `Close_lag1`, `Close_lag2`, `Close_lag3`.

Observed target semantics from legacy scripts and docs:
- Target is binary.
- `1` means `Close[t + 5] > Close[t]`.
- `0` means price is not higher after the horizon.
- These are not BUY and SELL labels.

## Legacy Model Architecture

### Model Type

Legacy scripts train `xgboost.XGBClassifier` models via scikit-learn APIs and save them with `joblib.dump`.

### Model Library

Required libraries in legacy scripts:
- `xgboost`
- `scikit-learn`
- `pandas`
- `numpy`
- `joblib`

The current checkout does not include dependency metadata, so reproducibility is incomplete.

### Expected Feature Names And Order

The intraday training script uses 21 features in this exact order:

1. `Close`
2. `High`
3. `Low`
4. `Open`
5. `SMA_20`
6. `SMA_50`
7. `EMA_12`
8. `EMA_26`
9. `RSI`
10. `MACD`
11. `MACD_signal`
12. `MACD_hist`
13. `BB_upper`
14. `BB_middle`
15. `BB_lower`
16. `FVG_Size`
17. `FVG_Type`
18. `OB_Type`
19. `Close_lag1`
20. `Close_lag2`
21. `Close_lag3`

The daily `X_features.csv` has 23 model input columns after `Date`, including `Volume`, encoded SMC fields, and `Recovery_Type_Encoded`. The README says the daily model expects 23 features:

1. `Close`
2. `High`
3. `Low`
4. `Open`
5. `Volume`
6. `SMA_20`
7. `SMA_50`
8. `EMA_12`
9. `EMA_26`
10. `RSI`
11. `MACD`
12. `MACD_signal`
13. `MACD_hist`
14. `BB_upper`
15. `BB_middle`
16. `BB_lower`
17. `FVG_Size`
18. `FVG_Type_Encoded`
19. `OB_Type_Encoded`
20. `Recovery_Type_Encoded`
21. `Close_lag1`
22. `Close_lag2`
23. `Close_lag3`

Implementation implication: feature contracts differ between daily and intraday models. Every model must have a manifest that fixes feature names, order, target horizon, class semantics, preprocessing, and training window.

### Class Labels And Semantics

Verified semantics:
- `1`: price higher after the prediction horizon.
- `0`: price not higher after the prediction horizon.

Not verified:
- Whether any loaded LFS model preserves scikit-learn `classes_` as `[0, 1]`.
- Whether class order in `predict_proba()` is stable for every saved artifact.

Implementation implication: the adapter must check `classes_` when available and must reject ambiguous class order.

### Prediction Target And Horizon

Legacy intraday target:
- `prediction_horizon = 5`
- `Target = Close.shift(-5) > Close`
- Horizon unit equals the source timeframe, so 5 bars.

Legacy daily target:
- Documentation and `y_target.csv` describe a 5-day ahead binary target.

Implementation implication: the existing model predicts directional tendency over a fixed horizon. It does not output entry, stop, target, or trade validity.

### Training Timeframe And Dataset

Legacy scripts train separate intraday models for `1m`, `15m`, and `30m` CSVs.

Published documentation also describes a daily model trained on Yahoo Finance `GC=F` data from 2000-2020. That daily model file is not visible in the current checkout as a loadable model.

### Training Period

Verified from visible files:
- Intraday CSV snapshots are recent and short, ending in September 2025 in the visible sample.
- Daily feature file runs through 2020-12-30.

Claimed in docs:
- Daily data spans 2000-2020.

### Inference Method

Legacy intraday backtest uses:
- `model.predict_proba(features)[0][1]` as the probability of upward movement.
- Long if probability is above `0.6`.
- Short if probability is below `0.4`.

This inference is not an SMC setup engine. It is a probability threshold rule without structural stop, target, or invalidation.

### `predict()` Behavior

For `XGBClassifier`, `predict()` normally returns a class label (`0` or `1`). This has not been verified against the absent LFS binaries.

### `predict_proba()` Availability

Legacy scripts require `predict_proba()`. Availability must be checked at adapter load time.

### Probability Calibration

No calibration method is present in the legacy scripts or artifacts. Treat probabilities as uncalibrated until validated.

### Feature Preprocessing

Legacy intraday script:
- Computes rolling/EMA indicators on raw OHLC data.
- Drops NaN rows.
- Fills NaN values with `0.0` in backtest inference.
- Does not scale features.

Daily docs mention standardized `X_features.csv`, but the scaler object is not present. README explicitly says scalers need to be recreated or saved.

Implementation implication: a new adapter must not silently recreate unknown preprocessing. It should require manifest-declared preprocessing and reject missing scaler state for models that require scaling.

### Missing-Value Behavior

Legacy training drops NaN rows.

Legacy backtest replaces NaN feature values with zero. That creates a training/inference mismatch and can produce invalid predictions around indicator warmup periods.

Implementation implication: new inference should reject incomplete feature rows or use a manifest-declared imputation rule. Zero-filling should not be the default.

## Known Bugs And Risks

### Look-Ahead And Future Leakage

- The intraday `detect_fvg()` uses `next_high = df['High'].iloc[i+1]` while assigning the FVG to index `i`. A live system cannot know candle `i+1` while making a decision at candle `i`.
- The FVG implementation does not match the curated v1 rule requiring a three-candle FVG known only after candle 3 closes.
- Daily `smc_features_dataset.csv` includes `Future_Close`; that column must never be available to feature generation.
- Legacy random train/test splitting mixes time periods and can leak regime information.
- Grid search uses standard `cv=3`, not a chronological time-series split.
- The legacy backtest appears to trade on the same datasets used for training/optimization, with no reliable walk-forward separation.

### Feature Pipeline Risks

- Intraday feature count and daily feature count differ.
- Intraday SMC fields are placeholders: `OB_Type` is always `0`; backtest sets FVG and OB features to zero.
- Published feature importance for intraday models gives zero importance to `FVG_Size`, `FVG_Type`, and `OB_Type`.
- The README and papers claim stronger SMC contribution than the visible intraday artifacts support.

### Backtesting Risks

- Legacy backtest has no structural entries, stops, take-profits, or invalidation.
- It uses fixed stake sizing and closes/reverses by probability thresholds.
- It lacks realistic spread/slippage modeling for gold beyond a generic commission parameter.
- The saved intraday backtest report has only one trade for 15m and one trade for 30m. It is not statistically meaningful.
- Analyzer output has inconsistencies: the one-trade reports show zero winning and zero losing trades.

### Live-Inference Risks

- Existing model files are not loadable from the visible checkout.
- Feature order is not guaranteed unless enforced by a manifest.
- Higher-timeframe feature construction is not implemented and could leak incomplete candles if added naively.
- Session logic requires New York timezone and daylight-saving handling.
- Yahoo `GC=F` futures are not identical to broker XAUUSD spot/CFD pricing.
- No macro-news filter exists.

## Existing Model Verification Status

The existing ML models are untrusted.

Verified:
- Legacy intended model type: XGBoost classifier.
- Legacy target: `Close[t+horizon] > Close[t]`.
- Intraday expected feature order from `train_multi_timeframe.py`.
- Intraday `predict_proba()` thresholding from `backtest_multi_timeframe.py`.
- Current `.pkl` artifacts are LFS pointers in `HEAD`, not visible loadable binaries.

Unverified:
- Actual loaded model object type for each LFS artifact.
- Actual `classes_`.
- Actual feature names stored on the model.
- Actual hyperparameters in each saved model.
- Actual training window for each model artifact.
- Probability calibration.
- Out-of-sample profitability.

Required before any model can affect `HYBRID_VALIDATED` signals:
- Load through a manifest-backed adapter.
- Verify object type, class order, feature order, preprocessing, target horizon, and prediction behavior.
- Reproduce feature generation causally.
- Run chronological walk-forward validation with costs.
- Show measurable after-cost out-of-sample expectancy improvement versus `RULE_ONLY` and satisfy the evidence gate in `docs/implementation/MODEL_INTEGRATION.md`.

## Recommended System Architecture

Implement a new package rather than extending legacy scripts directly:

- `data`: Yahoo-style CSV loaders, canonical OHLCV schema, timezone conversion, closed-candle resampling, causal HTF joins.
- `features`: deterministic technical features and source-grounded SMC primitives.
- `strategy`: signal assembly from hard-gated setup templates.
- `models`: manifest-backed model adapter and verification helpers.
- `backtest`: closed-bar simulator with conservative fills, costs, signal logs, and rejection logs.
- `validation`: chronological walk-forward split generation and reports.
- `paper`: file-backed paper ledger with no broker execution.
- `cli`: commands for analysis, signal generation, backtest, validation, and paper replay.

The rest of the application must consume `ModelPrediction` and the strategy signal schema. It must not call `joblib.load()` or model methods directly outside the adapter.

## Implementation Defaults

- Use offline CSVs first.
- Use 15m as the initial execution timeframe.
- Use resampled 4H/Daily context only from closed candles.
- Treat ML as unavailable or unverified until validation passes.
- Do not let missing or unverified ML block `RULE_ONLY` or `HYBRID_RESEARCH`.
- Return `NO_TRADE` when a required rule setup component or risk condition is missing; apply ML rejection only in `HYBRID_VALIDATED`.
- Do not enable live order execution.
