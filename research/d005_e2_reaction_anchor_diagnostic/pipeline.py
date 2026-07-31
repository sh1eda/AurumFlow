"""End-to-end isolated D005_E2 reaction-anchor diagnostic."""

from __future__ import annotations

from datetime import date
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
    anchor_outcome_summary,
    attach_evidence_signatures,
    build_direction_audit,
    cap_state_direction_distribution,
    cap_sensitivity,
    classify_dominant_cause,
    confirmation_cohort_summary,
    latency_summary,
    principal_anchor_summary,
    sequence_funnel,
    weekly_diagnostics,
)
from .config import ReactionAnchorDiagnosticConfig
from .outcomes import (
    build_anchor_inventory,
    calculate_forward_outcomes,
    sequence_latency_outcomes,
)
from .reconstruction import (
    attach_first_refinement_interaction,
    build_candidate_inventory,
    confirmation_inventory,
    evaluate_uncapped_core_snapshots,
    load_e1_event_inventory,
    reconstruct_e1_capped_sequences,
    reconstruct_uncapped_sequences,
)
from .reporting import directory_fingerprint, persist_artifacts


def _verify_e1_sources(
    e1_reproducibility: dict[str, object],
) -> tuple[int, list[str]]:
    mismatches: list[str] = []
    files = e1_reproducibility["input_provenance"]["files"]
    for record in files:
        path = Path(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(record["bytes"])
            or sha256_file(path) != record["sha256"]
        ):
            mismatches.append(str(path))
    return len(files), mismatches


