# Power Of Three

## Selected Definitions

- `NEEDS_PARAMETER_RESEARCH`: PO3 frames a candle or session as open -> manipulation -> expansion -> close.
- `NEEDS_PARAMETER_RESEARCH`: Bullish PO3 often has price open, trade below the open or raid sell-side liquidity, then expand upward and close higher.
- `NEEDS_PARAMETER_RESEARCH`: Bearish PO3 is the inverse: open, trade above open or raid buy-side liquidity, then expand downward and close lower.
- `DISCRETIONARY_DO_NOT_AUTOMATE_YET`: PO3 examples tied to 8:30, 9:30, or 10:00 index windows are not XAUUSD-ready.

## Source Authority

- Primary: `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf`
- Secondary: `EKINYZBB ILERI SEVIYE ICT SERISI.pdf`, `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`

## Implementation-Relevant Interpretation

Future implementation should first define the anchor:

- daily open in New York time,
- weekly open,
- London session open,
- New York session open,
- broker/server daily open, if data requires it.

Only after anchor testing should PO3 become a bias or setup filter.

## XAUUSD Adaptation Notes

XAUUSD trades nearly 24 hours and reacts to both London and New York liquidity. A "true day open" assumption must be tested against the data feed used by the bot. Do not inherit ES/NQ opening behavior.

## Unresolved Ambiguities

- Which open is authoritative for spot/CFD XAUUSD.
- How much movement below/above open qualifies as manipulation.
- Whether expansion must create FVG or body-close structure break.

## Do Not Automate Yet

- 10 AM or 8:30 index PO3 models.
- Any open-touch fade.
- PO3 direction without HTF draw and liquidity context.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`
