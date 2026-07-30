# Pre-D005 Strategy Source PDF Audit

## Audit status and boundary

Status: **complete for the 12 prioritized authoritative PDFs, with two image-only notes inspected as supporting evidence only**.

This is a documentation and requirements-extraction task. It does not authorize D005 implementation. No production or research strategy logic, defaults, signals, execution rules, datasets, or market data were changed.

All page references below are **1-based PDF page numbers**, not the page numbers printed inside a document. Category labels are:

- **A — Explicit source rule:** stated in at least one inspected PDF.
- **B — User-defined strategy rule:** stated by the user; may agree with sources but is not promoted to category A.
- **C — Interpretive implementation candidate:** a measurable research translation, not a source fact.
- **D — Unsupported assumption:** neither sourced nor user-defined; prohibited from D005 without approval.

Timing guardrail: every 09:30 NYSE Open, 10:00 Key Open, index PO3, ES/SP500/NAS100, RTH, Opening Range Gap, and index “Silver Bullet” timing is educational context only. No such timing or expected behavior may be transferred to XAUUSD without independent XAUUSD validation. The user’s 08:30–09:00 New York window remains a research constraint, not a fact proven by the PDFs.

Repository root:

`/Users/serhanceylan/Desktop/shiedafx - finance/XAUUSDBOT/xauusd-trading-ai-smc-v2`

## 1. Relevant source inventory

### Method and accessibility

The audit enumerated every PDF in `docs/raw_sources/`, computed SHA-256 with the file bytes, and opened every file with a PDF parser. All **43 of 43** PDFs were physically accessible and openable. Some files emitted recoverable cross-reference warnings, but every file returned a page count and rendered successfully where selected.

Page-indexed text was extracted from the 12 authoritative PDFs and two supporting notes. Text coverage varied because some pages are chart images:

| Source | Text-bearing pages / total | Evidence handling |
|---|---:|---|
| `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | 405 / 405 | Text extraction plus rendered inspection |
| `the-ict-handbook-v-1 1.pdf` | 37 / 37 | Text extraction plus rendered inspection |
| `Smart Money Concept (SMC) Trading.pdf` | 131 / 167 | Text extraction plus rendered inspection |
| `EKINYZBB BOOTCAMP SERISI.pdf` | 19 / 20 | Text extraction plus rendered inspection |
| `EKINYZBB ILERI SEVIYE ICT SERISI.pdf` | 12 / 12 | Text extraction plus rendered inspection |
| `IPDA_-Market_Cycle.pdf` | 11 / 22 | Text extraction plus rendered inspection |
| `Mastering ict.pdf` | 49 / 49 | Text extraction plus rendered inspection |
| `Market Structure - Skatfx.pdf` | 28 / 28 | Extracted glyph encoding was unreliable; rendered pages control |
| `One Setup For Life - Redeye.pdf` | 5 / 12 | Text extraction plus rendered inspection of chart pages |
| `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf` | 15 / 15 | Text extraction plus rendered inspection |
| `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf` | 11 / 11 | Text extraction plus rendered inspection |
| `_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf` | 7 / 7 | Text extraction plus rendered inspection |
| `INDICES 8.30 PO3 Model Mr MatriX.pdf` | 0 / 7 | Image-only; rendered pages are controlling evidence |
| `PO3 Model (10 AM) Mr MatriX.pdf` | 0 / 5 | Image-only; rendered pages are controlling evidence |

Local OCR was not required to interpret the two supporting notes: their rendered text was legible. No claim in this audit rests on OCR alone.

### Complete openable PDF and hash inventory

Role `authoritative` denotes the 12 prioritized D005 sources. Role `supporting_only` denotes the two image-only notes. `inventory_only` files were opened and hashed but were not used to create category A rules in this prioritized audit.

| # | Exact source path | Pages | SHA-256 | Role |
|---:|---|---:|---|---|
| 1 | `docs/raw_sources/0934380406_Trading_Secrets_of_the_Inner_Circle_Goodwin_1997_12_01.pdf` | 97 | `535de078a62eaeb7b7742ed0af6bdba852b7b39b2bb6bad22c8fbf344a079418` | inventory_only |
| 2 | `docs/raw_sources/_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf` | 11 | `45c79925ebda8a68f5d27c0e87dffda981187f21c1a1375f864dc04b9c4013e6` | authoritative |
| 3 | `docs/raw_sources/_ICT_-_Market_CYCLE__Manipulation_Series_(Ep.3).pdf` | 12 | `f4c842c4095472208ea8358848f4880b3e4c3522531bcb0c93a60e84bb2c00be` | inventory_only |
| 4 | `docs/raw_sources/_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf` | 8 | `27e6c6731f4051593f875f1a372c5aa9a7d52cb6c50a79136cdc13aab0238b26` | inventory_only |
| 5 | `docs/raw_sources/_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf` | 15 | `8ce98e60cae3b47b19f8e17b7bb8ae486a53f891858b0a9ef8101bb842a59231` | authoritative |
| 6 | `docs/raw_sources/_Maniplasyon_Nedir_Piyasalar_Neden_Maniplasyon_zerine_Kuruludur.pdf` | 13 | `ada5a835fdbd8d4de70b921cbd244a01f0debfc430eaf5a0d5cd100f3b508341` | inventory_only |
| 7 | `docs/raw_sources/_Maniplasyon_Stratejisi_ile_aldm_ilem_2000_Manipulation_Series_Ep.pdf` | 8 | `c4fa028713714765c9b12d959d2c65e2e7d48e8c2efa778df6835f1416e8b809` | inventory_only |
| 8 | `docs/raw_sources/_Market_Maker_Model_Nedir_10_000_payoutu_mmxm_ve_maniplasyon_teknikleri.pdf` | 14 | `b8624038c5000bb8d3193d860a54d40b33f02f23d9450d8905bb934a1d3f07ab` | inventory_only |
| 9 | `docs/raw_sources/_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf` | 7 | `65259bcfe8f57a4b064cf3783aca13f5d59b6303fda3116557fcc58cc3979ed5` | authoritative |
| 10 | `docs/raw_sources/_Yln_eyrekleri_nasl_yorumlanmal_2025_Bitcoin_Tahminlerim_HTF_Bias.pdf` | 8 | `1f71713dd4e4756f8780d35aa04dcb75f9ee92c7e41e636081ad384682e55e6a` | inventory_only |
| 11 | `docs/raw_sources/Advanced Algorithmic Trading - Michael L. Halls.pdf` | 509 | `840908fd054f61ba0213a5dd79fed2dcbc6b8f3963ed72e89e6e05cd1991228b` | inventory_only |
| 12 | `docs/raw_sources/Artificial Intelligence in Finance.pdf` | 477 | `5e567dccfc24b29a1340905d16791558bcc6969dc0ab7bd388561a592a48716b` | inventory_only |
| 13 | `docs/raw_sources/COT LW 1.pdf` | 3 | `0a2fc03121decc66f265af57fccc4d3664f679c8b0c0fb81902af3eb842272b8` | inventory_only |
| 14 | `docs/raw_sources/CRT Model Mr matriX.pdf` | 10 | `650946e71d64e510bd99364ce09797082add83cba6395e5ad91cb09764c61655` | inventory_only |
| 15 | `docs/raw_sources/Deep Learning for Finance.pdf` | 362 | `068e6191cf6c5f6f0aed13d0bae8d06137048f33d6a8d9ca16ff32b51bec81d3` | inventory_only |
| 16 | `docs/raw_sources/DREYKO_NOTES_2025_Lecture_Series_Making_Money_With_SMC_Concepts.pdf` | 18 | `3d614cf4c01c112759edd8e683544882940d83292015c5c6b03d5dd8460f0c54` | inventory_only |
| 17 | `docs/raw_sources/EKINYZBB BOOTCAMP SERISI.pdf` | 20 | `6fd9c61fb7956ce2e31a3cbf94f1edcfe405325dccd5693bc4b95635100d59ae` | authoritative |
| 18 | `docs/raw_sources/EKINYZBB ILERI SEVIYE ICT SERISI.pdf` | 12 | `001ba8bb7afe603d1326ad8341dbde12bb0cde07a323435683a90bd3b4c1be1c` | authoritative |
| 19 | `docs/raw_sources/ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | 405 | `0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0` | authoritative |
| 20 | `docs/raw_sources/ICT Ekolünde.pdf` | 4 | `966ea16c347c9936e191d5a7a05af8f2601ece685a87eede0adf12c83a63bb53` | inventory_only |
| 21 | `docs/raw_sources/INDICES 8.30 PO3 Model Mr MatriX.pdf` | 7 | `c3f62c98fd460aa9cfaa19febfe0ea8c35e81a6c38a0ea0f26f7889dd556a9c3` | supporting_only |
| 22 | `docs/raw_sources/Insider'ların_Sırlarıyla_Hisse_Senedi_ve_Emtia_Ticareti_COT_Raporunun.pdf` | 52 | `bdfecb0279638501ca7f0aca9fc16c6a6b8440d6139beab573a0bedad5214727` | inventory_only |
| 23 | `docs/raw_sources/IPDA_-Market_Cycle.pdf` | 22 | `63179e0340e1d78f01b8b1c28a4e55c350bdc7af4a66ad6ea28b0c2acbf97857` | authoritative |
| 24 | `docs/raw_sources/Larry Williams Forecast 2026.pdf` | 128 | `c199b310420ba64d73dfeec38c6a2754c3cd7452798d3ae7a918955cc9422616` | inventory_only |
| 25 | `docs/raw_sources/Market Structure - Skatfx.pdf` | 28 | `ef00bc585d5a554c60ddd510d040faad3e11b3320772db9d895fac480b0bacc8` | authoritative |
| 26 | `docs/raw_sources/Mastering ict.pdf` | 49 | `7f380e5abca325db845270cb76e6c1fe04ae64290822d7f28ccaeba32ab287b3` | authoritative |
| 27 | `docs/raw_sources/Michael Jenkins - The Geometry of Stock Market Profits.pdf` | 161 | `95dce3a049a65b614f1162193305dcac60bce035ead38aef62bf422144cc9d41` | inventory_only |
| 28 | `docs/raw_sources/Michael_McDonald_Predict_Market_Swings_with_Technical_Analysis.pdf` | 220 | `327637502f1c14bfdcd295537ee4c4d1aaa6d8a7d88fe9470b4daeadb330055c` | inventory_only |
| 29 | `docs/raw_sources/MMXM Trader's executions 2023 .pdf` | 144 | `24a7d5d677a509b5279ae3bc8741a1df0eec99ff45e2ed01f6740009a538e12d` | inventory_only; duplicate bytes with #30 |
| 30 | `docs/raw_sources/MMXM Trader's işlem örneği 2023  (1).pdf` | 144 | `24a7d5d677a509b5279ae3bc8741a1df0eec99ff45e2ed01f6740009a538e12d` | inventory_only; duplicate bytes with #29 |
| 31 | `docs/raw_sources/One Setup For Life - Redeye.pdf` | 12 | `4649eb507b1c6d81382cd435d4b220a8bf4610dcd604c4008df93ca9bfa336e5` | authoritative |
| 32 | `docs/raw_sources/Opening Range GAP - DREYKO.pdf` | 18 | `51d28c6961c70955f52f73f3ab7f86687b6cd4bb6ae42ea357f6ba9c222eb028` | inventory_only |
| 33 | `docs/raw_sources/PO3 Model (10 AM) Mr MatriX.pdf` | 5 | `7d3dc7e5f7efe2aa0f0fca3a36fcf7becb014a26ff296dbdd789bbdcbe383f53` | supporting_only |
| 34 | `docs/raw_sources/Smart Money Concept (SMC) Trading.pdf` | 167 | `eee94a43c182ae92802ec83aecf4421ddf0ed64cdfceeb7ab075dc2df21b304e` | authoritative |
| 35 | `docs/raw_sources/Successful Algorithmic Trading - Michael L. Halls.pdf` | 208 | `d21306851059fe16b571e0c19e7b780f2d311a497bb34caa1353e32e69d5184f` | inventory_only |
| 36 | `docs/raw_sources/Sunu 16.pdf` | 12 | `4649eb507b1c6d81382cd435d4b220a8bf4610dcd604c4008df93ca9bfa336e5` | inventory_only; duplicate bytes with #31 |
| 37 | `docs/raw_sources/tarıkabiönemlinotlar (1).pdf` | 20 | `f63a0d63282ae68bcd125415e57a9ee77032752bd64218104bbce776874a9f14` | inventory_only |
| 38 | `docs/raw_sources/the-ict-handbook-v-1 1.pdf` | 37 | `5ac9da7c14a3c246add9495d1171ba3c834f34cc56df0470065aec4ce0ccae34` | authoritative |
| 39 | `docs/raw_sources/Trade Stocks and Commodities With the Insiders.pdf` | 224 | `e0cb141f9b3dc2573d3daac935227910030a2ac2e67c18bdfa8328c22d8bec19` | inventory_only |
| 40 | `docs/raw_sources/Trade_Stocks_Commodities_with_the_Insiders_Secrets_of_the_COT_Report.pdf` | 224 | `4da1a1f2b821e25675ed87a9eaa8d2b2f51ee33a2b90cfe2ff7e5f026bfb3671` | inventory_only |
| 41 | `docs/raw_sources/Unlocking Success in ICT 2022 Mentorship - Lumitrader-1.pdf` | 435 | `0bbcbe091a9523a326d233af94bd3cbea9940746431fe2587e9995d2215cc652` | inventory_only; duplicate bytes with #42 |
| 42 | `docs/raw_sources/Unlocking Success in ICT 2022.pdf` | 435 | `0bbcbe091a9523a326d233af94bd3cbea9940746431fe2587e9995d2215cc652` | inventory_only; duplicate bytes with #41 |
| 43 | `docs/raw_sources/xx_williams_larry_r_inner_circle_workshop_seminar_manual_pr_dd4.pdf` | 89 | `e2df214d675db7edd582e80bb6d9ed66edc4c6afca74f201f93361f2d1d1806a` | inventory_only |

