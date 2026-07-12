# Session Logic

## Selected Definitions

- `NEEDS_BACKTEST_VALIDATION`: Killzones are time windows with greater expected liquidity and cleaner price action. ICT sources list them in New York/EST time.
- `NEEDS_BACKTEST_VALIDATION`: Session high/low model trades from a prior consolidated session low to high or high to low only after manipulation and confirmation.
- `NEEDS_BACKTEST_VALIDATION`: Judas Swing is a false move through session or range liquidity followed by MSS and movement toward opposing liquidity.
- `REJECTED_FOR_AUTOMATION`: Index RTH opening range gap rules do not directly transfer to XAUUSD.

## Source Authority

- Primary: `the-ict-handbook-v-1 1.pdf`, `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`
- Secondary: `One Setup For Life - Redeye.pdf`, `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf`
- Partial: `DREYKO_NOTES_2025_Lecture_Series_Making_Money_With_SMC_Concepts.pdf`, `ICT Ekolünde.pdf`

## Implementation-Relevant Interpretation

Represent all sessions explicitly before strategy logic:

- Asia range,
- London open,
- New York AM,
- London close,
- New York PM only if proven useful for XAUUSD,
- major news windows as separate no-trade/research features.

Session windows must be timezone-aware and DST-aware.

## XAUUSD Adaptation Notes

Gold often concentrates liquidity around London and New York overlap, US data releases, and COMEX-related flows. The sources provide index/forex windows, not a validated gold calendar. Future work should profile XAUUSD volatility and sweep behavior by New York time.

## Unresolved Ambiguities

- Exact XAUUSD killzones.
- Whether NY PM has useful gold behavior.
- How to treat US macro releases at 8:30 and 10:00 New York time.
- Whether broker server candles align with New York session boundaries.

## Do Not Automate Yet

- 9:30 ES/NQ Judas rules.
- 8:30/10:00 index PO3 models.
- Opening Range Gap targets from RTH markets.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/FINAL_REPORT.md`
