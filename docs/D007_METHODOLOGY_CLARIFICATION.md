# D007 Outcome-Blind Methodology Clarification Addendum

## Status and authority

This is the chronological clarification addendum to
`docs/D007_OTE_RESEARCH_SPEC.md` and
`docs/D007_HISTORICAL_EXECUTION_CONTRACT.md`. The original preregistration
remains frozen. This addendum changes none of the original OTE geometry,
upstream selector, lifecycle, outcome, adequacy, authorization, interval,
namespace, or disposition registries. It resolves only the seven
implementation-blocking ambiguities identified before an empirical pipeline
was implemented.

At authorship, no D007 historical outcome had been accessed, constructed, or
computed. No D007 empirical control, interaction, adequacy, statistic, or
redundancy result was inspected or produced. The decisions below use tracked
repository conventions, accepted upstream methodology, causal and
reproducibility principles, synthetic semantics, and standard tests selected
before D007 outcome access. Where the original preregistration did not contain
enough detail, the rule is labeled a new outcome-blind clarification rather
than attributed retrospectively to the original text.

Historical execution remains forbidden until this addendum is reviewed and
merged. The historical pipeline must implement these rules without runtime
methodology switches and must fail closed on any identity or schema drift.

The following remain unchanged: primary band `0.62-0.79`, reference `0.705`,
equilibrium `0.50`, D005 `1h_5m` displacement basis, swing and endpoint
selectors, availability cutoff, lifecycle/touch/invalidation/expiry rules,
overlap/deduplication/stable IDs, interaction set, adequacy thresholds, outcome
definitions, historical source lineage, authorized interval, authorization
token, and output namespace.

## 1. New York named-trading-date semantics

### Frozen D007 rule

D007 uses the established D004-D006 named-session convention:

1. Convert every timezone-aware timestamp to the IANA zone
   `America/New_York`.
2. The named trading day is the half-open local interval `[18:00, 18:00)`.
   A local timestamp before `18:00:00` keeps its local calendar date. A
   timestamp exactly at or after `18:00:00` is assigned to the following local
   calendar date. There is no second rollover.
3. IANA timezone rules determine UTC offset. The UTC rollover is `23:00Z`
   during standard time and `22:00Z` during daylight time. No fixed UTC offset
   or hand-written DST calendar is permitted. Naive, ambiguous, or nonexistent
   local timestamps fail closed; source timestamps are expected to be explicit
   UTC.
4. `validation_year` is the year of that named date. All 13 five-minute
   availability timestamps from event through the exact 60-minute endpoint
   must have a named year in `{2022, 2023, 2024, 2025}`.
5. The source terminal `<2026-01-01T00:00:00Z` is a separate, additional gate.
   The named-year and source-terminal predicates are evaluated independently;
   neither gate relaxes the other.
6. The frozen session labels remain D005's labels. In particular, local
   `18:00-23:59:59...` is `asia` and is named for the following date. Local
   post-midnight observations use their existing D005 label and the same local
   calendar date unless and until the next 18:00 rollover.
7. Consequently, `2025-12-31 18:00` New York and later are named
   `2026-01-01` and are ineligible for D007 validation. The exact instant is
   included in the rollover.

This rule supersedes only the incomplete D007 synthetic guardrail that compared
the stored date with the unshifted local calendar date. It does not alter any
D004-D006 artifact or re-label an upstream study.

### Outcome-blind reason

D004's accepted daily-event schema, D005 daily aggregation, and D006 detector
all use the same exact 18:00 New York rollover. Selecting that established
project convention avoids having two meanings for “named trading date” in a
single causal chain and was decided without D007 outcomes.

## 2. Matched controls

### Common event and candidate contract

The treatment event for every empirical D007 comparison is the primary-band
first-touch bar `available_at`. Its reference is that bar close and its endpoint
is the complete close exactly 60 elapsed minutes later.

