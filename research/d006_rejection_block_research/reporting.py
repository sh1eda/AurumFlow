"""Atomic, manifest-bound reporting for the frozen D006 historical execution."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Mapping

import numpy as np
import pandas as pd

from .schemas import validate_aggregate_audit


OUTPUT_DIRECTORY = Path("research_outputs/D006_REJECTION_BLOCK_RESEARCH")
REPORT_NAME = "D006_REJECTION_BLOCK_RESEARCH_REPORT.md"


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    if value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        timestamp = pd.Timestamp(value)
        return timestamp.isoformat() if not pd.isna(timestamp) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"cannot encode D006 value: {type(value).__name__}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, default=_json_default, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd", version="2.6")


def _fmt(value: object) -> str:
    if value is None:
        return "NOT_EVALUATED"
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def render_report(result: Mapping[str, object]) -> str:
    """Render the exact frozen hierarchy and non-production disposition wording."""

    integrity = result["integrity"]
    adequacy = result["sample_adequacy"]
    structural = result["primary_structural_claim"]
    primary = result["primary_empirical_claim"]
    lines = [
        "# D006 Rejection-Block Structural and Empirical Research",
        "",
        "D006 is a research-only component study. It makes no production-suitability decision and does not select a composite strategy.",
        "",
        "## 1. Definition and provenance",
        "",
        f"- Specification SHA-256: `{result['spec_sha256']}`",
        f"- Configuration fingerprint: `{result['config_fingerprint']}`",
        "- Definition family: `single_wick_50_d3_v1`, `cluster2_wick_50_d3_v1`.",
        "- Quantitative operationalizations remain the frozen D006 preregistration; no parameter was fitted or searched.",
        "",
        "## 2. Integrity",
        "",
        f"- Status: **{integrity['status']}**",
        f"- Reproducibility fingerprint match: `{integrity['reproducibility_match']}`",
        f"- 2026 rows selected: `{integrity['selected_2026_rows']}`",
        f"- Protected inputs preserved: `{integrity['protected_inputs_preserved']}`",
        "",
        "## 3. Sample adequacy",
        "",
        f"- Status: **{adequacy['status']}**",
    ]
    for name, values in sorted(adequacy["requirements"].items()):
        lines.append(f"- `{name}`: observed `{_fmt(values['observed'])}`, required `{_fmt(values['required'])}`, pass `{values['passed']}`.")
    lines.extend([
        "",
        "## 4. Primary structural claim",
        "",
        f"- Status: **{structural['status']}**",
        f"- Detected blocks: `{result['aggregate_audit']['detected']}`.",
        f"- Stable ordered bytes: `{structural['stable_ordered_bytes']}`.",
        "",
        "## 5. Data applicability, interval, and lifecycle audit",
        "",
        "- Source: frozen D003-v2 canonical mid ticks and verified release metadata.",
        "- Calibration/warm-up: 2021 only.",
        "- Rolling validation: 2022, 2023, 2024, 2025.",
        "- Outcome-known 2026 interval: explicitly excluded.",
        "- Future blind interval: none.",
        f"- Selected canonical files: `{result['source_audit']['selected_file_count']}`.",
        f"- Selected canonical rows: `{result['source_audit']['selected_row_count']}`.",
        "",
        f"- Lifecycle eligible: `{result['aggregate_audit']['lifecycle_eligible']}`.",
        f"- Touched / untouched: `{result['aggregate_audit']['touched']}` / `{result['aggregate_audit']['untouched']}`.",
        f"- Mitigated / invalidated / expired / active-censored: `{result['aggregate_audit']['mitigated']}` / `{result['aggregate_audit']['invalidated']}` / `{result['aggregate_audit']['expired']}` / `{result['aggregate_audit']['active_censored']}`.",
        f"- Overlapping / nested: `{result['aggregate_audit']['overlapping']}` / `{result['aggregate_audit']['nested']}`.",
        f"- Structural first-failure exclusions: `{result['aggregate_audit']['exclusions_by_reason']}`.",
        f"- Primary endpoint/control first-failure exclusions: `{result['aggregate_audit']['primary_exclusions_by_reason']}`.",
        "",
    ])
    lines.extend(
        [
            "",
            "## 6. Primary empirical claim",
            "",
            f"- Status: **{primary['status']}**",
            f"- Reporting mode: `{primary['mode']}`",
            f"- Pairs: `{_fmt(primary.get('n'))}`.",
            f"- Mean paired direction-aligned difference: `{_fmt(primary.get('mean'))}` XAUUSD price units.",
            f"- 95% interval: `[{_fmt(primary.get('ci_lower'))}, {_fmt(primary.get('ci_upper'))}]`.",
            f"- Two-sided paired p-value: `{_fmt(primary.get('p_value'))}`.",
            f"- Trading-date bootstrap lower bound: `{_fmt(primary.get('bootstrap_ci_lower'))}`.",
            f"- Temporal stability: `{primary.get('temporal_stability_passed', False)}`.",
            "",
            "## 7. Controls",
            "",
        ]
    )
    for name, values in sorted(result["controls"].items()):
        lines.append(f"- `{name}`: pairs `{_fmt(values.get('n'))}`, mean difference `{_fmt(values.get('mean'))}`, q-value `{_fmt(values.get('q_value'))}`.")
    lines.extend(["", "## 8. Interactions", ""])
    for name, values in sorted(result["interactions"].items()):
        lines.append(f"- `{name}`: role `{values.get('classification')}`, status `{values.get('status')}`, pairs `{_fmt(values.get('n'))}`, q-value `{_fmt(values.get('q_value'))}`.")
    lines.extend(["", "## 9. Redundancy", ""])
    for name, values in sorted(result["redundancy"].items()):
        lines.append(f"- `{name}`: causal-time overlap count `{_fmt(values.get('overlap_count'))}`, denominator `{_fmt(values.get('denominator'))}`, rate `{_fmt(values.get('overlap_rate'))}`; price-eligible `{_fmt(values.get('price_eligible_count'))}`, price-zone overlap `{_fmt(values.get('price_overlap_count'))}`, price-zone rate `{_fmt(values.get('price_overlap_rate'))}`.")
    lines.extend(["", "## 10. Geometry", ""])
    for name, values in sorted(result["geometry"].items()):
        lines.append(f"- `{name}`: eligible `{_fmt(values.get('eligible'))}`, touched `{_fmt(values.get('touched'))}`, touch rate `{_fmt(values.get('touch_rate'))}`, improvement `{values.get('improvement_passed', False)}`.")
    lines.extend(["", "## 11. Year, direction, session, and volatility stability", ""])
    for name, values in sorted(result["stability"].items()):
        lines.append(f"- `{name}`: n `{_fmt(values.get('n'))}`, mean `{_fmt(values.get('mean'))}`, interval `[{_fmt(values.get('ci_lower'))}, {_fmt(values.get('ci_upper'))}]`.")
    lines.extend(
        [
            "",
            "## 12. Preregistered secondary results",
            "",
            "All secondary families retain their frozen membership and Benjamini-Hochberg correction, including NOT_EVALUATED cells.",
            "",
            "## 13. Exploratory diagnostics",
            "",
            "Exploratory diagnostics are descriptive only and did not determine acceptance or disposition.",
            "",
            "## 14. Limitations",
            "",
            "- This is historical rolling-origin component research, not an independent or blind replication.",
            "- The 2026 interval is outcome-known and excluded.",
            "- Missing context is unavailable, never imputed as neutral.",
            "- D006 evaluates price movement and geometry only; it does not establish production suitability.",
            "",
            "## 15. Component disposition",
            "",
            f"**{result['component_disposition']}**",
            "",
            "## 16. Recommendation for later composite research",
            "",
            str(result["recommendation"]),
            "",
        ]
    )
    if adequacy["status"] != "SAMPLE_ADEQUATE":
        lines.insert(
            2,
            "**SAMPLE INADEQUATE: all numerical results are descriptive and non-decisional; the primary empirical claim is NOT_EVALUATED and no metric is evidence of edge.**",
        )
        lines.insert(3, "")
    return "\n".join(lines)


def publish_results(
    root: Path,
    *,
    result: Mapping[str, object],
    tables: Mapping[str, pd.DataFrame],
    output_relative: Path = OUTPUT_DIRECTORY,
) -> Path:
    """Publish a complete D006 package atomically and refuse overwrite."""

    validate_aggregate_audit(result["aggregate_audit"])
    output = (root / output_relative).resolve()
    root_resolved = root.resolve()
    if root_resolved not in output.parents or output == root_resolved:
        raise ValueError("D006 output must remain inside the repository")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite D006 output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".d006-stage-", dir=output.parent))
    try:
        _write_json(stage / "source_audit.json", result["source_audit"])
        _write_json(stage / "aggregate_audit.json", result["aggregate_audit"])
        _write_json(stage / "statistical_validation.json", result["statistical_validation"])
        _write_json(stage / "summary.json", result)
        _write_json(stage / "run_manifest.json", result["run_manifest"])
        (stage / REPORT_NAME).write_text(render_report(result), encoding="utf-8")
        for name, frame in sorted(tables.items()):
            if not name.endswith(".parquet") or Path(name).name != name:
                raise ValueError(f"unsafe D006 table name: {name}")
            _write_parquet(stage / name, frame)
        artifacts = []
        for path in sorted(item for item in stage.iterdir() if item.name != "artifact_manifest.json"):
            artifacts.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        manifest = {"schema_version": "d006-artifact-manifest-v1", "artifacts": artifacts}
        _write_json(stage / "artifact_manifest.json", manifest)
        os.replace(stage, output)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    verify_results(output)
    return output


def verify_results(output: Path) -> dict[str, object]:
    """Verify exact output membership and every manifest-bound artifact byte."""

    manifest_path = output / "artifact_manifest.json"
    if output.is_symlink() or not output.is_dir() or not manifest_path.is_file():
        raise ValueError("D006 output namespace is invalid")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("D006 artifact manifest is invalid")
    expected = {record["path"] for record in records} | {"artifact_manifest.json"}
    observed = {path.name for path in output.iterdir() if path.is_file() and not path.is_symlink()}
    if expected != observed:
        raise ValueError("D006 artifact membership mismatch")
    for record in records:
        path = output / record["path"]
        if path.stat().st_size != record["bytes"] or sha256_file(path) != record["sha256"]:
            raise ValueError(f"D006 artifact mismatch: {record['path']}")
    aggregate = json.loads((output / "aggregate_audit.json").read_text(encoding="utf-8"))
    validate_aggregate_audit(aggregate)
    return {"verified": True, "artifact_count": len(records) + 1, "manifest_sha256": sha256_file(manifest_path)}


__all__ = ["OUTPUT_DIRECTORY", "REPORT_NAME", "publish_results", "render_report", "sha256_file", "verify_results"]
