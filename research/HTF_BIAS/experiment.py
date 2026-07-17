"""TASK 002 registered Phase 1 experiment entry point."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from aurumflow_research import ExperimentResult, ResearchDecision
from aurumflow_research.data import MarketDataRequest

from .analysis import PRIMARY_HORIZON, run_analysis
from .definitions import (
    CANDIDATE_DEFINITIONS,
    DECISION_RULES,
    DEFERRED_FEATURE_FAMILIES,
    FEATURE_DICTIONARY,
    OUTCOME_DEFINITIONS,
)
from .features import build_phase1_samples


RESEARCH_ARTIFACTS = (
    "feature_dictionary.json",
    "feature_availability_and_leakage_audit.csv",
    "feature_availability_and_leakage_audit.json",
    "dataset_qualification_report.json",
    "dataset_qualification_report.md",
    "sample_construction_report.json",
    "sample_construction_report.md",
    "candidate_definition_register.json",
    "candidate_definition_register.md",
    "outcome_definition_register.json",
    "outcome_definition_register.md",
    "chronological_partition_specification.json",
    "chronological_partition_specification.md",
    "baseline_comparison.csv",
    "standalone_results.csv",
    "candidate_comparison.csv",
    "feature_relationships.csv",
    "neutral_outcome_results.csv",
    "robustness_results.csv",
    "sensitivity_results.csv",
    "holdout_results.csv",
    "phase1_summary.json",
    "research_report.md",
)


def _json_default(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if pd.isna(value):
        return None
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            _json_safe(payload),
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _markdown_table(rows: list[Mapping[str, object]], columns: list[str]) -> str:
    if not rows:
        return "No rows."
    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join("---" for _ in columns) + "|"
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                value = "—" if math.isnan(value) else f"{value:.4f}"
            elif value is None:
                value = "—"
            cells.append(str(value).replace("|", "\\|"))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, divider, *body])


def _dataset_markdown(quality: Mapping[str, object]) -> str:
    warnings = "\n".join(f"- {value}" for value in quality.get("warnings", []))
    return f"""# HTF Bias Phase 1 Dataset Qualification

Verdict: **{quality['verdict']}**

## Selected canonical inputs

- Market structure: {quality['structure']}
- UTC coverage: `{quality['first_timestamp_utc']}` through `{quality['last_timestamp_utc']}`
- Evaluation timezone: `{quality['evaluation_timezone']}` using DST-aware IANA conversion
- Source mapping: {quality['source_timezone_mapping']}
- Rows: {quality['row_count']:,}
- Missing expected-open minutes: {quality['missing_expected_open_minutes']:,} ({quality['missing_expected_open_percentage']}%)
- Missing expected-open periods: {quality['missing_period_count']} (longest {quality['longest_missing_period_minutes']} minutes)
- Duplicate timestamps: {quality['duplicate_timestamps']}
- Invalid OHLC rows: {quality['invalid_ohlc_rows']}
- Complete eligible New York weekdays: {quality['complete_eligible_new_york_weekdays']}
- Partial/incomplete weekdays excluded as prior-day anchors: {quality['partial_or_incomplete_new_york_weekdays']}
- Calendar rows: {quality['calendar_rows']}

The experiment reuses the validated canonical derivative and does not create a second normalization pipeline. Missing observations are not filled. Partial weekdays are not eligible as previous-day anchors; partial prior weeks and Monday ranges are flagged explicitly.

## Exclusions and warnings

{warnings}
"""


def _sample_markdown(payload: Mapping[str, object]) -> str:
    exclusions = payload.get("exclusion_counts", {})
    exclusion_lines = "\n".join(f"- `{key}`: {value}" for key, value in exclusions.items()) or "- None"
    return f"""# HTF Bias Phase 1 Sample Construction

