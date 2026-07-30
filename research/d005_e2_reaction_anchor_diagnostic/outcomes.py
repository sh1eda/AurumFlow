"""Downstream-only anchor and latency outcomes for D005_E2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from research.context_engine.config import local_bounds
from research.d005_e1_context_engine_empirical.outcomes import _ExtremumTree

from .config import ReactionAnchorDiagnosticConfig


ANCHOR_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("poi_or_sweep_close", "candidate_at", "close"),
    ("mss_confirmation_close", "mss_confirmed_at", "close"),
    (
        "displacement_confirmation_close",
        "displacement_confirmed_at",
        "close",
    ),
    ("refinement_creation_close", "refinement_created_at", "close"),
    (
        "refinement_interaction_reference",
        "refinement_interacted_at",
        "refinement_interaction_price",
    ),
    (
        "refinement_interaction_close",
        "refinement_interacted_at",
        "refinement_interaction_close",
    ),
    (
        "reaction_confirmed_close",
        "d005_reaction_confirmed_at",
        "close",
    ),
)


def build_anchor_inventory(
    sequences: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sequence in sequences.to_dict("records"):
        for anchor_type, timestamp_field, price_basis in ANCHOR_FIELDS:
            anchor_at = sequence.get(timestamp_field)
            if anchor_at is None or pd.isna(anchor_at):
                continue
            override = (
                sequence.get(price_basis)
                if price_basis != "close"
                else np.nan
            )
            rows.append(
                {
                    "sequence_id": sequence["sequence_id"],
                    "population": sequence["population"],
                    "mapping_variant": sequence["mapping_variant"],
                    "sequence_status": sequence.get("sequence_status"),
                    "sequence_cohort": sequence.get("sequence_cohort"),
                    "engine_selected_reaction_confirmed": bool(
                        sequence.get(
                            "engine_selected_reaction_confirmed", False
                        )
                    ),
                    "outcome": sequence["outcome"],
                    "candidate_type": sequence["candidate_type"],
                    "candidate_source": sequence["candidate_source"],
                    "candidate_variant": sequence["candidate_variant"],
                    "candidate_taxonomy": sequence["candidate_taxonomy"],
                    "refinement_type": sequence.get("refinement_type"),
                    "refinement_variant": sequence.get(
                        "refinement_variant"
                    ),
                    "pmh_pml": sequence.get("pmh_pml", False),
                    "anchor_type": anchor_type,
                    "anchor_at": pd.Timestamp(anchor_at),
                    "direction": int(
                        sequence.get("final_d005_direction", 0)
                        or sequence.get("candidate_direction", 0)
                        or 0
                    ),
                    "anchor_price_basis": price_basis,
                    "anchor_price_override": override,
                }
            )
    return pd.DataFrame.from_records(rows)


def calculate_forward_outcomes(
    anchors: pd.DataFrame,
    one_minute: pd.DataFrame,
    *,
    config: ReactionAnchorDiagnosticConfig,
) -> pd.DataFrame:
    """Calculate causal price paths from each independently retained anchor."""

    if anchors.empty:
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
    for anchor in anchors.to_dict("records"):
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
            mfe_at = pd.Timestamp(available[mfe_position])
            mae_at = pd.Timestamp(available[mae_position])
            record = {
                **anchor,
                "anchor_at": anchor_at,
                "anchor_price": anchor_price,
                "horizon": horizon,
                "horizon_at": horizon_at,
                "observed_until": pd.Timestamp(available[end]),
                "end_price": float(closes[end]),
                "signed_forward_movement": (
                    float(closes[end]) - anchor_price
                )
                * direction,
                "mfe": float(mfe),
                "mae": float(mae),
                "mfe_mae_ratio": (
                    float(mfe / mae) if mae > 0 else np.nan
                ),
                "adverse_before_favorable": bool(
                    mae_position < mfe_position
                ),
                "time_to_mfe_minutes": (
                    mfe_at - anchor_at
                ).total_seconds()
                / 60.0,
                "time_to_mae_minutes": (
                    mae_at - anchor_at
                ).total_seconds()
                / 60.0,
                "outcome_is_downstream_only": True,
            }
            for threshold in config.mfe_price_thresholds:
                label = str(threshold).replace(".", "_")
                record[f"mfe_ge_{label}"] = bool(mfe >= threshold)
            rows.append(record)
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


def sequence_latency_outcomes(
    sequences: pd.DataFrame,
    one_minute: pd.DataFrame,
) -> pd.DataFrame:
    """Measure stage latency and movement already consumed by later anchors."""

    available = pd.DatetimeIndex(
        pd.to_datetime(one_minute["available_at"], utc=True)
    )
    available_ns = available.as_unit("ns").asi8
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    highs = one_minute["high"].to_numpy(dtype=float, copy=False)
    lows = one_minute["low"].to_numpy(dtype=float, copy=False)
    high_tree = _ExtremumTree(highs, maximum=True)
    low_tree = _ExtremumTree(lows, maximum=False)
    pairs = (
        ("event_to_mss", "candidate_at", "mss_confirmed_at"),
        (
            "mss_to_displacement",
            "mss_confirmed_at",
            "displacement_confirmed_at",
        ),
        (
            "displacement_to_refinement_creation",
            "displacement_confirmed_at",
            "refinement_created_at",
        ),
        (
            "refinement_creation_to_first_interaction",
            "refinement_created_at",
            "refinement_interacted_at",
        ),
        (
            "first_interaction_to_reaction_confirmed",
            "refinement_interacted_at",
            "d005_reaction_confirmed_at",
        ),
    )
    rows: list[dict[str, object]] = []
    for sequence in sequences.to_dict("records"):
        direction = int(
            sequence.get("final_d005_direction", 0)
            or sequence.get("candidate_direction", 0)
            or 0
        )
        candidate = _price_at(
            sequence.get("candidate_at"), available_ns, closes
        )
        for label, left_field, right_field in pairs:
            left_value = sequence.get(left_field)
            right_value = sequence.get(right_field)
            left = _price_at(left_value, available_ns, closes)
            right = _price_at(right_value, available_ns, closes)
            if left is None or right is None:
                continue
            left_position, left_price = left
            right_position, right_price = right
            elapsed = (
                pd.Timestamp(right_value) - pd.Timestamp(left_value)
            ).total_seconds() / 60.0
            record = {
                "sequence_id": sequence["sequence_id"],
                "population": sequence["population"],
                "mapping_variant": sequence["mapping_variant"],
                "outcome": sequence["outcome"],
                "candidate_type": sequence["candidate_type"],
                "candidate_variant": sequence["candidate_variant"],
                "refinement_type": sequence.get("refinement_type"),
                "refinement_variant": sequence.get(
                    "refinement_variant"
                ),
                "latency_stage": label,
                "from_at": pd.Timestamp(left_value),
                "to_at": pd.Timestamp(right_value),
                "elapsed_minutes": elapsed,
                "timestamp_order_valid": elapsed >= 0,
                "signed_stage_movement": (
                    right_price - left_price
                )
                * direction,
            }
            if (
                candidate is not None
                and right_position > candidate[0]
            ):
                candidate_position, candidate_price = candidate
                maximum, _ = high_tree.query(
                    candidate_position + 1, right_position + 1
                )
                minimum, _ = low_tree.query(
                    candidate_position + 1, right_position + 1
                )
                if direction > 0:
                    consumed_mfe = maximum - candidate_price
                    consumed_mae = candidate_price - minimum
                else:
                    consumed_mfe = candidate_price - minimum
                    consumed_mae = maximum - candidate_price
                record["candidate_to_stage_mfe_consumed"] = float(
                    consumed_mfe
                )
                record["candidate_to_stage_mae_consumed"] = float(
                    consumed_mae
                )
                record["candidate_to_stage_signed_movement"] = (
                    right_price - candidate_price
                ) * direction
            else:
                record["candidate_to_stage_mfe_consumed"] = np.nan
                record["candidate_to_stage_mae_consumed"] = np.nan
                record["candidate_to_stage_signed_movement"] = np.nan
            rows.append(record)
    return pd.DataFrame.from_records(rows)
