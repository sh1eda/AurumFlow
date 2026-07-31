from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from research.d005_e4_2026_independent_replication import (
    preflight as preflight_module,
)
from research.d005_e4_2026_independent_replication.cli import main
from research.d005_e4_2026_independent_replication.config import (
    ALLOWED_METRICS,
    FROZEN_END,
    FROZEN_HISTORICAL_HASHES,
    FROZEN_OUTPUT,
    FROZEN_START,
    IndependentReplication2026Config,
    artifact_requirements,
)
from research.d005_e4_2026_independent_replication.preflight import (
    build_preflight_result,
    sha256_file,
    verify_registered_artifact_directory,
    verify_release_integrity,
)


ROOT = Path(__file__).resolve().parents[1]


def _config() -> IndependentReplication2026Config:
    return IndependentReplication2026Config(independent_replication=True)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_release_fixture(root: Path) -> Path:
    release = root / "data/releases/d003-v2"
    canonical_root = root / "data/canonical/xauusd_ticks_d003-v2"
    parquet = (
        canonical_root
        / "year=2026/month=01/xauusd_ticks_2026-01-02.parquet"
    )
    parquet.parent.mkdir(parents=True)
    parquet.write_bytes(b"opaque-parquet-payload-not-read-by-preflight")
    relative = parquet.relative_to(root).as_posix()
    registered_parquet_hash = "a" * 64
    canonical = {
        "canonical_file_count": 1,
        "dataset_id": "fixture-d003-v2",
        "dataset_version": "d003-v2",
        "date_range": {
            "start_inclusive": "2021-01-01T00:00:00Z",
            "end_exclusive": "2026-07-29T00:00:00Z",
        },
        "files": [
            {
                "byte_size": parquet.stat().st_size,
                "path": relative,
                "sha256": registered_parquet_hash,
            }
        ],
        "reconciliation": {"balanced": True},
        "duplicate_count": 0,
        "rejected_record_count": 0,
        "row_count": 10,
        "status": "complete",
        "symbol": "XAUUSD",
    }
    canonical_path = canonical_root / "canonical_manifest.json"
    release_canonical = release / "canonical_manifest.json"
    _write_json(canonical_path, canonical)
    release.mkdir(parents=True, exist_ok=True)
    release_canonical.write_bytes(canonical_path.read_bytes())
    canonical_hash = sha256_file(canonical_path)
    parquet_manifest = release / "parquet_sha256.txt"
    parquet_manifest.write_text(
        f"{registered_parquet_hash}  {relative}\n",
        encoding="utf-8",
    )
    verification = release / "full_verification.json"
    _write_json(
        verification,
        {
            "canonical_manifest_sha256": canonical_hash,
            "dataset_id": canonical["dataset_id"],
            "dataset_version": canonical["dataset_version"],
            "date_range": canonical["date_range"],
            "errors": [],
            "metrics": {"canonical_file_count": 1, "row_count": 10},
            "passed": True,
            "symbol": "XAUUSD",
        },
    )
    descriptor = release / "RELEASE.txt"
    descriptor.write_text(
        "\n".join(
            [
                "release_id=d003-v2",
                "symbol=XAUUSD",
                "start_utc=2021-01-01T00:00:00Z",
                "end_utc=2026-07-29T00:00:00Z",
                "rows=10",
                "parquet_files=1",
                "duplicate_count=0",
                "rejected_record_count=0",
                "verification_passed=true",
                "verification_errors=0",
                "parquet_checksum_manifest_sha256="
                + sha256_file(parquet_manifest),
                "",
            ]
        ),
        encoding="utf-8",
    )
    release_manifest = release / "release_sha256.txt"
    release_manifest.write_text(
        "\n".join(
            [
                f"{sha256_file(release_canonical)}  "
                "data/releases/d003-v2/canonical_manifest.json",
                f"{sha256_file(verification)}  "
                "data/releases/d003-v2/full_verification.json",
                f"{sha256_file(parquet_manifest)}  "
                "data/releases/d003-v2/parquet_sha256.txt",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return parquet


def test_explicit_flag_and_exact_interval_are_required() -> None:
    with pytest.raises(ValueError, match="explicit"):
        IndependentReplication2026Config(
            independent_replication=False
        ).validate()
    config = _config()
    config.validate()
    assert config.start == FROZEN_START
    assert config.end == FROZEN_END


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start", "2026-01-02T00:00:00Z"),
        ("end", "2026-07-30T00:00:00Z"),
        ("start", "2025-01-01T00:00:00Z"),
        ("end", "2026-12-31T00:00:00Z"),
    ],
)
def test_alternative_intervals_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="only"):
        replace(_config(), **{field: value}).validate()


