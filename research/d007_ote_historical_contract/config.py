"""Frozen outcome-blind operational contract for later D007 history."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from .schemas import ALL_ARTIFACTS, schema_fingerprint


CONTRACT_SPEC_PATH = Path("docs/D007_HISTORICAL_EXECUTION_CONTRACT.md")
CONTRACT_SPEC_SHA256 = "59fc8ddd0ab1aa8786de573817e1ac47d1efcfd81918c8754b4f3150ac818a84"
CLARIFICATION_SPEC_PATH = Path("docs/D007_METHODOLOGY_CLARIFICATION.md")
CLARIFICATION_SPEC_SHA256 = "b5637a24ce9cb97c35e68636d17fe2359396397422652d1ff5b2d3c2811f087b"
CLARIFICATION_MODULE_PATH = Path("research/d007_methodology_clarification.py")
CLARIFICATION_MODULE_SHA256 = "cf58d7f34b5b00ccc1168cb60a85f417ecc1527c276641213084515e97cd5ca1"
ASSOCIATION_SPEC_PATH = Path("docs/D007_ASSOCIATION_IDENTITY_CLARIFICATION.md")
ASSOCIATION_SPEC_SHA256 = "a885365ff2fb4004792a0af54b9eab4e51ad1b9095ed650d458306050305f2de"
ASSOCIATION_MODULE_PATH = Path("research/d007_association_identity.py")
ASSOCIATION_MODULE_SHA256 = "02c7ba7f64fb7aac5b6ab9ba17e1a24eae60fe6398c5f2e3b978616a10130553"
FROZEN_CONTRACT_FINGERPRINT = "6c30867112c1c50acef36e276a72987b791bcf1ac8efd76e78d441b35c60507b"
FROZEN_SCHEMA_SHA256 = "703f6c0d61e7d73cf13ad14e36732abbb91acf141f104ec46ea4f03252061d31"
EXECUTION_AUTHORIZATION = "EXECUTE_FROZEN_D007_OTE_2022_2025"
CANONICAL_MODULE = "research.d007_ote_historical_contract"
CANONICAL_EXECUTION_COMMAND = (
    "python -m research.d007_ote_historical_contract execute "
    "--authorization EXECUTE_FROZEN_D007_OTE_2022_2025"
)
OUTPUT_DIRECTORY = Path("research_outputs/D007_OTE_RESEARCH")
STAGING_PREFIX = ".D007_OTE_RESEARCH.staging-"
PUBLICATION_LOCK = Path("research_outputs/.D007_OTE_RESEARCH.publish.lock")
SOURCE_ROOT = Path("research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m")
D004_ROOT = Path("research_outputs/D004_XAUUSD_0830_0900")
D004_REPRODUCIBILITY_SHA256 = "c29fa7de14e51970ab51bc71f53c73d50ea470e8c1e6fc2d970273826a980133"
D005_E4_ROOT = Path("research_outputs/D005_E4_1H_5M_REVERSAL_REPLICATION")

D007_SPEC_SHA256 = "adb093f40b0a3a43a6174e81763e3625d38e88ba223f4b392076a240918d364f"
D007_CONFIG_FINGERPRINT = "83150b0f40e418fbe0ce1f7a308e62bff705af98be0267254375f82a585938a8"
D007_SYNTHETIC_IMPLEMENTATION_FINGERPRINT = (
    "475208c3f41d57ed283d64ba8b8955b848b7fe09ef92b0f7d026c1268c010987"
)

D005_E4_ARTIFACT_SHA256 = (
    ("artifact_manifest.json", "f8807f56db5b31832422c9df1350343e932411673af86c09ddfaf8cdcaef8445"),
    ("configuration_snapshot.json", "1fb9a52d2ad2ab80d23e16d3c6009082713ed86aeea60e8725e883d849ea11a8"),
    ("displacement_anchors.parquet", "d6a45058c11f32a7cb476d2ec578c50f53c017b080f3537002c1624049e42ce0"),
    ("eligible_sequences.parquet", "059e7053e46f753f5cede6714f2de5ea3a5a0ee47ae7d781cdd55d6af1c00b40"),
    ("implementation_provenance.json", "0a4dd92f19df0afd48663afc3d78000162d680c8bf683a5ac5944f10889160fe"),
    ("reproducibility_metadata.json", "e0b98a979545983d6608dfd16c5f9c9e86a5c1a5c269074bc01cb1444fd65aa9"),
    ("source_provenance.json", "65cfdeb98358cc88390eabb48b57ff380b50d92467c906b45094339efb9a21e1"),
)

FROZEN_CONTRACT_IMPLEMENTATION_SHA256 = (
    ("__init__.py", "f6d2f94b05d9410d7d1bdf25ab7138b73f6f44184f0730d33189bdef3113588a"),
    ("__main__.py", "53caca90c43d3b8f8c9fe7b65dadd531ce8620cd5ef2d7a80c7ddddd6710f729"),
    ("config.py", "12c81a9afd3fa9fdabaa1aacaa206211c26270dbd9df98d7c7508b3692f77f8a"),
    ("preflight.py", "c85861e2ef67bc45df260a90258e24259ce94794edfde4189c50c5415150a07c"),
    ("runner.py", "88d3fc00a9722ffa827f782b8fd00d3e69cc533c576dceb69c87ee3f9f46f9b0"),
    ("schemas.py", "9a085db7ca73256575b1c90c490dc1c8e97bae49830e4ba54d57ec23397933b0"),
)

ALLOWED_CHANGED_PREFIXES = (
    "docs/D007_METHODOLOGY_CLARIFICATION.md",
    "docs/D007_ASSOCIATION_IDENTITY_CLARIFICATION.md",
    "docs/D007_HISTORICAL_EXECUTION_CONTRACT.md",
    "research/d007_methodology_clarification.py",
    "research/d007_association_identity.py",
    "research/d007_ote_research/guardrails.py",
    "research/d007_ote_historical_contract/",
    "tests/test_d007_methodology_clarification.py",
    "tests/test_d007_association_identity.py",
    "tests/test_d007_historical_contract.py",
)

VALIDATION_COMMANDS = (
    "python -m pytest tests/test_d007_association_identity.py tests/test_d007_methodology_clarification.py tests/test_d007_historical_contract.py tests/test_d007_ote_research.py -q",
    "python -m pytest tests/test_d005_e4_1h_5m_reversal_replication.py tests/test_d005_e5_reporting_hardening.py tests/test_d005_e6_future_blind_replication.py -q",
    "python -m pytest tests/test_d006_rejection_block_research.py tests/test_d006_historical_source.py tests/test_d006_historical_context.py tests/test_d006_historical_execution.py -q",
    "python -m research.d007_ote_historical_contract preflight --authorization EXECUTE_FROZEN_D007_OTE_2022_2025",
    "python -m pytest -q",
    "git diff --check",
)

FORBIDDEN_RUNTIME_PARAMETERS = (
    "ote_band",
    "reference_depth",
    "equilibrium_depth",
    "swing_selector",
    "endpoint_selector",
    "upstream_mapping",
    "lifecycle_expiry_hours",
    "controls",
    "interactions",
    "adequacy_thresholds",
    "statistical_family",
    "outcome_definition",
)


@dataclass(frozen=True)
class HistoricalExecutionContract:
    contract_id: str = "D007_OTE_HISTORICAL_EXECUTION_CONTRACT"
    version: str = "d007-historical-contract-v1"
    research_only: bool = True
    production_authorized: bool = False
    historical_execution_default: bool = False
    authorization_token: str = EXECUTION_AUTHORIZATION
    source_lineage_id: str = "d003-v1>D004-bars-1m>D005-E4-v1"
    source_role: str = "hash_verified_d003_derived_e3_source"
    source_root: str = SOURCE_ROOT.as_posix()
    source_start_date: str = "2021-01-03"
    source_end_date: str = "2025-12-31"
    terminal_timestamp_exclusive: str = "2026-01-01T00:00:00Z"
    source_file_count: int = 1554
    source_row_count: int = 1772168
    source_selection_sha256: str = "21f410613d95ec9482b0baa1766b64e362725ec60d817bf53e1d4b511636c3e3"
    relative_source_inventory_sha256: str = "f76e6e88870c505da68b0615bc5dfc6aefe2da08afad0fede7ae159df88d9659"
    d003_release_id: str = "d003-v1"
    d003_dataset_id: str = "3ef1612c3ac73469e0b0"
    d003_canonical_manifest_sha256: str = "16a560443f6429e4250d68af7b5a02d7da255d7dfcf7b2945d34a2c29a9d62ab"
    d005_e4_version: str = "D005-E4-v1"
    d005_e4_config_fingerprint: str = "34e044c602ca0e7aa5a467273e20538171b0363b6c72f6ed9415dc281d825880"
    d005_e4_implementation_sha256: str = "c6ab71a0709a647be301fd7886d566d5d0f0a2ed3ea6df5fb29b900ed44869af"
    calibration_year: int = 2021
    validation_years: tuple[int, ...] = (2022, 2023, 2024, 2025)
    forbidden_named_years: tuple[int, ...] = (2026,)
    timezone: str = "America/New_York"
    endpoint_minutes: int = 60
    bar_minutes: int = 5
    output_directory: str = OUTPUT_DIRECTORY.as_posix()
    staging_prefix: str = STAGING_PREFIX
    publication_lock: str = PUBLICATION_LOCK.as_posix()
    overwrite_existing_output: bool = False
    artifact_manifest_schema: str = "d007-ote-artifact-manifest-v1"
    run_manifest_schema: str = "d007-ote-run-manifest-v1"
    output_artifacts: tuple[str, ...] = ALL_ARTIFACTS
    schema_sha256: str = FROZEN_SCHEMA_SHA256
    ote_band: tuple[float, float] = (0.62, 0.79)
    reference_depth: float = 0.705
    equilibrium_depth: float = 0.50
    upstream_mapping: str = "1h_5m"
    upstream_event_type: str = "displacement_confirmation"
    lifecycle_expiry_hours: int = 24

    def __post_init__(self) -> None:
        if (
            self.contract_id,
            self.version,
            self.research_only,
            self.production_authorized,
            self.historical_execution_default,
            self.authorization_token,
            self.source_lineage_id,
            self.source_role,
            self.source_root,
            self.source_start_date,
            self.source_end_date,
            self.terminal_timestamp_exclusive,
            self.source_file_count,
            self.source_row_count,
            self.source_selection_sha256,
            self.relative_source_inventory_sha256,
            self.d003_release_id,
            self.d003_dataset_id,
            self.d003_canonical_manifest_sha256,
            self.d005_e4_version,
            self.d005_e4_config_fingerprint,
            self.d005_e4_implementation_sha256,
            self.calibration_year,
            self.validation_years,
            self.forbidden_named_years,
            self.timezone,
            self.endpoint_minutes,
            self.bar_minutes,
            self.output_directory,
            self.staging_prefix,
            self.publication_lock,
            self.overwrite_existing_output,
            self.artifact_manifest_schema,
            self.run_manifest_schema,
            self.output_artifacts,
            self.ote_band,
            self.reference_depth,
            self.equilibrium_depth,
            self.upstream_mapping,
            self.upstream_event_type,
            self.lifecycle_expiry_hours,
        ) != (
            "D007_OTE_HISTORICAL_EXECUTION_CONTRACT",
            "d007-historical-contract-v1",
            True,
            False,
            False,
            EXECUTION_AUTHORIZATION,
            "d003-v1>D004-bars-1m>D005-E4-v1",
            "hash_verified_d003_derived_e3_source",
            SOURCE_ROOT.as_posix(),
            "2021-01-03",
            "2025-12-31",
            "2026-01-01T00:00:00Z",
            1554,
            1772168,
            "21f410613d95ec9482b0baa1766b64e362725ec60d817bf53e1d4b511636c3e3",
            "f76e6e88870c505da68b0615bc5dfc6aefe2da08afad0fede7ae159df88d9659",
            "d003-v1",
            "3ef1612c3ac73469e0b0",
            "16a560443f6429e4250d68af7b5a02d7da255d7dfcf7b2945d34a2c29a9d62ab",
            "D005-E4-v1",
            "34e044c602ca0e7aa5a467273e20538171b0363b6c72f6ed9415dc281d825880",
            "c6ab71a0709a647be301fd7886d566d5d0f0a2ed3ea6df5fb29b900ed44869af",
            2021,
            (2022, 2023, 2024, 2025),
            (2026,),
            "America/New_York",
            60,
            5,
            OUTPUT_DIRECTORY.as_posix(),
            STAGING_PREFIX,
            PUBLICATION_LOCK.as_posix(),
            False,
            "d007-ote-artifact-manifest-v1",
            "d007-ote-run-manifest-v1",
            ALL_ARTIFACTS,
            (0.62, 0.79),
            0.705,
            0.50,
            "1h_5m",
            "displacement_confirmation",
            24,
        ):
            raise ValueError("D007 historical execution contract is immutable")
        if self.schema_sha256 != schema_fingerprint():
            raise ValueError("D007 historical output schema fingerprint changed")

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload.update(
            {
                "canonical_execution_command": CANONICAL_EXECUTION_COMMAND,
                "association_module_path": ASSOCIATION_MODULE_PATH.as_posix(),
                "association_module_sha256": ASSOCIATION_MODULE_SHA256,
                "association_spec_path": ASSOCIATION_SPEC_PATH.as_posix(),
                "association_spec_sha256": ASSOCIATION_SPEC_SHA256,
                "clarification_module_path": CLARIFICATION_MODULE_PATH.as_posix(),
                "clarification_module_sha256": CLARIFICATION_MODULE_SHA256,
                "clarification_spec_path": CLARIFICATION_SPEC_PATH.as_posix(),
                "clarification_spec_sha256": CLARIFICATION_SPEC_SHA256,
                "contract_spec_path": CONTRACT_SPEC_PATH.as_posix(),
                "contract_spec_sha256": CONTRACT_SPEC_SHA256,
                "d007_config_fingerprint": D007_CONFIG_FINGERPRINT,
                "d007_spec_sha256": D007_SPEC_SHA256,
                "d007_synthetic_implementation_fingerprint": D007_SYNTHETIC_IMPLEMENTATION_FINGERPRINT,
                "d005_e4_artifact_sha256": list(D005_E4_ARTIFACT_SHA256),
                "d004_reproducibility_sha256": D004_REPRODUCIBILITY_SHA256,
                "forbidden_runtime_parameters": list(FORBIDDEN_RUNTIME_PARAMETERS),
                "validation_commands": list(VALIDATION_COMMANDS),
            }
        )
        return payload


DEFAULT_CONTRACT = HistoricalExecutionContract()


def contract_fingerprint(contract: HistoricalExecutionContract = DEFAULT_CONTRACT) -> str:
    encoded = json.dumps(
        contract.snapshot(), sort_keys=True, separators=(",", ":")
    ).encode()
    return sha256(encoded).hexdigest()


def validate_frozen_contract(contract: HistoricalExecutionContract = DEFAULT_CONTRACT) -> None:
    if contract != DEFAULT_CONTRACT:
        raise ValueError("D007 historical execution contract changed")
    if CONTRACT_SPEC_SHA256 == "CONTRACT_SPEC_SHA256_PLACEHOLDER":
        raise ValueError("D007 historical contract specification hash is not frozen")
    if FROZEN_CONTRACT_FINGERPRINT == "CONTRACT_FINGERPRINT_PLACEHOLDER":
        raise ValueError("D007 historical contract fingerprint is not frozen")
    if any(digest.endswith("PLACEHOLDER") for _path, digest in FROZEN_CONTRACT_IMPLEMENTATION_SHA256):
        raise ValueError("D007 historical contract implementation hashes are not frozen")
    if contract_fingerprint(contract) != FROZEN_CONTRACT_FINGERPRINT:
        raise ValueError("D007 historical contract fingerprint mismatch")


__all__ = [
    "ASSOCIATION_MODULE_PATH",
    "ASSOCIATION_MODULE_SHA256",
    "ASSOCIATION_SPEC_PATH",
    "ASSOCIATION_SPEC_SHA256",
    "CANONICAL_EXECUTION_COMMAND",
    "CLARIFICATION_MODULE_PATH",
    "CLARIFICATION_MODULE_SHA256",
    "CLARIFICATION_SPEC_PATH",
    "CLARIFICATION_SPEC_SHA256",
    "CONTRACT_SPEC_PATH",
    "CONTRACT_SPEC_SHA256",
    "DEFAULT_CONTRACT",
    "D005_E4_ARTIFACT_SHA256",
    "D005_E4_ROOT",
    "D004_REPRODUCIBILITY_SHA256",
    "D004_ROOT",
    "EXECUTION_AUTHORIZATION",
    "FORBIDDEN_RUNTIME_PARAMETERS",
    "FROZEN_CONTRACT_IMPLEMENTATION_SHA256",
    "FROZEN_CONTRACT_FINGERPRINT",
    "FROZEN_SCHEMA_SHA256",
    "HistoricalExecutionContract",
    "OUTPUT_DIRECTORY",
    "PUBLICATION_LOCK",
    "SOURCE_ROOT",
    "STAGING_PREFIX",
    "VALIDATION_COMMANDS",
    "contract_fingerprint",
    "validate_frozen_contract",
]
