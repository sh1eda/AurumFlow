# D006 Rejection-Block Structural and Empirical Research Preregistration

## Status, boundary, and scientific purpose

D006 is an additive, research-only component study for XAUUSD. It does not
define or implement a production strategy and it does not select a composite
strategy. Its purpose is to determine whether rejection blocks are causal,
reproducible structural objects; whether they add independent or conditional
forward price-movement information; whether they improve execution geometry;
and whether they are sufficiently non-redundant to carry into a later,
separately preregistered interaction and ablation milestone.

The immutable antecedents are D003, D004, D005, D005_E4, D005_E5, and D005_E6,
including their tracked specifications and code and their protected local
data, releases, manifests, checksums, reports, and ignored research outputs.
D006 never changes those artifacts or production defaults. The D005_E4 2026
interval is outcome-known and inadequate, D005_E5 is post-outcome reporting
hardening, and D005_E6 leaves the blind boundary unproven. No 2026 observation
is blind D006 evidence.

This first D006 task is preregistration, preflight, and synthetic structural
validation only. It is not authorized to open a canonical Parquet payload,
decode a historical market row, run a detector on real data, observe a real
block count, calculate an historical or future outcome, or create
`research_outputs/D006_REJECTION_BLOCK_RESEARCH/`. The implementation stops
before any real-data execution path.

The production recommendation cannot be changed by D006. D006 never emits
`PRODUCTION_READY`, never authorizes an entry, and never reports trade
expectancy, profit factor, P&L, position sizing, fees, slippage, funded-account
suitability, or production readiness. All scientific metrics are price-path,
structural, lifecycle, redundancy, interaction, or geometry metrics.

## Questions and evidence classes

D006 must answer:

1. Can rejection blocks be detected causally, deterministically, and with
   stable identities?
2. Do they contain forward price-movement information after the first causal
   touch?
3. Does their value depend on frozen context direction, D004 manipulation
   state, session, a frozen liquidity-sweep state, displacement, or refinement
   confirmation?
4. Do proximal, midpoint, or distal references improve timing or invalidation
   geometry when combined with frozen context signals?
5. Are rejection blocks redundant with displacement, refinement, MSS, FVG,
   liquidity-sweep, or D005 context-engine events?
6. Which observations, if any, justify carrying the component into later
   composite research?

Every result is assigned to exactly one evidence class:

| Evidence class | Meaning in D006 |
|---|---|
| Standalone information value | Direction-aligned movement after a baseline rejection-block touch versus the preregistered matched non-block control. |
| Conditional information value | Incremental movement in one of the fixed causal interaction cohorts versus its matched control. |
| Execution-geometry value | Differences among proximal, midpoint, and distal lifecycle/path metrics without stop, target, R, fill, or P&L semantics. |
| Redundancy | Structural overlap, timing equivalence, or disappearance of incremental value against a frozen existing feature. |
| Interaction value | A preregistered, adequate, temporally stable, BH-surviving conditional difference not explained entirely by its frozen constituent feature. |
| Production suitability | Outside D006. No D006 observation establishes it. |

A weak standalone result does not reject the component when a preregistered
conditional interaction or geometry result satisfies its independent decision
rule. Exploratory diagnostics cannot determine D006 acceptance or disposition.

## Definition provenance and authority

The definition audit was completed before D006 outcome access.

### Source-level authority

The only tracked source-level rule is A29 in
`docs/D005_STRATEGY_SOURCE_AUDIT.md` and the equivalent entry in
`research/context_engine/source_rule_catalog.json`: one or more long-wick
candles at a swing form a rejection block when price extends beyond the
body/bodies to exhaust body-level liquidity before reversing. The audit's
failure-to-continue and acceptance-through wording is a project synthesis,
not verbatim source text. The tracked audit cites pages 363-364 of
`ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`.

The underlying PDF payload is not tracked, but it was restored at
`docs/raw_sources/ICT 2022 Mentorship - Lumi Traders (405 sayfa) -
@eseckal.pdf`. Direct text and rendered-page inspection of PDF pages 363-366
was completed on 2026-08-03 without OCR. Its SHA-256 is
`0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0`,
which exactly matches the pre-D006 inventory committed in
`docs/D005_STRATEGY_SOURCE_AUDIT.md`. The current payload is ignored and
untracked, so hash equality establishes byte identity with the prior audit but
does not convert the PDF into a tracked dependency.

The inspected pages directly define the concept as one or more long-wick
candles at a swing high or low, with price extending beyond the candle
body/bodies to exhaust buy-side or sell-side liquidity before reversing. They
also describe the body-edge-to-wick interval and explicitly allow formation
over more than one candle. They do not state a wick fraction, ATR rule,
lookback, exact expansion window, quantitative confirmation, lifecycle expiry,
overlap rule, or exact invalidation threshold. D006 therefore distinguishes
the direct conceptual definition from every quantitative operationalization
below and does not attribute a D006 numeric value to ICT or another source
unless the criterion table says so.

### Restored relevant-source inventory

All 43 PDFs under `docs/raw_sources/` were parser-opened and hash-checked in the
tracked D005 audit. Direct inspection for this review identified 30 potentially
relevant files: the 14 prioritized D005 documents below and 16 additional
title/keyword or exact-duplicate candidates in the following table. Only the
ICT rejection-block pages directly support a frozen D006 detection rule. The
remaining 14 files are general finance, COT, algorithmic-finance, geometry, or
forecasting works with no relevant D006 methodology. Current hashes for all 43
match the pre-D006 tracked inventory.

Every row below is PDF format, ignored by `.gitignore:105`, untracked by Git,
and unstaged. Each exact hash was recorded in tracked commit `bb9469f` on
2026-07-31, before this D006 specification was created on 2026-08-03. The
current bytes match that pre-D006 audit record exactly. Because the payloads
themselves are ignored and untracked, Git does not establish when the current
local copies arrived; the provenance claim is limited to byte equality with
the previously recorded hashes.

