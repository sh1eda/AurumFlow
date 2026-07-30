"""CLI for running and independently verifying D004."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from .config import ResearchConfig
from .pipeline import run_research
from .verification import verify_output


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _resolutions(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bar resolutions must be comma-separated integers") from exc
    if not result:
        raise argparse.ArgumentTypeError("at least one bar resolution is required")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="D004 isolated XAUUSD 08:30-09:00 New York research"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="build all D004 research artifacts")
    run.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("data/canonical/xauusd_ticks"),
    )
    run.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research_outputs/D004_XAUUSD_0830_0900"),
    )
    run.add_argument("--start-date", type=_date)
    run.add_argument("--end-date", type=_date)
    run.add_argument("--timezone", default="America/New_York")
    run.add_argument("--window-start", default="08:30")
    run.add_argument("--window-end", default="09:00")
    run.add_argument("--bar-resolutions", type=_resolutions, default=(1, 5, 15))
    run.add_argument(
        "--reference-range",
        choices=("0000_0830", "0700_0830", "0800_0830", "0800_0830_exact"),
        default="0800_0830",
    )
    run.add_argument(
        "--sweep-threshold-mode",
        choices=("absolute", "bps", "atr_fraction", "recent_range_fraction"),
        default="absolute",
    )
    run.add_argument("--sweep-threshold", type=float, default=0.05)
    run.add_argument(
        "--displacement-threshold-mode",
        choices=("expanding_percentile",),
        default="expanding_percentile",
        help="D004 permits only causal expanding-percentile classification",
    )
    run.add_argument(
        "--observation-horizons",
        default="0900_0930,0900_1000,0900_1200,0900_1600,0900_1700",
        help="registered horizons; supplied value is recorded and must remain complete",
    )
    run.add_argument(
        "--cost-scenario",
        choices=("all", "zero_cost", "repository_default", "conservative"),
        default="all",
        help="all scenarios are always calculated; this option documents the requested view",
    )
    run.add_argument("--event-labels", type=Path)
    run.add_argument("--worker-count", type=int, default=1)
    run.add_argument("--random-seed", type=int, default=4004)
    run.add_argument("--bootstrap-resamples", type=int, default=1000)
    run.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    run.add_argument("--report-path", type=Path)

    verify = subparsers.add_parser("verify", help="independently verify persisted artifacts")
    verify.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        result = verify_output(args.output_dir, write=True)
        print(f"D004 verification: {result['status']}")
        return 0 if result["status"] == "PASS" else 1
    registered_horizons = {
        "0900_0930",
        "0900_1000",
        "0900_1200",
        "0900_1600",
        "0900_1700",
    }
    supplied_horizons = set(args.observation_horizons.split(","))
    if supplied_horizons != registered_horizons:
        print(
            "ERROR: D004 requires all registered observation horizons; "
            f"got {sorted(supplied_horizons)}",
            file=sys.stderr,
        )
        return 2
    config = ResearchConfig(
        dataset_root=args.dataset_root.resolve(),
        output_dir=args.output_dir.resolve(),
        start_date=args.start_date,
        end_date=args.end_date,
        timezone=args.timezone,
        window_start=args.window_start,
        window_end=args.window_end,
        bar_resolutions=args.bar_resolutions,
        reference_range=args.reference_range,
        primary_sweep_threshold_mode=args.sweep_threshold_mode,
        primary_sweep_threshold=args.sweep_threshold,
        bootstrap_resamples=args.bootstrap_resamples,
        random_seed=args.random_seed,
        worker_count=args.worker_count,
        resume=args.resume,
        event_labels=args.event_labels.resolve() if args.event_labels else None,
        report_path=args.report_path.resolve() if args.report_path else None,
    )
    try:
        result = run_research(config, argv=[sys.executable, "-m", __package__, *(argv or sys.argv[1:])])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"D004 completed: {result['output_dir']}")
    print(f"Independent verification: {result['verification']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
