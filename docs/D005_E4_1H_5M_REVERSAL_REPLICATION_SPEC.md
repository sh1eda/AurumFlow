# D005_E4 1H→5m Reversal Replication Preregistration

## Boundary and freeze time

`D005_E4_1H_5M_REVERSAL_REPLICATION` is an isolated replication study. This
specification freezes the sample design, eligibility, anchors, direction,
deduplication, exclusions, endpoints, inference, and classification before E4
outcomes are computed. It does not change D005, D005_E1, D005_E2, D005_E3,
canonical data, production behavior, or any strategy default, gate, threshold,
or state transition.

Anchors are observations, not entries. E4 does not define execution, stops,
targets, position size, returns, expectancy, or P&L.

## Frozen discovery result

E4 verifies that the protected E3 primary table contains, without using these
values to redefine eligibility:

- displacement confirmation, `1h_5m`, reversal: N 1,778, 60-minute mean
  `+0.560` after rounding, BH q `0.0088`;
- refinement-array creation, `1h_5m`, reversal: N 1,778, 60-minute mean
  `+0.559` after rounding, BH q `0.0088`.

The primary mapping is `1h_5m`. The optional-1m mapping is disabled in the
primary design and may appear only as a frozen secondary comparator.

## Sample-independence decision

The hash-verified D003-derived source ends on 2025-12-31. A separate MT5 export
contains 2026 data, but it is not D003-derived, has different feed provenance,
and carries qualification warnings. It is excluded before E4 outcomes are
computed.

No 2021–2025 block was reserved before E3 selected the cohort. Therefore E4
cannot claim a genuinely independent post-discovery sample. The selected
fallback is deterministic rolling-origin temporal validation:

| Fold | Discovery prefix | Validation block |
|---|---|---|
| RO-2022 | 2021 | 2022 |
| RO-2023 | 2021–2022 | 2023 |
| RO-2024 | 2021–2023 | 2024 |
| RO-2025 | 2021–2024 | 2025 |

The four validation blocks are disjoint from their own discovery prefixes.
Their union, 2022–2025, is E4's primary internal temporal-validation sample.
Every validation observation necessarily overlaps E3 because E3 used the full
2021–2025 period. This overlap precludes category 1, regardless of the internal
result. The 2021 observations are calibration-prefix context only and are
excluded from the E4 primary endpoint.

## Frozen primary eligibility

A primary sequence must satisfy all of the following using protected E3 anchor
and sequence fields:

1. population is the deterministic-deduplicated E2 uncapped population;
2. `mapping_variant == "1h_5m"`;
3. frozen `outcome == "reversal"`;
4. a causal `displacement_confirmation` anchor exists;
5. `main_scope_eligible` is true;
6. `anchor_causally_observable` is true;
7. `anchor_selected_using_later_completion` is false;
8. displacement direction is non-neutral;
9. sequence ID is unique; and
10. the first anchor ordered by `anchor_at`, `anchor_event_id`, and
    `anchor_id` is retained if an unexpected duplicate exists.

The selection function cannot read later refinement, reaction confirmation,
invalidation, timeout, MFE, MAE, or forward-outcome fields. PMH/PML prerequisite
failures remain excluded by the frozen E3 `main_scope_eligible` field. Missing
60-minute observations are not imputed and remain in the eligibility audit.

The frozen direction is the displacement direction available at the anchor. It
must equal the candidate and MSS direction. Price movement never relabels it.

## Secondary refinement cohort

`refinement_array_creation` is joined only to already eligible primary sequence
IDs. Its existence never influences primary inclusion. The first causal
refinement anchor is retained by the same deterministic ordering. Displacement
and refinement remain paired observations belonging to one sequence, never
independent samples.

Refinement presence/absence and later `reaction_confirmed` completion are
retrospective diagnostic labels only.

## Endpoints

The sole primary endpoint is mean direction-aligned XAUUSD price movement 60
minutes after displacement confirmation in the union of the 2022–2025
validation blocks.

Primary descriptive fields are median, win probability, MFE, MAE, MFE/MAE
ratio, adverse-before-favorable probability, median time to MFE and MAE,
sample size, standard error, two-sided 95% Student-t confidence interval, and a
deterministic 2,000-resample percentile bootstrap interval of the mean using
seed `50054`.

