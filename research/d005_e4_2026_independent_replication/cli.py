"""CLI for the read-only D005_E4 2026 preflight."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import FROZEN_END, FROZEN_START, IndependentReplication2026Config
from .preflight import build_preflight_result, render_preflight_json


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="D005_E4 2026 independent replication preflight only"
    )
    result.add_argument(
        "--independent-replication",
        action="store_true",
        help="required explicit acknowledgement of the independent extension",
    )
    result.add_argument("--start", default=FROZEN_START)
    result.add_argument("--end", default=FROZEN_END)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        config = IndependentReplication2026Config(
            independent_replication=arguments.independent_replication,
            start=arguments.start,
            end=arguments.end,
        )
        result = build_preflight_result(
            repository_root=Path.cwd(),
            config=config,
        )
    except ValueError as exc:
        print(f"preflight configuration error: {exc}", file=sys.stderr)
        return 2
    print(render_preflight_json(result), end="")
    return 0 if result["authorized_to_calculate_2026_outcomes"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
