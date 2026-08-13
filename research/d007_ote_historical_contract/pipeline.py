"""Composition boundary for the frozen D007 empirical historical study.

The public historical runner supplies authenticated real inputs.  Tests supply
only synthetic in-memory inputs and temporary output roots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math
from typing import Mapping

import pandas as pd

from research.d007_association_identity import (
    ASSOCIATION_ARTIFACT_PATHS,
    ASSOCIATION_PROJECTIONS,
    AUTHORITY_ID as ASSOCIATION_AUTHORITY_ID,
    D004EventIdentity,
    D006BlockIdentity,
    E4SequenceIdentity,
    associate_d004_to_e4,
    associate_d006_to_e4,
    select_d006_block as select_association_d006_block,
)
from research.d007_methodology_clarification import UPSTREAM_ARTIFACTS
from research.d007_methodology_clarification import (
    GEOMETRY_HYPOTHESES,
    INTERACTION_HYPOTHESES,
    REDUNDANCY_FEATURES,
    ablation_status,
    named_trading_date,
)
from research.d007_ote_research.detector import deduplicate_primary_overlaps
from research.d007_ote_research.lifecycle import evaluate_lifecycle, primary_lifecycle_eligible

from .artifacts import ArtifactPackage, empty_table_frame, publish_package, publish_synthetic_package
from .empirical import (
    build_5m_bars,
    associate_upstream_ids,
    equilibrium_candidates,
    exact_60m_outcome,
    make_candidate,
    match_family,
    Membership,
    reconstruct_ote_ranges,
    select_d004_reentry,
    select_d006_membership,
    select_e1_context,
    select_e3_liquidity_sweep,
    select_e3_refinement,
    select_redundancy_evidence,
)
from .reporting import render_historical_report
from .schemas import TABLE_SCHEMAS
from .loaders import ASSOCIATION_PROJECTIONS_BY_PATH, MarketParquetRecord, load_market_bars, load_structural_artifact
from .config import (
    ASSOCIATION_MODULE_PATH,
    ASSOCIATION_MODULE_SHA256,
    ASSOCIATION_SPEC_PATH,
    ASSOCIATION_SPEC_SHA256,
    CLARIFICATION_MODULE_PATH,
    CLARIFICATION_MODULE_SHA256,
    CLARIFICATION_SPEC_PATH,
    CLARIFICATION_SPEC_SHA256,
    CONTRACT_SPEC_PATH,
    CONTRACT_SPEC_SHA256,
    DEFAULT_CONTRACT,
    D005_E4_ROOT,
    FROZEN_CONTRACT_IMPLEMENTATION_SHA256,
    SOURCE_ROOT,
    contract_fingerprint,
)
from .statistics import (
    benjamini_hochberg,
    date_cluster_bootstrap,
    exact_mcnemar,
    mean_test,
    noninferiority_stability,
    paired_student_t,
    direction_stability,
    positive_effect_passes,
    temporal_stability,
    zero_margin_noninferiority_guard,
)


@dataclass(frozen=True)
class PipelineResult:
    package: ArtifactPackage
    result: Mapping[str, object]


def geometry_candidate_passes(
    *,
    adjusted: Mapping[str, Mapping[str, object]],
    bootstrap: Mapping[str, Mapping[str, object]],
    stability: Mapping[str, Mapping[str, object]],
) -> bool:
    """Apply all frozen pooled, yearly, and direction geometry guards."""

    incidence = adjusted["geometry_touch_incidence"]
    movement = adjusted["geometry_directional_movement"]
    movement_split = stability["geometry_directional_movement"]
    movement_stable = noninferiority_stability(
        movement_split["yearly"],
        movement_split["directions"],
    )
    adequate = all(
        int(adjusted[name].get("n", 0)) >= 200 for name in GEOMETRY_HYPOTHESES
    )
    access_stable = all(
        stability[name]["temporal"]["passed"]
        and stability[name]["direction"]["passed"]
        for name in ("geometry_touch_incidence", "geometry_time_to_touch")
    )
    return bool(
        adequate
        and incidence.get("risk_difference") is not None
        and incidence["risk_difference"] > 0
        and bootstrap["geometry_touch_incidence"].get("ci_lower") is not None
        and bootstrap["geometry_touch_incidence"]["ci_lower"] > 0
        and incidence.get("q_value") is not None
        and incidence["q_value"] <= 0.05
        and positive_effect_passes(
            adjusted["geometry_time_to_touch"],
            bootstrap["geometry_time_to_touch"],
            adjusted["geometry_time_to_touch"].get("q_value"),
        )
        and zero_margin_noninferiority_guard(movement, movement.get("q_value"))
        and access_stable
        and movement_stable["passed"]
    )


def _interaction_ablation_status(
    name: str,
    row: Mapping[str, object],
    stability: Mapping[str, object],
) -> str:
    if name == "against_d005_context_negative_control":
        return "NOT_APPLICABLE_NEGATIVE_CONTROL"
    minimum = 100 if name in {"after_d004_manipulation", "d006_rejection_block"} else 200
    bootstrap = row.get("bootstrap", {})
    if (
        int(row.get("n", 0)) >= minimum
        and row.get("mean") is not None
        and row["mean"] > 0
        and row.get("ci_lower") is not None
        and row["ci_lower"] > 0
        and isinstance(bootstrap, Mapping)
        and bootstrap.get("ci_lower") is not None
        and bootstrap["ci_lower"] > 0
        and row.get("q_value") is not None
        and row["q_value"] <= 0.05
        and stability["temporal"]["passed"]
        and stability["direction"]["passed"]
    ):
        return "NON_REDUNDANT"
    if (
        int(row.get("n", 0)) >= minimum
        and row.get("ci_upper") is not None
        and row["ci_upper"] <= 0
    ):
        return "FULLY_ACCOUNTED"
    return "INCONCLUSIVE"


def _range_row(item: object, *, session: str, volatility: str) -> dict[str, object]:
    named = named_trading_date(item.range_available_at)
    return {
        **asdict(item),
        "direction": int(item.direction),
        "named_trading_date": named,
        "validation_year": named.year,
        "session": session,
        "causal_volatility_bucket": volatility,
    }


def _session(stamp: pd.Timestamp) -> str:
    local = stamp.tz_convert("America/New_York")
    minute = local.hour * 60 + local.minute
    return (
        "asia" if minute >= 1080 else
        "premarket" if minute < 510 else
        "ny_observation" if minute < 720 else
        "ny_afternoon" if minute < 1020 else
        "maintenance"
    )


def _optional_timestamp(value: object) -> object | None:
    return None if value is None or pd.isna(value) else value


def _volatility_buckets(bars: tuple[object, ...]) -> dict[str, str]:
    """Use the latest complete prior named day and its prior 20-day median."""

    rows = pd.DataFrame({
        "date": [named_trading_date(bar.available_at) for bar in bars],
        "session": [_session(bar.available_at) for bar in bars],
        "high": [bar.high for bar in bars],
        "low": [bar.low for bar in bars],
    })
    rows = rows.loc[rows["session"].ne("maintenance")]
    daily = rows.groupby("date", sort=True).agg(high=("high", "max"), low=("low", "min"), bars=("high", "size"))
    daily["range"] = daily["high"] - daily["low"]
    complete = daily["range"].where(daily["bars"].ge(math.ceil(276 * 0.95)))
    daily["ratio"] = complete.shift(1) / complete.shift(2).rolling(20, min_periods=20).median()
    result: dict[str, str] = {}
    for day, ratio in daily["ratio"].items():
        result[str(day)] = (
            "unavailable" if pd.isna(ratio) else
            "low" if float(ratio) < 0.75 else
            "high" if float(ratio) > 1.25 else
            "normal"
        )
    return result


def _rows(upstream: Mapping[str, pd.DataFrame], suffix: str) -> tuple[Mapping[str, object], ...]:
    """Return one registered projected role without discovering any input."""

    frames = [frame for path, frame in upstream.items() if path.endswith(suffix)]
    if len(frames) > 1:
        raise ValueError(f"ambiguous registered upstream role: {suffix}")
    return tuple(frames[0].to_dict("records")) if frames else ()


def _enrich_sequence_identities(
    sequences: tuple[Mapping[str, object], ...],
    anchors: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    """Join authenticated E4 projections by exact sequence ID, never time."""

    anchor_by_sequence: dict[str, Mapping[str, object]] = {}
    for row in anchors:
        identifier = str(row.get("sequence_id", ""))
        if not identifier or identifier in anchor_by_sequence:
            raise ValueError("E4 displacement-anchor sequence identity is missing or duplicate")
        anchor_by_sequence[identifier] = row
    output: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for sequence in sequences:
        identifier = str(sequence.get("sequence_id", ""))
        if not identifier or identifier in seen:
            raise ValueError("E4 eligible-sequence identity is missing or duplicate")
        seen.add(identifier)
        anchor = anchor_by_sequence.get(identifier)
        if anchor is None:
            raise ValueError("E4 eligible sequence lacks its exact displacement anchor")
        merged = dict(sequence)
        for name in (
            "anchor_event_id",
            "anchor_at",
            "anchor_session",
            "anchor_year",
        ):
            merged[name] = anchor.get(name)
        try:
            identity = E4SequenceIdentity(
                sequence_id=identifier,
                displacement_confirmation_event_id=str(
                    sequence.get("displacement_confirmation_event_id", "")
                ),
                anchor_event_id=str(anchor.get("anchor_event_id", "")),
                anchor_at=anchor.get("anchor_at"),
                direction=sequence.get("direction"),
                anchor_session=str(anchor.get("anchor_session", "")),
                anchor_year=int(anchor.get("anchor_year")),
                mapping_variant=str(sequence.get("mapping_variant", "")),
                main_scope_eligible=sequence.get("main_scope_eligible"),
                anchor_causally_observable=sequence.get("anchor_causally_observable"),
                anchor_selected_using_later_completion=sequence.get(
                    "anchor_selected_using_later_completion"
                ),
                anchor_sequence_id=str(anchor.get("sequence_id", "")),
                anchor_mapping_variant=str(anchor.get("mapping_variant", "")),
                anchor_direction=anchor.get("direction"),
                anchor_main_scope_eligible=anchor.get("main_scope_eligible"),
                anchor_causal_flag=anchor.get("anchor_causally_observable"),
                anchor_later_completion_flag=anchor.get(
                    "anchor_selected_using_later_completion"
                ),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "ambiguous_or_invalid_e4_identity: exact sequence/anchor join failed"
            ) from error
        merged["association_identity"] = identity
        output.append(merged)
    if set(anchor_by_sequence) - seen:
        raise ValueError("E4 displacement anchor has no exact eligible sequence")
    return tuple(output)


def _e4_identities(
    sequences: tuple[Mapping[str, object], ...],
) -> tuple[E4SequenceIdentity, ...]:
    identities = tuple(row.get("association_identity") for row in sequences)
    if not identities or any(not isinstance(item, E4SequenceIdentity) for item in identities):
        raise ValueError("authenticated E4 association identities are required")
    return identities  # type: ignore[return-value]


def _d004_constituents(
    rows: tuple[Mapping[str, object], ...],
) -> tuple[tuple[D004EventIdentity, Mapping[str, object]], ...]:
    output: list[tuple[D004EventIdentity, Mapping[str, object]]] = []
    for row in rows:
        named = pd.Timestamp(row.get("trading_date")).date()
        for side, direction in (("high", -1), ("low", 1)):
            sweep_at = row.get(f"{side}_sweep_time")
            reentry_at = row.get(f"{side}_reentry_time")
            if (
                not bool(row.get(f"{side}_sweep"))
                or not bool(row.get(f"{side}_reentry"))
                or sweep_at is None
                or reentry_at is None
                or pd.isna(sweep_at)
                or pd.isna(reentry_at)
            ):
                continue
            event = D004EventIdentity(
                event_id=f"d004:{named.isoformat()}:{side}",
                trading_date=named,
                side=side,
                reference_name=str(row.get("primary_reference_name", "")),
                sweep_at=sweep_at,
                reentry_at=reentry_at,
                available_at=pd.Timestamp(reentry_at) + pd.Timedelta(minutes=1),
                direction=direction,
            )
            output.append((event, row))
    return tuple(output)


def _d006_blocks(
    rows: tuple[Mapping[str, object], ...],
) -> tuple[
    tuple[tuple[D006BlockIdentity, Mapping[str, object]], ...],
    tuple[dict[str, object], ...],
]:
    output: list[tuple[D006BlockIdentity, Mapping[str, object]]] = []
    exclusions: list[dict[str, object]] = []
    for row in rows:
        block_id = str(row.get("block_id", ""))
        available_at = _optional_timestamp(row.get("causal_availability"))
        first_touch = _optional_timestamp(row.get("first_touch_timestamp"))
        direction = {"bullish": 1, "bearish": -1, "1": 1, "-1": -1}.get(
            str(row.get("direction", "")).lower()
        )
        if direction is None:
            exclusions.append({
                "object_id": block_id,
                "stage": "d006_association",
                "first_failure": "ambiguous_or_invalid_d006_identity",
                "available_at": available_at,
                "constituent_event_at": first_touch,
            })
            continue
        if first_touch is None:
            exclusions.append({
                "object_id": block_id,
                "stage": "d006_association",
                "first_failure": "lifecycle_ineligible_block",
                "available_at": available_at,
                "constituent_event_at": None,
            })
            continue
        sources = row.get("source_bar_ids")
        source_ids = tuple(str(item) for item in sources) if isinstance(sources, (list, tuple)) else ()
        try:
            identity = D006BlockIdentity(
                block_id=block_id,
                definition_name=str(row.get("definition_name", "")),
                direction=direction,
                source_bar_ids=source_ids,
                expansion_bar_id=str(row.get("expansion_bar_id", "")),
                confirmation_at=row.get("confirmation_timestamp"),
                causal_availability=row.get("causal_availability"),
                first_touch_at=first_touch,
                expiry_deadline=row.get("expiry_deadline"),
                range_size=float(row.get("range")),
                lifecycle_state=str(row.get("lifecycle_state", "")),
                mitigation_at=_optional_timestamp(row.get("mitigation_timestamp")),
                invalidation_at=_optional_timestamp(row.get("invalidation_timestamp")),
                expiry_at=_optional_timestamp(row.get("expiry_timestamp")),
                preavailability_interaction=bool(
                    row.get("preavailability_interaction", False)
                ),
            )
        except (TypeError, ValueError):
            exclusions.append({
                "object_id": block_id,
                "stage": "d006_association",
                "first_failure": "ambiguous_or_invalid_d006_identity",
                "available_at": available_at,
                "constituent_event_at": first_touch,
            })
            continue
        output.append((identity, row))
    return tuple(output), tuple(exclusions)


def _association_provenance(
    decision: object,
    constituent: object,
    source_row: Mapping[str, object],
    sequence: E4SequenceIdentity | None,
) -> dict[str, object]:
    identities = {item.path: item for item in UPSTREAM_ARTIFACTS}
    family = str(getattr(decision, "family"))
    constituent_key = "d004_daily_events" if family == "d004" else "d006_structural_blocks"
    constituent_path = ASSOCIATION_ARTIFACT_PATHS[constituent_key]
    payload: dict[str, object] = {
        "authority_id": ASSOCIATION_AUTHORITY_ID,
        "precedence_version": "new_outcome_blind_temporal_association_v1",
        "family": family,
        "constituent_id": getattr(decision, "constituent_id"),
        "association_id": getattr(decision, "association_id"),
        "exclusion_reason": getattr(decision, "exclusion_reason"),
        "constituent_event_at": getattr(decision, "constituent_event_at").isoformat(),
        "constituent_artifact": {
            "path": constituent_path,
            "sha256": identities[constituent_path].sha256,
        },
        "source_milestone_identities": [
            {
                "milestone": item.milestone,
                "artifact_path": item.path,
                "version_config_identity": item.version,
                "version_authority_path": item.version_authority_path,
                "version_authority_sha256": item.version_authority_sha256,
            }
            for item in UPSTREAM_ARTIFACTS
            if item.milestone
            in ({"D004", "D005-E4"} if family == "d004" else {"D005-E4", "D006"})
        ],
    }
    if sequence is not None:
        payload.update(
            {
                "e4_sequence_id": sequence.sequence_id,
                "e4_anchor_event_id": sequence.anchor_event_id,
                "e4_displacement_confirmation_event_id": sequence.displacement_confirmation_event_id,
                "e4_anchor_at": sequence.anchor_at.isoformat(),
                "e4_artifacts": [
                    {
                        "path": ASSOCIATION_ARTIFACT_PATHS[key],
                        "sha256": identities[ASSOCIATION_ARTIFACT_PATHS[key]].sha256,
                    }
                    for key in (
                        "d005_e4_eligible_sequences",
                        "d005_e4_displacement_anchors",
                    )
                ],
                "direction": getattr(decision, "direction"),
                "e4_session": getattr(decision, "session"),
                "e4_anchor_year": getattr(decision, "e4_anchor_year"),
                "e4_validation_year": getattr(decision, "e4_validation_year"),
                "e4_named_date": getattr(decision, "e4_named_date").isoformat(),
                "constituent_named_date": getattr(decision, "named_date").isoformat(),
                "mapping": sequence.mapping_variant,
                "association_reference_at": getattr(
                    decision, "association_reference_at"
                ).isoformat(),
                "association_distance_minutes": getattr(
                    decision, "association_distance_minutes"
                ),
                "e4_availability_to_constituent_event_minutes": getattr(
                    decision, "elapsed_minutes"
                ),
            }
        )
    if family == "d004":
        payload["constituent_fields"] = {
            "side": getattr(constituent, "side"),
            "reference_name": getattr(constituent, "reference_name"),
            "sweep_at": getattr(constituent, "sweep_at").isoformat(),
            "reentry_at": getattr(constituent, "reentry_at").isoformat(),
            "named_date": getattr(constituent, "trading_date").isoformat(),
        }
    else:
        payload["constituent_fields"] = {
            "block_id": getattr(constituent, "block_id"),
            "source_bar_ids": list(getattr(constituent, "source_bar_ids")),
            "expansion_bar_id": getattr(constituent, "expansion_bar_id"),
            "confirmation_at": getattr(constituent, "confirmation_at").isoformat(),
            "causal_availability": getattr(
                constituent, "causal_availability"
            ).isoformat(),
            "first_touch_at": getattr(constituent, "first_touch_at").isoformat(),
            "mitigation_at": getattr(constituent, "mitigation_at").isoformat()
            if getattr(constituent, "mitigation_at") is not None
            else None,
            "invalidation_at": getattr(constituent, "invalidation_at").isoformat()
            if getattr(constituent, "invalidation_at") is not None
            else None,
            "expiry_at": getattr(constituent, "expiry_at").isoformat()
            if getattr(constituent, "expiry_at") is not None
            else None,
            "expiry_deadline": getattr(constituent, "expiry_deadline").isoformat(),
            "range": getattr(constituent, "range_size"),
            "definition": getattr(constituent, "definition_name"),
        }
    return payload


def _deterministic_provenance(
    *,
    source_files: tuple[Mapping[str, object], ...] = (),
    association_rows: tuple[Mapping[str, object], ...] = (),
    synthetic: bool = False,
) -> dict[str, object]:
    upstream = [
        {
            "milestone": item.milestone,
            "path": item.path,
            "sha256": item.sha256,
            "manifest_path": item.manifest_path,
            "manifest_sha256": item.manifest_sha256,
            "version_authority_path": item.version_authority_path,
            "version_authority_sha256": item.version_authority_sha256,
            "version": item.version,
            "schema_identity": item.schema_identity,
            "role": item.role,
            "projected_columns": list(
                ASSOCIATION_PROJECTIONS.get(
                    next(
                        (
                            key
                            for key, path in ASSOCIATION_ARTIFACT_PATHS.items()
                            if path == item.path
                        ),
                        "",
                    ),
                    item.required_columns,
                )
            ),
        }
        for item in UPSTREAM_ARTIFACTS
    ]
    return {
        "source_lineage": "synthetic_fixture"
        if synthetic
        else "d003-v1>D004-bars-1m>D005-E4-v1",
        "source_status": "SYNTHETIC_VERIFIED" if synthetic else "AUTHENTICATED",
        "upstream_status": "SYNTHETIC_VERIFIED" if synthetic else "AUTHENTICATED",
        "source_files": [dict(item) for item in source_files],
        "upstream_artifacts": upstream,
        "contract_identities": {
            "preregistration_sha256": DEFAULT_CONTRACT.snapshot()["d007_spec_sha256"],
            "historical_contract_path": CONTRACT_SPEC_PATH.as_posix(),
            "historical_contract_sha256": CONTRACT_SPEC_SHA256,
            "methodology_spec_path": CLARIFICATION_SPEC_PATH.as_posix(),
            "methodology_spec_sha256": CLARIFICATION_SPEC_SHA256,
            "methodology_module_path": CLARIFICATION_MODULE_PATH.as_posix(),
            "methodology_module_sha256": CLARIFICATION_MODULE_SHA256,
            "association_spec_path": ASSOCIATION_SPEC_PATH.as_posix(),
            "association_spec_sha256": ASSOCIATION_SPEC_SHA256,
            "association_module_path": ASSOCIATION_MODULE_PATH.as_posix(),
            "association_module_sha256": ASSOCIATION_MODULE_SHA256,
            "contract_fingerprint": contract_fingerprint(),
        },
        "implementation_files": [
            {"path": name, "sha256": digest}
            for name, digest in FROZEN_CONTRACT_IMPLEMENTATION_SHA256
        ],
        "association_authority": ASSOCIATION_AUTHORITY_ID,
        "association_projections": {
            key: list(columns) for key, columns in ASSOCIATION_PROJECTIONS.items()
        },
        "associations": [dict(item) for item in association_rows],
        "decoded_real_market_rows": 0 if synthetic else None,
        "decoded_real_upstream_rows": 0 if synthetic else None,
    }


def _nearest_unrelated_minutes(
    event_at: pd.Timestamp, upstream_event_id: str, touches: Mapping[str, pd.Timestamp | None], ranges: Mapping[str, object]
) -> float | None:
    values = [
        abs((touches.get(range_.range_id) - event_at).total_seconds() / 60.0)
        for range_ in ranges.values()
        if touches.get(range_.range_id) is not None and range_.upstream_event_id != upstream_event_id
    ]
    return min(values) if values else None


def _candidate_for_event(
    *,
    candidate_id: str,
    event_at: object,
    evidence_ids: tuple[object, ...],
    sequences: tuple[Mapping[str, object], ...],
    bars: tuple[object, ...],
    session: str,
    volatility: str,
    primary_by_upstream: Mapping[str, object],
    touches: Mapping[str, pd.Timestamp | None],
    evaluation_direction: object | None = None,
) -> object:
    """Construct one matcher candidate only from registered identity evidence."""

    stamp = pd.Timestamp(event_at)
    if stamp.tz is None:
        raise ValueError("candidate event must be timezone-aware")
    stamp = stamp.tz_convert("UTC")
    # Association is deliberately attempted before looking up the candidate's
    # own range.  A missing/ambiguous ID is retained as an auditable failure.
    association = associate_upstream_ids(evidence_ids, sequences)
    own_range = primary_by_upstream.get(str(association.sequence.get("sequence_id", ""))) if association.sequence is not None else None
    own_touch = bool(own_range is not None and touches.get(own_range.range_id) is not None and touches[own_range.range_id] <= stamp)
    direction = own_range.direction if own_range is not None else 1
    endpoint = exact_60m_outcome(stamp, direction, bars)
    return make_candidate(
        candidate_id=candidate_id,
        event_at=stamp,
        evidence_ids=evidence_ids,
        sequences=sequences,
        session=session,
        volatility_bucket=volatility,
        endpoint_complete=endpoint.endpoint_complete,
        own_ote_touched_at_event=own_touch,
        nearest_unrelated_ote_touch_minutes=_nearest_unrelated_minutes(stamp, str(association.sequence.get("sequence_id", "")) if association.sequence is not None else "", touches, primary_by_upstream),
        evaluation_direction=evaluation_direction,
    )


def _pair_rows(
    matches: tuple[tuple[str, str | None], ...],
    treatments: Mapping[str, object],
    controls: Mapping[str, object],
    treatment_outcomes: Mapping[str, object],
    control_outcomes: Mapping[str, object],
    family: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Materialize every matching attempt and only endpoint-complete pairs."""

    audit: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    for treatment_id, control_id in matches:
        treatment = treatments[treatment_id].observation
        control = controls[control_id].observation if control_id is not None else None
        audit.append({
            "control_family": family,
            "treatment_range_id": treatment_id,
            "control_id": control_id,
            "treatment_event_at": treatment.event_at,
            "control_event_at": control.event_at if control is not None else None,
            "matched": control is not None,
            "first_failure": None if control is not None else "missing_control",
        })
        left = treatment_outcomes.get(treatment_id)
        right = control_outcomes.get(control_id) if control_id is not None else None
        if left is None or right is None or not left.endpoint_complete or not right.endpoint_complete:
            continue
        pairs.append({
            "treatment_range_id": treatment_id,
            "control_id": control_id,
            "direction": treatment.direction,
            "named_trading_date": treatment.named_date,
            "treatment_event_at": treatment.event_at,
            "control_event_at": control.event_at,
            "treatment_reference_close": left.reference_close,
            "treatment_endpoint_close": left.endpoint_close,
            "treatment_movement": left.direction_aligned_movement,
            "control_reference_close": right.reference_close,
            "control_endpoint_close": right.endpoint_close,
            "control_movement": right.direction_aligned_movement,
            "paired_difference": left.direction_aligned_movement - right.direction_aligned_movement,
            "endpoint_complete": True,
        })
    return audit, pairs


