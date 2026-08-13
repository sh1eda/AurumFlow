# D007 Association Identity Clarification Addendum

## Status, scope, and authority

This is a chronological, outcome-blind addendum to
`docs/D007_OTE_RESEARCH_SPEC.md`,
`docs/D007_HISTORICAL_EXECUTION_CONTRACT.md`, and
`docs/D007_METHODOLOGY_CLARIFICATION.md`. It resolves only the previously
unspecified association identities between D004/D006 constituent events and
frozen D005-E4 displacement sequences. Previously frozen D007 geometry,
selectors, lifecycle, controls, interactions, adequacy, inference, outcome,
interval, disposition, and production boundaries remain unchanged.

At authorship, no D007 historical outcome had been accessed, constructed, or
computed. No empirical D007 control, interaction, adequacy cell, statistic,
redundancy result, or historical output package was produced. No candidate
rule was inspected against sample size or performance. This addendum uses only
accepted upstream methodology, authenticated artifact schemas and identities,
causal timing conventions, and synthetic tests.

Historical D007 execution remains forbidden until this addendum is reviewed
and merged. The empirical historical pipeline is outside this task and must
not be restored or imported into this clarification diff.

## Blocker and repository evidence

The D004 `daily_events.parquet` schema has no D005 `sequence_id`,
`candidate_id`, `mss_id`, `displacement_id`, confirmation-event ID, or anchor
ID. Its authoritative constituent is instead one accepted named-date/side row
with one-minute sweep and completed-re-entry timestamps. D004 is derived from
accepted D003 `d003-v1` bars.

The D006 `structural_blocks.parquet` schema has a stable `block_id`, D006
source-bar IDs, an expansion-bar ID, and causal timestamps, but no D005-E4 ID.
D006 was independently built from D003-v2 and its IDs have a different
namespace from D005-E4's D003-v1/D005 lineage. Byte identity across that
cross-milestone event boundary is not an accepted identity authority.

D005-E4 supplies the exact accepted sequence and displacement identity chain:

`eligible_sequences.sequence_id`
→ `eligible_sequences.displacement_confirmation_event_id`
→ exact `displacement_anchors.sequence_id`
→ `displacement_anchors.anchor_event_id` / `anchor_at`.

The two E4 tables must be hash-authenticated first and joined exactly on the
unique `sequence_id`. Mapping, direction, causal-eligibility flags, and anchor
time must agree. Zero or multiple anchor rows, conflicting identities, or
schema/hash drift is `ambiguous_or_invalid_e4_identity` and fails closed.
No E4 outcome, retrospective, later-state, MFE, MAE, or forward field is
authorized.

Because neither constituent artifact exposes a shared E4 ID and no accepted
reconstruction produces one, exact ID-only association is impossible. The
following temporal bridges are explicitly new outcome-blind clarifications;
they are not represented as original preregistered rules. They use exact
windows and deterministic precedence rather than a generic configurable
nearest-time matcher.

For only the `after_d004_manipulation` and `d006_rejection_block` constituent
relationships, this addendum supersedes the generic exact-ID-only candidate
association sentence in `D007_METHODOLOGY_CLARIFICATION.md` section 2 because
repository evidence proves that neither authenticated constituent carries an
E4 ID. The exact-ID rule remains unchanged for every relationship that exposes
one. This exception does not reinterpret a temporal match as lineage: output
provenance must label it `new_outcome_blind_temporal_association_v1`. No other
frozen D007 rule is changed.

## Common E4 eligibility and identity

An association candidate is one authenticated E4 row satisfying all of:

1. `mapping_variant == "1h_5m"`;
2. non-empty unique `sequence_id`;
3. non-empty `displacement_confirmation_event_id`;
4. an exact one-row `displacement_anchors.sequence_id` join;
5. `main_scope_eligible == true`;
6. `anchor_causally_observable == true`;
7. `anchor_selected_using_later_completion == false`;
8. exact direction agreement between the E4 sequence and anchor; and
9. timezone-aware causal `anchor_at`, a frozen D005 session consistent with
   that instant, and the stored E4 `anchor_year` consistent with the local
   calendar year used upstream. D007 validation year is derived separately
   from the established 18:00-roll named date; the two are both retained and
   are not silently conflated at the year-end boundary.

