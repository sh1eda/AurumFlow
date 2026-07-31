# RESEARCH_CATALOG
## Candidate Research Definitions

**Version:** 0.1 Draft

---

# Purpose

This catalog defines the research objects investigated by the project.

Its purpose is **not** to prescribe implementation rules.

Instead, it provides a structured inventory of discretionary concepts that will be evaluated through objective, empirical research.

The inclusion of a concept in this catalog reflects its relevance within the ICT/SMC discretionary trading domain and the operator's existing methodology. Inclusion alone does not imply predictive validity or production readiness.

Each research object follows the same lifecycle:

Candidate Definition

↓

Objective Detection

↓

Feature Engineering

↓

Statistical Evaluation

↓

Robustness Testing

↓

Acceptance, Rejection, or Inconclusive Classification

---

# Research Object Template

Every research object should ultimately contain:

- Research Objective
- Candidate Definition
- Candidate Features
- Candidate Context Requirements
- Candidate Confirmation Signals
- Candidate Invalidation Conditions
- Candidate Failure Modes
- Candidate Quality Metrics
- Statistical Validation Results
- Implementation Status

---

# Research Object 01 — Higher Timeframe Bias

**Research Objective**

Determine whether higher-timeframe directional context provides measurable predictive value for intraday execution.

**Candidate Features**

- Weekly market structure
- Daily market structure
- 4H market structure
- Premium / Discount positioning
- External liquidity relationship
- Internal liquidity relationship
- HTF displacement
- HTF delivery arrays
- Swing sequencing
- Market delivery state

**Research Questions**

- Does HTF bias exist as an objective phenomenon?
- Which structural variables contribute most?
- Which variables are redundant?
- Does HTF bias improve execution quality?
- Does HTF bias improve target probability?

---

# Research Object 02 — Liquidity Pools

**Research Objective**

Evaluate whether interaction with liquidity objectives influences future price behavior.

**Candidate Features**

- Previous Day High / Low
- Previous Week High / Low
- Monday High / Low
- Monthly extremes
- Quarterly extremes
- External swing highs/lows
- Internal swing highs/lows
- Equal highs/lows

**Research Questions**

- Does untouched liquidity carry predictive value?
- Does liquidity consumption alter market state?
- Does proximity to liquidity affect execution quality?

---

# Research Object 03 — Delivery Arrays

Candidate objects include:

- Order Block
- Fair Value Gap
- Inversion Fair Value Gap
- Breaker
- Mitigation Block
- Balanced Price Range
- Volume Imbalance
- Rejection Block

For every object, research shall determine:

- objective identification
- structural origin
- lifecycle
- interaction with liquidity
- interaction with HTF context
- interaction with session timing
- measurable contribution
- failure conditions

---

# Research Object 04 — Session Structure

Candidate domains include:

- Asia
- London
- New York
- Session overlap
- Opening ranges
- Overnight range

Research questions include:

- Which session characteristics persist?
- Which characteristics vary by market regime?
- Which characteristics contribute to execution quality?

---

# Research Object 05 — Engineered Liquidity

Candidate observations include:

- liquidity sweeps
- equal highs/lows
- false breakouts
- stop runs
- compression
- expansion
- pre-news displacement
- pre-session displacement

Research objective:

Determine whether engineered liquidity can be detected objectively and whether it improves subsequent trade selection.

---

# Research Object 06 — SMT Divergence

Candidate research variables include:

- timing alignment
- correlated instruments
- structural divergence
- liquidity divergence
- displacement confirmation
- persistence
- resolution quality

Research shall distinguish between random divergence and statistically meaningful divergence.

---

# Research Object 07 — OTE

Research objective:

Determine whether OTE-style retracement zones contribute independent predictive value after controlling for higher-timeframe context, liquidity, and session effects.

Potential research dimensions include:

- retracement depth
- volatility adjustment
- interaction with delivery arrays
- interaction with liquidity objectives
- interaction with displacement quality

---

# Research Object 08 — Entry Validation

Candidate execution families include:

- Rejection Block
- FVG Re-entry
- Order Block Reaction
- Breaker Continuation
- Liquidity Sweep Reversal
- Displacement Continuation

Research shall compare execution families using identical validation procedures and objective performance metrics.

---

# Catalog Evolution Policy

This catalog is intentionally extensible.

Future concepts may be added without modifying the core research specification, provided they follow the same research lifecycle and validation standards.

New concepts may include, but are not limited to:

- CISD
- AMD
- Judas Swing
- Silver Bullet
- Macro Session Models
- Additional ICT/SMC concepts
- Non-ICT market structure hypotheses

The project is methodology-agnostic. Any concept demonstrating measurable, reproducible value under objective evaluation may become a candidate for implementation.

---

**End of Initial Research Catalog**