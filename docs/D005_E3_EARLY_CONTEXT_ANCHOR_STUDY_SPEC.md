# D005_E3 Early Context Anchor Study Specification

## Boundary

`D005_E3_EARLY_CONTEXT_ANCHOR_STUDY` is an isolated descriptive study of
causally available context anchors. It reads the frozen D005, D005_E1, and
D005_E2 implementation and artifacts plus the exact D003-derived market-data
selection verified by E2. It does not modify any prior artifact, canonical
data, strategy default, threshold, state transition, or production behavior.

An anchor is an observation timestamp, not an entry. The study does not
assume execution, stops, targets, position size, returns, expectancy, or P&L.

## Fixed prior conclusions

The accepted E2 conclusions remain fixed:

- direction labels are causal and contain no sign inversion;
- `reaction_confirmed` is systematically late relative to context;
- capped E1 sampling materially distorted the result; and
- earlier candidate anchors had better descriptive outcomes than the existing
  reaction-confirmed anchor.

The study fails closed if protected E1/E2/D005 fingerprints or the E2 summary
classification differ from their recorded values.

## Inputs and population

- Sample: 2021-01-03 through 2025-12-31.
- Timezone: `America/New_York`.
- Population: all deterministic-deduplicated `e2_uncapped` sequence rows.
- Source files, sizes, and SHA-256 hashes must match E2 provenance.
- Invalid PMH/PML prerequisite rows remain in the sequence and exclusion
  audit but are not eligible candidate-context anchors.
- Missing-date, excluded-evaluation, gap, premarket-coverage, DST, and source
  metadata are copied from protected E1 artifacts without reinterpretation.

Main anchor eligibility depends only on evidence available at the anchor.
Later structural completion, engine confirmation, invalidation, timeout, or
conflict flags are retained only for explicitly retrospective diagnostics.

## Anchor definitions

Each sequence may contribute at most one row per anchor type. Exact event IDs,
directions, availability timestamps, and direction sources remain separate.

1. `parent_context_creation`: parent structure direction at its causal
   creation timestamp. Neutral directions remain inventoried but have no
   directional forward outcome.
2. `htf_poi_interaction`: POI candidate interaction, for POI-origin sequences.
3. `named_liquidity_sweep`: named sweep availability, including qualifying
   PMH/PML, for liquidity-origin sequences.
4. `candidate_context_creation`: the frozen candidate evidence availability.
5. `mss_body_close_confirmation`: selected reaction-timeframe MSS availability.
6. `displacement_confirmation`: selected displacement availability.
7. `first_aligned_raw_fvg_creation`: first raw refinement-timeframe FVG in the
   candidate direction available at or after candidate creation. It is not
   required to become context-qualified later.
8. `first_context_qualified_fvg_creation`: first aligned raw FVG available only
   after the same sequence's candidate, MSS, and displacement were all
   causally available and parent alignment was valid.
9. One independent anchor for each qualifying OB variant:
   `consecutive_block`, `last_opposing_candle`, and
   `inefficiency_break_origin`. Qualification uses the same causal
   candidate/MSS/displacement/parent-alignment requirements. Variants are
   never merged.
10. `refinement_array_creation`: the existing E2 reconstructed refinement
    array availability.
11. `refinement_array_first_interaction`: E2's first completed
    refinement-timeframe overlap after array creation and before body-close
    invalidation. The interaction reference price and bar close remain
    separate fields; neither is an entry.
12. `reaction_confirmed`: the unchanged D005 transition timestamp for exact
    engine-selected uncapped evidence.

Raw and qualified arrays are selected using event availability and current
sequence evidence only. Final interaction, invalidation, confirmation, and
forward outcomes never decide which array is retained.

## Outcomes and analysis unit

The analysis key is `sequence_id + anchor_type`; deterministic duplicate keys
are removed before outcomes. Cohort explosion never changes the principal
sample size.

