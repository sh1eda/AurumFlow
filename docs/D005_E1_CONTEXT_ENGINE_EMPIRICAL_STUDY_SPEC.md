# D005_E1 Context Engine Empirical Study Specification

## Status and boundary

`D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY` is a descriptive, isolated
evaluation of the approved D005 research engine. It does not change D005
defaults, authorize entries, define trade expectancy, select an Order Block
winner, or connect any output to production strategy, execution, or risk
code.

The study reads only the hash-verified one-minute derivative built from the
immutable D003 canonical XAUUSD tick dataset. All features and snapshots use
closed-bar availability. Forward outcomes are joined only after an anchor
event has been created and are never inputs to a state or gate.

## Frozen main-study configuration

- Requested data period: 2021-01-03 through 2025-12-31, subject to observed
  data and the warm-up requirements below.
- Evaluation timezone: `America/New_York`.
- Fixed observation clocks: 08:30, 09:00, 10:00, and 12:00 New York.
- Clocks are labels only and cannot create direction.
- D005 mappings remain separate:
  - Weekly → 4H → 1H;
  - Daily → 1H → 15m;
  - 4H → 15m → 5m;
  - 1H → 5m; and
  - 1H → 5m → optional 1m as a separate configuration fingerprint.
- D005 MSS, displacement, PMH/PML, balance, risk, and timeout defaults remain
  unchanged.
- No alternative threshold is part of the main study.

The rolling causal warm-up is a computational study setting rather than a
D005 threshold:

| Mapping | Warm-up |
|---|---:|
| Weekly → 4H → 1H | 180 calendar days |
| Daily → 1H → 15m | 45 calendar days |
| 4H → 15m → 5m | 20 calendar days |
| 1H → 5m | 8 calendar days |
| 1H → 5m → 1m | 8 calendar days |

These intervals cover at least the frozen 20-bar balance lookback plus pivot
and ATR history on each parent timeframe. Weekly remains 180 calendar days
because twenty completed weekly bars require materially more calendar history.

Every evaluation records its warm-up bound. A snapshot that lacks the frozen
D005 minimum history fails closed. The report must identify left-edge and
missing-data exclusions.

## Evaluation modes

### Mode A — fixed observation

Evaluate every data-qualified weekday at each configured clock for every
mapping variant. The bar closing exactly at the observation timestamp is
available; a bar opening at that timestamp is not.

### Mode B — event driven

Build a causal candidate schedule from the newly available timestamps of:

- confirmed parent pivots that can change context;
- HTF FVG/OB interaction or invalidation;
- named parent liquidity sweep;
- first body-close MSS for a confirmed pivot;
- displacement confirmation;
- refinement FVG/OB interaction or invalidation;
- PMH/PML sweep in the frozen 08:30–09:00 observation interval;
- candidate timeout; and
- a state transition discovered by a preceding evaluation.

Candidate timestamps are only evaluation triggers. The frozen D005 engine
decides the state. Rows with the same mapping variant, state, direction,
evidence IDs, gates, and transition path are deduplicated until one of those
fields changes. Trigger families are retained as a list.

For computational tractability, the main run preregisters a maximum of 12
event evaluations per New York date and mapping. Reaction confirmation,
conflict, invalidation, timeout, HTF POI interaction, and named liquidity
sweep timestamps receive first priority. The uncapped, selected, and omitted
date-level trigger counts are retained in the event-schedule artifact. This
is an observation-sampling limit, not a D005 strategy threshold; conclusions
must disclose schedule truncation and cannot infer absence from omitted
lower-priority timestamps.

## Gate attribution

The study preserves the engine reasons and maps them to these non-exclusive
research labels:

| Engine evidence | E1 gate label |
|---|---|
| parent/child direction conflict | `parent_child_conflict` |
| no qualified context event | `missing_reaction` |
| body-close MSS absent | `mss_failure`, `missing_reaction` |
| measurable displacement absent | `displacement_failure`, `missing_reaction` |
| lower-timeframe refinement absent | `missing_refinement`, `no_aligned_fvg_or_zone` |
| opposing-array trap | `trapped_between_opposing_arrays` |
| unresolved boundaries | `unresolved_range` |
| move overextended | `overextension` |
| proposed risk invalid | `invalid_risk` |
| candidate age exceeds frozen timeout without MSS | `candidate_timeout` |
| required bars/history absent | `missing_data` |
| unresolved or non-balanced context at PMH/PML fallback time | `pmh_pml_prerequisite_failure` |

