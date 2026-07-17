"""Framework-owned run artifacts and human-readable report rendering."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Mapping


FRAMEWORK_ARTIFACTS = (
    "report.md",
    "summary.json",
    "execution_metadata.json",
    "research_status.json",
    "resolved_configuration.json",
    "run.log.jsonl",
)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_text(
        path,
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
    )


def _bullet_lines(values: list[str], empty_text: str = "None reported.") -> list[str]:
    return [f"- {value}" for value in values] if values else [empty_text]


def render_markdown(summary: Mapping[str, Any]) -> str:
    experiment = summary["experiment"]
    run = summary["run"]
    result = summary.get("result")
    error = summary.get("error")

    lines = [
        f"# {experiment['title']}",
        "",
        f"- Experiment: `{experiment['id']}`",
        f"- Research object: `{experiment['research_object']}`",
        f"- Experiment version: `{experiment['version']}`",
        f"- Run ID: `{run['run_id']}`",
        f"- Execution status: **{run['execution_status']}**",
        f"- Research status: **{run['research_status']}**",
        f"- Started: {run['started_at']}",
        f"- Completed: {run['completed_at']}",
        f"- Output: `{run['output_location']}`",
        "",
        "## Hypothesis",
        "",
        experiment["hypothesis"],
        "",
        "## Measurable definition",
        "",
        experiment["measurable_definition"],
        "",
    ]

    if result:
        lines.extend(
            [
                "## Result",
                "",
                result["summary"],
                "",
                f"Decision rationale: {result['status_rationale']}",
                "",
                "## Statistical evidence",
                "",
                f"- Sample size: {result['sample_size']}",
                "- Bootstrap confidence intervals:",
                "",
                "```json",
                json.dumps(
                    result["bootstrap_confidence_intervals"],
                    indent=2,
                    sort_keys=True,
                    default=str,
                ),
                "```",
                "",
                "### Robustness checks",
                "",
                *_bullet_lines(result["robustness_checks"]),
                "",
                "### Sensitivity analysis",
                "",
                *_bullet_lines(result["sensitivity_analysis"]),
                "",
                "### Data exclusions",
                "",
                *_bullet_lines(result["data_exclusions"]),
                "",
                "### Known limitations",
                "",
                *_bullet_lines(result["limitations"]),
                "",
                "## Findings",
                "",
                *_bullet_lines(result["findings"]),
                "",
                "## Metrics",
                "",
                "```json",
                json.dumps(result["metrics"], indent=2, sort_keys=True, default=str),
                "```",
                "",
            ]
        )
    elif error:
        lines.extend(
            [
                "## Execution failure",
                "",
                f"- Type: `{error['type']}`",
                f"- Message: {error['message']}",
                "",
                "No scientific conclusion was produced. A failed run is never interpreted "
                "as evidence for or against the hypothesis.",
                "",
            ]
        )

    lines.extend(
        [
            "## Resolved configuration",
            "",
            "```json",
            json.dumps(
                summary["resolved_configuration"], indent=2, sort_keys=True, default=str
            ),
            "```",
            "",
            "## Data inputs",
            "",
        ]
    )
    inputs = summary.get("inputs", [])
    if inputs:
        for item in inputs:
            lines.append(
                f"- `{item['source']}:{item['dataset']}` — {item['row_count']} rows, "
                f"SHA-256 `{item['fingerprint']}`"
            )
    else:
        lines.append("No market dataset was loaded through the framework data layer.")
    lines.extend(
        [
            "",
            "## Run artifacts",
            "",
            *[f"- `{name}`" for name in FRAMEWORK_ARTIFACTS],
            "",
        ]
    )
    return "\n".join(lines)


def write_report_bundle(
    *,
    output_dir: Path,
    summary: Mapping[str, Any],
    execution_metadata: Mapping[str, Any],
    research_status: Mapping[str, Any],
    resolved_configuration: Mapping[str, Any],
) -> None:
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "execution_metadata.json", execution_metadata)
    write_json(output_dir / "research_status.json", research_status)
    write_json(output_dir / "resolved_configuration.json", resolved_configuration)
    _atomic_text(output_dir / "report.md", render_markdown(summary))
