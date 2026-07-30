# D005_E2 Reaction Anchor Diagnostic Specification

## Boundary

`D005_E2_REACTION_ANCHOR_DIAGNOSTIC` is an isolated causal-labeling and
anchor-timing study. It reads the frozen D005 implementation, the completed
D005_E1 artifacts, and the same hash-verified D003-derived one-minute data
used by E1. It does not change D005 defaults, thresholds, gates, state
transitions, or production behavior.

The study does not assume an entry, spread, stop, target, position size, or
P&L. All forward results are descriptive XAUUSD price movement.

## Frozen inputs

- Requested sample: 2021-01-03 through 2025-12-31.
- Evaluation timezone: `America/New_York`.
- D005 and E1 artifact directories are read-only protected inputs.
- Source files and their SHA-256 hashes must exactly match the E1
  reproducibility record.
- D005 mappings remain independent:
  - Weekly → 4H → 1H;
  - Daily → 1H → 15m;
  - 4H → 15m → 5m;
  - 1H → 5m; and
  - 1H → 5m → optional 1m.

## Diagnostic populations

Two populations are retained separately:

1. `e1_capped`: the unique E1 transitions whose target state was
   `reaction_confirmed`.
2. `e2_uncapped`: every causally reconstructable candidate chain found from
   the full E1 event inventory without a per-date or per-mapping event cap.

The uncapped population is constructed by deterministic evidence joins, not
by loosening a D005 gate. Every parent POI interaction and named liquidity
sweep is considered. Candidate rows are retained even when an aligned MSS,
displacement, or refinement array is absent.

Structural sequence completion is not treated as final D005 confirmation.
At every unique structural-completion timestamp, the unchanged D005 engine
is replayed with the mapping's frozen warm-up and configuration. The study
records its state, direction, outcome, no-trade reasons, risk fields,
transitions, and selected evidence. An uncapped sequence is an engine-selected
`reaction_confirmed` sequence only when its candidate, MSS, displacement, and
refinement IDs exactly match the engine's four selected evidence IDs.

PMH/PML inventory sweeps that fail E1's recorded balanced/unresolved/no-HTF
prerequisites remain in the exclusion funnel and are not included in forward
analysis. The replay does not let PMH/PML override HTF context.

Duplicate rows are removed only when mapping, candidate, MSS, displacement,
and refinement evidence identifiers are all identical. Counts before and
after this exact deduplication are recorded.

## Direction semantics

Direction uses the frozen D005 integer convention:

- `+1`: expected bullish price movement;
- `-1`: expected bearish price movement;
- `0`: unresolved.

For liquidity:

- buy-side, equal-high, and premarket-high liquidity has raid direction
  `+1` and expected post-sweep reaction direction `-1`;
- sell-side, equal-low, and premarket-low liquidity has raid direction
  `-1` and expected post-sweep reaction direction `+1`.

The study records parent, liquidity-expected, MSS, displacement,
refinement-array, final D005, and realized directions independently. It
never silently substitutes the raid direction for the expected reaction
direction.

## Preserved causal timestamps

Every candidate row preserves these fields independently:

1. `parent_context_created_at`;
2. `candidate_event_at`;
3. `mss_confirmed_at`;
4. `displacement_confirmed_at`;
5. `refinement_created_at`;
6. `refinement_interacted_at`;
7. `d005_reaction_confirmed_at`;
8. `candidate_invalidated_at` and `candidate_timeout_at`.

`refinement_interacted_at` is reconstructed from the first completed
refinement-timeframe bar after array availability whose range overlaps the
zone before a body-close invalidation. The interaction reference price is
the first boundary encountered from the expected approach side; the same
bar's close is recorded separately. Neither is treated as an entry.

## Forward outcomes

Forward outcomes are calculated independently at:

- candidate POI/sweep event close;
- MSS confirmation close;
- displacement confirmation close;
- refinement-array creation close;
- first refinement-array interaction reference and close;
- D005 reaction-confirmed close.

Horizons are 5, 15, 30, 60, and 120 minutes, the next New York noon, and the
17:00 New York selected trading-day close.

Each row records signed movement, MFE, MAE, MFE/MAE ratio, time to both
extremes, whether adverse excursion occurred first, and whether MFE exceeded
the frozen descriptive price-unit thresholds 0.5, 1.0, 2.0, and 5.0.
Forward outcomes never feed evidence reconstruction or direction labels.

## Sequence latency

Elapsed minutes and intervening signed price movement are measured for:

- event → MSS;
- MSS → displacement;
- displacement → refinement creation;
- refinement creation → first interaction; and
- first interaction → D005 reaction confirmation.

For every later stage, the study also records favorable and adverse
excursion already realized since the candidate event.

## Cohorts and cap sensitivity

Principal results keep reversal and continuation separate. Additional
cohorts retain:

- liquidity sweep versus POI interaction;
- FVG candidates;
- each independent OB candidate and refinement variant;
- PMH/PML;
- full sweep → MSS → displacement → refinement chains;
- full POI → MSS → displacement → refinement chains;
- parent-aligned reversals; and
- parent-aligned continuations.

The cap-sensitivity comparison matches exact evidence signatures between the
E1 capped and engine-selected E2 uncapped populations. It reports overlap,
direction/state composition, anchor timing, and forward differences without
assuming that a larger population is better. The descriptive materiality
flag is true when capped and uncapped 60-minute completion means differ in
sign or their absolute difference exceeds the greater of 0.5 XAUUSD price
units and the absolute uncapped mean. This is a diagnostic classification
rule, not an optimized threshold or production setting.

## Required classification

The final report must select one or more of:

1. Direction-label implementation defect.
2. Reaction confirmation is causally correct but systematically late.
3. Context thesis has no positive forward directional relationship.
4. Negative result is concentrated in one mapping.
5. Negative result is concentrated in reversal or continuation sequences.
6. Negative result is caused by specific POI/array variants.
7. Capped sampling materially distorted D005_E1.
8. Evidence remains inconclusive.

The classification is evidence-driven and must not be softened into a
production recommendation.

## Acceptance criteria

1. E2 is a new package and output directory with no production import.
2. D005 and E1 outputs have identical before/after fingerprints.
3. All E1 source hashes are reverified.
4. All five mappings remain separate.
5. The uncapped reconstruction has no per-day or per-mapping event cap.
6. Direction semantics have deterministic unit tests.
7. Every reconstructed timestamp is causal and independently retained.
8. Refinement creation and first interaction are not conflated.
9. Reversal and continuation principal results are separate.
10. Forward outcomes are downstream-only and never treated as P&L.
11. The three OB variants remain separate.
12. PMH/PML remains research-only and cannot override HTF context.
13. Weekly zero-confirmation causes are explicitly attributed.
14. Configuration, source, implementation, and artifact hashes are emitted.
15. Focused and full repository tests pass.
