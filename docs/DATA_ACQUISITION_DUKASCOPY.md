# Dukascopy Historical Tick Data Acquisition

## Scope

TASK D001 is an infrastructure-only path from the public Dukascopy archive to a
feed-specific canonical XAUUSD tick dataset. It does not run inside research
experiments, change `xauusd_signal`, alter strategy behavior, or combine Dukascopy
with the existing MT5 feed.

The pipeline has three explicit gates:

1. `download_dukascopy_ticks.py` obtains and validates immutable native archive
   objects, then records them in an atomic JSON manifest.
2. `verify_dukascopy_downloads.py` independently recomputes checksums and classifies
   every expected native partition.
3. `build_dukascopy_canonical.py` decodes only manifest entries that pass the
   independent verification contract and writes deterministic, date-partitioned
   Parquet.

Research code may consume a canonical dataset. It must not download data or append
MT5 records to a Dukascopy dataset.

## Source and Format Contract

The default source identifier is `dukascopy-public-bi5`. It requires no paid
account, API key, or browser automation. The versioned source contract lives in
`config/dukascopy_data.toml`; local absolute paths are not embedded in it.

The implementation assumes the native public archive layout:

```text
https://datafeed.dukascopy.com/datafeed/{ARCHIVE_SYMBOL}/{YYYY}/{MM_ZERO}/{DD}/{HH}h_ticks.bi5
```

- The native partition is one UTC hour.
- `MM_ZERO` is a zero-based month (`00` is January and `11` is December).
- The configured XAUUSD archive symbol is `XAUUSD`.
- Each object is an LZMA-compressed stream of big-endian `>IIIff` records (20
  bytes): millisecond offset within the UTC hour, integer ask, integer bid,
  floating ask volume, and floating bid volume.
- XAUUSD integer prices are divided by the configured `price_scale = 1000`.
- Source timestamp precision is retained at one millisecond.

These are source-specific assumptions, not inferred properties. If Dukascopy changes
the archive contract or a different symbol is added, update and version the TOML
mapping before acquisition. A successful HTTP response is not sufficient: the
compressed stream, record size, offsets, and volumes must also validate.

Date boundaries use UTC and follow `[start, end)`: `--start` is inclusive and
`--end` is exclusive. A date such as `2025-01-08` means midnight UTC. ISO datetimes
must contain an explicit offset and be aligned to a whole UTC hour.

## Directory Layout

```text
config/dukascopy_data.toml                 tracked source/config contract
scripts/dukascopy_common.py                shared partition, manifest, and BI5 code
scripts/download_dukascopy_ticks.py        acquisition CLI
scripts/verify_dukascopy_downloads.py      independent verification CLI
scripts/build_dukascopy_canonical.py       canonical build CLI
data/raw/dukascopy/                        immutable source BI5 objects (ignored)
data/processed/dukascopy/                  canonical Parquet datasets (ignored)
data/manifests/                            generated acquisition manifests (ignored)
data/reports/                              generated quality reports (ignored)
data/logs/dukascopy/                       generated JSONL logs (ignored)
```

Only `.gitkeep` directory markers are tracked below `data/`. BI5, Parquet,
manifests, reports, temporary files, and runtime logs are ignored by Git.

## Download and Resume

Run a one-day historical pilot before any long acquisition:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD \
  --start 2025-01-07 \
  --end 2025-01-08 \
  --output-root data/raw/dukascopy
```

Preview the exact hourly URLs and destinations without network or manifest writes:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 --dry-run
```

The downloader writes each response to a same-directory temporary file, flushes it,
then atomically renames it only after BI5 validation. It records SHA-256, size,
source URL, partition and download timestamps, retry count, status, error details,
and decoded record count. The manifest itself is also replaced atomically after
every partition.

On restart, a `verified` manifest entry is skipped only when its file still exists,
its SHA-256 still matches, and its payload still validates. A valid final raw file
left by an interruption before the manifest update is recovered without another
network request. Malformed or corrupt non-empty objects are never accepted as
closures.

Transient network errors, HTTP 408/425/429, and server errors use bounded
exponential backoff. Permanent HTTP errors do not. A persistent HTTP/2-capable
client avoids reconnecting for every native hour; requests are still throttled
according to TOML settings. Every partition emits structured JSON progress; a
JSONL copy is written under `data/logs/dukascopy/` unless `--no-log-file` is used.

To retry only failed or absent work:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 \
  --only failed-or-missing
```

`--only failed` and `--only missing` are also available. The command exits nonzero
whenever the requested range still contains unresolved non-closure partitions,
including partitions excluded by the selected mode.

### Raw-data immutability

Accepted `.bi5` files are source artifacts, not working files. Never edit them in
place. A manifest checksum mismatch makes the object corrupt; a later downloader
run may atomically replace it only by obtaining and validating the same source
partition again. Canonical builds never modify raw objects.

## Verification

```bash
python scripts/verify_dukascopy_downloads.py \
  --symbol XAUUSD \
  --start 2025-01-07 \
  --end 2025-01-08
