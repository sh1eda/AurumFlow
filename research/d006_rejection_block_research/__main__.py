"""Fixed-scope command surface for D006 historical execution and verification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import EXECUTION_AUTHORIZATION, run_historical_execution
from .preflight import run_preflight
from .reporting import OUTPUT_DIRECTORY, verify_results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute or verify frozen D006 research")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--authorization", required=True)
    subparsers.add_parser("verify")
    subparsers.add_parser("preflight")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    if args.command == "execute":
        if args.authorization != EXECUTION_AUTHORIZATION:
            raise SystemExit("exact D006 historical authorization token is required")
        output = run_historical_execution(
            root,
            authorization=args.authorization,
        )
        print(output)
        return 0
    if args.command == "verify":
        print(json.dumps(verify_results(root / OUTPUT_DIRECTORY), sort_keys=True))
        return 0
    result = run_preflight(
        root,
        (),
        historical_execution_authorized=True,
    )
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
