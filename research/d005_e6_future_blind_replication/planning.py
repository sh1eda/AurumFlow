"""Deterministic, aggregate-only sample accumulation planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PlanningScenario:
    name: str
    endpoint_complete_per_month: float


SCENARIOS = (
    PlanningScenario("pessimistic", 18.0),
    PlanningScenario("central", 23.0),
    PlanningScenario("optimistic", 37.0),
)
DIRECTION_SHARES = (0.50, 0.40, 0.30)
ENDPOINT_RETENTION = (1.00, 0.90, 0.80)


def _months(required: int, monthly_rate: float) -> float:
    if required <= 0 or monthly_rate <= 0:
        raise ValueError("required N and planning rate must be positive")
    return round(required / monthly_rate, 1)


def sample_size_plan() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        row = asdict(scenario)
        row["months_to_total_1000"] = _months(1000, scenario.endpoint_complete_per_month)
        row["months_to_direction_200"] = {
            f"share_{share:.2f}": _months(
                200, scenario.endpoint_complete_per_month * share
            )
            for share in DIRECTION_SHARES
        }
        row["endpoint_exclusion_sensitivity"] = {
            f"retention_{retention:.2f}": {
                "effective_monthly_rate": round(
                    scenario.endpoint_complete_per_month * retention, 1
                ),
                "months_to_total_1000": _months(
                    1000, scenario.endpoint_complete_per_month * retention
                ),
                "months_to_direction_200_at_30pct_share": _months(
                    200, scenario.endpoint_complete_per_month * retention * 0.30
                ),
            }
            for retention in ENDPOINT_RETENTION
        }
        rows.append(row)
    return {
        "historical_adequacy_thresholds": {
            "minimum_total_primary": 1000,
            "minimum_bearish": 200,
            "minimum_bullish": 200,
            "complete_required_endpoint_coverage": True,
        },
        "known_aggregate_inputs": {
            "historical_primary_n": 1778,
            "historical_calendar_years": 4,
            "e4_endpoint_complete_n": 156,
            "e4_calendar_days": 209,
        },
        "scenarios": rows,
        "planning_only": True,
        "decision_rule": False,
        "future_observation_used": False,
        "limitation": (
            "Historical rolling-origin and future construction definitions differ; "
            "rates are approximate and non-scientific."
        ),
    }
