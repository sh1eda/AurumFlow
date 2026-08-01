# XAUUSD Trading AI — Project Agent Rules

## Purpose and current gate

This repository builds and validates an explainable XAUUSD research system. Correctness, causality, reproducibility, and artifact integrity take priority over speed.

Completed milestone context is binding:

- D003-v1 is accepted and frozen by `docs/D003_ACCEPTANCE_REPORT.md`; canonical data must be versioned, never overwritten.
- D004 is isolated descriptive research. Its `[08:30,09:00) America/New_York` window is not a standalone directional rule and did not change production defaults.
- D005 through the historical E4 study is research-only. E4 concluded that no genuinely independent replication sample was available and recommended a hash-verified post-2025 D003-derived sample before repeating the frozen design; it explicitly did not authorize entry-geometry research or production promotion.
- A local ignored `data/releases/d003-v2/` bundle exists and reports successful verification, but no tracked acceptance report in this branch authorizes it to supersede D003-v1 or unlock the D005 research gate. Only the primary Sol thread may assess that gate under an explicitly authorized task.

Research findings never become production behavior or defaults automatically. Do not execute live trading, broker operations, or real-money order paths.

## Authority and cost routing

- The primary GPT-5.6 Sol thread owns planning, methodology, architecture, leakage boundaries, research-gate decisions, final review, and acceptance.
- Use `project_implementer` (GPT-5.6 Terra) for bounded production-quality implementation after Sol assigns an explicit write scope and file ownership.
- Use `project_explorer` and `project_verifier` (GPT-5.6 Luna) only for narrow, mechanically verifiable exploration or verification.
- Do not spawn subagents for trivial work the primary thread can complete more cheaply without duplicated context. Use no more agents than the task requires.
- Keep ambiguous, methodological, architectural, leakage-sensitive, artifact-sensitive, and final-acceptance work in Sol.
- Parallel write work is forbidden unless scopes are disjoint and Sol explicitly assigns each file to one writer. One active writer per file.

## Protected data and artifacts

Treat these as read-only unless the user explicitly authorizes a versioned workflow and Sol confirms the integrity gate:

- raw source data under `data/raw/dukascopy/`;
- canonical roots `data/canonical/xauusd_ticks/` and `data/canonical/xauusd_ticks_d003-v2/`;
- the current local release bundle `data/releases/d003-v2/` and any release metadata, checksum list, or manifest registered there;
- acquisition manifests under `data/manifests/` when present;
- `research_outputs/D004_XAUUSD_0830_0900/`;
- `research_outputs/D005_CONTEXT_ENGINE/`;
- `research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY/`;
- `research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC/`;
- `research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY/`;
- `research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION/`;
- files registered by any `artifact_manifest.json`, canonical manifest, release checksum list, or reproducibility record; and
- accepted or frozen milestone records: `docs/D003_ACCEPTANCE_REPORT.md`, `docs/D003_CANONICAL_XAUUSD_TICKS.md`, `docs/D004_XAUUSD_0830_0900_MANIPULATION_RESEARCH.md`, `docs/D005_STRATEGY_SOURCE_AUDIT.md`, `docs/D005_CONTEXT_ENGINE_RESEARCH_REPORT.md`, `docs/D005_CONTEXT_ENGINE_TECHNICAL_SPEC.md`, and the D005 E1–E4 specifications in `docs/`.

Never overwrite a canonical dataset, raw file, release bundle, manifest, checksum, registered artifact, reproducibility record, or acceptance report. Corrections require a separately named version and explicit authorization. Hashing, file listing, size checks, and manifest comparison do not authorize row access or mutation.

## Forward-outcome and leakage boundary

- Do not decode or inspect Parquet rows unless the task explicitly authorizes that access and Sol confirms the applicable gate. Unauthorized Parquet row decoding is a stop condition.
- D005, E1, E2, E3, and E4 artifact directories are protected inputs for later work. Do not inspect protected forward-outcome tables under a structural, configuration, or checksum task.
- Use only information available at the causal timestamp. Closed-bar availability is mandatory; future data, target leakage, and look-ahead are forbidden.
- Forward outcomes may be joined only after an anchor exists and must never create, select, rank, relabel, filter, or gate an anchor, state, direction, feature, or cohort.
- Later refinement, reaction confirmation, invalidation, timeout, MFE, MAE, or outcome-like fields must not influence earlier selection.
- Preserve D004's timing guardrail: clocks are observation/execution labels, not standalone XAUUSD direction.
- Do not continue research, loosen a gate, begin entry-geometry work, or promote a result without an explicit task and Sol methodology approval.

## Git, worktree, and write safety

- Inspect the branch, worktree status, applicable instructions, and file ownership before editing.
- Never implement directly on `main`. Stop before editing if the active branch is `main`.
- Preserve user changes and unrelated diffs. Never overwrite another worktree or active agent's file.
- Never use destructive Git operations or destructive conflict resolution.
- Do not commit, push, merge, delete branches, rewrite history, or alter remote state without explicit user authorization. Never push directly to `main`.
- Stop before editing when scope or ownership is absent, a required path is protected, forward-outcome access would violate the gate, repository state materially differs from the parent task, or repository integrity cannot be demonstrated.

## Implementation and validation

- Make the smallest defensible change. Production strategy defaults may change only when the task explicitly permits it, and every behavioral change requires focused tests while existing tests continue to pass.
- If `automation/config.yaml` is absent, do not invent its contents or claim its commands ran. When present, inspect it before selecting validation commands.
- Documented general validation is `python -m pytest` (also `make test`). Use focused pytest targets for scoped changes and the full suite when the authorized task requires it.
- `python -m scripts.validate_canonical_dataset` is documented for D003 but reads canonical Parquet rows; do not run it without explicit data-access authorization.
- Do not run data or research pipelines merely to validate unrelated infrastructure.

## Required subagent report

Every subagent returns:

1. task scope and assigned file ownership;
2. exact files inspected and changed;
3. commands and tests executed, with results;
4. evidence with exact file references;
5. protected-path, production-default, Parquet-access, and leakage checks;
6. assumptions, deviations, risks, and blockers;
7. acceptance-criteria status; and
8. recommended next action.

An implementer report is evidence, not acceptance. Independent verification and final review remain with the primary Sol thread.