Every event-bearing control candidate must have exactly one causal association
to an eligible, distinct D005-E4 `1h_5m` sequence. Association uses IDs only:
an ID in the candidate's frozen evidence must match exactly one of the E4
sequence's `sequence_id`, `candidate_id`, `mss_id`, `displacement_id`,
`displacement_confirmation_event_id`, or `anchor_event_id`. Zero matches or
more than one eligible sequence is `ambiguous_upstream_association` and is
ineligible. Time-nearest association is forbidden. The associated E4 sequence
supplies direction, upstream mapping, displacement availability, session,
validation year, and the availability-to-event bucket.

The candidate event bases and universes are:

| Family | Event time | Candidate universe | Candidate-specific eligibility |
|---|---|---|---|
| `matched_equilibrium_50` | first causal inclusive touch of `L(0.50)` on a distinct deduplicated E4-backed range | lifecycle-eligible primary ranges other than the treatment's upstream sequence | range was available; primary OTE band had not been touched at or before the equilibrium event |
| `matched_context_without_ote` | D005-E1 `reaction_confirmed` snapshot `evaluation_at` | non-neutral `1h_5m`, 1H-parent/5m-reaction snapshots with optional 1m refinement false | evidence IDs associate to exactly one eligible E4 sequence; its OTE band had not been touched at or before snapshot time |
| `matched_displacement_availability` | E4 `confirmation_event_available_at` | eligible distinct E4 displacement-confirmation sequences | E4 causal flags pass, directions agree, and its OTE band had not been touched at the availability instant |

`upstream_no_ote_touch` remains a structural denominator with no invented
event time and is never passed to an endpoint matcher. `matched_time_session_volatility`
is an audit view of the primary pairs. `direction_balanced` is an equal-weight
bullish/bearish audit of those same pairs. Neither creates or replaces pairs.

Before matching, candidates must have a complete 60-minute endpoint, exactly
one upstream association, no own OTE touch at or before their event, and no
unrelated OTE first touch strictly less than 120 elapsed minutes away. Exactly
120 minutes is eligible. A candidate on the treatment's named date, associated
with the treatment's upstream event, outside plus/minus 30 named calendar days,
or outside the registered year is ineligible.

Matching keys are exact validation year, frozen D005 session, direction,
causal volatility bucket, mapping `1h_5m`, and elapsed displacement-availability
to event bucket `[0,30)`, `[30,60)`, `[60,180)`, or `[180,1440]` minutes.
Negative elapsed time and elapsed time above 1,440 minutes are ineligible.
The volatility bucket remains the preregistered prior-complete-day calculation.

Treatments are processed stably by `(event_at, range_id)`. Within each control
family, matching is 1:1 without replacement. Eligible candidates are scored by
SHA-256 of UTF-8 text
`7007|family|treatment range ID|candidate event_at in canonical UTC ISO-8601`.
Lowest digest wins; equal digest/event-time ties use lexical candidate ID.
Candidate input order cannot affect the result. No candidate may be reused
inside a family; families have independent used-ID sets. No match records
`missing_control`; no relaxed key, wider window, replacement stratum, or later
search is allowed.

### Outcome-blind reason

The common matcher, no-replacement policy, hash ordering, and strata are the
already-frozen D006/D007 conventions. Exact ID association prevents a
time-nearest choice from becoming an outcome-sensitive hidden selector. Family
event bases are the first causal instant at which each stated constituent
exists.

## 3. Exact geometry and interaction tests

### Rules common to continuous paired tests

The analysis unit is one unique 1:1 matched pair. The statistic is the mean of
within-pair differences. Unless stated otherwise, the test is a two-sided
paired Student t-test, equivalently a one-sample t-test of differences against
zero, with a two-sided 95% Student-t interval. The null is mean difference
`0`; the alternative is not `0`. Positive direction is always D007 treatment
minus control. Effect reporting is treatment mean, control mean, mean and
median paired difference, sample standard deviation, standardized paired mean
when defined, and 95% interval, in XAUUSD price units (or minutes for timing).
No P&L or trade interpretation is permitted.

