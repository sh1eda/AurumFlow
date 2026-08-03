# D005_E4 2026 Independent Replication Extension Preregistration

## Status and boundary

This document is an additive preregistration for a possible independent
out-of-sample extension of `D005_E4_1H_5M_REVERSAL_REPLICATION`. It does not
replace or amend the frozen historical specification at
`docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md`.

The historical specification, historical configuration, selection logic,
metric implementation, protected artifacts, and production strategy are
immutable. The historical specification SHA-256 at registration is
`704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b`.

This extension must be frozen before any 2026 anchor outcome is read or
calculated. Its preflight entry point performs metadata and file-availability
checks only. It does not load Parquet market data, select anchors, calculate
outcomes, or write research results.

## Independent sample

The only accepted replication interval is:

```text
[2026-01-01T00:00:00Z, 2026-07-29T00:00:00Z)
```

The interval is inclusive at the start and exclusive at the end. No other
start or end is permitted.

The 2026 sample was not used for historical fitting, filtering, model
selection, threshold selection, mapping selection, benchmark construction, or
multiple-testing decisions. No hypothesis, threshold, anchor definition,
regime filter, context rule, metric, subgroup, or rejection rule may be added,
removed, or selected after observing 2026 outcomes.

## Frozen inputs and eligibility

The extension reuses the historical primary eligibility without alteration:

1. deterministic-deduplicated E2 uncapped population;
2. `mapping_variant == "1h_5m"`;
3. frozen `outcome == "reversal"`;
4. causal `displacement_confirmation` anchor;
5. `main_scope_eligible` is true;
6. `anchor_causally_observable` is true;
7. `anchor_selected_using_later_completion` is false;
8. displacement direction is non-neutral; and
9. the first anchor by `anchor_at`, `anchor_event_id`, and `anchor_id` is kept
   per unique sequence.

Refinement remains a secondary paired observation joined only after primary
sequence selection. The first eligible `refinement_array_creation` anchor is
kept using the same ordering. Later refinement or reaction completion cannot
affect primary eligibility.

The historical selection and metric implementation files are protected by
preflight SHA-256 checks. Historical fitting and rolling-origin selection paths
must not be invoked by the 2026 preflight or future outcome runner.

## Frozen endpoints and inference

The sole primary endpoint remains mean direction-aligned XAUUSD price movement
60 minutes after displacement confirmation. The anchor price, direction,
closed-bar availability, horizon close, signed movement, MFE, MAE, path order,
and time-to-extreme definitions must be reused exactly from the frozen
implementation.

Primary descriptive fields remain sample count, mean, median, win probability,
MFE, MAE, mean-MFE/mean-MAE ratio, median MFE/MAE ratio,
adverse-before-favorable probability, median time to MFE and MAE, standard
deviation, standard error, two-sided 95% Student-t interval, and deterministic
percentile bootstrap interval of the mean.

The bootstrap remains 2,000 resamples with base seed `50054`. Cell seeds must
use the historical deterministic derivation. Secondary endpoints remain 5,
15, 30, and 120 minutes, New York noon, and 17:00 New York trading-day close
for displacement, plus the seven frozen refinement endpoints. Their 13
two-sided one-sample t-tests remain one Benjamini-Hochberg family at q=0.05.
The displacement 60-minute primary test is excluded from that family.

Outputs are price-movement research metrics, not trades or P&L. The extension
must not request, calculate, or report entries, stops, targets, fills, sizing,
fees, slippage, returns, R expectancy, profit factor, trade drawdown, or any
other execution metric.

## Fixed historical comparison

The fixed discovery comparison targets are:

- displacement confirmation, `1h_5m`, reversal: N 1,778, 60-minute mean
  `+0.560` after rounding, BH q `0.0088`;
- refinement-array creation, `1h_5m`, reversal: N 1,778, 60-minute mean
  `+0.559` after rounding, BH q `0.0088`.

These values must not be recomputed unless the exact historical artifacts are
present and integrity-verified. Missing historical artifacts must be reported
as missing; approximate reconstruction is forbidden.

## Preregistered evaluation statuses

The following statuses use only metrics and thresholds already frozen in the
historical E4 specification. They are not the requested A/B/C classification
and cannot authorize production promotion.

### `REPRODUCIBILITY_DEFECT`

Assigned first if a protected hash, manifest integrity check, causal invariant,
direction invariant, deterministic selection invariant, or closed-bar
availability invariant fails.

