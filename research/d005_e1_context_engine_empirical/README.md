# D005_E1 Context Engine Empirical Study

This package evaluates the frozen, isolated D005 engine in fixed-clock and
event-driven descriptive modes. It cannot authorize entries or write to the
existing D005 output directory.

Example:

```bash
python -m research.d005_e1_context_engine_empirical \
  --one-minute-bars research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m \
  --output-dir research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY \
  --start-date 2021-01-03 \
  --end-date 2025-12-31 \
  --fixed-clocks 08:30,09:00,10:00,12:00 \
  --report-path docs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_REPORT.md
```

Clock labels are observation points, not XAUUSD direction rules. The D004
08:30–09:00 no-standalone-edge guardrail remains binding.
