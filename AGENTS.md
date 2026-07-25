# XAUUSD Trading AI Engineering Rules

## Project objective

Build and validate an XAUUSD trading system without introducing
unverified production behaviour.

## Non-negotiable rules

1. Never modify production strategy defaults unless the task explicitly permits it.
2. Never use future data, target leakage or look-ahead information.
3. Never overwrite canonical datasets.
4. Never modify raw market data.
5. Every behavioral change must include tests.
6. Existing tests must continue to pass.
7. Research findings must not automatically become production defaults.
8. Do not commit secrets, credentials, account numbers or broker tokens.
9. Do not execute live trading or broker operations.
10. Do not merge or push directly to main.

## Required validation

Run the commands defined in automation/config.yaml.

## Completion requirements

Every completed task must report:

- Files changed
- Tests added
- Tests executed
- Test results
- Assumptions
- Risks
- Acceptance criteria status
- Recommended next action