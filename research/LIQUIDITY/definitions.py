"""Frozen, data-free definitions for Liquidity Research Phase 1.

The experiment serializes these registers before it evaluates the chronological
holdout.  Liquidity words are operational labels only; none of the definitions
asserts intent, order placement, or a trading opportunity.
"""

from __future__ import annotations


NEW_YORK_TIMEZONE = "America/New_York"
EVALUATION_CLOCKS = ("08:30", "09:30")
FORWARD_HORIZONS_MINUTES = {
    "30m": 30,
    "60m": 60,
    "120m": 120,
}
NEW_YORK_STUDY_END = "12:00"
TRADING_DAY_END = "17:00"

# All price thresholds are causal functions of the observed spread and a
# completed-bar volatility scale.  Floors prevent a zero-spread print from
# silently collapsing a definition.
PRIMARY_TOUCH_SPREAD_FACTOR = 0.50
PRIMARY_EXCEED_SPREAD_FACTOR = 1.50
PRIMARY_APPROACH_VOLATILITY_FACTOR = 0.10
MINIMUM_PRICE_TOLERANCE = 0.05
RECLAIM_WINDOW_MINUTES = 30
PRIMARY_EVENT_COOLDOWN_MINUTES = 30
PRIMARY_OUTCOME_HORIZON = "60m"
DEFAULT_SWING_MAX_AGE_DAYS = 35

PRIMARY_LEVEL_VARIANTS = {
    "previous_day": "completed_primary",
    "previous_week": "completed_primary",
    "monday_dynamic": "forming_primary",
    "monday_completed": "completed_primary",
    "swing_4h": "width_2",
    "swing_daily": "width_2",
    "equal_high_low": "volatility_normalized",
}


LEVEL_DICTIONARY: tuple[dict[str, object], ...] = (
    {
        "family": "previous_day",
        "members": ["PDH", "PDL"],
        "price_source": "mid high/low of a >=90%-covered completed New York weekday",
        "creation_timestamp": "source extreme bar close",
        "first_availability": "00:00 America/New_York after the source day",
        "expiration": "end of the immediately following eligible New York weekday",
        "confirmation_delay": "source day completion",
        "primary_variant": "completed_primary",
    },
    {
        "family": "previous_week",
        "members": ["PWH", "PWL"],
        "price_source": "mid high/low of a >=90%-covered completed New York market week",
        "creation_timestamp": "source extreme bar close",
        "first_availability": "Saturday 00:00 America/New_York after the source week",
        "expiration": "next Saturday 00:00 America/New_York",
        "confirmation_delay": "source market-week completion",
        "primary_variant": "completed_primary",
    },
    {
        "family": "monday_dynamic",
        "members": ["FORMING_MONDAY_HIGH", "FORMING_MONDAY_LOW"],
        "price_source": "running Monday mid extreme through the last completed one-minute bar",
        "creation_timestamp": "bar close that establishes the new running extreme",
        "first_availability": "that one-minute bar close",
        "expiration": "next running-extreme revision or Tuesday 00:00 New York",
        "confirmation_delay": "one completed minute; never uses the eventual Monday range",
        "primary_variant": "forming_primary",
    },
    {
        "family": "monday_completed",
        "members": ["MONDAY_HIGH", "MONDAY_LOW"],
        "price_source": "mid extremes of an eligible completed Monday",
        "creation_timestamp": "source extreme bar close",
        "first_availability": "Tuesday 00:00 America/New_York",
        "expiration": "Saturday 00:00 America/New_York",
        "confirmation_delay": "completed Monday",
        "primary_variant": "completed_primary",
    },
    {
        "family": "swing_4h",
        "members": ["CONFIRMED_4H_SWING_HIGH", "CONFIRMED_4H_SWING_LOW"],
        "price_source": "strict pivot against equal left/right widths on completed UTC-aligned 4H bars",
        "creation_timestamp": "pivot bar close",
        "first_availability": "close of the final required right-side 4H bar",
        "expiration": "35 calendar days or primary consumed transition, whichever is earlier",
        "confirmation_delay": "2 right bars primary; width 3 sensitivity",
        "primary_variant": "width_2",
    },
    {
        "family": "swing_daily",
        "members": ["CONFIRMED_DAILY_SWING_HIGH", "CONFIRMED_DAILY_SWING_LOW"],
        "price_source": "strict pivot on eligible completed New York weekdays",
        "creation_timestamp": "pivot source day completion",
        "first_availability": "completion of the final required right-side eligible day",
        "expiration": "35 calendar days or primary consumed transition, whichever is earlier",
        "confirmation_delay": "2 right bars primary; width 3 sensitivity",
        "primary_variant": "width_2",
    },
    {
        "family": "equal_high_low",
        "members": ["EQUAL_HIGH_CLUSTER", "EQUAL_LOW_CLUSTER"],
        "price_source": "mean of two same-side confirmed width-2 4H pivots at least 8 hours apart",
        "creation_timestamp": "second contributing pivot timestamp",
        "first_availability": "second pivot confirmation timestamp",
        "expiration": "35 calendar days or primary consumed transition, whichever is earlier",
        "confirmation_delay": "both pivots must be confirmed",
        "primary_variant": "volatility-normalized tolerance; absolute and spread-aware variants are sensitivities",
    },
)