| Exact filename | SHA-256 | Relevant PDF pages / methodology | Direct support for a frozen D006 detection rule |
|---|---|---|---|
| `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | `0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0` | 27, 32-36, 42-43, 48-50, 83-90, 109-111, 137-138, 342-350, 363-366; liquidity, MSS/displacement, OB, rejection block | Yes: conceptual swing/wick/body-liquidity definition, one-or-more candles, and body-edge-to-wick zone only; no D006 numeric threshold |
| `the-ict-handbook-v-1 1.pdf` | `5ac9da7c14a3c246add9495d1171ba3c834f34cc56df0470065aec4ce0ccae34` | 7-10, 17, 20-22, 24-26; liquidity, sweep/MSS, FVG, OB, PD arrays | No exact RB rule; supports frozen contextual comparisons only |
| `Smart Money Concept (SMC) Trading.pdf` | `eee94a43c182ae92802ec83aecf4421ddf0ed64cdfceeb7ab075dc2df21b304e` | 21, 24-31, 46, 49, 55-56, 64-65, 76, 81, 86, 110; liquidity, OB/supply-demand, structure, confirmation | No exact RB rule; supports context and redundancy concepts only |
| `EKINYZBB BOOTCAMP SERISI.pdf` | `6fd9c61fb7956ce2e31a3cbf94f1edcfe405325dccd5693bc4b95635100d59ae` | 4, 6-7, 12-13, 18-20; FVG, PD arrays, displacement, MSS | No exact RB rule; supports displacement/context terminology only |
| `EKINYZBB ILERI SEVIYE ICT SERISI.pdf` | `001ba8bb7afe603d1326ad8341dbde12bb0cde07a323435683a90bd3b4c1be1c` | 5, 7-8, 10, 12; hierarchy, OB qualification, market cycle | No exact RB rule |
| `IPDA_-Market_Cycle.pdf` | `63179e0340e1d78f01b8b1c28a4e55c350bdc7af4a66ad6ea28b0c2acbf97857` | 2-3, 15-16, 19; consolidation, expansion, retracement, reversal | No exact RB or quantitative expansion rule |
| `Mastering ict.pdf` | `7f380e5abca325db845270cb76e6c1fe04ae64290822d7f28ccaeba32ab287b3` | 6-19, 28, 34, 39-43; liquidity, ranges, premium/discount, FVG/OB, order flow | No exact RB rule; supports context/redundancy concepts only |
| `Market Structure - Skatfx.pdf` | `ef00bc585d5a554c60ddd510d040faad3e11b3320772db9d895fac480b0bacc8` | 3-10; rendered inspection controls; trend, swing, and range structure | No exact RB rule or numeric swing width |
| `One Setup For Life - Redeye.pdf` | `4649eb507b1c6d81382cd435d4b220a8bf4610dcd604c4008df93ca9bfa336e5` | 2-12; session-range sweeps and chart examples | No exact RB rule; contextual sweep evidence only |
| `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf` | `8ce98e60cae3b47b19f8e17b7bb8ae486a53f891858b0a9ef8101bb842a59231` | 3-12; manipulation, HTF FVG, expansion | No exact RB or quantitative expansion rule |
| `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf` | `45c79925ebda8a68f5d27c0e87dffda981187f21c1a1375f864dc04b9c4013e6` | 2-7; false move, stop hunt, MSS, OB, continuation/reversal | No exact RB rule; contextual sweep evidence only |
| `_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf` | `65259bcfe8f57a4b064cf3783aca13f5d59b6303fda3116557fcc58cc3979ed5` | 2-6; range sweep, expansion, MSS, OB, FVG reaction | No exact RB or quantitative threshold |
| `INDICES 8.30 PO3 Model Mr MatriX.pdf` | `c3f62c98fd460aa9cfaa19febfe0ea8c35e81a6c38a0ea0f26f7889dd556a9c3` | 1-6; image-only rendered inspection; prior bias, sweep/PD-array, CISD/FVG | No; supporting index-specific context only and prohibited as XAU timing authority |
| `PO3 Model (10 AM) Mr MatriX.pdf` | `7d3dc7e5f7efe2aa0f0fca3a36fcf7becb014a26ff296dbdd789bbdcbe383f53` | 1-4; image-only rendered inspection; HTF PD array, stop hunt, LTF entry | No; supporting index-specific context only and prohibited as XAU timing authority |

Additional potentially relevant files were retained as inventory evidence only:

| Exact filename | SHA-256 | Relevant PDF pages / methodology | Direct support for a frozen D006 detection rule |
|---|---|---|---|
| `_ICT_-_Market_CYCLE__Manipulation_Series_(Ep.3).pdf` | `f4c842c4095472208ea8358848f4880b3e4c3522531bcb0c93a60e84bb2c00be` | 5, 7, 9, 11-12; expansion/reversal/retracement, PD arrays, OB/FVG | No |
| `_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf` | `27e6c6731f4051593f875f1a372c5aa9a7d52cb6c50a79136cdc13aab0238b26` | 5-7; SMT, FVG preservation, breaker examples | No |
| `_Maniplasyon_Nedir_Piyasalar_Neden_Maniplasyon_zerine_Kuruludur.pdf` | `ada5a835fdbd8d4de70b921cbd244a01f0debfc430eaf5a0d5cd100f3b508341` | 3-6, 8-13; consolidation, expansion, liquidity, OB/FVG | No |
| `_Maniplasyon_Stratejisi_ile_aldm_ilem_2000_Manipulation_Series_Ep.pdf` | `c4fa028713714765c9b12d959d2c65e2e7d48e8c2efa778df6835f1416e8b809` | 3-6; SMT, FVG equilibrium, expansion/liquidity examples | No |
| `_Market_Maker_Model_Nedir_10_000_payoutu_mmxm_ve_maniplasyon_teknikleri.pdf` | `b8624038c5000bb8d3193d860a54d40b33f02f23d9450d8905bb934a1d3f07ab` | 2, 7-9, 11-13; PD arrays, OB/FVG, expansion/liquidity | No |
| `_Yln_eyrekleri_nasl_yorumlanmal_2025_Bitcoin_Tahminlerim_HTF_Bias.pdf` | `1f71713dd4e4756f8780d35aa04dcb75f9ee92c7e41e636081ad384682e55e6a` | 3-7; quarterly accumulation/expansion/reversal forecast | No |
| `DREYKO_NOTES_2025_Lecture_Series_Making_Money_With_SMC_Concepts.pdf` | `3d614cf4c01c112759edd8e683544882940d83292015c5c6b03d5dd8460f0c54` | 5, 9, 14; gap fractions, structure/liquidity, ORG/SIBI | No |
| `Opening Range GAP - DREYKO.pdf` | `51d28c6961c70955f52f73f3ab7f86687b6cd4bb6ae42ea357f6ba9c222eb028` | 5, 9, 14; near-duplicate index/RTH material | No |
| `ICT Ekolünde.pdf` | `966ea16c347c9936e191d5a7a05af8f2601ece685a87eede0adf12c83a63bb53` | 2-4; liquidity engineering, gap, retracement | No |
| `Sunu 16.pdf` | `4649eb507b1c6d81382cd435d4b220a8bf4610dcd604c4008df93ca9bfa336e5` | 2-12; exact duplicate bytes of `One Setup For Life - Redeye.pdf` | No additional support |
| `MMXM Trader's executions 2023 .pdf` | `24a7d5d677a509b5279ae3bc8741a1df0eec99ff45e2ed01f6740009a538e12d` | 144 image-only pages; execution examples, no usable text section | No |
| `MMXM Trader's işlem örneği 2023  (1).pdf` | `24a7d5d677a509b5279ae3bc8741a1df0eec99ff45e2ed01f6740009a538e12d` | Exact duplicate bytes of the preceding MMXM file | No |
| `Unlocking Success in ICT 2022 Mentorship - Lumitrader-1.pdf` | `0bbcbe091a9523a326d233af94bd3cbea9940746431fe2587e9995d2215cc652` | 435 image-only pages; broad ICT mentorship copy, no usable text section | No independent support |
| `Unlocking Success in ICT 2022.pdf` | `0bbcbe091a9523a326d233af94bd3cbea9940746431fe2587e9995d2215cc652` | Exact duplicate bytes of the preceding Unlocking Success file | No independent support |
| `CRT Model Mr matriX.pdf` | `650946e71d64e510bd99364ce09797082add83cba6395e5ad91cb09764c61655` | 10 image-only pages; title-level range-model candidate, no usable text section | No |
| `tarıkabiönemlinotlar (1).pdf` | `f63a0d63282ae68bcd125415e57a9ee77032752bd64218104bbce776874a9f14` | 20 image-only note pages; no usable text section | No |

