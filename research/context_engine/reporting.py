"""Artifact persistence and research-only reporting for D005."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

import pandas as pd

from .config import ContextEngineConfig
from .engine import EvaluationResult
from .models import EvidenceEvent


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _events_frame(
    observations: Sequence[tuple[EvidenceEvent, str, str]],
) -> pd.DataFrame:
    records_by_observation: dict[str, dict[str, object]] = {}
    for event, evaluation_at, mapping_name in observations:
        observation_key = (
            f"{event.event_id}|{evaluation_at}|{mapping_name}".encode("utf-8")
        )
        observation_id = hashlib.sha256(observation_key).hexdigest()[:24]
        records_by_observation[observation_id] = {
            "observation_id": observation_id,
            "evaluation_at": evaluation_at,
            "mapping_name": mapping_name,
            **event.to_record(),
        }
    records = list(records_by_observation.values())
    if not records:
        return pd.DataFrame(
            columns=[
                "observation_id",
                "evaluation_at",
                "mapping_name",
                "event_id",
                "event_type",
                "direction",
                "timeframe",
                "variant",
                "taxonomy",
                "created_at",
                "available_at",
                "source_rule_ids",
                "parameters",
                "level",
                "zone_low",
                "zone_high",
                "interacted_at",
                "confirmed_at",
                "invalidated_at",
            ]
        )
    return pd.DataFrame.from_records(records).sort_values(
        ["evaluation_at", "mapping_name", "available_at", "event_id"],
        kind="mergesort",
    )


def _observations(
    results: Sequence[EvaluationResult],
    attribute: str,
) -> list[tuple[EvidenceEvent, str, str]]:
    return [
        (
            event,
            result.snapshot.evaluation_at.isoformat(),
            result.snapshot.mapping_name,
        )
        for result in results
        for event in getattr(result, attribute)
    ]


def _implementation_provenance(config: ContextEngineConfig) -> dict[str, object]:
    package = Path(__file__).resolve().parent
    files: list[tuple[str, Path]] = [
        (f"research/context_engine/{path.name}", path)
        for path in sorted(package.glob("*.py"))
    ]
    catalog = Path(config.source_rule_catalog)
    if not catalog.is_absolute():
        catalog = Path.cwd() / catalog
    if catalog.is_file():
        files.append((config.source_rule_catalog, catalog.resolve()))
    records = [
        {
            "path": label,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for label, path in files
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


def persist_research_results(
    results: Sequence[EvaluationResult],
    *,
    output_dir: Path,
    config: ContextEngineConfig,
    input_provenance: dict[str, object],
    command: Sequence[str] = (),
    report_path: Path | None = None,
) -> dict[str, object]:
    """Write only D005 research artifacts beneath the selected output."""

    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshots = pd.DataFrame.from_records(
        [result.snapshot.to_record() for result in results]
    )
    if not snapshots.empty:
        snapshots = snapshots.sort_values(
            ["evaluation_at", "mapping_name"], kind="mergesort"
        )
    fvgs = _events_frame(_observations(results, "fvg_events"))
    obs = _events_frame(_observations(results, "order_block_events"))
    liquidity = _events_frame(_observations(results, "liquidity_events"))
    confirmations = _events_frame(_observations(results, "confirmation_events"))
    conflicts = _events_frame(_observations(results, "conflict_events"))
    transition_records = [
        {
            **transition.to_record(),
            "evaluation_at": result.snapshot.evaluation_at.isoformat(),
            "mapping_name": result.snapshot.mapping_name,
        }
        for result in results
        for transition in result.snapshot.transitions
    ]
    transitions = pd.DataFrame.from_records(
        transition_records,
        columns=(
            "from_state",
            "to_state",
            "occurred_at",
            "reason",
            "evidence_ids",
            "evaluation_at",
            "mapping_name",
        ),
    )
    implementation = _implementation_provenance(config)
    frames = {
        "context_snapshots.parquet": snapshots,
        "fvg_events.parquet": fvgs,
        "order_block_events.parquet": obs,
        "liquidity_events.parquet": liquidity,
        "confirmation_events.parquet": confirmations,
        "conflicts.parquet": conflicts,
        "state_transitions.parquet": transitions,
    }
    for frame in frames.values():
        frame["d005_version"] = config.d005_version
        frame["config_fingerprint"] = config.fingerprint()
        frame["implementation_sha256"] = implementation[
            "implementation_sha256"
        ]
    for filename, frame in frames.items():
        _atomic_parquet(frame, output / filename)

    state_counts = (
        snapshots["state"].value_counts(dropna=False).sort_index().to_dict()
        if not snapshots.empty
        else {}
    )
    outcome_counts = (
        snapshots["outcome"].value_counts(dropna=False).sort_index().to_dict()
        if not snapshots.empty
        else {}
    )
    ob_variant_statistics = {}
    if not obs.empty:
        for variant, group in obs.groupby("variant", sort=True):
            ob_variant_statistics[str(variant)] = {
                "unique_detections": int(group["event_id"].nunique()),
                "observations": int(len(group)),
                "unique_interactions": int(
                    group.loc[group["interacted_at"].notna(), "event_id"].nunique()
                ),
                "unique_confirmations": int(
                    group.loc[group["confirmed_at"].notna(), "event_id"].nunique()
                ),
                "unique_invalidations": int(
                    group.loc[group["invalidated_at"].notna(), "event_id"].nunique()
                ),
            }
    summary = {
        "d005_version": config.d005_version,
        "research_only": True,
        "entry_authorized_count": int(
            snapshots["entry_authorized"].fillna(False).sum()
        )
        if not snapshots.empty
        else 0,
        "snapshot_count": int(len(snapshots)),
        "state_counts": {str(key): int(value) for key, value in state_counts.items()},
        "outcome_counts": {
            str(key): int(value) for key, value in outcome_counts.items()
        },
        "conflict_count": int(conflicts["event_id"].nunique()) if not conflicts.empty else 0,
        "conflict_observation_count": int(len(conflicts)),
        "fvg_event_count": int(fvgs["event_id"].nunique()) if not fvgs.empty else 0,
        "fvg_observation_count": int(len(fvgs)),
        "order_block_event_count": int(obs["event_id"].nunique()) if not obs.empty else 0,
        "order_block_observation_count": int(len(obs)),
        "order_block_variant_counts": {
            str(key): int(value)
            for key, value in obs.groupby("variant", sort=True)["event_id"].nunique().items()
        }
        if not obs.empty
        else {},
        "order_block_variant_statistics": ob_variant_statistics,
        "liquidity_event_count": int(liquidity["event_id"].nunique()) if not liquidity.empty else 0,
        "liquidity_observation_count": int(len(liquidity)),
        "confirmation_event_count": int(confirmations["event_id"].nunique()) if not confirmations.empty else 0,
        "confirmation_observation_count": int(len(confirmations)),
        "config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation["implementation_sha256"],
        "d004_guardrail": "The 08:30-09:00 New York window has no robust standalone directional edge in D004 and is not a D005 directional rule.",
        "production_behavior_changed": False,
    }
    _atomic_json(config.snapshot(), output / "configuration_snapshot.json")
    _atomic_json(implementation, output / "implementation_provenance.json")
    _atomic_json(
        {
            "tables": {
                filename: _schema(frame) for filename, frame in frames.items()
            }
        },
        output / "feature_schema.json",
    )
    _atomic_json(summary, output / "summary.json")
    _atomic_json(
        {
            "input": input_provenance,
            "command": list(command),
            "config_fingerprint": config.fingerprint(),
            "implementation_sha256": implementation[
                "implementation_sha256"
            ],
        },
        output / "reproducibility_metadata.json",
    )

    report = render_report(summary, config, input_provenance)
    local_report = output / "D005_CONTEXT_ENGINE_RESEARCH_REPORT.md"
    _atomic_text(report, local_report)
    if report_path is not None:
        _atomic_text(report, report_path.resolve())

    manifest_records = []
    for path in sorted(output.iterdir()):
        if path.name == "artifact_manifest.json" or not path.is_file():
            continue
        manifest_records.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "d005_version": config.d005_version,
        "config_fingerprint": config.fingerprint(),
        "implementation_sha256": implementation["implementation_sha256"],
        "artifacts": manifest_records,
    }
    _atomic_json(manifest, output / "artifact_manifest.json")
    return {
        "output_dir": str(output),
        "summary": summary,
        "manifest": manifest,
        "report": str(local_report),
    }


def render_report(
    summary: dict[str, object],
    config: ContextEngineConfig,
    input_provenance: dict[str, object],
) -> str:
    state_rows = "\n".join(
        f"| `{name}` | {count} |"
        for name, count in sorted(summary["state_counts"].items())
    ) or "| _none_ | 0 |"
    outcome_rows = "\n".join(
        f"| `{name}` | {count} |"
        for name, count in sorted(summary["outcome_counts"].items())
    ) or "| _none_ | 0 |"
    ob_rows = "\n".join(
        "| `{name}` | {unique_detections} | {observations} | "
        "{unique_interactions} | {unique_confirmations} | "
        "{unique_invalidations} |".format(name=name, **statistics)
        for name, statistics in sorted(
            summary["order_block_variant_statistics"].items()
        )
    ) or "| _none_ | 0 | 0 | 0 | 0 | 0 |"
    return f"""# D005 Context Engine Research Report

