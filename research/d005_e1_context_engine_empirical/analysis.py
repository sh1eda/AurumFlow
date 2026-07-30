"""Descriptive state, gate, array, and stability analyses for D005_E1."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from research.context_engine.bars import TIMEFRAME_MINUTES
from research.context_engine.models import ContextState

from .config import EmpiricalStudyConfig
from .outcomes import _ExtremumTree, session_label


ALL_STATES = tuple(item.value for item in ContextState)


GATE_MAP: dict[str, tuple[str, ...]] = {
    "parent_child_direction_conflict": ("parent_child_conflict",),
    "candidate_opposes_parent": ("parent_child_conflict",),
    "reaction_confirmation_absent": ("missing_reaction",),
    "no_qualified_context_event": ("missing_reaction",),
    "body_close_mss_absent": ("mss_failure", "missing_reaction"),
    "measurable_displacement_absent": (
        "displacement_failure",
        "missing_reaction",
    ),
    "lower_timeframe_refinement_absent": (
        "missing_refinement",
        "no_aligned_fvg_or_zone",
    ),
    "trapped_between_opposing_arrays": (
        "trapped_between_opposing_arrays",
    ),
    "range_boundaries_unresolved": ("unresolved_range",),
    "move_overextended": ("overextension",),
    "proposed_risk_invalid": ("invalid_risk",),
}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [value]


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def gate_attribution(
    snapshots: pd.DataFrame,
    *,
    config: EmpiricalStudyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Emit non-exclusive gate rows plus observed overlap combinations."""

    rows: list[dict[str, object]] = []
    for snapshot in snapshots.to_dict("records"):
        if snapshot["state"] not in {
            "neutral",
            "conflict",
            "invalidated",
            "candidate_poi",
            "candidate_liquidity_event",
            "provisional_context",
        }:
            continue
        reasons = [str(item) for item in _as_list(snapshot["no_trade_reasons"])]
        gates: set[str] = set()
        for reason in reasons:
            if reason.startswith("missing_required_"):
                gates.add("missing_data")
            gates.update(GATE_MAP.get(reason, ()))
        transitions = _as_list(snapshot.get("transitions"))
        candidate_at: pd.Timestamp | None = None
        for transition in transitions:
            if not isinstance(transition, Mapping):
                continue
            if transition.get("to_state") in {
                "candidate_poi",
                "candidate_liquidity_event",
            }:
                candidate_at = pd.Timestamp(transition["occurred_at"])
        if (
            candidate_at is not None
            and "mss_failure" in gates
            and pd.Timestamp(snapshot["evaluation_at"])
            > candidate_at
            + pd.Timedelta(
                minutes=int(snapshot["reaction_minutes"])
                * int(snapshot["confirmation_timeout_bars"])
            )
        ):
            gates.add("candidate_timeout")
        local_clock = snapshot.get("observation_clock")
        if (
            local_clock in {"08:30", "09:00"}
            and int(snapshot.get("parent_direction", 0)) == 0
            and not bool(snapshot.get("balanced_ranging", False))
        ):
            gates.add("pmh_pml_prerequisite_failure")
        if not gates and snapshot["state"] != "reaction_confirmed":
            gates.add("unattributed_neutral_or_provisional")
        for gate in sorted(gates):
            rows.append(
                {
                    "snapshot_id": snapshot["snapshot_id"],
                    "evaluation_at": snapshot["evaluation_at"],
                    "session_date": snapshot["session_date"],
                    "mode": snapshot["mode"],
                    "mapping_variant": snapshot["mapping_variant"],
                    "state": snapshot["state"],
                    "gate": gate,
                    "exact_engine_reasons": reasons,
                }
            )
    attribution = pd.DataFrame.from_records(rows)
    if attribution.empty:
        return attribution, pd.DataFrame()
    combinations = (
        attribution.groupby("snapshot_id", sort=False)["gate"]
        .agg(lambda values: "|".join(sorted(set(values))))
        .rename("gate_combination")
        .reset_index()
        .merge(
            snapshots[
                [
                    "snapshot_id",
                    "mode",
                    "mapping_variant",
                    "session_date",
                ]
            ],
            on="snapshot_id",
            how="left",
            validate="one_to_one",
        )
    )
    overlap = (
        combinations.groupby(
            ["mode", "mapping_variant", "gate_combination"],
            dropna=False,
        )
        .size()
        .rename("snapshot_count")
        .reset_index()
    )
    return attribution, overlap


