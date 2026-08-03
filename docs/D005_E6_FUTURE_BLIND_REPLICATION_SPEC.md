# D005_E6 Future-Blind Independent Replication Preregistration and Readiness Specification

## Status and scientific purpose

D005_E6 is an additive, planning-and-readiness-only preregistration for a
future evaluation of the frozen historical 60-minute direction-aligned
XAUUSD displacement-anchor effect on a genuinely unseen interval. It does not
execute that evaluation and is not replication evidence.

The immutable antecedents are D003, D004, D005, D005_E1 through D005_E5 and
their tracked specifications, code, manifests, releases, acceptance records,
and protected artifacts. The first 2026 D005_E4 execution is outcome-known:
integrity was `INTEGRITY_VERIFIED`, adequacy was
`INDEPENDENT_SAMPLE_INADEQUATE`, and the primary result was `NOT_EVALUATED`.
D005_E4 and the post-outcome D005_E5 hardening remain non-accepted as
independent replication evidence.

E6 must not repair or reinterpret E4, use the observed E4 outcomes to change a
hypothesis or threshold, reuse any part of the observed 2026 interval as blind
data, or claim independence for any date whose outcome was previously
accessed. It must not add trade, P&L, execution, return, R, expectancy,
profit-factor, stop, target, fill, sizing, fee, or slippage semantics. It must
not create an A/B/C classification unless a separate deterministic temporal
rule is frozen before future outcome access.

The production recommendation remains **continue research only** until a
future preregistered evaluation is completed and accepted.

## Outcome-access prohibition

E6 contains no scientific execution path. Permitted activity is limited to
source and manifest inspection, file-path and filesystem-metadata inspection,
previously frozen aggregate-count analysis, deterministic planning,
preregistration fingerprinting, and readiness checks that do not decode market
rows.

E6 must not read a future Parquet payload; decode a market-price row; build a
future bar; construct or count a future anchor; count future endpoint
eligibility; calculate a future return, MFE, MAE, effect size, interval,
p-value, bootstrap, direction/session/month statistic, or adequacy result; or
generate a scientific report. It creates no scientific output directory.

## Metadata-only exposure audit and blind boundary

The accepted E4 aggregate `run_manifest.json` proves that the outcome runner
accepted `[2026-01-01T00:00:00Z, 2026-07-29T00:00:00Z)`. The frozen D003-v2
canonical endpoint used by E4 is `2026-07-29T00:00:00Z`. The accepted aggregate
package does not contain the exact timestamp of the last market row read.
E5 also records that endpoint-denominator evidence was only partially
complete. An interval end is not evidence that a row at that timestamp existed
or was opened.

The E6 metadata audit therefore records:

- latest exactly proven outcome-bearing timestamp: `UNPROVEN`;
- latest canonical timestamp declared by the ignored D003-v2 metadata:
  `2026-07-28T23:59:59.092Z`, which is not proof that this exact row was
  outcome-accessed;
- conservative non-blind exposure interval:
  `[2026-01-01T00:00:00Z, 2026-07-29T00:00:00Z)`;
- frozen canonical end boundary: `2026-07-29T00:00:00Z`; and
- earliest proven blind start: `UNPROVEN`.

This is fail-closed. No date immediately after 2026-07-29 is presumed blind.
The audit may inspect tracked/ref path names, stash identities and subjects,
filesystem names/sizes/mtimes, shell-command text, and the fixed aggregate
manifests. It may not apply a stash, inspect stash payloads, read ignored
event-level output, or open a Parquet payload. Later-file absence in the
current checkout is necessary evidence but is not by itself proof of an exact
exposure boundary across every prior environment or command.

The audit found no local canonical Parquet filename dated on or after
2026-07-29. It found outcome aggregate files for the already-known E4 interval,
relevant compiled caches, historical refs, and two E4 forensic stash subjects,
but no permitted metadata that proves a later market row was or was not
opened. The stashes cannot be inspected under this preregistration.