STATE_TRANSITION_DICTIONARY: tuple[dict[str, object], ...] = (
    {
        "state": "untouched",
        "definition": "no timestamp-available touch episode has occurred since level availability",
        "availability": "known at the observation timestamp",
    },
    {
        "state": "approached",
        "definition": "the executable side enters 0.10 completed daily-range units of the level without a touch",
        "availability": "one-minute bar close",
    },
    {
        "state": "touched",
        "definition": "ask range for a high-side level or bid range for a low-side level intersects level +/- max(0.05, 0.5x observed median spread)",
        "availability": "one-minute bar close; first and repeated episodes are counted separately",
    },
    {
        "state": "exceeded",
        "definition": "ask high is above a high-side level or bid low below a low-side level by max(0.05, 1.5x observed median spread)",
        "availability": "one-minute bar close",
    },
    {
        "state": "closed_beyond",
        "definition": "ask close for a high-side level or bid close for a low-side level closes beyond the exceedance threshold",
        "availability": "one-minute bar close",
    },
    {
        "state": "reclaimed",
        "definition": "after exceedance, the full executable spread closes on the original side: ask close below a high or bid close above a low",
        "availability": "one-minute bar close after the exceedance",
    },
    {
        "state": "moved_away",
        "definition": "after touch, mid close moves to the original side by the preregistered approach band",
        "availability": "one-minute bar close after the touch",
    },
    {
        "state": "consumed",
        "definition": "a close beyond remains unreclaimed for 30 observed minutes and the terminal executable close remains beyond; the level becomes inactive only then",
        "availability": "30 minutes after the qualifying close-beyond when coverage is complete",
    },
    {
        "state": "expired",
        "definition": "family-specific natural eligibility end is reached without revising history",
        "availability": "at the declared expiration timestamp",
    },
)


HYPOTHESIS_REGISTER: tuple[dict[str, object], ...] = (
    {
        "id": "A_UNTOUCHED_LEVEL_REACH",
        "question": "Do untouched levels have different reach probability from equally distant opposite-side controls after distance/time/volatility stratification?",
        "primary_metric": "60-minute session-clustered reach-rate lift",
        "classification": "preregistered",
    },
    {
        "id": "B_FIRST_TOUCH_DISTINCTION",
        "question": "Does first-touch post-interaction behavior differ from repeated-touch behavior?",
        "primary_metric": "60-minute side-aligned return difference and absolute-return difference",
        "classification": "preregistered",
    },
    {
        "id": "C_LEVEL_FAMILY_DISTINCTION",
        "question": "Are candidate families distinguishable in reach or post-touch behavior?",
        "primary_metric": "family reach lift and post-touch standardized effect",
        "classification": "preregistered with family-wise point estimates; no ranking from unadjusted p-values",
    },
    {
        "id": "D_EXCEEDANCE_RECLAIM",
        "question": "Does a reclaim after exceedance have different neutral path behavior from an unreclaimed exceedance?",
        "primary_metric": "60-minute side-aligned return and expansion difference",
        "classification": "preregistered",
    },
    {
        "id": "E_CONFLUENCE",
        "question": "Do independently constructed nearby levels differ from isolated levels after distance control?",
        "primary_metric": "60-minute reach lift for confluence_count >=2",
        "classification": "preregistered",
    },
    {
        "id": "F_SESSION_NEWS_INTERACTION",
        "question": "Are liquidity outcomes stable across 08:30/09:30 and official timing-only news regimes?",
        "primary_metric": "stratified effect direction and uncertainty",
        "classification": "preregistered stability analysis; no directional news inference",
    },
)


