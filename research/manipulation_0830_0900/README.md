# D004 XAUUSD 08:30–09:00 New York Research

This package is an isolated consumer of the immutable D003 canonical tick
dataset. It is outside production package discovery and does not change
`xauusd_signal`, strategy defaults, execution, or live-trading behavior.

## Run

```bash
python -m research.manipulation_0830_0900 run \
  --dataset-root data/canonical/xauusd_ticks \
  --output-dir research_outputs/D004_XAUUSD_0830_0900 \
  --timezone America/New_York \
  --window-start 08:30 \
  --window-end 09:00 \
  --bar-resolutions 1,5,15 \
  --reference-range 0800_0830 \
  --sweep-threshold-mode absolute \
  --sweep-threshold 0.05 \
  --worker-count 4 \
  --random-seed 4004 \
  --resume \
  --report-path docs/D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md
```

Independently recheck an existing run:

```bash
python -m research.manipulation_0830_0900 verify \
  --output-dir research_outputs/D004_XAUUSD_0830_0900
```

The default command remains research-only. `--resume` checks the source
manifest identity and cached-file hash before reusing a UTC-day candle cache.
Canonical Parquet files are opened read-only.

## Time and session definitions

- Every clock uses an IANA zone, never a fixed offset.
- The manipulation window is the half-open interval
  `[08:30:00,09:00:00) America/New_York`.
- The repository's validated named trading day is prior-date 18:00 through
  named-date 17:00 in `America/New_York`.
- London is `[08:00,12:00) Europe/London`; its DST calendar is independent of
  New York.
- Asia is the deterministic sensitivity `[20:00,00:00) America/New_York`.
- All bar timestamps are left edges. A candle-dependent MSS or FVG becomes
  available at candle close.

## Leakage controls

Window features use observations no later than 09:00. Displacement thresholds
use expanding distributions shifted by one eligible trading date. Confirmed
swings are unavailable until all configured right bars close. FVGs are
unavailable until the third candle closes. Previous-day levels are shifted
from a completed named session. Future bars are used only for outcomes.

Chronological evaluation is 60% development, 20% validation, and 20% holdout.
The yearly table is an expanding-history walk-forward view. No main evaluation
randomly shuffles dates.

## Generated schema

`daily_events.parquet` has one row for every New York weekday in selected
coverage, including explicitly flagged incomplete dates. Its generated
`daily_event_schema.json` lists every field and dtype. Key families are:

- source coverage and deterministic OHLC/tick summaries;
- four manipulation subwindows and five observation horizons;
- four reference-range variants and primary sweep/re-entry fields;
- causal displacement metrics and prior-only percentile thresholds;
- MSS and 1m/5m/15m FVG flags;
- previous-day, session-open, midnight, Asia, London, and premarket levels;
- HOD/LOD prices, first-attainment timestamps, and tolerance flags;
- optional externally supplied macro labels; and
- chronological partition labels.

`fvg_events.parquet` contains creation/availability, direction, width,
ATR-normalized width, first touch, fill, full fill, invalidation, expiration,
and proximal/midpoint/75%-depth/distal same-event and full-horizon excursion
metrics. Geometry risk is the entry-to-one-tick-beyond-distal invalidation
distance. Zero/default and conservative-cost terminal R are stored separately;
means, medians, and tail percentiles are reported because small gaps create
heavy-tailed R units.

`strategy_events.parquet` is a separate hypothetical event replay. It never
feeds production. Every row states its variant, causal direction, 09:00 entry,
window-extreme stop, 2R target, horizon, cost scenario, exit, MFE, MAE, gross R,
and net R.

## Optional event labels

CSV or Parquet labels require `trading_date`. They may include `event_label` or
`event_name`, `category`, and an explicitly timezone-aware `event_timestamp`.
No calendar is scraped and no news event is inferred from price or volatility.
