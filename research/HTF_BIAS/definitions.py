"""Preregistered definitions for HTF Bias Phase 1.

The registers in this module are deliberately data-free.  The experiment writes
them before evaluating the holdout and never tunes these rules from holdout
results.
"""

from __future__ import annotations


NEW_YORK_TIMEZONE = "America/New_York"
EVALUATION_CLOCKS = ("08:30", "09:30")
FORWARD_HORIZONS_MINUTES = {
    "30m": 30,
    "60m": 60,
    "120m": 120,
}
SESSION_ENDPOINT_CLOCK = "12:00"
NEUTRAL_RETURN_BPS = 0.5


FEATURE_DICTIONARY: tuple[dict[str, object], ...] = (
    {
        "feature": "prior_day_position",
        "family": "prior_day_location",
        "definition": "(evaluation mid-open - prior eligible New York weekday low) / prior eligible weekday range",
        "source_timeframe": "New York calendar day",
        "observation_cutoff": "previous eligible weekday only",
        "required_lookback": "one eligible weekday",
        "confirmation_delay": "until the prior weekday is complete",
        "availability_rule": "prior_day_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "distance_to_pdh_range",
        "family": "prior_day_location",
        "definition": "(PDH - evaluation price) / prior-day range",
        "source_timeframe": "New York calendar day",
        "observation_cutoff": "previous eligible weekday only",
        "required_lookback": "one eligible weekday",
        "confirmation_delay": "until the prior weekday is complete",
        "availability_rule": "prior_day_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "distance_to_pdl_range",
        "family": "prior_day_location",
        "definition": "(evaluation price - PDL) / prior-day range",
        "source_timeframe": "New York calendar day",
        "observation_cutoff": "previous eligible weekday only",
        "required_lookback": "one eligible weekday",
        "confirmation_delay": "until the prior weekday is complete",
        "availability_rule": "prior_day_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "pdh_touched_before_evaluation",
        "family": "prior_day_location",
        "definition": "current New York date high before evaluation is at least PDH",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "current day plus prior eligible weekday",
        "confirmation_delay": "none beyond completed source bars",
        "availability_rule": "intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "pdl_touched_before_evaluation",
        "family": "prior_day_location",
        "definition": "current New York date low before evaluation is at most PDL",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "current day plus prior eligible weekday",
        "confirmation_delay": "none beyond completed source bars",
        "availability_rule": "intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "prior_week_position",
        "family": "prior_week_location",
        "definition": "position of evaluation price in the prior completed New York market-week range",
        "source_timeframe": "market week",
        "observation_cutoff": "completed prior market week only",
        "required_lookback": "one completed week",
        "confirmation_delay": "until prior week close",
        "availability_rule": "prior_week_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "pwh_touched_before_evaluation",
        "family": "prior_week_location",
        "definition": "current market-week high before evaluation is at least PWH",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "current and prior market week",
        "confirmation_delay": "none beyond completed source bars",
        "availability_rule": "intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "pwl_touched_before_evaluation",
        "family": "prior_week_location",
        "definition": "current market-week low before evaluation is at most PWL",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "current and prior market week",
        "confirmation_delay": "none beyond completed source bars",
        "availability_rule": "intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "monday_position",
        "family": "monday_range",
        "definition": "position in Monday range observed before evaluation; full Monday is used only from Tuesday onward",
        "source_timeframe": "one minute / New York Monday",
        "observation_cutoff": "strictly before evaluation on Monday; completed Monday later in week",
        "required_lookback": "current market week",
        "confirmation_delay": "none for forming range; full-range flag only after Monday ends",
        "availability_rule": "monday_range_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "monday_high_taken_before_evaluation",
        "family": "monday_range",
        "definition": "post-Monday bars before evaluation have traded at or above completed Monday high",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "completed Monday plus current week path",
        "confirmation_delay": "not defined while Monday range is forming",
        "availability_rule": "monday_range_complete and intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "monday_low_taken_before_evaluation",
        "family": "monday_range",
        "definition": "post-Monday bars before evaluation have traded at or below completed Monday low",
        "source_timeframe": "one minute",
        "observation_cutoff": "strictly before evaluation",
        "required_lookback": "completed Monday plus current week path",
        "confirmation_delay": "not defined while Monday range is forming",
        "availability_rule": "monday_range_complete and intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "daily_structure_w2",
        "family": "htf_swing_structure",
        "definition": "HH+HL=+1, LH+LL=-1, otherwise 0 using confirmed daily pivots of width 2",
        "source_timeframe": "eligible New York weekday",
        "observation_cutoff": "confirmed pivots only",
        "required_lookback": "two confirmed highs and two confirmed lows",
        "confirmation_delay": "two complete right-side daily bars",
        "availability_rule": "daily_structure_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "daily_structure_w3",
        "family": "htf_swing_structure",
        "definition": "sensitivity structure using confirmed daily pivots of width 3",
        "source_timeframe": "eligible New York weekday",
        "observation_cutoff": "confirmed pivots only",
        "required_lookback": "two confirmed highs and two confirmed lows",
        "confirmation_delay": "three complete right-side daily bars",
        "availability_rule": "daily_structure_w3_available_at <= evaluation_timestamp",
        "test_classification": "sensitivity",
    },
    {
        "feature": "h4_structure_w2",
        "family": "htf_swing_structure",
        "definition": "HH+HL=+1, LH+LL=-1, otherwise 0 using confirmed UTC-aligned 4H pivots of width 2",
        "source_timeframe": "4H",
        "observation_cutoff": "confirmed closed pivots only",
        "required_lookback": "two confirmed highs and two confirmed lows",
        "confirmation_delay": "two completed right-side 4H bars",
        "availability_rule": "h4_structure_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "h4_structure_w3",
        "family": "htf_swing_structure",
        "definition": "sensitivity structure using confirmed 4H pivots of width 3",
        "source_timeframe": "4H",
        "observation_cutoff": "confirmed closed pivots only",
        "required_lookback": "two confirmed highs and two confirmed lows",
        "confirmation_delay": "three completed right-side 4H bars",
        "availability_rule": "h4_structure_w3_available_at <= evaluation_timestamp",
        "test_classification": "sensitivity",
    },
    {
        "feature": "daily_displacement_direction",
        "family": "htf_displacement",
        "definition": "direction of latest eligible daily candle meeting body/range, range/prior ATR14 and outer-close rules",
        "source_timeframe": "eligible New York weekday",
        "observation_cutoff": "latest completed eligible day",
        "required_lookback": "14 prior eligible daily true ranges",
        "confirmation_delay": "daily candle completion",
        "availability_rule": "daily_displacement_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "h4_displacement_direction",
        "family": "htf_displacement",
        "definition": "direction of latest completed 4H candle meeting body/range, range/prior ATR14 and outer-close rules",
        "source_timeframe": "4H",
        "observation_cutoff": "latest completed 4H bar",
        "required_lookback": "14 prior 4H true ranges",
        "confirmation_delay": "4H candle completion",
        "availability_rule": "h4_displacement_available_at <= evaluation_timestamp",
        "test_classification": "preregistered",
    },
    {
        "feature": "swing_range_position",
        "family": "premium_discount",
        "definition": "position between latest confirmed external HTF swing low and high",
        "source_timeframe": "daily confirmed swings",
        "observation_cutoff": "confirmed pivots only",
        "required_lookback": "latest confirmed high and low",
        "confirmation_delay": "same as pivot confirmation",
        "availability_rule": "daily_structure_available_at <= evaluation_timestamp",
        "test_classification": "exploratory",
    },
    {
        "feature": "prior_return_120m_bps",
        "family": "baseline",
        "definition": "log return from last completed mid close at or before evaluation-120m to evaluation mid-open",
        "source_timeframe": "one minute",
        "observation_cutoff": "evaluation timestamp",
        "required_lookback": "120 minutes",
        "confirmation_delay": "none beyond completed source bars",
        "availability_rule": "intraday_cutoff_at <= evaluation_timestamp",
        "test_classification": "baseline",
    },
    {
        "feature": "news_0830",
        "family": "news_context",
        "definition": "official timing-only calendar indicates at least one 08:30 New York release",
        "source_timeframe": "official calendar",
        "observation_cutoff": "schedule fixed before market evaluation",
        "required_lookback": "none",
        "confirmation_delay": "none",
        "availability_rule": "calendar is point-in-time timing register; no actual/consensus values used",
        "test_classification": "baseline/control",
    },
)


