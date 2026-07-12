# Codex Context Guide

Future sessions should not start by reading the raw PDFs. Read compact Markdown first.

## Mandatory Reading

Read these before strategy development:

1. `docs/source_analysis/FINAL_SOURCE_SELECTION.md`
2. `docs/source_analysis/SOURCE_CONFLICTS.md`
3. `docs/source_analysis/CONCEPT_AUTHORITY_MAP.md`
4. All files in `docs/knowledge/`

## Optional Reading

Use these only for audit or source-selection questions:

- `docs/source_analysis/SOURCE_INVENTORY.md`
- `docs/source_analysis/SOURCE_RANKING.md`
- `docs/source_analysis/REDUNDANCY_MAP.md`
- `docs/source_analysis/EXTRACTED_CONCEPTS.md`

## Raw Source Escalation Rule

Open an original PDF only when:

- compact knowledge files are ambiguous,
- a source conflict must be verified,
- exact original wording or chart context matters,
- an image-only source is explicitly needed for visual inspection.

Prefer `docs/knowledge/` over `docs/raw_sources/` in normal development.

## Raw Sources Worth Escalating To

- `docs/raw_sources/the-ict-handbook-v-1 1.pdf`
- `docs/raw_sources/Smart Money Concept (SMC) Trading.pdf`
- `docs/raw_sources/ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`
- `docs/raw_sources/EKINYZBB BOOTCAMP SERISI.pdf`
- `docs/raw_sources/EKINYZBB ILERI SEVIYE ICT SERISI.pdf`
- `docs/raw_sources/IPDA_-Market_Cycle.pdf`
- `docs/raw_sources/_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf`
- `docs/raw_sources/_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf`
- `docs/raw_sources/_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf`

## Do Not Read By Default

Do not read these raw PDFs unless the user specifically asks or a compact-source conflict requires it:

- `docs/raw_sources/0934380406_Trading_Secrets_of_the_Inner_Circle_Goodwin_1997_12_01.pdf`
- `docs/raw_sources/CRT Model Mr matriX.pdf`
- `docs/raw_sources/INDICES 8.30 PO3 Model Mr MatriX.pdf`
- `docs/raw_sources/Larry Williams Forecast 2026.pdf`
- `docs/raw_sources/Michael Jenkins - The Geometry of Stock Market Profits.pdf`
- `docs/raw_sources/Michael_McDonald_Predict_Market_Swings_with_Technical_Analysis.pdf`
- `docs/raw_sources/PO3 Model (10 AM) Mr MatriX.pdf`
- `docs/raw_sources/tarıkabiönemlinotlar (1).pdf`
- all exact duplicates listed in `docs/source_analysis/REDUNDANCY_MAP.md`

## Development Boundary

This phase produced source triage only. It does not authorize bot construction, ML integration, BUY/SELL signals, entries, stop-loss, or take-profit execution logic. Future implementation must first formalize and backtest the concepts marked `NEEDS_FORMALIZATION`, `NEEDS_PARAMETER_RESEARCH`, or `NEEDS_BACKTEST_VALIDATION`.
