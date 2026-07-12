# Contributing to AurumFlow

Thanks for helping improve AurumFlow. The project is research software for explainable trading-system experimentation, so contributions should favor clarity, reproducibility, and careful validation over novelty.

## Scope

Good contributions include:

- Documentation improvements.
- Tests that make existing behavior clearer.
- Bug fixes that preserve intended strategy behavior.
- Developer-experience improvements.
- Research tooling that stays separate from default strategy behavior.

Avoid contributions that:

- Claim guaranteed performance or future profitability.
- Add opaque trading logic without tests and explanation.
- Change strategy behavior without a clear issue, rationale, and regression coverage.
- Add broker execution paths without explicit safety review.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

## Coding Standards

- Keep code small, explicit, and easy to inspect.
- Prefer deterministic functions over hidden state.
- Use type hints for public functions and dataclasses where they clarify contracts.
- Keep strategy decisions explainable through valid reasons, rejection reasons, and structured outputs.
- Do not introduce unnecessary abstractions around trading rules.
- Do not commit secrets, local configuration, raw broker exports, large datasets, or model artifacts.

## Testing Requirements

Run the full test suite before opening a pull request:

```bash
python -m pytest
```

Add focused tests when you change:

- Data loading or resampling.
- Event detection.
- Strategy acceptance or rejection behavior.
- Backtest accounting.
- Validation gates.
- Paper-ledger behavior.
- Model-adapter safeguards.

Tests should use small synthetic datasets when possible. Large market datasets should not be required for CI or basic local validation.

## No Look-Ahead Policy

No contribution may use information before it would have been known in time.

Required expectations:

- Swings are known only after the confirming candle closes.
- Fair value gaps are known only after the third candle closes.
- Higher-timeframe data joins must use already closed higher-timeframe candles.
- Backtests may not enter on information from the same candle that generated a signal unless explicitly modeled and tested.
- Any ML features must be timestamped and must use only data available at the feature timestamp.

When changing time alignment, add tests that prove causality.

## Deterministic Behavior Requirements

For the same input CSV and configuration, default outputs should be reproducible. If a research tool needs randomness, expose a seed and keep it out of default signal behavior.

## Documentation Expectations

Update documentation when behavior, commands, configuration, or limitations change. Documentation should be conservative:

- Do not describe planned work as implemented.
- Do not include performance claims without reproducible evidence and clear caveats.
- State research limitations plainly.
- Keep examples runnable with the current CLI.

## Pull Request Workflow

1. Open or reference an issue for behavior changes.
2. Keep the pull request focused on one topic.
3. Include tests or explain why tests are not applicable.
4. Update documentation for user-facing changes.
5. Confirm that `python -m pytest` passes.
6. Fill out the pull request template.

## Commit Style

Use short, imperative commit messages:

```text
Add walk-forward validation docs
Fix causal HTF join test
Tighten paper ledger README
```

Prefer a clear subject line over rigid commit prefixes. If a commit changes strategy behavior, mention that explicitly in the body and link the issue.
