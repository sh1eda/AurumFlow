"""Synthetic-only structural rejection-block research primitives."""

from .config import D006Config, SPEC_PATH, SPEC_SHA256
from .detector import detect_rejection_blocks
from .lifecycle import combine_structural_records, evaluate_lifecycle
from .models import CombinedStructuralRecord, Direction, RejectionBlock

__all__ = [
    "D006Config",
    "CombinedStructuralRecord",
    "Direction",
    "RejectionBlock",
    "SPEC_PATH",
    "SPEC_SHA256",
    "detect_rejection_blocks",
    "combine_structural_records",
    "evaluate_lifecycle",
]
