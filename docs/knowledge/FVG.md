# Fair Value Gaps

## Selected Definitions

- `READY_FOR_IMPLEMENTATION`: A Fair Value Gap is a three-candle inefficiency where candle 1 and candle 3 do not overlap by wick range after a fast move.
- `READY_FOR_IMPLEMENTATION`: Store bullish and bearish raw FVG zones as objective price intervals.
- `NEEDS_FORMALIZATION`: A useful FVG should likely be filtered by context: prior liquidity raid, displacement, MSS/CHoCH, premium/discount, and higher-timeframe draw.
- `NEEDS_FORMALIZATION`: IFVG is a prior FVG that fails and acts in the opposite direction. Prefer close-through validation for 15m+ until backtests say otherwise.
- `NEEDS_BACKTEST_VALIDATION`: Consequent encroachment is the midpoint of an FVG and can be tested as an entry refinement or mitigation threshold.

## Source Authority

- Primary: `the-ict-handbook-v-1 1.pdf`, `EKINYZBB BOOTCAMP SERISI.pdf`
- Secondary: `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`, `Smart Money Concept (SMC) Trading.pdf`, `Mastering ict.pdf`

## Implementation-Relevant Interpretation

Separate the detection layer from the strategy layer:

- Detection layer: raw FVG bounds, direction, timeframe, creation candle, fill percentage, midpoint.
- Context layer: prior raid, displacement, structure shift, session, premium/discount location.
- Strategy layer: whether to use the FVG as HTF POI, 15m entry array, target, or no-trade reference.

## XAUUSD Adaptation Notes

FVG geometry transfers directly to XAUUSD. Quality filters must be researched on gold because gold frequently creates intraday wicks and news-driven displacement.

## Unresolved Ambiguities

- Whether a wick into an FVG counts as mitigation or full fill.
- Whether IFVG violation requires wick-through, body close, or displacement close.
- Whether 0.25 and 0.75 levels add value beyond the midpoint.

## Do Not Automate Yet

- Entry from every FVG touch.
- Arbitrary displacement formulas such as body > 1.5 ATR unless introduced later as a research hypothesis.
- Index ORG FVG rules without XAUUSD-specific tests.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
