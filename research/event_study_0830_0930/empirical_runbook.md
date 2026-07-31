# Empirical Runbook

This runbook enforces staged research. It does not authorize production changes or claim an edge.

## 1. Import without mutating raw files

Follow `external_data_setup.md` to produce canonical UTC one-minute bid/ask bars and canonical release records. Keep adapter metadata with the normalized files.

## 2. Validate before analysis

```bash
python -m research.event_study_0830_0930.empirical_cli validate \
  --market research/event_study_0830_0930/external_data/normalized/xauusd_1m_bidask.csv \
  --calendar research/event_study_0830_0930/external_data/calendar/releases_canonical.csv \
  --quality-json research/event_study_0830_0930/external_data/quality/data_quality_report.json \
  --quality-md research/event_study_0830_0930/external_data/quality/data_quality_report.md
```

Exit code 2 means the report was written but empirical execution is blocked. Critical defaults include non-monotonic or duplicate bar timestamps, coarser-than-one-minute bars, non-positive spreads, bid above ask, invalid OHLC, mixed sources/symbols, weekend/known-closure records, excessive missing minutes and incomplete event windows. Missing observations are never filled.

Review per-year/month coverage and every `event_window_coverage` record. Holiday/early-close rules and broker maintenance schedules must be confirmed against the selected feed before a final multi-year run.

Use `--thresholds-json path/to/thresholds.local.json` to supply feed-specific limits and timezone-aware UTC holiday/early-close intervals. The local file remains ignored; any relaxation must be justified in run metadata and must not disable event-window completeness checks silently.

## 3. Stage 1: timing and volatility only

```bash
python -m research.event_study_0830_0930.empirical_cli stage1 \
  --market research/event_study_0830_0930/external_data/normalized/xauusd_1m_bidask.csv \
  --calendar research/event_study_0830_0930/external_data/calendar/releases_canonical.csv \
  --output research/event_study_0830_0930/outputs/stage1
```

Stage 1 writes session-window metrics, 08:30/09:30/10:00 clock effects, news/non-news group summaries, clusters, metadata and quality reports. Midpoints are used only for descriptive movement statistics. No midpoint execution performance is reported, and no discretionary entry concept is tested.

## Later-stage gates

1. **Stage 2 — lifecycle classification:** run only after Stage 1 coverage and classification audits pass. Report ambiguous and unclassified days.
2. **Stage 3 — simple benchmarks:** pre-news breakout/re-entry, midpoint hold, fixed retracements, and 08:30/09:30 sweeps.
3. **Stage 4 — ICT/SMC geometry:** FVG, rejection block, OTE, MSS and displacement, each compared with a simpler benchmark.
4. **Stage 5 — tick confirmation:** confirm any candidate with real spread, intraminute path, stop/limit execution and news slippage.

The optimistic/base/stress scenarios in `execution_cost_model.py` are explicit assumptions until calibrated to the chosen feed. Longs enter at ask and exit at bid; shorts enter at bid and exit at ask. Trades cancel when the configured maximum spread is exceeded.

No one-minute result may be proposed for production without independent tick-level confirmation and a separate production review.