def run_diagnostic(
    *,
    e1_output: Path,
    output_dir: Path,
    config: ReactionAnchorDiagnosticConfig,
    command: Sequence[str] = (),
) -> dict[str, object]:
    config.validate()
    started = perf_counter()
    e1_output = e1_output.resolve()
    d005_output = Path(config.d005_output).resolve()
    output_dir = output_dir.resolve()
    if output_dir in {e1_output, d005_output}:
        raise ValueError("E2 output cannot overwrite D005 or E1")
    e1_before = directory_fingerprint(e1_output)
    d005_before = directory_fingerprint(d005_output)

    e1_reproducibility = json.loads(
        (e1_output / "reproducibility_metadata.json").read_text()
    )
    e1_summary = json.loads((e1_output / "summary.json").read_text())
    source_count, source_mismatches = _verify_e1_sources(
        e1_reproducibility
    )
    if source_mismatches:
        raise RuntimeError(
            "E1 source hash verification failed: "
            + ", ".join(source_mismatches[:10])
        )
    source = Path(e1_reproducibility["input_provenance"]["source"])
    one_minute_raw, provenance = load_one_minute_bars(
        source,
        start_date=config.start_date,
        end_date=config.end_date,
        lookback_days=max(
            variant.warmup_days for variant in config.mapping_variants
        ),
    )
    if (
        provenance["selection_sha256"]
        != e1_reproducibility["input_provenance"]["selection_sha256"]
    ):
        raise RuntimeError("E2 source selection differs from E1")
    timeframes = build_timeframes(one_minute_raw)
    one_minute = timeframes["1min"]

    events = load_e1_event_inventory(e1_output)
    confirmations = confirmation_inventory(timeframes, config)
    candidates = build_candidate_inventory(
        events=events,
        e1_output=e1_output,
        timeframes=timeframes,
        config=config,
    )
    uncapped, deduplication = reconstruct_uncapped_sequences(
        candidates=candidates,
        confirmations=confirmations,
        events=events,
        timeframes=timeframes,
        config=config,
    )
    uncapped, engine_evaluations = evaluate_uncapped_core_snapshots(
        uncapped,
        timeframes=timeframes,
        config=config,
    )
    capped = reconstruct_e1_capped_sequences(
        e1_output=e1_output,
        events=events,
        confirmations=confirmations,
        config=config,
    )
    uncapped = attach_first_refinement_interaction(
        uncapped, timeframes=timeframes
    )
    capped = attach_first_refinement_interaction(
        capped, timeframes=timeframes
    )
    sequences = attach_evidence_signatures(
        pd.concat([capped, uncapped], ignore_index=True, sort=False)
    )
    sequences["engine_selected_reaction_confirmed"] = sequences[
        "engine_selected_reaction_confirmed"
    ].fillna(False)
    sequences["sequence_cohort"] = sequences["sequence_status"].astype(str)
    sequences.loc[
        sequences["population"].eq("e1_capped"), "sequence_cohort"
    ] = "e1_reaction_confirmed"
    sequences.loc[
        sequences["engine_selected_reaction_confirmed"],
        "sequence_cohort",
    ] = "engine_reaction_confirmed"
    analysis_sequences = sequences[
        ~sequences["sequence_status"].eq(
            "pmh_pml_prerequisite_failure"
        )
    ].copy()
    confirmed_sequences = sequences[
        sequences["population"].eq("e1_capped")
        | sequences["engine_selected_reaction_confirmed"]
    ].copy()
    anchors = build_anchor_inventory(analysis_sequences)
    forward = calculate_forward_outcomes(
        anchors, one_minute, config=config
    )
    latency = sequence_latency_outcomes(
        analysis_sequences, one_minute
    )
    direction_audit, mismatch = build_direction_audit(
        sequences, forward
    )
    anchor_summary = anchor_outcome_summary(forward)
    principal = principal_anchor_summary(forward)
    latency_aggregate = latency_summary(latency)
    funnel = sequence_funnel(sequences)
    weekly = weekly_diagnostics(sequences)
    cohorts = confirmation_cohort_summary(
        confirmed_sequences, forward
    )
    cap_membership, cap_summary = cap_sensitivity(
        sequences, forward
    )
    state_direction = cap_state_direction_distribution(
        sequences, engine_evaluations
    )
    dominant = classify_dominant_cause(
        direction_audit=direction_audit,
        sequences=sequences,
        forward=forward,
        cap_summary=cap_summary,
    )

    frames = {
        "candidate_sequences": sequences,
        "excluded_candidate_sequences": uncapped[
            ~uncapped["sequence_status"].eq("core_sequence_complete")
        ].copy(),
        "confirmation_event_inventory": confirmations,
        "uncapped_engine_evaluations": engine_evaluations,
        "anchor_inventory": anchors,
        "anchor_forward_outcomes": forward,
        "anchor_outcome_summary": anchor_summary,
        "principal_anchor_summary": principal,
        "sequence_latency": latency,
        "latency_summary": latency_aggregate,
        "direction_label_audit": direction_audit,
        "direction_mismatch_summary": mismatch,
        "sequence_funnel": funnel,
        "weekly_diagnostics": weekly,
        "confirmation_cohort_summary": cohorts,
        "cap_sensitivity_membership": cap_membership,
        "cap_sensitivity_summary": cap_summary,
        "cap_state_direction_distribution": state_direction,
    }

    e1_after_compute = directory_fingerprint(e1_output)
    d005_after_compute = directory_fingerprint(d005_output)
    if e1_after_compute != e1_before:
        raise RuntimeError("E1 artifacts changed during E2 computation")
    if d005_after_compute != d005_before:
        raise RuntimeError("D005 artifacts changed during E2 computation")
    run_metadata = {
        "command": list(command)
        or [sys.executable, "-m", "research.d005_e2_reaction_anchor_diagnostic"],
        "runtime_seconds_before_persistence": perf_counter() - started,
        "source": str(source.resolve()),
        "source_file_count": source_count,
        "source_row_count": int(provenance["row_count"]),
        "source_selection_sha256": provenance["selection_sha256"],
        "source_hash_mismatch_count": len(source_mismatches),
        "source_files": provenance["files"],
        "e1_output": str(e1_output),
        "e1_fingerprint_before": e1_before,
        "d005_output": str(d005_output),
        "d005_fingerprint_before": d005_before,
        "e1_study_config_fingerprint": e1_summary[
            "study_config_fingerprint"
        ],
        "e1_implementation_sha256": e1_summary[
            "implementation_sha256"
        ],
        "e1_capped_event_schedule_rows": e1_summary[
            "event_schedule_rows"
        ],
        "e1_uncapped_candidate_schedule_rows": e1_summary[
            "event_schedule_uncapped_rows"
        ],
        "e1_omitted_schedule_rows": e1_summary[
            "event_schedule_omitted_rows"
        ],
        "e2_event_cap": None,
        "candidate_event_count": len(candidates),
        "confirmation_event_count": len(confirmations),
        "uncapped_engine_evaluation_count": len(engine_evaluations),
        "deduplication_counts": deduplication,
        "e1_fingerprint_preserved": True,
        "d005_fingerprint_preserved": True,
    }
    summary = persist_artifacts(
        frames=frames,
        output_dir=output_dir,
        config=config,
        run_metadata=run_metadata,
        dominant_cause=dominant,
    )
    e1_after = directory_fingerprint(e1_output)
    d005_after = directory_fingerprint(d005_output)
    if e1_after != e1_before:
        raise RuntimeError("E1 artifacts changed during E2 persistence")
    if d005_after != d005_before:
        raise RuntimeError("D005 artifacts changed during E2 persistence")
    return summary
