# D007 OTE Research Preregistration and Synthetic Structural Preflight

## Status, authorization, and stop boundary

D007 is an additive, research-only component specification. This milestone
freezes definition, provenance, causal construction, lifecycle, controls,
interactions, inference, adequacy, and dispositions; it implements only
synthetic structural preflight. It does not authorize historical D007
execution, a market-data loader, an outcome calculator, a report generator, a
production entry, or a strategy/default change.

The following actions are forbidden in this milestone:

- opening canonical or raw market rows for D007;
- calculating a real OTE range, count, prevalence, touch, or outcome;
- inspecting empirical OTE performance;
- using any 2026 observation for validation;
- creating `research_outputs/D007_OTE_RESEARCH`;
- introducing P&L, expectancy, stop-loss, take-profit, leverage, sizing, order,
  or execution semantics; and
- changing D003-D006 artifacts, manifests, checksums, reports, code, or
  production behavior.

The existing active OTE gate remains controlling. The tracked
`research/event_study_0830_0930/research_gate_assessment.md` authorizes only an
isolated framework, classifies OTE as exploratory entry geometry to be compared
with simpler retracements, and records no reliable evidence that OTE ratios are
superior. `research/OTE/README.md` and `object.toml` remain an unimplemented
`candidate_definition` with decision `not_evaluated`. D007 does not edit or
promote that object.

## Repository state and inherited evidence

The preregistration was created on branch `agent/D007-ote-research` from clean
commit `e49c4d5`, which also matched `main` and `origin/main` at initial
inspection. The immutable antecedents are:

- D003 `d003-v1`, accepted and frozen as the canonical source contract;
- D004, accepted as isolated descriptive manipulation research;
- D005 and E1-E3, research-only context and causal-anchor work with
  `entry_authorized=false`;
- D005_E4, E5, and E6, which freeze the `1h_5m` displacement sequence,
  reporting limitations, and the unproven future-blind boundary;
- D006, whose completed local summary reports `INTEGRITY_VERIFIED`,
  `SAMPLE_INADEQUATE`, primary claims `NOT_EVALUATED`, and component disposition
  `INSUFFICIENT_EVIDENCE`.

D006's tracked specification still contains stale first-stage language that
forbids the historical runner/output later added by tracked commits. D007 does
not resolve or reinterpret that inconsistency. A D006 rejection-block
interaction is therefore exploratory/descriptive only and can never establish
D007 conditional candidacy.

Tracked D003 acceptance names `d003-v1`; ignored local D003-v2 metadata and the
known 2026 work have a separate provenance history. No dataset version is
selected by this synthetic-only milestone. The absent
`automation/config.yaml` is recorded as absent, not reconstructed.

## Source and provenance audit

### Audit procedure and pre-existence boundary

The actual local source directory is `docs/raw_sources/`. It is ignored by Git.
All 43 PDFs were parser-scanned for OTE, Optimal Trade Entry, Fibonacci,
`0.618`, `0.62`, `0.705`, `0.79`, and `0.786`. Relevant pages used below were
then extracted and rendered for visual inspection. The current primary-source
bytes match SHA-256 values already recorded in the tracked D006 source
inventory before D007. This establishes byte identity with pre-D007 repository
evidence; it does not make the ignored PDF payloads tracked dependencies or
establish the date on which a local copy arrived.

### Sources used for D007 rules

