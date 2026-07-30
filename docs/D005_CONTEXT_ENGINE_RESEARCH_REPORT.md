# D005 Context Engine Research Report

## Scope

This output is an isolated research artifact. It does not change production
strategy defaults, signals, execution, risk, or live behavior. Every snapshot
has `entry_authorized=false`.

The D004 guardrail remains active: the `[08:30,09:00) America/New_York`
window did not show a robust standalone directional edge and is not used here
as a directional rule. No 09:30 NYSE, 10:00 Key Open, index PO3, RTH, ES, NQ,
NAS100, or SP500 timing behavior is transferred to XAUUSD.

## Configuration

- Version: `D005-v1`
- Config fingerprint: `bc7a241b06977afc585a75b8bfbfe721df53bd0fb0cdd5914e194e70d9b28559`
- Implementation fingerprint: `7dda9f6a350c2515e1b76594ca518846af665cb391e1b2566724427ee9bcc5a1`
- Primary mapping: `4h_15m_5m`
- Optional 1m refinement: `False`
- Premarket interval: `[00:00,08:30) America/New_York`
- MSS variant: `body_close_pivot_w2`
- Displacement variant: `atr_body_baseline`
- Research source: `/Users/serhanceylan/Desktop/shiedafx - finance/XAUUSDBOT/xauusd-trading-ai-smc-v2/research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m`
- Selected input files / rows: `108` / `123734`
- Requested session dates: `2025-12-01` through `2025-12-05`
- Input selection SHA-256: `b793a7b3908f85fbdc830f414c5d7430cd114df6d22bcbbee4decbfc0d3f7156`

## Snapshot states

| State | Count |
|---|---:|
| `candidate_liquidity_event` | 2 |
| `conflict` | 2 |
| `invalidated` | 9 |
| `neutral` | 3 |
| `provisional_context` | 4 |

## Outcome labels

| Outcome | Count |
|---|---:|
| `neutral` | 20 |

## Order Block variants

| Variant | Unique detections | Observations | Unique interactions | Unique confirmations | Unique invalidations |
|---|---:|---:|---:|---:|---:|
| `consecutive_block` | 1035 | 3436 | 61 | 7 | 48 |
| `inefficiency_break_origin` | 397 | 1305 | 19 | 1 | 13 |
| `last_opposing_candle` | 2079 | 6885 | 114 | 11 | 92 |

No aggregate `valid_ob` field is produced.

## Event totals

- Snapshots: 20
- FVG events / observations: 7636 / 25372
- OB events / observations: 3511 / 11626
- Liquidity events / observations: 836 / 3195
- Confirmation events / observations: 2300 / 9198
- Conflicts / observations: 2 / 2
- Entry authorizations: 0

## Interpretation

Counts describe engine evidence coverage only. They are not expectancy,
profitability, or production-promotion evidence. `reaction_confirmed` records
completion of the configured research sequence and remains non-executable.

## Limitations

- Source concepts remain discretionary and are represented by named variants.
- This report does not establish an XAUUSD timing edge.
- PMH/PML is a category B/C clue and cannot override valid HTF context.
- A separate preregistered outcome study is required before any predictive
  interpretation.
