"""Artifact persistence and full descriptive report for D005_E1."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from research.context_engine.config import ContextEngineConfig
from research.context_engine.reporting import sha256_file

from .config import EmpiricalStudyConfig


def _atomic_json(payload: object, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _atomic_text(text: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)


def _atomic_parquet(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    frame.to_parquet(
        temporary,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )
    os.replace(temporary, target)


def _normalize_parquet_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    """Give scalar timestamp columns one stable Arrow-compatible dtype."""

    result = frame.copy()
    for column in result.columns:
        if column == "timestamp_utc" or column.endswith("_at"):
            result[column] = pd.to_datetime(
                result[column],
                utc=True,
                errors="coerce",
            )
    return result


def _implementation_provenance(
    config: EmpiricalStudyConfig,
) -> dict[str, object]:
    repository = Path.cwd()
    paths: list[tuple[str, Path]] = []
    for relative in (
        Path("research/context_engine"),
        Path("research/d005_e1_context_engine_empirical"),
    ):
        for path in sorted((repository / relative).glob("*.py")):
            paths.append((str(relative / path.name), path))
    for relative in (
        Path(config.d005_source_catalog),
        Path(config.technical_spec),
    ):
        path = repository / relative
        if path.is_file():
            paths.append((str(relative), path))
    records = [
        {
            "path": label,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in paths
    ]
    combined = "|".join(
        f"{record['path']}:{record['sha256']}" for record in records
    )
    return {
        "files": records,
        "implementation_sha256": hashlib.sha256(
            combined.encode("utf-8")
        ).hexdigest(),
    }


def _schema(frame: pd.DataFrame) -> list[dict[str, str]]:
    return [
        {"column": column, "dtype": str(dtype)}
        for column, dtype in frame.dtypes.items()
    ]


def _safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else np.nan


def _summary(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: EmpiricalStudyConfig,
    run_metadata: Mapping[str, object],
    implementation: Mapping[str, object],
) -> dict[str, object]:
    snapshots = frames["context_snapshots"]
    gates = frames["gate_attribution"]
    fvg = frames["fvg_event_statistics"]
    obs = frames["order_block_event_statistics"]
    pmh = frames["pmh_pml_events"]
    forward = frames["forward_outcomes"]
    data_quality = frames["data_quality_periods"]
    excluded = frames["excluded_evaluations"]
    state_counts = (
        snapshots["state"].value_counts().sort_index().to_dict()
        if not snapshots.empty
        else {}
    )
    mode_counts = (
        snapshots["mode"].value_counts().sort_index().to_dict()
        if not snapshots.empty
        else {}
    )
    mapping_counts = (
        snapshots["mapping_variant"].value_counts().sort_index().to_dict()
        if not snapshots.empty
        else {}
    )
    gate_counts = (
        gates["gate"].value_counts().sort_index().to_dict()
        if not gates.empty
        else {}
    )
    pmh_swept = int(pmh["swept"].fillna(False).sum()) if not pmh.empty else 0
    pmh_rows = int(len(pmh))
    reaction_count = int(state_counts.get("reaction_confirmed", 0))
    forward_directional = (
        forward[forward["direction"].ne(0)]
        if not forward.empty
        else forward
    )
    return {
        "study_id": config.study_id,
        "version": config.version,
        "research_only": True,
        "optimization_performed": False,
        "production_behavior_changed": False,
        "entry_authorized_count": (
            int(snapshots["entry_authorized"].fillna(False).sum())
            if not snapshots.empty
            else 0
        ),
        "snapshot_count": int(len(snapshots)),
        "state_counts": {str(k): int(v) for k, v in state_counts.items()},
        "state_rates": {
            str(key): _safe_rate(int(value), len(snapshots))
            for key, value in state_counts.items()
        },
        "mode_counts": {str(k): int(v) for k, v in mode_counts.items()},
        "mapping_counts": {
            str(k): int(v) for k, v in mapping_counts.items()
        },
        "reaction_confirmed_count": reaction_count,
        "transition_count": int(len(frames["state_transitions"])),
        "gate_counts": {str(k): int(v) for k, v in gate_counts.items()},
        "conflict_count": int(len(frames["conflicts"])),
        "invalidation_count": int(len(frames["invalidations"])),
        "raw_fvg_count": int(len(fvg)),
        "fully_context_qualified_fvg_count": (
            int(fvg["context_qualified"].fillna(False).sum())
            if not fvg.empty
            else 0
        ),
        "wick_ifvg_count": (
            int(fvg["wick_ifvg"].fillna(False).sum())
            if not fvg.empty
            else 0
        ),
        "body_close_ifvg_count": (
            int(fvg["body_close_ifvg"].fillna(False).sum())
            if not fvg.empty
            else 0
        ),
        "order_block_count": int(len(obs)),
        "order_block_variants": (
            sorted(obs["variant"].dropna().unique().tolist())
            if not obs.empty
            else []
        ),
        "pmh_pml_rows": pmh_rows,
        "pmh_pml_sweep_rows": pmh_swept,
        "pmh_pml_sweep_rate": _safe_rate(pmh_swept, pmh_rows),
        "forward_outcome_rows": int(len(forward)),
        "directional_forward_rows": int(len(forward_directional)),
        "neutral_forward_rows": (
            int(forward["direction"].eq(0).sum())
            if not forward.empty
            else 0
        ),
        "fixed_schedule_rows": int(
            run_metadata["fixed_schedule_rows"]
        ),
        "event_schedule_rows": int(
            run_metadata["event_schedule_rows"]
        ),
        "event_schedule_uncapped_rows": int(
            run_metadata["event_schedule_uncapped_rows"]
        ),
        "event_schedule_omitted_rows": int(
            run_metadata["event_schedule_omitted_rows"]
        ),
        "event_schedule_truncated_mapping_dates": int(
            run_metadata["event_schedule_truncated_mapping_dates"]
        ),
        "event_evaluations_attempted": int(
            run_metadata["event_evaluations_attempted"]
        ),
        "event_evaluations_deduplicated": int(
            run_metadata["event_evaluations_deduplicated"]
        ),
        "runtime_seconds": float(run_metadata["runtime_seconds"]),
        "requested_start_date": config.start_date.isoformat(),
        "requested_end_date": config.end_date.isoformat(),
        "source": run_metadata["input_provenance"]["source"],
        "source_file_count": int(
            run_metadata["input_provenance"]["file_count"]
        ),
        "source_selection_sha256": run_metadata["input_provenance"][
            "selection_sha256"
        ],
        "source_files": run_metadata["input_provenance"]["files"],
        "missing_full_date_count": (
            int(data_quality["missing_full_date"].fillna(False).sum())
            if not data_quality.empty
            else 0
        ),
        "dst_transition_date_count": (
            int(data_quality["dst_transition"].fillna(False).sum())
            if not data_quality.empty
            else 0
        ),
        "excluded_fixed_evaluation_count": int(len(excluded)),
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
        "d004_guardrail": (
            "08:30-09:00 New York has no robust standalone directional "
            "edge and is not a D005_E1 direction rule."
        ),
    }


def _markdown_table(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    maximum_rows: int = 30,
) -> str:
    if frame.empty:
        return "_No qualifying rows._"
    selected = frame.loc[:, [item for item in columns if item in frame]].head(
        maximum_rows
    )
    headers = list(selected.columns)
    rows = [
        "| " + " | ".join(str(value) for value in row) + " |"
        for row in selected.itertuples(index=False, name=None)
    ]
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *rows,
        ]
    )


def render_report(
    *,
    frames: Mapping[str, pd.DataFrame],
    config: EmpiricalStudyConfig,
    summary: Mapping[str, object],
    run_metadata: Mapping[str, object],
) -> str:
    input_info = run_metadata["input_provenance"]
    states = pd.DataFrame(
        [
            {
                "state": state,
                "count": count,
                "rate": summary["state_rates"].get(state),
            }
            for state, count in summary["state_counts"].items()
        ]
    )
    gates = pd.DataFrame(
        [
            {"gate": gate, "attributions": count}
            for gate, count in summary["gate_counts"].items()
        ]
    ).sort_values("attributions", ascending=False) if summary["gate_counts"] else pd.DataFrame()
    mapping = frames["mapping_summary"]
    ob_summary = frames["order_block_variant_summary"]
    fvg_summary = frames["fvg_category_summary"]
    pmh_summary = frames["pmh_pml_summary"]
    timing = frames["timing_guardrail_summary"]
    annual = frames["annual_summary"]
    regime = frames["regime_summary"]
    forward_stability = frames["forward_stability_summary"]
    forward = frames["forward_outcomes"]
    forward_summary = (
        forward.groupby(
            ["anchor_type", "horizon", "direction"], dropna=False
        )
        .agg(
            observations=("anchor_id", "nunique"),
            mean_signed_change=("signed_change", "mean"),
            mean_absolute_change=("absolute_change", "mean"),
            mean_mfe=("mfe", "mean"),
            mean_mae=("mae", "mean"),
        )
        .reset_index()
        if not forward.empty
        else pd.DataFrame()
    )
    diagnostics = gates.head(12)
    return f"""# D005_E1 Context Engine Empirical Study

