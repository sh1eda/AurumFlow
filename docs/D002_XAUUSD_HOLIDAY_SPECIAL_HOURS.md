# D002 — XAUUSD Holiday and Special-Hours Calendar Research

## Scope and decision

D002 evaluates the 757 `empty_payload_open_market` records in:

`data/reports/dukascopy_XAUUSD_holiday_candidates_2021_2026.json`

for the half-open range `2021-01-01T00:00:00Z` through
`2026-01-01T00:00:00Z`. It is an offline, report-only calendar overlay. It
does not modify the D001 regular calendar, the Dukascopy manifest, verified BI5
files, canonical data, production strategy code, or research logic.

Decision:

- `expected_holiday_closure`: 413 hourly partitions
- `expected_special_hours_closure`: 344 hourly partitions
- `unexplained_empty_payload`: 0 hourly partitions

The 757 inputs were grouped into 380 contiguous intervals before the calendar
research was applied.

## Fail-closed evidence policy

A D002 closure classification requires both:

1. an exact hourly match to a source-backed D002 calendar rule; and
2. preserved source evidence showing HTTP 200, a zero-byte response, and
   `confirmed_empty_payload`.

An empty response alone is not evidence of a closure. HTTP, proxy, TLS,
timeout, connection, decode, malformed non-empty payload, checksum, missing
file, and missing-manifest conditions are ineligible. An unmatched or
ineligible record remains `unexplained_empty_payload`.

The machine-readable calendar is
[`config/dukascopy_XAUUSD_holiday_calendar.json`](../config/dukascopy_XAUUSD_holiday_calendar.json).
Each rule contains its closure type, supporting source IDs, publication/date,
applicable timezone, exact interval, and confidence. The audit expands this
metadata onto every classified partition.

## Source-backed calendar findings

### XAU Sunday opening hour

Dukascopy’s current trading-hours page publishes the general market opening
at 21:00 GMT in summer and 22:00 GMT in winter, while the XAU/USD settlement
break occupies 21:00–22:00 GMT in summer and 22:00–23:00 GMT in winter.
Dukascopy’s original XAU/USD launch notice states the consequence explicitly:
summer XAU trading begins Sunday at 22:00 GMT.

The exact first Sunday hour is therefore classified as
`expected_special_hours_closure` when the payload is confirmed empty. The rule
is represented as Sunday 17:00–18:00 `America/New_York`, which expands to
21:00–22:00 UTC in U.S. daylight time and 22:00–23:00 UTC in U.S. standard
time.

Sources:

- [Dukascopy General Features — Trading Hours](https://www.dukascopy.com/swiss/english/forex/forex-trading-accounts/link/)
- [Dukascopy XAU/USD launch notice, 2011-04-08](https://www.dukascopy.com/swiss/english/about/ournews/-dbl194921)

### U.S. versus European DST transition weeks

Dukascopy’s annual notices state that its market opening and daily settlement
follow 17:00 New York. For XAU/USD, the settlement boundary changes from 22:00
to 21:00 GMT when U.S. daylight time starts and returns to 22:00 GMT when U.S.
daylight time ends.

This matters during the weeks when `America/New_York` and `Europe/London`
change clocks on different Sundays. D002 classifies only the confirmed-empty
21:00–22:00 UTC partitions that the authoritative U.S.-DST schedule closes
while the frozen D001 Europe/London rule still considers them open. Hours on
the aligned side of each boundary do not match the D002 special-hours rule.

Annual source examples:

- [2021 U.S. DST start](https://www.dukascopy.com/europe/english/about/ournews/change-to-daylight-saving-time-2021-in-us)
- [2023 U.S. DST start](https://www.dukascopy.com/europe/hu/about/ournews/change-to-daylight-saving-time-2023-in-the-us)
- [2024 U.S. DST start](https://www.dukascopy.com/swiss/it/about/ournews/daylight-saving-time-2024-in-the-us)
- [2025 U.S. DST start](https://www.dukascopy.com/swiss/french/about/ournews/daylight-saving-time-2025-in-the-us)
- [Dukascopy explanation of the EU/U.S. end-date gap](https://www.dukascopy.com/swiss/english/about/ournews/daylight-savings-time-ends-dbl200887/)
- [2024 U.S. DST end](https://www.dukascopy.com/swiss/english/about/ournews/daylight-savings-time-ends-in-us-dbl202961)

### Good Friday

Dukascopy’s Easter notices identify Good Friday closures. Its detailed
historical XAU schedule states that gold and silver stop after Thursday
settlement, remain closed on Good Friday, and resume after the Sunday XAU
opening break. D002 encodes the exact candidate-side intersection for every
Good Friday from 2021 through 2025.

Sources:

- [Detailed Dukascopy Easter gold schedule](https://www.dukascopy.com/swiss/english/about/ournews/easter-holiday-news)
- [Easter closures 2021](https://www.dukascopy.com/swiss/english/about/ournews/easter-weekend-market-closures-2021)
- [Easter closures 2024](https://www.dukascopy.com/swiss/pt/about/ournews/easter-weekend-market-closures-2024)
- [Easter closures 2025](https://www.dukascopy.com/swiss/english/about/ournews/easter-weekend-market-closures-2025)

### U.S. national holidays and early closes

Dukascopy’s current XAU/USD specification publishes a non-trading window on
U.S. national holidays. D002 combines that instrument rule with official U.S.
holiday dates and dated Dukascopy Bullion notices. Covered families are Martin
Luther King Jr. Day, Washington’s Birthday, Memorial Day, Juneteenth,
Independence Day, Labor Day, and Thanksgiving.

Thanksgiving Friday is not treated as a full national-holiday closure. Dated
Dukascopy notices explicitly identify special closures on both Thursday and
Friday, so the Friday intervals are
`expected_special_hours_closure`.

Sources:

- [U.S. Office of Personnel Management federal-holiday schedules](https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/)
- [Dukascopy Memorial Day 2021](https://www.dukascopy.com/swiss/english/about/ournews/market-closures-on-memorial-day-dbl202104)
- [Dukascopy Independence Day 2022](https://www.dukascopy.com/swiss/english/about/ournews/market-closures-on-independence-day-in-the-us-dbl202410/)
- [Dukascopy Juneteenth 2025](https://www.dukascopy.com/swiss/english/about/ournews/juneteenth-national-independence-day-dbl203146)
- [Dukascopy exact MLK Day Gold/Silver hours](https://www.dukascopy.com/swiss/english/about/ournews/martin-luther-king-day)
- [Dukascopy exact Labor Day Gold/Silver hours](https://www.dukascopy.com/swiss/english/about/ournews/september-2nd-ndash-us-labor-day-holiday)
- [Dukascopy exact Thanksgiving Gold/Silver hours](https://www.dukascopy.com/swiss/english/about/ournews/us-thanksgiving-holiday-trading-hours-dbl200902/)
- [Dukascopy Thanksgiving 2023](https://www.dukascopy.com/swiss/english/about/ournews/thanksgiving-day-in-the-us-dbl202684)
- [Dukascopy Thanksgiving 2025](https://www.dukascopy.com/swiss/english/about/ournews/thanksgiving-day-in-the-us-dbl203236)

### Christmas and New Year

Dated Dukascopy notices identify FX and Bullion market closures across
Christmas and New Year. D002 classifies the full holiday intervals and keeps
the separately supported Christmas Eve early-close partitions under
`expected_special_hours_closure`. Observed-day handling is cross-checked
against the official U.S. convention.

Sources:

- [Dukascopy exact Gold/Silver holiday schedule, 2013-12-09](https://www.dukascopy.com/swiss/english/about/ournews/holiday-trading-hours-schedule-dbl199995/)
- [Dukascopy Christmas/New Year 2022](https://www.dukascopy.com/swiss/arabic/about/ournews/market-closures-during-x-mas-and-new-year)
- [Dukascopy Christmas/New Year 2023](https://www.dukascopy.com/swiss/english/about/ournews/market-closures-on-christmas-and-new-year-dbl202761)
- [Dukascopy Christmas/New Year 2024](https://www.dukascopy.com/swiss/english/about/ournews/market-closures-during-x-mas-and-new-year-dbl203022)
- [Dukascopy Christmas/New Year 2025](https://www.dukascopy.com/swiss/english/about/ournews/market-closures-during-x-mas-and-new-year-dbl203256)

### Rules not applied

No standalone UK or European civil-holiday rule was applied. The candidate
hours were already covered by more directly applicable Dukascopy XAU/USD,
Bullion, Easter, Christmas/New Year, or U.S.-holiday schedules. No exceptional
maintenance rule was added either: the frozen D001 calendar remains
authoritative for normal maintenance, and D002 does not infer exceptional
maintenance from an empty response.

## Reconciliation

Before D002:

`43824 = 29563 verified + 13504 regular closures + 0 holiday closures + 0 special-hours closures + 0 missing + 0 corrupt + 757 unresolved`

After D002:

`43824 = 29563 verified + 13504 regular closures + 413 holiday closures + 344 special-hours closures + 0 missing + 0 corrupt + 0 unresolved`

The result is balanced.

## Integrity controls

Before classification, D002 wrote a read-only baseline containing:

- the full reconciliation;
- every verified path and file size;
- every stored and computed SHA256;
- verified manifest status and evidence kind; and
- all unresolved timestamps and their evidence fields.

After classification, D002 re-read the manifest and every verified BI5 file.
It fails if any verified file is added, removed, renamed, resized, or modified;
if a stored SHA256 changes or no longer matches; if a previously verified
partition is downgraded; if a closure lacks confirmed-empty evidence; or if the
reconciliation is not balanced.

The final integrity result is pass:

- 29,563 verified files before and after;
- manifest SHA256 unchanged;
- no added, removed, renamed, resized, or downgraded verified partition;
- every stored SHA256 matches the corresponding BI5 file;
- zero closure classifications without confirmed-empty evidence.

Generated audit artifacts:

- `data/reports/D002_XAUUSD_baseline_2021_2026.json`
- `data/reports/D002_XAUUSD_holiday_special_hours_audit.json`
- `data/reports/D002_XAUUSD_holiday_special_hours_audit.md`
- `data/reports/D002_XAUUSD_unexplained_timestamps.json`

Run:

```bash
python scripts/research_dukascopy_holiday_calendar.py --baseline-only
python scripts/research_dukascopy_holiday_calendar.py
```

The first command must be executed before classification and is intentionally
read-only with respect to manifest and BI5 data.