There is also a provenance qualification: current tracked D003 acceptance
documentation names d003-v1, while the E4 2026 package and ignored local
release metadata name d003-v2; the ignored d003-v2 canonical manifest declares
a dirty build worktree and references acquisition/D002 audit files that are
not present locally. The task-level milestone treats D003-v2 as immutable, so
E6 does not reinterpret or regenerate it, but these repository gaps prevent
the local metadata from proving an authoritative exact access boundary.

The two E4 forensic stashes remain immutable. E6 neither applies nor depends
on them. Their object identities and subjects may be reported as
non-scientific provenance metadata only.

## Proposed fixed calendar interval policy

Because the exact blind boundary is unproven, the interval below is a
**proposed, unregistered policy**. Registration remains false until a reviewed
commit made before the proposed start supplies durable pre-outcome provenance
and a separate boundary record closes every forensic ambiguity without
outcome access.

- Proposed eligible-anchor interval:
  `[2027-01-01T00:00:00Z, 2033-01-01T00:00:00Z)`.
- Design: fixed six-calendar-year interval chosen before outcome access.
- Endpoint buffer: 24 hours after the exclusive anchor end.
- Earliest possible execution under the proposal:
  `2033-01-02T00:00:00Z`.
- Actual execution authorization: always false in E6.

The six-year length is justified by the conservative planning scenarios below,
not by any future count or effect. The interval never stops when a target N,
p-value, sign, confidence interval, or effect size is reached. Sequential
"continue until N" sampling is prohibited.

Market holidays and genuinely closed sessions remain inside calendar time and
do not extend the interval. Missing or incomplete sessions are counted under
the frozen aggregate audit; they are not imputed. An incomplete final day or
an endpoint unavailable by the end of the 24-hour buffer fails structural
completeness and cannot extend the interval. No early peek, partial report,
interim significance test, or interim scientific summary is permitted.
Elapsed time and metadata-only file coverage may be checked before execution.
Coverage cannot be inferred from observed anchors. Missing-session treatment
must be supported by a preregistered metadata coverage contract before an
execution implementation is considered.

## Sample-size planning

### Unchanged adequacy thresholds

The historical thresholds remain decision rules and are not changed in
response to the E4 observation count:

- minimum total primary observations: 1,000;
- minimum bearish observations: 200;
- minimum bullish observations: 200; and
- complete coverage of every required endpoint and structural completeness
  requirement.

### Planning inputs and scenarios

The estimates below are planning aids, not decision rules. They use only the
frozen historical primary N of 1,778 over the 2022-2025 validation union and
the already-known E4 endpoint-complete aggregate N of 156 over its 209-day
calendar interval. The historical rolling-origin construction and the future
construction contract are not identical, so all estimates are approximate
and non-scientific.

| Scenario | Endpoint-complete planning rate | Months to total N=1,000 | Months to directional N=200 at 50% share | At 40% minority share | At 30% minority share |
|---|---:|---:|---:|---:|---:|
| Pessimistic | 18/month | 55.6 | 22.2 | 27.8 | 37.0 |
| Central | 23/month | 43.5 | 17.4 | 21.7 | 29.0 |
| Optimistic | 37/month | 27.0 | 10.8 | 13.5 | 18.0 |

Endpoint exclusions reduce a rate by multiplication. A 10% exclusion shock
multiplies every duration by `1/0.90` (about 1.11); a 20% shock multiplies it by
`1/0.80` (1.25). Under the pessimistic 18/month scenario, a 20% shock gives
14.4/month and about 69.4 months to total N=1,000. At a 30% minority-direction
share it gives about 46.3 months to directional N=200. The proposed 72-month
calendar interval is therefore expected—but not guaranteed—to clear the
registered thresholds under these conservative sensitivities.

Rates may change with volatility regimes, direction imbalance, holidays,
missing sessions, endpoint exclusions, causal-observability failures,
deduplication, or differences between the historical and future data
construction. No unseen count may be inspected to update the scenarios.

## Frozen scientific claim hierarchy

