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

Holiday and special-hours classification is a separate, report-only D002
overlay documented in
[`D002_XAUUSD_HOLIDAY_SPECIAL_HOURS.md`](D002_XAUUSD_HOLIDAY_SPECIAL_HOURS.md).
It does not alter the frozen D001 calendar, verified BI5 files, or manifest
semantics.

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

Transient network errors (including timeouts and stream resets), HTTP
408/425/429, and server errors use the configured server-friendly retry waits of
15, 60, and 300 seconds. A larger source `Retry-After` value takes precedence.
Permanent HTTP errors do not retry. The shared HTTPX client uses HTTP/1.1
(`http2=False`) to reduce stream-reset failures and retains the connection across
sequential archive requests.

The downloader waits 2 seconds after every completed partition request by default,
including successful requests. Override that delay for a run with:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 \
  --request-delay-seconds 3.0
```

After five consecutive partitions end in transient source failures, the downloader
pauses for 900 seconds before continuing. A successful download or confirmed
expected closure resets the counter. `retry_backoff_seconds`,
`circuit_breaker_threshold`, and `circuit_breaker_pause_seconds` are configurable
in `config/dukascopy_data.toml`; the request delay and both circuit-breaker values
also have CLI overrides. These controls do not alter manifest statuses: an HTTP 429,
503, timeout, or stream reset remains a failed/unresolved partition and cannot
become an expected closure.

Every partition emits structured JSON progress; a JSONL copy is written under
`data/logs/dukascopy/` unless `--no-log-file` is used.

### Optional proxy

Direct connections remain the default. Pass one HTTP(S) proxy directly when
required:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 \
  --proxy-url 'http://username:password@proxy-host:port'
```

For unattended use, keep the value in the `DUKASCOPY_PROXY_URL` environment
variable. The CLI uses it automatically when `--proxy-url` is omitted:

```bash
export DUKASCOPY_PROXY_URL='http://username:password@proxy-host:port'
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08
```

An explicit CLI value takes precedence over the environment variable:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 \
  --proxy-url "$DUKASCOPY_PROXY_URL"
```

Proxy credentials are passed only to HTTPX. They are not written to the manifest or
structured logs; any proxy URL included in an initialization or transport
diagnostic has its complete username and password replaced with `***:***`.

For a small stable pool, create a local text file with one HTTP(S) proxy URL per
line. Blank lines and lines whose first non-whitespace character is `#` are ignored.
Exact duplicates are removed while preserving the first occurrence:

```text
# primary routes
http://username:password@proxy-host-1:port
http://username:password@proxy-host-2:port

# fallback route
http://username:password@proxy-host-3:port
```

Start or resume through that pool with:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD --start 2025-01-07 --end 2025-01-08 \
  --proxy-file /secure/path/dukascopy-proxies.txt
```

`--proxy-url` and `--proxy-file` are mutually exclusive. Proxy files are validated
before acquisition starts, and a file with no usable entries fails immediately.
The downloader never prints the file contents. Keep the file outside the repository,
restrict its filesystem permissions, and do not commit it. Supplying credentials on
the command line can expose them to shell history or process inspection; prefer a
protected proxy file or `DUKASCOPY_PROXY_URL` environment variable.

The pool keeps using a healthy proxy rather than rotating on every request. By
default, two consecutive proxy-specific transient failures rotate to the next proxy
in stable round-robin order. The rotated-out proxy cools down for 300 seconds.
Override those defaults with `--proxy-rotate-after-failures` and
`--proxy-cooldown-seconds`. HTTP 429/502/503/504, timeouts, resets, SSL/TLS transport
failures, and protocol stream errors affect proxy health. Expected closures,
BI5/checksum failures, local I/O errors, and deterministic HTTP 4xx responses do
not.

Cooling proxies are skipped. If every proxy is cooling down, the downloader waits
until the earliest cooldown expires and emits a credential-safe `proxy_pool_wait`
event. A `proxy_rotation` event records only masked previous/next proxy URLs. Pool
rotation happens inside the existing retry policy; the global source circuit breaker
is deferred while untried healthy pool members remain and can activate only after
transient failures span the available pool. Direct and single-`--proxy-url` modes
retain the original circuit-breaker behavior.

Example full-range resume using the pool without redownloading verified objects:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD \
  --start 2021-01-01 \
  --end 2026-07-18 \
  --output-root data/raw/dukascopy \
  --only failed-or-missing \
  --proxy-file /secure/path/dukascopy-proxies.txt \
  --request-delay-seconds 3
```

Use a few reliable, long-lived proxies. Rapid per-request rotation creates more
connections, makes failures harder to attribute, and is intentionally not the pool
strategy.

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

