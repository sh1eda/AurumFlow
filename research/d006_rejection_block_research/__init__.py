"""Frozen D006 structural and historical research package."""

from .config import D006Config, SPEC_PATH, SPEC_SHA256
from .detector import detect_rejection_blocks
from .lifecycle import combine_structural_records, evaluate_lifecycle
from .models import CombinedStructuralRecord, Direction, RejectionBlock
from .pipeline import EXECUTION_AUTHORIZATION, run_historical_execution

__all__ = [
    "D006Config",
    "EXECUTION_AUTHORIZATION",
    "CombinedStructuralRecord",
    "Direction",
    "RejectionBlock",
    "SPEC_PATH",
    "SPEC_SHA256",
    "detect_rejection_blocks",
    "combine_structural_records",
    "evaluate_lifecycle",
    "run_historical_execution",
]
