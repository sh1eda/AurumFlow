"""CLI for the isolated D003_E1 audit."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import ExtensionAuditConfig
from .pipeline import run_audit


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Run the D003_E1 2026 canonical-extension gate"
    )
    value.add_argument(
        "--output",
        type=Path,
        default=Path(
            "research_outputs/D003_E1_2026_CANONICAL_EXTENSION"
        ),
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run_audit(
        output_dir=args.output,
        config=ExtensionAuditConfig(),
        command=[sys.executable, "-m", __package__],
    )
    return 0
