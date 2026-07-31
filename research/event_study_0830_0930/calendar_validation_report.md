# Calendar validation report

## Gate

**READY_FOR_TIMING_ONLY_STAGE1**. The scheduled timestamps, DST conversion, source attribution, canonical classifications and one-row-per-weekday classification passed the fail-closed checks. Surprise and revision analysis is disabled because the corresponding release-vintage fields are absent.

## Coverage

- Study period: `2025-07-17` through `2026-07-17`
- Canonical timezone: `America/New_York`
- Trading weekdays classified: 262
- Events: 592
- Clusters: 266
- Simultaneous clusters: 149
- Missing classification dates: 0

### Events by ET time

- `08:30` ET: 380
- `09:15` ET: 22
- `10:00` ET: 154
- `14:00` ET: 28
- `14:30` ET: 8

### Events by category

- `business_inventories`: 13
- `construction_spending`: 12
- `consumption_retail_sales`: 26
- `durable_goods`: 24
- `factory_orders`: 12
- `growth_gdp`: 11
- `housing_sales`: 25
- `housing_starts`: 26
- `industrial_production`: 22
- `inflation_cpi`: 22
- `inflation_pce`: 22
- `inflation_ppi`: 22
- `labor_claims`: 92
- `labor_compensation`: 4
- `labor_jolts`: 11
- `labor_payrolls`: 11
- `labor_unemployment`: 11
- `labor_wages`: 11
- `manufacturing_ism`: 12
- `monetary_policy_fomc`: 36
- `personal_income`: 11
- `personal_spending`: 11
- `productivity`: 16
- `regional_manufacturing`: 25
- `sentiment_consumer`: 37
- `services_ism`: 12
- `trade`: 19
- `trade_prices`: 24
- `wholesale_inventories`: 12

## Integrity checks

- Duplicate event IDs: 0
- Duplicate canonical events: 0
- Invalid deterministic IDs: 0
- Unknown timezones: 0
- Missing source URLs: 0
- Weekend releases: 0
- Unresolved timestamp conflicts: 0
- Resolved stale-mirror conflicts: 1
- Census source rows explicitly marked suspended: 11
- Rescheduled official-release bundles preserved: 30

The UTC timestamps are derived from timezone-aware `America/New_York` timestamps, so EST/EDT is handled by the IANA timezone database. The actual publication time is canonical; known earlier schedules are retained separately.

Primary Census list-view calendars replace mirror dates for Census families; rows marked `Suspended` are not treated as releases. Primary BEA schedules are accepted only when an actual `View` release link exists, preventing planned-but-canceled GDP rows from entering the inventory. The stale October 6, 2025 NY Fed mirror entry for JOLTS was rejected in favor of the BLS release archive, which confirms the August release on September 30 and the cancellation of the September reference-period release.

The 2025/2026 BLS lapse notices are applied explicitly. Examples include Employment Situation on November 20 and December 16, CPI on October 24 and December 18, and the February 2026 JOLTS/Employment/CPI delays. The Federal Reserve G.17 release moved to December 3 and the next two planned releases were combined on December 23. BEA produced nonstandard 10:00 ET Personal Income and Outlays publications on December 5, 2025 and January 22, 2026; those times remain intact rather than being normalized to 08:30.

## Values

- Official actual values: 0 (0.0%)
- Consensus values: 0 (0.0%)
- Revision values: 0 (0.0%)
- Surprise analysis: disabled

## Simultaneous attribution

Same-source component bundles are `clean_cluster`. Independent same-time releases are `ambiguous_cluster` and excluded from single-event attribution. There are 84 ambiguous clusters and 0 evaluable conflicting-surprise clusters. Conflict evaluation cannot occur without valid surprises.

## Limitations

- No trustworthy redistributable point-in-time consensus source was established; all consensus fields are null.
- Official actual and revision vintages are not extracted in this timing build.
- S&P Global 09:45 U.S. PMI is excluded because complete historical access and redistribution rights were not established.
- Non-news classifications are relative to the registered usable official sources.
- The date grid includes every Monday-Friday ET date, including U.S. holidays; Stage 1 must intersect it with observed XAUUSD market coverage.

No market data was read, no strategy test was run, and no Stage 1 output was produced.
