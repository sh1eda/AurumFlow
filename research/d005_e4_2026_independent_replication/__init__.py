"""Fail-closed preflight for the D005_E4 2026 independent extension."""

from .config import IndependentReplication2026Config
from .preflight import build_preflight_result

__all__ = ["IndependentReplication2026Config", "build_preflight_result"]
