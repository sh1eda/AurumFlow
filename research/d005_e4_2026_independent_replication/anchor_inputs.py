"""Outcome-isolated 2026 structural inputs for frozen D005_E4.

This module stops at causal displacement/refinement anchors.  It deliberately
does not import the E1/E3 outcome modules, the E4 selector, or any analysis or
reporting module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research.context_engine.bars import build_timeframes, normalize_bars
from research.context_engine.config import ContextEngineConfig
from research.context_engine.engine import ContextEngine, EvaluationResult
from research.context_engine.features import confirmed_swings
from .frozen_structural_loader import (
    EmpiricalStudyConfig,
    MappingVariant,
    ReactionAnchorDiagnosticConfig,
    build_pmh_pml_inventory,
    classify_outcome,
    confirmation_inventory,
    directions_at,
    evaluate_uncapped_core_snapshots,
    event_schedule_from_inventory,
    expected_post_sweep_direction,
    fixed_observation_schedule,
    liquidity_raid_direction,
    reconstruct_uncapped_sequences,
)

from .config import (
    FROZEN_ANCHOR_RULE_HASHES,
    FROZEN_END,
    FROZEN_START,
    IndependentReplication2026Config,
)
from .preflight import sha256_file, verify_2026_parquet_contents


SCHEMA_VERSION = "d005-e4-2026-anchor-input-v1"
PRIMARY_VARIANT = MappingVariant("1h_5m", "1h_5m_1m", False, 8)
PRIMARY_ANCHOR = "displacement_confirmation"
SECONDARY_ANCHOR = "refinement_array_creation"
FROZEN_HORIZONS = (5, 15, 30, 60, 120)
TICK_VALUE_COLUMNS = (
    "timestamp_utc",
    "bid",
    "ask",
    "bid_volume",
    "ask_volume",
    "mid",
    "spread",
)
CANONICAL_FIELDS = (
    ("timestamp_utc", pa.timestamp("ms", tz="UTC"), False),
    ("bid", pa.float64(), False),
    ("ask", pa.float64(), False),
    ("bid_volume", pa.float32(), False),
    ("ask_volume", pa.float32(), False),
    ("mid", pa.float64(), False),
    ("spread", pa.float64(), False),
    ("symbol", pa.string(), False),
    ("source_partition", pa.string(), False),
)
FORBIDDEN_OUTPUT_TOKENS = (
    "return",
    "movement",
    "mfe",
    "mae",
    "profit",
    "loss",
    "expectancy",
    "drawdown",
    "p_value",
    "confidence_interval",
    "bootstrap",
    "effect_size",
    "classification",
    "trade_",
    "pnl",
    "anchor_price",
    "forward_price",
    "end_price",
)
EVENT_ATTRIBUTES = (
    "fvg_events",
    "order_block_events",
    "liquidity_events",
    "confirmation_events",
    "conflict_events",
)
HISTORICAL_RULE_PROVENANCE: Mapping[str, str] = {
    "canonical_schema": "scripts/build_dukascopy_canonical.py:canonical_schema",
    "tick_order_and_identity": (
        "scripts/validate_canonical_dataset.py:verify_canonical"
    ),
    "one_minute_bars": "research/manipulation_0830_0900/bars.py:ticks_to_one_minute",
    "five_minute_and_one_hour_bars": "research/context_engine/bars.py:build_timeframes",
    "closed_bar_contract": (
        "research/context_engine/bars.py:normalize_bars,closed_bars_asof"
    ),
    "fixed_and_event_schedules": (
        "research/d005_e1_context_engine_empirical/schedule.py:"
        "fixed_observation_schedule,event_schedule_from_inventory"
    ),
    "structural_evidence": "research/context_engine/engine.py:ContextEngine.evaluate",
    "candidate_direction_and_class": (
        "research/d005_e2_reaction_anchor_diagnostic/"
        "directions.py:classify_outcome"
    ),
    "mss_displacement_and_refinement_chain": (
        "research/d005_e2_reaction_anchor_diagnostic/"
        "reconstruction.py:reconstruct_uncapped_sequences"
    ),
    "confirmation_state": (
        "research/d005_e2_reaction_anchor_diagnostic/"
        "reconstruction.py:evaluate_uncapped_core_snapshots"
    ),
    "stable_anchor_identifier": (
        "research/d005_e3_early_context_anchor_study/"
        "anchors.py:build_anchor_event_table"
    ),
    "primary_and_refinement_deduplication": (
        "research/d005_e4_1h_5m_reversal_replication/"
        "selection.py:select_primary_anchors,select_refinement_anchors"
    ),
    "forward_window_boundary_only": (
        "research/d005_e3_early_context_anchor_study/"
        "outcomes.py:calculate_forward_outcomes (traced, never imported or called)"
    ),
}


class AnchorInputError(RuntimeError):
    """Raised when structural construction cannot preserve the frozen rules."""


@dataclass(frozen=True)
class AnchorInventoryResult:
    anchors: pd.DataFrame
    inventory_fingerprint: str
    structural_schema: tuple[str, ...]
    diagnostics: Mapping[str, Any]


def _expected_arrow_schema() -> pa.Schema:
    return pa.schema(
        [pa.field(name, kind, nullable=nullable) for name, kind, nullable in CANONICAL_FIELDS]
    )


def validate_tick_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Enforce the canonical values needed for bars and duplicate identity."""

    if set(frame.columns) != set(TICK_VALUE_COLUMNS):
        missing = sorted(set(TICK_VALUE_COLUMNS) - set(frame.columns))
        additional = sorted(set(frame.columns) - set(TICK_VALUE_COLUMNS))
        raise AnchorInputError(
            f"unexpected tick value schema; missing={missing}, additional={additional}"
        )
    result = frame.loc[:, TICK_VALUE_COLUMNS].copy()
    dtype = result["timestamp_utc"].dtype
    timezone = getattr(dtype, "tz", None)
    if timezone is None or str(timezone) not in {"UTC", "UTC+00:00"}:
        raise AnchorInputError("tick timestamps must use the UTC timezone")
    timestamps = pd.DatetimeIndex(result["timestamp_utc"])
    if not timestamps.is_monotonic_increasing:
        raise AnchorInputError("tick timestamps must be ordered")
    identity = [
        "timestamp_utc",
        "bid",
        "ask",
        "bid_volume",
        "ask_volume",
    ]
    if result.duplicated(identity).any():
        raise AnchorInputError("duplicate canonical tick identity")
    numeric = result.drop(columns="timestamp_utc")
    if numeric.isna().any().any() or not np.isfinite(
        numeric.to_numpy(dtype=float)
    ).all():
        raise AnchorInputError("tick values contain missing or non-finite data")
    if result[["bid", "ask"]].le(0).any().any():
        raise AnchorInputError("bid and ask must be positive")
    if result["ask"].lt(result["bid"]).any():
        raise AnchorInputError("ask cannot be below bid")
    if not np.allclose(
        result["spread"].to_numpy(dtype=float),
        result["ask"].to_numpy(dtype=float)
        - result["bid"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise AnchorInputError("spread differs from ask minus bid")
    if not np.allclose(
        result["mid"].to_numpy(dtype=float),
        (
            result["ask"].to_numpy(dtype=float)
            + result["bid"].to_numpy(dtype=float)
        )
        / 2.0,
        rtol=0.0,
        atol=1e-12,
    ):
        raise AnchorInputError("mid differs from bid/ask midpoint")
    return result


def _ticks_to_one_minute(ticks: pd.DataFrame) -> pd.DataFrame:
    """Exact D004 UTC, epoch-aligned, half-open one-minute aggregation."""

    frame = ticks.loc[:, ["timestamp_utc", "bid", "ask", "mid", "spread"]].copy()
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp_utc"), utc=True))
    if index.hasnans or not index.is_monotonic_increasing:
        raise AnchorInputError("canonical tick timestamps cannot build bars")
    frame.index = index
    pieces: list[pd.DataFrame] = []
    for name in ("bid", "ask", "mid"):
        piece = frame[name].resample(
            "1min", label="left", closed="left", origin="epoch"
        ).ohlc().rename(
            columns={
                "open": f"{name}_open",
                "high": f"{name}_high",
                "low": f"{name}_low",
                "close": f"{name}_close",
            }
        )
        pieces.append(piece)
    spread = frame["spread"].resample(
        "1min", label="left", closed="left", origin="epoch"
    ).agg(["median", "max", "last"])
    spread.columns = ["median_spread", "maximum_spread", "last_spread"]
    tick_count = frame["mid"].resample(
        "1min", label="left", closed="left", origin="epoch"
    ).size().rename("tick_count")
    bars = pd.concat([*pieces, tick_count, spread], axis=1)
    bars = bars[bars["tick_count"].gt(0)].copy()
    bars.index.name = "timestamp_utc"
    bars["tick_count"] = bars["tick_count"].astype("int64")
    numeric = bars.select_dtypes(include=[np.number])
    if numeric.isna().any().any() or not np.isfinite(
        numeric.to_numpy(dtype=float)
    ).all():
        raise AnchorInputError("one-minute bars contain invalid values")
    return bars


def build_structural_timeframes(ticks: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build the frozen UTC 1m -> 5m/1H closed-bar hierarchy."""

    validated = validate_tick_values(ticks)
    one_minute = _ticks_to_one_minute(
        validated.loc[:, ["timestamp_utc", "bid", "ask", "mid", "spread"]]
    )
    built = build_timeframes(one_minute)
    result = {name: built[name] for name in ("1min", "5min", "1H")}
    for name, frame in result.items():
        normalized = normalize_bars(frame, name)
        available = pd.DatetimeIndex(
            pd.to_datetime(normalized["available_at"], utc=True)
        )
        if (available <= normalized.index).any():
            raise AnchorInputError(f"{name} contains a non-closed bar")
    return result


def _registered_2026_records(root: Path) -> list[dict[str, Any]]:
    manifest_path = (
        root / "data/canonical/xauusd_ticks_d003-v2/canonical_manifest.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [
        record
        for record in payload.get("files", [])
        if isinstance(record, dict)
        and "/year=2026/" in f"/{record.get('path', '')}"
    ]
    return sorted(records, key=lambda record: str(record["path"]))


def load_2026_structural_timeframes(
    repository_root: Path,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Read only structural tick columns after all 178 byte hashes pass."""

    root = repository_root.resolve()
    content = verify_2026_parquet_contents(root)
    if not content["all_verified"]:
        raise AnchorInputError(
            "2026 Parquet content integrity failed: "
            + "; ".join(content["errors"])
        )
    start = pd.Timestamp(FROZEN_START)
    end = pd.Timestamp(FROZEN_END)
    expected_schema = _expected_arrow_schema()
    one_minute_parts: list[pd.DataFrame] = []
    source_minimum: pd.Timestamp | None = None
    source_maximum: pd.Timestamp | None = None
    previous_maximum: pd.Timestamp | None = None
    previous_boundary_keys: set[tuple[object, ...]] = set()

    records = _registered_2026_records(root)
    if len(records) != 178:
        raise AnchorInputError("registered 2026 record count is not 178")
    for record in records:
        path = root / str(record["path"])
        parquet = pq.ParquetFile(path)
        if parquet.schema_arrow.remove_metadata() != expected_schema:
            raise AnchorInputError(f"canonical Parquet schema mismatch: {record['path']}")
        table = parquet.read(columns=list(TICK_VALUE_COLUMNS))
        if table.num_rows != record.get("row_count"):
            raise AnchorInputError(f"canonical row count mismatch: {record['path']}")
        frame = validate_tick_values(table.to_pandas())
        if frame.empty:
            raise AnchorInputError(f"empty canonical Parquet: {record['path']}")
        timestamps = pd.DatetimeIndex(frame["timestamp_utc"])
        minimum = pd.Timestamp(timestamps[0])
        maximum = pd.Timestamp(timestamps[-1])
        if minimum < start or maximum >= end:
            raise AnchorInputError("source tick lies outside the frozen interval")
        if previous_maximum is not None and minimum < previous_maximum:
            raise AnchorInputError("cross-file tick ordering violation")
        identity_columns = [
            "timestamp_utc",
            "bid",
            "ask",
            "bid_volume",
            "ask_volume",
        ]
        if previous_maximum is not None and minimum == previous_maximum:
            boundary = frame.loc[
                frame["timestamp_utc"].eq(minimum), identity_columns
            ]
            keys = set(boundary.itertuples(index=False, name=None))
            if keys & previous_boundary_keys:
                raise AnchorInputError("cross-file duplicate canonical tick identity")
        last = frame.loc[
            frame["timestamp_utc"].eq(maximum), identity_columns
        ]
        previous_boundary_keys = set(last.itertuples(index=False, name=None))
        previous_maximum = maximum
        source_minimum = minimum if source_minimum is None else source_minimum
        source_maximum = maximum
        one_minute_parts.append(
            _ticks_to_one_minute(
                frame.loc[:, ["timestamp_utc", "bid", "ask", "mid", "spread"]]
            )
        )

    one_minute = pd.concat(one_minute_parts).sort_index(kind="mergesort")
    if one_minute.index.has_duplicates:
        raise AnchorInputError("one-minute construction produced duplicate bars")
    built = build_timeframes(one_minute)
    timeframes = {name: built[name] for name in ("1min", "5min", "1H")}
    for name, frame in timeframes.items():
        normalized = normalize_bars(frame, name)
        if normalized.index.min() < start or normalized.index.max() >= end:
            raise AnchorInputError(f"{name} bar lies outside the frozen interval")
        available = pd.DatetimeIndex(
            pd.to_datetime(normalized["available_at"], utc=True)
        )
        if (available <= normalized.index).any():
            raise AnchorInputError(f"{name} closed-bar contract failed")
    return timeframes, {
        "source_files_read": len(records),
        "source_start_utc": source_minimum.isoformat() if source_minimum else None,
        "source_end_utc": source_maximum.isoformat() if source_maximum else None,
        "schema_valid": True,
        "bar_counts": {name: len(frame) for name, frame in timeframes.items()},
        "verified_file_set_sha256": content["verified_file_set_sha256"],
        "parquet_checksum_manifest_sha256": content[
            "checksum_manifest_sha256"
        ],
    }


def _slice_timeframes(
    timeframes: Mapping[str, pd.DataFrame],
    *,
    evaluation_at: pd.Timestamp,
    warmup_days: int,
) -> dict[str, pd.DataFrame]:
    left = evaluation_at - pd.Timedelta(days=warmup_days)
    return {
        name: frame.loc[(frame.index >= left) & (frame.index <= evaluation_at)]
        for name, frame in timeframes.items()
    }


class _StructuralAccumulator:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.events: dict[tuple[str, str], dict[str, Any]] = {}

    def add(
        self,
        result: EvaluationResult,
        *,
        mode: str,
        observation_clock: str | None,
    ) -> None:
        snapshot = result.snapshot.to_record()
        evaluation = pd.Timestamp(result.snapshot.evaluation_at)
        self.snapshots.append(
            {
                **snapshot,
                "mapping_variant": PRIMARY_VARIANT.name,
                "mode": mode,
                "observation_clock": observation_clock,
                "session_date": evaluation.tz_convert(
                    "America/New_York"
                ).date().isoformat(),
            }
        )
        for attribute in EVENT_ATTRIBUTES:
            for event in getattr(result, attribute):
                key = (PRIMARY_VARIANT.name, event.event_id)
                record = {
                    **event.to_record(),
                    "mapping_variant": PRIMARY_VARIANT.name,
                    "event_family": attribute,
                    "last_observed_at": evaluation,
                }
                prior = self.events.get(key)
                record["first_observed_at"] = (
                    prior["first_observed_at"] if prior else evaluation
                )
                self.events[key] = record

    def snapshot_frame(self) -> pd.DataFrame:
        return pd.DataFrame.from_records(self.snapshots)

    def event_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame.from_records(list(self.events.values()))
        if frame.empty:
            return frame
        for column in (
            "created_at",
            "available_at",
            "interacted_at",
            "confirmed_at",
            "invalidated_at",
        ):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        return frame.sort_values(
            ["available_at", "mapping_variant", "event_id"], kind="mergesort"
        ).reset_index(drop=True)


def _evaluate_schedule(
    schedule: pd.DataFrame,
    *,
    timeframes: Mapping[str, pd.DataFrame],
    accumulator: _StructuralAccumulator,
) -> None:
    engine = ContextEngine(
        ContextEngineConfig(
            primary_mapping=PRIMARY_VARIANT.d005_mapping,
            optional_1m_refinement=False,
        )
    )
    for row in schedule.to_dict("records"):
        evaluation = pd.Timestamp(row["evaluation_at"]).tz_convert("UTC")
        if not (pd.Timestamp(FROZEN_START) <= evaluation < pd.Timestamp(FROZEN_END)):
            raise AnchorInputError("evaluation schedule escaped the frozen interval")
        result = engine.evaluate(
            _slice_timeframes(
                timeframes,
                evaluation_at=evaluation,
                warmup_days=PRIMARY_VARIANT.warmup_days,
            ),
            evaluation_at=evaluation,
            mapping_name=PRIMARY_VARIANT.d005_mapping,
            session_date=evaluation.tz_convert("America/New_York").date(),
        )
        observation_clock = row.get("observation_clock")
        accumulator.add(
            result,
            mode=str(row["mode"]),
            observation_clock=(
                None
                if observation_clock is None or pd.isna(observation_clock)
                else str(observation_clock)
            ),
        )


def _structural_e1_inventories(
    timeframes: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    study = EmpiricalStudyConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 28),
        mapping_variants=(PRIMARY_VARIANT,),
        parallel_workers=1,
    )
    study.validate()
    fixed, _ = fixed_observation_schedule(timeframes["1min"], study)
    accumulator = _StructuralAccumulator()
    _evaluate_schedule(fixed, timeframes=timeframes, accumulator=accumulator)
    fixed_snapshots = accumulator.snapshot_frame()
    fixed_events = accumulator.event_frame()
    pmh = build_pmh_pml_inventory(
        timeframes["1min"],
        study_config=study,
        d005_config=ContextEngineConfig(),
    )
    transitions = [
        dict(transition)
        for snapshot in fixed_snapshots.to_dict("records")
        for transition in snapshot["transitions"]
    ]
    pmh_sweep_times = tuple(
        pd.to_datetime(pmh.loc[pmh["swept"], "sweep_at"], utc=True)
    )
    event_schedule = event_schedule_from_inventory(
        variant=PRIMARY_VARIANT,
        event_records=fixed_events.to_dict("records"),
        transition_records=transitions,
        timeframes=timeframes,
        d005_config=ContextEngineConfig(primary_mapping="1h_5m_1m"),
        study_config=study,
        pmh_sweep_times=pmh_sweep_times,
    )
    _evaluate_schedule(
        event_schedule, timeframes=timeframes, accumulator=accumulator
    )
    return accumulator.event_frame(), fixed_snapshots, pmh


def _candidate_inventory(
    *,
    events: pd.DataFrame,
    fixed_snapshots: pd.DataFrame,
    pmh: pd.DataFrame,
    timeframes: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    d005 = ContextEngineConfig(primary_mapping="1h_5m_1m")
    mapping = d005.mapping("1h_5m_1m")
    candidates: list[pd.DataFrame] = []
    arrays = events[
        events["event_type"].isin(["raw_fvg", "order_block"])
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
        events["event_type"].eq("liquidity_sweep")
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

    pmh_work = pmh[pmh["swept"].fillna(False) & pmh["sweep_at"].notna()].copy()
    fixed_0830 = fixed_snapshots[
        fixed_snapshots["mode"].eq("fixed_clock")
        & fixed_snapshots["observation_clock"].eq("08:30")
    ].drop_duplicates("session_date", keep="last")
    prerequisite = {
        str(row["session_date"]): (
            int(row.get("parent_direction", 0) or 0) == 0
            and bool(row.get("balanced_ranging", False))
        )
        for row in fixed_0830.to_dict("records")
    }
    if not pmh_work.empty:
        pmh_work["mapping_variant"] = PRIMARY_VARIANT.name
        pmh_work["event_id"] = pmh_work["sweep_event_id"]
        pmh_work["event_type"] = "liquidity_sweep"
        pmh_work["timeframe"] = "1min"
        pmh_work["variant"] = "penetration_body_reclaim"
        pmh_work["available_at"] = pd.to_datetime(pmh_work["sweep_at"], utc=True)
        pmh_work["created_at"] = pmh_work["available_at"]
        pmh_work["interacted_at"] = pmh_work["available_at"]
        pmh_work["confirmed_at"] = pmh_work["available_at"]
        pmh_work["invalidated_at"] = pd.NaT
        pmh_work["zone_low"] = np.nan
        pmh_work["zone_high"] = np.nan
        pmh_work["parameters"] = "{}"
        pmh_work["candidate_event_at"] = pmh_work["available_at"]
        pmh_work["candidate_source"] = "pmh_pml_sweep"
        pmh_work["pmh_pml"] = True
        pmh_work["pmh_pml_prerequisites_met"] = pmh_work["session_date"].map(
            prerequisite
        ).fillna(False)
        candidates.append(pmh_work)
    if not candidates:
        return pd.DataFrame()

    frame = pd.concat(candidates, ignore_index=True, sort=False)
    frame = frame[
        pd.to_datetime(frame["candidate_event_at"], utc=True).ge(FROZEN_START)
        & pd.to_datetime(frame["candidate_event_at"], utc=True).lt(FROZEN_END)
    ]
    frame = frame.drop_duplicates(
        ["mapping_variant", "event_id", "candidate_event_at"]
    ).sort_values(
        ["mapping_variant", "candidate_event_at", "event_id"], kind="mergesort"
    )
    frame["candidate_event_at"] = pd.to_datetime(
        frame["candidate_event_at"], utc=True
    )
    frame["invalidated_at"] = pd.to_datetime(
        frame["invalidated_at"], utc=True, errors="coerce"
    )
    frame["direction"] = pd.to_numeric(frame["direction"], errors="coerce").fillna(0).astype(int)

    parent_swings = confirmed_swings(
        timeframes[mapping.parent], width=d005.mss.pivot_width
    )
    child_swings = confirmed_swings(
        timeframes[mapping.reaction], width=d005.mss.pivot_width
    )
    parent_direction, context_at = directions_at(
        parent_swings, frame["candidate_event_at"]
    )
    child_direction, _ = directions_at(child_swings, frame["candidate_event_at"])
    frame["parent_direction"] = parent_direction
    frame["parent_context_created_at"] = context_at
    frame["pre_candidate_child_direction"] = child_direction
    frame["liquidity_raid_direction"] = frame["taxonomy"].map(
        liquidity_raid_direction
    )
    frame["liquidity_expected_direction"] = frame["taxonomy"].map(
        expected_post_sweep_direction
    )
    frame["candidate_direction"] = frame["direction"]
    frame["candidate_parent_aligned"] = frame["parent_direction"].eq(0) | frame[
        "parent_direction"
    ].eq(frame["candidate_direction"])
    frame["outcome"] = [
        classify_outcome(
            candidate_type=str(event_type),
            candidate_direction=int(direction),
            parent_direction=int(parent),
            pre_candidate_child_direction=int(child),
        )
        for event_type, direction, parent, child in zip(
            frame["event_type"],
            frame["candidate_direction"],
            frame["parent_direction"],
            frame["pre_candidate_child_direction"],
            strict=True,
        )
    ]
    frame["candidate_id"] = frame["event_id"].astype(str)
    return frame.reset_index(drop=True)


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _session_label(stamp: pd.Timestamp) -> str:
    local = stamp.tz_convert("America/New_York")
    minutes = local.hour * 60 + local.minute
    if minutes >= 18 * 60:
        return "asia"
    if minutes < 8 * 60 + 30:
        return "premarket"
    if minutes < 12 * 60:
        return "ny_observation"
    if minutes < 17 * 60:
        return "ny_afternoon"
    return "maintenance"


def _forward_eligibility(
    anchor_at: pd.Timestamp,
    available_ns: np.ndarray,
) -> dict[str, bool]:
    position = int(np.searchsorted(available_ns, anchor_at.value, side="right")) - 1
    result: dict[str, bool] = {"source_bar_available": position >= 0}
    end = pd.Timestamp(FROZEN_END)
    for minutes in FROZEN_HORIZONS:
        endpoint = anchor_at + pd.Timedelta(minutes=minutes)
        endpoint_inside = endpoint <= end
        endpoint_position = (
            int(np.searchsorted(available_ns, endpoint.value, side="right")) - 1
            if endpoint_inside
            else -1
        )
        result[f"horizon_{minutes}m_eligible"] = bool(
            position >= 0 and endpoint_inside and endpoint_position > position
        )
    return result


def _anchor_rows(
    sequences: pd.DataFrame,
    one_minute: pd.DataFrame,
) -> pd.DataFrame:
    eligible = sequences[
        sequences["mapping_variant"].eq("1h_5m")
        & sequences["outcome"].eq("reversal")
        & sequences["displacement_id"].notna()
        & sequences["displacement_confirmed_at"].notna()
        & sequences["candidate_direction"].ne(0)
    ].copy()
    eligible["main_candidate_eligible"] = ~(
        eligible["pmh_pml"].fillna(False).astype(bool)
        & ~eligible["pmh_pml_prerequisites_met"].fillna(False).astype(bool)
    )
    eligible = eligible[eligible["main_candidate_eligible"]]
    eligible["displacement_confirmed_at"] = pd.to_datetime(
        eligible["displacement_confirmed_at"], utc=True
    )
    eligible = eligible[
        eligible["displacement_confirmed_at"].ge(FROZEN_START)
        & eligible["displacement_confirmed_at"].lt(FROZEN_END)
    ].sort_values(
        ["sequence_id", "displacement_confirmed_at", "displacement_id"],
        kind="mergesort",
    ).drop_duplicates("sequence_id", keep="first")

    available_ns = pd.DatetimeIndex(
        pd.to_datetime(one_minute["available_at"], utc=True)
    ).as_unit("ns").asi8
    rows: list[dict[str, Any]] = []
    for sequence in eligible.to_dict("records"):
        confirmation_state = (
            "engine_confirmed"
            if bool(sequence.get("engine_selected_reaction_confirmed", False))
            else "never_confirmed"
        )

        def add(anchor_type: str, timestamp: object, event_id: object) -> None:
            if timestamp is None or pd.isna(timestamp) or event_id is None:
                return
            stamp = pd.Timestamp(timestamp).tz_convert("UTC")
            if not (pd.Timestamp(FROZEN_START) <= stamp < pd.Timestamp(FROZEN_END)):
                return
            anchor_id = _stable_id(
                "D005-E3-v1", sequence["sequence_id"], anchor_type, event_id
            )
            local = stamp.tz_convert("America/New_York")
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_id": anchor_id,
                    "sequence_id": str(sequence["sequence_id"]),
                    "anchor_event_id": str(event_id),
                    "anchor_timestamp": stamp,
                    "anchor_type": anchor_type,
                    "direction": int(sequence["candidate_direction"]),
                    "direction_source": (
                        "displacement_direction"
                        if anchor_type == PRIMARY_ANCHOR
                        else "refinement_array_direction"
                    ),
                    "candidate_timestamp": pd.Timestamp(
                        sequence["candidate_at"]
                    ).tz_convert("UTC"),
                    "mss_confirmation_timestamp": (
                        pd.Timestamp(sequence["mss_confirmed_at"]).tz_convert("UTC")
                        if not pd.isna(sequence["mss_confirmed_at"])
                        else pd.NaT
                    ),
                    "displacement_creation_timestamp": (
                        pd.Timestamp(sequence["displacement_created_at"]).tz_convert("UTC")
                        if not pd.isna(sequence["displacement_created_at"])
                        else pd.NaT
                    ),
                    "displacement_confirmation_timestamp": pd.Timestamp(
                        sequence["displacement_confirmed_at"]
                    ).tz_convert("UTC"),
                    "refinement_creation_timestamp": (
                        pd.Timestamp(sequence["refinement_created_at"]).tz_convert("UTC")
                        if not pd.isna(sequence["refinement_created_at"])
                        else pd.NaT
                    ),
                    "confirmation_state": confirmation_state,
                    "sequence_status": str(sequence["sequence_status"]),
                    "deduplication_identity": (
                        f"{sequence['sequence_id']}|{anchor_type}"
                    ),
                    "anchor_causally_observable": True,
                    "anchor_selected_using_later_completion": False,
                    "interval_eligible": True,
                    "session": _session_label(stamp),
                    "session_date": local.date().isoformat(),
                    **_forward_eligibility(stamp, available_ns),
                }
            )

        add(
            PRIMARY_ANCHOR,
            sequence["displacement_confirmed_at"],
            sequence["displacement_id"],
        )
        add(
            SECONDARY_ANCHOR,
            sequence.get("refinement_created_at"),
            sequence.get("refinement_id"),
        )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return frame
    return frame.sort_values(
        ["anchor_timestamp", "sequence_id", "anchor_type", "event_id"],
        kind="mergesort",
    ).drop_duplicates(
        ["sequence_id", "anchor_type"], keep="first"
    ).reset_index(drop=True)


def assert_structural_output(frame: pd.DataFrame) -> None:
    lowered = [str(column).lower() for column in frame.columns]
    forbidden = sorted(
        column
        for column in lowered
        if any(token in column for token in FORBIDDEN_OUTPUT_TOKENS)
    )
    if forbidden:
        raise AnchorInputError(f"outcome-bearing structural columns: {forbidden}")
    if "anchor_timestamp" in frame:
        dtype = frame["anchor_timestamp"].dtype
        timezone = getattr(dtype, "tz", None)
        if timezone is None or str(timezone) not in {"UTC", "UTC+00:00"}:
            raise AnchorInputError("anchor timestamps are not UTC")
    if not frame.empty:
        if frame["event_id"].duplicated().any():
            raise AnchorInputError("duplicate structural event identifiers")
        if frame.duplicated(["sequence_id", "anchor_type"]).any():
            raise AnchorInputError("duplicate sequence/anchor identity")


def inventory_fingerprint(frame: pd.DataFrame) -> str:
    assert_structural_output(frame)
    records: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        normalized: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, pd.Timestamp):
                normalized[key] = None if pd.isna(value) else value.isoformat()
            elif isinstance(value, np.generic):
                normalized[key] = value.item()
            elif pd.isna(value):
                normalized[key] = None
            else:
                normalized[key] = value
        records.append(normalized)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "columns": list(frame.columns),
        "records": records,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def construct_2026_anchor_inventory(
    *,
    repository_root: Path,
    config: IndependentReplication2026Config,
) -> AnchorInventoryResult:
    """Construct and retain only the frozen structural E4 input cohort."""

    config.validate()
    if config.outcome_calculation_authorized:
        raise AnchorInputError("outcome authorization is forbidden in this stage")
    root = repository_root.resolve()
    mismatches = [
        relative
        for relative, expected in FROZEN_ANCHOR_RULE_HASHES.items()
        if not (root / relative).is_file()
        or sha256_file(root / relative) != expected
    ]
    if mismatches:
        raise AnchorInputError(
            f"frozen anchor-rule source hash mismatch: {mismatches}"
        )
    timeframes, source = load_2026_structural_timeframes(root)
    events, fixed_snapshots, pmh = _structural_e1_inventories(timeframes)
    candidates = _candidate_inventory(
        events=events,
        fixed_snapshots=fixed_snapshots,
        pmh=pmh,
        timeframes=timeframes,
    )
    diagnostic = ReactionAnchorDiagnosticConfig(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 7, 28),
        mapping_variants=(PRIMARY_VARIANT,),
    )
    diagnostic.validate()
    confirmations = confirmation_inventory(timeframes, diagnostic)
    sequences, _ = reconstruct_uncapped_sequences(
        candidates=candidates,
        confirmations=confirmations,
        events=events,
        timeframes=timeframes,
        config=diagnostic,
    )
    sequences, _ = evaluate_uncapped_core_snapshots(
        sequences, timeframes=timeframes, config=diagnostic
    )
    anchors = _anchor_rows(sequences, timeframes["1min"])
    assert_structural_output(anchors)
    fingerprint = inventory_fingerprint(anchors)
    endpoint_exclusions = {
        f"{minutes}m": int(
            (~anchors[f"horizon_{minutes}m_eligible"]).sum()
        )
        if not anchors.empty
        else 0
        for minutes in FROZEN_HORIZONS
    }
    return AnchorInventoryResult(
        anchors=anchors,
        inventory_fingerprint=fingerprint,
        structural_schema=tuple(anchors.columns),
        diagnostics={
            **source,
            "historical_rule_provenance": dict(HISTORICAL_RULE_PROVENANCE),
            "endpoint_or_missing_bar_exclusions": endpoint_exclusions,
            "historical_selection_invoked": False,
            "forward_outcome_module_invoked": False,
            "final_output_directory_created": False,
        },
    )


__all__ = [
    "AnchorInputError",
    "AnchorInventoryResult",
    "SCHEMA_VERSION",
    "HISTORICAL_RULE_PROVENANCE",
    "assert_structural_output",
    "build_structural_timeframes",
    "construct_2026_anchor_inventory",
    "inventory_fingerprint",
    "load_2026_structural_timeframes",
    "validate_tick_values",
]