def flatten_transitions(
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """Flatten and deduplicate the within-snapshot evidence paths."""

    records: dict[str, dict[str, object]] = {}
    for snapshot in snapshots.to_dict("records"):
        previous_at: pd.Timestamp | None = None
        for transition in _as_list(snapshot.get("transitions")):
            if not isinstance(transition, Mapping):
                continue
            occurred = pd.Timestamp(transition["occurred_at"])
            transition_id = _stable_id(
                snapshot["mapping_variant"],
                transition["from_state"],
                transition["to_state"],
                occurred,
                transition.get("reason"),
                tuple(_as_list(transition.get("evidence_ids"))),
            )
            elapsed = (
                (occurred - previous_at).total_seconds() / 60.0
                if previous_at is not None
                else np.nan
            )
            record = {
                "transition_id": transition_id,
                "snapshot_id": snapshot["snapshot_id"],
                "evaluation_at": snapshot["evaluation_at"],
                "occurred_at": occurred,
                "session_date": occurred.tz_convert(
                    snapshot["timezone"]
                ).date().isoformat(),
                "mode": snapshot["mode"],
                "mapping_variant": snapshot["mapping_variant"],
                "from_state": transition["from_state"],
                "to_state": transition["to_state"],
                "reason": transition.get("reason"),
                "evidence_ids": _as_list(transition.get("evidence_ids")),
                "direction": (
                    int(snapshot["direction"])
                    if int(snapshot["direction"])
                    else int(snapshot["parent_direction"])
                ),
                "outcome": snapshot.get("outcome", "neutral"),
                "elapsed_minutes_from_prior_stage": elapsed,
                "elapsed_reaction_bars_from_prior_stage": (
                    elapsed / float(snapshot["reaction_minutes"])
                    if np.isfinite(elapsed)
                    else np.nan
                ),
                "transition_kind": "engine_path",
            }
            existing = records.get(transition_id)
            if existing is None or snapshot["mode"] == "event_driven":
                records[transition_id] = record
            previous_at = occurred

        candidate_transitions = [
            item
            for item in _as_list(snapshot.get("transitions"))
            if isinstance(item, Mapping)
            and item.get("to_state")
            in {"candidate_poi", "candidate_liquidity_event"}
        ]
        reasons = set(
            str(item) for item in _as_list(snapshot.get("no_trade_reasons"))
        )
        if candidate_transitions and reasons.intersection(
            {
                "body_close_mss_absent",
                "measurable_displacement_absent",
                "reaction_confirmation_absent",
            }
        ):
            candidate = candidate_transitions[-1]
            candidate_at = pd.Timestamp(candidate["occurred_at"])
            timeout_at = candidate_at + pd.Timedelta(
                minutes=int(snapshot["reaction_minutes"])
                * int(snapshot["confirmation_timeout_bars"])
            )
            evaluation_at = pd.Timestamp(snapshot["evaluation_at"])
            if evaluation_at >= timeout_at:
                transition_id = _stable_id(
                    snapshot["mapping_variant"],
                    candidate["to_state"],
                    "timeout",
                    timeout_at,
                )
                records[transition_id] = {
                    "transition_id": transition_id,
                    "snapshot_id": snapshot["snapshot_id"],
                    "evaluation_at": evaluation_at,
                    "occurred_at": timeout_at,
                    "session_date": timeout_at.tz_convert(
                        snapshot["timezone"]
                    ).date().isoformat(),
                    "mode": snapshot["mode"],
                    "mapping_variant": snapshot["mapping_variant"],
                    "from_state": candidate["to_state"],
                    "to_state": "timeout",
                    "reason": "candidate_confirmation_timeout",
                    "evidence_ids": _as_list(
                        candidate.get("evidence_ids")
                    ),
                    "direction": (
                        int(snapshot["direction"])
                        if int(snapshot["direction"])
                        else int(snapshot["parent_direction"])
                    ),
                    "outcome": snapshot.get("outcome", "neutral"),
                    "elapsed_minutes_from_prior_stage": (
                        timeout_at - candidate_at
                    ).total_seconds()
                    / 60.0,
                    "elapsed_reaction_bars_from_prior_stage": float(
                        snapshot["confirmation_timeout_bars"]
                    ),
                    "transition_kind": "derived_timeout_observation",
                }

    # D005 evaluations are intentionally stateless. This study therefore
    # observes the first later invalidation after each reaction confirmation
    # without feeding that relationship back into the engine.
    ordered = snapshots.sort_values(
        ["mapping_variant", "evaluation_at", "mode"],
        kind="mergesort",
    )
    for mapping_variant, group in ordered.groupby(
        "mapping_variant",
        sort=False,
    ):
        active_reaction: dict[str, object] | None = None
        for snapshot in group.to_dict("records"):
            reaction_paths = [
                item
                for item in _as_list(snapshot.get("transitions"))
                if isinstance(item, Mapping)
                and item.get("to_state") == "reaction_confirmed"
            ]
            if reaction_paths:
                path = reaction_paths[-1]
                active_reaction = {
                    "occurred_at": pd.Timestamp(path["occurred_at"]),
                    "snapshot": snapshot,
                    "evidence_ids": _as_list(path.get("evidence_ids")),
                }
            if (
                active_reaction is None
                or snapshot.get("state") != "invalidated"
            ):
                continue
            invalidated_at = pd.Timestamp(snapshot["evaluation_at"])
            reaction_at = pd.Timestamp(active_reaction["occurred_at"])
            if invalidated_at <= reaction_at:
                continue
            elapsed = (invalidated_at - reaction_at).total_seconds() / 60.0
            transition_id = _stable_id(
                mapping_variant,
                "reaction_confirmed",
                "later_invalidation",
                reaction_at,
                invalidated_at,
            )
            records[transition_id] = {
                "transition_id": transition_id,
                "snapshot_id": snapshot["snapshot_id"],
                "evaluation_at": invalidated_at,
                "occurred_at": invalidated_at,
                "session_date": snapshot["session_date"],
                "mode": snapshot["mode"],
                "mapping_variant": mapping_variant,
                "from_state": "reaction_confirmed",
                "to_state": "invalidated",
                "reason": "later_snapshot_invalidation",
                "evidence_ids": active_reaction["evidence_ids"],
                "direction": int(
                    active_reaction["snapshot"].get("direction", 0) or 0
                ),
                "outcome": active_reaction["snapshot"].get(
                    "outcome",
                    "neutral",
                ),
                "elapsed_minutes_from_prior_stage": elapsed,
                "elapsed_reaction_bars_from_prior_stage": (
                    elapsed / float(snapshot["reaction_minutes"])
                ),
                "transition_kind": "derived_later_observation",
            }
            active_reaction = None
    frame = pd.DataFrame.from_records(list(records.values()))
    if frame.empty:
        return frame
    return frame.sort_values(
        ["occurred_at", "mapping_variant", "transition_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def transition_funnel(transitions: pd.DataFrame) -> pd.DataFrame:
    if transitions.empty:
        return pd.DataFrame()
    frame = transitions.copy()
    frame["transition"] = (
        frame["from_state"].astype(str) + " -> " + frame["to_state"].astype(str)
    )
    return (
        frame.groupby(["mapping_variant", "transition"], dropna=False)
        .agg(
            transition_count=("transition_id", "nunique"),
            median_elapsed_minutes=(
                "elapsed_minutes_from_prior_stage",
                "median",
            ),
            median_elapsed_reaction_bars=(
                "elapsed_reaction_bars_from_prior_stage",
                "median",
            ),
        )
        .reset_index()
    )


def _state_summary(
    snapshots: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame()
    base = (
        snapshots.groupby(group_columns, dropna=False)
        .agg(
            snapshot_count=("snapshot_id", "nunique"),
            directional_count=("direction", lambda values: int((values != 0).sum())),
            entry_authorized_count=(
                "entry_authorized",
                lambda values: int(pd.Series(values).fillna(False).sum()),
            ),
        )
        .reset_index()
    )
    counts = (
        snapshots.groupby(group_columns + ["state"], dropna=False)
        .size()
        .unstack("state", fill_value=0)
        .reindex(columns=ALL_STATES, fill_value=0)
        .add_suffix("_count")
        .reset_index()
    )
    result = base.merge(counts, on=group_columns, how="left")
    for state in ALL_STATES:
        result[f"{state}_rate"] = (
            result[f"{state}_count"] / result["snapshot_count"]
        )
    return result


def bootstrap_reaction_rate(
    snapshots: pd.DataFrame,
    *,
    group_columns: list[str],
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    """Cluster bootstrap reaction-confirmed rate by local trading date."""

    rng = np.random.default_rng(config.bootstrap_seed)
    records: list[dict[str, object]] = []
    for keys, group in snapshots.groupby(group_columns, dropna=False):
        key_tuple = keys if isinstance(keys, tuple) else (keys,)
        daily = (
            group.assign(
                reaction=group["state"].eq("reaction_confirmed").astype(float)
            )
            .groupby("session_date")["reaction"]
            .mean()
            .to_numpy(dtype=float)
        )
        if not len(daily):
            continue
        estimates = np.empty(config.bootstrap_resamples, dtype=float)
        for position in range(config.bootstrap_resamples):
            estimates[position] = rng.choice(
                daily, size=len(daily), replace=True
            ).mean()
        records.append(
            {
                **dict(zip(group_columns, key_tuple, strict=True)),
                "reaction_confirmed_rate": float(daily.mean()),
                "bootstrap_ci_low": float(np.quantile(estimates, 0.025)),
                "bootstrap_ci_high": float(np.quantile(estimates, 0.975)),
                "bootstrap_trading_dates": int(len(daily)),
                "bootstrap_resamples": config.bootstrap_resamples,
            }
        )
    return pd.DataFrame.from_records(records)


def build_snapshot_summaries(
    snapshots: pd.DataFrame,
    *,
    config: EmpiricalStudyConfig,
) -> dict[str, pd.DataFrame]:
    frame = snapshots.copy()
    stamp = pd.to_datetime(frame["evaluation_at"], utc=True).dt.tz_convert(
        config.timezone
    )
    frame["year"] = stamp.dt.year
    frame["month"] = stamp.dt.strftime("%Y-%m")
    frame["session"] = stamp.map(
        lambda value: session_label(value, config.timezone)
    )
    frame["dst"] = stamp.map(
        lambda value: bool(value.dst() and value.dst().total_seconds())
    )
    annual = _state_summary(
        frame,
        ["year", "mode", "mapping_variant", "direction", "outcome"],
    )
    monthly = _state_summary(
        frame,
        ["month", "mode", "mapping_variant"],
    )
    regime = _state_summary(
        frame,
        [
            "volatility_regime",
            "mode",
            "mapping_variant",
            "direction",
            "outcome",
            "session",
            "dst",
        ],
    )
    mapping = _state_summary(
        frame,
        ["mode", "mapping_variant", "direction", "outcome"],
    )
    confidence = bootstrap_reaction_rate(
        frame,
        group_columns=["mode", "mapping_variant"],
        config=config,
    )
    confidence = confidence.drop(
        columns=["reaction_confirmed_rate"],
        errors="ignore",
    )
    mapping = mapping.merge(
        confidence,
        on=["mode", "mapping_variant"],
        how="left",
    )
    return {
        "annual_summary": annual,
        "monthly_summary": monthly,
        "regime_summary": regime,
        "mapping_summary": mapping,
    }


def _parse_parameters(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def fvg_event_statistics(
    events: pd.DataFrame,
    one_minute: pd.DataFrame,
    *,
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    """Separate raw/context flags and independently observe IFVG variants."""

    frame = events[events["event_type"].eq("raw_fvg")].copy()
    if frame.empty:
        return frame
    available_index = (
        pd.DatetimeIndex(one_minute.index) + pd.Timedelta(minutes=1)
    )
    available_ns = available_index.as_unit("ns").asi8
    highs = one_minute["high"].to_numpy(dtype=float, copy=False)
    lows = one_minute["low"].to_numpy(dtype=float, copy=False)
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    high_tree = _ExtremumTree(highs, maximum=True)
    low_tree = _ExtremumTree(lows, maximum=False)
    close_high_tree = _ExtremumTree(closes, maximum=True)
    close_low_tree = _ExtremumTree(closes, maximum=False)
    records: list[dict[str, object]] = []
    for record in frame.to_dict("records"):
        parameters = _parse_parameters(record.get("parameters"))
        available_at = pd.Timestamp(record["available_at"])
        start = int(
            np.searchsorted(
                available_ns, available_at.value, side="right"
            )
        )
        censor_at = available_at + pd.Timedelta(
            days=config.array_lifecycle_followup_days
        )
        end = int(
            np.searchsorted(available_ns, censor_at.value, side="right")
        )
        end = min(end, len(one_minute))
        direction = int(record["direction"])
        if direction > 0:
            threshold = np.nextafter(
                float(record["zone_low"]),
                -np.inf,
            )
            wick_position = low_tree.first_threshold(
                start,
                end,
                threshold,
            )
            close_position = close_low_tree.first_threshold(
                start,
                end,
                threshold,
            )
        else:
            threshold = np.nextafter(
                float(record["zone_high"]),
                np.inf,
            )
            wick_position = high_tree.first_threshold(
                start,
                end,
                threshold,
            )
            close_position = close_high_tree.first_threshold(
                start,
                end,
                threshold,
            )
        wick_at = (
            pd.Timestamp(available_index[wick_position])
            if wick_position >= 0
            else None
        )
        close_at = (
            pd.Timestamp(available_index[close_position])
            if close_position >= 0
            else None
        )
        records.append(
            {
                **record,
                "raw_fvg": True,
                "liquidity_qualified": bool(
                    parameters.get("liquidity_qualified", False)
                ),
                "mss_qualified": bool(
                    parameters.get("mss_qualified", False)
                ),
                "displacement_qualified": bool(
                    parameters.get("displacement_qualified", False)
                ),
                "context_qualified": bool(
                    parameters.get("context_qualified", False)
                ),
                "interacted": (
                    record.get("interacted_at") is not None
                    and not pd.isna(record.get("interacted_at"))
                ),
                "confirmed": (
                    record.get("confirmed_at") is not None
                    and not pd.isna(record.get("confirmed_at"))
                ),
                "invalidated": (
                    record.get("invalidated_at") is not None
                    and not pd.isna(record.get("invalidated_at"))
                ),
                "wick_violation_at": wick_at,
                "body_close_violation_at": close_at,
                "wick_ifvg": wick_at is not None,
                "body_close_ifvg": close_at is not None,
                "lifecycle_censor_at": censor_at,
                "lifecycle_censored": wick_at is None or close_at is None,
                "interaction_delay_minutes": (
                    (
                        pd.Timestamp(record["interacted_at"]) - available_at
                    ).total_seconds()
                    / 60.0
                    if record.get("interacted_at") is not None
                    and not pd.isna(record.get("interacted_at"))
                    else np.nan
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def order_block_event_statistics(
    events: pd.DataFrame,
    *,
    reaction_minutes_by_variant: Mapping[str, int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep all three OB variants separate and attach overlap diagnostics."""

    obs = events[events["event_type"].eq("order_block")].copy()
    if obs.empty:
        return obs, pd.DataFrame()
    fvgs = events[events["event_type"].eq("raw_fvg")].copy()
    sweeps = events[events["event_type"].eq("liquidity_sweep")].copy()
    obs["available_at"] = pd.to_datetime(obs["available_at"], utc=True)
    if not fvgs.empty:
        fvgs["available_at"] = pd.to_datetime(
            fvgs["available_at"],
            utc=True,
        )
    if not sweeps.empty:
        sweeps["available_at"] = pd.to_datetime(
            sweeps["available_at"],
            utc=True,
        )
    obs["zone_width"] = obs["zone_high"] - obs["zone_low"]
    obs["time_to_first_interaction_minutes"] = (
        pd.to_datetime(obs["interacted_at"], utc=True)
        - pd.to_datetime(obs["available_at"], utc=True)
    ).dt.total_seconds() / 60.0
    fvg_overlap: list[bool] = []
    liquidity_overlap: list[bool] = []
    fvg_groups: dict[
        tuple[str, int],
        tuple[np.ndarray, np.ndarray, np.ndarray],
    ] = {}
    for keys, group in fvgs.groupby(
        ["mapping_variant", "direction"],
        sort=False,
    ):
        ordered = group.sort_values("available_at")
        fvg_groups[(str(keys[0]), int(keys[1]))] = (
            pd.DatetimeIndex(ordered["available_at"])
            .as_unit("ns")
            .asi8,
            ordered["zone_low"].to_numpy(dtype=float),
            ordered["zone_high"].to_numpy(dtype=float),
        )
    sweep_groups: dict[tuple[str, int], np.ndarray] = {}
    for keys, group in sweeps.groupby(
        ["mapping_variant", "direction"],
        sort=False,
    ):
        sweep_groups[(str(keys[0]), int(keys[1]))] = (
            pd.DatetimeIndex(group["available_at"])
            .sort_values()
            .as_unit("ns")
            .asi8
        )
    for record in obs.to_dict("records"):
        mapping_variant = str(record["mapping_variant"])
        direction = int(record["direction"])
        parent_minutes = (
            7 * 24 * 60
            if mapping_variant.startswith("weekly")
            else 24 * 60
            if mapping_variant.startswith("daily")
            else 240
            if mapping_variant.startswith("4h")
            else 60
        )
        available = pd.Timestamp(record["available_at"])
        grouped_fvgs = fvg_groups.get((mapping_variant, direction))
        if grouped_fvgs is not None:
            times, lows, highs = grouped_fvgs
            window_ns = parent_minutes * 60_000_000_000
            left = int(
                np.searchsorted(
                    times,
                    available.value - window_ns,
                    side="left",
                )
            )
            right = int(
                np.searchsorted(
                    times,
                    available.value + window_ns,
                    side="right",
                )
            )
            fvg_overlap.append(
                bool(
                    (
                        (highs[left:right] >= float(record["zone_low"]))
                        & (
                            lows[left:right]
                            <= float(record["zone_high"])
                        )
                    ).any()
                )
            )
        else:
            fvg_overlap.append(False)
        reaction_minutes = reaction_minutes_by_variant[mapping_variant]
        grouped_sweeps = sweep_groups.get((mapping_variant, direction))
        if grouped_sweeps is not None:
            left_ns = (
                available.value
                - 12 * reaction_minutes * 60_000_000_000
            )
            left = int(
                np.searchsorted(grouped_sweeps, left_ns, side="left")
            )
            right = int(
                np.searchsorted(
                    grouped_sweeps,
                    available.value,
                    side="right",
                )
            )
            liquidity_overlap.append(right > left)
        else:
            liquidity_overlap.append(False)
    obs["overlap_with_fvg"] = fvg_overlap
    obs["overlap_with_liquidity_event"] = liquidity_overlap
    obs["interacted"] = obs["interacted_at"].notna()
    obs["confirmed"] = obs["confirmed_at"].notna()
    obs["invalidated"] = obs["invalidated_at"].notna()
    summary = (
        obs.groupby(["mapping_variant", "variant"], dropna=False)
        .agg(
            detection_count=("event_id", "nunique"),
            median_zone_width=("zone_width", "median"),
            median_time_to_first_interaction_minutes=(
                "time_to_first_interaction_minutes",
                "median",
            ),
            interaction_rate=("interacted", "mean"),
            reaction_confirmation_rate=("confirmed", "mean"),
            invalidation_rate=("invalidated", "mean"),
            fvg_overlap_rate=("overlap_with_fvg", "mean"),
            liquidity_overlap_rate=(
                "overlap_with_liquidity_event",
                "mean",
            ),
        )
        .reset_index()
    )
    return obs, summary


def fvg_category_summary(fvgs: pd.DataFrame) -> pd.DataFrame:
    """Summarize each requested FVG qualification independently."""

    if fvgs.empty:
        return pd.DataFrame()
    categories = {
        "raw_fvg": "raw_fvg",
        "liquidity_qualified_fvg": "liquidity_qualified",
        "mss_qualified_fvg": "mss_qualified",
        "displacement_qualified_fvg": "displacement_qualified",
        "fully_context_qualified_fvg": "context_qualified",
        "wick_violation_ifvg": "wick_ifvg",
        "body_close_violation_ifvg": "body_close_ifvg",
    }
    rows: list[dict[str, object]] = []
    for mapping_variant, mapping_frame in fvgs.groupby(
        "mapping_variant",
        sort=False,
    ):
        for category, column in categories.items():
            subset = mapping_frame[mapping_frame[column].fillna(False)]
            rows.append(
                {
                    "mapping_variant": mapping_variant,
                    "fvg_category": category,
                    "detection_count": int(subset["event_id"].nunique()),
                    "interaction_rate": (
                        float(subset["interacted"].mean())
                        if len(subset)
                        else np.nan
                    ),
                    "reaction_confirmation_rate": (
                        float(subset["confirmed"].mean())
                        if len(subset)
                        else np.nan
                    ),
                    "invalidation_rate": (
                        float(subset["invalidated"].mean())
                        if len(subset)
                        else np.nan
                    ),
                    "mean_favorable_excursion_60m": (
                        float(
                            subset["favorable_excursion_60m"].mean()
                        )
                        if len(subset)
                        and "favorable_excursion_60m" in subset
                        else np.nan
                    ),
                    "mean_adverse_excursion_60m": (
                        float(subset["adverse_excursion_60m"].mean())
                        if len(subset)
                        and "adverse_excursion_60m" in subset
                        else np.nan
                    ),
                }
            )
    return pd.DataFrame.from_records(rows)


def pmh_pml_summary(pmh: pd.DataFrame) -> pd.DataFrame:
    """Describe PMH/PML sweeps without promoting them to bias."""

    if pmh.empty:
        return pd.DataFrame()

    def _conditional_rate(
        group: pd.DataFrame,
        condition: pd.Series,
        result: str,
    ) -> float:
        eligible = group.loc[condition, result]
        return float(eligible.mean()) if len(eligible) else np.nan

    rows = []
    for mapping_variant, group in pmh.groupby(
        "mapping_variant",
        sort=False,
    ):
        swept = group["swept"].fillna(False)
        reaction = group["later_reaction_confirmed"].fillna(False)
        agreement = group["agrees_with_later_reaction"].dropna()
        rows.append(
            {
                "mapping_variant": mapping_variant,
                "level_observations": int(len(group)),
                "sweep_count": int(swept.sum()),
                "sweep_frequency": float(swept.mean()),
                "balanced_ranging_prerequisite_frequency": float(
                    group["pmh_pml_prerequisites_met"].fillna(False).mean()
                ),
                "reaction_confirmation_rate_after_sweep": (
                    float(reaction[swept].mean())
                    if swept.any()
                    else np.nan
                ),
                "reaction_rate_when_htf_unresolved": _conditional_rate(
                    group,
                    group["htf_unresolved_at_0830"].fillna(False),
                    "later_reaction_confirmed",
                ),
                "reaction_rate_when_valid_htf_exists": _conditional_rate(
                    group,
                    group["valid_htf_context_at_0830"].fillna(False),
                    "later_reaction_confirmed",
                ),
                "agreement_rate_with_later_reaction": (
                    float(agreement.astype(bool).mean())
                    if len(agreement)
                    else np.nan
                ),
                "overrides_htf_context": False,
                "independent_bias": False,
            }
        )
    return pd.DataFrame.from_records(rows)


def forward_stability_summary(forward: pd.DataFrame) -> pd.DataFrame:
    """Retain requested forward partitions without creating a score."""

    if forward.empty:
        return pd.DataFrame()
    group_columns = [
        "year",
        "volatility_regime",
        "direction",
        "mapping_variant",
        "outcome",
        "session",
        "dst",
        "anchor_type",
        "horizon",
    ]
    return (
        forward.groupby(group_columns, dropna=False)
        .agg(
            observations=("anchor_id", "nunique"),
            mean_signed_change=("signed_change", "mean"),
            median_signed_change=("signed_change", "median"),
            mean_absolute_change=("absolute_change", "mean"),
            mean_mfe=("mfe", "mean"),
            mean_mae=("mae", "mean"),
            opposing_liquidity_reach_rate=(
                "opposing_liquidity_reached",
                "mean",
            ),
            invalidation_first_rate=("invalidation_first", "mean"),
            median_time_to_mfe_minutes=("time_to_mfe_minutes", "median"),
            median_time_to_mae_minutes=("time_to_mae_minutes", "median"),
        )
        .reset_index()
    )


def timing_guardrail_summary(snapshots: pd.DataFrame) -> pd.DataFrame:
    fixed = snapshots[
        snapshots["mode"].eq("fixed_clock")
        & snapshots["observation_clock"].isin(["08:30", "09:00"])
    ].copy()
    if fixed.empty:
        return pd.DataFrame()
    pivot = fixed.pivot_table(
        index=["session_date", "mapping_variant"],
        columns="observation_clock",
        values="state",
        aggfunc="last",
    ).reset_index()
    if "08:30" not in pivot or "09:00" not in pivot:
        return pd.DataFrame()
    pivot["window_result"] = np.select(
        [
            pivot["09:00"].eq("reaction_confirmed"),
            pivot["09:00"].eq("invalidated"),
            pivot["09:00"].eq("candidate_liquidity_event"),
            pivot["08:30"].eq(pivot["09:00"]),
        ],
        [
            "reaction_confirmation",
            "context_invalidation",
            "candidate_liquidity_event",
            "context_unchanged_or_unresolved",
        ],
        default="context_changed_unresolved",
    )
    return (
        pivot.groupby(["mapping_variant", "window_result"])
        .size()
        .rename("date_count")
        .reset_index()
        .assign(
            standalone_direction_rule=False,
            causal_clock_claim=False,
        )
    )
