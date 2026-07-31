# Official-source calendar review

## Scope and decision

This review was completed before calendar collection. It covers the XAUUSD study interval from 2025-07-17 through 2026-07-17 and treats `America/New_York` as the canonical release timezone. Official agency schedules and vintage release archives are the primary timing sources. The Federal Reserve Bank of New York historical economic-indicator calendar is used only as an official archival timing cross-check where an institutional publisher supplies a date but not a durable public timestamp.

No trustworthy, redistributable historical consensus source was identified. Consensus fields must therefore remain null. The calendar can support timing, clustering, release-category, and official-vintage attribution, but the initial gate cannot claim complete surprise analysis.

## Source decisions by family

### BLS releases

The BLS release calendar explicitly states that calendar times are Eastern Time and provides monthly and release-family archives. It is the primary source for CPI, PPI, Employment Situation components, JOLTS, import/export prices, ECI, productivity, and unit labor costs. The archived release page is the value-vintage authority when actual or revision fields are later added. The final schedule must preserve dates revised after the 2025 and 2026 appropriations lapses rather than using superseded planned dates.

Reliability: `OFFICIAL_PRIMARY`.

### Census and joint Census/BEA releases

The Census annual list-view calendars provide indicator, release date, release time, reference period, and program identifiers. They also retain suspended and delayed 2025 entries, which is essential for fail-closed non-news classification. These calendars are primary for retail sales, durable goods, starts and permits, new-home sales, factory orders, construction spending, business/wholesale inventories, and the joint trade release.

Reliability: `OFFICIAL_PRIMARY`.

### BEA releases

BEA's full 2025 and current 2026 schedules distinguish GDP estimate vintages and Personal Income and Outlays releases. BEA schedule-update notices document post-shutdown changes, including combined or delayed GDP and PCE publications. Those actual publication dates take precedence; original scheduled dates are preserved separately where published.

Reliability: `OFFICIAL_PRIMARY`.

### Weekly unemployment claims

DOL/ETA release PDFs state the publication timestamp and preserve the claims week and revision. Weekly dates require archive-level verification because holiday weeks can move the normal Thursday 08:30 ET publication. A generated every-Thursday rule alone is insufficient.

Reliability: `OFFICIAL_ARCHIVE`.

### Federal Reserve releases

The G.17 page and announcement feed document 09:15 ET Industrial Production and Capacity Utilization releases, including the delayed September-November 2025 sequence. The FOMC calendar supplies meeting decisions, statements, SEP materials, press conferences, and minutes. Monetary-policy records remain separate from ordinary macro releases.

Reliability: `OFFICIAL_PRIMARY`.

### Regional Federal Reserve surveys

The New York Fed Empire State survey archive states that releases occur at or shortly after 08:30. The Philadelphia Fed Manufacturing Business Outlook Survey calendar specifies 08:30 and its archived PDFs explicitly preserve release vintages. Both are included as regional manufacturing categories rather than national PMIs.

Reliability: `OFFICIAL_PRIMARY`.

### ISM

ISM's official calendar specifies Manufacturing on the first business day and Services on the third business day at 10:00 ET, with dated holiday exceptions. Only schedule metadata and public release URLs are used; proprietary report content is not redistributed.

Reliability: `OFFICIAL_PRIMARY` for timing.

### Consumer sentiment publishers

The Conference Board publishes Consumer Confidence at 10:00 ET on the last Tuesday of each month. Its page warns that the data are copyrighted, so only timing metadata is retained. University of Michigan supplies an official preliminary/final date document, but its durable public page does not establish every historical release time; 10:00 ET is accepted only when corroborated by the New York Fed official calendar mirror. Values are not redistributed.

Reliability: `OFFICIAL_PRIMARY` for Conference Board schedule timing and `OFFICIAL_ARCHIVE` for Michigan date plus mirror-confirmed time.

### Housing institutional release

NAR provides annual Existing-Home Sales schedules and states 10:00 ET on release pages. Timing metadata is included. NAR values are not redistributed because the publisher restricts storage and redistribution.

Reliability: `OFFICIAL_PRIMARY` for timing.

### S&P Global U.S. PMI

S&P Global bulletins are copyrighted, monthly archives are not consistently accessible, and the study cannot guarantee a complete public historical 09:45 ET inventory without licensed access. This source is classified `UNUSABLE` for the present build and is not collected. Calendar completeness must explicitly disclose the missing 09:45 PMI family; affected days cannot be called fully complete for all requested event families.

## Consensus and revision policy

Official publishers generally do not publish pre-release market consensus. No consensus will be estimated, inferred from price, copied from an unattributed retail calendar, or backfilled from later commentary. `consensus`, `consensus_source`, and surprise fields remain null unless a separately licensed, auditable source is added later.

Official previous and revised-previous fields are populated only when the vintage release itself supplies both values and the extraction is deterministic. Latest revised time-series data must remain in `latest_revised_value` and cannot replace the release-time actual or prior. The first build is therefore expected to be timing-complete for usable source families but value-incomplete.

## Importance rule

Importance is a research classification, not a retail-calendar label:

- `major`: CPI/PPI headline and core, Employment Situation components, retail sales, GDP, PCE price indexes, ISM, JOLTS, and scheduled FOMC decisions/statements/SEP/press conferences/minutes.
- `minor`: jobless claims, personal income/spending, durable goods, trade, ECI, productivity/unit labor costs, import/export prices, Industrial Production/Capacity Utilization, Consumer Confidence, Michigan sentiment, housing, regional Fed surveys, factory orders, construction spending, and inventories.
- `none`: out-of-scope informational publications retained only for schedule provenance; these are normally excluded from the canonical event inventory.

## Fail-closed rules

- A date is `no_scheduled_release` only when all usable source-family inventories for that date are complete.
- Suspended, postponed, or canceled entries are not treated as publications.
- A changed schedule uses the actual publication time and preserves the original scheduled time when the agency publishes it.
- Duplicate component events are rejected by deterministic event ID.
- Unknown timezone, unresolved conflicting timestamp, missing official attribution for an official value, or duplicate canonical event is a blocking error.
- Missing consensus is a warning and disables surprise features; it does not invalidate timing analysis.

## Expected gate

Unless a trustworthy historical consensus dataset is supplied, the maximum defensible verdict is `READY_FOR_TIMING_ONLY_STAGE1`. This review does not authorize or run Stage 1.

## Reproducibility

Raw official pages are intentionally git-ignored. Their filenames and SHA-256 hashes are recorded in `calendar_quality_report.json`; the public URLs and archive methods are in `calendar_source_register.csv`. An exact historical rebuild requires the same frozen raw pages because live agency schedules are mutable.

From the repository root, after restoring the frozen pages under `external_data/raw/calendar`, rebuild the timing inventory and reports with:

```bash
python -m research.event_study_0830_0930.official_calendar_builder
```

Then verify the required adapter round-trip with:

```bash
python -m research.event_study_0830_0930.empirical_cli import-calendar \
  --input research/event_study_0830_0930/external_data/calendar/us_releases_point_in_time.csv \
  --adapter generic-csv \
  --source-timezone America/New_York \
  --source official_release_archive \
  --events-output research/event_study_0830_0930/external_data/calendar/us_releases.canonical.csv \
  --clusters-output research/event_study_0830_0930/external_data/calendar/us_release_clusters.csv \
  --metadata-output research/event_study_0830_0930/external_data/calendar/calendar_metadata.json
```

Neither command reads market data or runs Stage 1.
