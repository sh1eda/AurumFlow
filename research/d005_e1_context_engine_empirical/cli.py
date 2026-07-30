"""Command line entry point for the D005_E1 empirical study."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from pathlib import Path
import sys

from .config import EmpiricalStudyConfig
from .pipeline import run_empirical_study


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    defaults = EmpiricalStudyConfig()
    parser = argparse.ArgumentParser(
        description="D005_E1 isolated Context Engine empirical study"
    )
    parser.add_argument(
        "--one-minute-bars",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "research_outputs/"
            "D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
        ),
    )
    parser.add_argument("--start-date", type=_date, default=defaults.start_date)
    parser.add_argument("--end-date", type=_date, default=defaults.end_date)
    parser.add_argument(
        "--fixed-clocks",
        default=",".join(defaults.fixed_clocks),
    )
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=defaults.parallel_workers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = replace(
        EmpiricalStudyConfig(),
        start_date=args.start_date,
        end_date=args.end_date,
        fixed_clocks=tuple(
            item.strip()
            for item in args.fixed_clocks.split(",")
            if item.strip()
        ),
        parallel_workers=args.workers,
    )
    try:
        result = run_empirical_study(
            one_minute_source=args.one_minute_bars,
            output_dir=args.output_dir,
            config=config,
            report_path=args.report_path,
            command=[
                sys.executable,
                "-m",
                "research.d005_e1_context_engine_empirical",
                *(argv or sys.argv[1:]),
            ],
            progress_every=args.progress_every,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"E1 completed: {result['output_dir']}")
    print(f"Snapshots: {result['summary']['snapshot_count']}")
    print(
        "Reaction confirmed: "
        f"{result['summary']['reaction_confirmed_count']}"
    )
    print("Production behavior changed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
