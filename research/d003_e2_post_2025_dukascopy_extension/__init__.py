"""Reporting-only wrapper for the frozen D003_E2 acquisition pipeline."""

from .config import D003E2Config
from .reporting import finalize_failed_acquisition

__all__ = ["D003E2Config", "finalize_failed_acquisition"]

