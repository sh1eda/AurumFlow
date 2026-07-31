"""Load exact frozen structural modules without executing their package APIs.

The historical E1 package ``__init__`` imports its full pipeline, which in
turn imports forward-outcome code.  This loader executes only the reviewed
config/schedule/PMH and E2 direction/reconstruction source files under private
package names, preserving their relative imports while keeping that forward
module outside the import graph.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from zoneinfo import ZoneInfo

from research.context_engine.config import NEW_YORK

from .config import FROZEN_ANCHOR_RULE_HASHES


_RESEARCH_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORY_ROOT = _RESEARCH_ROOT.parent
_PRIVATE_ROOT = __package__ + "._frozen_structural"


def _verify(relative: str) -> None:
    path = _REPOSITORY_ROOT / relative
    observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    if observed != FROZEN_ANCHOR_RULE_HASHES[relative]:
        raise RuntimeError(f"frozen structural source hash mismatch: {relative}")


def _package(name: str, path: Path) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    module.__package__ = name
    sys.modules[name] = module
    return module


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen structural source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


_package(_PRIVATE_ROOT, _RESEARCH_ROOT)
_E1_NAME = _PRIVATE_ROOT + ".e1"
_E1_PATH = _RESEARCH_ROOT / "d005_e1_context_engine_empirical"
_package(_E1_NAME, _E1_PATH)
for _relative in (
    "research/d005_e1_context_engine_empirical/config.py",
    "research/d005_e1_context_engine_empirical/schedule.py",
    "research/d005_e1_context_engine_empirical/pmh.py",
):
    _verify(_relative)
e1_config = _module(_E1_NAME + ".config", _E1_PATH / "config.py")
e1_schedule = _module(_E1_NAME + ".schedule", _E1_PATH / "schedule.py")
e1_pmh = _module(_E1_NAME + ".pmh", _E1_PATH / "pmh.py")

_E2_NAME = _PRIVATE_ROOT + ".e2"
_E2_PATH = _RESEARCH_ROOT / "d005_e2_reaction_anchor_diagnostic"
_package(_E2_NAME, _E2_PATH)
for _relative in (
    "research/d005_e2_reaction_anchor_diagnostic/config.py",
    "research/d005_e2_reaction_anchor_diagnostic/directions.py",
    "research/d005_e2_reaction_anchor_diagnostic/reconstruction.py",
):
    _verify(_relative)
e2_directions = _module(_E2_NAME + ".directions", _E2_PATH / "directions.py")


@dataclass(frozen=True)
class ReactionAnchorDiagnosticConfig:
    """Exact E2 structural configuration with a private E1 mapping type."""

    study_id: str = "D005_E2_REACTION_ANCHOR_DIAGNOSTIC"
    version: str = "D005-E2-v1"
    timezone: str = NEW_YORK
    start_date: date = date(2021, 1, 3)
    end_date: date = date(2025, 12, 31)
    mapping_variants: tuple[object, ...] = e1_config.DEFAULT_MAPPING_VARIANTS
    forward_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)
    day_end_clock: str = "17:00"
    mfe_price_thresholds: tuple[float, ...] = (0.5, 1.0, 2.0, 5.0)
    e1_output: str = (
        "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY"
    )
    d005_output: str = "research_outputs/D005_CONTEXT_ENGINE"
    technical_spec: str = (
        "docs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC_SPEC.md"
    )
    uncapped_event_limit: None = None
    deterministic_deduplication: bool = True
    production_entry_authorization: bool = False
    optimization: bool = False
    metadata: dict[str, object] = field(
        default_factory=lambda: {
            "study_type": "causal_anchor_and_direction_diagnostic",
            "production_integration": False,
            "threshold_change": False,
            "state_logic_change": False,
            "canonical_ob_selection": False,
            "timing_signal": False,
        }
    )

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.timezone != NEW_YORK:
            raise ValueError("E2 must use America/New_York")
        if self.end_date < self.start_date:
            raise ValueError("end date precedes start date")
        if self.uncapped_event_limit is not None:
            raise ValueError("E2 uncapped reconstruction cannot set an event cap")
        if any(value <= 0 for value in self.forward_minutes):
            raise ValueError("forward horizons must be positive")
        if any(value <= 0 for value in self.mfe_price_thresholds):
            raise ValueError("MFE thresholds must be positive")
        if len(set(self.mfe_price_thresholds)) != len(
            self.mfe_price_thresholds
        ):
            raise ValueError("MFE thresholds must be unique")
        if self.production_entry_authorization:
            raise ValueError("E2 cannot authorize entries")
        if self.optimization:
            raise ValueError("E2 is not an optimization study")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["event_cap"] = None
        payload["price_outcome_semantics"] = "descriptive_not_pnl"
        payload["index_timing_transfer"] = False
        payload["pmh_pml_bias_override"] = False
        return payload

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.snapshot(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def mapping_variant(self, name: str) -> object:
        return next(item for item in self.mapping_variants if item.name == name)


e2_config = ModuleType(_E2_NAME + ".config")
e2_config.__package__ = _E2_NAME
e2_config.ReactionAnchorDiagnosticConfig = ReactionAnchorDiagnosticConfig
sys.modules[e2_config.__name__] = e2_config
e2_reconstruction = _module(
    _E2_NAME + ".reconstruction", _E2_PATH / "reconstruction.py"
)


EmpiricalStudyConfig = e1_config.EmpiricalStudyConfig
MappingVariant = e1_config.MappingVariant
build_pmh_pml_inventory = e1_pmh.build_pmh_pml_inventory
event_schedule_from_inventory = e1_schedule.event_schedule_from_inventory
fixed_observation_schedule = e1_schedule.fixed_observation_schedule
classify_outcome = e2_directions.classify_outcome
expected_post_sweep_direction = e2_directions.expected_post_sweep_direction
liquidity_raid_direction = e2_directions.liquidity_raid_direction
directions_at = e2_reconstruction._directions_at
confirmation_inventory = e2_reconstruction.confirmation_inventory
evaluate_uncapped_core_snapshots = (
    e2_reconstruction.evaluate_uncapped_core_snapshots
)
reconstruct_uncapped_sequences = e2_reconstruction.reconstruct_uncapped_sequences


__all__ = [
    "EmpiricalStudyConfig",
    "MappingVariant",
    "ReactionAnchorDiagnosticConfig",
    "build_pmh_pml_inventory",
    "classify_outcome",
    "confirmation_inventory",
    "directions_at",
    "evaluate_uncapped_core_snapshots",
    "event_schedule_from_inventory",
    "expected_post_sweep_direction",
    "fixed_observation_schedule",
    "liquidity_raid_direction",
    "reconstruct_uncapped_sequences",
]