### Existing tracked research translation

`research/event_study_0830_0930/concept_definitions.md` registers an
exploratory deterministic proxy after a predeclared sweep: use the first
close-back candle; require wick/true-range at least 0.50 and a close in the
opposite half; define a bullish zone as `[low, min(open, close)]` and a bearish
zone as `[max(open, close), high]`; consider proximal, midpoint, and distal;
and treat one versus two candles and displacement within 1, 3, or 5 bars as
competing sensitivities. `research/event_study_0830_0930/structures.py`
implements the single-candle 0.50 geometry. This is Category-C exploratory
methodology, not a D005 feature or production default.

D005 supplies separate frozen causal conventions used by D006: five-minute
reaction/refinement bars; prior ATR with lookback 14 and minimum 10; body/range
at least 0.60 and true-range/prior-ATR at least 1.25 for displacement; UTC
closed-bar availability; body-close MSS; independent raw/qualified FVG;
independent OB variants; and causal liquidity/context timestamps. Reusing a
threshold does not promote or change the D005 default.

### Criterion-level provenance

The classification vocabulary is closed:
`DIRECT_SOURCE_DEFINITION`, `INHERITED_FROZEN_PROJECT_CONVENTION`,
`NEW_D006_PREREGISTERED_OPERATIONALIZATION`, and `UNSUPPORTED`. A direct
conceptual rule does not make a numeric implementation threshold direct. The
following table freezes the provenance of every definition and lifecycle
criterion before any D006 market-outcome access.

| Frozen criterion | Exact source and location | Classification | Numeric value existed before D006? | Selected without D006 outcome access? | Scientific justification |
|---|---|---|---|---|---|
| Long-wick candle(s) at a swing, bullish/bearish symmetric concept | `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf`, PDF pp. 363-364; D005 audit A29 | `DIRECT_SOURCE_DEFINITION` | N/A | Yes | This is the source concept; it permits one or more candles and defines direction by swing high/low and wick-side liquidity exhaustion. |
| Exactly one baseline and exactly two consecutive candles as the fixed sensitivity | Event-study `concept_definitions.md`, rejection-block sensitivity section; ICT PDF p. 363 permits more than one candle | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes: one versus up to two was recorded pre-D006 | Yes | Registers the smallest pre-existing family instead of selecting a cluster length from outcomes. |
| Five-minute source timeframe | `research/context_engine/config.py`, frozen `reaction_timeframe` and `refinement_timeframe` | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Keeps construction aligned with the frozen D005 reaction/refinement leg. |
| Strict two-bar left swing | D006 specification, bullish/bearish rule 1; related pre-D006 event-study swing width was two-sided | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | Partly: width 2 existed, but the causal left-only rule did not | Yes | A two-left-bar test is causal at rejection-bar close and avoids future right-side swing confirmation. |
| Sweep of the immediately prior candle body edge | D006 specification, bullish/bearish rule 2 | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Converts the source's body-liquidity concept into a local, observable comparison without claiming hidden order flow. |
| Close-back reclaim of that prior-body edge | D006 specification, bullish/bearish rule 2 | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | The general close-back proxy existed; this exact edge did not | Yes | Supplies deterministic rejection/failure-to-continue confirmation on a closed bar. |
| Wick/range threshold `0.50` | Event-study `concept_definitions.md` and `structures.py`, rejection-block proxy | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Reuses the only implemented pre-D006 wick-dominance cutoff; the ICT PDF gives no number. |
| Close in the opposite half of the rejection candle | Event-study `concept_definitions.md` and `structures.py`, rejection-block proxy | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes: half-range `0.50` | Yes | Reuses the pre-D006 deterministic close-location proxy. |
| Candidate true-range/prior-ATR threshold `1.00` | D006 specification, bullish/bearish rule 5; earlier project displacement sensitivities contained `1.00`, not as an RB threshold | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | The number existed elsewhere; this use did not | Yes | Requires non-trivial normalized range while keeping it distinct from the stronger confirmation expansion. |
| Prior ATR lookback `14` | `research/context_engine/config.py`, frozen `atr_lookback` | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Reuses D005's causal volatility normalization. |
| Minimum prior ATR observations `10` | `research/context_engine/config.py`, frozen `atr_min_periods` | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Reuses D005's fail-closed minimum history rule. |
| Expansion within the next `3` closed bars | D006 definition IDs and bullish/bearish rule 6; event study preregistered `1`, `3`, and `5` as sensitivities | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | Yes: `3` was one pre-D006 sensitivity, but not the frozen RB choice | Yes | Fixes one bounded confirmation window instead of outcome-selecting among the prior alternatives. |
| Expansion body/range threshold `0.60` | `research/context_engine/config.py`, frozen D005 displacement threshold | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Reuses the existing causal displacement-strength convention. |
| Expansion true-range/prior-ATR threshold `1.25` | `research/context_engine/config.py`, frozen D005 displacement threshold | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Reuses the existing normalized displacement-strength convention. |
| Expansion close beyond the rejection body edge | D006 specification, bullish/bearish rule 6 | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Converts failure-to-continue/reversal into an auditable directional confirmation, without attributing the precise edge to the source. |
| Expansion must not cross the distal extreme | D006 specification, bullish/bearish rule 6 | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Prevents a candle that already violates the proposed zone from confirming it. |
| Single-candle proximal/distal boundaries are body edge to wick extreme | ICT PDF pp. 363-366; event-study `concept_definitions.md` and `structures.py` | `DIRECT_SOURCE_DEFINITION` | N/A for source concept | Yes | The source describes the body-edge-to-wick rejection interval; the tracked proxy implements the same single-candle geometry. |
| Two-candle cluster boundaries use the nearest body edge and most extreme wick across the cluster | D006 specification, block-boundary rules | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Extends the directly supported zone concept to a reproducible two-candle aggregate. |
| Proximal, midpoint, and distal geometry set | Event-study `concept_definitions.md`, rejection-block sensitivity section | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Preserves the pre-D006 small geometry set without choosing a best boundary. |
| Availability only after the qualifying expansion bar closes; defining-bar entries and same-bar touches excluded | D005 closed-bar conventions in `research/context_engine/bars.py` and D006 causality contract | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes for closed-bar availability; N/A for a numeric value | Yes | Enforces causal observability and makes ambiguous construction/touch ordering fail closed. |
| Invalidation is the first later closed-bar close through distal | D006 lifecycle section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Gives acceptance-through-area a deterministic, causal lifecycle meaning without trade-stop semantics. |
| Mitigation is first causal midpoint touch, with terminal-event precedence | D006 lifecycle section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | Midpoint existed; this lifecycle rule did not | Yes | Separates zone interaction from directional outcomes and resolves same-timestamp state changes deterministically. |
| First touch only; later touches retained only as audit counts | D006 lifecycle section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Prevents repeated observations from multiplying one structural event. |
| Expiry at `24` elapsed UTC hours after availability | D006 lifecycle section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Bounds lifecycle exposure with a fixed wall-clock rule; it is not claimed as source-derived. |
| Same-direction overlap uses connected components; strict containment records nesting; opposite directions remain distinct | D006 overlap/nesting section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Preserves every detected block while providing stable overlap and parent identifiers without outcome-based suppression. |
| Session/trading-date and DST handling | Frozen D005 IANA-zone session convention in `research/context_engine/config.py` and `bars.py` | `INHERITED_FROZEN_PROJECT_CONVENTION` | Yes | Yes | Retains explicit UTC storage and causal New York session labeling through DST. |
| Stable SHA-256 block IDs and deterministic ordering | D006 identifier/ordering section | `NEW_D006_PREREGISTERED_OPERATIONALIZATION` | No | Yes | Makes repeated runs and lifecycle joins byte-stable and auditable. |

