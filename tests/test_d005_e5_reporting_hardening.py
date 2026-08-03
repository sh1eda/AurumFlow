"""Focused boundary tests for the D005_E5 aggregate-only review."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from research.d005_e5_reporting_hardening import review


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _write_e4_fixture(root: Path) -> Path:
    source = root / review.E4_OUTPUT_RELATIVE
    source.mkdir(parents=True)
    summary = {
        "integrity_status": "INTEGRITY_VERIFIED",
        "adequacy_status": "INDEPENDENT_SAMPLE_INADEQUATE",
        "primary_replication_status": "NOT_EVALUATED",
        "primary_registered_metrics": {"sample_count": 156, "mean_signed_movement": 1.25},
        "registered_checks": {"required_endpoint_coverage": False},
        "secondary_diagnostics": [{"sample_count": 10, "p_value": 0.4}],
    }
    run_manifest = {
        "study_id": "d005-e4-2026-independent-replication",
        "accepted_interval": {"start": "2026-01-01T00:00:00Z", "end_exclusive": "2026-07-29T00:00:00Z"},
        "structural_inventory_fingerprint": "structural-fingerprint",
        "outcome_implementation_fingerprint": "implementation-fingerprint",
        **{key: summary[key] for key in review.REQUIRED_STATUSES},
    }
    scientific = {
        "study_id": run_manifest["study_id"],
        "accepted_interval": run_manifest["accepted_interval"],
        "structural_inventory_fingerprint": run_manifest["structural_inventory_fingerprint"],
        "result": summary,
    }
    fingerprint = review._fingerprint(scientific)
    summary["deterministic_result_fingerprint"] = fingerprint
    run_manifest["deterministic_result_fingerprint"] = fingerprint
    payloads: dict[str, object] = {
        "summary.json": summary,
        "run_manifest.json": run_manifest,
        "statistical_validation.json": {"sample_count": 156, "null_metric": None},
        "secondary_diagnostics.json": [{"sample_count": 10, "p_value": 0.4}],
        "direction_summary.json": [{"direction": 1, "sample_count": 80}],
        "monthly_summary.json": [{"anchor_month": "2026-01", "sample_count": 25}],
        "session_summary.json": [{"session": "ny", "sample_count": 25}],
        "paired_refinement_summary.json": [{"paired_sequence_count": 50, "mean": 0.0}],
        "historical_comparison.json": {"historical_sample_count": 1778},
    }
    for name, payload in payloads.items():
        (source / name).write_text(_dump(payload), encoding="utf-8")
    (source / "report.md").write_text("frozen report\n", encoding="utf-8")
    records = [
        {
            "path": name,
            "bytes": (source / name).stat().st_size,
            "sha256": hashlib.sha256((source / name).read_bytes()).hexdigest(),
        }
        for name in sorted(review.E4_FILES - {"artifact_manifest.json"})
    ]
    manifest = {
        "schema_version": "d005-e4-2026-artifact-manifest-v1",
        "scientific_result_fingerprint": fingerprint,
        "manifest_self_excluded": True,
        "manifest_self_exclusion_reason": "self-referential checksum is circular",
        "artifacts": records,
    }
    (source / "artifact_manifest.json").write_text(_dump(manifest), encoding="utf-8")
    return source


def _assert_qualified_tree(source: object, observed: object) -> None:
    if isinstance(source, dict):
        assert isinstance(observed, dict)
        assert set(observed) == set(source)
        for key, value in source.items():
            _assert_qualified_tree(value, observed[key])
    elif isinstance(source, list):
        assert isinstance(observed, list)
        assert len(observed) == len(source)
        for left, right in zip(source, observed):
            _assert_qualified_tree(left, right)
    else:
        assert observed == {
            "source_value": source,
            "qualification": review.QUALIFICATION,
        }


def test_verified_review_preserves_exact_leaves_and_stops_at_adequacy(tmp_path: Path) -> None:
    source = _write_e4_fixture(tmp_path)
    source_bytes = {path.name: path.read_bytes() for path in source.iterdir()}
    audit = review.build_audit_report(source)

    assert audit["scientific_decision_authorized"] is False
    assert audit["all_metrics_descriptive_only"] is True
    assert audit["replication_evidence_claim_permitted"] is False
    assert audit["blind_replication"] is False
    assert audit["independent_replication"] is False
    assert audit["original_execution_modified"] is False
    assert audit["fixed_decision_tree"]["terminal_status"]["source_value"] == "NOT_EVALUATED"
    assert audit["fixed_decision_tree"]["terminates_at"] == "ADEQUACY_FAILURE"
    assert audit["endpoint_audit"]["structural_primary_cohort_count"] == "UNAVAILABLE_IN_FROZEN_AGGREGATES"
    assert audit["endpoint_audit"]["structurally_60m_eligible_count"] == "UNAVAILABLE_IN_FROZEN_AGGREGATES"
    assert audit["endpoint_audit"]["endpoint_complete_count"]["source_value"] == 156
    assert audit["endpoint_audit"]["required_endpoint_coverage"]["source_value"] is False
    assert audit["endpoint_audit"]["audit_completeness_status"] == "AUDIT_PARTIALLY_COMPLETE"
    assert audit["refinement_audit"]["zero_lag_counts"] == "UNAVAILABLE_IN_FROZEN_AGGREGATES"
    assert audit["refinement_audit"]["distinct_source_counts"] == "UNAVAILABLE_IN_FROZEN_AGGREGATES"
    assert audit["refinement_audit"]["independent_empirical_verification"] is False
    assert audit["refinement_audit"]["zero_minute_lag_structurally_possible"]["source_value"] is True
    assert audit["refinement_audit"]["zero_paired_difference_structurally_possible"]["source_value"] is True
    timestamp_invariant = audit["refinement_audit"]["invariant_statements"][0]
    assert timestamp_invariant["displacement_source_timestamp"] == "displacement_confirmation_timestamp"
    assert timestamp_invariant["refinement_source_timestamp"] == "refinement_creation_timestamp"
    for name in sorted(review.E4_FILES - {"report.md"}):
        _assert_qualified_tree(
            json.loads((source / name).read_text(encoding="utf-8")),
            audit["frozen_aggregate_evidence"][name],
        )
    assert {path.name: path.read_bytes() for path in source.iterdir()} == source_bytes


def test_endpoint_audit_classification_is_deterministic() -> None:
    unavailable = {
        field: review.UNAVAILABLE for field in review.ENDPOINT_REQUIRED_FIELDS
    }
    complete = {
        field: index
        for index, field in enumerate(sorted(review.ENDPOINT_REQUIRED_FIELDS))
    }
    partial = dict(unavailable)
    partial["endpoint_complete_count"] = 156

    assert review.classify_endpoint_audit(unavailable) == "AUDIT_INCOMPLETE"
    assert review.classify_endpoint_audit(complete) == "AUDIT_COMPLETE"
    assert review.classify_endpoint_audit(partial) == "AUDIT_PARTIALLY_COMPLETE"
    with pytest.raises(review.ReviewError, match="exact eight evidence fields"):
        review.classify_endpoint_audit({"endpoint_complete_count": 156})


def test_fingerprint_checksum_status_and_namespace_fail_closed(tmp_path: Path) -> None:
    source = _write_e4_fixture(tmp_path)
    summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    summary["adequacy_status"] = "INDEPENDENT_SAMPLE_ADEQUATE"
    (source / "summary.json").write_text(_dump(summary), encoding="utf-8")
    with pytest.raises(review.ReviewError, match="checksum mismatch"):
        review.build_audit_report(source)

    source = _write_e4_fixture(tmp_path / "second")
    (source / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(review.ReviewError, match="unexpected file"):
        review.build_audit_report(source)

    source = _write_e4_fixture(tmp_path / "third")
    manifest = json.loads((source / "artifact_manifest.json").read_text(encoding="utf-8"))
    manifest["scientific_result_fingerprint"] = "altered"
    (source / "artifact_manifest.json").write_text(_dump(manifest), encoding="utf-8")
    with pytest.raises(review.ReviewError, match="fingerprint mismatch"):
        review.build_audit_report(source)

    source = _write_e4_fixture(tmp_path / "nonfinite")
    (source / "statistical_validation.json").write_text(
        '{"invalid":NaN}\n', encoding="utf-8"
    )
    with pytest.raises(review.ReviewError, match="non-finite JSON value"):
        review.build_audit_report(source)

    first_source = _write_e4_fixture(tmp_path / "fourth")
    second_source = _write_e4_fixture(tmp_path / "fifth")
    first_audit = review.build_audit_report(first_source)
    second_audit = review.build_audit_report(second_source)
    assert review._stable_json(first_audit) == review._stable_json(second_audit)


def test_symlink_overlap_atomicity_collision_and_determinism(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _write_e4_fixture(tmp_path)
    output = tmp_path / review.E5_OUTPUT_RELATIVE
    first = review.publish_e5_review(tmp_path)
    assert first["published"] and review.verify_e5_review(output)["valid"]
    assert first["package_fingerprint"] == json.loads(
        (output / "artifact_manifest.json").read_text(encoding="utf-8")
    )["deterministic_package_fingerprint"]
    original = {path.name: path.read_bytes() for path in output.iterdir()}
    second = review.publish_e5_review(tmp_path)
    assert second["reused_existing"]
    assert {path.name: path.read_bytes() for path in output.iterdir()} == original
    assert review.publish_e5_review(tmp_path, verify_only=True)["reused_existing"]
    report_lines = (output / "report.md").read_text(encoding="utf-8").splitlines()
    assert len(report_lines) >= 9
    assert report_lines[:6] == [
        "1. This is a post-outcome reporting hardening artifact.",
        "2. The original execution was not modified.",
        "3. Outcomes were already known before E5.",
        "4. E5 is not an independent replication.",
        "5. Scientific values are copied exactly from frozen aggregate artifacts.",
        "6. No scientific conclusion may be upgraded by this report.",
    ]
    assert report_lines[6] == "No numerical result constitutes replication evidence."
    assert report_lines[8] == "# NOT_EVALUATED"
    report = "\n".join(report_lines)
    assert "Integrity: INTEGRITY_VERIFIED" in report
    assert (
        "Adequacy: INDEPENDENT_SAMPLE_INADEQUATE "
        "[TERMINATE SCIENTIFIC EVALUATION]" in report
    )
    assert "Primary Evaluation: NOT_EVALUATED" in report
    assert "Endpoint-complete count: `156` — DESCRIPTIVE AND NON-DECISIONAL" in report
    assert (
        "Structural-eligibility clause: `UNAVAILABLE_IN_FROZEN_AGGREGATES`"
        in report
    )
    assert (
        "Expected-ID versus observed-ID equality clause: "
        "`UNAVAILABLE_IN_FROZEN_AGGREGATES`" in report
    )
    prohibited_claims = (
        "replication succeeded",
        "replication successful",
        "hypothesis confirmed",
        "results support",
        "evidence validates",
    )
    assert not any(claim in report.lower() for claim in prohibited_claims)

    (output / "report.md").write_text("collision\n", encoding="utf-8")
    resigned = review._checksum_manifest(output, first["fingerprint"])
    (output / "artifact_manifest.json").write_text(
        review._stable_json(resigned, indent=2) + "\n", encoding="utf-8"
    )
    assert review.verify_e5_review(output)["valid"]
    with pytest.raises(review.ArtifactCollisionError, match="refusing to overwrite"):
        review.publish_e5_review(tmp_path)
    with pytest.raises(review.ReviewError, match="verify-only E5 package failed"):
        review.publish_e5_review(tmp_path, verify_only=True)

    with pytest.raises(review.ReviewError, match="must not overlap"):
        review._validate_source_and_output(source, source)
    linked_root = tmp_path / "linked-root"
    linked_source = linked_root / review.E4_OUTPUT_RELATIVE
    linked_source.parent.mkdir(parents=True)
    linked_source.symlink_to(source, target_is_directory=True)
    with pytest.raises(review.ReviewError, match="symlink"):
        review.publish_e5_review(linked_root)

    second_root = tmp_path / "path-independent-root"
    _write_e4_fixture(second_root)
    path_independent = review.publish_e5_review(second_root)
    second_output = second_root / review.E5_OUTPUT_RELATIVE
    assert path_independent["fingerprint"] == first["fingerprint"]
    assert path_independent["package_fingerprint"] == first["package_fingerprint"]
    assert {
        path.name: path.read_bytes() for path in second_output.iterdir()
    } == original

    failed_root = tmp_path / "failed-root"
    _write_e4_fixture(failed_root)
    failed_output = failed_root / review.E5_OUTPUT_RELATIVE
    monkeypatch.setattr(review.os, "rename", lambda _source, _target: (_ for _ in ()).throw(OSError("rename failed")))
    with pytest.raises(OSError, match="rename failed"):
        review.publish_e5_review(failed_root)
    assert not failed_output.exists()
    assert not list(failed_output.parent.glob(f".{failed_output.name}.staging-*"))


def test_static_boundary_has_no_outcome_import_or_event_data_access() -> None:
    source = Path(review.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    plain_imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(module.startswith("research.d005_e4_2026_independent_replication") for module in imports)
    assert not any(
        module.startswith("research.d005_e4_2026_independent_replication")
        for module in plain_imports
    )
    assert "read_parquet" not in source
    assert "to_parquet" not in source
    assert "pandas" not in source
    assert "execute_frozen_replication" not in source
    assert "calculate_forward_outcomes" not in source


def test_runtime_opens_only_exact_aggregate_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write_e4_fixture(tmp_path)
    opened: list[Path] = []
    original_open = Path.open

    def recording_open(path: Path, *args: object, **kwargs: object):
        opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", recording_open)
    review.build_audit_report(source)

    assert opened
    assert {path.name for path in opened} <= review.E4_FILES
    assert all(path.parent == source for path in opened)
    assert not any(path.suffix.lower() == ".parquet" for path in opened)
    assert not any("event" in path.name.lower() for path in opened)