OUTCOME_DEFINITION_REGISTER: tuple[dict[str, object], ...] = (
    {
        "outcome": "level_reached_{horizon}",
        "definition": "future executable bid/ask range intersects the level tolerance in a half-open window",
        "horizons": ["30m", "60m", "120m", "study_end_1200", "trading_day_end_1700"],
    },
    {
        "outcome": "time_to_reach_minutes",
        "definition": "elapsed minutes to first timestamp-available touch; censored at the named horizon",
        "horizons": ["30m", "60m", "120m", "study_end_1200", "trading_day_end_1700"],
    },
    {
        "outcome": "path_before_reach",
        "definition": "toward/away excursion, path efficiency, maximum deviation and realized volatility through first reach or 120-minute censor",
        "horizons": ["120m"],
    },
    {
        "outcome": "post_interaction_return_and_excursion",
        "definition": "signed mid-close log return, absolute return, upward/downward excursion, side-aligned continuation depth, close relative to level and realized volatility",
        "horizons": ["30m", "60m", "120m"],
    },
    {
        "outcome": "post_touch_lifecycle",
        "definition": "exceedance, reclaim, time to reclaim, time spent beyond and return to original side without profitability labels",
        "horizons": ["30m", "60m", "120m"],
    },
    {
        "outcome": "opposing_level_reach",
        "definition": "reach of the nearest independently known active opposite-side primary level after an interaction",
        "horizons": ["60m", "120m"],
    },
)


MATCHED_BASELINE_METHODOLOGY = {
    "control_level": "At each anchor, mirror the observed absolute level distance to the opposite side of the evaluation mid-open; use the same spread-aware touch rule and horizon.",
    "seeded_control": "A stable SHA-256 draw from the run seed, anchor id and level id chooses a preregistered 0.9/1.0/1.1 distance multiplier for sensitivity only; generation is independent of row order.",
    "distance_baseline": "Frozen absolute and prior-day-range-normalized distance bands.",
    "conditional_baseline": "Development-only empirical reach rates in frozen distance x horizon x evaluation-clock x volatility bands; validation/holdout never alter the lookup.",
    "other_controls": [
        "unconditional reach distribution",
        "evaluation time",
        "weekday",
        "official timing-only news regime",
        "level age",
        "first versus repeated touch",
        "nearest 5-dollar non-liquidity grid sensitivity",
    ],
    "interpretation": "A raw reach rate is not incremental evidence; the primary comparison is paired control lift plus development-frozen conditional residual.",
}


DECISION_RULES = {
    "frozen_before_holdout": True,
    "primary_horizon": PRIMARY_OUTCOME_HORIZON,
    "minimum_anchor_observations_per_partition_family": 60,
    "minimum_interaction_events_per_partition_family": 40,
    "minimum_unique_sessions": 25,
    "meaningful_reach_rate_lift": 0.03,
    "meaningful_post_interaction_standardized_effect": 0.10,
    "uncertainty": "session-cluster bootstrap 95% interval must exclude zero for full evidence",
    "incremental_value": "paired matched-control lift and conditional-baseline residual must agree in sign",
    "robustness": "at least 70% of adequate registered strata/sensitivities retain the primary effect direction",
    "temporal_consistency": "validation and holdout effects must agree in direction",
    "proceed": "at least one family/state passes sample, incremental, uncertainty, robustness and temporal gates",
    "proceed_with_caution": "same-direction validation/holdout incremental evidence exists but uncertainty, robustness, or history breadth misses the full gate",
    "reject": "adequate validation/holdout samples provide stable near-zero or adverse incremental evidence for every tested definition",
    "inconclusive": "sample adequacy, one-year history, uncertainty or instability prevents proceed/reject",
    "history_confidence_cap": "fewer than two complete years prohibits PROCEED",
}


SENSITIVITY_REGISTER: tuple[dict[str, object], ...] = (
    {"dimension": "touch_tolerance", "values": [0.5, 1.0, 1.5], "unit": "primary tolerance multiplier"},
    {"dimension": "exceedance_threshold", "values": [1.0, 1.5, 2.0], "unit": "median-spread factor"},
    {"dimension": "reclaim_horizon", "values": [30, 60, 120], "unit": "minutes after exceedance"},
    {"dimension": "lifecycle", "values": ["immediate_close", "unreclaimed_30m", "natural_expiry"]},
    {"dimension": "swing_width", "values": [2, 3]},
    {"dimension": "equal_cluster", "values": ["absolute", "spread_aware", "volatility_normalized"]},
    {"dimension": "event_cooldown", "values": [15, 30, 60], "unit": "minutes"},
    {"dimension": "overlap", "values": ["clustered_primary", "non_overlapping_120m"]},
    {"dimension": "evaluation_clock", "values": ["08:30", "09:30"]},
    {"dimension": "forward_horizon", "values": ["30m", "60m", "120m"]},
    {"dimension": "spread_filter", "values": ["all", "below_session_p95"]},
    {"dimension": "outlier_treatment", "values": ["raw", "winsorized_1_99"]},
    {"dimension": "strata", "values": ["news", "weekday", "high_low_side", "level_age", "first_repeated"]},
)