Co-attribution is intentional and reported in both marginal and overlap
tables. Gates are not loosened.

## Event and array definitions

Raw FVG, contextual flags, and all three OB definitions are inherited from
D005. E1 additionally records two descriptive IFVG lifecycle timestamps:

- `wick_violation_at`: first completed bar whose wick fully crosses the distal
  FVG boundary; and
- `body_close_violation_at`: first completed bar whose close crosses that
  boundary.

These do not alter D005 invalidation.

IFVG lifecycle observation is capped at 30 calendar days after formation to
keep the variant horizon explicit and computationally bounded. Rows reaching
the cap without violation are censored rather than classified as permanent.

An OB/FVG interaction is the first completed bar overlapping the zone after
the array was available. Zone excursion anchors use that completed
interaction timestamp and the contemporaneous one-minute close. No assumed
entry is created.

OB overlap definitions are frozen as:

- FVG overlap: same-direction zones geometrically overlap and their
  availability timestamps are no more than one parent bar apart;
- liquidity overlap: a same-direction named sweep became available during
  the preceding 12 reaction bars.

## Forward outcomes

Anchors are newly observed context events and deduplicated state transitions.
The anchor price is the latest completed one-minute mid close at or before the
anchor timestamp.

Outcomes are measured at:

- 15, 30, 60, and 120 minutes;
- the next New York noon when the anchor precedes noon; and
- the 17:00 New York trading-day boundary.

Directional rows record price-unit signed change, MFE, MAE, and time to each
extreme. Neutral rows have no signed return; they record absolute change and
high-low expansion. No spread, slippage, position size, stop, target, or P&L
is assumed.

Where an observable opposing liquidity level and zone/swing invalidation
level both exist at the anchor, E1 records which was reached first. Levels
created after the anchor are ineligible.

## Stability definitions

- Volatility regime is causal: the most recently completed D005 daily range
  divided by the median of the previous 20 completed daily ranges.
  - `low`: ratio < 0.75;
  - `normal`: 0.75–1.25;
  - `high`: ratio > 1.25;
  - `unavailable`: insufficient history.
- DST is derived from the New York IANA UTC offset at the anchor.
- Sessions are exclusive New York intervals:
  - `asia`: 18:00–00:00;
  - `premarket`: 00:00–08:30;
  - `ny_observation`: 08:30–12:00;
  - `ny_afternoon`: 12:00–17:00;
  - `maintenance`: 17:00–18:00.
- Bootstrap intervals use a fixed seed and resample trading dates, not
  individual overlapping events.

No pooled statistic alone may rank or promote a mapping or variant.

## Required artifacts

All writes are confined to
`research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/`:

- `context_snapshots.parquet`
- `state_transitions.parquet`
- `transition_funnel.parquet`
- `gate_attribution.parquet`
- `gate_overlap.parquet`
- `conflicts.parquet`
- `invalidations.parquet`
- `fvg_event_statistics.parquet`
- `order_block_event_statistics.parquet`
- `order_block_variant_summary.parquet`
- `liquidity_events.parquet`
- `pmh_pml_events.parquet`
- `forward_outcomes.parquet`
- `annual_summary.parquet`
- `monthly_summary.parquet`
- `regime_summary.parquet`
- `mapping_summary.parquet`
- `timing_guardrail_summary.parquet`
- `data_quality_periods.parquet`
- `excluded_evaluations.parquet`
- `configuration_snapshot.json`
- `implementation_provenance.json`
- `reproducibility_metadata.json`
- `summary.json`
- `artifact_manifest.json`
- `D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_REPORT.md`

## Acceptance criteria

1. E1 is a separate package and output directory with no production import.
2. Existing D005 output files are not modified.
3. Both modes and all five mapping variants are represented.
4. All fixed clocks are evaluated as observation labels only.
5. Event triggers are causal and identical snapshots are deduplicated.
6. Every unavailable/future bar is excluded before feature construction.
7. Gate attribution retains exact D005 reasons and non-exclusive E1 labels.
8. FVG categories and IFVG lifecycle variants remain separate.
9. OB variants remain separate and no canonical winner is selected.
10. PMH/PML remains `[00:00,08:30)` New York and cannot override HTF context.
11. Forward outcomes are downstream-only and neutral anchors remain unsigned.
12. Annual, monthly, mapping, regime, direction, outcome, session, and DST
    breakdowns are emitted.
13. Source, configuration, implementation, schedule, and artifact hashes are
    recorded.
14. D004’s no-standalone-edge conclusion is retained.
15. New focused tests and the full repository suite pass.
