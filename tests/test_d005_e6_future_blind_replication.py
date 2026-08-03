from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import ast
import json
import os
from pathlib import Path

import pytest

from research.d005_e6_future_blind_replication import boundary
from research.d005_e6_future_blind_replication.config import (
    EARLIEST_PROPOSED_EXECUTION,
    E6ReadinessConfig,
    FROZEN_TRACKED_SHA256,
    FixedIntervalPolicy,
    PROPOSED_END_EXCLUSIVE,
    PROPOSED_START,
    SPEC_PATH,
    SPEC_SHA256,
)
from research.d005_e6_future_blind_replication.planning import sample_size_plan
from research.d005_e6_future_blind_replication.readiness import (
    build_readiness_report,
    sha256_file,
    verify_frozen_fingerprints,
    verify_no_scientific_execution_path,
)
from research.d005_e6_future_blind_replication.schemas import (
    AGGREGATE_AUDIT_FIELDS,
    COUNT_FIELDS,
    DECISION_PATH,
    DENOMINATOR_KEYS,
    PRIMARY_FAIL_STATUS,
    PRIMARY_PASS_STATUS,
    PRIMARY_RULE_CHECKS,
    REQUIRED_ENDPOINT_KEYS,
    SchemaViolation,
    aggregate_audit_schema,
    reconcile_aggregate_counts,
    reporting_contract_schema,
    validate_reporting_contract,
)


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "research/d005_e6_future_blind_replication"


def _write_boundary_fixture(root: Path) -> Path:
    manifest = root / boundary.E4_RUN_MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "accepted_interval": {
                    "start": "2026-01-01T00:00:00Z",
                    "end_exclusive": "2026-07-29T00:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )
    parquet = (
        root
        / "data/canonical/xauusd_ticks_d003-v2/year=2026/month=07"
        / "xauusd_ticks_2026-07-28.parquet"
    )
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"must-remain-opaque")
    return parquet


def _denominators() -> dict[str, str]:
    return {key: f"preregistered denominator for {key}" for key in DENOMINATOR_KEYS}


def _valid_audit() -> dict[str, object]:
    payload: dict[str, object] = {field: 0 for field in COUNT_FIELDS}
    payload.update(
        {
            "total_structural_primary_cohort_count": 120,
            "excluded_interval_boundary_count": 5,
            "excluded_duplicate_identity_count": 3,
            "excluded_causal_observability_failure_count": 2,
            "excluded_incomplete_sessions_count": 10,
            "structurally_60m_eligible_count": 100,
            "excluded_missing_bars_count": 3,
            "excluded_incomplete_endpoint_count": 2,
            "endpoint_complete_primary_count": 95,
            "expected_eligible_sequence_id_count": 100,
            "observed_outcome_sequence_id_count": 95,
            "expected_observed_sequence_ids_equal": False,
            "required_endpoint_coverage_complete": True,
            "bearish_count": 48,
            "bullish_count": 45,
            "direction_unknown_or_rejected_count": 2,
            "refinement_paired_count": 80,
            "zero_lag_refinement_pair_count": 10,
            "distinct_displacement_source_timestamp_count": 90,
            "distinct_refinement_source_timestamp_count": 75,
            "distinct_displacement_refinement_source_timestamp_pair_count": 78,
            "denominator_definitions": _denominators(),
            "required_endpoint_complete_counts": {
                key: (80 if key.startswith("refinement_") else 95)
                for key in REQUIRED_ENDPOINT_KEYS
            },
        }
    )
    assert set(payload) == AGGREGATE_AUDIT_FIELDS
    return payload


