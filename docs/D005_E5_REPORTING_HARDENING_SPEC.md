# D005_E5 Post-Outcome Reporting Hardening Specification

## Status, evidence boundary, and non-replication statement

The first frozen 2026 D005_E4 execution occurred before this specification
was written. Its outcomes are already known: integrity was
`INTEGRITY_VERIFIED`, independent-sample adequacy was
`INDEPENDENT_SAMPLE_INADEQUATE`, and the primary result was `NOT_EVALUATED`.
The package at
`research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION` is an immutable,
historical, non-accepted execution record.

D005_E5 is a post-outcome reporting and aggregate-audit hardening exercise. It
is not blind and is not an independent replication. It cannot repair, replace,
rerun, amend, or upgrade the original execution. It may produce only an
audit-complete or explicitly audit-incomplete derivative report from already
frozen aggregate artifacts. A future genuinely blind replication requires a
new, previously unseen date interval and a separately registered design.

No E5 process may recalculate, change, filter, impute, round differently, or
reinterpret a scientific value. Hypotheses, thresholds, eligibility rules,
sample rules, endpoints, statistical procedures, result statuses, historical
comparisons, and production defaults remain frozen.

## Protected inputs and prohibited access

Every existing byte under
`research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION` is read-only. Its
manifest and fingerprints must not be regenerated. The seven pre-existing
untracked E4 execution and test files are immutable forensic source material;
E5 neither edits nor imports them.

The E5 review may read only these aggregate E4 package files:

- `artifact_manifest.json`;
- `summary.json`;
- `run_manifest.json`;
- `statistical_validation.json`;
- `secondary_diagnostics.json`;
- `direction_summary.json`;
- `monthly_summary.json`;
- `session_summary.json`;
- `paired_refinement_summary.json`;
- `historical_comparison.json`; and
- `report.md`.

Canonical data, raw data, release data, Parquet files, structural inventories,
event-level rows, paired rows, and market-price data are forbidden inputs.
E5 may not import or call the E4 outcome, anchor construction, preflight,
execution, or historical computation modules.

## Immutable aggregate verification

Before deriving a report, the E5 reviewer must:

1. reject symlinked, missing, additional, renamed, or unsafe E4 package paths;
2. verify every E4 payload byte against `artifact_manifest.json`;
3. require the manifest's declared scientific fingerprint to equal the
   deterministic result fingerprints in `summary.json` and
   `run_manifest.json`;
4. independently reconstruct the E4 scientific fingerprint from the frozen
   aggregate result and run-manifest identity fields; and
5. require the three frozen statuses stated above.

Failure is fail-closed and creates no E5 output.

## Universal descriptive and non-decisional contract

Because adequacy failed, no numerical result constitutes replication evidence.
`NOT_EVALUATED` is the dominant scientific status. Scientific decision-making
is unauthorized, every metric is descriptive only, and no replication-evidence
claim is permitted.

Every copied aggregate scalar, including positive means, historical
differences, direction and session summaries, p-values, confidence intervals,
robustness checks, refinement diagnostics, monthly statistics, booleans, and
nulls, must be enclosed in a machine-readable record containing the exact
source value and the qualification
`DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE`. This qualification does
not alter the source value.

The E5 audit must expose at least:

```json
{
  "scientific_decision_authorized": false,
  "all_metrics_descriptive_only": true,
  "replication_evidence_claim_permitted": false
}
```

No E5 table or prose may claim or imply success, support, confirmation,
validation, blind replication, independent replication, or an upgraded
scientific conclusion.

## Deterministic decision hierarchy

The reporting decision tree is fixed:

```text
Integrity
  -> Adequacy
    -> Primary Evaluation
      -> Secondary Diagnostics
        -> A/B/C only if separately registered before outcome access
```

The observed path terminates at adequacy failure:

```text
INTEGRITY_VERIFIED
  -> INDEPENDENT_SAMPLE_INADEQUATE [TERMINATE SCIENTIFIC EVALUATION]
    -> NOT_EVALUATED
      -> secondary values DESCRIPTIVE_NON_DECISIONAL only
        -> A/B/C BLOCKED_NOT_SEPARATELY_REGISTERED
```

Secondary values may be displayed after termination only as explicitly
qualified descriptive records. They cannot revive or bypass the failed gate.

## Aggregate endpoint-coverage audit

