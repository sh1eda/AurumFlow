# D007 Historical Execution Contract

## Status and separation from the scientific preregistration

This document is the outcome-blind execution-contract addendum anticipated by
`docs/D007_OTE_RESEARCH_SPEC.md`. It authorizes no D007 historical outcome
access in this milestone. It freezes the operational inputs, authorization,
command surface, output namespace, artifact schemas, and validation commands
that a later separately authorized task must use.

The original D007 scientific preregistration remains authoritative and is not
rewritten by this addendum. The OTE band `0.62-0.79`, reference `0.705`,
equilibrium control `0.50`, D005 `1h_5m` displacement basis, causal origin and
endpoint selectors, lifecycle, overlap and deduplication rules, controls,
interactions, adequacy thresholds, inference, outcome definitions, and New York
named-trading-date rules are unchanged.

## Frozen source lineage

D007 consumes the already-frozen D005 E4 historical lineage. It does not select
or rebuild a canonical tick release and does not read the ignored D003-v2
canonical payload.

The lineage is:

1. tracked, accepted D003 release `d003-v1`, documented as the immutable
   downstream-research source in `docs/D003_ACCEPTANCE_REPORT.md`;
2. the D004 deterministic one-minute cache derived from `d003-v1`;
3. D005 E4 `D005-E4-v1`, which reverified every selected cache file and froze
   the D005 `1h_5m` displacement sequence; and
4. D007 causal construction from those immutable bars and upstream events.

The local D003-v1 canonical/release payload is not present. That prevents a
canonical rebuild, but it does not require a new dataset choice: D007 consumes
the preserved D004 cache and D005 E4 structural artifacts. D004
`reproducibility_metadata.json` is frozen at SHA-256
`c29fa7de14e51970ab51bc71f53c73d50ea470e8c1e6fc2d970273826a980133`
and records D003 `d003-v1`, dataset ID `3ef1612c3ac73469e0b0`, and canonical
manifest SHA-256
`16a560443f6429e4250d68af7b5a02d7da255d7dfcf7b2945d34a2c29a9d62ab`.
Ignored D003-v2 metadata is not an authorized source and cannot substitute for
this lineage, even though its overlapping 2021-2025 file checksums match the
D004 checkpoint inventory.

The exact repository-resolved source root is
`research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m`. The D005 E4 source
selection contains 1,554 files and 1,772,168 one-minute rows from selected
calendar dates `2021-01-03` through `2025-12-31`. Its original selection
SHA-256 is
`21f410613d95ec9482b0baa1766b64e362725ec60d817bf53e1d4b511636c3e3`.
Because that historical fingerprint embeds an absolute checkout path, this
contract additionally freezes the path-independent inventory fingerprint
`f76e6e88870c505da68b0615bc5dfc6aefe2da08afad0fede7ae159df88d9659`,
computed from sorted
`relative-path<TAB>bytes<TAB>rows<TAB>sha256` records.

Required D005 E4 identities are:

| Artifact | SHA-256 |
|---|---|
| `artifact_manifest.json` | `f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445` |
| `configuration_snapshot.json` | `1fb9a52d2ad2ab80d23e16d3c6009082713ed86aeea60e8725e883d849ea11a8` |
| `source_provenance.json` | `65cfdeb98358cc88390eabb48b57ff380b50d92467c906b45094339efb9a21e1` |
| `reproducibility_metadata.json` | `e0b98a979545983d6608dfd16c5f9c9e86a5c1a5c269074bc01cb1444fd65aa9` |
| `eligible_sequences.parquet` | `059e7053e46f753f5cede6714f2de5ea3a5a0ee47ae7d781cdd55d6af1c00b40` |
| `displacement_anchors.parquet` | `d6a45058c11f32a7cb476d2ec578c50f53c017b080f3537002c1624049e42ce0` |
| `implementation_provenance.json` | `0a4dd92f19df0afd48663afc3d78000162d680c8bf683a5ac5944f10889160fe` |

The E4 study-config fingerprint is
`34e044c602ca0e7aa5a467273e20538171b0363b6c72f6ed9415dc281d825880`
and its implementation SHA-256 is
`c6ab71a0709a647be301fd7886d566d5d0f0a2ed3ea6df5fb29b900ed44869af`.
Any mismatch fails closed. The D005 event tables are consumed, never regenerated
or reselected. D005 E4 outcome tables are not authorized D007 inputs.
The E4 implementation-provenance inventory is also rehashed file by file and
must reproduce the registered implementation fingerprint.

## Historical and named-date boundary

