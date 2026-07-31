"""CLI for the isolated D005_E2 diagnostic."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys

from .config import ReactionAnchorDiagnosticConfig
from .pipeline import run_diagnostic


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="D005_E2 isolated reaction-anchor diagnostic"
    )
    result.add_argument(
        "--e1-output",
        type=Path,
        default=Path(
            "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
        ),
    )
    result.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC"
        ),
    )
    result.add_argument("--start-date", type=date.fromisoformat)
    result.add_argument("--end-date", type=date.fromisoformat)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    config = ReactionAnchorDiagnosticConfig()
    if arguments.start_date is not None:
        config = replace(config, start_date=arguments.start_date)
    if arguments.end_date is not None:
        config = replace(config, end_date=arguments.end_date)
    summary = run_diagnostic(
        e1_output=arguments.e1_output,
        output_dir=arguments.output_dir,
        config=config,
        command=sys.argv,
    )
    print(f"E2 sequences: {summary['candidate_sequence_rows']}")
    print(
        "Dominant cause: "
        + "; ".join(summary["dominant_cause"]["classification_labels"])
    )
    print("Production behavior changed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