### `INDEPENDENT_SAMPLE_INADEQUATE`

Assigned when no reproducibility defect exists but the primary endpoint has
fewer than 1,000 observations, either bullish or bearish direction has fewer
than 200 observations, or required endpoint coverage is unavailable.

### `REGISTERED_NON_TEMPORAL_CHECKS_PASS`

Assigned only when no defect or inadequacy exists and all of the following
historically frozen checks pass:

1. primary mean is greater than zero;
2. the two-sided 95% Student-t interval lower bound is greater than zero;
3. bullish and bearish subsets each have at least 200 observations and neither
   subset has a 95% interval entirely below zero;
4. the never-later-confirmed subset is at least 90% of the independent sample
   and has positive mean movement;
5. deterministic deduplication leaves the effect sign positive;
6. all causal, availability, closed-bar, and direction invariants pass;
7. mean MFE divided by mean MAE is at least 0.75;
8. median MFE/MAE ratio is at least 0.50;
9. mean movement remains positive after removing the 1% largest absolute
   movements; and
10. the two-sided 1% trimmed mean is positive.

### `REGISTERED_NON_TEMPORAL_CHECKS_FAIL`

Assigned when the independent sample is adequate and defect-free but one or
more registered non-temporal checks fail.

The historical rule also requires four validation-year blocks, at least 200
observations in every block, and at least three positive block means. A partial
2026 interval contains only one calendar-year block. No monthly substitute,
new block count, or new temporal threshold was historically registered.
Monthly results may therefore be descriptive only, and the historical temporal
check remains unresolved for this extension.

No deterministic mapping from these statuses to `REPLICATED`,
`PARTIALLY_REPLICATED`, or `FAILED_REPLICATION` exists in the frozen materials.
The A/B/C classification is blocked unless a separate rule is registered
before first access to 2026 outcomes. No A/B/C label may be inferred after the
results are observed.

## Required artifact and integrity gate

Before any outcome access, preflight must verify availability and identity of:

- `data/canonical/xauusd_ticks_d003-v2` and its 2026 Parquet partitions;
- `data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json`;
- the `data/releases/d003-v2` release descriptor, canonical manifest,
  independent verification report, Parquet checksum manifest, and release
  checksum manifest;
- protected D005, E1, E2, and E3 artifact manifests and E4-required tables;
- the historical E4 artifact manifest, summary, primary result, and historical
  comparison;
- every protected historical source file listed by the additive configuration.

Presence alone does not prove integrity. The future outcome runner must remain
disabled until release checksum semantics, canonical verification, protected
artifact manifests, and all declared source hashes are verified successfully.
If any item is absent or unverifiable, preflight fails closed and creates no
output directory.

No repository documentation defines a safe artifact-restoration procedure for
the local D003-v2 release or ignored D005 through E4 outputs. Acquisition and
build scripts are generation procedures, not restoration instructions, and
must not be used by this extension without separate authorization.

### Automation validation requirement audit

`AGENTS.md` says to run commands from `automation/config.yaml`, but no such
file exists in the tracked tree or any Git-visible history. No tracked
template, schema, example, generator, or consumer for that path exists. The
same scaffold commit, `798209607759f7c7b1e313473e2dbb2283e55e9c`, introduced
the AGENTS instruction and `automation/orchestrator.py`. The orchestrator does
not read `automation/config.yaml`; it reads a `validation_commands` list from
each task YAML. The tracked `tasks/backlog/D003.yaml` demonstrates that actual
contract.

Therefore `automation/config.yaml` is an unavailable repository-level
validation aid and a stale general convention, not a scientific dependency of
the D005_E4 replication. Its absence is reported as a preflight warning. It is
not a required artifact and cannot block dataset integrity, anchor
construction, or future replication authorization. No replacement file may be
invented without an authoritative tracked schema or canonical template.

### D003-v2 metadata and 2026 byte verification boundary

Before 2026 Parquet access, preflight verifies the SHA-256 of
`release_sha256.txt` members, the registered SHA-256 of
`parquet_sha256.txt`, equality of the canonical and release manifest copies,
the independent verification report, dataset identity and coverage, exact
agreement between all 1,732 canonical file records and Parquet checksum
entries, actual path presence, and declared byte sizes. These checks do not
open a Parquet file.

