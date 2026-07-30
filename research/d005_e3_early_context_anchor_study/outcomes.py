"""Downstream-only price outcomes and latency paths for D005_E3."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.context_engine.config import local_bounds
from research.d005_e1_context_engine_empirical.outcomes import (
    _ExtremumTree,
    add_causal_volatility_regime,
)

from .config import EarlyContextAnchorStudyConfig


def annotate_anchor_volatility(
    anchors: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Use only completed daily ranges available by each anchor."""

    return add_causal_volatility_regime(anchors, daily, config)


def calculate_forward_outcomes(
    anchors: pd.DataFrame,
    one_minute: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Calculate causal descriptive paths from each independent anchor."""

    eligible = anchors[
        anchors["main_scope_eligible"]
        & anchors["anchor_causally_observable"]
        & ~anchors["anchor_selected_using_later_completion"]
    ].copy()
    if eligible.empty:
        return pd.DataFrame()
    available = pd.DatetimeIndex(
        pd.to_datetime(one_minute["available_at"], utc=True)
    )
    available_ns = available.as_unit("ns").asi8
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    highs = one_minute["high"].to_numpy(dtype=float, copy=False)
    lows = one_minute["low"].to_numpy(dtype=float, copy=False)
    high_tree = _ExtremumTree(highs, maximum=True)
    low_tree = _ExtremumTree(lows, maximum=False)
    rows: list[dict[str, object]] = []
    for anchor in eligible.to_dict("records"):
        anchor_at = pd.Timestamp(anchor["anchor_at"]).tz_convert("UTC")
        position = int(
            np.searchsorted(available_ns, anchor_at.value, side="right")
        ) - 1
        if position < 0:
            continue
        override = anchor.get("anchor_price_override")
        anchor_price = (
            float(override)
            if override is not None and not pd.isna(override)
            else float(closes[position])
        )
        direction = int(anchor["direction"])
        local_date = anchor_at.tz_convert(config.timezone).date()
        noon, _ = local_bounds(
            local_date, "12:00", "12:00", config.timezone
        )
        close_at, _ = local_bounds(
            local_date,
            config.day_end_clock,
            config.day_end_clock,
            config.timezone,
        )
        horizons = [
            (
                f"{minutes}m",
                anchor_at + pd.Timedelta(minutes=minutes),
            )
            for minutes in config.forward_minutes
        ]
        if anchor_at < noon:
            horizons.append(("ny_noon", noon))
        if anchor_at < close_at:
            horizons.append(("trading_day_close", close_at))
        for horizon, horizon_at in horizons:
            end = int(
                np.searchsorted(
                    available_ns, horizon_at.value, side="right"
                )
            ) - 1
            if end <= position:
                continue
            left = position + 1
            right = end + 1
            maximum, maximum_position = high_tree.query(left, right)
            minimum, minimum_position = low_tree.query(left, right)
            if direction > 0:
                mfe = maximum - anchor_price
                mae = anchor_price - minimum
                mfe_position = maximum_position
                mae_position = minimum_position
            else:
                mfe = anchor_price - minimum
                mae = maximum - anchor_price
                mfe_position = minimum_position
                mae_position = maximum_position
            signed = (float(closes[end]) - anchor_price) * direction
            rows.append(
                {
                    **anchor,
                    "anchor_at": anchor_at,
                    "anchor_price": anchor_price,
                    "horizon": horizon,
                    "horizon_at": horizon_at,
                    "observed_until": pd.Timestamp(available[end]),
                    "end_price": float(closes[end]),
                    "signed_forward_movement": signed,
                    "win": bool(signed > 0),
                    "mfe": float(mfe),
                    "mae": float(mae),
                    "mfe_mae_ratio": (
                        float(mfe / mae) if mae > 0 else np.nan
                    ),
                    "adverse_before_favorable": bool(
                        mae_position < mfe_position
                    ),
                    "time_to_mfe_minutes": (
                        pd.Timestamp(available[mfe_position]) - anchor_at
                    ).total_seconds()
                    / 60.0,
                    "time_to_mae_minutes": (
                        pd.Timestamp(available[mae_position]) - anchor_at
                    ).total_seconds()
                    / 60.0,
                    "outcome_is_downstream_only": True,
                    "pnl_calculated": False,
                    "entry_assumed": False,
                }
            )
    return pd.DataFrame.from_records(rows)


def _price_at(
    timestamp: object,
    available_ns: np.ndarray,
    closes: np.ndarray,
) -> tuple[int, float] | None:
    if timestamp is None or pd.isna(timestamp):
        return None
    stamp = pd.Timestamp(timestamp).tz_convert("UTC")
    position = int(
        np.searchsorted(available_ns, stamp.value, side="right")
    ) - 1
    if position < 0:
        return None
    return position, float(closes[position])


def build_latency_decay(
    anchors: pd.DataFrame,
    one_minute: pd.DataFrame,
) -> pd.DataFrame:
    """Retain exact stage latency and candidate-to-stage consumed movement."""

    available = pd.DatetimeIndex(
        pd.to_datetime(one_minute["available_at"], utc=True)
    )
    available_ns = available.as_unit("ns").asi8
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    highs = one_minute["high"].to_numpy(dtype=float, copy=False)
    lows = one_minute["low"].to_numpy(dtype=float, copy=False)
    high_tree = _ExtremumTree(highs, maximum=True)
    low_tree = _ExtremumTree(lows, maximum=False)
    lookup = {
        (str(row.sequence_id), str(row.anchor_type)): row
        for row in anchors.itertuples()
    }
    sequence_ids = anchors["sequence_id"].drop_duplicates()
    rows: list[dict[str, object]] = []
    array_types = (
        "first_aligned_raw_fvg_creation",
        "first_context_qualified_fvg_creation",
        "qualifying_ob_consecutive_block_creation",
        "qualifying_ob_last_opposing_candle_creation",
        "qualifying_ob_inefficiency_break_origin_creation",
        "refinement_array_creation",
    )
    for sequence_id in sequence_ids:
        sequence_key = str(sequence_id)
        candidate = lookup.get(
            (sequence_key, "candidate_context_creation")
        )
        if candidate is None:
            continue
        origin = lookup.get((sequence_key, "htf_poi_interaction"))
        if origin is None:
            origin = lookup.get((sequence_key, "named_liquidity_sweep"))
        pairs: list[tuple[str, object, object]] = [
            ("origin_to_candidate", origin, candidate),
            (
                "candidate_to_mss",
                candidate,
                lookup.get(
                    (sequence_key, "mss_body_close_confirmation")
                ),
            ),
            (
                "mss_to_displacement",
                lookup.get(
                    (sequence_key, "mss_body_close_confirmation")
                ),
                lookup.get(
                    (sequence_key, "displacement_confirmation")
                ),
            ),
        ]
        displacement = lookup.get(
            (sequence_key, "displacement_confirmation")
        )
        pairs.extend(
            (
                f"displacement_to_{anchor_type}",
                displacement,
                lookup.get((sequence_key, anchor_type)),
            )
            for anchor_type in array_types
        )
        pairs.extend(
            [
                (
                    "refinement_creation_to_first_interaction",
                    lookup.get(
                        (sequence_key, "refinement_array_creation")
                    ),
                    lookup.get(
                        (
                            sequence_key,
                            "refinement_array_first_interaction",
                        )
                    ),
                ),
                (
                    "first_interaction_to_reaction_confirmed",
                    lookup.get(
                        (
                            sequence_key,
                            "refinement_array_first_interaction",
                        )
                    ),
                    lookup.get((sequence_key, "reaction_confirmed")),
                ),
            ]
        )
        candidate_price = _price_at(
            candidate.anchor_at, available_ns, closes
        )
        if candidate_price is None:
            continue
        candidate_position, candidate_close = candidate_price
        direction = int(candidate.direction)
        for stage, left_anchor, right_anchor in pairs:
            if left_anchor is None or right_anchor is None:
                continue
            left_price_result = _price_at(
                left_anchor.anchor_at, available_ns, closes
            )
            right_price_result = _price_at(
                right_anchor.anchor_at, available_ns, closes
            )
            if left_price_result is None or right_price_result is None:
                continue
            left_position, left_close = left_price_result
            right_position, right_close = right_price_result
            left_override = getattr(
                left_anchor, "anchor_price_override", np.nan
            )
            right_override = getattr(
                right_anchor, "anchor_price_override", np.nan
            )
            if not pd.isna(left_override):
                left_close = float(left_override)
            if not pd.isna(right_override):
                right_close = float(right_override)
            consumed_right = max(candidate_position + 1, right_position + 1)
            if consumed_right > candidate_position + 1:
                maximum, _ = high_tree.query(
                    candidate_position + 1, consumed_right
                )
                minimum, _ = low_tree.query(
                    candidate_position + 1, consumed_right
                )
                if direction > 0:
                    mfe_consumed = maximum - candidate_close
                    mae_consumed = candidate_close - minimum
                else:
                    mfe_consumed = candidate_close - minimum
                    mae_consumed = maximum - candidate_close
            else:
                mfe_consumed = 0.0
                mae_consumed = 0.0
            left_at = pd.Timestamp(left_anchor.anchor_at)
            right_at = pd.Timestamp(right_anchor.anchor_at)
            rows.append(
                {
                    "sequence_id": sequence_key,
                    "mapping_variant": candidate.mapping_variant,
                    "outcome": candidate.outcome,
                    "direction": direction,
                    "latency_stage": stage,
                    "left_anchor_type": left_anchor.anchor_type,
                    "right_anchor_type": right_anchor.anchor_type,
                    "left_anchor_id": left_anchor.anchor_id,
                    "right_anchor_id": right_anchor.anchor_id,
                    "left_at": left_at,
                    "right_at": right_at,
                    "elapsed_minutes": (
                        right_at - left_at
                    ).total_seconds()
                    / 60.0,
                    "timestamp_order_valid": bool(right_at >= left_at),
                    "signed_stage_movement": (
                        right_close - left_close
                    )
                    * direction,
                    "candidate_to_stage_signed_movement": (
                        right_close - candidate_close
                    )
                    * direction,
                    "candidate_to_stage_mfe_consumed": float(
                        mfe_consumed
                    ),
                    "candidate_to_stage_mae_incurred": float(
                        mae_consumed
                    ),
                    "later_engine_confirmed": bool(
                        candidate.later_engine_confirmed
                    ),
                    "retrospective_terminal_class": (
                        candidate.retrospective_terminal_class
                    ),
                }
            )
    return pd.DataFrame.from_records(rows)

