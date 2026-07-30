"""Persistence and report rendering for D003_E1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .audit import sha256_file


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            _json_safe(value),
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def write_frame(output: Path, name: str, frame: pd.DataFrame) -> None:
    frame.to_parquet(output / f"{name}.parquet", index=False)


def _table(frame: pd.DataFrame, columns: list[str]) -> str:
    display = frame[columns].copy()
    def cell(value: object) -> str:
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        return str(value).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [
        "| " + " | ".join(cell(value) for value in row) + " |"
        for row in display.itertuples(index=False, name=None)
    ]
    return "\n".join([header, divider, *rows])


def build_report(
    *,
    inventory: pd.DataFrame,
    schema: pd.DataFrame,
    comparison: dict[str, pd.DataFrame],
    gaps: pd.DataFrame,
    duplicates: pd.DataFrame,
    timezone_audit: dict[str, object],
    compatibility: dict[str, object],
    historical: dict[str, object],
    build_summary: dict[str, object],
    summary: dict[str, object],
) -> str:
    overlap = comparison["overlap_summary"].iloc[0]
    dist = comparison["feed_distributions"]
    gap_counts = gaps["gap_classification"].value_counts().to_dict()
    blockers = "\n".join(
        f"- {reason}" for reason in compatibility["blocking_reasons"]
    )
    return f"""# D003_E1 2026 Canonical Extension Gate

## Decision

**D003 compatibility class {compatibility['classification_id']}: {compatibility['classification_label']}.**

Stage A passed: `{compatibility['stage_a_passed']}`  
Stage B permitted: `{compatibility['stage_b_permitted']}`

The post-2025 source is useful only as a separately labeled MT5/unknown-broker
feed. It is not a valid extension of the Dukascopy-derived D003 release.

## Source and provenance

{_table(inventory, ['path', 'role', 'source_type', 'broker_or_feed_provenance', 'timezone', 'row_count', 'file_size_bytes', 'sha256', 'post_2025_candidate'])}

The raw tick export is the controlling source. Existing normalized tick and
one-minute CSVs are read-only derivatives from the earlier isolated
event-study normalizer; they are not D003 outputs.

## Blocking contract differences

{blockers}

{_table(schema, ['column', 'required_type', 'required_nullable', 'candidate_evidence', 'reconstructable_without_inference', 'contract_satisfied'])}

The raw `<VOLUME>` field is empty throughout the validated source. M15
tick-volume counts cannot be allocated to individual bid/ask ticks and are not
native side volumes. Writing zeros, nulls, copied M15 counts, or inferred side
volumes would violate the non-nullable D003 contract.

## Timezone and DST

- Raw timestamp marker present: `{timezone_audit['file_contains_timezone_marker']}`
- Selected interpretation: `{timezone_audit['source_timezone']}`
- Evidence grade: `{timezone_audit['confidence_grade']}`
- Broker-authenticated: `{timezone_audit['broker_authenticated']}`
- Winter behavior: `{timezone_audit['winter_behavior']}`
- Summer behavior: `{timezone_audit['summer_behavior']}`
- U.S./Europe mismatch behavior: `{timezone_audit['dst_mismatch_behavior']}`

The Europe/Helsinki interpretation is strongly supported by multi-event and
seasonal alignment. It is still an inference because the export and available
documentation do not identify the broker or server timezone.

## True-overlap feed comparison

- D003 overlap minutes: `{int(overlap['d003_overlap_minutes'])}`
- MT5 overlap minutes: `{int(overlap['mt5_overlap_minutes'])}`
- Exact common UTC minutes: `{int(overlap['common_minutes'])}`
- Coverage Jaccard: `{float(overlap['coverage_jaccard']):.6f}`
- Median absolute mid-close difference: `{float(overlap['abs_mid_close_diff_median']):.6f}`
- P95 absolute mid-close difference: `{float(overlap['abs_mid_close_diff_p95']):.6f}`
- One-minute return correlation: `{float(overlap['one_minute_return_correlation']):.6f}`
- MT5/D003 median-spread ratio: `{float(overlap['median_spread_ratio_mt5_to_d003']):.6f}`
- MT5/D003 median tick-count ratio: `{float(overlap['median_tick_count_ratio_mt5_to_d003']):.6f}`

{_table(dist, ['feed', 'minute_rows', 'duplicate_minutes', 'gaps_over_one_minute', 'absolute_1m_return_median', 'mid_bar_range_median', 'median_spread_median', 'tick_count_median'])}

These differences are consistent with different broker/feed composition.
Price similarity or sign consistency cannot establish Dukascopy provenance.

## Missing periods, duplicates, and sessions

- Detected gaps over one populated minute: `{len(gaps)}`
- Gap classifications: `{json.dumps(gap_counts, sort_keys=True)}`
- Normalized duplicate minute timestamps:
  `{int(duplicates.loc[duplicates['level'].eq('normalized_minute_timestamp'), 'duplicate_count'].iloc[0])}`
- Raw same-millisecond timestamp rows: `1,091,679`

Raw same-millisecond observations are not automatically exact duplicates.
D003 exact identity cannot be reproduced because it includes native bid and
ask volumes, which are absent.

## Historical release integrity

- Release: `{historical['release_id']}`
- Declared rows: `{historical['declared_rows']}`
- Declared files: `{historical['declared_files']}`
- Hash mismatches: `{len(historical['mismatches'])}`
- Missing files: `{len(historical['missing_files'])}`
- Verification passed: `{historical['verified']}`

## Canonical build

- Candidate release: `{build_summary['candidate_release_id']}`
- Build attempted: `{build_summary['canonical_build_attempted']}`
- Canonical rows: `{build_summary['canonical_row_count']}`
- Canonical Parquet files: `{build_summary['canonical_file_count']}`
- Deterministic canonical rebuild established:
  `{build_summary['deterministic_canonical_rebuild_established']}`
- Reason: `{build_summary['reason']}`

No candidate Parquet or release directory was created. The build stopped
before transformation because passing the D003 schema would require
fabricating native volume fields and bypassing the frozen BI5 pipeline.

## Stage B and hard replication classification

**Category {summary['replication_classification_id']}: {summary['replication_classification_label']}.**

No post-2025 D005 sequence, displacement anchor, refinement anchor, MFE, MAE,
or price outcome was calculated. Sample sufficiency and effect replication are
therefore not evaluated.

## Recommendation

Obtain hash-verified post-2025 Dukascopy BI5 partitions through D001/D002 and
build a new D003 release with the frozen builder and verifier. Alternatively,
obtain an authenticated same-feed tick export containing native bid and ask
volumes plus explicit timezone provenance. Resolve feed compatibility before
any independent E4 or entry-feasibility research.
"""


def build_artifact_manifest(output: Path) -> dict[str, object]:
    records = []
    for path in sorted(item for item in output.iterdir() if item.is_file()):
        if path.name == "artifact_manifest.json":
            continue
        records.append(
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "manifest_version": 1,
        "artifact_count": len(records),
        "files": records,
    }
