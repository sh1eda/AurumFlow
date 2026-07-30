"""Causal evidence-chain reconstruction for D005_E2."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import multiprocessing
from pathlib import Path

import numpy as np
import pandas as pd

from research.context_engine.bars import TIMEFRAME_MINUTES
from research.context_engine.config import ContextEngineConfig
from research.context_engine.engine import ContextEngine
from research.context_engine.features import (
    confirmed_swings,
    detect_displacements,
    detect_mss,
)

from .config import ReactionAnchorDiagnosticConfig
from .directions import (
    classify_outcome,
    expected_post_sweep_direction,
    liquidity_raid_direction,
)


_FORK_E2_TIMEFRAMES: Mapping[str, pd.DataFrame] | None = None


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _json_parameters(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def d005_config_for_mapping_variant(variant) -> ContextEngineConfig:
    """Preserve each E1 mapping's frozen optional-refinement switch."""

    return ContextEngineConfig(
        primary_mapping=variant.d005_mapping,
        optional_1m_refinement=variant.optional_1m_refinement,
    )


def load_e1_event_inventory(e1_output: Path) -> pd.DataFrame:
    """Load independent E1 array/liquidity artifacts into one schema."""

    frames: list[pd.DataFrame] = []
    for artifact, family in (
        ("fvg_event_statistics.parquet", "fvg"),
        ("order_block_event_statistics.parquet", "order_block"),
        ("liquidity_events.parquet", "liquidity"),
    ):
        frame = pd.read_parquet(e1_output / artifact)
        frame["source_artifact"] = artifact
        frame["event_family"] = family
        frames.append(frame)
    columns = sorted(set().union(*(set(frame.columns) for frame in frames)))
    normalized = [
        frame.reindex(columns=columns)
        for frame in frames
    ]
    events = pd.concat(normalized, ignore_index=True)
    for column in (
        "created_at",
        "available_at",
        "interacted_at",
        "confirmed_at",
        "invalidated_at",
    ):
        events[column] = pd.to_datetime(events[column], utc=True, errors="coerce")
    events["direction"] = pd.to_numeric(
        events["direction"], errors="coerce"
    ).fillna(0).astype(int)
    return events.drop_duplicates(
        ["mapping_variant", "event_id"], keep="last"
    ).reset_index(drop=True)


def confirmation_inventory(
    timeframes: Mapping[str, pd.DataFrame],
    config: ReactionAnchorDiagnosticConfig,
) -> pd.DataFrame:
    """Detect all causal MSS/displacement events required by any mapping."""

    required = sorted(
        {
            d005_config_for_mapping_variant(variant)
            .mapping(variant.d005_mapping)
            .reaction
            for variant in config.mapping_variants
        },
        key=lambda name: TIMEFRAME_MINUTES[name],
    )
    end = max(
        pd.Timestamp(frame["available_at"].iloc[-1])
        for name, frame in timeframes.items()
        if name in required and not frame.empty
    )
    records: list[dict[str, object]] = []
    d005 = ContextEngineConfig()
    for timeframe in required:
        events = (
            *detect_mss(
                timeframes[timeframe],
                timeframe=timeframe,
                variant=d005.mss,
                evaluation_at=end,
            ),
            *detect_displacements(
                timeframes[timeframe],
                timeframe=timeframe,
                variant=d005.displacement,
                evaluation_at=end,
            ),
        )
        records.extend(event.to_record() for event in events)
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        return frame
    for column in ("created_at", "available_at", "confirmed_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame.drop_duplicates("event_id").sort_values(
        ["available_at", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def _directions_at(
    swings: pd.DataFrame,
    timestamps: pd.Series,
) -> tuple[np.ndarray, list[pd.Timestamp | pd.NaT]]:
    """Vector-equivalent multi-timestamp form of structure_direction."""

    directions = np.zeros(len(timestamps), dtype=np.int8)
    contexts: list[pd.Timestamp | pd.NaT] = [pd.NaT] * len(timestamps)
    if swings.empty or timestamps.empty:
        return directions, contexts
    high = swings[swings["swing_type"].eq("high")].sort_values(
        "confirmation_at"
    )
    low = swings[swings["swing_type"].eq("low")].sort_values(
        "confirmation_at"
    )
    if len(high) < 2 or len(low) < 2:
        return directions, contexts
    high_at = pd.DatetimeIndex(
        pd.to_datetime(high["confirmation_at"], utc=True)
    ).as_unit("ns").asi8
    low_at = pd.DatetimeIndex(
        pd.to_datetime(low["confirmation_at"], utc=True)
    ).as_unit("ns").asi8
    high_level = high["level"].to_numpy(dtype=float)
    low_level = low["level"].to_numpy(dtype=float)
    query = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True)).as_unit(
        "ns"
    ).asi8
    for position, stamp in enumerate(query):
        hi = int(np.searchsorted(high_at, stamp, side="right"))
        lo = int(np.searchsorted(low_at, stamp, side="right"))
        if hi < 2 or lo < 2:
            continue
        high_change = high_level[hi - 1] - high_level[hi - 2]
        low_change = low_level[lo - 1] - low_level[lo - 2]
        directions[position] = (
            1
            if high_change > 0 and low_change > 0
            else -1
            if high_change < 0 and low_change < 0
            else 0
        )
        contexts[position] = pd.Timestamp(
            max(high_at[hi - 1], low_at[lo - 1]), tz="UTC"
        )
    return directions, contexts


