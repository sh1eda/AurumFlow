# Market Structure

## Selected Definitions

- `READY_FOR_IMPLEMENTATION`: Short-term swing high/low can use the three-candle formation from the ICT handbook. A swing high has a higher high than the candle on both sides. A swing low has a lower low than the candle on both sides.
- `NEEDS_FORMALIZATION`: BOS is a break of structure in the direction of the existing trend.
- `NEEDS_FORMALIZATION`: MSS/CHoCH is a break against the existing trend, ideally after liquidity has been raided or a higher-timeframe zone has been mitigated.
- `NEEDS_FORMALIZATION`: Prefer candle body close to confirm structure breaks on 15m and higher. Record wick breaks separately as raids.

## Source Authority

- Primary: `the-ict-handbook-v-1 1.pdf`, `Smart Money Concept (SMC) Trading.pdf`
- Secondary: `EKINYZBB BOOTCAMP SERISI.pdf`, `Market Structure - Skatfx.pdf`

## Implementation-Relevant Interpretation

The bot should separate structural events:

- `swing_high` / `swing_low` from deterministic local candle patterns,
- `liquidity_raid` when price crosses a prior swing/session level,
- `bos_body_close` when price closes beyond a structural swing in trend direction,
- `mss_body_close` when price closes beyond a structural swing against prior direction.

This separation prevents wick-only manipulation from being mislabeled as a trend change.

## XAUUSD Adaptation Notes

Structure concepts transfer directly to gold. The open parameter is swing sensitivity by timeframe. The working assumption for future strategy development should be HTF context from 4H/Daily and execution context around 15m, because multiple sources pair macro/micro timeframes this way.

## Unresolved Ambiguities

- Exact definition of intermediate-term high/low beyond the short-term three-candle pattern.
- Whether CHoCH and MSS should be separate event types or aliases.
- How much displacement is required after MSS.

## Do Not Automate Yet

- Trend reversal from wick-only breaks on 15m+.
- "Sharp turn" or "strong market structure shift" without explicit measurable hypotheses.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`