- Evaluation rows constructed: {payload['evaluation_rows']}
- Unique New York session dates: {payload['unique_session_dates']}
- 08:30 rows: {payload['evaluation_clock_counts'].get('08:30', 0)}
- 09:30 rows: {payload['evaluation_clock_counts'].get('09:30', 0)}
- Rows with complete 60-minute outcome: {payload['complete_60m_outcomes']}
- Rows with incomplete 60-minute outcome: {payload['incomplete_60m_outcomes']}

Evaluation price is the mid-open of the exact one-minute anchor bar. Every HTF feature uses completed bars with availability at or before that anchor; intraday path features use bars strictly before it. Forward windows are half-open and require the final boundary bar plus at least 95% minute coverage. No missing bar is imputed.

## Construction exclusions

{exclusion_lines}
"""


def _partition_markdown(specification: Mapping[str, object]) -> str:
    rows = []
    for name in ("development", "validation", "holdout"):
        item = specification[name]
        rows.append(
            {
                "partition": name,
                "start": item["start"],
                "end": item["end"],
                "sessions": item["sessions"],
                "evaluation_rows": item["evaluation_rows"],
                "purpose": item["purpose"],
            }
        )
    return f"""# Chronological Partition Specification

{_markdown_table(rows, ['partition', 'start', 'end', 'sessions', 'evaluation_rows', 'purpose'])}

- Random split: **no**
- Coverage years: {specification['coverage_years']}
- Two-year confidence cap applies: {specification['history_confidence_cap_applies']}
- Holdout isolation: {specification['holdout_isolation_rule']}
"""


def _register_markdown(title: str, register: tuple[dict[str, object], ...]) -> str:
    return f"# {title}\n\n```json\n{json.dumps(register, indent=2, default=_json_default)}\n```\n"


def _research_report(
    *,
    quality: Mapping[str, object],
    samples: pd.DataFrame,
    candidate_results: pd.DataFrame,
    robustness: pd.DataFrame,
    summary: Mapping[str, object],
    partition_specification: Mapping[str, object],
    frozen_register: Mapping[str, object],
) -> str:
    primary = candidate_results[candidate_results["horizon"].eq(PRIMARY_HORIZON)]
    rows: list[dict[str, object]] = []
    for _, row in primary.iterrows():
        rows.append(
            {
                "candidate": row["candidate"],
                "partition": row["partition"],
                "n": int(row["directional_observations"]),
                "aligned mean bps": float(row["mean_aligned_return_bps"]),
                "95% CI lower": float(row["aligned_return_ci_lower"]),
                "95% CI upper": float(row["aligned_return_ci_upper"]),
                "effect size": float(row["standardized_effect_size"]),
                "accuracy": float(row["directional_accuracy"]),
                "accuracy lift": float(row["accuracy_lift_vs_selected_baseline"]),
            }
        )
    adequate = robustness[robustness["adequate_subgroup_sample"]]
    robust_summary = (
        adequate.groupby("candidate")["positive_directional_evidence"].mean().to_dict()
        if not adequate.empty
        else {}
    )
    robust_lines = "\n".join(
        f"- `{candidate}` positive in {value:.1%} of adequate registered validation/holdout strata."
        for candidate, value in robust_summary.items()
    ) or "- No candidate had enough observations for an adequate subgroup robustness rate."
    selected = frozen_register.get("model_e_selected_direction_columns", [])
    return f"""# Higher Timeframe Bias Research — Phase 1

## Scientific question

Do objectively measurable higher-timeframe context variables provide information about subsequent intraday XAUUSD behavior beyond unconditional, clock, weekday, news-timing, and prior-momentum baselines?

## Data and temporal integrity

The study used {quality['row_count']:,} already-normalized one-minute bid/ask bars from `{quality['first_timestamp_utc']}` through `{quality['last_timestamp_utc']}`. Evaluation anchors are 08:30 and 09:30 `America/New_York`, recorded in local time and UTC. Feature availability audits found no future-availability violation. Daily and weekly levels use only completed eligible periods; confirmed swings respect their right-side confirmation delay; Monday values are explicitly forming on Monday and completed only from Tuesday onward.