def build_candidate_inventory(
    *,
    events: pd.DataFrame,
    e1_output: Path,
    timeframes: Mapping[str, pd.DataFrame],
    config: ReactionAnchorDiagnosticConfig,
) -> pd.DataFrame:
    """Return every parent POI interaction and named sweep without a cap."""

    candidates: list[pd.DataFrame] = []
    for variant in config.mapping_variants:
        mapping = d005_config_for_mapping_variant(variant).mapping(
            variant.d005_mapping
        )
        arrays = events[
            events["mapping_variant"].eq(variant.name)
            & events["event_type"].isin(["raw_fvg", "order_block"])
            & events["timeframe"].eq(mapping.parent)
            & events["interacted_at"].notna()
        ].copy()
        if not arrays.empty:
            arrays["candidate_event_at"] = arrays["interacted_at"]
            arrays["candidate_source"] = "poi_interaction"
            arrays["pmh_pml"] = False
            arrays["pmh_pml_prerequisites_met"] = True
            candidates.append(arrays)
        sweeps = events[
            events["mapping_variant"].eq(variant.name)
            & events["event_type"].eq("liquidity_sweep")
            & events["timeframe"].eq(mapping.reaction)
        ].copy()
        if not sweeps.empty:
            sweeps["candidate_event_at"] = sweeps["available_at"]
            sweeps["candidate_source"] = "liquidity_sweep"
            sweeps["pmh_pml"] = sweeps["taxonomy"].isin(
                ["premarket_high", "premarket_low"]
            )
            sweeps["pmh_pml_prerequisites_met"] = True
            candidates.append(sweeps)

    pmh = pd.read_parquet(e1_output / "pmh_pml_events.parquet")
    pmh = pmh[pmh["swept"].fillna(False) & pmh["sweep_at"].notna()].copy()
    if not pmh.empty:
        pmh["event_id"] = pmh["sweep_event_id"]
        pmh["event_type"] = "liquidity_sweep"
        pmh["timeframe"] = "1min"
        pmh["variant"] = "penetration_body_reclaim"
        pmh["available_at"] = pd.to_datetime(pmh["sweep_at"], utc=True)
        pmh["created_at"] = pmh["available_at"]
        pmh["interacted_at"] = pmh["available_at"]
        pmh["confirmed_at"] = pmh["available_at"]
        pmh["invalidated_at"] = pd.NaT
        pmh["zone_low"] = np.nan
        pmh["zone_high"] = np.nan
        pmh["parameters"] = "{}"
        pmh["candidate_event_at"] = pmh["available_at"]
        pmh["candidate_source"] = "pmh_pml_sweep"
        pmh["pmh_pml"] = True
        pmh["source_artifact"] = "pmh_pml_events.parquet"
        pmh["event_family"] = "liquidity"
        candidates.append(pmh)
    if not candidates:
        return pd.DataFrame()
    frame = pd.concat(candidates, ignore_index=True, sort=False)
    frame = frame.drop_duplicates(
        ["mapping_variant", "event_id", "candidate_event_at"]
    ).sort_values(
        ["mapping_variant", "candidate_event_at", "event_id"],
        kind="mergesort",
    )
    frame["candidate_event_at"] = pd.to_datetime(
        frame["candidate_event_at"], utc=True
    )
    frame["invalidated_at"] = pd.to_datetime(
        frame["invalidated_at"], utc=True, errors="coerce"
    )
    frame["direction"] = pd.to_numeric(
        frame["direction"], errors="coerce"
    ).fillna(0).astype(int)

    annotated: list[pd.DataFrame] = []
    for variant in config.mapping_variants:
        subset = frame[frame["mapping_variant"].eq(variant.name)].copy()
        if subset.empty:
            continue
        d005 = d005_config_for_mapping_variant(variant)
        mapping = d005.mapping(variant.d005_mapping)
        parent_swings = confirmed_swings(
            timeframes[mapping.parent], width=d005.mss.pivot_width
        )
        child_swings = confirmed_swings(
            timeframes[mapping.reaction], width=d005.mss.pivot_width
        )
        parent_direction, context_at = _directions_at(
            parent_swings, subset["candidate_event_at"]
        )
        child_direction, _ = _directions_at(
            child_swings, subset["candidate_event_at"]
        )
        subset["parent_direction"] = parent_direction
        subset["parent_context_created_at"] = context_at
        subset["pre_candidate_child_direction"] = child_direction
        subset["liquidity_raid_direction"] = subset["taxonomy"].map(
            liquidity_raid_direction
        )
        subset["liquidity_expected_direction"] = subset["taxonomy"].map(
            expected_post_sweep_direction
        )
        subset["candidate_direction"] = subset["direction"]
        subset["candidate_parent_aligned"] = (
            subset["parent_direction"].eq(0)
            | subset["parent_direction"].eq(subset["candidate_direction"])
        )
        subset["outcome"] = [
            classify_outcome(
                candidate_type=str(event_type),
                candidate_direction=int(direction),
                parent_direction=int(parent),
                pre_candidate_child_direction=int(child),
            )
            for event_type, direction, parent, child in zip(
                subset["event_type"],
                subset["candidate_direction"],
                subset["parent_direction"],
                subset["pre_candidate_child_direction"],
                strict=True,
            )
        ]
        annotated.append(subset)
    result = pd.concat(annotated, ignore_index=True)
    result["candidate_id"] = result["event_id"].astype(str)
    return result