No frozen primary-definition criterion is `UNSUPPORTED`. The rules classified
as `NEW_D006_PREREGISTERED_OPERATIONALIZATION` are explicitly new measurement
choices, not recovered ICT thresholds. No numeric value was changed during
this provenance review. Because the complete definition family remains fixed
before any D006 market outcome was opened, no re-registration is required for
this wording-only correction; changing any rule later would require a new
versioned preregistration before outcome access.

### Registered source fingerprints

The preflight registers these tracked provenance bytes:

| Path | SHA-256 |
|---|---|
| `docs/D005_STRATEGY_SOURCE_AUDIT.md` | `b9fcbc36efb51ef2a77ef2bfa09dea1df092e007bf18f7d4240d274c0e47fddd` |
| `research/context_engine/source_rule_catalog.json` | `13e71c4a1cfea76c3124ef9473b8f426abae252421ae9c0c619b673a5b8e3d3e` |
| `research/event_study_0830_0930/concept_definitions.md` | `0f6d813243eb658138419d8f7664209de0b1ef192bca7a3c632f9fd141352176` |
| `research/event_study_0830_0930/structures.py` | `915e75a18c484daac25d2200a773bda688aa7975771695031094ff8abe42ce74` |
| `research/context_engine/config.py` | `3b86421d5292987df8d646b67ab198c4a7c8b0e620837bbe2139f1a69bf3084e` |
| `research/context_engine/bars.py` | `44756989dedd90379b70d0530d847bfc228654bf1a82e38b47b2d0e02bd17761` |
| `research/context_engine/features.py` | `018d3671452b626168d2e83d115a3f35a09491fa7a92c2bb6078ba67062f75e1` |
| `research/context_engine/models.py` | `56e7d189cb3a39e27e553fb946d0acfa9096d3719f384986515e4ecdfd62866b` |
| `docs/D005_E4_1H_5M_REVERSAL_REPLICATION_SPEC.md` | `704c9e17072fa122ce27e9adcce510543dd265c43201e65fd432e816128d749b` |
| `docs/D005_E5_REPORTING_HARDENING_SPEC.md` | `440dcdb7edb344914a5a0dac43659b96ff48fe48dbee7827521084e93f503a15` |
| `docs/D005_E6_FUTURE_BLIND_REPLICATION_SPEC.md` | `1bba4d33adf8cefca81cd7b2cae1d9b3318494c49adb6de3fa1680928ec840fb` |

A mismatch is `REPRODUCIBILITY_DEFECT`; it is never silently accepted as a
new definition.

## Frozen definition family

The definition family contains exactly two profiles. It is not a Cartesian
grid and cannot be expanded after outcome access.

| Registry order | Definition ID | Role | Rejection candles |
|---:|---|---|---:|
| 0 | `single_wick_50_d3_v1` | Confirmatory baseline | Exactly one |
| 1 | `cluster2_wick_50_d3_v1` | Preregistered definition sensitivity | Exactly two consecutive, same-direction qualifying candles |

Both profiles use the same source timeframe, thresholds, expansion rule, zone
semantics, lifecycle, and outcome contract. Only the source-supported ambiguity
between one and more-than-one rejection candles differs. The 0.40/0.60 wick
fractions and 1/5-bar displacement windows documented by the earlier event
study are not D006 tests. No best definition, horizon, boundary, subgroup, or
parameter may be selected after outcomes are visible.

### Source timeframe and bar requirements

- Source timeframe: `5min` only, matching the frozen D005 `1h_5m` reaction and
  refinement leg.
- Historical construction, when separately authorized: D003 mid ticks to
  complete UTC one-minute OHLC, then to five-minute OHLC using left-closed,
  left-labeled epoch-aligned intervals. Lower-timeframe reconstruction of
  rejection-block lifecycle order is prohibited.
- Required structural bar fields are `timestamp_utc`, `bar_id`, `open`, `high`,
  `low`, `close`, `available_at`, and `is_complete`.
- `timestamp_utc` and `available_at` must be explicit UTC; a five-minute bar at
  `t` is available exactly at `t + 5 minutes`.
- Timestamps and bar IDs must be non-null, unique, and strictly increasing.
  OHLC must be finite and internally valid. Every input bar must be complete.
- A zero-range bar cannot be a rejection or expansion candle.
- ATR is the arithmetic mean of true range over the 14 preceding bars,
  shifted so the current bar is excluded, with at least 10 preceding values.
  Missing prior ATR makes that candidate ineligible; it is not imputed.

### Bullish rejection block

For the last rejection candle `r`, and its immediately prior candle `p`, all
conditions must hold using closed bars only:

1. `r.low` is strictly below the minimum low of the two bars preceding `r`.
2. `r.low < min(p.open, p.close)` and
   `r.close >= min(p.open, p.close)`. This is the deterministic body-edge
   sweep and close-back proxy; it does not assert hidden orders.
3. The lower-wick interval is `[r.low, min(r.open, r.close)]` and its width
   divided by `r.high-r.low` is at least `0.50`.
4. `r.close >= r.low + 0.50 * (r.high-r.low)`.
5. `true_range(r) / prior_ATR(r) >= 1.00`.
6. The first qualifying bullish expansion among the next one, two, or three
   closed bars has positive body, body/range at least `0.60`,
   true-range/prior-ATR at least `1.25`, closes strictly above
   `max(open, close)` over the rejection candle or cluster, and does not trade
   below the cluster distal extreme.

For `single_wick_50_d3_v1`, the cluster is `r`. For
`cluster2_wick_50_d3_v1`, both consecutive rejection candles must independently
satisfy conditions 2-5 in the same bullish direction, the second candle must
also satisfy condition 1 relative to the two bars before it, and the expansion
search begins after the second candle. A one-candle block is never relabeled as
a cluster.

The bullish boundaries are:

- distal: minimum low of the rejection candle(s);
- proximal: maximum `min(open, close)` over the rejection candle(s);
- midpoint: arithmetic mean of distal and proximal; and
- range: proximal minus distal, which must be strictly positive.

### Bearish rejection block

The bearish rules are the exact inverse:

1. `r.high` is strictly above the maximum high of the two bars preceding `r`.
2. `r.high > max(p.open, p.close)` and
   `r.close <= max(p.open, p.close)`.
3. The upper-wick interval is `[max(r.open, r.close), r.high]` and wick/range
   is at least `0.50`.
4. `r.close <= r.high - 0.50 * (r.high-r.low)`.
5. `true_range(r) / prior_ATR(r) >= 1.00`.
6. The first qualifying bearish expansion within the next three closed bars
   has negative body, body/range at least `0.60`, true-range/prior-ATR at least
   `1.25`, closes strictly below the minimum rejection-candle body edge, and
   does not trade above the cluster distal extreme.

The bearish proximal price is the minimum `max(open, close)` over the rejection
candle(s), distal is the maximum high, midpoint is their arithmetic mean, and
range is distal minus proximal.

### Creation, confirmation, and causal availability

- Source candle IDs are the ordered `bar_id` values of the rejection
  candle(s), followed by the expansion bar ID in a separate confirmation field.
- `creation_timestamp` is the opening timestamp of the last rejection candle.
- `confirmation_timestamp` is the `available_at` timestamp of the qualifying
  expansion bar.
- `causal_availability_timestamp` equals `confirmation_timestamp`. The block
  does not exist causally before the expansion closes.
- The rejection candle, any intervening bar, and the expansion bar cannot be
  used as a block touch or entry-timing observation.
- A block formed and traded through or touched before availability is retained
  as a structural detection with exclusion reason
  `pre_availability_interaction`; it is ineligible for touch/outcome cohorts.
- The first lifecycle bar may open at or after causal availability. A touch
  observed inside the expansion bar is always excluded.
- Same-timestamp construction that cannot establish strict source order fails
  closed. No tick or one-minute reconstruction may resolve an ambiguous
  five-minute lifecycle ordering in D006.

### Identity and deterministic ordering

The stable block ID is a truncated SHA-256 over the D006 version, definition
ID, source timeframe, direction, ordered rejection bar IDs, expansion bar ID,
creation and availability timestamps, and hexadecimal representations of
proximal/midpoint/distal. It never includes a later touch, invalidation,
mitigation, expiry, context, outcome, or report field.

Exact IDs are deduplicated. The canonical sort is causal availability,
definition registry order, creation timestamp, direction (`bearish` before
`bullish`), ordered source candle IDs, and block ID. Detector output must be
invariant to later lifecycle or outcome mutation.

## Overlap, nesting, and lifecycle

### Overlap and nesting

No detected block is removed merely because another block exists.

- Two blocks overlap when their closed price intervals intersect and both are
  causally available.
- Overlap groups are deterministic connected components. Their stable group ID
  is a hash of the sorted member IDs.
- For same-direction blocks, a later block wholly contained inside an earlier
  causally available block records the earliest causal containing block as
  `parent_block_id`. Lifecycle reporting separately records whether that parent
  remained active when the child became available. Remaining same-direction
  intersections share an overlap group without a parent relationship.
- Opposite-direction intersections share an overlap group but never create a
  parent/child relationship and never cancel or net one another.
- Nested and overlapping records are retained for audits. The baseline primary
  empirical cohort deduplicates by overlap group, direction, and definition,
  keeping the earliest availability, then smaller range, then block ID. This
  rule is structural and cannot inspect outcomes.

### Lifecycle states and transitions

A block begins `ACTIVE_UNTOUCHED` at causal availability. Only later complete
five-minute bars are eligible. The maximum lifetime is 24 elapsed UTC hours;
session boundaries do not reset it.

- First touch: first eligible bar whose high-low interval intersects the
  block's closed distal-proximal interval.
- Mitigation: first eligible bar that reaches or passes midpoint from the
  proximal side. It is terminal `MITIGATED` for D006 accounting.
- Invalidation: bullish close strictly below distal or bearish close strictly
  above distal. It is terminal `INVALIDATED`.
- Expiry: still-active block reaches availability plus 24 elapsed hours. It is
  terminal `EXPIRED` at that deadline.
- A proximal-only first touch changes state to `ACTIVE_TOUCHED`. Later touches
  increment `touch_count` but never replace `first_touch_timestamp`.
- For multiple conditions in one closed bar, precedence is invalidation,
  mitigation, first touch, then expiry. The terminal timestamp is that bar's
  `available_at`, except expiry uses the registered deadline.
- Lifecycle timestamps must be at or after availability and must respect the
  registered precedence. Future invalidation, mitigation, or expiry information
  cannot enter initial detection or identity.

Sessions use the frozen D005 exclusive `America/New_York` labels at causal
availability: `asia` 18:00-00:00, `premarket` 00:00-08:30,
`ny_observation` 08:30-12:00, `ny_afternoon` 12:00-17:00, and
`maintenance` 17:00-18:00. IANA conversion handles DST; fixed UTC offsets are
prohibited. Named trading dates follow the frozen 18:00-17:00 New York
convention. Blocks carry across all boundaries until a terminal transition.

## Data applicability and interval policy

### Verified contract and provenance qualification

The task identifies D003-v2 as immutable. Local release metadata records:

- release: `d003-v2`, XAUUSD canonical ticks;
- interval: `[2021-01-01T00:00:00Z, 2026-07-29T00:00:00Z)`;
- canonical manifest SHA-256:
  `a687c7acd95a6c4533528ab04a96373fc20000b826167ddd51bc57da34a2346d`;
- full verification SHA-256:
  `fbf0d909d60f9c906911d06aa21b5f125d4a68dbc2d65e444a559d89a1211efe`;
- Parquet checksum-manifest SHA-256:
  `f7d941278428a5e7a2f6890a22bf76e9da2af120f419242b5ba817125354173f`;
- release-checksum file SHA-256:
  `dac7f92993882f989dc04321d2df969efc383c7924edab5bc9bc9ac41a3266df`;
- exact canonical columns: `timestamp_utc`, `bid`, `ask`, `bid_volume`,
  `ask_volume`, `mid`, `spread`, `symbol`, `source_partition`; and
- verification status passed with zero reported timestamp, ordering,
  duplicate, price, spread, or volume errors.

Tracked D003 acceptance documentation names d003-v1, while the ignored local
d003-v2 metadata and E6 describe a provenance gap involving a dirty build
worktree and absent acquisition/D002 audit files. D006 does not repair,
reinterpret, regenerate, or overwrite either release. A later historical run
must verify the exact d003-v2 release/manifest/checksum contract and resolve or
explicitly accept the documented provenance qualification through human
review. Metadata presence is not permission to open a Parquet payload in this
task.

### Frozen historical design

All bounds are half-open UTC intervals.

| Role | Interval | Use |
|---|---|---|
| Bar source | `[2021-01-01T00:00:00Z, 2026-01-01T00:00:00Z)` | Construction coverage only; 2026 and later excluded. |
| Warm-up/calibration | `[2021-01-01T00:00:00Z, 2022-01-01T00:00:00Z)` | ATR warm-up, structural QA, and frozen matching-stratum support only; no threshold fitting or acceptance claim. |
| Rolling validation 1 | `[2022-01-01T00:00:00Z, 2023-01-01T00:00:00Z)` | Historical validation fold. |
| Rolling validation 2 | `[2023-01-01T00:00:00Z, 2024-01-01T00:00:00Z)` | Historical validation fold. |
| Rolling validation 3 | `[2024-01-01T00:00:00Z, 2025-01-01T00:00:00Z)` | Historical validation fold. |
| Rolling validation 4 | `[2025-01-01T00:00:00Z, 2026-01-01T00:00:00Z)` | Historical validation fold. |
| Final holdout | None | D006 makes no independent-replication claim. |

