"""Causal sequence and anchor reconstruction for D005_E3."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from research.context_engine.config import ContextEngineConfig
from research.d005_e1_context_engine_empirical.outcomes import session_label

from .config import EarlyContextAnchorStudyConfig


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _as_parameters(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            result = json.loads(value)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def load_uncapped_sequences(e2_output: Path) -> pd.DataFrame:
    """Load the accepted uncapped population without changing E2 rows."""

    frame = pd.read_parquet(e2_output / "candidate_sequences.parquet")
    frame = frame[frame["population"].eq("e2_uncapped")].copy()
    for column in (
        "parent_context_created_at",
        "candidate_at",
        "candidate_invalidated_at",
        "candidate_timeout_at",
        "mss_confirmed_at",
        "displacement_confirmed_at",
        "refinement_created_at",
        "refinement_interacted_at",
        "refinement_array_invalidated_at",
        "d005_reaction_confirmed_at",
    ):
        frame[column] = pd.to_datetime(
            frame[column], utc=True, errors="coerce"
        )
    frame = frame.drop_duplicates("sequence_id").reset_index(drop=True)
    pmh_pml = frame["pmh_pml"].fillna(False).astype(bool)
    pmh_pml_prerequisites = (
        frame["pmh_pml_prerequisites_met"].fillna(False).astype(bool)
    )
    frame["main_candidate_eligible"] = ~(
        pmh_pml & ~pmh_pml_prerequisites
    )
    frame["later_structurally_complete"] = frame[
        "sequence_status"
    ].eq("core_sequence_complete")
    frame["later_engine_confirmed"] = frame[
        "engine_selected_reaction_confirmed"
    ].fillna(False)
    frame["later_invalidated"] = (
        frame["candidate_invalidated_at"].notna()
        | frame["refinement_array_invalidated_at"].notna()
        | frame["engine_state"].eq("invalidated")
    )
    frame["later_timed_out"] = frame["sequence_status"].eq(
        "mss_timeout"
    )
    frame["later_missing_data"] = frame["sequence_status"].eq(
        "missing_reaction_bars"
    )
    frame["later_conflicted"] = (
        frame["sequence_status"].eq("candidate_opposes_parent")
        | frame["engine_state"].eq("conflict")
    )
    frame["parent_candidate_aligned"] = (
        frame["parent_direction"].eq(0)
        | frame["parent_direction"].eq(frame["candidate_direction"])
    )
    frame["retrospective_terminal_class"] = np.select(
        [
            frame["later_engine_confirmed"],
            frame["later_conflicted"],
            frame["later_timed_out"],
            frame["later_invalidated"],
            frame["later_missing_data"],
            frame["later_structurally_complete"],
        ],
        [
            "frozen_engine_confirmed",
            "later_conflicted",
            "later_timed_out",
            "later_invalidated",
            "later_missing_data",
            "structurally_complete_not_confirmed",
        ],
        default="later_stage_failure_or_unconfirmed",
    )
    return frame


def _balance_at(
    bars: pd.DataFrame,
    timestamp: pd.Timestamp,
    *,
    lookback: int,
    maximum_efficiency: float,
    maximum_range_atr: float,
    minimum_touches: int,
) -> dict[str, object]:
    available = pd.DatetimeIndex(
        pd.to_datetime(bars["available_at"], utc=True)
    ).as_unit("ns").asi8
    right = int(
        np.searchsorted(available, timestamp.value, side="right")
    )
    left = max(0, right - lookback)
    causal = bars.iloc[left:right]
    if len(causal) < lookback:
        return {
            "balanced_ranging": False,
            "range_like": False,
            "range_boundaries_resolved": False,
            "balance_efficiency_ratio": np.nan,
            "balance_range_atr": np.nan,
        }
    close = causal["close"].to_numpy(dtype=float)
    high = causal["high"].to_numpy(dtype=float)
    low = causal["low"].to_numpy(dtype=float)
    path = float(np.abs(np.diff(close)).sum())
    efficiency = abs(float(close[-1] - close[0])) / path if path else 0.0
    prior = np.r_[np.nan, close[:-1]]
    true_range = np.nanmax(
        np.vstack(
            [
                high - low,
                np.abs(high - prior),
                np.abs(low - prior),
            ]
        ),
        axis=0,
    )
    atr = float(np.nanmean(true_range[:-1]))
    range_high = float(np.max(high))
    range_low = float(np.min(low))
    range_atr = (
        (range_high - range_low) / atr if atr > 0 else np.inf
    )
    tolerance = max((range_high - range_low) * 0.10, 1e-12)
    high_touches = int((high >= range_high - tolerance).sum())
    low_touches = int((low <= range_low + tolerance).sum())
    range_like = bool(
        efficiency <= maximum_efficiency
        and range_atr <= maximum_range_atr
    )
    boundaries = bool(
        high_touches >= minimum_touches
        and low_touches >= minimum_touches
        and range_high > range_low
    )
    return {
        "balanced_ranging": bool(range_like and boundaries),
        "range_like": range_like,
        "range_boundaries_resolved": boundaries,
        "balance_efficiency_ratio": efficiency,
        "balance_range_atr": range_atr,
    }


def annotate_causal_context(
    sequences: pd.DataFrame,
    *,
    timeframes: Mapping[str, pd.DataFrame],
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Attach balance/session fields available at candidate creation."""

    result = sequences.copy()
    d005 = ContextEngineConfig()
    records: dict[int, dict[str, object]] = {}
    for variant in config.mapping_variants:
        indices = result.index[result["mapping_variant"].eq(variant.name)]
        if indices.empty:
            continue
        variant_config = ContextEngineConfig(
            primary_mapping=variant.d005_mapping,
            optional_1m_refinement=variant.optional_1m_refinement,
        )
        mapping = variant_config.mapping(variant.d005_mapping)
        bars = timeframes[mapping.parent]
        cache: dict[int, dict[str, object]] = {}
        for index in indices:
            stamp = pd.Timestamp(result.at[index, "candidate_at"])
            cached = cache.get(stamp.value)
            if cached is None:
                cached = _balance_at(
                    bars,
                    stamp,
                    lookback=d005.balance.lookback_bars,
                    maximum_efficiency=d005.balance.maximum_efficiency_ratio,
                    maximum_range_atr=d005.balance.maximum_range_atr,
                    minimum_touches=d005.balance.minimum_boundary_touches,
                )
                cache[stamp.value] = cached
            records[int(index)] = cached
    annotations = pd.DataFrame.from_dict(records, orient="index")
    for column in annotations:
        result.loc[annotations.index, column] = annotations[column]
    local = pd.to_datetime(result["candidate_at"], utc=True).dt.tz_convert(
        config.timezone
    )
    result["candidate_session_date"] = local.dt.date.astype(str)
    result["candidate_year"] = local.dt.year
    result["candidate_session"] = [
        session_label(value, config.timezone)
        for value in pd.to_datetime(result["candidate_at"], utc=True)
    ]
    result["candidate_dst"] = [
        bool(value.dst() and value.dst().total_seconds())
        for value in local
    ]
    return result