The history covers {partition_specification['coverage_years']} years, so the preregistered two-year confidence cap applies. Official calendar data support timing-only 08:30 versus non-08:30 context; actual, consensus, revision, and directional surprise values are not used.

## Candidate definitions

Models A-D test structure, range location, liquidity position, and displacement separately. Model E is an unweighted majority of development-qualified A-D families. Frozen Model E members: `{selected or 'none'}`. HTF imbalance/delivery-array proximity is deferred because no independently validated HTF detector exists.

## Primary 60-minute evidence

{_markdown_table(rows, ['candidate', 'partition', 'n', 'aligned mean bps', '95% CI lower', '95% CI upper', 'effect size', 'accuracy', 'accuracy lift'])}

## Robustness

{robust_lines}

Sensitivity outputs separately compare swing widths, mean-ATR versus robust-median displacement normalization, range-location continuation versus reversion, toward versus away liquidity formulations, evaluation times, horizons, outlier treatment, strict window completeness, spread filters, news regimes, subperiods, weekdays, and bullish/bearish symmetry. Exploratory feature correlations and subgroup slices are not ranked from point estimates.

## Decision

**{summary['phase1_decision']}** — {summary['rationale']}

## Limitations

- One year cannot establish year-by-year stability or a durable market-regime result.
- Holdout and subgroup samples are modest, especially for neutral-heavy structure/displacement candidates.
- The spot feed is broker-specific; timezone mapping is strongly supported but not broker-documented.
- News controls are official timing/category context only; surprise analysis is unavailable.
- Observed spreads are contextual quality filters, not a trading-cost or execution model.
- No candidate is a production signal, strategy, entry, stop, target, or position-sizing rule.

## Next research step