Every successful association is one constituent event to exactly one E4
sequence. Several constituent events may resolve to the same E4 sequence
(many-to-one), but one constituent event is never expanded into multiple
candidate observations. This preserves the common 1:1-without-replacement
control matcher: the no-replacement key is the association ID, and one
physical constituent event has only one such ID per family.

The stable association ID is the lowercase hexadecimal SHA-256, prefixed by
`d007-assoc-`, of UTF-8 text joined with literal `|`:

`D007_ASSOCIATION_IDENTITY_CLARIFICATION_V1|family|constituent_id|sequence_id|displacement_confirmation_event_id`.

Input row order is never part of identity or precedence.

## D004 daily event → D005-E4 sequence

### Authoritative constituent identity and availability

Each accepted D004 row may emit at most one `high` and one `low` completed
sweep/re-entry constituent:

- high side has direction `-1`; low side has direction `+1`;
- stored `trading_date` is the 18:00-roll New York named date;
- `sweep_at` is the corresponding `high_sweep_time` or `low_sweep_time`;
- the stored re-entry time is the one-minute bar left edge;
- causal `available_at` is re-entry time plus exactly one minute; and
- constituent ID is `d004:<trading_date>:<side>`.

The event identity also retains `primary_reference_name`. A missing timestamp,
false sweep/re-entry flag, side/direction conflict, named-date conflict, or
noncausal `sweep_at >= available_at` is rejected before association.

### Frozen association algorithm

For one D004 constituent:

1. start with the common eligible E4 universe;
2. require exact direction agreement;
3. require the same 18:00-roll New York named trading date;
4. require elapsed UTC minutes `D004 available_at - E4 anchor_at` in the closed
   interval `[0, 1440]`; and
5. select the maximum E4 `anchor_at`, breaking an equal-time tie by lexical
   `displacement_confirmation_event_id`, then lexical `sequence_id`.

This is a latest-prior causal bridge, not an unrestricted nearest-time rule.
The exact temporal window is the intersection of the same named trading date
and `[D004 available_at - 1440 minutes, D004 available_at]`. Both elapsed
boundaries are inclusive, matching the existing nonnegative `[0,1440]`
availability-to-event contract. The named-date boundary is exact and uses IANA
timezone rules. No future E4 anchor is eligible. There is no fallback to
another date, opposite direction, relaxed mapping, later-completion row,
trading-date-only duplicate, or unbounded search.

If multiple E4 sequences exist, latest-prior and lexical precedence
selects exactly one; this is not ambiguity. No qualifying E4 row records one
of the closed reasons `no_eligible_e4_sequence`, `direction_mismatch`,
`named_date_mismatch`, or `no_prior_e4_in_1440m_window`, and the D004
constituent is ineligible for a D007 constituent-control candidate. It remains
in candidate/failure audits and never counts toward adequacy.

Session equality is not an extra D004 association predicate. The D004
interaction authority is same named date plus exact nonfuture causal
precedence; the
selected E4 row supplies the frozen session and validation year used by the
common D007 matcher. Adding a same-session condition would be a new scientific
restriction unsupported by D004's daily-context role.

## D006 structural block → D005-E4 sequence

### Authoritative constituent identity and lifecycle

The authoritative identity is D006 `block_id`, backed by its ordered
`source_bar_ids`, `expansion_bar_id`, and exact
`confirmation_timestamp == causal_availability`. Only
`single_wick_50_d3_v1` is eligible. Direction must be exact. The block must
have no pre-availability interaction and must have a first causal proximal
touch.

At the constituent event (that first touch), the block must satisfy the
already-frozen lifecycle:

- availability is no later than first touch;
- first touch is strictly before the 24-hour expiry deadline;
- no mitigation, invalidation, or expiry timestamp is at or before first
  touch; and
- a later final terminal state may be present only when its timestamp is
  strictly after the constituent event.

Equality at a terminal or expiry boundary is ineligible. Cluster-two rows,
opposite direction, unknown lifecycle, and missing source identity fail closed.
D006's standalone `INSUFFICIENT_EVIDENCE` disposition remains unchanged.

### Frozen association algorithm

For one lifecycle-eligible D006 block:

1. use the common eligible E4 universe;
2. require exact direction agreement;
3. require E4 and D006 causal availability to have the same 18:00-roll New
   York named date;
4. require the same frozen D005 session label;
5. require
   `D006 causal_availability - 60 minutes <= E4 anchor_at < D006 causal_availability`;
6. select the maximum E4 `anchor_at`; and
7. break an equal-time tie by lexical
   `displacement_confirmation_event_id`, then lexical `sequence_id`.

The association distance is elapsed UTC minutes from the E4 displacement
anchor to D006 causal availability. The common matcher elapsed value remains
E4 anchor to the constituent event at D006 first touch; both values must be
emitted separately. The 60-minute lower boundary is inclusive, reusing
D006's frozen causal context/redundancy window. The upper boundary is exclusive
because D006's confirmation/expansion bar is not permitted to masquerade as a
prior constituent displacement when cross-lineage IDs cannot prove that it is
distinct. There is no fallback beyond 60 minutes, across a date/session,
against direction, or to the same-time bar.

If multiple E4 candidates exist, latest/lexical precedence selects exactly
one. No qualifying row records `no_eligible_e4_sequence`, `direction_mismatch`,
`named_date_or_session_mismatch`, or `no_prior_e4_in_60m_window`. A
lifecycle-ineligible block records `lifecycle_ineligible_block`. Excluded
blocks remain in failure audits and never count toward adequacy.

When multiple blocks are evaluated for D007-plus-D006 treatment membership,
the previously frozen selection remains latest causal availability, then
smallest range, then lexical `block_id`, after exact direction and lifecycle
filters. The selected block's association is then resolved by the algorithm
above. This addendum does not retune that precedence.

## Required association provenance

Every successful association row must emit all of:

- authority ID and association ID;
- family (`d004` or `d006`);
- constituent ID and exact constituent event timestamp;
- constituent artifact path and SHA-256;
- D004 side, reference name, sweep time, re-entry time, and named date, or
  D006 block ID, source-bar IDs, expansion-bar ID, confirmation/availability,
  first touch, lifecycle timestamps, range, and definition;
- E4 `sequence_id`, `anchor_event_id`,
  `displacement_confirmation_event_id`, and `anchor_at`;
- E4 artifact paths and SHA-256 values for both authenticated E4 tables;
- exact direction, E4 session, stored upstream anchor year, derived D007 named
  date/validation year, constituent named date, and mapping;
- association-reference timestamp, signed association-distance minutes,
  nonnegative E4-availability-to-constituent-event minutes, and the fixed
  precedence version; and
- source milestone versions/config fingerprints already frozen by the prior
  clarification registry.

Every excluded row must emit constituent ID, family, authority ID, the first
closed exclusion reason, and causal event timestamp. Run/source provenance
must identify this addendum and implementation bytes in addition to the prior
preregistration, historical contract, and methodology clarification. No
absolute checkout path is an identity field.

## Projection allowlist clarification

`research/d007_association_identity.py::ASSOCIATION_PROJECTIONS` is the complete
association-role allowlist. Reads must name a non-empty explicit projection;
`columns=None`, whole-table reads, and non-allowlisted columns fail before
Parquet decoding. Existing artifact hashes, manifests, schema identities, and
prior role-specific columns remain frozen.

The only newly permitted columns are:

| Artifact | Column | Causal need and safety |
|---|---|---|
| D004 `daily_events.parquet` | `primary_reference_name` | Authenticates which already-frozen reference the sweep/re-entry identity used; known at event time, not an outcome. |
| D004 `daily_events.parquet` | `high_sweep_time` | Provides source-event identity and proves sweep precedes high-side re-entry; event-time structural timestamp, not retrospective performance. |
| D004 `daily_events.parquet` | `low_sweep_time` | Same for the low-side event; event-time structural timestamp, not retrospective performance. |
| D006 `structural_blocks.parquet` | `source_bar_ids` | Supplies the stable causal bars already hashed into `block_id`; no later lifecycle or outcome content. |
| D006 `structural_blocks.parquet` | `expansion_bar_id` | Supplies the confirming expansion source identity already available when the block exists; not an outcome. |
| D006 `structural_blocks.parquet` | `confirmation_timestamp` | Cross-checks exact causal availability and the strict prior-E4 boundary; known on the confirming bar close. |

No E4 column is newly permitted: the prior clarification already allowlisted
the required exact sequence/displacement identities and anchor provenance
across `eligible_sequences.parquet` and `displacement_anchors.parquet`.
Forbidden examples remain every `outcome`, `later_*`, `retrospective_*`, MFE,
MAE, terminal-R, forward-path, and unregistered lifecycle-outcome field.

## Secondary verifier findings

All five findings are implementation gaps governed by already-frozen rules;
none authorizes a new empirical or scientific choice.

1. **Interaction-specific constituent ablations — `IMPLEMENTATION_ONLY`.**
   `D007_METHODOLOGY_CLARIFICATION.md` sections 4 and 5 require every positive
   interaction to use its own identical-cohort constituent-only ablation, with
   unchanged endpoint, matcher, inference, stability, and non-redundancy rule.
   The D004/D006 ablations remain descriptive/non-decisional. A generic pooled
   ablation cannot substitute.
2. **Geometry movement stability in final geometry decision —
   `IMPLEMENTATION_ONLY`.** Section 3 makes directional movement a mandatory
   non-inferiority guard in `GEOMETRY_CANDIDATE`; the following yearly and
   direction clauses are conjunctive final-decision inputs, not report-only
   fields. For movement, pooled t-interval lower bound must be `>= 0`, no
   adequate yearly interval may be wholly negative, and neither bullish nor
   bearish interval may be wholly negative. A movement q-value cannot create a
   candidate, and omission of any guard prevents candidacy.
3. **E4 session/year provenance for every candidate — `IMPLEMENTATION_ONLY`.**
   Sections 2 and 6 require every event-bearing candidate to have one E4
   association and require that E4 row to supply mapping, session, validation
   year, direction, and availability bucket. This addendum supplies the two
   missing association algorithms; pipeline code must not derive candidate
   strata from D004/D006 local labels or treatment rows.
4. **Separate redundancy price denominator and `price_not_available` —
   `IMPLEMENTATION_ONLY`.** Section 5 requires the complete comparison
   population as the time-association denominator, only authenticated
   price/zone rows as the price-overlap denominator, and missing price geometry
   to be reported as `price_not_available`, never zero overlap.
5. **Full deterministic run/source provenance identities —
   `IMPLEMENTATION_ONLY`.** Section 6 already requires exact bytes, manifests,
   schema/version authorities, role, and projected columns. The required
   association-level fields above specify how that fixed identity inventory is
   carried into the next pipeline without creating a scientific selector.

## Review gate

Acceptance requires synthetic tests for unique/no/multiple association,
direction and date/session mismatch, boundary inclusivity, lifecycle failure,
multiple-block precedence, input-order invariance, stable IDs, explicit
projections, forbidden outcomes, and full-table rejection. Hash-only preflight
must authenticate all prior protected inputs plus this addendum and its
machine-readable authority without decoding D007 rows.

Until review and merge, real D007 OTE construction, lifecycle outcomes,
empirical controls/interactions, adequacy/statistics, and historical output
publication remain forbidden.