- `verified_data`: the expected BI5 file exists; its manifest path, partition
  timestamp, byte size, and SHA-256 agree with disk; BI5 decoding succeeds; and
  the manifest record count is a non-negative integer equal to the decoded count.
- `expected_market_closure`: an explicit configured calendar rule matches and the
  manifest preserves affirmative empty-response or explicit no-data source
  evidence.
- `missing_partition`: no accepted source object is available.
- `corrupt_partition`: file SHA-256 differs from the manifest.
- `malformed_payload`: checksum matches but BI5/LZMA validation fails.
- `unresolved_status`: a failure, unknown status, or unmanifested object needs
  intervention.

The verifier generates the complete UTC-hour sequence for `[start, end)` instead
of iterating only over files or manifest entries. It therefore reports an hour
that is absent from both disk and the manifest as `missing_partition`. Duplicate
raw JSON keys are rejected during manifest parsing, and duplicate declared
`partition_timestamp` values are reported as manifest errors rather than silently
overwriting or aliasing an hourly record.

Each completed report prints and stores this reconciliation:

```text
expected_partitions =
verified +
expected_market_closures +
missing +
corrupt +
unresolved
```

For the reconciliation, `corrupt` includes checksum-corrupt and malformed
payload classifications. The report also stores `accounted_partitions` and a
`balanced` boolean. The verifier exits nonzero if reconciliation is unbalanced or
if `missing`, `corrupt`, or `unresolved` is nonzero.

### Shared XAUUSD market calendar

Dukascopy Bank's published [Trading Hours](https://www.dukascopy.com/swiss/english/forex/forex-trading-accounts/link/)
specifies ordinary trading from Sunday 21:00 UTC through Friday 21:00 UTC
during summer time and from Sunday 22:00 UTC through Friday 22:00 UTC during
winter time. The same table specifies an XAU/USD maintenance break of
21:00–22:00 UTC during summer time and 22:00–23:00 UTC during winter time.

D001 represents both the weekly session and daily maintenance boundaries in one
versioned `symbol_market_calendars.XAUUSD` rule using the IANA
`Europe/London` calendar:

| Calendar interval | London local time | Summer UTC | Winter UTC |
|---|---|---|---|
| Weekly market close | Friday 22:00 through Sunday 22:00 | Friday 21:00 through Sunday 21:00 | Friday 22:00 through Sunday 22:00 |
| Daily maintenance | 22:00–23:00 Monday–Friday | 21:00–22:00 UTC | 22:00–23:00 UTC |

The timezone database, rather than a hard-coded month or list of transition dates,
therefore determines each year's DST boundaries. On transition weekends, the
Friday and Sunday UTC boundaries can differ by one hour because each boundary is
converted independently through the London calendar. The rule is symbol-specific
and does not change other instruments. Its source URL, named calendar, weekly
boundaries, maintenance interval, and weekdays are retained in the TOML and copied
into every JSON verification report. The downloader and verifier call the same
calendar function.

The verifier requires two independent conditions before it reports
`expected_market_closure`:

1. The exact native UTC hour matches the configured rule for the requested symbol.
2. The manifest preserves affirmative source evidence that the response was empty,
   or uses an explicitly enumerated no-data status.

A calendar match does not convert an HTTP or network error into a closure. A
recorded `empty_payload` is accepted only inside the matching calendar hour.
Missing files or manifest records, timeouts, proxy failures, HTTP responses,
decode failures, and ambiguous prior closure labels are not closure evidence. A
non-empty object is always checksum-checked and BI5-validated first; checksum
drift remains `corrupt_partition`, and malformed LZMA/BI5 or placeholder content
remains `malformed_payload`, even during a calculated closure.

When the downloader receives a confirmed empty response inside the shared
calendar, it records `status = expected_market_closure` immediately and preserves
the `empty_payload:` source evidence in `error_details`. Empty responses during
open hours remain failed/unresolved. Legacy UTC rules remain available through
`full_day_closed_weekdays`, `explicit_closed_dates`, and
`closed_utc_hours_by_weekday`, but the default XAUUSD weekend is not duplicated in
those tables.

Existing manifests can be re-evaluated without source access or manifest writes:

```bash
python scripts/verify_dukascopy_downloads.py \
  --symbol XAUUSD \
  --start 2024-10-07T19:00:00Z \
  --end 2026-01-01T00:00:00Z \
  --reclassify-empty-closures
```

This report-only mode never downloads data and never mutates the manifest. Its
JSON/Markdown outputs list every `empty_payload` transition from unresolved to
expected closure and group every remaining blocking timestamp by evidence/error
kind. Ambiguous legacy labels that do not preserve affirmative empty/no-data
evidence remain unresolved even if the calendar says the market was closed.