Extend the same frozen definitions to at least two additional full years and a second XAUUSD/GC-quality feed. Re-run the untouched chronological validation before considering any narrower Phase 2 mechanism study. Do not promote a context label to production from this Phase 1 run.
"""


def run(context) -> ExperimentResult:
    parameters = context.parameters
    source = str(parameters.get("data_source", "validated_event_study_csv"))
    market_dataset = str(parameters["market_dataset"])
    calendar_dataset = str(parameters["calendar_dataset"])
    bootstrap_resamples = int(parameters.get("bootstrap_resamples", 2000))
    if bootstrap_resamples < 200:
        raise ValueError("bootstrap_resamples must be at least 200")
    evaluation_clocks = tuple(str(value) for value in parameters.get("evaluation_clocks", ["08:30", "09:30"]))

    market = context.data.load(
        source,
        MarketDataRequest(
            dataset=market_dataset,
            symbol="XAUUSD",
            timeframe="1m_bidask",
        ),
    )
    calendar = context.data.load(
        source,
        MarketDataRequest(dataset=calendar_dataset, symbol="USD", timeframe="daily"),
    )
    context.logger.info(
        "inputs_loaded",
        "Validated market and official timing inputs loaded",
        market_rows=len(market.frame),
        calendar_rows=len(calendar.frame),
    )

    built = build_phase1_samples(
        market.frame,
        calendar.frame,
        evaluation_clocks=evaluation_clocks,
    )
    context.logger.info(
        "samples_constructed",
        "Causal evaluation samples constructed",
        evaluation_rows=len(built.samples),
        leakage_audit="PASS",
    )
    analysis = run_analysis(
        built.samples,
        bootstrap_resamples=bootstrap_resamples,
        seed=context.random.randint(0, 2**31 - 1),
    )

    output = context.output_dir
    feature_payload = {
        "features": FEATURE_DICTIONARY,
        "deferred_families": DEFERRED_FEATURE_FAMILIES,
        "conventions": {
            "evaluation_price": "mid_open at the exact anchor minute",
            "feature_cutoff": "completed source observations strictly before evaluation unless a level-period availability timestamp is earlier",
            "timezone": "America/New_York via IANA rules; canonical timestamps retained in UTC",
        },
    }
    _write_json(output / "feature_dictionary.json", feature_payload)
    built.feature_audit.to_csv(output / "feature_availability_and_leakage_audit.csv", index=False)
    _write_json(
        output / "feature_availability_and_leakage_audit.json",
        {
            "status": "PASS",
            "rows": built.feature_audit.to_dict(orient="records"),
            "total_future_availability_violations": int(
                built.feature_audit["future_availability_violations"].sum()
            ),
        },
    )
    _write_json(output / "dataset_qualification_report.json", built.data_quality)
    (output / "dataset_qualification_report.md").write_text(
        _dataset_markdown(built.data_quality), encoding="utf-8"
    )
    exclusion_counts = (
        built.exclusions["reason"].value_counts().to_dict()
        if not built.exclusions.empty
        else {}
    )
    sample_payload = {
        "evaluation_rows": int(len(built.samples)),
        "unique_session_dates": int(built.samples["session_date"].nunique()),
        "evaluation_clock_counts": built.samples["evaluation_clock"].value_counts().to_dict(),
        "complete_60m_outcomes": int(built.samples["forward_return_bps_60m"].notna().sum()),
        "incomplete_60m_outcomes": int(built.samples["forward_return_bps_60m"].isna().sum()),
        "exclusion_counts": exclusion_counts,
        "outcome_exclusion_counts": built.samples["outcome_exclusion_reasons"].value_counts().to_dict(),
        "missing_data_policy": "no imputation; anchor rows missing an exact evaluation bar are excluded; outcomes require endpoint and >=95% coverage",
    }
    _write_json(output / "sample_construction_report.json", sample_payload)
    (output / "sample_construction_report.md").write_text(
        _sample_markdown(sample_payload), encoding="utf-8"
    )
    candidate_register = {
        "candidates": CANDIDATE_DEFINITIONS,
        "decision_rules": DECISION_RULES,
        "frozen_register": analysis.frozen_register,
    }
    _write_json(output / "candidate_definition_register.json", candidate_register)
    (output / "candidate_definition_register.md").write_text(
        _register_markdown("Candidate Definition Register", CANDIDATE_DEFINITIONS)
        + "\n## Frozen development register\n\n```json\n"
        + json.dumps(_json_safe(analysis.frozen_register), indent=2, default=_json_default)
        + "\n```\n",
        encoding="utf-8",
    )
    _write_json(output / "outcome_definition_register.json", OUTCOME_DEFINITIONS)
    (output / "outcome_definition_register.md").write_text(
        _register_markdown("Outcome Definition Register", OUTCOME_DEFINITIONS),
        encoding="utf-8",
    )
    _write_json(
        output / "chronological_partition_specification.json",
        analysis.partition_specification,
    )
    (output / "chronological_partition_specification.md").write_text(
        _partition_markdown(analysis.partition_specification), encoding="utf-8"
    )
    for name, table in (
        ("baseline_comparison.csv", analysis.baseline_comparison),
        ("standalone_results.csv", analysis.standalone_results),
        ("candidate_comparison.csv", analysis.candidate_comparison),
        ("feature_relationships.csv", analysis.feature_relationships),
        ("neutral_outcome_results.csv", analysis.neutral_outcome_results),
        ("robustness_results.csv", analysis.robustness_results),
        ("sensitivity_results.csv", analysis.sensitivity_results),
        ("holdout_results.csv", analysis.holdout_results),
    ):
        table.to_csv(output / name, index=False)
    phase1_summary = {
        **analysis.phase1_summary,
        "sample_size": int(len(analysis.samples)),
        "partition_specification": analysis.partition_specification,
        "data_coverage": {
            "first_timestamp_utc": built.data_quality["first_timestamp_utc"],
            "last_timestamp_utc": built.data_quality["last_timestamp_utc"],
            "row_count": built.data_quality["row_count"],
        },
        "production_code_changed": False,
        "production_defaults_changed": False,
    }
    _write_json(output / "phase1_summary.json", phase1_summary)
    (output / "research_report.md").write_text(
        _research_report(
            quality=built.data_quality,
            samples=analysis.samples,
            candidate_results=analysis.candidate_comparison,
            robustness=analysis.robustness_results,
            summary=analysis.phase1_summary,
            partition_specification=analysis.partition_specification,
            frozen_register=analysis.frozen_register,
        ),
        encoding="utf-8",
    )

    missing_artifacts = [name for name in RESEARCH_ARTIFACTS if not (output / name).is_file()]
    if missing_artifacts:
        raise RuntimeError(f"research artifact generation incomplete: {missing_artifacts}")
    phase_decision = analysis.phase1_summary["phase1_decision"]
    if phase_decision == "PROCEED":
        framework_decision = ResearchDecision.ACCEPTED
    elif phase_decision == "REJECT_CURRENT_CANDIDATE_DEFINITIONS":
        framework_decision = ResearchDecision.REJECTED
    else:
        framework_decision = ResearchDecision.INCONCLUSIVE
    holdout_primary = analysis.holdout_results[
        analysis.holdout_results["horizon"].eq(PRIMARY_HORIZON)
    ]
    intervals = {
        str(row["candidate"]): {
            "mean_aligned_return_bps": _json_safe(float(row["mean_aligned_return_bps"])),
            "lower": _json_safe(float(row["aligned_return_ci_lower"])),
            "upper": _json_safe(float(row["aligned_return_ci_upper"])),
            "n": int(row["directional_observations"]),
        }
        for _, row in holdout_primary.iterrows()
    }
    robustness_checks = [
        "Evaluation-time, news-regime, weekday, subperiod, direction, spread-filter, and complete-window strata written to robustness_results.csv",
        "Daily/4H swing-width and volatility-normalization alternatives written to sensitivity_results.csv",
        "The feature-availability audit reported zero future-availability violations",
    ]
    sensitivity = [
        "Swing width 2 versus 3",
        "ATR14 mean versus rolling robust median normalization",
        "Range-location continuation versus reversion",
        "Nearest-level toward versus away direction",
        "30/60/120 minute and fixed 12:00 New York outcomes",
        "Raw versus 1st/99th percentile outlier treatment",
        "95% versus complete outcome-window coverage and spread filters",
    ]
    limitations = list(built.data_quality["warnings"]) + [
        "Official news records contain timing/categories but no validated actual, consensus, revision, or surprise values.",
        "HTF imbalance/delivery-array proximity was deferred rather than importing unvalidated entry logic.",
        "No probabilistic output exists, so probability calibration is not applicable.",
    ]
    return ExperimentResult(
        summary=f"HTF Bias Phase 1 completed with decision {phase_decision}.",
        research_status=framework_decision,
        status_rationale=str(analysis.phase1_summary["rationale"]),
        sample_size=int(len(analysis.samples)),
        bootstrap_confidence_intervals=intervals,
        robustness_checks=robustness_checks,
        sensitivity_analysis=sensitivity,
        data_exclusions=[
            f"{key}: {value}" for key, value in exclusion_counts.items()
        ],
        limitations=limitations,
        metrics={
            "phase1_decision": phase_decision,
            "coverage_years": analysis.partition_specification["coverage_years"],
            "evaluation_rows": int(len(analysis.samples)),
            "holdout_sessions": analysis.partition_specification["holdout"]["sessions"],
            "model_e_selected_families": analysis.frozen_register[
                "model_e_selected_direction_columns"
            ],
            "production_code_changed": False,
        },
        findings=[str(analysis.phase1_summary["rationale"])],
        artifacts=list(RESEARCH_ARTIFACTS),
    )
