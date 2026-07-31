# D001 — Final Acceptance Report

## Scope and source of truth

This report accepts the completed D001 acquisition/recovery result together
with the D002 holiday and special-hours overlay. It is documentation-only and
does not change source code, manifests, generated reports, canonical data,
hashes, BI5 files, tests, strategy code, or research logic.

The source artifacts are:

- `data/reports/dukascopy_XAUUSD_download_quality.json`
- `data/reports/dukascopy_XAUUSD_download_quality_before_targeted_recovery_2021_2026.json`
- `data/reports/D002_XAUUSD_baseline_2021_2026.json`
- `data/reports/D002_XAUUSD_holiday_special_hours_audit.json`
- `data/reports/dukascopy_XAUUSD_canonical_quality.json`

## Dataset

| Field | Accepted value |
|---|---:|
| Symbol | `XAUUSD` |
| Date range | `[2021-01-01T00:00:00Z, 2026-01-01T00:00:00Z)` |
| Expected hourly partitions | 43,824 |
| Verified partitions | 29,563 |
| Regular market closures | 13,504 |
| Holiday closures | 413 |
| Special-hours closures | 344 |
| Missing partitions | 0 |
| Corrupt partitions | 0 |
| D001 unresolved | 757 |
| D002 overlay unresolved | 0 |

The accepted D001+D002 reconciliation is:

`43,824 = 29,563 verified + 13,504 regular market closures + 413 holiday closures + 344 special-hours closures + 0 missing + 0 corrupt + 0 unresolved`

The reconciliation is balanced. D001 alone intentionally retains 757
`empty_payload_open_market` records as unresolved. D002 is the authoritative,
report-only overlay that classifies those same confirmed HTTP 200, zero-byte
responses as 413 holiday closures and 344 special-hours closures.

## Downloader

- **Resume support:** The downloader supports `--only failed-or-missing`,
  `--only failed`, and `--only missing`. A verified entry is skipped only when
  its BI5 file still exists, its SHA256 matches, and the payload validates.
  Valid final files left by an interruption before a manifest update can be
  recovered without a new request.
- **Verifier:** The verifier generates every UTC hour in `[start, end)` and
  assigns exactly one classification per partition. It detects silent gaps,
  duplicate manifest entries, missing files, checksum failures, malformed BI5,
  inconsistent record counts, unexpected empty responses, and unresolved
  source failures.
- **Proxy pool:** Direct, single-proxy, and proxy-pool modes are supported.
  Pool rotation is health-based and stable round-robin, with masked identities,
  per-proxy cooldowns, and no credential logging. The configured defaults
  rotate after two proxy-specific transient failures and cool a proxy for 300
  seconds.
- **Retry policy:** Transient HTTP and transport failures use configured waits
  of 15, 60, and 300 seconds. A larger valid `Retry-After` value takes
  precedence. Permanent failures do not receive transient retries.
- **Throttling:** The default delay is 2 seconds between completed partition
  requests, including after successful requests.
- **Circuit breaker:** Five consecutive transient source failures trigger a
  900-second pause. A successful download or confirmed expected closure resets
  the counter. Proxy-pool mode first exhausts healthy, untried routes.
- **Manifest:** Partition status, file location, byte size, SHA256, record
  count, retry count, timestamps, masked proxy identity, response evidence, and
  failure details are preserved in an atomically replaced JSON manifest.
- **SHA256:** Download, resume, verification, recovery, and canonical build
  gates compare the stored SHA256 with the corresponding BI5 file.
- **BI5 validation:** A response must decompress as LZMA and decode into
  complete 20-byte big-endian `>IIIff` records with valid in-hour offsets and
  plausible fields. Corrupt or malformed non-empty responses are never
  closures.
- **Canonical pipeline:** The builder independently rechecks accepted BI5
  checksums and decoding, reads only verified partitions, performs a stable
  chronological sort, and writes deterministic date-partitioned Parquet with
  fixed schema, compression, metadata, fingerprints, and output checksums. The
  existing one-day canonical pilot covers 24 hours as 23 verified partitions
  plus one regular closure, with zero unresolved partitions and 246,168 rows.

## Recovery Summary

The targeted recovery workflow used verifier-derived unresolved-only
allowlists and retained resumability, atomic writes, evidence fields, proxy
controls, and fail-closed closure classification.

The preserved full-range pre-recovery report contained 6,754 unresolved
partitions:

| Pre-recovery evidence group | Partitions |
|---|---:|
| `ambiguous_closure_evidence` | 5,709 |
| `empty_payload_open_market` | 749 |
| `http_5xx` | 216 |
| `timeout` | 58 |
| `manifest_status_failed` | 13 |
| `connection_error` | 9 |
| **Total allowlisted** | **6,754** |

Across the completed targeted recovery passes:

- 270 partitions became newly verified;
- 5,727 partitions became newly classified regular market closures;
- verified partitions increased from 29,293 to 29,563;
- regular market closures increased from 7,777 to 13,504; and
- unresolved partitions decreased from 6,754 to 757.

Before D002, all 757 remaining unresolved records were confirmed HTTP 200,
zero-byte `empty_payload_open_market` responses. D002 grouped them into 380
contiguous intervals and classified 413 as
`expected_holiday_closure` and 344 as
`expected_special_hours_closure`. No D002 candidate remains unexplained.

From the preserved pre-recovery state through D002, the combined result is 270
new verified partitions and 6,484 newly classified closures, with zero final
overlay unresolved partitions.

## Integrity