def test_historical_execution_and_tuning_paths_cannot_be_enabled() -> None:
    fields = (
        "historical_selection_authorized",
        "historical_fitting_authorized",
        "parameter_search_authorized",
        "outcome_calculation_authorized",
        "production_integration_authorized",
    )
    for field in fields:
        with pytest.raises(ValueError, match="preflight cannot authorize"):
            replace(_config(), **{field: True}).validate()


def test_output_path_is_fixed_and_cannot_collide() -> None:
    assert _config().output_dir == FROZEN_OUTPUT
    with pytest.raises(ValueError, match="output directory is frozen"):
        replace(
            _config(),
            output_dir=(
                "research_outputs/"
                "D005_E4_1H_5M_REVERSAL_REPLICATION"
            ),
        ).validate()


def test_trade_or_pnl_metrics_cannot_be_requested() -> None:
    assert _config().requested_metrics == ALLOWED_METRICS
    with pytest.raises(ValueError, match="metric set is frozen"):
        replace(
            _config(),
            requested_metrics=ALLOWED_METRICS + ("expectancy_r",),
        ).validate()


def test_frozen_historical_files_match_and_preflight_does_not_change_them() -> None:
    before = {
        relative: sha256_file(ROOT / relative)
        for relative in FROZEN_HISTORICAL_HASHES
    }
    assert before == FROZEN_HISTORICAL_HASHES
    result = build_preflight_result(
        repository_root=ROOT,
        config=_config(),
    )
    after = {
        relative: sha256_file(ROOT / relative)
        for relative in FROZEN_HISTORICAL_HASHES
    }
    assert after == before
    assert result["historical_implementation_integrity"]["all_verified"]


def test_missing_artifacts_fail_closed_without_creating_output(tmp_path: Path) -> None:
    result = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    assert not result["all_required_artifacts_present"]
    assert not result["authorized_to_calculate_2026_outcomes"]
    assert not result["output_directory_created"]
    assert not (tmp_path / FROZEN_OUTPUT).exists()
    assert any(
        reason.startswith("MISSING_REQUIRED_ARTIFACT:")
        for reason in result["blocking_reasons"]
    )


def test_missing_automation_config_is_warning_not_replication_dependency(
    tmp_path: Path,
) -> None:
    automation = next(
        requirement
        for requirement in artifact_requirements()
        if requirement.name == "automation_validation_aid"
    )
    assert not automation.required
    result = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    assert result["automation_validation_aid"] == {
        "path": "automation/config.yaml",
        "present": False,
        "authoritative_definition_found": False,
        "scientific_replication_dependency": False,
        "blocks_replication_authorization": False,
        "classification": "unavailable_repository_level_validation_aid",
    }
    assert (
        "UNAVAILABLE_REPOSITORY_VALIDATION_AID:automation/config.yaml"
        in result["warnings"]
    )
    assert not any(
        "automation" in reason.lower()
        for reason in result["blocking_reasons"]
    )


