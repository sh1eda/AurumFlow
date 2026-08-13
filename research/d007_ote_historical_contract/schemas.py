"""Outcome-blind, exact future artifact membership and table schemas."""

from __future__ import annotations

from hashlib import sha256
import json
from types import MappingProxyType


JSON_ARTIFACTS = (
    "aggregate_audit.json",
    "artifact_manifest.json",
    "contract_snapshot.json",
    "run_manifest.json",
    "source_audit.json",
    "statistical_validation.json",
    "summary.json",
    "upstream_audit.json",
)
REPORT_ARTIFACT = "D007_OTE_HISTORICAL_RESEARCH_REPORT.md"


def _field(name: str, logical_type: str, nullable: bool = False) -> tuple[str, str, bool]:
    return name, logical_type, nullable


_TABLE_SCHEMAS = {
    "control_matches.parquet": (
        _field("control_family", "string"),
        _field("treatment_range_id", "string"),
        _field("control_id", "string", True),
        _field("treatment_event_at", "timestamp_utc"),
        _field("control_event_at", "timestamp_utc", True),
        _field("matched", "bool"),
        _field("first_failure", "string", True),
    ),
    "dedup_exclusions.parquet": (
        _field("range_id", "string"),
        _field("upstream_event_id", "string"),
        _field("geometry_id", "string"),
        _field("exclusion_reason", "string"),
        _field("retained_range_id", "string", True),
    ),
    "exclusions.parquet": (
        _field("object_id", "string"),
        _field("stage", "string"),
        _field("first_failure", "string"),
        _field("available_at", "timestamp_utc", True),
    ),
    "geometry_comparisons.parquet": (
        _field("comparison", "string"),
        _field("metric", "string"),
        _field("n", "int64"),
        _field("estimate", "float64", True),
        _field("p_value", "float64", True),
        _field("q_value", "float64", True),
        _field("status", "string"),
    ),
    "interaction_pairs.parquet": (
        _field("interaction_name", "string"),
        _field("range_id", "string"),
        _field("evidence_id", "string", True),
        _field("evidence_available_at", "timestamp_utc", True),
        _field("eligible", "bool"),
        _field("paired_difference", "float64", True),
        _field("first_failure", "string", True),
    ),
    "lifecycle_records.parquet": (
        _field("range_id", "string"),
        _field("status", "string"),
        _field("available_at", "timestamp_utc"),
        _field("first_touch_at", "timestamp_utc", True),
        _field("invalidated_at", "timestamp_utc", True),
        _field("expired_at", "timestamp_utc", True),
        _field("expiry_deadline", "timestamp_utc"),
        _field("touch_count", "int64"),
        _field("repeated_touch_count", "int64"),
        _field("lifecycle_eligible", "bool"),
    ),
    "ote_ranges.parquet": (
        _field("range_id", "string"),
        _field("upstream_event_id", "string"),
        _field("geometry_id", "string"),
        _field("direction", "int8"),
        _field("origin_price", "float64"),
        _field("endpoint_price", "float64"),
        _field("origin_at", "timestamp_utc"),
        _field("origin_available_at", "timestamp_utc"),
        _field("endpoint_at", "timestamp_utc"),
        _field("range_available_at", "timestamp_utc"),
        _field("proximal", "float64"),
        _field("reference", "float64"),
        _field("distal", "float64"),
        _field("equilibrium", "float64"),
        _field("zone_low", "float64"),
        _field("zone_high", "float64"),
        _field("invalidation_price", "float64"),
        _field("expiry_deadline", "timestamp_utc"),
        _field("source_bar_ids", "list<string>"),
        _field("preavailability_interaction", "bool"),
        _field("overlap_group_id", "string", True),
        _field("parent_range_id", "string", True),
        _field("named_trading_date", "date32"),
        _field("validation_year", "int16"),
        _field("session", "string"),
        _field("causal_volatility_bucket", "string"),
    ),
    "primary_pairs.parquet": (
        _field("treatment_range_id", "string"),
        _field("control_id", "string"),
        _field("direction", "int8"),
        _field("named_trading_date", "date32"),
        _field("treatment_event_at", "timestamp_utc"),
        _field("control_event_at", "timestamp_utc"),
        _field("treatment_reference_close", "float64"),
        _field("treatment_endpoint_close", "float64"),
        _field("treatment_movement", "float64"),
        _field("control_reference_close", "float64"),
        _field("control_endpoint_close", "float64"),
        _field("control_movement", "float64"),
        _field("paired_difference", "float64"),
        _field("endpoint_complete", "bool"),
    ),
    "primary_treatments.parquet": (
        _field("range_id", "string"),
        _field("first_touch_at", "timestamp_utc"),
        _field("reference_close", "float64"),
        _field("endpoint_at", "timestamp_utc"),
        _field("endpoint_close", "float64"),
        _field("direction_aligned_movement", "float64"),
        _field("endpoint_complete", "bool"),
        _field("first_failure", "string", True),
    ),
    "redundancy_audit.parquet": (
        _field("feature", "string"),
        _field("time_association_count", "int64"),
        _field("time_association_denominator", "int64"),
        _field("time_association_rate", "float64", True),
        _field("price_overlap_count", "int64"),
        _field("price_overlap_denominator", "int64"),
        _field("price_overlap_rate", "float64", True),
        _field("price_audit_state", "string"),
        _field("median_signed_minutes", "float64", True),
        _field("first_failure", "string", True),
        _field("incremental_status", "string"),
    ),
    "sensitivity_705.parquet": (
        _field("range_id", "string"),
        _field("upstream_event_id", "string"),
        _field("first_touch_at", "timestamp_utc", True),
        _field("touch_count", "int64"),
        _field("time_to_touch_minutes", "float64", True),
        _field("direction_aligned_movement", "float64", True),
        _field("endpoint_complete", "bool"),
    ),
    "stability_summaries.parquet": (
        _field("split_family", "string"),
        _field("split_value", "string"),
        _field("n", "int64"),
        _field("mean", "float64", True),
        _field("ci_lower", "float64", True),
        _field("ci_upper", "float64", True),
        _field("required_sign", "bool", True),
        _field("status", "string"),
    ),
}

TABLE_SCHEMAS = MappingProxyType(_TABLE_SCHEMAS)
PARQUET_ARTIFACTS = tuple(sorted(TABLE_SCHEMAS))
ALL_ARTIFACTS = tuple(sorted((*JSON_ARTIFACTS, REPORT_ARTIFACT, *PARQUET_ARTIFACTS)))


def schema_fingerprint() -> str:
    payload = {
        name: [list(field) for field in fields]
        for name, fields in sorted(TABLE_SCHEMAS.items())
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


__all__ = [
    "ALL_ARTIFACTS",
    "JSON_ARTIFACTS",
    "PARQUET_ARTIFACTS",
    "REPORT_ARTIFACT",
    "TABLE_SCHEMAS",
    "schema_fingerprint",
]