@dataclass(frozen=True)
class _EventIndex:
    frame: pd.DataFrame
    available_ns: np.ndarray
    created_ns: np.ndarray

    @classmethod
    def build(cls, frame: pd.DataFrame | None) -> "_EventIndex":
        if frame is None or frame.empty:
            return cls(
                pd.DataFrame(),
                np.asarray([], dtype=np.int64),
                np.asarray([], dtype=np.int64),
            )
        ordered = frame.sort_values(
            ["available_at", "event_id"], kind="mergesort"
        ).reset_index(drop=True)
        available = pd.DatetimeIndex(
            pd.to_datetime(ordered["available_at"], utc=True)
        ).as_unit("ns").asi8
        created = pd.DatetimeIndex(
            pd.to_datetime(ordered["created_at"], utc=True)
        ).as_unit("ns").asi8
        return cls(ordered, available, created)

    def first(
        self,
        *,
        left: pd.Timestamp,
        right: pd.Timestamp | None = None,
        created_not_before: pd.Timestamp | None = None,
    ) -> pd.Series | None:
        position = int(
            np.searchsorted(self.available_ns, left.value, side="left")
        )
        right_ns = right.value if right is not None else np.iinfo(np.int64).max
        created_ns = (
            created_not_before.value
            if created_not_before is not None
            else np.iinfo(np.int64).min
        )
        while position < len(self.frame):
            if self.available_ns[position] > right_ns:
                return None
            if self.created_ns[position] >= created_ns:
                return self.frame.iloc[position]
            position += 1
        return None


