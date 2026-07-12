# Market Maker Models

## Selected Definitions

- `NEEDS_FORMALIZATION`: Market Maker Buy/Sell Model is described as a sequence of consolidation, manipulation/re-distribution or re-accumulation, reversal, and expansion.
- `NEEDS_FORMALIZATION`: MMXM concepts overlap with PO3, Judas Swing, range manipulation, FVG, OB, and SMT.
- `DISCRETIONARY_DO_NOT_AUTOMATE_YET`: Current MMXM sources are mostly personal interpretation and trade examples, not deterministic specifications.

## Source Authority

- Primary: `_Market_Maker_Model_Nedir_10_000_payoutu_mmxm_ve_maniplasyon_teknikleri.pdf`
- Secondary: `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf`, `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf`, `IPDA_-Market_Cycle.pdf`
- Example-only/redundant: MMXM execution PDFs.

## Implementation-Relevant Interpretation

Use MMXM as a narrative grouping, not as an independent signal. Future code should first implement lower-level objective events:

- range/consolidation,
- liquidity raid,
- FVG/displacement,
- MSS/CHoCH,
- retest of PD array,
- movement toward opposing liquidity.

Only after those pieces are tested should a higher-level MMXM classifier be attempted.

## XAUUSD Adaptation Notes

MMXM may transfer as a behavioral model, but XAUUSD needs session-specific validation. Gold can perform strong macro-driven expansions that look like MMXM in hindsight.

## Unresolved Ambiguities

- How to detect consolidation and re-distribution without hindsight.
- How to distinguish MMXM from ordinary trend continuation.
- Whether SMT is required or optional in MMXM reversal.

## Do Not Automate Yet

- Payout examples as evidence.
- Manual pattern recognition converted into hard-coded rules without measurable definitions.
- Early entries before price "proves itself" through objective confirmation.

## Source References

- `docs/source_analysis/FINAL_SOURCE_SELECTION.md`
- `docs/source_analysis/SOURCE_CONFLICTS.md`