## Scope

This output is an isolated research artifact. It does not change production
strategy defaults, signals, execution, risk, or live behavior. Every snapshot
has `entry_authorized=false`.

The D004 guardrail remains active: the `[08:30,09:00) America/New_York`
window did not show a robust standalone directional edge and is not used here
as a directional rule. No 09:30 NYSE, 10:00 Key Open, index PO3, RTH, ES, NQ,
NAS100, or SP500 timing behavior is transferred to XAUUSD.

## Configuration

- Version: `{config.d005_version}`
- Config fingerprint: `{config.fingerprint()}`
- Implementation fingerprint: `{summary["implementation_sha256"]}`
- Primary mapping: `{config.primary_mapping}`
- Optional 1m refinement: `{config.optional_1m_refinement}`
- Premarket interval: `[{config.premarket.start},{config.premarket.end}) {config.premarket.timezone}`
- MSS variant: `{config.mss.name}`
- Displacement variant: `{config.displacement.name}`
- Research source: `{input_provenance.get("source", "unspecified")}`
- Selected input files / rows: `{input_provenance.get("file_count", "unspecified")}` / `{input_provenance.get("row_count", "unspecified")}`
- Requested session dates: `{input_provenance.get("requested_start_date", "open")}` through `{input_provenance.get("requested_end_date", "open")}`
- Input selection SHA-256: `{input_provenance.get("selection_sha256", "unspecified")}`

