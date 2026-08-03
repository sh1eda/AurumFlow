"""Aggregate-only audit and reporting contracts for a future implementation."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any, Final


COUNT_FIELDS: Final = frozenset(
    {
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
        "bearish_count",
        "bullish_count",
        "direction_unknown_or_rejected_count",
        "refinement_paired_count",
        "zero_lag_refinement_pair_count",
        "distinct_displacement_source_timestamp_count",
        "distinct_refinement_source_timestamp_count",
        "distinct_displacement_refinement_source_timestamp_pair_count",
    }
)
BOOLEAN_FIELDS: Final = frozenset(
    {"expected_observed_sequence_ids_equal", "required_endpoint_coverage_complete"}
)
DENOMINATOR_KEYS: Final = frozenset(
    {
        "total_structural_primary_cohort",
        "structurally_60m_eligible",
        "endpoint_complete_primary",
        "direction_counts",
        "refinement_pairs",
        "displacement_distinct_timestamps",
        "refinement_distinct_timestamps",
        "source_timestamp_pairs",
        "required_endpoint_counts",
    }
)
REQUIRED_ENDPOINT_KEYS: Final = frozenset(
    {
        "displacement_5m",
        "displacement_15m",
        "displacement_30m",
        "displacement_60m",
        "displacement_120m",
        "displacement_new_york_noon",
        "displacement_new_york_1700",
        "refinement_5m",
        "refinement_15m",
        "refinement_30m",
        "refinement_60m",
        "refinement_120m",
        "refinement_new_york_noon",
        "refinement_new_york_1700",
    }
)
AGGREGATE_AUDIT_FIELDS: Final = COUNT_FIELDS | BOOLEAN_FIELDS | {
    "denominator_definitions",
    "required_endpoint_complete_counts",
}
FORBIDDEN_REPORT_KEY_FRAGMENTS: Final = (
    "a_b_c",
    "abc_classification",
    "trade",
    "pnl",
    "profit_factor",
    "expectancy",
    "stop",
    "target",
    "fill",
    "sizing",
    "fee",
    "slippage",
    "return",
)
PRIMARY_RULE_CHECKS: Final = frozenset(
    {
        "mean_positive",
        "student_t_interval_lower_positive",
        "direction_intervals_not_entirely_below_zero",
        "never_later_confirmed_share_and_mean",
        "deduplicated_effect_sign_positive",
        "causal_availability_closed_bar_direction_invariants",
        "mean_mfe_to_mean_mae_at_least_0_75",
        "median_mfe_mae_at_least_0_50",
        "mean_positive_after_largest_1pct_removed",
        "two_sided_1pct_trimmed_mean_positive",
    }
)
PRIMARY_PASS_STATUS: Final = "REGISTERED_NON_TEMPORAL_CHECKS_PASS"
PRIMARY_FAIL_STATUS: Final = "REGISTERED_NON_TEMPORAL_CHECKS_FAIL"
DECISION_PATH: Final = (
    "Integrity",
    "Adequacy",
    "Primary Evaluation",
    "Secondary Diagnostics",
    "Separate temporal classification only if preregistered",
)
SAFE_AUDIT_FIELD_NAMES: Final = frozenset(
    {
        "fingerprint_mismatches",
        "integrity_failure_reasons",
        "unauthorized_outcome_access_detected",
        "parquet_payload_opened",
        "market_row_decoded",
    }
)


class SchemaViolation(ValueError):
    """Raised whenever an aggregate or reporting contract fails closed."""


def aggregate_audit_schema() -> dict[str, object]:
    return {
        "required_fields": sorted(AGGREGATE_AUDIT_FIELDS),
        "count_fields": sorted(COUNT_FIELDS),
        "boolean_fields": sorted(BOOLEAN_FIELDS),
        "denominator_keys": sorted(DENOMINATOR_KEYS),
        "required_endpoint_keys": sorted(REQUIRED_ENDPOINT_KEYS),
        "additional_fields_permitted": False,
        "event_level_fields_permitted": False,
    }


def reconcile_aggregate_counts(payload: Mapping[str, Any]) -> bool:
    if set(payload) != AGGREGATE_AUDIT_FIELDS:
        raise SchemaViolation("aggregate audit must contain the exact preregistered field set")
    for field in COUNT_FIELDS:
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SchemaViolation(f"{field} must be a non-negative integer")
    equality = payload["expected_observed_sequence_ids_equal"]
    if not isinstance(equality, bool):
        raise SchemaViolation("expected-versus-observed equality must be boolean")
    endpoint_coverage = payload["required_endpoint_coverage_complete"]
    if not isinstance(endpoint_coverage, bool):
        raise SchemaViolation("required endpoint coverage result must be boolean")
    denominators = payload["denominator_definitions"]
    if not isinstance(denominators, Mapping) or set(denominators) != DENOMINATOR_KEYS:
        raise SchemaViolation("all exact denominator definitions are required")
    if not all(isinstance(value, str) and value.strip() for value in denominators.values()):
        raise SchemaViolation("denominator definitions must be non-empty strings")

    total = payload["total_structural_primary_cohort_count"]
    structural = payload["structurally_60m_eligible_count"]
    endpoint = payload["endpoint_complete_primary_count"]
    structural_exclusions = sum(
        payload[field]
        for field in (
            "excluded_interval_boundary_count",
            "excluded_duplicate_identity_count",
            "excluded_causal_observability_failure_count",
            "excluded_incomplete_sessions_count",
        )
    )
    endpoint_exclusions = (
        payload["excluded_missing_bars_count"]
        + payload["excluded_incomplete_endpoint_count"]
    )
    if structural != total - structural_exclusions:
        raise SchemaViolation("structural cohort reconciliation failed")
    if endpoint != structural - endpoint_exclusions:
        raise SchemaViolation("endpoint-complete reconciliation failed")
    if payload["expected_eligible_sequence_id_count"] != structural:
        raise SchemaViolation("expected eligible ID count must equal structural eligibility")
    if payload["observed_outcome_sequence_id_count"] != endpoint:
        raise SchemaViolation("observed outcome ID count must equal endpoint completeness")
    observed_equality = (
        payload["expected_eligible_sequence_id_count"]
        == payload["observed_outcome_sequence_id_count"]
    )
    if equality is not observed_equality:
        raise SchemaViolation("expected-versus-observed equality result is inconsistent")
    if (
        payload["bearish_count"]
        + payload["bullish_count"]
        + payload["direction_unknown_or_rejected_count"]
        != endpoint
    ):
        raise SchemaViolation("direction counts do not reconcile to endpoint completeness")
    if not (
        payload["zero_lag_refinement_pair_count"]
        <= payload["refinement_paired_count"]
        <= endpoint
    ):
        raise SchemaViolation("refinement-pair counts violate their denominator")
    if payload["distinct_displacement_source_timestamp_count"] > endpoint:
        raise SchemaViolation("displacement timestamp count exceeds endpoint denominator")
    for field in (
        "distinct_refinement_source_timestamp_count",
        "distinct_displacement_refinement_source_timestamp_pair_count",
    ):
        if payload[field] > payload["refinement_paired_count"]:
            raise SchemaViolation(f"{field} exceeds the paired-refinement denominator")
    endpoint_counts = payload["required_endpoint_complete_counts"]
    if not isinstance(endpoint_counts, Mapping) or set(endpoint_counts) != REQUIRED_ENDPOINT_KEYS:
        raise SchemaViolation("all exact required endpoint counts are mandatory")
    if not all(
        not isinstance(value, bool) and isinstance(value, int) and value >= 0
        for value in endpoint_counts.values()
    ):
        raise SchemaViolation("required endpoint counts must be non-negative integers")
    coverage_observed = all(
        value == (payload["refinement_paired_count"] if key.startswith("refinement_") else endpoint)
        for key, value in endpoint_counts.items()
    )
    if endpoint_coverage is not coverage_observed:
        raise SchemaViolation("required endpoint coverage result is inconsistent")
    return True


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in FORBIDDEN_REPORT_KEY_FRAGMENTS):
                raise SchemaViolation(f"forbidden reporting field: {key}")
            _reject_forbidden_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_forbidden_keys(item)


def _reject_forbidden_name(value: str) -> None:
    normalized = value.lower().replace("-", "_")
    if any(fragment in normalized for fragment in FORBIDDEN_REPORT_KEY_FRAGMENTS):
        raise SchemaViolation(f"forbidden reporting name: {value}")


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def validate_reporting_contract(payload: Mapping[str, Any]) -> bool:
    _reject_forbidden_keys(payload)
    integrity = payload.get("integrity_status")
    adequacy = payload.get("adequacy_status")
    if payload.get("decision_path") != list(DECISION_PATH):
        raise SchemaViolation("the immutable decision path is required")
    if integrity not in {"INTEGRITY_VERIFIED", "REPRODUCIBILITY_DEFECT"}:
        raise SchemaViolation("integrity status is missing or invalid")
    if integrity == "REPRODUCIBILITY_DEFECT":
        if set(payload) != {"decision_path", "integrity_status", "safe_audit_fields"}:
            raise SchemaViolation("integrity failure permits the exact safe audit fields only")
        safe_fields = payload["safe_audit_fields"]
        if not isinstance(safe_fields, Mapping) or set(safe_fields) != SAFE_AUDIT_FIELD_NAMES:
            raise SchemaViolation("the exact preregistered safe audit fields are required")
        if not all(
            isinstance(safe_fields[key], bool)
            for key in (
                "unauthorized_outcome_access_detected",
                "parquet_payload_opened",
                "market_row_decoded",
            )
        ):
            raise SchemaViolation("safe access audit fields must be boolean")
        for key in ("fingerprint_mismatches", "integrity_failure_reasons"):
            if not isinstance(safe_fields[key], list) or not all(
                isinstance(item, str) for item in safe_fields[key]
            ):
                raise SchemaViolation("safe integrity audit fields must be string lists")
        return True
    if adequacy not in {"INDEPENDENT_SAMPLE_INADEQUATE", "INDEPENDENT_SAMPLE_ADEQUATE"}:
        raise SchemaViolation("adequacy status is missing or invalid")
    if adequacy == "INDEPENDENT_SAMPLE_INADEQUATE":
        allowed = {
            "decision_path",
            "integrity_status",
            "adequacy_status",
            "primary_status",
            "scientific_decision_authorized",
            "all_metrics_descriptive_only",
            "replication_evidence_claim_permitted",
            "scientific_metrics",
        }
        if set(payload) != allowed:
            raise SchemaViolation("adequacy failure report field set is not exact")
        required = {
            "primary_status": "NOT_EVALUATED",
            "scientific_decision_authorized": False,
            "all_metrics_descriptive_only": True,
            "replication_evidence_claim_permitted": False,
        }
        for key, expected in required.items():
            if payload.get(key) != expected:
                raise SchemaViolation(f"adequacy failure requires {key}={expected!r}")
        metrics = payload.get("scientific_metrics", [])
        if not isinstance(metrics, list):
            raise SchemaViolation("scientific_metrics must be a list of qualified records")
        for record in metrics:
            if (
                not isinstance(record, Mapping)
                or set(record) != {"name", "value", "qualification"}
                or not isinstance(record.get("name"), str)
                or not _finite_number(record.get("value"))
                or record.get("qualification")
                != "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"
            ):
                raise SchemaViolation("every metric must be explicitly descriptive")
            _reject_forbidden_name(record["name"])
        return True
    if adequacy == "INDEPENDENT_SAMPLE_ADEQUATE":
        allowed = {
            "decision_path",
            "integrity_status",
            "adequacy_status",
            "primary_rule_registered",
            "registered_primary_checks",
            "primary_status",
            "secondary_diagnostics",
        }
        if set(payload) != allowed:
            raise SchemaViolation("adequate report field set is not exact")
        if payload.get("primary_rule_registered") is not True:
            raise SchemaViolation("adequacy cannot authorize primary evaluation without a rule")
        checks = payload.get("registered_primary_checks")
        if not isinstance(checks, Mapping) or set(checks) != PRIMARY_RULE_CHECKS:
            raise SchemaViolation("the exact ten registered primary checks are required")
        if not all(isinstance(value, bool) for value in checks.values()):
            raise SchemaViolation("registered primary check results must be boolean")
        expected_status = PRIMARY_PASS_STATUS if all(checks.values()) else PRIMARY_FAIL_STATUS
        if payload.get("primary_status") != expected_status:
            raise SchemaViolation("primary status does not match the exact registered rule")
        diagnostics = payload.get("secondary_diagnostics")
        if not isinstance(diagnostics, list):
            raise SchemaViolation("secondary diagnostics must be an aggregate list")
        for record in diagnostics:
            if (
                not isinstance(record, Mapping)
                or set(record) != {"name", "value", "qualification"}
                or not isinstance(record.get("name"), str)
                or not _finite_number(record.get("value"))
                or record.get("qualification") != "SECONDARY_DIAGNOSTIC_NON_PRIMARY"
            ):
                raise SchemaViolation("secondary diagnostics must remain explicitly non-primary")
            _reject_forbidden_name(record["name"])
    return True


def reporting_contract_schema() -> dict[str, object]:
    return {
        "decision_path": list(DECISION_PATH),
        "adequacy_failure": {
            "primary_status": "NOT_EVALUATED",
            "scientific_decision_authorized": False,
            "all_metrics_descriptive_only": True,
            "replication_evidence_claim_permitted": False,
            "metric_qualification": "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE",
        },
        "integrity_failure": "SAFE_AUDIT_FIELDS_ONLY",
        "adequacy_pass_primary_rule": {
            "required_checks": sorted(PRIMARY_RULE_CHECKS),
            "all_checks_true_status": PRIMARY_PASS_STATUS,
            "any_check_false_status": PRIMARY_FAIL_STATUS,
        },
        "additional_scientific_fields_permitted": False,
    }
