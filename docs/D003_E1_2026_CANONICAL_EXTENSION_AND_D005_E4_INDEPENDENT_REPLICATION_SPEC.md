# D003_E1 2026 Canonical Extension and D005_E4 Independent Replication

## Status and isolation

This specification was frozen before the quantitative overlap comparison and
before any post-2025 D005 outcome was calculated. The task has two hard-gated
stages:

1. qualify and, only if compatible, build `d003-2026-extension-v1`; and
2. only after Stage A passes, run the frozen D005_E4 hypothesis on the
   independent post-2025 extension.

Historical `d003-v1`, D005, D005_E1, D005_E2, D005_E3, D005_E4, canonical
historical partitions, production behavior, and strategy defaults are
protected read-only inputs.

## Authoritative contracts

The Stage A contract is the existing D003 implementation:

- `scripts/build_dukascopy_canonical.py`
- `scripts/validate_canonical_dataset.py`
- `data/releases/d003-v1/canonical_manifest.json`
- `data/releases/d003-v1/full_verification.json`
- `data/releases/d003-v1/parquet_sha256.txt`

The exact D003 Arrow fields are non-nullable:

1. `timestamp_utc`: `timestamp[ms, tz=UTC]`
2. `bid`: `float64`
3. `ask`: `float64`
4. `bid_volume`: `float32`
5. `ask_volume`: `float32`
6. `mid`: `float64`
7. `spread`: `float64`
8. `symbol`: `string`
9. `source_partition`: `string`

D003 metadata identifies the source as `dukascopy-public-bi5`. The frozen
builder accepts D001-verified Dukascopy BI5 partitions, respects the D002
closure overlay, retains native side volumes, and fails rather than writing a
day containing missing or invalid required values.

## Source roles

Every local XAUUSD market file is inventoried. A file is a post-2025 candidate
only when it contains observations after `2025-12-31T23:59:59.999Z`.
Pre-2026 files may be retained only as provenance or overlap evidence.

Existing normalized MT5 derivatives are read-only audit aids. They are not
D003 canonical outputs and must not be relabeled as such. The raw tick export
is controlling evidence for source-field availability; a derivative cannot
create source provenance or native fields absent from the raw export.

## Frozen compatibility decision

Compatibility is classified without using D005 outcomes:

### 1. Directly compatible

All of the following must hold:

- authenticated same feed/source family as D003;
- exact native D003 fields, including bid and ask volume;
- timestamp timezone is explicit and verified;
- D001/D002-compatible partition provenance is complete;
- the frozen D003 builder and independent verifier accept the source without
  semantic or schema adaptation; and
- overlap evidence, when available, reveals no unresolved feed break.

### 2. Compatible after deterministic normalization

All class-1 conditions hold except representation-only differences that can be
normalized without inference, such as explicit source timezone conversion,
column renaming, numeric casting without loss, deterministic symbol
normalization, or deterministic partition layout. Required values must be
observed in the source. A different broker/feed is not a representation-only
difference.

### 3. Usable only as a separately labeled feed

The source is structurally usable for separately labeled research, but at
least one of the following holds:

- broker/feed provenance differs from or cannot be authenticated as D003;
- a required native D003 field is absent and cannot be reconstructed without
  inference;
- timezone is empirically inferred rather than authenticated;
- the source cannot enter the frozen D003/D001/D002 build path; or
- overlap evidence shows a material feed-composition difference.

Class 3 fails Stage A and forbids Stage B.

### 4. Incompatible

The source cannot be normalized safely even as a separately labeled feed
because timestamps, prices, ordering, integrity, or provenance are
irreparably ambiguous or invalid. Class 4 fails Stage A and forbids Stage B.

Classes 1 and 2 require every Stage A acceptance check. No quantitative
similarity can override missing source fields or different feed provenance.

## Frozen feed-comparison design

The true overlap is the intersection of the D003-derived one-minute cache and
the MT5-derived one-minute bid/ask file. Comparison is timestamp-exact in UTC
and reports, without imputing missing minutes:

- source and matched-minute counts;
- intersection and union coverage;
- absolute and signed mid-close price differences;
- bid, ask, and mid OHLC differences;
- one-minute return differences on consecutive common minutes;
- median and maximum spread distributions;
- tick-count distributions;
- bar-range and absolute-return volatility distributions;
- gap and duplicate frequencies;
- UTC-hour/session coverage;
- seasonal/DST-regime comparisons; and
- extreme spread, range, return, and tick-count frequencies using fixed
  within-feed 99th and 99.9th percentile diagnostics.

These measurements describe feed differences. They do not establish feed
identity and do not modify the provenance-based compatibility gate.

## Timezone and DST rule

Naive MT5 server timestamps are never assumed to be UTC or New York time.
Existing evidence for `Europe/Helsinki` is audited and labeled according to
its actual strength. Empirical market-event alignment is supporting evidence,
not broker authentication. UTC-normalized derivatives control only after
their lineage, source hash, and conversion rule are verified.

## Canonical-build gate

No candidate Parquet file may be written when:

- a required non-nullable D003 field is absent;
- native bid/ask volume would have to be fabricated;
- the frozen D003 builder cannot accept the source;
- timezone normalization is unresolved;
- provenance is incomplete; or
- compatibility is class 3 or 4.

When the pre-build gate fails, the candidate release has zero canonical rows
and zero canonical files. Reports and manifests are still produced, but no
release directory or Stage B directory is created.

## Frozen Stage B design

If and only if Stage A passes, Stage B must reuse the frozen E4 values:

- mapping `1H -> 5m`;
- reversal family;
- first causal displacement confirmation;
- unique sequence IDs;
- no later-completion condition;
- no optional 1m or CISD;
- primary 60-minute direction-aligned movement;
- paired refinement creation;
- minimum total N `1000`;
- minimum direction N `200`;
- confidence level `95%`;
- bootstrap resamples `2000`, seed `50054`;
- no threshold, timing, POI, OB, FVG, session, or subgroup changes.

If Stage A fails, the hard replication classification is category 6:
feed incompatibility prevents a valid D003-derived replication. No outcome is
calculated and sample sufficiency is not reinterpreted.