```

The default outputs are:

```text
data/reports/dukascopy_XAUUSD_download_quality.json
data/reports/dukascopy_XAUUSD_download_quality.md
```

Every expected hour is classified as exactly one of:

- `verified_data`: file exists, SHA-256 matches, and BI5 validation succeeds.
- `expected_market_closure`: an explicit configured calendar rule matches and the
  partition also has empty, missing, or explicit no-data evidence.
- `missing_partition`: no accepted source object is available.
- `corrupt_partition`: file SHA-256 differs from the manifest.
- `malformed_payload`: checksum matches but BI5/LZMA validation fails.
- `unresolved_status`: a failure, unknown status, or unmanifested object needs
  intervention.

### XAUUSD daily trading break

Dukascopy Bank's published [Trading Hours](https://www.dukascopy.com/swiss/english/forex/forex-trading-accounts/link/)
table specifies an XAU/USD trading break of 21:00–22:00 GMT/UTC during summer
time and 22:00–23:00 GMT/UTC during winter time. D001 represents both published
intervals as one 22:00–23:00 local interval using the IANA `Europe/London`
calendar:

| London calendar state | London local interval | Matching UTC partition |
|---|---|---|
| BST (UTC+01:00) | 22:00–23:00 | 21:00–22:00 UTC |
| GMT (UTC+00:00) | 22:00–23:00 | 22:00–23:00 UTC |

The timezone database, rather than a hard-coded month or list of transition dates,
therefore determines each year's DST boundaries. The configured local weekdays are
Monday through Friday (`0` through `4`). The rule is nested under
`symbol_daily_breaks.XAUUSD`, so it does not change any other instrument. The
source URL, named calendar, local interval, and weekdays are retained in the TOML
and copied into every JSON verification report.

The verifier requires two independent conditions before it reports
`expected_market_closure`:

1. The exact native UTC hour matches the configured rule for the requested symbol.
2. The raw response is empty, the partition has no payload, or the manifest uses an
   explicitly enumerated no-data status.

A calendar match does not convert an HTTP or network error into a closure. A
recorded `empty_payload` is accepted only inside the matching calendar hour. A
non-empty object is always checksum-checked and BI5-validated first; checksum drift
remains `corrupt_partition`, and malformed LZMA/BI5 or placeholder content remains
`malformed_payload`, even during the break.

The other default calendar rule remains Saturday (UTC weekday `5`) as a full-day
closure. Additional audited rules may be added using
`full_day_closed_weekdays`, `explicit_closed_dates`, or
`closed_utc_hours_by_weekday`. An empty response outside a configured closure,
explicit no-data outside a configured closure, and all arbitrary HTTP/network
failures remain unresolved.

## Canonical Build

```bash
python scripts/build_dukascopy_canonical.py \
  --symbol XAUUSD \
  --start 2025-01-07 \
  --end 2025-01-08
```

The builder independently verifies each selected checksum and payload. It never
reads a raw partition whose classification is not `verified_data`, never imputes
ticks, and never reads or joins the MT5 feed. Missing or excluded hours remain
listed in dataset metadata and produce a nonzero exit status.

The canonical schema is:

| Column | Type | Meaning |
|---|---|---|
| `timestamp` | `timestamp[ms, tz=UTC]` | Source hour plus millisecond offset |
| `bid` | `float64` | Dukascopy bid after configured scaling |
| `ask` | `float64` | Dukascopy ask after configured scaling |
| `bid_volume` | `float32` | Source bid volume |
| `ask_volume` | `float32` | Source ask volume |
| `symbol` | `string` | Requested canonical symbol |
| `feed` | `string` | Always `dukascopy` |
| `source_partition` | `timestamp[ms, tz=UTC]` | Native archive hour |

Output is partitioned as:

```text
data/processed/dukascopy/XAUUSD/{dataset_id}/date=YYYY-MM-DD/ticks.parquet
data/processed/dukascopy/XAUUSD/{dataset_id}/dataset_metadata.json
data/processed/dukascopy/XAUUSD/latest.json
```

`dataset_id` is derived from verified partition checksums, relevant configuration,
the requested range, and the D001 code version. Rows use a stable chronological
sort. Parquet options and metadata are fixed, daily files are atomically replaced,
and `build_timestamp` is deterministically derived from the selected manifest
inputs. Rebuilding identical verified inputs and configuration therefore produces
the same fingerprint, metadata, and Parquet checksums.

Dataset metadata records requested and actual coverage, row count, source/feed,
schema, UTC precision, source manifest hash, output checksums, quality statistics,
exclusions, logical build timestamp, and code/config versions. It reports exact
duplicates, duplicate timestamps, source-order reversals, crossed spreads,
non-positive prices, spreads over the configured limit, malformed records, large
tick gaps, and missing partitions. Records are reported rather than silently
dropped or repaired.

## Reproducibility Procedure

1. Use a clean checkout and record the Git commit.
2. Install the declared project dependencies, including PyArrow.
3. Keep `config/dukascopy_data.toml` unchanged or archive the reviewed version.
4. Run the downloader for a small pilot and retain its manifest/log.
5. Run independent verification; require zero unresolved partitions for complete
   requested coverage.
6. Run the canonical builder with the exact same `[start, end)` range.
7. Archive the manifest SHA-256, dataset input fingerprint, dataset metadata, and
   listed Parquet SHA-256 values.
8. On reproduction, compare those hashes. Do not substitute another feed for a
   missing Dukascopy partition.

For the user-authorized multi-year range, run only after the pilot has been reviewed:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD \
  --start 2021-01-01 \
  --end 2026-07-18 \
  --output-root data/raw/dukascopy
```

This command is intentionally not started by tests, documentation, or any research
experiment.

## Failure Modes and Limitations

- Public archive availability and historical completeness are not guaranteed.
  Coverage is a measured report outcome, not a source claim.
- XAUUSD scaling and binary-field ordering are explicit source assumptions that
  must be re-audited if Dukascopy changes its format.
- The daily-break rule covers only the source-backed XAUUSD interval. Unconfigured
  Friday/Sunday session hours and special US-holiday hours can remain unresolved;
  they are not inferred from this rule.
- An empty/no-tick object is not accepted automatically. It remains unresolved
  unless the exact symbol calendar rule also matches.
- Large builds process one UTC day at a time but still require enough memory for one
  day of decoded ticks.
- Quality thresholds flag observations; they do not repair, remove, or impute them.
- `latest.json` is a local convenience pointer, not a mutable combined feed.
