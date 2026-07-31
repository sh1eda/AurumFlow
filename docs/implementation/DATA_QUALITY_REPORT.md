# Data Quality Report

## Result

The supplied MetaTrader 5 XAUUSD M15 export passed AurumFlow's structural checks and was accepted as the primary research dataset. No rows were repaired, removed, sorted, or deduplicated. A UTC-normalized local copy was written only after validation passed.

This result establishes that the file is structurally usable for research. It does not establish broker provenance, quote type, or complete session coverage.

## Source And Schema

| Field | Value |
| --- | --- |
| Source file | `data/local/XAUUSDM15.csv` |
| Source | MetaTrader 5 export |
| Symbol | XAUUSD |
| Broker/feed | Unknown |
| Price type | Unknown; bid, ask, or midpoint was not documented |
| Raw encoding | UTF-16 little-endian with BOM |
| Raw layout | Headerless, comma-delimited |
| Raw columns | Timestamp, open, high, low, close, tick volume, spread |
| Volume | MT5 tick volume; present on every row |
| Spread field | Present but zero on every row; not usable as a cost estimate |
| Normalized file | `data/local/XAUUSDM15.utc.csv` |
| Git policy | `data/local/` is ignored; neither market-data file is committed |

The headerless MT5 layout is normalized to AurumFlow's canonical schema:

```text
timestamp,open,high,low,close,volume
```

The source spread field is not part of the canonical OHLCV frame.

## Validation Command

```bash
python -m xauusd_signal data-check \
  --csv data/local/XAUUSDM15.csv \
  --source "MetaTrader 5 export" \
  --symbol XAUUSD \
  --broker unknown \
  --price-type unknown \
  --source-timezone Europe/Helsinki \
  --expected-frequency 15min \
  --normalized-output data/local/XAUUSDM15.utc.csv \
  --format json
```

## Timestamp Normalization

The source contains naive local timestamps from `2023-07-26 01:00` through `2026-07-14 19:45`. The broker server timezone was not supplied. The observed weekday close/reopen pattern is consistent with an Eastern European UTC+2/UTC+3 server clock, so `Europe/Helsinki` is the explicit research assumption. It produces the following UTC range:

- first bar open: `2023-07-25 22:00:00+00:00`
- last bar open: `2026-07-14 16:45:00+00:00`
- elapsed coverage: `1084.78125` days

`Europe/Helsinki` applies IANA daylight-saving transitions rather than a fixed offset. The source has no timezone marker, so this assumption cannot be proven from the file. If the broker used another server timezone or different DST rules, every normalized timestamp may be shifted. OHLC ordering and bar-relative strategy behavior are unchanged, but UTC calendar/session attribution can change. The exact broker timezone must be confirmed before session-dependent or live-execution research.

## Structural Findings

| Check | Result |
| --- | ---: |
| Total rows | 69,768 |
| Timestamp parse errors | 0 |
| Duplicate timestamps | 0 |
| Unsorted timestamp pairs | 0 |
| Duplicate candles | 0 |
| Rows with missing OHLC | 0 |
| Invalid OHLC relationships | 0 |
| Non-positive prices | 0 |
| Zero-range candles | 17 |
| Volume non-null | 69,768 |
| Missing volume | 0 |
| Zero volume | 0 |
| Meets one-year minimum | Yes |
| Structurally valid for research | Yes |

All OHLC relationship checks passed: each high is at least the open, close, and low; each low is at most the open and close.

## Interval And Gap Findings

There are `69,767` timestamp transitions. Of these, `68,983` are exactly 15 minutes (`98.88%`) and `784` differ from 15 minutes.

| Gap class | Count | Interpretation |
| --- | ---: | --- |
| 30 minutes | 11 | One expected bar absent or a short source closure |
| 45 minutes | 1 | Two expected bars absent or a short source closure |
| 1 hour | 2 | Three expected bars absent or a short source closure |
| 1 hour 15 minutes | 528 | Dominant daily maintenance closure pattern |
| Longer than 1 hour | 770 | Daily, weekend, holiday, or source gaps |
| Weekend-scale gaps | 155 | Predominantly two-day-plus market closures |

The checker reports `34,372` estimated missing 15-minute slots and `770` large gaps over one hour. That estimate counts every closed-market interval as if continuous trading were expected; it is not a count of proven missing candles. The 14 short anomalies from 30 minutes through one hour imply 19 absent 15-minute slots, but these also require broker-session confirmation before being classified as data loss.

There are `1,008` rows whose normalized UTC timestamp falls on Saturday or Sunday. Most are consistent with the source's server-day/session boundary and the timezone conversion; they were reported, not deleted. AurumFlow does not silently impose a weekday filter.

## Known Feed Limitations

- Broker and feed are unknown.
- Price type is unknown.
- The source timezone is inferred rather than documented.
- Tick volume is not centralized physical volume.
- The exported spread column is all zero and cannot support transaction-cost calibration.
- Market closures and true missing intervals cannot be separated without the broker's session calendar.
- The 17 zero-range candles were retained because they do not violate OHLC integrity.
- The file ends during 2026 and therefore represents 2026 year-to-date only.

## Decision

The dataset is suitable for the requested RULE_ONLY funnel and baseline measurements with the limitations above. It is not sufficient to validate broker execution costs, session-specific rules, or production behavior.