Outcomes use the anchor's own first available timestamp at 5, 15, 30, 60, and
120 minutes, New York noon, and 17:00 New York selected trading-day close.
They include signed price movement, win indicator (`signed movement > 0`),
MFE, MAE, MFE/MAE ratio, adverse-before-favorable order, and time to both
extremes. All observations are downstream-only.

Normal 95% confidence intervals are reported for descriptive summary cells.
Primary comparisons additionally use 1,000 deterministic bootstrap resamples
of the mean with seed `50053`.

## Preregistered primary comparisons

Primary anchor family:

- candidate context;
- MSS;
- displacement;
- refinement-array creation;
- first refinement interaction; and
- existing reaction confirmation.

Primary horizon: 60 minutes.

Each approved mapping and reversal/continuation label is a separate cell.
There are 60 registered cells before empty-cell removal:

`6 anchors × 5 mappings × 2 outcome families`.

No pooled mapping score is created. Two-sided one-sample t-test p-values are
adjusted together using Benjamini-Hochberg false-discovery-rate control at
`q = 0.05`. Secondary horizons, directions, years, sessions, volatility
regimes, origins, PMH/PML, FVGs, OBs, and retrospective completion cohorts are
exploratory and cannot promote an anchor.

## Stability criteria

A primary mapping/outcome cell survives only when:

1. sample size is at least 100;
2. mean signed movement is positive;
3. median signed movement is non-negative;
4. BH-adjusted q-value is at most 0.05;
5. deterministic bootstrap 95% mean interval is strictly above zero;
6. at least four calendar years with at least 15 observations are positive;
7. bullish and bearish subsets each have at least 25 observations and
   positive means; and
8. the anchor is main-scope causal evidence, not future-completion selected.

An anchor family is broadly stable only if surviving cells cover at least
three distinct mappings and both reversal and continuation. A narrow anchor
requires at least one surviving primary cell.

## Exact primary classification

Exactly one category is selected in this order:

1. **Broadly stable earlier causal anchor**: an anchor earlier than
   `reaction_confirmed` meets the broad rule.
2. **Earlier anchor only in a narrow defensible cohort**: no broad anchor,
   but at least one earlier primary cell survives all cell criteria.
3. **Candidate information but no operationally stable anchor**: no stable
   cell, but candidate context has positive mean and non-negative median in at
   least three registered cells and at least one positive FDR-significant
   cell.
4. **Positive result explained by retrospective conditioning**: categories
   1–3 fail, while the later engine-confirmed candidate cohort has at least
   100 observations, a bootstrap interval above zero, and a mean at least one
   XAUUSD price unit above the all-candidate mean.
5. **No meaningful relationship after uncapped multiplicity analysis**:
   categories 1–4 fail and no earlier primary cell has positive mean with
   q-value at most 0.05.
6. **Inconclusive**: none of the deterministic rules above resolves the
   evidence.

The one-price-unit rule is a diagnostic conditioning-gap flag, not a strategy
threshold or optimized production value.

## Latency decay

Sequence-level latency retains:

- POI/sweep → candidate;
- candidate → MSS;
- MSS → displacement;
- displacement → each FVG/OB/refinement creation;
- refinement creation → first interaction; and
- first interaction → reaction confirmation.

For each pair, elapsed minutes, stage price movement, candidate-to-stage MFE
and MAE, and timestamp ordering are recorded. Aggregate tables compare
left-anchor and right-anchor 60-minute means and win rates to locate gradual
decay or a discrete collapse.

## Acceptance criteria

1. E3 has a new package and output directory.
2. D005/E1/E2 fingerprints are identical before and after the run.
3. Every source hash is reverified.
4. All five mappings and three OB variants remain independent.
5. Main samples never require later sequence completion.
6. Retrospective conditioning is explicit in every affected table.
7. Anchor timestamps and directions are causal and independently preserved.
8. Outcomes are downstream-only and never P&L.
9. Primary comparisons and multiplicity control match this specification.
10. Focused and full repository tests pass.

