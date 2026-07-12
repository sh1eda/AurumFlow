# SMT

## Selected Definitions

- `NEEDS_PARAMETER_RESEARCH`: SMT is divergence between correlated instruments. One instrument makes a new high/low while the paired instrument fails to confirm.
- `NEEDS_PARAMETER_RESEARCH`: Candidate XAUUSD pair is XAGUSD, but source material does not define a complete XAU/XAG rule set.
- `NEEDS_FORMALIZATION`: SMT requires a defined pair, correlation direction, timeframe alignment, swing matching method, and divergence threshold.

## Source Authority

- Primary: `_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf`
- Secondary: `IPDA_-Market_Cycle.pdf`

## Implementation-Relevant Interpretation

SMT should be a confirmation or risk-context feature, not a primary signal. Required fields:

- primary symbol: XAUUSD,
- comparison symbol: candidate XAGUSD,
- timeframe: likely 15m, 1H, and 4H to test,
- swing detector shared across both series,
- alignment tolerance for bar timestamps and session gaps,
- divergence direction.

## XAUUSD Adaptation Notes

The source explicitly names XAU-XAG as a correlated pair type, but does not define practical parameters. XAUUSD/XAGUSD may behave differently around gold-specific macro shocks, USD moves, and silver industrial-demand events.

## Unresolved Ambiguities

- Whether to compare absolute highs/lows or swing highs/lows.
- How many bars of time offset are acceptable.
- Whether correlation must be rolling-confirmed before SMT is considered valid.
- Whether SMT improves stops, entries, or only confidence.

## Do Not Automate Yet

- Any SMT filter without XAU/XAG backtest.
- Correlation pairs copied from NQ/ES, BTC/ETH, or EUR/GBP.
- Stop placement based solely on SMT.

## Source References

- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
- `docs/source_analysis/SOURCE_CONFLICTS.md`
