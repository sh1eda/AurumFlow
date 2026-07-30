# D003_E1 2026 Canonical Extension Gate

This package performs the isolated, fail-closed Stage A audit for
`D003_E1_2026_CANONICAL_EXTENSION_AND_D005_E4_INDEPENDENT_REPLICATION`.

It inventories and hashes the local post-2025 XAUUSD sources, imports the
frozen D003 Arrow schema as authority, audits timezone/DST evidence, compares
the true 2025 D003/MT5 overlap, verifies the frozen D003 release hashes, and
classifies compatibility before any strategy outcome is calculated.

Run:

```bash
python -m research.d003_e1_2026_canonical_extension
```

Only compatibility classes 1 or 2 permit the conditional Stage B output.
Classes 3 or 4 create no candidate canonical release and no Stage B
directory.