- The D002 baseline recorded all 29,563 verified file paths, file sizes,
  manifest statuses, evidence kinds, stored SHA256 values, and independently
  computed SHA256 values before classification.
- The current manifest SHA256 is
  `7938fafdfe3b909af81208319fc3b817c3746f65efa31d32499cb5b0b0ed7fb3`.
- The manifest hash before and after the read-only D002 audit is identical.
- The verified file count is 29,563 before and after the audit.
- Every stored SHA256 matches its corresponding verified BI5 file.
- No verified partition was added, removed, renamed, resized, downgraded, or
  modified during the audit.
- No holiday or special-hours closure was accepted without preserved
  `confirmed_empty_payload`, HTTP 200, and zero-byte evidence.
- D002 ran in `offline_report_only` mode. It did not mutate the manifest or any
  verified BI5 file.
- No historical download was performed during the D002 baseline,
  classification, or integrity audit.

## Testing

| Check | Result |
|---|---|
| Full offline test suite | **PASS — 301 tests passed in 9.08 seconds** |
| Python source compilation | **PASS — 21 Python files compiled in memory without repository bytecode writes** |
| `git diff --check` | **PASS** |
| D001 reconciliation | **PASS — balanced** |
| D001+D002 overlay reconciliation | **PASS — balanced** |
| D002 integrity audit | **PASS** |

The test run disabled Python bytecode and pytest cache writes so that acceptance
verification remained compatible with this documentation-only task.

## Risks

1. **D002 remains an overlay.** The D001 manifest and raw D001 verification
   report retain 757 unresolved statuses by design. A consumer that ignores the
   D002 audit will see an incomplete reconciliation.
2. **Canonical-build integration is not automatic.** The current canonical
   builder uses the D001 partition classifier and does not ingest the D002
   calendar directly. Full-range build review must therefore retain the D002
   audit beside the canonical metadata and reconcile the 757 D001 exclusions
   as 413 holiday plus 344 special-hours closures. This is an operational
   integration limitation, not a missing-data or integrity defect.
3. **Confidence is not uniform.** Of the 757 D002 classifications, 506 are
   high confidence and 251 are medium confidence. Every accepted classification
   is source-backed and evidence-gated, but future archived Dukascopy notices
   may strengthen the medium-confidence records.
4. **The accepted range is fixed.** This acceptance ends at
   `2026-01-01T00:00:00Z` exclusive. Later partitions and future holiday
   schedules require a new verification and calendar extension.
5. **The full-range canonical artifact has not yet been built.** The canonical
   pipeline has a successful one-day pilot, while full-range Parquet resource
   use, output size, and final quality statistics remain to be observed during
   the canonical-build task.
6. **No production promotion is implied.** This acceptance authorizes the
   canonical build only. Strategy, research, and production promotion decisions
   remain separate gates.

## Acceptance Criteria

| Acceptance criterion | Result | Evidence |
|---|---|---|
| Exact symbol and half-open UTC range are fixed | **PASS** | D001 and D002 both report `XAUUSD`, 2021-01-01 through 2026-01-01 |
| Every expected hour is accounted for exactly once | **PASS** | 43,824 expected and 43,824 accounted |
| Reconciliation is balanced | **PASS** | D001 and D001+D002 reconciliations both report `balanced = true` |
| Verified partitions have present, decodable BI5 files | **PASS** | 29,563 verified partitions passed verifier and D002 baseline checks |
| Stored SHA256 values match verified files | **PASS** | D002 integrity audit reports zero mismatches |
| No missing partitions remain | **PASS** | Missing = 0 |
| No corrupt or malformed partitions remain | **PASS** | Corrupt = 0 |
| Regular closures require exact shared-calendar and source-evidence matches | **PASS** | 13,504 regular closures; errors and non-empty malformed payloads remain ineligible |
| Holiday closures require authoritative schedules and confirmed-empty evidence | **PASS** | 413 D002 holiday closures; zero evidence violations |
| Special-hours closures require authoritative schedules and confirmed-empty evidence | **PASS** | 344 D002 special-hours closures; zero evidence violations |
| No D002 overlay unresolved partitions remain | **PASS** | `unexplained_empty_payload = 0` |
| Targeted recovery operated on the unresolved full-range set | **PASS** | Preserved pre-recovery report contains exactly 6,754 unresolved partitions across all six groups |
| Resume, retry, throttling, proxy-pool, and circuit-breaker behavior is covered | **PASS** | Implemented downloader controls and passing offline regression suite |
| Manifest semantics and atomic raw-file handling are preserved | **PASS** | D001 contract retained; D002 reports `manifest_mutated = false` |
| Verified BI5 files remained immutable through audit | **PASS** | Zero added, removed, renamed, resized, downgraded, or modified verified files |
| Canonical pipeline has passed an end-to-end pilot | **PASS** | 23 verified + 1 closure, zero unresolved, 246,168 canonical rows |
| Full offline tests pass | **PASS** | 301 passed |
| Python compilation passes | **PASS** | 21 Python files compiled successfully |
| Patch whitespace validation passes | **PASS** | `git diff --check` completed without findings |
| Strategy and research logic remain unchanged by acceptance | **PASS** | This report is documentation-only |

The dataset is ready to enter the canonical-build stage because every expected
partition has a balanced D001+D002 disposition, all 29,563 accepted source
objects pass file and SHA256 integrity checks, and no missing, corrupt, or
overlay-unresolved partition remains. The D002 overlay must accompany canonical
build review so that its 757 source-backed closures are not reinterpreted as
ordinary D001 failures.

## D001 STATUS:

READY FOR CANONICAL BUILD