The preflight additionally selects exactly the 178 checksum-manifest entries
under `year=2026`, rejects missing, additional, renamed, or size-mismatched
files, and hashes the opaque bytes of every selected Parquet file. This phase
does not decode a Parquet row. The content-integrity blocker is removed only
when all 178 hashes match. The deterministic file-set fingerprint is computed
from sorted repository-relative paths, sizes, and registered hashes, so an
absolute checkout path cannot affect it.

Protected historical D005/E1/E2/E3/E4 artifacts are outside the independent
2026 sample. Preflight may hash those files against their registered artifact
manifests. Any missing file, size mismatch, hash mismatch, duplicate record,
unsafe path, or unregistered file fails closed.

### Isolated 2026 anchor-input construction

The historical E4 pipeline reads `anchor_events.parquet` and
`unique_sequences.parquet` from the protected historical E3 output and
`confirmation_event_inventory.parquet` from the protected historical E2
output. Those historical artifacts do not constitute a preregistered 2026
anchor inventory. Restoring them is necessary for integrity and historical
comparison, but is not sufficient to produce the independent sample.

No precomputed 2026 E2/E3-equivalent anchor inventory is used. The additive
module
`research/d005_e4_2026_independent_replication/anchor_inputs.py` reconstructs
only the frozen structural input in memory. It verifies the canonical Arrow
schema and tick identity, reads only the registered 2026 files, constructs the
frozen UTC one-minute, five-minute, and one-hour closed bars, replays the
frozen fixed/event schedules and D005 context engine for `1h_5m`, applies the
frozen E2 sequence reconstruction and engine-evidence match, and reproduces
the frozen E3 anchor identifiers and E4 displacement/refinement deduplication.
Because the historical E1 package initializer imports its forward pipeline,
`frozen_structural_loader.py` loads only the hash-registered E1 structural
config/schedule/PMH files and E2 direction/reconstruction files under private
module names. Runtime tests require the E1/E3 forward modules and E4
selection/analysis/pipeline modules to remain absent from `sys.modules` before
and after construction.

No data before `2026-01-01T00:00:00Z` or at/after
`2026-07-29T00:00:00Z` may be opened to supply lookback. Missing early-period
warm-up therefore remains missing data; it is not backfilled. Intraday bars
remain UTC epoch-aligned and are usable only after their `available_at`
timestamp. Partial bars are retained under the historical bar rule, PMH/PML
incomplete coverage remains ineligible under its historical prerequisite, and
forward-window eligibility is limited to endpoints no later than the frozen
end with an available downstream bar. No forward price is read by this stage.

The in-memory inventory contains only structural identifiers, timestamps,
directions, confirmation state, deduplication identity, session labels, and
eligibility flags. A schema firewall rejects price/outcome/performance
columns. The module does not import or call the E1/E3 forward-outcome modules,
the historical E4 selector, fitting, analysis, or reporting code, and it does
not create the final output directory.

## Additive implementation contract

The preflight entry point is:

```bash
python -m research.d005_e4_2026_independent_replication \
  --independent-replication \
  --start 2026-01-01T00:00:00Z \
  --end 2026-07-29T00:00:00Z
```

It must:

- require the explicit independent-replication flag;
- reject every alternative interval;
- reserve only
  `research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION`;
- reject collisions with historical or protected outputs;
- record the historical and extension specification hashes, Git commit,
  configuration fingerprint, protected implementation hashes, and available
  manifest hashes in its in-memory preflight result;
- record unavailable hashes as null;
- perform no fitting, historical selection, tuning, or outcome calculation;
- never create an output directory while blocked; and
- keep the historical independent-replication guard unchanged.

The preflight intentionally contains no outcome-execution function. A future
outcome runner requires a separate reviewed change after the gate passes and
before any 2026 outcome is accessed.

The unregistered partial-year rule blocks only an A/B/C classification. It is
not a reason to invent a temporal rule and does not itself block a separately
reviewed runner from calculating the already preregistered non-A/B/C outcome
fields. At this stage all outcome calculation remains unauthorized because no
outcome runner has been implemented.

## Output isolation and production boundary

Future successful artifacts may be written only under
`research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION`. Historical E4 output
paths and every D005/E1/E2/E3 path remain read-only. Canonical data, raw data,
release files, manifests, and production strategy code remain read-only.

This research extension cannot change production defaults or authorize a
production candidate.
