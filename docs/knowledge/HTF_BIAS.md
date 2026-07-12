# Higher-Timeframe Bias

## Selected Definitions

- `READY_FOR_IMPLEMENTATION`: Track prior day/week/month highs and lows as HTF liquidity.
- `NEEDS_FORMALIZATION`: HTF draw-on-liquidity is the likely next price objective, usually external liquidity or an internal imbalance depending on current context.
- `NEEDS_FORMALIZATION`: External/internal liquidity sequencing suggests price often moves from external liquidity to internal FVG, then back toward external liquidity.
- `NEEDS_PARAMETER_RESEARCH`: COT can provide weekly gold-futures regime context, not intraday direction.

## Source Authority

- Primary: `EKINYZBB ILERI SEVIYE ICT SERISI.pdf`, `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`
- Secondary: `IPDA_-Market_Cycle.pdf`, `Trade_Stocks_Commodities_with_the_Insiders_Secrets_of_the_COT_Report.pdf`, `COT LW 1.pdf`

## Implementation-Relevant Interpretation

HTF bias should be a ranked context model, not a single binary long/short flag:

- current location relative to daily/weekly dealing range,
- nearest external liquidity above/below,
- nearest internal FVG above/below,
- active 4H/Daily structure direction,
- whether recent liquidity was raided and accepted/rejected,
- optional COT/regime context if later researched.

## XAUUSD Adaptation Notes

XAUUSD is suitable for HTF liquidity and FVG concepts. COT mapping must use gold futures data, account for reporting lag, and should not override real-time structure.

## Unresolved Ambiguities

- How to rank competing draws.
- When external liquidity is considered "taken enough."
- Whether COT positioning improves or lags XAUUSD intraday decisions.

## Do Not Automate Yet

- Bitcoin quarterly HTF bias.
- COT as a direct entry trigger.
- A fixed long/short bias from one FVG or one liquidity raid.

## Source References

- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
- `docs/source_analysis/FINAL_SOURCE_SELECTION.md`
