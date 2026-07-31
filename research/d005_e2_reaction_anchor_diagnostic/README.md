# D005_E2 Reaction Anchor Diagnostic

Run from the repository root:

```bash
python -m research.d005_e2_reaction_anchor_diagnostic \
  --e1-output research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY \
  --output-dir research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC
```

E2 is research-only. It does not modify D005/E1 artifacts, strategy
thresholds, state logic, production behavior, or canonical market data.
It reconstructs every uncapped candidate chain, then replays the unchanged
D005 engine at each unique structural-completion timestamp. Structural
completion and exact engine-selected `reaction_confirmed` evidence are
reported separately.