An event is eligible in a fold only when its 120-minute maximum registered
endpoint is strictly before the fold's exclusive end. This creates a
120-minute endpoint buffer inside every fold and prevents cross-fold endpoint
borrowing. Thresholds and registries are identical in every fold. There is no
rolling refit, early stopping, sample-size stopping, or best-year selection.

The known E4 interval `[2026-01-01T00:00:00Z, 2026-07-29T00:00:00Z)` is
excluded from D006 discovery, validation, and holdout claims. Future independent
replication is a later milestone and cannot reuse that interval as blind data.

### Completeness and missing data

Each constructed segment must contain at least 95% of the five-minute bars
expected from the verified D003 source/closure contract. Missing intervals are
not imputed. Candidate source sequences crossing a missing or incomplete bar
are excluded as `incomplete_source_sequence`. A required outcome endpoint that
is missing is `incomplete_endpoint`. Endpoint completeness must be 100% in the
primary paired cohort. Missing context produces `context_unavailable`, never a
neutral or adverse label. Non-finite values are rejected. No primary or
confirmatory metric uses value trimming or winsorization.

## Layered implementation contract

All D006 code is additive under `research/d006_rejection_block_research/`.
The complete later architecture is:

1. `source.py`: release verification, read authorization, tick/one-minute and
   five-minute construction;
2. `detector.py`: structural definition only;
3. `lifecycle.py`: touch, mitigation, invalidation, expiry, overlap, nesting;
4. `context.py`: causal joins to frozen D004/D005 structural features;
5. `outcomes.py`: downstream price-path endpoints only;
6. `statistics.py`: registered tests, bootstrap, BH, stability, disposition;
7. `reporting.py`: schema validation and isolated atomic reporting.

In the first task only configuration/models, synthetic detector, synthetic
lifecycle, schemas, and outcome-disabled preflight may exist. `source.py`,
`context.py`, `outcomes.py`, `statistics.py`, `reporting.py`, an execution
pipeline, CLI, and scientific output writer are intentionally absent. Their
absence is a guardrail, not an incomplete historical run.

The combined structural export formed by a one-to-one detector/lifecycle join
contains only: block ID; definition; direction; source timeframe; creation,
confirmation, and availability timestamps; proximal, midpoint, and distal;
range and prior-ATR-normalized range; ordered rejection and expansion source
candle IDs; session and trading date; lifecycle state and timestamps; touch
count; expiry deadline; overlap group; parent relationship; and causal context
keys. It also carries the causal pre-availability-interaction exclusion flag
and, for a nested block, whether its parent was active when the child became
available. Detector and lifecycle records remain separate internally. Neither record
contains a forward endpoint, statistical result, or component disposition.

## Frozen scientific hierarchy

Every future D006 report begins with:

```text
Integrity -> Sample Adequacy -> Structural Claim -> Primary Empirical Claim
          -> Preregistered Secondary Claims -> Component Disposition
```

### Integrity gate

Any failure below yields `REPRODUCIBILITY_DEFECT`; no scientific claim is
evaluated:

- specification, configuration, implementation, provenance, canonical,
  release, manifest, or checksum fingerprint mismatch;
- unauthorized data, output, or production access;
- UTC, interval, session, DST, closed-bar, completeness, or endpoint invariant;
- unstable block identity/order or non-reconciling lifecycle/overlap accounting;
- causal context join, deduplication, or treatment/control reconciliation
  failure;
- future invalidation/mitigation/outcome information in detection or selection;
- forbidden fitting, tuning, subgroup selection, parameter expansion, or
  outcome-conditioned stopping; or
- modification of a protected D003-D005/E4-E6, production, raw, canonical,
  release, manifest, checksum, report, stash, branch, or ignored output.

### Registered sample-adequacy gate

Thresholds are checked before effect estimates can be decisional:

| Requirement | Minimum |
|---|---:|
| Baseline detected blocks across 2022-2025 | 1,000 |
| Baseline bullish blocks | 200 |
| Baseline bearish blocks | 200 |
| Lifecycle-eligible baseline blocks | 800 |
| First-touched baseline blocks | 500 |
| Untouched baseline blocks, when compared | 200 |
| Endpoint-complete primary treatment/control pairs | 500, exact 1:1 |
| Endpoint-complete primary pairs per year | 100 in each of 2022-2025 |
| Primary pairs per direction | 200 bullish and 200 bearish |
| Touched blocks in each required session | 50 in each of asia, premarket, ny_observation, ny_afternoon |
| Maintenance | reported, not required |
| Each confirmatory interaction | 200 treatment/control pairs |
| D004 manipulation interaction | 100 pairs because its frozen clock eligibility is narrow |
| Geometry boundary cohort | at least 200 and at least 60% of proximal cohort |
| Primary endpoint coverage | 100% |
| Required years | all four validation years |

Every confirmatory context stratum must meet its own registered minimum; an
adequate pooled sample cannot rescue an inadequate stratum. If any requirement
needed by a claim fails, that claim is `NOT_EVALUATED`. If the global primary
requirements fail, the dominant adequacy status is `SAMPLE_INADEQUATE`, the
primary status is `NOT_EVALUATED`, all numeric results are explicitly
`DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE`, and no metric is evidence
of edge.

### Primary structural claim

> Rejection blocks can be detected causally, reproducibly, and with stable
> lifecycle accounting across all four historical years and both directions.

It passes only if integrity and global adequacy pass; two identical runs from
the same verified inputs produce identical ordered detector/lifecycle bytes;
all identities and causal availability timestamps remain unchanged after
mutation of later lifecycle/outcome-like fields; every count reconciles;
every year and direction is present above its minimum; and zero UTC,
closed-bar, source-order, overlap, nesting, or lifecycle-order violations are
observed. It fails on any unmet condition and can never be inferred from
synthetic fixtures alone. This first task proves implementation guardrails,
not the historical structural claim.

### Primary empirical claim

The sole primary empirical claim is:

> Among deduplicated, lifecycle-eligible `single_wick_50_d3_v1` blocks with a
> first causal proximal-zone touch in the 2022-2025 rolling validation folds,
> the mean 60-minute direction-aligned close-to-close movement after the touch
> is greater than that of the preregistered matched non-block control and is
> temporally stable.

The event timestamp is the first-touch five-minute bar's `available_at`. The
reference price is that bar's close, which is causal and identical in meaning
for treatment and control. The endpoint is the last complete five-minute close
at exactly 60 minutes after the event timestamp. Direction alignment is
`+1 * (endpoint-reference)` for bullish and `-1 * (endpoint-reference)` for
bearish. Each block contributes once after structural overlap-group
deduplication. Blocks with pre-availability interaction, missing bars,
incomplete session/source sequence, incomplete endpoint, ambiguous order,
missing control, or missing direction are excluded with one first-failure
reason.

