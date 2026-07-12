# Source Conflicts

Conflicts are not merged silently. Preferred definitions below are implementation recommendations, not claims that all sources agree.

## Order Block vs Supply/Demand

- `the-ict-handbook-v-1 1.pdf`: bullish OB is consecutive bearish candles before a move up; bearish OB is consecutive bullish candles before a move down. It explicitly separates OB from supply/demand.
- `Smart Money Concept (SMC) Trading.pdf`: treats demand/supply zones as core execution zones and uses "last candle before inefficiency/BOS/CHoCH" style logic.
- `Mastering ict.pdf`: describes OB as institutional footprint zones and also gives breaker definitions.

Implementation difference: a consecutive-candle OB detector is much easier to code than a subjective supply/demand zone detector. Recommendation: implement deterministic ICT-style OB separately from SMC supply/demand. Do not use supply/demand zone rules to override OB rules.

## BOS, CHoCH, and MSS

- `Smart Money Concept (SMC) Trading.pdf`: structure breaks are confirmed by candle body close except possibly on 1m.
- `EKINYZBB BOOTCAMP SERISI.pdf`: BOS continues trend after swing high/low break; MSS is reversal structure, and wick-only action is more like manipulation/liquidity.
- `the-ict-handbook-v-1 1.pdf`: distinguishes MSS using short-term highs/lows from S.MSS using intermediate-term highs/lows.

Implementation difference: wick breaks create many false events; body-close breaks lag but are more deterministic. Recommendation: use body-close on 15m and higher; record wick raids separately as liquidity events.

## FVG Definition and Validation

- `the-ict-handbook-v-1 1.pdf`: FVG is a three-candle pattern with no overlapping candle wicks.
- `Smart Money Concept (SMC) Trading.pdf`: imbalance is described through a fast move where middle candle displacement creates a gap between candle 1 low and candle 3 high in bearish examples.
- `EKINYZBB BOOTCAMP SERISI.pdf`: emphasizes that useful FVGs should follow liquidity being taken and market structure changing.

Implementation difference: geometric detection can be deterministic; "useful" FVG selection is a strategy filter. Recommendation: implement raw FVG geometry first, then test filters such as prior liquidity raid, displacement, and MSS.

## IFVG

- `the-ict-handbook-v-1 1.pdf`: inverse FVG is a regular FVG that is violated/broken through.
- `EKINYZBB BOOTCAMP SERISI.pdf`: IFVG requires price to close through/displace beyond the gap, then potentially retest around consequent encroachment.

Implementation difference: wick-through vs close-through changes event count and false positives. Recommendation: prefer close-through for 15m/XAUUSD; keep wick-through as a research flag only.

## Liquidity Sweep vs Liquidity Grab

- Several sources refer to taking EQH/EQL or session highs/lows as liquidity.
- `Smart Money Concept (SMC) Trading.pdf` and `EKINYZBB BOOTCAMP SERISI.pdf` imply that useful sweeps need a reaction/confirmation, not just touching the level.

Implementation difference: a raw raid is simply price crossing a prior level; a confirmed sweep requires rejection, return inside range, or MSS. Recommendation: store both `liquidity_raid` and `confirmed_sweep`.

## Dealing Range

- `Mastering ict.pdf`: dealing range is formed after both buy-side and sell-side liquidity are taken.
- Other notes use significant high-low ranges more loosely for premium/discount and OTE.

Implementation difference: liquidity-defined ranges are less frequent but cleaner; arbitrary swing legs are more frequent. Recommendation: use two range types: `liquidity_dealing_range` and `swing_leg_range`.

## PO3 Interpretation

- `_Institutional_PO3...`: explains PO3 as open, manipulation, expansion, close across chosen timeframe.
- Image-only files such as `PO3 Model (10 AM) Mr MatriX.pdf` and `INDICES 8.30 PO3 Model...` appear time-specific and index-specific but were not text-readable.

Implementation difference: general PO3 can transfer; 8:30/10:00 index models cannot be assumed for gold. Recommendation: use PO3 as phase labeling only until XAUUSD session tests define time anchors.

## SMT Interpretation

- `_ICT_SMT_Nedir...`: gives examples across BTC/ETH, EUR/GBP vs DXY, NQ/ES, and mentions XAU/XAG as a correlated pair class.

Implementation difference: the concept is programmable only after pair, correlation direction, swing matching, and timeframe are defined. Recommendation: research XAUUSD vs XAGUSD first; do not use SMT as implementation-ready confirmation yet.

## Session Timing

- `the-ict-handbook-v-1 1.pdf`: killzones are listed in EST/New York time, and NY PM silver bullet is marked indices-only.
- `ICT 2022 Mentorship...`: many examples use 9:30, 10:00, 8:30 news, ES/NQ point thresholds, and London/NY session behavior.
- `One Setup For Life - Redeye.pdf`: lists several session windows and RTH-specific opening range gap logic.

Implementation difference: XAUUSD spot/CFD trading has different liquidity cycles than ES/NQ RTH. Recommendation: represent all sessions in New York time with DST handling, then backtest XAUUSD-specific windows.

## Stop Placement

- `EKINYZBB BOOTCAMP SERISI.pdf`: aggressive stop can be at last swing body or the body of the candle that starts the FVG.
- `Smart Money Concept (SMC) Trading.pdf`: stops are often outside supply/demand or refined zones, sometimes using 50% entry logic.
- SMT note suggests stops can be protected below the SMT/FVG structure.

Implementation difference: body stops are tighter and more fragile; zone-extreme stops are wider. Recommendation: do not automate a single stop rule yet; backtest multiple explicit variants.

## Target Selection

- ICT sources emphasize external liquidity and draw-on-liquidity.
- SMC guide often targets the next unmitigated supply/demand zone or obvious EQH/EQL/trendline liquidity.
- DREYKO/ORG notes target ORG subdivisions and opening gaps for index sessions.

Implementation difference: targets can conflict when nearest unmitigated zone is opposite the external liquidity draw. Recommendation: define a target priority model and test per XAUUSD session.
