"""Fail-closed input and audit schemas for structural-only D006 work."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

import pandas as pd


class SchemaError(ValueError):
    """A data or audit integrity condition that must stop evaluation."""


BAR_FIELDS = ("open", "high", "low", "close", "available_at", "is_complete", "bar_id")
STRUCTURAL_DETECTOR_FIELDS = (
    "block_id",
    "definition_name",
    "direction",
    "timeframe",
    "source_bar_ids",
    "expansion_bar_id",
    "creation_timestamp",
    "confirmation_timestamp",
    "causal_availability",
    "distal",
    "proximal",
    "midpoint",
    "range",
    "normalized_range",
    "session",
    "trading_date",
    "context_keys",
    "preavailability_interaction",
    "overlap_group_id",
    "parent_block_id",
)
AGGREGATE_AUDIT_FIELDS = (
    "detected",
    "duplicate_id_excluded",
    "lifecycle_eligible",
    "endpoint_eligible",
    "endpoint_complete_count",
    "touched",
    "untouched",
    "invalidated",
    "mitigated",
    "expired",
    "active_censored",
    "overlapping",
    "nested",
    "bullish",
    "bearish",
    "preavailability_count",
    "endpoint_coverage_complete",
    "expected_primary_pairs",
    "observed_primary_pairs",
    "controls_expected",
    "controls_observed",
    "controls_matched",
    "controls_unmatched",
    "by_definition",
    "by_year",
    "by_session",
    "by_direction",
    "by_terminal_state",
    "exclusions_by_reason",
    "primary_exclusions_by_reason",
    "treatment_control_reconciliation",
    "interactions",
    "geometry",
    "denominator_definitions",
)

DEFINITION_KEYS = frozenset({"single_wick_50_d3_v1", "cluster2_wick_50_d3_v1"})
YEAR_KEYS = frozenset({"2022", "2023", "2024", "2025"})
SESSION_KEYS = frozenset(
    {"asia", "premarket", "ny_observation", "ny_afternoon", "maintenance"}
)
EXCLUSION_KEYS = frozenset(
    {
        "interval_boundary",
        "duplicate_identity",
        "causal_observability_failure",
        "incomplete_source_sequence",
        "incomplete_session",
        "pre_availability_interaction",
        "missing_context",
        "missing_control",
        "incomplete_endpoint",
    }
)
CONTROL_KEYS = frozenset(
    {
        "matched_non_block",
        "matched_displacement_without_rb",
        "matched_context_without_rb",
        "matched_time_session_volatility",
        "direction_balanced",
        "random_time_placebo",
    }
)
INTERACTION_KEYS = frozenset(
    {
        "rb_alone",
        "aligned_d005_context",
        "after_d004_manipulation",
        "frozen_liquidity_sweep",
        "displacement_confirmation",
        "refinement_confirmation",
        "against_d005_context_negative_control",
    }
)
GEOMETRY_KEYS = frozenset({"proximal", "midpoint", "distal"})
DIRECTION_KEYS = frozenset({"bullish", "bearish"})
TERMINAL_STATE_KEYS = frozenset({"MITIGATED", "INVALIDATED", "EXPIRED", "ACTIVE_CENSORED"})
DENOMINATOR_KEYS = frozenset(
    {
        "detected",
        "eligible",
        "touch",
        "lifecycle",
        "direction",
        "overlap",
        "endpoint",
        "definition",
        "year",
        "session",
        "exclusion",
        "control",
        "interaction",
        "geometry",
    }
)
RECONCILIATION_FIELDS = frozenset(
    {"candidate_count", "matched_count", "unmatched_count", "endpoint_complete_pair_count"}
)
INTERACTION_RECONCILIATION_FIELDS = frozenset(
    {"candidate_count", "eligible_count", "endpoint_complete_count", "matched_count", "excluded_count"}
)
GEOMETRY_RECONCILIATION_FIELDS = frozenset(
    {"eligible_count", "touched_count", "endpoint_complete_count"}
)
FORBIDDEN_REPORT_KEY_FRAGMENTS = (
    "expectancy",
    "fee",
    "funded",
    "pnl",
    "position_size",
    "profit",
    "r_multiple",
    "slippage",
    "stop",
    "target",
    "trade",
)


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(fragment in normalized for fragment in FORBIDDEN_REPORT_KEY_FRAGMENTS):
                raise SchemaError(f"forbidden D006 reporting field: {key}")
            _reject_forbidden_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden_keys(item)


def _utc_timestamp(value: object, label: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if str(timestamp.tz) != "UTC":
        raise SchemaError(f"{label} must be explicit UTC")
    return timestamp


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def validate_bars(bars: pd.DataFrame, evaluation_at: object) -> pd.DataFrame:
    """Validate five-minute, already-closed synthetic bars without coercion."""

    if not isinstance(bars, pd.DataFrame):
        raise SchemaError("bars must be a DataFrame")
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.name != "timestamp_utc":
        raise SchemaError("bars require a DatetimeIndex named timestamp_utc")
    if bars.index.tz is None or str(bars.index.tz) != "UTC":
        raise SchemaError("bar timestamps must be explicit UTC")
    if bars.index.hasnans:
        raise SchemaError("bar timestamps must be non-null")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise SchemaError("bar timestamps must be unique and ordered")
    if not ((bars.index.minute % 5 == 0) & (bars.index.second == 0) & (bars.index.microsecond == 0)).all():
        raise SchemaError("bar timestamps must be epoch-aligned to five minutes")
    missing = [name for name in BAR_FIELDS if name not in bars.columns]
    if missing:
        raise SchemaError(f"missing required bar fields: {missing}")
    if (
        bars["bar_id"].isna().any()
        or not bars["bar_id"].map(lambda value: isinstance(value, str) and bool(value)).all()
        or not bars["bar_id"].is_unique
    ):
        raise SchemaError("bar IDs must be non-empty unique strings")
    bar_ids = bars["bar_id"]
    if not bar_ids.equals(bar_ids.sort_values(kind="stable")):
        raise SchemaError("bar IDs must be strictly ordered with source time")
    if bars["is_complete"].dtype != bool or not bars["is_complete"].all():
        raise SchemaError("all bars must be complete")
    numeric = bars.loc[:, ["open", "high", "low", "close"]]
    if not numeric.map(lambda value: isinstance(value, (int, float)) and isfinite(value)).all().all():
        raise SchemaError("OHLC values must be finite")
    if (numeric["high"] < numeric[["open", "low", "close"]].max(axis=1)).any() or (
        numeric["low"] > numeric[["open", "high", "close"]].min(axis=1)
    ).any():
        raise SchemaError("OHLC values are invalid")
    available = pd.to_datetime(bars["available_at"], utc=False)
    if available.isna().any():
        raise SchemaError("available_at must be non-null")
    if getattr(available.dt, "tz", None) is None or str(available.dt.tz) != "UTC":
        raise SchemaError("available_at must be explicit UTC")
    expected = pd.Series(bars.index + pd.Timedelta(minutes=5), index=bars.index)
    if not available.reset_index(drop=True).equals(expected.reset_index(drop=True)):
        raise SchemaError("available_at must equal bar start plus five minutes")
    cutoff = _utc_timestamp(evaluation_at, "evaluation_at")
    if (bars.index > cutoff).any() or (available > cutoff).any():
        raise SchemaError("bars after evaluation_at are forbidden")
    return bars.copy(deep=True)


def validate_aggregate_audit(audit: Mapping[str, object]) -> None:
    """Validate an exact, deterministically reconciled structural audit payload."""

    _reject_forbidden_keys(audit)
    if set(audit) != set(AGGREGATE_AUDIT_FIELDS):
        raise SchemaError("aggregate audit fields must exactly match the D006 schema")
    counts = (
        "detected", "duplicate_id_excluded", "lifecycle_eligible", "endpoint_eligible",
        "endpoint_complete_count", "touched", "untouched", "invalidated", "mitigated",
        "expired", "active_censored", "overlapping", "nested", "bullish", "bearish",
        "preavailability_count", "expected_primary_pairs",
        "observed_primary_pairs", "controls_expected", "controls_observed",
        "controls_matched", "controls_unmatched",
    )
    if any(not _is_nonnegative_int(audit[name]) for name in counts):
        raise SchemaError("aggregate counts must be non-negative integers")
    if audit["touched"] + audit["untouched"] != audit["lifecycle_eligible"]:
        raise SchemaError("touch denominator does not reconcile to lifecycle eligible")
    if audit["invalidated"] + audit["mitigated"] + audit["expired"] + audit["active_censored"] != audit["lifecycle_eligible"]:
        raise SchemaError("lifecycle counts do not reconcile to lifecycle eligible")
    if audit["touched"] < audit["mitigated"] or audit["nested"] > audit["overlapping"]:
        raise SchemaError("structural count relationships are invalid")
    if audit["bullish"] + audit["bearish"] != audit["detected"]:
        raise SchemaError("direction counts do not reconcile to detected")
    if audit["overlapping"] > audit["detected"]:
        raise SchemaError("overlapping cannot exceed detected")
    exclusions = audit["exclusions_by_reason"]
    if (
        not isinstance(exclusions, Mapping)
        or set(exclusions) != EXCLUSION_KEYS
        or any(not _is_nonnegative_int(value) for value in exclusions.values())
    ):
        raise SchemaError("the exact exclusion registry requires non-negative integer counts")
    if audit["lifecycle_eligible"] + sum(exclusions.values()) != audit["detected"]:
        raise SchemaError("lifecycle eligible plus exclusions must reconcile to detected")
    if audit["duplicate_id_excluded"] != exclusions["duplicate_identity"]:
        raise SchemaError("duplicate-ID count does not match its exclusion")
    if audit["preavailability_count"] != exclusions["pre_availability_interaction"]:
        raise SchemaError("preavailability count does not match its exclusion")
    primary_exclusions = audit["primary_exclusions_by_reason"]
    if (
        not isinstance(primary_exclusions, Mapping)
        or set(primary_exclusions) != EXCLUSION_KEYS
        or any(not _is_nonnegative_int(value) for value in primary_exclusions.values())
        or sum(primary_exclusions.values())
        != audit["expected_primary_pairs"] - audit["observed_primary_pairs"]
    ):
        raise SchemaError("primary exclusion counts do not reconcile")
    exact_count_maps = (
        ("by_definition", DEFINITION_KEYS, audit["detected"]),
        ("by_year", YEAR_KEYS, audit["detected"]),
        ("by_session", SESSION_KEYS, audit["detected"]),
        ("by_direction", DIRECTION_KEYS, audit["detected"]),
        ("by_terminal_state", TERMINAL_STATE_KEYS, audit["lifecycle_eligible"]),
    )
    for name, keys, total in exact_count_maps:
        mapping = audit[name]
        if (
            not isinstance(mapping, Mapping)
            or set(mapping) != keys
            or any(not _is_nonnegative_int(value) for value in mapping.values())
        ):
            raise SchemaError(f"{name} must contain the exact registered non-negative counts")
        if total is not None and sum(mapping.values()) != total:
            raise SchemaError(f"{name} does not reconcile to its denominator")
    if (
        audit["by_direction"]["bullish"] != audit["bullish"]
        or audit["by_direction"]["bearish"] != audit["bearish"]
        or audit["by_terminal_state"]["MITIGATED"] != audit["mitigated"]
        or audit["by_terminal_state"]["INVALIDATED"] != audit["invalidated"]
        or audit["by_terminal_state"]["EXPIRED"] != audit["expired"]
        or audit["by_terminal_state"]["ACTIVE_CENSORED"] != audit["active_censored"]
    ):
        raise SchemaError("direction or terminal-state map disagrees with aggregate counts")
    if not (
        audit["endpoint_complete_count"] <= audit["endpoint_eligible"] <= audit["lifecycle_eligible"]
        and audit["endpoint_eligible"] <= audit["touched"]
    ):
        raise SchemaError("endpoint counts do not reconcile to touched lifecycle population")
    if not isinstance(audit["endpoint_coverage_complete"], bool):
        raise SchemaError("endpoint coverage result must be boolean")
    coverage_observed = (
        audit["expected_primary_pairs"]
        == audit["observed_primary_pairs"]
        == audit["endpoint_complete_count"]
    )
    if audit["endpoint_coverage_complete"] is not coverage_observed:
        raise SchemaError("endpoint coverage result is inconsistent")
    control_counts = tuple(audit[name] for name in ("controls_expected", "controls_observed", "controls_matched", "controls_unmatched"))
    if any(not _is_nonnegative_int(value) for value in control_counts) or audit["controls_expected"] != audit["controls_matched"] + audit["controls_unmatched"] or audit["controls_observed"] != audit["controls_matched"] or audit["controls_expected"] != audit["expected_primary_pairs"] or audit["controls_observed"] != audit["observed_primary_pairs"]:
        raise SchemaError("control counts do not reconcile")
    reconciliation = audit["treatment_control_reconciliation"]
    if not isinstance(reconciliation, Mapping) or set(reconciliation) != CONTROL_KEYS:
        raise SchemaError("every registered control reconciliation is required")
    for values in reconciliation.values():
        if (
            not isinstance(values, Mapping)
            or set(values) != RECONCILIATION_FIELDS
            or any(not _is_nonnegative_int(value) for value in values.values())
            or values["candidate_count"]
            != values["matched_count"] + values["unmatched_count"]
            or values["endpoint_complete_pair_count"] > values["matched_count"]
        ):
            raise SchemaError("control-family reconciliation failed")
    interactions = audit["interactions"]
    if not isinstance(interactions, Mapping) or set(interactions) != INTERACTION_KEYS:
        raise SchemaError("every registered interaction reconciliation is required")
    for values in interactions.values():
        if (
            not isinstance(values, Mapping)
            or set(values) != INTERACTION_RECONCILIATION_FIELDS
            or any(not _is_nonnegative_int(value) for value in values.values())
            or values["candidate_count"] != values["eligible_count"] + values["excluded_count"]
            or values["matched_count"] > values["eligible_count"]
            or values["endpoint_complete_count"] > values["matched_count"]
        ):
            raise SchemaError("interaction-family reconciliation failed")
    geometry = audit["geometry"]
    if not isinstance(geometry, Mapping) or set(geometry) != GEOMETRY_KEYS:
        raise SchemaError("every registered geometry reconciliation is required")
    for values in geometry.values():
        if (
            not isinstance(values, Mapping)
            or set(values) != GEOMETRY_RECONCILIATION_FIELDS
            or any(not _is_nonnegative_int(value) for value in values.values())
            or values["endpoint_complete_count"] > values["touched_count"]
            or values["touched_count"] > values["eligible_count"]
        ):
            raise SchemaError("geometry reconciliation failed")
    denominators = audit["denominator_definitions"]
    if (
        not isinstance(denominators, Mapping)
        or set(denominators) != DENOMINATOR_KEYS
        or any(not isinstance(value, str) or not value.strip() for value in denominators.values())
    ):
        raise SchemaError("all exact denominator definitions are required")


def validate_fail_report(report: Mapping[str, object]) -> None:
    """Require integrity, then adequacy, then a non-decisional primary path if needed."""

    _reject_forbidden_keys(report)
    expected = ("integrity", "adequacy", "primary")
    if tuple(report.keys()) != expected:
        raise SchemaError("report must follow integrity, adequacy, primary order")
    integrity, adequacy, primary = (report[name] for name in expected)
    if not all(isinstance(value, Mapping) for value in (integrity, adequacy, primary)):
        raise SchemaError("report stages must be mappings")
    if tuple(integrity) != ("status",) or tuple(adequacy) != ("status",):
        raise SchemaError("integrity and adequacy fail-report fields are closed")
    if tuple(primary) != ("status", "mode"):
        raise SchemaError("primary fail-report fields are closed")
    if integrity.get("status") not in {"INTEGRITY_VERIFIED", "REPRODUCIBILITY_DEFECT"}:
        raise SchemaError("integrity status is invalid")
    if adequacy.get("status") not in {"SAMPLE_ADEQUATE", "SAMPLE_INADEQUATE", "NOT_EVALUATED"}:
        raise SchemaError("adequacy status is invalid")
    if primary.get("status") != "NOT_EVALUATED":
        raise SchemaError("primary status is invalid")
    if integrity["status"] == "REPRODUCIBILITY_DEFECT":
        if (
            adequacy["status"] != "NOT_EVALUATED"
            or primary["status"] != "NOT_EVALUATED"
            or primary.get("mode") != "SAFE_AUDIT_ONLY"
        ):
            raise SchemaError("integrity failure permits safe audit fields only")
    elif adequacy["status"] == "SAMPLE_INADEQUATE" and (
        primary["status"] != "NOT_EVALUATED"
        or primary.get("mode")
        != "DESCRIPTIVE_NON_DECISIONAL_AFTER_ADEQUACY_FAILURE"
    ):
        raise SchemaError("sample inadequacy must be descriptive and non-decisional")
    elif adequacy["status"] == "NOT_EVALUATED" and primary["status"] != "NOT_EVALUATED":
        raise SchemaError("primary cannot be evaluated before adequacy")