def _split_rows(name: str, pairs: list[dict[str, object]], *, required_sign: bool = True) -> tuple[list[dict[str, object]], dict[str, object]]:
    frame = pd.DataFrame(pairs)
    output: list[dict[str, object]] = []
    yearly: dict[int, dict[str, object]] = {}
    for year in (2022, 2023, 2024, 2025):
        subset = frame.loc[frame["named_trading_date"].map(lambda value: value.year == year)] if len(frame) else frame
        test = mean_test(subset["paired_difference"] if len(subset) else [])
        yearly[year] = test
        output.append({"split_family": name, "split_value": str(year), "n": int(test["n"]), "mean": test["mean"], "ci_lower": test["ci_lower"], "ci_upper": test["ci_upper"], "required_sign": required_sign, "status": test["status"]})
    directions: dict[str, dict[str, object]] = {}
    for label, value in (("bullish", 1), ("bearish", -1)):
        subset = frame.loc[frame["direction"] == value] if len(frame) else frame
        test = mean_test(subset["paired_difference"] if len(subset) else [])
        directions[label] = test
        output.append({"split_family": name, "split_value": label, "n": int(test["n"]), "mean": test["mean"], "ci_lower": test["ci_lower"], "ci_upper": test["ci_upper"], "required_sign": required_sign, "status": test["status"]})
    return output, {"temporal": temporal_stability(yearly, positive=required_sign), "direction": direction_stability(directions, positive=required_sign), "yearly": yearly, "directions": directions}


