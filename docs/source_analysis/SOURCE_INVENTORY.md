# Source Inventory

Scope: lightweight inventory of all PDFs in `docs/raw_sources/`. This pass used filename, `pdfinfo` page counts, hashes, first pages, text extractability, table-of-contents signals, and targeted keyword search. It intentionally did not deeply parse every PDF.

## Inventory

| # | Source | Pages | Source type | Main topics | Market focus | Relevance / deeper-read decision |
|---|---:|---:|---|---|---|---|
| 1 | `0934380406_Trading_Secrets_of_the_Inner_Circle_Goodwin_1997_12_01.pdf` | 97 | old trading manual / promotional scan | stock/options timing, inner-circle framing | stocks | Low. Rejected; not SMC/ICT, dated, promotional front matter. |
| 2 | `Advanced Algorithmic Trading - Michael L. Halls.pdf` | 509 | quantitative methodology | time-series modeling, ML classifiers, backtest/infrastructure concepts | multi-market | Partial. Useful only for future engineering methodology, not strategy knowledge. |
| 3 | `Artificial Intelligence in Finance.pdf` | 477 | AI/finance textbook | neural nets, RL, statistical/economic inefficiency | multi-market | Partial. Future ML research only; not SMC source. |
| 4 | `COT LW 1.pdf` | 3 | short translated lesson | COT report, commercials, COT index examples including gold | futures/gold | Partial. Useful HTF context, promotional and not execution-ready. |
| 5 | `CRT Model Mr matriX.pdf` | 10 | image-only note | likely CRT model | unknown | Rejected for this phase; text not extractable and no deterministic content observed. |
| 6 | `DREYKO_NOTES_2025_Lecture_Series_Making_Money_With_SMC_Concepts.pdf` | 18 | personal lecture notes | opening-range gap, FVG EQ, ORG fib levels, MSB | indices/RTH | Partial. Specific and index-timing dependent. |
| 7 | `Deep Learning for Finance.pdf` | 362 | ML/finance textbook | deep learning, financial prediction, macro examples | multi-market | Partial. Future ML research only; not strategy knowledge. |
| 8 | `EKINYZBB BOOTCAMP SERISI.pdf` | 20 | conceptual education notes | BOS, MSS, liquidity, FVG, IFVG, breaker, entry checklist | mostly FX/ICT | Core. High density of programmable SMC concepts. |
| 9 | `EKINYZBB ILERI SEVIYE ICT SERISI.pdf` | 12 | advanced ICT notes | PO3, failure swing, external/internal liquidity, order blocks | ICT/multi-market | Core. Strong HTF bias concepts, but some discretionary claims. |
| 10 | `ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf` | 405 | translated mentorship/reference | liquidity, FVG, BSL/SSL, killzones, Judas, weekly profiles, silver bullet | mostly indices/forex | Core. Broad reference and glossary; must filter index-specific timings. |
| 11 | `ICT Ekolünde.pdf` | 4 | short personal note | opening gap, liquidity void, BSL/SSL around gaps | indices/opening gaps | Partial. Useful terminology only. |
| 12 | `INDICES 8.30 PO3 Model Mr MatriX.pdf` | 7 | image-only note | likely index 8:30 PO3 | indices | Rejected for XAUUSD automation; image-only and index-specific. |
| 13 | `IPDA_-Market_Cycle.pdf` | 22 | conceptual education | accumulation, expansion, retracement, reversal, COT mention | multi-market | Core. Compact market-cycle source; not directly executable without formalization. |
| 14 | `Insider'ların_Sırlarıyla_Hisse_Senedi_ve_Emtia_Ticareti_COT_Raporunun.pdf` | 52 | translated COT excerpt/book | commercials, open interest, COT definitions | stocks/commodities | Redundant. COT book content covered better by the full English source and short gold lesson. |
| 15 | `Larry Williams Forecast 2026.pdf` | 128 | annual forecast | macro/cycles/2026 predictions | stocks/macro | Rejected. Time-bound forecast, not deterministic source. |
| 16 | `MMXM Trader's executions 2023 .pdf` | 144 | trade examples / image-only | MMXM executions | unknown | Redundant/example-only. Exact duplicate of Turkish execution file and not text-readable. |
| 17 | `MMXM Trader's işlem örneği 2023  (1).pdf` | 144 | trade examples / image-only | MMXM executions | unknown | Redundant/example-only. Exact duplicate of English-named execution file. |
| 18 | `Market Structure - Skatfx.pdf` | 28 | conceptual education | basic market structure, HH/HL/LH/LL | FX/multi-market | Supporting. Useful basics, lower authority than ICT/SMC sources. |
| 19 | `Mastering ict.pdf` | 49 | reference handbook | liquidity, dealing range, P/D, OB, FVG, breaker, MMXM | ICT/multi-market | Supporting. Clear definitions, but secondary and partly generic. |
| 20 | `Michael Jenkins - The Geometry of Stock Market Profits.pdf` | 161 | technical-analysis book | geometry, cycles, angles | stocks | Rejected. Too subjective and unrelated to SMC implementation. |
| 21 | `Michael_McDonald_Predict_Market_Swings_with_Technical_Analysis.pdf` | 220 | technical-analysis book | market swings, Dow/Elliott style concepts | stocks | Rejected for this KB. Generic, not liquidity/SMC programmable enough. |
| 22 | `One Setup For Life - Redeye.pdf` | 12 | focused setup note | session highs/lows, Asia/London/NY ranges, ORG | indices/forex sessions | Supporting. Mechanically useful as session-range concept; not full model. |
| 23 | `Opening Range GAP - DREYKO.pdf` | 18 | personal lecture notes | opening range gap | indices/RTH | Redundant. Near-duplicate of DREYKO notes. |
| 24 | `PO3 Model (10 AM) Mr MatriX.pdf` | 5 | image-only note | 10 AM PO3 model | likely indices | Rejected. Image-only and time-window specific. |
| 25 | `Smart Money Concept (SMC) Trading.pdf` | 167 | strategy/reference guide | liquidity, imbalance, supply/demand, CHoCH, structure, checklist | FX/SMC | Core. Strong execution workflow, but terminology conflicts with ICT OB definitions. |
| 26 | `Successful Algorithmic Trading - Michael L. Halls.pdf` | 208 | quantitative methodology | strategy research, backtesting, costs, infrastructure | multi-market | Partial. Future engineering methodology only. |
| 27 | `Sunu 16.pdf` | 12 | setup note | same as Redeye session setup | sessions | Redundant. Exact duplicate of `One Setup For Life - Redeye.pdf`. |
| 28 | `Trade Stocks and Commodities With the Insiders.pdf` | 224 | COT book copy | COT, commercials, open interest | commodities/stocks | Redundant. Similar/full duplicate of primary COT book. |
| 29 | `Trade_Stocks_Commodities_with_the_Insiders_Secrets_of_the_COT_Report.pdf` | 224 | reference book | COT report, commercials, COT index, open interest | commodities/stocks | Supporting. Useful for weekly futures context; not intraday execution. |
| 30 | `Unlocking Success in ICT 2022 Mentorship - Lumitrader-1.pdf` | 435 | image-only mentorship copy | ICT 2022 | ICT | Redundant. Exact duplicate of `Unlocking Success in ICT 2022.pdf`; text version exists separately. |
| 31 | `Unlocking Success in ICT 2022.pdf` | 435 | image-only mentorship copy | ICT 2022 | ICT | Redundant. Exact duplicate of Lumitrader copy; prefer text-readable 405-page ICT translation. |
| 32 | `_ICT_-_Judas_Swing__Manipulation_Series_(Ep.5).pdf` | 11 | personal lecture / transcript | Judas Swing, MMXM, session false move, MSS | ICT/sessions | Supporting. Good concept source, needs time/market adaptation. |
| 33 | `_ICT_-_Market_CYCLE__Manipulation_Series_(Ep.3).pdf` | 12 | personal lecture / transcript | market cycle, COT, Bitcoin cycle | crypto/ICT | Partial. Mostly crypto-specific; use only for cycle intuition. |
| 34 | `_ICT_SMT_Nedir_Korelasyon_Nasl_Yorumlanr_Manipulation_Series_Ep.pdf` | 8 | personal lecture / transcript | SMT, correlated pairs, XAU-XAG example, FVG preservation | crypto/indices/FX/metals | Supporting. Important but not implementation-ready without pair rules. |
| 35 | `_Institutional_PO3_Nedir__Manipulation_Series_(Ep.2).pdf` | 15 | personal lecture / transcript | PO3, open/manipulation/expansion, ES examples | indices/ICT | Supporting. Good PO3 source, index-specific examples. |
| 36 | `_Maniplasyon_Nedir_Piyasalar_Neden_Maniplasyon_zerine_Kuruludur.pdf` | 13 | personal lecture / transcript | manipulation, OB, FVG, volume imbalance | ICT/general | Partial. Useful narrative, low determinism. |
| 37 | `_Maniplasyon_Stratejisi_ile_aldm_ilem_2000_Manipulation_Series_Ep.pdf` | 8 | trade example / transcript | BTC trade, daily FVG EQ, macro timing, stop at high | crypto | Partial/example-only. Do not generalize rules without tests. |
| 38 | `_Market_Maker_Model_Nedir_10_000_payoutu_mmxm_ve_maniplasyon_teknikleri.pdf` | 14 | personal interpretation / trade example | MMXM, PD arrays, FVG, breaker, targets | mixed | Partial. Useful phase vocabulary; promotional/example-heavy. |
| 39 | `_Range_Maniplasyonu_Nasl_Kullanlr_Manipulation_Series_Ep_4.pdf` | 7 | personal lecture / transcript | range manipulation, weekly FVG, MSS, range high/low | indices/ICT | Supporting. Useful for range workflow; needs objective rules. |
| 40 | `_Yln_eyrekleri_nasl_yorumlanmal_2025_Bitcoin_Tahminlerim_HTF_Bias.pdf` | 8 | market-specific forecast / transcript | yearly quarters, Bitcoin HTF bias | crypto/Bitcoin | Partial. Research-only; not directly transferable. |
| 41 | `tarıkabiönemlinotlar (1).pdf` | 20 | image-only notes | unknown | unknown | Rejected. Text not extractable and content cannot be evaluated reliably. |
| 42 | `the-ict-handbook-v-1 1.pdf` | 37 | reference handbook | liquidity, MSS/S.MSS, FVG, OB, killzones, silver bullets | ICT/forex/indices | Core. Compact and highly readable; good future first read. |
| 43 | `xx_williams_larry_r_inner_circle_workshop_seminar_manual_pr_dd4.pdf` | 89 | commodity workshop manual | commodity seasonals, COT-like framing, old trading rules | commodities | Partial. Research-only; not direct SMC implementation. |

## Immediate Duplicates / Near-Duplicates

- Exact duplicate: `MMXM Trader's executions 2023 .pdf` and `MMXM Trader's işlem örneği 2023  (1).pdf`.
- Exact duplicate: `Unlocking Success in ICT 2022 Mentorship - Lumitrader-1.pdf` and `Unlocking Success in ICT 2022.pdf`.
- Exact duplicate: `One Setup For Life - Redeye.pdf` and `Sunu 16.pdf`.
- Near duplicate: `DREYKO_NOTES_2025_Lecture_Series_Making_Money_With_SMC_Concepts.pdf` and `Opening Range GAP - DREYKO.pdf`.
- Redundant COT copies: `Trade_Stocks_Commodities_with_the_Insiders_Secrets_of_the_COT_Report.pdf`, `Trade Stocks and Commodities With the Insiders.pdf`, and the Turkish excerpt.
