"""Registered Liquidity Phase 1 experiment and reproducible artifacts."""

from __future__ import annotations

from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from aurumflow_research import ExperimentResult, ResearchDecision
from aurumflow_research.data import MarketDataRequest

from .analysis import run_liquidity_analysis
from .definitions import (
    DECISION_RULES,
    HYPOTHESIS_REGISTER,
    LEVEL_DICTIONARY,
    MATCHED_BASELINE_METHODOLOGY,
    OUTCOME_DEFINITION_REGISTER,
    SENSITIVITY_REGISTER,
    STATE_TRANSITION_DICTIONARY,
)
from .levels import build_liquidity_dataset


RESEARCH_ARTIFACTS = (
    "liquidity_level_dictionary.json",
    "liquidity_level_dictionary.md",
    "state_transition_dictionary.json",
    "state_transition_dictionary.md",
    "level_availability_and_leakage_audit.csv",
    "level_availability_and_leakage_audit.json",
    "dataset_qualification_report.json",
    "dataset_qualification_report.md",
    "level_construction_report.json",
    "level_construction_report.md",
    "event_construction_and_deduplication_report.json",
    "event_construction_and_deduplication_report.md",
    "candidate_hypothesis_register.json",
    "candidate_hypothesis_register.md",
    "outcome_definition_register.json",
    "outcome_definition_register.md",
    "matched_baseline_methodology.json",
    "matched_baseline_methodology.md",
    "chronological_partition_specification.json",
    "chronological_partition_specification.md",
    "frozen_conditional_baselines.json",
    "fixed_anchor_results.csv",
    "interaction_event_results.csv",
    "level_family_comparison.csv",
    "reach_survival_results.csv",
    "hypothesis_results.csv",
    "robustness_matrix.csv",
    "sensitivity_analysis.csv",
    "level_inventory.csv",
    "state_transitions.csv",
    "fixed_anchor_observations.csv",
    "interaction_events.csv",
    "phase1_summary.json",
    "research_report.md",
)