## Research boundary

This is a descriptive study of the isolated D005 engine. It does not authorize
entries, modify D005 defaults, select a production threshold, choose a
canonical Order Block, or connect to production behavior. Forward outcomes
are downstream-only and were never used to create context or gates.

The D004 guardrail remains binding: 08:30–09:00 New York has no robust
standalone directional edge. The 08:30, 09:00, 10:00, and 12:00 clocks below
are observation labels only. No index timing behavior is transferred to
XAUUSD.

## 1. Dataset and reproducibility

- Requested period: `{config.start_date}` through `{config.end_date}`
- Source: `{input_info["source"]}`
- Hash-verified source files: `{input_info["file_count"]}`
- One-minute rows with causal warm-up: `{input_info["row_count"]}`
- Source selection SHA-256: `{input_info["selection_sha256"]}`
- Study config fingerprint: `{summary["study_config_fingerprint"]}`
- Implementation SHA-256: `{summary["implementation_sha256"]}`
- Runtime seconds: `{summary["runtime_seconds"]:.2f}`
- Fixed schedule rows before mapping expansion: `{summary["fixed_schedule_rows"]}`
- Event schedule rows: `{summary["event_schedule_rows"]}`
- Uncapped event trigger rows: `{summary["event_schedule_uncapped_rows"]}`
- Omitted lower-priority event trigger rows: `{summary["event_schedule_omitted_rows"]}`
- Mapping-dates affected by the preregistered `{config.event_schedule_max_per_day_mapping}`-event cap: `{summary["event_schedule_truncated_mapping_dates"]}`
- Deduplicated event evaluations: `{summary["event_evaluations_deduplicated"]}` of `{summary["event_evaluations_attempted"]}`
- Missing full dates: `{summary["missing_full_date_count"]}`
- Fixed-clock exclusions: `{summary["excluded_fixed_evaluation_count"]}`
- Detected New York DST transition dates: `{summary["dst_transition_date_count"]}`

