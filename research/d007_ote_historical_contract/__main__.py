"""Single command surface for D007 historical contract preflight/execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import EXECUTION_AUTHORIZATION
from .preflight import run_contract_preflight
from .runner import HistoricalPipelineDeferred, run_historical_execution


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or execute frozen D007 history")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "execute"):
        child = subparsers.add_parser(command)
        child.add_argument("--authorization", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorization != EXECUTION_AUTHORIZATION:
        raise SystemExit("exact D007 historical execution authorization token is required")
    root = args.root.resolve()
    if args.command == "preflight":
        result = run_contract_preflight(root, authorization=args.authorization)
        print(json.dumps(result.to_dict(), sort_keys=True))
        return 0
    try:
        run_historical_execution(root, authorization=args.authorization)
    except HistoricalPipelineDeferred as exc:
        raise SystemExit(str(exc)) from exc
    raise AssertionError("D007 historical execution returned without an output path")


if __name__ == "__main__":
    raise SystemExit(main())
