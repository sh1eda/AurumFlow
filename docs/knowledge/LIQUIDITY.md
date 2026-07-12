# Liquidity

## Selected Definitions

- `READY_FOR_IMPLEMENTATION`: Time-based liquidity levels are prior year/quarter/month/week/day/session highs and lows. These can be extracted mechanically from OHLC data once the session calendar is fixed.
- `NEEDS_FORMALIZATION`: Buy-side liquidity is the pool of buy stops resting above prior highs, equal highs, and range highs. Sell-side liquidity is the pool of sell stops resting below prior lows, equal lows, and range lows.
- `NEEDS_FORMALIZATION`: A raw liquidity raid is price crossing a known liquidity level. A confirmed sweep requires an additional reaction, such as return inside the range, body-close rejection, MSS, or displacement.
- `NEEDS_FORMALIZATION`: External range liquidity lies outside a selected dealing range. Internal range liquidity includes FVGs and other PD arrays inside that range.

## Source Authority

- Primary: `the-ict-handbook-v-1 1.pdf`, `Smart Money Concept (SMC) Trading.pdf`
- Secondary: `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`, `EKINYZBB ILERI SEVIYE ICT SERISI.pdf`, `Mastering ict.pdf`

## Implementation-Relevant Interpretation

The future bot should maintain a registry of objective liquidity levels before evaluating entries:

- previous day high/low,
- previous week high/low,
- previous month high/low,
- current and previous session high/low,
- equal highs/equal lows after a formal tolerance is chosen,
- dealing-range high/low after range definition is chosen.

Do not treat "liquidity above/below" as a trade signal by itself. It is context for bias, target selection, and setup filtering.

## XAUUSD Adaptation Notes

Time-based levels transfer well to XAUUSD. Session levels need New York-time mapping with daylight saving handling. Equal-high/equal-low tolerance should be volatility-aware for gold, likely using tick size, spread, or ATR-based thresholds, but no source provides a tested formula.

## Unresolved Ambiguities

- How close two highs/lows must be to count as equal.
- Whether a sweep requires wick-only penetration, body close beyond the level, or return back inside.
- Which liquidity pool has priority when multiple nearby levels exist.

## Do Not Automate Yet

- A direct trade from every liquidity raid.
- Any arbitrary formula for "strong sweep" or "strong displacement" without backtest framing.
- Index-specific point thresholds from ES/NQ examples.

## Source References

- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
- `docs/source_analysis/SOURCE_CONFLICTS.md`