The source calendar selection is fixed to `2021-01-03` through
`2025-12-31`, with 2021 serving only as causal warm-up/calibration context.
D007 validation named trading years are exactly 2022, 2023, 2024, and 2025 in
`America/New_York`. Source timestamps must be earlier than
`2026-01-01T00:00:00Z`.

Every required five-minute timestamp from an event through its exact 60-minute
endpoint must exist. The event and all required timestamps must belong to a
registered New York named trading year. If any required timestamp enters New
York named-year 2026, the observation is ineligible. Missing terminal source
coverage never extends the interval and is never imputed.

## Authorization and canonical command

Historical execution remains false by default. The sole token is:

`EXECUTE_FROZEN_D007_OTE_2022_2025`

The future canonical command is:

```text
python -m research.d007_ote_historical_contract execute --authorization EXECUTE_FROZEN_D007_OTE_2022_2025
```

The outcome-blind contract preflight command is:

```text
python -m research.d007_ote_historical_contract preflight --authorization EXECUTE_FROZEN_D007_OTE_2022_2025
```

There are no runtime methodology arguments. The command rejects missing or
altered authorization, lineage, interval, fingerprint, output, or methodology
state. In this contract milestone the `execute` command deliberately stops
after authorization with `HISTORICAL_PIPELINE_DEFERRED`; the later empirical
execution task must connect the frozen pipeline behind this same command and
must not change the contract.

Every executable contract file (`__init__.py`, `__main__.py`, `config.py`,
`preflight.py`, `runner.py`, and `schemas.py`) has a frozen SHA-256 identity in
the contract configuration. `config.py` uses a deterministic normalized
self-hash: only its stored self-hash value is replaced by a fixed sentinel before
hashing. Authorization fails if any other byte of any executable contract file
is modified independently of a new reviewed contract version.

## Output namespace and artifact contract

The sole future output root is
`research_outputs/D007_OTE_RESEARCH`. It must not exist before first
publication. Publication must stage a complete package beside the destination,
atomically rename it, refuse overwrite, and verify exact artifact membership,
byte sizes, and SHA-256 values. Canonical, release, raw, D003-D006 output,
production, and strategy paths are never writable by D007.

The transient staging prefix is `.D007_OTE_RESEARCH.staging-` and the sole
publication lock is `research_outputs/.D007_OTE_RESEARCH.publish.lock`.
Transient material is never part of the artifact manifest and must be removed
after failure. An existing output is a hard collision: reruns never overwrite or
silently reuse it. The artifact-manifest and run-manifest schema identifiers are
`d007-ote-artifact-manifest-v1` and `d007-ote-run-manifest-v1`.

Every future package contains exactly the JSON, Markdown, and Parquet artifacts
registered in `research/d007_ote_historical_contract/schemas.py`.
`artifact_manifest.json` is self-excluding. Exact table columns and logical
types are frozen in that module. Empty registered cohorts still emit their
registered empty table so artifact membership never depends on results.

No artifact in this namespace is created by this contract milestone.

## Validation command contract

`automation/config.yaml` has no tracked version or reconstructable repository
history. It is not fabricated here. The D007 commands are therefore frozen in
`research/d007_ote_historical_contract/config.py` and are:

```text
python -m pytest tests/test_d007_historical_contract.py tests/test_d007_ote_research.py -q
python -m pytest tests/test_d005_e4_1h_5m_reversal_replication.py tests/test_d005_e5_reporting_hardening.py tests/test_d005_e6_future_blind_replication.py -q
python -m pytest tests/test_d006_rejection_block_research.py tests/test_d006_historical_source.py tests/test_d006_historical_context.py tests/test_d006_historical_execution.py -q
python -m research.d007_ote_historical_contract preflight --authorization EXECUTE_FROZEN_D007_OTE_2022_2025
python -m pytest -q
git diff --check
```

The missing AGENTS-level automation configuration remains a repository issue;
these commands are a milestone-local, evidence-supported contract rather than a
reconstruction of that absent file. The D003 canonical validator is not a D007
command: D007 consumes the immutable E4 cache lineage and is forbidden from
rebuilding or substituting canonical data.

## Outcome-blind acceptance

This contract is acceptable only if synthetic tests prove exact authorization,
fingerprints, source and upstream identities, interval and named-year handling,
output confinement, methodology immutability, deterministic identity, and zero
outcome access. No D007 historical event construction, lifecycle accounting,
adequacy evaluation, inference, or empirical artifact publication is permitted
while creating or validating this addendum.

Contract-owned changes are limited to this document,
`research/d007_ote_historical_contract/`, and
`tests/test_d007_historical_contract.py`. The preflight rejects any supplied
changed-path inventory outside that ownership boundary.
