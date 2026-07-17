from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from aurumflow_research.config import deep_merge, load_config, parse_parameter_overrides
from aurumflow_research.data import (
    CSVMarketDataSource,
    DataCatalog,
    MarketDataRequest,
    RecordingDataAccess,
)
from aurumflow_research.discovery import ExperimentCatalog, ResearchObjectCatalog
from aurumflow_research.models import (
    ExperimentDefinition,
    ExperimentResult,
    ResearchDecision,
)
from aurumflow_research.reporting import FRAMEWORK_ARTIFACTS
from aurumflow_research.runner import ExperimentRunFailed, ExperimentRunner


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _definition() -> ExperimentDefinition:
    return ExperimentDefinition.from_mapping(
        {
            "id": "framework_contract_v1",
            "research_object": "TEST_OBJECT",
            "title": "Framework contract",
            "version": "0.1.0",
            "entry_point": f"{__name__}:_extension_entry_point",
            "output_namespace": "framework_contract",
            "hypothesis": "Does the infrastructure preserve one isolated run?",
            "measurable_definition": "All mandatory artifacts exist and agree on status.",
            "required_data": [],
            "success_criteria": ["All framework artifacts are emitted"],
            "failure_criteria": ["Any mandatory artifact is absent"],
            "validation_method": "Exercise the runner with an infrastructure-only callable.",
            "known_limitations": ["This test does not evaluate market behavior"],
            "parameters": {"nested": {"manifest": 1}},
        },
        REPOSITORY_ROOT / "tests" / "synthetic-experiment.toml",
    )


def _test_config(tmp_path: Path):
    base = load_config(REPOSITORY_ROOT / "config" / "research.toml")
    return replace(
        base,
        paths=replace(base.paths, outputs=tmp_path / "outputs"),
        logging=replace(base.logging, console=False),
        experiment_defaults={"nested": {"central": 1}},
    )


def _extension_entry_point(context) -> ExperimentResult:
    context.logger.info("contract_checked", "Synthetic framework contract checked")
    return ExperimentResult(
        summary="The infrastructure-only callable completed.",
        research_status=ResearchDecision.INCONCLUSIVE,
        status_rationale="No market hypothesis was evaluated.",
        sample_size=0,
        bootstrap_confidence_intervals={},
        robustness_checks=[],
        sensitivity_analysis=[],
        data_exclusions=[],
        limitations=["Infrastructure tests cannot establish market validity"],
        metrics={"resolved_override": context.parameters["nested"]["override"]},
        findings=["The run contract was exercised"],
    )


def test_central_configuration_and_parameter_precedence(tmp_path: Path) -> None:
    config = load_config(REPOSITORY_ROOT / "config" / "research.toml")

    assert config.project.root == REPOSITORY_ROOT
    assert config.paths.research_objects == REPOSITORY_ROOT / "research"
    assert config.paths.outputs == REPOSITORY_ROOT / "research_outputs"
    assert "local_csv" in config.data_sources

    overrides = parse_parameter_overrides(
        ["nested.value=3", 'label="controlled"', "enabled=true"]
    )
    merged = deep_merge(
        {"nested": {"central": 1, "value": 1}},
        {"nested": {"manifest": 2, "value": 2}},
        overrides,
    )
    assert merged == {
        "nested": {"central": 1, "manifest": 2, "value": 3},
        "label": "controlled",
        "enabled": True,
    }


def test_catalog_discovers_research_objects_and_registered_experiments() -> None:
    objects = ResearchObjectCatalog.discover(REPOSITORY_ROOT / "research")
    experiments = ExperimentCatalog.discover(REPOSITORY_ROOT / "research", objects)

    assert {item.object_id for item in objects} == {
        "HTF_BIAS",
        "LIQUIDITY",
        "DELIVERY_ARRAYS",
        "SESSION_STRUCTURE",
        "ENGINEERED_LIQUIDITY",
        "SMT",
        "OTE",
        "ENTRY_VALIDATION",
    }
    assert {item.experiment_id for item in experiments} == {"HTF_BIAS_PHASE1"}
    assert all(item.decision is ResearchDecision.NOT_EVALUATED for item in objects)