OUTCOME_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "outcome": "forward_return_bps_{horizon}",
        "definition": "10,000 * log(last mid-close in [evaluation, endpoint) / evaluation mid-open)",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint",
    },
    {
        "outcome": "direction_{horizon}",
        "definition": "+1 above +0.5 bps, -1 below -0.5 bps, 0 within the preregistered neutral band",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint",
    },
    {
        "outcome": "up/down_excursion_bps_{horizon}",
        "definition": "maximum mid-high rise and maximum mid-low fall from evaluation price; no stop or target assumption",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint",
    },
    {
        "outcome": "reaches_{level}_{horizon}",
        "definition": "subsequent mid-price range touches PDH/PDL/PWH/PWL/Monday high/Monday low known at evaluation",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint; unknown levels remain missing",
    },
    {
        "outcome": "range_expansion_bps_{horizon}",
        "definition": "10,000 * log(max mid-high / min mid-low) after evaluation",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint",
    },
    {
        "outcome": "realized_volatility_bps_{horizon}",
        "definition": "10,000 * square root of summed squared one-minute mid-close log returns",
        "horizons": ["30m", "60m", "120m", "session_end_1200"],
        "availability": "only after the named endpoint",
    },
)


CANDIDATE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "candidate": "MODEL_A_STRUCTURE_ONLY",
        "families": ["htf_swing_structure"],
        "definition": "daily-width-2 and 4H-width-2 structure agree; one non-neutral timeframe may stand when the other is neutral; disagreement is neutral",
        "thresholds": {},
        "test_classification": "preregistered",
    },
    {
        "candidate": "MODEL_B_RANGE_LOCATION_ONLY",
        "families": ["prior_day_location", "prior_week_location"],
        "definition": "direction of the equally averaged centered prior-day/prior-week positions with a +/-0.10 neutral zone",
        "thresholds": {"neutral_zone": 0.10},
        "test_classification": "preregistered",
    },
    {
        "candidate": "MODEL_C_LIQUIDITY_POSITION_ONLY",
        "families": ["prior_day_location", "prior_week_location", "monday_range"],
        "definition": "direction toward the nearest not-yet-touched known upper/lower external level; equal distance is neutral",
        "thresholds": {},
        "test_classification": "preregistered",
    },
    {
        "candidate": "MODEL_D_DISPLACEMENT_CONTEXT_ONLY",
        "families": ["htf_displacement"],
        "definition": "daily and 4H displacement directions agree; one qualifying timeframe may stand when the other is neutral; disagreement is neutral",
        "thresholds": {"body_fraction": 0.60, "range_over_prior_atr14": 1.25, "outer_close_fraction": 0.25},
        "test_classification": "preregistered",
    },
    {
        "candidate": "MODEL_E_SIMPLE_COMPOSITE",
        "families": ["development-qualified A-D only"],
        "definition": "unweighted majority vote of A-D candidates passing the frozen development gate; ties are neutral and no family receives a discretionary weight",
        "thresholds": {},
        "test_classification": "preregistered conditional composite",
    },
)


