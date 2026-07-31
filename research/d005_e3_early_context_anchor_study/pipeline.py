"""End-to-end isolated D005_E3 early-context anchor study."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Sequence

import pandas as pd

from research.context_engine.bars import build_timeframes
from research.context_engine.pipeline import load_one_minute_bars
from research.context_engine.reporting import sha256_file

from .analysis import (
    anchor_forward_summary,
    build_candidate_decomposition,
    build_cohort_overlap,
    build_conditioning_audit,
    build_direction_family_audit,
    build_primary_comparisons,
    build_standard_summaries,
    classify_result,
    earliest_anchor_criteria,
    latency_decay_summary,
)
from .anchors import (
    annotate_causal_context,
    attach_independent_array_anchors,
    build_anchor_event_table,
    load_uncapped_sequences,
)
from .config import EarlyContextAnchorStudyConfig
from .outcomes import (
    annotate_anchor_volatility,
    build_latency_decay,
    calculate_forward_outcomes,
)
from .reporting import directory_fingerprint, persist_artifacts


def _verify_source_files(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    checked: list[dict[str, object]] = []
    for record in records:
        path = Path(str(record["path"]))
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        digest = sha256_file(path) if exists else None
        checked.append(
            {
                **record,
                "exists": exists,
                "observed_bytes": size,
                "observed_sha256": digest,
                "verified": bool(
                    exists
                    and size == int(record["bytes"])
                    and digest == record["sha256"]
                ),
            }
        )
    return checked


def _verify_fixed_e2_conclusions(
    summary: dict[str, object],
) -> dict[str, object]:
    dominant = summary["dominant_cause"]
    diagnostic = dominant["diagnostic_values"]
    checks = {
        "classification_ids_are_2_and_7": (
            dominant["classification_ids"] == [2, 7]
        ),
        "direction_invariants_valid": bool(
            diagnostic["direction_invariants_valid"]
        ),
        "median_capped_latency_about_70m": abs(
            float(diagnostic["median_e1_candidate_to_reaction_minutes"])
            - 70.0
        )
        <= 1.0,
        "candidate_exceeds_reaction_60m": (
            float(diagnostic["e1_candidate_mean_signed_60m"])
            > float(diagnostic["e1_reaction_mean_signed_60m"])
        ),
        "cap_distortion_classified": (
            7 in dominant["classification_ids"]
        ),
    }
    if not all(checks.values()):
        failures = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(
            "Accepted E2 findings differ from the frozen baseline: "
            + ", ".join(failures)
        )
    return checks


def _copy_quality_frames(e1_output: Path) -> dict[str, pd.DataFrame]:
    return {
        "data_quality_periods": pd.read_parquet(
            e1_output / "data_quality_periods.parquet"
        ),
        "excluded_evaluations": pd.read_parquet(
            e1_output / "excluded_evaluations.parquet"
        ),
    }


def run_study(
    *,
    output_dir: Path,
    config: EarlyContextAnchorStudyConfig,
    command: Sequence[str] = (),
) -> dict[str, object]:
    config.validate()
    started = perf_counter()
    output_dir = output_dir.resolve()
    protected = {
        "d005": Path(config.d005_output).resolve(),
        "e1": Path(config.e1_output).resolve(),
        "e2": Path(config.e2_output).resolve(),
    }
    if output_dir in set(protected.values()):
        raise ValueError("E3 output cannot overwrite D005, E1, or E2")
    for name, path in protected.items():
        if not path.is_dir():
            raise FileNotFoundError(
                f"Required protected {name.upper()} output is absent: {path}"
            )
    fingerprints_before = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }

    e2_summary = json.loads(
        (protected["e2"] / "summary.json").read_text(encoding="utf-8")
    )
    e2_reproducibility = json.loads(
        (
            protected["e2"] / "reproducibility_metadata.json"
        ).read_text(encoding="utf-8")
    )
    fixed_e2_checks = _verify_fixed_e2_conclusions(e2_summary)
    source_records = list(e2_reproducibility["source_files"])
    verified_sources = _verify_source_files(source_records)
    mismatches = [
        item for item in verified_sources if not item["verified"]
    ]
    if mismatches:
        raise RuntimeError(
            "E3 source hash verification failed: "
            + ", ".join(str(item["path"]) for item in mismatches[:10])
        )

    source = Path(str(e2_reproducibility["source"]))
    one_minute_raw, provenance = load_one_minute_bars(
        source,
        start_date=config.start_date,
        end_date=config.end_date,
        lookback_days=max(
            variant.warmup_days for variant in config.mapping_variants
        ),
    )
    expected_selection = e2_reproducibility[
        "source_selection_sha256"
    ]
    if provenance["selection_sha256"] != expected_selection:
        raise RuntimeError("E3 source selection differs from accepted E2")
    if int(provenance["row_count"]) != int(
        e2_reproducibility["source_row_count"]
    ):
        raise RuntimeError("E3 source row count differs from accepted E2")
    timeframes = build_timeframes(one_minute_raw)

    sequences = load_uncapped_sequences(protected["e2"])
    sequences = annotate_causal_context(
        sequences, timeframes=timeframes, config=config
    )
    sequences = attach_independent_array_anchors(
        sequences, e1_output=protected["e1"], config=config
    )
    anchors, anchor_deduplication = build_anchor_event_table(
        sequences, config=config
    )
    anchors = annotate_anchor_volatility(
        anchors, timeframes["1D"], config=config
    )
    if anchors.duplicated(["sequence_id", "anchor_type"]).any():
        raise RuntimeError("E3 anchor uniqueness invariant failed")
    if anchors["anchor_selected_using_later_completion"].any():
        raise RuntimeError("E3 main anchors contain future selection")
    forward = calculate_forward_outcomes(
        anchors, timeframes["1min"], config=config
    )
    latency = build_latency_decay(anchors, timeframes["1min"])
    anchor_summary = anchor_forward_summary(forward, config=config)
    standard = build_standard_summaries(forward, config=config)
    primary = build_primary_comparisons(forward, config=config)
    if len(primary) != 60:
        raise RuntimeError("E3 registered primary family is not 60 cells")
    criteria = earliest_anchor_criteria(primary, config=config)
    decomposition = build_candidate_decomposition(
        forward, config=config
    )
    conditioning = build_conditioning_audit(
        forward, config=config
    )
    direction_audit, direction_summary = build_direction_family_audit(
        sequences
    )
    membership, overlap = build_cohort_overlap(sequences)
    latency_summary_frame = latency_decay_summary(latency, forward)
    classification = classify_result(
        primary=primary,
        criteria=criteria,
        forward=forward,
        config=config,
    )
    if classification["primary_classification_id"] not in range(1, 7):
        raise RuntimeError("E3 classification is outside categories 1-6")

    confidence = anchor_summary[
        [
            "mapping_variant",
            "outcome",
            "anchor_type",
            "horizon",
            "forward_observations",
            "mean_signed_movement",
            "standard_error",
            "mean_ci_lower",
            "mean_ci_upper",
            "confidence_level",
        ]
    ].copy()
    quality = _copy_quality_frames(protected["e1"])
    fvg_events = pd.read_parquet(
        protected["e1"] / "fvg_event_statistics.parquet",
        columns=["event_id"],
    )
    ob_events = pd.read_parquet(
        protected["e1"] / "order_block_event_statistics.parquet",
        columns=["event_id", "variant"],
    )
    ob_counts = {
        str(key): int(value)
        for key, value in ob_events["variant"].value_counts().items()
    }
    frames = {
        "anchor_events": anchors,
        "unique_sequences": sequences,
        "anchor_forward_outcomes": forward,
        "anchor_forward_summary": anchor_summary,
        "latency_decay": latency,
        "latency_decay_summary": latency_summary_frame,
        "candidate_anchor_decomposition": decomposition,
        "multiplicity_adjusted_comparisons": primary,
        "confidence_intervals": confidence,
        "causal_conditioning_audit": conditioning,
        "direction_family_audit": direction_audit,
        "direction_family_summary": direction_summary,
        "cohort_membership": membership,
        "cohort_overlap": overlap,
        "earliest_anchor_criteria": criteria,
        **standard,
        **quality,
    }

    fingerprints_after_compute = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }
    if fingerprints_after_compute != fingerprints_before:
        raise RuntimeError(
            "A protected D005/E1/E2 artifact changed during E3 computation"
        )
    source_provenance = {
        "source": str(source.resolve()),
        "requested_start_date": config.start_date.isoformat(),
        "requested_end_date": config.end_date.isoformat(),
        "lookback_days": max(
            variant.warmup_days for variant in config.mapping_variants
        ),
        "file_count": len(verified_sources),
        "row_count": int(provenance["row_count"]),
        "selection_sha256": provenance["selection_sha256"],
        "hash_mismatch_count": len(mismatches),
        "read_only": True,
        "files": verified_sources,
    }
    run_metadata = {
        "command": list(command)
        or [
            sys.executable,
            "-m",
            "research.d005_e3_early_context_anchor_study",
        ],
        "runtime_seconds_before_persistence": perf_counter() - started,
        "source_file_count": len(verified_sources),
        "source_row_count": int(provenance["row_count"]),
        "source_selection_sha256": provenance["selection_sha256"],
        "source_hash_mismatch_count": len(mismatches),
        "protected_paths": {
            name: str(path) for name, path in protected.items()
        },
        "protected_fingerprints_before": fingerprints_before,
        "protected_fingerprints_after_compute": fingerprints_after_compute,
        "protected_artifacts_preserved": True,
        "accepted_e2_checks": fixed_e2_checks,
        "accepted_e2_implementation_sha256": e2_summary[
            "implementation_sha256"
        ],
        "accepted_e2_config_fingerprint": e2_summary[
            "study_config_fingerprint"
        ],
        "accepted_e2_candidate_deduplication": dict(
            e2_reproducibility["deduplication_counts"]
        ),
        "e3_event_cap": None,
        "sequence_rows_loaded": len(sequences),
        "anchor_deduplication": anchor_deduplication,
        "raw_fvg_event_count": len(fvg_events),
        "ob_variant_event_counts": ob_counts,
        "quality_source": str(protected["e1"]),
    }
    summary = persist_artifacts(
        frames=frames,
        output_dir=output_dir,
        config=config,
        run_metadata=run_metadata,
        source_provenance=source_provenance,
        classification=classification,
    )
    fingerprints_after = {
        name: directory_fingerprint(path)
        for name, path in protected.items()
    }
    if fingerprints_after != fingerprints_before:
        raise RuntimeError(
            "A protected D005/E1/E2 artifact changed during E3 persistence"
        )
    return summary


__all__ = ["run_study"]
