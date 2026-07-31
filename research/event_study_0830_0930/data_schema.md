# Empirical Data Schemas

These schemas belong only to the isolated XAUUSD event study. Raw measurements remain immutable; adapters write normalized derivatives. UTC is the internal clock. `America/New_York` is derived only for release and session analysis with IANA timezone rules.

## Mode A: one-minute bid/ask bars

One row represents `[timestamp, timestamp + 1 minute)`.

| Column | Type | Required | Meaning |
|---|---|---:|---|
| `timestamp` | timezone-aware datetime | yes | Minute start in UTC |
| `bid_open`, `bid_high`, `bid_low`, `bid_close` | positive float | yes | Bid-side OHLC |
| `ask_open`, `ask_high`, `ask_low`, `ask_close` | positive float | yes | Ask-side OHLC |
| `tick_volume`, `real_volume` | non-negative number | no | Source-defined volume; provenance must explain semantics |
| `source` | string | yes | Vendor/broker/feed identifier |
| `symbol` | string | yes | Source symbol, normally `XAUUSD` or a documented suffix variant |
| `mid_open`, `mid_high`, `mid_low`, `mid_close` | float | no | Analytical midpoint fields; never executable prices |
| `tick_count` | integer | no | Ticks observed in the minute |
| `median_spread`, `maximum_spread`, `last_spread` | float | no | Tick-derived spread summaries in price units |

Bid and ask OHLC are validated independently. A single-price OHLC export is not expanded into bid and ask bars.

## Mode B: ticks

| Column | Type | Required | Meaning |
|---|---|---:|---|
| `timestamp` | timezone-aware datetime | yes | Tick timestamp converted to UTC without truncation |
| `bid`, `ask` | positive float | yes | Executable quoted sides |
| `bid_size`, `ask_size` | non-negative number | no | Displayed size where supplied |
| `source` | string | yes | Vendor/broker/feed identifier |
| `symbol` | string | yes | Source symbol |

Tick aggregation groups by left-closed UTC minute. Bid and ask OHLC are calculated independently; midpoint OHLC is calculated from per-tick midpoints. Tick count, median spread, maximum spread and last spread are retained. No minute is forward-filled.

## Canonical economic releases

| Column | Type | Required | Integrity rule |
|---|---|---:|---|
| `event_id` | string | yes | Stable source identifier or deterministic hash |
| `release_timestamp_utc` | timezone-aware datetime | yes | Canonical event time |
| `release_timestamp_new_york` | timezone-aware datetime | yes | IANA-derived analytical time |
| `event_name`, `institution`, `country`, `category`, `importance` | string | yes | `importance` is `major`, `minor` or `none` |
| `actual`, `consensus`, `previous`, `revised_previous` | float/null | no | Values known for the stated release vintage |
| `unit`, `release_version`, `source`, `source_url` | string | yes | Provenance and vintage fields |
| `retrieval_timestamp` | timezone-aware datetime/null | no | When the record was retrieved |
| `point_in_time_verified` | boolean | yes | Controls surprise eligibility |
| `notes` | string | yes | Free-text limitation or provenance note |

The adapter additionally emits `event_type`, surprise fields and explicit exclusion reasons. Standardized surprises use prior observations only and are grouped by event type and unit so incompatible scales are not pooled. Unverified records remain usable for timing-only analysis but receive no surprise value.

Supported event classifications include CPI/Core CPI, NFP, unemployment, hourly earnings, PPI/Core PPI, retail/core retail sales, GDP, jobless claims, durable goods, income, spending, PCE/Core PCE, ISM manufacturing/services, Consumer Confidence, JOLTS, University of Michigan and relevant Federal Reserve events.

## Event clusters

Releases sharing an exact UTC timestamp form one cluster. Cluster rows preserve event IDs, names and individual surprise records as JSON arrays; they also report event count, dominant-event status, conflicting directional mappings, combined-surprise completeness and whether event-specific attribution must be excluded.

## Quality report

`data_quality_report.json` contains the validation status, critical violations, start/end, row count, missing-minute percentage, duplicates, spread diagnostics, OHLC errors, weekend/closure records, missing event windows, DST round-trip errors, and year/month coverage. Missing observations are reported, never filled.
