from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.d007_ote_historical_contract.artifacts import (
    ArtifactError,
    ArtifactPackage,
    empty_table_frame,
    publish_package,
    publish_synthetic_package,
    stage_package,
    verify_staged_package,
)
from research.d007_ote_historical_contract.schemas import JSON_ARTIFACTS, TABLE_SCHEMAS


def _package() -> ArtifactPackage:
    json_objects = {
        name: {"artifact": name, "synthetic": True}
        for name in JSON_ARTIFACTS
        if name != "artifact_manifest.json"
    }
    tables = {name: empty_table_frame(name) for name in TABLE_SCHEMAS}
    return ArtifactPackage(json_objects, "# Synthetic D007 Report\n", tables)


def test_synthetic_package_stages_and_verifies_exact_membership(tmp_path: Path) -> None:
    staging = tmp_path / "stage"
    manifest = stage_package(_package(), staging)
    assert manifest == verify_staged_package(staging)
    assert manifest["schema"] == "d007-ote-artifact-manifest-v1"
    assert "artifact_manifest.json" not in {row["path"] for row in manifest["artifacts"]}


def test_publication_is_atomic_and_refuses_overwrite(tmp_path: Path) -> None:
    output = publish_synthetic_package(tmp_path, Path("synthetic/output"), _package())
    assert output == tmp_path / "synthetic/output"
    with pytest.raises(ArtifactError, match="must not exist|overwrite"):
        publish_synthetic_package(tmp_path, Path("synthetic/output"), _package())


def test_publication_lock_is_exclusive_and_removed_after_failure(tmp_path: Path) -> None:
    lock = tmp_path / ".d007-synthetic.publish.lock"
    lock.write_text("held\n", encoding="utf-8")
    with pytest.raises(ArtifactError, match="lock already exists"):
        publish_synthetic_package(tmp_path, Path("synthetic/output"), _package())
    lock.unlink()

    broken = _package()
    broken = ArtifactPackage({}, broken.report, broken.tables)
    with pytest.raises(ArtifactError, match="membership"):
        publish_synthetic_package(tmp_path, Path("synthetic/output"), broken)
    assert not lock.exists()


def test_staging_failure_leaves_no_final_output_or_staging(tmp_path: Path) -> None:
    broken = _package()
    broken = ArtifactPackage(
        {name: value for name, value in broken.json_objects.items() if name != "summary.json"},
        broken.report,
        broken.tables,
    )
    with pytest.raises(ArtifactError, match="membership"):
        publish_synthetic_package(tmp_path, Path("synthetic/output"), broken)
    assert not (tmp_path / "research_outputs/D007_OTE_RESEARCH").exists()
    parent = tmp_path / "research_outputs"
    assert not parent.exists() or not list(parent.glob(".D007_OTE_RESEARCH.staging-*"))


def test_schema_and_checksum_drift_fail_closed(tmp_path: Path) -> None:
    package = _package()
    tables = dict(package.tables)
    tables["control_matches.parquet"] = tables["control_matches.parquet"].drop(
        columns="matched"
    )
    with pytest.raises(ArtifactError, match="columns"):
        stage_package(ArtifactPackage(package.json_objects, package.report, tables), tmp_path / "bad-schema")

    staging = tmp_path / "valid"
    stage_package(package, staging)
    (staging / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ArtifactError, match="checksum"):
        verify_staged_package(staging)


def test_symlink_and_unauthorized_output_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "research_outputs").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "research_outputs/D007_OTE_RESEARCH").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ArtifactError, match="symlink"):
        publish_package(tmp_path, _package())
    with pytest.raises(ArtifactError, match="unauthorized"):
        publish_package(tmp_path, _package(), output_relative=Path("research_outputs/alternate"))


def test_json_is_canonical_and_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    stage_package(_package(), first)
    stage_package(_package(), second)
    first_manifest = json.loads((first / "artifact_manifest.json").read_text())
    second_manifest = json.loads((second / "artifact_manifest.json").read_text())
    assert first_manifest == second_manifest