## Snapshot states

| State | Count |
|---|---:|
{state_rows}

## Outcome labels

| Outcome | Count |
|---|---:|
{outcome_rows}

## Order Block variants

| Variant | Unique detections | Observations | Unique interactions | Unique confirmations | Unique invalidations |
|---|---:|---:|---:|---:|---:|
{ob_rows}

No aggregate `valid_ob` field is produced.

## Event totals

- Snapshots: {summary["snapshot_count"]}
- FVG events / observations: {summary["fvg_event_count"]} / {summary["fvg_observation_count"]}
- OB events / observations: {summary["order_block_event_count"]} / {summary["order_block_observation_count"]}
- Liquidity events / observations: {summary["liquidity_event_count"]} / {summary["liquidity_observation_count"]}
- Confirmation events / observations: {summary["confirmation_event_count"]} / {summary["confirmation_observation_count"]}
- Conflicts / observations: {summary["conflict_count"]} / {summary["conflict_observation_count"]}
- Entry authorizations: {summary["entry_authorized_count"]}

## Interpretation

Counts describe engine evidence coverage only. They are not expectancy,
profitability, or production-promotion evidence. `reaction_confirmed` records
completion of the configured research sequence and remains non-executable.

## Limitations

- Source concepts remain discretionary and are represented by named variants.
- This report does not establish an XAUUSD timing edge.
- PMH/PML is a category B/C clue and cannot override valid HTF context.
- A separate preregistered outcome study is required before any predictive
  interpretation.
"""