Pairs with a missing/non-finite endpoint or effect are excluded before
inference with one first-failure reason and cannot count toward adequacy.
Decisional matched pairs require 100% endpoint coverage. No imputation,
carry-forward, horizon substitution, winsorization, or effect-based removal is
allowed. At least two finite pairs are required to compute a t statistic, but
the preregistered adequacy minimum for the cell still controls decisions. With
fewer than two pairs, the cell is `NOT_EVALUATED`. If variance is zero, report
the constant effect and zero standard deviation, but set t statistic, p-value,
and inferential interval to unavailable and label
`NOT_EVALUATED_ZERO_VARIANCE`; this prevents a constant synthetic artifact
from creating infinite significance. Ties and exact zero differences remain in
the sample. Descriptive robust summaries remain exactly those in the original
preregistration and never replace the primary statistic.

The date bootstrap uses 2,000 resamples. Sort unique named dates, group all
pairs on each date, then sample that many date groups with replacement while
preserving every within-date pair. The cell seed is the unsigned big-endian
integer represented by the first eight bytes of SHA-256 of UTF-8
`7007|family|hypothesis_id`, reduced modulo `2**32`. Sampling uses NumPy
`Generator(PCG64(seed)).integers(0, number_of_dates,
size=(2000, number_of_dates), endpoint=False)`; each row is one resample in
index order. The two-sided percentile interval uses NumPy quantiles `0.025`
and `0.975` with `method="linear"`. No fallback seed, PRNG, draw order,
quantile convention, or adaptive resample count exists.

Benjamini-Hochberg uses the full registered family size even when a hypothesis
is missing: six for interactions, two for incremental controls, and three for
geometry. Rank finite p-values ascending by `(p_value, hypothesis_id)`, but use
the full registered `m` in `min(1, p*m/rank)` and enforce reverse cumulative
monotonicity. Missing cells keep `q_value=null` and `reject=false`; they stay in
their family. Adjusted significance is `q <= 0.05`, inclusive.

### Three geometry hypotheses

All comparisons pair the band and `0.705` objects from the same upstream event;
objects from different events are never paired.

| ID | Analysis unit and estimand | Null / alternative and test | Applicability and decision interpretation |
|---|---|---|---|
| `geometry_touch_incidence` | every lifecycle-eligible upstream event with both fixed objects; paired probability `I(band touched)-I(0.705 touched)` | `H0`: discordant probabilities are equal; `H1`: unequal. Exact two-sided McNemar uses SciPy `binomtest(band_only, band_only + reference_only, p=0.5, alternative="two-sided")`, whose two-sided tail is the probability-ordering convention. Effect is paired risk difference; 95% interval is the fixed date-bootstrap percentile interval. | At least 200 upstream events. A geometry access benefit requires positive risk difference, bootstrap lower bound `>0`, and BH `q<=0.05`. Zero discordance bypasses `binomtest` and is an evaluated cell with effect 0, p 1, and no benefit. |
| `geometry_time_to_touch` | events touched by both geometries; `0.705 elapsed minutes - band elapsed minutes` | mean difference `0` versus nonzero; two-sided paired t-test and 95% t interval | At least 200 complete pairs. Benefit requires positive mean, interval lower bound `>0`, bootstrap lower `>0`, and BH `q<=0.05`. Exact ties remain zero. |
| `geometry_directional_movement` | events touched by both with each geometry's own exact 60-minute endpoint complete; band minus `0.705` movement | mean difference `0` versus nonzero; two-sided paired t-test and 95% t interval | At least 200 complete pairs. This is a zero-margin non-inferiority guard: lower bound must be `>=0`; a BH-significant negative mean fails. It is not a claim that the band is superior. |

`GEOMETRY_CANDIDATE` requires structural and geometry adequacy, both access
benefits above, the movement non-inferiority guard, positive access-effect sign
in at least three of four adequate years, no adequate year with its interval
wholly negative, both directions with the required sign and neither interval
wholly negative, and no integrity failure. A movement q-value alone cannot
create a candidate. Missing or inadequate geometry cells cannot be rescued by
another cell.

