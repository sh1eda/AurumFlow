#!/usr/bin/env python3
"""Regenerate the curated event-study research registers without extra tools."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable, Sequence


SOURCE_HEADER = (
    "source_id",
    "source_title",
    "author_or_institution",
    "publication_date",
    "source_type",
    "url",
    "concepts_supported",
    "market_studied",
    "time_period_studied",
    "data_frequency",
    "main_result",
    "important_limitations",
    "source_quality_tier",
)

SOURCE_ROWS = (('S01',
  'Schedule of Selected Releases 2026',
  'U.S. Bureau of Labor Statistics',
  '2026-03-10 (last modified)',
  'Official release calendar',
  'https://www.bls.gov/schedule/2026/home.htm',
  'Official Eastern Time release timestamps; 08:30 CPI, PPI and Employment Situation; 10:00 JOLTS '
  'and other releases',
  'U.S. macroeconomic data',
  '2026 schedule',
  'Event timestamps',
  'Confirms that important BLS releases are scheduled at both 08:30 and 10:00 ET and that the '
  'calendar uses Eastern Time.',
  'Current-year schedule only; revisions and shutdown-related changes require a point-in-time '
  'calendar archive.',
  'Tier 1'),
 ('S02',
  'Release Schedule',
  'U.S. Bureau of Economic Analysis',
  '2026-07-16 (last modified)',
  'Official release calendar',
  'https://www.bea.gov/news/schedule',
  'Official release timestamps for GDP, personal income/outlays/PCE and trade',
  'U.S. macroeconomic data',
  'Current 2026 schedule',
  'Event timestamps',
  'Shows major BEA releases, including GDP and Personal Income and Outlays, commonly scheduled for '
  '08:30 ET.',
  'Live schedule can change; historical event-study use requires archived dates and original '
  'release times.',
  'Tier 1'),
 ('S03',
  'U.S. Census Bureau Economic Indicator Release Schedule: List View',
  'U.S. Census Bureau',
  '2026',
  'Official release calendar',
  'https://www.census.gov/economic-indicators/calendar-listview.html',
  '08:30 durable goods, retail sales and housing starts; 10:00 new-home sales, construction '
  'spending and inventories',
  'U.S. macroeconomic data',
  '2026 schedule',
  'Event timestamps',
  'Establishes that 10:00 ET contains genuine scheduled information arrivals as well as 08:30 '
  'releases.',
  'Current calendar is not a surprise database and may contain rescheduled releases; archive '
  'snapshots are needed.',
  'Tier 1'),
 ('S04',
  'ISM PMI Reports',
  'Institute for Supply Management',
  'n.d.; accessed 2026-07-17',
  'Official methodology/release page',
  'https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/',
  '10:00 ET Manufacturing and Services PMI release timing; survey construction',
  'U.S. manufacturing and services',
  'Current methodology',
  'Monthly event timestamps',
  'Manufacturing PMI is released on the first business day at 10:00 ET; ISM describes '
  'industry-weighted survey panels.',
  'Not a historical surprise series; ISM is a private association rather than a government agency.',
  'Tier 1'),
 ('S05',
  'US Consumer Confidence',
  'The Conference Board',
  'n.d.; accessed 2026-07-17',
  'Official methodology/release page',
  'https://www.conference-board.org/topics/consumer-confidence/',
  '10:00 ET Consumer Confidence release timing',
  'U.S. household survey',
  'Current methodology',
  'Monthly event timestamps',
  'The Conference Board states that the Consumer Confidence Index is published at 10:00 ET.',
  'Historical forecast, actual and revision vintages are not supplied on this public landing page.',
  'Tier 1'),
 ('S06',
  'Meeting Calendars and Information',
  'Board of Governors of the Federal Reserve System',
  'n.d.; accessed 2026-07-17',
  'Official central-bank calendar',
  'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
  'FOMC meeting dates and policy-statement documentation',
  'U.S. monetary policy',
  'Historical and current meetings',
  'Event timestamps',
  'FOMC decisions are separately timed information events and should not be mixed with the '
  '08:30/09:30 study without controls.',
  'FOMC statements are generally 14:00 ET, outside the requested morning window; unscheduled '
  'speeches still require a separate calendar.',
  'Tier 1'),
 ('S07',
  'Nasdaq Systems: Hours of Operation',
  'Nasdaq',
  '2026',
  'Exchange session documentation',
  'https://www.nasdaqtrader.com/content/technicalsupport/nasdaq_sys_hours.pdf',
  '09:30-16:00 ET Nasdaq market hours; extended system hours',
  'Nasdaq equities and indexes',
  'Current exchange specification',
  'Session timestamps',
  'Confirms that 09:30 ET is the formal U.S. cash-equity market open while Nasdaq systems operate '
  'before it.',
  'Does not show that NQ futures reverse at 09:30 or that other assets inherit an edge.',
  'Tier 1'),
 ('S08',
  'Trading Information',
  'New York Stock Exchange',
  'n.d.; accessed 2026-07-17',
  'Exchange session and auction documentation',
  'https://www.nyse.com/trade/trading-information',
  '09:30 ET core open auction; pre-opening order entry; 09:30-16:00 core session',
  'NYSE cash equities',
  'Current exchange specification',
  'Session timestamps',
  'Confirms that a concentrated opening auction occurs at 09:30 ET for cash equities.',
  'Cash-equity auction mechanics do not apply directly to spot gold or continuously traded COMEX '
  'gold futures.',
  'Tier 1'),
 ('S09',
  'Gold Futures and Options Fact Card',
  'CME Group / COMEX',
  '2026',
  'Exchange contract documentation',
  'https://www.cmegroup.com/trading/metals/files/fact-card-gold-futures-options.pdf',
  'GC contract size, tick, physical settlement and near-round-the-clock Globex trading hours',
  'COMEX Gold futures (GC)',
  'Current contract specification',
  'Contract/session specification',
  'GC trades from Sunday through Friday with only a daily maintenance break, so gold is already '
  'active before 09:30 ET.',
  'Product documentation is not evidence of an intraday return anomaly or of spot-CFD execution '
  'quality.',
  'Tier 1'),
 ('S10',
  'COMEX Rulebook Chapter 113: Gold Futures',
  'CME Group / COMEX',
  'current chapter; accessed 2026-07-17',
  'Exchange rulebook',
  'https://www.cmegroup.com/content/dam/cmegroup/rulebook/COMEX/1a/113.pdf',
  'GC deliverable contract and exchange time convention',
  'COMEX Gold futures (GC)',
  'Current contract rules',
  'Contract specification',
  'Defines the 100-troy-ounce physically delivered GC contract and specifies New York time when '
  'otherwise unstated.',
  'Rulebook terms do not establish price behavior at 08:30, 09:30 or 10:00.',
  'Tier 1'),
 ('S11',
  'Trading COMEX Gold and Silver',
  'CME Group',
  'n.d.; accessed 2026-07-17',
  'Exchange educational market-structure article',
  'https://www.cmegroup.com/education/articles-and-reports/trading-comex-gold-and-silver',
  'London, New York and Shanghai gold centers; hourly GC volume context',
  'Global gold and COMEX futures',
  'Contemporary overview',
  'Hourly descriptive volume',
  'Documents multiple global gold trading centers and supports treating gold as a global, not '
  'cash-equity-session-only, market.',
  'Exchange-authored educational material; descriptive rather than causal research.',
  'Tier 2'),
 ('S12',
  'Impact of Macroeconomic News on Metal Futures',
  'John Elder, Hong Miao and Sanjay Ramchander',
  '2012',
  'Peer-reviewed journal article',
  'https://mountainscholar.org/bitstream/10217/206884/1/Miao_H_BanFin_2012.pdf',
  'Gold reaction to 08:30, 09:15 and 10:00 announcements; surprises; continuation versus sign '
  'response',
  'COMEX gold, silver and copper futures',
  '2002-2008',
  '5-minute intraday returns, volatility and volume',
  'The 08:30 announcement set had the largest impact on gold; NFP and durable-goods surprises were '
  'especially important. Some 10:00 releases also affected returns, and announcement effects '
  'dissipated within about 60 minutes.',
  'Older regime; futures rather than retail XAUUSD; release-time mix changed; no 09:30-equity-open '
  'control and no ICT patterns.',
  'Tier 1'),
 ('S13',
  'Examining the Impact of Macroeconomic Announcements on Gold Futures in a VAR-GARCH Framework',
  "Lee A. Smales, Barry O'Grady and Yi Yang",
  '2015 (online 2014)',
  'Peer-reviewed journal article',
  'https://espace.curtin.edu.au/bitstream/handle/20.500.11937/28039/227202.pdf?sequence=2',
  '08:30 macro-news effect; spreads, volatility, returns and volume; transaction costs',
  'COMEX gold futures',
  '2006-2012; 1,532 trading days',
  'Transaction data aggregated to 30 seconds',
  'Major 08:30 announcements produced a sharp activity jump; the unconditional difference from '
  'non-announcement days became statistically indistinguishable within about three minutes. Higher '
  'volatility widened spreads and reduced volume.',
  'Only selected major 08:30 announcements; historical pit/open timing; not spot XAUUSD and not a '
  'directional strategy test.',
  'Tier 1'),
 ('S14',
  'Do Macroeconomics News Releases Affect Gold and Silver Prices?',
  'Rohan Christie-David, Mukesh Chaudhry and Timothy W. Koch',
  '2000',
  'Peer-reviewed journal article',
  'https://core.ac.uk/download/357567523.pdf',
  'Announcement surprise effects; contradictory/modest evidence; rapid price adjustment',
  'COMEX gold and silver futures',
  '1992-1995',
  '15-minute intraday returns',
  'Gold responded to CPI, unemployment, GDP, PPI and capacity utilization, but metals reacted to '
  'fewer announcements than interest-rate futures; many releases had no detectable effect.',
  'Old low-inflation sample, floor-trading hours and 15-minute aggregation obscure first-minute '
  'dynamics.',
  'Tier 1'),
 ('S15',
  'What Moves the Gold Market?',
  'Jun Cai, Yan-Leung Cheung and Michael C. S. Wong',
  '2001',
  'Peer-reviewed journal article',
  'https://ideas.repec.org/a/wly/jfutmk/v21y2001i3p257-278.html',
  'Intraday gold volatility seasonality and announcement effects',
  'COMEX gold futures',
  '1994-1997',
  '5-minute high-frequency returns',
  'Intraday periodicity materially affects volatility; employment, GDP, CPI and personal-income '
  'announcements were the strongest of 23 releases.',
  'Older floor-trading era; abstract-level public access here; does not test 09:30 manipulation or '
  'modern XAUUSD costs.',
  'Tier 1'),
 ('S16',
  'Who Sets the Price of Gold? London or New York',
  'Martin Hauptfleisch, Talis J. Putnins and Brian M. Lucey',
  '2016',
  'Peer-reviewed journal article',
  'https://www.pure.ed.ac.uk/ws/files/82358957/GoldILS_JFutMkt_Forthcoming.pdf',
  'Gold futures-versus-spot price discovery; electronic trading; announcements',
  'COMEX futures and London OTC spot gold',
  '1997-2014 (17 years)',
  'One-second data aggregated to hourly price-discovery estimates',
  'COMEX contributed more to gold price discovery on average; after near-24-hour Globex adoption, '
  'floor-opening/time-zone patterns weakened. US GDP increased futures information leadership, '
  'while employment news increased quote noise.',
  'Hourly event indicators cannot isolate 08:30 versus 09:30; institutional London spot data are '
  'not a retail XAUUSD feed.',
  'Tier 1'),
 ('S17',
  'How Do Macroeconomic News Surprises Affect Round-the-Clock Price Discovery of Gold?',
  'Neharika Sobti, Sanjay Sehgal and Balakrishnan Ilango',
  '2021',
  'Peer-reviewed journal article',
  'https://www.sciencedirect.com/science/article/pii/S1057521921002209',
  'Round-the-clock gold price discovery; news-surprise size, asymmetry and state dependence',
  'COMEX, London OTC and Shanghai gold futures',
  '2013-2018',
  'One-minute data',
  'US futures led global price discovery; the New York-London overlap was most informative; large '
  'and dispersed US surprises had asymmetric, state-dependent effects.',
  'Paywalled full text; session-level results do not establish a standalone 09:30 effect or an ICT '
  'setup.',
  'Tier 1'),
 ('S18',
  'The Timing of the Flight to Gold: An Intra-Day Analysis of Gold and the S&P 500',
  'Dirk G. Baur and Konstantin Kuck',
  '2020',
  'Peer-reviewed journal article',
  'https://www.sciencedirect.com/science/article/pii/S1544612319301448',
  'Gold response to extreme equity shocks; cross-asset risk sentiment',
  'Spot gold, gold futures and S&P 500',
  '2007-2018',
  '5-minute intraday returns',
  'Extreme negative five-minute S&P 500 returns led positive gold responses, supporting a fast '
  'flight-to-gold channel.',
  'Conditions on extreme equity losses, not all 09:30 opens; correlation/lead response does not '
  'imply predictable routine reversals.',
  'Tier 1'),
 ('S19',
  'Stop-Loss Orders and Price Cascades in Currency Markets',
  'Carol L. Osler / Federal Reserve Bank of New York',
  '2002 staff report',
  'Reputable working paper with transparent methodology',
  'https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf',
  'Stop clustering, liquidity levels, continuation versus reversal, opposing evidence to automatic '
  'sweep reversal',
  'USD/DEM, USD/JPY and USD/GBP',
  '1996-1998',
  'Minute quotes plus documented dealer orders; bootstrap tests',
  'Exchange rates trended unusually rapidly after reaching stop-loss clusters; stop-loss responses '
  'were larger and longer than take-profit responses. This supports cascades/continuation, not an '
  'automatic reversal narrative.',
  'FX, not gold; round-number order data from one historical dealer sample; does not validate ICT '
  'intent claims.',
  'Tier 1'),
 ('S20',
  'A Comparison of Trading and Non-Trading Mechanisms for Price Discovery',
  'Michael J. Barclay and Terrence Hendershott',
  '2008',
  'Peer-reviewed journal article',
  'https://www.sciencedirect.com/science/article/pii/S0927539808000170',
  'Nasdaq pre-open and 09:30 price discovery; efficient-opening counterpoint',
  '250 high-volume Nasdaq stocks',
  '1993-1999',
  'TAQ trades and quotes; intraday',
  'As pre-open volume grew, opening prices became more efficient and price discovery shifted into '
  'the pre-open for the highest-volume stocks.',
  'Cash stocks in an older market structure; does not cover NQ futures or gold and does not test '
  'reversal profitability.',
  'Tier 1'),
 ('S21',
  'The Short-Run Dynamics of the Price Adjustment to New Information',
  'Louis H. Ederington and Jae Ha Lee',
  '1995',
  'Peer-reviewed journal article',
  'https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/shortrun-dynamics-of-the-price-adjustment-to-new-information/00BEB6F23889807615ADA3EC3050994E',
  'Efficient rapid adjustment after macro releases; counterpoint to predictable post-news reversal',
  'Interest-rate and FX futures',
  'Historical tick sample',
  '10-second and tick-by-tick returns',
  'Price adjustment began within 10 seconds and was essentially complete within about 40 seconds '
  'for the studied announcements.',
  'Not gold; historical futures microstructure; rapid average adjustment does not rule out '
  'conditional intraday continuation/reversal.',
  'Tier 1'),
 ('S22',
  'What Drives Gold Prices?',
  'Federal Reserve Bank of Chicago',
  '2021',
  'Institutional econometric research',
  'https://www.chicagofed.org/publications/chicago-fed-letter/2021/464',
  'Gold relationships with real rates, inflation expectations and pessimism/risk sentiment',
  'LBMA gold and U.S. macro/financial variables',
  '1971-2021',
  'Annual, quarterly and limited daily regressions',
  'Gold was negatively associated with expected long-term real rates and positively associated '
  'with pessimistic expectations; the authors stress correlation rather than causality.',
  'Primarily low-frequency; cannot determine five-minute post-release pathways or execution rules.',
  'Tier 2'),
 ('S23',
  "Evaluating Qaurum: Why Simple Isn't Always Best",
  'World Gold Council',
  '2021',
  'Institutional research',
  'https://www.gold.org/goldhub/research/qaurum-vs-us-real-rates-and-dollar-model',
  'Gold, real yields and U.S. dollar; multi-driver framing',
  'Gold and macro-financial factors',
  'Model-dependent historical sample',
  'Monthly/quarterly model comparison',
  'Argues that real yields and the dollar are important but insufficient alone; demand, '
  'positioning and other drivers matter.',
  'Industry body; proprietary inputs and low frequency; not causal evidence for a morning entry '
  'rule.',
  'Tier 2'),
 ('S24',
  'ICT NQ Futures Strategy: Bias, Kill Zones, and CISD Entry',
  'SMC X',
  '2026',
  'Practitioner strategy article',
  'https://www.smartmoneytrader.co/blog/ict-nq-futures-strategy',
  'Nasdaq pre-market sweep; 09:30 displacement; HTF bias and confirmation',
  'NQ/MNQ futures',
  'Not disclosed',
  'Chart examples; no disclosed dataset',
  'Defines a practitioner sequence of pre-market sweep, 09:30 displacement and later confirmation.',
  'No transparent backtest, sample, costs or falsification; marketing language and '
  'institutional-intent claims are unverified.',
  'Tier 3'),
 ('S25',
  '2022 ICT Mentorship Notes',
  'Community summary of Inner Circle Trader material',
  '2025 posting; underlying 2022 material',
  'Practitioner notes',
  'https://innercircletrading.blog/wp-content/uploads/2025/01/2022-ict-mentorship-notes-download-free.pdf',
  '09:30 first move opposite eventual trend; liquidity, FVG and New York session narrative',
  'Mostly U.S. equity-index futures',
  'Examples not systematically sampled',
  'Annotated charts/notes',
  'Records the practitioner claim that the first move after 09:30 often opposes the eventual '
  'session trend.',
  'Derivative notes rather than the primary lecture; qualitative wording; no denominator, controls '
  'or costs.',
  'Tier 3'),
 ('S26',
  'Fair Value Gap (FVG): ICT Strategy and Backtest Guide',
  'Backtrex',
  '2026-05-23',
  'Practitioner/quant education',
  'https://backtrex.com/en/blog/fair-value-gap-trading-strategy',
  'Three-candle FVG geometry; need for backtesting',
  'Multi-market',
  'Not disclosed on landing page',
  'Bar-pattern examples',
  'Defines an FVG as non-overlap between candle-one and candle-three wicks around an impulsive '
  'middle candle and explicitly frames performance as a backtest question.',
  'Commercial educator; claims about unfilled orders/institutional causes are not independently '
  'established.',
  'Tier 3'),
 ('S27',
  'Optimal Trade Entry',
  'Quantum Algo',
  '2026-04-30',
  'Practitioner glossary',
  'https://www.quantum-algo.com/glossary/optimal-trade-entry/',
  'OTE 62%-79% retracement zone and 70.5% reference',
  'Multi-market',
  'Not disclosed',
  'Definition/examples',
  'Defines OTE as the 62%-79% Fibonacci retracement of an impulse, often combined with an FVG or '
  'order block.',
  'No empirical support for the privileged ratios; promotional and partly asserts institutional '
  'behavior.',
  'Tier 3'),
 ('S28',
  'ICT Rejection Block Explained',
  'ICT Flow',
  '2026-05-31',
  'Practitioner education article',
  'https://ictflow.com/blog/ict-rejection-block-explained',
  'Rejection-block wick zone',
  'Multi-market',
  'Not disclosed',
  'Definition/examples',
  'Defines a rejection block from a significant wick at a structural level, with the zone spanning '
  'the wick.',
  'Significant wick, key level and institutional causation are subjective; no performance study.',
  'Tier 3'),
 ('S29',
  'ICT Judas Swing: How to Predict and Trade It',
  'ICT Killzone',
  '2026',
  'Practitioner education article',
  'https://www.ictkillzone.com/ict-judas-swing',
  'Judas swing, AMD, 08:30-09:30 New York false-move hypothesis, 10:00 Silver Bullet',
  'FX, index futures and gold examples',
  'Not disclosed',
  'Definition/examples',
  'Defines the New York Judas as a sharp 08:30-09:30 false move/sweep that may precede reversal '
  'and places a later entry window at 10:00-11:00.',
  'No disclosed data or methodology; even examples list FOMC incorrectly among typical 08:30 '
  'releases; intent and frequency claims are unverified.',
  'Tier 3'),
 ('S30',
  '10 AM Key Open Liquidity & Rejection Wick',
  'TradingView community script by jolianos',
  '2026-06-28',
  'Public practitioner indicator',
  'https://www.tradingview.com/script/UfnfGTEC-10-AM-Key-Open-Liquidity-Rejection-Wick/',
  '10:00 key-open line; rejection wick; liquidity sweep; OTE and FVG confluence',
  'Chart-configurable; commonly index futures',
  'Not disclosed',
  'Indicator rules; no backtest',
  "Shows that '10 AM key open' is used in community tooling as the open of the 10:00 candle, not "
  'as an exchange-defined session open.',
  'Closed-source script, no empirical validation, arbitrary defaults and no distinction from 10:00 '
  'economic releases.',
  'Tier 4'),
 ('S31',
  'ICT Silver Bullet Community Indicators',
  'TradingView community',
  'n.d.; accessed 2026-07-17',
  'Public practitioner indicators',
  'https://www.tradingview.com/scripts/silverbullet/',
  '10:00-11:00 ET Silver Bullet time window and FVG',
  'Mostly U.S. index futures/FX',
  'Not disclosed',
  'Indicator definitions/examples',
  'Community implementations consistently identify an AM Silver Bullet window of 10:00-11:00 ET.',
  'Community aggregation, variable implementations and no proof of edge; a time window is not a '
  'formal market open.',
  'Tier 4'),
 ('S32',
  'Liquidity Sweep',
  'AlgoBars Concepts',
  '2026',
  'Practitioner glossary',
  'https://algobars.com/concepts/liquidity-sweep/',
  'Sweep as breach followed by rapid return; distinction from genuine breakout',
  'Multi-market',
  'Not disclosed',
  'Definition/examples',
  'Provides a directly programmable practitioner description: breach an obvious high/low and '
  'return within one or two candles.',
  'Stop locations and institutional intent are assumed, not observed; no outcome statistics.',
  'Tier 3'),
 ('S33',
  'ICT Market Structure Shift (MSS): How to Spot and Trade It',
  'LegalClarity',
  '2026-06-17',
  'Practitioner education article',
  'https://legalclarity.org/ict-market-structure-shift-mss-how-to-spot-and-trade-it/',
  'Three-bar swings; displacement body close through a prior swing; FVG confluence',
  'Multi-market',
  'Not disclosed',
  'Definition/examples',
  'Defines MSS as a displacement-backed break of a prior swing and describes a three-candle swing '
  'convention.',
  'Non-specialist trading source; no dataset, costs or proof; used only to capture terminology.',
  'Tier 3'),
 ('S34',
  'Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A Systematic Falsification '
  'Study',
  'Mathias Mesfin',
  '2026-05-05',
  'Non-peer-reviewed working paper',
  'https://arxiv.org/abs/2605.04004',
  'Critical test of opening, liquidity-grab, momentum and news OHLCV signals',
  'MNQ futures',
  '2021-2025; 947 sessions',
  '5-minute OHLCV; walk-forward tests',
  'None of fourteen signal families met all predeclared significance, cost, sample-size and '
  'multi-year stability criteria.',
  'Very recent single-author preprint; methods and data require independent replication; fixed '
  'two-point cost; not gold.',
  'Tier 2'),
 ('S35',
  'How Do Gold Intra-Day Returns and Volatility React to Monetary Policy Shocks?',
  'Basel Awartani, Syed Mujahid Hussain and Nader Virk',
  '2024',
  'Peer-reviewed journal article',
  'https://www.sciencedirect.com/science/article/pii/S1057521924004186',
  'Gold response to FOMC shocks; asymmetry and multi-minute adjustment',
  'Gold market',
  'Study-specific modern sample',
  '5-minute intraday data',
  'Gold returns and volatility were more sensitive to looser than tighter FOMC shocks; adjustment '
  'continued beyond five minutes.',
  'FOMC timing is outside the morning study; does not validate 08:30/09:30 ICT geometry.',
  'Tier 1'))

TRANSFER_HEADER = (
    "concept",
    "original_nasdaq_rationale",
    "nasdaq_specific_dependency",
    "possible_xauusd_equivalent",
    "supporting_evidence",
    "contradicting_evidence",
    "transferability_rating",
    "recommended_test",
    "risks_of_direct_transplantation",
)

TRANSFER_ROWS = (('08:30 macro impulse',
  'Scheduled U.S. data creates a pre-cash-open NQ move that practitioners may label manipulation.',
  'NQ prices anticipated equity cash-open repricing and index constituents.',
  'Treat 08:30 as an event-time gold information shock, conditional on release category and '
  'standardized surprise.',
  'S01-S03, S12-S15 show formal release timing and strong gold announcement effects.',
  'S14 finds many releases have no detectable metal effect; S21 shows very rapid efficient '
  'adjustment in other futures.',
  'Directly transferable',
  'Compare 08:30-08:35 absolute return and range on major, minor and no-release days; regress on '
  'standardized surprise.',
  'Calling the move manipulation prejudges reversal and ignores efficient price discovery.'),
 ('09:30 cash-equity open',
  'Opening auction and cash/index arbitrage concentrate equity information and volume.',
  'Formal Nasdaq/NYSE 09:30 auction, constituent openings, cash-futures basis and ETF '
  'creation/redemption.',
  'Potential cross-asset risk-sentiment or portfolio-rebalancing impulse in gold, tested after '
  'controlling for 08:30.',
  'S07-S08 establish the auction; S18 supports a gold response to extreme equity shocks.',
  'S09 and S16 show gold already trades and discovers price before 09:30; no controlled XAUUSD '
  '09:30 edge was found.',
  'Transferable with modification',
  'Estimate incremental 09:30 volatility/return with day fixed effects or matched controls '
  'including 08:30 impulse, news category and surprise.',
  'Mistakes an equity-specific institutional open for a gold session open.'),
 ('10:00 key open',
  'Community reference to the open of the 10:00 candle after initial equity-open volatility.',
  'No formal Nasdaq/NYSE session begins at 10:00; often tied to index-trader routines.',
  'Use as a secondary event window and explicitly flag scheduled 10:00 releases.',
  'S03-S05 show real 10:00 releases; S12 finds some 10:00 news effects; S30-S31 document the '
  'community heuristic.',
  'No exchange source recognizes a 10:00 market open; S30-S31 provide no empirical proof.',
  'Weakly transferable',
  'Compare 10:00-10:30 on 10:00-release versus non-release days and test whether any residual '
  'clock effect remains.',
  'Attributes macro-release repricing to a chart candle or community key-open narrative.'),
 ('09:30 liquidity sweep',
  'Cash-open volume may breach pre-market or 08:30 extremes before reversing.',
  'Cash-auction order imbalances and index arbitrage.',
  'Observable breach-and-reentry of the 08:30 impulse extreme or pre-news range after 09:30.',
  'S24-S25 describe the practitioner pattern; S18 supports a conditional equity-to-gold channel.',
  'S19 shows stop clusters can propagate continuation; S34 reports null results for OHLCV '
  'liquidity-grab families in MNQ.',
  'Transferable with modification',
  'Compare post-09:30 breach/reentry outcomes with matched accepted breakouts, separately on news '
  'and non-news days.',
  'Sweep labels can be assigned with hindsight and do not reveal order intent.'),
 ('Judas swing',
  "An opening false move against a presumed daily bias precedes the 'real' direction.",
  'Kill-zone conventions and cash-open narrative are commonly derived from index/FX education.',
  'Rename as a deterministic false-breakout-and-reversal outcome; do not encode intent.',
  'S29 and S25 document the practitioner hypothesis.',
  'S12-S13 support fast news price discovery; S19 supports continuation cascades; no gold-specific '
  'Judas study found.',
  'Weakly transferable',
  'Test breach, close-back and MSS rules with causal confirmation; compare to all breakouts.',
  "Bias and 'real direction' can be hindsight labels; high multiple-testing risk."),
 ('Liquidity sweep',
  'Stops are assumed to cluster beyond session/swing extremes and the breach supplies liquidity.',
  'Reference levels often use overnight, pre-market and RTH structures specific to index futures.',
  'Cross of a predeclared gold range/swing followed by a close back within a fixed number of bars.',
  'S19 supports order clustering/cascades in FX; S32 supplies programmable practitioner geometry.',
  'S19 finds continuation after stop clusters, contradicting automatic-reversal claims; no XAU '
  'order-book proof.',
  'Transferable with modification',
  'Test reversal and continuation conditional on breach size, close-back speed, news and surprise.',
  'Retail XAUUSD is fragmented OTC/CFD; actual stops and centralized volume are unobserved.'),
 ('Displacement',
  'Large directional candle indicates aggressive repricing and validates MSS/FVG.',
  'None in geometry, though typical size thresholds depend on NQ volatility and tick value.',
  'Candle body/range standardized by rolling same-time gold volatility, close location and '
  'optional FVG.',
  'S12-S15 support unusually large event-time gold moves; S33 captures practitioner use.',
  'Large bars can be public-news price discovery rather than institutional directional commitment.',
  'Directly transferable',
  'Sensitivity over body/median and true-range/ATR thresholds; evaluate forward returns without '
  'conditioning on future bars.',
  'Absolute-point rules fail across gold price and volatility regimes.'),
 ('Market structure shift',
  'Post-sweep body close through a confirmed swing signals reversal.',
  "Swing scale calibrated to NQ's microstructure and chosen chart timeframe.",
  'Causal break of the most recent confirmed 1-minute or 3-minute pivot with displacement.',
  'S33 provides practitioner definition; deterministic swing logic is implementable.',
  'No independent evidence that this pattern has gold expectancy; pivot confirmation introduces '
  'delay.',
  'Transferable with modification',
  'Compare 1-minute and 3-minute MSS; vary pivot width and displacement filter.',
  'Using future bars to identify pivots causes look-ahead; loose swing selection creates '
  'researcher discretion.'),
 ('Fair value gap',
  'Three-candle wick non-overlap marks a fast NQ delivery zone and potential retracement entry.',
  'No formal dependency, but frequency and tick size are instrument/timeframe specific.',
  'Identical three-bar gap geometry on gold, treated only as a bar pattern.',
  'S26 defines reproducible geometry; S13 documents fast event moves and wider spreads.',
  "No independent evidence that the zone is 'fair value' or must fill; gaps may be microstructure "
  'artifacts.',
  'Transferable with modification',
  'Test first proximal, midpoint and distal touch after causal creation, net of event-time costs.',
  'Semantic institutional claims and fill expectation may not transfer; bid/ask gaps differ from '
  'OHLC gaps.'),
 ('Rejection block',
  'Wick at an index liquidity level is treated as a future entry zone.',
  'Often selected using discretionary RTH highs/lows and visible chart narrative.',
  'Mechanically define body-to-wick zone on a sweep/reentry candle with a minimum wick fraction.',
  'S28 documents wick-zone terminology.',
  'No Tier 1/2 validation; competing definitions select one or multiple candles.',
  'Insufficient evidence',
  'Include only as a separately labeled experimental geometry with predeclared wick and pivot '
  'rules.',
  'High degrees of freedom and hindsight candle selection.'),
 ('OTE retracement',
  'Deep 62%-79% retracement of an NQ impulse is claimed to offer favorable risk/reward.',
  'None formal, but impulse anchoring is discretionary and NQ-specific examples dominate.',
  'Fixed 62%-79% retracement of the objectively defined 08:30 impulse, plus 50%, 62% and 75% '
  'single levels.',
  'S27 documents the exact practitioner zone.',
  'No empirical source establishes privileged Fibonacci ratios; simple retracement is the '
  'appropriate benchmark.',
  'Weakly transferable',
  'Compare all predeclared depths on identical event cohorts and report fill/expiry/cost '
  'trade-offs.',
  'Anchor selection and multiple depths invite data mining; deep entries may never fill.'),
 ('Acceptance outside range',
  'Holding above/below pre-market range suggests genuine index breakout rather than manipulation.',
  'Pre-market range is closely tied to RTH transition.',
  'Two consecutive 1-minute closes or one 3-minute close beyond a buffered pre-news boundary.',
  'S19 supports persistent/cascade behavior after levels; market-auction logic makes acceptance a '
  'neutral construct.',
  'Threshold is a research proxy, not a named empirical gold fact.',
  'Directly transferable',
  'Vary close count, time allowance and volatility buffer; compare continuation rates.',
  'Long confirmation delays entries and can re-label the same path under different bar '
  'aggregation.'),
 ('Re-entry into range',
  'Return inside the pre-market range signals failed breakout and potential reversal.',
  'Nasdaq pre-market boundaries are equity-session specific.',
  'First causal close back inside the 07:30-08:29 or 08:00-08:29 gold range after a breach.',
  'S32 matches practitioner geometry; S14 shows heterogeneous news reaction that makes failure '
  'plausible.',
  'S19 shows breaches near stops may continue rather than re-enter.',
  'Directly transferable',
  'Estimate full-reversal probability versus accepted breakout baseline by news class.',
  'Using wick-only reentry or unrestricted time makes the rule hindsight-prone.'),
 ('Impulse midpoint hold',
  'NQ holding the news impulse equilibrium until cash open is treated as continuation evidence.',
  'Interaction with cash-open flows.',
  'Whether all closes or a required fraction of closes remain on the impulse-direction side of 50% '
  'through 09:29.',
  'A neutral measurable state; consistent with continuation hypotheses from S19.',
  'No source validates 50% as a privileged threshold.',
  'Transferable with modification',
  'Test 50%, 62% and time-weighted hold fractions; report monotonicity rather than best-only '
  'threshold.',
  'Threshold optimization can manufacture an apparent edge.'),
 ('Opening range manipulation',
  'First RTH move is assumed to trap traders before reversal.',
  'Requires the 09:30 cash opening auction and constituent order imbalance.',
  'Do not transfer the manipulation label; test only 09:30 false breakout on non-news gold days.',
  'S24-S25 document the hypothesis.',
  'S20 supports efficient opening price discovery; S34 finds no robust MNQ OHLCV family after '
  'costs.',
  'Not transferable',
  'Retain only the observable non-news false-breakout family as exploratory, with no intent claim.',
  'Direct copying imports equity-auction mechanics and hindsight narrative into gold.'),
 ('London high/low target',
  'NQ/FX New York setups often use overnight/London extremes as stop/liquidity references.',
  'Practitioner London window conventions and daylight-saving mismatch.',
  'Gold London-session high/low using an explicit Europe/London clock, plus ET-window sensitivity.',
  'S11 and S16 establish London as an important gold center; S29 uses London extremes in the '
  'framework.',
  'A single retail XAU feed may not represent London OTC price/volume; session boundary is not '
  'unique.',
  'Transferable with modification',
  'Compare actual London-clock and fixed-ET definitions; predeclare one primary.',
  'DST mismatch and feed-specific Sunday/daily maintenance bars can shift extremes.'),
 ('Previous-day high/low',
  'Widely watched RTH liquidity levels for index futures.',
  'RTH versus full-session day is meaningful and market-specific.',
  'Prior complete New York trading-day high/low and, separately, prior COMEX session high/low.',
  'Generic observable reference; no strong source-specific performance claim.',
  'No empirical evidence here that gold reverses at these levels.',
  'Transferable with modification',
  'Test prior NY calendar day and prior COMEX trade-date definitions separately.',
  'Ambiguous day boundary in 23-hour gold trading and broker maintenance windows.'),
 ('Cross-asset HTF bias',
  'NQ direction is aligned with equity structure and index liquidity targets.',
  'Equity-index constituents, earnings and cash breadth.',
  'Causal gold bias using prior daily trend plus contemporaneous but lagged USD/real-yield/risk '
  'variables when available.',
  'S18, S22 and S23 support equity-risk, real-yield and dollar channels.',
  'Relationships are state-dependent and often low-frequency; fixed signs may fail.',
  'Transferable with modification',
  'Report alignment using a predeclared, lagged bias and compare unfiltered results; never infer '
  'bias from future session path.',
  'Adding many macro filters increases overfit and may require unavailable high-frequency '
  'instruments.'),
 ('Lifecycle AMD labels',
  'Accumulation-manipulation-distribution narrates the NQ day around pre-market and cash open.',
  'RTH transition and daily-bias storytelling.',
  'Replace intent labels with mutually exclusive path states based on breach, reentry, retracement '
  'and extension.',
  'S29 documents AMD/Judas terminology.',
  'No independent evidence of deterministic institutional sequencing; overlapping states can be '
  'assigned with hindsight.',
  'Weakly transferable',
  'Classify outcomes for reporting only; strategy signals may use only information available by '
  'entry time.',
  'Using final lifecycle as an entry filter is direct look-ahead bias.'))

VALID_SOURCE_TIERS = {"Tier 1", "Tier 2", "Tier 3", "Tier 4"}
VALID_TRANSFER_RATINGS = {
    "Directly transferable",
    "Transferable with modification",
    "Weakly transferable",
    "Not transferable",
    "Insufficient evidence",
}


def _validate_rows(
    name: str,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
) -> None:
    expected_width = len(header)
    for row_number, row in enumerate(rows, start=2):
        if len(row) != expected_width:
            raise ValueError(
                f"{name} row {row_number} has {len(row)} columns; expected {expected_width}"
            )
        if any(not isinstance(value, str) for value in row):
            raise TypeError(f"{name} row {row_number} contains a non-string value")


def _validate_registers() -> None:
    _validate_rows("source register", SOURCE_HEADER, SOURCE_ROWS)
    _validate_rows("transfer matrix", TRANSFER_HEADER, TRANSFER_ROWS)

    source_ids = [row[0] for row in SOURCE_ROWS]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source register contains duplicate source IDs")
    if any(row[-1] not in VALID_SOURCE_TIERS for row in SOURCE_ROWS):
        raise ValueError("source register contains an invalid quality tier")
    if any(row[6] not in VALID_TRANSFER_RATINGS for row in TRANSFER_ROWS):
        raise ValueError("transfer matrix contains an invalid transferability rating")


def _write_csv(
    path: Path,
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="destination directory (defaults to the event-study directory)",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    event_study_dir = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir or event_study_dir

    _validate_registers()
    _write_csv(output_dir / "source_register.csv", SOURCE_HEADER, SOURCE_ROWS)
    _write_csv(
        output_dir / "nasdaq_to_xauusd_transfer_matrix.csv",
        TRANSFER_HEADER,
        TRANSFER_ROWS,
    )
    print(
        f"Wrote {len(SOURCE_ROWS)} sources and {len(TRANSFER_ROWS)} transfer rows "
        f"to {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
