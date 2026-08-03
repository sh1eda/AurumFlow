"""Stdout-only D005_E6 readiness command."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Sequence

from .config import parse_utc
from .readiness import build_readiness_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="D005_E6 metadata-only readiness")
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--as-of",
        type=parse_utc,
        help="Optional explicit UTC readiness instant; never enters a scientific fingerprint.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    as_of: datetime | None = args.as_of
    report = build_readiness_report(args.repository_root, as_of=as_of)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0
