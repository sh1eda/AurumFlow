"""Finalize D003_E2 acquisition evidence without altering the pipeline."""

from pathlib import Path

from .config import D003E2Config
from .reporting import finalize_failed_acquisition

finalize_failed_acquisition(root=Path.cwd(), config=D003E2Config())