def test_metadata_audit_never_opens_parquet_or_decodes_market_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parquet = _write_boundary_fixture(tmp_path)
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        if path.suffix.lower() == ".parquet":
            raise AssertionError(f"Parquet was opened: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    audit = boundary.audit_blind_boundary(tmp_path)
    assert audit["parquet_payload_opened"] is False
    assert audit["market_row_decoded"] is False
    assert audit["future_anchor_count_observed"] is False
    assert audit["later_local_market_file_metadata"] == []
    with pytest.raises(Exception, match="Parquet"):
        sha256_file(parquet)


def test_no_anchor_outcome_or_statistics_execution_module_exists_or_imports() -> None:
    forbidden_names = {
        "loader.py",
        "anchors.py",
        "outcomes.py",
        "statistics.py",
        "reporting.py",
        "execution.py",
    }
    assert not ({path.name for path in PACKAGE.glob("*.py")} & forbidden_names)
    result = verify_no_scientific_execution_path(PACKAGE)
    assert result == {"verified": True, "violations": []}
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any("anchor_inputs" in module or "outcomes" in module for module in imports)


def test_boundary_uncertainty_fails_closed_and_known_dates_are_rejected(tmp_path: Path) -> None:
    _write_boundary_fixture(tmp_path)
    audit = boundary.audit_blind_boundary(tmp_path)
    assert audit["latest_exact_outcome_timestamp"] == "UNPROVEN"
    assert audit["earliest_proven_blind_start"] == "UNPROVEN"
    assert audit["blind_boundary_proven"] is False
    for value in (
        "2026-01-01T00:00:00Z",
        "2026-07-28T23:59:59Z",
        "2026-07-29T00:00:00Z",
        PROPOSED_START,
    ):
        assert boundary.candidate_blind_start_is_proven(value) is False


def test_boundary_audit_rejects_symlinked_metadata_and_parquet_paths(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    parquet = _write_boundary_fixture(root)
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"opaque")
    parquet.unlink()
    parquet.symlink_to(outside)
    with pytest.raises(boundary.BoundaryAuditError, match="symlink"):
        boundary.audit_blind_boundary(root)

    parquet.unlink()
    parquet.write_bytes(b"opaque")
    manifest = root / boundary.E4_RUN_MANIFEST
    outside_manifest = tmp_path / "outside.json"
    outside_manifest.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(outside_manifest)
    with pytest.raises(boundary.BoundaryAuditError, match="symlink"):
        boundary.audit_blind_boundary(root)


def test_fixed_interval_policy_is_exact_deterministic_and_unregistered() -> None:
    first = FixedIntervalPolicy()
    second = FixedIntervalPolicy()
    first.validate()
    second.validate()
    assert first == second
    assert first.anchor_start == PROPOSED_START
    assert first.anchor_end_exclusive == PROPOSED_END_EXCLUSIVE
    assert first.earliest_execution == EARLIEST_PROPOSED_EXECUTION
    assert first.endpoint_buffer_hours == 24
    assert first.registration_status == "PROPOSED_UNREGISTERED"
    with pytest.raises(ValueError, match="immutable"):
        replace(first, anchor_end_exclusive="2032-01-01T00:00:00Z").validate()


def test_early_execution_and_endpoint_buffer_are_enforced() -> None:
    policy = FixedIntervalPolicy()
    with pytest.raises(ValueError, match="endpoint buffer"):
        replace(policy, earliest_execution=PROPOSED_END_EXCLUSIVE).validate()
    assert datetime.fromisoformat(
        EARLIEST_PROPOSED_EXECUTION.replace("Z", "+00:00")
    ) > datetime.fromisoformat(PROPOSED_END_EXCLUSIVE.replace("Z", "+00:00"))


def test_sample_planning_uses_only_frozen_aggregates_and_preserves_thresholds() -> None:
    plan = sample_size_plan()
    assert plan["historical_adequacy_thresholds"] == {
        "minimum_total_primary": 1000,
        "minimum_bearish": 200,
        "minimum_bullish": 200,
        "complete_required_endpoint_coverage": True,
    }
    assert plan["known_aggregate_inputs"] == {
        "historical_primary_n": 1778,
        "historical_calendar_years": 4,
        "e4_endpoint_complete_n": 156,
        "e4_calendar_days": 209,
    }
    assert [row["name"] for row in plan["scenarios"]] == [
        "pessimistic",
        "central",
        "optimistic",
    ]
    assert plan["future_observation_used"] is False
    assert plan["decision_rule"] is False


def test_aggregate_audit_schema_contains_every_preregistered_field() -> None:
    schema = aggregate_audit_schema()
    required = set(schema["required_fields"])
    assert required == AGGREGATE_AUDIT_FIELDS
    for field in (
        "total_structural_primary_cohort_count",
        "structurally_60m_eligible_count",
        "endpoint_complete_primary_count",
        "excluded_incomplete_endpoint_count",
        "excluded_missing_bars_count",
        "excluded_incomplete_sessions_count",
        "excluded_causal_observability_failure_count",
        "excluded_duplicate_identity_count",
        "excluded_interval_boundary_count",
        "expected_eligible_sequence_id_count",
        "observed_outcome_sequence_id_count",
        "expected_observed_sequence_ids_equal",
        "required_endpoint_coverage_complete",
        "bearish_count",
        "bullish_count",
        "direction_unknown_or_rejected_count",
        "refinement_paired_count",
        "zero_lag_refinement_pair_count",
        "distinct_displacement_source_timestamp_count",
        "distinct_refinement_source_timestamp_count",
        "distinct_displacement_refinement_source_timestamp_pair_count",
        "denominator_definitions",
        "required_endpoint_complete_counts",
    ):
        assert field in required
    assert schema["additional_fields_permitted"] is False
    assert schema["event_level_fields_permitted"] is False


def test_aggregate_count_reconciliation_is_deterministic_and_fail_closed() -> None:
    payload = _valid_audit()
    assert reconcile_aggregate_counts(payload)
    assert reconcile_aggregate_counts(dict(payload))
    broken = dict(payload)
    broken["endpoint_complete_primary_count"] = 94
    with pytest.raises(SchemaViolation, match="endpoint-complete"):
        reconcile_aggregate_counts(broken)
    extra = dict(payload)
    extra["unregistered"] = 1
    with pytest.raises(SchemaViolation, match="exact preregistered"):
        reconcile_aggregate_counts(extra)


def test_descriptive_labeling_is_mandatory_after_adequacy_failure() -> None:
    report = {
        "decision_path": list(DECISION_PATH),
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_INADEQUATE",
        "primary_status": "NOT_EVALUATED",
        "scientific_decision_authorized": False,
        "all_metrics_descriptive_only": True,
        "replication_evidence_claim_permitted": False,
        "scientific_metrics": [
            {
                "name": "example_metric",
                "value": 1.25,
                "qualification": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
            }
        ],
    }
    assert validate_reporting_contract(report)
    for field in (
        "scientific_decision_authorized",
        "all_metrics_descriptive_only",
        "replication_evidence_claim_permitted",
    ):
        broken = dict(report)
        broken[field] = not report[field]
        with pytest.raises(SchemaViolation, match=field):
            validate_reporting_contract(broken)
    broken = dict(report)
    broken["scientific_metrics"] = [{"name": "example_metric", "value": 1.25}]
    with pytest.raises(SchemaViolation, match="explicitly descriptive"):
        validate_reporting_contract(broken)


@pytest.mark.parametrize(
    "forbidden",
    [
        "a_b_c_classification",
        "trade_count",
        "pnl",
        "profit_factor",
        "return_metric",
        "stop_distance",
        "target_price",
        "fill_price",
        "position_sizing",
        "fees",
        "slippage",
    ],
)
def test_classification_and_trade_fields_cannot_be_emitted(forbidden: str) -> None:
    with pytest.raises(SchemaViolation, match="forbidden reporting field"):
        validate_reporting_contract({forbidden: 1})
    schema_text = json.dumps(reporting_contract_schema(), sort_keys=True).lower()
    assert "a_b_c" not in schema_text
    assert "pnl" not in schema_text

    inadequate = {
        "decision_path": list(DECISION_PATH),
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_INADEQUATE",
        "primary_status": "NOT_EVALUATED",
        "scientific_decision_authorized": False,
        "all_metrics_descriptive_only": True,
        "replication_evidence_claim_permitted": False,
        "scientific_metrics": [
            {
                "name": forbidden,
                "value": 1.0,
                "qualification": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
            }
        ],
    }
    with pytest.raises(SchemaViolation, match="forbidden reporting name"):
        validate_reporting_contract(inadequate)

    adequate = {
        "decision_path": list(DECISION_PATH),
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_ADEQUATE",
        "primary_rule_registered": True,
        "registered_primary_checks": {name: True for name in PRIMARY_RULE_CHECKS},
        "primary_status": PRIMARY_PASS_STATUS,
        "secondary_diagnostics": [
            {
                "name": forbidden,
                "value": 1.0,
                "qualification": "SECONDARY_DIAGNOSTIC_NON_PRIMARY",
            }
        ],
    }
    with pytest.raises(SchemaViolation, match="forbidden reporting name"):
        validate_reporting_contract(adequate)


def test_integrity_failure_emits_safe_audit_fields_only() -> None:
    assert validate_reporting_contract(
        {
            "decision_path": list(DECISION_PATH),
            "integrity_status": "REPRODUCIBILITY_DEFECT",
            "safe_audit_fields": {
                "fingerprint_mismatches": ["protected.py"],
                "integrity_failure_reasons": ["HASH_MISMATCH"],
                "unauthorized_outcome_access_detected": False,
                "parquet_payload_opened": False,
                "market_row_decoded": False,
            },
        }
    )
    with pytest.raises(SchemaViolation, match="safe audit"):
        validate_reporting_contract(
            {
                "decision_path": list(DECISION_PATH),
                "integrity_status": "REPRODUCIBILITY_DEFECT",
                "primary_status": "NOT_EVALUATED",
            }
        )
    with pytest.raises(SchemaViolation, match="exact preregistered"):
        validate_reporting_contract(
            {
                "decision_path": list(DECISION_PATH),
                "integrity_status": "REPRODUCIBILITY_DEFECT",
                "safe_audit_fields": {"scientific_metrics": []},
            }
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_reporting_contract_rejects_non_finite_numerical_values(value: float) -> None:
    report = {
        "decision_path": list(DECISION_PATH),
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_INADEQUATE",
        "primary_status": "NOT_EVALUATED",
        "scientific_decision_authorized": False,
        "all_metrics_descriptive_only": True,
        "replication_evidence_claim_permitted": False,
        "scientific_metrics": [
            {
                "name": "example_metric",
                "value": value,
                "qualification": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
            }
        ],
    }
    with pytest.raises(SchemaViolation, match="explicitly descriptive"):
        validate_reporting_contract(report)


def test_exact_non_temporal_primary_pass_fail_rule_is_deterministic() -> None:
    checks = {name: True for name in PRIMARY_RULE_CHECKS}
    report = {
        "decision_path": list(DECISION_PATH),
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_ADEQUATE",
        "primary_rule_registered": True,
        "registered_primary_checks": checks,
        "primary_status": PRIMARY_PASS_STATUS,
        "secondary_diagnostics": [],
    }
    assert validate_reporting_contract(report)
    failed = dict(report)
    failed_checks = dict(checks)
    failed_checks["mean_positive"] = False
    failed["registered_primary_checks"] = failed_checks
    failed["primary_status"] = PRIMARY_FAIL_STATUS
    assert validate_reporting_contract(failed)
    wrong = dict(failed)
    wrong["primary_status"] = PRIMARY_PASS_STATUS
    with pytest.raises(SchemaViolation, match="does not match"):
        validate_reporting_contract(wrong)


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"decision_path": list(DECISION_PATH), "foo": 1},
        {
            "decision_path": list(DECISION_PATH),
            "integrity_status": "UNKNOWN",
        },
        {
            "decision_path": list(DECISION_PATH),
            "integrity_status": "INTEGRITY_VERIFIED",
            "adequacy_status": "UNKNOWN",
        },
    ],
)
def test_reporting_contract_rejects_missing_unknown_or_invalid_gate_fields(
    invalid: dict[str, object],
) -> None:
    with pytest.raises(SchemaViolation):
        validate_reporting_contract(invalid)