def test_new_object_and_experiment_are_discovered_without_core_edits(
    tmp_path: Path,
) -> None:
    object_root = tmp_path / "research" / "NEW_OBJECT"
    experiment_root = object_root / "experiments" / "question_v1"
    experiment_root.mkdir(parents=True)
    (object_root / "object.toml").write_text(
        """
[object]
id = "NEW_OBJECT"
title = "New Object"
version = "0.1.0"
catalog_reference = "test catalog"
layer = 2
lifecycle = "candidate_definition"
decision = "not_evaluated"
objective = "Evaluate a new neutral question."
""".strip(),
        encoding="utf-8",
    )
    (experiment_root / "experiment.toml").write_text(
        f"""
[experiment]
id = "new_question_v1"
research_object = "NEW_OBJECT"
title = "New question"
version = "0.1.0"
entry_point = "{__name__}:_extension_entry_point"
output_namespace = "new_question_v1"
hypothesis = "Does X improve Y?"
measurable_definition = "Measure X and Y using preregistered rules."
required_data = []
success_criteria = ["Threshold is met"]
failure_criteria = ["Threshold is not met"]
validation_method = "Run an isolated test."
known_limitations = ["Synthetic extension test"]

[parameters]
window = 10
""".strip(),
        encoding="utf-8",
    )

    objects = ResearchObjectCatalog.discover(tmp_path / "research")
    experiments = ExperimentCatalog.discover(tmp_path / "research", objects)
    definition = experiments.get("new_question_v1")

    assert objects.get("NEW_OBJECT").title == "New Object"
    assert definition.default_parameters == {"window": 10}
    assert experiments.load_entry_point(definition) is _extension_entry_point


def test_csv_data_source_records_content_provenance(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    csv_path = data_root / "sample.csv"
    csv_bytes = (
        b"timestamp,open,high,low,close\n"
        b"2026-01-01T00:00:00Z,1,2,0,1\n"
        b"2026-01-01T00:01:00Z,2,3,1,2\n"
    )
    csv_path.write_bytes(csv_bytes)
    catalog = DataCatalog()
    catalog.register(
        "fixture",
        CSVMarketDataSource(
            name="fixture", root=data_root, timestamp_column="timestamp"
        ),
    )
    access = RecordingDataAccess(catalog)

    loaded = access.load(
        "fixture",
        MarketDataRequest(
            dataset="sample.csv",
            symbol="XAUUSD",
            timeframe="1m",
            start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        ),
    )

    assert isinstance(loaded.frame, pd.DataFrame)
    assert len(loaded.frame) == 1
    assert loaded.provenance.fingerprint == hashlib.sha256(csv_bytes).hexdigest()
    assert loaded.provenance.request["symbol"] == "XAUUSD"
    assert access.inputs[0]["row_count"] == 1


def test_runner_writes_complete_report_bundle(tmp_path: Path) -> None:
    runner = ExperimentRunner(_test_config(tmp_path), DataCatalog())

    outcome = runner.run(
        _definition(),
        _extension_entry_point,
        {"nested": {"override": 7}},
    )

    assert outcome.result.research_status is ResearchDecision.INCONCLUSIVE
    assert all((outcome.output_dir / name).is_file() for name in FRAMEWORK_ARTIFACTS)
    summary = json.loads((outcome.output_dir / "summary.json").read_text())
    execution = json.loads(
        (outcome.output_dir / "execution_metadata.json").read_text()
    )
    status = json.loads((outcome.output_dir / "research_status.json").read_text())
    log_lines = (outcome.output_dir / "run.log.jsonl").read_text().splitlines()

    assert summary["run"]["execution_status"] == "completed"
    assert summary["result"]["metrics"]["resolved_override"] == 7
    assert summary["resolved_configuration"]["experiment_parameters"] == {
        "nested": {"central": 1, "manifest": 1, "override": 7}
    }
    assert execution["configuration_hash"] == summary["run"]["configuration_hash"]
    assert execution["random_seed"] == 1729
    assert status["status"] == "inconclusive"
    assert any(json.loads(line)["event"] == "experiment_completed" for line in log_lines)
    assert "No market dataset was loaded" in (outcome.output_dir / "report.md").read_text()


def test_runner_preserves_failure_artifacts_without_a_research_conclusion(
    tmp_path: Path,
) -> None:
    def failing_entry_point(context):
        raise RuntimeError("controlled failure")

    runner = ExperimentRunner(_test_config(tmp_path), DataCatalog())

    with pytest.raises(ExperimentRunFailed) as raised:
        runner.run(_definition(), failing_entry_point, {"nested": {"override": 1}})

    output_dir = raised.value.output_dir
    assert all((output_dir / name).is_file() for name in FRAMEWORK_ARTIFACTS)
    summary = json.loads((output_dir / "summary.json").read_text())
    status = json.loads((output_dir / "research_status.json").read_text())
    assert summary["run"]["execution_status"] == "failed"
    assert "result" not in summary
    assert status["status"] == "failed"
    assert "no research conclusion" in status["rationale"].lower()


def test_accepted_or_rejected_results_require_statistical_evidence() -> None:
    with pytest.raises(ValueError, match="require evidence fields"):
        ExperimentResult(
            summary="Unsupported conclusion",
            research_status=ResearchDecision.ACCEPTED,
            status_rationale="Missing evidence",
            sample_size=0,
            bootstrap_confidence_intervals={},
            robustness_checks=[],
            sensitivity_analysis=[],
            data_exclusions=[],
            limitations=[],
        )
