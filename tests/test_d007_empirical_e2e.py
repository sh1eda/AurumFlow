from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from research.d007_methodology_clarification import named_trading_date
from research.d007_ote_historical_contract.empirical import build_5m_bars, reconstruct_ote_ranges
from research.d007_ote_historical_contract.pipeline import _volatility_buckets, build_empirical_package, geometry_candidate_passes, run_synthetic_study
from research.d007_ote_historical_contract.schemas import ALL_ARTIFACTS, TABLE_SCHEMAS


def _minutes(start: str, periods: int, bullish: bool) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="min", tz="UTC")
    values: list[dict[str, object]] = []
    for position, stamp in enumerate(index):
        # Deterministic path: a width-two opposite swing, displacement, touch,
        # then enough complete bars for the exact 60-minute endpoint.
        if bullish:
            center = 100 + position * 0.05
            if 10 <= position < 15:
                center -= (5 - abs(position - 12)) * 2
            if 30 <= position < 45:
                center += (position - 29) * 0.8
            if 45 <= position < 60:
                center -= (position - 44) * 0.45
        else:
            center = 200 - position * 0.05
            if 10 <= position < 15:
                center += (5 - abs(position - 12)) * 2
            if 30 <= position < 45:
                center -= (position - 29) * 0.8
            if 45 <= position < 60:
                center += (position - 44) * 0.45
        values.append({"timestamp_utc": stamp, "open": center, "high": center + 1, "low": center - 1, "close": center + (0.1 if bullish else -0.1)})
    return pd.DataFrame(values)


def _sequence(identifier: str, direction: int, created: str, available: str) -> dict[str, object]:
    anchor_at = pd.Timestamp(created)
    return {
        "sequence_id": identifier,
        "mapping_variant": "1h_5m",
        "direction": direction,
        "candidate_direction": direction,
        "mss_direction": direction,
        "displacement_direction": direction,
        "confirmation_event_direction": direction,
        "main_candidate_eligible": True,
        "main_scope_eligible": True,
        "anchor_causally_observable": True,
        "anchor_selected_using_later_completion": False,
        "displacement_created_at": pd.Timestamp(created),
        "confirmation_event_available_at": pd.Timestamp(available),
        "displacement_confirmation_event_id": f"disp-{identifier}",
        "anchor_event_id": f"anchor-{identifier}",
        "anchor_at": anchor_at,
        "anchor_session": "premarket",
        "anchor_year": anchor_at.tz_convert("America/New_York").year,
    }


def _anchor_frame(sequence: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "sequence_id": sequence["sequence_id"],
            "mapping_variant": sequence["mapping_variant"],
            "anchor_event_id": sequence["anchor_event_id"],
            "anchor_at": sequence["anchor_at"],
            "direction": sequence["direction"],
            "main_scope_eligible": sequence["main_scope_eligible"],
            "anchor_causally_observable": sequence["anchor_causally_observable"],
            "anchor_selected_using_later_completion": sequence["anchor_selected_using_later_completion"],
            "anchor_session": sequence["anchor_session"],
            "anchor_year": sequence["anchor_year"],
        }]
    )


def test_miniature_bullish_and_bearish_synthetic_studies_publish_complete_packages(tmp_path: Path) -> None:
    for name, bullish in (("bull", True), ("bear", False)):
        frame = _minutes("2024-05-01T09:00:00Z", 180, bullish)
        sequence = _sequence(
            name,
            1 if bullish else -1,
            "2024-05-01T09:30:00Z",
            "2024-05-01T09:45:00Z",
        )
        output = run_synthetic_study(
            projected_1m=frame,
            sequences=(sequence,),
            output_root=tmp_path,
            output_relative=Path(name),
        )
        assert {path.name for path in output.iterdir()} == set(ALL_ARTIFACTS)
        manifest = json.loads((output / "artifact_manifest.json").read_text())
        assert manifest["schema"] == "d007-ote-artifact-manifest-v1"
        ranges = pq.read_table(output / "ote_ranges.parquet").to_pandas()
        assert set(ranges["direction"]) == ({1} if bullish else {-1})
        summary = json.loads((output / "summary.json").read_text())
        assert summary["disposition"] == "INSUFFICIENT_EVIDENCE"
        assert summary["adequacy"]["status"] == "SAMPLE_INADEQUATE"


