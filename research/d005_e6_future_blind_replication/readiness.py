"""Pre-execution readiness checks with no outcome or output path."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
from typing import Final

from .boundary import audit_blind_boundary
from .config import (
    E6ReadinessConfig,
    FROZEN_AGGREGATE_MANIFEST_SHA256,
    FROZEN_TRACKED_SHA256,
    SPEC_PATH,
    SPEC_SHA256,
    parse_utc,
)
from .planning import sample_size_plan
from .schemas import aggregate_audit_schema, reporting_contract_schema


FORBIDDEN_MODULE_IMPORTS: Final = (
    "pandas",
    "pyarrow",
    "research.d005_e4_2026_independent_replication.anchor_inputs",
    "research.d005_e4_1h_5m_reversal_replication",
)
FORBIDDEN_CALL_NAMES: Final = frozenset(
    {
        "read_parquet",
        "ParquetFile",
        "construct_anchors",
        "calculate_outcomes",
        "bootstrap",
    }
)
FORBIDDEN_SOURCE_FILENAMES: Final = frozenset(
    {
        "loader.py",
        "anchors.py",
        "outcomes.py",
        "statistics.py",
        "reporting.py",
        "execution.py",
    }
)


class ReadinessError(RuntimeError):
    """Raised when a preregistered readiness invariant fails."""


def sha256_file(path: Path) -> str:
    if path.suffix.lower() == ".parquet":
        raise ReadinessError("E6 must never open a Parquet payload")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ReadinessError(f"cannot verify protected file: {path.name}") from error
    return digest.hexdigest()


def verify_frozen_fingerprints(repository_root: Path) -> dict[str, object]:
    expected = {
        **FROZEN_TRACKED_SHA256,
        **FROZEN_AGGREGATE_MANIFEST_SHA256,
        SPEC_PATH: SPEC_SHA256,
    }
    mismatches: list[str] = []
    for relative, registered in sorted(expected.items()):
        path = repository_root / relative
        if not path.is_file() or path.is_symlink() or sha256_file(path) != registered:
            mismatches.append(relative)
    return {
        "verified": not mismatches,
        "mismatches": mismatches,
        "registered_file_total": len(expected),
    }


def verify_no_scientific_execution_path(package_root: Path) -> dict[str, object]:
    violations: list[str] = []
    for path in sorted(package_root.glob("*.py")):
        if path.name in FORBIDDEN_SOURCE_FILENAMES:
            violations.append(f"forbidden source filename: {path.name}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                modules = []
            for module in modules:
                if any(
                    module == forbidden or module.startswith(forbidden + ".")
                    for forbidden in FORBIDDEN_MODULE_IMPORTS
                ):
                    violations.append(f"forbidden import in {path.name}: {module}")
            if isinstance(node, ast.Call):
                call = node.func
                name = call.id if isinstance(call, ast.Name) else (
                    call.attr if isinstance(call, ast.Attribute) else ""
                )
                if name in FORBIDDEN_CALL_NAMES:
                    violations.append(f"forbidden call in {path.name}: {name}")
    return {"verified": not violations, "violations": violations}


def _git_metadata(repository_root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    try:
        return {
            "commit": run("rev-parse", "HEAD"),
            "branch": run("branch", "--show-current"),
            "working_tree_status": run("status", "--short"),
            "forensic_stash_metadata": run(
                "stash", "list", "--format=%gd%x09%H%x09%gs"
            ).splitlines(),
            "stash_payload_inspected": False,
        }
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReadinessError("Git metadata audit failed") from error


def build_readiness_report(
    repository_root: Path,
    *,
    as_of: datetime | None = None,
) -> dict[str, object]:
    config = E6ReadinessConfig()
    config.validate()
    root = repository_root.resolve()
    instant = as_of or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ReadinessError("as_of must be timezone-aware")
    instant = instant.astimezone(timezone.utc)

    fingerprints = verify_frozen_fingerprints(root)
    execution_path = verify_no_scientific_execution_path(
        root / "research/d005_e6_future_blind_replication"
    )
    boundary = audit_blind_boundary(root)
    elapsed = instant >= parse_utc(config.policy.earliest_execution)
    blockers = [
        "BLIND_BOUNDARY_UNPROVEN",
        "INTERVAL_UNREGISTERED",
        "FUTURE_METADATA_COVERAGE_UNAVAILABLE",
        "SCIENTIFIC_EXECUTION_PATH_INTENTIONALLY_ABSENT",
    ]
    if not elapsed:
        blockers.append("EARLIEST_EXECUTION_DATE_NOT_REACHED")
    if not fingerprints["verified"]:
        blockers.append("FROZEN_FINGERPRINT_MISMATCH")
    if not execution_path["verified"]:
        blockers.append("FORBIDDEN_EXECUTION_PATH_PRESENT")

    return {
        "study_id": config.study_id,
        "readiness_kind": "PLANNING_AND_METADATA_ONLY",
        "configuration_fingerprint": config.fingerprint(),
        "specification": {"path": SPEC_PATH, "sha256": SPEC_SHA256},
        "frozen_fingerprints": fingerprints,
        "scientific_execution_path_absent": execution_path,
        "blind_boundary": boundary,
        "fixed_interval_policy": {
            "anchor_start": config.policy.anchor_start,
            "anchor_end_exclusive": config.policy.anchor_end_exclusive,
            "endpoint_buffer_hours": config.policy.endpoint_buffer_hours,
            "earliest_execution": config.policy.earliest_execution,
            "registration_status": config.policy.registration_status,
            "early_peeking_permitted": False,
            "partial_reports_permitted": False,
            "interim_significance_testing_permitted": False,
        },
        "elapsed_calendar_requirement_met": elapsed,
        "metadata_file_coverage_verified": False,
        "sample_size_planning": sample_size_plan(),
        "aggregate_audit_schema": aggregate_audit_schema(),
        "reporting_contract_schema": reporting_contract_schema(),
        "git_metadata": _git_metadata(root),
        "readiness_blockers": blockers,
        "interval_registered": False,
        "scientific_execution_authorized": False,
        "scientific_output_directory_created": False,
        "future_anchor_count_observed": False,
        "future_outcome_calculated": False,
        "production_recommendation": config.production_recommendation,
    }