Every eventual report must begin with this immutable decision path:

```text
Integrity -> Adequacy -> Primary Evaluation -> Secondary Diagnostics
          -> A/B/C only if separately preregistered
```

### Integrity gate

`REPRODUCIBILITY_DEFECT` is the potential status for any failure involving
protected implementation hashes, specification/configuration hashes,
canonical or release integrity, future file-set integrity, UTC/interval or
structural construction invariants, causal observability, direction rules,
endpoint rules, deduplication, forbidden historical fitting/selection, or
unauthorized outcome access. If integrity fails, scientific outcomes are not
evaluated or reported beyond safe audit fields.

### Adequacy gate

`INDEPENDENT_SAMPLE_INADEQUATE` is the potential status when integrity passes
but total N, either per-direction N, complete required endpoint coverage, or a
preregistered structural completeness requirement fails.

### Primary evaluation

The claim remains exactly the mean direction-aligned XAUUSD price movement 60
minutes after causal `displacement_confirmation` for the frozen `1h_5m`,
`reversal`, deterministic-deduplicated primary sequence. Direction is the
non-neutral displacement direction available at the anchor. No horizon or
subgroup may replace it.

The inherited non-temporal checks are: mean greater than zero; two-sided 95%
Student-t lower bound greater than zero; both direction counts at least 200
with neither direction interval entirely below zero; never-later-confirmed
share at least 90% with positive mean; positive sign after deterministic
deduplication; all causal/availability/closed-bar/direction invariants pass;
mean-MFE/mean-MAE at least 0.75; median MFE/MAE at least 0.50; positive mean
after removal of the 1% largest absolute movements; and positive two-sided 1%
trimmed mean.

After integrity and adequacy pass, the exact non-temporal primary decision is
`REGISTERED_NON_TEMPORAL_CHECKS_PASS` if and only if all ten inherited checks
above pass; otherwise it is `REGISTERED_NON_TEMPORAL_CHECKS_FAIL`. This is the
complete registered non-A/B/C pass/fail rule. Secondary diagnostics cannot
alter it.

The historical rule also names four validation-year blocks, at least 200 per
block, and at least three positive block means. The frozen materials do not
unambiguously map those historical blocks to the proposed future six-year
interval, and the E4 extension explicitly left its temporal rule unresolved.
E6 does not invent a replacement. The missing temporal mapping blocks only a
temporal or A/B/C classification; it does not block the registered
non-temporal primary status.

### Secondary diagnostics

Historically inherited diagnostics are the frozen displacement horizons 5,
15, 30, 120 minutes, New York noon, and 17:00 trading-day close; the seven
frozen refinement endpoints; the 13-test Benjamini-Hochberg family at q=0.05;
and the frozen stability splits. E4/E5 reporting diagnostics are the already
known aggregate direction, month, session, paired-refinement, historical
comparison, endpoint-audit, and descriptive-qualification fields. E6 planning
diagnostics are accumulation scenarios, direction imbalance, endpoint
exclusion sensitivity, boundary provenance, interval readiness, and metadata
coverage readiness. Planning and reporting diagnostics are non-scientific.
No secondary diagnostic can redefine primary success.

No A/B/C result field exists in the E6 schemas. Its absence cannot block a
future non-A/B/C replication status after the primary-rule gap is separately
resolved.

## Aggregate-only audit contract

Before future outcome access, an eventual aggregate package must contain these
integer fields:

1. `total_structural_primary_cohort_count`;
2. `structurally_60m_eligible_count`;
3. `endpoint_complete_primary_count`;
4. `excluded_incomplete_endpoint_count`;
5. `excluded_missing_bars_count`;
6. `excluded_incomplete_sessions_count`;
7. `excluded_causal_observability_failure_count`;
8. `excluded_duplicate_identity_count`;
9. `excluded_interval_boundary_count`;
10. `expected_eligible_sequence_id_count`;
11. `observed_outcome_sequence_id_count`;
12. `expected_observed_sequence_ids_equal` (boolean);
13. `bearish_count`;
14. `bullish_count`;
15. `direction_unknown_or_rejected_count`;
16. `refinement_paired_count`;
17. `zero_lag_refinement_pair_count`;
18. `distinct_displacement_source_timestamp_count`;
19. `distinct_refinement_source_timestamp_count`; and
20. `distinct_displacement_refinement_source_timestamp_pair_count`;
21. `required_endpoint_complete_counts`, an exact aggregate map for the seven
    displacement endpoints and seven refinement endpoints; and
