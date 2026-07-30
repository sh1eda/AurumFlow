# D005 — Isolated XAUUSD Context Engine Technical Specification

## Purpose and boundary

D005 is a research-only evidence engine over immutable, closed XAUUSD bars
derived from the D003 canonical tick dataset. It must not import into, mutate,
or alter `xauusd_signal` strategy defaults, signals, execution, risk, or live
behavior.

The engine describes context evidence. It does not authorize or execute
trades. Its only actionable-looking state name, `reaction_confirmed`, means
that the configured research evidence sequence completed; it is not a
production signal.

## Inputs

- Timezone-aware UTC OHLC bars with left-aligned timestamps and explicit
  bar-close availability.
- Supported context/reaction/refinement timeframes:
  Weekly→4H→1H, Daily→1H→15m, 4H→15m→5m, and 1H→5m→optional 1m.
- D003 canonical provenance or a hash-verified derivative of D003.
- A frozen `ContextEngineConfig` containing every threshold and variant.

All source bars must be closed. A bar opening at `t` with duration `d` is
available only at `t + d`. Confirmed pivots are available only after their
right-side confirmation bar closes.

## Outputs

The primary output is an immutable `ContextSnapshot` with:

- evaluation timestamp and parent/reaction/refinement timeframes;
- evidence state: `neutral`, `provisional_context`, `candidate_poi`,
  `candidate_liquidity_event`, `reaction_confirmed`, `conflict`, or
  `invalidated`;
- non-actionable direction: bearish, neutral, or bullish;
- outcome label: reversal, continuation, or neutral;
- parent-veto/conflict result;
- detected swing/liquidity/FVG/OB/PMH/PML evidence;
- MSS, displacement, timeout, retracement, missing-data, trapped-array,
  overextension, and risk-validity gates;
- `entry_authorized=false` unconditionally in D005;
- source-rule IDs, variant IDs, parameters, and evidence timestamps.

Independent event tables are emitted for raw FVGs, each Order Block variant,
liquidity events, state transitions, and conflicts. No ambiguous aggregate
`valid_ob` field is permitted.

## Parent-veto model

Primary parent/reaction/refinement mappings:

| Parent | Reaction | Refinement |
|---|---|---|
| Weekly | 4H | 1H |
| Daily | 1H | 15m |
| 4H | 15m | 5m |
| 1H | 5m | optional 1m |

A still-valid parent direction constrains the child. A materially opposing
child direction produces `conflict`, neutral outcome, and no trade. Weighted
scoring may not resolve conflicts. Every conflict is retained with timestamps
and evidence provenance.

## Evidence state machine

Allowed forward transitions:

- `neutral` → `provisional_context`
- `provisional_context` → `candidate_poi`
- `provisional_context` → `candidate_liquidity_event`
- either candidate → `reaction_confirmed`
- any non-terminal evidence state → `conflict` or `invalidated`
- failed or expired candidates → `neutral` or `invalidated`

`provisional_context` is not actionable. `reaction_confirmed` requires:

1. HTF POI interaction or named liquidity event;
2. candle-body-close MSS on the designated reaction timeframe;
3. configured measurable displacement;
4. lower-timeframe refinement evidence; and
5. an aligned raw FVG or independently named zone variant.

D005 never emits production entry authorization.

## Feature contracts

### Swings and liquidity

- Pivots use configurable symmetric left/right widths and right-side
  confirmation delays.
- Raw liquidity includes confirmed swing highs/lows and configurable equal
  high/low clusters.
- A sweep is a configured penetration of a level followed by an optional
  body-close reclaim. Sweep and reclaim become available only at bar close.

### Fair Value Gaps

Raw FVG geometry is a three-closed-candle wick non-overlap. Detection,
interaction, qualification, and invalidation are separate fields.

Context qualification flags are independent:

- prior named liquidity event;
- body-close MSS;
- configured displacement;
- parent alignment.

IFVG wick-violation and body-close-violation variants remain separately named.

### Order Block variants

Three independent taxonomies are required:

- `consecutive_block`;
- `last_opposing_candle`;
- `inefficiency_break_origin`.

Each variant has independent geometry, creation/availability, interactions,
confirmation, invalidation, and statistics. ICT Order Blocks and SMC
supply/demand zones remain separate provenance taxonomies.

### MSS and displacement

MSS variants expose:

- pivot width;
- body-close requirement;
- direction;
- break level;
- confirmation timestamp; and
- confirmation timeout.

