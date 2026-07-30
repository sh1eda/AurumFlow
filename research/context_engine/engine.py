"""Parent-veto D005 evidence engine.

The engine is intentionally not connected to production strategy code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .bars import TIMEFRAME_MINUTES, closed_bars_asof, normalize_bars
from .config import ContextEngineConfig, local_bounds
from .features import (
    apply_zone_interactions,
    classify_balanced,
    confirmed_swings,
    detect_displacements,
    equal_liquidity_levels,
    detect_fvgs,
    detect_liquidity_sweeps,
    detect_mss,
    detect_order_blocks,
    latest_prior_atr,
    premarket_levels,
    qualify_fvgs,
    qualify_order_blocks,
    structure_direction,
    swing_liquidity_levels,
    trapped_between_opposing_arrays,
)
from .models import (
    ContextSnapshot,
    ContextState,
    Direction,
    EvidenceEvent,
    OutcomeLabel,
    StateTransition,
)


@dataclass(frozen=True)
class EvaluationResult:
    snapshot: ContextSnapshot
    fvg_events: tuple[EvidenceEvent, ...]
    order_block_events: tuple[EvidenceEvent, ...]
    liquidity_events: tuple[EvidenceEvent, ...]
    confirmation_events: tuple[EvidenceEvent, ...]
    conflict_events: tuple[EvidenceEvent, ...]

    def __post_init__(self) -> None:
        evaluation = pd.Timestamp(self.snapshot.evaluation_at)
        for event in self.all_events:
            timestamps = (
                event.available_at,
                event.interacted_at,
                event.confirmed_at,
                event.invalidated_at,
            )
            if any(
                value is not None
                and not pd.isna(value)
                and pd.Timestamp(value) > evaluation
                for value in timestamps
            ):
                raise ValueError(
                    f"event {event.event_id} contains future evidence"
                )

    @property
    def all_events(self) -> tuple[EvidenceEvent, ...]:
        return (
            self.fvg_events
            + self.order_block_events
            + self.liquidity_events
            + self.confirmation_events
            + self.conflict_events
        )


class ContextEngine:
    """Evaluate one causal D005 context snapshot."""

    def __init__(self, config: ContextEngineConfig | None = None) -> None:
        self.config = config or ContextEngineConfig()
        self.config.validate()

    def evaluate(
        self,
        timeframes: Mapping[str, pd.DataFrame],
        *,
        evaluation_at: pd.Timestamp,
        mapping_name: str | None = None,
        session_date: date | None = None,
    ) -> EvaluationResult:
        evaluation = pd.Timestamp(evaluation_at)
        if evaluation.tz is None:
            raise ValueError("evaluation_at must be timezone-aware")
        evaluation = evaluation.tz_convert("UTC")
        mapping = self.config.mapping(mapping_name)
        refinement_timeframe = (
            mapping.optional_refinement
            if self.config.optional_1m_refinement and mapping.optional_refinement
            else mapping.refinement
        )
        required = {
            mapping.parent,
            mapping.reaction,
            refinement_timeframe,
            "1min",
        }
        missing = sorted(required - set(timeframes))
        if missing:
            return self._terminal_result(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=ContextState.NEUTRAL,
                reasons=(f"missing_required_timeframes:{','.join(missing)}",),
                missing_required_data=True,
            )

        bars = {
            name: normalize_bars(timeframes[name], name)
            for name in required
        }
        parent = bars[mapping.parent]
        reaction = bars[mapping.reaction]
        refinement = bars[refinement_timeframe]
        one_minute = bars["1min"]
        minimum_parent = 2 * self.config.mss.pivot_width + 4
        if (
            len(closed_bars_asof(parent, evaluation)) < minimum_parent
            or len(closed_bars_asof(reaction, evaluation))
            < self.config.balance.lookback_bars
            or len(closed_bars_asof(refinement, evaluation)) < 3
        ):
            return self._terminal_result(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=ContextState.NEUTRAL,
                reasons=("missing_required_closed_bar_history",),
                missing_required_data=True,
            )

        parent_closed = closed_bars_asof(parent, evaluation)
        reaction_closed = closed_bars_asof(reaction, evaluation)
        parent_swings = confirmed_swings(
            parent_closed, width=self.config.mss.pivot_width
        )
        reaction_swings = confirmed_swings(
            reaction_closed, width=self.config.mss.pivot_width
        )
        parent_direction, parent_context = structure_direction(
            parent_swings, evaluation
        )
        child_direction, _ = structure_direction(reaction_swings, evaluation)
        balance = classify_balanced(
            parent, evaluation_at=evaluation, variant=self.config.balance
        )
        transitions: list[StateTransition] = []
        provisional_at = (
            pd.Timestamp(parent_context["available_at"])
            if parent_context
            else evaluation
        )
        transitions.append(
            StateTransition(
                ContextState.NEUTRAL,
                ContextState.PROVISIONAL_CONTEXT,
                provisional_at,
                "parent_order_flow"
                if parent_direction != Direction.NEUTRAL
                else "unresolved_balanced_context"
                if balance["balanced"]
                else "unresolved_context",
            )
        )

        if (
            parent_direction != Direction.NEUTRAL
            and child_direction != Direction.NEUTRAL
            and child_direction != parent_direction
        ):
            conflict = self._conflict_event(
                evaluation,
                mapping.parent,
                parent_direction,
                child_direction,
                "parent_child_direction_conflict",
            )
            transitions.append(
                StateTransition(
                    ContextState.PROVISIONAL_CONTEXT,
                    ContextState.CONFLICT,
                    evaluation,
                    "parent_veto",
                    (conflict.event_id,),
                )
            )
            snapshot = self._snapshot(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=ContextState.CONFLICT,
                direction=Direction.NEUTRAL,
                outcome=OutcomeLabel.NEUTRAL,
                parent_direction=parent_direction,
                child_direction=child_direction,
                reasons=("parent_child_direction_conflict",),
                evidence_ids=(conflict.event_id,),
                source_rule_ids=("B01", "C06"),
                variant_ids=("parent_veto",),
                transitions=transitions,
                balanced=bool(balance["balanced"]),
                risk_valid=False,
            )
            return EvaluationResult(snapshot, (), (), (), (), (conflict,))

        parent_displacements = detect_displacements(
            parent,
            timeframe=mapping.parent,
            variant=self.config.displacement,
            evaluation_at=evaluation,
        )
        parent_fvgs_raw = detect_fvgs(
            parent,
            timeframe=mapping.parent,
            evaluation_at=evaluation,
            minimum_width=self.config.fvg_minimum_width,
        )
        parent_obs = detect_order_blocks(
            parent,
            timeframe=mapping.parent,
            evaluation_at=evaluation,
            displacement_events=parent_displacements,
            fvg_events=parent_fvgs_raw,
            lookback_bars=self.config.ob_lookback_bars,
        )
        parent_fvgs = apply_zone_interactions(
            parent_fvgs_raw, reaction, evaluation_at=evaluation
        )
        parent_obs = apply_zone_interactions(
            parent_obs, reaction, evaluation_at=evaluation
        )

        candidate_pois = [
            event
            for event in (*parent_fvgs, *parent_obs)
            if event.interacted_at is not None
            and event.invalidated_at is None
            and pd.Timestamp(event.interacted_at) >= provisional_at
            and (
                parent_direction == Direction.NEUTRAL
                or event.direction == parent_direction
            )
        ]

        parent_atr = latest_prior_atr(
            parent,
            evaluation_at=evaluation,
            lookback=self.config.displacement.atr_lookback,
            min_periods=self.config.displacement.atr_min_periods,
        )
        parent_levels = swing_liquidity_levels(
            parent_swings,
            timeframe=mapping.parent,
            evaluation_at=evaluation,
        ) + equal_liquidity_levels(
            parent_swings,
            timeframe=mapping.parent,
            evaluation_at=evaluation,
            atr=parent_atr,
            tolerance_atr=self.config.equal_level_tolerance_atr,
        )
        liquidity_sweeps = detect_liquidity_sweeps(
            parent_levels,
            reaction,
            timeframe=mapping.reaction,
            evaluation_at=evaluation,
            penetration=self.config.liquidity_sweep_penetration,
            require_reclaim=self.config.require_liquidity_reclaim,
        )
        liquidity_sweeps = tuple(
            event
            for event in liquidity_sweeps
            if pd.Timestamp(event.available_at) >= provisional_at
            and (
                parent_direction == Direction.NEUTRAL
                or event.direction == parent_direction
            )
        )

        pmh_pml_levels: tuple[EvidenceEvent, ...] = ()
        pmh_pml_sweeps: tuple[EvidenceEvent, ...] = ()
        pmh_metadata: dict[str, object] = {}
        resolved_session_date = session_date or evaluation.tz_convert(
            self.config.timezone
        ).date()
        premarket_left, premarket_right = local_bounds(
            resolved_session_date,
            self.config.premarket.start,
            self.config.premarket.end,
            self.config.premarket.timezone,
        )
        if (
            parent_direction == Direction.NEUTRAL
            and not candidate_pois
            and not liquidity_sweeps
            and evaluation >= premarket_right
        ):
            balance_at_premarket = classify_balanced(
                parent,
                evaluation_at=premarket_right,
                variant=self.config.balance,
            )
            if balance_at_premarket["balanced"]:
                pmh_pml_levels, pmh_metadata = premarket_levels(
                    one_minute,
                    session_date=resolved_session_date,
                    config=self.config.premarket,
                )
                _, observation_end = local_bounds(
                    resolved_session_date, "08:30", "09:00", self.config.timezone
                )
                observation_cutoff = min(evaluation, observation_end)
                pmh_pml_sweeps = detect_liquidity_sweeps(
                    pmh_pml_levels,
                    one_minute,
                    timeframe="1min",
                    evaluation_at=observation_cutoff,
                    penetration=self.config.premarket.sweep_penetration,
                    require_reclaim=self.config.premarket.require_body_close_reclaim,
                )
                pmh_pml_sweeps = tuple(
                    event
                    for event in pmh_pml_sweeps
                    if premarket_right <= pd.Timestamp(event.available_at) <= observation_end
                )
                provisional_at = premarket_right
                transitions[0] = StateTransition(
                    ContextState.NEUTRAL,
                    ContextState.PROVISIONAL_CONTEXT,
                    provisional_at,
                    "unresolved_balanced_context",
                )

        candidate: EvidenceEvent | None = None
        candidate_state: ContextState | None = None
        if candidate_pois:
            candidate = max(
                candidate_pois,
                key=lambda event: pd.Timestamp(event.interacted_at),
            )
            candidate_state = ContextState.CANDIDATE_POI
        elif liquidity_sweeps:
            candidate = max(
                liquidity_sweeps, key=lambda event: pd.Timestamp(event.available_at)
            )
            candidate_state = ContextState.CANDIDATE_LIQUIDITY_EVENT
        elif pmh_pml_sweeps:
            candidate = max(
                pmh_pml_sweeps, key=lambda event: pd.Timestamp(event.available_at)
            )
            candidate_state = ContextState.CANDIDATE_LIQUIDITY_EVENT

        all_liquidity = tuple(parent_levels) + tuple(liquidity_sweeps) + tuple(
            pmh_pml_levels
        ) + tuple(pmh_pml_sweeps)

        if candidate is None or candidate_state is None:
            state = (
                ContextState.PROVISIONAL_CONTEXT
                if parent_direction != Direction.NEUTRAL
                else ContextState.NEUTRAL
            )
            if state == ContextState.NEUTRAL:
                transitions.append(
                    StateTransition(
                        ContextState.PROVISIONAL_CONTEXT,
                        ContextState.NEUTRAL,
                        evaluation,
                        "no_qualified_context_event",
                    )
                )
            snapshot = self._snapshot(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=state,
                direction=Direction.NEUTRAL,
                outcome=OutcomeLabel.NEUTRAL,
                parent_direction=parent_direction,
                child_direction=child_direction,
                reasons=("reaction_confirmation_absent", "no_qualified_context_event"),
                evidence_ids=(),
                source_rule_ids=("A31",),
                variant_ids=(self.config.mss.name, self.config.displacement.name),
                transitions=transitions,
                balanced=bool(balance["balanced"]),
                risk_valid=False,
            )
            return EvaluationResult(
                snapshot,
                tuple(parent_fvgs),
                tuple(parent_obs),
                all_liquidity,
                tuple(parent_displacements),
                (),
            )

        candidate_at = pd.Timestamp(
            candidate.interacted_at
            if candidate.interacted_at is not None
            else candidate.available_at
        )
        transitions.append(
            StateTransition(
                ContextState.PROVISIONAL_CONTEXT,
                candidate_state,
                candidate_at,
                candidate.event_type,
                (candidate.event_id,),
            )
        )
        if (
            parent_direction != Direction.NEUTRAL
            and candidate.direction != parent_direction
        ):
            conflict = self._conflict_event(
                evaluation,
                mapping.parent,
                parent_direction,
                candidate.direction,
                "candidate_opposes_parent",
            )
            transitions.append(
                StateTransition(
                    candidate_state,
                    ContextState.CONFLICT,
                    evaluation,
                    "parent_veto",
                    (candidate.event_id, conflict.event_id),
                )
            )
            snapshot = self._snapshot(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=ContextState.CONFLICT,
                direction=Direction.NEUTRAL,
                outcome=OutcomeLabel.NEUTRAL,
                parent_direction=parent_direction,
                child_direction=child_direction,
                reasons=("candidate_opposes_parent",),
                evidence_ids=(candidate.event_id, conflict.event_id),
                source_rule_ids=("B01", "C06"),
                variant_ids=("parent_veto", candidate.variant),
                transitions=transitions,
                balanced=bool(balance["balanced"]),
                risk_valid=False,
            )
            return EvaluationResult(
                snapshot,
                tuple(parent_fvgs),
                tuple(parent_obs),
                all_liquidity,
                tuple(parent_displacements),
                (conflict,),
            )

        reaction_mss = detect_mss(
            reaction,
            timeframe=mapping.reaction,
            variant=self.config.mss,
            evaluation_at=evaluation,
            start_at=candidate_at,
        )
        reaction_displacements = detect_displacements(
            reaction,
            timeframe=mapping.reaction,
            variant=self.config.displacement,
            evaluation_at=evaluation,
        )
        timeout = pd.Timedelta(
            minutes=TIMEFRAME_MINUTES[mapping.reaction]
            * self.config.mss.confirmation_timeout_bars
        )
        aligned_mss = [
            event
            for event in reaction_mss
            if event.direction == candidate.direction
            and candidate_at <= pd.Timestamp(event.available_at) <= candidate_at + timeout
        ]
        selected_mss = (
            min(aligned_mss, key=lambda event: pd.Timestamp(event.available_at))
            if aligned_mss
            else None
        )
        aligned_displacements = [
            event
            for event in reaction_displacements
            if event.direction == candidate.direction
            and pd.Timestamp(event.created_at) >= candidate_at
            and (
                selected_mss is None
                or pd.Timestamp(event.created_at) >= pd.Timestamp(selected_mss.created_at)
            )
        ]
        selected_displacement = (
            min(
                aligned_displacements,
                key=lambda event: pd.Timestamp(event.available_at),
            )
            if aligned_displacements
            else None
        )

        refinement_displacements = detect_displacements(
            refinement,
            timeframe=refinement_timeframe,
            variant=self.config.displacement,
            evaluation_at=evaluation,
        )
        refinement_fvgs_raw = detect_fvgs(
            refinement,
            timeframe=refinement_timeframe,
            evaluation_at=evaluation,
            minimum_width=self.config.fvg_minimum_width,
        )
        refinement_mss = detect_mss(
            refinement,
            timeframe=refinement_timeframe,
            variant=self.config.mss,
            evaluation_at=evaluation,
            start_at=candidate_at,
        )
        refinement_fvgs = qualify_fvgs(
            refinement_fvgs_raw,
            liquidity_events=all_liquidity,
            mss_events=tuple(reaction_mss) + tuple(refinement_mss),
            displacement_events=tuple(reaction_displacements)
            + tuple(refinement_displacements),
            parent_direction=parent_direction,
            context_events=(candidate,),
        )
        refinement_obs_raw = detect_order_blocks(
            refinement,
            timeframe=refinement_timeframe,
            evaluation_at=evaluation,
            displacement_events=refinement_displacements,
            fvg_events=refinement_fvgs_raw,
            lookback_bars=self.config.ob_lookback_bars,
        )
        confirmation_start = (
            max(
                pd.Timestamp(selected_mss.available_at),
                pd.Timestamp(selected_displacement.available_at),
            )
            if selected_mss is not None and selected_displacement is not None
            else candidate_at
        )
        refinement_obs = qualify_order_blocks(
            refinement_obs_raw,
            liquidity_events=all_liquidity,
            mss_events=tuple(reaction_mss) + tuple(refinement_mss),
            displacement_events=tuple(reaction_displacements)
            + tuple(refinement_displacements),
            parent_direction=parent_direction,
            context_events=(candidate,),
        )
        entry_zones = [
            event
            for event in (*refinement_fvgs, *refinement_obs)
            if event.direction == candidate.direction
            and pd.Timestamp(event.available_at) >= confirmation_start
            and event.invalidated_at is None
            and bool(event.parameters.get("context_qualified", False))
        ]
        entry_zone = (
            min(entry_zones, key=lambda event: pd.Timestamp(event.available_at))
            if entry_zones
            else None
        )

        reaction_atr = latest_prior_atr(
            reaction,
            evaluation_at=evaluation,
            lookback=self.config.displacement.atr_lookback,
            min_periods=self.config.displacement.atr_min_periods,
        )
        current_price = float(reaction_closed["close"].iloc[-1])
        parent_arrays = tuple(parent_fvgs) + tuple(parent_obs)
        trapped = trapped_between_opposing_arrays(
            price=current_price,
            atr=parent_atr,
            events=parent_arrays,
            maximum_distance_atr=self.config.trapped_array_max_distance_atr,
        )
        reference_price = (
            float(candidate.level)
            if candidate.level is not None
            else (
                float(candidate.zone_low) + float(candidate.zone_high)
            )
            / 2.0
            if candidate.zone_low is not None and candidate.zone_high is not None
            else current_price
        )
        overextended = bool(
            np.isfinite(reaction_atr)
            and reaction_atr > 0
            and abs(current_price - reference_price) / reaction_atr
            > self.config.maximum_overextension_atr
        )
        zone_width = (
            float(entry_zone.zone_high) - float(entry_zone.zone_low)
            if entry_zone is not None
            and entry_zone.zone_low is not None
            and entry_zone.zone_high is not None
            else math.nan
        )
        risk_valid = bool(
            np.isfinite(zone_width)
            and zone_width > self.config.minimum_zone_width
            and np.isfinite(reaction_atr)
            and reaction_atr > 0
            and zone_width / reaction_atr <= self.config.maximum_zone_risk_atr
        )
        unresolved_range = bool(
            balance.get("range_like", False)
            and not balance.get("boundaries_resolved", False)
        )
        gates = {
            "body_close_mss_absent": selected_mss is None,
            "measurable_displacement_absent": selected_displacement is None,
            "lower_timeframe_refinement_absent": entry_zone is None,
            "trapped_between_opposing_arrays": trapped,
            "range_boundaries_unresolved": unresolved_range,
            "move_overextended": overextended,
            "proposed_risk_invalid": not risk_valid,
        }
        failed = tuple(name for name, value in gates.items() if value)

        confirmation_events = (
            tuple(parent_displacements)
            + tuple(reaction_mss)
            + tuple(reaction_displacements)
            + tuple(refinement_mss)
            + tuple(refinement_displacements)
        )
        all_fvgs = tuple(parent_fvgs) + tuple(refinement_fvgs)
        all_obs = tuple(parent_obs) + tuple(refinement_obs)
        evidence = [candidate.event_id]
        if selected_mss:
            evidence.append(selected_mss.event_id)
        if selected_displacement:
            evidence.append(selected_displacement.event_id)
        if entry_zone:
            evidence.append(entry_zone.event_id)

        timed_out = evaluation > candidate_at + timeout and selected_mss is None
        invalidating_failure = bool(
            timed_out or trapped or unresolved_range or overextended or not risk_valid
        )
        if failed:
            final_state = (
                ContextState.INVALIDATED if invalidating_failure else candidate_state
            )
            if final_state == ContextState.INVALIDATED:
                transitions.append(
                    StateTransition(
                        candidate_state,
                        ContextState.INVALIDATED,
                        evaluation,
                        "confirmation_or_risk_gate_failed",
                        tuple(evidence),
                    )
                )
            snapshot = self._snapshot(
                evaluation=evaluation,
                mapping=mapping,
                refinement_timeframe=refinement_timeframe,
                state=final_state,
                direction=Direction.NEUTRAL,
                outcome=OutcomeLabel.NEUTRAL,
                parent_direction=parent_direction,
                child_direction=child_direction,
                reasons=failed,
                evidence_ids=tuple(evidence),
                source_rule_ids=("B04", "A31", "C01", "C02"),
                variant_ids=(
                    self.config.mss.name,
                    self.config.displacement.name,
                    candidate.variant,
                    *(() if entry_zone is None else (entry_zone.variant,)),
                ),
                transitions=transitions,
                balanced=bool(balance["balanced"]),
                trapped=trapped,
                overextended=overextended,
                risk_valid=risk_valid,
            )
            return EvaluationResult(
                snapshot,
                all_fvgs,
                all_obs,
                all_liquidity,
                confirmation_events,
                (),
            )

        transitions.append(
            StateTransition(
                candidate_state,
                ContextState.REACTION_CONFIRMED,
                max(
                    pd.Timestamp(selected_mss.available_at),
                    pd.Timestamp(selected_displacement.available_at),
                    pd.Timestamp(entry_zone.available_at),
                ),
                "conservative_reaction_sequence_complete",
                tuple(evidence),
            )
        )
        pre_candidate_direction, _ = structure_direction(
            reaction_swings, candidate_at
        )
        outcome = (
            OutcomeLabel.REVERSAL
            if pre_candidate_direction not in (Direction.NEUTRAL, candidate.direction)
            or (
                parent_direction == Direction.NEUTRAL
                and candidate.event_type == "liquidity_sweep"
            )
            else OutcomeLabel.CONTINUATION
        )
        snapshot = self._snapshot(
            evaluation=evaluation,
            mapping=mapping,
            refinement_timeframe=refinement_timeframe,
            state=ContextState.REACTION_CONFIRMED,
            direction=candidate.direction,
            outcome=outcome,
            parent_direction=parent_direction,
            child_direction=child_direction,
            reasons=("research_only_no_entry_authorization",),
            evidence_ids=tuple(evidence),
            source_rule_ids=("B04", "B08", "A11", "A13", "A14"),
            variant_ids=(
                self.config.mss.name,
                self.config.displacement.name,
                candidate.variant,
                entry_zone.variant,
            ),
            transitions=transitions,
            balanced=bool(balance["balanced"]),
            trapped=trapped,
            overextended=overextended,
            risk_valid=risk_valid,
        )
        return EvaluationResult(
            snapshot,
            all_fvgs,
            all_obs,
            all_liquidity,
            confirmation_events,
            (),
        )

    def _snapshot(
        self,
        *,
        evaluation: pd.Timestamp,
        mapping,
        refinement_timeframe: str,
        state: ContextState,
        direction: Direction,
        outcome: OutcomeLabel,
        parent_direction: Direction,
        child_direction: Direction,
        reasons: tuple[str, ...],
        evidence_ids: tuple[str, ...],
        source_rule_ids: tuple[str, ...],
        variant_ids: tuple[str, ...],
        transitions: Sequence[StateTransition],
        balanced: bool,
        risk_valid: bool,
        trapped: bool = False,
        missing: bool = False,
        overextended: bool = False,
    ) -> ContextSnapshot:
        return ContextSnapshot(
            evaluation_at=evaluation,
            mapping_name=mapping.name,
            parent_timeframe=mapping.parent,
            reaction_timeframe=mapping.reaction,
            refinement_timeframe=refinement_timeframe,
            state=state,
            direction=direction,
            outcome=outcome,
            parent_direction=parent_direction,
            child_direction=child_direction,
            entry_authorized=False,
            no_trade_reasons=reasons,
            evidence_ids=evidence_ids,
            source_rule_ids=source_rule_ids,
            variant_ids=variant_ids,
            config_fingerprint=self.config.fingerprint(),
            transitions=tuple(transitions),
            balanced_ranging=balanced,
            trapped_between_arrays=trapped,
            missing_required_data=missing,
            overextended=overextended,
            risk_valid=risk_valid,
        )

    def _terminal_result(
        self,
        *,
        evaluation: pd.Timestamp,
        mapping,
        refinement_timeframe: str,
        state: ContextState,
        reasons: tuple[str, ...],
        missing_required_data: bool,
    ) -> EvaluationResult:
        snapshot = self._snapshot(
            evaluation=evaluation,
            mapping=mapping,
            refinement_timeframe=refinement_timeframe,
            state=state,
            direction=Direction.NEUTRAL,
            outcome=OutcomeLabel.NEUTRAL,
            parent_direction=Direction.NEUTRAL,
            child_direction=Direction.NEUTRAL,
            reasons=reasons,
            evidence_ids=(),
            source_rule_ids=("A31",),
            variant_ids=(),
            transitions=(),
            balanced=False,
            risk_valid=False,
            missing=missing_required_data,
        )
        return EvaluationResult(snapshot, (), (), (), (), ())

    @staticmethod
    def _conflict_event(
        evaluation: pd.Timestamp,
        timeframe: str,
        parent_direction: Direction,
        child_direction: Direction,
        reason: str,
    ) -> EvidenceEvent:
        return EvidenceEvent(
            event_id=f"conflict-{evaluation.value}-{reason}",
            event_type="context_conflict",
            direction=Direction.NEUTRAL,
            timeframe=timeframe,
            variant="parent_veto",
            taxonomy="context_conflict",
            created_at=evaluation,
            available_at=evaluation,
            confirmed_at=evaluation,
            source_rule_ids=("B01", "C06"),
            parameters={
                "parent_direction": int(parent_direction),
                "child_direction": int(child_direction),
                "reason": reason,
                "weighted_scoring_used": False,
            },
        )
