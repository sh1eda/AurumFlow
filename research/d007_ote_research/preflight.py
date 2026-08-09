"""Static/hash-only D007 preflight with no historical or outcome execution path."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Mapping

from .config import (
    D007Config,
    FROZEN_DATA_METADATA_SHA256,
    FROZEN_IGNORED_ARTIFACT_COUNT,
    FROZEN_IGNORED_ARTIFACT_FINGERPRINT,
    PROTECTED_TRACKED_SHA256,
    SPEC_PATH,
    SPEC_SHA256,
    config_fingerprint,
)


OWNED_PACKAGE = Path("research/d007_ote_research")
ALLOWED_CHANGED_PREFIXES = (
    str(OWNED_PACKAGE) + "/",
    "tests/test_d007_",
    "docs/D007_",
)
ALLOWED_MODULE_STEMS = {
    "__init__",
    "config",
    "detector",
    "guardrails",
    "lifecycle",
    "models",
    "preflight",
}
FORBIDDEN_MODULE_STEMS = {
    "__main__",
    "analysis",
    "cli",
    "outcomes",
    "pipeline",
    "reporting",
    "runner",
    "source",
    "statistics",
}
FORBIDDEN_IMPORT_PREFIXES = (
    "duckdb",
    "polars",
    "pyarrow",
    "research.context_engine",
    "research.d004",
    "research.d005",
    "research.d006",
    "research.event_study_0830_0930",
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
    "scan_parquet",
    "to_csv",
    "to_json",
    "to_parquet",
    "ttest_1samp",
}
RAW_SOURCE_SHA256 = (
    (
        "docs/raw_sources/ICT 2022 Mentorship - Lumi Traders (405 sayfa) - @eseckal.pdf",
        "0cc50fcd129d22d3c68704ffa115cd3b6bc53c93b399c39c55a349d9034e96a0",
    ),
    (
        "docs/raw_sources/EKINYZBB BOOTCAMP SERISI.pdf",
        "6fd9c61fb7956ce2e31a3cbf94f1edcfe405325dccd5693bc4b95635100d59ae",
    ),
)


@dataclass(frozen=True)
class PreflightResult:
    config_fingerprint: str
    implementation_fingerprint: str
    spec_sha256: str
    spec_hash_status: str
    source_hashes: Mapping[str, str]
    protected_hashes: Mapping[str, str]
    data_metadata_hashes: Mapping[str, str]
    raw_source_hashes: Mapping[str, str]
    ignored_artifact_count: int
    ignored_artifact_fingerprint: str
    accessed_market_data: bool = False
    accessed_historical_outcomes: bool = False
    wrote_outputs: bool = False


def _hash_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".csv", ".feather", ".arrow"}:
        raise ValueError("D007 preflight cannot open market/outcome table payloads")
    return sha256(path.read_bytes()).hexdigest()


def verify_path_hashes(root: Path, expected: Mapping[Path, str]) -> dict[str, str]:
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
        raise ValueError(f"D007 protected/source hash mismatch: {mismatches}")
    return actual


def fingerprint_ignored_non_table_artifacts(root: Path) -> tuple[int, str]:
    """Hash ignored reports/manifests without opening any table payload."""

    artifact_root = root / "research_outputs"
    excluded_suffixes = {".parquet", ".csv", ".feather", ".arrow", ".pyc"}
    files = sorted(
        path
        for path in artifact_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() not in excluded_suffixes
        and "__pycache__" not in path.parts
    )
    rows = [
        f"{path.relative_to(root)}\t{_hash_file(path)}"
        for path in files
    ]
    return len(files), sha256("\n".join(rows).encode("utf-8")).hexdigest()


def inspect_static_package(package_root: Path) -> dict[str, str]:
    files = sorted(package_root.rglob("*.py"))
    stems = {path.stem for path in files}
    registered_metadata_paths = {
        path for path, _digest in FROZEN_DATA_METADATA_SHA256
    }
    invalid = (stems - ALLOWED_MODULE_STEMS) | (stems & FORBIDDEN_MODULE_STEMS)
    if invalid:
        raise ValueError(f"forbidden D007 module surface: {sorted(invalid)}")
    hashes: dict[str, str] = {}
    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            if any(
                module == forbidden or module.startswith(forbidden + ".")
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
                if name in FORBIDDEN_CALL_NAMES:
                    raise ValueError(f"forbidden historical/outcome call in {path}: {name}")
            if (
                path.stem != "preflight"
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and not (
                    path.stem == "config"
                    and node.value in registered_metadata_paths
                )
                and any(
                    token in node.value.lower()
                    for token in ("research_outputs/", "data/canonical/", "data/raw/")
                )
            ):
                raise ValueError(f"forbidden D007 data/output path literal in {path}")
        hashes[str(path.relative_to(package_root))] = _hash_file(path)
    return hashes


def assert_allowed_changed_paths(changed_paths: Iterable[str]) -> None:
    invalid = [
        path for path in changed_paths if not path.startswith(ALLOWED_CHANGED_PREFIXES)
    ]
    if invalid:
        raise ValueError(f"changed paths outside D007 ownership: {invalid}")


def assert_no_d007_output(root: Path) -> None:
    candidates = (
        root / OWNED_PACKAGE / "outputs",
        root / "research_outputs" / "D007_OTE_RESEARCH",
        root / "research_outputs" / "d007_ote_research",
    )
    existing = [str(path) for path in candidates if path.exists()]
    if existing:
        raise ValueError(f"D007 scientific outputs are forbidden: {existing}")


def assert_validation_year(year: int, config: D007Config = D007Config()) -> None:
    if year not in config.validation_years or year in config.forbidden_years:
        raise ValueError("D007 preflight forbids outcome-known or unregistered years")


def assert_historical_execution_forbidden() -> None:
    raise PermissionError("historical D007 execution is not authorized by this milestone")


def _implementation_fingerprint(hashes: Mapping[str, str]) -> str:
    material = "\n".join(
        f"{path}\t{digest}" for path, digest in sorted(hashes.items())
    )
    return sha256(material.encode("utf-8")).hexdigest()


def run_preflight(
    root: Path,
    changed_paths: Iterable[str],
    config: D007Config = D007Config(),
) -> PreflightResult:
    assert_allowed_changed_paths(changed_paths)
    assert_no_d007_output(root)
    source_hashes = inspect_static_package(root / OWNED_PACKAGE)
    protected = verify_path_hashes(
        root, {Path(path): digest for path, digest in PROTECTED_TRACKED_SHA256}
    )
    data_metadata = verify_path_hashes(
        root, {Path(path): digest for path, digest in FROZEN_DATA_METADATA_SHA256}
    )
    raw_sources = verify_path_hashes(
        root, {Path(path): digest for path, digest in RAW_SOURCE_SHA256}
    )
    artifact_count, artifact_fingerprint = fingerprint_ignored_non_table_artifacts(root)
    if (artifact_count, artifact_fingerprint) != (
        FROZEN_IGNORED_ARTIFACT_COUNT,
        FROZEN_IGNORED_ARTIFACT_FINGERPRINT,
    ):
        raise ValueError("D007 ignored-artifact aggregate mismatch")
    spec_path = root / SPEC_PATH
    if not spec_path.is_file():
        raise ValueError("controlled D007 specification is missing")
    actual_spec_hash = _hash_file(spec_path)
    if SPEC_SHA256 == "SPEC_SHA256_PLACEHOLDER":
        spec_status = "PLACEHOLDER"
    elif actual_spec_hash != SPEC_SHA256:
        raise ValueError("controlled D007 specification hash mismatch")
    else:
        spec_status = "VERIFIED"
    return PreflightResult(
        config_fingerprint=config_fingerprint(config),
        implementation_fingerprint=_implementation_fingerprint(source_hashes),
        spec_sha256=actual_spec_hash,
        spec_hash_status=spec_status,
        source_hashes=source_hashes,
        protected_hashes=protected,
        data_metadata_hashes=data_metadata,
        raw_source_hashes=raw_sources,
        ignored_artifact_count=artifact_count,
        ignored_artifact_fingerprint=artifact_fingerprint,
    )
