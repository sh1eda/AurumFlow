# Risk And Targets

## Selected Definitions

- `NEEDS_BACKTEST_VALIDATION`: Candidate stop placements include beyond the swept swing, beyond zone extreme, at FVG-origin candle body, or below/above SMT-protected structure.
- `NEEDS_BACKTEST_VALIDATION`: Candidate targets include opposing external liquidity, next unmitigated supply/demand zone, FVG/imbalance, session high/low, and partials at CE or range subdivisions.
- `DISCRETIONARY_DO_NOT_AUTOMATE_YET`: No source provides a complete XAUUSD stop-loss/take-profit specification.

## Source Authority

- Primary: `Smart Money Concept (SMC) Trading.pdf`, `EKINYZBB BOOTCAMP SERISI.pdf`
- Secondary: `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`, `_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf`, DREYKO notes for rejected index-specific ORG targets.

## Implementation-Relevant Interpretation

Risk and target logic should be tested as explicit variants:

- stop beyond structural swing,
- stop beyond FVG/OB/breaker zone,
- body-based aggressive stop,
- fixed invalidation after MSS failure,
- target nearest external liquidity,
- target next unmitigated zone,
- target HTF FVG midpoint or full fill.

Each variant must be linked to the setup type and session context.

## XAUUSD Adaptation Notes

Gold spread, volatility, and news spikes make aggressive stops fragile. Risk logic should include broker spread/slippage assumptions and macro-news filters when backtested.

## Unresolved Ambiguities

- Whether body stops are viable on 15m XAUUSD.
- Whether targets should prefer liquidity over imbalance.
- How to handle partial exits.
- Whether time-based exits are needed for session setups.

## Do Not Automate Yet

- A single universal stop rule.
- A single universal RR target.
- 15-handle or ES/NQ point assumptions.
- Stop placement solely because a source trade example used it.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/FINAL_REPORT.md`