Secondary endpoints are 5, 15, 30, and 120 minutes, New York noon, and 17:00
New York trading-day close for displacement, plus all seven refinement
endpoints including refinement 60 minutes. Their two-sided one-sample t-test
p-values form one Benjamini-Hochberg family at q=0.05. The displacement
60-minute primary test is not included in that secondary family.

No horizon may replace the registered primary endpoint.

## Frozen stability splits

Primary 60-minute results are reported without becoming filters by:

- validation year/fold;
- bullish versus bearish direction;
- causal E3 volatility regime;
- New York anchor-session segment;
- POI, ordinary-liquidity, and PMH/PML origin;
- PMH/PML involvement;
- displacement `true_range_atr`: `[1.25,1.75)`, `[1.75,2.50)`, and
  `[2.50,+∞)`; values below 1.25 or unavailable are audited separately;
- candidate-to-displacement latency: `[0,60)`, `[60,180)`, `[180,360)`, and
  `[360,+∞)` minutes; negative/unavailable values are audited separately;
- later refinement present versus absent, explicitly retrospective; and
- later frozen-engine reaction confirmation, explicitly retrospective.

No split can promote a failed primary result. No within-E4 subgroup can be
called replicated.

## Frozen replication checks

The internal rolling-origin displacement result passes only if all checks hold:

1. validation mean is greater than zero;
2. the two-sided 95% t-interval lower bound is greater than zero;
3. total validation N is at least 1,000, every validation block has at least
   200 observations, and at least three of four block means are positive;
4. bullish and bearish validation subsets each have at least 200 observations,
   and neither subset has a 95% confidence interval entirely below zero;
5. the never-later-confirmed subset has at least 90% of validation N and a
   positive mean;
6. deterministic deduplication leaves the effect sign positive;
7. all causal, availability, closed-bar, and direction invariants pass;
8. mean MFE divided by mean MAE is at least 0.75 and median MFE/MAE ratio is at
   least 0.50;
9. the mean remains positive after removing the 1% largest absolute
   60-minute movements; and
10. the 1% two-sided trimmed mean is positive.

These are diagnostic research thresholds, not D005 or production thresholds.

## Causal audit

For every eligible displacement observation E4 verifies:

- candidate, MSS, displacement creation, and displacement availability do not
  occur after the anchor;
- displacement `available_at` equals the anchor and is no later than E4
  `evaluation_at`, which equals the anchor;
- the corresponding completed 5-minute bar and a completed one-minute bar are
  available at the anchor;
- candidate, MSS, and displacement directions are known, non-neutral, and
  aligned;
- inclusion flags are causal and do not reference later completion or outcomes;
- primary sequence IDs remain unchanged when later refinement, reaction,
  invalidation, timeout, and outcome-like columns are deterministically
  mutated.

Any causal or direction failure is a reproducibility defect.

## Exact classification

Exactly one category is selected in this order:

1. **Independent replication** only if the source is a genuinely separated,
   hash-verified post-2025 D003 derivative and every replication check passes.
2. **Positive but too weak/uncertain** when a genuinely independent adequate
   sample is positive but fails one or more non-defect replication checks.
3. **Narrower subgroup only** when the independent primary result fails but an
   exploratory subgroup is positive.
4. **Does not replicate** when an adequate genuinely independent primary
   sample is non-positive without a reproducibility defect.
5. **Independent sample inadequate** when no eligible genuinely independent
   sample exists, including this preregistered rolling-origin fallback.
6. **Reproducibility/implementation defect** when a protected fingerprint,
   frozen discovery value, source hash, causal invariant, direction invariant,
   or deterministic selection invariant fails.

E4 separately reports whether the internal rolling-origin checks pass, but that
secondary label cannot override category 5.

## Acceptance criteria

1. E4 uses a new package and output directory.
2. D005/E1/E2/E3 fingerprints are identical before and after E4.
3. All authoritative D003-derived source hashes are reverified.
4. Discovery values match the frozen E3 table.
5. Selection is unique, causal, deterministic, and outcome-independent.
6. Primary and refinement observations remain paired by sequence.
7. Primary and secondary inference matches this preregistration.
8. Optional 1m, CISD, PMH/PML, clocks, OB variants, and subgroups are not
   promoted.
9. Outcomes remain descriptive price paths, never trades or P&L.
10. Focused and full repository tests pass.