def reconstruct_uncapped_sequences(
    *,
    candidates: pd.DataFrame,
    confirmations: pd.DataFrame,
    events: pd.DataFrame,
    timeframes: Mapping[str, pd.DataFrame],
    config: ReactionAnchorDiagnosticConfig,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Reconstruct every candidate chain with no schedule cap."""

    d005 = ContextEngineConfig()
    confirmation_groups = {
        key: _EventIndex.build(group)
        for key, group in confirmations.groupby(
            ["event_type", "timeframe", "direction"], dropna=False
        )
    }
    array_groups: dict[tuple[str, str, int], _EventIndex] = {}
    any_array_groups: dict[tuple[str, str], _EventIndex] = {}
    reaction_available_by_mapping: dict[str, np.ndarray] = {}
    for variant in config.mapping_variants:
        mapping = d005_config_for_mapping_variant(variant).mapping(
            variant.d005_mapping
        )
        refinement = (
            mapping.optional_refinement
            if variant.optional_1m_refinement
            and mapping.optional_refinement
            else mapping.refinement
        )
        arrays = events[
            events["mapping_variant"].eq(variant.name)
            & events["event_type"].isin(["raw_fvg", "order_block"])
            & events["timeframe"].eq(refinement)
        ].sort_values(["available_at", "event_id"], kind="mergesort")
        any_array_groups[(variant.name, refinement)] = _EventIndex.build(
            arrays
        )
        for direction, group in arrays.groupby("direction"):
            array_groups[(variant.name, refinement, int(direction))] = (
                _EventIndex.build(group)
            )
        reaction_available_by_mapping[variant.name] = pd.DatetimeIndex(
            pd.to_datetime(
                timeframes[mapping.reaction]["available_at"], utc=True
            )
        ).as_unit("ns").asi8

    rows: list[dict[str, object]] = []
    for candidate in candidates.to_dict("records"):
        variant = config.mapping_variant(str(candidate["mapping_variant"]))
        mapping = d005_config_for_mapping_variant(variant).mapping(
            variant.d005_mapping
        )
        refinement = (
            mapping.optional_refinement
            if variant.optional_1m_refinement
            and mapping.optional_refinement
            else mapping.refinement
        )
        candidate_at = pd.Timestamp(candidate["candidate_event_at"])
        direction = int(candidate["candidate_direction"])
        timeout_at = candidate_at + pd.Timedelta(
            minutes=TIMEFRAME_MINUTES[mapping.reaction]
            * d005.mss.confirmation_timeout_bars
        )
        invalidated_at = candidate.get("invalidated_at")
        invalidated_at = (
            pd.Timestamp(invalidated_at)
            if invalidated_at is not None and not pd.isna(invalidated_at)
            else None
        )
        reaction_available = reaction_available_by_mapping[variant.name]
        observed_reaction_bars = int(
            np.searchsorted(
                reaction_available, timeout_at.value, side="right"
            )
            - np.searchsorted(
                reaction_available, candidate_at.value, side="left"
            )
        )
        base = {
            "population": "e2_uncapped",
            "mapping_variant": variant.name,
            "parent_timeframe": mapping.parent,
            "reaction_timeframe": mapping.reaction,
            "refinement_timeframe": refinement,
            "candidate_id": str(candidate["candidate_id"]),
            "candidate_type": str(candidate["event_type"]),
            "candidate_source": str(candidate["candidate_source"]),
            "candidate_variant": str(candidate.get("variant", "")),
            "candidate_taxonomy": str(candidate.get("taxonomy", "")),
            "candidate_at": candidate_at,
            "parent_context_created_at": candidate.get(
                "parent_context_created_at"
            ),
            "candidate_invalidated_at": invalidated_at,
            "candidate_timeout_at": timeout_at,
            "parent_direction": int(candidate["parent_direction"]),
            "pre_candidate_child_direction": int(
                candidate["pre_candidate_child_direction"]
            ),
            "liquidity_raid_direction": int(
                candidate["liquidity_raid_direction"]
            ),
            "liquidity_expected_direction": int(
                candidate["liquidity_expected_direction"]
            ),
            "candidate_direction": direction,
            "outcome": str(candidate["outcome"]),
            "pmh_pml": bool(candidate.get("pmh_pml", False)),
            "pmh_pml_prerequisites_met": bool(
                candidate.get("pmh_pml_prerequisites_met", True)
            ),
            "observed_reaction_bars_to_timeout": observed_reaction_bars,
            "mss_id": None,
            "mss_direction": 0,
            "mss_confirmed_at": pd.NaT,
            "mss_created_at": pd.NaT,
            "displacement_id": None,
            "displacement_direction": 0,
            "displacement_confirmed_at": pd.NaT,
            "displacement_created_at": pd.NaT,
            "refinement_id": None,
            "refinement_type": None,
            "refinement_variant": None,
            "refinement_direction": 0,
            "refinement_created_at": pd.NaT,
            "refinement_zone_low": np.nan,
            "refinement_zone_high": np.nan,
            "d005_reaction_confirmed_at": pd.NaT,
            "final_d005_direction": 0,
            "e1_transition_id": None,
        }
        if bool(candidate.get("pmh_pml", False)) and not bool(
            candidate.get("pmh_pml_prerequisites_met", False)
        ):
            rows.append(
                {
                    **base,
                    "sequence_status": "pmh_pml_prerequisite_failure",
                }
            )
            continue
        if not bool(candidate["candidate_parent_aligned"]):
            rows.append({**base, "sequence_status": "candidate_opposes_parent"})
            continue
        mss = confirmation_groups.get(
            ("market_structure_shift", mapping.reaction, direction),
            _EventIndex.build(None),
        ).first(
            left=candidate_at,
            right=timeout_at,
        )
        if mss is None:
            status = (
                "missing_reaction_bars"
                if observed_reaction_bars
                < d005.mss.confirmation_timeout_bars
                else "mss_timeout"
            )
            rows.append({**base, "sequence_status": status})
            continue
        mss_at = pd.Timestamp(mss["available_at"])
        mss_created = pd.Timestamp(mss["created_at"])
        with_mss = {
            **base,
            "mss_id": str(mss["event_id"]),
            "mss_direction": int(mss["direction"]),
            "mss_confirmed_at": mss_at,
            "mss_created_at": mss_created,
        }
        displacement = confirmation_groups.get(
            ("displacement", mapping.reaction, direction),
            _EventIndex.build(None),
        ).first(
            left=candidate_at,
            right=invalidated_at,
            created_not_before=max(candidate_at, mss_created),
        )
        if displacement is None:
            rows.append(
                {**with_mss, "sequence_status": "displacement_failure"}
            )
            continue
        displacement_at = pd.Timestamp(displacement["available_at"])
        displacement_created = pd.Timestamp(displacement["created_at"])
        with_displacement = {
            **with_mss,
            "displacement_id": str(displacement["event_id"]),
            "displacement_direction": int(displacement["direction"]),
            "displacement_confirmed_at": displacement_at,
            "displacement_created_at": displacement_created,
        }
        confirmation_start = max(mss_at, displacement_at)
        refinement_array = array_groups.get(
            (variant.name, refinement, direction),
            _EventIndex.build(None),
        ).first(
            left=confirmation_start,
            right=invalidated_at,
        )
        if refinement_array is None:
            any_array = any_array_groups.get(
                (variant.name, refinement),
                _EventIndex.build(None),
            ).first(
                left=confirmation_start,
                right=invalidated_at,
            )
            rows.append(
                {
                    **with_displacement,
                    "sequence_status": (
                        "aligned_array_failure"
                        if any_array is not None
                        else "refinement_failure"
                    ),
                }
            )
            continue
        rows.append(
            {
                **with_displacement,
                "refinement_id": str(refinement_array["event_id"]),
                "refinement_type": str(refinement_array["event_type"]),
                "refinement_variant": str(refinement_array["variant"]),
                "refinement_direction": int(
                    refinement_array["direction"]
                ),
                "refinement_created_at": pd.Timestamp(
                    refinement_array["available_at"]
                ),
                "refinement_zone_low": float(
                    refinement_array["zone_low"]
                ),
                "refinement_zone_high": float(
                    refinement_array["zone_high"]
                ),
                "final_d005_direction": direction,
                "sequence_status": "core_sequence_complete",
            }
        )
    frame = pd.DataFrame.from_records(rows)
    before = len(frame)
    signature_columns = [
        "mapping_variant",
        "candidate_id",
        "mss_id",
        "displacement_id",
        "refinement_id",
        "sequence_status",
    ]
    frame = frame.drop_duplicates(signature_columns).reset_index(drop=True)
    frame["sequence_id"] = [
        _stable_id(*(record[column] for column in signature_columns))
        for record in frame.to_dict("records")
    ]
    return frame, {
        "candidate_rows_before_deduplication": before,
        "candidate_rows_after_deduplication": len(frame),
        "candidate_rows_deduplicated": before - len(frame),
    }


def _slice_timeframes(
    timeframes: Mapping[str, pd.DataFrame],
    *,
    evaluation_at: pd.Timestamp,
    warmup_days: int,
) -> dict[str, pd.DataFrame]:
    left = evaluation_at - pd.Timedelta(days=warmup_days)
    return {
        name: frame.loc[
            (frame.index >= left) & (frame.index <= evaluation_at)
        ]
        for name, frame in timeframes.items()
    }


def _evaluate_uncapped_batch(
    variant,
    evaluation_rows: pd.DataFrame,
    timeframes: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Replay the unchanged D005 engine at each structural completion time."""

    engine = ContextEngine(
        ContextEngineConfig(
            primary_mapping=variant.d005_mapping,
            optional_1m_refinement=variant.optional_1m_refinement,
        )
    )
    records: list[dict[str, object]] = []
    for row in evaluation_rows.to_dict("records"):
        evaluation_at = pd.Timestamp(row["evaluation_at"]).tz_convert("UTC")
        result = engine.evaluate(
            _slice_timeframes(
                timeframes,
                evaluation_at=evaluation_at,
                warmup_days=variant.warmup_days,
            ),
            evaluation_at=evaluation_at,
            mapping_name=variant.d005_mapping,
            session_date=evaluation_at.tz_convert(
                "America/New_York"
            ).date(),
        )
        snapshot = result.snapshot.to_record()
        reaction_at = pd.NaT
        for transition in snapshot["transitions"]:
            if transition["to_state"] == "reaction_confirmed":
                reaction_at = pd.Timestamp(transition["occurred_at"])
                break
        records.append(
            {
                "engine_evaluation_id": _stable_id(
                    "e2_uncapped_engine",
                    variant.name,
                    evaluation_at,
                ),
                "mapping_variant": variant.name,
                "evaluation_at": evaluation_at,
                "engine_state": snapshot["state"],
                "engine_direction": int(snapshot["direction"]),
                "engine_outcome": snapshot["outcome"],
                "engine_parent_direction": int(
                    snapshot["parent_direction"]
                ),
                "engine_child_direction": int(snapshot["child_direction"]),
                "engine_no_trade_reasons": snapshot[
                    "no_trade_reasons"
                ],
                "engine_evidence_ids": snapshot["evidence_ids"],
                "engine_transitions": snapshot["transitions"],
                "engine_balanced_ranging": bool(
                    snapshot["balanced_ranging"]
                ),
                "engine_trapped_between_arrays": bool(
                    snapshot["trapped_between_arrays"]
                ),
                "engine_missing_required_data": bool(
                    snapshot["missing_required_data"]
                ),
                "engine_overextended": bool(snapshot["overextended"]),
                "engine_risk_valid": bool(snapshot["risk_valid"]),
                "engine_reaction_confirmed_at": reaction_at,
            }
        )
    return pd.DataFrame.from_records(records)


def _fork_uncapped_worker(
    payload: tuple[object, pd.DataFrame],
) -> pd.DataFrame:
    if _FORK_E2_TIMEFRAMES is None:
        raise RuntimeError("parallel E2 worker was not initialized")
    variant, rows = payload
    return _evaluate_uncapped_batch(
        variant,
        rows,
        _FORK_E2_TIMEFRAMES,
    )


def engine_evidence_matches_sequence(
    record: Mapping[str, object],
) -> bool:
    """Require exact ordered candidate/MSS/displacement/refinement identity."""

    if record.get("engine_state") != "reaction_confirmed":
        return False
    evidence = record.get("engine_evidence_ids")
    if not isinstance(evidence, (list, tuple, np.ndarray)):
        return False
    expected = [
        record.get("candidate_id"),
        record.get("mss_id"),
        record.get("displacement_id"),
        record.get("refinement_id"),
    ]
    return [str(value) for value in list(evidence)[:4]] == [
        str(value) for value in expected
    ]


def attach_uncapped_engine_evaluations(
    sequences: pd.DataFrame,
    evaluations: pd.DataFrame,
) -> pd.DataFrame:
    """Join frozen-engine replay fields with UTC-safe confirmation times."""

    annotated = sequences.merge(
        evaluations,
        left_on=["mapping_variant", "refinement_created_at"],
        right_on=["mapping_variant", "evaluation_at"],
        how="left",
        validate="many_to_one",
    )
    annotated["engine_selected_reaction_confirmed"] = [
        engine_evidence_matches_sequence(record)
        for record in annotated.to_dict("records")
    ]
    annotated["d005_reaction_confirmed_at"] = pd.to_datetime(
        annotated["d005_reaction_confirmed_at"],
        utc=True,
        errors="coerce",
    )
    annotated["engine_reaction_confirmed_at"] = pd.to_datetime(
        annotated["engine_reaction_confirmed_at"],
        utc=True,
        errors="coerce",
    )
    selected = annotated["engine_selected_reaction_confirmed"]
    annotated.loc[selected, "d005_reaction_confirmed_at"] = annotated.loc[
        selected, "engine_reaction_confirmed_at"
    ]
    annotated.loc[selected, "final_d005_direction"] = annotated.loc[
        selected, "engine_direction"
    ].astype(int)
    return annotated


def evaluate_uncapped_core_snapshots(
    sequences: pd.DataFrame,
    *,
    timeframes: Mapping[str, pd.DataFrame],
    config: ReactionAnchorDiagnosticConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate every unique uncapped structural completion without a cap.

    Structural reconstruction is intentionally retained separately from this
    frozen-engine replay. A sequence is selected only if all four evidence
    identifiers match the engine's chosen evidence at that timestamp.
    """

    complete = sequences[
        sequences["sequence_status"].eq("core_sequence_complete")
        & sequences["refinement_created_at"].notna()
    ]
    batches: list[tuple[object, pd.DataFrame]] = []
    for variant in config.mapping_variants:
        timestamps = (
            complete[
                complete["mapping_variant"].eq(variant.name)
            ][["refinement_created_at"]]
            .drop_duplicates()
            .rename(columns={"refinement_created_at": "evaluation_at"})
            .sort_values("evaluation_at", kind="mergesort")
            .reset_index(drop=True)
        )
        if not timestamps.empty:
            batches.append((variant, timestamps))
    if not batches:
        return sequences.copy(), pd.DataFrame()

    global _FORK_E2_TIMEFRAMES
    _FORK_E2_TIMEFRAMES = timeframes
    results: list[pd.DataFrame] = []
    workers = min(5, len(batches))
    if workers == 1:
        variant, rows = batches[0]
        results.append(_evaluate_uncapped_batch(variant, rows, timeframes))
    else:
        try:
            context = multiprocessing.get_context("fork")
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=context,
            ) as executor:
                futures = {
                    executor.submit(
                        _fork_uncapped_worker, (variant, rows)
                    ): variant.name
                    for variant, rows in batches
                }
                for future in as_completed(futures):
                    results.append(future.result())
                    print(
                        "E2 uncapped engine replay mapping complete: "
                        f"{futures[future]}",
                        flush=True,
                    )
        except (OSError, PermissionError):
            results = [
                _evaluate_uncapped_batch(variant, rows, timeframes)
                for variant, rows in batches
            ]
    _FORK_E2_TIMEFRAMES = None
    evaluations = (
        pd.concat(results, ignore_index=True)
        .sort_values(
            ["evaluation_at", "mapping_variant"], kind="mergesort"
        )
        .reset_index(drop=True)
    )
    annotated = attach_uncapped_engine_evaluations(sequences, evaluations)
    return annotated, evaluations


def reconstruct_e1_capped_sequences(
    *,
    e1_output: Path,
    events: pd.DataFrame,
    confirmations: pd.DataFrame,
    config: ReactionAnchorDiagnosticConfig,
) -> pd.DataFrame:
    """Rebuild exact unique E1 confirmed evidence paths."""

    snapshots = pd.read_parquet(e1_output / "context_snapshots.parquet")
    snapshots = snapshots[snapshots["state"].eq("reaction_confirmed")]
    transitions = pd.read_parquet(e1_output / "state_transitions.parquet")
    transitions = transitions[
        transitions["to_state"].eq("reaction_confirmed")
    ][
        [
            "transition_id",
            "snapshot_id",
            "occurred_at",
            "mapping_variant",
        ]
    ]
    frame = transitions.merge(
        snapshots[
            [
                "snapshot_id",
                "parent_timeframe",
                "reaction_timeframe",
                "refinement_timeframe",
                "parent_direction",
                "child_direction",
                "direction",
                "outcome",
                "evidence_ids",
                "transitions",
            ]
        ],
        on="snapshot_id",
        how="left",
        validate="many_to_one",
        suffixes=("", "_snapshot"),
    )
    event_lookup = {
        (str(row.event_id), str(row.mapping_variant)): row
        for row in events.itertuples()
    }
    confirmation_lookup = {
        str(row.event_id): row for row in confirmations.itertuples()
    }
    d005 = ContextEngineConfig()
    rows: list[dict[str, object]] = []
    for record in frame.to_dict("records"):
        evidence = list(record["evidence_ids"])
        if len(evidence) < 4:
            continue
        mapping_variant = str(record["mapping_variant"])
        candidate = event_lookup.get((str(evidence[0]), mapping_variant))
        mss = confirmation_lookup.get(str(evidence[1]))
        displacement = confirmation_lookup.get(str(evidence[2]))
        refinement = event_lookup.get((str(evidence[3]), mapping_variant))
        if not all((candidate, mss, displacement, refinement)):
            continue
        candidate_at = pd.Timestamp(
            candidate.interacted_at
            if candidate.interacted_at is not None
            and not pd.isna(candidate.interacted_at)
            else candidate.available_at
        )
        mapping_variant_config = config.mapping_variant(mapping_variant)
        mapping = d005_config_for_mapping_variant(
            mapping_variant_config
        ).mapping(mapping_variant_config.d005_mapping)
        timeout_at = candidate_at + pd.Timedelta(
            minutes=TIMEFRAME_MINUTES[mapping.reaction]
            * d005.mss.confirmation_timeout_bars
        )
        context_at = pd.NaT
        pre_child = 0
        for transition in record["transitions"]:
            if transition.get("to_state") == "provisional_context":
                context_at = pd.Timestamp(transition["occurred_at"])
                break
        liquidity_expected = expected_post_sweep_direction(
            str(candidate.taxonomy)
        )
        raid_direction = liquidity_raid_direction(str(candidate.taxonomy))
        rows.append(
            {
                "population": "e1_capped",
                "sequence_id": str(record["transition_id"]),
                "e1_transition_id": str(record["transition_id"]),
                "mapping_variant": mapping_variant,
                "parent_timeframe": str(record["parent_timeframe"]),
                "reaction_timeframe": str(record["reaction_timeframe"]),
                "refinement_timeframe": str(record["refinement_timeframe"]),
                "candidate_id": str(candidate.event_id),
                "candidate_type": str(candidate.event_type),
                "candidate_source": (
                    "pmh_pml_sweep"
                    if str(candidate.taxonomy)
                    in {"premarket_high", "premarket_low"}
                    else "liquidity_sweep"
                    if str(candidate.event_type) == "liquidity_sweep"
                    else "poi_interaction"
                ),
                "candidate_variant": str(candidate.variant),
                "candidate_taxonomy": str(candidate.taxonomy),
                "candidate_at": candidate_at,
                "parent_context_created_at": context_at,
                "candidate_invalidated_at": (
                    pd.Timestamp(candidate.invalidated_at)
                    if candidate.invalidated_at is not None
                    and not pd.isna(candidate.invalidated_at)
                    else pd.NaT
                ),
                "candidate_timeout_at": timeout_at,
                "parent_direction": int(record["parent_direction"]),
                "pre_candidate_child_direction": pre_child,
                "liquidity_raid_direction": raid_direction,
                "liquidity_expected_direction": liquidity_expected,
                "candidate_direction": int(candidate.direction),
                "mss_id": str(mss.event_id),
                "mss_direction": int(mss.direction),
                "mss_confirmed_at": pd.Timestamp(mss.available_at),
                "mss_created_at": pd.Timestamp(mss.created_at),
                "displacement_id": str(displacement.event_id),
                "displacement_direction": int(displacement.direction),
                "displacement_confirmed_at": pd.Timestamp(
                    displacement.available_at
                ),
                "displacement_created_at": pd.Timestamp(
                    displacement.created_at
                ),
                "refinement_id": str(refinement.event_id),
                "refinement_type": str(refinement.event_type),
                "refinement_variant": str(refinement.variant),
                "refinement_direction": int(refinement.direction),
                "refinement_created_at": pd.Timestamp(
                    refinement.available_at
                ),
                "refinement_zone_low": float(refinement.zone_low),
                "refinement_zone_high": float(refinement.zone_high),
                "d005_reaction_confirmed_at": pd.Timestamp(
                    record["occurred_at"]
                ),
                "final_d005_direction": int(record["direction"]),
                "outcome": str(record["outcome"]),
                "pmh_pml": str(candidate.taxonomy)
                in {"premarket_high", "premarket_low"},
                "observed_reaction_bars_to_timeout": np.nan,
                "sequence_status": "reaction_confirmed",
            }
        )
    return pd.DataFrame.from_records(rows).drop_duplicates(
        "sequence_id"
    ).reset_index(drop=True)


def attach_first_refinement_interaction(
    sequences: pd.DataFrame,
    *,
    timeframes: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Attach first post-creation refinement-zone overlap and its close."""

    result = sequences.copy()
    result["refinement_interacted_at"] = pd.Series(
        pd.NaT, index=result.index, dtype="datetime64[ns, UTC]"
    )
    result["refinement_interaction_price"] = np.nan
    result["refinement_interaction_close"] = np.nan
    result["refinement_array_invalidated_at"] = pd.Series(
        pd.NaT, index=result.index, dtype="datetime64[ns, UTC]"
    )
    eligible = result[
        result["refinement_created_at"].notna()
        & result["refinement_zone_low"].notna()
        & result["refinement_zone_high"].notna()
    ]
    for timeframe, group in eligible.groupby("refinement_timeframe"):
        bars = timeframes[str(timeframe)]
        available = pd.DatetimeIndex(
            pd.to_datetime(bars["available_at"], utc=True)
        )
        available_ns = available.as_unit("ns").asi8
        highs = bars["high"].to_numpy(dtype=float, copy=False)
        lows = bars["low"].to_numpy(dtype=float, copy=False)
        closes = bars["close"].to_numpy(dtype=float, copy=False)
        for index, sequence in group.iterrows():
            created = pd.Timestamp(sequence["refinement_created_at"])
            start = int(
                np.searchsorted(available_ns, created.value, side="right")
            )
            zone_low = float(sequence["refinement_zone_low"])
            zone_high = float(sequence["refinement_zone_high"])
            overlap = np.flatnonzero(
                (highs[start:] >= zone_low) & (lows[start:] <= zone_high)
            )
            direction = int(sequence["refinement_direction"])
            failure = np.flatnonzero(
                closes[start:] < zone_low
                if direction > 0
                else closes[start:] > zone_high
            )
            overlap_position = (
                start + int(overlap[0]) if overlap.size else None
            )
            failure_position = (
                start + int(failure[0]) if failure.size else None
            )
            if failure_position is not None:
                result.at[index, "refinement_array_invalidated_at"] = (
                    pd.Timestamp(available[failure_position])
                )
            if overlap_position is None or (
                failure_position is not None
                and overlap_position > failure_position
            ):
                continue
            interaction_at = pd.Timestamp(available[overlap_position])
            intersection_low = max(lows[overlap_position], zone_low)
            intersection_high = min(highs[overlap_position], zone_high)
            reference = (
                intersection_high if direction > 0 else intersection_low
            )
            result.at[index, "refinement_interacted_at"] = interaction_at
            result.at[index, "refinement_interaction_price"] = float(reference)
            result.at[index, "refinement_interaction_close"] = float(
                closes[overlap_position]
            )
    for column in (
        "refinement_interacted_at",
        "refinement_array_invalidated_at",
    ):
        result[column] = pd.to_datetime(result[column], utc=True)
    return result