Displacement variants expose:

- minimum candle-body/range ratio;
- minimum true-range/prior-ATR ratio;
- maximum immediate retracement fraction;
- lookback;
- direction; and
- availability timestamp.

The terms “strong” and “clean” do not appear as executable booleans.

### PMH/PML

The default, configurable premarket interval is the half-open local window
`[00:00,08:30) America/New_York`.

- PMH is the maximum completed-bar high in the interval.
- PML is the minimum completed-bar low in the interval.
- Bounds are converted through the IANA timezone database.
- A sweep is only a manipulation clue when HTF context is unresolved and the
  configured balanced/ranging classifier is true.
- PMH/PML cannot create direction, override a valid parent, or authorize an
  entry.

### Timing guardrail

`[08:30,09:00) America/New_York` is recorded only as a research observation
and execution window. The engine contains no 09:30 NYSE, 10:00 Key Open,
index PO3, RTH, ES, NQ, NAS100, or SP500 behavior.

## Neutral/no-trade gates

The snapshot must be neutral/no-trade when any required gate fails:

- parent/child conflict;
- absent reaction confirmation;
- price trapped between opposing arrays;
- unresolved range boundaries;
- missing required closed bars;
- overextended move;
- invalid proposed research risk;
- expired confirmation timeout; or
- PMH/PML sweep without HTF-unresolved balanced/ranging prerequisites.

## No-look-ahead controls

- Every feature carries `available_at`.
- `available_at <= evaluation_at` is enforced for every included event.
- Evaluation-time slicing excludes future bars and the unclosed evaluation
  bar.
- Pivot confirmation uses right-side bars only after those bars close.
- ATR, range, and displacement thresholds use strictly prior closed bars.
- Mutating prices after an evaluation timestamp must not change the earlier
  snapshot.

## Configuration and provenance

Every snapshot and event records:

- D005 version and config fingerprint;
- source-rule catalog IDs;
- feature and taxonomy variant;
- configured thresholds;
- source, creation, confirmation, interaction, and invalidation timestamps;
- data availability timestamp; and
- parent/reaction/refinement mapping.

Defaults are research defaults only. Alternative variants must be selected by
configuration and may not silently replace defaults.

## Research artifacts

A D005 research run may write only beneath its selected output directory:

- `context_snapshots.parquet`
- `fvg_events.parquet`
- `order_block_events.parquet`
- `liquidity_events.parquet`
- `confirmation_events.parquet`
- `conflicts.parquet`
- `state_transitions.parquet`
- `configuration_snapshot.json`
- `implementation_provenance.json`
- `feature_schema.json`
- `summary.json`
- `reproducibility_metadata.json`
- `D005_CONTEXT_ENGINE_RESEARCH_REPORT.md`
- `artifact_manifest.json`

The report must state that D004 found no robust standalone 08:30–09:00
directional edge and must not promote a timing result to production.

## Acceptance criteria

1. The package is located under `research/context_engine/` and has no
   production import or registration.
2. All seven evidence states and guarded transitions are implemented.
3. Parent-veto conflict produces `conflict`, neutral outcome, and
   `entry_authorized=false`.
4. All three OB variants emit independent records and no `valid_ob` aggregate
   exists.
5. Raw FVG geometry is separate from contextual qualification and IFVG
   variants.
6. Weekly→4H→1H, Daily→1H→15m, 4H→15m→5m, and 1H→5m→optional 1m mappings
   are represented explicitly.
7. Reaction confirmation requires HTF event, body-close MSS, displacement,
   refinement, and aligned entry array/zone.
8. PMH/PML uses configurable `[00:00,08:30)` New York half-open bounds,
   passes spring and autumn DST tests, and cannot independently produce
   direction.
9. Missing data, conflict, absent confirmation, opposing arrays, unresolved
   range, overextension, and invalid risk fail closed.
10. Every event/snapshot has source-rule, variant, parameter, and timestamp
    provenance.
11. Future-data mutation tests prove earlier outputs are unchanged.
12. The 1m refinement is disabled by default and tested as an explicit
    variant.
13. No index-specific clock behavior exists in executable D005 defaults.
14. Existing production defaults and outputs remain byte-for-byte/code-value
    unchanged in isolation tests.
15. Unit and repository tests pass, and a research report documents scope,
    limitations, validation, and the D004 timing guardrail.