@dataclass(frozen=True)
class _EventIndex:
    frame: pd.DataFrame
    available_ns: np.ndarray

    @classmethod
    def build(cls, frame: pd.DataFrame) -> "_EventIndex":
        if frame.empty:
            return cls(frame.copy(), np.asarray([], dtype=np.int64))
        ordered = frame.sort_values(
            ["available_at", "event_id"], kind="mergesort"
        ).reset_index(drop=True)
        return cls(
            ordered,
            pd.DatetimeIndex(
                pd.to_datetime(ordered["available_at"], utc=True)
            )
            .as_unit("ns")
            .asi8,
        )

    def first(
        self,
        *,
        left: pd.Timestamp,
        right: pd.Timestamp | None,
    ) -> pd.Series | None:
        position = int(
            np.searchsorted(self.available_ns, left.value, side="left")
        )
        if position >= len(self.frame):
            return None
        if (
            right is not None
            and self.available_ns[position] > right.value
        ):
            return None
        return self.frame.iloc[position]


def _right_boundary(sequence: dict[str, object]) -> pd.Timestamp | None:
    invalidated = sequence.get("candidate_invalidated_at")
    if invalidated is not None and not pd.isna(invalidated):
        return pd.Timestamp(invalidated)
    if sequence.get("mss_id") is None or pd.isna(sequence.get("mss_id")):
        timeout = sequence.get("candidate_timeout_at")
        if timeout is not None and not pd.isna(timeout):
            return pd.Timestamp(timeout)
    return None


