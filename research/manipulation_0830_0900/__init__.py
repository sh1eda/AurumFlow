"""Isolated D004 XAUUSD 08:30-09:00 New York research framework.

Nothing in this package is imported by the production ``xauusd_signal``
package.  The package consumes the immutable D003 canonical tick dataset and
writes only research artifacts.
"""

from .config import ResearchConfig
from .features import (
    classify_displacement_expanding,
    classify_sweep,
    detect_fvgs,
    label_hod_lod,
)
from .pipeline import run_research
from .verification import verify_output

__all__ = [
    "ResearchConfig",
    "classify_displacement_expanding",
    "classify_sweep",
    "detect_fvgs",
    "label_hod_lod",
    "run_research",
    "verify_output",
]