22. `required_endpoint_coverage_complete` (boolean).

It must also include exact denominator definitions for the cohort,
structural-eligibility, endpoint-complete, direction, refinement, and distinct
timestamp counts. No event-level output is required or permitted by E6.

Exclusions use a mutually exclusive first-failure precedence:
interval boundary, duplicate identity, causal-observability failure,
incomplete session, missing bars, incomplete endpoint. Required invariants are:

```text
structurally_60m_eligible_count
  = total_structural_primary_cohort_count
  - excluded_interval_boundary_count
  - excluded_duplicate_identity_count
  - excluded_causal_observability_failure_count
  - excluded_incomplete_sessions_count

endpoint_complete_primary_count
  = structurally_60m_eligible_count
  - excluded_missing_bars_count
  - excluded_incomplete_endpoint_count

expected_eligible_sequence_id_count = structurally_60m_eligible_count
observed_outcome_sequence_id_count = endpoint_complete_primary_count
expected_observed_sequence_ids_equal
  = (expected_eligible_sequence_id_count
     == observed_outcome_sequence_id_count)

bearish_count + bullish_count + direction_unknown_or_rejected_count
  = endpoint_complete_primary_count

0 <= zero_lag_refinement_pair_count <= refinement_paired_count
                                     <= endpoint_complete_primary_count

required_endpoint_coverage_complete
  = every displacement endpoint count equals endpoint_complete_primary_count
    and every refinement endpoint count equals refinement_paired_count
```

All counts are non-negative integers. Distinct timestamp counts cannot exceed
their stated paired or endpoint-complete denominator. Any unknown field,
denominator omission, inequality, or unreconciled count fails closed.

## Reporting contract

If adequacy fails, primary status is `NOT_EVALUATED`; every numerical metric is
explicitly descriptive and non-decisional; no numerical result is replication
evidence; and positive means, intervals, p-values, historical differences,
direction/session/month splits, robustness checks, and secondary results may
not imply support or confirmation. The machine-readable report must contain:

```json
{
  "scientific_decision_authorized": false,
  "all_metrics_descriptive_only": true,
  "replication_evidence_claim_permitted": false
}
```

If integrity fails, only the exact safe audit fields may be emitted:
fingerprint mismatch paths, integrity-failure reason codes, unauthorized-access
detection, Parquet-open detection, and market-row-decode detection. If adequacy passes,
only the preregistered ten-check non-temporal primary rule may determine the
primary status. Unknown keys and every A/B/C or trade/P&L-related key are
forbidden, including their use as generic metric or diagnostic names. Every
reported numerical value must be finite.

## Readiness package and authorization

The additive package lives only under
`research/d005_e6_future_blind_replication/`. It contains configuration,
fingerprinting, metadata-only boundary checks, fixed-policy validation,
sample-size planning, aggregate/reporting schemas, and a pre-execution
readiness CLI. It contains no future loader, bar/anchor constructor, outcome
calculator, forward-price reader, bootstrap/statistics runner, or scientific
report generator.

The CLI verifies tracked frozen hashes and accepted aggregate-manifest hashes,
inspects path metadata only, reports boundary/policy/elapsed-coverage status,
and keeps `scientific_execution_authorized` false. It writes nothing and never
creates a scientific output directory.

At this registration stage:

- blind boundary proven: false;
- fixed interval registered: false;
- exact non-temporal primary decision rule registered: true;
- scientific execution authorized: false; and
- production recommendation: `continue research only`.