### Six interaction hypotheses

Each interaction compares the OTE-plus-constituent treatment at OTE first touch
with the separately matched constituent-only observation defined in section 4.
The estimand is mean paired 60-minute direction-aligned movement difference.
All six use the common two-sided paired t-test, 95% t interval, date bootstrap,
and the single six-member BH family.

| ID | Minimum pairs | Positive-pass / interpretation |
|---|---:|---|
| `aligned_d005_context` | 200 | positive mean, t and bootstrap lower bounds `>0`, BH `q<=0.05`, stability, and non-redundancy; may support conditional candidacy |
| `after_d004_manipulation` | 100 | same statistical rule when adequate, but always exploratory and never affects disposition |
| `frozen_liquidity_sweep` | 200 | positive rule; may support conditional candidacy |
| `refinement_confirmation` | 200 | positive rule; may support conditional candidacy |
| `d006_rejection_block` | 100 | same calculation if adequate, but descriptive/exploratory only and never affects disposition |
| `against_d005_context_negative_control` | 200 | never supports candidacy; a positive mean with t lower `>0` and BH `q<=0.05` is `NEGATIVE_CONTROL_FAILURE` and blocks `CONDITIONAL_CANDIDATE`; a non-positive or non-significant result is consistent/inconclusive, not proof of no effect |

For a positive interaction, stability requires all four years to have at least
two pairs, positive yearly means in at least three, and no yearly 95% interval
wholly negative. Bullish and bearish cohorts must each have at least two pairs,
a positive mean, and no 95% interval wholly negative. These `n>=2` split rules
only define computability; the total preregistered minimum still determines
adequacy. D004 and D006 stay in the BH family even though they are
non-decisional.

### Outcome-blind reason

Paired Student-t inference, date clustering, full-family BH denominators, and
stability direction are established D005/D006 conventions. Exact McNemar is
the simplest correct paired binary test for touch incidence. The zero-variance
and missing rules are fail-closed choices made before outcomes.

## 4. Interaction membership and constituent controls

Interaction evidence is selected without outcomes. At a tied latest timestamp,
multiple rows with different directions are `conflicting_constituents` and the
interaction is ineligible. Same-direction ties select lexical stable ID. No
conjunction between interactions is searched.

| Interaction | Treatment membership | Constituent-only control event |
|---|---|---|
| `aligned_d005_context` | latest unambiguous non-neutral D005-E1 `reaction_confirmed` `1h_5m` snapshot at or before range availability agrees with range direction | another eligible aligned snapshot at its `evaluation_at`, uniquely E4-associated, with no OTE touch by that time |
| `after_d004_manipulation` | D004 completed sweep plus re-entry is available strictly before range availability, on the same 18:00-roll named date, and its reaction agrees | another qualifying D004 re-entry; event is recorded one-minute bar left edge plus one minute, uniquely associated to one eligible E4 sequence, no OTE touch by event |
| `frozen_liquidity_sweep` | latest unambiguous E3 `named_liquidity_sweep` whose `anchor_at` is no later than range availability, direction agrees, `main_scope_eligible` and `anchor_causally_observable` are true, and `anchor_selected_using_later_completion` is false | another causally eligible sweep at `anchor_at`, uniquely E4-associated, no OTE touch by event |
| `refinement_confirmation` | latest unambiguous E3 `refinement_array_creation` available no later than first touch and direction agrees; later first-interaction or final lifecycle information is not required or used | another refinement-creation anchor at `anchor_at`, uniquely E4-associated, no OTE touch by event |
| `d006_rejection_block` | section 7 | another eligible D006 block's first causal proximal touch, direction aligned, with no OTE touch by that time; descriptive only |
| `against_d005_context_negative_control` | latest unambiguous non-neutral reaction-confirmed snapshot at range availability disagrees exactly with OTE direction | another such snapshot at `evaluation_at`; evaluation direction is defined as the opposite of context direction, uniquely E4-associated, no OTE touch by event |