Missing dates, observed minutes, gaps, premarket coverage, and DST transitions
are retained in `data_quality_periods.parquet`; clock-level exclusions are in
`excluded_evaluations.parquet`. The event cap is observation sampling, not a
strategy threshold; no absence claim is made from omitted lower-priority
timestamps.

## 2. State and transition distribution

{_markdown_table(states, ["state", "count", "rate"])}

Transitions are retained at their original D005 `occurred_at` timestamps.
The funnel contains `{summary["transition_count"]}` unique transitions.

{_markdown_table(frames["transition_funnel"], ["mapping_variant", "transition", "transition_count", "median_elapsed_minutes", "median_elapsed_reaction_bars"])}

## 3. Gate attribution

Gate labels are non-exclusive. A snapshot can legitimately appear under
multiple gates; `gate_overlap.parquet` preserves combinations.

{_markdown_table(gates, ["gate", "attributions"])}

Diagnostics for low reaction-confirmed coverage must begin with these gate
frequencies rather than changing thresholds.

## 4. Mapping-level behavior

Mappings and the optional 1m refinement remain independent; no combined score
or winner is produced.

{_markdown_table(mapping, ["mode", "mapping_variant", "snapshot_count", "reaction_confirmed_count", "reaction_confirmed_rate", "bootstrap_ci_low", "bootstrap_ci_high"])}