| Filename | SHA-256 | Relevant PDF page/section | Conceptual claim actually supported | Numerical value directly supported? | Pre-D007 repository evidence? |
|---|---|---|---|---|---|
| `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | `0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0` | PDF pp. 221-229, especially p. 222 (printed p. 221), pp. 224 and 227 | OTE is a deep Fibonacci retracement of a directional swing; draw low-to-high for bullish and high-to-low for bearish; use trend/structure and confluence; premium/discount is oriented around equilibrium | Yes: band `0.62-0.79`, reference `0.705`, equilibrium `0.50`; p. 222 also calls `0.705-0.79` discount for bullish and premium for bearish | Yes: exact hash recorded in tracked D006 source audit before D007; earlier tracked event-study definition also recorded `0.62-0.79` and `0.705` |
| `EKINYZBB BOOTCAMP SERISI.pdf` | `6fd9c61fb7956ce2e31a3cbf94f1edcfe405325dccd5693bc4b95635100d59ae` | PDF p. 12 | OTE is a Fibonacci setting drawn low-to-high for long and high-to-low for short, from swing low/high; displacement and FVG are described as context | Yes: `0.79`, `0.705`, and `0.62` are named retracement levels | Yes: exact hash recorded in tracked D006 source audit before D007 |

### Relevant sources audited but not used as D007 numerical authority

| Filename | SHA-256 | Relevant pages | Audit conclusion |
|---|---|---|---|
| `Mastering ict.pdf` | `7f380e5abca325db845270cb76e6c1fe04ae64290822d7f28ccaeba32ab287b3` | 10-11 and related range/P-D sections | Supports dealing-range and premium/discount context, but not an exact D007 OTE detector or causal range selector. |
| `Smart Money Concept (SMC) Trading.pdf` | `eee94a43c182ae92802ec83aecf4421ddf0ed64cdfceeb7ab075dc2df21b304e` | 134, 141, 143, 146, 148 | Discusses `0.618` Fibonacci examples and also acknowledges reversals need not occur there. It does not define the source-supported D007 `0.62-0.79` family. |
| `Trade Stocks and Commodities With the Insiders.pdf` | `e0cb141f9b3dc2573d3daac935227910030a2ac2e67c18bdfa8328c22d8bec19` | 203-208 | Presents contrary evidence/argument that Fibonacci retracements are not privileged. It reinforces the requirement to test incremental value; it supplies no D007 detector rule. |
| `IPDA_-Market_Cycle.pdf` | `63179e0340e1d78f01b8b1c28a4e55c350bdc7af4a66ad6ea28b0c2acbf97857` | 15-16 | Supports expansion/retracement vocabulary only; no OTE boundaries or causal range selector. |

An existing tracked event-study operationalization at
`research/event_study_0830_0930/concept_definitions.md` defines the same
`0.62-0.79` candidate band and `0.705` sensitivity on a fixed 08:30 impulse.
Its strategy implementation reduces the OHLC zone's first entry to a `0.62`
proxy and emits `0.705` separately. That is exploratory historical research,
not a frozen D005 feature and not D007 outcome evidence. D007 inherits only the
already-recorded source geometry and causal principle; it registers a different
upstream range before any D007 outcome access.

### Closed provenance vocabulary and criterion register

Every D007 rule uses exactly one of:

- `DIRECT_SOURCE_DEFINITION`
- `INHERITED_FROZEN_PROJECT_CONVENTION`
- `NEW_D007_PREREGISTERED_OPERATIONALIZATION`
- `UNSUPPORTED`

| Criterion | Exact evidence | Classification | Numerical rule directly supported? | Selected before D007 outcome access? |
|---|---|---|---|---|
| OTE as directional swing retracement geometry | ICT PDF pp. 221-227; Bootcamp p. 12 | `DIRECT_SOURCE_DEFINITION` | N/A | Yes |
| Inclusive primary band `0.62-0.79` | ICT PDF p. 222 | `DIRECT_SOURCE_DEFINITION` | Yes | Yes |
| `0.705` central/reference geometry | ICT PDF p. 222; exact arithmetic midpoint of `0.62` and `0.79` | `DIRECT_SOURCE_DEFINITION` | Yes | Yes |
| Bullish low-to-high / bearish high-to-low symmetry | ICT PDF pp. 224-227; Bootcamp p. 12 | `DIRECT_SOURCE_DEFINITION` | Directional construction, not a fitted number | Yes |
| `0.50` equilibrium/premium-discount reference | ICT PDF pp. 224, 227; D005 audit A17-A18 | `DIRECT_SOURCE_DEFINITION` | Yes | Yes |
| Five-minute closed-bar input and UTC availability | D005 context-engine bar contract | `INHERITED_FROZEN_PROJECT_CONVENTION` | Five minutes existed before D007 | Yes |
| Primary upstream `1h_5m` displacement-confirmation sequence | D005_E4 frozen sequence and direction contract | `INHERITED_FROZEN_PROJECT_CONVENTION` | Mapping and confirmation existed before D007 | Yes |
| Latest already-confirmed opposite swing as origin | D005 width-two confirmed-swing mechanism plus D007 selection rule | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No authoritative OTE source supplies this selector | Yes |
| Furthest directional extreme through frozen displacement availability as endpoint | D007 causal range rule | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No | Yes |
| No extension after range availability | D007 immutability rule | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No | Yes |
| Invalidation on first later close beyond origin | D007 lifecycle rule | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No; it is not a trade stop | Yes |
| Expiry at 24 elapsed UTC hours | Reusable D006 lifecycle convention | `INHERITED_FROZEN_PROJECT_CONVENTION` | Existing project number, not direct OTE source | Yes |
| First-touch/repeated-touch semantics and event precedence | D007 lifecycle rule | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No | Yes |
| Matching, 60-minute endpoint, 95% confidence, 2,000 date bootstraps, BH at 0.05 | Frozen D005_E4/D006 inference conventions | `INHERITED_FROZEN_PROJECT_CONVENTION` | Not an OTE source rule | Yes |
| Bootstrap and deterministic-control seed `7007` | D007 preregistration | `NEW_D007_PREREGISTERED_OPERATIONALIZATION` | No source privileges this seed | Yes |

No required primary criterion is `UNSUPPORTED`. Configuration validation fails
closed if a required criterion is changed to `UNSUPPORTED`. The direct source
supports the OTE concept and numbers; it does not support the causal selector,
lifecycle, controls, inference, adequacy, or disposition rules.

## Research object and exact geometry

D007 does not test whether a Fibonacci number is inherently predictive. It
tests whether a causally observable deep-retracement geometry provides
incremental information after the same frozen upstream directional impulse.

For direction `d` (`+1` bullish, `-1` bearish), origin `O`, endpoint `E`, and
range magnitude `R = abs(E-O)`, retracement price at depth `r` is:

```text
L(r) = E - d * r * R
```

The research object records:

- frozen D005 upstream event ID, mapping, event type, and direction;
- origin price/time and its prior confirmation/availability time;
- endpoint price/time;
- range availability timestamp;
- geometry ID, proximal `L(0.62)`, reference `L(0.705)`, distal `L(0.79)`,
  equilibrium `L(0.50)`, and ordered price-zone bounds;
- first causal touch, repeated-touch count, invalidation, expiry, and terminal
  accounting;
- stable range ID, overlap-group ID, parent range ID, and source-bar IDs; and
- pre-availability retracement-interaction flag.

The primary geometry is the inclusive band `[0.62, 0.79]`. `0.62` is proximal
because it is encountered first when price retraces from the endpoint;
`0.79` is distal. `0.705` is the band reference. The sole fixed sensitivity is
the point geometry `0.705`. Geometry is an explicit multiple-testing dimension.
No `0.618`, `0.786`, `0.75`, or neighboring value is a D007 confirmatory
variant, and no boundary may move after outcomes.

For bullish legs, equilibrium and the OTE band are below the endpoint and the
band is discount-oriented. For bearish legs they are above the endpoint and
premium-oriented. This symmetry is formulaic; the price bounds are always
stored low-to-high regardless of direction.

## Primary causal upstream range

The sole primary construction uses the frozen D005_E4 `1h_5m` sequence:

1. Start from a non-neutral D005 `displacement_confirmation` event whose
   candidate, body-close MSS, and displacement directions agree under the
   frozen sequence contract.
2. On the five-minute reaction bars, select the latest opposite-side swing
   whose width-two right-side confirmation was available no later than the
   displacement bar's creation time. Bullish uses the confirmed swing low;
   bearish uses the confirmed swing high. This is the origin.
3. The endpoint is the furthest directional wick extreme from the displacement
   creation bar through the final closed bar that makes the frozen D005
   displacement event available. This includes only the already-frozen
   immediate-retracement confirmation interval.
4. Range availability is the D005 displacement `available_at`, which must be no
   earlier than both endpoint-bar closure and origin confirmation. The OTE
   range does not exist before that timestamp.

The primary selector never uses a later swing, later refinement, first OTE
touch, later range extension, endpoint outcome, or final lifecycle label. It
has no swing-algorithm family and no sensitivity range construction.

All required bars must be complete, uniquely identified, strictly ordered,
five-minute, and closed by the declared availability. Missing origin,
displacement creation bar, confirmation-tail bar, direction agreement, or
complete data fails construction. Future bars may be present in a synthetic
fixture only to prove that they are discarded before OHLC inspection.

Directional extremes occurring inside the upstream confirmation interval are
included before availability. Once `AVAILABLE`, origin and endpoint are
immutable even if price extends before first touch. A later extension can
create a new opportunity only through a distinct frozen D005 upstream event.

Exactly one band opportunity and one registered `0.705` sensitivity
opportunity exist per upstream event. Repeated touches do not create new
opportunities. Exact duplicate `(upstream event, geometry)` objects are
deterministically excluded; conflicting reconstructions are a reproducibility
defect. Multiple events on the same day are preserved. There is no
one-trade-per-day rule.

Same-direction zones use closed-interval connected components for overlap.
Strict containment records the smallest containing parent. Opposite directions
remain distinct. Primary empirical deduplication retains the earliest
available primary-band object within the same overlap group and direction,
then orders by stable ID. Distinct `0.705` sensitivities remain a separate
geometry cohort.

## Lifecycle and causal touch semantics

The lifecycle starts at `AVAILABLE`. A bar is eligible only if its open is no
earlier than range availability and its complete close/`available_at` is known
at evaluation. Once the final endpoint bar has formed, any retracement into the
eventual zone on a later construction/confirmation bar strictly after that
endpoint bar is marked `preavailability_interaction`; the range is retained for
audit but excluded from the primary lifecycle-eligible cohort. The outbound
displacement bar and the selected endpoint bar are not touches: the range does
not yet exist, and their high-low span cannot establish post-endpoint
retracement ordering from OHLC.

A touch is inclusive OHLC overlap with the ordered zone. The event timestamp
is the touching five-minute bar's `available_at`; the causal reference price
for a later empirical endpoint is that bar's close. The first eligible overlap
is the first touch. Later overlaps increment an audit count but never create a
new primary observation.

Invalidation is the first later complete five-minute close strictly beyond the
origin against direction: below origin for bullish and above origin for
bearish. Origin equality does not invalidate. This is structural acceptance
through the entire impulse, not a stop or execution instruction.

Expiry is exactly 24 elapsed UTC hours after availability. A bar that closes
after the deadline is not used to infer an intrabar pre-deadline event.

Same-bar precedence is fail-closed:

1. expiry/deadline exclusion;
2. close-based invalidation;
3. inclusive zone touch.

Thus a bar that both overlaps the zone and closes beyond origin invalidates and
does not add a touch. Existing earlier touch timestamps remain auditable if a
later bar invalidates. Incomplete eligible bars fail lifecycle evaluation;
they are not treated as untouched.

## Frozen scientific claims and endpoint

### Primary structural claim

> D007 OTE ranges can be constructed causally and reproduced byte-identically,
> with stable identities and reconciled lifecycle accounting, at adequate
> sample across 2022-2025, both directions, and every required session.

Synthetic fixtures prove only implementation semantics. A later separately
authorized historical run must satisfy integrity, adequacy, exact repeated-run
identity, zero causal/order violations, all year/direction/session minimums,
and reconciled counts before this claim can pass.

### Primary empirical claim

> Among deduplicated, lifecycle-eligible primary-band ranges with a first
> causal touch, mean 60-minute direction-aligned close-to-close movement after
> the touch is greater than the preregistered matched equilibrium-retracement
> control from the same frozen upstream event class, and the paired increment
> is temporally and directionally stable.

The event timestamp is the first-touch bar `available_at`; reference is that
bar's close. The endpoint is the last complete five-minute close at exactly
60 elapsed minutes. Movement is `d * (endpoint close - reference close)` in
XAUUSD price units. All 13 availability timestamps from event through endpoint
at five-minute spacing must exist; no interpolation or imputation is allowed.
Validation year is the year of the named `America/New_York` trading date, not
the UTC calendar year. Every required endpoint timestamp must remain within a
registered New York validation year, so an interval crossing into named-year
2026 is ineligible.
The current package implements timestamp eligibility only and accepts no OHLC
endpoint value.

The estimand is the mean within-pair OTE-minus-control difference. No other
horizon, reference, direction relabeling, subgroup, geometry, or endpoint can
replace it after outcome access.

## Controls and deterministic matching

All control variables must be known at the candidate event. Matching is 1:1,
without replacement within a family, on a different named New York trading
date, within plus/minus 30 calendar days, and with exact:

- validation year;
- frozen D005 session;
- direction;
- causal volatility bucket (latest complete daily range divided by the median
  of the previous 20 complete daily ranges: low `<0.75`, normal
  `0.75-1.25`, high `>1.25`, unavailable);
- upstream mapping `1h_5m`; and
- elapsed availability-to-event bucket: `[0,30)`, `[30,60)`, `[60,180)`, or
  `[180,1440]` minutes.

Candidates within 120 minutes of an unrelated OTE first touch, whose own OTE
band was already touched by the candidate timestamp, or without complete
endpoint timestamps are ineligible. The control range may be `AVAILABLE` - and
must be available for its equilibrium to be causal - but its own OTE band must
remain untouched at the control event. Ordering is the lowest SHA-256 of
`7007 | control family | treatment range ID | candidate timestamp`. A missing
match is `missing_control`; no replacement stratum is searched.

The fixed controls are:

1. `matched_equilibrium_50`: primary; first causal `0.50` equilibrium touch on
   a different eligible D005 upstream impulse while its OTE zone remains
   untouched at the control event.
2. `upstream_no_ote_touch`: structural adequacy/control denominator only;
   lifecycle-eligible upstream ranges that expire or censor without OTE touch.
   It has no invented event timestamp and is not used for the primary endpoint.
3. `matched_context_without_ote`: frozen D005 `reaction_confirmed` event with no
   prior OTE touch, matched at its causal timestamp; incremental secondary.
4. `matched_displacement_availability`: another frozen D005 displacement
   availability with no prior OTE touch at that timestamp; incremental
   secondary.
5. `matched_time_session_volatility`: audit view of the exact primary matching
   constraints; it cannot change pairs.
6. `direction_balanced`: deterministic equal-direction reweighting audit; it
   cannot change the primary paired sample.

No control family may be selected by performance. There is no random-level or
random-time search in D007.

## Fixed interaction family

No combination outside this table is a D007 test.

| Interaction | Causal eligibility | Direction | Role | Minimum pairs |
|---|---|---|---|---:|
| `ote_alone` | Primary band first causal touch | OTE/upstream | Primary | 500 |
| `aligned_d005_context` | Latest `reaction_confirmed` D005 state and all evidence available no later than range availability | Exact agreement | Confirmatory secondary | 200 |
| `after_d004_manipulation` | Frozen causal D004 sweep/re-entry state complete strictly before range availability on same named date; retrospective day label forbidden | Exact agreement | Exploratory | 100 |
| `frozen_liquidity_sweep` | Frozen sweep evidence available and not invalidated by range availability | Exact agreement | Confirmatory secondary | 200 |
| `refinement_confirmation` | Frozen refinement creation/confirmation available no later than first touch | Exact agreement | Confirmatory secondary | 200 |
| `d006_rejection_block` | D006 block causally available no later than first touch | Exact agreement | Exploratory/descriptive only because D006 is `INSUFFICIENT_EVIDENCE` | 100 descriptive |
| `against_d005_context_negative_control` | Non-neutral D005 context available by range availability | Exact disagreement | Confirmatory negative control | 200 |

The upstream D005 displacement is mandatory for every D007 range, not an
optional interaction. Interactions are evaluated individually; no conjunction
or combination search is permitted. D004 and D006 rows cannot alone produce
`CONDITIONAL_CANDIDATE`.

## Redundancy and incremental-value plan

Before effect estimates, report structural overlap, exact denominators, and
signed causal time differences against:

- D005 displacement confirmation and strength;
- body-close MSS;
- refinement-array creation/confirmation;
- raw and qualified FVG;
- frozen liquidity-sweep state;
- D005 context direction/session;
- D006 rejection block, descriptively only;
- equilibrium/premium-discount position; and
- continuous retracement depth and availability-to-touch time.

OTE may merely encode generic displacement retracement, premium/discount,
pullback depth, session, context, or liquidity behavior. Structural overlap is
not incremental value. A standalone positive mean is insufficient. Candidate
status requires the registered paired comparison plus an ablation on identical
constituent-feature cohorts. No black-box feature importance, feature-set
search, threshold search, or post-outcome covariate selection is allowed.

## Statistical conventions

- Confidence level: 95%.
- Primary test: two-sided paired Student t-test of OTE-minus-control
  differences at alpha `0.05`; the mean must be positive, the 95% interval
  lower bound above zero, and p-value below `0.05`.
- Bootstrap: 2,000 New York-trading-date resamples preserving all same-date
  pairs, base seed `7007`, SHA-256-derived cell seeds. The primary bootstrap
  lower bound must exceed zero.
- Multiple testing: primary is one unadjusted test. Six non-standalone
  interactions are one Benjamini-Hochberg family at `q=0.05`, including
  missing/not-evaluated and exploratory rows. Two fixed incremental-control
  comparisons are one BH family. Band-versus-`0.705` touch incidence,
  time-to-touch, and direction-aligned movement are one three-test geometry BH
  family.
- Time splits: mandatory 2022, 2023, 2024, and 2025. 2026 is forbidden.
- Direction splits: mandatory bullish and bearish.
- Session splits: the five frozen D005 labels; maintenance is descriptive and
  not required for adequacy.
- Stability: required sign in at least three of four adequate years and no
  adequate year with a 95% interval wholly in the opposite direction; both
  direction cohorts must have the required sign and neither may be
  significantly opposite.
- Bootstrap unit: named New York trading date, preserving within-date event
  dependence.
- Finite-value policy: primary retains every finite value, performs no
  effect-based trimming, and excludes non-finite values with one first-failure
  reason. Median, IQR, 1% symmetric trimmed mean, and largest-1%-absolute
  removal are descriptive sensitivities only.
- Endpoint policy: 100% timestamp coverage within every decisional matched
  pair; no imputation, carry-forward, interpolation, or horizon substitution.

No inference code or historical outcome path exists in this milestone.

## Sample-adequacy gate

These thresholds are frozen without reading D007 outcomes:

| Requirement | Minimum |
|---|---:|
| Constructed primary-band ranges | 1,000 |
| Lifecycle-eligible primary-band ranges | 800 |
| First causal primary-band touches | 500 |
| Untouched/control observations when required | 200 |
| Endpoint-complete primary pairs | 500, exact 1:1 |
| Primary pairs per validation year | 100 in each of 2022-2025 |
| Primary pairs per direction | 200 bullish and 200 bearish |
| Touches per required session | 50 in asia, premarket, ny_observation, ny_afternoon |
| Each confirmatory interaction | 200 pairs |
| D004 exploratory interaction | 100 pairs |
| D006 descriptive interaction | 100 observations; never decisional |
| Each geometry cohort | 200 |
| Primary endpoint coverage | 100% |

Each confirmatory claim and geometry cohort must meet its own threshold; pooled
adequacy cannot rescue an inadequate stratum. If global adequacy fails,
primary status is `NOT_EVALUATED`, all numeric output is
`DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE`, no positive result is OTE
evidence, and no candidacy can be inferred.

## Fail-closed component dispositions

Exactly one disposition is assigned in this priority order:

1. `REPRODUCIBILITY_DEFECT`: protected/source/spec/config/implementation
   integrity fails; repeated construction differs; a causal, ID, lifecycle,
   order, completeness, endpoint, or reconciliation invariant fails; or a
   forbidden input/output path is accessed.
2. `INSUFFICIENT_EVIDENCE`: integrity passes but global adequacy, endpoint
   coverage, structural claim, or a required year/direction/session cannot be
   evaluated.
3. `NON_REDUNDANT_COMPONENT_CANDIDATE`: structural and primary claims pass;
   primary and registered incremental comparisons survive their rules; year
   and direction stability pass; and no frozen constituent fully accounts for
   the increment.
4. `CONDITIONAL_CANDIDATE`: structural claim passes and at least one adequate
   confirmatory non-D004/non-D006 interaction improves over its matched
   constituent control, survives BH, is stable, and is non-redundant even if
   standalone evidence is weak.
5. `GEOMETRY_CANDIDATE`: structural claim passes and the adequate registered
   band-versus-`0.705` geometry rule survives its three-test BH family with
   stable non-inferior directional movement, even if standalone directional
   evidence is weak.
6. `REJECT_COMPONENT`: global adequacy and structural claim pass; the primary
   paired-difference 95% upper bound is at most zero; at least three of four
   yearly means are non-positive; and no non-redundant, conditional, or
   geometry rule passes.
7. `STRUCTURALLY_VALID_EMPIRICALLY_WEAK`: structural claim passes but no
   candidate or deterministic rejection rule above passes.

No disposition authorizes production use.

## Synthetic implementation and guardrails

The additive package `research/d007_ote_research/` contains only:

- fixed configuration/provenance/interaction registries;
- immutable bars, upstream anchors, ranges, stable IDs, overlap, and nesting;
- causal range and fixed-geometry construction;
- deterministic lifecycle and deduplication;
- metadata-only control, interaction, endpoint-eligibility, adequacy, and
  disposition helpers; and
- static/hash-only preflight.

It intentionally contains no `__main__`, CLI, historical source loader,
pipeline, outcome, statistics, report, runner, or output module. Static
preflight rejects such modules, market/outcome table calls, imports from
historical research packages, canonical/raw/output path literals, protected
hash drift, raw-source hash drift, D007 output directories, 2026, and any
changed path outside D007 ownership.

Synthetic tests must cover bullish/bearish construction, exact boundary
inclusion/exclusion, availability, future mutation, incomplete construction and
lifecycle data, fixed extension semantics, first/repeated touch, invalidation,
expiry, precedence, stable IDs, deterministic deduplication, overlap/nesting,
same-impulse fixed geometries, control eligibility/selection, interaction
causality, endpoint timestamp eligibility, 2026/history/output forbiddance, and
unsupported provenance.

## Protected boundaries and acceptance criteria

Protected tracked fingerprints include the relevant D003-D006 specifications,
D005 context implementation, event-study OTE definition/implementation and
gate, OTE placeholder, and production strategy. Static preflight verifies them.
Static preflight also verifies five frozen D003-v2 canonical/release metadata
hashes plus a frozen count and aggregate SHA-256 over every ignored non-table
artifact beneath `research_outputs`. The aggregate is the SHA-256 of sorted
`relative-path<TAB>file-SHA-256` lines; Parquet, CSV, Feather, Arrow, bytecode,
and `__pycache__` payloads are excluded. Canonical/raw market payloads are
neither opened nor rewritten.

D007 preregistration/preflight is acceptable only when:

1. source bytes and page-level claims are recorded without quantitative
   overclaim;
2. every required criterion has one closed provenance classification and none
   is `UNSUPPORTED`;
3. geometry, upstream range, lifecycle, claims, controls, interactions,
   redundancy, statistics, adequacy, and dispositions are frozen;
4. focused synthetic and D005/D006 guardrail tests pass;
5. full repository tests, static preflight, protected fingerprints,
   `git diff --check`, and new-file whitespace checks pass;
6. an independent read-only verifier finds no leakage, protected-path,
   provenance, methodology, or test defect;
7. no historical D007 outcome or prohibited real prevalence/count is produced;
8. 2026 is not used; and
9. no production file/default changes.

Passing this milestone means only that the D007 definition and synthetic
guardrails are reviewable. Historical D007 execution requires a separate
explicit authorization after this specification is frozen and after the
D003-v2 provenance, missing automation manifest, D006 spec/execution
inconsistency, and future-blind boundary are independently reviewed.