Each interaction treatment is matched to its own constituent-only universe with
the section 2 matcher and family label `interaction:<interaction_id>`. The
treatment denominator is every deduplicated, lifecycle-eligible, endpoint-
complete OTE first touch satisfying that interaction before control matching.
The paired denominator is successful, endpoint-complete 1:1 matches. Report
candidate, eligible, matched, unmatched, endpoint-complete, and first-failure
counts. A missing constituent control does not remove the treatment from the
candidate denominator and cannot count toward adequacy.

An interaction is non-redundant only when its identical-cohort constituent
ablation passes the positive rule. D004 and D006 remain non-decisional even if
their descriptive ablation passes. The negative control cannot be called
non-redundant.

For authenticated E3 rows, `anchor_at` is both the causal event and availability
timestamp. E3 has no authenticated causal `invalidated_at`; its
`later_invalidated` and other `later_*`/`outcome` fields are retrospective and
are forbidden D007 projections. Consequently, “valid at range availability”
for the frozen liquidity sweep means the three causal flags in the table, not
a later lifecycle test. This is a new outcome-blind clarification forced by
the accepted E3 schema; future implementation may not infer an invalidation
timestamp or consult the retrospective boolean.

## 5. Ablation and redundancy

### Structural association algorithm

The comparison population is every deduplicated, lifecycle-eligible primary
band with a first causal touch and complete 60-minute endpoint. Its primary
reference instant is range availability. Report each frozen feature in the
original D007 list; do not add, drop, combine, or select features after results.

The D005 displacement event and strength are associated by the range's exact
upstream E4 ID, regardless of elapsed time. Equilibrium position, continuous
retracement depth, and availability-to-touch time are deterministic fields of
that same range and need no external event join.

For MSS, refinement, raw FVG, qualified FVG, liquidity sweep, D005 context, and
D006 block evidence, a causal-time association requires evidence availability
within the inclusive window `[range availability - 60 minutes, range
availability + 60 minutes]` and no later than first touch. Evidence that has an
authenticated causal invalidation/terminal timestamp and has already
invalidated or terminated at the applicable reference is ineligible. E3 has no
such authenticated timestamp and uses only its causal flags as specified in
section 4. Direction must agree, except the explicitly registered negative
context diagnostic. Exact `-60` and `+60` boundaries are included.

When multiple eligible evidence rows exist, select the smallest absolute signed
minute difference from range availability, then earlier `available_at`, then
lexical stable ID. A tie with conflicting directions fails closed before this
precedence. Signed minutes are `feature available_at - range available_at`.

For evidence with a price zone, price overlap is closed-interval intersection
with the OTE band. For a point level, association is inclusive containment in
the OTE band. Evidence without a frozen causal price or zone is
`price_not_available`, not zero overlap. Denominator for time association is
the complete comparison population; denominator for price overlap is only rows
with an authenticated frozen price/zone. Missing evidence remains in the time
denominator. Report exact count, denominator, rate, signed-median minutes, and
first-failure reason.

An association rate equal to `1.0` is `FULL_STRUCTURAL_OVERLAP`; any value less
than `1.0`, including the exact floating-point boundary represented by equal
integer numerator and denominator, is not full overlap. Structural overlap is
descriptive and never by itself establishes or rejects incremental value.

### Fixed ablation and decision mapping

The only decisional standalone ablations are the already-registered
`matched_context_without_ote` and `matched_displacement_availability`
comparisons, on identical OTE treatment cohorts and endpoints. They form the
fixed two-hypothesis BH family. No feature-set search, refit, black-box
importance, regression selection, subgroup search, or alternative threshold is
permitted.

For either ablation:

- `NON_REDUNDANT` requires its total minimum of 200 pairs, positive mean,
  two-sided t lower bound `>0`, date-bootstrap lower bound `>0`, BH `q<=0.05`,
  and the interaction stability rules;