### Relevant authoritative page ranges

| Source | Relevant 1-based PDF pages | Principal use |
|---|---|---|
| `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | 27, 32–36, 42–43, 48–50, 60, 63, 83–90, 109–111, 117–118, 121, 123–124, 127, 137–138, 292–296, 342–350, 363–366, 379–381, 388–389 | Bias, external/internal liquidity, FVG, MSS/displacement, ranges, OB, rejection block, timeframe refinement |
| `the-ict-handbook-v-1 1.pdf` | 7–10, 17, 20–22, 24–26, 29–30 | Liquidity, range sweep/MSS, FVG, OB, timing distinctions |
| `Smart Money Concept (SMC) Trading.pdf` | 6–7, 13–14, 21, 24–25, 29, 31, 36, 46, 49, 55–56, 64–65, 68, 70, 76, 81, 83, 86, 110, 112, 117, 119, 121, 150 | HTF zones, confirmation, continuation, liquidity, structure, timeframe precedence, entries/stops/targets |
| `EKINYZBB BOOTCAMP SERISI.pdf` | 4, 6–7, 12–13, 18–20 | FVG, PD arrays, displacement, timeframe ladder, no-trade and entry flow |
| `EKINYZBB ILERI SEVIYE ICT SERISI.pdf` | 5, 7–8, 10, 12 | DOL, hierarchy pairs, OB qualification, market cycle |
| `IPDA_-Market_Cycle.pdf` | 2–3, 15–16, 19 | Consolidation, expansion, retracement, reversal |
| `Mastering ict.pdf` | 6–19, 28, 34, 39–43 | Liquidity, dealing range, premium/discount, FVG/OB, PO3, order flow, neutral state |
| `Market Structure - Skatfx.pdf` | 3–10 | Trend and range structure; rendered pages control due bad text encoding |
| `One Setup For Life - Redeye.pdf` | 2–12 | Consolidated session-range sweep model; chart-only examples |
| `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf` | 3–12 | Prior directional expectation, manipulation, HTF FVG example, expansion |
| `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf` | 2–7 | False move, stop hunt, MSS, HTF-aligned reversal and continuation |
| `_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf` | 2–6 | Range boundary sweep, MSS/OB, weekly FVG reaction, no-direction state |
| `INDICES 8.30 PO3 Model Mr MatriX.pdf` | 1–6 | Supporting only: pre-existing bias, post-08:30 sweep/PD-array interaction and CISD/FVG entry |
| `PO3 Model (10 AM) Mr MatriX.pdf` | 1–4 | Supporting only: index-specific HTF array touch, stop hunt, LTF entry |

## 2. Page-referenced category A concept extraction

The table records the source’s rule, not a recommendation to implement it unchanged.

| ID | Concept and explicit rule | Source / page / section | TF | Preconditions | Confirmation | Invalidation or no-trade | Codability / ambiguity |
|---|---|---|---|---|---|---|---|
| A01 | Use HTF context before LTF execution; Daily/4H carry the principal directional information and LTF refines the setup. | `ICT 2022 Mentorship…`, pp. 121, 379, 389, “High Probability Daytrade Setups”; `EKINYZBB BOOTCAMP…`, p. 18 | Monthly/Weekly/Daily/4H → 1H/15m/5m/1m | Closed HTF structure and/or PD-array context | LTF setup aligned with HTF | Conflicting or unclear direction | Implementable with variants; exact parent/child precedence conflicts across sources |
| A02 | Explicit pairing is Monthly PD array→Daily structure, Weekly→4H, Daily→1H, and 4H→15m; another source states Daily order flow overrides 4H and 4H overrides 15m. | `EKINYZBB ILERI…`, pp. 7–8; `Smart Money Concept…`, p. 121 | Multi-TF | A parent TF condition exists | Child TF structure/reaction | Parent/child conflict unresolved | Requires user clarification before one hierarchy is selected |
| A03 | PD array is an umbrella for delivery arrays; FVG and OB can serve as HTF POIs and as lower-timeframe entry arrays. | `EKINYZBB BOOTCAMP…`, p. 7; `the-ict-handbook…`, pp. 22, 26 | HTF POI; LTF entry | A geometrically identified array | Context-appropriate reaction | Array violation depends on array type | Ready as taxonomy; individual validity is not |
| A04 | Basic FVG geometry is a three-candle imbalance with non-overlap between candle 1 and candle 3 wicks; it accompanies one-sided displacement. | `the-ict-handbook…`, p. 20; `ICT 2022 Mentorship…`, pp. 83–84; `EKINYZBB BOOTCAMP…`, p. 4 | Any; HTF preferred for context | Three closed candles | Geometric gap | Filled/violated treatment differs from formation | Ready for raw detection |
| A05 | A higher-probability/logical FVG is contextual: liquidity should be taken and MSS/displacement should accompany the move; bearish FVGs after BSL and bullish FVGs after SSL are emphasized. | `EKINYZBB BOOTCAMP…`, p. 4; `ICT 2022 Mentorship…`, pp. 86–89 | HTF or entry TF | Prior named liquidity and raw FVG | MSS/displacement in expected direction | No qualifying liquidity/reaction | Implementable as multiple variants; “important” liquidity is ambiguous |
| A06 | An FVG that is traded through becomes an inverse FVG, but the sources do not consistently specify wick versus close or full versus partial violation. | `EKINYZBB BOOTCAMP…`, p. 13; `the-ict-handbook…`, p. 21 | Any | Existing FVG | Trade/close through, depending source wording | Not consistently defined | Requires clarification |
| A07 | OB definitions vary: consecutive opposing candles before a move; the last opposing candle before impulse; or the last recent candle producing inefficiency and structure break. | `the-ict-handbook…`, pp. 24–25; `Mastering ict.pdf`, p. 16; `Smart Money Concept…`, p. 29 | Any, contextualized on HTF | Impulsive departure; some sources require structure break/inefficiency | Retest/reaction | Geometric invalidation not unified | Not safely codable as one detector until resolved |
| A08 | A high-probability OB is not used alone; it should occur at an important high/low with liquidity support, momentum reversal/structure evidence, and no major correction before retest. | `ICT 2022 Mentorship…`, pp. 342, 344–346; `EKINYZBB ILERI…`, p. 10 | HTF then LTF | Direction/narrative plus liquidity | Formation and later retest/reaction | Weak/no liquidity context or significant correction | Implementable with variants; “important,” “major,” and body/wick bounds need metrics |
| A09 | Liquidity pools include swing highs/lows, equal highs/lows, consolidations/ranges, session highs/lows, and prior day/week/month highs/lows; BSL lies above highs and SSL below lows. | `the-ict-handbook…`, pp. 7, 10; `Smart Money Concept…`, pp. 21, 24; `Mastering ict.pdf`, pp. 7–8 | Any | Prior observable level | Level is traded/swept, then reaction is evaluated | Liquidity presence alone is not an entry | Ready for objective level families; significance ranking is not |
| A10 | Liquidity is monitored, not traded by itself; after a pool is taken, wait for a reaction/shift before acting. | `Smart Money Concept…`, pp. 21, 76; `ICT 2022 Mentorship…`, pp. 27, 49 | HTF context or LTF entry | Named liquidity level is swept | Opposite MSS/CHoCH/CISD or displacement | No shift or continued acceptance beyond level | Implementable with confirmation variants |
| A11 | MSS is a break of the recent opposing swing; a reversal MSS should be energetic and leave displacement rather than only a wick/small candle. | `ICT 2022 Mentorship…`, pp. 48–49; `EKINYZBB BOOTCAMP…`, p. 7 | Confirmation TF | Liquidity/context plus identifiable swing | Body-led break with displacement | Wick-only raid or weak/no close | Implementable with variants; pivot and energy thresholds unresolved |
| A12 | One source confirms non-micro structure breaks only by candle-body close, while another describes MSS more generally as a break of the prior swing. | `Smart Money Concept…`, p. 110; `ICT 2022 Mentorship…`, p. 48 | 4H/15m versus 1m | Defined swing | Body close beyond swing on non-micro TF | Wick-only break | Implementable, but source conflict should be preserved as variants |
| A13 | Displacement is an aggressive, sharp, one-sided move that closes beyond a prior high/low and does not immediately return to the range. | `ICT 2022 Mentorship…`, p. 85; `EKINYZBB BOOTCAMP…`, pp. 6, 12 | Reaction/confirmation TF | Prior range or swing | Large/fast body-led expansion and structure close | Immediate retrace into origin/range or wick-only move | Requires calibrated research thresholds |
| A14 | POI touch alone is not sufficient in the stricter workflows: wait for a reaction and lower-timeframe structure confirmation before entry. | `EKINYZBB BOOTCAMP…`, pp. 19–20; `Smart Money Concept…`, pp. 56, 81, 86 | HTF POI → LTF | Price reaches/comes from HTF POI | Liquidity grab/rejection plus CHoCH/MSS/displacement | No LTF confirmation | Implementable with variants |
| A15 | A permissive SMC workflow says H4 zones determine direction/targets and price does not always have to wait at the POI; its checklist later says H4/Daily zones matter when price is reaching or reacting from them. | `Smart Money Concept…`, pp. 55, 150 | Daily/H4 → 15m | H4 zone/control state | Either control-based direction or actual reaction, depending passage | Opposing controlling zone may require confirmation | Internal source conflict; requires explicit D005 policy |
| A16 | Price can be modeled as alternating between external range liquidity and internal range liquidity/imbalance; after external liquidity is taken, an internal FVG may become the draw, and after internal rebalance, external liquidity may become the draw. | `ICT 2022 Mentorship…`, pp. 32–35; `Mastering ict.pdf`, pp. 13–14 | Monthly/Weekly/Daily/4H fractal ranges | Defined dealing range plus ERL/IRL | Reaction/displacement indicates the next draw | Opposite array fails to hold or range is misidentified | Implementable with variants; this is not the same as a fixed “PD first, sweep second” hierarchy |
| A17 | A dealing range is defined between a BSL and SSL event after both sides have been taken; premium is above its 50% midpoint and discount below. | `Mastering ict.pdf`, pp. 10–11 | Any relevant range | Both BSL and SSL have been taken | Correctly anchored range | Wrong/fractal-mismatched anchors | Implementable with anchor variants |
| A18 | Premium/discount is contextual, not a standalone direction rule: seek longs in discount and shorts in premium when broader order flow and arrays align. | `Mastering ict.pdf`, p. 11; `EKINYZBB BOOTCAMP…`, pp. 7, 19; `ICT 2022 Mentorship…`, p. 123 | HTF range with LTF refinement | Valid dealing range and directional context | PD-array reaction/confirmation | Opposing HTF context or unclear range | Implementable once range anchors are selected |
| A19 | A ranging/neutral market is price oscillating between defined boundaries without a clear trend, or trapped between opposing PD arrays without displacement breaking swing highs/lows. | `Market Structure - Skatfx.pdf`, pp. 9–10; `Mastering ict.pdf`, p. 43 | Context TF | Observable bounds/opposing arrays | Repeated containment and absent displacement break | Clean breakout/shift ends neutrality | Implementable with multiple research variants |
| A20 | Do not trade inside a higher-timeframe accumulation/range; wait for one boundary to be manipulated, then MSS/OB can frame movement toward the other side. | `_Range_Maniplasyonu…`, pp. 2–3, 6; `the-ict-handbook…`, p. 9 | HTF range → LTF | Defined range and boundary sweep | MSS plus entry array/OB | No shift, invalid risk, or price already extended | Implementable with variants |
| A21 | Consolidation is followed by expansion, not directly by retracement or reversal; after expansion, retracement, reversal, or renewed consolidation are possible. | `IPDA_-Market_Cycle.pdf`, pp. 2–3; `EKINYZBB ILERI…`, p. 12; `ICT 2022 Mentorship…`, pp. 137–138 | Fractal | Consolidation identified | Expansion away from range | “Consolidation” itself is not quantitatively defined | Requires a consolidation metric |
| A22 | Session highs/lows, including Asia and London, are liquidity references; a later session may sweep/reverse them or continue the existing move. | `ICT 2022 Mentorship…`, pp. 32, 50, 296; `One Setup For Life…`, pp. 2–3 | Intraday | Prior session range/high/low | Sweep plus MMXM/MSS/reaction | Immediate fade without confirmation is rejected | Implementable after session clocks and DST are specified |
| A23 | Judas/PO3 manipulation is a false move/stop hunt against an already anticipated direction before expansion; it is not presented as an independent source of HTF direction. | `_ICT_-_Judas_Swing…`, pp. 2, 5–7; `_Institutional_PO3…`, pp. 3–7; `Mastering ict.pdf`, p. 34 | HTF narrative → intraday | Pre-existing expected direction and consolidation/open reference | Stop hunt plus MSS/reaction | No prior narrative or no shift | Structurally implementable; all asset/time claims require XAU validation |
| A24 | The 08:30 material assumes a prior buy/sell-day narrative, identifies liquidity before the event, then seeks a shift and FVG/PD-array entry; it does not establish direction solely from the clock. | `ICT 2022 Mentorship…`, pp. 60, 63, 90, 117–118 | 15m context → 5m/LTF entry | Prior directional context and named liquidity | Post-event shift/displacement and entry array | No context, no shift, or no valid entry | Structural concept only; exact 08:30–09:00 window is user-defined and must be XAU-validated |
| A25 | The image-only 8:30 note explicitly says “if bias is bullish/bearish,” then use a post-08:30 sweep or PD-array tap and CISD/FVG; it is supporting, not sole authority. | `INDICES 8.30 PO3 Model Mr MatriX.pdf`, pp. 2–6 | Index example, 5m entry | Bias already exists | Sweep/tap plus CISD or FVG | Wrong/no bias | Supporting only; never XAU timing authority |
| A26 | The image-only 10:00 note requires a Daily/HTF PD-array tag, stop hunt at the index-specific 10:00 open, then 15m/5m/1m CISD/breaker entry. | `PO3 Model (10 AM) Mr MatriX.pdf`, pp. 2–4 | Daily→4H→15m/5m/1m | HTF array tag | Stop hunt plus LTF entry model | No HTF tag/stop hunt | Supporting structural sequence only; 10:00 timing prohibited for XAU transfer |
| A27 | Continuation entries are explicitly allowed after a confirmed change/flip or after an HTF zone break; New York may continue a London move. | `Smart Money Concept…`, pp. 49, 64; `_ICT_-_Judas_Swing…`, pp. 6–7; `ICT 2022 Mentorship…`, p. 296 | HTF/LTF | Established direction or confirmed shift | BOS/retest/continuation PD array | Structure breaks against the trend | Ready as a permitted setup family; entry details remain variant-dependent |
| A28 | Reversal entries require stronger evidence and are characterized as riskier: liquidity/manipulation, reaction, and structure shift are repeatedly required. | `IPDA_-Market_Cycle.pdf`, p. 19; `ICT 2022 Mentorship…`, pp. 48–49; `_Range_Maniplasyonu…`, p. 3 | HTF event → LTF shift | Extreme/POI/liquidity event | MSS/displacement/reaction | No shift or opposing order flow remains intact | Implementable with variants |
| A29 | A rejection block is formed by one or more long-wick candles at a swing where body-level liquidity is swept/exhausted. | `ICT 2022 Mentorship…`, pp. 363–364 | Any, HTF contextual | Swing and long rejection wick(s) | Failure to continue through the swept area | Acceptance/close through the rejection area not precisely defined | Requires measurable wick/body and invalidation thresholds |
| A30 | Stops are generally placed beyond the confirming swing or entry-zone/OB extreme; one checklist allows the latest swing body or origin-candle body. Targets are opposing liquidity, external range liquidity, or the next unmitigated opposing zone. | `EKINYZBB BOOTCAMP…`, p. 20; `Smart Money Concept…`, pp. 81, 86, 150; `ICT 2022 Mentorship…`, p. 346 | Entry TF; HTF target | Confirmed entry model | Entry at FVG/OB/zone | Stop/zone extreme breached | Implementable as explicit research variants; spread/buffer and wick/body policy unresolved |
| A31 | No-trade conditions include no clear direction/market intent, price between opposing arrays, consolidation without a boundary event, conflicting plausible directions, invalid risk, or a missed/overextended move. | `EKINYZBB BOOTCAMP…`, p. 19; `Mastering ict.pdf`, p. 43; `ICT 2022 Mentorship…`, pp. 295, 388 | All | Context assessment | None; abstention is the outcome | A later valid context event can release neutrality | Ready as a conservative gate after each term is measured |

### Coverage of the requested concepts

All requested concepts were found at least at a descriptive level except **Premarket High/Low as a named, source-defined construct**. “Strong reaction,” “clean displacement,” “significant liquidity,” “valid POI,” and exact invalidation thresholds remain discretionary.

- Higher-timeframe bias and hierarchy: A01–A02
- POI / PD arrays / FVG / OB / IFVG / rejection block: A03–A08, A29
- Liquidity pools, BSL/SSL, sweep/raid: A09–A10, A16–A17
- Reaction, displacement, MSS/CHoCH/CISD: A11–A15
- Premium/discount and dealing range: A17–A18
- Premarket High/Low: **not explicitly defined**
- Asia/London/session liquidity: A22
- Range/balanced conditions: A19–A21
- 08:30 timing/execution: A24–A26, with guardrail
- Manipulation, reversal, continuation: A23, A27–A28
- Entry, stop, targets, no-trade: A30–A31

## 3. Source-derived strategy flow

The most defensible shared flow is:

1. **Frame HTF order flow and the active dealing range.** Use a parent timeframe to identify structure, premium/discount, external liquidity, and internal PD arrays.
2. **Locate a contextual event, not merely a shape.** Candidate events are an HTF FVG/OB reaction, a named liquidity sweep, or a range-boundary manipulation.
3. **Observe the reaction.** A wick-only touch is insufficient in the stricter sources. Look for body-led displacement and a break/shift of an opposing swing.
4. **Refine on a child timeframe.** Use MSS/CHoCH/CISD and an entry PD array/zone in the HTF-consistent direction.
5. **Invalidate beyond the confirming structure/zone.** Target the next opposing liquidity pool, external range liquidity, or unmitigated opposing zone.
6. **Abstain when context is neutral or conflicted.** No clear HTF order flow, price trapped between arrays, range interior without a boundary event, weak/no displacement, or invalid risk means no trade.

This is a source synthesis, not a single verbatim algorithm. Sources differ on exact timeframe pairing, OB geometry, and whether H4 control can provide direction before a same-day H4 POI touch.

## 4. Comparison with the eight category B user rules

| # | User-defined rule (B) | Source comparison | Result |
|---:|---|---|---|
| B1 | Establish directional context from an HTF POI or liquidity event. | A01, A10, A14, A16, A23 support context from HTF arrays/order flow/liquidity plus reaction. | **Agrees in principle.** Do not reduce HTF context to POI geometry alone. |
| B2 | Use Weekly, Daily, 4H, and optionally 1H context. | A01–A02 use these TFs, but sources also use Monthly and paired parent→child mappings. SMC explicitly says Daily overrides 4H and 4H overrides 15m. | **Partially explicit; exact hierarchy is user-defined.** |
| B3 | Valid FVGs and OBs are candidate HTF POIs. | A03–A08 explicitly support FVG/OB as HTF POIs. | **Confirmed agreement.** “Valid” remains unresolved. |
| B4 | Establish bias only after a valid reaction from the POI. | A10, A14 support reaction/shift confirmation. A15 contains a competing H4-control workflow that does not always require waiting at the POI. | **Strongly supported by stricter sources, but not universal.** Conservative D005 scope should keep the reaction gate. |
| B5 | If no suitable PD array exists, wait for an HTF liquidity sweep and reaction. | Sources support sweep+reaction, but A16 describes ERL/IRL alternation, not “liquidity only if no PD array.” | **User-defined priority; not explicitly source-prescribed.** |
| B6 | If balanced/ranging and HTF context is unclear, use PMH/PML sweeps as intraday manipulation clues. | A19–A22 support range/session-boundary sweeps and confirmation. No authoritative source defines PMH/PML or grants it this fallback priority. | **PMH/PML portion is user-defined.** Treat only as a research feature/manipulation clue, never standalone bias. |
| B7 | Use 08:30–09:00 NY mainly for execution, not standalone direction. | A24–A26 assume prior bias/narrative and use the event for sweep/shift/entry. Exact sources often discuss broader/different windows and index examples. | **Structural agreement; exact XAUUSD window requires validation.** |
| B8 | After context/manipulation, seek LTF confirmation and PD-array entry in expected direction. | A11–A14, A23–A24, A27–A30 explicitly support this sequence. | **Confirmed agreement.** Exact confirmation and array definitions remain variants. |

## 5. Rule-priority analysis

### Proposed hierarchy

1. HTF FVG or OB interaction and confirmed reaction.
2. HTF liquidity sweep and confirmed reaction when no usable PD array exists.
3. PMH/PML sweep when balanced and HTF context is unresolved.
4. Neutral/no trade otherwise.

### Finding

The hierarchy is **not explicitly stated as a universal priority list**.

- Step 1 is well supported as one high-quality path.
- Step 2 is supported as an event path, but the “only when no usable PD array exists” condition is category B. The source model more often alternates between external liquidity and internal imbalance according to the active dealing range.
- Step 3 is not category A as written. Sources support range/session-high/low sweeps, not a named PMH/PML fallback bias mechanism.
- Step 4 is explicit and strongly supported.

### Premarket role

From the authoritative set, a session/premarket boundary sweep is best classified as a **manipulation or liquidity clue requiring confirmation**, not an independent bias engine. The image-only 8:30 note also begins with “if the bias is bullish/bearish,” which confirms that timing/sweep follows a prior narrative.

### Must an HTF POI be touched before the trading day?

No universal source rule requires the touch to occur before the calendar/trading day. Stricter workflows require price to reach or react from the HTF POI before an entry is valid; `Smart Money Concept (SMC) Trading.pdf` p. 55 also permits H4 zones to set direction/targets without waiting for the POI, while p. 150 emphasizes reaching/reacting. D005 should not assume a pre-day touch requirement.

### Can bias form during 08:30–09:00?

The sources allow new evidence during an event window to **confirm, reject, or leave unresolved** a prior directional hypothesis. They do not support creating full HTF bias from the clock alone. A D005 research state may transition from neutral to confirmed during the window only if an already defined HTF/range event and reaction occur; this is an interpretive candidate, not an explicit timing rule.

### Can intraday override HTF?

No source supports a bare PMH/PML or clock event overriding a clear, still-valid HTF condition. Intraday failure can invalidate a proposed entry or show the HTF thesis has not confirmed. Actual HTF invalidation must be defined on the HTF/parent structure; a lower-TF counter-signal should normally cause abstention rather than reverse the HTF direction automatically.

### Timeframe conflicts

The one explicit precedence statement is Daily > 4H > 15m (`Smart Money Concept…`, p. 121). Other sources use parent/child pairs rather than a single total order. The safest D005 behavior is **abstention on parent/child directional conflict**, with conflict states logged for research, until the user chooses a precedence policy.

### Reversal and continuation

Both are allowed. Reversals require a contextual extreme/liquidity/POI event plus stronger displacement/shift confirmation. Continuations are allowed after order flow is established, after a BOS/retest or zone break, or when New York continues a prior session move.

## 6. Conflict matrix

| Conflict | Competing definitions / pages | Research implication | Resolution options |
|---|---|---|---|
| OB geometry | Consecutive opposing candles: `the-ict-handbook…` pp. 24–25. Last opposing candle: `Mastering ict.pdf` p. 16 and `ICT 2022 Mentorship…` p. 350. Last recent candle creating inefficiency/structure break: `Smart Money Concept…` pp. 25, 29. | Different detectors produce different zones, widths, touches, and outcomes. | Implement named variants only: `consecutive_block`, `last_opposing_candle`, `inefficiency_break_origin`; do not select a default without approval. |
| OB conceptual framing | Handbook p. 25 says OB is not simply supply/demand; ICT p. 350 describes OB as supply/demand; SMC pp. 25–31 uses supply/demand-zone logic. | Terminology can conceal materially different geometry. | Keep `ict_order_block` and `smc_supply_demand_zone` as separate concepts. |
| FVG validity | Raw 3-candle gap: Handbook p. 20 / ICT pp. 83–84. “Logical/high probability” adds prior liquidity and MSS: Bootcamp p. 4 / ICT pp. 86–89. | A single boolean “valid” would mix geometry with context. | Detect raw geometry first; attach separate quality flags/variants. |
| IFVG invalidation | Handbook p. 21 says broken/violated FVG; Bootcamp p. 13 uses a candle close through. | Wick-through versus close-through changes signals. | Research `wick_violation` and `body_close_violation`; no default yet. |
| MSS/structure break | ICT pp. 48–49 focuses on energetic break of prior swing. SMC p. 110 requires candle-body close except 1m/seconds. Bootcamp p. 7 contrasts wick raid with body MSS. | Pivot, close rule, and energy filter alter confirmation timing. | Require body close for conservative baseline; retain pivot/energy thresholds as variants, subject to approval. |
| HTF zone touch | SMC p. 55: H4 zones set direction and “don’t have to wait for these POIs.” SMC p. 150: care about H4/Daily zones when price reaches/reacts; Bootcamp pp. 19–20 waits for reaction. | Determines whether direction can exist before a POI event. | Conservative reaction-gated variant; separate control-state variant; user must approve any non-reaction bias. |
| Timeframe precedence | Advanced pp. 7–8: Monthly→Daily, Weekly→4H, Daily→1H, 4H→15m. SMC p. 121: Daily > 4H > 15m. ICT pp. 379, 389: Daily/4H most important, H1 for liquidity. | A total order is not uniform across sources. | Parent-child pair engine, explicit Daily override, or strict agreement/abstention. |
| Proposed PD→liquidity fallback | User B5 says sweep only if no suitable PD array. ICT pp. 32–35 and Mastering pp. 13–14 use ERL/IRL alternation based on current range state. | Fixed priority may misrepresent the source state machine. | Test both as named research variants; do not make user hierarchy a source fact. |
| PMH/PML fallback | User B6 names PMH/PML. Sources identify session highs/lows generally (Handbook p. 10; SMC p. 24; ICT p. 32) but do not define Premarket clock or priority. | Boundary values depend entirely on clock, feed, DST, and session definition. | User supplies precise PMH/PML interval; research-only feature; abstain if undefined. |
| Range definition | Skatfx pp. 9–10: bounded sideways price/no direction. Mastering p. 43: between opposing arrays/no displacement break. Range Manipulation pp. 2–3: HTF accumulation with boundaries. Mastering p. 10 defines a dealing range only after both BSL and SSL are taken. | “Range,” “consolidation,” and “dealing range” are not synonyms. | Store distinct states: `sideways_range`, `accumulation`, `dealing_range`, `neutral_between_arrays`. |
| Session clocks/timezones | Handbook pp. 29–30 separates forex and index timing. Redeye pp. 4–5 uses RTH/09:30. Range p. 6 uses 09:30. Supporting notes use UTC-4/08:30/10:00. | Naive clock reuse creates instrument/session leakage and DST errors. | Use IANA `America/New_York`, instrument-specific research windows, and prohibit index timing transfer to XAUUSD. |
| Reversal versus continuation | Range/Handbook emphasize boundary sweep and reversal; SMC pp. 49, 64 and Judas pp. 6–7 explicitly allow continuation. | A reversal-only engine would omit sourced setups. | D005 should model `reversal`, `continuation`, and `neutral` as separate outcomes. |
| Stop placement | Bootcamp p. 20 permits latest swing body/origin-candle body; SMC pp. 81, 86 uses zone/swing extreme; ICT p. 346 uses OB extreme. | Body versus wick extreme changes risk and labels. | Separate named stop variants; no production default change. |

No conflict above is silently resolved.

## 7. Missing-definition matrix

| Missing or discretionary definition | Source status | Why it blocks a single deterministic rule | Category C research candidates |
|---|---|---|---|
| Valid POI | FVG/OB types are sourced; universal validity is not | Geometry, freshness, context, mitigation, and age are conflated | Raw geometry + freshness + prior sweep + displacement/MSS flags |
| Strong reaction / respecting an array | Repeatedly required, not measured | Minimum excursion and close behavior unspecified | Close back through proximal edge; N-bar excursion ≥ k×ATR; no close beyond distal edge |
| Clean displacement | Described as fast/aggressive/body-led | No size, speed, or retrace threshold | Body/range percentile; ≥ k×ATR; break of pivot by close; origin not retraced within N bars |
| Significant liquidity | Liquidity families are explicit; significance is not | Equal highs, session highs, PDH/PWH, etc. may conflict | Rank by TF, touches, age, equal-level tolerance, and distance |
| Valid/invalid OB | Conflicting geometry and invalidation | Detectors produce incompatible zones | Three named OB variants plus body/wick invalidation variants |
| Valid/invalid FVG | Raw geometry clear; contextual validity and IFVG transition differ | One boolean loses evidence | `raw_fvg`, `liquidity_qualified`, `mss_qualified`, `ifvg_close`, `ifvg_wick` |
| MSS pivot | Prior “short-term” swing not algorithmically specified | Swing sensitivity changes every confirmation | Fixed left/right fractal, zigzag/ATR, or structure hierarchy variants |
| Consolidation/ranging | Multiple descriptive definitions | Width, duration, volatility, and boundaries unspecified | N-bar normalized width; ADX/efficiency ratio; overlapping-bars ratio; dual-boundary touches |
| Balanced market | Equilibrium/neutral discussed, no universal state | May mean 50% pricing, sideways range, or opposing arrays | Separate `at_equilibrium`, `sideways`, and `opposing_arrays` flags |
| Premarket High/Low | Not defined in the authoritative set | Clock, DST, holidays, and feed determine levels | User-specified New York half-open interval; retain as research-only |
| HTF conflict | One source gives partial precedence; no complete rule | Weekly/Daily/4H/1H can disagree | Strict agreement; parent veto; weighted score; abstention baseline |
| POI-touch timing | Sources conflict | Bias before touch versus only after reaction changes state machine | `control_state` versus `reaction_confirmed` states |
| 08:30–09:00 macro behavior on XAUUSD | Not proven by PDFs | Index/forex educational examples are not XAU statistics | Event study on XAUUSD only; keep clock feature disabled outside research |
| No-trade release | No exact timeout/expiry | Neutral state may persist indefinitely | Release only on new HTF close/event; POI expiry by bars/mitigation; daily reset variant |

Any candidate above is category C, not source fact.

## 8. Codability assessment

| Major concept | Assessment | Rationale |
|---|---|---|
| Raw BSL/SSL at prior highs/lows, equal highs/lows, session and D/W/M extremes | **Ready to implement** in research | Objective once tolerance and sessions are configured |
| Raw three-candle FVG | **Ready to implement** | Consistent geometry across core sources |
| Premium/discount after a selected dealing range | **Ready to implement** | Midpoint is objective; range anchor is a separate variant |
| Raw swing trend / body-close structure break | **Implementable with multiple research variants** | Pivot algorithm and micro-TF exception vary |
| Context-qualified FVG | **Implementable with multiple research variants** | Prior sweep/MSS/displacement filters can be enumerated |
| OB | **Requires user clarification** for a default; variants are implementable | Core definitions conflict |
| Liquidity sweep/raid | **Implementable with multiple research variants** | Wick-through/reclaim, close-through, and tolerance differ |
| Reaction/displacement/MSS | **Implementable with multiple research variants** | Requires explicit measurable thresholds |
| HTF hierarchy | **Requires user clarification** | Sources provide incompatible/partial precedence models |
| PMH/PML fallback | **Requires user clarification** | Not source-defined; session clock absent |
| 08:30–09:00 XAUUSD behavior | **Not safely codable as a rule before statistical validation** | Source timing evidence is not XAU-specific |
| Range/balanced state | **Implementable with multiple research variants** | Several distinct source meanings must not be merged |
| Reversal and continuation classification | **Ready to implement as labels/research outcomes** | Both are explicitly allowed |
| Stops/targets | **Implementable with multiple research variants** | Source alternatives are explicit but not unified |
| Automatic production bias | **Not safely codable at this stage** | Audit approval, definitions, research validation, and tests are still required |

## 9. Questions that genuinely require user clarification

1. **HTF conflict policy:** should D005 use strict agreement/abstention, explicit Daily-over-4H precedence, or the parent→child pairs (Monthly→Daily, Weekly→4H, Daily→1H, 4H→15m)? The conservative recommendation is parent veto plus abstention on unresolved conflict.
2. **OB definition:** should research implement all three named variants, or is one intended as the canonical D005 definition? No source-consistent single default exists.
3. **Premarket High/Low:** what exact `America/New_York` half-open interval defines PMH/PML for XAUUSD, and should it remain a research-only clue that can never override valid HTF context?
4. **Reaction confirmation:** should the conservative baseline require a candle-body MSS plus displacement after the HTF event, and on which child timeframe for Weekly, Daily, 4H, and 1H POIs?
5. **Bias before POI touch:** may an HTF control/order-flow state be logged as a provisional bias before touch, or must D005 expose only `neutral`, `candidate`, and `reaction_confirmed` with no actionable direction until reaction?
6. **Exact XAUUSD timing scope:** confirm that 08:30–09:00 New York is a research observation/execution window whose effects must be estimated from XAUUSD data, not a deterministic source rule.

These are materially outcome-changing choices. Other thresholds can be exposed as named research variants without selecting a production default.

## 10. Recommended scope for D005

D005 should remain an **isolated research context engine**, disabled from production and unable to change strategy defaults.

Recommended first scope:

1. Create immutable, closed-bar HTF features for raw swings, prior D/W/session levels, raw FVGs, and separately named OB variants.
2. Represent context as evidence states rather than one opaque bias: `neutral`, `candidate_poi`, `candidate_liquidity_event`, `reaction_confirmed`, `conflict`, `invalidated`.
3. Preserve the source distinction between raw geometry and contextual qualification.
4. Implement reaction/MSS/displacement as configurable research variants with no chosen production default.
5. Model reversal and continuation separately.
6. Treat PMH/PML and 08:30–09:00 only as research features behind an `America/New_York` clock and DST-safe configuration.
7. Default to neutral/no-trade whenever parent/child context conflicts or required definitions are absent.
8. Emit provenance for every state: source-rule ID, TF, event time, prerequisites, confirmation, invalidation, and variant name.
9. Backtest all timing claims independently on XAUUSD with closed-bar, no-look-ahead logic.
10. Do not connect outputs to production strategy behavior until the audit is approved, user choices are recorded, tests pass, and research evidence is separately reviewed.

### Explicitly out of scope until approval

- Production bias or entry behavior.
- A canonical OB detector.
- A PMH/PML bias override.
- Any deterministic 09:30, 10:00, index PO3, or copied index-session behavior on XAUUSD.
- Automatic promotion of research winners to production defaults.
- Any use of future bars, same-bar hindsight, or unclosed HTF candles.

## Completion record

- Files changed by this audit: `docs/D005_STRATEGY_SOURCE_AUDIT.md`, `research/context_engine/source_rule_catalog.json`
- Tests added: none; documentation/catalog task only
- Validation executed: 43-file existence/open/page-count/hash audit; page-indexed extraction for 14 selected sources; rendered visual inspection of relevant pages; JSON parse/schema checks
- Assumptions: page references mean 1-based PDF pages; 12 prioritized sources are authoritative; two MatriX notes are supporting only
- Risks: educational sources are internally inconsistent and discretionary; none constitutes XAUUSD statistical validation
- Acceptance status: source audit deliverables complete; D005 implementation intentionally not started
- Recommended next action: review this audit and answer the six material clarification questions before authorizing D005

