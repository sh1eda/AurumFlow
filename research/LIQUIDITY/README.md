# Liquidity

Lifecycle: `statistical_evaluation`. Research-object decision: `not_evaluated`.

TASK 003 adds the registered `LIQUIDITY_PHASE1` empirical program. It constructs
timestamp-safe previous-day, previous-week, forming/completed Monday, confirmed
4H/daily swing, and equal-high/low candidates. It evaluates their independent
reach and interaction behavior at fixed 08:30/09:30 New York anchors and after
completed-bar interaction events.

The operational labels `approached`, `touched`, `exceeded`, `closed_beyond`,
`reclaimed`, `moved_away`, and `consumed` describe observed bid/ask behavior;
they do not assert intent or establish a strategy. HTF Bias remains inconclusive
and is not used as a filter.

Generated artifacts are written under the ignored
`research_outputs/LIQUIDITY/phase1/` namespace.

Run from the repository root:

```bash
python -m aurumflow_research run LIQUIDITY_PHASE1
```

The object decision stays `not_evaluated` because an experiment-level Phase 1
decision is separate from a final object-wide scientific classification. No
production package, signal, entry, stop, target, execution behavior, or default
is changed.