## 5. FVG and Order Block findings

- Raw FVGs: `{summary["raw_fvg_count"]}`
- Fully context-qualified FVGs: `{summary["fully_context_qualified_fvg_count"]}`
- Wick IFVG observations: `{summary["wick_ifvg_count"]}`
- Body-close IFVG observations: `{summary["body_close_ifvg_count"]}`

The FVG table retains raw, liquidity-, MSS-, displacement-, and fully
context-qualified flags independently.

{_markdown_table(fvg_summary, ["mapping_variant", "fvg_category", "detection_count", "interaction_rate", "reaction_confirmation_rate", "invalidation_rate", "mean_favorable_excursion_60m", "mean_adverse_excursion_60m"], maximum_rows=40)}

{_markdown_table(ob_summary, ["mapping_variant", "variant", "detection_count", "median_zone_width", "interaction_rate", "reaction_confirmation_rate", "invalidation_rate", "mean_favorable_excursion_60m", "mean_adverse_excursion_60m", "fvg_overlap_rate", "liquidity_overlap_rate"])}

These OB statistics are descriptive. They do not select a canonical
definition.

## 6. PMH/PML findings

- Expanded PMH/PML mapping rows: `{summary["pmh_pml_rows"]}`
- Sweep rows: `{summary["pmh_pml_sweep_rows"]}`
- Sweep rate: `{summary["pmh_pml_sweep_rate"]}`

Each row records whether HTF context was unresolved, whether the balanced
prerequisite was met, and whether a later reaction-confirmed direction agreed.
PMH/PML never overrides valid HTF context and never creates independent bias.

{_markdown_table(pmh_summary, ["mapping_variant", "level_observations", "sweep_count", "sweep_frequency", "balanced_ranging_prerequisite_frequency", "reaction_confirmation_rate_after_sweep", "reaction_rate_when_htf_unresolved", "reaction_rate_when_valid_htf_exists", "agreement_rate_with_later_reaction"])}

## 7. Forward-price descriptive outcomes

Directional anchors have signed price-unit change, MFE, and MAE. Neutral
anchors have unsigned change and range expansion; their signed fields remain
null. These are not entry, stop, target, cost, or P&L results.

{_markdown_table(forward_summary, ["anchor_type", "horizon", "direction", "observations", "mean_signed_change", "mean_absolute_change", "mean_mfe", "mean_mae"])}

## 8. Stability

Annual, monthly, volatility-regime, direction, outcome, session, mapping, and
DST partitions are machine-readable. Bootstrap intervals resample trading
dates.

{_markdown_table(annual, ["year", "mode", "mapping_variant", "direction", "outcome", "snapshot_count", "reaction_confirmed_rate"])}

{_markdown_table(regime, ["volatility_regime", "mode", "mapping_variant", "direction", "outcome", "session", "dst", "snapshot_count", "reaction_confirmed_rate"], maximum_rows=20)}

Forward results are also partitioned by year, causal volatility regime,
direction, mapping, reversal/continuation label where applicable, session,
DST, event family, and horizon:

{_markdown_table(forward_stability, ["year", "volatility_regime", "direction", "mapping_variant", "outcome", "session", "dst", "anchor_type", "horizon", "observations", "mean_signed_change", "mean_absolute_change", "opposing_liquidity_reach_rate", "invalidation_first_rate"], maximum_rows=30)}

## 9. Implementation and data-quality diagnostics

The main study did not change a threshold. Low selectivity must be interpreted
against missing data, genuine absence of candidates, MSS/displacement/refinement
gates, timeout, overlapping gates, and the event schedule’s recorded
deduplication.

{_markdown_table(diagnostics, ["gate", "attributions"])}

No production or canonical-data path was written. Existing D005 artifacts were
treated as protected inputs and are not E1 outputs.

## 10. Timing guardrail and next research stage

{_markdown_table(timing, ["mapping_variant", "window_result", "date_count", "standalone_direction_rule", "causal_clock_claim"])}

The appropriate next step is review of this descriptive evidence and its
diagnostics. Any alternative threshold must be preregistered as a separately
named sensitivity variant with its own fingerprint. Production integration is
outside scope and is not recommended or proposed by this report.
"""


def persist_study_artifacts(
    *,
    frames: Mapping[str, pd.DataFrame],
    output_dir: Path,
    config: EmpiricalStudyConfig,
    run_metadata: Mapping[str, object],
    report_path: Path | None,
) -> dict[str, object]:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    implementation = _implementation_provenance(config)
    persisted: dict[str, pd.DataFrame] = {}
    d005_fingerprints = {
        variant.name: ContextEngineConfig(
            primary_mapping=variant.d005_mapping,
            optional_1m_refinement=variant.optional_1m_refinement,
        ).fingerprint()
        for variant in config.mapping_variants
    }
    for name, source in frames.items():
        frame = _normalize_parquet_timestamps(source)
        frame["study_version"] = config.version
        frame["study_config_fingerprint"] = config.fingerprint()
        frame["implementation_sha256"] = implementation[
            "implementation_sha256"
        ]
        if "mapping_variant" in frame:
            frame["d005_config_fingerprint"] = frame[
                "mapping_variant"
            ].map(d005_fingerprints)
        persisted[name] = frame
        _atomic_parquet(frame, output / f"{name}.parquet")

    summary = _summary(
        persisted,
        config=config,
        run_metadata=run_metadata,
        implementation=implementation,
    )
    _atomic_json(
        config.snapshot(), output / "configuration_snapshot.json"
    )
    _atomic_json(
        implementation, output / "implementation_provenance.json"
    )
    _atomic_json(
        {
            **run_metadata,
            "study_config_fingerprint": config.fingerprint(),
            "implementation_sha256": implementation[
                "implementation_sha256"
            ],
            "d005_config_fingerprints": d005_fingerprints,
        },
        output / "reproducibility_metadata.json",
    )
    _atomic_json(
        {
            "tables": {
                f"{name}.parquet": _schema(frame)
                for name, frame in persisted.items()
            }
        },
        output / "feature_schema.json",
    )
    _atomic_json(summary, output / "summary.json")
    report = render_report(
        frames=persisted,
        config=config,
        summary=summary,
        run_metadata=run_metadata,
    )
    local_report = (
        output / "D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY_REPORT.md"
    )
    _atomic_text(report, local_report)
    if report_path is not None:
        _atomic_text(report, report_path.resolve())

    artifact_records = []
    for path in sorted(output.iterdir()):
        if path.name == "artifact_manifest.json" or not path.is_file():
            continue
        artifact_records.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "study_id": config.study_id,
        "version": config.version,
        "study_config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation[
            "implementation_sha256"
        ],
        "artifacts": artifact_records,
    }
    _atomic_json(manifest, output / "artifact_manifest.json")
    return {
        "output_dir": str(output),
        "summary": summary,
        "manifest": manifest,
        "report": str(local_report),
    }
