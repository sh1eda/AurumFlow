"""Hash-only authorization preflight for the frozen D007 history contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from research.d007_methodology_clarification import (
    ADDENDUM_SHA256,
    named_trading_date,
    verify_upstream_identities,
)
from research.d007_ote_research.config import config_fingerprint as d007_config_fingerprint
from research.d007_ote_research.preflight import run_preflight as run_synthetic_preflight

from .config import (
    ALLOWED_CHANGED_PREFIXES,
    CLARIFICATION_MODULE_PATH,
    CLARIFICATION_MODULE_SHA256,
    CLARIFICATION_SPEC_PATH,
    CLARIFICATION_SPEC_SHA256,
    CONTRACT_SPEC_PATH,
    CONTRACT_SPEC_SHA256,
    DEFAULT_CONTRACT,
    D005_E4_ARTIFACT_SHA256,
    D005_E4_ROOT,
    D004_REPRODUCIBILITY_SHA256,
    D004_ROOT,
    D007_CONFIG_FINGERPRINT,
    D007_SPEC_SHA256,
    D007_SYNTHETIC_IMPLEMENTATION_FINGERPRINT,
    EXECUTION_AUTHORIZATION,
    FROZEN_CONTRACT_IMPLEMENTATION_SHA256,
    OUTPUT_DIRECTORY,
    SOURCE_ROOT,
    HistoricalExecutionContract,
    contract_fingerprint,
    validate_frozen_contract,
)


class ContractPreflightError(RuntimeError):
    """Raised before any D007 historical row may be decoded."""


@dataclass(frozen=True)
class ContractPreflightResult:
    contract_fingerprint: str
    contract_spec_sha256: str
    d007_spec_sha256: str
    d007_config_fingerprint: str
    d007_synthetic_implementation_fingerprint: str
    clarification_addendum_sha256: str
    clarification_module_sha256: str
    clarification_dependency_hashes: dict[str, str]
    d005_e4_artifact_hashes: dict[str, str]
    contract_implementation_hashes: dict[str, str]
    d004_reproducibility_sha256: str
    d005_e4_implementation_sha256: str
    source_selection_sha256: str
    relative_source_inventory_sha256: str
    source_file_count: int
    source_row_count: int
    output_directory: str
    historical_execution_authorized: bool
    decoded_market_rows: int = 0
    constructed_d007_events: int = 0
    accessed_historical_outcomes: bool = False
    applied_adequacy_gate: bool = False
    performed_statistical_analysis: bool = False
    wrote_outputs: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_sha256(path: Path, expected: str, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise ContractPreflightError(f"missing or unsafe {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ContractPreflightError(f"{label} SHA-256 mismatch: {path}")
    return actual


def normalized_config_sha256(path: Path, expected: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise ContractPreflightError(f"missing or unsafe D007 contract config: {path}")
    source = path.read_text(encoding="utf-8")
    needle = f'    ("config.py", "{expected}"),'
    sentinel = '    ("config.py", "CONFIG_NORMALIZED_SHA256"),'
    if source.count(needle) != 1:
        raise ContractPreflightError("D007 contract config self-hash field is invalid")
    return sha256(source.replace(needle, sentinel).encode("utf-8")).hexdigest()


def assert_authorized_output_path(
    repository_root: Path,
    output_relative: Path = OUTPUT_DIRECTORY,
) -> Path:
    root = repository_root.resolve()
    raw_output = root / output_relative
    raw_expected = root / OUTPUT_DIRECTORY
    output = raw_output.resolve()
    expected = raw_expected.resolve()
    if output != expected:
        raise ContractPreflightError("unauthorized D007 historical output path")
    if root not in output.parents or output == root:
        raise ContractPreflightError("D007 output must remain inside the repository")
    path_cursor = raw_output
    while path_cursor != root:
        if path_cursor.is_symlink():
            raise ContractPreflightError("D007 output path cannot contain symlinks")
        path_cursor = path_cursor.parent
    forbidden_roots = (
        root / "data",
        root / "xauusd_signal",
        root / "research_outputs/D003_E1_2026_CANONICAL_EXTENSION",
        root / "research_outputs/D003_E2_POST_2025_DUKASCOPY_BI5_EXTENSION",
        root / "research_outputs/D004_XAUUSD_0830_0900",
        root / "research_outputs/D005_CONTEXT_ENGINE",
        root / "research_outputs/D005_E1_CONTEXT_ENGINE_EMPIRICAL_STUDY",
        root / "research_outputs/D005_E2_REACTION_ANCHOR_DIAGNOSTIC",
        root / "research_outputs/D005_E3_EARLY_CONTEXT_ANCHOR_STUDY",
        root / "research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION",
        root / "research_outputs/D005_E4_2026_INDEPENDENT_REPLICATION",
        root / "research_outputs/D005_E5_REPORTING_HARDENING",
        root / "research_outputs/D006_REJECTION_BLOCK_RESEARCH",
    )
    if any(output == item.resolve() or item.resolve() in output.parents for item in forbidden_roots):
        raise ContractPreflightError("D007 output collides with a protected path")
    if raw_output.exists() or raw_output.is_symlink():
        raise ContractPreflightError("D007 historical output must not exist before first publication")
    return output


def assert_exact_interval(
    start_date: str,
    end_date: str,
    terminal_timestamp_exclusive: str,
    contract: HistoricalExecutionContract = DEFAULT_CONTRACT,
) -> None:
    if (
        start_date,
        end_date,
        terminal_timestamp_exclusive,
    ) != (
        contract.source_start_date,
        contract.source_end_date,
        contract.terminal_timestamp_exclusive,
    ):
        raise ContractPreflightError("unauthorized D007 historical interval")


def assert_allowed_changed_paths(changed_paths: tuple[str, ...]) -> None:
    invalid = [
        path for path in changed_paths if not path.startswith(ALLOWED_CHANGED_PREFIXES)
    ]
    if invalid:
        raise ContractPreflightError(f"changed paths outside D007 contract ownership: {invalid}")


def required_endpoint_timestamps(
    event_at: pd.Timestamp | str,
    contract: HistoricalExecutionContract = DEFAULT_CONTRACT,
) -> tuple[pd.Timestamp, ...]:
    event = pd.Timestamp(event_at)
    if event.tz is None:
        raise ContractPreflightError("D007 event timestamp must be timezone-aware")
    event = event.tz_convert("UTC")
    if event.second or event.microsecond or event.nanosecond or event.minute % contract.bar_minutes:
        raise ContractPreflightError("D007 event timestamp must align to the frozen five-minute grid")
    required = tuple(
        event + pd.Timedelta(minutes=offset)
        for offset in range(0, contract.endpoint_minutes + 1, contract.bar_minutes)
    )
    named_years = tuple(named_trading_date(stamp).year for stamp in required)
    if any(year in contract.forbidden_named_years for year in named_years):
        raise ContractPreflightError("D007 endpoint enters forbidden New York named-year 2026")
    if any(year not in contract.validation_years for year in named_years):
        raise ContractPreflightError("D007 endpoint is outside the frozen validation years")
    terminal = pd.Timestamp(contract.terminal_timestamp_exclusive)
    if any(stamp >= terminal for stamp in required):
        raise ContractPreflightError("D007 endpoint exceeds the frozen source terminal boundary")
    return required


def _manifest_records(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("artifacts")
    if not isinstance(records, list):
        raise ContractPreflightError("D005 E4 artifact manifest is invalid")
    result: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("sha256"), str):
            raise ContractPreflightError("D005 E4 artifact manifest record is invalid")
        if record["path"] in result:
            raise ContractPreflightError("duplicate D005 E4 artifact manifest path")
        result[record["path"]] = record["sha256"]
    return result


def _relative_source_record_path(value: object) -> str:
    if not isinstance(value, str):
        raise ContractPreflightError("D005 E4 source path is invalid")
    marker = SOURCE_ROOT.as_posix() + "/"
    normalized = value.replace("\\", "/")
    if marker not in normalized:
        raise ContractPreflightError("D005 E4 source escaped the frozen source root")
    relative = normalized.split(marker, 1)[1]
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise ContractPreflightError("D005 E4 source relative path is unsafe")
    return Path(relative).as_posix()


def _verify_source_inventory(
    root: Path,
    source_provenance: dict[str, object],
    contract: HistoricalExecutionContract,
) -> tuple[str, int, int]:
    expected_fields = {
        "source_role": "hash_verified_d003_derived_e3_source",
        "requested_start_date": contract.source_start_date,
        "requested_end_date": contract.source_end_date,
        "file_count": contract.source_file_count,
        "row_count": contract.source_row_count,
        "selection_sha256": contract.source_selection_sha256,
        "hash_mismatch_count": 0,
        "read_only": True,
        "post_2025_d003_derived_available": False,
    }
    for field, expected in expected_fields.items():
        if source_provenance.get(field) != expected:
            raise ContractPreflightError(f"D005 E4 source provenance mismatch: {field}")
    authoritative = source_provenance.get("authoritative_source")
    if not isinstance(authoritative, str) or not authoritative.replace("\\", "/").endswith(SOURCE_ROOT.as_posix()):
        raise ContractPreflightError("D005 E4 authoritative source root mismatch")
    records = source_provenance.get("files")
    if not isinstance(records, list) or len(records) != contract.source_file_count:
        raise ContractPreflightError("D005 E4 source inventory count mismatch")
    inventory_rows: list[str] = []
    expected_paths: set[str] = set()
    observed_rows = 0
    source_root = root / SOURCE_ROOT
    for record in records:
        if not isinstance(record, dict):
            raise ContractPreflightError("D005 E4 source inventory record is invalid")
        relative = _relative_source_record_path(record.get("path"))
        if relative in expected_paths:
            raise ContractPreflightError("duplicate D005 E4 source inventory path")
        expected_paths.add(relative)
        byte_size = record.get("bytes")
        row_count = record.get("rows")
        expected_hash = record.get("sha256")
        if not isinstance(byte_size, int) or not isinstance(row_count, int) or not isinstance(expected_hash, str) or record.get("verified") is not True:
            raise ContractPreflightError("D005 E4 source inventory fields are invalid")
        candidate = source_root / relative
        if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_size != byte_size:
            raise ContractPreflightError(f"D005 E4 source member missing or changed: {relative}")
        if sha256_file(candidate) != expected_hash:
            raise ContractPreflightError(f"D005 E4 source member hash mismatch: {relative}")
        observed_rows += row_count
        inventory_rows.append(f"{relative}\t{byte_size}\t{row_count}\t{expected_hash}")
    actual_paths = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.parquet")
        if path.is_file() and not path.is_symlink()
    }
    if actual_paths != expected_paths:
        raise ContractPreflightError("D005 E4 source file membership mismatch")
    fingerprint = sha256("\n".join(sorted(inventory_rows)).encode()).hexdigest()
    if fingerprint != contract.relative_source_inventory_sha256:
        raise ContractPreflightError("D005 E4 relative source inventory fingerprint mismatch")
    if observed_rows != contract.source_row_count:
        raise ContractPreflightError("D005 E4 source row-count metadata mismatch")
    return fingerprint, len(expected_paths), observed_rows


def _verify_d005_e4(root: Path, contract: HistoricalExecutionContract) -> tuple[dict[str, str], dict[str, object]]:
    expected = dict(D005_E4_ARTIFACT_SHA256)
    observed = {
        name: verify_file_sha256(root / D005_E4_ROOT / name, digest, f"D005 E4 {name}")
        for name, digest in D005_E4_ARTIFACT_SHA256
    }
    manifest = _manifest_records(root / D005_E4_ROOT / "artifact_manifest.json")
    for name in ("configuration_snapshot.json", "source_provenance.json", "reproducibility_metadata.json", "implementation_provenance.json", "eligible_sequences.parquet", "displacement_anchors.parquet"):
        if manifest.get(name) != expected[name]:
            raise ContractPreflightError(f"D005 E4 manifest identity mismatch: {name}")
    reproducibility = json.loads((root / D005_E4_ROOT / "reproducibility_metadata.json").read_text(encoding="utf-8"))
    required = {
        "study_id": "D005_E4_1H_5M_REVERSAL_REPLICATION",
        "study_version": contract.d005_e4_version,
        "study_config_fingerprint": contract.d005_e4_config_fingerprint,
        "implementation_sha256": contract.d005_e4_implementation_sha256,
        "source_selection_sha256": contract.source_selection_sha256,
        "source_file_count": contract.source_file_count,
        "source_row_count": contract.source_row_count,
        "post_2025_d003_derived_available": False,
    }
    for field, value in required.items():
        if reproducibility.get(field) != value:
            raise ContractPreflightError(f"D005 E4 reproducibility identity mismatch: {field}")
    source_provenance = json.loads((root / D005_E4_ROOT / "source_provenance.json").read_text(encoding="utf-8"))
    return observed, source_provenance


def _verify_d004_lineage(root: Path, contract: HistoricalExecutionContract) -> str:
    path = root / D004_ROOT / "reproducibility_metadata.json"
    observed = verify_file_sha256(
        path,
        D004_REPRODUCIBILITY_SHA256,
        "D004 reproducibility metadata",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = payload.get("canonical_dataset")
    expected = {
        "dataset_version": contract.d003_release_id,
        "dataset_id": contract.d003_dataset_id,
        "manifest_sha256": contract.d003_canonical_manifest_sha256,
        "canonical_file_count": 1554,
        "canonical_row_count": 270997638,
        "date_range": {
            "start_inclusive": "2021-01-01T00:00:00Z",
            "end_exclusive": contract.terminal_timestamp_exclusive,
        },
    }
    if canonical != expected:
        raise ContractPreflightError("D004 canonical D003-v1 lineage mismatch")
    return observed


def _verify_d005_implementation(root: Path, contract: HistoricalExecutionContract) -> str:
    path = root / D005_E4_ROOT / "implementation_provenance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("files")
    if not isinstance(records, list) or not records:
        raise ContractPreflightError("D005 E4 implementation provenance is invalid")
    combined: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ContractPreflightError("D005 E4 implementation record is invalid")
        relative = record.get("path")
        expected_hash = record.get("sha256")
        expected_size = record.get("bytes")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or relative in seen
            or not isinstance(expected_hash, str)
            or not isinstance(expected_size, int)
        ):
            raise ContractPreflightError("D005 E4 implementation record fields are invalid")
        seen.add(relative)
        candidate = root / relative
        if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_size != expected_size:
            raise ContractPreflightError(f"D005 E4 implementation file missing or changed: {relative}")
        if sha256_file(candidate) != expected_hash:
            raise ContractPreflightError(f"D005 E4 implementation hash mismatch: {relative}")
        combined.append(f"{relative}:{expected_hash}")
    fingerprint = sha256("|".join(combined).encode("utf-8")).hexdigest()
    if payload.get("implementation_sha256") != fingerprint or fingerprint != contract.d005_e4_implementation_sha256:
        raise ContractPreflightError("D005 E4 implementation fingerprint mismatch")
    return fingerprint


def _verify_contract_implementation(root: Path) -> dict[str, str]:
    package = root / "research/d007_ote_historical_contract"
    observed: dict[str, str] = {}
    for name, expected in FROZEN_CONTRACT_IMPLEMENTATION_SHA256:
        actual = (
            normalized_config_sha256(package / name, expected)
            if name == "config.py"
            else verify_file_sha256(package / name, expected, f"D007 contract {name}")
        )
        if actual != expected:
            raise ContractPreflightError(f"D007 contract {name} SHA-256 mismatch")
        observed[name] = actual
    return observed


def run_contract_preflight(
    repository_root: Path,
    *,
    authorization: str,
    output_relative: Path = OUTPUT_DIRECTORY,
    contract: HistoricalExecutionContract = DEFAULT_CONTRACT,
    changed_paths: tuple[str, ...] = (),
) -> ContractPreflightResult:
    """Authorize only exact future execution without decoding historical rows."""

    if authorization != EXECUTION_AUTHORIZATION:
        raise ContractPreflightError("exact D007 historical execution authorization is required")
    assert_allowed_changed_paths(changed_paths)
    validate_frozen_contract(contract)
    root = repository_root.resolve()
    contract_spec = verify_file_sha256(root / CONTRACT_SPEC_PATH, CONTRACT_SPEC_SHA256, "D007 historical contract specification")
    clarification_spec = verify_file_sha256(
        root / CLARIFICATION_SPEC_PATH,
        CLARIFICATION_SPEC_SHA256,
        "D007 methodology clarification addendum",
    )
    clarification_module = verify_file_sha256(
        root / CLARIFICATION_MODULE_PATH,
        CLARIFICATION_MODULE_SHA256,
        "D007 methodology clarification module",
    )
    if clarification_spec != ADDENDUM_SHA256:
        raise ContractPreflightError("D007 clarification addendum identity mismatch")
    try:
        clarification_dependencies = verify_upstream_identities(root)
    except ValueError as error:
        raise ContractPreflightError(str(error)) from error
    synthetic_changed_paths = tuple(
        path for path in changed_paths if path.startswith(("research/d007_ote_research/", "tests/test_d007_", "docs/D007_"))
        and not path.startswith(("research/d007_ote_historical_contract/", "tests/test_d007_historical_contract.py", "docs/D007_HISTORICAL_EXECUTION_CONTRACT.md"))
    )
    synthetic = run_synthetic_preflight(root, synthetic_changed_paths)
    if synthetic.spec_sha256 != D007_SPEC_SHA256:
        raise ContractPreflightError("frozen D007 scientific specification changed")
    if d007_config_fingerprint() != D007_CONFIG_FINGERPRINT:
        raise ContractPreflightError("frozen D007 scientific configuration changed")
    if synthetic.implementation_fingerprint != D007_SYNTHETIC_IMPLEMENTATION_FINGERPRINT:
        raise ContractPreflightError("frozen D007 synthetic implementation changed")
    assert_authorized_output_path(root, output_relative)
    implementation_hashes = _verify_contract_implementation(root)
    d004_reproducibility = _verify_d004_lineage(root, contract)
    artifacts, source_provenance = _verify_d005_e4(root, contract)
    d005_implementation = _verify_d005_implementation(root, contract)
    inventory, file_count, row_count = _verify_source_inventory(root, source_provenance, contract)
    return ContractPreflightResult(
        contract_fingerprint=contract_fingerprint(contract),
        contract_spec_sha256=contract_spec,
        d007_spec_sha256=synthetic.spec_sha256,
        d007_config_fingerprint=d007_config_fingerprint(),
        d007_synthetic_implementation_fingerprint=synthetic.implementation_fingerprint,
        clarification_addendum_sha256=clarification_spec,
        clarification_module_sha256=clarification_module,
        clarification_dependency_hashes=clarification_dependencies,
        d005_e4_artifact_hashes=artifacts,
        contract_implementation_hashes=implementation_hashes,
        d004_reproducibility_sha256=d004_reproducibility,
        d005_e4_implementation_sha256=d005_implementation,
        source_selection_sha256=contract.source_selection_sha256,
        relative_source_inventory_sha256=inventory,
        source_file_count=file_count,
        source_row_count=row_count,
        output_directory=OUTPUT_DIRECTORY.as_posix(),
        historical_execution_authorized=True,
    )


__all__ = [
    "ContractPreflightError",
    "ContractPreflightResult",
    "assert_authorized_output_path",
    "assert_allowed_changed_paths",
    "assert_exact_interval",
    "required_endpoint_timestamps",
    "run_contract_preflight",
    "normalized_config_sha256",
    "sha256_file",
    "verify_file_sha256",
]