DECISION_RULES = {
    "primary_outcome": "forward_return_bps_60m",
    "minimum_directional_observations_per_partition": 80,
    "minimum_long_and_short_observations": 25,
    "standalone_value": {
        "mean_aligned_return_bps": "> 0",
        "bootstrap_95pct_lower_bound": "> 0",
        "standardized_effect_size": ">= 0.10",
        "directional_accuracy": ">= 0.52",
        "long_short_symmetry": "both directional sides have positive aligned mean",
    },
    "incremental_value": {
        "baseline": "best development directional accuracy among evaluation-time, day-of-week, news, additive timing, and prior-momentum baselines",
        "bootstrap_95pct_lower_accuracy_lift": "> 0",
    },
    "robustness": "positive aligned mean in at least 70% of adequate preregistered strata/sensitivities",
    "proceed": "at least one frozen candidate passes development, validation and untouched holdout standalone+incremental gates, robustness, symmetry and temporal consistency",
    "proceed_with_caution": "same-direction validation/holdout evidence exists but uncertainty, robustness, or history breadth misses the full proceed gate",
    "inconclusive": "data breadth, sample adequacy, or uncertainty prevents a reliable accept/reject decision",
    "reject": "adequate data exist but no candidate has positive stable validation and holdout evidence under the registered definitions",
    "history_confidence_cap": "fewer than two complete years prevents PROCEED and year-stability claims",
}


DEFERRED_FEATURE_FAMILIES = (
    {
        "family": "htf_imbalance_or_delivery_array_proximity",
        "status": "deferred",
        "reason": "No separately validated timestamp-safe HTF object detector exists; importing entry-oriented FVG/array logic would violate the Phase 1 layer boundary.",
    },
)


CONTINUOUS_FEATURES: tuple[str, ...] = (
    "prior_day_position",
    "distance_to_pdh_range",
    "distance_to_pdl_range",
    "prior_week_position",
    "distance_to_pwh_range",
    "distance_to_pwl_range",
    "monday_position",
    "swing_range_position",
    "prior_return_120m_bps",
    "prior_atr14_bps",
)


CANDIDATE_COLUMNS = {
    "MODEL_A_STRUCTURE_ONLY": "candidate_a",
    "MODEL_B_RANGE_LOCATION_ONLY": "candidate_b",
    "MODEL_C_LIQUIDITY_POSITION_ONLY": "candidate_c",
    "MODEL_D_DISPLACEMENT_CONTEXT_ONLY": "candidate_d",
    "MODEL_E_SIMPLE_COMPOSITE": "candidate_e",
}
