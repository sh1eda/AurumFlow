# Order Blocks And Breakers

## Selected Definitions

- `NEEDS_FORMALIZATION`: Preferred ICT-style order block definition: bullish OB is the consecutive bearish candle run before displacement upward; bearish OB is the consecutive bullish candle run before displacement downward.
- `NEEDS_FORMALIZATION`: Do not treat OB and supply/demand as the same object. The SMC guide's supply/demand zones should be modeled separately if used.
- `NEEDS_FORMALIZATION`: Bullish breaker structure: low -> high -> lower low sweep -> break above prior high; the last up-close candle(s) before the sweep may become the breaker area. Bearish is inverse.
- `NEEDS_BACKTEST_VALIDATION`: High-probability OB filters include prior liquidity raid, FVG presence, and alignment with HTF draw.

## Source Authority

- Primary OB: `the-ict-handbook-v-1 1.pdf`
- Primary breaker: `EKINYZBB BOOTCAMP SERISI.pdf`, `Mastering ict.pdf`
- Secondary: `EKINYZBB ILERI SEVIYE ICT SERISI.pdf`, `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`

## Implementation-Relevant Interpretation

Future implementation should represent:

- `order_block`: candle-run based zone,
- `supply_demand_zone`: zone that created inefficiency and BOS/CHoCH, if separately formalized,
- `breaker_block`: failed/swept structure that later retests as support/resistance.

This avoids a major source conflict where "last candle before move" and "consecutive opposite candles" produce different zones.

## XAUUSD Adaptation Notes

OB and breaker structures transfer to XAUUSD, but zone width can be large on gold. Refinement from 4H/Daily to 15m may be necessary, and stop models require backtesting.

## Unresolved Ambiguities

- Whether candle wicks or bodies define the final zone.
- How many consecutive candles are allowed in an OB run.
- Whether displacement must include an FVG.
- How to select one OB when multiple nested OBs exist.

## Do Not Automate Yet

- OB entries without liquidity, structure, and HTF context.
- Replacing OB logic with subjective supply/demand drawings.
- Using payout/trade examples as validation.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`