### Targeted unresolved-evidence recovery

Use the verifier JSON as an exact request allowlist when source evidence must be
refreshed:

```bash
python scripts/download_dukascopy_ticks.py \
  --symbol XAUUSD \
  --start 2021-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z \
  --targeted-recovery-report data/reports/dukascopy_XAUUSD_download_quality.json \
  --targeted-recovery-expected-count 6754 \
  --proxy-file proxies.txt
```

The downloader validates that the report symbol and `[start, end)` range match
exactly. Every timestamp in every
`reclassification_audit.remaining_unresolved_by_error_kind` group forms the
request allowlist; this includes empty-payload, HTTP, timeout, connection, and
other unresolved evidence categories without special-case duplication. Every
other hour is excluded before file or transport processing.

Before constructing a network client, targeted recovery fails closed unless the
report is balanced, covers every expected hour exactly once, the grouped
timestamps exactly equal the report's unresolved classifications, no timestamp
is duplicated or outside the requested range, and no verified or confirmed
closure classification overlaps the allowlist. The optional
`--targeted-recovery-expected-count` adds an operator-supplied exact-count gate.
The `targeted_recovery_preflight` JSONL event preserves these audit counts and
per-group totals. An allowlisted hour that has become verified or a confirmed
closure is skipped on resume.

Each final attempt records `evidence_kind`, HTTP status, response byte length,
retry count, masked proxy identity, and final-attempt timestamp alongside the
existing status, error, checksum, and record-count fields. Credentials are never
stored. A valid BI5 response is written through the existing atomic path; empty,
HTTP, proxy, timeout, TLS/SSL, connection, and malformed-response outcomes retain
their distinct evidence kinds.

After recovery, write a separate special-hours research list while rerunning the
full verifier:

```bash
python scripts/verify_dukascopy_downloads.py \
  --symbol XAUUSD \
  --start 2021-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z \
  --reclassify-empty-closures \
  --holiday-candidates-report \
    data/reports/dukascopy_XAUUSD_holiday_candidates.json
```

## Canonical Build

```bash
python scripts/build_dukascopy_canonical.py \
  --start 2021-11-25T00:00:00Z \
  --end 2021-11-29T00:00:00Z
```

The D003 builder independently verifies each selected checksum and payload. It
never decodes a raw partition whose classification is not `verified_data`,
never imputes ticks, and never reads or joins the MT5 feed. D001 regular
closures and exact partitions in the accepted D002 report-only overlay are
excluded and reconciled; a missing, corrupt, malformed, or unexplained hour
stops the build.

The canonical schema is:

| Column | Type | Meaning |
|---|---|---|
| `timestamp_utc` | `timestamp[ms, tz=UTC]` | Source hour plus millisecond offset |
| `bid` | `float64` | Dukascopy bid after configured scaling |
| `ask` | `float64` | Dukascopy ask after configured scaling |
| `bid_volume` | `float32` | Source bid volume |
| `ask_volume` | `float32` | Source ask volume |
| `mid` | `float64` | `(bid + ask) / 2` |
| `spread` | `float64` | `ask - bid` |
| `symbol` | `string` | Requested canonical symbol |
| `source_partition` | `string` | Native archive hour in UTC |

Output is partitioned as:

```text
data/canonical/xauusd_ticks/canonical_manifest.json
data/canonical/xauusd_ticks/year=YYYY/month=MM/xauusd_ticks_YYYY-MM-DD.parquet
```

Rows use a stable chronological sort and exact duplicates are removed with
within-partition and partition-boundary counts. Invalid records fail closed.
Daily files are created atomically and never overwritten. The checkpointed
manifest permits resume only when file hashes and source fingerprints match.
Rebuilding identical verified inputs and configuration therefore reuses the
completed output unchanged.

Run the independent D003 verifier with:

```bash
python -m scripts.validate_canonical_dataset
```

See [`D003_CANONICAL_XAUUSD_TICKS.md`](D003_CANONICAL_XAUUSD_TICKS.md) for the
existing-builder assessment, complete manifest contract, resume rules, and
verification scope.

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
- The shared calendar covers the source-backed XAUUSD weekly session and daily
  maintenance interval. Special US-holiday hours can remain unresolved; they are
  not inferred from the ordinary calendar.
- An empty/no-tick object is not accepted automatically. It remains unresolved
  unless the exact symbol calendar rule also matches.
- Large builds process one UTC day at a time but still require enough memory for one
  day of decoded ticks.
- Quality thresholds flag observations; they do not repair, remove, or impute them.
- `latest.json` is a local convenience pointer, not a mutable combined feed.
