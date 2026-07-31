# Event classification rules

## Scope

The mapping is deterministic and is applied only to registered official or official-archive release names. It does not use retail-calendar impact labels. One official release may expand into multiple measurable components, and `release_bundle_key` preserves that relationship.

## Importance rule

`major` is assigned ex ante to broad U.S. inflation, payroll/unemployment/wage, retail-sales, GDP, PCE, ISM, JOLTS and scheduled FOMC information. Other registered releases are `minor`. The label is a research stratum, not a claim that price will move and not a source-provided rating.

## Bundles and attribution

Components from the same official release share a bundle key. Same-time components in one bundle form a `clean_cluster`. Independently published releases that collide at the same time form an `ambiguous_cluster`; no dominant event is forced. Surprise conflicts can be evaluated only after point-in-time actual and consensus values exist.

## Values and revisions

All value fields are null in this timing build. `point_in_time_verified` therefore remains false even when `timing_verified` is true. A later revised time series must never be substituted for a release-vintage actual or prior value.

## Non-news-day safety

A weekday is classified as a non-news day only relative to the registered usable sources. S&P Global 09:45 PMI is excluded because a complete, redistributable official archive was not established; the limitation is carried in `calendar_completeness_status` and metadata.

## Schedule changes

The actual publication timestamp is canonical. When an official notice identifies an earlier schedule, the prior timestamp is retained in `original_scheduled_timestamp_local` and UTC, with a reason. Combined releases may retain more than one original timestamp separated by semicolons.
