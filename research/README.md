# Research Objects

This directory owns isolated research objects. It is separate from the
`xauusd_signal` package and must not change production behavior.

Each object directory contains an `object.toml` lifecycle manifest and a place
for future experiment modules. The framework discovers manifests recursively;
adding an object or experiment does not require a core-framework edit.

The current catalog directories are placeholders only. They contain no market
definition, feature, signal, strategy, execution, optimization, or model logic.

See [Research Framework Architecture](../docs/RESEARCH_FRAMEWORK.md) for the
extension workflow and artifact contract.
