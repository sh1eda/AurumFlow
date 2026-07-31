# Isolated XAUUSD 08:30–10:30 ET Event Study

This directory is a research sandbox. It is excluded from the distributable packages in `pyproject.toml` and does not import or modify `xauusd_signal`, production defaults, production entry logic or production risk settings.

The mandatory source gate is documented in:

- `source_register.csv`
- `literature_review.md`
- `concept_definitions.md`
- `nasdaq_to_xauusd_transfer_matrix.csv`
- `hypothesis_register.md`
- `research_limitations.md`
- `research_gate_assessment.md`

All tests in this directory use synthetic fixtures only. They verify framework mechanics, adapters, validation, causal timing and output contracts; they are not empirical validation of an XAUUSD trading edge.

## Environment setup

Use Python 3.11 or newer and install the repository with its declared development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the standard repository suite, including the isolated research tests:

```bash
python -m pytest
```

Run only the synthetic event-study tests:

```bash
python -m pytest research/event_study_0830_0930/tests
```

Regenerate the two curated research registers using only the Python standard library:

```bash
python research/event_study_0830_0930/tools/build_research_registers.py
```

## Empirical-data integration

The bid/ask ingestion and Stage 1 pipeline is documented in:

- [data schema](data_schema.md)
- [external data setup](external_data_setup.md)
- [empirical runbook](empirical_runbook.md)
- [sample configuration](sample_config.yaml)
- [current blocked quality report](data_quality_report.md)

Source adapters support MT5, Dukascopy, generic CSV, explicitly mapped broker CSV and Parquet. Tick inputs are aggregated into independent bid and ask one-minute bars without forward filling. Economic releases are normalized, point-in-time eligibility is recorded, and simultaneous releases are clustered before attribution.

The executable empirical commands live in `empirical_cli.py`. Stage 1 refuses critical quality failures and measures timing, volatility and spread only; it does not test entry geometry.

## Input contract

The legacy research-core price CSV contract is:

- `timestamp` (or `datetime`, `time`, `date_time`)
- `open`, `high`, `low`, `close`
- optional `spread` in price units
- one-minute or finer observations; coarser bars are rejected and never upsampled
- timestamps must be timezone-aware, or `--source-timezone` must specify an IANA zone

Calendar CSV:

- `release_timestamp`, `event_name`, `importance`
- `importance` is exactly `major`, `minor` or `none`
- strongly recommended: `category`, `actual`, `consensus`, `previous`, `revision`, `surprise`, `units`, `source_url`, `vintage_retrieved_at`
- the calendar must be point-in-time; a currently displayed official schedule is not a substitute for historical surprise vintages

All analysis converts timestamps to IANA `America/New_York`. No fixed UTC offset is used. London primary ranges use `Europe/London` local 08:00–12:00, so the U.S./U.K. DST mismatch is handled automatically.

New empirical runs must first use the canonical bid/ask schemas in `data_schema.md`; single-price bars remain suitable only for synthetic framework tests, not executable empirical inference.

## Run

```bash
python -m research.event_study_0830_0930.cli \
  --prices /path/to/xauusd_1m_bidask.csv \
  --calendar /path/to/us_releases_point_in_time.csv \
  --output /path/to/isolated_output \
  --source-timezone UTC
```

Add `--run-strategies` only after inspecting the data-quality and unconditional event-study outputs. Strategy families A/B/C remain separate. The default cost scenarios are labeled assumptions in price units and should be replaced or supplemented with broker-observed bid/ask data.

## Outputs

- `session_features.csv`: registered windows, ranges, normalization, path variables and retrospective lifecycle states
- `heatmap_5m.csv`: class/10:00-overlay movement data
- `event_test_panel.csv` and `hypothesis_test_results.csv`: preregistered 08:30, adjusted 09:30, 10:00 and re-entry contrasts with session bootstrap intervals and small-sample warnings
- `heatmap_absolute_movement.svg` and `heatmap_directional_movement.svg`
- `data_quality_report.md` and `run_metadata.json`
- optional `candidate_orders.csv` and `trade_outcomes.csv`
- optional `strategy_performance.csv`: sample, frequency, fill/win rate, R, PF, costs, drawdown, MFE/MAE, expiration and stability slices
- optional `bootstrap_confidence_intervals.csv`: session-clustered intervals by family
- `event_study_report.md`: result index and production-decision boundary

## Causal boundary

Lifecycle states are assigned after 10:30 and are never read by the trigger/order generator. Pivots become eligible only after right-hand confirmation bars close. FVG entries become eligible only after candle three closes. When stop and target are both touched in one OHLC bar, the simulator assigns the stop first. A bar touch does not prove an executable fill during an announcement; tick replay is preferable.

The registered higher-timeframe proxy is the sign of the return from the prior fourth daily close to the prior daily close. It uses no current New York-session information and is a research conditioning variable, not discretionary “bias.”

For OHLC execution, the primary OTE-zone proxy is the first touch of the proximal 62% boundary of the registered 62%–79% band; it is intentionally identical to the standalone 62% entry when there is no inter-bar gap. A separate 70.5% sensitivity is emitted. Tick replay is required to resolve a gap directly into the interior of the zone.

## Current local data qualification

The original M15 file remains intentionally rejected for this event study. A separate local MT5 tick export, `data/local/XAUUSD_202507171300_202607171409.csv`, has now passed the structural normalization gate through the isolated streaming workflow in `tick_qualification.py`. The raw export and its normalized derivatives remain ignored and are not distributable repository assets.

Qualification outputs are:

- `tick_inspection.md`
- `tick_validation_report.md`
- `tick_metadata.json`
- ignored canonical ticks under `external_data/normalized/`
- ignored one-minute bid/ask bars under `external_data/normalized/`

The data verdict is `WARNING`, not `READY`: the file contains no timezone marker, and the `Europe/Helsinki` broker-server mapping remains an inference pending broker confirmation. Extreme and zero-spread states also require explicit cost sensitivity. The empirical study was **not** run; a point-in-time historical U.S. release calendar is still missing.

Re-run qualification in three explicit phases:

```bash
python -m research.event_study_0830_0930.tick_qualification validate \
  --input data/local/XAUUSD_202507171300_202607171409.csv \
  --output-dir research/event_study_0830_0930 \
  --source-timezone Europe/Helsinki \
  --timezone-status assumed

python -m research.event_study_0830_0930.tick_qualification normalize \
  --input data/local/XAUUSD_202507171300_202607171409.csv \
  --output-dir research/event_study_0830_0930 \
  --normalized-dir research/event_study_0830_0930/external_data/normalized \
  --source-timezone Europe/Helsinki

python -m research.event_study_0830_0930.tick_qualification verify \
  --output-dir research/event_study_0830_0930
```

## Required external datasets and next phase

The next empirical phase requires datasets that are intentionally not distributed with this repository:

- timezone-aware XAUUSD or COMEX gold observations at one-minute resolution or finer, with continuous coverage across the registered 07:30–10:30 ET windows;
- preferably tick-level bid/ask quotes and trades for announcement-time spread, slippage, fill-order and MFE/MAE analysis;
- a point-in-time historical U.S. release calendar containing release timestamps, categories, importance, actuals, consensus values, revisions and vintages; and
- optional causal, timestamp-aligned U.S. dollar, Treasury/real-yield and equity-risk series for cross-asset controls.

After provenance and licensing checks, the next phase is to run the unconditional event study first, audit missing sessions and event classifications, then evaluate strategy families A, B and C separately. Production research should be considered only if results remain stable across years, directions and event categories after costs and bootstrap uncertainty.