def build_empirical_package(
    *,
    projected_1m: pd.DataFrame,
    sequences: tuple[Mapping[str, object], ...],
    upstream: Mapping[str, pd.DataFrame] | None = None,
    source_files: tuple[Mapping[str, object], ...] = (),
    synthetic: bool = True,
) -> PipelineResult:
    """Run every frozen analytical stage on already authenticated projections."""
    if not synthetic and not source_files:
        raise ValueError("authenticated historical provenance requires source file identities")
    upstream = upstream or {}
    sequences = _enrich_sequence_identities(
        sequences, _rows(upstream, "displacement_anchors.parquet")
    )
    e4_identities = _e4_identities(sequences)
    bars = build_5m_bars(projected_1m)
    if not bars:
        raise ValueError("D007 study has no complete five-minute bars")
    analysis_bars = tuple(
        bar for bar in bars if named_trading_date(bar.available_at).year in (2022, 2023, 2024, 2025)
    )
    ranges: list[object] = []
    exclusions: list[dict[str, object]] = []
    for sequence in sorted(sequences, key=lambda row: str(row.get("sequence_id", ""))):
        available = sequence.get("confirmation_event_available_at")
        if available is None or named_trading_date(available).year not in (2022, 2023, 2024, 2025):
            exclusions.append({"object_id": str(sequence.get("sequence_id", "")), "stage": "validation_interval", "first_failure": "outside_registered_named_year", "available_at": available})
            continue
        try:
            ranges.extend(reconstruct_ote_ranges(sequence, bars))
        except ValueError as exc:
            exclusions.append({"object_id": str(sequence.get("sequence_id", "")), "stage": "geometry", "first_failure": str(exc), "available_at": sequence.get("confirmation_event_available_at")})
    if not ranges:
        raise ValueError("D007 study constructed no frozen ranges")
    primary_all = [item for item in ranges if item.geometry_id == "ote_band_62_79"]
    primary, overlap_excluded = deduplicate_primary_overlaps(primary_all)
    range_by_id = {item.range_id: item for item in ranges}
    primary_by_upstream = {item.upstream_event_id: item for item in primary}
    lifecycle: dict[str, object] = {}
    for item in ranges:
        try:
            lifecycle[item.range_id] = evaluate_lifecycle(item, analysis_bars, min(max(bar.available_at for bar in analysis_bars), item.expiry_deadline))
        except ValueError as exc:
            exclusions.append({"object_id": item.range_id, "stage": "lifecycle", "first_failure": str(exc), "available_at": item.range_available_at})
    sequence_by_id = {str(row["sequence_id"]): row for row in sequences}
    sessions = {
        item.range_id: str(sequence_by_id[item.upstream_event_id]["anchor_session"])
        for item in ranges
    }
    volatility_by_date = _volatility_buckets(bars)
    volatility = {item.range_id: volatility_by_date.get(str(named_trading_date(item.range_available_at)), "unavailable") for item in ranges}
    touches = {range_id: record.first_touch_at for range_id, record in lifecycle.items()}
    treatment_candidates: list[object] = []
    treatment_outcomes: dict[str, object] = {}
    treatment_rows: list[dict[str, object]] = []
    treatment_ranges: dict[str, object] = {}
    for item in primary:
        record = lifecycle.get(item.range_id)
        if record is None or not primary_lifecycle_eligible(item) or record.first_touch_at is None:
            continue
        outcome = exact_60m_outcome(record.first_touch_at, item.direction, bars)
        treatment_outcomes[item.range_id] = outcome
        treatment_rows.append({"range_id": item.range_id, "first_touch_at": record.first_touch_at, "reference_close": outcome.reference_close, "endpoint_at": outcome.endpoint_at, "endpoint_close": outcome.endpoint_close, "direction_aligned_movement": outcome.direction_aligned_movement, "endpoint_complete": outcome.endpoint_complete, "first_failure": outcome.first_failure})
        candidate = make_candidate(candidate_id=item.range_id, event_at=record.first_touch_at, evidence_ids=(item.upstream_event_id,), sequences=sequences, session=None, volatility_bucket=volatility[item.range_id], endpoint_complete=outcome.endpoint_complete, own_ote_touched_at_event=False, nearest_unrelated_ote_touch_minutes=_nearest_unrelated_minutes(record.first_touch_at, item.upstream_event_id, touches, primary_by_upstream))
        if candidate.first_failure is not None:
            exclusions.append({"object_id": item.range_id, "stage": "treatment_association", "first_failure": candidate.first_failure, "available_at": record.first_touch_at})
            continue
        treatment_candidates.append(candidate); treatment_ranges[item.range_id] = item
    treatment_by_id = {item.observation.observation_id: item for item in treatment_candidates}
    e1_rows = _rows(upstream, "context_snapshots.parquet")
    e3_rows = _rows(upstream, "anchor_events.parquet")
    d004_rows = _rows(upstream, "daily_events.parquet")
    d006_rows = _rows(upstream, "structural_blocks.parquet")
    d004_constituents = _d004_constituents(d004_rows)
    d006_constituents, d006_exclusions = _d006_blocks(d006_rows)
    exclusions.extend(d006_exclusions)
    d006_path = ASSOCIATION_ARTIFACT_PATHS["d006_structural_blocks"]
    d006_identity = next(item for item in UPSTREAM_ARTIFACTS if item.path == d006_path)
    association_records: list[dict[str, object]] = [
        {
            "authority_id": ASSOCIATION_AUTHORITY_ID,
            "precedence_version": "new_outcome_blind_temporal_association_v1",
            "family": "d006",
            "constituent_id": exclusion["object_id"],
            "association_id": None,
            "exclusion_reason": exclusion["first_failure"],
            "constituent_event_at": (
                exclusion["constituent_event_at"].isoformat()
                if exclusion["constituent_event_at"] is not None
                else None
            ),
            "constituent_artifact": {
                "path": d006_path,
                "sha256": d006_identity.sha256,
            },
        }
        for exclusion in d006_exclusions
    ]
    d004_decisions: dict[str, object] = {}
    for constituent, source_row in d004_constituents:
        decision = associate_d004_to_e4(constituent, e4_identities)
        d004_decisions[constituent.event_id] = decision
        selected = next(
            (
                item
                for item in e4_identities
                if item.sequence_id == decision.e4_sequence_id
            ),
            None,
        )
        association_records.append(
            _association_provenance(decision, constituent, source_row, selected)
        )
    d006_decisions: dict[str, object] = {}
    for constituent, source_row in d006_constituents:
        decision = associate_d006_to_e4(constituent, e4_identities)
        d006_decisions[constituent.block_id] = decision
        selected = next(
            (
                item
                for item in e4_identities
                if item.sequence_id == decision.e4_sequence_id
            ),
            None,
        )
        association_records.append(
            _association_provenance(decision, constituent, source_row, selected)
        )
    equilibrium = equilibrium_candidates(primary, lifecycle, analysis_bars, session_by_range=sessions, volatility_by_range=volatility, sequences=sequences)
    context_controls = [
        _candidate_for_event(candidate_id=f"context:{row.get('snapshot_id', '')}", event_at=row["evaluation_at"], evidence_ids=tuple(row.get("evidence_ids") or ()), sequences=sequences, bars=bars, session="", volatility=volatility_by_date.get(str(named_trading_date(row["evaluation_at"])), "unavailable"), primary_by_upstream=primary_by_upstream, touches=touches, evaluation_direction=row.get("direction"))
        for row in e1_rows if row.get("state") == "reaction_confirmed" and row.get("mapping_name", row.get("mapping_variant")) == "1h_5m" and row.get("parent_timeframe") == "1H" and row.get("reaction_timeframe") == "5m" and not bool(row.get("optional_1m_refinement", False))
    ]
    displacement_controls = [
        _candidate_for_event(candidate_id=f"displacement:{row.get('sequence_id', '')}", event_at=row["confirmation_event_available_at"], evidence_ids=(row.get("sequence_id"),), sequences=sequences, bars=bars, session="", volatility=volatility_by_date.get(str(named_trading_date(row["confirmation_event_available_at"])), "unavailable"), primary_by_upstream=primary_by_upstream, touches=touches)
        for row in sequences
    ]
    families = {
        "matched_equilibrium_50": list(equilibrium),
        "matched_context_without_ote": context_controls,
        "matched_displacement_availability": displacement_controls,
    }
    control_rows: list[dict[str, object]] = []
    all_pairs: dict[str, list[dict[str, object]]] = {}
    control_summary: dict[str, object] = {}
    for family, candidates in families.items():
        candidate_by_id = {item.observation.observation_id: item for item in candidates if item.first_failure is None}
        outcomes = {identifier: exact_60m_outcome(item.observation.event_at, item.observation.direction, bars) for identifier, item in candidate_by_id.items()}
        matches = match_family(treatment_candidates, candidates, family)
        audits, pairs = _pair_rows(matches, treatment_by_id, candidate_by_id, treatment_outcomes, outcomes, family)
        control_rows.extend(audits); all_pairs[family] = pairs
        control_summary[family] = {"candidate": len(candidates), "eligible": len(candidate_by_id), "matched": sum(row["matched"] for row in audits), "endpoint_complete": len(pairs), "status": "EVALUATED" if pairs else "NOT_EVALUATED"}
    # Audit views reuse the exact primary pairs and never create replacement observations.
    for family in ("matched_time_session_volatility", "direction_balanced"):
        control_summary[family] = {"candidate": len(all_pairs["matched_equilibrium_50"]), "eligible": len(all_pairs["matched_equilibrium_50"]), "matched": len(all_pairs["matched_equilibrium_50"]), "endpoint_complete": len(all_pairs["matched_equilibrium_50"]), "status": "AUDIT_VIEW_REUSES_PRIMARY_PAIRS"}
    control_summary["upstream_no_ote_touch"] = {"candidate": sum(touches.get(item.range_id) is None for item in primary), "eligible": sum(touches.get(item.range_id) is None for item in primary), "matched": 0, "endpoint_complete": 0, "status": "STRUCTURAL_DENOMINATOR_NO_EVENT"}
    primary_pairs = all_pairs["matched_equilibrium_50"]
    primary_frame = pd.DataFrame(primary_pairs)
    primary_test = paired_student_t(primary_frame, treatment="treatment_movement", control="control_movement") if len(primary_frame) else mean_test([])
    primary_bootstrap = date_cluster_bootstrap(primary_frame, difference_column="paired_difference", date_column="named_trading_date", family="primary", hypothesis_id="ote_alone") if len(primary_frame) else {"status": "NOT_EVALUATED", "ci_lower": None, "ci_upper": None}

    sensitivity_rows: list[dict[str, object]] = []
    by_upstream = {item.upstream_event_id: item for item in ranges if item.geometry_id == "ote_reference_705"}
    band_touch: list[bool] = []; ref_touch: list[bool] = []; incidence_pairs: list[dict[str, object]] = []; time_pairs: list[dict[str, object]] = []; movement_pairs: list[dict[str, object]] = []
    for band in (item for item in primary_all if primary_lifecycle_eligible(item)):
        ref = by_upstream.get(band.upstream_event_id); record = lifecycle.get(ref.range_id) if ref is not None else None
        if ref is None or record is None:
            continue
        outcome = exact_60m_outcome(record.first_touch_at, ref.direction, bars) if record.first_touch_at is not None else None
        elapsed = (record.first_touch_at - ref.range_available_at).total_seconds() / 60.0 if record.first_touch_at is not None else None
        sensitivity_rows.append({"range_id": ref.range_id, "upstream_event_id": ref.upstream_event_id, "first_touch_at": record.first_touch_at, "touch_count": record.touch_count, "time_to_touch_minutes": elapsed, "direction_aligned_movement": outcome.direction_aligned_movement if outcome else None, "endpoint_complete": outcome.endpoint_complete if outcome else False})
        band_record = lifecycle.get(band.range_id)
        if band_record is None:
            continue
        band_touched = band_record.first_touch_at is not None
        ref_touched = record.first_touch_at is not None
        band_touch.append(band_touched); ref_touch.append(ref_touched)
        incidence_pairs.append({"named_trading_date": named_trading_date(band.range_available_at), "direction": int(band.direction), "paired_difference": int(band_touched) - int(ref_touched)})
        if band_record.first_touch_at is not None and record.first_touch_at is not None:
            time_pairs.append({"named_trading_date": named_trading_date(band_record.first_touch_at), "direction": int(band.direction), "paired_difference": (record.first_touch_at - ref.range_available_at).total_seconds() / 60.0 - (band_record.first_touch_at - band.range_available_at).total_seconds() / 60.0})
            left, right = exact_60m_outcome(band_record.first_touch_at, band.direction, bars), exact_60m_outcome(record.first_touch_at, ref.direction, bars)
            if left.endpoint_complete and right.endpoint_complete:
                movement_pairs.append({"named_trading_date": named_trading_date(band_record.first_touch_at), "direction": int(band.direction), "paired_difference": left.direction_aligned_movement - right.direction_aligned_movement})
    geometry_stats = {"geometry_touch_incidence": exact_mcnemar(band_touch, ref_touch), "geometry_time_to_touch": mean_test([row["paired_difference"] for row in time_pairs]), "geometry_directional_movement": mean_test([row["paired_difference"] for row in movement_pairs])}
    geometry_bootstrap = {
        "geometry_touch_incidence": date_cluster_bootstrap(pd.DataFrame(incidence_pairs), difference_column="paired_difference", date_column="named_trading_date", family="geometry", hypothesis_id="geometry_touch_incidence") if incidence_pairs else {"status": "NOT_EVALUATED", "ci_lower": None},
        "geometry_time_to_touch": date_cluster_bootstrap(pd.DataFrame(time_pairs), difference_column="paired_difference", date_column="named_trading_date", family="geometry", hypothesis_id="geometry_time_to_touch") if time_pairs else {"status": "NOT_EVALUATED", "ci_lower": None},
        "geometry_directional_movement": date_cluster_bootstrap(pd.DataFrame(movement_pairs), difference_column="paired_difference", date_column="named_trading_date", family="geometry", hypothesis_id="geometry_directional_movement") if movement_pairs else {"status": "NOT_EVALUATED", "ci_lower": None},
    }
    geometry_adjusted = benjamini_hochberg(geometry_stats, family="geometry")
    geometry_rows = [{"comparison": "ote_band_62_79_vs_ote_reference_705", "metric": name, "n": int(geometry_adjusted[name].get("n", 0)), "estimate": geometry_adjusted[name].get("mean", geometry_adjusted[name].get("risk_difference")), "p_value": geometry_adjusted[name].get("p_value"), "q_value": geometry_adjusted[name].get("q_value"), "status": geometry_adjusted[name].get("status", "NOT_EVALUATED")} for name in GEOMETRY_HYPOTHESES]

    d006_blocks = tuple(item for item, _row in d006_constituents)

    def d004_membership(item: object, _touch: object) -> Membership:
        eligible = [
            event
            for event, _row in d004_constituents
            if event.direction == int(item.direction)
            and event.available_at < item.range_available_at
            and event.trading_date == named_trading_date(item.range_available_at)
            and getattr(d004_decisions[event.event_id], "associated")
        ]
        if not eligible:
            return Membership(
                "after_d004_manipulation", None, None, None, False, "missing_constituent"
            )
        selected = min(
            eligible,
            key=lambda event: (-event.available_at.value, event.event_id),
        )
        return Membership(
            "after_d004_manipulation",
            selected.event_id,
            selected.available_at,
            item.direction,
            True,
        )

    def d006_membership(item: object, touch: object) -> Membership:
        selected = select_association_d006_block(d006_blocks, touch, int(item.direction))
        if selected is None or not getattr(
            d006_decisions[selected.block_id], "associated"
        ):
            return Membership(
                "d006_rejection_block", None, None, None, False, "missing_constituent"
            )
        return Membership(
            "d006_rejection_block",
            selected.block_id,
            selected.first_touch_at,
            item.direction,
            True,
        )
    interaction_pairs: list[dict[str, object]] = []
    interaction_statistics: dict[str, dict[str, object]] = {}
    interaction_stability: dict[str, object] = {}
    interaction_pair_sets: dict[str, list[dict[str, object]]] = {}
    interaction_ablation_raw: dict[str, dict[str, object]] = {}
    selector = {
        "aligned_d005_context": lambda item, touch: select_e1_context(item, e1_rows),
        "after_d004_manipulation": d004_membership,
        "frozen_liquidity_sweep": lambda item, touch: select_e3_liquidity_sweep(item, e3_rows),
        "refinement_confirmation": lambda item, touch: select_e3_refinement(item, touch, e3_rows),
        "d006_rejection_block": d006_membership,
        "against_d005_context_negative_control": lambda item, touch: select_e1_context(item, e1_rows, negative=True),
    }
    for name in INTERACTION_HYPOTHESES:
        selected: list[object] = []
        members: dict[str, object] = {}
        for identifier, item in treatment_ranges.items():
            membership = selector[name](item, treatment_by_id[identifier].observation.event_at)
            members[identifier] = membership
            if membership.eligible:
                selected.append(treatment_by_id[identifier])
        if name in {"aligned_d005_context", "against_d005_context_negative_control"}:
            candidates = [
                _candidate_for_event(
                    candidate_id=f"interaction:{name}:{row.get('snapshot_id', '')}",
                    event_at=row["evaluation_at"], evidence_ids=tuple(row.get("evidence_ids") or ()),
                    sequences=sequences, bars=bars, session="",
                    volatility=volatility_by_date.get(str(named_trading_date(row["evaluation_at"])), "unavailable"),
                    primary_by_upstream=primary_by_upstream, touches=touches,
                    evaluation_direction=(int(row.get("direction")) if name == "aligned_d005_context" else -int(row.get("direction"))),
                )
                for row in e1_rows
                if row.get("state") == "reaction_confirmed"
                and row.get("mapping_name", row.get("mapping_variant")) == "1h_5m"
                and row.get("parent_timeframe") == "1H"
                and row.get("reaction_timeframe") == "5m"
                and not bool(row.get("optional_1m_refinement", False))
                and row.get("direction") in (-1, 1)
            ]
        elif name in {"frozen_liquidity_sweep", "refinement_confirmation"}:
            candidates = [_candidate_for_event(candidate_id=f"{name}:{row.get('anchor_id', '')}", event_at=row["anchor_at"], evidence_ids=(row.get("anchor_event_id"),), sequences=sequences, bars=bars, session="", volatility=volatility_by_date.get(str(named_trading_date(row["anchor_at"])), "unavailable"), primary_by_upstream=primary_by_upstream, touches=touches, evaluation_direction=row.get("direction")) for row in e3_rows if row.get("anchor_type") == ("named_liquidity_sweep" if name == "frozen_liquidity_sweep" else "refinement_array_creation") and (name != "frozen_liquidity_sweep" or (bool(row.get("main_scope_eligible")) and bool(row.get("anchor_causally_observable")) and not bool(row.get("anchor_selected_using_later_completion"))))]
            candidates = [candidate for candidate in candidates if candidate.first_failure is None]
        elif name == "after_d004_manipulation":
            candidates = []
            for event, _row in d004_constituents:
                decision = d004_decisions[event.event_id]
                candidates.append(
                    make_candidate(
                        candidate_id=str(decision.association_id or event.event_id),
                        event_at=event.available_at,
                        evidence_ids=(decision.e4_sequence_id,),
                        sequences=sequences,
                        session=None,
                        volatility_bucket=volatility_by_date.get(
                            str(named_trading_date(event.available_at)), "unavailable"
                        ),
                        endpoint_complete=exact_60m_outcome(
                            event.available_at, event.direction, bars
                        ).endpoint_complete,
                        own_ote_touched_at_event=False,
                        nearest_unrelated_ote_touch_minutes=_nearest_unrelated_minutes(
                            event.available_at,
                            str(decision.e4_sequence_id or ""),
                            touches,
                            primary_by_upstream,
                        ),
                        evaluation_direction=event.direction,
                        association_decision=decision,
                    )
                )
        else:
            candidates = []
            for block, _row in d006_constituents:
                decision = d006_decisions[block.block_id]
                candidates.append(
                    make_candidate(
                        candidate_id=str(decision.association_id or block.block_id),
                        event_at=block.first_touch_at,
                        evidence_ids=(decision.e4_sequence_id,),
                        sequences=sequences,
                        session=None,
                        volatility_bucket=volatility_by_date.get(
                            str(named_trading_date(block.first_touch_at)), "unavailable"
                        ),
                        endpoint_complete=exact_60m_outcome(
                            block.first_touch_at, block.direction, bars
                        ).endpoint_complete,
                        own_ote_touched_at_event=False,
                        nearest_unrelated_ote_touch_minutes=_nearest_unrelated_minutes(
                            block.first_touch_at,
                            str(decision.e4_sequence_id or ""),
                            touches,
                            primary_by_upstream,
                        ),
                        evaluation_direction=block.direction,
                        association_decision=decision,
                    )
                )
        candidate_by_id = {item.observation.observation_id: item for item in candidates if item.first_failure is None}
        outcomes = {identifier: exact_60m_outcome(item.observation.event_at, item.observation.direction, bars) for identifier, item in candidate_by_id.items()}
        matches = match_family(selected, candidates, f"interaction:{name}")
        audits, pairs = _pair_rows(matches, treatment_by_id, candidate_by_id, treatment_outcomes, outcomes, f"interaction:{name}")
        control_rows.extend(audits)
        matched_by_range = {row["treatment_range_id"]: row for row in audits}
        pair_by_range = {row["treatment_range_id"]: row for row in pairs}
        for identifier, membership in members.items():
            audit = matched_by_range.get(identifier)
            interaction_pairs.append({"interaction_name": name, "range_id": identifier, "evidence_id": membership.evidence_id, "evidence_available_at": membership.event_at, "eligible": membership.eligible, "paired_difference": pair_by_range.get(identifier, {}).get("paired_difference"), "first_failure": membership.first_failure if not membership.eligible else (audit.get("first_failure") if audit else "missing_control")})
        test = paired_student_t(pd.DataFrame(pairs), treatment="treatment_movement", control="control_movement") if pairs else mean_test([])
        bootstrap = date_cluster_bootstrap(pd.DataFrame(pairs), difference_column="paired_difference", date_column="named_trading_date", family="interactions", hypothesis_id=name) if pairs else {"status": "NOT_EVALUATED", "ci_lower": None}
        interaction_statistics[name] = {**test, "bootstrap": bootstrap, "candidate": len(members), "eligible": len(selected), "matched": len(audits) - sum(not row["matched"] for row in audits), "endpoint_complete": len(pairs)}
        _, interaction_stability[name] = _split_rows(name, pairs)
        interaction_pair_sets[name] = pairs
        interaction_ablation_raw[name] = {
            **test,
            "bootstrap": bootstrap,
            "identical_cohort": tuple(sorted(row["treatment_range_id"] for row in pairs)),
        }
    interaction_adjusted = benjamini_hochberg(interaction_statistics, family="interactions")
    interaction_ablation_adjusted = benjamini_hochberg(
        interaction_ablation_raw, family="interactions"
    )
    interaction_ablations = {
        name: _interaction_ablation_status(
            name, row, interaction_stability[name]
        )
        for name, row in interaction_ablation_adjusted.items()
    }

    incremental_raw: dict[str, dict[str, object]] = {}
    incremental_stability: dict[str, object] = {}
    for family in ("matched_context_without_ote", "matched_displacement_availability"):
        pairs = all_pairs[family]
        test = paired_student_t(pd.DataFrame(pairs), treatment="treatment_movement", control="control_movement") if pairs else mean_test([])
        bootstrap = date_cluster_bootstrap(pd.DataFrame(pairs), difference_column="paired_difference", date_column="named_trading_date", family="incremental_controls", hypothesis_id=family) if pairs else {"status": "NOT_EVALUATED", "ci_lower": None}
        incremental_raw[family] = {**test, "bootstrap": bootstrap}
        _, incremental_stability[family] = _split_rows(family, pairs)
    incremental_adjusted = benjamini_hochberg(incremental_raw, family="incremental_controls")
    ablations = {name: ablation_status(n=int(row.get("n", 0)), mean_difference=float(row["mean"]) if row.get("mean") is not None else float("nan"), t_interval_lower=float(row["ci_lower"]) if row.get("ci_lower") is not None else float("nan"), t_interval_upper=float(row["ci_upper"]) if row.get("ci_upper") is not None else float("nan"), bootstrap_lower=float(row["bootstrap"].get("ci_lower")) if row.get("bootstrap", {}).get("ci_lower") is not None else float("nan"), q_value=float(row["q_value"]) if row.get("q_value") is not None else float("nan"), stable=bool(incremental_stability[name]["temporal"]["passed"] and incremental_stability[name]["direction"]["passed"])) for name, row in incremental_adjusted.items()}

    redundancy_rows: list[dict[str, object]] = []
    population = [(item, treatment_by_id[identifier].observation.event_at) for identifier, item in treatment_ranges.items() if treatment_outcomes[identifier].endpoint_complete]
    for feature in REDUNDANCY_FEATURES:
        time_associated: list[bool] = []
        price_eligible: list[bool] = []
        price_overlapped: list[bool] = []
        signed: list[float] = []
        failures: list[str] = []
        for item, touch in population:
            if feature in {"d005_displacement", "equilibrium_position", "continuous_retracement_depth", "availability_to_touch_time"}:
                time_associated.append(True)
                if feature == "availability_to_touch_time": signed.append((touch - item.range_available_at).total_seconds() / 60.0)
                if feature == "equilibrium_position":
                    price_eligible.append(True)
                    price_overlapped.append(
                        item.zone_low <= item.equilibrium <= item.zone_high
                    )
                else:
                    price_eligible.append(False)
                    failures.append("price_not_available")
                continue
            if feature == "d005_displacement_strength":
                time_associated.append(False)
                price_eligible.append(False)
                failures.extend(("missing_authenticated_evidence", "price_not_available"))
                continue
            if feature == "d005_context":
                rows, key = e1_rows, "evaluation_at"
            elif feature == "d006_rejection_block":
                rows, key = d006_rows, "causal_availability"
            else:
                anchor_type = {
                    "body_close_mss": "mss_body_close_confirmation",
                    "refinement_array": "refinement_array_creation",
                    "raw_fvg": "first_aligned_raw_fvg_creation",
                    "qualified_fvg": "first_context_qualified_fvg_creation",
                    "liquidity_sweep": "named_liquidity_sweep",
                }[feature]
                rows, key = tuple(row for row in e3_rows if row.get("anchor_type") == anchor_type), "anchor_at"
            normalized = [{
                "evidence_id": row.get("snapshot_id", row.get("anchor_id", row.get("block_id", ""))),
                "available_at": row.get(key),
                "direction": ({"bullish": 1, "bearish": -1, "1": 1, "-1": -1}.get(str(row.get("direction", "")).lower(), row.get("direction")) if feature == "d006_rejection_block" else row.get("direction")),
                "mitigation_at": _optional_timestamp(row.get("mitigation_timestamp")),
                "invalidation_at": _optional_timestamp(row.get("invalidation_timestamp")),
                "expiry_at": _optional_timestamp(row.get("expiry_timestamp")),
                "price": (
                    float(row.get("anchor_price_override"))
                    if feature in {"body_close_mss", "refinement_array", "raw_fvg", "qualified_fvg", "liquidity_sweep"}
                    and row.get("anchor_price_override") is not None
                    and not pd.isna(row.get("anchor_price_override"))
                    else None
                ),
            } for row in rows if row.get(key) is not None]
            association = select_redundancy_evidence(item, touch, normalized)
            if association.evidence_id is not None:
                time_associated.append(True); signed.append(float(association.signed_minutes))
                selected_price = next(
                    (
                        row.get("price")
                        for row in normalized
                        if row.get("evidence_id") == association.evidence_id
                    ),
                    None,
                )
                if selected_price is None:
                    price_eligible.append(False)
                    failures.append("price_not_available")
                else:
                    price_eligible.append(True)
                    price_overlapped.append(
                        item.zone_low <= float(selected_price) <= item.zone_high
                    )
            else:
                time_associated.append(False)
                price_eligible.append(False)
                failures.extend((association.first_failure or "missing_constituent", "price_not_available"))
        time_denominator = len(population)
        time_count = sum(time_associated)
        price_denominator = sum(price_eligible)
        price_count = sum(price_overlapped)
        incremental_status = (
            ablations["matched_context_without_ote"] if feature == "d005_context" else
            ablations["matched_displacement_availability"] if feature == "d005_displacement" else
            "MISSING_AUTHENTICATED_STRENGTH" if feature == "d005_displacement_strength" else
            "NOT_APPLICABLE_STRUCTURAL"
        )
        redundancy_rows.append({"feature": feature, "time_association_count": time_count, "time_association_denominator": time_denominator, "time_association_rate": time_count / time_denominator if time_denominator else None, "price_overlap_count": price_count, "price_overlap_denominator": price_denominator, "price_overlap_rate": price_count / price_denominator if price_denominator else None, "price_audit_state": "evaluated" if price_denominator == time_denominator else "price_not_available", "median_signed_minutes": float(pd.Series(signed).median()) if signed else None, "first_failure": failures[0] if failures else None, "incremental_status": incremental_status})
    stability_rows, primary_stability = _split_rows("ote_alone", primary_pairs)
    geometry_stability: dict[str, object] = {}
    for name, pairs in (("geometry_touch_incidence", incidence_pairs), ("geometry_time_to_touch", time_pairs), ("geometry_directional_movement", movement_pairs)):
        rows, split = _split_rows(name, pairs); stability_rows.extend(rows); geometry_stability[name] = split
    for name, pairs in all_pairs.items():
        if name != "matched_equilibrium_50":
            rows, _ = _split_rows(name, pairs); stability_rows.extend(rows)
    for name in INTERACTION_HYPOTHESES:
        rows, _ = _split_rows(name, interaction_pair_sets[name]); stability_rows.extend(rows)
    primary_matched = sum(row["matched"] for row in control_rows if row["control_family"] == "matched_equilibrium_50")
    counts = {"constructed_ranges": len(primary_all), "lifecycle_eligible": sum(primary_lifecycle_eligible(item) and item.range_id in lifecycle for item in primary_all), "first_touches": len(treatment_rows), "untouched_controls": sum(touches.get(item.range_id) is None for item in primary), "primary_pairs": len(primary_pairs), "bullish": sum(row["direction"] == 1 for row in primary_pairs), "bearish": sum(row["direction"] == -1 for row in primary_pairs), "endpoint_coverage": 1.0 if primary_matched > 0 and len(primary_pairs) == primary_matched else 0.0}
    for year in (2022, 2023, 2024, 2025): counts[f"pairs_{year}"] = sum(row["named_trading_date"].year == year for row in primary_pairs)
    for name in ("asia", "premarket", "ny_observation", "ny_afternoon"): counts[f"touches_{name}"] = sum(sessions[row["range_id"]] == name for row in treatment_rows)
    counts["interaction_ote_alone"] = len(primary_pairs)
    for name in INTERACTION_HYPOTHESES: counts[f"interaction_{name}"] = int(interaction_adjusted[name].get("n", 0))
    counts["geometry_ote_band_62_79"] = len(band_touch); counts["geometry_ote_reference_705"] = len(ref_touch)
    from research.d007_ote_research.guardrails import adequacy_status, component_disposition
    adequacy = adequacy_status(counts)
    yearly_means = {year: primary_stability["yearly"][year].get("mean") for year in (2022, 2023, 2024, 2025)}
    geometry_passed = geometry_candidate_passes(
        adjusted=geometry_adjusted,
        bootstrap=geometry_bootstrap,
        stability=geometry_stability,
    )
    negative = interaction_adjusted["against_d005_context_negative_control"]
    negative_control_failure = bool(negative.get("mean") is not None and negative["mean"] > 0 and negative.get("ci_lower") is not None and negative["ci_lower"] > 0 and negative.get("q_value") is not None and negative["q_value"] <= .05)
    conditional = bool(not negative_control_failure and any(name not in {"after_d004_manipulation", "d006_rejection_block", "against_d005_context_negative_control"} and positive_effect_passes(interaction_adjusted[name], interaction_adjusted[name].get("bootstrap", {}), interaction_adjusted[name].get("q_value")) and interaction_stability[name]["temporal"]["passed"] and interaction_stability[name]["direction"]["passed"] and interaction_ablations[name] == "NON_REDUNDANT" for name in INTERACTION_HYPOTHESES))
    primary_passed = bool(primary_test.get("mean") is not None and primary_test["mean"] > 0 and primary_test.get("ci_lower") is not None and primary_test["ci_lower"] > 0 and primary_test.get("p_value") is not None and primary_test["p_value"] < .05 and primary_bootstrap.get("ci_lower") is not None and primary_bootstrap["ci_lower"] > 0 and primary_stability["temporal"]["passed"] and primary_stability["direction"]["passed"])
    disposition = component_disposition(integrity_passed=True, adequacy_passed=adequacy == "SAMPLE_ADEQUATE", structural_passed=bool(ranges), primary_ci_upper=primary_test.get("ci_upper"), non_redundant_passed=primary_passed and all(value == "NON_REDUNDANT" for value in ablations.values()), conditional_passed=conditional, geometry_passed=geometry_passed, yearly_means=yearly_means)

    tables = {name: empty_table_frame(name) for name in TABLE_SCHEMAS}
    def frame(name: str, rows: list[dict[str, object]]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=[field[0] for field in TABLE_SCHEMAS[name]])
    tables["ote_ranges.parquet"] = frame("ote_ranges.parquet", [_range_row(item, session=sessions[item.range_id], volatility=volatility[item.range_id]) for item in ranges])
    tables["lifecycle_records.parquet"] = frame("lifecycle_records.parquet", [{**asdict(record), "lifecycle_eligible": primary_lifecycle_eligible(range_by_id[record.range_id])} for record in lifecycle.values()])
    tables["primary_treatments.parquet"] = frame("primary_treatments.parquet", treatment_rows)
    tables["control_matches.parquet"] = frame("control_matches.parquet", control_rows)
    tables["primary_pairs.parquet"] = frame("primary_pairs.parquet", primary_pairs)
    tables["interaction_pairs.parquet"] = frame("interaction_pairs.parquet", interaction_pairs)
    tables["sensitivity_705.parquet"] = frame("sensitivity_705.parquet", sensitivity_rows)
    tables["redundancy_audit.parquet"] = frame("redundancy_audit.parquet", redundancy_rows)
    tables["stability_summaries.parquet"] = frame("stability_summaries.parquet", stability_rows)
    tables["exclusions.parquet"] = frame("exclusions.parquet", exclusions)
    tables["dedup_exclusions.parquet"] = frame("dedup_exclusions.parquet", [{"range_id": item.range_id, "upstream_event_id": item.upstream_event_id, "geometry_id": item.geometry_id, "exclusion_reason": "primary_overlap_deduplication", "retained_range_id": None} for item in overlap_excluded])
    tables["geometry_comparisons.parquet"] = frame("geometry_comparisons.parquet", geometry_rows)
    provenance_payload = _deterministic_provenance(
        source_files=source_files,
        synthetic=synthetic,
    )
    provenance_payload["associations"] = association_records
    result = {"disposition": disposition, "provenance": provenance_payload, "counts": {**counts, "exclusions": len(exclusions)}, "adequacy": {"status": adequacy, "requirements": counts}, "statistics": {"primary_status": primary_test.get("status"), "primary_mean_difference": primary_test.get("mean"), "primary_interval": [primary_test.get("ci_lower"), primary_test.get("ci_upper")], "primary": primary_test, "bootstrap": primary_bootstrap, "geometry": geometry_adjusted, "geometry_bootstrap": geometry_bootstrap, "interactions": interaction_adjusted, "interaction_ablations": interaction_ablation_adjusted, "incremental_controls": incremental_adjusted}, "controls": control_summary, "geometry": geometry_adjusted, "interactions": interaction_adjusted, "redundancy": {"features": redundancy_rows, "ablations": ablations, "interaction_ablations": interaction_ablations, "status": "EVALUATED_FIXED_ABLATIONS"}}
    json_objects = {"aggregate_audit.json": result["counts"], "contract_snapshot.json": DEFAULT_CONTRACT.snapshot(), "run_manifest.json": {"schema": "d007-ote-run-manifest-v1", "disposition": disposition, "contract_fingerprint": provenance_payload.get("contract_identities", {}).get("contract_fingerprint") if isinstance(provenance_payload.get("contract_identities"), Mapping) else None, "implementation_files": provenance_payload.get("implementation_files", []), "association_authority": provenance_payload.get("association_authority")}, "source_audit.json": provenance_payload, "statistical_validation.json": result["statistics"], "summary.json": result, "upstream_audit.json": {name: {"rows": len(value), "projected_columns": list(value.columns)} for name, value in upstream.items()}}
    return PipelineResult(ArtifactPackage(json_objects, render_historical_report(result), tables), result)


