# Entry Models

## Selected Definitions

- `NEEDS_FORMALIZATION`: A robust ICT/SMC entry sequence is generally: HTF context -> liquidity raid or mitigation -> MSS/CHoCH -> retrace to FVG/IFVG/OB/breaker -> target opposing liquidity or unmitigated zone.
- `NEEDS_BACKTEST_VALIDATION`: Session high/low setup requires prior session consolidation, manipulation of a high/low, confirmation, and movement toward opposing session liquidity.
- `NEEDS_BACKTEST_VALIDATION`: FVG/IFVG entries should be filtered by liquidity and structure, not taken from raw FVG touch alone.
- `DISCRETIONARY_DO_NOT_AUTOMATE_YET`: MMXM, Judas, and PO3 should stay as context labels until their components are formalized.

## Source Authority

- Primary: `Smart Money Concept (SMC) Trading.pdf`, `EKINYZBB BOOTCAMP SERISI.pdf`
- Secondary: `the-ict-handbook-v-1 1.pdf`, `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`, `One Setup For Life - Redeye.pdf`

## Implementation-Relevant Interpretation

Future implementation should build event primitives before strategy decisions:

- `htf_draw_selected`,
- `liquidity_raid_detected`,
- `confirmed_sweep`,
- `mss_body_close`,
- `fvg_created`,
- `ifvg_confirmed`,
- `ob_or_breaker_available`,
- `retrace_into_entry_array`,
- `session_window_valid`.

Do not emit BUY/SELL from this knowledge base. These are candidate components only.

## XAUUSD Adaptation Notes

Gold execution should likely start on 15m confirmation with optional lower-timeframe refinement only after backtesting. The SMC guide uses 1m for execution, but the repository request emphasizes future 15-minute execution usefulness, so 1m logic should not be assumed.

## Unresolved Ambiguities

- Entry zone priority when FVG, OB, and breaker overlap.
- Whether entry waits for CE/midpoint or first touch.
- Whether MSS must occur on 15m, 5m, or 1m.
- Whether session filters improve or reduce gold performance.

## Do Not Automate Yet

- Entry on raw level touch.
- Entry from image-only or payout examples.
- "Sharp turn" and "price proves itself" without formal definitions.

## Source References

- `docs/source_analysis/SOURCE_CONFLICTS.md`
- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