def attach_independent_array_anchors(
    sequences: pd.DataFrame,
    *,
    e1_output: Path,
    config: EarlyContextAnchorStudyConfig,
) -> pd.DataFrame:
    """Attach raw/qualified FVG and three independent OB anchors."""

    fvg = pd.read_parquet(e1_output / "fvg_event_statistics.parquet")
    ob = pd.read_parquet(
        e1_output / "order_block_event_statistics.parquet"
    )
    for frame in (fvg, ob):
        for column in (
            "created_at",
            "available_at",
            "interacted_at",
            "invalidated_at",
        ):
            frame[column] = pd.to_datetime(
                frame[column], utc=True, errors="coerce"
            )
        frame["direction"] = pd.to_numeric(
            frame["direction"], errors="coerce"
        ).fillna(0).astype(int)
    fvg_indices = {
        key: _EventIndex.build(group)
        for key, group in fvg.groupby(
            ["mapping_variant", "timeframe", "direction"],
            dropna=False,
        )
    }
    ob_indices = {
        key: _EventIndex.build(group)
        for key, group in ob.groupby(
            ["mapping_variant", "timeframe", "direction", "variant"],
            dropna=False,
        )
    }
    result = sequences.copy()
    array_prefixes = (
        "raw_fvg",
        "qualified_fvg",
        *(f"qualified_ob_{variant}" for variant in config.ob_variants),
    )
    for prefix in array_prefixes:
        result[f"{prefix}_id"] = None
        result[f"{prefix}_at"] = pd.Series(
            pd.NaT, index=result.index, dtype="datetime64[ns, UTC]"
        )
        result[f"{prefix}_direction"] = 0
        result[f"{prefix}_variant"] = None
        result[f"{prefix}_taxonomy"] = None

    empty = _EventIndex.build(pd.DataFrame())
    for index, sequence in result.iterrows():
        mapping = str(sequence["mapping_variant"])
        timeframe = str(sequence["refinement_timeframe"])
        direction = int(sequence["candidate_direction"])
        candidate_at = pd.Timestamp(sequence["candidate_at"])
        right = _right_boundary(sequence.to_dict())
        raw = fvg_indices.get(
            (mapping, timeframe, direction), empty
        ).first(left=candidate_at, right=right)
        if raw is not None:
            _set_array(result, index, "raw_fvg", raw)

        mss_at = sequence.get("mss_confirmed_at")
        displacement_at = sequence.get("displacement_confirmed_at")
        causally_qualified = bool(
            sequence["parent_candidate_aligned"]
            and mss_at is not None
            and not pd.isna(mss_at)
            and displacement_at is not None
            and not pd.isna(displacement_at)
        )
        if not causally_qualified:
            continue
        qualified_at = max(
            candidate_at,
            pd.Timestamp(mss_at),
            pd.Timestamp(displacement_at),
        )
        qualified_fvg = fvg_indices.get(
            (mapping, timeframe, direction), empty
        ).first(left=qualified_at, right=right)
        if qualified_fvg is not None:
            _set_array(
                result, index, "qualified_fvg", qualified_fvg
            )
        for variant in config.ob_variants:
            event = ob_indices.get(
                (mapping, timeframe, direction, variant), empty
            ).first(left=qualified_at, right=right)
            if event is not None:
                _set_array(
                    result,
                    index,
                    f"qualified_ob_{variant}",
                    event,
                )

    result["has_causal_raw_fvg"] = result["raw_fvg_id"].notna()
    result["has_causal_qualified_fvg"] = result[
        "qualified_fvg_id"
    ].notna()
    for variant in config.ob_variants:
        result[f"has_causal_ob_{variant}"] = result[
            f"qualified_ob_{variant}_id"
        ].notna()
    return result


def _set_array(
    result: pd.DataFrame,
    index: int,
    prefix: str,
    event: pd.Series,
) -> None:
    result.at[index, f"{prefix}_id"] = str(event["event_id"])
    result.at[index, f"{prefix}_at"] = pd.Timestamp(
        event["available_at"]
    )
    result.at[index, f"{prefix}_direction"] = int(event["direction"])
    result.at[index, f"{prefix}_variant"] = str(event["variant"])
    result.at[index, f"{prefix}_taxonomy"] = str(event["taxonomy"])