def test_release_manifests_cross_verify_without_opening_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet = _write_release_fixture(tmp_path)
    hashed_paths: list[Path] = []
    original = preflight_module.sha256_file

    def guarded_sha256(path: Path) -> str:
        hashed_paths.append(path)
        assert path.suffix != ".parquet"
        return original(path)

    monkeypatch.setattr(preflight_module, "sha256_file", guarded_sha256)
    result = verify_release_integrity(tmp_path)
    assert result["metadata_and_manifest_integrity_verified"], result["errors"]
    assert result["parquet_checksum_entry_count"] == 1
    assert result["actual_parquet_path_count"] == 1
    assert result["independent_2026_parquet_path_count"] == 1
    assert result["parquet_file_content_hashes_verified"] is False
    assert result["parquet_files_opened"] == 0
    assert parquet not in hashed_paths


def test_release_manifest_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_release_fixture(tmp_path)
    path = tmp_path / "data/releases/d003-v2/parquet_sha256.txt"
    path.write_text(
        path.read_text(encoding="utf-8").replace("a" * 64, "b" * 64),
        encoding="utf-8",
    )
    result = verify_release_integrity(tmp_path)
    assert not result["metadata_and_manifest_integrity_verified"]
    assert result["errors"]


def test_registered_historical_artifact_hash_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "historical-output"
    output.mkdir()
    artifact = output / "table.parquet"
    artifact.write_bytes(b"historical-only")
    _write_json(
        output / "artifact_manifest.json",
        {
            "artifacts": [
                {
                    "bytes": artifact.stat().st_size,
                    "path": artifact.name,
                    "sha256": sha256_file(artifact),
                }
            ]
        },
    )
    verified = verify_registered_artifact_directory(output)
    assert verified["all_registered_hashes_verified"]
    assert verified["parquet_files_hashed"] == 1
    artifact.write_bytes(b"historical-Only")
    mismatch = verify_registered_artifact_directory(output)
    assert not mismatch["all_registered_hashes_verified"]
    assert any("hash mismatch" in error for error in mismatch["errors"])


def test_preflight_never_hashes_2026_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parquet = _write_release_fixture(tmp_path)
    hashed_paths: list[Path] = []
    original = preflight_module.sha256_file

    def guarded_sha256(path: Path) -> str:
        hashed_paths.append(path)
        assert path != parquet
        return original(path)

    monkeypatch.setattr(preflight_module, "sha256_file", guarded_sha256)
    result = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    assert result["preflight_opened_2026_parquet_files"] == 0
    assert parquet not in hashed_paths
    assert not result["authorized_to_calculate_2026_outcomes"]


def test_empty_2026_partition_directory_is_present_but_incomplete(
    tmp_path: Path,
) -> None:
    (tmp_path / "data/canonical/xauusd_ticks_d003-v2/year=2026").mkdir(
        parents=True
    )
    result = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    partition = next(
        record
        for record in result["artifact_availability"]
        if record["artifact_name"]
        == "canonical_d003_v2_2026_parquet_partitions"
    )
    assert partition["present"]
    assert not partition["complete"]
    assert partition["parquet_file_count"] == 0


def test_fingerprints_and_integrity_fields_are_deterministic(tmp_path: Path) -> None:
    first = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    second = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    assert first == second
    assert first["configuration_fingerprint"] == _config().fingerprint()
    assert first["historical_specification"]["sha256"] is None
    assert first["extension_specification"]["sha256"] is None


def test_preflight_result_emits_no_trade_or_pnl_metrics(tmp_path: Path) -> None:
    result = build_preflight_result(
        repository_root=tmp_path,
        config=_config(),
    )
    encoded = json.dumps(result, sort_keys=True)
    for forbidden in (
        "expectancy_r",
        "profit_factor",
        "stop_hit_count",
        "target_hit_count",
        "trade_count",
        "fill_rate",
    ):
        assert forbidden not in encoded


def test_cli_fails_closed_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "--independent-replication",
            "--start",
            FROZEN_START,
            "--end",
            FROZEN_END,
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 2
    assert payload["authorized_to_calculate_2026_outcomes"] is False
    assert not (tmp_path / FROZEN_OUTPUT).exists()