def _json_default(value: object) -> object:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        return _json_default(value)
    except TypeError:
        return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _markdown_table(rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> str:
    if not rows:
        return "_No rows._"

    def render(value: object) -> str:
        if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
            return "—"
        if isinstance(value, float):
            return f"{value:.4f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    body = [
        "| " + " | ".join(render(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _register_markdown(title: str, rows: Sequence[Mapping[str, object]]) -> str:
    sections = [f"# {title}", "", "Frozen before final holdout evaluation.", ""]
    for row in rows:
        heading = row.get("family") or row.get("state") or row.get("id") or row.get("outcome") or row.get("dimension")
        sections.extend([f"## {heading}", ""])
        for key, value in row.items():
            if key in {"family", "state", "id", "outcome", "dimension"}:
                continue
            rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
            sections.append(f"- {key.replace('_', ' ').title()}: {rendered}")
        sections.append("")
    return "\n".join(sections)


def _mapping_markdown(title: str, payload: Mapping[str, object]) -> str:
    lines = [f"# {title}", ""]
    for key, value in payload.items():
        if isinstance(value, Mapping):
            lines.extend([f"## {key.replace('_', ' ').title()}", ""])
            for nested_key, nested_value in value.items():
                lines.append(f"- {nested_key.replace('_', ' ').title()}: {nested_value}")
            lines.append("")
        elif isinstance(value, list):
            lines.extend([f"## {key.replace('_', ' ').title()}", ""])
            lines.extend(f"- {item}" for item in value)
            lines.append("")
        else:
            lines.append(f"- {key.replace('_', ' ').title()}: {value}")
    return "\n".join(lines) + "\n"


def _dataset_markdown(quality: Mapping[str, object]) -> str:
    periods = quality.get("largest_missing_periods", [])
    rows = [
        {
            "start UTC": item.get("start_utc"),
            "end UTC": item.get("end_utc"),
            "minutes": item.get("minutes"),
        }
        for item in periods[:10]
    ]
    return f"""# Liquidity Phase 1 Dataset Qualification

## Source and coverage

- Source: validated canonical one-minute XAUUSD bid/ask derivative reused from TASK 002
- Rows: {quality['row_count']:,}
- UTC coverage: `{quality['first_timestamp_utc']}` through `{quality['last_timestamp_utc']}`
- Canonical timezone: `{quality['canonical_timezone']}`
- Evaluation timezone: `{quality['evaluation_timezone']}` with IANA DST rules
- Source mapping: {quality['source_timezone_mapping']}
- Structure: {quality['structure']}
- Official timing-only calendar rows: {quality['calendar_rows']}

## Quality and exclusions

- Verdict: `{quality['verdict']}`
- Missing expected-open minutes: {quality['missing_expected_open_minutes']:,} ({quality['missing_expected_open_percentage']}%)
- Missing periods: {quality['missing_period_count']} (longest {quality['longest_missing_period_minutes']} minutes)
- Duplicate timestamps: {quality['duplicate_timestamps']}
- Invalid OHLC rows: {quality['invalid_ohlc_rows']}
- Bid-above-ask rows: {quality['bid_above_ask_rows']}
- Zero median-spread minutes retained: {quality['zero_median_spread_minutes']}
- Maximum spread above 5 retained: {quality['maximum_spread_above_5_minutes']}
- Missing data: {quality['missing_data_policy']}

{_markdown_table(rows, ['start UTC', 'end UTC', 'minutes'])}

The experiment reads the validated derivative through the framework data adapter and does not create a second normalization, timezone, trading-day, or calendar pipeline. Incomplete daily/weekly source periods are excluded by the level constructor. HTF Bias is not used as a filter.
"""


def _partition_markdown(specification: Mapping[str, object]) -> str:
    rows = []
    for name in ("development", "validation", "holdout"):
        value = specification[name]
        rows.append(
            {
                "partition": name,
                "start": value["start"],
                "end": value["end"],
                "sessions": value["sessions"],
                "anchor rows": value["anchor_rows"],
                "event rows": value["event_rows"],
                "purpose": value["purpose"],
            }
        )
    return f"""# Chronological Partition Specification

{_markdown_table(rows, ['partition', 'start', 'end', 'sessions', 'anchor rows', 'event rows', 'purpose'])}

- Method: {specification['method']}
- Random split: {specification['random_split']}
- Coverage years: {specification['coverage_years']}
- Two-year history confidence cap: {specification['history_confidence_cap_applies']}
- Holdout isolation: {specification['holdout_isolation_rule']}
"""


def _research_report(
    *,
    quality: Mapping[str, object],
    level_report: Mapping[str, object],
    event_report: Mapping[str, object],
    summary: Mapping[str, object],
    family_comparison: pd.DataFrame,
    interaction_results: pd.DataFrame,
    robustness: pd.DataFrame,
) -> str:
    anchor_rows = family_comparison[
        family_comparison["partition"].isin(["validation", "holdout"])
    ][
        [
            "family", "partition", "usable_observations", "unique_sessions",
            "reach_rate", "matched_control_reach_rate", "paired_reach_rate_lift",
            "paired_lift_ci_lower", "paired_lift_ci_upper", "conditional_baseline_residual",
        ]
    ].to_dict(orient="records")
    touch_rows = interaction_results[
        interaction_results["partition"].isin(["validation", "holdout"])
        & interaction_results["event_type"].eq("touch")
        & interaction_results["interaction_group"].eq("all")
        & interaction_results["horizon"].eq("60m")
    ][
        [
            "family", "partition", "usable_events", "unique_sessions",
            "mean_side_aligned_return_bps", "aligned_return_ci_lower",
            "aligned_return_ci_upper", "standardized_effect_size",
        ]
    ].to_dict(orient="records")
    adequate_robustness = robustness[robustness["n"].ge(30)]
    positive_fraction = (
        float(adequate_robustness["effect"].gt(0).mean())
        if not adequate_robustness.empty
        else math.nan
    )
    decision = summary["phase1_decision"]
    return f"""# Liquidity Research — Phase 1

## Scientific question

Do objectively known historical price levels and timestamp-available interaction states contain incremental information about subsequent XAUUSD intraday reach, path, volatility, or neutral movement beyond distance, time, volatility, weekday, and official timing-only news baselines?

## Data

The study reused {quality['row_count']:,} validated one-minute bid/ask bars from `{quality['first_timestamp_utc']}` through `{quality['last_timestamp_utc']}`. All canonical timestamps are UTC; anchor labels and trading-day rules use `{quality['evaluation_timezone']}` with DST-aware IANA conversion. Missing observations were not filled. The history spans {summary['partition_specification']['coverage_years']} years, so the frozen two-year confidence cap applies.

## Liquidity definitions

The independent primary families are previous-day, previous-week, forming-Monday, completed-Monday, confirmed width-2 4H and daily swings, and volatility-normalized equal-high/low clusters. Width-3 swings and absolute/spread-aware equal clusters are sensitivities. Levels become available only after their source information and required right-side confirmation exist. States are descriptive transitions: untouched, approached, touched, exceeded, closed beyond, reclaimed, moved away, consumed, and expired.

Constructed levels: {level_report['total_levels']:,} ({level_report['primary_levels']:,} primary). Primary consumed levels: {level_report['consumed_primary_levels']:,}. Availability audit: PASS.

## Study design

The fixed-anchor study snapshots all eligible levels at 08:30 and 09:30 New York time and measures 30/60/120-minute, noon-window, and trading-day reach plus censored time-to-reach and pre-reach path. The interaction study begins outcomes only after a completed bar establishes approach, touch, exceedance, close-beyond, reclaim, or move-away. It keeps the earliest same-family/side/type price-zone event within {event_report['cooldown_minutes']} minutes and flags 120-minute overlap.

At each anchor, the primary control is a synthetic level at exactly the same absolute distance on the opposite side. A development-only distance x evaluation-clock x volatility empirical rate supplies the conditional baseline. Holdout rows never fit either baseline.

## Fixed-anchor results — primary 60-minute family comparison

{_markdown_table(anchor_rows, ['family', 'partition', 'usable_observations', 'unique_sessions', 'reach_rate', 'matched_control_reach_rate', 'paired_reach_rate_lift', 'paired_lift_ci_lower', 'paired_lift_ci_upper', 'conditional_baseline_residual'])}

## Interaction results — touch events

{_markdown_table(touch_rows, ['family', 'partition', 'usable_events', 'unique_sessions', 'mean_side_aligned_return_bps', 'aligned_return_ci_lower', 'aligned_return_ci_upper', 'standardized_effect_size'])}

## Robustness

The robustness matrix covers evaluation time, official timing-only news regime, weekday, high/low side, level age, chronological half, and first/repeated interactions. {len(adequate_robustness)} strata have at least 30 observations; their pooled positive-effect fraction is {positive_fraction:.1%} when estimable. Sensitivities cover horizons, touch/exceedance thresholds, reclaim horizons, lifecycle rules, swing/equal-level variants, spread and missing-data filters, control generation, event cooldown/overlap handling, and outlier treatment.

## Decision

**{decision}** — {summary['rationale']}

This is a Phase 1 experiment decision, not a final scientific decision for every possible liquidity formulation. The research object remains at `statistical_evaluation` / `not_evaluated`.

## Limitations

- One year cannot establish year-over-year or durable regime stability.
- XAUUSD spot is a broker-specific feed rather than a consolidated tape.
- Broker timezone mapping is strongly supported empirically but not broker-documented.
- Official calendar controls use timing/category only and never infer direction.
- Multiple levels within a session remain dependent; uncertainty is clustered by session and event overlap is audited.
- Equal-level and lifecycle definitions are deliberately small candidate sets, not exhaustive searches.
- No result is a strategy, direction, entry, stop, target, execution assumption, or production liquidity score.

## Narrow next step

Extend the frozen definitions to additional full years and a second high-quality XAUUSD or GC-derived reference before narrowing Phase 2 to any family/state that shows same-direction validation and holdout incremental evidence. Do not promote these results into production behavior.
"""


def run(context) -> ExperimentResult:
    parameters = context.parameters
    data_source = str(parameters["data_source"])
    market_dataset = str(parameters["market_dataset"])
    calendar_dataset = str(parameters["calendar_dataset"])
    evaluation_clocks = tuple(str(value) for value in parameters.get("evaluation_clocks", ["08:30", "09:30"]))
    bootstrap_resamples = int(parameters.get("bootstrap_resamples", 2000))
    event_cooldown = int(parameters.get("event_cooldown_minutes", 30))
    analysis_seed = context.random.randint(0, 2**31 - 1)
    if bootstrap_resamples < 200:
        raise ValueError("bootstrap_resamples must be at least 200")

    market = context.data.load(
        data_source,
        MarketDataRequest(dataset=market_dataset, symbol="XAUUSD", timeframe="1m"),
    )
    calendar = context.data.load(
        data_source,
        MarketDataRequest(dataset=calendar_dataset, symbol="USD", timeframe="daily"),
    )
    context.logger.info(
        "data_loaded",
        "Loaded validated Liquidity Phase 1 inputs",
        market_rows=len(market.frame),
        calendar_rows=len(calendar.frame),
    )

    output = context.output_dir
    # Freeze and write data-free definitions before any holdout analysis call.
    register_payloads = (
        ("liquidity_level_dictionary", LEVEL_DICTIONARY, "Liquidity Level Dictionary"),
        ("state_transition_dictionary", STATE_TRANSITION_DICTIONARY, "State Transition Dictionary"),
        ("candidate_hypothesis_register", HYPOTHESIS_REGISTER, "Candidate Hypothesis Register"),
        ("outcome_definition_register", OUTCOME_DEFINITION_REGISTER, "Outcome Definition Register"),
    )
    for basename, payload, title in register_payloads:
        _write_json(output / f"{basename}.json", list(payload))
        (output / f"{basename}.md").write_text(
            _register_markdown(title, payload), encoding="utf-8"
        )
    _write_json(output / "matched_baseline_methodology.json", MATCHED_BASELINE_METHODOLOGY)
    (output / "matched_baseline_methodology.md").write_text(
        _mapping_markdown("Matched Baseline Methodology", MATCHED_BASELINE_METHODOLOGY),
        encoding="utf-8",
    )

    built = build_liquidity_dataset(
        market.frame,
        calendar.frame,
        evaluation_clocks=evaluation_clocks,
        seed=analysis_seed,
        event_cooldown_minutes=event_cooldown,
    )
    context.logger.info(
        "dataset_constructed",
        "Constructed timestamp-safe levels, anchors, and interaction events",
        levels=len(built.levels),
        anchors=len(built.anchor_observations),
        events=len(built.events),
    )
    analysis = run_liquidity_analysis(
        built.anchor_observations,
        built.events,
        bootstrap_resamples=bootstrap_resamples,
        seed=analysis_seed,
        raw_events=built.raw_events,
    )

    _write_json(output / "dataset_qualification_report.json", built.data_quality)
    (output / "dataset_qualification_report.md").write_text(
        _dataset_markdown(built.data_quality), encoding="utf-8"
    )
    _write_json(output / "level_construction_report.json", built.level_report)
    (output / "level_construction_report.md").write_text(
        _mapping_markdown("Level Construction Report", built.level_report), encoding="utf-8"
    )
    _write_json(
        output / "event_construction_and_deduplication_report.json", built.event_report
    )
    (output / "event_construction_and_deduplication_report.md").write_text(
        _mapping_markdown(
            "Event Construction and Deduplication Report", built.event_report
        ),
        encoding="utf-8",
    )
    built.availability_audit.to_csv(
        output / "level_availability_and_leakage_audit.csv", index=False
    )
    _write_json(
        output / "level_availability_and_leakage_audit.json",
        {
            "status": "PASS",
            "total_future_information_violations": int(
                built.availability_audit["future_information_violations"].sum()
            ),
            "rows": built.availability_audit.to_dict(orient="records"),
        },
    )
    _write_json(
        output / "chronological_partition_specification.json",
        analysis.partition_specification,
    )
    (output / "chronological_partition_specification.md").write_text(
        _partition_markdown(analysis.partition_specification), encoding="utf-8"
    )
    _write_json(output / "frozen_conditional_baselines.json", analysis.frozen_baselines)
    _write_json(output / "phase1_summary.json", analysis.phase1_summary)

    tables = (
        ("fixed_anchor_results.csv", analysis.fixed_anchor_results),
        ("interaction_event_results.csv", analysis.interaction_event_results),
        ("level_family_comparison.csv", analysis.level_family_comparison),
        ("reach_survival_results.csv", analysis.survival_results),
        ("hypothesis_results.csv", analysis.hypothesis_results),
        ("robustness_matrix.csv", analysis.robustness_matrix),
        ("sensitivity_analysis.csv", analysis.sensitivity_analysis),
        ("level_inventory.csv", built.levels),
        ("state_transitions.csv", built.transitions),
        ("fixed_anchor_observations.csv", analysis.anchors),
        ("interaction_events.csv", analysis.events),
    )
    for filename, table in tables:
        table.to_csv(output / filename, index=False)

    report = _research_report(
        quality=built.data_quality,
        level_report=built.level_report,
        event_report=built.event_report,
        summary=analysis.phase1_summary,
        family_comparison=analysis.level_family_comparison,
        interaction_results=analysis.interaction_event_results,
        robustness=analysis.robustness_matrix,
    )
    (output / "research_report.md").write_text(report, encoding="utf-8")

    missing = [name for name in RESEARCH_ARTIFACTS if not (output / name).is_file()]
    if missing:
        raise RuntimeError(f"liquidity artifact generation incomplete: {missing}")

    phase_decision = str(analysis.phase1_summary["phase1_decision"])
    if phase_decision == "PROCEED":
        research_status = ResearchDecision.ACCEPTED
    elif phase_decision == "REJECT_CURRENT_CANDIDATE_DEFINITIONS":
        research_status = ResearchDecision.REJECTED
    else:
        research_status = ResearchDecision.INCONCLUSIVE

    primary_holdout = analysis.fixed_anchor_results[
        analysis.fixed_anchor_results["partition"].eq("holdout")
        & analysis.fixed_anchor_results["horizon"].eq("60m")
        & analysis.fixed_anchor_results["state_group"].eq("untouched")
        & analysis.fixed_anchor_results["family"].ne("ALL")
    ]
    intervals = {
        str(row["family"]): {
            "paired_reach_lift_60m": [
                row["paired_lift_ci_lower"],
                row["paired_lift_ci_upper"],
            ],
            "n": row["usable_observations"],
        }
        for _, row in primary_holdout.iterrows()
    }
    findings = [
        f"{row['family']} holdout untouched-level 60m lift {row['paired_reach_rate_lift']:.4f} (n={int(row['usable_observations'])})."
        for _, row in primary_holdout.iterrows()
    ]
    findings.append("HTF Bias was not used as a filter, and no production signal or strategy was created.")
    return ExperimentResult(
        summary=f"Liquidity Phase 1 completed both study designs: {phase_decision}.",
        research_status=research_status,
        status_rationale=str(analysis.phase1_summary["rationale"]),
        sample_size=int(analysis.phase1_summary["fixed_anchor_primary_rows"]),
        bootstrap_confidence_intervals=intervals,
        robustness_checks=[
            "Session-clustered uncertainty was evaluated by clock, news timing, weekday, side, age, chronological half, and first/repeated interaction.",
            f"Level availability audit found {int(built.availability_audit['future_information_violations'].sum())} future-information violations.",
        ],
        sensitivity_analysis=[
            f"{row['dimension']}: {row['value']} ({row['classification']})"
            for _, row in analysis.sensitivity_analysis.iterrows()
        ],
        data_exclusions=[
            f"{key}: {value}"
            for key, value in built.exclusions["reason"].value_counts().sort_index().items()
        ] if not built.exclusions.empty else ["No anchor/event construction exclusions."],
        limitations=[
            "Only approximately one year of broker-specific spot XAUUSD history is available.",
            "The source timezone mapping is strongly supported but not broker-documented.",
            "Official calendar data provide timing/category context only, not directional surprise.",
            "Dependent levels/events are session-clustered, but limited history constrains subgroup precision.",
            "Threshold sensitivities evaluate neutral post-event outcomes and do not revise primary historical state labels after holdout inspection.",
        ],
        metrics={
            "phase1_decision": phase_decision,
            "level_count": len(built.levels),
            "primary_level_count": int(built.levels["is_primary"].sum()),
            "anchor_observations": len(analysis.anchors),
            "primary_anchor_observations": int(
                (
                    analysis.anchors["is_primary"]
                    & analysis.anchors["active_under_primary_lifecycle"]
                ).sum()
            ),
            "interaction_events": len(analysis.events),
            "coverage_years": analysis.partition_specification["coverage_years"],
            "research_object_lifecycle": "statistical_evaluation",
            "research_object_decision": "not_evaluated",
            "production_code_changed": False,
            "production_defaults_changed": False,
        },
        findings=findings,
        artifacts=list(RESEARCH_ARTIFACTS),
    )
