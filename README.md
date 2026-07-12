# AurumFlow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](pyproject.toml)
[![Status: Research](https://img.shields.io/badge/Status-Research-lightgrey.svg)](ROADMAP.md)

AurumFlow is an explainable XAUUSD signal research toolkit. It combines deterministic market-structure rules, causal OHLCV data handling, simple backtesting, walk-forward validation scaffolding, and paper-signal logging for experimentation and education.

This project is not financial advice. It is intended for research, experimentation, and education. Backtests are not proof of future profitability, and any machine-learning component requires independent validation before it is used in decision-making.

## Key Features

- Deterministic `RULE_ONLY` signal evaluation for XAUUSD-style OHLCV data.
- Causal event detection for swings, fair value gaps, liquidity raids, market structure shifts, and time-based liquidity levels.
- JSON CLI output for signal, backtest, validation, and paper-signal workflows.
- Simple R-multiple backtesting with spread, slippage, and commission inputs.
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
- `xauusd_signal.events`: deterministic market-event detectors.
- `xauusd_signal.strategy`: operating modes and rule-based signal generation.
- `xauusd_signal.backtest`: next-bar entry simulation and after-cost R-multiple reporting.
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
- `signal`, `backtest`, `validate`, and `paper` commands.
- `RULE_ONLY`, `HYBRID_RESEARCH`, and `HYBRID_VALIDATED` mode enums.
- Deterministic rule signal generation.
- Baseline backtesting and walk-forward reporting.
- Paper signal recording.
- Model adapter safeguards for research code.

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

`date` or `datetime` may be used instead of `timestamp`; the loader normalizes it internally. Timestamps are parsed as UTC.

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

Market events are detected only after the required candles have closed. Higher-timeframe joins use closed candles only. New contributions must preserve that causal boundary.

### Research First

This repository is for research and education. Backtests, walk-forward reports, and paper ledgers are evidence-gathering tools, not proof of future returns.

### Deterministic Rules

Rule behavior should be reproducible for the same input data and configuration. Any randomness introduced for research must use explicit seeds and must not affect default signal behavior.

### Optional ML Validation

ML is optional and must be validated before it can influence accepted signals. Model artifacts require clear manifests, feature ordering, class semantics, calibration status, and out-of-sample evidence.

## Known Limitations

- The CLI requires the user to provide higher-timeframe bias manually.
- Backtesting is simplified and does not model every execution detail.
- Data quality, broker feeds, spread behavior, and session definitions can materially affect research results.
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
