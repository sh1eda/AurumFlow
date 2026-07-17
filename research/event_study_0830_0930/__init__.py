"""Isolated XAUUSD 08:30–10:30 New York event-study framework.

This package is intentionally excluded from the production package declaration in
``pyproject.toml``.  It must not be imported by production signal code.
"""

from .config import StudyConfig
from .io import DataRequirementError, load_calendar, load_prices

__all__ = ["DataRequirementError", "StudyConfig", "load_calendar", "load_prices"]