The endpoint audit uses availability evidence, not scientific values, to
classify audit completeness. Its required fields are:

1. structural primary cohort size;
2. structurally 60-minute eligible count;
3. endpoint-complete outcome count;
4. excluded count;
5. exclusion-reason counts;
6. the structural-eligibility clause result;
7. the expected-ID versus observed-ID equality clause result; and
8. whether the reported primary N is the deterministic complete-case subset.

Unavailable evidence must be recorded exactly as
`UNAVAILABLE_IN_FROZEN_AGGREGATES`; it must never be inferred from a missing
denominator or recovered from event rows.

The reporting-only classification is deterministic:

- `AUDIT_COMPLETE`: all eight required fields are available;
- `AUDIT_INCOMPLETE`: none of the eight fields is available beyond the frozen
  composite coverage flag; or
- `AUDIT_PARTIALLY_COMPLETE`: every other availability pattern.

The frozen aggregate package supplies the endpoint-complete primary count and
the failed composite `required_endpoint_coverage` flag. The frozen code
invariant establishes that the reported primary count is the unique-sequence,
non-null, 60-minute complete-case subset. It does not expose the structural
denominator, eligible count, excluded count, exclusion reasons, or either
component of the failed conjunction. Consequently E5 must classify this audit
`AUDIT_PARTIALLY_COMPLETE`, preserve the original adequacy failure, and state
that endpoint coverage is not fully auditable. It must not claim the defect is
repaired.

## Refinement diagnostic audit

The frozen source-code invariants, bound to the E4 outcome-implementation
fingerprint in `run_manifest.json`, establish only the following architecture:

- displacement uses its confirmation timestamp while refinement uses its
  array-creation timestamp;
- each anchor type is deterministically deduplicated separately per sequence;
- displacement and refinement are paired by sequence with a one-to-one join;
  and
- equal source timestamps can structurally produce zero-minute lag and equal
  registered endpoints can structurally produce zero paired difference.

The aggregate paired summary may be copied with the universal descriptive
qualification. It contains no zero-lag count, distinct-source count, or paired
row evidence. Those fields are
`UNAVAILABLE_IN_FROZEN_AGGREGATES`; independent empirical verification is
false. A median lag of zero is not evidence that every pair has zero lag.

## Human-readable report preamble

Every E5 human-readable report must begin, before any result or table, with all
of these statements:

- this is a post-outcome reporting hardening artifact;
- the original execution was not modified;
- outcomes were already known before E5;
- E5 is not an independent replication;
- scientific values are copied exactly from frozen aggregate artifacts; and
- no scientific conclusion may be upgraded by this report.

The preamble must also state that no numerical result constitutes replication
evidence.

## Versioned package and publication contract

Code is isolated under `research/d005_e5_reporting_hardening/`. Generated
artifacts are isolated under
`research_outputs/D005_E5_REPORTING_HARDENING/`. E5 may not write anywhere
under the E4 output namespace.

The package contains a machine-readable audit, a human-readable report, a run
manifest, and a self-excluding artifact manifest. Publication stages a complete
package beside the destination and uses an atomic directory rename. Existing
non-identical output is a hard collision. An existing byte-identical package
is verified and reused without rewriting. A verification-only mode performs no
writes.

E5 scientific and package fingerprints are functions only of stable relative
paths and deterministic contents. Absolute checkout paths, host details,
process identifiers, and runtime timestamps are excluded.

## Acceptance criteria

E5 is reviewable only if tests prove that:

1. no Parquet or event-level file is opened;
2. no E4 outcome or execution function is imported or called;
3. every copied scientific value remains exact and every scalar is qualified;
4. `NOT_EVALUATED` and the three machine-readable authorization fields remain
   fixed;
5. unavailable endpoint and refinement evidence remains explicit and no count
   is invented;
6. audit classification is deterministic and E5 cannot claim blind or
   independent replication or scientific success;
7. E4 bytes and its artifact manifest remain valid and byte-identical;
8. E5 and E4 paths cannot collide;
9. output publication is atomic and refuses silent overwrite; and
10. repeated generation and verification produce identical fingerprints
    independent of absolute paths and runtime time.

Passing E5 acceptance does not accept the original E4 execution as final
replication evidence. It establishes only that the derivative reporting
package is deterministic, source-immutable, aggregate-only, and explicit about
its remaining audit gaps.
