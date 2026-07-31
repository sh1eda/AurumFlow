# D003 Acceptance Report — Canonical XAUUSD Tick Dataset

## Release

- Release ID: `d003-v1`
- Symbol: `XAUUSD`
- Dataset type: canonical tick dataset
- UTC range: `2021-01-01T00:00:00Z` to `2026-01-01T00:00:00Z`
- Dataset root: `data/canonical/xauusd_ticks`
- Local release bundle: `data/releases/d003-v1`

## Build Results

- Rows: `270,997,638`
- Parquet files: `1,554`
- Processed verified BI5 partitions: `29,563`
- Duplicate records removed: `0`
- Rejected records: `0`
- Reused Parquet files: `3`
- Approximate dataset size: `2.5 GB`

## Independent Verification

- Verification passed: `true`
- Verification errors: `0`
- Verified rows: `270,997,638`
- Verified Parquet files: `1,554`
- Verifier exit code: `0`

## Freeze Integrity

A SHA-256 checksum was calculated for every Parquet file.

- Parquet checksum entries: `1,554`
- SHA-256 of `parquet_sha256.txt`:
5a7abbea158bfe4dde9f58f0fa0f69b22f6891eee769e70f0a9ef6d679787713

The local release bundle contains:

- `RELEASE.txt`

- `canonical_manifest.json`

- `full_verification.json`

- `parquet_sha256.txt`

- `release_sha256.txt`

The canonical manifest, verification report, and Parquet checksum manifest all passed SHA-256 verification.

## Source Integrity

- Raw BI5 source files were not modified.

- The canonical dataset was built only from verified D001 partitions.

- D002 regular, holiday, and special-hours closure reconciliation was respected.

- No unresolved expected partition remained in the accepted build.

## Decision

**ACCEPTED AND FROZEN**

The `d003-v1` canonical XAUUSD tick dataset is approved as the immutable source dataset for downstream research-dataset generation.

Any future rebuild or source-data correction must use a new dataset version and must not silently overwrite `d003-v1`.