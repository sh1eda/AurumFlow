"""Infrastructure for isolated, reproducible AurumFlow research."""

from .models import (
    ExperimentDefinition,
    ExperimentResult,
    ResearchDecision,
    ResearchLifecycle,
    ResearchObjectDefinition,
)

__all__ = [
    "ExperimentDefinition",
    "ExperimentResult",
    "ResearchDecision",
    "ResearchLifecycle",
    "ResearchObjectDefinition",
]

__version__ = "0.1.0"
