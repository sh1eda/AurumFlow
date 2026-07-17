# AurumFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](pyproject.toml)
[![Status: Research](https://img.shields.io/badge/Status-Research-lightgrey.svg)](ROADMAP.md)

AurumFlow is an explainable XAUUSD signal research toolkit. It combines deterministic market-structure rules, causal OHLCV data handling, simple backtesting, walk-forward validation scaffolding, and paper-signal logging for experimentation and education.

This project is not financial advice. It is intended for research, experimentation, and education. Backtests are not proof of future profitability, and any machine-learning component requires independent validation before it is used in decision-making.

## Key Features

- Deterministic `RULE_ONLY` signal evaluation for XAUUSD-style OHLCV data.
- Causal event detection for swings, fair value gaps, liquidity raids, market structure shifts, and time-based liquidity levels.
- Strict OHLCV data-quality checks with explicit source-timezone handling and UTC normalization.
- Structured CLI output for signal, backtest, diagnostics, validation, and paper-signal workflows.
- Explicit pending-limit lifecycle with next-bar-first fills, bounded expiration, and conservative pre-entry invalidation.
- LONG, SHORT, and combined rule-funnel diagnostics with survival percentages and ranked outcomes.
- R-multiple backtesting with spread, slippage, and commission inputs.
- Chronological walk-forward validation report for baseline research.
- Paper ledger that records generated signals as JSON Lines without placing real orders.
- Guarded model-adapter interface for optional ML research and validation.
- Tests covering data causality, event detection, operating modes, backtesting, validation gates, and paper-ledger behavior.

## Architecture

```text
OHLCV CSV
  -> xauusd_signal.data
  -> xauusd_signal.events
  -> xauusd_signal.strategy
  -> signal JSON
  -> backtest / validation / paper ledger
```

Core modules:

- `xauusd_signal.data`: CSV loading, canonical OHLCV normalization, resampling, and causal higher-timeframe joins.
- `xauusd_signal.data_quality`: schema, timestamp, OHLC, duplicate, gap, weekend, and volume diagnostics.
- `xauusd_signal.events`: deterministic market-event detectors.
- `xauusd_signal.strategy`: operating modes and rule-based signal generation.
- `xauusd_signal.backtest`: bounded pending-entry simulation and after-cost R-multiple reporting.
- `xauusd_signal.diagnostics`: directional rule-funnel and outcome reporting.
- `xauusd_signal.validation`: chronological walk-forward reports and hybrid-validation gates.
- `xauusd_signal.models`: manifest-based model adapter with explicit unavailable states.
- `xauusd_signal.paper`: append-only paper signal ledger and blocked real-order placeholder.
- `xauusd_signal.cli`: command-line interface.

## Project Goals

- Keep trading logic explicit, inspectable, and testable.
- Avoid look-ahead bias in data joins and event detection.
- Separate research outputs from validated operating behavior.
- Support reproducible experiments before any execution research.
- Make ML optional, gated, and auditable instead of implicit.

## Current Status

Version `0.1.0` is an initial research release.

Implemented today:

- Python package and CLI.
- `data-check`, `signal`, `backtest`, `diagnose`, `validate`, and `paper` commands.
- `RULE_ONLY`, `HYBRID_RESEARCH`, and `HYBRID_VALIDATED` mode enums.
- Deterministic rule signal generation.
- Baseline backtesting and walk-forward reporting.
- Paper signal recording.
- Model adapter safeguards for research code.
- A documented real-data quality, fixed-bias funnel, and backtest baseline using a
  local MT5 XAUUSD M15 export. The dataset remains excluded from git.

Not implemented today:

- Broker integration or live order execution.
- Automatic higher-timeframe bias selection in the CLI.
- A validated ML model shipped with the repository.
- CLI loading of external ML artifacts.
- Claims of future performance.

## Repository Structure

```text
.
├── xauusd_signal/          # Python package
├── tests/                  # Pytest suite
├── docs/
│   ├── README.md           # Documentation index
│   ├── implementation/     # Implementation notes and specifications
│   ├── knowledge/          # Research notes on market concepts
│   └── source_analysis/    # Source review and concept-mapping notes
├── .github/                # Issue and pull request templates
├── pyproject.toml          # Packaging and test configuration
├── Makefile                # Common developer commands
├── ROADMAP.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

Local datasets, generated reports, model artifacts, paper ledgers, and raw research-source files should stay out of git unless they are intentionally curated for release.

## Isolated Event Study

The research-only [XAUUSD 08:30–10:30 ET event-study framework](research/event_study_0830_0930/README.md) documents the source gate, objective concept definitions, synthetic framework tests, external data requirements, and the boundary for a future empirical study. It does not alter production strategy behavior or claim a trading edge.

## Quick Start

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m xauusd_signal signal --csv path/to/ohlcv.csv --htf-bias BULLISH --mode RULE_ONLY --bars 500
```

After installation, the same CLI is also available as:

```bash
aurumflow signal --csv path/to/ohlcv.csv --htf-bias BULLISH --mode RULE_ONLY --bars 500
```

Expected CSV columns:

```text
timestamp,open,high,low,close,volume
```

`volume` may be omitted or nullable because the current RULE_ONLY strategy does not use it. `date`, `datetime`, or MT5-style `date` plus `time` columns may be used instead of `timestamp`. Timezone-aware values are converted to UTC. Naive timestamps are rejected unless `--source-timezone` is supplied.

## Installation

Use Python 3.11 or newer.

```bash
git clone <repository-url>
cd AurumFlow
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest
```

## Data Import And Validation

Keep local market data under the ignored `data/local/` directory. AurumFlow does not include a market dataset in the repository.

Required schema:

```text
timestamp,open,high,low,close,volume
```

Place a broker or data-vendor export at `data/local/xauusd_15m.csv`, then inspect it before running diagnostics:

```bash
aurumflow data-check \
  --csv data/local/xauusd_15m.csv \
  --source "DATA_VENDOR_OR_BROKER" \
  --symbol "SOURCE_SYMBOL" \
  --broker "BROKER_OR_FEED" \
  --price-type unknown \
  --source-timezone America/New_York
```

Omit `--source-timezone` only when every timestamp already contains a timezone or UTC offset. The command rejects naive timestamps otherwise. DST-ambiguous or nonexistent local timestamps are also rejected rather than guessed.

To write a UTC-normalized copy after structural checks pass:

```bash
aurumflow data-check \
  --csv data/local/xauusd_15m.csv \
  --source-timezone America/New_York \
  --normalized-output data/local/xauusd_15m.utc.csv \
  --format json
```

The normalized output is explicit and never drops corrupted rows. Duplicate timestamps, unsorted rows, missing or invalid OHLC values, and non-positive prices block output. Frequency gaps, weekend rows, zero-range candles, and incomplete volume are reported for source review.

## Running Signals

```bash
aurumflow signal \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --bars 500
```

The command prints a JSON object with the decision, setup metadata, entry zone, stop, take-profit levels, confidence, valid reasons, rejection reasons, and explanation.

## Running Backtests

```bash
aurumflow backtest \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --bars 2000 \
  --spread-cost 0.10 \
  --slippage 0.05 \
  --commission-r 0.01
```

The backtester reports closed trades, expectancy, profit factor, maximum drawdown in R, and rejection counts. It is a research tool, not a complete execution simulator.

The default execution model is `PENDING_LIMIT_AFTER_FVG_CREATION`. A valid setup creates one pending limit at the FVG midpoint, which is an implementation hypothesis. The activation bar cannot fill the order. Evaluation begins on the next closed bar and remains eligible for eight bars by default. Before entry, stop-level breach, structural close, and full FVG close-through checks are enabled; ambiguous entry/invalidation bars resolve to invalidation.

Backtest output keeps `entry_filled`, `entry_expired`, `setup_invalidated`, and `entry_not_reached` separate. Pending controls can be changed with `--max-entry-wait-bars` and the `--[no-]invalidate-on-*` options.

## Rule Funnel Diagnostics

```bash
aurumflow diagnose \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --bars 5000
```

The default human-readable report shows separate LONG, SHORT, and combined counts for each rule and order stage, survival from the previous stage, survival from evaluated bars, and ranked rejection/outcome codes. Use `--format json` for machine-readable output.

Use inclusive `--start` and exclusive `--end` UTC boundaries for reproducible yearly or sub-period diagnostics.

## Walk Forward Validation

```bash
aurumflow validate \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --bars 5000 \
  --folds 5
```

The validation command creates chronological folds and reports out-of-sample baseline metrics. The current CLI does not approve an ML model or enable live hybrid behavior.

## Paper Trading

```bash
aurumflow paper \
  --csv path/to/ohlcv.csv \
  --mode RULE_ONLY \
  --htf-bias BULLISH \
  --ledger state/paper-ledger.jsonl
```

Paper mode records the generated signal to a local JSON Lines ledger. It does not place orders. Real-money execution is intentionally blocked in the current codebase.

## Operating Modes

### RULE_ONLY

`RULE_ONLY` uses deterministic market-structure rules only. It does not require a model artifact and is the default mode.

### HYBRID_RESEARCH

`HYBRID_RESEARCH` is for studying ML predictions alongside deterministic rules. In the Python API, an injected model prediction can be recorded on the signal, but it does not block a rule signal. In the CLI, no external ML model is loaded, so the ML state remains unavailable.

### HYBRID_VALIDATED

`HYBRID_VALIDATED` is a guarded mode intended for a separately validated ML gate. In the current CLI path, it is not enabled with a verified model and will reject signals with `model_not_verified`. This is deliberate until validation evidence exists.

## Project Philosophy

### Explainability

Signals include structured reasons, rejection reasons, setup names, invalidation text, and model state. A contributor should be able to trace why a trade was accepted or rejected.

### No Look-Ahead Bias

Market events are detected only after the required candles have closed. Higher-timeframe joins use closed candles only. Swing targets must be detected by order activation, and pending orders cannot fill on their activation bar. New contributions must preserve that causal boundary.

### Research First

This repository is for research and education. Backtests, walk-forward reports, and paper ledgers are evidence-gathering tools, not proof of future returns.

### Deterministic Rules

Rule behavior should be reproducible for the same input data and configuration. Any randomness introduced for research must use explicit seeds and must not affect default signal behavior.

### Optional ML Validation

ML is optional and must be validated before it can influence accepted signals. Model artifacts require clear manifests, feature ordering, class semantics, calibration status, and out-of-sample evidence.

## Known Limitations

- The CLI requires the user to provide higher-timeframe bias manually.
- Backtesting is simplified, allows only one pending order or open position at a time, and does not model every execution detail.
- Data quality, broker feeds, spread behavior, and session definitions can materially affect research results.
- No real XAUUSD dataset is shipped. The documented baseline used a local MT5
  export with unknown broker, quote type, and broker-verified costs; see the
  [data-quality report](docs/implementation/DATA_QUALITY_REPORT.md),
  [funnel report](docs/implementation/REAL_DATA_FUNNEL_REPORT.md), and
  [backtest baseline](docs/implementation/REAL_DATA_BACKTEST_BASELINE.md).
- The repository does not ship a validated model artifact.
- Paper mode logs signals only and does not simulate full broker state.
- Live execution research is not implemented.
- No result in this repository should be interpreted as a guarantee of future performance.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned research stages. The roadmap is intentionally undated and should not be treated as a delivery commitment.

## Contributing

Contributions are welcome when they preserve the research-first scope of the project. Start with [CONTRIBUTING.md](CONTRIBUTING.md), especially the sections on tests, deterministic behavior, documentation, and no look-ahead policy.

## License

AurumFlow is released under the [MIT License](LICENSE).
