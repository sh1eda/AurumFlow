# Higher Timeframe Bias

Lifecycle: `statistical_evaluation`. Research-object decision: `not_evaluated`.

TASK 002 adds the registered `HTF_BIAS_PHASE1` empirical experiment. It defines
timestamp-safe daily, weekly, Monday-range, confirmed-swing, displacement,
premium/discount, and external-level context features and evaluates them against
neutral forward returns, direction, excursion, level reach, range expansion, and
realized volatility at 08:30 and 09:30 New York time.

The experiment is research-only. It does not emit a production bias, trading
signal, entry, stop, target, sizing rule, or execution instruction. Generated
artifacts are written under the ignored `research_outputs/HTF_BIAS/phase1/`
namespace.

Run from the repository root:

```bash
python -m aurumflow_research run HTF_BIAS_PHASE1
```

The research-object decision remains `not_evaluated` because a Phase 1 result is
not automatically a final decision about every possible HTF-context definition.
