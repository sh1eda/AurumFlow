# D005 Context Engine

This package is an isolated research-only consumer of closed XAUUSD bars
derived from the D003 canonical tick dataset. It is not part of production
package discovery and cannot authorize entries.

Example bounded run using the existing hash-verified D004 one-minute derivative:

```bash
python -m research.context_engine \
  --one-minute-bars research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m \
  --output-dir research_outputs/D005_CONTEXT_ENGINE \
  --start-date 2025-12-01 \
  --end-date 2025-12-05 \
  --evaluation-clock 09:00 \
  --no-optional-1m-refinement \
  --report-path docs/D005_CONTEXT_ENGINE_RESEARCH_REPORT.md
```

The default PMH/PML interval is `[00:00,08:30) America/New_York`. The
`[08:30,09:00)` interval is an observation/execution window only and never a
standalone direction rule.