def _market_inventory(repository_root: Path) -> tuple[MarketParquetRecord, ...]:
    payload = json.loads((repository_root / D005_E4_ROOT / "source_provenance.json").read_text(encoding="utf-8"))
    records = payload.get("files")
    if not isinstance(records, list):
        raise ValueError("D005 E4 source inventory is missing")
    marker = SOURCE_ROOT.as_posix() + "/"
    result: list[MarketParquetRecord] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("D005 E4 source inventory record is invalid")
        normalized = record["path"].replace("\\", "/")
        if marker not in normalized:
            raise ValueError("D005 E4 source inventory escaped frozen root")
        relative = normalized.split(marker, 1)[1]
        result.append(MarketParquetRecord(relative, str(record.get("sha256", "")), int(record.get("bytes", -1))))
    return tuple(result)


def run_authenticated_historical_pipeline(repository_root: Path) -> Path:
    """Decode only authenticated projections and publish the complete frozen package.

    The caller must have completed contract preflight and exact authorization
    before entering this function.  There is deliberately no independent CLI
    or methodology parameter surface here.
    """

    root = repository_root.resolve()
    market_inventory = _market_inventory(root)
    projected = load_market_bars(root / SOURCE_ROOT, market_inventory)
    upstream: dict[str, pd.DataFrame] = {}
    for identity in UPSTREAM_ARTIFACTS:
        projection = ASSOCIATION_PROJECTIONS_BY_PATH.get(
            identity.path, identity.required_columns
        )
        timestamps = tuple(name for name in projection if name.endswith("_at") or name.endswith("_time") or name.endswith("_timestamp") or name in {"causal_availability", "expiry_deadline"})
        unique = (
            ("sequence_id",) if "sequence_id" in projection else
            ("snapshot_id",) if "snapshot_id" in projection else
            ("anchor_id",) if "anchor_id" in projection else
            ("block_id",) if "block_id" in projection else ()
        )
        order = (
            ("trading_date",) if "trading_date" in projection else
            ("evaluation_at", "snapshot_id") if "snapshot_id" in projection else
            ("anchor_at", "anchor_id") if "anchor_id" in projection else
            ("causal_availability", "block_id") if "block_id" in projection else
            ("confirmation_event_available_at", "sequence_id") if "confirmation_event_available_at" in projection else
            ("anchor_at", "sequence_id") if "anchor_at" in projection and "sequence_id" in projection else
            unique
        )
        upstream[identity.path] = load_structural_artifact(
            root, identity, timestamp_columns=timestamps,
            unique_columns=unique, order_columns=order,
        )
    sequence_identity = next(item for item in UPSTREAM_ARTIFACTS if item.path.endswith("eligible_sequences.parquet"))
    sequences_frame = upstream[sequence_identity.path]
    result = build_empirical_package(
        projected_1m=projected,
        sequences=tuple(sequences_frame.to_dict("records")),
        upstream=upstream,
        source_files=tuple(
            {
                "relative_path": item.relative_path,
                "bytes": item.byte_size,
                "sha256": item.sha256,
            }
            for item in market_inventory
        ),
        synthetic=False,
    )
    return publish_package(root, result.package)


