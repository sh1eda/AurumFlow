# Market Cycles

## Selected Definitions

- `NEEDS_PARAMETER_RESEARCH`: The IPDA cycle is accumulation -> expansion -> retracement -> reversal.
- `NEEDS_PARAMETER_RESEARCH`: Expansion is the phase that leaves consolidation and often creates displacement/FVG.
- `NEEDS_PARAMETER_RESEARCH`: Retracement after expansion can offer lower-risk PD arrays such as FVG, OB, breaker, or OTE.
- `DISCRETIONARY_DO_NOT_AUTOMATE_YET`: Reversal is described as order-flow change after weakness/manipulation, but no deterministic rule is given.

## Source Authority

- Primary: `IPDA_-Market_Cycle.pdf`
- Secondary: `_ICT_-_Market_CYCLE__Manipulation_Series_(Ep.3).pdf`

## Implementation-Relevant Interpretation

Market-cycle labels are useful as regime annotations, not trade signals. A future implementation can test objective proxies:

- accumulation: compression/range with low realized volatility,
- expansion: range break plus displacement/FVG,
- retracement: return into prior PD array after expansion,
- reversal: liquidity raid plus MSS against established order flow.

These are hypotheses, not source definitions.

## XAUUSD Adaptation Notes

Cycle concepts transfer broadly to gold, but COT/BTC examples do not. Gold is sensitive to macro releases and session liquidity; cycle labels should be tested per session and per volatility regime.

## Unresolved Ambiguities

- How to detect accumulation without hindsight.
- How to distinguish retracement from reversal in real time.
- Whether COT positioning improves cycle labeling for XAUUSD.

## Do Not Automate Yet

- Phase labels as entry triggers.
- Bitcoin two-year cycle or yearly-quarter forecast assumptions.
- "Smart money accumulation" claims without measurable data.

## Source References

- `docs/source_analysis/EXTRACTED_CONCEPTS.md`
- `docs/source_analysis/FINAL_SOURCE_SELECTION.md`