def _base_anchor(sequence: dict[str, object]) -> dict[str, object]:
    return {
        "sequence_id": sequence["sequence_id"],
        "mapping_variant": sequence["mapping_variant"],
        "outcome": sequence["outcome"],
        "candidate_source": sequence["candidate_source"],
        "candidate_type": sequence["candidate_type"],
        "candidate_variant": sequence["candidate_variant"],
        "candidate_taxonomy": sequence["candidate_taxonomy"],
        "candidate_direction": int(sequence["candidate_direction"]),
        "parent_direction": int(sequence["parent_direction"]),
        "pmh_pml": bool(sequence.get("pmh_pml", False)),
        "pmh_pml_prerequisites_met": bool(
            sequence.get("pmh_pml_prerequisites_met", False)
        ),
        "balanced_ranging": bool(
            sequence.get("balanced_ranging", False)
        ),
        "range_like": bool(sequence.get("range_like", False)),
        "candidate_session": sequence["candidate_session"],
        "candidate_session_date": sequence["candidate_session_date"],
        "candidate_year": int(sequence["candidate_year"]),
        "candidate_dst": bool(sequence["candidate_dst"]),
        "sequence_status": sequence["sequence_status"],
        "main_candidate_eligible": bool(
            sequence["main_candidate_eligible"]
        ),
        "later_structurally_complete": bool(
            sequence["later_structurally_complete"]
        ),
        "later_engine_confirmed": bool(
            sequence["later_engine_confirmed"]
        ),
        "later_invalidated": bool(sequence["later_invalidated"]),
        "later_timed_out": bool(sequence["later_timed_out"]),
        "later_missing_data": bool(sequence["later_missing_data"]),
        "later_conflicted": bool(sequence["later_conflicted"]),
        "retrospective_terminal_class": sequence[
            "retrospective_terminal_class"
        ],
        "has_causal_raw_fvg": bool(
            sequence.get("has_causal_raw_fvg", False)
        ),
        "has_causal_qualified_fvg": bool(
            sequence.get("has_causal_qualified_fvg", False)
        ),
        "has_causal_ob_consecutive_block": bool(
            sequence.get("has_causal_ob_consecutive_block", False)
        ),
        "has_causal_ob_last_opposing_candle": bool(
            sequence.get("has_causal_ob_last_opposing_candle", False)
        ),
        "has_causal_ob_inefficiency_break_origin": bool(
            sequence.get(
                "has_causal_ob_inefficiency_break_origin", False
            )
        ),
    }