def test_configuration_fingerprint_is_stable_across_runtime_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = E6ReadinessConfig()
    config.validate()
    expected = config.fingerprint()
    previous = Path.cwd()
    monkeypatch.setenv("USER", "different-user")
    monkeypatch.setenv("HOSTNAME", "different-machine")
    monkeypatch.setenv("D005_E6_RUNTIME_NOISE", "different-environment")
    os.chdir(tmp_path)
    try:
        assert E6ReadinessConfig().fingerprint() == expected
    finally:
        os.chdir(previous)
    assert config.snapshot()["specification"] == {
        "path": SPEC_PATH,
        "sha256": SPEC_SHA256,
    }
    assert not any(str(tmp_path) in str(value) for value in config.snapshot().values())


def test_e4_e5_tracked_and_protected_aggregate_fingerprints_are_unchanged() -> None:
    result = verify_frozen_fingerprints(ROOT)
    assert result["verified"] is True
    assert result["mismatches"] == []
    for path in (
        "research/context_engine/engine.py",
        "research/d005_e1_context_engine_empirical/config.py",
        "research/d005_e2_reaction_anchor_diagnostic/reconstruction.py",
        "research/d005_e3_early_context_anchor_study/outcomes.py",
        "research/d005_e4_1h_5m_reversal_replication/analysis.py",
        "research/manipulation_0830_0900/bars.py",
        "scripts/build_dukascopy_canonical.py",
        "scripts/validate_canonical_dataset.py",
    ):
        assert path in FROZEN_TRACKED_SHA256
    assert result["registered_file_total"] == len(FROZEN_TRACKED_SHA256) + 3


def test_readiness_report_never_authorizes_or_creates_scientific_output() -> None:
    forbidden_output = ROOT / "research_outputs/D005_E6_FUTURE_BLIND_REPLICATION"
    existed_before = forbidden_output.exists()
    report = build_readiness_report(
        ROOT,
        as_of=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    assert report["blind_boundary"]["blind_boundary_proven"] is False
    assert report["interval_registered"] is False
    assert report["elapsed_calendar_requirement_met"] is False
    assert report["metadata_file_coverage_verified"] is False
    assert report["scientific_execution_authorized"] is False
    assert report["scientific_output_directory_created"] is False
    assert report["future_anchor_count_observed"] is False
    assert report["future_outcome_calculated"] is False
    assert report["production_recommendation"] == "continue research only"
    assert forbidden_output.exists() is existed_before
    assert "absolute" not in report["configuration_fingerprint"]