- `FULLY_ACCOUNTED` requires an adequate cell whose 95% upper bound is `<=0`;
- otherwise it is `INCONCLUSIVE`.

`NON_REDUNDANT_COMPONENT_CANDIDATE` requires the unchanged structural and
primary rules plus both registered ablations `NON_REDUNDANT`. One passing
ablation cannot rescue the other. Any `FULLY_ACCOUNTED`, inadequate, missing,
or inconclusive ablation prevents this disposition but does not automatically
reject the component. Interaction-specific conditional candidacy uses its own
identical-cohort constituent ablation. This algorithm introduces no
outcome-driven model selection.

### Outcome-blind reason

The inclusive 60-minute association window and deterministic nearest-event
precedence reuse the D006 causal redundancy convention. Direct E4 ID association
is stronger for the mandatory displacement and avoids treating elapsed time as
identity. Separate structural and effect-based labels prevent overlap from
being misrepresented as incremental evidence.

## 6. Interaction and context provenance

The machine-readable inventory is `UPSTREAM_ARTIFACTS` in
`research/d007_methodology_clarification.py`. It freezes these dependencies:

| Milestone | Artifact | Version / identity | SHA-256 | Schema identity | D007 role |
|---|---|---|---|---|---|
| D004 | `research_outputs/D004_XAUUSD_0830_0900/daily_events.parquet` | `D004_XAUUSD_0830_0900`, D003 `d003-v1`, dataset `3ef1612c3ac73469e0b0` | `43016a97f1f5ee00826eda52ee49fdb75e14c1eafcc93b5338cbd190248f6fd4` | `daily_event_schema.json` SHA `b8980e89a579024ba43cc53228f1157453efdd0701a3714175a7ff0fc2f50d3c` | D004 interaction/redundancy |
| D005-E1 | `research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/context_snapshots.parquet` | `D005-E1-v1`, config `85541774...` | `23f4fda9250b53c3fdf9d4227ac9f81a9a40c7258ebd179767c8cad72c157674` | `feature_schema.json` SHA `b2ed7fde...` | context constituents |
| D005-E3 | `research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/anchor_events.parquet` | `D005-E3-v1`, config `f08e9116...` | `f516f41c60eab94da6c5fb48a124e9a37dc325715868ca3e0f56a56b60cc1373` | `feature_schema.json` SHA `fcd2efc1...` | liquidity/refinement/MSS/FVG constituents |
| D005-E4 | `eligible_sequences.parquet` | `D005-E4-v1`, config `34e044c6...` | `059e7053e46f753f5cede6714f2de5ea3a5a0ee47ae7d781cdd55d6af1c00b40` | `feature_schema.json` SHA `993648cd...` | upstream association |
| D005-E4 | `displacement_anchors.parquet` | same | `d6a45058c11f32a7cb476d2ec578c50f53c017b080f3537002c1624049e42ce0` | same | displacement constituents |
| D006 | `research_outputs/D006_REJECTION_BLOCK_RESEARCH/structural_blocks.parquet` | `d006-v1`, structural fingerprint `5d5ed7f8...` | `3dbb0a64c46e8df52400b21f821739ba6cd74ed8797d6bd4d24a38034fa4451c` | tracked `schemas.py` SHA `7dab75f0...` | descriptive D006 interaction |

The exact manifest hashes, version-authority paths and hashes, full
version/config strings, required projected columns, and roles are in the
machine-readable registry and are normative; the shortened display values
above are not substitutes. Verification hashes bytes before reading manifest,
version-authority, or Parquet-footer metadata. It then validates the unique
manifest record's SHA and byte size, version/config identity, and the projected
Parquet schema without decoding a data row. Missing artifact, any path-component
symlink, manifest mismatch, schema-identity mismatch, required-column mismatch,
duplicate identity, version mismatch, or artifact-byte drift is
`REPRODUCIBILITY_DEFECT` and must stop historical execution before D007 rows
are decoded.