def build_anchor_event_table(
    sequences: pd.DataFrame,
    *,
    config: EarlyContextAnchorStudyConfig,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Create one causal row per sequence and independent anchor type."""

    rows: list[dict[str, object]] = []
    for sequence in sequences.to_dict("records"):
        base = _base_anchor(sequence)
        eligible = bool(sequence["main_candidate_eligible"])

        def add(
            anchor_type: str,
            timestamp: object,
            direction: int,
            direction_source: str,
            event_id: object,
            *,
            event_family: str,
            event_variant: object = None,
            event_taxonomy: object = None,
            price_basis: str = "close",
            price_override: object = np.nan,
        ) -> None:
            if timestamp is None or pd.isna(timestamp):
                return
            stamp = pd.Timestamp(timestamp)
            row = {
                **base,
                "anchor_type": anchor_type,
                "anchor_event_id": (
                    str(event_id)
                    if event_id is not None and not pd.isna(event_id)
                    else _stable_id(
                        anchor_type,
                        sequence["mapping_variant"],
                        stamp,
                        direction,
                    )
                ),
                "anchor_at": stamp,
                "direction": int(direction),
                "direction_source": direction_source,
                "event_family": event_family,
                "event_variant": (
                    str(event_variant)
                    if event_variant is not None
                    and not pd.isna(event_variant)
                    else None
                ),
                "event_taxonomy": (
                    str(event_taxonomy)
                    if event_taxonomy is not None
                    and not pd.isna(event_taxonomy)
                    else None
                ),
                "anchor_price_basis": price_basis,
                "anchor_price_override": price_override,
                "main_scope_eligible": bool(eligible and direction != 0),
                "anchor_causally_observable": True,
                "anchor_selected_using_later_completion": False,
            }
            local = stamp.tz_convert(config.timezone)
            row["anchor_session_date"] = local.date().isoformat()
            row["anchor_year"] = local.year
            row["anchor_session"] = session_label(
                stamp, config.timezone
            )
            row["anchor_dst"] = bool(
                local.dst() and local.dst().total_seconds()
            )
            rows.append(row)

        add(
            "parent_context_creation",
            sequence["parent_context_created_at"],
            int(sequence["parent_direction"]),
            "parent_structure_direction",
            None,
            event_family="parent_context",
        )
        origin_type = (
            "htf_poi_interaction"
            if sequence["candidate_source"] == "poi_interaction"
            else "named_liquidity_sweep"
        )
        add(
            origin_type,
            sequence["candidate_at"],
            int(sequence["candidate_direction"]),
            (
                "poi_array_direction"
                if origin_type == "htf_poi_interaction"
                else "expected_post_sweep_direction"
            ),
            sequence["candidate_id"],
            event_family=sequence["candidate_source"],
            event_variant=sequence["candidate_variant"],
            event_taxonomy=sequence["candidate_taxonomy"],
        )
        add(
            "candidate_context_creation",
            sequence["candidate_at"],
            int(sequence["candidate_direction"]),
            "frozen_candidate_direction",
            sequence["candidate_id"],
            event_family="candidate_context",
            event_variant=sequence["candidate_variant"],
            event_taxonomy=sequence["candidate_taxonomy"],
        )
        add(
            "mss_body_close_confirmation",
            sequence["mss_confirmed_at"],
            int(sequence.get("mss_direction", 0) or 0),
            "mss_direction",
            sequence.get("mss_id"),
            event_family="market_structure_shift",
        )
        add(
            "displacement_confirmation",
            sequence["displacement_confirmed_at"],
            int(sequence.get("displacement_direction", 0) or 0),
            "displacement_direction",
            sequence.get("displacement_id"),
            event_family="displacement",
        )
        add(
            "first_aligned_raw_fvg_creation",
            sequence["raw_fvg_at"],
            int(sequence.get("raw_fvg_direction", 0) or 0),
            "raw_fvg_direction",
            sequence.get("raw_fvg_id"),
            event_family="raw_fvg",
            event_variant=sequence.get("raw_fvg_variant"),
            event_taxonomy=sequence.get("raw_fvg_taxonomy"),
        )
        add(
            "first_context_qualified_fvg_creation",
            sequence["qualified_fvg_at"],
            int(sequence.get("qualified_fvg_direction", 0) or 0),
            "context_qualified_fvg_direction",
            sequence.get("qualified_fvg_id"),
            event_family="context_qualified_fvg",
            event_variant=sequence.get("qualified_fvg_variant"),
            event_taxonomy=sequence.get("qualified_fvg_taxonomy"),
        )
        for variant in config.ob_variants:
            prefix = f"qualified_ob_{variant}"
            add(
                f"qualifying_ob_{variant}_creation",
                sequence[f"{prefix}_at"],
                int(sequence.get(f"{prefix}_direction", 0) or 0),
                f"{variant}_direction",
                sequence.get(f"{prefix}_id"),
                event_family="context_qualified_order_block",
                event_variant=variant,
                event_taxonomy=sequence.get(f"{prefix}_taxonomy"),
            )
        add(
            "refinement_array_creation",
            sequence["refinement_created_at"],
            int(sequence.get("refinement_direction", 0) or 0),
            "refinement_array_direction",
            sequence.get("refinement_id"),
            event_family="refinement_array",
            event_variant=sequence.get("refinement_variant"),
            event_taxonomy=sequence.get("refinement_type"),
        )
        add(
            "refinement_array_first_interaction",
            sequence["refinement_interacted_at"],
            int(sequence.get("refinement_direction", 0) or 0),
            "refinement_array_direction",
            sequence.get("refinement_id"),
            event_family="refinement_array_interaction",
            event_variant=sequence.get("refinement_variant"),
            event_taxonomy=sequence.get("refinement_type"),
            price_basis="refinement_interaction_price",
            price_override=sequence.get(
                "refinement_interaction_price", np.nan
            ),
        )
        add(
            "reaction_confirmed",
            sequence["d005_reaction_confirmed_at"],
            int(sequence.get("final_d005_direction", 0) or 0),
            "frozen_d005_direction",
            sequence.get("engine_evaluation_id"),
            event_family="d005_reaction_confirmed",
        )

    frame = pd.DataFrame.from_records(rows)
    before = len(frame)
    frame = frame.drop_duplicates(
        ["sequence_id", "anchor_type"], keep="first"
    ).sort_values(
        ["anchor_at", "mapping_variant", "sequence_id", "anchor_type"],
        kind="mergesort",
    ).reset_index(drop=True)
    frame["anchor_id"] = [
        _stable_id(
            config.version,
            sequence_id,
            anchor_type,
            anchor_event_id,
        )
        for sequence_id, anchor_type, anchor_event_id in zip(
            frame["sequence_id"],
            frame["anchor_type"],
            frame["anchor_event_id"],
            strict=True,
        )
    ]
    return frame, {
        "anchor_rows_before_deduplication": before,
        "anchor_rows_after_deduplication": len(frame),
        "anchor_rows_deduplicated": before - len(frame),
    }
