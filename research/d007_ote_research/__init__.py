"""D007 OTE preregistration and synthetic structural preflight.

This package deliberately contains no historical-data loader, outcome calculator,
runner, CLI, or production integration.
"""

from .config import D007Config, config_fingerprint
from .models import Direction, GeometryDefinition, OTERange

__all__ = (
    "D007Config",
    "Direction",
    "GeometryDefinition",
    "OTERange",
    "config_fingerprint",
)
