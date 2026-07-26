# D003 Canonical XAUUSD Tick Dataset

## Existing implementation assessment

The repository already contained the canonical build command at
`scripts/build_dukascopy_canonical.py`. Before D003, it:

- selected source hours with the D001 verifier's `classify_partition`;
- reused `inspect_bi5_payload` and `decode_ticks` from
  `scripts/dukascopy_common.py`;
- rechecked every selected raw-file SHA256 immediately before decoding;
- normalized native hour offsets into millisecond UTC timestamps;
- sorted rows deterministically;
- retained the native source hour as provenance;
- used fixed Parquet options and an atomic temporary-file replacement; and
- emitted file hashes, row counts, source-manifest identity, and quality
  statistics.

Those controls already satisfied the D003 requirements to reuse the BI5
decoder, read verified inputs, preserve UTC precision and provenance, sort
deterministically, hash outputs, and use atomic writes.

The pre-D003 implementation was not sufficient as the canonical research
dataset because it used the legacy schema (`timestamp`, no `mid` or `spread`,
and an extra `feed` column), wrote under a content-id/date layout rather than
`data/canonical/xauusd_ticks/year=YYYY/month=MM`, replaced existing daily
files, did not consume the accepted report-only D002 overlay, retained invalid
and duplicate rows, had no checkpoint manifest for resume, and had no
independent canonical verifier.

D003 therefore hardens the existing builder in place. It does not introduce a
second BI5 conversion implementation, change acquisition classifications, or
touch production strategy code.

## Build contract

The exact canonical columns are:

| Column | Arrow type | Definition |
|---|---|---|
| `timestamp_utc` | `timestamp[ms, tz=UTC]` | Native source hour plus BI5 millisecond offset |
| `bid` | `float64` | Scaled Dukascopy bid |
| `ask` | `float64` | Scaled Dukascopy ask |
| `bid_volume` | `float32` | Native bid volume |
| `ask_volume` | `float32` | Native ask volume |
| `mid` | `float64` | `(bid + ask) / 2` |
| `spread` | `float64` | `ask - bid` |
| `symbol` | `string` | Always `XAUUSD` |
| `source_partition` | `string` | Originating hourly partition in UTC |

Daily files are deterministic and bounded in memory:

```text
data/canonical/xauusd_ticks/
  canonical_manifest.json
  year=YYYY/
    month=MM/
      xauusd_ticks_YYYY-MM-DD.parquet
```

The preflight re-derives every requested hourly classification. It accepts only
`verified_data`, D001 `expected_market_closure`, or an exact partition in the
accepted D002 audit whose source-manifest integrity proof still matches. Any
other classification stops the build before output.

Each raw SHA256 and decoded row count is checked again during conversion.
Rows with timestamps outside their source hour, non-finite or non-positive
prices, crossed quotes, or non-finite/negative volumes fail the affected build
day without producing a Parquet file. Exact duplicate tick identity excludes
`source_partition`, keeps the first deterministic occurrence, and records
within-partition and adjacent-partition-boundary removals separately.

The manifest is atomically checkpointed after each completed UTC day. A resume
reuses a file only when its SHA256 and source-partition fingerprint match. A
completed identical build returns without rewriting either files or manifest.
Existing incompatible, corrupt, or unmanifested outputs fail closed rather
than being overwritten.

`build_timestamp` is a reproducible logical timestamp derived from the latest
selected acquisition timestamp. The Git commit, complete schema, acquisition
manifest SHA256, D002 audit SHA256, build configuration, partition coverage,
closure counts, per-file statistics and hashes, duplicate removals, rejected
records, and reconciliation are recorded explicitly.

## Commands

Build a bounded range:

```bash
python scripts/build_dukascopy_canonical.py \
  --start 2021-11-25T00:00:00Z \
  --end 2021-11-29T00:00:00Z
```

The independent verifier does not import the builder. It re-derives source
coverage and closure exclusions, validates the source and D002 hashes, reads
every declared Parquet file, checks the exact schema, ordering, UTC timestamps,
exact duplicates, price/spread/volume invariants, per-file and aggregate
statistics, hashes, layout, undeclared files, and complete reconciliation:

```bash
python -m scripts.validate_canonical_dataset
```

To save a verification report for a bounded smoke build:

```bash
python -m scripts.validate_canonical_dataset \
  --report data/reports/D003_XAUUSD_smoke_verification.json
```

The full 2021-2026 build must not be started until the bounded smoke result is
reviewed and explicitly approved.
