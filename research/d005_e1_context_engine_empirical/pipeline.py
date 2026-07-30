"""Two-pass fixed-clock and event-driven D005_E1 study runner."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
from time import perf_counter
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from research.context_engine.bars import (
    TIMEFRAME_MINUTES,
    build_timeframes,
)
from research.context_engine.config import ContextEngineConfig
from research.context_engine.engine import ContextEngine, EvaluationResult
from research.context_engine.pipeline import load_one_minute_bars
from research.context_engine.reporting import sha256_file

from .analysis import (
    build_snapshot_summaries,
    flatten_transitions,
    forward_stability_summary,
    fvg_category_summary,
    fvg_event_statistics,
    gate_attribution,
    order_block_event_statistics,
    pmh_pml_summary,
    timing_guardrail_summary,
    transition_funnel,
)
from .config import EmpiricalStudyConfig, MappingVariant
from .outcomes import (
    add_causal_volatility_regime,
    build_forward_outcomes,
    event_anchors,
    session_label,
    transition_anchors,
)
from .pmh import build_pmh_pml_inventory
from .reporting import persist_study_artifacts
from .schedule import (
    build_data_quality_periods,
    event_schedule_from_inventory,
    fixed_observation_schedule,
)


EVENT_ATTRIBUTES = (
    "fvg_events",
    "order_block_events",
    "liquidity_events",
    "confirmation_events",
    "conflict_events",
)


_FORK_TIMEFRAMES: Mapping[str, pd.DataFrame] | None = None
_FORK_STUDY_CONFIG: EmpiricalStudyConfig | None = None


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def _directory_fingerprint(path: Path) -> str:
    """Hash material files without reading or mutating their contents."""

    if not path.exists():
        return "absent"
    records = []
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        records.append(
            f"{item.relative_to(path)}:{item.stat().st_size}:{sha256_file(item)}"
        )
    return hashlib.sha256("|".join(records).encode("utf-8")).hexdigest()


def _d005_config(variant: MappingVariant) -> ContextEngineConfig:
    return ContextEngineConfig(
        primary_mapping=variant.d005_mapping,
        optional_1m_refinement=variant.optional_1m_refinement,
    )


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


def _snapshot_signature(record: Mapping[str, object]) -> str:
    transitions = [
        {
            "from_state": item.get("from_state"),
            "to_state": item.get("to_state"),
            "reason": item.get("reason"),
            "evidence_ids": item.get("evidence_ids"),
        }
        for item in record.get("transitions", [])
    ]
    payload = {
        "state": record["state"],
        "direction": record["direction"],
        "outcome": record["outcome"],
        "parent_direction": record["parent_direction"],
        "child_direction": record["child_direction"],
        "no_trade_reasons": record["no_trade_reasons"],
        "evidence_ids": record["evidence_ids"],
        "transitions": transitions,
        "balanced_ranging": record["balanced_ranging"],
        "trapped_between_arrays": record["trapped_between_arrays"],
        "missing_required_data": record["missing_required_data"],
        "overextended": record["overextended"],
        "risk_valid": record["risk_valid"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _chronological_chunks(
    frame: pd.DataFrame,
    count: int,
) -> list[pd.DataFrame]:
    boundaries = np.linspace(
        0,
        len(frame),
        count + 1,
        dtype=int,
    )
    return [
        frame.iloc[left:right].reset_index(drop=True)
        for left, right in zip(
            boundaries[:-1],
            boundaries[1:],
            strict=True,
        )
        if right > left
    ]


class StudyAccumulator:
    """Retain snapshots plus the latest causal lifecycle for each event."""

    def __init__(self, config: EmpiricalStudyConfig) -> None:
        self.config = config
        self.snapshots: list[dict[str, object]] = []
        self.events: dict[tuple[str, str], dict[str, object]] = {}
        self.last_event_signature: dict[str, str] = {}
        self.event_evaluations_attempted = 0
        self.event_evaluations_deduplicated = 0

    def add(
        self,
        result: EvaluationResult,
        *,
        variant: MappingVariant,
        mode: str,
        observation_clock: str | None,
        trigger_types: Sequence[str] = (),
    ) -> bool:
        snapshot = result.snapshot.to_record()
        evaluation = pd.Timestamp(result.snapshot.evaluation_at)
        local = evaluation.tz_convert(self.config.timezone)
        mapping = _d005_config(variant).mapping(variant.d005_mapping)
        record = {
            **snapshot,
            "snapshot_id": _stable_id(
                self.config.version,
                variant.name,
                mode,
                evaluation,
            ),
            "mapping_variant": variant.name,
            "d005_mapping": variant.d005_mapping,
            "optional_1m_refinement": variant.optional_1m_refinement,
            "mode": mode,
            "observation_clock": observation_clock,
            "trigger_types": list(trigger_types),
            "session_date": local.date().isoformat(),
            "year": local.year,
            "month": f"{local.year:04d}-{local.month:02d}",
            "session": session_label(evaluation, self.config.timezone),
            "dst": bool(local.dst() and local.dst().total_seconds()),
            "timezone": self.config.timezone,
            "warmup_days": variant.warmup_days,
            "reaction_minutes": TIMEFRAME_MINUTES[mapping.reaction],
            "confirmation_timeout_bars": _d005_config(
                variant
            ).mss.confirmation_timeout_bars,
            "study_config_fingerprint": self.config.fingerprint(),
            "research_only": True,
        }
        signature = _snapshot_signature(record)
        record["snapshot_signature"] = signature
        keep = True
        if mode == "event_driven":
            self.event_evaluations_attempted += 1
            previous = self.last_event_signature.get(variant.name)
            if (
                self.config.event_snapshot_deduplication
                and previous == signature
            ):
                self.event_evaluations_deduplicated += 1
                keep = False
            self.last_event_signature[variant.name] = signature
        if keep:
            self.snapshots.append(record)
        self._add_events(
            result,
            variant=variant,
            mode=mode,
            evaluation=evaluation,
        )
        return keep

    def _add_events(
        self,
        result: EvaluationResult,
        *,
        variant: MappingVariant,
        mode: str,
        evaluation: pd.Timestamp,
    ) -> None:
        for attribute in EVENT_ATTRIBUTES:
            for event in getattr(result, attribute):
                key = (variant.name, event.event_id)
                signature = hashlib.sha256(
                    json.dumps(
                        {
                            "direction": int(event.direction),
                            "variant": event.variant,
                            "taxonomy": event.taxonomy,
                            "parameters": event.parameters,
                            "level": event.level,
                            "zone_low": event.zone_low,
                            "zone_high": event.zone_high,
                            "interacted_at": event.interacted_at,
                            "confirmed_at": event.confirmed_at,
                            "invalidated_at": event.invalidated_at,
                        },
                        sort_keys=True,
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                prior = self.events.get(key)
                if prior is not None and prior.get(
                    "_event_signature"
                ) == signature:
                    prior["last_observed_at"] = evaluation
                    prior["observed_in_modes"] = sorted(
                        set(prior["observed_in_modes"]) | {mode}
                    )
                    continue
                record = {
                    **event.to_record(),
                    "mapping_variant": variant.name,
                    "event_family": attribute,
                    "last_observed_at": evaluation,
                    "observed_in_modes": [mode],
                    "_event_signature": signature,
                }
                if prior is None:
                    record["first_observed_at"] = evaluation
                    self.events[key] = record
                    continue
                record["first_observed_at"] = prior["first_observed_at"]
                record["observed_in_modes"] = sorted(
                    set(prior["observed_in_modes"]) | {mode}
                )
                self.events[key] = record

    def snapshot_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame.from_records(self.snapshots)
        if frame.empty:
            return frame
        frame = frame.sort_values(
            ["evaluation_at", "mode", "mapping_variant"],
            kind="mergesort",
        ).reset_index(drop=True)
        event_mask = frame["mode"].eq("event_driven")
        previous = frame.loc[event_mask].groupby(
            "mapping_variant",
            sort=False,
        )["snapshot_signature"].shift()
        duplicate_index = frame.loc[event_mask].index[
            frame.loc[event_mask, "snapshot_signature"].eq(previous)
        ]
        return frame.drop(index=duplicate_index).reset_index(drop=True)

    def event_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame.from_records(list(self.events.values()))
        if frame.empty:
            return frame
        frame = frame.drop(columns=["_event_signature"], errors="ignore")
        return frame.sort_values(
            ["available_at", "mapping_variant", "event_id"],
            kind="mergesort",
        ).reset_index(drop=True)

    def merge(self, other: "StudyAccumulator") -> None:
        """Merge one mapping-local accumulator deterministically."""

        self.snapshots.extend(other.snapshots)
        self.event_evaluations_attempted += (
            other.event_evaluations_attempted
        )
        self.event_evaluations_deduplicated += (
            other.event_evaluations_deduplicated
        )
        for key, incoming in other.events.items():
            prior = self.events.get(key)
            if prior is None:
                self.events[key] = incoming
                continue
            incoming_at = pd.Timestamp(incoming["last_observed_at"])
            prior_at = pd.Timestamp(prior["last_observed_at"])
            selected = dict(incoming if incoming_at >= prior_at else prior)
            selected["first_observed_at"] = min(
                pd.Timestamp(incoming["first_observed_at"]),
                pd.Timestamp(prior["first_observed_at"]),
            )
            selected["observed_in_modes"] = sorted(
                set(incoming["observed_in_modes"])
                | set(prior["observed_in_modes"])
            )
            self.events[key] = selected


def _evaluate_rows(
    *,
    rows: pd.DataFrame,
    variant: MappingVariant,
    timeframes: Mapping[str, pd.DataFrame],
    accumulator: StudyAccumulator,
    progress_every: int,
) -> None:
    d005_config = _d005_config(variant)
    engine = ContextEngine(d005_config)
    total = len(rows)
    for position, row in enumerate(rows.to_dict("records"), start=1):
        evaluation = pd.Timestamp(row["evaluation_at"]).tz_convert("UTC")
        sliced = _slice_timeframes(
            timeframes,
            evaluation_at=evaluation,
            warmup_days=variant.warmup_days,
        )
        result = engine.evaluate(
            sliced,
            evaluation_at=evaluation,
            mapping_name=variant.d005_mapping,
            session_date=evaluation.tz_convert(
                accumulator.config.timezone
            ).date(),
        )
        accumulator.add(
            result,
            variant=variant,
            mode=str(row["mode"]),
            observation_clock=(
                str(row["observation_clock"])
                if row.get("observation_clock") is not None
                and not pd.isna(row.get("observation_clock"))
                else None
            ),
            trigger_types=tuple(row.get("trigger_types", ()) or ()),
        )
        if progress_every and position % progress_every == 0:
            print(
                f"E1 {variant.name} {row['mode']}: "
                f"{position}/{total}",
                flush=True,
            )


def _fork_worker(
    payload: tuple[MappingVariant, pd.DataFrame, int],
) -> StudyAccumulator:
    """Evaluate one mapping using read-only frames inherited by fork."""

    variant, rows, progress_every = payload
    if _FORK_TIMEFRAMES is None or _FORK_STUDY_CONFIG is None:
        raise RuntimeError("parallel E1 worker was not initialized")
    accumulator = StudyAccumulator(_FORK_STUDY_CONFIG)
    _evaluate_rows(
        rows=rows,
        variant=variant,
        timeframes=_FORK_TIMEFRAMES,
        accumulator=accumulator,
        progress_every=progress_every,
    )
    return accumulator


def _evaluate_mapping_batches(
    *,
    batches: Sequence[tuple[MappingVariant, pd.DataFrame]],
    timeframes: Mapping[str, pd.DataFrame],
    config: EmpiricalStudyConfig,
    accumulator: StudyAccumulator,
    progress_every: int,
    phase: str,
) -> None:
    """Run independent mappings concurrently without sharing mutable state."""

    active = [(variant, rows) for variant, rows in batches if not rows.empty]
    if not active:
        return
    workers = min(config.parallel_workers, len(active))
    if workers == 1:
        for variant, rows in active:
            local = StudyAccumulator(config)
            _evaluate_rows(
                rows=rows,
                variant=variant,
                timeframes=timeframes,
                accumulator=local,
                progress_every=progress_every,
            )
            accumulator.merge(local)
        return

    global _FORK_TIMEFRAMES, _FORK_STUDY_CONFIG
    _FORK_TIMEFRAMES = timeframes
    _FORK_STUDY_CONFIG = config
    context = multiprocessing.get_context("fork")
    try:
        executor = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
        )
    except (OSError, PermissionError):
        _FORK_TIMEFRAMES = None
        _FORK_STUDY_CONFIG = None
        print(
            "E1 process workers unavailable; using deterministic serial "
            f"{phase} evaluation",
            flush=True,
        )
        for variant, rows in active:
            local = StudyAccumulator(config)
            _evaluate_rows(
                rows=rows,
                variant=variant,
                timeframes=timeframes,
                accumulator=local,
                progress_every=progress_every,
            )
            accumulator.merge(local)
        return
    with executor:
        futures = {
            executor.submit(
                _fork_worker,
                (variant, rows, progress_every),
            ): variant.name
            for variant, rows in active
        }
        for future in as_completed(futures):
            accumulator.merge(future.result())
            print(
                f"E1 {phase} mapping complete: {futures[future]}",
                flush=True,
            )
    _FORK_TIMEFRAMES = None
    _FORK_STUDY_CONFIG = None


def _event_inventory_by_variant(
    events: pd.DataFrame,
    variant_name: str,
) -> list[dict[str, object]]:
    if events.empty:
        return []
    return events[events["mapping_variant"].eq(variant_name)].to_dict(
        "records"
    )


def _transition_inventory_by_variant(
    snapshots: pd.DataFrame,
    variant_name: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    subset = snapshots[snapshots["mapping_variant"].eq(variant_name)]
    for snapshot in subset.to_dict("records"):
        for transition in snapshot["transitions"]:
            records.append(dict(transition))
    return records


def _annotate_pmh_inventory(
    pmh: pd.DataFrame,
    snapshots: pd.DataFrame,
    config: EmpiricalStudyConfig,
) -> pd.DataFrame:
    if pmh.empty:
        return pmh
    fixed_0830 = snapshots[
        snapshots["mode"].eq("fixed_clock")
        & snapshots["observation_clock"].eq("08:30")
    ]
    reaction = snapshots[
        snapshots["state"].eq("reaction_confirmed")
    ].sort_values("evaluation_at")
    rows: list[dict[str, object]] = []
    for level in pmh.to_dict("records"):
        for variant in config.mapping_variants:
            context = fixed_0830[
                fixed_0830["session_date"].eq(level["session_date"])
                & fixed_0830["mapping_variant"].eq(variant.name)
            ]
            context_record = (
                context.iloc[-1].to_dict() if not context.empty else {}
            )
            sweep_at = level.get("sweep_at")
            later = reaction[
                reaction["session_date"].eq(level["session_date"])
                & reaction["mapping_variant"].eq(variant.name)
            ]
            if sweep_at is not None and not pd.isna(sweep_at):
                later = later[
                    pd.to_datetime(later["evaluation_at"], utc=True)
                    >= pd.Timestamp(sweep_at)
                ]
            later_record = later.iloc[0].to_dict() if not later.empty else {}
            later_direction = int(later_record.get("direction", 0) or 0)
            sweep_direction = int(level.get("direction", 0) or 0)
            rows.append(
                {
                    **level,
                    "mapping_variant": variant.name,
                    "parent_direction_at_0830": int(
                        context_record.get("parent_direction", 0) or 0
                    ),
                    "balanced_ranging_at_0830": bool(
                        context_record.get("balanced_ranging", False)
                    ),
                    "htf_unresolved_at_0830": int(
                        context_record.get("parent_direction", 0) or 0
                    )
                    == 0,
                    "valid_htf_context_at_0830": int(
                        context_record.get("parent_direction", 0) or 0
                    )
                    != 0,
                    "pmh_pml_prerequisites_met": (
                        int(context_record.get("parent_direction", 0) or 0)
                        == 0
                        and bool(
                            context_record.get("balanced_ranging", False)
                        )
                    ),
                    "later_reaction_confirmed": bool(later_record),
                    "later_reaction_direction": later_direction,
                    "agrees_with_later_reaction": (
                        sweep_direction == later_direction
                        if sweep_direction and later_direction
                        else None
                    ),
                    "overrides_htf_context": False,
                    "independent_bias": False,
                }
            )
    return pd.DataFrame.from_records(rows)


def _opposing_levels_for_anchors(
    anchors: pd.DataFrame,
    events: pd.DataFrame,
    one_minute: pd.DataFrame,
) -> pd.DataFrame:
    if anchors.empty:
        return anchors
    levels = events[
        events["event_type"].eq("liquidity_level")
        & events["level"].notna()
    ].copy()
    if levels.empty:
        result = anchors.copy()
        result["opposing_liquidity_level"] = np.nan
        return result
    available = pd.DatetimeIndex(one_minute.index) + pd.Timedelta(minutes=1)
    available_ns = available.as_unit("ns").asi8
    closes = one_minute["close"].to_numpy(dtype=float, copy=False)
    result = anchors.copy()
    result["opposing_liquidity_level"] = np.nan

    class Fenwick:
        def __init__(self, size: int) -> None:
            self.values = np.zeros(size + 1, dtype=np.int64)

        def add(self, index: int) -> None:
            position = index + 1
            while position < len(self.values):
                self.values[position] += 1
                position += position & -position

        def prefix(self, end: int) -> int:
            total = 0
            position = end
            while position:
                total += int(self.values[position])
                position -= position & -position
            return total

        def find_order(self, order: int) -> int:
            position = 0
            bit = 1 << (len(self.values).bit_length() - 1)
            remaining = order
            while bit:
                candidate = position + bit
                if (
                    candidate < len(self.values)
                    and int(self.values[candidate]) < remaining
                ):
                    position = candidate
                    remaining -= int(self.values[candidate])
                bit >>= 1
            return position

    for mapping_variant, anchor_group in result.groupby(
        "mapping_variant",
        sort=False,
    ):
        level_group = levels[
            levels["mapping_variant"].eq(mapping_variant)
        ].copy()
        if level_group.empty:
            continue
        level_group["available_at"] = pd.to_datetime(
            level_group["available_at"],
            utc=True,
        )
        level_group = level_group.sort_values("available_at")
        level_times = (
            pd.DatetimeIndex(level_group["available_at"])
            .as_unit("ns")
            .asi8
        )
        level_values = level_group["level"].to_numpy(dtype=float)
        coordinates = np.unique(level_values)
        tree = Fenwick(len(coordinates))
        level_cursor = 0
        ordered_anchors = anchor_group.assign(
            _anchor_at=pd.to_datetime(
                anchor_group["anchor_at"],
                utc=True,
            )
        ).sort_values("_anchor_at")
        for row_index, anchor in ordered_anchors.iterrows():
            anchor_at = pd.Timestamp(anchor["_anchor_at"])
            while (
                level_cursor < len(level_times)
                and level_times[level_cursor] <= anchor_at.value
            ):
                coordinate = int(
                    np.searchsorted(
                        coordinates,
                        level_values[level_cursor],
                    )
                )
                tree.add(coordinate)
                level_cursor += 1
            direction = int(anchor.get("direction", 0) or 0)
            if not direction:
                continue
            position = int(
                np.searchsorted(
                    available_ns,
                    anchor_at.value,
                    side="right",
                )
            ) - 1
            if position < 0:
                continue
            price = float(closes[position])
            if direction > 0:
                boundary = int(
                    np.searchsorted(coordinates, price, side="right")
                )
                before = tree.prefix(boundary)
                total = tree.prefix(len(coordinates))
                if total > before:
                    coordinate = tree.find_order(before + 1)
                    result.at[
                        row_index,
                        "opposing_liquidity_level",
                    ] = float(coordinates[coordinate])
            else:
                boundary = int(
                    np.searchsorted(coordinates, price, side="left")
                )
                count = tree.prefix(boundary)
                if count:
                    coordinate = tree.find_order(count)
                    result.at[
                        row_index,
                        "opposing_liquidity_level",
                    ] = float(coordinates[coordinate])
    return result


def run_empirical_study(
    *,
    one_minute_source: Path,
    output_dir: Path,
    config: EmpiricalStudyConfig,
    report_path: Path | None = None,
    command: Sequence[str] = (),
    progress_every: int = 1000,
) -> dict[str, object]:
    """Run fixed and event-driven E1 without modifying D005 outputs."""

    config.validate()
    started = perf_counter()
    one_minute_source = one_minute_source.resolve()
    protected_d005_output = (
        Path("research_outputs/D005_CONTEXT_ENGINE").resolve()
    )
    resolved_output = output_dir.resolve()
    if resolved_output == protected_d005_output:
        raise ValueError("E1 cannot write into the existing D005 output")
    protected_before = _directory_fingerprint(protected_d005_output)
    one_minute_raw, input_provenance = load_one_minute_bars(
        one_minute_source,
        start_date=config.start_date,
        end_date=config.end_date,
        lookback_days=max(
            item.warmup_days for item in config.mapping_variants
        ),
    )
    timeframes = build_timeframes(one_minute_raw)
    one_minute = timeframes["1min"]
    data_quality = build_data_quality_periods(one_minute, config)
    fixed_schedule, excluded = fixed_observation_schedule(
        one_minute, config
    )
    pmh_raw = build_pmh_pml_inventory(
        one_minute,
        study_config=config,
        d005_config=ContextEngineConfig(),
    )

    accumulator = StudyAccumulator(config)
    _evaluate_mapping_batches(
        batches=[
            (variant, fixed_schedule)
            for variant in config.mapping_variants
        ],
        timeframes=timeframes,
        config=config,
        accumulator=accumulator,
        progress_every=progress_every,
        phase="fixed_clock",
    )

    fixed_snapshots = accumulator.snapshot_frame()
    fixed_events = accumulator.event_frame()
    pmh_sweep_times = tuple(
        pd.to_datetime(
            pmh_raw.loc[pmh_raw["swept"], "sweep_at"], utc=True
        )
    )
    event_schedules: list[pd.DataFrame] = []
    event_batches: list[tuple[MappingVariant, pd.DataFrame]] = []
    for variant in config.mapping_variants:
        event_schedule = event_schedule_from_inventory(
            variant=variant,
            event_records=_event_inventory_by_variant(
                fixed_events, variant.name
            ),
            transition_records=_transition_inventory_by_variant(
                fixed_snapshots, variant.name
            ),
            timeframes=timeframes,
            d005_config=_d005_config(variant),
            study_config=config,
            pmh_sweep_times=pmh_sweep_times,
        )
        event_schedules.append(event_schedule)
        if (
            variant.optional_1m_refinement
            and config.parallel_workers > 1
            and len(event_schedule) > config.parallel_workers
        ):
            event_batches.extend(
                (variant, chunk)
                for chunk in _chronological_chunks(
                    event_schedule,
                    config.parallel_workers,
                )
            )
        else:
            event_batches.append((variant, event_schedule))
    _evaluate_mapping_batches(
        batches=event_batches,
        timeframes=timeframes,
        config=config,
        accumulator=accumulator,
        progress_every=progress_every,
        phase="event_driven",
    )

    snapshots = accumulator.snapshot_frame()
    snapshots = add_causal_volatility_regime(
        snapshots.rename(columns={"evaluation_at": "anchor_at"}),
        timeframes["1D"],
        config,
    ).rename(columns={"anchor_at": "evaluation_at"})
    events = accumulator.event_frame()
    transitions = flatten_transitions(snapshots)
    funnel = transition_funnel(transitions)
    gates, gate_overlap = gate_attribution(snapshots, config=config)
    summaries = build_snapshot_summaries(snapshots, config=config)
    timing = timing_guardrail_summary(snapshots)
    pmh = _annotate_pmh_inventory(pmh_raw, snapshots, config)

    fvg_statistics = fvg_event_statistics(
        events, one_minute, config=config
    )
    reaction_minutes_by_variant = {
        variant.name: TIMEFRAME_MINUTES[
            _d005_config(variant).mapping(
                variant.d005_mapping
            ).reaction
        ]
        for variant in config.mapping_variants
    }
    ob_statistics, ob_summary = order_block_event_statistics(
        events,
        reaction_minutes_by_variant=reaction_minutes_by_variant,
    )

    anchors = pd.concat(
        [
            transition_anchors(transitions),
            event_anchors(
                events.to_dict("records"),
                timezone=config.timezone,
            ),
        ],
        ignore_index=True,
    )
    if not anchors.empty:
        anchors = anchors[
            pd.to_datetime(anchors["anchor_at"], utc=True).between(
                pd.Timestamp(config.start_date, tz=config.timezone).tz_convert(
                    "UTC"
                ),
                pd.Timestamp(
                    config.end_date + pd.Timedelta(days=1),
                    tz=config.timezone,
                ).tz_convert("UTC"),
            )
        ].drop_duplicates(
            [
                "anchor_type",
                "source_id",
                "mapping_variant",
                "anchor_at",
            ]
        )
        anchors = _opposing_levels_for_anchors(
            anchors, events, one_minute
        )
        anchors = add_causal_volatility_regime(
            anchors,
            timeframes["1D"],
            config,
        )
        anchor_local = pd.to_datetime(
            anchors["anchor_at"],
            utc=True,
        ).dt.tz_convert(config.timezone)
        anchors["session_date"] = anchor_local.dt.date.astype(str)
        anchors["year"] = anchor_local.dt.year
        anchors["month"] = anchor_local.dt.strftime("%Y-%m")
        anchors["session"] = anchor_local.map(
            lambda value: session_label(value, config.timezone)
        )
        anchors["dst"] = anchor_local.map(
            lambda value: bool(
                value.dst() and value.dst().total_seconds()
            )
        )
    forward = build_forward_outcomes(
        anchors, one_minute, config=config
    )

    if not fvg_statistics.empty and not forward.empty:
        fvg_excursion = (
            forward[
                forward["horizon"].eq("60m")
                & forward["anchor_type"].eq("raw_fvg")
            ]
            .groupby(["source_id", "mapping_variant"], dropna=False)
            .agg(
                favorable_excursion_60m=("mfe", "max"),
                adverse_excursion_60m=("mae", "max"),
            )
            .reset_index()
            .rename(columns={"source_id": "event_id"})
        )
        fvg_statistics = fvg_statistics.merge(
            fvg_excursion,
            on=["event_id", "mapping_variant"],
            how="left",
        )
    fvg_summary = fvg_category_summary(fvg_statistics)

    if not ob_statistics.empty and not forward.empty:
        excursion = (
            forward[
                forward["horizon"].eq("60m")
                & forward["anchor_type"].eq("order_block")
            ]
            .groupby(["source_id", "mapping_variant"], dropna=False)
            .agg(
                favorable_excursion_60m=("mfe", "max"),
                adverse_excursion_60m=("mae", "max"),
            )
            .reset_index()
            .rename(columns={"source_id": "event_id"})
        )
        ob_statistics = ob_statistics.merge(
            excursion,
            on=["event_id", "mapping_variant"],
            how="left",
        )
        ob_summary = (
            ob_statistics.groupby(
                ["mapping_variant", "variant"], dropna=False
            )
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
                mean_favorable_excursion_60m=(
                    "favorable_excursion_60m",
                    "mean",
                ),
                mean_adverse_excursion_60m=(
                    "adverse_excursion_60m",
                    "mean",
                ),
                fvg_overlap_rate=("overlap_with_fvg", "mean"),
                liquidity_overlap_rate=(
                    "overlap_with_liquidity_event",
                    "mean",
                ),
            )
            .reset_index()
        )
    pmh_summary = pmh_pml_summary(pmh)
    forward_summary = forward_stability_summary(forward)

    conflicts = snapshots[snapshots["state"].eq("conflict")].copy()
    invalidations = snapshots[
        snapshots["state"].eq("invalidated")
    ].copy()
    liquidity_events = events[
        events["event_family"].isin(
            ["liquidity_events", "confirmation_events"]
        )
        & events["event_type"].isin(
            ["liquidity_level", "liquidity_sweep"]
        )
    ].copy()
    schedule_frame = pd.concat(
        [frame for frame in event_schedules if not frame.empty],
        ignore_index=True,
    ) if any(not frame.empty for frame in event_schedules) else pd.DataFrame()
    frames = {
        "context_snapshots": snapshots,
        "state_transitions": transitions,
        "transition_funnel": funnel,
        "gate_attribution": gates,
        "gate_overlap": gate_overlap,
        "conflicts": conflicts,
        "invalidations": invalidations,
        "fvg_event_statistics": fvg_statistics,
        "fvg_category_summary": fvg_summary,
        "order_block_event_statistics": ob_statistics,
        "order_block_variant_summary": ob_summary,
        "liquidity_events": liquidity_events,
        "pmh_pml_events": pmh,
        "pmh_pml_summary": pmh_summary,
        "forward_outcomes": forward,
        "forward_stability_summary": forward_summary,
        "annual_summary": summaries["annual_summary"],
        "monthly_summary": summaries["monthly_summary"],
        "regime_summary": summaries["regime_summary"],
        "mapping_summary": summaries["mapping_summary"],
        "timing_guardrail_summary": timing,
        "data_quality_periods": data_quality,
        "excluded_evaluations": excluded,
        "event_schedule": schedule_frame,
    }
    runtime_seconds = perf_counter() - started
    if schedule_frame.empty:
        uncapped_event_rows = 0
        omitted_event_rows = 0
        truncated_mapping_dates = 0
    else:
        schedule_dates = schedule_frame.groupby(
            ["mapping_variant", "session_date"],
            dropna=False,
        ).first()
        uncapped_event_rows = int(
            schedule_dates["uncapped_date_trigger_count"].sum()
        )
        omitted_event_rows = int(
            schedule_dates["omitted_date_trigger_count"].sum()
        )
        truncated_mapping_dates = int(
            schedule_dates["date_schedule_truncated"].sum()
        )
    run_metadata = {
        "runtime_seconds": runtime_seconds,
        "fixed_schedule_rows": int(len(fixed_schedule)),
        "event_schedule_rows": int(len(schedule_frame)),
        "event_schedule_uncapped_rows": uncapped_event_rows,
        "event_schedule_omitted_rows": omitted_event_rows,
        "event_schedule_truncated_mapping_dates": (
            truncated_mapping_dates
        ),
        "event_evaluations_attempted": (
            accumulator.event_evaluations_attempted
        ),
        "event_evaluations_deduplicated": (
            accumulator.event_evaluations_attempted
            - int(snapshots["mode"].eq("event_driven").sum())
        ),
        "input_provenance": input_provenance,
        "command": list(command)
        or [
            sys.executable,
            "-m",
            "research.d005_e1_context_engine_empirical",
        ],
        "protected_d005_output": str(protected_d005_output),
        "protected_d005_fingerprint_before": protected_before,
    }
    if _directory_fingerprint(protected_d005_output) != protected_before:
        raise RuntimeError("existing D005 artifacts changed during E1 computation")
    result = persist_study_artifacts(
        frames=frames,
        output_dir=resolved_output,
        config=config,
        run_metadata=run_metadata,
        report_path=report_path,
    )
    protected_after = _directory_fingerprint(protected_d005_output)
    if protected_after != protected_before:
        raise RuntimeError("existing D005 artifacts changed during E1 persistence")
    result["protected_d005_fingerprint"] = protected_after
    return result
