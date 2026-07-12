# Security Policy

## Supported Versions

Version `0.1.0` is the initial research release. Security fixes are considered for the current public release line.

## Reporting a Vulnerability

Please do not disclose security vulnerabilities in a public issue.

Use GitHub private vulnerability reporting if it is enabled for the repository. If private reporting is not enabled, open a minimal public issue asking for a private maintainer contact and do not include exploit details, credentials, account data, broker information, or private datasets.

Useful reports include:

- A clear description of the issue.
- Steps to reproduce with minimal data.
- The affected version or commit.
- The expected impact.
- Any safe mitigation you have identified.

## Trading and Strategy Risk

AurumFlow is experimental trading research software. A strategy weakness, poor market outcome, losing signal, unfavorable backtest, or model underperformance is not a software security vulnerability by itself.

Security issues include problems such as credential leakage, unsafe file handling, dependency vulnerabilities, unintended network access, or code paths that could place orders without explicit authorization.

The current codebase intentionally blocks real-money order placement.
