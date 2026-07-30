"""CLI for the isolated D005 context-engine research runner."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from .config import ContextEngineConfig, PremarketConfig
from .pipeline import run_context_research


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D005 isolated research-only XAUUSD context engine"
    )
    parser.add_argument(
        "--one-minute-bars",
        type=Path,
        required=True,
        help="read-only D003-derived one-minute parquet file or directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research_outputs/D005_CONTEXT_ENGINE"),
    )
    parser.add_argument("--start-date", type=_date)
    parser.add_argument("--end-date", type=_date)
    parser.add_argument("--evaluation-clock", default="09:00")
    parser.add_argument(
        "--mappings",
        default="weekly_4h_1h,daily_1h_15m,4h_15m_5m,1h_5m_1m",
    )
    parser.add_argument(
        "--optional-1m-refinement",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument("--premarket-start", default="00:00")
    parser.add_argument("--premarket-end", default="08:30")
    parser.add_argument("--report-path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = ContextEngineConfig(
        optional_1m_refinement=args.optional_1m_refinement,
        premarket=PremarketConfig(
            start=args.premarket_start,
            end=args.premarket_end,
        ),
    )
    mappings = tuple(name for name in args.mappings.split(",") if name)
    try:
        result = run_context_research(
            one_minute_source=args.one_minute_bars,
            output_dir=args.output_dir,
            config=config,
            start_date=args.start_date,
            end_date=args.end_date,
            evaluation_clock=args.evaluation_clock,
            mapping_names=mappings,
            report_path=args.report_path,
            command=[sys.executable, "-m", "research.context_engine", *(argv or sys.argv[1:])],
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"D005 completed: {result['output_dir']}")
    print(f"Snapshots: {result['summary']['snapshot_count']}")
    print("Production behavior changed: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