The estimand is the mean within-pair treatment-minus-control difference. The
primary test is a two-sided paired Student-t test at alpha 0.05 with a 95%
Student-t confidence interval; the claim requires a positive mean, confidence
interval lower bound above zero, and p-value below 0.05. This one-test family
is not BH-adjusted. A paired New York-trading-date bootstrap must corroborate a
lower bound above zero. Temporal stability additionally requires a positive
yearly mean difference in at least three of four adequate years and no adequate
year with a 95% confidence-interval upper bound below zero. The primary claim
cannot be redefined as a best horizon, boundary, definition, session,
direction, or subgroup.

## Controls and counterfactuals

All matching uses only fields causally known at the event and never uses a
forward price. Candidate controls must be endpoint complete, must not be on the
same New York trading date as treatment, and must not be a rejection-block
availability/touch or lie within 120 minutes of one. Matching is without
replacement inside a control family.

Each treatment is matched within validation year, D005 session, direction, and
causal volatility bucket. The volatility value is the most recent complete
D005 daily range divided by the median of the previous 20 complete daily
ranges; buckets are frozen as low `<0.75`, normal `0.75-1.25`, high `>1.25`,
and unavailable. Within the exact strata, candidates are limited to plus or
minus 30 calendar days and ordered by SHA-256 of
`D006 seed | control family | treatment block ID | candidate timestamp`; the
lowest unused hash wins. No eligible candidate means `missing_control`.

Registered controls are:

1. `matched_non_block`: complete five-minute candles with no active/touched
   rejection block; this is the primary control and provides time/session,
   volatility, and direction balance.
2. `matched_displacement_without_rb`: frozen D005 displacement confirmations
   with no active/touched rejection block, matched at their causal timestamp.
3. `matched_context_without_rb`: frozen D005 `reaction_confirmed` snapshots
   with no active/touched rejection block, matched at evaluation time.
4. `matched_time_session_volatility`: an explicit audit view of the same exact
   time/session/volatility constraints used by the primary matcher.
5. `direction_balanced`: an exact bullish/bearish reweighting audit; it cannot
   change the primary paired sample.
6. `random_time_placebo`: one eligible non-event time per treatment, selected
   by the same fixed seed/hash rule inside the exact strata.

Treatment and control definitions cannot change after results are visible.
Displacement-only, context-only, time/session/volatility, and random-placebo
incremental tests form the fixed four-test secondary control family. Direction
balance is an audit, not a fifth hypothesis.

## Fixed interaction registry

No other feature combination is a D006 test.

| Interaction ID | Eligibility and timing | Direction rule | Role | Minimum pairs |
|---|---|---|---|---:|
| `rb_alone` | Baseline block at first causal touch; no context required. | Block direction. | Primary standalone | 500 |
| `aligned_d005_context` | Latest D005 snapshot at or before block availability is `reaction_confirmed`; its evidence timestamps are no later than availability. | Exact agreement. | Confirmatory secondary | 200 |
| `after_d004_manipulation` | Frozen D004 causal manipulation/sweep-reentry state completed before block availability on the same named trading date. A retrospective D004 day label is forbidden. | Block agrees with the causally registered D004 reaction direction. | Preregistered exploratory because D004 is clock-narrow | 100 |
| `frozen_liquidity_sweep` | Latest frozen D005 liquidity-sweep evidence is available no later than block availability and has not been invalidated before availability. | Exact agreement. | Confirmatory secondary | 200 |
| `displacement_confirmation` | A distinct frozen D005 displacement confirmation is available no later than block availability and no more than 60 minutes earlier. The D006 expansion candle alone cannot self-satisfy this join. | Exact agreement. | Confirmatory secondary | 200 |
| `refinement_confirmation` | A frozen D005 refinement-array creation/confirmation is available no later than first touch. Later refinement is forbidden. | Exact agreement. | Confirmatory secondary | 200 |
| `against_d005_context_negative_control` | Latest causal D005 snapshot at or before availability is non-neutral and `reaction_confirmed`. | Exact disagreement. | Confirmatory negative control | 200 |

For every row, stored context keys include source event/snapshot ID, context
timestamp, available-at timestamp, frozen feature/version, and agreement. A
context timestamp after block availability, except the explicitly touch-time
refinement rule, fails integrity. The six non-standalone interactions are one
BH family; the D004 row is reported inside that family but cannot by itself
produce `CONDITIONAL_CANDIDATE` because its role is exploratory.

## Redundancy and incremental value

Structural redundancy is reported before effect estimates:

- price-zone and causal-time overlap with frozen displacement anchors;
- overlap with refinement-array anchors;
- overlap with body-close MSS events;
- overlap with raw and context-qualified FVG events when available;
- overlap with frozen liquidity sweeps and D005 reaction-confirmed context;
- signed time differences between rejection creation/availability/touch and
  each frozen feature; and
- exact identity/overlap denominators, never pooled across definitions.

Overlap is descriptive and cannot prove incremental value. Confirmatory
incremental tests compare the baseline treatment against the four registered
control families. A fixed ablation view compares, within the exact aligned
interaction cohort, existing feature alone versus existing feature plus
rejection block; it uses the same pairs and endpoint and cannot search feature
sets. Black-box feature importance is prohibited as primary evidence.

Any later predictive model is secondary only: a preregistered unpenalized
linear model with year fixed effects and frozen covariates for direction,
session, causal volatility bucket, D005 context direction, manipulation state,
liquidity sweep, displacement, refinement, MSS, and FVG. It must be fit on
prior years and evaluated on the next year without tuning. D006 acceptance
does not require or use this model.

## Geometry plan

Geometry is secondary and never uses stop, target, R, order, or P&L semantics.
The only boundary references are proximal, midpoint, and distal. For each,
D006 reports:

- causal touch rate and denominator;
- elapsed minutes to first touch;
- invalidation-before-touch rate;
- 60-minute direction-aligned close-to-close movement after boundary touch;
- maximum favorable excursion and maximum adverse excursion in price units;
- MFE/MAE ratio when MAE is positive, with zero-MAE cases reported separately;
- adverse-before-favorable ordering;
- expiry rate; and
- lifecycle duration.

Proximal is the frozen baseline. Midpoint-versus-proximal and
distal-versus-proximal comparisons for touch rate, time to first touch,
invalidation-before-touch, direction-aligned movement, and MFE/MAE ratio form
the exact 10-test geometry BH family. MFE, MAE, adverse ordering, expiry, and
duration are required descriptive diagnostics but are not additional tests.

A non-proximal boundary satisfies the geometry improvement rule only if its
cohort has at least 200 observations and at least 60% of the proximal sample;
both direction samples are adequate; direction-aligned movement is not
inferior (lower 95% paired-difference bound at least zero); MFE/MAE improves
with BH q-value at most 0.05; adverse-before-favorable probability is lower;
at least three of four adequate years agree in sign; and no year has a
significant opposite result. Midpoint has deterministic priority over distal
when both satisfy the rule. This is geometry evidence, not an entry rule.

