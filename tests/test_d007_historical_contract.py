from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from research.d007_ote_historical_contract.__main__ import build_parser
from research.d007_ote_historical_contract.config import (
    CONTRACT_SPEC_PATH,
    CONTRACT_SPEC_SHA256,
    DEFAULT_CONTRACT,
    EXECUTION_AUTHORIZATION,
    FORBIDDEN_RUNTIME_PARAMETERS,
    FROZEN_CONTRACT_IMPLEMENTATION_SHA256,
    FROZEN_CONTRACT_FINGERPRINT,
    FROZEN_SCHEMA_SHA256,
    OUTPUT_DIRECTORY,
    VALIDATION_COMMANDS,
    HistoricalExecutionContract,
    contract_fingerprint,
    validate_frozen_contract,
)
from research.d007_ote_historical_contract.preflight import (
    ContractPreflightError,
    assert_allowed_changed_paths,
    assert_authorized_output_path,
    assert_exact_interval,
    required_endpoint_timestamps,
    run_contract_preflight,
    normalized_config_sha256,
    sha256_file,
    verify_file_sha256,
)
from research.d007_ote_historical_contract.runner import (
    HistoricalPipelineDeferred,
    run_historical_execution,
)
from research.d007_ote_historical_contract.schemas import (
    ALL_ARTIFACTS,
    JSON_ARTIFACTS,
    PARQUET_ARTIFACTS,
    REPORT_ARTIFACT,
    TABLE_SCHEMAS,
    schema_fingerprint,
)
from research.d007_ote_research.config import D007Config, config_fingerprint


ROOT = Path(__file__).resolve().parents[1]


def test_contract_identity_and_spec_are_frozen() -> None:
    validate_frozen_contract()
    assert contract_fingerprint() == FROZEN_CONTRACT_FINGERPRINT
    assert sha256_file(ROOT / CONTRACT_SPEC_PATH) == CONTRACT_SPEC_SHA256
    assert DEFAULT_CONTRACT.schema_sha256 == schema_fingerprint()
    assert schema_fingerprint() == FROZEN_SCHEMA_SHA256
    assert {name for name, _digest in FROZEN_CONTRACT_IMPLEMENTATION_SHA256} == {
        "__init__.py",
        "__main__.py",
        "config.py",
        "preflight.py",
        "runner.py",
        "schemas.py",
    }
    expected_config_hash = dict(FROZEN_CONTRACT_IMPLEMENTATION_SHA256)["config.py"]
    assert normalized_config_sha256(
        ROOT / "research/d007_ote_historical_contract/config.py",
        expected_config_hash,
    ) == expected_config_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_lineage_id", "d003-v2"),
        ("source_start_date", "2021-01-01"),
        ("source_end_date", "2026-07-28"),
        ("terminal_timestamp_exclusive", "2026-07-29T00:00:00Z"),
        ("validation_years", (2022, 2023, 2024, 2025, 2026)),
        ("output_directory", "research_outputs/alternate"),
        ("ote_band", (0.618, 0.786)),
        ("reference_depth", 0.71),
        ("equilibrium_depth", 0.51),
        ("upstream_mapping", "1h_1m"),
        ("upstream_event_type", "reaction_confirmed"),
        ("lifecycle_expiry_hours", 12),
    ],
)
def test_contract_rejects_lineage_interval_output_and_methodology_drift(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match="immutable"):
        replace(DEFAULT_CONTRACT, **{field: value})


def test_contract_keeps_original_scientific_configuration_unchanged() -> None:
    config = D007Config()
    assert config_fingerprint(config) == "83150b0f40e418fbe0ce1f7a308e62bff705af98be0267254375f82a585938a8"
    assert (config.geometries[0].proximal_depth, config.geometries[0].distal_depth) == (0.62, 0.79)
    assert config.geometries[0].reference_depth == 0.705
    assert config.validation_years == (2022, 2023, 2024, 2025)
    assert config.forbidden_years == (2026,)


def test_lineage_and_validation_commands_are_explicit() -> None:
    assert DEFAULT_CONTRACT.source_lineage_id == "d003-v1>D004-bars-1m>D005-E4-v1"
    assert DEFAULT_CONTRACT.source_role == "hash_verified_d003_derived_e3_source"
    assert DEFAULT_CONTRACT.source_root == "research_outputs/D004_XAUUSD_0830_0900/cache/bars_1m"
    assert not any("d003-v2" in value for value in DEFAULT_CONTRACT.snapshot().values() if isinstance(value, str))
    assert VALIDATION_COMMANDS[-2:] == ("python -m pytest -q", "git diff --check")
    assert any("d007_ote_historical_contract preflight" in command for command in VALIDATION_COMMANDS)


def test_changed_path_ownership_is_contract_scoped() -> None:
    assert_allowed_changed_paths(
        (
            "docs/D007_HISTORICAL_EXECUTION_CONTRACT.md",
            "research/d007_ote_historical_contract/preflight.py",
            "tests/test_d007_historical_contract.py",
        )
    )
    with pytest.raises(ContractPreflightError, match="outside D007 contract ownership"):
        assert_allowed_changed_paths(("xauusd_signal/strategy.py",))


def test_authorization_fails_before_repository_access(tmp_path: Path) -> None:
    with pytest.raises(ContractPreflightError, match="exact D007"):
        run_contract_preflight(tmp_path, authorization="wrong")


def test_file_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ContractPreflightError, match="SHA-256 mismatch"):
        verify_file_sha256(path, "0" * 64, "synthetic source")