def test_full_empirical_composition_populates_associations_ablations_redundancy_and_provenance() -> None:
    """Exercise the in-memory pipeline in both directions, never a real input."""

    for name, bullish in (("bull", True), ("bear", False)):
        frame = _minutes("2024-05-01T09:00:00Z", 180, bullish)
        sequence = _sequence(name, 1 if bullish else -1, "2024-05-01T09:30:00Z", "2024-05-01T09:45:00Z")
        range_ = next(item for item in reconstruct_ote_ranges(sequence, build_5m_bars(frame)) if item.geometry_id == "ote_band_62_79")
        # D004 and D006 carry no E4 ID; the frozen temporal bridges associate
        # each constituent to the exact authenticated E4 identity instead.
        d004 = {
            "trading_date": range_.range_available_at.date(),
            "primary_reference_name": "0800_0830",
            "low_sweep": bullish,
            "high_sweep": not bullish,
            "low_sweep_time": range_.range_available_at - pd.Timedelta(minutes=9) if bullish else None,
            "high_sweep_time": range_.range_available_at - pd.Timedelta(minutes=9) if not bullish else None,
            "low_reentry": bullish,
            "high_reentry": not bullish,
            "low_reentry_time": range_.range_available_at - pd.Timedelta(minutes=6) if bullish else None,
            "high_reentry_time": range_.range_available_at - pd.Timedelta(minutes=6) if not bullish else None,
        }
        # The row is deliberately active at the eventual OTE touch.
        d006 = pd.DataFrame(columns=[
            "block_id", "definition_name", "direction", "source_bar_ids", "expansion_bar_id", "confirmation_timestamp", "causal_availability", "range", "lifecycle_state",
            "first_touch_timestamp", "mitigation_timestamp", "invalidation_timestamp", "expiry_timestamp",
            "expiry_deadline", "preavailability_interaction",
        ])
        neutral_context = pd.DataFrame([{
            "snapshot_id": f"neutral-{name}",
            "evaluation_at": range_.range_available_at,
            "mapping_name": "1h_5m",
            "mapping_variant": "1h_5m",
            "optional_1m_refinement": False,
            "parent_timeframe": "1H",
            "reaction_timeframe": "5m",
            "state": "neutral",
            "direction": 0,
            "evidence_ids": [],
        }])
        preliminary = build_empirical_package(
            projected_1m=frame,
            sequences=(sequence,),
            upstream={"daily_events.parquet": pd.DataFrame([d004]), "context_snapshots.parquet": neutral_context, "structural_blocks.parquet": d006, "displacement_anchors.parquet": _anchor_frame(sequence)},
        )
        touch = pd.Timestamp(preliminary.package.tables["primary_treatments.parquet"].iloc[0]["first_touch_at"])
        d006_row = {
            "block_id": f"block-{name}", "definition_name": "single_wick_50_d3_v1", "direction": "bullish" if bullish else "bearish",
            "source_bar_ids": [f"source-{name}"], "expansion_bar_id": f"expansion-{name}",
            "confirmation_timestamp": touch - pd.Timedelta(minutes=10),
            "causal_availability": touch - pd.Timedelta(minutes=10), "range": 1.0, "lifecycle_state": "ACTIVE_TOUCHED",
            "first_touch_timestamp": touch - pd.Timedelta(minutes=5), "mitigation_timestamp": None,
            "invalidation_timestamp": None, "expiry_timestamp": None, "expiry_deadline": touch + pd.Timedelta(hours=23, minutes=50),
            "preavailability_interaction": False,
        }
        untouched = {
            **d006_row,
            "block_id": f"untouched-{name}",
            "source_bar_ids": [f"untouched-source-{name}"],
            "expansion_bar_id": f"untouched-expansion-{name}",
            "lifecycle_state": "ACTIVE_UNTOUCHED",
            "first_touch_timestamp": None,
        }
        d006 = pd.DataFrame([d006_row, untouched])
        upstream = {"daily_events.parquet": pd.DataFrame([d004]), "context_snapshots.parquet": neutral_context, "structural_blocks.parquet": d006, "displacement_anchors.parquet": _anchor_frame(sequence)}
        result = build_empirical_package(projected_1m=frame, sequences=(sequence,), upstream=upstream)
        repeated = build_empirical_package(projected_1m=frame, sequences=(sequence,), upstream=upstream)
        assert repeated.package.json_objects["source_audit.json"] == result.package.json_objects["source_audit.json"]
        assert repeated.package.json_objects["run_manifest.json"] == result.package.json_objects["run_manifest.json"]
        assert set(result.package.tables) == set(TABLE_SCHEMAS)
        assert len(result.package.tables["geometry_comparisons.parquet"]) == 3
        assert set(result.package.tables["redundancy_audit.parquet"]["feature"]) == {
            "d005_displacement", "d005_displacement_strength", "body_close_mss", "refinement_array", "raw_fvg", "qualified_fvg",
            "liquidity_sweep", "d005_context", "d006_rejection_block", "equilibrium_position", "continuous_retracement_depth", "availability_to_touch_time",
        }
        interactions = result.package.tables["interaction_pairs.parquet"]
        assert set(interactions["interaction_name"]) == {
            "aligned_d005_context", "after_d004_manipulation", "frozen_liquidity_sweep", "refinement_confirmation", "d006_rejection_block", "against_d005_context_negative_control",
        }
        for interaction in ("after_d004_manipulation", "d006_rejection_block"):
            row = interactions.loc[interactions["interaction_name"] == interaction].iloc[0]
            assert row["eligible"]
        source_audit = result.package.json_objects["source_audit.json"]
        associations = source_audit["associations"]
        successful_associations = [row for row in associations if row["association_id"]]
        excluded_associations = [row for row in associations if not row["association_id"]]
        assert {row["family"] for row in associations} == {"d004", "d006"}
        assert all(row["association_id"].startswith("d007-assoc-") for row in successful_associations)
        assert all(row["precedence_version"] == "new_outcome_blind_temporal_association_v1" for row in associations)
        assert all(row["e4_session"] == "premarket" for row in successful_associations)
        assert all(len(row["e4_artifacts"]) == 2 for row in successful_associations)
        assert all(
            all(identity["version_config_identity"] for identity in row["source_milestone_identities"])
            for row in successful_associations
        )
        assert all(
            {identity["milestone"] for identity in row["source_milestone_identities"]}
            == ({"D004", "D005-E4"} if row["family"] == "d004" else {"D005-E4", "D006"})
            for row in successful_associations
        )
        assert excluded_associations == [{
            "authority_id": "D007_ASSOCIATION_IDENTITY_CLARIFICATION_V1",
            "precedence_version": "new_outcome_blind_temporal_association_v1",
            "family": "d006",
            "constituent_id": f"untouched-{name}",
            "association_id": None,
            "exclusion_reason": "lifecycle_ineligible_block",
            "constituent_event_at": None,
            "constituent_artifact": successful_associations[-1]["constituent_artifact"],
        }]
        d006_exclusions = result.package.tables["exclusions.parquet"]
        d006_exclusions = d006_exclusions.loc[
            d006_exclusions["object_id"] == f"untouched-{name}"
        ]
        assert len(d006_exclusions) == 1
        assert d006_exclusions.iloc[0]["first_failure"] == "lifecycle_ineligible_block"
        assert set(result.result["redundancy"]["interaction_ablations"]) == {
            "aligned_d005_context", "after_d004_manipulation", "frozen_liquidity_sweep",
            "refinement_confirmation", "d006_rejection_block", "against_d005_context_negative_control",
        }
        for name, ablation in result.result["statistics"]["interaction_ablations"].items():
            expected_cohort = tuple(sorted(interactions.loc[
                (interactions["interaction_name"] == name)
                & interactions["paired_difference"].notna(),
                "range_id",
            ]))
            assert ablation["identical_cohort"] == expected_cohort
        assert result.result["redundancy"]["interaction_ablations"]["against_d005_context_negative_control"] == "NOT_APPLICABLE_NEGATIVE_CONTROL"
        redundancy = result.package.tables["redundancy_audit.parquet"]
        context_redundancy = redundancy.loc[redundancy["feature"] == "d005_context"].iloc[0]
        assert context_redundancy["time_association_count"] == 0
        assert context_redundancy["first_failure"] == "missing_constituent"
        assert (redundancy["time_association_denominator"] >= redundancy["price_overlap_denominator"]).all()
        missing_price = redundancy["price_overlap_denominator"] < redundancy["time_association_denominator"]
        assert (redundancy.loc[missing_price, "price_audit_state"] == "price_not_available").all()
        assert (redundancy.loc[~missing_price, "price_audit_state"] == "evaluated").all()
        assert "price_not_available" in set(redundancy["price_audit_state"])
        run_manifest = result.package.json_objects["run_manifest.json"]
        assert run_manifest["association_authority"] == "D007_ASSOCIATION_IDENTITY_CLARIFICATION_V1"
        assert source_audit["contract_identities"]["association_module_sha256"]
        assert source_audit["upstream_artifacts"]
        assert all(item["projected_columns"] for item in source_audit["upstream_artifacts"])
        assert result.result["adequacy"]["status"] == "SAMPLE_INADEQUATE"
        assert result.result["disposition"] == "INSUFFICIENT_EVIDENCE"