## Statistical plan and fixed registries

- Confidence level: 95%.
- Student-t intervals: mean levels and paired mean differences; no normal
  approximation when fewer than two observations exist.
- Bootstrap: 2,000 resamples of New York trading dates, preserving all events
  and treatment/control pairs on each sampled date; fixed base seed `6006` and
  SHA-256-derived cell seeds.
- Primary test: paired two-sided Student-t test, one unadjusted hypothesis.
- FDR: Benjamini-Hochberg at `q=0.05`, independently within each frozen family.
- Exact families: one definition-sensitivity test; six interaction tests; four
  incremental-control tests; ten geometry tests. Family membership never
  depends on available or significant results; missing cells remain registered
  with `NOT_EVALUATED` and do not migrate to another family.
- Robust summaries: median, interquartile range, 1% symmetric trimmed mean,
  and mean after removing the largest 1% absolute observations. These are
  sensitivity diagnostics only; the primary analysis removes no finite
  observation.
- Direction: pooled primary plus mandatory bullish and bearish splits.
- Time: mandatory 2022, 2023, 2024, and 2025 splits; no pooled-only claim.
- Sessions: the five frozen D005 labels; maintenance is descriptive only.
- Missing values: never imputed; first-failure exclusion and denominator are
  recorded.
- Outliers: retained in the primary test; non-finite values fail/exclude under
  the registered data rule, not an effect-based rule.
- Effect sizes: treatment/control means and their paired difference in XAUUSD
  price units, standardized paired mean difference, median paired difference,
  and confidence intervals. No economic/trade conversion.
- Temporal stability: at least three of four adequate yearly effects have the
  required sign and no adequate year has a 95% interval wholly in the opposite
  direction.

Result labels are `CONFIRMATORY_PRIMARY`, `PREREGISTERED_SECONDARY`, or
`EXPLORATORY_DIAGNOSTIC`. Exploratory results cannot change acceptance or
component disposition.

## Component disposition

Exactly one disposition is selected using this priority order:

1. `REPRODUCIBILITY_DEFECT`: integrity fails.
2. `INSUFFICIENT_EVIDENCE`: integrity passes but global adequacy, primary
   endpoint coverage, or the structural claim cannot be evaluated.
3. `NON_REDUNDANT_COMPONENT_CANDIDATE`: structural and primary empirical claims
   pass; at least one of displacement-only or context-only incremental tests
   improves over matched control after BH; temporal and direction stability
   pass; and no exact existing-feature cohort fully accounts for the effect.
4. `CONDITIONAL_CANDIDATE`: the structural claim passes; at least one
   confirmatory interaction was preregistered, is adequate, improves over its
   matched constituent-feature control, is temporally and directionally stable,
   is not entirely explained by an existing frozen feature, and survives its
   registered BH family. `after_d004_manipulation` cannot alone satisfy this
   rule because it is exploratory.
5. `GEOMETRY_CANDIDATE`: the structural claim passes and the exact geometry
   improvement rule passes, even if standalone directional evidence does not.
6. `REJECT_COMPONENT`: global adequacy and the structural claim pass; the
   primary paired-difference 95% upper bound is at most zero; at least three of
   four yearly means are non-positive; and no non-redundant, conditional, or
   geometry rule passes.
7. `STRUCTURALLY_VALID_EMPIRICALLY_WEAK`: the structural claim passes, but no
   candidate or deterministic rejection rule above passes.

Candidate priority does not imply production suitability. A weak standalone
effect never blocks a later conditional or geometry candidate when its own
preregistered rule passes. No D006 result selects a final composite strategy.

## Aggregate audit and reporting contract

Before execution, the report schema requires exact integer counts and exact
denominator definitions for:

- detected, duplicate-ID-excluded, lifecycle-eligible, endpoint-eligible, and
  endpoint-complete blocks;
- touched, untouched, mitigated, invalidated, and expired blocks;
- pre-availability interaction, overlap, nested, bullish, and bearish blocks;
- definition, year, session, direction, and terminal-state counts;
- exclusions by the mutually exclusive precedence: interval boundary,
  duplicate identity, causal-observability failure, incomplete source sequence,
  incomplete session, pre-availability interaction, missing context, missing
  control, incomplete endpoint;
- treatment and every control candidate/matched/unmatched count;
- expected and observed treatment/control pair counts and equality;
- every interaction candidate, eligible, endpoint-complete, matched, and
  excluded count; and
- proximal, midpoint, and distal eligibility/touch/endpoint-complete counts.

Required reconciliation includes:

```text
detected = eligible + all mutually exclusive structural exclusions
eligible = touched + untouched
eligible = mitigated + invalidated + expired + active_censored
touched >= mitigated
overlapping <= detected
nested <= overlapping
bullish + bearish = detected
matched + unmatched = control_candidates
expected_pairs = observed_pairs = endpoint_complete_primary_pairs
```

Definition, year, session, direction, exclusion, interaction, control, and
geometry maps must sum to their stated denominators. Additional aggregate
fields are forbidden unless a later preregistration version is reviewed before
outcome access.

The final report must present, in order:

1. definition and provenance;
2. fingerprints and integrity;
3. data applicability and interval audit;
4. structural validation and reproducibility;
5. lifecycle/overlap/nesting accounting;
6. sample adequacy;
7. primary empirical result and primary matched control;
8. remaining controls and counterfactuals;
9. fixed context interactions;
10. redundancy and incremental value;
11. geometry;
12. yearly, direction, session, and causal-volatility stability;
13. preregistered secondary results;
14. separately labeled exploratory diagnostics;
15. limitations;
16. component disposition; and
17. recommendation for later composite research.

If integrity fails, only safe access/fingerprint/audit fields may be reported.
If adequacy fails, the dominant primary status is `NOT_EVALUATED`, every
number is descriptive and non-decisional, and no metric is presented as edge.

## First-task preflight and acceptance

The first task passes only when:

- this specification and a deterministic configuration fingerprint exist;
- the authoritative definition audit and data applicability qualification are
  recorded without opening a Parquet payload;
- the two-definition registry, causal timestamps, lifecycle, controls,
  interactions, multiple-testing families, adequacy thresholds, report schema,
  and dispositions are immutable in code and specification;
- synthetic tests prove bullish/bearish detection, causal availability,
  closed-bar enforcement, same-bar touch exclusion, lifecycle precedence,
  overlap/nesting, deterministic identity/order, strict UTC, missing-column and
  duplicate rejection;
- guardrail tests prove no canonical Parquet read, no historical outcome
  execution, no trade/P&L schema, no unrestricted parameter search, exact
  interaction/testing registries, complete aggregate schema, deterministic
  fingerprints, protected-path preservation, and no D006 scientific output
  directory; and
- focused D006, focused D005/E4/E5/E6 guardrails, the full repository suite,
  and `git diff --check` pass, subject to the documented absence of
  `automation/config.yaml`.

Passing this first task means only that the D006 preregistration and synthetic
preflight are reviewable. It does not pass either historical scientific claim
and does not authorize the next task. Real historical execution requires a
separate explicit instruction after review of this diff and the d003-v2
provenance qualification.
