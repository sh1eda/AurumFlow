"""Metadata-only D006 integrity checks with no data or result execution."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping

from .config import (
    D006Config,
    FROZEN_DATA_METADATA_SHA256,
    PROTECTED_TRACKED_SHA256,
    SPEC_PATH,
    SPEC_SHA256,
    config_fingerprint,
)


OWNED_PACKAGE = Path("research/d006_rejection_block_research")
OWNED_TEST_PREFIX = "tests/test_d006_"
ALLOWED_CHANGED_PREFIXES = (str(OWNED_PACKAGE) + "/", OWNED_TEST_PREFIX, "docs/D006_")
ALLOWED_MODULE_STEMS = {
    "__init__",
    "__main__",
    "config",
    "context",
    "detector",
    "lifecycle",
    "models",
    "outcomes",
    "pipeline",
    "preflight",
    "reporting",
    "schemas",
    "source",
    "statistics",
}
STRUCTURAL_ONLY_MODULE_STEMS = {
    "config", "detector", "lifecycle", "models", "preflight", "schemas"
}
FORBIDDEN_IMPORT_PREFIXES = (
    "duckdb",
    "polars",
    "pyarrow",
    "research.context_engine",
    "research.d004",
    "research.d005",
    "research.event_study_0830_0930",
    "research.d005_e1_context_engine_empirical.outcomes",
    "research.d005_e2_reaction_anchor_diagnostic.outcomes",
    "research.d005_e3_early_context_anchor_study.outcomes",
    "research.d005_e4_1h_5m_reversal_replication.analysis",
)
FORBIDDEN_CALL_NAMES = {
    "ParquetFile",
    "calculate_outcomes",
    "open",
    "read_csv",
    "read_feather",
    "read_hdf",
    "read_json",
    "read_orc",
    "read_parquet",
    "read_pickle",
    "read_sas",
    "read_sql",
    "read_table",
    "read_delta",
    "scan_parquet",
    "to_parquet",
    "ttest_1samp",
}


@dataclass(frozen=True)
class PreflightResult:
    config_fingerprint: str
    implementation_fingerprint: str
    spec_hash_status: str
    source_hashes: Mapping[str, str]
    protected_hashes: Mapping[str, str]
    data_metadata_hashes: Mapping[str, str]
    accessed_parquet: bool = False
    accessed_historical_outcomes: bool = False
    wrote_outputs: bool = False


def _hash_file(path: Path) -> str:
    if path.suffix.lower() == ".par" + "quet":
        raise ValueError("Parquet content must never be opened by D006 preflight")
    return sha256(path.read_bytes()).hexdigest()


def verify_path_hashes(root: Path, expected: Mapping[Path, str]) -> dict[str, str]:
    """Hash only supplied non-Parquet files and reject any mismatch."""

    actual: dict[str, str] = {}
    mismatches: list[str] = []
    for relative in sorted(expected, key=str):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            mismatches.append(str(relative))
            continue
        digest = _hash_file(path)
        actual[str(relative)] = digest
        if digest != expected[relative]:
            mismatches.append(str(relative))
    if mismatches:
        raise ValueError(f"hash mismatch: {mismatches}")
    return actual


def inspect_static_package(package_root: Path) -> dict[str, str]:
    """Audit the exact D006 module surface and preserve structural-layer isolation."""

    files = sorted(package_root.rglob("*.py"))
    stems = {path.stem for path in files}
    forbidden = stems - ALLOWED_MODULE_STEMS
    if forbidden:
        raise ValueError(f"forbidden D006 module names: {sorted(forbidden)}")
    hashes: dict[str, str] = {}
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if (
                path.stem in STRUCTURAL_ONLY_MODULE_STEMS
                and
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ".par" + "quet" in node.value.lower()
            ):
                raise ValueError(f"forbidden Parquet path literal in {path}")
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            if path.stem in STRUCTURAL_ONLY_MODULE_STEMS and any(
                module == forbidden or module.startswith(forbidden + ".")
                or (
                    forbidden in {"research.d004", "research.d005"}
                    and module.startswith(forbidden)
                )
                for module in modules
                for forbidden in FORBIDDEN_IMPORT_PREFIXES
            ):
                raise ValueError(f"forbidden historical/outcome import in {path}")
            if isinstance(node, ast.Call):
                call = node.func
                name = (
                    call.id
                    if isinstance(call, ast.Name)
                    else call.attr
                    if isinstance(call, ast.Attribute)
                    else ""
                )
                if path.stem in STRUCTURAL_ONLY_MODULE_STEMS and name in FORBIDDEN_CALL_NAMES:
                    raise ValueError(f"forbidden historical/outcome call in {path}: {name}")
        hashes[str(path.relative_to(package_root))] = _hash_file(path)
    return hashes


def assert_no_scientific_output_dir(root: Path) -> None:
    """D006 has no output directory at this structural preflight stage."""

    candidates = (
        root / OWNED_PACKAGE / "outputs",
        root / "research_outputs" / "d006_rejection_block_research",
        root / "research_outputs" / "D006_REJECTION_BLOCK_RESEARCH",
    )
    existing = [str(path) for path in candidates if path.exists()]
    if existing:
        raise ValueError(f"D006 scientific output directories are forbidden: {existing}")


def assert_allowed_changed_paths(changed_paths: Iterable[str]) -> None:
    invalid = [path for path in changed_paths if not path.startswith(ALLOWED_CHANGED_PREFIXES)]
    if invalid:
        raise ValueError(f"changed paths outside D006 ownership: {invalid}")


def _fingerprint_hashes(hashes: Mapping[str, str]) -> str:
    material = "\n".join(f"{path}\t{digest}" for path, digest in sorted(hashes.items()))
    return sha256(material.encode("utf-8")).hexdigest()


def run_preflight(
    root: Path,
    changed_paths: Iterable[str],
    config: D006Config = D006Config(),
    *,
    historical_execution_authorized: bool = False,
) -> PreflightResult:
    """Perform static and hash-only checks without opening a Parquet payload."""

    assert_allowed_changed_paths(changed_paths)
    if not historical_execution_authorized:
        assert_no_scientific_output_dir(root)
    source_hashes = inspect_static_package(root / OWNED_PACKAGE)
    checked_protected = verify_path_hashes(
        root, {Path(path): digest for path, digest in PROTECTED_TRACKED_SHA256}
    )
    checked_data_metadata = verify_path_hashes(
        root, {Path(path): digest for path, digest in FROZEN_DATA_METADATA_SHA256}
    )
    spec = root / SPEC_PATH
    if SPEC_SHA256 == "SPEC_SHA256_PLACEHOLDER":
        spec_status = "PLACEHOLDER"
    elif not spec.exists():
        raise ValueError("controlled D006 specification is missing")
    elif _hash_file(spec) != SPEC_SHA256:
        raise ValueError("controlled D006 specification hash mismatch")
    else:
        spec_status = "VERIFIED"
    return PreflightResult(
        config_fingerprint(config),
        _fingerprint_hashes(source_hashes),
        spec_status,
        source_hashes,
        checked_protected,
        checked_data_metadata,
    )
