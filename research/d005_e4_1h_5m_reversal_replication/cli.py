"""CLI for the isolated D005_E4 study."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import ReversalReplicationConfig
from .pipeline import run_study


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="D005_E4 isolated 1H→5m reversal replication"
    )
    result.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION"
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    config = ReversalReplicationConfig()
    summary = run_study(
        output_dir=arguments.output_dir,
        config=config,
        command=sys.argv,
    )
    classification = summary["classification"]
    print(
        f"E4 category {classification['primary_classification_id']}: "
        f"{classification['primary_classification_label']}"
    )
    print(
        "Internal rolling-origin checks passed: "
        f"{classification['internal_rolling_origin_checks_pass']}"
    )
    print(f"Recommendation: {classification['recommendation']}")
    print("Production behavior changed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
