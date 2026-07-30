# D003_E2 Post-2025 Dukascopy Extension

This is a reporting-only wrapper around the frozen D001/D002/D003
implementation. It does not download, decode, canonicalize, or modify strategy
behavior. The authentic acquisition itself is executed by
`scripts/download_dukascopy_ticks.py`.

After an acquisition gate failure, run:

```bash
python -m research.d003_e2_post_2025_dukascopy_extension
```

The wrapper converts the frozen manifest, independent D001 verifier report,
and structured log into the required machine-readable failure artifacts and
checks all protected fingerprints.