The registry's `required_columns` tuple is also the complete allowlist for the
future D007 interaction/redundancy loader. That loader must request an explicit
projection and may decode no other column. In particular, fields named
`outcome`, `later_*`, `retrospective_*`, lifecycle outcomes not listed for the
registered role, or other endpoint-like fields are forbidden even though they
may coexist in an authenticated upstream Parquet. Preflight authenticates the
allowlist against footer metadata; a later implementation must test that its
actual projection is a subset of the exact registered tuple.

These `research_outputs` artifacts are ignored local milestone outputs. This
addendum makes their exact current identities mandatory inputs; it does not
claim they are tracked or silently reconstructable. If they are absent, the
future run fails closed rather than regenerating or substituting them.

D005-E1/E3 and the D006 output have provenance histories distinct from the
D007 D003-v1/E4 price lineage. D006 in particular is D003-v2-derived. That
known mismatch is preserved and is why D006 remains descriptive-only. It is not
reinterpreted as a D007-valid standalone composite candidate. No D005/D006
outcome table is an authorized D007 input.

### Outcome-blind reason

The inventory is the smallest set of accepted structural artifacts required by
the original interaction and redundancy registry. Freezing bytes, manifest,
version, schema, projected columns, and role prevents a later artifact choice
from being made after D007 outcomes.

## 7. D006 rejection-block interaction

Only D006 definition `single_wick_50_d3_v1` is eligible. Cluster-two
sensitivity rows are excluded. The imported row must have a non-empty stable
block ID, exact `d006-v1`/registered structural fingerprint, causal five-minute
availability, no pre-availability interaction, and a first causal proximal
touch. Its direction must exactly agree with the D007 range.

Association is evaluated as of the D007 first touch, never from the D006 final
lifecycle label alone. The block must satisfy:

- `causal_availability <= D007 first_touch`;
- `causal_availability >= D007 first_touch - 24 elapsed UTC hours`;
- D006 first touch `<= D007 first_touch`;
- D007 first touch is strictly before D006 expiry deadline; and
- no D006 mitigation, invalidation, or expiry timestamp is `<=` D007 first
  touch.

Thus a block terminal exactly at the D007 touch is ineligible; an event exactly
at the causal-availability boundary is eligible; and expiry exactly 24 hours
after availability is exclusive. Final states `MITIGATED`, `INVALIDATED`, or
`EXPIRED` may appear in the frozen export only when their terminal timestamp is
strictly later than the D007 association instant. Unknown lifecycle states fail
closed.

If multiple blocks are eligible, choose latest causal availability, then
smallest `range`, then lexical `block_id`. This precedence handles nested and
overlapping rows without changing D006's stored identities. Opposite-direction
rows are ineligible, not fallback candidates. No row is selected by later
mitigation, outcome, or performance.

The constituent-only event is that selected block's first causal proximal
touch. The D007-plus-D006 treatment remains the D007 first touch. Both use the
same exact 60-minute direction-aligned endpoint definition and the common
matcher. The interaction requires 100 pairs to calculate its registered
descriptive test, remains in the six-test BH family, and can never establish
`CONDITIONAL_CANDIDATE`, `NON_REDUNDANT_COMPONENT_CANDIDATE`, or production
suitability.

### Outcome-blind reason

The primary D006 definition, 24-hour lifecycle, invalidation/mitigation/expiry
precedence, causal first touch, and deterministic range/ID precedence already
exist upstream. Reconstructing state as of the D007 event prevents later D006
lifecycle information from leaking into membership. The original D006
`SAMPLE_INADEQUATE`, primary `NOT_EVALUATED`, and `INSUFFICIENT_EVIDENCE`
disposition remain unchanged.

## Review gate

This addendum is acceptable only if synthetic tests cover the 18:00/DST/year
boundaries; deterministic control matching and exclusions; constituent
conflicts; D006 lifecycle, direction, multiple-row, and exact-window behavior;
redundancy boundaries; closed hypothesis registries; and provenance drift.
Historical D007 construction, outcomes, controls, interactions, adequacy,
statistics, redundancy results, and publication remain prohibited during this
review.