def test_volatility_stratum_uses_only_prior_complete_named_days() -> None:
    bars: list[SimpleNamespace] = []
    named_days = pd.date_range("2024-01-02", periods=23, freq="D")
    for position, day in enumerate(named_days):
        local_start = pd.Timestamp(day.date(), tz="America/New_York") - pd.Timedelta(hours=6)
        day_range = 5.0 if position == 21 else 10.0
        for stamp in pd.date_range(local_start, periods=276, freq="5min"):
            bars.append(SimpleNamespace(available_at=stamp.tz_convert("UTC"), high=100.0 + day_range, low=100.0))
    before = _volatility_buckets(tuple(bars))
    target = str(named_days[-1].date())
    assert before[target] == "low"

    mutated = [
        SimpleNamespace(available_at=bar.available_at, high=(10_000.0 if str(named_days[-1].date()) == str(named_trading_date(bar.available_at)) else bar.high), low=bar.low)
        for bar in bars
    ]
    assert _volatility_buckets(tuple(mutated))[target] == before[target]


def test_geometry_decision_requires_movement_year_and_direction_stability() -> None:
    adjusted = {
        "geometry_touch_incidence": {"n": 200, "risk_difference": 0.2, "q_value": 0.01},
        "geometry_time_to_touch": {"n": 200, "mean": 1.0, "ci_lower": 0.2, "q_value": 0.01},
        "geometry_directional_movement": {"n": 200, "mean": 0.1, "ci_lower": 0.0, "q_value": 0.9},
    }
    bootstrap = {
        "geometry_touch_incidence": {"ci_lower": 0.1},
        "geometry_time_to_touch": {"ci_lower": 0.1},
        "geometry_directional_movement": {"ci_lower": -0.1},
    }
    split = {
        "temporal": {"passed": True},
        "direction": {"passed": True},
        "yearly": {year: {"n": 2, "mean": 0.0, "ci_upper": 0.1} for year in (2022, 2023, 2024, 2025)},
        "directions": {direction: {"n": 2, "mean": 0.0, "ci_upper": 0.1} for direction in ("bullish", "bearish")},
    }
    stability = {
        "geometry_touch_incidence": split,
        "geometry_time_to_touch": split,
        "geometry_directional_movement": split,
    }
    assert geometry_candidate_passes(adjusted=adjusted, bootstrap=bootstrap, stability=stability)
    failed = {**split, "yearly": {**split["yearly"], 2025: {"n": 2, "mean": -1.0, "ci_upper": -0.01}}}
    assert not geometry_candidate_passes(
        adjusted=adjusted,
        bootstrap=bootstrap,
        stability={**stability, "geometry_directional_movement": failed},
    )
    failed_direction = {**split, "directions": {**split["directions"], "bearish": {"n": 2, "mean": -1.0, "ci_upper": -0.01}}}
    assert not geometry_candidate_passes(
        adjusted=adjusted,
        bootstrap=bootstrap,
        stability={**stability, "geometry_directional_movement": failed_direction},
    )