def run_synthetic_study(
    *,
    projected_1m: pd.DataFrame,
    sequences: tuple[Mapping[str, object], ...],
    output_root: Path,
    output_relative: Path = Path("synthetic-d007-package"),
) -> Path:
    """Exercise the complete composition and publication path on synthetic data."""

    anchors = pd.DataFrame(
        [
            {
                "sequence_id": row["sequence_id"],
                "mapping_variant": row["mapping_variant"],
                "anchor_event_id": row["anchor_event_id"],
                "anchor_at": row["anchor_at"],
                "direction": row["direction"],
                "main_scope_eligible": row["main_scope_eligible"],
                "anchor_causally_observable": row["anchor_causally_observable"],
                "anchor_selected_using_later_completion": row[
                    "anchor_selected_using_later_completion"
                ],
                "anchor_session": row["anchor_session"],
                "anchor_year": row["anchor_year"],
            }
            for row in sequences
        ]
    )
    result = build_empirical_package(
        projected_1m=projected_1m,
        sequences=sequences,
        upstream={"displacement_anchors.parquet": anchors},
    )
    return publish_synthetic_package(output_root, output_relative, result.package)


__all__ = ["PipelineResult", "build_empirical_package", "geometry_candidate_passes", "run_authenticated_historical_pipeline", "run_synthetic_study"]