def test_only_exact_output_namespace_is_authorized(tmp_path: Path) -> None:
    expected = assert_authorized_output_path(tmp_path)
    assert expected == (tmp_path / OUTPUT_DIRECTORY).resolve()
    for candidate in (
        Path("research_outputs/D006_REJECTION_BLOCK_RESEARCH"),
        Path("data/canonical/xauusd_ticks"),
        Path("xauusd_signal"),
        Path("research_outputs/d007_ote_research"),
    ):
        with pytest.raises(ContractPreflightError, match="unauthorized"):
            assert_authorized_output_path(tmp_path, candidate)
    expected.mkdir(parents=True)
    with pytest.raises(ContractPreflightError, match="must not exist"):
        assert_authorized_output_path(tmp_path)


def test_output_symlink_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "research_outputs").mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / OUTPUT_DIRECTORY).symlink_to(target, target_is_directory=True)
    with pytest.raises(ContractPreflightError, match="symlinks"):
        assert_authorized_output_path(tmp_path)


def test_only_exact_historical_interval_is_authorized() -> None:
    assert_exact_interval("2021-01-03", "2025-12-31", "2026-01-01T00:00:00Z")
    with pytest.raises(ContractPreflightError, match="interval"):
        assert_exact_interval("2021-01-03", "2026-07-28", "2026-07-29T00:00:00Z")


def test_endpoint_boundary_uses_new_york_named_year_and_source_terminal() -> None:
    required = required_endpoint_timestamps("2025-12-30T15:00:00Z")
    assert len(required) == 13
    assert required[-1] == pd.Timestamp("2025-12-30T16:00:00Z")
    with pytest.raises(ContractPreflightError, match="terminal boundary"):
        required_endpoint_timestamps("2025-12-31T23:30:00Z")
    with pytest.raises(ContractPreflightError, match="named-year 2026"):
        required_endpoint_timestamps("2026-01-01T05:00:00Z")
    with pytest.raises(ContractPreflightError, match="five-minute grid"):
        required_endpoint_timestamps("2025-12-30T15:02:00Z")


def test_canonical_cli_has_no_methodology_parameters() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["preflight", "--authorization", EXECUTION_AUTHORIZATION]
    )
    assert args.command == "preflight"
    for parameter in FORBIDDEN_RUNTIME_PARAMETERS:
        option = "--" + parameter.replace("_", "-")
        with pytest.raises(SystemExit):
            parser.parse_args(
                [
                    "execute",
                    "--authorization",
                    EXECUTION_AUTHORIZATION,
                    option,
                    "changed",
                ]
            )


def test_output_artifact_membership_and_schemas_are_exact() -> None:
    assert "artifact_manifest.json" in JSON_ARTIFACTS
    assert REPORT_ARTIFACT == "D007_OTE_HISTORICAL_RESEARCH_REPORT.md"
    assert tuple(sorted(TABLE_SCHEMAS)) == PARQUET_ARTIFACTS
    assert tuple(sorted((*JSON_ARTIFACTS, REPORT_ARTIFACT, *PARQUET_ARTIFACTS))) == ALL_ARTIFACTS
    assert all(name.endswith(".parquet") for name in PARQUET_ARTIFACTS)
    assert all(fields for fields in TABLE_SCHEMAS.values())
    assert len(ALL_ARTIFACTS) == len(set(ALL_ARTIFACTS))


def test_contract_package_contains_no_historical_outcome_implementation() -> None:
    package = ROOT / "research/d007_ote_historical_contract"
    forbidden_calls = {
        "read_parquet",
        "scan_parquet",
        "to_parquet",
        "ttest_1samp",
        "calculate_outcomes",
        "evaluate_lifecycle",
        "construct_ote_range",
    }
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                assert name not in forbidden_calls, f"forbidden outcome call {name} in {path}"


def test_outcome_blind_repository_preflight_authorizes_only_the_contract() -> None:
    result = run_contract_preflight(ROOT, authorization=EXECUTION_AUTHORIZATION)
    assert result.historical_execution_authorized is True
    assert result.contract_fingerprint == FROZEN_CONTRACT_FINGERPRINT
    assert result.source_file_count == 1554
    assert result.source_row_count == 1772168
    assert result.d004_reproducibility_sha256 == "c29fa7de14e51970ab51bc71f53c73d50ea470e8c1e6fc2d970273826a980133"
    assert result.d005_e4_implementation_sha256 == DEFAULT_CONTRACT.d005_e4_implementation_sha256
    assert result.contract_implementation_hashes == dict(FROZEN_CONTRACT_IMPLEMENTATION_SHA256)
    assert result.decoded_market_rows == 0
    assert result.constructed_d007_events == 0
    assert result.accessed_historical_outcomes is False
    assert result.applied_adequacy_gate is False
    assert result.performed_statistical_analysis is False
    assert result.wrote_outputs is False
    assert not (ROOT / OUTPUT_DIRECTORY).exists()


def test_execute_command_remains_deferred_after_valid_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    from research.d007_ote_historical_contract import runner

    observed: dict[str, object] = {}

    def fake_prepare(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(runner, "prepare_historical_execution", fake_prepare)
    with pytest.raises(HistoricalPipelineDeferred, match="HISTORICAL_PIPELINE_DEFERRED"):
        run_historical_execution(ROOT, authorization=EXECUTION_AUTHORIZATION)
    assert observed["kwargs"] == {
        "authorization": EXECUTION_AUTHORIZATION,
        "contract": DEFAULT_CONTRACT,
    }


def test_default_constructor_and_altered_schema_fail_closed() -> None:
    assert HistoricalExecutionContract() == DEFAULT_CONTRACT
    with pytest.raises(ValueError, match="schema fingerprint"):
        replace(DEFAULT_CONTRACT, schema_sha256="0" * 64)
