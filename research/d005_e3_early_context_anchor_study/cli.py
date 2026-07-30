"""CLI for the isolated D005_E3 study."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys

from .config import EarlyContextAnchorStudyConfig
from .pipeline import run_study


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="D005_E3 isolated early-context anchor study"
    )
    result.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY"
        ),
    )
    result.add_argument("--start-date", type=date.fromisoformat)
    result.add_argument("--end-date", type=date.fromisoformat)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    config = EarlyContextAnchorStudyConfig()
    if arguments.start_date is not None:
        config = replace(config, start_date=arguments.start_date)
    if arguments.end_date is not None:
        config = replace(config, end_date=arguments.end_date)
    summary = run_study(
        output_dir=arguments.output_dir,
        config=config,
        command=sys.argv,
    )
    classification = summary["classification"]
    print(
        f"E3 category {classification['primary_classification_id']}: "
        f"{classification['primary_classification_label']}"
    )
    print(f"Recommendation: {classification['recommendation']}")
    print("Production behavior changed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
